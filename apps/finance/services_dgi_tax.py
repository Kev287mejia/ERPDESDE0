import csv
import io
from decimal import Decimal
from django.utils import timezone

from apps.billing.models import Invoice
from apps.purchasing.models import PurchaseOrder
from apps.payroll.models import PayrollPeriod


class NicaraguaDgiTaxService:
    """
    Motor Tributario para Nicaragua (Ley 822 de Concertación Tributaria y Alcaldía Municipal).
    Consolida obligaciones fiscales de IVA 15%, Retenciones en la Fuente (IR e IMI)
    y Retenciones de Nómina / Cargas Sociales para la VET (Ventanilla Electrónica Tributaria).
    """

    @classmethod
    def get_tax_summary(cls, organization, year=None, month=None):
        """
        Calcula la liquidación consolidada de impuestos para el período especificado:
        - IVA Débito (Ventas) vs. IVA Crédito (Compras).
        - Retenciones en la fuente a proveedores (IR 1%-2% e IMI 1%).
        - Retenciones laborales (IR Salarial Art. 23 Ley 822) y Seguridad Social (INSS/INATEC).
        """
        # 1. Filtro base de Facturas de Venta
        invoices_qs = Invoice.objects.filter(
            organization=organization,
            status__in=[
                Invoice.Status.ISSUED,
                Invoice.Status.PARTIAL,
                Invoice.Status.PAID,
            ],
        )
        if year:
            invoices_qs = invoices_qs.filter(issue_date__year=year)
        if month:
            invoices_qs = invoices_qs.filter(issue_date__month=month)

        invoices = list(invoices_qs.select_related('account').order_by('issue_date', 'number'))

        sales_taxable_subtotal = Decimal('0.00')
        sales_exempt_subtotal = Decimal('0.00')
        iva_debit_sales = Decimal('0.00')
        ir_retention_suffered = Decimal('0.00')
        imi_retention_suffered = Decimal('0.00')
        sales_gross_total = Decimal('0.00')

        for inv in invoices:
            sales_gross_total += inv.gross_total
            if inv.apply_tax and inv.tax_total > Decimal('0.00'):
                sales_taxable_subtotal += inv.subtotal
                iva_debit_sales += inv.tax_total
            else:
                sales_exempt_subtotal += inv.subtotal
            ir_retention_suffered += inv.ir_retention_amount
            imi_retention_suffered += inv.imi_retention_amount

        # 2. Filtro base de Órdenes de Compra a Proveedores
        purchases_qs = PurchaseOrder.objects.filter(
            organization=organization,
            status__in=[
                PurchaseOrder.Status.APPROVED,
                PurchaseOrder.Status.RECEIVED,
                PurchaseOrder.Status.PARTIAL_PAID,
                PurchaseOrder.Status.PAID,
            ],
        )
        if year:
            purchases_qs = purchases_qs.filter(issue_date__year=year)
        if month:
            purchases_qs = purchases_qs.filter(issue_date__month=month)

        purchases = list(purchases_qs.select_related('supplier').order_by('issue_date', 'number'))

        purchases_taxable_subtotal = Decimal('0.00')
        purchases_exempt_subtotal = Decimal('0.00')
        iva_credit_purchases = Decimal('0.00')
        ir_professional_and_goods = Decimal('0.00')
        imi_municipal_tax = Decimal('0.00')
        purchases_gross_total = Decimal('0.00')

        for po in purchases:
            purchases_gross_total += po.gross_total
            if po.apply_tax and po.tax_total > Decimal('0.00'):
                purchases_taxable_subtotal += po.subtotal
                iva_credit_purchases += po.tax_total
            else:
                purchases_exempt_subtotal += po.subtotal
            ir_professional_and_goods += po.ir_withheld_amount
            imi_municipal_tax += po.imi_withheld_amount

        # 3. Filtro base de Nóminas del Período
        payroll_qs = PayrollPeriod.objects.filter(
            organization=organization,
            status=PayrollPeriod.Status.CLOSED,
        )
        if year:
            payroll_qs = payroll_qs.filter(payment_date__year=year)
        if month:
            payroll_qs = payroll_qs.filter(payment_date__month=month)

        payrolls = list(payroll_qs.order_by('payment_date', 'number'))

        total_gross_payroll = Decimal('0.00')
        ir_salary_withholding = Decimal('0.00')
        inss_employee_total = Decimal('0.00')
        inss_employer_total = Decimal('0.00')
        inatec_total = Decimal('0.00')

        for p in payrolls:
            total_gross_payroll += p.total_gross_salary
            ir_salary_withholding += p.total_ir_tax
            inss_employee_total += p.total_inss_employee
            inss_employer_total += p.total_inss_employer
            inatec_total += p.total_inatec

        inss_inatec_payable = inss_employee_total + inss_employer_total + inatec_total

        # 4. Liquidación Neta de IVA
        if iva_debit_sales >= iva_credit_purchases:
            net_iva_payable = iva_debit_sales - iva_credit_purchases
            iva_credit_balance = Decimal('0.00')
        else:
            net_iva_payable = Decimal('0.00')
            iva_credit_balance = iva_credit_purchases - iva_debit_sales

        # 5. Totales Consolidados por Ente Recaudador
        total_dgi_payable = net_iva_payable + ir_professional_and_goods + ir_salary_withholding
        total_municipal_payable = imi_municipal_tax
        total_inss_inatec_due = inss_inatec_payable

        return {
            'year': year,
            'month': month,
            # Ventas e IVA Débito
            'invoices': invoices,
            'invoices_count': len(invoices),
            'sales_taxable_subtotal': sales_taxable_subtotal,
            'sales_exempt_subtotal': sales_exempt_subtotal,
            'sales_gross_total': sales_gross_total,
            'iva_debit_sales': iva_debit_sales,
            'ir_retention_suffered': ir_retention_suffered,
            'imi_retention_suffered': imi_retention_suffered,
            # Compras e IVA Crédito
            'purchases': purchases,
            'purchases_count': len(purchases),
            'purchases_taxable_subtotal': purchases_taxable_subtotal,
            'purchases_exempt_subtotal': purchases_exempt_subtotal,
            'purchases_gross_total': purchases_gross_total,
            'iva_credit_purchases': iva_credit_purchases,
            'ir_professional_and_goods': ir_professional_and_goods,
            'imi_municipal_tax': imi_municipal_tax,
            # Nómina y Retenciones Laborales
            'payrolls': payrolls,
            'payrolls_count': len(payrolls),
            'total_gross_payroll': total_gross_payroll,
            'ir_salary_withholding': ir_salary_withholding,
            'inss_employee_total': inss_employee_total,
            'inss_employer_total': inss_employer_total,
            'inatec_total': inatec_total,
            'inss_inatec_payable': inss_inatec_payable,
            # Liquidación IVA
            'net_iva_payable': net_iva_payable,
            'iva_credit_balance': iva_credit_balance,
            # Totales Institucionales
            'total_dgi_payable': total_dgi_payable,
            'total_municipal_payable': total_municipal_payable,
            'total_inss_inatec_due': total_inss_inatec_due,
        }

    @classmethod
    def generate_vet_csv_payload(cls, organization, year=None, month=None):
        """
        Genera el archivo CSV con la sábana de soporte y revisión técnica para la
        Ventanilla Electrónica Tributaria (VET) de la DGI y Alcaldía.
        Estructura tabular estricta:
        RUC_CONTRIBUYENTE,RAZON_SOCIAL,FECHA_DOCUMENTO,TIPO_OPERACION,
        FOLIO_FACTURA_O_NOMINA,SUBTOTAL_GRAVADO_NIO,IVA_15_NIO,RETENCION_IR_NIO,
        RETENCION_IMI_NIO,TOTAL_NETO_NIO
        """
        summary = cls.get_tax_summary(organization, year=year, month=month)
        tax_id = organization.tax_id or ''
        legal_name = organization.legal_name or organization.name

        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

        # Encabezados Técnicos
        writer.writerow([
            'RUC_CONTRIBUYENTE',
            'RAZON_SOCIAL',
            'FECHA_DOCUMENTO',
            'TIPO_OPERACION',
            'FOLIO_FACTURA_O_NOMINA',
            'SUBTOTAL_GRAVADO_NIO',
            'IVA_15_NIO',
            'RETENCION_IR_NIO',
            'RETENCION_IMI_NIO',
            'TOTAL_NETO_NIO',
        ])

        # 1. Facturas de Venta Emitidas
        for inv in summary['invoices']:
            writer.writerow([
                tax_id,
                legal_name,
                inv.issue_date.strftime('%Y-%m-%d') if inv.issue_date else '',
                'VENTA_FACTURADA',
                inv.number,
                f"{inv.subtotal:.2f}",
                f"{inv.tax_total:.2f}",
                f"{inv.ir_retention_amount:.2f}",
                f"{inv.imi_retention_amount:.2f}",
                f"{inv.gross_total:.2f}",
            ])

        # 2. Facturas de Compra / Órdenes Recibidas
        for po in summary['purchases']:
            writer.writerow([
                tax_id,
                legal_name,
                po.issue_date.strftime('%Y-%m-%d') if po.issue_date else '',
                'COMPRA_CREDITO_FISCAL',
                po.supplier_invoice_number or po.number,
                f"{po.subtotal:.2f}",
                f"{po.tax_total:.2f}",
                f"{po.ir_withheld_amount:.2f}",
                f"{po.imi_withheld_amount:.2f}",
                f"{po.net_payable:.2f}",
            ])

        # 3. Planillas de Nómina Cerradas
        for p in summary['payrolls']:
            pay_date = p.payment_date or p.end_date or timezone.now().date()
            writer.writerow([
                tax_id,
                legal_name,
                pay_date.strftime('%Y-%m-%d'),
                'RETENCION_SALARIAL_NOMINA',
                p.number,
                f"{p.total_gross_salary:.2f}",
                "0.00",
                f"{p.total_ir_tax:.2f}",
                "0.00",
                f"{p.total_net_salary:.2f}",
            ])

        return output.getvalue()
