# Auditoría de Seguridad y Corrección de Acceso a SaaS HQ — Fase 1A

- **Fecha:** 16 de Octubre de 2026
- **Responsable:** Senior Django Security Engineer & QA Lead
- **Repositorio:** `willexe-1/ERP_SAS`
- **Rama:** `main`
- **Commit auditado:** `add4e3ae16dabff3d891f118ea2df88804fbacae`
- **Estado de trabajo:** Sin cambios fuera de alcance. Modificaciones limitadas exclusivamente a la capa de autorización de SaaS HQ y sus correspondientes pruebas de regresión.

---

## 1. Causa Raíz Confirmada

### 1.1 Confusión de Contextos: Autorización Tenant-Level vs. Platform-Level
El sistema implementa un modelo RBAC jerárquico (`RoleLevel`) con valores numéricos que van de `VIEWER` (10) a `OWNER_ADMIN` (100).
Dentro del modelo de datos de inquilinos (`OrganizationMembership`), el creador o administrador principal de una empresa cliente recibe el nivel de rol `RoleLevel.OWNER_ADMIN = 100`.

En las vistas originales de SaaS HQ (`apps/tenancy/views_saas_hq.py`):
```python
class EternalLabsSaasHqView(RoleLevelRequiredMixin, View):
    min_role_level = RoleLevel.OWNER_ADMIN

    def dispatch(self, request, *args, **kwargs):
        real_level = getattr(request, 'real_role_level', getattr(request, 'role_level', 0))
        if real_level < RoleLevel.OWNER_ADMIN and not (request.user and request.user.is_superuser):
            return render_403_rbac(...)
        return super().dispatch(request, *args, **kwargs)
```

La condición de rechazo era:
`if real_level < RoleLevel.OWNER_ADMIN and not (request.user and request.user.is_superuser):`

Por lógica booleana De Morgan, el acceso solo se rechazaba si:
`real_level < 100` **Y** el usuario **NO** era superusuario.

Por consiguiente, si cualquier usuario cliente tenía `real_level == 100` (`RoleLevel.OWNER_ADMIN`) dentro de su organización, `real_level < 100` resultaba **Falso**. En consecuencia, el bloque `if` se saltaba y el usuario cliente **obtenía acceso completo a SaaS HQ**, sin ser superusuario de la plataforma.

### 1.2 Ausencia de Controles Específicos en Vistas de Mutación y Exfiltración de Datos
- **Exfiltración de Datos de Otros Tenants (`TenantVaultBackupExportView`):**
  La vista aceptaba un parámetro URL `org_id` opcional (`/saas-hq/backup/<uuid:org_id>/`). Aunque tenía una comprobación `real_level < RoleLevel.OWNER_ADMIN`, un propietario de una organización A (nivel 100) podía enviar el UUID de una organización B y descargar el volcado completo en formato JSON con información tributaria, clientes CRM, inventario y facturación de dicha organización competidora.
- **Mutación de Planes (`SaasSwitchPlanView`):**
  Heredaba de `RoleLevelRequiredMixin` con `min_role_level = RoleLevel.OWNER_ADMIN`. No sobrescribía `dispatch` ni exigía `is_superuser`.
- **Suspensión/Activación de Tenants (`SaasUpdateStatusView`):**
  Heredaba de `RoleLevelRequiredMixin` con `min_role_level = RoleLevel.OWNER_ADMIN`. No sobrescribía `dispatch` ni exigía `is_superuser`.
- **Emisión Forzada de Facturas SaaS (`SaasGenerateInvoiceView`):**
  Heredaba de `RoleLevelRequiredMixin` con `min_role_level = RoleLevel.OWNER_ADMIN`. Permitía generar facturas arbitrarias.

---

## 2. Archivos y Funciones Modificados

### 2.1 `apps/tenancy/permissions.py`
Se introdujo la clase de mixin `PlatformSuperuserRequiredMixin`:
- **Herencia:** Hereda de `TenantRequiredMixin` para preservar la coherencia del ciclo de vida de la petición.
- **Flujo de verificación en `dispatch`:**
  1. **Autenticación temprana:** Verifica `if not request.user.is_authenticated: return self.handle_no_permission()`. Redirige limpiamente con código HTTP 302 a la pantalla de login, evitando además errores en plantillas como `403_rbac.html` que dependen de atributos del usuario autenticado.
  2. **Autorización estricta de plataforma:** Verifica `if not request.user.is_superuser: return render_403_rbac(...)`. Si el usuario no tiene la bandera `is_superuser=True`, devuelve de inmediato una respuesta HTTP 403 Forbidden con el template RBAC institucional.
  3. **Delegación segura:** Si y solo si ambas condiciones se satisfacen, invoca `super().dispatch(request, *args, **kwargs)`.

