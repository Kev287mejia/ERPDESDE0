import time
from django.db import connection
from django.http import JsonResponse
from django.views import View


class SystemHealthcheckView(View):
    """
    Endpoint de salud del sistema para balanceadores de carga, orquestadores
    (Docker, Kubernetes) y monitoreo de alta disponibilidad.
    Público, sin sesión ni autenticación requerida.
    """

    def get(self, request, *args, **kwargs):
        start_time = time.perf_counter()
        db_status = "connected"
        http_status = 200

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as e:
            db_status = f"disconnected: {str(e)}"
            http_status = 503

        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        data = {
            "status": "ok" if http_status == 200 else "error",
            "service": "VECTOR-ERP-SAS",
            "database": db_status,
            "country_engine": "NI-DGI-822",
            "latency_ms": latency_ms,
        }
        return JsonResponse(data, status=http_status)
