from decimal import Decimal
from django.contrib import messages
from django.db import models, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.billing.models import Invoice, InvoiceItem, PaymentReceipt
from apps.crm.models import Quote
from apps.operations.models import WorkOrder, WorkOrderTimelineLog
from apps.tenancy.models import RoleLevel
from apps.tenancy.permissions import ModuleAccessRequiredMixin


class InvoiceListView(ModuleAccessRequiredMixin, View):
    """
    Directorio de Facturas Fiscales y Monitor de Cartera (CxC).
    Accesible en lectura para Coordinador Operativo (80+).
    """
    required_module = 'billing'
    min_role_level = RoleLevel.OPERATIONS_COORD
    template_name = 'billing/invoice_list.html'

    def get(self, request, *args, **kwargs):
        qs = (
            Invoice.objects.for_org(request.organization)
            .select_related('account', 'source_quote', 'source_work_order', 'created_by')
            .prefetch_related('payments')
        )

        status_filter = request.GET.get('status', '').strip()
        if status_filter:
            qs = qs.filter(status=status_filter)

        search_query = request.GET.get('q', '').strip()
        if search_query:
            qs = qs.filter(
                models.Q(number__icontains=search_query) |
                models.Q(account__commercial_name__icontains=search_query) |
                models.Q(account__tax_id__icontains=search_query) |
                models.Q(retention_certificate_number__icontains=search_query)
            )

        invoices = list(qs)

        # Cálculo de KPIs de Cartera en memoria
        active_invoices = [inv for inv in invoices if inv.status != Invoice.Status.VOID]
        kpi_gross_total = sum(inv.gross_total for inv in active_invoices)
        kpi_retentions = sum(inv.total_retentions for inv in active_invoices)
        kpi_net_receivable = sum(inv.net_receivable for inv in active_invoices)
        kpi_collected = sum(inv.amount_paid for inv in active_invoices)
        kpi_balance_due = sum(inv.balance_due for inv in active_invoices)

        return render(request, self.template_name, {
            'invoices': invoices,
            'status_filter': status_filter,
            'search_query': search_query,
            'status_choices': Invoice.Status.choices,
            'kpi_gross_total': kpi_gross_total,
            'kpi_retentions': kpi_retentions,
            'kpi_net_receivable': kpi_net_receivable,
            'kpi_collected': kpi_collected,
            'kpi_balance_due': kpi_balance_due,
            'can_manage_billing': request.role_level >= RoleLevel.COMMERCIAL_MGR,
        })


class InvoiceDetailView(ModuleAccessRequiredMixin, View):
    """
    Expediente Fiscal Detallado de Factura, Retenciones y Caja (ROC).
    Permite lectura a Nivel 80+ y gestión completa a Nivel 85+.
    """
    required_module = 'billing'
    min_role_level = RoleLevel.OPERATIONS_COORD
    template_name = 'billing/invoice_detail.html'

    def get(self, request, pk, *args, **kwargs):
        invoice = get_object_or_404(
            Invoice.objects.for_org(request.organization).select_related('account', 'source_quote', 'source_work_order', 'created_by'),
            pk=pk
        )
        items = list(invoice.items.all())
        payments = list(invoice.payments.all().select_related('received_by'))

        return render(request, self.template_name, {
            'invoice': invoice,
            'items': items,
            'payments': payments,
            'payment_methods': PaymentReceipt.PaymentMethod.choices,
            'can_manage_billing': request.role_level >= RoleLevel.COMMERCIAL_MGR,
        })


class ConvertQuoteToInvoiceView(ModuleAccessRequiredMixin, View):
    """
    Conversión 1-Clic: Convierte una Cotización Aprobada en Factura Fiscal (ISSUED).
    Exclusivo para Gerente Comercial (85+) y Owner (100).
    """
    required_module = 'billing'
    min_role_level = RoleLevel.COMMERCIAL_MGR

    def post(self, request, quote_pk, *args, **kwargs):
        quote = get_object_or_404(
            Quote.objects.for_org(request.organization),
            pk=quote_pk
        )

        with transaction.atomic():
            invoice = Invoice.objects.create(
                organization=request.organization,
                account=quote.account,
                source_quote=quote,
                status=Invoice.Status.ISSUED,
                currency_code=quote.currency_code,
                currency_symbol=quote.currency_symbol,
                exchange_rate=quote.exchange_rate,
                apply_tax=quote.apply_tax,
                tax_name=quote.tax_name,
                tax_rate=quote.tax_rate,
                created_by=request.user,
                notes=quote.notes,
            )

            for q_item in quote.items.all():
                InvoiceItem.objects.create(
                    organization=request.organization,
                    invoice=invoice,
                    item_type=q_item.item_type,
                    code=q_item.code,
                    description=q_item.description,
                    unit=q_item.unit,
                    quantity=q_item.quantity,
                    unit_price=q_item.unit_price,
                    discount_percent=q_item.discount_percent,
                )

            invoice.recalculate_totals()
            invoice.save()

            messages.success(
                request,
                f"Factura fiscal emitida exitosamente: {invoice.number} por {invoice.currency_symbol} {invoice.gross_total:,.2f}."
            )

        return redirect('billing:invoice_detail', pk=invoice.pk)


