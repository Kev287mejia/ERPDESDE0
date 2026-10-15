# ==============================================================================
# VECTOR ERP SAS - CLOUD SAAS PRODUCTION CONTAINER
# Arquitectura: Multi-Tenant Enterprise / Python 3.12 / Gunicorn / WhiteNoise
# ==============================================================================

FROM python:3.12-slim

# Variables de entorno operativas
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DJANGO_SETTINGS_MODULE=config.settings

# Directorio de trabajo
WORKDIR /app

# Instalación de paquetes de sistema operativo para PostgreSQL y healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copia e instalación de dependencias Python
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia del código fuente del proyecto
COPY . /app/

# Creación de usuario del sistema sin privilegios root
RUN addgroup --system appgroup && adduser --system --group appuser

# Compilación de archivos estáticos para WhiteNoise
RUN SECRET_KEY=docker-build-temporary-key python manage.py collectstatic --noinput || true

# Asignación de permisos al usuario no root
RUN chown -R appuser:appgroup /app
USER appuser

# Exposición de puerto HTTP
EXPOSE 8000

# Healthcheck nativo apuntando al endpoint de salud /healthz/
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz/ || exit 1

# Servidor de producción WSGI Gunicorn
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "2", "--timeout", "120"]