### 2.2 `apps/tenancy/views_saas_hq.py`
- Se sustituyó la herencia de `RoleLevelRequiredMixin` por `PlatformSuperuserRequiredMixin` en las siguientes clases:
  - `EternalLabsSaasHqView` (Dashboard global de gobernanza y KPIs SaaS)
  - `TenantVaultBackupExportView` (Exportación de respaldos criptográficos)
  - `SaasSwitchPlanView` (Conmutación comercial de planes)
  - `SaasUpdateStatusView` (Suspensión, gracia o activación de tenants)
  - `SaasGenerateInvoiceView` (Generación de facturas maestras)
- Se eliminó la lógica defectuosa y permisiva `real_level < RoleLevel.OWNER_ADMIN` en `dispatch` y `get`.
- Se aseguró la resistencia a peticiones donde `request.organization` es `None` en `EternalLabsSaasHqView.get()`.
- Se añadieron alias explícitos para compatibilidad y completitud de nomenclatura:
  - `SaasHqExportTenantVaultView = TenantVaultBackupExportView`
  - `SaasHqInspectTenantView = TenantVaultBackupExportView`
  - `SaasHqUpdatePlanView = SaasSwitchPlanView`
  - `SaasHqToggleSuspendView = SaasUpdateStatusView`
  - `SaasHQDashboardView = EternalLabsSaasHqView`

### 2.3 `apps/tenancy/tests.py`
- En el conjunto de pruebas `SaasHqGovernanceAndHardeningTestSuite.setUp`, se añadió una organización dedicada de plataforma (`self.org_platform = 'Eternal Labs Master HQ'`) y un superusuario global de plataforma (`self.user_superadmin`). Se aisló este usuario para no alterar la cuota de 5 miembros de `self.org`, garantizando que pruebas concurrentes como `test_member_creation_blocked_when_max_users_quota_reached` mantengan su validez sin efectos colaterales.
- Se adaptaron los métodos:
  - `test_saas_hq_access_control_level_100_vs_lower_levels`: Verifica que el superusuario obtenga HTTP 200, mientras que el Owner de inquilino (nivel 100 sin superuser) y los niveles 85, 80, 50 y 20 reciban HTTP 403 Forbidden.
  - `test_tenant_vault_backup_export_sha256_and_security`: Verifica que solo el superusuario global pueda descargar el respaldo criptográfico y que un Owner de inquilino (nivel 100) sea rechazado con HTTP 403 Forbidden.

### 2.4 `apps/tenancy/tests_saas_hq.py`
- En `SaasHQMonetizationAndLocksTestCase.setUp`, se otorgaron las banderas `is_superuser=True` e `is_staff=True` al usuario administrador de pruebas para validar las operaciones legítimas de la plataforma.
- Se implementó la nueva suite de pruebas de seguridad `SaasHqSecurityPhase1ATestCase`, conteniendo 6 casos de prueba exhaustivos.

---

## 3. Pruebas Añadidas y Resultados

Se creó la suite `SaasHqSecurityPhase1ATestCase` en `apps/tenancy/tests_saas_hq.py`:
1. `test_anonymous_user_denied_access`:
   - Verifica que peticiones no autenticadas sean rechazadas inmediatamente con redirección HTTP 302 a `/accounts/login/`.
2. `test_tenant_owner_level_100_denied_access_to_all_saas_hq_views`:
   - Verifica que un propietario de inquilino con `RoleLevel.OWNER_ADMIN` (nivel 100) reciba HTTP 403 Forbidden en:
     - Dashboard SaaS HQ (`GET /saas-hq/`)
     - Respaldo de su propio inquilino (`GET /saas-hq/backup/<uuid>/`)
     - Cambio de plan (`POST /saas-hq/switch-plan/`)
     - Actualización de estado / suspensión (`POST /saas-hq/update-status/`)
     - Generación de factura (`POST /saas-hq/generate-invoice/`)
