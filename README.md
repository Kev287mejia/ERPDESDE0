# ERP SAS — Plataforma de Gestión Empresarial Adaptativa Multi-Tenant

**Desarrollado por:** Eternal Labs — División de Ingeniería de Software Empresarial  
**Estado del Release:** Fundación Arquitectónica v0.1.0 (Core, Multi-Tenancy, RBAC & Motor Regional)  
**Distribución:** Confidencial / Propiedad Intelectual Corporativa  

---

## 1. Planteamiento del Problema

Las empresas de servicios, mantenimiento industrial, contratistas de ingeniería y operaciones de campo en Centroamérica enfrentan una brecha estructural en sus sistemas de información:

1. **Rigidez de los ERPs Tradicionales:** Los sistemas monolíticos comerciales han sido diseñados bajo modelos contables rígidos pensados para corporaciones globales. Su implementación demanda inversiones desproporcionadas y obliga a las organizaciones a adaptar sus operaciones a la burocracia del software en lugar de que el sistema potencie el ritmo operativo.
2. **Fragmentación por Hojas de Cálculo:** Ante la complejidad de los sistemas tradicionales, las áreas operativas recurren a hojas de cálculo aisladas. Esta fragmentación destruye la trazabilidad entre las licitaciones comerciales, las órdenes de trabajo ejecutadas en campo, el control de inventarios en bodegas y el cumplimiento riguroso de seguridad laboral.

### La Solución de Eternal Labs

**ERP SAS** resuelve esta desconexión unificando en un solo flujo transaccional continuo todo el ciclo operativo: desde la prospección comercial y cotización formal bimonetaria, pasando por la Orden de Trabajo (OT) y despacho de cuadrillas técnicas, hasta la validación obligatoria de Seguridad y Salud en el Trabajo (SST), control de almacenes y arqueo de cajas chicas.

La plataforma opera bajo el principio de **Gestión Adaptativa por Contexto**: cada organización (Tenant) suscribe y activa de manera granular únicamente los subsistemas que demanda su giro industrial (Comercial, Operaciones, SST, Inventarios, Finanzas, Tecnología o Marketing), garantizando que los colaboradores interactúen exclusivamente con herramientas directamente relevantes para su función.

---

## 2. Arquitectura e Ingeniería del Sistema

### A. Aislamiento Multi-Tenant Estricto (`TenantScopedModel`)
La plataforma implementa un modelo de tenencia compartida con aislamiento lógico riguroso. Cada entidad transaccional hereda de `TenantScopedModel`, asegurando que todas las consultas y escrituras queden acotadas al identificador de la organización resuelta en la sesión.

El componente central `TenancyContextMiddleware` intercepta cada petición HTTP, resuelve la membresía del usuario autenticado y valida en tiempo de ejecución:
- Que la organización receptora esté activa.
- Que el usuario posea una membresía vigente en dicha organización.
- Que los módulos solicitados formen parte de la suscripción activa del Tenant.

Cualquier intento de acceso cruzado entre organizaciones o a subsistemas no suscritos genera una denegación inmediata a nivel de ORM y controlador (`403 Forbidden`).

### B. Motor de Localización Multi-País (`CountryConfig`)
La arquitectura está diseñada para operar de forma nativa en la región centroamericana (`NI`, `CR`, `HN`, `SV`, `GT`, `PA`) sin requerir reglas fiscales embebidas o modificadas en código.

En su versión inicial, el sistema opera con parametrización completa para **Nicaragua (NI)**:
- **Soporte Bimoneda Nativo:** Operaciones simultáneas en Córdobas (`NIO C$`) y Dólares Estadounidenses (`USD $`), con desglose de tasas de cambio y presentación financiera uniforme.
- **Validación Tributaria DGI:** Algoritmos de validación formal para Registro Único de Contribuyentes (`RUC` de 14 dígitos) y Cédula de Identidad Ciudadana con formato de serie y dígito verificador.
- **Régimen Fiscal Parametrizado:** Impuesto al Valor Agregado (`IVA 15%`), retenciones en la fuente y esquemas contables adaptados a NIIF para PYMES.

### C. Cadena de Mando Jerárquica (`RBAC Numérico 10..100`)
Para evitar fallas de escalamiento de privilegios e inversiones en la cadena de mando, el sistema implementa un control de acceso basado en roles con ponderación numérica lineal:

