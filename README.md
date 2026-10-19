# Proyecto Integrado

Aplicación web en Django con Django Admin personalizado y base de datos MySQL.
Proyecto de la asignatura Programación Back End (TI3041) – Evaluación Sumativa II.

**Equipo:** `Amaru Marin/Sebastian Alzamora/Benjamin Ocaranza/Vicente Ibarra`
**Sección:** `P2-C1`

## Requisitos previos

- Python 3.10 o superior
- Git
- MySQL en ejecución
- En Windows se recomienda usar Git Bash

## Instalación y ejecución

### 1. Clonar el repositorio

```bash
git clone https://github.com/amaruprog14/proyecto_integrado.git
cd proyecto_integrado/
```

### 2. Crear y activar el entorno virtual

```bash
python -m venv .venv
```

En macOS/Linux:

```bash
source .venv/bin/activate
```

En Windows con Git Bash:

```bash
source .venv/Scripts/activate
```

### 3. Instalar dependencias

```bash
python -m pip install -r requirements.txt
```

Dependencias principales: Django 5.2, mysqlclient y python-dotenv (ver `requirements.txt`).

### 4. Configurar variables de entorno

Copiar el archivo de ejemplo y completar los valores reales:

```bash
cp .env.example .env
```

Para generar una `SECRET_KEY` nueva:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

> El archivo `.env` contiene credenciales y **no se versiona** en Git.
> `settings.py` lee estas variables desde el entorno (con `python-dotenv`); para cambiar de
> base de datos solo se edita el `.env`, nunca el código.

### 5. Crear la base de datos

Desde el cliente de MySQL:

