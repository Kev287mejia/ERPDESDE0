import hashlib
import json
from decimal import Decimal
from django.contrib import messages
from django.db import models
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel, SaasSubscriptionInvoice
from apps.tenancy.permissions import PlatformSuperuserRequiredMixin, RoleLevelRequiredMixin, render_403_rbac

EXCHANGE_RATE_BCN = Decimal('36.6243')


class EternalLabsSaasHqView(PlatformSuperuserRequiredMixin, View):
    """
    Consola Maestra de Gobierno SaaS — Eternal Labs HQ.
    Acceso restringido exclusivamente a la Dirección General de Eternal Labs (Superadministrador de Plataforma).
    Provee control global multi-tenant de planes, cuotas de usuarios, conmutación de estado
    (Active/Suspended) y cálculo en tiempo real de MRR / ARR bimonetario ($ USD / C$ NIO).
    """
    template_name = 'tenancy/saas_hq.html'

    def get(self, request, *args, **kwargs):
        org = request.organization

        # 1. Métricas Globales de Eternal Labs SaaS (MRR Activo)
        active_tenants_qs = Organization.objects.filter(
            subscription_status__in=[
                Organization.SubscriptionStatus.ACTIVE,
                Organization.SubscriptionStatus.TRIAL,
            ]
        )
        mrr_agg = active_tenants_qs.aggregate(total_mrr=models.Sum('monthly_fee_usd'))
        mrr_usd = mrr_agg['total_mrr'] or Decimal('0.00')
        mrr_nio = (mrr_usd * EXCHANGE_RATE_BCN).quantize(Decimal('0.01'))

        total_arr_usd = (mrr_usd * 12).quantize(Decimal('0.01'))
        total_arr_nio = (mrr_nio * 12).quantize(Decimal('0.01'))

        total_tenants = Organization.objects.count()
        total_platform_users = OrganizationMembership.objects.filter(is_active=True).count()

        active_tenants_count = Organization.objects.filter(subscription_status=Organization.SubscriptionStatus.ACTIVE).count()
        trial_tenants_count = Organization.objects.filter(subscription_status=Organization.SubscriptionStatus.TRIAL).count()
        suspended_tenants_count = Organization.objects.filter(subscription_status=Organization.SubscriptionStatus.SUSPENDED).count()

        # 2. Tabla Maestra de Tenants con métricas de cuota y facturación
        tenants_list = []
        for t in Organization.objects.select_related('country').order_by('name'):
            active_cnt = t.memberships.filter(is_active=True).count()
            quota = t.max_users_quota or t.max_users or 50
            inv_cnt = t.invoices.count() if hasattr(t, 'invoices') else 0
            tenants_list.append({
                'org': t,
                'active_users': active_cnt,
                'max_users_quota': quota,
                'quota_pct': min(100.0, round((active_cnt / quota * 100), 1)) if quota > 0 else 100.0,
                'invoices_count': inv_cnt,
            })

        # 3. Distribución por Plan SaaS
        plans_distribution = []
        for code, label in Organization.SubscriptionPlan.choices:
            qs = Organization.objects.filter(subscription_plan=code)
            count = qs.count()
            fee_sum = qs.aggregate(total=models.Sum('monthly_fee_usd'))['total'] or Decimal('0.00')
            plans_distribution.append({
                'code': code,
                'label': label,
                'count': count,
                'total_usd': fee_sum,
                'total_nio': (fee_sum * EXCHANGE_RATE_BCN).quantize(Decimal('0.01')),
            })

        # 4. Distribución por Vertical de Industria
        verticals_distribution = []
        for code, label in Organization.BusinessVertical.choices:
            count = Organization.objects.filter(business_vertical=code).count()
            verticals_distribution.append({
                'code': code,
                'label': label,
                'count': count,
            })

        # 5. Métricas del Tenant Activo en sesión
        if org:
            active_members = org.active_members_count() if callable(org.active_members_count) else int(org.active_members_count)
            max_users = org.max_users_quota or org.max_users or 50
            quota_pct = round((active_members / max_users * 100), 1) if max_users > 0 else 100.0
            can_add, seat_reason = org.can_add_more_users()
            invoices = SaasSubscriptionInvoice.objects.filter(organization=org).order_by('-issued_at', '-created_at')
        else:
            active_members = 0
            max_users = 50
            quota_pct = 0.0
            can_add = True
            seat_reason = ""
            invoices = SaasSubscriptionInvoice.objects.none()

        context = {
            'organization': org,
            'current_org': org,
            # Métricas requeridas Tarea 2
            'total_tenants': total_tenants,
            'mrr_usd': mrr_usd,
            'mrr_nio': mrr_nio,
            'total_platform_users': total_platform_users,
            'tenants': tenants_list,
            # Métricas retrocompatibles para pruebas preexistentes
            'total_mrr_usd': mrr_usd,
            'total_mrr_nio': mrr_nio,
            'total_arr_usd': total_arr_usd,
            'total_arr_nio': total_arr_nio,
            'exchange_rate': EXCHANGE_RATE_BCN,
            'total_tenants_count': total_tenants,
            'active_tenants_count': active_tenants_count,
            'trial_tenants_count': trial_tenants_count,
            'suspended_tenants_count': suspended_tenants_count,
            'plans_distribution': plans_distribution,
            'verticals_distribution': verticals_distribution,
            'active_members': active_members,
            'max_users': max_users,
            'quota_pct': min(100.0, quota_pct),
            'can_add_users': can_add,
            'seat_reason': seat_reason,
            'invoices': invoices,
            'subscription_plans': Organization.SubscriptionPlan.choices,
            'subscription_statuses': Organization.SubscriptionStatus.choices,
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        org_id = request.POST.get('org_id')
        target_org = get_object_or_404(Organization, pk=org_id) if org_id else request.organization

        new_plan = request.POST.get('subscription_plan', '').strip().upper()
        new_status = request.POST.get('subscription_status', '').strip().upper()
        new_quota = request.POST.get('max_users_quota', '').strip()
        new_fee = request.POST.get('monthly_fee_usd', '').strip()

        update_fields = []
        if new_plan and new_plan in [p[0] for p in Organization.SubscriptionPlan.choices]:
            target_org.subscription_plan = new_plan
            update_fields.append('subscription_plan')
            if new_plan == Organization.SubscriptionPlan.PYME_STARTER:
                target_org.monthly_fee_usd = Decimal('39.00')
                target_org.max_users_quota = 5
                target_org.max_users = 5
                update_fields.extend(['monthly_fee_usd', 'max_users_quota', 'max_users'])
            elif new_plan == Organization.SubscriptionPlan.BUSINESS_PRO:
                target_org.monthly_fee_usd = Decimal('89.00')
                target_org.max_users_quota = 15
                target_org.max_users = 15
                update_fields.extend(['monthly_fee_usd', 'max_users_quota', 'max_users'])
            elif new_plan == Organization.SubscriptionPlan.ENTERPRISE:
                target_org.monthly_fee_usd = Decimal('199.00')
                target_org.max_users_quota = 50
                target_org.max_users = 50
                update_fields.extend(['monthly_fee_usd', 'max_users_quota', 'max_users'])

        if new_status and new_status in [s[0] for s in Organization.SubscriptionStatus.choices]:
            target_org.subscription_status = new_status
            update_fields.append('subscription_status')

        if new_quota:
            try:
                quota_val = int(new_quota)
                if quota_val > 0:
                    target_org.max_users_quota = quota_val
                    target_org.max_users = quota_val
                    update_fields.extend(['max_users_quota', 'max_users'])
            except ValueError:
                pass

        if new_fee:
            try:
                target_org.monthly_fee_usd = Decimal(new_fee)
                update_fields.append('monthly_fee_usd')
            except Exception:
                pass

        if update_fields:
            update_fields.append('updated_at')
            target_org.save(update_fields=list(set(update_fields)))
            messages.success(request, f"Parámetros de suscripción actualizados exitosamente para {target_org.name}.")
        else:
            messages.info(request, "No se registraron cambios en los parámetros del tenant.")

        return redirect('tenancy:saas_hq')


# Alias para retrocompatibilidad
SaasHQDashboardView = EternalLabsSaasHqView


class TenantVaultBackupExportView(PlatformSuperuserRequiredMixin, View):
    """
    Exportador de Respaldo Criptográfico por Organización (Tenant Vault Backup).
    Genera un volcado JSON con metadatos fiscales, miembros, CRM, inventario y facturación,
    sellado con un hash SHA-256 de integridad inmutable.
    Exclusivo para Superadministrador de Plataforma.
    """
    def get(self, request, org_id=None, *args, **kwargs):
        if org_id:
            org = get_object_or_404(Organization, pk=org_id)
        else:
            org = request.organization

        from apps.crm.models import Account
        from apps.inventory.models import InventoryItem
        from apps.billing.models import Invoice
        from apps.finance.models import JournalEntry

        members_data = [
            {
                'email': m.user.email,
                'full_name': m.user.get_full_name() or m.user.email,
                'role_level': m.role_level,
                'role_label': m.get_role_level_display(),
                'job_title': m.job_title,
                'is_active': m.is_active,
            }
            for m in org.memberships.select_related('user').all()
        ]

        crm_accounts = [
            {
                'commercial_name': a.commercial_name,
                'legal_name': a.legal_name,
                'tax_id': a.tax_id,
                'account_type': a.account_type,
            }
            for a in Account.objects.filter(organization=org)
        ]

        inventory_items = [
            {
                'sku': it.sku,
                'name': it.name,
                'category': it.category,
                'unit': it.unit,
                'unit_cost': str(it.unit_cost),
            }
            for it in InventoryItem.objects.filter(organization=org)
        ]

        invoices_list = [
            {
                'number': inv.number,
                'issue_date': inv.issue_date.isoformat() if inv.issue_date else None,
                'total_amount': str(inv.total_amount),
                'status': inv.status,
                'currency': inv.currency,
            }
            for inv in Invoice.objects.filter(organization=org).order_by('-issue_date')[:50]
        ]

        journal_count = JournalEntry.objects.filter(organization=org).count() if hasattr(org, 'journal_entries') or True else 0

        export_payload = {
            'vault_version': '1.0.0-GA',
            'platform': 'ERP SAS · Eternal Labs',
            'exported_at': timezone.now().isoformat(),
            'exported_by': request.user.email,
            'organization': {
                'id': str(org.id),
                'slug': org.slug,
                'name': org.name,
                'legal_name': org.legal_name,
                'tax_id': org.tax_id,
                'country': org.country.code,
                'currency': org.currency,
                'business_vertical': org.business_vertical,
                'subscription_plan': org.subscription_plan,
                'subscription_status': org.subscription_status,
                'monthly_fee_usd': str(org.monthly_fee_usd),
                'max_users_quota': org.max_users_quota,
                'enabled_modules': org.enabled_modules,
                'created_at': org.created_at.isoformat(),
            },
            'members': members_data,
            'crm_accounts': crm_accounts,
            'inventory': inventory_items,
            'invoices_summary': {
                'total_count': Invoice.objects.filter(organization=org).count(),
                'recent_invoices': invoices_list,
            },
            'journal_entries_count': journal_count,
        }

        raw_deterministic = json.dumps(export_payload, sort_keys=True, default=str)
        integrity_seal = hashlib.sha256(raw_deterministic.encode('utf-8')).hexdigest()

        final_document = {
            'integrity_seal_sha256': integrity_seal,
            'payload': export_payload,
        }

        response = HttpResponse(
            json.dumps(final_document, indent=2, default=str),
            content_type='application/json'
        )
        timestamp_str = timezone.now().strftime('%Y%m%d_%H%M%S')
        response['Content-Disposition'] = f'attachment; filename="tenant_vault_backup_{org.slug}_{timestamp_str}.json"'
        return response


class SaasSwitchPlanView(PlatformSuperuserRequiredMixin, View):
    """
    Conmutador de Plan Comercial SaaS para la organización activa.
    Ajusta tarifa mensual ($ USD) y cuota de membresías máximas según política.
    Exclusivo para Superadministrador de Plataforma.
    """
    def post(self, request, *args, **kwargs):
        org = request.organization
        plan_code = request.POST.get('subscription_plan', '').strip().upper()

        valid_plans = [choice[0] for choice in Organization.SubscriptionPlan.choices]
        if plan_code not in valid_plans:
            messages.error(request, f"Plan SaaS inválido: '{plan_code}'.")
            return redirect('tenancy:saas_hq')

        org.apply_subscription_plan(plan_code)
        messages.success(
            request,
            f"Plan SaaS actualizado con éxito a {org.get_subscription_plan_display()}. "
            f"Cuota: {org.max_users_quota} asientos, Tarifa: ${org.monthly_fee_usd} USD/mes."
        )
        return redirect('tenancy:saas_hq')


class SaasUpdateStatusView(PlatformSuperuserRequiredMixin, View):
    """
    Gestión del Ciclo de Vida y Estado de Suscripción (Activa, Gracia, Suspendida).
    Exclusivo para Superadministrador de Plataforma.
    """
    def post(self, request, *args, **kwargs):
        org = request.organization
        new_status = request.POST.get('subscription_status', '').strip().upper()

        valid_statuses = [choice[0] for choice in Organization.SubscriptionStatus.choices]
        if new_status not in valid_statuses:
            messages.error(request, f"Estado de suscripción inválido: '{new_status}'.")
            return redirect('tenancy:saas_hq')

        org.subscription_status = new_status
        org.save(update_fields=['subscription_status'])

        if new_status == Organization.SubscriptionStatus.SUSPENDED:
            messages.warning(
                request,
                f"La organización {org.name} ha sido colocada en SUSPENSIÓN COMERCIAL. "
                "Las operaciones de escritura en módulos operativos quedan bloqueadas en modo Solo Lectura."
            )
        else:
            messages.success(
                request,
                f"Estado de suscripción actualizado a {org.get_subscription_status_display()}."
            )
        return redirect('tenancy:saas_hq')


class SaasGenerateInvoiceView(PlatformSuperuserRequiredMixin, View):
    """
    Emisión manual/inmediata de Comprobante Fiscal de Suscripción SaaS para el Tenant.
    Exclusivo para Superadministrador de Plataforma.
    """
    def post(self, request, *args, **kwargs):
        org = request.organization
        billing_period = request.POST.get('billing_period', '').strip() or timezone.now().strftime('%Y-%m')
        status = request.POST.get('status', SaasSubscriptionInvoice.Status.PAID).strip().upper()
        payment_reference = request.POST.get('payment_reference', '').strip() or 'STRIPE-NI-88412 / BAC-USD'

        if status not in SaasSubscriptionInvoice.Status.values:
            status = SaasSubscriptionInvoice.Status.PAID

        invoice = SaasSubscriptionInvoice.objects.create(
            organization=org,
            plan_snapshot=org.subscription_plan,
            billing_period=billing_period,
            amount_usd=org.monthly_fee_usd,
            exchange_rate=EXCHANGE_RATE_BCN,
            amount_nio=(org.monthly_fee_usd * EXCHANGE_RATE_BCN).quantize(Decimal('0.01')),
            status=status,
            payment_reference=payment_reference,
            issued_at=timezone.now().date(),
        )

        messages.success(
            request,
            f"Factura de suscripción {invoice.number} emitida exitosamente por "
            f"${invoice.amount_usd} USD (C$ {invoice.amount_nio} NIO)."
        )
        return redirect('tenancy:saas_hq')


# Alias retrocompatibles y de especificación de seguridad
SaasHqExportTenantVaultView = TenantVaultBackupExportView
SaasHqInspectTenantView = TenantVaultBackupExportView
SaasHqUpdatePlanView = SaasSwitchPlanView
SaasHqToggleSuspendView = SaasUpdateStatusView