| Nivel Numérico | Rol Operativo | Alcance de Autoridad |
| :--- | :--- | :--- |
| **Nivel 100** | Owner / Administrador General | Gobierno corporativo, libros contables, nómina, gestión de módulos y control legal del RUC. |
| **Nivel 85** | Gerente Comercial | Gestión de licitaciones corporativas, pliegos, contratos y cotizaciones bimonetarias. |
| **Nivel 80** | Coordinador Operativo | Programación de cuadrillas de campo, asignación de ingenieros residentes y apertura de cajas chicas. |
| **Nivel 70** | Oficial SST (Seguridad y Salud) | Auditorías de campo, inspecciones preventivas, avales de riesgo y cumplimiento de Ley 618 (MITRAB). |
| **Nivel 50** | Ingeniero Residente / Supervisor | Ejecución técnica de Órdenes de Trabajo, rendición de cuentas y custodia de fondos asignados. |
| **Nivel 20** | Técnico de Campo | Reportes operativos diarios, checklist técnico de frentes de obra y registro de gastos menores. |
| **Nivel 10** | Observador / Auditor | Lectura restringida para auditorías externas, entidades reguladoras y monitoreo pasivo. |

El sistema incluye una herramienta de **Simulación de Rol en Tiempo Real**, permitiendo al Administrador General (Nivel 100) auditar la visibilidad de pantallas y restricciones desde la perspectiva de cualquier rango subordinado sin salir de su sesión.

### D. Interfaz Operativa de Alta Densidad (Swiss Grid UI)
La interfaz del sistema prescinde completamente del panel genérico administrativo para entregar una consola técnica construida bajo principios de diseño suizo:
- Cuadrícula de alta densidad con líneas capilares de 1px (`border-zinc-200`) y fondo blanco puro (`#FFFFFF`).
- Tipografía técnica calibrada: `Inter` para jerarquía textual y `JetBrains Mono` con cifras tabulares fijas (`tabular-nums`) para montos financieros, códigos de orden y métricas.
- Banda telemétrica de 4 celdas divididas para lectura inmediata de saldos, órdenes activas, disponibilidad de infraestructura y ratios de seguridad.

---

## 3. Stack Tecnológico

- **Lenguaje y Framework Principal:** Python 3.13 con Django 5.1.x
- **Gestor de Base de Datos:** PostgreSQL (Transaccional ACID) / SQLite para entornos de pruebas locales
- **Frontend & Reactividad Ligera:** Django Server-Side Templates + Tailwind CSS + Alpine.js + HTMX
- **Aislamiento Multi-Tenant:** Django ORM con filtrado forzado (`for_org`) y Middleware de Tenencia
- **Archivos Estáticos:** WhiteNoise con compresión gzip/brotli

---

## 4. Guía Rápida para Evaluadores (UX / Marketing & Producto)

Esta sección permite a los evaluadores de diseño, mercadeo y analistas de producto auditar el sistema en menos de un minuto con datos industriales reales de Nicaragua (cero configuraciones manuales requeridas):

### Acceso Inmediato: Botón "1-Clic Demo Sandbox"
1. Inicie el servidor local (`python manage.py runserver`) o acceda a la URL de producción y navegue a:
   ```
   http://127.0.0.1:8000/auth/login/
   ```
2. Debajo del formulario de acceso, en el panel **MODO EVALUACIÓN DE PRODUCTO & UX**, pulse el botón:
   `Ingresar al Sandbox Industrial (1-Clic Demo)`
3. El sistema autenticará automáticamente la sesión del evaluador (`evaluador@eternallabs.ni`) con privilegios completos de Owner (Nivel 100) en la organización industrial demostrativa **IMESA INGENIERÍA S.A.** (RUC `J0310000458912`) y redirigirá directamente al Centro de Control.

### Controles Interactivos de Datos en Interfaz (Swiss Grid Controls)
En el Centro de Control (`/tenancy/dashboard/`) y en la Consola de Personal (`/tenancy/team/`), el usuario Nivel 100 dispone de un panel técnico superior con dos acciones inmediatas:
- **Cargar Escenario Industrial NI:** Regenera de forma idempotente todas las entidades operativas en los 6 subsistemas (personal RBAC, cuentas corporativas, oportunidades, cotizaciones NIO/USD, cuadrillas, OTs con bitácora, checklists Ley 618 MITRAB, bodegas, materiales, Kardex y cajas chicas).
- **Vaciar Datos de Prueba:** Purga de forma segura todos los registros operativos de prueba, conservando intacta la organización y la cuenta del evaluador para auditoría de estados vacíos.

