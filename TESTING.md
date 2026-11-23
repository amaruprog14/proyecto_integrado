# Plan e informe de pruebas del SGR

Plan de pruebas e informe de resultados del Sistema de Gestión de Resultados para la **evaluación
sumativa III**. Reúne qué se prueba, cómo se ejecuta, la trazabilidad requisito → prueba, los
resultados obtenidos contra los esperados, sus discrepancias y las recomendaciones.

**Regla de este documento:** un resultado «obtenido» solo se registra si la prueba se ejecutó para
este informe (fecha, comando y commit en la [ficha de ejecución](#6-ficha-de-ejecución-del-protocolo)).
Un caso manual que no se ejecutó figura como **Pendiente de ejecución manual**, nunca como aprobado.

**Seguimiento posterior.** Las cifras de las secciones 1 a 11 corresponden a sus fechas originales. Las correcciones de RC-08 y RC-16 se registran en la [reevaluación del 23 de noviembre](#reevaluacion-rc08-rc16). El [balance acumulado y los casos pendientes](#verificacion-pendientes-local) incorporan las verificaciones locales posteriores. El [corte de la evaluación semestral](#alcance-semestral) aplica la aclaración del equipo sobre HTTP.

## 1. Alcance y versión

| Dato de control | Valor |
| --- | --- |
| Sistema | SGR, Sistema de Gestión de Resultados de la Municipalidad de La Serena (prototipo académico, datos ficticios) |
| Commit evaluado | `07064bd` (`main` con el merge del PR #58). Es el mismo commit en las corridas del 18-11-2026 y del 22-11-2026; `scripts/prueba_carga.py` y este documento están sin commitear en la rama `docs/plan-y-resultados-de-pruebas` |
| Fechas y zona horaria | 18-11-2026 (primera corrida) y 22-11-2026 (reejecución), America/Santiago |
| Ejecutor | Sebastián Alzamora (equipo), con ejecución asistida por Claude Code |
| Entorno de las pruebas automatizadas | LOCAL/QA: Windows 11, Python 3.14.7, Django 5.2.17, **MySQL 8.4.7** (WAMP); base de pruebas aislada `test_<DB_NAME>` |
| Servidor AWS (34.201.192.78) | Solo verificaciones de lectura (GET) el 18-11-2026 a las 13:01; el commit desplegado no se pudo comprobar. Las cuentas `verificadorA`, `delegadoA` y `coordinadorA` se crearon a mano en AWS el 22-11-2026 (sección 6.3). La prueba de carga y los casos funcionales en AWS quedan pendientes |
| Guía de Evaluación 3 (E3) | `III_Evaluacion_Proyecto_Integrado_SGR.pdf` (evaluación sumativa N.º 3, entrega el 27-11-2026): alcance funcional mínimo, reglas del cliente, tope de cumplimiento de 120 % y formato mínimo de cada caso de prueba (Actividad 4) |
| Guía del proyecto (S1) | `Guia_Proyecto_Software_SGR_Alumnos.pdf`, versión 1.0 del 31-08-2026: RF-001 a RF-038, RNF-001 a RNF-018, RN-001 a RN-013, CA-01 a CA-10, HU-01 a HU-31 |
| Plan de pruebas (PP) | `Requisitos_y_Plan_Pruebas_Segunda_Evaluacion_SGR.pdf`: bloques B1 a B21, **84 casos** (ACC, ADM, CAT, PAR, ACT, EVI, AGE, CAL, TAB, UX, SEG, INT, REN, AWS) y lotes de cálculo CAL-A a CAL-F |
| Matriz de la institución | `Copia INACAP 3ER COMPAÑIAS MATRIZ SGR TRIMESTRE 2026 REV.xlsx` (fuera del repositorio; se cita por hoja y celda) |

El PP se redactó para la segunda evaluación; aquí se reutiliza su catálogo completo porque hoy
están implementadas también las funciones que entonces quedaban fuera (agenda, evidencias,
cálculos, tableros, B7 a B12). Los identificadores RF, RNF, RN, CA y HU son los de S1; los casos
ACC…AWS son los de PP; las reglas del cliente de E3 se trazan en la sección 4.12 (RC-01 a RC-15).

## 2. Cómo ejecutarlas

Con el entorno virtual activo y el `.env` configurado (ver `README.md`):

```bash
python manage.py test --noinput            # suite completa (todas las apps, incluida common)
python manage.py test accounts             # una app
python manage.py test accounts.test_role_crud.GlobalAdministratorProtectionTests   # una clase
python manage.py test analytics.test_tube_cancellations.TubeCancellationTests.test_exact_cal_c_batch_with_cancellations
python manage.py test --keepdb             # reutiliza la base de pruebas entre ejecuciones
python manage.py makemigrations --check --dry-run   # no deben quedar migraciones pendientes
```

- **Motor.** Las pruebas usan el motor del proyecto, **MySQL**, con la conexión del `.env`. Django
  crea `test_<DB_NAME>`, aplica todas las migraciones y la elimina al terminar: no toca los datos de
  desarrollo. `DB_USER` necesita `CREATE` y `DROP`. La conexión usa `STRICT_TRANS_TABLES`, por lo
  que MySQL rechaza valores más largos que la columna en vez de truncarlos.
- **`--noinput`.** Si una ejecución anterior se interrumpió y quedó `test_<DB_NAME>`, Django la
  reemplaza sin preguntar.
- **Servidor MySQL encendido.** Con WAMP detenido la suite termina de inmediato con
  `OperationalError: (2002, "Can't connect to server on 'localhost' (10061)")`; no es un fallo de las
  pruebas (incidencia del 22-11-2026, sección 6.5).
- **Ejecución en serie.** `--parallel` clona la base de pruebas con `mysqldump`; si `mysqldump` no
  está en el `PATH` (caso del equipo de este informe), ejecutar en serie. WAMP lo trae en
  `C:\wamp64\bin\mysql\mysql8.4.7\bin`; para usar `--parallel` basta agregar esa carpeta al `PATH`
  de la sesión (`$env:PATH += ";C:\wamp64\bin\mysql\mysql8.4.7\bin"`). No lanzar dos ejecuciones a
  la vez contra el mismo servidor: comparten `test_<DB_NAME>` y fallan con tablas o columnas
  inexistentes y bloqueos `1213 Deadlock found`.
- **SQLite.** Sirve para una revisión rápida, pero cuatro pruebas de concurrencia exigen
  `SELECT FOR UPDATE` y se **omiten** en SQLite (`skipUnlessDBFeature("has_select_for_update")`):
  `activities.test_activity_completion.ActivityArchiveRealtimeTests.test_parallel_activity_creations_and_edits`,
  `activities.test_case_follow_up.CaseConcurrencyTests.test_simultaneous_third_and_fourth_management_only_create_one`,
  `activities.test_gifts.GiftConcurrencyTests.test_two_simultaneous_submissions_only_create_one_registration` y
  `common.test_period_concurrency.PeriodConcurrencyTests.test_registration_waits_for_close_and_rechecks_status`.
  En MySQL se ejecutan; la conformidad se declara con MySQL.
- **Sin red ni correo real.** Los correos usan el backend de memoria de Django y las pruebas de
  WebSocket usan la capa de canales en memoria.
- **Caché.** No se revierte con las transacciones: las pruebas de exportación limpian sus claves de
  espera por usuario antes y después de cada caso, sin desactivar el límite de 30 segundos.
- **WebSocket.** `python manage.py test activities.test_realtime common.test_realtime accounts.test_evaluation_admin`
  comprueba la matriz de cuentas, módulos y ámbitos de los avisos en tiempo real.

## 3. Organización de los módulos de prueba

`find . -name "test*.py"` (sin el entorno virtual) devuelve **61 archivos**: 57 con pruebas,
`agenda/tests.py` y `analytics/tests.py` vacíos, y dos módulos de apoyo que no contienen pruebas
(`common/testing_edit.py` y `common/testing_seed.py`).

| Módulo | Qué cubre |
| --- | --- |
| `accounts/test_absence_seed_migration.py` | Ida y vuelta de la migración `accounts/0015`: permisos de Ausencias en los roles de la semilla y reversión conservadora |
| `accounts/test_audit_trail.py` | Auditoría por campo (antes y después) y accesos fuera de ámbito con 404 y registro |
| `accounts/test_auth_flows.py` | Login, rutas protegidas, permisos por rol en el servidor, recuperación de contraseña por enlace y validador de composición |
| `accounts/test_authorization.py` | Perfil propio y autorización administrativa sin escalamiento (SEG-02) |
| `accounts/test_client_accounts_territories.py` | Cuentas de cliente del portal y territorios: CRUD, duplicados, ámbito por delegación y conflictos de edición |
| `accounts/test_delegation_context.py` | Delegación activa: selector solo con autorizadas, sesión y efecto en listas, exportación y formularios |
| `accounts/test_delegation_crud.py` | CRUD de Delegaciones, búsqueda, paginación, exportación, ámbito y permisos |
| `accounts/test_evaluation_admin.py` | Cuenta de evaluación limitada a Las Compañías: CRUD, aislamiento de otra delegación, Excel, WebSocket y preparación idempotente |
| `accounts/test_login_security.py` | Bloqueo temporal por intentos fallidos y auditoría de ingreso, fallo, bloqueo y cierre |
| `accounts/test_official_completion.py` | Funcionarios: detalle, archivado POST/CSRF, ámbito, edición simultánea, último administrador y WebSocket tras commit/rollback |
| `accounts/test_official_crud.py` | Funcionarios: CRUD, RUT, exportación y reglas de roles privilegiados |
| `accounts/test_official_delegations.py` | Código de delegación y delegaciones autorizadas del funcionario |
| `accounts/test_own_account.py` | Cambio de contraseña con sesión y edición de nombre y correo propios |
| `accounts/test_profile_photo.py` | Foto de perfil: recorte, validación de archivos y sesión propia |
| `accounts/test_role_crud.py` | CRUD de Roles, último Administrador global, permisos privilegiados y exportación segura |
| `accounts/test_seed_demo.py` | Semilla `seed_demo`: 2.000 registros, planes con pesos reales, permisos por rol, repetibilidad y protecciones |
| `accounts/test_user_crud.py` | CRUD de Usuarios, contraseñas, ámbito, exportación y último Administrador global |
| `accounts/tests.py` | Rutas de autenticación y mantenedores, admin de cargos e inline de actividades |
| `activities/test_activity_completion.py` | Actividades: modal, edición simultánea, historial, archivado y restauración, períodos cerrados y concurrencia |
| `activities/test_attention_submission.py` | Ingreso de atención: doble envío (repetido y con una carrera simulada con `mock` en la base), folio y detalle con ámbito |
| `activities/test_case_follow_up.py` | Seguimiento de casos sociales: reasignación, cierre, portal, correo fallido, concurrencia de la cuarta gestión y migración de folios |
| `activities/test_client_portal.py` | Portal de clientes: solicitudes propias, aislamiento entre clientes, respuesta del personal y foto privada |
| `activities/test_evidence.py` | Evidencias: etapas, aprobación única, rechazo con motivo, anulación y alertas a revisores |
| `activities/test_gifts.py` | Campañas de regalos: inscripción, duplicados por RUT, entrega, anulación, ámbito territorial, Excel y concurrencia |
| `activities/test_office_letters.py` | Oficina de Partes: cartas, número, ámbito, hitos, agenda y edición simultánea |
| `activities/test_realtime.py` | WebSocket de Actividades: avisos solo a lectores autorizados, revocación y orígenes ajenos |
| `activities/test_social_attention.py` | Reglas de atención social: tipo/subatención, límite de tres gestiones, códigos y descripción de 300 caracteres |
| `activities/tests.py` | Rutas de Actividades e ingreso de atención y ámbito del admin |
| `agenda/test_commitments.py` | Compromisos: creación desde caso y actividad, alerta de vencimiento, cancelación con justificación, reasignación auditada y atraso |
| `agenda/test_internal_comments.py` | Comentarios internos: escape de contenido, CSRF, autor y ámbito |
| `agenda/tests.py` | Vacío |
| `analytics/test_indicator_support.py` | Respaldo congelado («¿Qué respaldó este resultado?»): filas por alcance, tramos, anulaciones, bloqueo al cerrar y tope del resultado final |
| `analytics/test_measurement_configuration.py` | Planes de medición: pesos que suman 100, metas positivas, revisiones por vigencia, reapertura y auditoría de parámetros |
| `analytics/test_measurement_rules.py` | Días computables (91 días, 61,54 %), ausencias, tramos de cargo, «Pendientes en tubo» y listado e historial de Ausencias |
| `analytics/test_migration_reversal.py` | Reversión de `analytics/0006` con conversión de datos y vuelta adelante |
| `analytics/test_partial_plan_summary.py` | Resumen y Excel cuando el último tramo de cargo no tiene plan |
| `analytics/test_performance_calculator.py` | Calculador: lotes CAL-A, CAL-B, CAL-D, CAL-E y CAL-F, pesos reales, tope, evidencia aprobada y anulación |
| `analytics/test_performance_panel.py` | Mi desempeño, tablero de delegación, vista por cargo, exportaciones, alertas y congelamiento |
| `analytics/test_score_adjustments.py` | Reclamos y felicitaciones: validación, valores por versión, límite de tres, piso 0 y segregación |
| `analytics/test_score_role_migration.py` | Reversión conservadora de `analytics/0008` |
| `analytics/test_tube_cancellations.py` | Lote CAL-C exacto y cancelados con justificación en «Soluciones de ingresos al tubo» |
| `analytics/tests.py` | Vacío |
| `common/test_chilean_rut.py` | Validación y normalización de RUT |
| `common/test_description_limit.py` | Límites de descripción, nombres, usuarios, teléfonos e identificadores inválidos |
| `common/test_error_pages.py` | Páginas 400/404/500 sin detalles internos y archivos de `/media/` |
| `common/test_frontend.py` | Plantilla común, campos obligatorios, estados vacíos, menú por permisos y distintivo de contexto |
| `common/test_list_state.py` | Estado de listados (filtros, orden, página) y espera de 30 s por exportación |
| `common/test_live_search.py` | Búsqueda en tiempo real y aviso de cambios sin guardar al cambiar de delegación |
| `common/test_maintainer_consistency.py` | Contratos comunes de los mantenedores y longitudes sin truncamiento |
| `common/test_modal_feedback.py` | Confirmaciones de los modales de creación y edición en todos los CRUD |
| `common/test_period_concurrency.py` | Registro contra un período cerrado y espera del cierre simultáneo (`SELECT FOR UPDATE`) |
| `common/test_persistent_maintainers.py` | Catálogos persistentes, grupos, períodos y generación atención–actividad |
| `common/test_realtime.py` | Matriz WebSocket de todos los módulos y cuentas |
| `common/test_requirements.py` | 403 con auditoría por operación, longitudes, relaciones inactivas y entradas adversas |
| `common/testing_edit.py` | Apoyo: obtiene la revisión de edición de un formulario modal (sin pruebas) |
| `common/testing_seed.py` | Apoyo: fixture histórica pequeña para pruebas de permisos y UI (sin pruebas) |
| `common/tests.py` | Generación de `.xlsx` sin fórmulas y etiquetas de exportación |
| `configuration/test_audit.py` | Bitácora general: filtros, campos reservados y mutaciones denegadas |
| `configuration/test_item_crud.py` | CRUD de Ítems, código, permisos y desactivación con actividades |
| `configuration/tests.py` | Tipo de Atención, Sub Atención, períodos y auditoría por campo de catálogos |
| `sgr_api/tests.py` | API REST: tokens, bloqueo, revocación, períodos, delegación, conciliación, tope y piso |

## 4. Matriz requisito → prueba

Las pruebas se citan como `módulo.Clase.método`. Estado de **cobertura**: **Cubierto** (lo exigido
por el caso tiene prueba automatizada), **Parcial** (parte automatizada y parte manual o sin
implementar) o **Sin prueba**. Toda prueba citada se ejecutó y pasó en la corrida de la
[ficha](#6-ficha-de-ejecución-del-protocolo); lo manual queda en la [ficha de casos manuales](#62-ficha-de-casos-manuales).

### 4.1 Acceso y recuperación (B4)

| Caso | Requisito | Prueba | Cobertura |
| --- | --- | --- | --- |
| ACC-01 | RNF-004, HU-26 | `accounts.test_auth_flows.ProtectedRouteTests.test_menu_only_lists_permitted_sections`, `common.test_frontend.SidebarPermissionTests.test_sidebar_only_lists_screens_the_profile_can_open`, `accounts.test_evaluation_admin.EvaluationAdminTests.test_login_exact_permissions_single_delegation_and_global_preserved`. Ingreso real con cada rol en AWS: manual (M-01) | Parcial |
| ACC-02 | RNF-004 | `accounts.test_auth_flows.LoginTests.test_wrong_credentials_show_a_generic_error_and_create_no_session`, `...LoginTests.test_empty_fields_are_reported_per_field`, `...LoginTests.test_inactive_accounts_cannot_log_in`, `accounts.test_login_security.LoginLockoutTests.test_account_is_locked_after_the_maximum_and_rejects_even_the_right_password` | Cubierto |
| ACC-03 | RNF-004 | `accounts.test_auth_flows.ProtectedRouteTests.test_logout_ends_access_and_pages_are_not_cached`, `...ProtectedRouteTests.test_anonymous_users_are_sent_to_login`. Botón Atrás del navegador: manual (M-02) | Parcial |
| ACC-04 | Complemento | `accounts.test_auth_flows.PasswordRecoveryFlowTests.test_response_is_the_same_for_existing_and_unknown_emails`, `...test_request_takes_the_same_minimum_time_with_and_without_account`, `...test_inactive_account_receives_no_link` | Cubierto |
| ACC-05 | Complemento | `accounts.test_auth_flows.PasswordRecoveryFlowTests.test_valid_token_opens_the_new_password_form`, `...test_invalid_token_shows_a_clear_message_and_a_new_request_link`, `...test_expired_token_is_rejected`, `...test_used_token_cannot_be_reused`, `...test_a_second_request_waits_before_sending_another_link`. Se usa enlace con token en vez de código de seis dígitos (ver D-06) | Cubierto (adaptado) |
| ACC-06 | Complemento | `accounts.test_auth_flows.PasswordRecoveryFlowTests.test_weak_or_mismatched_passwords_are_rejected`, `...test_valid_password_replaces_the_old_one_and_is_audited` (también comprueba que la respuesta carga SweetAlert2), `accounts.test_auth_flows.PasswordCompositionValidatorTests.test_requires_uppercase_lowercase_and_digit`. Aspecto y texto del diálogo de confirmación: manual (M-03) | Parcial |

### 4.2 Organización, perfiles y catálogos (B5, B6)

| Caso | Requisito | Prueba | Cobertura |
| --- | --- | --- | --- |
| ADM-01 | RF-001 | `accounts.test_delegation_crud.DelegationCrudAdminTests.test_create_persists_and_generates_code`, `...test_update_persists_changes_and_keeps_code`. Que la delegación nueva aparezca de inmediato en filtros y asignaciones: sin prueba propia | Parcial |
| ADM-02 | RF-001 | `accounts.test_delegation_crud.DelegationCrudAdminTests.test_duplicate_name_is_rejected_case_insensitively`, `...test_deactivate_is_logical_and_keeps_history`, `...test_deactivate_does_not_remove_delegation_even_with_relations` | Cubierto |
| ADM-03 | RF-002 | `accounts.test_user_crud.UserCrudAdminTests.test_create_user_with_official_profile`, `...test_status_inactive_deactivates_user_and_profile`, `...test_status_suspended_blocks_authentication`, `accounts.test_official_crud.OfficialCrudTests.test_create_official_with_account_is_atomic_and_linked` | Cubierto |
| ADM-04 | RF-002 | `accounts.test_role_crud.RoleCrudAdminTests.test_update_audits_previous_and_new_permissions_and_scope`, `...test_deactivate_role_with_active_officials_warns_and_audits`, `accounts.test_role_crud.RolePermissionTests.test_deactivating_a_role_removes_the_access_it_granted`, `accounts.test_role_crud.GlobalAdministratorProtectionTests.test_last_global_administrator_cannot_be_deactivated` | Cubierto |
| ADM-05 | RF-003 | `analytics.test_performance_calculator.ProgressRulesTests.test_items_outside_the_plan_and_revisions_use_the_ruling_version`, `analytics.test_measurement_configuration.MeasurementConfigurationTests.test_revision_applies_to_existing_activities_by_effective_date`, `analytics.test_measurement_rules.MeasurementRulesTests.test_activity_items_follow_historical_position` | Cubierto |
| ADM-06 | RNF-005, CA-07 | `accounts.test_delegation_context.ActiveDelegationContextTests.test_single_delegation_does_not_render_selector`, `...test_user_cannot_select_an_active_but_unauthorized_delegation`, `...test_user_list_and_export_follow_the_selected_delegation`, `common.test_frontend.HeaderContextBadgeTests.test_header_shows_user_role_and_delegation_with_text_and_icon` | Cubierto |
| CAT-01 | RF-003, RF-004 | `configuration.test_item_crud.ItemCrudAdminTests.test_update_persists_changes_and_audits_only_what_changed`, `...test_deactivate_is_logical_and_audited`, `configuration.test_item_crud.ItemDeactivationWithActivitiesTests.test_confirmed_count_deactivates_and_audits_it` | Cubierto |
| CAT-02 | RF-004 | `configuration.tests.AttentionCatalogCrudTests.test_create_attention_type_generates_code_and_audit_entry`, `...test_attention_type_duplicate_name_is_rejected_case_insensitively`, `...test_deactivation_is_logical_and_retains_audit_history` | Cubierto |
| CAT-03 | RF-004 | `configuration.tests.AttentionCatalogCrudTests.test_subattention_creation_requires_an_active_attention_type`, `...test_subattention_create_saves_association_and_generated_code`, `...test_subattention_name_must_be_unique_within_attention_type`, `...test_subattention_cannot_be_activated_while_parent_is_inactive` | Cubierto |
| CAT-04 | RF-004, RF-038 | `configuration.tests.AttentionCatalogCrudTests.test_subattention_type_association_cannot_change_after_historical_attention`, `...test_attention_type_with_active_subattentions_cannot_be_deactivated`, `common.test_persistent_maintainers.PersistentMaintainerTests.test_activity_catalog_routes_manage_hierarchy_and_preserve_references`. Cambiar la etiqueta de un tipo ya usado y consultar el registro histórico: sin prueba propia | Parcial |
| CAT-05 | RNF-007 | `common.test_requirements.FieldLengthAndRelationTests.test_maximum_length_is_accepted_and_one_more_is_rejected`, `...test_username_length_is_validated_on_the_server`, `...test_inactive_role_cannot_be_assigned`, `common.test_maintainer_consistency.MaintainerDataTests.test_lengths_are_enforced_without_truncation`, `common.test_description_limit.DescriptionLimitFormTests.test_description_limits_match_browser_and_server` | Cubierto |
| CAT-06 | Complemento | `accounts.test_role_crud.RoleCrudAdminTests.test_deactivate_with_outdated_count_is_not_applied`, `configuration.test_item_crud.ItemDeactivationWithActivitiesTests.test_outdated_count_does_not_deactivate`, `common.test_modal_feedback.ModalFeedbackTests.test_modal_get_and_invalid_post_preserve_previous_feedback_and_field_errors`. Botón Cancelar de SweetAlert2: manual (M-04) | Parcial |

### 4.3 Períodos, metas y ponderaciones (B7)

| Caso | Requisito | Prueba | Cobertura |
| --- | --- | --- | --- |
| PAR-01 | RF-005, HU-28 | `configuration.tests.PeriodValidationTests.test_period_end_date_before_start_date_is_rejected`, `...test_period_overlapping_existing_one_is_rejected`, `analytics.test_performance_calculator.ExpectedGoalAndTrafficLightTests.test_guide_example_of_computable_days` | Cubierto |
| PAR-02 | RF-006, RN-001 | `analytics.test_measurement_configuration.MeasurementConfigurationTests.test_publication_requires_weights_to_add_exactly_one_hundred`, `...test_item_form_rejects_negative_and_over_one_hundred_weights`, `...test_maintainers_and_publication_validate_base_and_inherited_weights`. La «excepción formalmente configurada» de RN-001 no está implementada | Parcial |
| PAR-03 | RF-007, RN-002 | `analytics.test_measurement_configuration.MeasurementConfigurationTests.test_item_form_rejects_zero_and_negative_goals`, `analytics.test_performance_calculator.ProgressRulesTests.test_invalid_goal_does_not_divide_by_zero`, `...ProgressRulesTests.test_percentage_item_uses_done_commitments_cal_f` (fórmula porcentual). Rechazo de un ítem porcentual sin fórmula: sin prueba propia | Parcial |
| PAR-04 | RF-007, RF-038, CA-09 | `analytics.test_performance_panel.PerformancePanelTests.test_closed_period_keeps_goal_weight_and_total_light_after_later_plan_changes`, `...test_closing_freezes_weighted_and_tube_progress_and_later_changes_do_not_alter_it`, `analytics.test_performance_calculator.ProgressRulesTests.test_closed_period_percentage_does_not_change_after_its_end` | Cubierto |
| PAR-05 | RN-013, CA-10 | `analytics.test_measurement_configuration.MeasurementConfigurationTests.test_reopen_requires_global_permission_and_keeps_dates`, `common.test_period_concurrency.PeriodConcurrencyTests.test_registration_rejects_a_closed_period`, `activities.test_activity_completion.ActivityCompletionTests.test_closed_period_prevents_edit_archive_and_restore`, `analytics.test_performance_panel.PerformancePanelTests.test_reclosing_after_reopening_replaces_the_frozen_result` | Cubierto |
| PAR-06 | RNF-015, HU-25 | `analytics.test_measurement_configuration.MeasurementConfigurationTests.test_parameter_changes_are_visible_with_before_after_and_account_in_audit`, `analytics.test_indicator_support.IndicatorSupportTests.test_final_score_cap_is_configurable_used_and_frozen`, `analytics.test_performance_calculator.KnownCaseTests.test_coordinator_compliance_is_capped_at_the_configured_maximum`. Prueban que los parámetros se editan sin cambiar código, quedan auditados y que el tope se aplica; el efecto de `collective_threshold` no se prueba porque ningún cálculo lo usa (D-09) | Parcial |

### 4.4 Actividades, atención social y evidencias (B8, B9)

| Caso | Requisito | Prueba | Cobertura |
| --- | --- | --- | --- |
| ACT-01 | RF-009, CA-01 | `activities.test_activity_completion.ActivityCompletionTests.test_editor_has_complete_create_detail_edit_modal_flow_without_archival`, `...test_manual_registration_delegation_is_scoped_and_retained`, `analytics.test_performance_calculator.ProgressRulesTests.test_only_approved_evidence_counts_and_annulment_reverts` | Cubierto |
| ACT-02 | RF-010 | `activities.test_activity_completion.ActivityCompletionTests.test_invalid_required_date_type_and_foreign_relations_do_not_write`, `...test_manual_activity_checks_area_chain_and_retains_historical_values`, `common.test_description_limit.OfficialFieldRulesTests.test_phone_formats` | Cubierto |
| ACT-03 | RF-008, HU-06 | `analytics.test_performance_panel.PerformancePanelTests.test_selector_shows_goals_and_progress_of_each_period_with_plan`, `...test_panel_shows_the_delegation_and_defaults_to_the_current_period`, `...test_link_to_activities_lists_exactly_the_progress_of_the_item` | Cubierto |
| ACT-04 | RF-015, RN-012, CA-04 | `activities.test_social_attention.SocialAttentionRulesTests.test_limit_of_three_attentions_per_case`, `activities.test_social_attention.SocialAttentionEntryTests.test_post_reuses_existing_recipient_by_identifier`, `activities.test_case_follow_up.CaseFollowUpTests.test_presential_reuses_person_and_activation_grants_only_own_history` | Cubierto |
| ACT-05 | RF-015, RN-012, CA-04 | `activities.test_social_attention.SocialAttentionEntryTests.test_post_enforces_maximum_of_three_attentions_for_case`, `...test_post_rejects_subattention_from_another_type`, `activities.test_case_follow_up.CaseConcurrencyTests.test_simultaneous_third_and_fourth_management_only_create_one`. Limpieza visual de la subatención al cambiar el tipo: manual (M-05) | Parcial |
| ACT-06 | RF-009, RNF-007 | `activities.test_attention_submission.AttentionSubmissionTests.test_repeated_submission_creates_a_single_attention`, `...test_simultaneous_submission_is_resolved_by_the_database` (carrera simulada con `mock`: comprueba la restricción única y la recuperación), `...test_after_saving_the_entry_page_links_to_the_registered_attention` | Cubierto |
| EVI-01 | RF-011, RN-010, HU-10 | `activities.test_activity_completion.ActivityArchiveRealtimeTests.test_parallel_activity_creations_and_edits` (dos actividades creadas a la vez reciben códigos distintos). Inmutabilidad del código de actividad: sin prueba propia | Parcial |
| EVI-02 | RF-012, HU-09 | `activities.test_evidence.EvidenceTests.test_multiple_stages_share_the_activity_history_and_approve_once`, `...test_invalid_upload_is_atomic_and_closed_period_refuses_writes`, `activities.test_case_follow_up.CaseFollowUpTests.test_case_links_to_the_activity_evidence_only_when_authorized`. Autor, fecha y metadatos de carga: no se comprueban | Parcial |
| EVI-03 | RF-013, RF-014, CA-01 | `activities.test_evidence.EvidenceTests.test_multiple_stages_share_the_activity_history_and_approve_once`, `analytics.test_performance_calculator.ProgressRulesTests.test_second_approved_image_on_the_same_activity_does_not_duplicate_progress`, `analytics.test_performance_panel.PerformancePanelTests.test_result_changes_when_evidence_is_approved_and_not_when_rejected`. Registro de verificador, fecha y decisión en la auditoría: no se comprueba | Parcial |
| EVI-04 | RF-013, RF-014, CA-02 | `activities.test_evidence.EvidenceTests.test_author_cannot_review_and_rejection_requires_reason` (pide corrección con motivo), `analytics.test_performance_panel.PerformancePanelTests.test_result_changes_when_evidence_is_approved_and_not_when_rejected`. El recorrido rechazo → corrección → nueva carga → aprobación que puntúa una vez no se hace de extremo a extremo por la interfaz | Parcial |
| EVI-05 | RF-022, RN-009 | `activities.test_evidence.EvidenceTests.test_annulment_keeps_review_and_photos_and_updates_progress_once`, `...test_annulment_requires_an_approved_batch_permission_reason_and_open_period`, `analytics.test_indicator_support.IndicatorSupportTests.test_annulled_evidence_before_closing_is_not_in_the_support` | Cubierto |
| EVI-06 | RF-013, RNF-003, CA-08 | La revisión bloquea la fila con `select_for_update` (`activities/evidence.py`), pero no hay ninguna prueba automatizada de dos verificadores simultáneos | Sin prueba |

### 4.5 Agenda colectiva y alertas (B10, TAB-05, TAB-06)

| Caso | Requisito | Prueba | Cobertura |
| --- | --- | --- | --- |
| AGE-01 | RF-016, RF-017 | `agenda.test_commitments.CommitmentWorkflowTests.test_creation_from_activity_keeps_origin_and_rejects_a_past_due_date`, `...test_case_creation_measurement_scope_and_deadline_alert` | Cubierto |
| AGE-02 | RF-017 | `agenda.test_commitments.CommitmentWorkflowTests.test_creation_from_activity_keeps_origin_and_rejects_a_past_due_date` (fecha), `...test_internal_creation_validates_catalog_scope_and_reassignment_is_audited` (territorio). Sin responsable: sin prueba propia | Parcial |
| AGE-03 | RF-018, HU-13 | `agenda.test_commitments.CommitmentWorkflowTests.test_case_creation_measurement_scope_and_deadline_alert` (Realizado una sola vez con historial), `...test_cancelling_with_justification_closes_the_commitment_and_its_alert`. No se recorre la matriz completa de transiciones ni una transición prohibida | Parcial |
| AGE-04 | RF-019, RF-037, CA-03 | `agenda.test_commitments.CommitmentWorkflowTests.test_overdue_and_late_completion_remain_visible_for_closed_period`, `...test_case_creation_measurement_scope_and_deadline_alert`. Motivo y enlace de la alerta y fecha anterior al vencimiento: no se comprueban | Parcial |
| AGE-05 | RF-020 | `analytics.test_performance_calculator.ProgressRulesTests.test_percentage_item_uses_done_commitments_cal_f`, `analytics.test_performance_panel.PerformancePanelTests.test_commitment_can_be_completed_without_rewriting_frozen_progress`. El compromiso cuenta al pasar a Realizado; no existe una «validación» separada del cierre | Parcial |
| AGE-06 | RF-017, RF-036, HU-15 | `agenda.test_commitments.CommitmentWorkflowTests.test_internal_creation_validates_catalog_scope_and_reassignment_is_audited`, `activities.test_case_follow_up.CaseFollowUpTests.test_reassignment_saves_responsible_and_history` | Cubierto |
| TAB-05 | RF-035, HU-24 | `agenda.test_internal_comments.InternalCommentTests.test_activity_comments_escape_content_require_csrf_and_preserve_author`, `...test_case_conversation_is_staff_only_and_scoped`. Consulta del comentario desde otra cuenta autorizada: no se comprueba | Parcial |
| TAB-06 | RF-037, HU-31 | `analytics.test_performance_panel.PerformancePanelTests.test_performance_alerts_follow_scope_and_resolve_without_duplicates`, `activities.test_evidence.EvidenceTests.test_upload_notifies_only_scoped_reviewers_and_review_resolves_alert`, `agenda.test_commitments.CommitmentWorkflowTests.test_cancelling_with_justification_closes_the_commitment_and_its_alert` | Cubierto |

### 4.6 Medición y semáforo (B11, lotes CAL)

| Caso | Requisito | Prueba | Cobertura |
| --- | --- | --- | --- |
| CAL-01 | RF-022, RF-023 | `analytics.test_performance_calculator.KnownCaseTests.test_guide_lots_cal_a_and_cal_b` (8/10 = 80 %, 10/20 = 50 %), `analytics.test_performance_calculator.ProgressRulesTests.test_second_approved_image_on_the_same_activity_does_not_duplicate_progress` | Cubierto |
| CAL-02 | RF-024, RN-005 | `analytics.test_performance_calculator.KnownCaseTests.test_guide_lots_cal_a_and_cal_b` (32 + 30 = 62; 60 + 30 = 90), `...KnownCaseTests.test_coordinator_compliance_is_capped_at_the_configured_maximum`, `...KnownCaseTests.test_apoyo_administrativo_with_real_goals_and_weights` | Cubierto |
| CAL-03 | RF-021, RN-006 | `analytics.test_tube_cancellations.TubeCancellationTests.test_exact_cal_c_batch_with_cancellations` (8/1/1 → 80 %, meta 80 % → 100 %), `analytics.test_performance_calculator.ProgressRulesTests.test_percentage_item_uses_done_commitments_cal_f`. Prueban el ítem porcentual personal; el resumen colectivo de la delegación (RF-021, 20 % no realizado) y el umbral colectivo 79,99 / 80 / 80,01 % no tienen prueba: el umbral se guarda, pero ningún cálculo lo usa (D-09) | Parcial |
| CAL-04 | RF-026, RN-007, CA-05 | `analytics.test_performance_calculator.ExpectedGoalAndTrafficLightTests.test_inclusive_count_of_cal_d_test_lot`, `...test_cal_d_complete_result_with_inclusive_count`, `...test_guide_example_of_computable_days`, `analytics.test_measurement_rules.MeasurementRulesTests.test_absences_clip_dates_and_preserve_guide_without_official` | Cubierto |
| CAL-05 | RF-027, RN-008, CA-05 | `analytics.test_performance_calculator.ExpectedGoalAndTrafficLightTests.test_cal_e_boundaries_are_evaluated_without_rounding`, `...test_presentation_rounding_is_half_up_and_internal_precision_is_kept`, `analytics.test_measurement_rules.MeasurementRulesTests.test_max_percentage_half_step_is_red_with_default_thresholds` | Cubierto |
| CAL-06 | RF-023, RF-026 | `analytics.test_performance_calculator.ProgressRulesTests.test_invalid_goal_does_not_divide_by_zero`, `analytics.test_tube_cancellations.TubeCancellationTests.test_all_cancelled_means_no_denominator`, `analytics.test_measurement_rules.MeasurementRulesTests.test_max_percentage_matches_excel_boundaries_and_empty_denominator`, `...test_zero_days_has_no_lights_and_is_excluded_from_team_average` | Cubierto |

### 4.7 Tableros, informes y ajustes (B12, B13)

| Caso | Requisito | Prueba | Cobertura |
| --- | --- | --- | --- |
| TAB-01 | RF-028, RF-029, CA-06 | `analytics.test_performance_panel.PerformancePanelTests.test_delegation_totals_reuse_individual_results_and_measured_activity_filter`, `...test_territorial_totals_reconcile_with_detail_and_keep_individual_progress`, `...test_delegation_dashboard_enforces_team_scope_and_primary_membership`, `sgr_api.tests.PerformanceAPITests.test_delegation_dashboard_and_api_use_the_floored_totals` | Cubierto |
| TAB-02 | RF-030, HU-19 | `analytics.test_performance_panel.PerformancePanelTests.test_recent_activity_uses_valid_records_and_counts_elapsed_calendar_days`, `...test_red_result_shows_last_record_and_days_without_records` | Cubierto |
| TAB-03 | RF-031, RF-038, HU-22 | `analytics.test_performance_panel.PerformancePanelTests.test_position_dashboard_filters_and_totals_follow_team_scope`, `...test_position_dashboard_uses_frozen_position_and_delegation_after_transfer`, `...test_closed_period_keeps_goal_weight_and_total_light_after_later_plan_changes` | Cubierto |
| TAB-04 | RF-025, RN-011 | `analytics.test_score_adjustments.ScoreAdjustmentTests.test_register_within_scope_and_only_approval_changes_result`, `...test_plan_revision_sets_value_by_date_and_rejected_entries_do_not_score`, `...test_three_approved_congratulations_and_final_cap_are_preserved_at_close`, `...test_who_records_cannot_review_own_record`, `sgr_api.tests.PerformanceAPITests.test_total_reconciles_with_base_and_score_adjustments`. Los valores (+10 / −20) siguen pendientes de validación (D-03) | Cubierto |
| UX-01 | RF-032, HU-29 | `accounts.test_delegation_crud.DelegationCrudAdminTests.test_search_is_partial_and_case_insensitive`, `...test_status_filter_combines_with_search`, `common.test_live_search.LiveSearchMarkupTests.test_search_in_the_url_keeps_filters_in_pages_and_export`, `common.test_persistent_maintainers.PersistentMaintainerTests.test_invalid_pagination_and_date_filters_do_not_fail`. Espera, cancelación y «Buscando…» en el navegador: manual (M-06) | Parcial |
| UX-02 | RF-032 | `accounts.test_delegation_crud.DelegationCrudAdminTests.test_pagination_keeps_selected_size_and_filters`, `...test_out_of_range_page_is_clamped`, `common.test_list_state.ListStateTests.test_changes_reset_page_and_empty_filters_clear_session` | Cubierto |
| UX-03 | RF-033, RNF-016, HU-20 | `accounts.test_delegation_crud.DelegationCrudAdminTests.test_export_contains_every_filtered_record_shown_across_pages`, `accounts.test_user_crud.UserCrudAdminTests.test_export_has_no_passwords_and_includes_all_filtered_rows`, `common.test_list_state.ListStateTests.test_export_inherits_filters_and_order_without_changing_page`, `common.tests.BuildXlsxTests.test_text_is_never_read_as_a_formula_and_control_characters_are_removed`, `analytics.test_performance_panel.PerformancePanelTests.test_personal_export_preserves_calculation_and_excludes_private_support` | Cubierto |
| UX-04 | RNF-011 | `common.test_frontend.HeaderContextBadgeTests.test_header_shows_user_role_and_delegation_with_text_and_icon`, `common.test_frontend.MaintainerLayoutTests.test_forms_mark_required_fields_and_show_loading_while_saving`, `common.test_error_pages.ErrorPagesWithoutDebugTests.test_unhandled_error_returns_500_without_internal_details`. Normas gráficas de La Serena: manual (M-07) | Parcial |
| UX-05 | RNF-012 | `common.test_frontend.MaintainerLayoutTests.test_every_maintainer_marks_its_own_sidebar_link_as_current`, `analytics.test_performance_panel.PerformancePanelTests.test_rows_show_text_and_icon_traffic_lights_and_link_to_source_activities`. Teclado, foco y contraste: manual (M-08) | Parcial |
| UX-06 | RNF-013 | Chrome y Edge, escritorio y móvil: manual (M-09) | Sin prueba |

### 4.8 Seguridad, integridad y auditoría (B14, B15)

| Caso | Requisito | Prueba | Cobertura |
| --- | --- | --- | --- |
| SEG-01 | RNF-005, CA-07 | `accounts.test_audit_trail.OutOfScopeAccessAuditTests.test_foreign_records_answer_404_and_leave_an_audit_entry`, `activities.test_activity_completion.ActivityCompletionTests.test_foreign_detail_update_archive_and_restore_are_rejected`, `activities.test_attention_submission.AttentionDetailTests.test_attention_of_another_delegation_is_hidden_and_the_attempt_audited`, `accounts.test_user_crud.UserScopeTests.test_export_only_includes_authorized_users` | Cubierto |
| SEG-02 | RNF-005, CA-07 | `common.test_requirements.OperationAuthorizationTests.test_every_operation_of_the_six_maintainers_is_denied_and_audited`, `accounts.test_authorization.AdministrativeAuthorizationTests.test_role_privilege_is_not_assignable_without_role_permission`, `accounts.test_auth_flows.ProtectedRouteTests.test_each_screen_requires_its_permission_and_logs_the_denial` | Cubierto |
| SEG-03 | RNF-007 | `common.test_requirements.AdverseSearchInputTests.test_adverse_search_terms_are_treated_as_data`, `accounts.test_role_crud.RoleCrudAdminTests.test_export_stores_formula_like_values_as_text`, `agenda.test_internal_comments.InternalCommentTests.test_activity_comments_escape_content_require_csrf_and_preserve_author` | Cubierto |
| SEG-04 | RNF-004, RNF-006 | `accounts.test_audit_trail.FieldLevelAuditTests.test_user_update_records_profile_roles_and_password_change_without_its_value`, `accounts.test_user_crud.UserCrudAdminTests.test_export_has_no_passwords_and_includes_all_filtered_rows`, `accounts.test_own_account.PasswordChangeTests.test_wrong_current_password_is_rejected_and_audited`, `accounts.test_login_security.LoginAuditTests.test_failures_and_lock_are_audited_without_the_password`, `...LoginAuditTests.test_successful_login_and_logout_are_audited`, `sgr_api.tests.PerformanceAPITests.test_token_endpoint_respects_sgr_lockout`. Transporte cifrado: el servidor de prueba no usa HTTPS (D-10) | Parcial |
| SEG-05 | RNF-017 | `activities.test_evidence.EvidenceTests.test_invalid_upload_is_atomic_and_closed_period_refuses_writes`, `accounts.test_profile_photo.ProfilePhotoTests.test_invalid_uploads_and_crop_do_not_write`, `common.test_error_pages.MediaFilesTests.test_media_is_not_served_by_django_without_debug`, `...MediaFilesTests.test_client_photo_is_private_even_with_debug_and_a_known_file_path`. Antivirus y retención: no implementados | Parcial |
| SEG-06 | RNF-009, RNF-006 | `accounts.test_seed_demo.SeedDemoTests.test_source_catalogs_and_all_personal_data_are_synthetic`, `analytics.test_performance_panel.PerformancePanelTests.test_personal_export_preserves_calculation_and_excludes_private_support`. Política de retención y eliminación: no implementada | Parcial |
| INT-01 | RF-034, RNF-003, CA-08 | `activities.test_activity_completion.ActivityArchiveRealtimeTests.test_parallel_activity_creations_and_edits` (dos cuentas crean registros distintos a la vez y ambos quedan íntegros). Complementan, para envíos duplicados: `activities.test_gifts.GiftConcurrencyTests.test_two_simultaneous_submissions_only_create_one_registration` y `activities.test_attention_submission.AttentionSubmissionTests.test_simultaneous_submission_is_resolved_by_the_database` | Cubierto |
| INT-02 | RF-034, RNF-007, CA-08 | `activities.test_activity_completion.ActivityCompletionTests.test_stale_activity_edit_preserves_first_save_and_can_retry_with_current_revision`, `accounts.test_official_completion.OfficialCompletionTests.test_stale_official_edit_preserves_the_first_save`, `analytics.test_measurement_configuration.MeasurementConfigurationTests.test_stale_rules_do_not_overwrite_another_edit`, `analytics.test_measurement_rules.MeasurementRulesTests.test_absence_edit_rejects_stale_revision` | Cubierto |
| INT-03 | RF-036, RNF-008, CA-09 | `accounts.test_audit_trail.FieldLevelAuditTests.test_official_update_records_the_changed_fields`, `configuration.test_audit.AuditViewTests.test_mutations_with_or_without_csrf_are_denied_and_audited`, `analytics.test_measurement_configuration.MeasurementConfigurationTests.test_parameter_changes_are_visible_with_before_after_and_account_in_audit`, `analytics.test_measurement_rules.MeasurementRulesTests.test_absence_edit_audits_previous_reason_dates_and_kind` | Cubierto |
| INT-04 | RNF-014, RNF-015 | `accounts.test_delegation_crud.DelegationCrudAdminTests.test_create_persists_and_generates_code`, `configuration.tests.PeriodValidationTests.test_period_consecutive_to_existing_one_is_accepted`, `analytics.test_measurement_configuration.MeasurementConfigurationTests.test_revision_applies_to_existing_activities_by_effective_date`. Prueban que delegaciones, períodos y revisiones se agregan por parametrización; el efecto en volumen y escalabilidad no se mide | Parcial |
| INT-05 | RNF-010 | Respaldo y restauración con RPO/RTO medidos: manual (M-10) | Sin prueba |
| INT-06 | RNF-001, RNF-018 | Monitoreo, falla inducida y disponibilidad: manual (M-11) | Sin prueba |

### 4.9 Rendimiento y despliegue (B16, B17)

| Caso | Requisito | Prueba | Cobertura |
| --- | --- | --- | --- |
| REN-01 | RNF-002 | `accounts.test_seed_demo.SeedDemoTests.test_performance_panel_renders_under_two_seconds_with_the_seed`, `analytics.test_performance_calculator.ProgressRulesTests.test_query_count_does_not_grow_with_activities`, `scripts/prueba_carga.py` (sección 5.2). Volúmenes de 5.000 y 10.000 registros: no preparados (la semilla trae 2.000) | Parcial |
| REN-02 | RNF-002 | `analytics.test_performance_panel.PerformancePanelTests.test_delegation_dashboard_queries_do_not_grow_with_team_size` (tablero) y `...test_query_count_does_not_grow_with_records` (Mi desempeño). Tablero bajo carga multiusuario: pendiente (M-19) | Parcial |
| REN-03 | RNF-002, RF-033 | Exportación de 10.000 registros con usuarios concurrentes: pendiente (M-19) | Sin prueba |
| REN-04 | RNF-003, RF-034, CA-08 | Concurrencia funcional de INT-01 y INT-02; carga mixta con escrituras progresivas: pendiente (M-19) | Parcial |
| REN-05 | RNF-002, RNF-018 | Carga incremental en AWS-TEST hasta degradación: pendiente (M-12 para consultas y M-19 para el resto) | Sin prueba |
| REN-06 | RNF-001, RNF-003 | Recuperación tras estrés: pendiente (M-19) | Sin prueba |
| AWS-01 | Complemento | Lista de verificación de la sección 5.3 (D1 a D4 y D9) | **Fallido**: por HTTP responden login, estáticos, API y `/media/` (18-11-2026 13:01:35), pero HTTPS no responde (D-10) y la versión desplegada no se pudo verificar |
| AWS-02 | RNF-004, RNF-005 | Seis roles en AWS: manual (M-01) | Sin prueba |
| AWS-03 | RF-001, RF-004 | CRUD con reinicio de la aplicación en AWS: manual (M-13) | Sin prueba |
| AWS-04 | CA-01, CA-06 | Flujo actividad → evidencia → aprobación → tablero → Excel en AWS: manual (M-14) | Sin prueba |
| AWS-05 | RNF-006 | Puertos, Security Groups y exposición de la base: manual (M-15) | Sin prueba |
| AWS-06 | Complemento | Instalación desde clon limpio y reversión: manual (M-16) | Sin prueba |

### 4.10 Módulos adicionales del incremento

Funciones implementadas que el PP no detalla caso a caso. Se prueban con los requisitos de S1 que
las respaldan.

| Área | Requisito | Prueba | Cobertura |
| --- | --- | --- | --- |
| Casos sociales: seguimiento, reasignación y cierre | RF-015, RF-036, HU-03 | `activities.test_case_follow_up.CaseFollowUpTests.test_reassignment_saves_responsible_and_history`, `...test_closed_cases_update_activity_list_detail_and_export`, `...test_online_tracking_closes_with_public_response_after_pending_step`, `...test_email_failure_preserves_attention_and_resend_invalidates_old_link` | Cubierto |
| Oficina de Partes (cartas e hitos) | RF-016, RF-034, RF-036 | `activities.test_office_letters.OfficeLetterAndFollowUpTests.test_creation_number_scope_and_history`, `...test_direct_milestones_calculate_intervals_and_agenda`, `...test_editing_a_stale_letter_preserves_the_first_change_and_the_draft`, `...test_case_without_visit_rejects_both_visit_dates` | Cubierto |
| Portal de clientes | RNF-005, RNF-009 | `activities.test_client_portal.ClientPortalTests.test_direct_url_and_filters_never_expose_another_client`, `...test_create_owner_status_and_duplicate_protection`, `activities.test_client_portal.ClientPhotoTests.test_client_crop_and_private_photo` | Cubierto |
| Regalos y entregas | RNF-005, RNF-007, RF-033 | `activities.test_gifts.GiftFlowTests.test_duplicate_between_delegations_and_formats_and_cancelled`, `...test_deliver_once_and_reject_stale_or_edit`, `...test_cancel_requires_reason_and_preserves_history`, `...test_foreign_registration_is_hidden_and_forged_territory_rejected`, `...test_filters_summary_and_excel_have_same_scope`, `...test_permission_migration_is_scoped_to_seed_roles`, `activities.test_gifts.GiftConcurrencyTests.test_two_simultaneous_submissions_only_create_one_registration` | Cubierto |
| Ausencias (días computables) | RF-005, RN-007 | `analytics.test_measurement_rules.MeasurementRulesTests.test_absences_clip_dates_and_preserve_guide_without_official`, `...test_expected_percentage_uses_the_official_absences`, `...test_freeze_preserves_days_and_prohibits_all_absence_mutations`, `...test_absence_delegation_scope_hides_and_blocks_other_delegations`, `...test_absence_pagination_keeps_the_official_filter`, `...test_absence_history_is_explicit_and_archived_official_is_read_only`, `accounts.test_absence_seed_migration.Accounts0015RoundTripTests.test_grant_reverse_conservatively_and_grant_again` | Cubierto |
| Tramos de cargo | RF-008, RF-038 | `analytics.test_measurement_rules.MeasurementRulesTests.test_two_position_segments_distinct_plans_and_boundary`, `...test_segmented_goal_and_traffic_light_follow_evaluated_segments`, `analytics.test_partial_plan_summary.PartialPlanSummaryTests.test_live_summary_shows_previous_contribution_adjustment_and_cap`, `analytics.test_indicator_support.IndicatorSupportTests.test_final_score_cap_survives_a_last_segment_without_plan` | Cubierto |
| API REST de desempeño | RNF-004, RNF-005, RNF-016 | `sgr_api.tests.PerformanceAPITests.test_issue_refresh_invalid_password_and_expired_token`, `...test_role_removal_and_suspension_take_effect_after_token_issuance`, `...test_delegation_authorization_and_resource_audit`, `...test_web_approval_changes_the_personal_and_team_json`, `...test_final_score_floor_keeps_the_breakdown_reconcilable`, `...test_documentation_requires_an_enabled_environment_and_web_session` | Cubierto |
| Congelamiento y trazabilidad | RN-013, RF-036, RF-038, CA-10 | `analytics.test_performance_panel.PerformancePanelTests.test_closing_freezes_weighted_and_tube_progress_and_later_changes_do_not_alter_it`, `analytics.test_indicator_support.IndicatorSupportTests.test_activity_edited_or_archived_after_closing_keeps_frozen_values`, `...test_close_period_takes_the_registry_lock_before_freezing`, `sgr_api.tests.PerformanceAPITests.test_closed_results_and_historical_delegation_remain_frozen`, `analytics.test_migration_reversal.Analytics0006ReversalTests.test_reverting_to_0005_converts_data_restores_schema_and_migrates_forward` | Cubierto |
| WebSocket en tiempo real | RF-034, RNF-005 | `common.test_realtime.AllMaintainersRealtimeTests.test_all_modules_all_accounts_and_rendered_connections`, `activities.test_realtime.ActivityRealtimeTests.test_revoked_permission_and_logout_close_existing_connection` | Cubierto |

### 4.11 Trazabilidad por requisito de S1

Cada RF, RN, RNF y CA se vincula con los casos que le asigna el PP (B4 a B17 y B19). Regla: **Cubierto**
si todos sus casos están Cubiertos, **Sin prueba** si ninguno tiene prueba automatizada y **Parcial** en
el resto. Las áreas de la sección 4.10 complementan, pero no cambian este estado.

| Requisito | Casos | Cobertura |
| --- | --- | --- |
| RF-001 Delegaciones | ADM-01, ADM-02, AWS-03 | Parcial |
| RF-002 Usuarios y roles | ADM-03, ADM-04 | Cubierto |
| RF-003 Cargos y funciones | ADM-05, CAT-01 | Cubierto |
| RF-004 Catálogos | CAT-01, CAT-02, CAT-03, CAT-04, AWS-03 | Parcial |
| RF-005 Períodos | PAR-01 | Cubierto |
| RF-006 Ponderaciones | PAR-02 | Parcial |
| RF-007 Metas y umbrales | PAR-03, PAR-04 | Parcial |
| RF-008 Ficha personal | ACT-03 | Cubierto |
| RF-009 Registrar actividades | ACT-01, ACT-06 | Cubierto |
| RF-010 Validar campos | ACT-02 | Cubierto |
| RF-011 Código de evidencia | EVI-01 | Parcial |
| RF-012 Asociar evidencia | EVI-02 | Parcial |
| RF-013 Validar evidencia | EVI-03, EVI-04, EVI-06 | Parcial |
| RF-014 Puntuación por validación | EVI-03, EVI-04 | Parcial |
| RF-015 Atención social | ACT-04, ACT-05 | Parcial |
| RF-016 Crear compromisos | AGE-01 | Cubierto |
| RF-017 Asignar compromiso | AGE-01, AGE-02, AGE-06 | Parcial |
| RF-018 Estados | AGE-03 | Parcial |
| RF-019 Plazos | AGE-04 | Parcial |
| RF-020 Agenda y medición | AGE-05 | Parcial |
| RF-021 Resumen colectivo | CAL-03 | Parcial |
| RF-022 Avance actual | CAL-01, EVI-05 | Cubierto |
| RF-023 % de cumplimiento | CAL-01, CAL-06 | Cubierto |
| RF-024 Cumplimiento ponderado | CAL-02 | Cubierto |
| RF-025 Incentivos y penalizaciones | TAB-04 | Cubierto (reglas por validar, D-03) |
| RF-026 Meta esperada al día | CAL-04, CAL-06 | Cubierto |
| RF-027 Semáforo | CAL-05 | Cubierto |
| RF-028 Tablero personal | TAB-01 | Cubierto |
| RF-029 Tablero de delegación | TAB-01 | Cubierto |
| RF-030 Actividad reciente | TAB-02 | Cubierto |
| RF-031 Vista global por cargos | TAB-03 | Cubierto |
| RF-032 Buscar y filtrar | UX-01, UX-02 | Parcial |
| RF-033 Exportar informes | UX-03, REN-03 | Parcial |
| RF-034 Trabajo simultáneo | INT-01, INT-02, REN-04 | Parcial |
| RF-035 Coordinación | TAB-05 | Parcial |
| RF-036 Trazabilidad | INT-03, AGE-06 | Cubierto |
| RF-037 Alertas | TAB-06, AGE-04 | Parcial |
| RF-038 Versionar parámetros | CAT-04, PAR-04, TAB-03 | Parcial |
| RN-001 Suma 100 % | PAR-02 | Parcial |
| RN-002 Meta > 0 y fórmula porcentual | PAR-03 | Parcial |
| RN-003 Avance actual | CAL-01 | Cubierto |
| RN-004 % de cumplimiento | CAL-01 | Cubierto |
| RN-005 Ponderado y tope 150 % | CAL-02 | Cubierto según S1 y PP; E3 fija 120 % (D-13) |
| RN-006 Umbral colectivo 80 % | CAL-03 | Parcial (el umbral no se aplica, D-09) |
| RN-007 Meta esperada al día | CAL-04 | Cubierto |
| RN-008 Semáforo | CAL-05 | Cubierto |
| RN-009 Solo validación aprobada | EVI-05 | Cubierto |
| RN-010 Códigos únicos | EVI-01 | Parcial |
| RN-011 Ajustes parametrizables | TAB-04 | Cubierto (valores por validar, D-03) |
| RN-012 Tres gestiones | ACT-04, ACT-05 | Parcial |
| RN-013 Período cerrado | PAR-05 | Cubierto |
| RNF-001 Disponibilidad | INT-06, REN-06 | Sin prueba |
| RNF-002 Rendimiento | REN-01, REN-02, REN-03, REN-05 | Parcial |
| RNF-003 Concurrencia | EVI-06, INT-01, REN-04, REN-06 | Parcial |
| RNF-004 Autenticación | ACC-01, ACC-02, ACC-03, SEG-04, AWS-02 | Parcial |
| RNF-005 Autorización | ADM-06, SEG-01, SEG-02, AWS-02 | Parcial |
| RNF-006 Confidencialidad | SEG-04, SEG-06, AWS-05 | Parcial |
| RNF-007 Integridad | CAT-05, SEG-03, ACT-06, INT-02 | Cubierto |
| RNF-008 Auditoría | INT-03 | Cubierto |
| RNF-009 Privacidad | SEG-06 | Parcial |
| RNF-010 Respaldo | INT-05 | Sin prueba |
| RNF-011 Usabilidad | UX-04 | Parcial |
| RNF-012 Accesibilidad | UX-05 | Parcial |
| RNF-013 Compatibilidad | UX-06 | Sin prueba |
| RNF-014 Escalabilidad | INT-04 | Parcial (solo parametrización, sin prueba de volumen) |
| RNF-015 Mantenibilidad | PAR-06, INT-04 | Parcial |
| RNF-016 Interoperabilidad | UX-03 | Cubierto |
| RNF-017 Gestión de evidencias | SEG-05 | Parcial |
| RNF-018 Monitoreo | INT-06, REN-05 | Sin prueba |

| Criterio integral | Casos (PP B19) | Cobertura |
| --- | --- | --- |
| CA-01 Registro validado | ACT-01, EVI-03, AWS-04 | Parcial |
| CA-02 Evidencia rechazada | EVI-04 | Parcial |
| CA-03 Compromiso vencido | AGE-04, TAB-06 | Parcial |
| CA-04 Atención social | ACT-04, ACT-05 | Parcial |
| CA-05 Cálculo diario | CAL-04, CAL-05 | Cubierto |
| CA-06 Consolidación | TAB-01, CAL-03, AWS-04 | Parcial |
| CA-07 Control de acceso | ADM-06, SEG-01, SEG-02 | Cubierto |
| CA-08 Concurrencia | EVI-06, INT-01, INT-02, REN-04 | Parcial |
| CA-09 Historial | INT-03, PAR-04 | Cubierto |
| CA-10 Período cerrado | PAR-05 | Cubierto |

Historias de usuario (mapa de PP B19): HU-01 ACT · HU-02 AGE · HU-03 ACT-04/05 · HU-04 ADM-05,
CAT-01, PAR · HU-05 PAR · HU-06 ACT-03, CAL-01 · HU-07 CAL, TAB-04 · HU-08 TAB-01/03 · HU-09
EVI-02, SEG-05 · HU-10 EVI-01 · HU-11 EVI-03 a EVI-06 · HU-12 AGE-01/02 · HU-13 AGE-03 · HU-14
AGE-04, CAL-03 · HU-15 AGE-06 · HU-16 y HU-17 CAL-04/05 · HU-18 TAB-01/03 · HU-19 TAB-02/06 ·
HU-20 UX-01/03 · HU-21 CAL-05, TAB-01/06 · HU-22 TAB-03 · HU-23 INT-01/02, REN-04 · HU-24 TAB-05 ·
HU-25 PAR-04/06 · HU-26 ACC, ADM, SEG · HU-27 CAT · HU-28 PAR-01/05 · HU-29 UX-01/02 · HU-30
INT-03 · HU-31 TAB-06. Una HU queda cerrada solo si todos sus casos están Cubiertos y sus manuales
aprobados.

### 4.12 Reglas del cliente y alcance de la Guía de Evaluación 3

E3 (Actividad 1 y 2) agrega reglas que S1 y el PP no traían. Cada una se trazó contra el código y
la suite. **Fallido** significa que lo obtenido contradice lo que pide E3; **Sin prueba** que no se
encontró ni implementación ni prueba.

| Caso | Regla de E3 | Prueba o evidencia | Estado |
| --- | --- | --- | --- |
| RC-01 | Las actividades o solicitudes cuyo usuario sea el delegado no contabilizan | No implementada: `analytics.services.computable_activities` (`analytics/services.py:39`) solo exige evidencia aprobada y un ítem del plan vigente; no mira quién es el usuario atendido | Sin prueba (D-15) |
| RC-02 | Sin nombre y teléfono del usuario no hay puntaje | No implementada: el mismo criterio de `computable_activities` no revisa nombre ni teléfono | Sin prueba (D-15) |
| RC-03 | Límite diario de siete actividades | No implementada: no hay validación de cantidad diaria en el registro de actividades | Sin prueba (D-15) |
| RC-04 | Bloqueo del ingreso tardío de gestiones de una semana cerrada | El bloqueo existe por **período** cerrado, no por semana: `common.test_period_concurrency.PeriodConcurrencyTests.test_registration_rejects_a_closed_period`, `activities.test_activity_completion.ActivityCompletionTests.test_closed_period_prevents_edit_archive_and_restore`. No existe cierre semanal | Parcial (D-15) |
| RC-05 | Las coordinaciones preparatorias no ponderan como acción cumplida | Solo ponderan los ítems de la versión publicada del plan: `analytics.test_performance_calculator.ProgressRulesTests.test_items_outside_the_plan_and_revisions_use_the_ruling_version`. No hay una categoría «coordinación preparatoria» que se excluya explícitamente | Parcial |
| RC-06 | Felicitación válida solo con respaldo formal del delegado | Solo cuentan las aprobadas, y quien registra o el afectado no pueden aprobar: `analytics.test_score_adjustments.ScoreAdjustmentTests.test_register_within_scope_and_only_approval_changes_result`, `...test_who_records_cannot_review_own_record`, `...test_affected_official_cannot_review_a_record_about_themselves`. No se exige que el respaldo venga del delegado ni un documento formal | Parcial (D-15) |
| RC-07 | Las ausencias informadas por el delegado ajustan las metas del semáforo | `analytics.test_measurement_rules.MeasurementRulesTests.test_expected_percentage_uses_the_official_absences`, `...test_absences_clip_dates_and_preserve_guide_without_official`, `accounts.test_seed_demo.SeedDemoTests.test_absence_permissions_follow_the_demo_roles` (el Delegado gestiona Ausencias) | Cubierto |
| RC-08 | Un registro aprobado no permite modificaciones | **Fallido.** Prueba exploratoria del 22-11-2026 (fuera del repositorio, ficha 6.1): una actividad con evidencia aprobada en un período abierto se editó con respuesta 302 y el cambio quedó guardado. `check_mutable` (`common/maintainers.py:415-424`) y la fila del listado (`common/maintainers.py:243-247`) solo miran la atención de origen, el período abierto y el archivado | Fallido (D-14) |
| RC-09 | Solo cuentan los registros aprobados que ponderan a la meta | `analytics.test_performance_calculator.ProgressRulesTests.test_only_approved_evidence_counts_and_annulment_reverts`, `analytics.test_performance_panel.PerformancePanelTests.test_result_changes_when_evidence_is_approved_and_not_when_rejected`, `analytics.test_performance_calculator.ProgressRulesTests.test_items_outside_the_plan_and_revisions_use_the_ruling_version` | Cubierto |
| RC-10 | El Tubo se consulta por toda la delegación y cada funcionario modifica solo lo suyo mientras no esté aprobado | No hay una pantalla «Tubo» con ese nombre: el tubo se mide con los compromisos de la Agenda («Soluciones de ingresos al tubo», «Pendientes en tubo»). Solo está probado que los registros fuera del ámbito se rechazan con 404 y quedan auditados (`accounts.test_audit_trail.OutOfScopeAccessAuditTests.test_foreign_records_answer_404_and_leave_an_audit_entry` para delegaciones, usuarios y funcionarios ajenos; `common.test_persistent_maintainers.PersistentMaintainerTests.test_own_scope_hides_other_official_activities_and_export` para el detalle de una actividad con alcance propio). La consulta de la Agenda por toda la delegación está en el código (`agenda/commitments.py:26-29`, alcance DELEGATION) pero sin prueba. La edición solo por el dueño **no está implementada** para el rol sembrado Funcionario: tiene `agenda.change_commitment` con alcance DELEGATION (`common/management/commands/seed_demo.py:35` y `:247`), la vista filtra lo editable con ese mismo alcance (`agenda/commitment_views.py:223`) y `Commitment.change_status` no revisa quién es el responsable (`agenda/models.py:81`). La condición «mientras no esté aprobado» falla (RC-08) | Parcial (D-15) |
| RC-11 | Búsqueda dinámica por código, RUT o nombre del solicitante | Actividades busca por código, funcionario, ítem, fecha y tipo (`common/maintainers.py:39`), no por RUT del solicitante; Regalos sí busca por RUT y nombre (`activities/gifts.py:259`). Pruebas: `common.test_live_search.LiveSearchMarkupTests.test_search_in_the_url_keeps_filters_in_pages_and_export` (búsqueda por texto en los mantenedores, no por RUT) y `activities.test_gifts.GiftFlowTests.test_leading_zeros_and_points_share_canonical_rut` (solo normaliza el RUT). La búsqueda por RUT no tiene prueba | Parcial |
| RC-12 | Creación con contraseña temporal y cambio obligatorio en el primer ingreso | El administrador fija la contraseña inicial (`accounts.test_user_crud.UserCrudAdminTests.test_create_requires_password`); no existe marca de contraseña temporal ni cambio obligatorio en el primer ingreso | Parcial (D-15) |
| RC-13 | Recuperación con token que expira | `accounts.test_auth_flows.PasswordRecoveryFlowTests.test_expired_token_is_rejected`, `...test_used_token_cannot_be_reused`, `...test_valid_token_opens_the_new_password_form` (ver ACC-05) | Cubierto |
| RC-14 | Contraseñas con hash seguro | Se usa el hasher por defecto de Django (PBKDF2; `config/settings.py` no redefine `PASSWORD_HASHERS`). Las pruebas comprueban `check_password` y que la contraseña no aparece en exportaciones ni auditoría (`accounts.test_user_crud.UserCrudAdminTests.test_export_has_no_passwords_and_includes_all_filtered_rows`, `accounts.test_audit_trail.FieldLevelAuditTests.test_user_update_records_profile_roles_and_password_change_without_its_value`); ninguna afirma el formato del hash guardado | Parcial |
| RC-15 | Control de acceso a evidencias y archivos | `activities.test_evidence.EvidenceTests.test_multiple_stages_share_the_activity_history_and_approve_once` (la imagen se entrega con `Cache-Control` privado y `no-store`; un lector de otra delegación recibe 404), `common.test_error_pages.MediaFilesTests.test_media_is_not_served_by_django_without_debug`, `...MediaFilesTests.test_client_photo_is_private_even_with_debug_and_a_known_file_path` | Cubierto |
| RC-16 | Tope máximo de cumplimiento de 120 % por funcionario | **Fallido frente a E3.** El sistema usa `max_final_score` con 150 por defecto (`analytics/models.py:60-64`, `analytics/services.py:26`) y el tope por ítem `max_computable` también es 150 (`analytics/models.py:34-36`). `analytics.test_performance_calculator.KnownCaseTests.test_coordinator_compliance_is_capped_at_the_configured_maximum` y `analytics.test_indicator_support.IndicatorSupportTests.test_final_score_cap_is_configurable_used_and_frozen` pasan y prueban que el tope es configurable (este último lo fija en 120), pero el valor por defecto no es el de E3 | Fallido (D-13) |

## 5. Pruebas de borde, estrés y despliegue (B16 a B18)

### 5.1 Lo que ya existe en la suite

- **Concurrencia en MySQL.** Cuatro pruebas con `SELECT FOR UPDATE` e hilos reales (sección 2),
  más la edición simultánea con revisión de formulario en Actividades, Funcionarios, Usuarios,
  Cartas, Ausencias, Territorios y planes de medición (INT-02).
- **Límites y bordes.** Longitud máxima y máxima + 1 (`common.test_requirements.FieldLengthAndRelationTests`),
  descripción de 300 y 301 caracteres con CRLF (`activities.test_social_attention.SocialAttentionEntryTests`),
  identificadores inexistentes, enormes, negativos y no numéricos (`common.test_description_limit.InvalidIdentifierTests`),
  fronteras del semáforo sin redondeo anticipado (CAL-E) y denominadores vacíos (CAL-06).
- **Archivos.** Cargas inválidas atómicas y fotos privadas (SEG-05):
  `activities.test_evidence.EvidenceTests.test_invalid_upload_is_atomic_and_closed_period_refuses_writes`
  rechaza un lote con un archivo que no es imagen, un lote vacío y un lote de 11 imágenes sin escribir
  nada en la base ni en disco. El tamaño máximo en bytes de cada imagen no tiene prueba propia.
- **Bloqueo de inicio de sesión.** Tras `LOGIN_MAX_FAILED_ATTEMPTS` (5) por `LOGIN_LOCKOUT_MINUTES`
  (10), también en el admin y en la API (`accounts.test_login_security.LoginLockoutTests`,
  `sgr_api.tests.PerformanceAPITests.test_token_endpoint_respects_sgr_lockout`).
- **Entradas adversas.** Apóstrofos, condiciones SQL y etiquetas HTML como datos (SEG-03); textos
  que empiezan con `=` se exportan como texto (`common.tests.BuildXlsxTests`).
- **Consultas que no crecen con los datos.** `analytics.test_performance_calculator.ProgressRulesTests.test_query_count_does_not_grow_with_activities`,
  `analytics.test_performance_panel.PerformancePanelTests.test_query_count_does_not_grow_with_records` y
  `analytics.test_performance_panel.PerformancePanelTests.test_delegation_dashboard_queries_do_not_grow_with_team_size`.

### 5.2 Prueba de carga (`scripts/prueba_carga.py`)

Script con biblioteca estándar (`concurrent.futures` y `urllib`). Cada usuario virtual abre su
propia sesión con el formulario de ingreso (token CSRF incluido) y luego alterna «Mi desempeño»
(`/analytics/mi-desempeno/`) y «Actividades» (`/activities/`) hasta completar el total de
consultas. Informa por operación: cantidad, errores, promedio, p95 (rango más cercano) y máximo; y
en total: duración, solicitudes por segundo, errores y **cuántos usuarios virtuales alcanzaron a
hacer al menos una consulta**. Una respuesta distinta de 200 o una redirección al login cuenta como
error. Un fallo de red o de tiempo de espera se registra con el **tiempo real** que tardó en fallar,
no con el máximo de `--timeout` (mejora del 22-11-2026).

```bash
# PowerShell: $env:SGR_CLAVE_PRUEBA = "<clave de las cuentas de prueba>"
python scripts/prueba_carga.py --url http://127.0.0.1:8000 \
    --usuarios adminA,editorA,readerA,readerB --concurrencia 20 --solicitudes 200 --json carga.json
```

Todas las cuentas de `--usuarios` deben poder abrir «Mi desempeño» y «Actividades». `adminEvalA`
no sirve para esta prueba: no tiene `analytics.view_indicatorsnapshot` y recibe 403 en «Mi
desempeño» (lo confirmó la corrida del 18-11-2026 a las 13:00:18 de la ficha).

- La contraseña se lee de `SGR_CLAVE_PRUEBA` o de `--archivo-clave`, nunca de un argumento.
- Con un servidor que no sea local exige `--permitir-remoto`.
- Antes de lanzar la carga hace un ingreso de prueba; si falla, se detiene. Una clave equivocada
  repetida por todos los usuarios virtuales bloquearía las cuentas (5 fallos por cuenta, 10 minutos).
- **Por HTTP la contraseña y la cookie de sesión viajan sin cifrar.** Mientras AWS no tenga HTTPS
  (D-10), usar solo cuentas de prueba desechables y cambiarles la clave después.
- **Contra AWS (pendiente, M-12):** ejecutarlo el responsable, con cuentas desechables, con carga baja y en el entorno
  autorizado, por ejemplo `--url http://34.201.192.78 --permitir-remoto --concurrencia 5 --solicitudes 50`,
  y luego seguir los escalones del protocolo B18 (1 usuario de control, 10 normales, 20 y 50) solo
  si el docente aprueba la carga normal y los límites de parada.

Resultado obtenido en el servidor local: ver la [ficha](#61-ejecución-automatizada).

### 5.3 Lista de verificación del despliegue

«Local» es el servidor de desarrollo de este equipo con el commit evaluado; no reemplaza la
verificación en AWS.

| N.º | Verificación | Cómo | Esperado | Local | AWS (34.201.192.78) |
| --- | --- | --- | --- | --- | --- |
| D1 | Login | Abrir `/accounts/login/` e ingresar con una cuenta de prueba | 200, ingreso al inicio | OK: página 200 e ingreso de 20 sesiones en la carga (13:01) | Parcial: página 200 (13:01); ingreso con cuenta pendiente (M-01) |
| D2 | Estáticos | Abrir un CSS de `/static/` | 200 con `text/css` | OK: 200 `text/css` | OK: 200 `text/css` |
| D3 | API con credenciales falsas | `GET /api/v1/periodos/` con `Authorization: Bearer token-falso` | 401 | OK: 401 | OK: 401 |
| D4 | `/media/` no público | `GET /media/<archivo inexistente o privado>` sin sesión | 404 con `DEBUG=False` | No aplica: `DEBUG=True` en local (archivo inexistente → 404). Cubierto por `common.test_error_pages.MediaFilesTests.test_media_is_not_served_by_django_without_debug` | Parcial: 404 para un archivo inexistente; falta probar uno privado existente |
| D5 | Evidencia de varias imágenes | Cargar 3 fotografías sintéticas en una actividad y aprobarla | Una etapa, aporte una sola vez | Pendiente (M-14) | Pendiente (M-14) |
| D6 | WebSocket entre dos pestañas | Dos cuentas autorizadas; crear una actividad en una | La otra se actualiza sin F5 | Pendiente (M-17) | Pendiente (M-17) |
| D7 | Exportación a Excel | Exportar Actividades filtradas y comparar con la tabla | Mismas filas en todas las páginas | Pendiente (M-18) | Pendiente (M-18) |
| D8 | `check --deploy` | `python manage.py check --deploy` con la configuración del servidor | Sin advertencias | Fallido: 5 advertencias (W004, W008, W012, W016, W018) | Pendiente |
| D9 | HTTPS y versión | Abrir por HTTPS y comparar el commit desplegado | Certificado válido, commit evaluado | No aplica en local | **Fallido** (AWS-01): HTTPS sin respuesta (18-11-2026 13:01:35, D-10); versión desplegada sin verificar |

## 6. Ficha de ejecución del protocolo

### 6.1 Ejecución automatizada

| Fecha | Ejecutor | Entorno | Comando | Commit | Duración | Resultado |
| --- | --- | --- | --- | --- | --- | --- |
| 18-11-2026 12:44:08 a 12:53:35 | Sebastián Alzamora, asistido por Claude Code | LOCAL, MySQL 8.4.7, en serie (sin `mysqldump` en el `PATH`) | `python manage.py test --noinput -v 2` | `07064bd` | 567 s (512,1 s de pruebas) | **796 ejecutadas: 796 OK, 0 fallos, 0 errores, 0 omitidas** |
| 18-11-2026 12:56:55 | Ídem | LOCAL | `python manage.py makemigrations --check --dry-run` | `07064bd` | < 5 s | «No changes detected», código de salida 0 |
| 18-11-2026 (cierre de fase, 1.ª ronda) | Ídem (subagente de pruebas) | LOCAL, MySQL 8.4.7, en serie | `python manage.py test --noinput` y `makemigrations --check --dry-run` | `07064bd` + cambios de documentación | 428,1 s de pruebas | 796 OK, 0 fallos, 0 errores, 0 omitidas; «No changes detected» |
| 18-11-2026 (cierre de fase, 2.ª ronda) | Ídem (subagente de pruebas) | LOCAL, MySQL 8.4.7, en serie | Ídem y `python -m py_compile scripts/prueba_carga.py` | `07064bd` + cambios de documentación | 708,3 s de pruebas | 796 OK, 0 fallos, 0 errores, 0 omitidas; «No changes detected»; el script compila |
| 18-11-2026 | Ídem | LOCAL, `.env` de desarrollo | `python manage.py check --deploy` | `07064bd` | < 5 s | 5 advertencias: W004, W008, W012, W016, W018 (D-10) |
| 18-11-2026 12:57 | Ídem | LOCAL, copia temporal del repositorio en cada commit | `python manage.py test --noinput common.test_modal_feedback` | `aa72d94` (PR #49), `1f444ca` (PR #51), `8bbcd58` (PR #52) | ≈ 2 s cada una | #49 y #51: FAILED (1 fallo y 1 error); #52: 3 OK (D-07) |
| 18-11-2026 13:00:10 | Ídem | LOCAL, `runserver` (Daphne, `DEBUG=True`) sobre la base temporal `sgr_carga_tmp` (migrada y con `seed_demo`, 2.000 registros; borrada al terminar) | `python scripts/prueba_carga.py --usuarios adminA,editorA,readerA,readerB,adminEvalA --concurrencia 1 --solicitudes 10` | `07064bd` + `scripts/prueba_carga.py` sin commitear en la rama `docs/plan-y-resultados-de-pruebas` | 1,56 s | Control: 12 solicitudes, 0 errores |
| 18-11-2026 13:00:18 | Ídem | Ídem | `python scripts/prueba_carga.py --usuarios adminA,editorA,readerA,readerB,adminEvalA --concurrencia 20 --solicitudes 200` | `07064bd` + `scripts/prueba_carga.py` sin commitear en la rama `docs/plan-y-resultados-de-pruebas` | 20,34 s | 240 solicitudes, 16 errores: HTTP 403 en Mi desempeño para `adminEvalA`, que no tiene `analytics.view_indicatorsnapshot` (comportamiento esperado, no de carga) |
| 18-11-2026 13:01:01 | Ídem | Ídem | `python scripts/prueba_carga.py --usuarios adminA,editorA,readerA,readerB --concurrencia 20 --solicitudes 200` | `07064bd` + `scripts/prueba_carga.py` sin commitear en la rama `docs/plan-y-resultados-de-pruebas` | 19,20 s | 240 solicitudes, 12,5 por segundo, **0 errores** (tabla siguiente) |
| 18-11-2026 13:01:28 | Ídem | LOCAL, mismo servidor | `curl` de la lista 5.3 (D2, D3, D4) | `07064bd` | — | Estáticos 200 `text/css`; API con token falso 401; `/media/` inexistente 404 |
| 18-11-2026 13:01:35 | Ídem | AWS 34.201.192.78, solo GET | `curl` de la lista 5.3 (D1 a D4 y HTTPS) | Desconocido | — | Login 200, estáticos 200, API 401, `/media/` 404, HTTPS sin respuesta |
| 22-11-2026 18:43:45 a 18:43:56 | Sebastián Alzamora, asistido por Claude Code | LOCAL, WAMP detenido | `python manage.py test --noinput -v 2` | `07064bd` | 11 s | **Bloqueada**: encontró 796 pruebas, pero no ejecutó ninguna: `OperationalError (2002) Can't connect to server on 'localhost' (10061)`. Incidencia INC-01 (sección 6.5) |
| 22-11-2026 18:44:57 a 18:52:03 | Ídem | LOCAL, MySQL 8.4.7 (WAMP), en serie (sin `mysqldump` en el `PATH`) | `python manage.py test --noinput -v 2` | `07064bd` (mismo commit que la corrida del 18-11-2026) | 426 s (399,4 s de pruebas) | **796 ejecutadas: 796 OK, 0 fallos, 0 errores, 0 omitidas** |
| 22-11-2026 18:52:05 | Ídem | LOCAL | `python manage.py makemigrations --check --dry-run` | `07064bd` | < 5 s | «No changes detected», código de salida 0 |
| 22-11-2026 18:52:14 a 18:52:36 | Ídem | LOCAL, MySQL 8.4.7, base de pruebas aislada | Prueba exploratoria fuera del repositorio (`probe_approved_edit.ApprovedActivityEditProbe`, con `ActivityFixture` de `activities.test_activity_completion`): crea una evidencia aprobada en una actividad de período abierto y la edita como su dueño | `07064bd` | 0,3 s | GET del formulario de edición 200; POST 302 y la descripción quedó «Cambiada tras aprobar». Confirma D-14 (RC-08 Fallido) |
| 22-11-2026 18:53:36 | Ídem | LOCAL, `runserver` (Daphne, `DEBUG=True`) sobre la base temporal `sgr_carga_tmp` (migrada y con `seed_demo`, 2.000 registros; clave aleatoria solo en variables de entorno; base borrada al terminar) | `python scripts/prueba_carga.py --usuarios adminA,editorA,readerA,readerB --concurrencia 1 --solicitudes 10` | `07064bd` + `scripts/prueba_carga.py` sin commitear en la rama `docs/plan-y-resultados-de-pruebas` (versión con tiempo real en fallos de red) | 1,42 s | Control: 12 solicitudes, 0 errores, 1 de 1 usuarios virtuales alcanzó a consultar |
| 22-11-2026 18:53:39 | Ídem | Ídem | `python scripts/prueba_carga.py --usuarios adminA,editorA,readerA,readerB --concurrencia 20 --solicitudes 200` | Ídem | 19,12 s | 240 solicitudes, 12,55 por segundo, **0 errores**, 20 de 20 usuarios virtuales alcanzaron a consultar (tabla siguiente) |

Resultado de la carga moderada (20 usuarios virtuales, 4 cuentas, 200 consultas más 20 ingresos),
en las dos corridas sobre el servidor local:

| Operación | Corrida | Solicitudes | Errores | Promedio | p95 | Máximo |
| --- | --- | --- | --- | --- | --- | --- |
| Formulario de inicio de sesión | 18-11-2026 13:01:01 | 20 | 0 | 286,2 ms | 389,6 ms | 402,0 ms |
| Formulario de inicio de sesión | 22-11-2026 18:53:39 | 20 | 0 | 72,0 ms | 95,2 ms | 103,7 ms |
| Inicio de sesión | 18-11-2026 | 20 | 0 | 1.520,8 ms | 1.758,0 ms | 1.760,5 ms |
| Inicio de sesión | 22-11-2026 | 20 | 0 | 1.405,4 ms | 1.847,2 ms | 1.857,9 ms |
| Mi desempeño | 18-11-2026 | 99 | 0 | 1.489,5 ms | 1.862,1 ms | 1.977,1 ms |
| Mi desempeño | 22-11-2026 | 102 | 0 | 1.526,8 ms | 1.855,2 ms | 1.999,9 ms |
| Actividades | 18-11-2026 | 101 | 0 | 1.850,5 ms | **2.737,4 ms** | **3.039,3 ms** |
| Actividades | 22-11-2026 | 98 | 0 | 1.890,8 ms | **2.729,9 ms** | **2.885,9 ms** |

Con 1 usuario (control) Mi desempeño promedió 126,0 ms (18-11) y 121,2 ms (22-11), y Actividades
92,8 ms y 83,7 ms. Con 20 usuarios simultáneos el servidor de desarrollo (un proceso, `DEBUG=True`)
supera en las dos corridas el objetivo de 2 s de S1 en Actividades (p95 2,73 a 2,74 s); Mi
desempeño queda bajo 2 s. La segunda corrida repite la primera con diferencias menores, salvo el
formulario de inicio de sesión. No es una medición de AWS ni de producción: sirve como línea base y
para validar el script (REN-01 Parcial). La carga se hizo en una base temporal para no modificar la
de desarrollo del equipo (el 18-11-2026 tenía 19 migraciones sin aplicar).

**Pruebas omitidas:** ninguna. Las cuatro pruebas con `skipUnlessDBFeature("has_select_for_update")` (sección 2) se ejecutaron porque el motor es MySQL. La línea «No se pudo enviar una invitación al portal…» que aparece en la salida es un mensaje esperado de `activities.test_case_follow_up.CaseFollowUpTests.test_email_failure_preserves_attention_and_resend_invalidates_old_link`, que simula la falla del correo; la prueba pasa.

### 6.2 Ficha de casos manuales

Estado inicial de todos: **Pendiente de ejecución manual** (PP B4: «Todas las filas parten en
estado No ejecutado»). El responsable completa obtenido, estado y fecha al ejecutarlos.

| ID | Caso | Pasos | Esperado | Obtenido | Estado | Responsable | Fecha |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M-01 | ACC-01, AWS-02 | Ingresar con cada rol de demostración (Administrador, Coordinador, Delegado, Funcionario, Verificador, Consulta) en AWS; abrir menú, una lectura y una escritura permitida y otra denegada | Menú y delegación según el rol; denegada con 403 | — | Pendiente de ejecución manual | Equipo | — |
| M-02 | ACC-03 | Cerrar sesión, pulsar Atrás y recargar | No se muestran datos protegidos; vuelve al login | — | Pendiente de ejecución manual | Equipo | — |
| M-03 | ACC-06 | Recuperar la contraseña con el enlace del buzón de prueba y guardar una nueva | SweetAlert2 de éxito; la clave anterior ya no sirve | — | Pendiente de ejecución manual | Equipo | — |
| M-04 | CAT-06 | Desactivar un registro y pulsar Cancelar en el diálogo | No cambia nada; sin mensaje de éxito | — | Pendiente de ejecución manual | Equipo | — |
| M-05 | ACT-05 | En el ingreso de atención, elegir tipo y subatención y luego cambiar el tipo | La subatención se limpia si deja de ser válida | — | Pendiente de ejecución manual | Equipo | — |
| M-06 | UX-01 | Escribir en la búsqueda de un listado, borrar y escribir rápido; cortar la red | «Buscando…», sin resultados mezclados; error visible sin red | — | Pendiente de ejecución manual | Equipo | — |
| M-07 | UX-04 | Comparar login, un CRUD y el ingreso de atención con laserena.cl/conocenos/normas-graficas | Logotipo, colores y tipografías conformes | — | Pendiente de ejecución manual | Equipo | — |
| M-08 | UX-05 | Recorrer login, un CRUD y Mi desempeño solo con teclado; medir contraste | Foco visible y ordenado; contraste suficiente; semáforo con texto | — | Pendiente de ejecución manual | Equipo | — |
| M-09 | UX-06 | Login, registro de actividad, carga de evidencia, consulta y Excel en Chrome y Edge, escritorio y móvil | Flujos completos; registrar versiones y tamaños | — | Pendiente de ejecución manual | Equipo | — |
| M-10 | INT-05 | Respaldar base y `media/`, restaurar en un ambiente aislado y medir pérdida y tiempo | Datos coherentes; RPO y RTO medidos | — | Pendiente de ejecución manual | Equipo | — |
| M-11 | INT-06 | Detener la aplicación en AWS y recuperarla; revisar registros | Caída detectada y recuperación registrada | — | Pendiente de ejecución manual | Equipo | — |
| M-12 | REN-01, REN-05 (consultas) | Con cuentas de prueba desechables, ejecutar `scripts/prueba_carga.py` contra AWS con carga baja y luego por escalones B18. Mide solo inicio de sesión, Mi desempeño y Actividades | p95 ≤ 2 s en esas consultas; 0 % de errores en carga normal | — | Pendiente de ejecución manual | Equipo | — |
| M-13 | AWS-03 | Crear, editar y desactivar un registro por CRUD; reiniciar la aplicación | Persisten tras el reinicio | — | Pendiente de ejecución manual | Equipo | — |
| M-14 | AWS-04, D5 | Registrar actividad, cargar 3 imágenes, aprobar como verificador; abrir ficha, tablero y Excel | Un incremento; mismo valor en detalle, resumen y archivo | — | Pendiente de ejecución manual | Equipo | — |
| M-15 | AWS-05 | Revisar Security Groups, puertos abiertos y acceso a MySQL desde fuera | Solo 80/443 (y SSH restringido); base no expuesta | — | Pendiente de ejecución manual | Equipo | — |
| M-16 | AWS-06 | Clonar el repositorio limpio, instalar según README, migrar y desplegar el commit; respaldar la base desechable con datos representativos; ensayar la reversión de migraciones (`python manage.py migrate analytics 0005` y volver con `python manage.py migrate`, como en `analytics.test_migration_reversal`); restaurar el respaldo y comparar valores; restaurar el commit anterior | Procedimiento reproducible; la reversión y la vuelta adelante terminan sin errores. La reversión a `0005` deshace `0006` a `0009`: convierte datos (`MAX_PERCENTAGE` → `PERCENTAGE`, meta vacía → 0), elimina columnas (entre ellas `computable_days`, `segments`, `complaint_points`, `congratulation_points` y `max_final_score`) y las tablas de ajustes de puntaje y del respaldo congelado (`analytics/migrations/0007_score_adjustments.py`, `analytics/migrations/0009_frozen_support_and_final_score_cap.py`). Tras restaurar el respaldo, los valores coinciden con los previos | — | Pendiente de ejecución manual | Equipo | — |
| M-17 | D6 | Abrir Actividades con dos cuentas autorizadas en dos pestañas y crear un registro | La otra pestaña se actualiza sin recargar | — | Pendiente de ejecución manual | Equipo | — |
| M-18 | D7, UX-03 | Filtrar un listado con más de una página y exportar | El Excel trae todas las filas filtradas | — | Pendiente de ejecución manual | Equipo | — |
| M-19 | REN-02 a REN-06 | Escenarios que el script no cubre: tablero de delegación con filtros repetidos, exportación de 10.000 registros mientras otros consultan, escrituras concurrentes progresivas, estrés hasta degradación y recuperación (herramienta por definir; registrar CPU y memoria) | Tablero ≤ 5 s; archivo completo; sin pérdidas ni duplicados; recuperación documentada | — | Pendiente de ejecución manual | Equipo | — |
| CU-DEMO-01 a REG-DEMO-01 | Demostración | Ver las fichas completas a continuación | — | — | Pendiente de ejecución manual | Sebastián Alzamora | — |

#### Formato de caso (Guía de Evaluación 3, Actividad 4)

Cada caso manual crítico se registra con estos cinco bloques. El formato se aplica completo a los
casos de la demostración y a M-01, M-14 y M-16; los demás M-xx usan la tabla anterior y se pasan a
este formato al ejecutarlos.

| Bloque | Campos |
| --- | --- |
| Identificación | Código, nombre, requerimiento asociado y prioridad |
| Preparación | Precondiciones, perfil de usuario y datos de prueba |
| Ejecución | Pasos numerados y verificables |
| Resultado | Esperado, obtenido y estado |
| Seguimiento | Responsable, fecha, evidencia, defecto asociado, corrección y reejecución |

#### CU-DEMO-01 Iniciar sesión

| Bloque | Contenido |
| --- | --- |
| Identificación | **CU-DEMO-01** · Iniciar sesión · HU-26, RNF-004, ACC-01 · Prioridad alta |
| Preparación | Entorno AWS (34.201.192.78) con el commit evaluado. Perfil: Funcionario, cuenta `editorA` (sección 6.3). La contraseña la entrega el responsable fuera del repositorio |
| Ejecución | 1. Abrir `/accounts/login/` sin sesión. 2. Verificar que se ve el enlace «¿Olvidaste tu contraseña?». 3. Ingresar con `editorA`. 4. Revisar el menú lateral y el distintivo de rol y delegación. 5. Abrir por URL una pantalla que el rol no tiene (por ejemplo, Roles) |
| Resultado | Esperado: el enlace de recuperación está visible; el ingreso lleva al inicio; el menú solo muestra las secciones del rol Funcionario; la pantalla no permitida responde 403. Obtenido: — . Estado: **Pendiente de ejecución manual** |
| Seguimiento | Responsable: Sebastián Alzamora. Fecha: — . Evidencia: capturas del login, del menú y del 403. Defecto: — . Corrección: — . Reejecución: — . Pruebas automatizadas relacionadas: `accounts.tests.AuthenticationFrontendRouteTests.test_login_and_recovery_request_render_without_session`, `accounts.test_auth_flows.ProtectedRouteTests.test_menu_only_lists_permitted_sections`, `accounts.test_auth_flows.ProtectedRouteTests.test_each_screen_requires_its_permission_and_logs_the_denial` |

#### CU-DEMO-02 Registrar actividad

| Bloque | Contenido |
| --- | --- |
| Identificación | **CU-DEMO-02** · Registrar actividad · HU-01, RF-009, RF-010, RF-011 · Prioridad alta |
| Preparación | Período abierto que incluya la fecha de hoy. Perfil: Funcionario, `editorA`. Datos: un ítem vigente del plan de su cargo y un tipo de actividad de su área |
| Ejecución | 1. Abrir Actividades y pulsar «Nueva». 2. Completar todos los campos salvo el ítem y guardar. 3. Elegir el ítem y guardar. 4. Abrir el detalle y anotar el código. 5. Editar la actividad, quitar el ítem y guardar. 6. Volver a elegir el ítem, cambiar la descripción y guardar |
| Resultado | Esperado: el paso 2 se rechaza con el error en el campo ítem y no se crea nada; el paso 3 crea la actividad con código `ACT-<número>` generado por el sistema; el paso 5 se rechaza con la misma validación; el paso 6 guarda el cambio y conserva el código. Obtenido: — . Estado: **Pendiente de ejecución manual** |
| Seguimiento | Responsable: Sebastián Alzamora. Fecha: — . Evidencia: capturas del error, del código y del historial. Defecto: — . Corrección: — . Reejecución: — . Pruebas automatizadas relacionadas: `activities.test_activity_completion.ActivityCompletionTests.test_invalid_required_date_type_and_foreign_relations_do_not_write`, `common.test_persistent_maintainers.PersistentMaintainerTests.test_manual_create_and_move_from_closed_period_is_rejected` (código `ACT-\d+`), `activities.test_activity_completion.ActivityCompletionTests.test_editor_has_complete_create_detail_edit_modal_flow_without_archival` |

#### CU-DEMO-03 Validar evidencia

| Bloque | Contenido |
| --- | --- |
| Identificación | **CU-DEMO-03** · Validar evidencia · HU-09, HU-11, RF-012, RF-013, RN-009 · Prioridad alta |
| Preparación | Entorno AWS. Perfiles: Funcionario `editorA` y Verificador `verificadorA` (creado a mano, sección 6.3), en la misma delegación. Datos: la actividad de CU-DEMO-02 y una o más imágenes sintéticas |
| Ejecución | 1. Con `editorA`, abrir la actividad y adjuntar las imágenes. 2. Cerrar sesión e ingresar con `verificadorA`. 3. Abrir la evidencia y elegir «Rechazar» sin escribir observación. 4. Escribir una observación y elegir «Aprobar». 5. Abrir Actividades y aplicar el filtro «Solo las que cuentan en la medición» |
| Resultado | Esperado: el paso 3 se rechaza con «Indica el motivo de la decisión.» y no cambia el estado; el paso 4 aprueba una sola vez; en el paso 5 la actividad aparece en el listado filtrado. Obtenido: — . Estado: **Pendiente de ejecución manual** |
| Seguimiento | Responsable: Sebastián Alzamora. Fecha: — . Evidencia: capturas del mensaje, del estado aprobado y del listado filtrado. Defecto: — . Corrección: — . Reejecución: — . Pruebas automatizadas relacionadas: `activities.test_evidence.EvidenceTests.test_author_cannot_review_and_rejection_requires_reason`, `activities.test_evidence.EvidenceTests.test_multiple_stages_share_the_activity_history_and_approve_once`, `analytics.test_performance_panel.PerformancePanelTests.test_rows_show_text_and_icon_traffic_lights_and_link_to_source_activities` (enlace con `evidence=counted`) |

#### REG-DEMO-01 Regalos: un RUT por campaña

| Bloque | Contenido |
| --- | --- |
| Identificación | **REG-DEMO-01** · Inscripción única por RUT en una campaña de regalos · RNF-007, RNF-005 · Prioridad media |
| Preparación | Una campaña de regalos abierta en la que participan dos delegaciones. Perfiles: una cuenta con permiso de inscripción en cada delegación (por ejemplo `editorA` en Las Compañías y una cuenta de Antena con el mismo permiso). Datos: un RUT sintético válido |
| Ejecución | 1. Desde Las Compañías, inscribir al niño con el RUT. 2. Desde la otra delegación, inscribir el mismo RUT en la misma campaña. 3. Repetir el paso 2 escribiendo el RUT con puntos o con ceros a la izquierda |
| Resultado | Esperado: el paso 1 crea la inscripción; los pasos 2 y 3 se rechazan con «RUT ya ingresado por la delegación Las Compañías en esta campaña…» (`activities/gifts.py:166`) y no se crea un segundo registro. Obtenido: — . Estado: **Pendiente de ejecución manual** |
| Seguimiento | Responsable: Sebastián Alzamora. Fecha: — . Evidencia: captura del mensaje y del listado. Defecto: — . Corrección: — . Reejecución: — . Pruebas automatizadas relacionadas: `activities.test_gifts.GiftFlowTests.test_duplicate_between_delegations_and_formats_and_cancelled`, `activities.test_gifts.GiftFlowTests.test_leading_zeros_and_points_share_canonical_rut`, `activities.test_gifts.GiftConcurrencyTests.test_two_simultaneous_submissions_only_create_one_registration` |

#### M-01, M-14 y M-16 (críticos de despliegue)

| Caso | Identificación | Preparación | Ejecución | Resultado | Seguimiento |
| --- | --- | --- | --- | --- | --- |
| M-01 | Ingreso por rol en AWS · ACC-01, AWS-02, RNF-004, RNF-005 · Alta | AWS con el commit evaluado; las seis cuentas de la sección 6.3 | 1. Ingresar con cada cuenta. 2. Revisar menú y delegación. 3. Hacer una lectura y una escritura permitidas. 4. Intentar una escritura no permitida | Esperado: menú y delegación según el rol; lo no permitido responde 403. Obtenido: — . Estado: **Pendiente de ejecución manual** | Responsable: Equipo. Fecha: — . Evidencia: una captura por rol. Defecto, corrección y reejecución: — |
| M-14 | Flujo completo en AWS · AWS-04, CA-01, CA-06 · Alta | AWS; `editorA` y `verificadorA`; período abierto con plan publicado | 1. Registrar una actividad. 2. Cargar 3 imágenes. 3. Aprobar como verificador. 4. Abrir Mi desempeño, el tablero de delegación y el Excel | Esperado: un solo incremento, igual en detalle, resumen y archivo. Obtenido: — . Estado: **Pendiente de ejecución manual** | Responsable: Equipo. Fecha: — . Evidencia: capturas y archivo Excel. Defecto, corrección y reejecución: — |
| M-16 | Instalación limpia y reversión · AWS-06 · Media | Equipo sin el proyecto; base MySQL desechable | 1. Clonar e instalar según el README. 2. `migrate` y `seed_demo`. 3. Respaldar la base (`mysqldump`) y anotar valores de control (un resultado de Mi desempeño, un ajuste de puntaje y un respaldo congelado). 4. `migrate analytics 0005`. 5. `migrate`. 6. Restaurar el respaldo y comparar los valores de control. 7. Volver al commit anterior y repetir el despliegue | Esperado: cada paso termina sin errores; la reversión aplica las conversiones documentadas (`MAX_PERCENTAGE` → `PERCENTAGE`, meta vacía → 0) y borra las columnas y tablas de `0006` a `0009`; tras restaurar el respaldo, los valores de control coinciden. Obtenido: — . Estado: **Pendiente de ejecución manual** | Responsable: Equipo. Fecha: — . Evidencia: salida de consola. Defecto, corrección y reejecución: — |

### 6.3 Perfiles de prueba

Las contraseñas no se escriben en el repositorio: las de la semilla salen de `SEED_DEMO_PASSWORD`
del `.env` local y las de las cuentas creadas a mano las guarda el responsable.

| Actor | Usuario | Delegación | Origen |
| --- | --- | --- | --- |
| Administrador | `adminA` | Global | Semilla `seed_demo` |
| Funcionario | `editorA` | Las Compañías | Semilla `seed_demo` |
| Usuario de consulta | `readerA` | Las Compañías | Semilla `seed_demo` |
| Usuario de consulta | `readerB` | Antena | Semilla `seed_demo` |
| Verificador | `verificadorA` | — | Creada a mano en AWS el 22-11-2026 |
| Delegado | `delegadoA` | — | Creada a mano en AWS el 22-11-2026 |
| Coordinador del sistema | `coordinadorA` | — | Creada a mano en AWS el 22-11-2026 |

**Hallazgo (D-16):** la semilla crea las cuentas `adminA`, `editorA`, `readerA`, `readerB`, `clientA`,
`clientB` (`common/management/commands/seed_demo.py:271`) y `adminEvalA` (con `provision_evaluation_admin`,
`common/management/commands/seed_demo.py:289`), pero ninguna para
los roles Verificador, Delegado y Coordinador. Por eso esas tres se crearon a mano en AWS, y un
entorno nuevo no puede repetir CU-DEMO-03 ni M-01 sin volver a crearlas (recomendación R-13). Este
documento no registra la delegación ni los permisos de esas cuentas porque no se verificaron desde
el repositorio; deben anotarse al ejecutar M-01.

### 6.4 Indicadores de ejecución (Guía de Evaluación 3, Actividad 4)

Dos niveles: las **pruebas automatizadas** (un método de prueba = una prueba) y los **casos del
plan** (84 del PP, 16 reglas de E3 de la sección 4.12 y 4 casos de la demostración). Un caso se
cuenta como ejecutado solo si tiene resultado obtenido completo: Aprobado (Cubierto y sus pruebas
pasaron) o Fallido. Un caso Parcial o Sin prueba queda pendiente.

| Indicador | Pruebas automatizadas | Casos del plan |
| --- | --- | --- |
| Planificadas | 796 | 104 (84 PP + 16 RC + 4 de la demostración) |
| Ejecutadas | 796 (corrida del 22-11-2026 18:44:57; igual el 18-11-2026) | 48 (45 aprobados + 3 fallidos) |
| Aprobadas | 796 | 45 (41 del PP + 4 RC) |
| Fallidas | 0 | 3: AWS-01 (sin HTTPS), RC-08 (registro aprobado editable, D-14) y RC-16 (tope 150 en vez de 120, D-13) |
| Bloqueadas | 0 en la corrida válida. La corrida de las 18:43:45 del 22-11-2026 quedó bloqueada entera (796 sin ejecutar) por MySQL detenido (INC-01) y se repitió | 0. Pendientes sin bloqueo: 56 (30 Parciales y 12 Sin prueba del PP; 7 Parciales y 3 Sin prueba de RC; 4 de la demostración) |
| Corregidas | 1 prueba: `common.test_modal_feedback.ModalFeedbackTests.test_inline_create_and_update_do_not_leave_a_confirmation_in_any_crud` (DEF-01) | 9 defectos corregidos con prueba de regresión (DEF-01 a DEF-09, sección 6.5) |
| Reejecutadas | 796 el 22-11-2026 sobre el mismo commit, y las 3 de `common.test_modal_feedback` en `8bbcd58` tras la corrección de DEF-01 (3 OK) | Los 9 defectos corregidos: sus pruebas de regresión pasaron en las corridas del 18-11-2026 y del 22-11-2026 |

### 6.5 Registro de defectos e incidencias

«Detectado por» indica cómo se encontró. Los defectos DEF-02 a DEF-09 se detectaron en las
revisiones de cierre de fase (sección 11); ese origen consta en la bitácora local del equipo
(`.claude/tmp`, no versionada). Lo verificable en git es el commit que trae la corrección y su
prueba de regresión.

| ID | Detectado por | Defecto y causa | Impacto | Corrección | Commit / PR | Resultado de la reejecución |
| --- | --- | --- | --- | --- | --- | --- |
| DEF-01 | Ejecución de la prueba sobre cada merge (18-11-2026, ficha 6.1) | `common.test_modal_feedback.ModalFeedbackTests.test_inline_create_and_update_do_not_leave_a_confirmation_in_any_crud` fallaba: `e29c3cc` (PR #49) hizo obligatorios el asunto y el tipo de actividad y la prueba no los enviaba (D-07) | Suite en rojo en `main` entre los PR #49 y #52; el comportamiento de la aplicación era el esperado | Solo se corrigió la prueba | `6bf1ef2` (PR #52, merge `8bbcd58`) | `8bbcd58`: 3 OK. `07064bd`: 796 OK (18-11-2026 y 22-11-2026) |
| DEF-02 | Revisión de cierre de fase | Cerrar el período no tomaba el bloqueo del registro de períodos antes de congelar | Un registro simultáneo podía quedar fuera del congelamiento | `close_period` toma el bloqueo antes de congelar | `8683f32` (PR #56, merge `9946086`) | `analytics.test_indicator_support.IndicatorSupportTests.test_close_period_takes_the_registry_lock_before_freezing` OK el 22-11-2026 |
| DEF-03 | Revisión de cierre de fase | Con un último tramo de cargo sin plan se perdía el tope del resultado final | Total sin tope en ese caso | El tope se conserva aunque el último tramo no tenga plan | `8683f32` (PR #56) | `analytics.test_indicator_support.IndicatorSupportTests.test_final_score_cap_survives_a_last_segment_without_plan` OK |
| DEF-04 | Revisión de cierre de fase | El respaldo congelado mostraba actividades archivadas sin exigir el permiso de archivo | Exposición de registros archivados | Filas archivadas solo con el permiso | `8683f32` (PR #56) | `analytics.test_indicator_support.IndicatorSupportTests.test_archived_activity_rows_need_the_archive_permission` OK |
| DEF-05 | Revisión de cierre de fase | El resumen no mostraba el desglose cuando el último tramo no tiene plan | Resumen y Excel incompletos | Resumen con aporte previo, ajuste y tope | `3dc3d61` (PR #58, merge `07064bd`) | `analytics.test_partial_plan_summary.PartialPlanSummaryTests` (5 pruebas) OK |
| DEF-06 | Revisión de cierre de fase | La bitácora de Ausencias no guardaba el motivo anterior al editar | Auditoría incompleta | Se audita motivo, fechas y tipo anteriores | `3dc3d61` (PR #58) | `analytics.test_measurement_rules.MeasurementRulesTests.test_absence_edit_audits_previous_reason_dates_and_kind` OK |
| DEF-07 | Revisión de cierre de fase | Ausencias ofrecía funcionarios archivados por defecto | Registros sobre personas que ya no están | Se excluyen por defecto; el historial es explícito y de solo lectura | `3dc3d61` (PR #58) | `analytics.test_measurement_rules.MeasurementRulesTests.test_absence_default_excludes_archived_officials_from_rows_and_choices`, `...test_absence_history_is_explicit_and_archived_official_is_read_only` OK |
| DEF-08 | Revisión de cierre de fase | La reversión de las migraciones de permisos (`accounts/0015`, `analytics/0008`) quitaba permisos que no había puesto | Pérdida de permisos asignados a mano al revertir | Reversión conservadora e idempotente | `3dc3d61` (PR #58) | `accounts.test_absence_seed_migration.Accounts0015RoundTripTests.test_grant_reverse_conservatively_and_grant_again`, `analytics.test_score_role_migration.ScoreRoleMigrationTests.test_reverse_preserves_manual_and_granted_permissions_and_reapply_is_idempotent` OK |
| DEF-09 | Revisión del PR #58 (mensaje del commit de corrección) | Regalos perdía la delegación de origen tras traspasar un territorio y no permitía gestionar campañas con catálogos inactivos | Inscripciones atribuidas a otra delegación; campañas sin poder cerrarse | Se conserva la delegación histórica y se permite anular y cerrar con catálogos inactivos | `654e257` (PR #58) | `activities.test_gifts.GiftFlowTests.test_delivery_preserves_original_delegation_after_territory_transfer`, `...test_inactive_original_delegation_keeps_history_and_allows_cancellation`, `...test_campaign_with_all_participants_inactive_remains_manageable_globally` OK |
| DEF-10 | Trazabilidad con E3 (22-11-2026) | Tope de 150 por defecto; E3 pide 120 % (D-13) | Resultados sobre 120 % se aceptan | Pendiente (R-10) | — | Abierto |
| DEF-11 | Trazabilidad con E3 y prueba exploratoria (22-11-2026) | Actividad con evidencia aprobada sigue editable (D-14) | Se puede cambiar un registro que ya puntuó | Pendiente (R-11) | — | Abierto. Severidad alta |
| DEF-12 | Trazabilidad con E3 (22-11-2026) | Reglas del cliente sin implementar (D-15) | Puntajes que E3 no aceptaría | Pendiente (R-12) | — | Abierto |
| DEF-13 | Preparación de la demostración (22-11-2026) | La semilla no crea cuentas Verificador, Delegado ni Coordinador (D-16) | Demostración no reproducible en un entorno nuevo | Cuentas creadas a mano en AWS; pendiente en la semilla (R-13) | — | Abierto |
| DEF-14 | Revisión del 18-11-2026 | Umbral colectivo guardado pero no aplicado (D-09) | RN-006 sin efecto | Pendiente (R-06) | — | Abierto |
| DEF-15 | `check --deploy` y GET a AWS (18-11-2026) | Sin HTTPS en AWS (D-10) | Credenciales y cookie en claro | Pendiente (R-01) | — | Abierto |
| INC-01 | Ejecución de la suite (22-11-2026 18:43:45) | Incidencia de configuración: el servicio MySQL de WAMP estaba detenido (`OperationalError 2002`) | La corrida quedó bloqueada | Se levantó WAMP y se repitió la suite | — | 796 OK a las 18:52:03 |

## 7. Resultados obtenidos vs esperados y discrepancias

Solo se incluyen discrepancias comprobadas en el código, el historial de git, el README o la matriz.

| ID | Caso | Esperado | Obtenido | ¿Coincide? | Causa | Acción |
| --- | --- | --- | --- | --- | --- | --- |
| D-01 | Matriz, hoja «PLAN y CON» (Gestión y planificación) | Ponderadores que suman 100 % (RN-001) | `D9 = SUM(D3:D8)` = 0,85 (85 %) | No | Falta una fila en el Excel | El SGR normaliza a 100 % (17,65 / 35,29 / 5,88 / 41,18), documentado en README «Supuestos y limitaciones»; validar con la municipalidad |
| D-02 | Matriz, hoja «AP ADM.» (Apoyo administrativo) | El total suma todas las filas (RF-024) | `I8 = SUM(I3:I6)` deja fuera la fila 7, Emergencia (peso 0,05) | No | Fórmula del Excel | El SGR suma todas las filas; `analytics.test_performance_calculator.KnownCaseTests.test_apoyo_administrativo_with_real_goals_and_weights` lo fija |
| D-03 | Valor del reclamo | Valor parametrizable y aprobado (RN-011 menciona −20 % y −30 %) | Hoja RECLAMOS `J3` = −0,2 y `J5` = 0,1 (felicitación); las hojas de cargo usan −0,3 por reclamo (p. ej. «AP ADM.» `E10`, «PLAN y CON» `D11`) y −0,2 en «COOR DISERCO» `D14` y «G SOC 1» `E16` | No | La matriz no es uniforme y la guía deja el valor pendiente; además la matriz lo aplica como fracción del total (%) y el SGR como puntos | Por defecto +10 y −20 puntos por versión del plan, editables; validar valor y unidad (puntos o %) |
| D-04 | CAL-D (PP B3) | Regla institucional de días computables | CAL-D es «un dato de ensayo propuesto, no una regla institucional»; el ejemplo de la guía (91 días, 61,54 % al 26-08) no coincide con el conteo inclusivo de CAL-D | No | Dos ejemplos con convenciones distintas | Por defecto, el ejemplo de la guía; el modo inclusivo reproduce CAL-D (`analytics.test_performance_calculator.ExpectedGoalAndTrafficLightTests.test_cal_d_complete_result_with_inclusive_count`) |
| D-05 | CAL-C (PP B3) y RF-018 | Cuatro estados (Ingresado, Pendiente, En proceso, Realizado) | CAL-C usa tres (Realizado, Pendiente, En proceso); el SGR agrega «Cancelado con justificación» | Parcial | La guía no define cancelados | Los cancelados con justificación salen del numerador y del denominador (`analytics.test_tube_cancellations`); pendiente de validación |
| D-06 | ACC-05 (A1, C2) | Recuperación con código de seis dígitos | Recuperación con enlace firmado de un solo uso (commit `2e6aa77`) | Parcial | Decisión de diseño: enlace con vigencia y espera entre envíos | Se prueban vigencia, reutilización y frecuencia sobre el enlace; documentarlo como adaptación |
| D-07 | `common.test_modal_feedback.ModalFeedbackTests.test_inline_create_and_update_do_not_leave_a_confirmation_in_any_crud` | Verde en `main` | Ejecutada el 18-11-2026 en cada merge: en `aa72d94` (PR #49) y `1f444ca` (PR #51) falla (`AssertionError: 200 != 204 : * subject` al crear y error al editar la actividad); en `8bbcd58` (PR #52) pasa (3 OK) | No | El PR #49 (`e29c3cc`) pasó a exigir asunto y tipo de actividad en el registro manual; la prueba no los enviaba | Corregida en `6bf1ef2` (llegó a `main` con el PR #52, `8bbcd58`); solo cambió la prueba |
| D-08 | Revisiones de código (PR #56 a #58) | Sin defectos altos abiertos | Se corrigieron: bloqueo del registro de períodos al cerrar (`close_period`), tope del resultado final con último tramo sin plan, actividades archivadas en el respaldo congelado, desglose sin plan en el último tramo, motivo anterior en la bitácora de Ausencias, funcionarios archivados en Ausencias y reversión conservadora de `accounts/0015` y `analytics/0008` | Sí, tras corregir | Hallazgos de revisión | Pruebas de regresión: `analytics.test_indicator_support.IndicatorSupportTests.test_close_period_takes_the_registry_lock_before_freezing`, `...test_final_score_cap_survives_a_last_segment_without_plan`, `...test_archived_activity_rows_need_the_archive_permission`, `analytics.test_partial_plan_summary`, `analytics.test_measurement_rules.MeasurementRulesTests.test_absence_edit_audits_previous_reason_dates_and_kind`, `...test_absence_default_excludes_archived_officials_from_rows_and_choices`, `analytics.test_score_role_migration`, `accounts.test_absence_seed_migration`. Origen: registros de las revisiones de Codex del equipo (`.claude/tmp`, no versionados) del 17-11-2026 |
| D-09 | CAL-03 / RN-006 | Umbral colectivo de 80 % configurable y aplicado (79,99 % no alcanza; 80 % alcanza) | `collective_threshold` se guarda en la versión del plan y se muestra, pero ningún cálculo ni tablero lo usa | No | Función no implementada | CAL-F ya existe (ítem porcentual personal, `analytics.test_performance_calculator.ProgressRulesTests.test_percentage_item_uses_done_commitments_cal_f`); falta el umbral colectivo: implementar el indicador colectivo con su fórmula aprobada y probar 79,99 / 80 / 80,01 % |
| D-10 | SEG-04, AWS-01 | Comunicaciones cifradas (RNF-006) | `check --deploy` en local: W004 (HSTS), W008 (SSL redirect), W012 y W016 (cookies seguras) y W018 (`DEBUG` en el `.env` local) | No | El servidor de prueba no tiene dominio ni certificado | Ver recomendación R-01 |
| D-11 | Reglas sin definición en la guía | Reglas aprobadas antes de declarar conformidad (PP B1) | Implementadas como supuestos: descuento de ausencias, cancelados, piso 0 del resultado final, máximo de tres felicitaciones, tope del resultado final, segregación al validar y permisos de Ausencias | Pendiente | La guía no las define | Listadas en README «Decisiones adicionales del proyecto, pendientes de validación»; validar con la municipalidad |
| D-12 | Semilla en bases ya desplegadas | `seed_demo` actualiza los roles de demostración | La protección de `seed_demo` detiene la carga y revierte si encuentra un rol con nombre de demostración sin la marca de la semilla o una cuenta que no reconoce (`accounts.test_seed_demo.SeedDemoTests.test_reseed_does_not_upgrade_a_custom_role_with_a_demo_name`, `accounts.test_seed_demo.SeedDemoSafetyTests.test_collision_does_not_link_or_overwrite_foreign_account_and_rolls_back`); los permisos nuevos llegan por migraciones de datos (`accounts/0015`, `analytics/0008`, `activities/0018`) | Parcial | Protección deliberada contra sobrescribir datos ajenos | Ver recomendación R-03 |
| D-13 | RC-16, CAL-02, RN-005 | E3: «tope máximo de cumplimiento de 120 %» por funcionario | `max_final_score` vale 150 por defecto (`analytics/models.py:60-64`; `MAX_FINAL_SCORE` en `analytics/services.py:26`) y el tope por ítem `max_computable` también (`analytics/models.py:34-36`). La matriz de la sección 4.11 decía «tope 150 %» siguiendo S1 y PP B3 | No | S1 y PP B3 piden 150 %; E3, posterior, pide 120 %. El tope es configurable por versión del plan (`analytics.test_indicator_support.IndicatorSupportTests.test_final_score_cap_is_configurable_used_and_frozen` lo fija en 120 y pasa), pero el valor por defecto no es el de E3 | Recomendación R-10 (prioridad alta). No se cambió código en esta fase |
| D-14 | RC-08 | E3: «Un registro aprobado no debe permitir modificaciones» | Prueba exploratoria del 22-11-2026 (ficha 6.1): con evidencia aprobada y período abierto, el `POST` de edición respondió 302 y guardó la nueva descripción. `check_mutable` (`common/maintainers.py:415-424`) solo rechaza actividades de atención social y de período cerrado; la fila del listado (`common/maintainers.py:243-247`) muestra «Editar» con el mismo criterio | No | La edición se bloquea por período cerrado (RN-013), no por aprobación | Recomendación R-11 (prioridad alta). No se corrigió en esta fase |
| D-15 | RC-01 a RC-04, RC-06, RC-10, RC-12 | Reglas del cliente de E3 implementadas | No se encontró implementación de: delegado como usuario que no contabiliza, puntaje condicionado a nombre y teléfono, límite diario de siete actividades, cierre semanal, respaldo formal del delegado para felicitaciones, contraseña temporal con cambio obligatorio en el primer ingreso, y edición de compromisos del Tubo restringida a su responsable (RC-10) (búsquedas en el código del 22-11-2026, sección 4.12) | No | E3 llegó después de S1 y del PP; esas reglas no estaban en ellos | Recomendación R-12 |
| D-16 | Sección 6.3, M-01, CU-DEMO-03 | Las cuentas de todos los roles de la demostración salen de la semilla | `seed_demo` no crea cuentas Verificador, Delegado ni Coordinador; `verificadorA`, `delegadoA` y `coordinadorA` se crearon a mano en AWS el 22-11-2026 | No | La semilla se diseñó para las cuentas de la segunda evaluación | Recomendación R-13 |

Los casos con cobertura automatizada dieron el resultado esperado en las ejecuciones de la ficha
(796 de 796 pruebas OK el 18-11-2026 y el 22-11-2026). Los 41 casos Cubiertos del PP y los 4
Cubiertos de la sección 4.12 se consideran Aprobados en su parte automatizada; AWS-01, RC-08 y RC-16
quedan Fallidos; los Parciales y Sin prueba dependen de los casos manuales de la sección 6.2 o de
funciones no implementadas (D-15).

## 8. Análisis y validación de resultados

- **Acceso y seguridad.** Se probaron ingreso, bloqueo, cierre, recuperación por enlace, permisos
  por operación con 403 auditado, acceso fuera de ámbito con 404 auditado y entradas adversas. La
  validación usa las cuentas y ámbitos de la semilla (dos delegaciones). Sin prueba: el recorrido
  real por rol en AWS, el botón Atrás y el transporte cifrado. Riesgo **medio**: sin HTTPS las
  credenciales y la cookie de sesión viajan en claro en el servidor de prueba.
- **Mantenedores y catálogos.** Los seis CRUD y los catálogos tienen ciclo completo, duplicados,
  longitudes máxima y máxima + 1, desactivación lógica con historia, exportación de todas las
  páginas sin campos internos y edición simultánea. Sin prueba automatizada: los diálogos de
  SweetAlert2 y las normas gráficas. Riesgo **bajo**.
- **Medición y semáforo.** Se validó con datos independientes: CAL-A (62 puntos), CAL-B (90 con tope
  150 %, el de S1 y PP; E3 pide 120 %, D-13), CAL-C exacto (8 Realizados, 1 Pendiente, 1 En proceso = 80 %, meta 80 % = 100 %), CAL-D
  inclusivo (3,33 % el día 1 y 50 % el 15-10), CAL-E en sus cuatro fronteras sin redondeo, el ejemplo
  de la guía (91 días, 61,54 % al 26-08) y los pesos y metas reales por cargo de la matriz (por
  ejemplo Apoyo administrativo y el tope del Coordinador). Sin prueba: el umbral colectivo (D-09) y
  la excepción formal a la suma de 100 %. Riesgo **medio**: varias reglas numéricas siguen como
  supuestos sin aprobación (D-01, D-03, D-11).
- **Evidencias.** Aprobación única aunque haya varias imágenes, rechazo con motivo sin puntaje,
  anulación que recalcula una sola vez, autor que no puede revisar y alertas a revisores en su
  ámbito. Sin prueba: dos verificadores simultáneos (EVI-06), la inmutabilidad del código de
  actividad (EVI-01), el recorrido completo rechazo → corrección → aprobación por la interfaz
  (EVI-04) y el registro de autor, fecha y metadatos (EVI-02, EVI-03). Riesgo **medio** por concurrencia: el código bloquea la fila, pero no hay
  prueba que lo demuestre.
- **Agenda.** Creación desde actividad y caso, alerta de vencimiento, atraso visible en período
  cerrado, cancelación con justificación y reasignación auditada. Sin prueba: la matriz completa de
  transiciones con una prohibida (AGE-03) y la falta de responsable (AGE-02). Riesgo **bajo**.
- **Tableros e informes.** El total de la delegación sale de los resultados individuales y concilia
  con el detalle y con el Excel; la vista por cargo respeta filtros y congelamiento; la actividad
  reciente cuenta días corridos; el piso 0 se refleja igual en panel, API, tablero y Excel. Sin
  prueba: tiempos bajo carga multiusuario y exportación de 10.000 registros. Riesgo **medio** hasta
  medir en AWS.
- **API.** Tokens con vencimiento y revocación por cambio de contraseña, bloqueo compartido con el
  login, autorización por delegación con auditoría, conciliación del total (base + ajustes, con tope
  y piso) y resultados congelados. Riesgo **bajo**.
- **Reglas del cliente de E3.** De 16 reglas trazadas, 4 están Cubiertas (ausencias, solo lo
  aprobado cuenta, token de recuperación y acceso a evidencias), 7 son Parciales, 3 no tienen
  implementación y 2 fallan: el registro aprobado sigue editable (D-14) y el tope por defecto es 150
  en vez de 120 (D-13). Riesgo **alto**: E3 exige estas reglas en la demostración del 27-11-2026, y
  dos de las fallidas cambian el puntaje o permiten modificar lo que ya puntuó.

## 9. Recomendaciones

| ID | Recomendación | Ligada a | Prioridad | Responsable sugerido |
| --- | --- | --- | --- | --- |
| R-01 | Publicar el SGR con dominio y certificado (HTTPS) y activar `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` y `DEBUG=False`; repetir `check --deploy` sin advertencias | D-10, SEG-04, AWS-01 | Alta | Responsable de despliegue |
| R-02 | Validar con la municipalidad las reglas pendientes: suma de «Gestión y planificación», Emergencia en «AP ADM.», valor y unidad de reclamos y felicitaciones, cancelados, ausencias, piso 0, tope del total y segregación | D-01 a D-05, D-11 | Alta | Jefatura de proyecto con la contraparte municipal |
| R-03 | Agregar una vía explícita y auditada para actualizar los roles de la semilla en bases ya desplegadas (migración de datos por permiso nuevo, como `accounts/0015`, o un comando con `--dry-run` que muestre la diferencia) en vez de depender de `seed_demo` | D-12 | Media | Desarrollo |
| R-04 | Ejecutar `scripts/prueba_carga.py` en AWS con carga baja y luego los escalones B18 aprobados (M-12); definir la herramienta y ejecutar los escenarios de tablero, exportación, escrituras y estrés que el script no cubre (M-19); repetirlo en cada entrega y registrar p95, máximo y errores | REN-01 a REN-06, M-12, M-19 | Media | Responsable de pruebas |
| R-05 | Ejecutar y registrar los casos manuales M-01 a M-19 y los de la demostración (CU-DEMO-01 a CU-DEMO-03, REG-DEMO-01) con evidencia (captura, archivo o salida), en LOCAL y en AWS con el mismo commit | Sección 6.2 | Alta | Sebastián Alzamora (responsable de pruebas) |
| R-06 | Implementar el indicador colectivo con `collective_threshold` y probar 79,99 / 80 / 80,01 % | D-09, CAL-03 | Media | Desarrollo |
| R-07 | Agregar pruebas automatizadas faltantes: dos verificadores simultáneos (EVI-06), inmutabilidad del código de actividad (EVI-01), recorrido rechazo → corrección → aprobación por la interfaz (EVI-04), autor y metadatos de la evidencia (EVI-02), matriz de transiciones de agenda con una prohibida (AGE-03) y compromiso sin responsable (AGE-02) | EVI-01, EVI-06, AGE-02, AGE-03 | Media | Desarrollo |
| R-08 | Preparar volúmenes de 5.000 y 10.000 registros con semilla reproducible para REN-01 y REN-03 | REN-01, REN-03 | Baja | Desarrollo |
| R-09 | Definir y probar respaldo y restauración (RPO 24 h, RTO 4 h) y monitoreo básico de disponibilidad | INT-05, INT-06 | Media | Responsable de despliegue |
| R-10 | Alinear el tope con E3: llevar el valor por defecto de `max_final_score` (y, si la contraparte lo confirma, de `max_computable`) a 120 con una migración de datos para las versiones en borrador, sin tocar las publicadas ni los períodos congelados; actualizar CAL-02/RN-005 y sus pruebas | D-13, RC-16 | Alta | Desarrollo, con validación de la jefatura de proyecto |
| R-11 | Bloquear la edición, el archivado y el cambio de ítem o fecha de una actividad con evidencia aprobada vigente (en `check_mutable` y en la fila del listado), permitiendo solo la anulación auditada; agregar la prueba de regresión que convierta la prueba exploratoria en automatizada | D-14, RC-08, RC-10 | Alta | Desarrollo |
| R-12 | Implementar y probar las reglas del cliente pendientes de E3 (delegado, nombre y teléfono, límite diario, cierre semanal, respaldo del delegado, contraseña temporal con cambio obligatorio), empezando por las que afectan el puntaje | D-15, RC-01 a RC-04, RC-06, RC-12 | Alta | Desarrollo, con validación de la contraparte municipal |
| R-13 | Agregar a `seed_demo` cuentas de prueba para Verificador, Delegado y Coordinador (por ejemplo `verificadorA`, `delegadoA` y `coordinadorA`) con la misma clave de `SEED_DEMO_PASSWORD`, y su prueba en `accounts.test_seed_demo` | D-16 | Media | Desarrollo |
| R-14 | Ejecutar los casos de la demostración (CU-DEMO-01 a CU-DEMO-03, REG-DEMO-01) antes del 27-11-2026 y registrar lo obtenido en sus fichas | Sección 6.2 | Alta | Sebastián Alzamora |

## 10. Indicadores de cierre (PP B21)

«Aprobado» solo se usa para un caso Cubierto cuyas pruebas pasaron en la ficha. Un caso Parcial no
cuenta como Aprobado mientras su parte manual siga pendiente.

| Indicador | Valor |
| --- | --- |
| Casos diseñados en el PP | 84 |
| Variantes adicionales creadas | 9 áreas de la sección 4.10 (casos sociales, Oficina de Partes, portal, regalos, ausencias, tramos, API, congelamiento, WebSocket), 16 reglas de E3 (RC-01 a RC-16), 4 casos de la demostración y 19 casos manuales M-01 a M-19 |
| Casos aplicables al incremento | 84 del PP; 104 con RC y la demostración |
| Cobertura de diseño del PP (automatizada) | Cubierto 41 · Parcial 30 · Sin prueba 12 · Fallido 1 |
| Aprobados / fallidos (PP) | 41 / 1 (AWS-01: sin HTTPS) |
| Bloqueados / no ejecutados / no aplica (PP) | 0 / 42 (30 Parciales con parte manual o sin implementar pendiente y 12 Sin prueba) / 0 |
| Cobertura ejecutada (PP) | (41 + 1) / 84 × 100 = **50,0 %** |
| Tasa de aprobación (PP) | 41 / (41 + 1) × 100 = **97,6 %** |
| Con RC y la demostración | Ejecutados 48 de 104 = **46,2 %**; aprobados 45 de 48 = **93,8 %** (fallidos: AWS-01, RC-08, RC-16) |
| Defectos críticos / altos abiertos | 0 / 3: D-13 (tope 150 en vez de 120), D-14 (registro aprobado editable) y D-15 (reglas de E3 sin implementar). Abiertos de severidad media: D-09 (umbral colectivo sin aplicar), D-10 (sin HTTPS) y D-16 (semilla sin cuentas de tres roles) |
| Pruebas automatizadas | 796 ejecutadas, 796 OK, 0 omitidas (18-11-2026 y 22-11-2026) |
| Versión evaluada y fecha de cierre | `07064bd`; corridas del 18-11-2026 y del 22-11-2026 |
| Decisión de aceptación | Propuesta del equipo: **Aceptado con condiciones** (R-01, R-02, R-05, R-10, R-11 y R-12). Decisión del docente o responsable: pendiente |

## 11. Revisión

La revisión es una práctica de calidad aplicada en cada fase de trabajo, antes de dar un cambio por
listo y sin hacer commit durante el proceso. La definición del flujo y de los agentes vive en
`.claude/` (no versionada en el repositorio).

1. **Suite completa.** Se ejecutan `python manage.py test --noinput` en MySQL y
   `python manage.py makemigrations --check --dry-run`. Un fallo se corrige en su causa y la suite
   se repite hasta pasar entera.
2. **Revisión de Codex, en una o dos rondas.** Un revisor de solo lectura analiza los cambios sin
   commitear o la rama contra `main`. Se corrigen los hallazgos confirmados de severidad alta y
   media, se repiten la suite y la revisión, y como máximo se hacen dos rondas; lo que queda se lista
   como pendiente, sin ocultarlo.
3. **Trazabilidad con spec-checker.** Se compara lo implementado con los requisitos de la fase
   (RF, RN, RNF, HU y CA de S1, y desde esta fase las reglas de E3) y se obtiene una tabla de
   cumplimiento con evidencia.

Resultado verificable de esta práctica en el historial:

- Defectos detectados en la revisión y corregidos antes del merge, cada uno con su prueba de
  regresión: DEF-02 a DEF-04 en `8683f32` (PR #56), DEF-05 a DEF-08 en `3dc3d61` (PR #58) y DEF-09
  en `654e257` (PR #58). Sus pruebas pasaron en las corridas del 18-11-2026 y del 22-11-2026.
- Un fallo de la suite en `main` (DEF-01) se detectó al ejecutar la prueba sobre cada merge y se
  corrigió en `6bf1ef2` (PR #52).
- Las decisiones que la revisión no puede cerrar porque dependen del cliente quedan listadas en la
  sección «Decisiones adicionales del proyecto, pendientes de validación» del README y en D-11.
- La trazabilidad con E3 de esta fase (sección 4.12) encontró DEF-10 a DEF-13; quedan abiertos con
  recomendación porque esta fase solo cambia documentación y `scripts/prueba_carga.py`.

Este documento no afirma aprobaciones de revisores en GitHub: los PR se integraron con merge, pero
su revisión formal en la plataforma no se verificó para este informe.

<a id="reevaluacion-rc08-rc16"></a>

## Reevaluación de RC-08 y RC-16 · 23-11-2026

Versión probada: cambios locales sobre `0fc9ad7`. Entorno de verificación: Django 5.2.17 y MySQL local con base temporal de pruebas. La ejecución del 22-11-2026 documentó 45 de 48 criterios aprobados. Esta reevaluación da seguimiento a dos de los tres fallos de ese corte.

| Criterio y defecto | Procedimiento automatizado | Resultado esperado |
| --- | --- | --- |
| RC-08 · D-14 / DEF-11 | Abrir la edición de una actividad manual en período abierto, crear dos aprobaciones e intentar cambiar fecha, ítem, descripción o archivar. Retirar las aprobaciones de una en una. | Con una o más aprobaciones vigentes se ocultan las acciones y el servidor conserva los datos, incluso ante un formulario abierto previamente. Una vez anulada la última aprobación, un editor autorizado vuelve a poder guardar. |
| RC-16 · D-13 / DEF-10 | Calcular 150 puntos base, comprobar el máximo final, agregar ajustes en otro caso y consultar el panel y la API. Probar un plan publicado anterior, una revisión, un límite inferior y un cierre histórico. | Máximo individual de 120 puntos después de los ajustes. Se respeta un límite inferior del plan y se conserva el valor histórico al consultar un cierre. El cumplimiento por ítem conserva su regla propia (CAL-02 / RN-005). |
| Migración de RC-16 | Migrar borradores con topes de 200 y 90 y una versión publicada con 150. | Los topes resultantes son 120, 90 y 150 respectivamente. El cálculo en vivo utiliza como máximo 120. La reversión del esquema conserva los topes ajustados de los borradores. |

**Resultado obtenido.** RC-08 y RC-16 aprobados en la reejecución automatizada. La suite completa ejecutó **798 pruebas en 161,810 s** con resultado `OK`, sin fallos, errores ni pruebas omitidas. Se utilizó `python manage.py test --settings=rc_migration` con una configuración temporal que aisló el nombre de la base de pruebas MySQL y las carpetas de archivos. Django eliminó la base temporal al finalizar. Se verificaron el HTML de la vista y las respuestas del servidor, incluida la respuesta HTTP 423 al guardar una edición bloqueada desde el modal. La interacción visual entre dos navegadores quedó pendiente de prueba manual.

**Cómo reproducir las verificaciones en una base de pruebas de MySQL**

```bash
python manage.py test activities.test_activity_completion.ActivityCompletionTests.test_current_approvals_block_manual_edits_and_archiving activities.test_evidence
python manage.py test analytics.test_final_score_cap_migration analytics.test_indicator_support analytics.test_score_adjustments analytics.test_measurement_configuration sgr_api.tests
python manage.py test
```

La pauta de esta entrega admite HTTP según la aclaración del equipo. AWS-01 conserva su anotación histórica y queda fuera de esta reevaluación. La regla de titularidad de compromisos de la Agenda (RC-10) tiene seguimiento independiente.

<a id="verificacion-pendientes-local"></a>

## Verificación de casos pendientes · 23-11-2026

**Balance para la presentación.** Se verificaron 20 criterios que figuraban como pendientes en el protocolo. Diecisiete cumplieron su resultado esperado y en tres se reprodujo un incumplimiento. Cada criterio se cuenta una sola vez, aunque requiera varias pruebas.

| Corte acumulado sobre los mismos 104 criterios | Aprobados | Fallidos | Pendientes | Evaluados |
| --- | ---: | ---: | ---: | ---: |
| Informe del 22 de noviembre | 45 | 3 | 56 | 48 |
| Tras repetir RC-08 y RC-16 | 47 | 1 | 56 | 48 |
| Tras verificar otros 20 criterios el 23 de noviembre | **64** | **4** | **36** | **68** |

De los cuatro fallos del acumulado, tres son las reglas locales detalladas más abajo. El cuarto es AWS-01 por HTTPS en el corte histórico. El equipo indicó que la entrega académica admite HTTP. Se conserva el denominador original y se identifica AWS-01 por separado. Esta ejecución no evalúa el despliegue actual.

### Ficha de ejecución y reproducción

- **Versión y entorno.** Copia de trabajo sobre `0fc9ad7`, con los cambios locales de RC-08 y RC-16. Django 5.2.17, datos ficticios, base de pruebas MySQL y carpetas temporales de imágenes. La suite de Django ejecutó **808 pruebas en 162,275 s**, con resultado `OK`, sin errores, fallos ni omisiones. El caso simultáneo EVI-06 se ejecutó en MySQL con dos conexiones. Después se amplió CAT-04 para cambiar también el nombre del tipo principal y se repitió individualmente con resultado `OK`.
- **Navegador.** Brave con Chromium 158.0.8127.42, controlado por Playwright contra Django/ASGI local. Se utilizaron una base SQLite separada, sesiones ficticias y un buzón de archivos para la recuperación. La interfaz cargó Bootstrap y SweetAlert2. Las cinco comprobaciones de navegador se ejecutaron aparte de la suite. No se evaluó la entrega por un proveedor SMTP ni la compatibilidad con otros navegadores.
- **Reglas E3.** En otra base de pruebas MySQL se ejecutaron tres comprobaciones de aceptación independientes. Resultado: tres diferencias de comportamiento reproducidas, cero errores de preparación en la ejecución final. Sus pasos y valores observados se indican abajo. Los tres fallos de aceptación son compatibles con una suite de regresión en verde, porque evalúan exigencias adicionales.
- **Reproducción de la suite.** Desde la raíz, con configuración de QA, usuario habilitado para crear y eliminar la base de pruebas y directorios temporales para los archivos, ejecutar `python manage.py test`. Para repetir el lote directamente relacionado con las nuevas comprobaciones:

```bash
python manage.py test accounts.test_official_crud accounts.test_user_crud activities.test_activity_completion activities.test_case_follow_up activities.test_evidence agenda.test_commitments agenda.test_internal_comments
```

### Criterios aprobados en MySQL

| Criterio | Prueba y resultado obtenido | Archivo y método reproducible |
| --- | --- | --- |
| ADM-01 | Una delegación creada desde el mantenedor apareció inmediatamente en el filtro del tablero y se pudo asignar a un funcionario nuevo. Se comprobó la delegación guardada. | [Funcionarios](accounts/test_official_crud.py) · `test_new_delegation_is_available_for_filtering_and_assignment` |
| CAT-04 | Tras renombrar el tipo y la subatención desde sus mantenedores, el detalle de la atención anterior siguió accesible, mostró ambas etiquetas nuevas y conservó ambas relaciones. | [Seguimiento de atenciones](activities/test_case_follow_up.py) · `test_catalog_rename_keeps_the_existing_attention_consultable` |
| EVI-01 | Al crear y editar desde el mantenedor, el sistema conservó el código generado y guardó el cambio válido de descripción aunque se enviara otro código. | [Registro de actividad](activities/test_activity_completion.py) · `test_registration_code_is_generated_and_survives_edits` |
| EVI-02 | La carga conservó autor, etapa, fecha, nombre original y formato. El tamaño registrado correspondió al archivo privado de prueba. | [Evidencias](activities/test_evidence.py) · `test_upload_and_review_record_metadata_and_audit` |
| EVI-03 | La aprobación registró verificador, fecha, decisión y observación. La bitácora identificó al actor y el paso de pendiente a aprobada. | [Evidencias](activities/test_evidence.py) · `test_upload_and_review_record_metadata_and_audit` |
| EVI-04 | Mediante los formularios HTTP, el autor realizó cargas sucesivas y el verificador rechazó, pidió corrección y luego aprobó. El avance fue 0, 0 y 1. Repetir la aprobación lo mantuvo en 1. | [Evidencias](activities/test_evidence.py) · `test_rejected_and_corrected_uploads_count_only_after_approval` |
| EVI-06 | Dos verificadores enviaron decisiones incompatibles sobre el mismo lote. Se aceptó una sola decisión por imagen y hubo un único evento de revisión del lote. El segundo intento recibió el aviso de que ya no estaba pendiente. | [Revisión concurrente](activities/test_evidence.py) · `test_two_reviewers_leave_one_decision_and_one_audit_record` |
| AGE-02 | La Agenda rechazó crear un compromiso sin responsable y no guardó filas. En la misma suite pasaron las validaciones de fecha y territorio que ya cubrían el resto del criterio. | [Compromisos](agenda/test_commitments.py) · `test_creation_requires_a_responsible_official` |
| AGE-03 | Se comprobaron las 25 combinaciones entre los cinco estados. Cada transición permitida dejó un evento con autor, origen y destino. Las prohibidas y las repeticiones conservaron el estado y el historial. | [Compromisos](agenda/test_commitments.py) · `test_every_status_transition_preserves_consistent_history` |
| AGE-04 | Dos días antes del vencimiento, la bandeja mostró el motivo y la fecha correcta. Su enlace abrió el compromiso correspondiente. | [Compromisos](agenda/test_commitments.py) · `test_alert_shows_reason_date_and_working_link_before_due_date` |
| TAB-05 | Una segunda cuenta autorizada de la misma delegación leyó desde el detalle el comentario publicado por la primera. El sistema conservó la autoría original. | [Comentarios internos](agenda/test_internal_comments.py) · `test_another_authorized_official_reads_the_activity_comment` |
| RC-14 | La cuenta creada desde el mantenedor guardó un hash PBKDF2-SHA256 con sal y el factor de trabajo configurado. La contraseña válida coincidió y otra fue rechazada. | [Creación de usuarios](accounts/test_user_crud.py) · `test_create_user_with_official_profile` |

### Resultados de los recorridos en navegador

Ejecutados en QA local el 23-11-2026. Las filas M-02 a M-06 identifican los escenarios de la ficha 6.2 y no aumentan el total de criterios. Cada recorrido utiliza datos descartables.

| Ficha y criterio | Preparación y pasos para repetir | Resultado observado |
| --- | --- | --- |
| M-02 · ACC-03 | 1. Ingresar con un funcionario con acceso a Ingreso de atención. 2. Abrir el formulario y cerrar sesión. 3. Pulsar Atrás y recargar. | El formulario protegido dejó de mostrarse. Al recargar apareció el inicio de sesión. **Aprobado**. |
| M-03 · ACC-06 | 1. Solicitar recuperación para una cuenta activa con correo de prueba. 2. Abrir el enlace recibido en su buzón y guardar una contraseña nueva. 3. Probar el ingreso con la anterior y con la nueva. | SweetAlert2 mostró «Tu contraseña fue actualizada». La clave anterior no permitió abrir la pantalla protegida y la nueva sí. **Aprobado**. |
| M-04 · CAT-06 | 1. Abrir Delegaciones con permiso de edición y elegir una delegación activa. 2. Pulsar Desactivar y luego Cancelar en el diálogo. 3. Recargar la lista. | No hubo envío del formulario ni aviso de éxito. La fila conservó sus valores y continuó ofreciendo Desactivar. **Aprobado**. |
| M-05 · ACT-05 | 1. Preparar dos tipos con subatenciones diferentes. 2. En Ingreso de atención seleccionar el primer tipo y su subatención. 3. Cambiar al segundo tipo. | Se limpió la selección anterior, su opción quedó deshabilitada y se pudo elegir la subatención válida del segundo tipo. **Aprobado**. |
| M-06 · UX-01 | 1. Abrir Delegaciones con filas ficticias Centro y Sur. 2. Buscar Centro, esperar «Buscando…», borrar y escribir Sur rápidamente. 3. Limpiar la búsqueda y repetir con el navegador sin red. | El último filtro mostró solo Sur, al limpiar volvieron ambas filas y el error de red fue visible. **Aprobado**. |

### Reglas E3 con incumplimiento reproducido

| Regla | Cómo reproducir en un entorno de pruebas | Resultado esperado | Resultado observado el 23-11-2026 |
| --- | --- | --- | --- |
| RC-02 · Datos del solicitante | 1. Usar un funcionario de Apoyo administrativo con plan publicado y avance inicial 0. 2. Preparar una actividad del ítem «Atención de usuario teléfono y presencial» con evidencia aprobada, nombre de contacto y teléfono vacíos. 3. Calcular el desempeño del período. | La actividad aporta cero puntos. | El avance subió a 1 y el ítem aportó aproximadamente 0,0833 puntos ponderados. **Fallido**. |
| RC-03 · Máximo diario | 1. Usar un editor autorizado, un funcionario y un día del período abierto sin actividades. 2. Guardar ocho actividades manuales distintas para ese funcionario y esa fecha. 3. Contar las filas vigentes. | Como máximo se guardan siete. | El octavo envío desde el formulario devolvió HTTP 204 y quedaron ocho actividades. **Fallido**. |
| RC-12 · Primer ingreso | 1. Crear un funcionario desde Usuarios y asignar la clave inicial. 2. Ingresar desde una sesión nueva. 3. Intentar abrir Mi perfil antes de cambiar la clave. | Se exige cambiar la contraseña inicial antes de usar el sistema. | La sesión llegó a Inicio y abrió el perfil del funcionario sin exigir el cambio. **Fallido**. |

Estos hallazgos actualizan la evidencia de D-15. Para cerrar cada uno se requiere corregir su comportamiento y repetir el caso con el mismo resultado esperado.

### Inventario de los 36 criterios pendientes

| Grupo | Cantidad | Identificadores pendientes |
| --- | ---: | --- |
| Plan de pruebas funcional, interfaz y seguridad | 12 | ACC-01, PAR-02, PAR-03, PAR-06, AGE-05, CAL-03, UX-04, UX-05, UX-06, SEG-04, SEG-05, SEG-06 |
| Integridad y recuperación | 3 | INT-04, INT-05, INT-06 |
| Rendimiento y carga | 6 | REN-01 a REN-06 |
| Despliegue | 5 | AWS-02 a AWS-06 |
| Reglas del cliente | 6 | RC-01, RC-04, RC-05, RC-06, RC-10, RC-11 |
| Demostraciones con sus evidencias | 4 | CU-DEMO-01, CU-DEMO-02, CU-DEMO-03, REG-DEMO-01 |

Los casos que exigen AWS, otros navegadores, restauración o pruebas de carga conservan sus condiciones originales. Para una próxima sesión local se pueden priorizar los recorridos de demostración CU-DEMO-02 (actividad) y REG-DEMO-01 (regalos) y guardar las capturas previstas en la ficha 6.2.

<a id="alcance-semestral"></a>

## Correcciones de RC-02, RC-03 y RC-12 y alcance HTTP del semestre · 23-11-2026

La evaluación académica requiere acceso por **HTTP durante todo el semestre**. HTTPS queda como mejora futura. En AWS-01, las respuestas HTTP están documentadas en la sección 5.3 y sigue pendiente identificar la versión desplegada. Para este corte, AWS-01 queda **pendiente de confirmar el despliegue**, sin fallo atribuible a HTTPS. En SEG-04, el cifrado del transporte también queda fuera de la exigencia semestral. Las mediciones anteriores conservan su fecha y alcance.

| Regla | Reejecución local con datos ficticios | Evidencia reproducible |
| --- | --- | --- |
| RC-02 | Se aprobó la evidencia de una actividad del plan. Sin nombre, con nombre en blanco o sin teléfono aportó cero. Con nombre y teléfono aportó una unidad. En las atenciones automáticas los datos se consultan en la ficha del solicitante. | [Cálculo individual](analytics/test_performance_calculator.py) · `test_approved_activity_requires_contact_name_and_phone`. [Conciliación territorial](analytics/test_performance_panel.py) · `test_territorial_totals_reconcile_with_detail_and_keep_individual_progress`. |
| RC-03 | Siete altas manuales del mismo funcionario y fecha fueron aceptadas. La octava mostró el límite y se conservaron siete filas. En Ingreso de atención, superar el cupo tampoco dejó una gestión ni un caso adicional. Crear, mover y restaurar usan el cupo del funcionario y fecha de destino dentro del bloqueo transaccional de períodos. | [Actividades](activities/test_activity_completion.py) · `test_daily_limit_rejects_eighth_activity`. [Ingreso de atención](activities/test_case_follow_up.py) · `test_eighth_automatic_activity_rolls_back_attention_and_case`. |
| RC-12 | Una cuenta nueva fue dirigida al cambio de contraseña al intentar entrar al perfil. Reutilizar la clave inicial mantuvo la restricción. Guardar una diferente permitió acceder. Se comprobó también el rechazo de la solicitud de token con la contraseña inicial y la recuperación mediante un enlace de prueba. | [Alta y primer ingreso](accounts/test_user_crud.py) · `test_create_user_with_official_profile`. [Recuperación](accounts/test_auth_flows.py) · `test_recovery_replaces_initial_password_before_access_is_enabled`. |

La migración `accounts/0016_initial_password` crea el registro de cambio obligatorio para las altas posteriores desde los mantenedores. No asigna contraseñas ni modifica cuentas preexistentes. Estas verificaciones corresponden a bases de pruebas y no acreditan que la nueva versión esté desplegada en AWS.

**Resultado final.** La suite completa de Django sobre MySQL local ejecutó **812 pruebas en 166,981 s**, con resultado `OK`, sin fallos, errores ni omisiones. Se ejecutó `python manage.py test --settings=qa_diagnostic_settings --noinput` con una configuración temporal que aisló la base y los directorios de archivos. Django eliminó la base de pruebas al finalizar. Se comprobó también que los modelos coinciden con las migraciones. Por autorización del equipo se aplicó únicamente `accounts.0016_initial_password` a la base local de desarrollo y se verificó la existencia de su tabla.

**Balance semestral sobre los 104 criterios originales:** 67 aprobados, 0 fallidos y 37 pendientes de verificación. Los tres casos RC pasan de fallidos a aprobados. A los 36 pendientes anteriores se suma la confirmación de la versión desplegada de AWS-01. La ausencia de HTTPS no es un defecto de esta evaluación.

### Revisión de SEG-04 bajo el alcance HTTP semestral · 23-11-2026

**SEG-04 aprobado para la evaluación semestral.** Se repitieron individualmente las seis pruebas identificadas en la fila SEG-04 de la sección 4 (auditoría de edición de cuenta, exportación filtrada de usuarios, rechazo de clave actual incorrecta, auditoría de intentos y bloqueo, auditoría de ingreso y salida, y bloqueo en la emisión de tokens). Django ejecutó las seis en una base temporal SQLite con datos ficticios en 4,282 s, con resultado `OK`. La corrida completa anterior también las incluyó en MySQL. Esta evidencia corresponde a los controles de aplicación. El transporte HTTPS está fuera de la evaluación según la aclaración del equipo. Esta revisión no comprueba la configuración de AWS.

**Balance actualizado:** 68 criterios aprobados, 0 fallidos y 36 pendientes sobre 104. AWS-01 sigue pendiente de identificar la versión desplegada.

### Comprobación pública de AWS-01 por HTTP · 23-11-2026

Desde fuera de la instancia, una petición GET a la raíz de `http://34.201.192.78` devolvió 302 hacia `/accounts/login/`. El destino respondió 200 con HTML, formulario POST y campo de contraseña. Las dos hojas de estilo del mismo sitio enlazadas por esa página, `/static/css/styles.css` y `/static/css/client-portal.css`, respondieron 200 con tipo `text/css` y contenido. Se comprobó la respuesta HTTP sin iniciar sesión. Para completar AWS-01 queda comparar el commit de la copia desplegada con la revisión evaluada. El balance continúa en 68 aprobados y 36 pendientes.

### Cierre de AWS-01 · 23-11-2026

**Aprobado para la evaluación semestral por HTTP.** El equipo ejecutó `git -C /var/www/proyecto_integrado rev-parse HEAD` en EC2 y obtuvo `07064bd1b9b2ac27010c979a0c88c30ccc30b117`. Corresponde al merge del PR #58 y coincide con el commit evaluado en la sección 1. Esta identificación completa la comprobación HTTP descrita arriba.

Las correcciones RC-02, RC-03 y RC-12 se probaron en la copia local y aún están sin commit. El hash de EC2 identifica la revisión del repositorio en disco. Por sí solo no acredita cambios sin commit en el servidor ni la ejecución allí de la suite local.

**Balance acumulado del semestre:** 69 aprobados, 0 fallidos y 35 pendientes sobre 104 criterios.
