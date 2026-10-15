import csv
from decimal import Decimal
from django.contrib import messages
from django.http import HttpResponse, Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from apps.billing.models import Invoice
from apps.purchasing.models import PurchaseOrder
from apps.finance.services import sync_commercial_and_purchasing_to_ledger
from apps.tenancy.models import RoleLevel
from apps.tenancy.permissions import ModuleAccessRequiredMixin


class VETDGITaxCenterView(ModuleAccessRequiredMixin, View):
    """
    Consola Fiscal DGI & Alcaldía de Managua (Ley 822 - Concertación Tributaria).
    Consolida:
    1. Anexo de Retenciones en la Fuente Practicadas (IR 1%-2% / IMI 1%).
    2. Libro de Compras e IVA Crédito Fiscal Acreditable (15%).
    3. Libro de Ventas, IVA Débito Fiscal y Exenciones Ley 822.
    4. Cuadro de Liquidación Mensual DGI (IVA Neto y Retenciones por Enterar).

    Accesible en lectura para Coordinador Operativo (80+).
    Acciones de exportación y sincronización contable para Gerente Comercial (85+).
    """
    required_module = 'billing'
    min_role_level = RoleLevel.OPERATIONS_COORD
    template_name = 'billing/vet_dgi.html'

    def get(self, request, *args, **kwargs):
        org = request.organization
        now = timezone.now()

        # Filtro de Año y Mes (por defecto año actual o filtro explícito)
        selected_year = request.GET.get('year', str(now.year)).strip()
        selected_month = request.GET.get('month', '').strip()

        # -------------------------------------------------------------
        # PANEL 1: RETENCIONES EN LA FUENTE PRACTICADAS (COMPRAS)
        # -------------------------------------------------------------
        retention_pos = (
            PurchaseOrder.objects.for_org(org)
            .filter(
                status__in=[
                    PurchaseOrder.Status.RECEIVED,
                    PurchaseOrder.Status.PARTIAL_PAID,
                    PurchaseOrder.Status.PAID,
                ]
            )
            .filter(
                models_Q := (
                    models_Q_def := __import__('django.db.models', fromlist=['Q']).Q
                )(ir_withheld_amount__gt=Decimal('0.00')) | models_Q_def(imi_withheld_amount__gt=Decimal('0.00'))
            )
            .select_related('supplier')
            .order_by('-issue_date')
        )

        if selected_year and selected_year.isdigit():
            retention_pos = retention_pos.filter(issue_date__year=int(selected_year))
        if selected_month and selected_month.isdigit() and 1 <= int(selected_month) <= 12:
            retention_pos = retention_pos.filter(issue_date__month=int(selected_month))

        retentions_list = list(retention_pos)
        tot_ret_base = sum(po.subtotal for po in retentions_list)
        tot_ret_ir = sum(po.ir_withheld_amount for po in retentions_list)
        tot_ret_imi = sum(po.imi_withheld_amount for po in retentions_list)
        tot_ret_practiced = tot_ret_ir + tot_ret_imi

        # -------------------------------------------------------------
        # PANEL 2: LIBRO DE COMPRAS E IVA CRÉDITO FISCAL (15%)
        # -------------------------------------------------------------
        purchases_qs = (
            PurchaseOrder.objects.for_org(org)
            .filter(
                status__in=[
                    PurchaseOrder.Status.RECEIVED,
                    PurchaseOrder.Status.PARTIAL_PAID,
                    PurchaseOrder.Status.PAID,
                ]
            )
            .select_related('supplier')
            .order_by('-issue_date')
        )

        if selected_year and selected_year.isdigit():
            purchases_qs = purchases_qs.filter(issue_date__year=int(selected_year))
        if selected_month and selected_month.isdigit() and 1 <= int(selected_month) <= 12:
            purchases_qs = purchases_qs.filter(issue_date__month=int(selected_month))

        purchases_list = list(purchases_qs)
        tot_purchases_taxable = sum(po.subtotal for po in purchases_list if po.tax_total > Decimal('0.00'))
        tot_purchases_exempt = sum(po.subtotal for po in purchases_list if po.tax_total == Decimal('0.00'))
        tot_purchases_iva = sum(po.tax_total for po in purchases_list)
        tot_purchases_gross = sum(po.gross_total for po in purchases_list)

        # -------------------------------------------------------------
        # PANEL 3: LIBRO DE VENTAS, IVA DÉBITO FISCAL Y EXENCIONES (LEY 822)
        # -------------------------------------------------------------
        sales_qs = (
            Invoice.objects.for_org(org)
            .filter(
                status__in=[
                    Invoice.Status.ISSUED,
                    Invoice.Status.PARTIAL,
                    Invoice.Status.PAID,
                ]
            )
            .select_related('account')
            .order_by('-issue_date')
        )

        if selected_year and selected_year.isdigit():
            sales_qs = sales_qs.filter(issue_date__year=int(selected_year))
        if selected_month and selected_month.isdigit() and 1 <= int(selected_month) <= 12:
            sales_qs = sales_qs.filter(issue_date__month=int(selected_month))

        sales_list = list(sales_qs)
        tot_sales_taxable = sum(inv.subtotal for inv in sales_list if inv.tax_total > Decimal('0.00'))
        tot_sales_exempt = sum(inv.subtotal for inv in sales_list if inv.tax_total == Decimal('0.00'))
        tot_sales_iva = sum(inv.tax_total for inv in sales_list)
        tot_sales_ir_withheld = sum(inv.ir_retention_amount for inv in sales_list)
        tot_sales_imi_withheld = sum(inv.imi_retention_amount for inv in sales_list)
        tot_sales_gross = sum(inv.gross_total for inv in sales_list)
        tot_sales_net = sum(inv.net_receivable for inv in sales_list)

        # -------------------------------------------------------------
        # CUADRO DE LIQUIDACIÓN MENSUAL DGI
        # -------------------------------------------------------------
        iva_neto_dgi = tot_sales_iva - tot_purchases_iva
        total_retenciones_a_enterar = tot_ret_ir + tot_ret_imi
        total_retenciones_sufridas = tot_sales_ir_withheld + tot_sales_imi_withheld

        can_export_and_sync = (getattr(request, 'role_level', 0) >= RoleLevel.COMMERCIAL_MGR)

        available_years = [now.year, now.year - 1, now.year - 2]
        months_choices = [
            ('1', '01 - Enero'), ('2', '02 - Febrero'), ('3', '03 - Marzo'),
            ('4', '04 - Abril'), ('5', '05 - Mayo'), ('6', '06 - Junio'),
            ('7', '07 - Julio'), ('8', '08 - Agosto'), ('9', '09 - Septiembre'),
            ('10', '10 - Octubre'), ('11', '11 - Noviembre'), ('12', '12 - Diciembre'),
        ]

        context = {
            'selected_year': selected_year,
            'selected_month': selected_month,
            'available_years': available_years,
            'months_choices': months_choices,
            # Panel 1 Retenciones
            'retentions_list': retentions_list,
            'tot_ret_base': tot_ret_base,
            'tot_ret_ir': tot_ret_ir,
            'tot_ret_imi': tot_ret_imi,
            'tot_ret_practiced': tot_ret_practiced,
            # Panel 2 Compras
            'purchases_list': purchases_list,
            'tot_purchases_taxable': tot_purchases_taxable,
            'tot_purchases_exempt': tot_purchases_exempt,
            'tot_purchases_iva': tot_purchases_iva,
            'tot_purchases_gross': tot_purchases_gross,
            # Panel 3 Ventas
            'sales_list': sales_list,
            'tot_sales_taxable': tot_sales_taxable,
            'tot_sales_exempt': tot_sales_exempt,
            'tot_sales_iva': tot_sales_iva,
            'tot_sales_ir_withheld': tot_sales_ir_withheld,
            'tot_sales_imi_withheld': tot_sales_imi_withheld,
            'tot_sales_gross': tot_sales_gross,
            'tot_sales_net': tot_sales_net,
            # Liquidación DGI
            'iva_neto_dgi': iva_neto_dgi,
            'is_iva_payable': iva_neto_dgi >= Decimal('0.00'),
            'iva_payable_amount': max(Decimal('0.00'), iva_neto_dgi),
            'iva_favor_amount': abs(min(Decimal('0.00'), iva_neto_dgi)),
            'total_retenciones_a_enterar': total_retenciones_a_enterar,
            'total_retenciones_sufridas': total_retenciones_sufridas,
            'can_export_and_sync': can_export_and_sync,
        }
        return render(request, self.template_name, context)


