# Pruebas del SGR

Pruebas automatizadas de la segunda evaluación (Parte A): acceso y recuperación de contraseña,
los seis mantenedores (Delegaciones, Roles, Usuarios, Ítems y metas, Tipo de Atención y Sub
Atención), el ingreso de atención y los requisitos comunes de interfaz y contexto.

## Cómo ejecutarlas

Con el entorno virtual activo y el `.env` configurado (ver `README.md`):

```bash
python manage.py test                      # suite completa (todas las apps, incluida common)
python manage.py test accounts             # una app
python manage.py test accounts.test_role_crud.GlobalAdministratorProtectionTests   # una clase
python manage.py test --keepdb             # reutiliza la base de pruebas entre ejecuciones
```

La suite completa tarda alrededor de dos minutos y medio en un equipo de desarrollo. No requiere
red ni correo real: los correos de recuperación usan el backend de memoria de Django durante las
pruebas.

## Base de datos usada

Las pruebas usan el mismo motor del proyecto, **MySQL**, con la conexión del `.env`
(`DB_ENGINE`, `DB_HOST`, `DB_USER`, etc.). Django crea una base aparte, `test_<DB_NAME>`, aplica
todas las migraciones y la elimina al terminar, así que **no se tocan los datos de desarrollo**.

- El usuario de `DB_USER` necesita permiso para crear y eliminar esa base (`CREATE`, `DROP`).
- La conexión usa `STRICT_TRANS_TABLES` (ver `config/settings.py`), de modo que MySQL rechaza
  valores que exceden el largo de una columna en lugar de truncarlos. Por eso los datos de prueba
  respetan los largos del modelo (por ejemplo, RUT de hasta 20 caracteres).
- Si una ejecución anterior se interrumpió y quedó la base `test_<DB_NAME>`, usar
  `python manage.py test --noinput` para que Django la reemplace sin preguntar.

Cada prueba corre dentro de una transacción que se revierte al terminar, por lo que el orden de
ejecución no afecta los resultados.

## Organización

| Módulo | Qué cubre |
| ------ | --------- |
| `accounts/test_auth_flows.py` | Login, rutas protegidas, permisos por rol, recuperación de contraseña |
| `accounts/test_login_security.py` | Bloqueo temporal por intentos fallidos y auditoría de inicio/cierre de sesión |
| `accounts/test_password_reset.py` | Modelo del código de recuperación y delegaciones autorizadas |
| `accounts/test_delegation_crud.py` | CRUD, búsqueda, paginación, exportación y ámbito de Delegaciones |
| `accounts/test_role_crud.py` | CRUD de Roles, último Administrador global, permisos privilegiados |
| `accounts/test_user_crud.py` | CRUD de Usuarios, exportación, ámbito, reglas de roles |
| `accounts/test_official_crud.py` | Funcionarios: CRUD, exportación a Excel y reglas de roles |
| `accounts/test_authorization.py` | Perfil propio y autorización administrativa (SEG-02) |
| `accounts/test_delegation_context.py` | Delegación activa: selector, sesión y efecto en listas y formularios |
| `accounts/test_audit_trail.py` | Auditoría con valor anterior/nuevo y accesos fuera de ámbito |
| `accounts/test_seed_demo.py` | Datos de demostración (`seed_demo`) y accesos por rol |
| `configuration/test_item_crud.py` | CRUD de Ítems, código, actividades afectadas al desactivar |
| `configuration/tests.py` | Tipo de Atención y Sub Atención, auditoría por campo, períodos |
| `activities/test_social_attention.py` | Reglas e ingreso de atención |
| `activities/test_attention_submission.py` | Doble envío en el servidor y consulta de la atención registrada |
| `common/tests.py` | Generación de `.xlsx`, textos de exportación, paginación compartida |
| `common/test_frontend.py` | Navegación, distintivo de contexto, estados de carga/vacío/error, maquetas |
| `common/test_requirements.py` | 403 con auditoría en cada operación, longitudes, relaciones inactivas, entradas adversas |
| `common/test_live_search.py` | Búsqueda en tiempo real (marcado, filtros en la URL) y aviso de cambios sin guardar al cambiar de delegación |

