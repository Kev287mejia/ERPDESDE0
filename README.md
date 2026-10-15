# ERP SAS — Plataforma de Gestión Empresarial Adaptativa Multi-Tenant

**Desarrollado por:** Eternal Labs — División de Ingeniería de Software Empresarial  
**Versión Oficial:** Release v1.0.0-GA (General Availability)  
**Distribución:** Confidencial / Propiedad Intelectual Corporativa  
**Arquitectura:** Multi-Tenant SaaS · Micro-módulos Integrados · Motor Fiscal Centroamericano  

---

## 1. Visión y Resumen Ejecutivo

**ERP SAS** es una plataforma unificada de planificación de recursos empresariales y gobierno operativo diseñada para solventar la desconexión crítica entre la prospección comercial, la ejecución técnica en campo, el control de inventarios, la fiscalidad centroamericana (DGI Ley 822 / MITRAB Ley 618) y la contabilidad bajo normas NIIF para PYMES.

A diferencia de los ERPs tradicionales monolíticos, la plataforma opera bajo el paradigma de **Gobierno Adaptativo por Contexto**: cada organización (Tenant) suscribe y activa de manera granular únicamente los subsistemas que demanda su giro industrial, garantizando una experiencia de usuario de alta densidad en estética **All-Light Swiss Grid** (sin ruido visual, con tipografía técnica calibrada y tiempos de respuesta sub-segundo).

---

## 2. Los 12 Módulos Integrados de la Plataforma

| # | Módulo | Directorio | Alcance y Capacidades Operativas |
| :--- | :--- | :--- | :--- |
| **01** | **Tenencia & Gobierno Multi-Tenant** | `apps/tenancy` | Aislamiento estricto por organización (`TenantScopedModel`), control de planes SaaS (`ENTERPRISE`, `BUSINESS_PRO`, `PYME_STARTER`), cuotas de usuarios, conmutador de inquilinos y auditoría de suscripción. |
| **02** | **Autenticación & RBAC Jerárquico** | `apps/accounts_auth` | Cadena de mando numérica lineal (Niveles 10 a 100), simulación de roles en tiempo real, control de sesiones corporativas y bitácora de acceso. |
| **03** | **CRM & Cotizador Bimonetario** | `apps/crm` | Pipeline de ventas, cuentas corporativas, gestión de contactos, licitaciones y cotizaciones formales bimonetarias (`NIO C$` y `USD $`). |
| **04** | **Operaciones & Órdenes de Trabajo** | `apps/operations` | Gestión de Órdenes de Trabajo (OTs), asignación de cuadrillas de campo, bitácora de avances, rendición técnica y firmas digitales. |
| **05** | **Seguridad y Salud en el Trabajo (SST)** | `apps/sst` | Cumplimiento estricto de la Ley 618 (MITRAB), actas de entrega de EPP, checklists de seguridad de campo y avales de riesgo preventivo. |
| **06** | **Inventario, Bodegas & Kardex** | `apps/inventory` | Control multialmacén, movimientos Kardex (PEPS/Promedio), trazabilidad de lotes con expiración FEFO y códigos de barra. |
| **07** | **Finanzas, Tesorería & Caja Chica** | `apps/finance` | Cuentas bancarias multimoneda, custodia y rendición de fondos fijos de caja chica, contabilidad de partida doble bajo NIIF y balance de comprobación. |
| **08** | **Facturación Fiscal DGI & Turnos POS** | `apps/billing` | Facturación formal con pie de imprenta DGI, retenciones en la fuente (2% / 1%), Recibos Oficiales de Caja (ROC), terminal de punto de venta (POS) y turnos de caja con arqueo ciego Corte X / Corte Z sellados con SHA-256 inmutable. |
| **09** | **Compras, Proveedores & Cuentas por Pagar** | `apps/purchasing` | Catálogo de proveedores, órdenes de compra (OC), control de recepciones de almacén y registro de pasivos comerciales. |
| **10** | **Repositorio Documental ISO** | `apps/repository` | Bóveda documental jerárquica con control estricto de versiones, estados de vigencia (Borrador, Vigente, Obsoleto) y auditoría de descargas. |
| **11** | **Mesa de Ayuda & Tickets SLA** | `apps/tickets` | Mesa de servicio técnico, acuerdos de nivel de servicio (SLA) con semáforos de criticidad, asignación a especialistas e historial de comentarios. |
| **12** | **Servidor MCP & Gobierno de Tokens** | `apps/ai_agent` | Servidor del protocolo Model Context Protocol (MCP) para interoperabilidad contextual, auditoría de consumo de tokens y tokens de acceso con alcance granular. |

---

## 3. Las 4 Verticales de Negocio Demostrativas

La plataforma incorpora perfiles de negocio preconfigurados y sembrados para auditoría inmediata:

1. **SERMANSA Ingeniería S.A. (Servicios de Ingeniería y Mantenimiento Industrial)**
   - *Giro:* `ENGINEERING_SERVICES` · *Plan SaaS:* `ENTERPRISE` ($199.00 USD/mes · Cuota 50 usuarios).
   - *Flujo:* Licitaciones, OTs de campo, cuadrillas técnicas, checklists SST Ley 618 MITRAB, fondos de caja chica y nómina industrial.