### Inicialización por Terminal (CLI Alternativo)
Si prefiere aprovisionar el entorno desde la consola de comandos, ejecute:
```bash
python manage.py prepare_sandbox
```
*Argumentos opcionales:*
- `python manage.py prepare_sandbox --reset`: Limpia previamente las organizaciones residuales de pruebas antes de sembrar los datos.

### Auditoría con el Simulador de Roles en Tiempo Real
Desde la barra superior de navegación, el evaluador puede alternar en caliente entre los niveles jerárquicos:
- **Gerente Comercial (85):** Visualización de pipeline corporativo, cotizaciones y clientes.
- **Coordinador Operativo (80):** Asignación de cuadrillas y seguimiento de órdenes de trabajo.
- **Oficial SST (70):** Bloqueos de seguridad, checklists normativos MITRAB y dotación EPP.
- **Ingeniero Residente (50):** Ejecución técnica de partidas de obra y rendición de caja chica.
- **Técnico de Campo (20):** Reportes diarios de bitácora y comprobantes de gasto menor.
### Evaluación Remota en Vivo con Cloudflare Quick Tunnels
Para compartir una sesión de evaluación remota con el equipo de Marketing y Diseño sin requerir registro previo ni configuración de puertos:
```bash
./run_live_demo.sh
```
*El script levanta el servidor local Django en el puerto `8000` y genera de forma automática un túnel HTTPS seguro (`https://xxxx.trycloudflare.com`). Al compartir ese enlace, el evaluador puede acceder directamente al sistema y presionar el botón "1-Clic Demo".*

---

## 5. Despliegue en la Nube y Contenedores

La plataforma está optimizada para despliegue automatizado y continuo en proveedores PaaS (Render, Railway, Fly.io) o infraestructura propia sobre Kubernetes/Docker:

### A. Despliegue Automatizado en Render (`render.yaml`)
El repositorio incluye el blueprint formal `render.yaml` que aprovisiona conjuntamente el servicio web Python y la base de datos PostgreSQL administrada:
1. Conecte el repositorio en el panel de Render.
2. Render detectará automáticamente `render.yaml` y ejecutará el script `build.sh`:
   - Instalación de dependencias optimizadas de `requirements.txt`.
   - Recopilación de archivos estáticos con WhiteNoise (`collectstatic`).
   - Aplicación de migraciones de base de datos relacionales (`migrate`).
   - Ejecución automática de `seed_countries` y `prepare_sandbox`.
3. El servicio web arrancará mediante Gunicorn con balanceo de trabajadores concurrentes:
   ```bash
   gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --threads 2
   ```

### B. Despliegue Mediante Contenedores Docker (`Dockerfile`)
Para ejecutar la plataforma en cualquier servidor o clúster local:
```bash
# Construcción de la imagen de producción
docker build -t erp-vector:latest .

# Ejecución del contenedor
docker run -d \
  -p 8000:8000 \
  -e SECRET_KEY="clave-de-produccion-corporativa" \
  -e DEBUG="False" \
  -e ALLOWED_HOSTS="localhost,127.0.0.1,tudominio.com" \
  --name erp-vector-app erp-vector:latest
```

### C. Variables de Entorno de Producción
| Variable | Descripción | Valor Predeterminado / Ejemplo |
| :--- | :--- | :--- |
| `SECRET_KEY` | Clave criptográfica para firmas de sesión | Generada en despliegue |
| `DEBUG` | Indicador de depuración en desarrollo | `False` en producción |
| `DATABASE_URL` | URI de conexión a PostgreSQL relacional | Fallback a `sqlite:///db.sqlite3` |
| `ALLOWED_HOSTS` | Lista de dominios permitidos separados por coma | `.onrender.com,localhost` |
| `CSRF_TRUSTED_ORIGINS` | Orígenes HTTPS válidos para peticiones POST | `https://*.onrender.com` |

---

## 6. Propiedad Intelectual y Créditos

Copyright (c) 2026 Eternal Labs. Todos los derechos reservados. Arquitectura y dirección técnica desarrollada por Eternal Labs.