## Matriz requisito → prueba

Referencias del documento «Requisitos y plan de pruebas de la segunda evaluación». Las rutas de
prueba se abrevian como `módulo.Clase[.método]`. Una fila marcada como **manual** no tiene prueba
automatizada y debe ejecutarse y registrarse en la ficha de ejecución; no se declara aprobada.

### Acceso y recuperación (B4, A3)

| Requisito | Pruebas |
| --------- | ------- |
| ACC-01 Ingreso por cada rol, opciones según permisos | `accounts.test_seed_demo.SeedDemoAccessTests`, `accounts.test_auth_flows.ProtectedRouteTests.test_menu_only_lists_permitted_sections` |
| ACC-02 Clave incorrecta, cuenta inactiva, campos vacíos, mensaje genérico, sin sesión | `accounts.test_auth_flows.LoginTests` |
| ACC-02 / RNF Bloqueo temporal por intentos fallidos (configurable, sin revelar la cuenta) | `accounts.test_login_security.LoginLockoutTests` |
| ACC-03 Cierre de sesión, Atrás y rutas protegidas | `accounts.test_auth_flows.ProtectedRouteTests.test_logout_ends_access_and_pages_are_not_cached`, `...test_anonymous_users_are_sent_to_login` |
| ACC-04 Respuesta genérica de recuperación | `accounts.test_auth_flows.PasswordRecoveryFlowTests.test_response_is_the_same_for_existing_and_unknown_emails`, `...test_inactive_account_receives_no_code` |
| ACC-05 Código vigente, erróneo, vencido, reutilizado, reenvío e intentos | `accounts.test_auth_flows.PasswordRecoveryFlowTests`, `accounts.test_password_reset.PasswordResetCodeTests` |
| ACC-06 Clave débil, confirmación distinta, nueva aceptada, anterior y código invalidados | `accounts.test_auth_flows.PasswordRecoveryFlowTests.test_weak_or_mismatched_passwords_are_rejected`, `...test_valid_password_replaces_the_old_one_and_invalidates_the_code`, `PasswordCompositionValidatorTests` |
| SEG-04 Auditoría de ingresos, fallos, bloqueos y cierres sin contraseñas | `accounts.test_login_security.LoginAuditTests` |

### Mantenedores (A1, A2, B5, B6)