```sql
CREATE DATABASE proyecto_integrado CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

El nombre debe coincidir con `DB_NAME` del `.env`.

### 6. Verificar, migrar y cargar datos de prueba

```bash
python manage.py check
python manage.py migrate
python manage.py seed_demo
```

> Las migraciones ya están versionadas en el repositorio, por lo que no es necesario
> ejecutar `makemigrations` para levantar el proyecto.
> `seed_demo` es idempotente: puede ejecutarse varias veces sin duplicar datos.

### 7. Levantar el servidor

```bash
python manage.py runserver
```

Abrir el sitio en <http://127.0.0.1:8000/>. El Admin está disponible en
<http://127.0.0.1:8000/admin/>.

### Frontend de los anexos C1–C6

Las pantallas de la segunda evaluación están disponibles en estas rutas:

| Anexo | Pantalla | Ruta |
| ----- | -------- | ---- |
| C1 | Ingreso al sistema | `/accounts/login/` |
| C1 | Recuperar contraseña | `/accounts/recuperar/` |
| C2 | Validar código | `/accounts/recuperar/codigo/` |
| C2 | Crear nueva contraseña | `/accounts/recuperar/nueva-clave/` |
| C3 | Delegaciones y roles | `/accounts/delegaciones/`, `/accounts/roles/` |
| C4 | Usuarios e ítems y metas | `/accounts/usuarios/`, `/configuration/items/` |
| C5 | Tipo de Atención y Sub Atención | `/configuration/tipos-atencion/`, `/configuration/subatenciones/` |
| C6 | Ingreso de atención | `/activities/atenciones/nueva/` |

Los mantenedores de Tipo de Atención y Sub Atención (C5) consultan y guardan registros en
la base de datos. Permiten crear, consultar, editar, buscar, filtrar, paginar y exportar
los catálogos; los códigos se generan automáticamente y los cambios de estado son
desactivaciones lógicas para conservar el historial. Se exige el permiso `view_*` para
consultar y los permisos `add_*` / `change_*` para crear y modificar. No se permite
desactivar un tipo que tenga subatenciones activas ni reasignar una subatención vinculada
a atenciones históricas. Las acciones también se validan en el servidor.

El ingreso de atención (C6) guarda atenciones en la base de datos. El solicitante se identifica
por RUT u otro identificador: si ya existe una persona activa, se reutiliza su registro y no se
modifica su nombre; si no existe, se crea junto con la atención. La delegación se elige entre las
autorizadas para el funcionario, y el responsable y la fecha/hora se asignan en el servidor.
Los tipos y subatenciones provienen de los catálogos activos; la relación se valida también en
el servidor. Se aplican el límite de tres gestiones por persona y las reglas del modelo de
atención. Al guardar, se confirma el identificador de atención y se registra el evento de
auditoría. Cancelar no crea registros.

### Anexos A1–A3

Los mantenedores de Delegaciones, Roles, Usuarios, Ítems y metas, Tipo de Atención y Sub
Atención usan registros persistidos y controles de acceso del servidor. Las exportaciones de
estos catálogos se descargan en formato Excel (`.xlsx`) y respetan los filtros aplicados.
Cuando un usuario tiene acceso a varias delegaciones activas, puede cambiar la delegación
activa desde la cabecera; la selección se guarda en la sesión y solo admite delegaciones que
siguen autorizadas. El contexto se aplica a las listas y exportaciones de usuarios y funcionarios,
a las opciones iniciales de los formularios y al ingreso de atención. Las asignaciones de acceso
a varias delegaciones se conservan al editar un funcionario.

El requisito de pruebas de estrés del Anexo A3 sigue pendiente de evidencia verificable. No se
han inventado métricas ni se ha afirmado una ejecución en AWS: para completar el informe se
necesitan el entorno AWS de prueba, el alcance de las rutas, la concurrencia y duración previstas,
y los umbrales de aceptación acordados.

El login, el cierre de sesión, la protección de rutas y la recuperación de contraseña (C1–C2)
sí están integrados con el backend (ver [Acceso y recuperación de contraseña](#acceso-y-recuperación-de-contraseña)).

### Acceso y recuperación de contraseña

**Ingreso (C1).** Se ingresa con nombre de usuario o correo (el del funcionario o, si no
tiene, el del usuario) y contraseña. Los errores de credenciales muestran un mensaje genérico.
Un usuario inactivo o un funcionario Inactivo, Suspendido o archivado no puede ingresar, y si
tenía una sesión abierta deja de ser reconocido en la siguiente petición. El cierre de sesión
es por `POST` y las páginas protegidas se envían sin caché, por lo que el botón Atrás no
recupera datos tras cerrar sesión.

**Rutas protegidas.** Sin sesión, toda pantalla interna redirige al login. Con sesión, cada
vista valida en el servidor el permiso requerido (ocultar opciones del menú es solo visual):

| Pantalla | Permiso requerido |
| -------- | ----------------- |
| Inicio | Solo sesión activa |
| Delegaciones, Roles, Cargos, Áreas, Funcionarios | `accounts.view_delegation`, `view_role`, `view_position`, `view_area`, `view_official` |
| Usuarios, Grupos | `auth.view_user`, `auth.view_group` |
| Actividades, Ingreso de atención | `activities.view_activity`, `activities.add_socialattention` |
| Ítems, Períodos | `configuration.view_item`, `view_period` |
| Consulta de Tipo de Atención y Sub Atención | `configuration.view_attentiontype`, `view_subattentiontype` |
| Crear Tipo de Atención y Sub Atención | `configuration.add_attentiontype`, `add_subattentiontype` |
| Editar y activar/desactivar Tipo de Atención y Sub Atención | `configuration.change_attentiontype`, `change_subattentiontype` |

Los permisos provienen del usuario, de sus grupos y de los **roles SGR vigentes** (activos y no
archivados) de su funcionario (`accounts.backends.SGRAuthBackend`). Salvo el superusuario, se
exige además un funcionario habilitado. Cada acceso denegado responde 403 y queda en el log de
auditoría (`AuditLog`, acción «Acceso denegado»).

**Recuperación (C1–C2).** Flujo en tres pasos con el modelo `PasswordResetCode`:

1. Se ingresa el correo. La respuesta es la misma exista o no la cuenta; solo una cuenta
   activa recibe el código de seis dígitos (en la base solo se guarda su hash).
2. Se valida el código: controla vigencia, intentos fallidos, código ya usado, espera entre
   reenvíos y máximo de reenvíos.
3. Solo tras una verificación válida se define la nueva contraseña. Se validan sus requisitos
   en el navegador y en el servidor (mínimo 8 caracteres, mayúscula, minúscula y número, además
   de los validadores de Django). Al guardar se invalida el código, se registra en auditoría y
   se vuelve al login con una confirmación SweetAlert2.

Los mensajes del sistema (mensajes de Django) se muestran con SweetAlert2. Parámetros
configurables en el `.env` (valores por defecto entre paréntesis): `PASSWORD_RESET_CODE_TTL_MINUTES`
(10), `PASSWORD_RESET_RESEND_WAIT_SECONDS` (45), `PASSWORD_RESET_MAX_ATTEMPTS` (5) y
`PASSWORD_RESET_MAX_RESENDS` (3). Por defecto el correo se imprime en la consola de
`runserver` (`EMAIL_BACKEND` de consola); para enviarlo a un buzón real se configuran
`EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` y las variables `EMAIL_*`.

Para ejecutar las pruebas:

```bash
python manage.py test accounts activities configuration
```

## Cuentas de prueba

Creadas por el comando `seed_demo` (solo para demostración). Todas usan la contraseña `demo1234`
y también pueden ingresar con su correo (por ejemplo, `funcionario1@demo.cl` o `admin@demo.cl`).

| Usuario          | Rol SGR                                           | Área         | Delegación                                  | Alcance                                                                                                                                         |
| ---------------- | ------------------------------------------------- | ------------ | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `admin_demo`     | Superusuario; rol Administrador                   | Todas        | D01 Centro (alcance ALL: todas las activas) | Acceso completo (incluye eliminar y ver registros archivados)                                                                                   |
| `funcionario1`   | Operador                                          | Área Norte   | D01 Centro                                  | Ve y gestiona actividades de su área; solo consulta funcionarios e ítems                                                                        |
| `funcionario2`   | Operador y Verificador                            | Área Norte   | D02 Norte                                   | Como funcionario1, más validación de evidencias (dos roles)                                                                                     |
| `funcionario3`   | Coordinador y Operador                            | Área Sur     | D03 Sur (alcance ALL: todas las activas)    | Como funcionario1, más consulta transversal y gestión de ítems y períodos                                                                       |
| `funcionario4`   | Supervisor y Operador                             | Área Sur     | D03 Sur; autorizadas Sur y Norte            | Como funcionario1, más consulta de delegaciones y períodos. Dos delegaciones autorizadas para probar el selector                                 |
| `funcionario5`   | Sin rol                                           | Sin contexto | —                                           | Su funcionario asociado está archivado y sin usuario vinculado: **acceso denegado** (demuestra que la falta de contexto nunca amplía el acceso) |
| `consulta_norte` | Consulta                                          | Área Norte   | D02 Norte                                   | Solo lectura sobre actividades, funcionarios e ítems de su área                                                                                 |

Todos son staff. Los permisos efectivos de los funcionarios vienen **solo de sus roles SGR vigentes**
(ninguno tiene grupos ni permisos propios), por lo que desactivar un rol retira lo que otorgaba.

Roles SGR (modelo `Role`, definidos en `seed_demo`). Ninguno incluye permisos de eliminar: la
eliminación queda reservada al superusuario y el resto se archiva o desactiva.

| Rol           | Alcance    | Permisos                                                                                                  |
| ------------- | ---------- | --------------------------------------------------------------------------------------------------------- |
| Administrador | ALL        | `view`, `add` y `change` sobre cuentas, actividades y configuración, más usuarios y grupos; la auditoría solo se consulta |
| Coordinador   | ALL        | Consulta de la operación, delegaciones y catálogos; `add` y `change` sobre Ítems y Períodos                |
| Supervisor    | DELEGATION | Consulta de actividades, atenciones, evidencias, funcionarios, delegaciones, ítems y períodos              |
| Operador      | DELEGATION | `view`, `add` y `change` sobre Actividad; `view` y `add` sobre Atención social; `view` sobre Funcionario e Ítem |
| Verificador   | DELEGATION | Consulta de actividades, atenciones, evidencias, funcionarios e ítems; `add` y `change` sobre Validación de evidencia |
| Consulta      | DELEGATION | Solo `view` sobre Actividad, Funcionario e Ítem                                                           |

## Datos cargados por `seed_demo`

- 5 áreas (Norte, Sur, Centro, Cordillera, Costa), 5 cargos, 5 ítems y 5 períodos (tablas maestras)
- 4 delegaciones: D01 Centro, D02 Norte y D03 Sur activas; D04 Rural inactiva (direcciones ficticias)
- 6 roles SGR (ver tabla anterior)
- 7 funcionarios, todos con delegación y al menos un rol: 2 en Área Norte, 2 en Área Sur, 1 en Área
  Centro (archivado), 1 de consulta en Área Norte y el funcionario del administrador
- 10 actividades (2 por cada uno de los 5 funcionarios principales)
- 1 funcionario con `deleted_at` como evidencia de borrado lógico
- Áreas Norte y Sur con funcionarios y actividades, para demostrar el scoping por área

El comando puede ejecutarse varias veces, incluso en días distintos, sin duplicar datos. En cada
ejecución restablece los permisos de los roles, y la delegación, delegaciones autorizadas y roles
de los funcionarios de demostración. Si una base cargada con una versión anterior tiene a los
usuarios de demostración en los grupos `Funcionarios` o `Consulta`, los quita de ellos (los grupos
no se eliminan).

## Arquitectura del proyecto

### Apps

| App             | Responsabilidad                                                                                         | Estado                            |
| --------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------- |
| `accounts`      | Usuarios, delegaciones, roles, cargos, áreas y funcionarios; frontend de C1–C4                          | Implementada                      |
| `configuration` | Ítems, períodos y catálogos de atención; frontend de C4–C5                                               | Implementada                      |
| `activities`    | Registro de actividades e interfaz demostrativa de ingreso de atención; frontend de C6                 | Implementada                      |
| `common`        | `BaseModel` (auditoría), `get_user_area` (scoping) y comando `seed_demo`                                 | Implementada                      |
| `agenda`        | Planificación de actividades                                                                           | Reservada para la siguiente etapa |
| `analytics`     | Reportes e indicadores                                                                                   | Reservada para la siguiente etapa |

### Estructura de carpetas

```
proyecto_integrado/
├── manage.py
├── requirements.txt
├── .env.example
├── .gitignore
├── config/
├── common/
│   ├── mixins.py
│   ├── admin_utils.py
│   └── management/commands/
│       └── seed_demo.py
├── accounts/
│   ├── models.py
│   ├── admin.py
│   └── migrations/
├── configuration/
│   ├── models.py
│   ├── admin.py
│   └── migrations/
├── activities/
│   ├── models.py
│   ├── admin.py
│   └── migrations/
├── agenda/
└── analytics/
```

## Modelado y auditoría

Todos los modelos heredan de `common.mixins.BaseModel`, que aporta los campos de
auditoría `created_at`, `updated_at` y `deleted_at`.

Los modelos y atributos del dominio usan nomenclatura en inglés; las etiquetas visibles
en el Admin están en español mediante `verbose_name`.

| Modelo     | App             | Tipo      | Descripción                                                                                                                                                                                                                                         |
| ---------- | --------------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Position` | `accounts`      | Maestra   | Cargos formales de la organización (`position_name` único, `is_active`). Métodos `activate_position()` y `deactivate_position()`                                                                                                                    |
| `Area`     | `accounts`      | Maestra   | Áreas u unidades organizacionales (`area_name` único, `is_active`)                                                                                                                                                                                  |
| `Official` | `accounts`      | Operativa | Funcionario/a del organismo. Se vincula 1 a 1 con un `User` de Django y pertenece a un `Area` y un `Position`. Incluye `full_name`, `national_id` (único), `email` (único), `phone` y `status` (Activo / Inactivo / Suspendido)                     |
| `Item`     | `configuration` | Maestra   | Ítems medibles del sistema, usados por `Activity` (`item_name` único, `is_active`)                                                                                                                                                                  |
| `Period`   | `configuration` | Maestra   | Período de gestión con `start_date`, `end_date` y `status` (Abierto / Cerrado). Valida que no se solape con otros períodos y que la fecha de término no sea anterior a la de inicio (también como `CheckConstraint` en BD). Método `close_period()` |
| `AttentionType` | `configuration` | Maestra | Tipo de atención con código automático (`TAT-####`), nombre, descripción y estado; no se desactiva mientras tenga subatenciones activas |
| `SubattentionType` | `configuration` | Maestra | Subatención con código automático (`SAT-####`), nombre, tipo de atención asociado y estado; conserva sus atenciones históricas |
| `Activity` | `activities`    | Operativa | Actividad realizada por un `Official` sobre un `Item`, con `date`, `record_type` y `action_description`                                                                                                                                             |