class ConvertWorkOrderToInvoiceView(ModuleAccessRequiredMixin, View):
    """
    Conversión 1-Clic: Factura una Orden de Trabajo con base en las partidas ejecutadas.
    Registra un evento inmutable en el historial operativo de la OT.
    Exclusivo para Gerente Comercial (85+) y Owner (100).
    """
    required_module = 'billing'
    min_role_level = RoleLevel.COMMERCIAL_MGR

    def post(self, request, wo_pk, *args, **kwargs):
        wo = get_object_or_404(
            WorkOrder.objects.for_org(request.organization),
            pk=wo_pk
        )

        with transaction.atomic():
            quote = wo.source_quote
            currency_code = quote.currency_code if quote else request.organization.currency
            currency_symbol = quote.currency_symbol if quote else request.organization.currency_symbol
            exchange_rate = quote.exchange_rate if quote else Decimal('36.6243')
            apply_tax = quote.apply_tax if quote else True
            tax_rate = quote.tax_rate if quote else Decimal('15.00')

            # Mapear precios unitarios y descuentos de la cotización
            quote_item_map = {}
            if quote:
                for qi in quote.items.all():
                    if qi.code:
                        quote_item_map[qi.code] = (qi.unit_price, qi.discount_percent)

            invoice = Invoice.objects.create(
                organization=request.organization,
                account=wo.account,
                source_quote=quote,
                source_work_order=wo,
                status=Invoice.Status.ISSUED,
                currency_code=currency_code,
                currency_symbol=currency_symbol,
                exchange_rate=exchange_rate,
                apply_tax=apply_tax,
                tax_rate=tax_rate,
                created_by=request.user,
                notes=f"Facturación derivada de la Orden de Trabajo {wo.number}.",
            )

            for w_item in wo.items.all():
                qty = w_item.executed_quantity if w_item.executed_quantity > Decimal('0.00') else w_item.planned_quantity
                price, disc = quote_item_map.get(w_item.code, (Decimal('0.00'), Decimal('0.00')))
                InvoiceItem.objects.create(
                    organization=request.organization,
                    invoice=invoice,
                    item_type=w_item.item_type,
                    code=w_item.code,
                    description=w_item.description,
                    unit=w_item.unit,
                    quantity=qty,
                    unit_price=price,
                    discount_percent=disc,
                )

            invoice.recalculate_totals()
            invoice.save()

            # Bitácora inmutable en la Orden de Trabajo
            WorkOrderTimelineLog.objects.create(
                organization=request.organization,
                work_order=wo,
                event_type='INVOICED',
                summary=f"Orden de Trabajo facturada bajo Folio {invoice.number}",
                details=f"Factura emitida por {invoice.currency_symbol} {invoice.gross_total:,.2f} con {invoice.items.count()} partidas.",
                actor=request.user,
            )

            messages.success(
                request,
                f"Orden de Trabajo {wo.number} facturada correctamente bajo Folio {invoice.number}."
            )

        return redirect('billing:invoice_detail', pk=invoice.pk)


class InvoiceApplyRetentionsView(ModuleAccessRequiredMixin, View):
    """
    Aplica o actualiza retenciones en la fuente (IR e IMI) sobre la base imponible gravable.
    Exclusivo para Gerente Comercial (85+) y Owner (100).
    """
    required_module = 'billing'
    min_role_level = RoleLevel.COMMERCIAL_MGR

    def post(self, request, pk, *args, **kwargs):
        invoice = get_object_or_404(
            Invoice.objects.for_org(request.organization),
            pk=pk
        )

        try:
            ir_rate = Decimal(request.POST.get('ir_retention_rate', '0.00'))
            imi_rate = Decimal(request.POST.get('imi_retention_rate', '0.00'))
            cert_num = request.POST.get('retention_certificate_number', '').strip()

            invoice.ir_retention_rate = ir_rate
            invoice.imi_retention_rate = imi_rate
            invoice.retention_certificate_number = cert_num
            invoice.recalculate_totals()
            invoice.save()

            messages.success(
                request,
                f"Retenciones actualizadas en {invoice.number}: IR {ir_rate}% ({invoice.currency_symbol} {invoice.ir_retention_amount:,.2f}) "
                f"+ IMI {imi_rate}% ({invoice.currency_symbol} {invoice.imi_retention_amount:,.2f}). "
                f"Neto a cobrar: {invoice.currency_symbol} {invoice.net_receivable:,.2f}."
            )
        except Exception as e:
            messages.error(request, f"Error al procesar retenciones: {str(e)}")

        return redirect('billing:invoice_detail', pk=invoice.pk)


