from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.core.models import CountryConfig


class Command(BaseCommand):
    help = "Siembra y actualiza las configuraciones fiscales, monetarias y regionales para Centroamérica."

    COUNTRIES_DATA = [
        {
            "code": "NI",
            "name": "Nicaragua",
            "flag_emoji": "🇳🇮",
            "is_active": True,  # Operaciones iniciales activadas en Nicaragua
            "primary_currency_code": "NIO",
            "primary_currency_symbol": "C$",
            "secondary_currency_code": "USD",
            "secondary_currency_symbol": "$",
            "tax_id_label": "RUC",
            "tax_id_regex": r"^(?:[0-9]{14}|[Jj0-9][0-9]{13}|\d{3}-\d{6}-\d{4}[A-Za-z0-9])$",
            "personal_id_label": "Cédula de Identidad",
            "personal_id_regex": r"^\d{3}-\d{6}-\d{4}[A-Z]$",
            "default_tax_name": "IVA",
            "default_tax_rate": Decimal("15.00"),
            "timezone": "America/Managua",
        },
        {
            "code": "CR",
            "name": "Costa Rica",
            "flag_emoji": "🇨🇷",
            "is_active": False,
            "primary_currency_code": "CRC",
            "primary_currency_symbol": "₡",
            "secondary_currency_code": "USD",
            "secondary_currency_symbol": "$",
            "tax_id_label": "Cédula Jurídica / NIF",
            "tax_id_regex": r"^\d{10}$",
            "personal_id_label": "Cédula de Identidad",
            "personal_id_regex": r"^\d{9}$",
            "default_tax_name": "IVA",
            "default_tax_rate": Decimal("13.00"),
            "timezone": "America/Costa_Rica",
        },
        {
            "code": "HN",
            "name": "Honduras",
            "flag_emoji": "🇭🇳",
            "is_active": False,
            "primary_currency_code": "HNL",
            "primary_currency_symbol": "L",
            "secondary_currency_code": "USD",
            "secondary_currency_symbol": "$",
            "tax_id_label": "RTN",
            "tax_id_regex": r"^\d{14}$",
            "personal_id_label": "DNI / Identidad",
            "personal_id_regex": r"^(?:\d{13}|\d{4}-\d{4}-\d{5})$",
            "default_tax_name": "ISV",
            "default_tax_rate": Decimal("15.00"),
            "timezone": "America/Tegucigalpa",
        },
        {
            "code": "SV",
            "name": "El Salvador",
            "flag_emoji": "🇸🇻",
            "is_active": False,
            "primary_currency_code": "USD",
            "primary_currency_symbol": "$",
            "secondary_currency_code": "USD",
            "secondary_currency_symbol": "$",
            "tax_id_label": "NIT",
            "tax_id_regex": r"^(?:\d{14}|\d{9})$",
            "personal_id_label": "DUI",
            "personal_id_regex": r"^(?:\d{8}-\d{1}|\d{9})$",
            "default_tax_name": "IVA",
            "default_tax_rate": Decimal("13.00"),
            "timezone": "America/El_Salvador",
        },
        {
            "code": "GT",
            "name": "Guatemala",
            "flag_emoji": "🇬🇹",
            "is_active": False,
            "primary_currency_code": "GTQ",
            "primary_currency_symbol": "Q",
            "secondary_currency_code": "USD",
            "secondary_currency_symbol": "$",
            "tax_id_label": "NIT",
            "tax_id_regex": r"^[0-9]+-?[0-9kK]?$",
            "personal_id_label": "DPI / CUI",
            "personal_id_regex": r"^(?:\d{13}|\d{4}\s\d{5}\s\d{4})$",
            "default_tax_name": "IVA",
            "default_tax_rate": Decimal("12.00"),
            "timezone": "America/Guatemala",
        },
        {
            "code": "PA",
            "name": "Panamá",
            "flag_emoji": "🇵🇦",
            "is_active": False,
            "primary_currency_code": "PAB",
            "primary_currency_symbol": "B/.",
            "secondary_currency_code": "USD",
            "secondary_currency_symbol": "$",
            "tax_id_label": "RUC",
            "tax_id_regex": r"^[0-9A-Za-z\-]+$",
            "personal_id_label": "Cédula de Identidad Personal",
            "personal_id_regex": r"^(?:[0-9]{1,2}-[0-9]{1,4}-[0-9]{1,6}|\d{7,10})$",
            "default_tax_name": "ITBMS",
            "default_tax_rate": Decimal("7.00"),
            "timezone": "America/Panama",
        },
    ]

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Iniciando semillero de países de Centroamérica..."))

        created_count = 0
        updated_count = 0

        for country_info in self.COUNTRIES_DATA:
            code = country_info.pop("code")
            obj, created = CountryConfig.objects.update_or_create(
                code=code,
                defaults=country_info,
            )
            # Restaurar el código en el diccionario para idempotencia si se itera nuevamente
            country_info["code"] = code

            status_text = self.style.SUCCESS("CREADO") if created else self.style.WARNING("ACTUALIZADO")
            active_badge = "[OPERATIVO]" if obj.is_active else "[FUTURO]"

            self.stdout.write(
                f"  {obj.flag_emoji} {obj.name} ({obj.code}) {active_badge} "
                f"| Moneda: {obj.primary_currency_code} ({obj.primary_currency_symbol}) "
                f"| {obj.default_tax_name}: {obj.default_tax_rate}% "
                f"-> {status_text}"
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSemillero completado con éxito. {created_count} países creados, {updated_count} actualizados."
            )
        )