| Requisito | Pruebas |
| --------- | ------- |
| ADM-01 / ADM-02 Delegaciones: CRUD, duplicado, desactivación lógica con historia | `accounts.test_delegation_crud.DelegationCrudAdminTests` |
| ADM-03 Usuarios: crear, editar, desactivar; cuenta inactiva sin acceso | `accounts.test_user_crud.UserCrudAdminTests`, `accounts.test_official_crud.OfficialCrudTests` |
| ADM-04 Roles: lectura limitada, baja que respeta usuarios, cambios auditables | `accounts.test_role_crud.RoleCrudAdminTests`, `...RolePermissionTests`, `...GlobalAdministratorProtectionTests` |
| ADM-04 Último Administrador global protegido también desde Usuarios y Funcionarios | `accounts.test_user_crud.LastGlobalAdministratorAccountTests`, `accounts.test_official_crud.OfficialRoleRulesTests` |
| ADM-04 Rol inactivo asignado se conserva al editar | `accounts.test_user_crud.InactiveRoleAssignmentTests`, `accounts.test_official_crud.OfficialRoleRulesTests.test_editing_keeps_the_inactive_role_and_shows_it_locked` |
| ADM-06 Delegación activa, selector solo con autorizadas, contexto fijo si es única | `accounts.test_delegation_context.ActiveDelegationContextTests` |
| CAT-01 Ítems: crear, consultar, modificar, desactivar; código no se vacía; actividades afectadas | `configuration.test_item_crud` |
| CAT-02 Tipo de Atención: ciclo completo y duplicados | `configuration.tests.AttentionCatalogCrudTests` |
| CAT-03 Sub Atención: asociación válida, tipo inactivo rechazado | `configuration.tests.AttentionCatalogCrudTests.test_subattention_creation_requires_an_active_attention_type`, `...test_subattention_create_saves_association_and_generated_code` |
| CAT-04 Tipo y sub usados por atenciones históricas | `configuration.tests.AttentionCatalogCrudTests.test_subattention_type_association_cannot_change_after_historical_attention`, `...test_attention_type_with_active_subattentions_cannot_be_deactivated` |
| CAT-05 Vacío, longitud máxima y máxima+1, relación inactiva, sin guardado parcial | `common.test_requirements.FieldLengthAndRelationTests`, `*_crud.*test_required_fields_are_validated` |
| CAT-06 Cancelar no modifica; error controlado; éxito solo tras guardar | `*_crud.*test_deactivate_rejects_get_requests`, `accounts.test_role_crud.RoleCrudAdminTests.test_deactivate_with_outdated_count_is_not_applied`, `configuration.test_item_crud.ItemDeactivationWithActivitiesTests.test_outdated_count_does_not_deactivate`. Botón Cancelar del diálogo SweetAlert2: **manual** |
| INT-03 Auditoría con usuario, fecha, origen, acción, antes y después | `accounts.test_audit_trail.FieldLevelAuditTests`, `accounts.test_role_crud.RoleCrudAdminTests.test_update_audits_previous_and_new_permissions_and_scope`, `configuration.test_item_crud.ItemCrudAdminTests.test_update_persists_changes_and_audits_only_what_changed`, `configuration.tests.CatalogAuditAndExportCleanupTests` |

### Listados, búsqueda y exportación (A2, B13)

| Requisito | Pruebas |
| --------- | ------- |
| UX-01 Búsqueda parcial sin distinguir mayúsculas y filtros combinados | `*_crud.*test_search_is_partial_and_case_insensitive*`, `*_crud.*test_status_filter_combines_with_search` |
| B1 / UX-01 Búsqueda en tiempo real que conserva los filtros en la URL, el paginador y la exportación | `common.test_live_search.LiveSearchMarkupTests`. Espera de 400 ms, cancelación, «Buscando…» y error de red: **manual** en el navegador |
| A2 Advertir cambios sin guardar al cambiar la delegación activa | `common.test_live_search.DelegationSwitchWarningTests` (script y selector). Confirmación SweetAlert2 y cancelación: **manual** |
| UX-02 Paginación de 10, filtros al paginar, página ajustada | `*_crud.*test_pagination_is_ten_per_page_and_keeps_filters`, `*_crud.*test_out_of_range_page_is_clamped`, `configuration.tests.CatalogAuditAndExportCleanupTests.test_out_of_range_page_is_clamped` |
| UX-03 Exportar a Excel: todas las páginas, filtros, columnas, sin secretos ni campos internos | `accounts.test_delegation_crud.DelegationCrudAdminTests.test_export_*`, `accounts.test_user_crud.UserCrudAdminTests.test_export_*`, `accounts.test_official_crud.OfficialExportTests`, `accounts.test_role_crud.RoleCrudAdminTests.test_export_*`, `configuration.test_item_crud.ItemCrudAdminTests.test_export_*`, `configuration.tests.AttentionCatalogCrudTests.test_*excel_export*`, `common.tests` |
| Estados de carga, vacío, sin coincidencias y error | `common.test_frontend.MaintainerLayoutTests`, `*_crud.*test_empty_states_distinguish_no_matches`, `common.test_frontend.ErrorPageTests` |
| Campos obligatorios marcados, Guardar y Cancelar | `common.test_frontend.MaintainerLayoutTests.test_forms_mark_required_fields_and_show_loading_while_saving` |
| Maquetas identificadas como datos de demostración | `common.test_frontend.MaintainerLayoutTests.test_mockups_are_clearly_identified_as_demo_data`, `common.tests.ExportLabelTests` |
| UX-04 Contexto de delegación, usuario y rol con texto e ícono | `common.test_frontend.HeaderContextBadgeTests`, `accounts.test_seed_demo.SeedDemoDataTests.test_header_shows_delegation_and_role` |
| UX-04 Normas gráficas y aspecto de SweetAlert2 | **manual** (revisión visual contra laserena.cl/conocenos/normas-graficas) |
| UX-05 Navegación con teclado, foco y etiquetas | Parcial: `common.test_frontend.MaintainerLayoutTests.test_every_maintainer_marks_its_own_sidebar_link_as_current` (aria-current). Recorrido con teclado y contraste: **manual** |
| UX-06 Chrome y Edge, escritorio y móvil | **manual** |

