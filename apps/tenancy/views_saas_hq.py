from decimal import Decimal
from django.contrib import messages
from django.db import models
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from apps.tenancy.models import Organization, RoleLevel, SaasSubscriptionInvoice
from apps.tenancy.permissions import RoleLevelRequiredMixin

EXCHANGE_RATE_BCN = Decimal('36.6243')


class SaasHQDashboardView(RoleLevelRequiredMixin, View):
    """
    Consola Ejecutiva de Monetización y Gobierno SaaS HQ.
    Acceso restringido exclusivamente al Administrador General / SuperAdmin (RoleLevel.OWNER_ADMIN 100).
    Proporciona métricas globales MRR/ARR bimonetarias ($ USD / C$ NIO),
    monitoreo de cuotas de asientos, distribución de cartera y gestión de suscripción.
    """
    min_role_level = RoleLevel.OWNER_ADMIN
    template_name = 'tenancy/saas_hq.html'

    def get(self, request, *args, **kwargs):
        org = request.organization

        # 1. Métricas Globales de Monetización de la Plataforma SaaS
        mrr_agg = Organization.objects.filter(
            subscription_status__in=[
                Organization.SubscriptionStatus.ACTIVE,
                Organization.SubscriptionStatus.TRIAL,
            ]
        ).aggregate(total_mrr=models.Sum('monthly_fee_usd'))
        total_mrr_usd = mrr_agg['total_mrr'] or Decimal('0.00')
        total_mrr_nio = (total_mrr_usd * EXCHANGE_RATE_BCN).quantize(Decimal('0.01'))

        total_arr_usd = (total_mrr_usd * 12).quantize(Decimal('0.01'))
        total_arr_nio = (total_mrr_nio * 12).quantize(Decimal('0.01'))

        total_tenants_count = Organization.objects.count()
        active_tenants_count = Organization.objects.filter(subscription_status=Organization.SubscriptionStatus.ACTIVE).count()
        trial_tenants_count = Organization.objects.filter(subscription_status=Organization.SubscriptionStatus.TRIAL).count()
        suspended_tenants_count = Organization.objects.filter(subscription_status=Organization.SubscriptionStatus.SUSPENDED).count()

        # 2. Distribución por Plan SaaS
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

        # 3. Distribución por Giro de Negocio (BusinessVertical)
        verticals_distribution = []
        for code, label in Organization.BusinessVertical.choices:
            count = Organization.objects.filter(business_vertical=code).count()
            verticals_distribution.append({
                'code': code,
                'label': label,
                'count': count,
            })

        # 4. Asientos y Cuota de la Organización Activa
        active_members = org.active_members_count()
        max_users = org.max_users
        quota_pct = round((active_members / max_users * 100), 1) if max_users > 0 else 100.0
        can_add, seat_reason = org.can_add_more_users()

        # 5. Historial de Facturación SaaS del Tenant Activo
        invoices = SaasSubscriptionInvoice.objects.filter(organization=org).order_by('-issued_at', '-created_at')

        context = {
            'organization': org,
            'total_mrr_usd': total_mrr_usd,
            'total_mrr_nio': total_mrr_nio,
            'total_arr_usd': total_arr_usd,
            'total_arr_nio': total_arr_nio,
            'exchange_rate': EXCHANGE_RATE_BCN,
            'total_tenants_count': total_tenants_count,
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


class SaasSwitchPlanView(RoleLevelRequiredMixin, View):
    """
    Conmutador de Plan Comercial SaaS para la organización activa.
    Ajusta tarifa mensual ($ USD) y cuota de membresías máximas según política.
    """
    min_role_level = RoleLevel.OWNER_ADMIN

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
            f"Cuota: {org.max_users} asientos, Tarifa: ${org.monthly_fee_usd} USD/mes."
        )
        return redirect('tenancy:saas_hq')


class SaasUpdateStatusView(RoleLevelRequiredMixin, View):
    """
    Gestión del Ciclo de Vida y Estado de Suscripción (Activa, Gracia, Suspendida).
    """
    min_role_level = RoleLevel.OWNER_ADMIN

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


class SaasGenerateInvoiceView(RoleLevelRequiredMixin, View):
    """
    Emisión manual/inmediata de Comprobante Fiscal de Suscripción SaaS para el Tenant.
    """
    min_role_level = RoleLevel.OWNER_ADMIN

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