class InvoiceRegisterPaymentView(ModuleAccessRequiredMixin, View):
    """
    Registra un Recibo Oficial de Caja (ROC) bimonetario para liquidar total o parcialmente una factura.
    Aplica conversión automática de moneda oficial BCN si se paga en divisa alterna.
    Exclusivo para Gerente Comercial (85+) y Owner (100).
    """
    required_module = 'billing'
    min_role_level = RoleLevel.COMMERCIAL_MGR

    def post(self, request, pk, *args, **kwargs):
        invoice = get_object_or_404(
            Invoice.objects.for_org(request.organization),
            pk=pk
        )

        try:
            amount_paid = Decimal(request.POST.get('amount', '0.00'))
            currency_paid = request.POST.get('currency_paid', invoice.currency_code).strip().upper()
            payment_method = request.POST.get('payment_method', PaymentReceipt.PaymentMethod.TRANSFER_BAC)
            reference_number = request.POST.get('reference_number', '').strip()
            notes = request.POST.get('notes', '').strip()

            if amount_paid <= Decimal('0.00'):
                messages.error(request, "El monto recaudado debe ser estrictamente mayor a 0.")
                return redirect('billing:invoice_detail', pk=invoice.pk)

            with transaction.atomic():
                receipt = PaymentReceipt.objects.create(
                    organization=request.organization,
                    invoice=invoice,
                    currency_paid=currency_paid,
                    amount_in_payment_currency=amount_paid,
                    exchange_rate_applied=invoice.exchange_rate,
                    payment_method=payment_method,
                    reference_number=reference_number,
                    received_by=request.user,
                    notes=notes,
                )

                messages.success(
                    request,
                    f"Recibo Oficial de Caja emitido: {receipt.number} por {currency_paid} {amount_paid:,.2f} "
                    f"(Acreditado a factura: {invoice.currency_symbol} {receipt.amount_applied_to_invoice:,.2f}). "
                    f"Saldo restante: {invoice.currency_symbol} {invoice.balance_due:,.2f} [{invoice.get_status_display()}]."
                )

        except Exception as e:
            messages.error(request, f"Error al registrar cobro: {str(e)}")

        return redirect('billing:invoice_detail', pk=invoice.pk)


class InvoiceVoidView(ModuleAccessRequiredMixin, View):
    """
    Anula una factura fiscal si no posee pagos acreditados.
    Exclusivo para Gerente Comercial (85+) y Owner (100).
    """
    required_module = 'billing'
    min_role_level = RoleLevel.COMMERCIAL_MGR

    def post(self, request, pk, *args, **kwargs):
        invoice = get_object_or_404(
            Invoice.objects.for_org(request.organization),
            pk=pk
        )

        if invoice.amount_paid > Decimal('0.00'):
            messages.error(request, "No se puede anular una factura con cobros o recibos de caja aplicados.")
            return redirect('billing:invoice_detail', pk=invoice.pk)

        invoice.status = Invoice.Status.VOID
        invoice.save(update_fields=['status', 'updated_at'])
        messages.warning(request, f"La factura {invoice.number} ha sido formalmente anulada.")

        return redirect('billing:invoice_detail', pk=invoice.pk)


class InvoicePrintView(ModuleAccessRequiredMixin, View):
    """
    Comprobante Fiscal Imprimible / Estado de Cuenta Oficial DGI.
    Formato Swiss Grid monocromático de alta legibilidad para entrega al cliente.
    """
    required_module = 'billing'
    min_role_level = RoleLevel.OPERATIONS_COORD
    template_name = 'billing/invoice_print.html'

    def get(self, request, pk, *args, **kwargs):
        invoice = get_object_or_404(
            Invoice.objects.for_org(request.organization).select_related('account', 'created_by'),
            pk=pk
        )
        return render(request, self.template_name, {
            'invoice': invoice,
            'items': invoice.items.all(),
            'payments': invoice.payments.all(),
        })