### Ingreso de atención y seguridad (A2, B8, B14)

| Requisito | Pruebas |
| --------- | ------- |
| ACT-01 Registro con identificador, autor y delegación de la sesión | `activities.test_social_attention.SocialAttentionEntryTests.test_post_creates_recipient_and_persists_attention_with_server_context` |
| ACT-02 / C6 Campos obligatorios, catálogos inactivos, delegación fuera de ámbito | `activities.test_social_attention.SocialAttentionEntryTests`, `common.test_requirements.FieldLengthAndRelationTests.test_attention_entry_rejects_an_inactive_attention_type_with_an_active_subattention` |
| ACT-04 / ACT-05 Límite de tres gestiones; sub de otro tipo rechazada | `activities.test_social_attention.SocialAttentionRulesTests`, `...SocialAttentionEntryTests.test_post_rejects_subattention_from_another_type` |
| ACT-06 Doble envío: una sola atención (también simultáneo) | `activities.test_attention_submission.AttentionSubmissionTests` |
| C6 Mostrar el identificador y consultar la atención registrada; cancelar no crea registros | `activities.test_attention_submission.AttentionSubmissionTests.test_after_saving_the_entry_page_links_to_the_registered_attention`, `activities.test_attention_submission.AttentionDetailTests`, `activities.test_social_attention.SocialAttentionEntryTests.test_opening_form_does_not_create_recipient_or_attention` |
| SEG-01 Identificador de otra delegación: denegado y trazable | `accounts.test_audit_trail.OutOfScopeAccessAuditTests`, `*ScopeTests`, `activities.test_attention_submission.AttentionDetailTests.test_attention_of_another_delegation_is_hidden_and_the_attempt_audited` |
| SEG-02 Autorización por operación, sin escalamiento (403 con auditoría) | `common.test_requirements.OperationAuthorizationTests`, `accounts.test_user_crud.UserCrudAdminTests.test_actor_without_role_management_permission_cannot_assign_privileged_role`, `accounts.test_role_crud.RolePermissionTests`, `accounts.test_official_crud.OfficialRoleRulesTests.test_privileged_role_without_role_permission_is_denied_with_403_and_audited` |
| SEG-03 Entradas adversas tratadas como datos | `common.test_requirements.AdverseSearchInputTests`, `accounts.test_role_crud.RoleCrudAdminTests.test_export_stores_formula_like_values_as_text` |
| SEG-04 Contraseñas con hash, nunca en exportaciones ni auditoría | `accounts.test_user_crud.UserCrudAdminTests.test_export_has_no_passwords_and_includes_all_filtered_rows`, `accounts.test_audit_trail.FieldLevelAuditTests.test_user_update_records_profile_roles_and_password_change_without_its_value`, `accounts.test_password_reset.PasswordResetCodeTests.test_issue_stores_only_the_hash` |

### Fuera del alcance de estas pruebas automatizadas

Las pruebas de rendimiento y estrés (B16, B18) y las de despliegue (B17) requieren el entorno de
prueba acordado y se registran aparte con sus métricas reales. Los casos de agenda, evidencias,
cálculos y tableros (B7 a B12) corresponden a funciones que aún no forman parte del incremento y
quedan como no ejecutados con esa justificación.