2. **Ferretería El Maestro S.A. (Comercio Ferretero y Materiales)**
   - *Giro:* `HARDWARE_STORE` · *Plan SaaS:* `BUSINESS_PRO` ($89.00 USD/mes · Cuota 15 usuarios).
   - *Flujo:* Terminal POS para mostrador, 3 listas de precios (Público, Técnico, Mayorista), compras y control de inventario de construcción.
3. **Farmacia Santa Lucía S.A. (Salud y Droguería Farmacéutica)**
   - *Giro:* `PHARMACY_HEALTH` · *Plan SaaS:* `BUSINESS_PRO` ($89.00 USD/mes · Cuota 15 usuarios).
   - *Flujo:* Gestión estricta de medicamentos con Registro Sanitario MINSA, control de lotes con caducidad FEFO y dispensación en POS.
4. **Comercial Masaya S.A. (Comercio Minorista y PYME Retail)**
   - *Giro:* `SME_RETAIL` · *Plan SaaS:* `PYME_STARTER` ($39.00 USD/mes · Cuota 5 usuarios).
   - *Flujo:* Facturación ágil de tienda, control de caja y catálogo de productos esenciales.

---

## 4. Arquitectura de Seguridad, Multi-Tenancy y Consola SaaS HQ

### A. Consola Maestra de Gobierno SaaS (`/saas-hq/`)
- Exclusiva para la Dirección General y SuperAdmins (Nivel 100).
- Métricas globales en tiempo real: MRR consolidado ($416.00 USD / C$ 15,235.71 NIO), ARR proyectado ($4,992.00 USD), distribución por plan y por vertical de negocio.
- Tabla Maestra de Tenants con actualización de planes, cuotas de usuarios y conmutación de estado operativo (`ACTIVE` / `SUSPENDED`).
- Bloqueo de mutaciones operativas (POST) cuando una organización se encuentra en suspensión por mora, preservando la lectura y auditoría.

### B. Respaldo Criptográfico por Organización (`Tenant Vault Backup JSON`)
- Exportación portátil estructurada en formato JSON (`/saas-hq/backup-json/<org_id>/`).
- Contiene metadatos fiscales, colaboradores, cuentas CRM, catálogo de inventario, pólizas y resumen de facturas.
- Sello criptográfico inmutable `integrity_seal_sha256` calculado sobre el payload canónico para garantizar la autenticidad del archivo.

### C. Telemetría y Salud de Infraestructura (`/healthz/`)
- Endpoint público para monitores Cloud (Docker, Kubernetes, Render, Railway, Cloudflare).
- Responde `HTTP 200 OK` con JSON estructurado validando: conectividad a la base de datos (`SELECT 1`), conteo de jurisdicciones activas, versión del sistema (`1.0.0-GA`) y latencia en milisegundos.

### D. Hardening de Cabeceras HTTP en Producción
- `SECURE_CONTENT_TYPE_NOSNIFF = True`
- `X_FRAME_OPTIONS = 'SAMEORIGIN'`
- `REFERRER_POLICY = 'strict-origin-when-cross-origin'`

### E. Capacidades PWA de Campo (Progressive Web App)
- `manifest.json` y `service-worker.js` registrados en la raíz.
- Soporte de instalación nativa en dispositivos móviles y de escritorio.
- Modo de contingencia offline (`/offline/`) para supervisores e inspectores en zonas sin cobertura de red.

---

## 5. Cadena de Mando Jerárquica (RBAC Numérico 10..100)

| Nivel | Rol Operativo | Capacidades Principales |
| :---: | :--- | :--- |
| **100** | **Owner / Administrador General** | Consola SaaS HQ, balance contable, gobierno de suscripción, nómina legal y simulador de roles. |
| **85** | **Gerente Comercial** | Gestión de pipeline de ventas, cuentas corporativas, contratos y cotizaciones bimonetarias. |
| **80** | **Coordinador Operativo** | Asignación de cuadrillas, programación de OTs y autorización de partidas operativas. |
| **70** | **Oficial SST (Seguridad y Salud)** | Checklists Ley 618 MITRAB, actas de EPP y avales preventivos de seguridad. |
| **50** | **Ingeniero Residente / Supervisor** | Ejecución técnica de OTs, rendición de caja chica y supervisión de campo. |
| **20** | **Técnico de Campo** | Bitácoras diarias de trabajo, reporte de incidencias y registro de gastos menores. |
| **10** | **Auditor / Observador Pasivo** | Lectura estricta para fiscalizadores externos e inspecciones regulatorias. |

---

## 6. Guía Rápida de Puesta en Marcha

### Requisitos Previos
- Python 3.12+ / 3.13
- Entorno virtual activado (`venv`)

### Inicialización en 3 Pasos
```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Ejecutar migraciones relacionales
python manage.py migrate

# 3. Sembrar datos de demostración de las 4 verticales y usuarios
python manage.py seed_demo_erp
```

### Ejecución de Pruebas Automatizadas
```bash
python manage.py test
```
*La suite ejecuta más de 150 pruebas unitarias y de integración al 100% de cobertura sin regresiones.*

### Credenciales de Demostración
- **Usuario Administrador (Nivel 100):** `admin@sermansa.ni` · Clave: `Eternal2026*`
- **Usuario Evaluador (Nivel 100):** `evaluador@eternallabs.ni` · Clave: `Eternal2026*`

---

## 7. Propiedad Intelectual

Copyright (c) 2026 Eternal Labs. Todos los derechos reservados.  
División de Ingeniería de Software Empresarial y Seguridad Cloud.