class VETDGIExportCSVView(ModuleAccessRequiredMixin, View):
    """
    Exportador Oficial CSV / TSV estructurado para la Ventanilla Electrónica Tributaria (VET - DGI).
    Requiere nivel mínimo COMMERCIAL_MGR (85+).
    """
    required_module = 'billing'
    min_role_level = RoleLevel.COMMERCIAL_MGR

    def get(self, request, report_type, *args, **kwargs):
        org = request.organization
        now = timezone.now()

        selected_year = request.GET.get('year', str(now.year)).strip()
        selected_month = request.GET.get('month', '').strip()

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        tax_id_clean = (org.tax_id or 'ND').replace('-', '').strip()
        response['Content-Disposition'] = f'attachment; filename="VET_DGI_{report_type}_{tax_id_clean}.csv"'

        # BOM para compatibilidad con Microsoft Excel
        response.write('\ufeff')
        writer = csv.writer(response)

        if report_type == 'retentions':
            writer.writerow([
                'RUC Proveedor',
                'Razon Social',
                'Factura Proveedor',
                'Fecha Emision',
                'Base Imponible C$',
                'Retencion IR C$',
                'Retencion IMI C$',
                'No Constancia RET',
            ])

            from django.db.models import Q
            qs = (
                PurchaseOrder.objects.for_org(org)
                .filter(
                    status__in=[
                        PurchaseOrder.Status.RECEIVED,
                        PurchaseOrder.Status.PARTIAL_PAID,
                        PurchaseOrder.Status.PAID,
                    ]
                )
                .filter(Q(ir_withheld_amount__gt=Decimal('0.00')) | Q(imi_withheld_amount__gt=Decimal('0.00')))
                .select_related('supplier')
                .order_by('-issue_date')
            )
            if selected_year and selected_year.isdigit():
                qs = qs.filter(issue_date__year=int(selected_year))
            if selected_month and selected_month.isdigit() and 1 <= int(selected_month) <= 12:
                qs = qs.filter(issue_date__month=int(selected_month))

            for po in qs:
                ruc = po.supplier.tax_id if po.supplier else ''
                name = po.supplier.commercial_name if po.supplier else ''
                fac = po.supplier_invoice_number or po.number
                date_str = po.issue_date.strftime('%Y-%m-%d') if po.issue_date else ''
                writer.writerow([
                    ruc,
                    name,
                    fac,
                    date_str,
                    f"{po.subtotal:.2f}",
                    f"{po.ir_withheld_amount:.2f}",
                    f"{po.imi_withheld_amount:.2f}",
                    po.withholding_certificate_number or 'PENDIENTE',
                ])

        elif report_type == 'purchases_iva':
            writer.writerow([
                'No Orden Compra',
                'RUC Proveedor',
                'Razon Social',
                'Factura Proveedor',
                'Fecha Emision',
                'Base Gravada 15% C$',
                'Base Exenta C$',
                'IVA Credito Fiscal 15% C$',
                'Total Facturado C$',
            ])

            qs = (
                PurchaseOrder.objects.for_org(org)
                .filter(
                    status__in=[
                        PurchaseOrder.Status.RECEIVED,
                        PurchaseOrder.Status.PARTIAL_PAID,
                        PurchaseOrder.Status.PAID,
                    ]
                )
                .select_related('supplier')
                .order_by('-issue_date')
            )
            if selected_year and selected_year.isdigit():
                qs = qs.filter(issue_date__year=int(selected_year))
            if selected_month and selected_month.isdigit() and 1 <= int(selected_month) <= 12:
                qs = qs.filter(issue_date__month=int(selected_month))

            for po in qs:
                ruc = po.supplier.tax_id if po.supplier else ''
                name = po.supplier.commercial_name if po.supplier else ''
                fac = po.supplier_invoice_number or po.number
                date_str = po.issue_date.strftime('%Y-%m-%d') if po.issue_date else ''
                gravada = po.subtotal if po.tax_total > Decimal('0.00') else Decimal('0.00')
                exenta = po.subtotal if po.tax_total == Decimal('0.00') else Decimal('0.00')

                writer.writerow([
                    po.number,
                    ruc,
                    name,
                    fac,
                    date_str,
                    f"{gravada:.2f}",
                    f"{exenta:.2f}",
                    f"{po.tax_total:.2f}",
                    f"{po.gross_total:.2f}",
                ])

        elif report_type == 'sales_dgi':
            writer.writerow([
                'No Factura',
                'Fecha Emision',
                'RUC Cliente',
                'Razon Social',
                'Ventas Gravadas 15% C$',
                'Ventas Exentas 0% C$',
                'IVA Debito Fiscal 15% C$',
                'Retencion IR Sufrida C$',
                'Retencion IMI Sufrida C$',
                'Total Facturado Bruto C$',
                'Neto Cobrado C$',
            ])

            qs = (
                Invoice.objects.for_org(org)
                .filter(
                    status__in=[
                        Invoice.Status.ISSUED,
                        Invoice.Status.PARTIAL,
                        Invoice.Status.PAID,
                    ]
                )
                .select_related('account')
                .order_by('-issue_date')
            )
            if selected_year and selected_year.isdigit():
                qs = qs.filter(issue_date__year=int(selected_year))
            if selected_month and selected_month.isdigit() and 1 <= int(selected_month) <= 12:
                qs = qs.filter(issue_date__month=int(selected_month))

            for inv in qs:
                ruc = inv.account.tax_id if inv.account else ''
                name = inv.account.commercial_name if inv.account else ''
                date_str = inv.issue_date.strftime('%Y-%m-%d') if inv.issue_date else ''
                gravada = inv.subtotal if inv.tax_total > Decimal('0.00') else Decimal('0.00')
                exenta = inv.subtotal if inv.tax_total == Decimal('0.00') else Decimal('0.00')

                writer.writerow([
                    inv.number,
                    date_str,
                    ruc,
                    name,
                    f"{gravada:.2f}",
                    f"{exenta:.2f}",
                    f"{inv.tax_total:.2f}",
                    f"{inv.ir_retention_amount:.2f}",
                    f"{inv.imi_retention_amount:.2f}",
                    f"{inv.gross_total:.2f}",
                    f"{inv.net_receivable:.2f}",
                ])
        else:
            raise Http404(f"Tipo de reporte '{report_type}' no soportado.")

        return response


class VETDGISyncLedgerView(ModuleAccessRequiredMixin, View):
    """
    Sincronización Automática con Libro Diario NIIF / DGI en apps/finance.
    Genera pólizas de partida doble cuadrada para todas las facturas y compras pendientes.
    Requiere nivel mínimo COMMERCIAL_MGR (85+).
    """
    required_module = 'billing'
    min_role_level = RoleLevel.COMMERCIAL_MGR

    def post(self, request, *args, **kwargs):
        org = request.organization
        try:
            stats = sync_commercial_and_purchasing_to_ledger(org, request.user)
            messages.success(
                request,
                f"Sincronización contable completada: {stats['invoices_synced']} facturas DGI y "
                f"{stats['purchases_synced']} compras contabilizadas en partida doble (Total: {stats['total_entries']} pólizas cuadradas)."
            )
        except Exception as e:
            messages.error(request, f"Error al sincronizar con contabilidad: {str(e)}")

        return redirect('billing:vet_dgi_center')
