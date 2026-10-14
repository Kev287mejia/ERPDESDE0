from django.contrib import admin
from apps.billing.models import Invoice, InvoiceItem, PaymentReceipt


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0


class PaymentReceiptInline(admin.TabularInline):
    model = PaymentReceipt
    extra = 0
    readonly_fields = ('number', 'payment_date', 'currency_paid', 'amount_in_payment_currency', 'amount_applied_to_invoice')


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('number', 'account', 'status', 'issue_date', 'currency_code', 'gross_total', 'net_receivable', 'balance_due')
    list_filter = ('status', 'currency_code', 'payment_condition', 'issue_date')
    search_fields = ('number', 'account__commercial_name', 'account__tax_id')
    inlines = [InvoiceItemInline, PaymentReceiptInline]


@admin.register(PaymentReceipt)
class PaymentReceiptAdmin(admin.ModelAdmin):
    list_display = ('number', 'invoice', 'payment_date', 'payment_method', 'currency_paid', 'amount_in_payment_currency', 'amount_applied_to_invoice')
    list_filter = ('payment_method', 'currency_paid', 'payment_date')
    search_fields = ('number', 'invoice__number', 'reference_number')
