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

## 4. Guía de Despliegue Local (Desarrollo)

### Requisitos Previos
- Python 3.13 o superior instalado en el sistema operativo.
- Git instalado y configurado.

### Paso 1: Clonar el Repositorio
```bash
git clone https://github.com/Kev287mejia/ERPDESDE0.git
cd ERPDESDE0
```

### Paso 2: Crear y Activar el Entorno Virtual
En macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

En Windows (PowerShell):
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### Paso 3: Instalar Dependencias
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Paso 4: Configurar Variables de Entorno
Copie el archivo de ejemplo y defina las credenciales correspondientes:
```bash
cp .env.example .env
```

### Paso 5: Ejecutar Migraciones de Base de Datos
```bash
python manage.py migrate
```

### Paso 6: Inicializar la Configuración Regional de Países
Ejecute el comando de poblamiento para precargar las configuraciones fiscales de Centroamérica:
```bash
python manage.py seed_countries
```

### Paso 7: Iniciar el Servidor de Desarrollo
```bash
python manage.py runserver
```

La consola operativa estará disponible en:
```
http://127.0.0.1:8000/
```

### Paso 8: Ejecución de la Suite de Pruebas Unitarias
Para validar la integridad de aislamiento de datos, permisos RBAC y motor financiero:
```bash
python manage.py test
```

---

## 5. Propiedad Intelectual y Créditos

Copyright (c) 2026 Eternal Labs. Todos los derechos reservados. Arquitectura y dirección técnica desarrollada por Eternal Labs.