Relaciones principales (todas con `on_delete=PROTECT`, salvo `Official.user` que usa `SET_NULL`):

- `Area` 1 — N `Official`
- `Position` 1 — N `Official`
- `User` 1 — 1 `Official`
- `Official` 1 — N `Activity`
- `Item` 1 — N `Activity`

## Funcionalidades del Admin

### Admin Básico

Todos los modelos están registrados en el Admin con `list_display`, `list_filter`,
`search_fields` y `ordering`, mostrando los campos de auditoría (`created_at`,
`updated_at`, `deleted_at`) en los listados.

### Admin Pro

| Modelo     | Funcionalidades                                                                                                                                                                       |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Position` | Acciones masivas «Activar cargos seleccionados» y «Desactivar cargos seleccionados»                                                                                                   |
| `Official` | `list_select_related` (evita consultas N+1), filtros por estado, área, cargo y `deleted_at`, búsqueda por nombre, RUT, correo, cargo y área. Inline de actividades (`ActivityInline`) |
| `Period`   | Acción masiva «Cerrar períodos seleccionados» y navegación por fecha (`date_hierarchy`)                                                                                               |
| `Activity` | Acción masiva «Archivar actividades seleccionadas» (borrado lógico), `autocomplete_fields` para funcionario e ítem, y `list_select_related`                                           |

### Borrado lógico

Las actividades no se eliminan físicamente: el Admin no permite `delete` sobre `Activity` y
ofrece la acción de archivar, que marca `deleted_at`. Los usuarios limitados no ven los
registros archivados; el superusuario sí.

## Seguridad y roles

El acceso a los datos se restringe por **área** mediante tres capas, apoyadas en
`common.admin_utils.get_user_area()`:

1. **Permisos por objeto** (`has_change_permission`): un usuario limitado solo puede editar
   registros de su área, incluso si intenta acceder directamente por URL.
2. **Queryset filtrado** (`get_queryset`): en `Official` y `Activity` solo se listan registros
   de su área y no archivados.
3. **Área no controlada por el navegador**: al guardar un `Official`, el área se fuerza a la
   del usuario (`save_model`); en `Activity`, el selector de funcionarios solo ofrece los
   de su área (`formfield_for_foreignkey`).

Reglas adicionales:

- El **superusuario** es la única excepción explícita al scoping (acceso global).
- Un usuario sin `Official` asociado, sin área o con funcionario archivado recibe
  `PermissionDenied`: la falta de contexto **nunca** amplía el acceso.
- Solo el superusuario puede eliminar `Official`; nadie puede eliminar `Activity`.

> Nota: el scoping por área está aplicado a `Official` y `Activity`. Las tablas maestras
> (`Area`, `Position`, `Item`, `Period`) no tienen filtrado por área, y a los usuarios
> limitados no se les otorgan permisos de modificación sobre ellas.

## Flujo de trabajo Git

- **Rama principal:** `main` (solo commit inicial directo; el resto se integra por Pull Request).
- **Ramas de trabajo**:
    - `configuration/base-configuraciones`: clase base y configuración
    - `Modelos-iniciales`: modelos del dominio
    - `configuration/seeds`: comando `seed_demo`
    - `feature/admin-basico`: Admin básico
    - `feature/admin-pro`: Admin pro
    - `configuration/models`: renombrado de modelos y campos a inglés
    - `configuration/scoping`: seguridad y scoping por área
- **Integración:** Pull Request hacia `main` (8 PR integrados a la fecha).
- **Commits:** prefijados con el número de historia de Scrum, p. ej. `Scrum 15: Seguridad Scoping`.

El `.gitignore` excluye `.env`, `.venv/` y otros archivos locales.

## Problemas frecuentes

- **`Can't connect to MySQL server`**: MySQL no está corriendo o el `DB_HOST`/`DB_PORT` es incorrecto. Usar `127.0.0.1` en lugar de `localhost` en Windows.
- **`Access denied for user`**: revisar `DB_USER` y `DB_PASSWORD` en el `.env`.
- **`Unknown database`**: crear la base de datos (paso 5).
- **Falla la instalación de `mysqlclient`**: en Windows, verificar que el entorno virtual esté activo y que la versión de Python sea compatible. En Linux pueden faltar las librerías de desarrollo (`libmysqlclient-dev`, `pkg-config`, `python3-dev`).
- **`KeyError: 'SECRET_KEY'` o `ImproperlyConfigured`**: falta el archivo `.env` o está incompleto (paso 4).
- **`403 Forbidden` al entrar al Admin con `funcionario5`**: es el comportamiento esperado; ese usuario no tiene área asignada (ver [Seguridad y roles](#seguridad-y-roles)).
