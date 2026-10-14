# ==============================================================================
# ETERNAL LABS - ENTERPRISE SOFTWARE DIVISION
# CONTENEDOR DE PRODUCCIÓN DOCKER (Dockerfile)
# Arquitectura: ERP SAS Multi-Tenant / Python 3.13 / Gunicorn / WhiteNoise
# ==============================================================================

FROM python:3.13-slim

# Variables de entorno de Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Directorio de trabajo
WORKDIR /app

# Instalación de paquetes de sistema operativo para PostgreSQL y compilación
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copia e instalación de dependencias de Python
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia del código fuente del proyecto
COPY . /app/

# Creación de usuario del sistema sin privilegios root
RUN addgroup --system appgroup && adduser --system --group appuser
RUN chown -R appuser:appgroup /app
USER appuser

# Exposición de puerto HTTP
EXPOSE 8000

# Ejecución mediante Gunicorn WSGI
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers 3 --threads 2 --timeout 120"]
