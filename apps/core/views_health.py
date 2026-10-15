import time
from django.db import connection
from django.http import JsonResponse
from django.utils import timezone
from django.views import View

from apps.core.models import CountryConfig


class SystemHealthcheckView(View):
    """
    Endpoint de telemetría y salud de infraestructura para balanceadores de carga,
    orquestadores Cloud (Docker, Kubernetes, Render, Railway) y monitoreo de alta disponibilidad.
    Público, sin sesión ni autenticación requerida.
    """

    def get(self, request, *args, **kwargs):
        start_time = time.perf_counter()
        db_status = "connected"
        http_status = 200
        active_jurisdictions = 0

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            active_jurisdictions = CountryConfig.objects.filter(is_active=True).count()
        except Exception as e:
            db_status = f"disconnected: {str(e)}"
            http_status = 503

        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        data = {
            "status": "ok" if http_status == 200 else "error",
            "service": "VECTOR-ERP-SAS",
            "version": "1.0.0-GA",
            "database": db_status,
            "active_jurisdictions": active_jurisdictions,
            "country_engine": "NI-DGI-822",
            "latency_ms": latency_ms,
            "timestamp": timezone.now().isoformat(),
        }
        return JsonResponse(data, status=http_status)

