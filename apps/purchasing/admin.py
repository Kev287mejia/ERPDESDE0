from django.contrib import admin
from apps.purchasing.models import Supplier, PurchaseOrder, PurchaseOrderItem, SupplierPayment


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0
    fields = ('inventory_item', 'description', 'unit', 'quantity', 'unit_cost', 'line_total')
    readonly_fields = ('line_total',)


class SupplierPaymentInline(admin.TabularInline):
    model = SupplierPayment
    extra = 0
    fields = ('number', 'payment_date', 'payment_method', 'currency_paid', 'amount_in_payment_currency', 'amount_applied_to_order')
    readonly_fields = ('number', 'payment_date', 'payment_method', 'currency_paid', 'amount_in_payment_currency', 'amount_applied_to_order')
    can_delete = False


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('code', 'commercial_name', 'tax_id', 'contact_name', 'phone', 'city', 'credit_days', 'is_active')
    search_fields = ('code', 'commercial_name', 'tax_id', 'contact_name')
    list_filter = ('is_active', 'city')


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('number', 'supplier', 'target_warehouse', 'status', 'issue_date', 'gross_total', 'net_payable', 'amount_paid', 'balance_due')
    search_fields = ('number', 'supplier__commercial_name', 'supplier_invoice_number', 'withholding_certificate_number')
    list_filter = ('status', 'target_warehouse', 'currency_code')
    inlines = [PurchaseOrderItemInline, SupplierPaymentInline]


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display = ('number', 'purchase_order', 'payment_date', 'payment_method', 'currency_paid', 'amount_in_payment_currency', 'amount_applied_to_order')
    search_fields = ('number', 'purchase_order__number', 'reference_number')
    list_filter = ('payment_method', 'currency_paid')