3. `test_normal_organization_members_denied_access`:
   - Verifica que roles inferiores dentro de un tenant cliente (Gerente Nivel 85, Facturador Nivel 50, Cajero/Vendedor Nivel 20) reciban HTTP 403 Forbidden.
4. `test_cross_tenant_tampering_and_data_leak_blocked`:
   - Verifica que un propietario del Tenant A no pueda consultar ni descargar la bóveda criptográfica del Tenant B (HTTP 403 Forbidden), impidiendo la exfiltración de datos entre inquilinos.
5. `test_platform_superuser_granted_access`:
   - Verifica que un usuario con `is_superuser=True` acceda legítimamente al dashboard (HTTP 200), pueda actualizar planes (HTTP 302 con cambio efectivo a ENTERPRISE), conmutar estados (HTTP 302 con cambio efectivo a SUSPENDED), generar facturas (HTTP 302) y descargar el respaldo con integridad SHA-256 válida.
6. `test_alternative_http_methods_blocked_by_authorization_gate`:
   - Verifica que métodos HTTP alternativos como PUT, DELETE y PATCH sean interceptados y rechazados por la compuerta de autorización (HTTP 403 Forbidden).

**Resultado de ejecución de la nueva suite:**
```bash
python3 manage.py test apps.tenancy.tests_saas_hq.SaasHqSecurityPhase1ATestCase
# Ran 6 tests in 9.735s
# OK
```

---

## 4. Resultado de las Pruebas Existentes

- **Suite `apps.tenancy.tests_saas_hq`:**
  - 14 pruebas ejecutadas (incluyendo suites anteriores de monetización y bloqueos).
  - Resultado: **14 tests PASSED (22.274s) — OK**.
- **Suite `apps.tenancy.tests.SaasHqGovernanceAndHardeningTestSuite`:**
  - 5 pruebas ejecutadas.
  - Resultado: **5 tests PASSED (16.591s) — OK**.
- **Suite completa de la aplicación `apps.tenancy`:**
  - 38 pruebas ejecutadas.
  - Resultado: **38 tests PASSED (61.182s) — OK**.
- **Suite completa del proyecto (155 tests):**
  - Comando: `python3 manage.py test`
  - Resultado: **Ran 155 tests in 326.213s — OK** (0 fallos, 0 errores en todos los módulos: accounts_auth, billing, crm, finance, inventory, operations, payroll, purchasing, repository, sst, tenancy, tickets).

---

## 5. Riesgos Residuales y Controles Pendientes de Revisión

1. **Dependencia de la sesión activa (`request.organization`):**
   - Vistas como `SaasSwitchPlanView` y `SaasUpdateStatusView` actúan sobre `request.organization` (el tenant activo seleccionado en la sesión del superadministrador). Si la sesión pierde o no define `request.organization`, la redirección ocurre sin advertencia. Se recomienda en fases posteriores permitir indicar explícitamente el `tenant_id` objetivo en el payload POST con validación de existencia.
2. **Superusuario vs. Doble Factor de Autenticación (MFA/2FA):**
   - Actualmente, la bandera `is_superuser=True` concede acceso directo sin exigir un segundo factor de autenticación obligatorio. En el roadmap de seguridad de SaaS HQ, se debe incorporar verificación TOTP/WebAuthn previa al ingreso a la consola maestra.
3. **Pistas de Auditoría Inmutables (Audit Logs):**
   - Si bien los respaldos exportados cuentan con sello SHA-256, las operaciones de suspensión o cambio de plan en SaaS HQ deben quedar registradas en un log de auditoría inmutable de eventos de plataforma (Phase 1B+), registrando IP, usuario superadmin, timestamp y acción ejecutada.

---

## 6. Resumen del Diff y Confirmación de Alcance

```
 M apps/tenancy/permissions.py
 M apps/tenancy/tests.py
 M apps/tenancy/tests_saas_hq.py
 M apps/tenancy/views_saas_hq.py
```
- **Total de archivos de código modificados:** 4 (estrictamente limitados a `apps/tenancy`).
- **Archivos fuera de alcance:** Ninguno. No se tocaron módulos de contabilidad, inventario, facturación, sst, compras, ventas, nómina ni plantillas ajenas a la consola. No se realizaron migraciones ni se agregaron dependencias externas.
