#!/usr/bin/env bash
# ==============================================================================
# ETERNAL LABS - ENTERPRISE SOFTWARE DIVISION
# SCRIPT DE CONSTRUCCIÓN Y DESPLIEGUE CONTINUO (CI/CD)
# Proyecto: ERP SAS Multi-Tenant B2B (Centroamérica / Nicaragua Core)
# ==============================================================================

set -o errexit

echo "==> [ETERNAL LABS] Instalando dependencias de producción..."
pip install --upgrade pip
pip install -r requirements.txt

echo "==> [ETERNAL LABS] Recopilando archivos estáticos con WhiteNoise..."
python manage.py collectstatic --no-input

echo "==> [ETERNAL LABS] Aplicando migraciones de base de datos..."
python manage.py migrate

echo "==> [ETERNAL LABS] Inicializando catálogo regional y escenario sandbox..."
python manage.py seed_countries || true
python manage.py prepare_sandbox

echo "==> [ETERNAL LABS] Proceso de construcción finalizado exitosamente."
