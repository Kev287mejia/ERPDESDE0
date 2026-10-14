#!/usr/bin/env bash
# ==============================================================================
# ETERNAL LABS - ENTERPRISE SOFTWARE DIVISION
# SCRIPT DE LANZAMIENTO PARA DEMOSTRACIÓN EN VIVO (LIVE SANDBOX TUNNEL)
# Arquitectura: ERP SAS Multi-Tenant B2B / Cloudflare Quick Tunnels
# ==============================================================================

set -o errexit

PORT=8000
SERVER_HOST="127.0.0.1"

echo "========================================================================"
echo "ETERNAL LABS — SERVIDOR DE EVALUACIÓN REMOTA EN VIVO"
echo "========================================================================"

# 1. Asegurar binario de cloudflared
CLOUDFLARED_BIN=""
if command -v cloudflared &> /dev/null; then
    CLOUDFLARED_BIN="$(command -v cloudflared)"
elif [ -f "/tmp/cloudflared_bin/cloudflared" ]; then
    CLOUDFLARED_BIN="/tmp/cloudflared_bin/cloudflared"
else
    echo "==> [ETERNAL LABS] Descargando binario oficial de Cloudflare Quick Tunnels..."
    mkdir -p /tmp/cloudflared_bin
    curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz | tar -xz -C /tmp/cloudflared_bin
    CLOUDFLARED_BIN="/tmp/cloudflared_bin/cloudflared"
fi

echo "==> [ETERNAL LABS] Binario detectado: $CLOUDFLARED_BIN"

# 2. Inicializar entorno sandbox local si es requerido
echo "==> [ETERNAL LABS] Verificando base de datos y migraciones relacionales..."
python3 manage.py migrate --no-input

# 3. Iniciar servidor Django en segundo plano si no está activo
DJANGO_PID=""
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null ; then
    echo "==> [ETERNAL LABS] Servidor Django ya está activo en puerto $PORT."
else
    echo "==> [ETERNAL LABS] Iniciando servidor Django en http://${SERVER_HOST}:${PORT}..."
    python3 manage.py runserver ${SERVER_HOST}:${PORT} &
    DJANGO_PID=$!
    sleep 2
fi

cleanup() {
    echo ""
    echo "==> [ETERNAL LABS] Cerrando túnel de evaluación y procesos en ejecución..."
    if [ -n "$DJANGO_PID" ]; then
        kill "$DJANGO_PID" 2>/dev/null || true
    fi
    exit 0
}

trap cleanup INT TERM EXIT

echo "========================================================================"
echo "==> [ETERNAL LABS] Abriendo túnel HTTPS seguro mediante Cloudflare..."
echo "==> Copie la URL pública generada (https://xxxx.trycloudflare.com)"
echo "==> Acceda directamente y pulse el botón: 'Ingresar al Sandbox Industrial (1-Clic Demo)'"
echo "========================================================================"
echo ""

exec "$CLOUDFLARED_BIN" tunnel --url "http://${SERVER_HOST}:${PORT}"
