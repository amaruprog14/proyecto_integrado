# Proyecto Integrado
 
Sistema de Gestión de Resultados (SGR) de la Municipalidad de La Serena: aplicación web en Django
con Django Admin personalizado y base de datos MySQL. Proyecto de la asignatura Programación Back
End (TI3041) – Evaluación Sumativa II.

**Equipo:** `Amaru Marin/Sebastian Alzamora/Benjamin Ocaranza/Vicente Ibarra`
**Sección:** `P2-C1`

## Estado de los módulos

| Módulo | Estado |
| ------ | ------ |
| Ingreso al sistema, cierre de sesión y rutas protegidas | Operativo, con bloqueo temporal por intentos fallidos y auditoría |
| Recuperar contraseña, validar código y crear nueva contraseña | Operativo |
| Delegaciones | Operativo con persistencia real |
| Roles | Operativo con persistencia real |
| Usuarios y Funcionarios | Operativo con persistencia real |
| Ítems y metas | Operativo con persistencia real (las metas por cargo aún no forman parte del mantenedor) |
| Tipo de Atención | Operativo con persistencia real |
| Sub Atención | Operativo con persistencia real |
| Ingreso de atención y consulta de la atención registrada | Operativo con persistencia real |
| Cargos, Áreas, Grupos, Períodos y Actividades | **Maquetas con datos de demostración**: los registros son ficticios, no se guardan y las acciones no están disponibles. Cada pantalla lo indica con el aviso «Datos de demostración» |
| Agenda, evidencias, cálculos y tableros | Pendientes para la siguiente etapa |
| Pruebas de estrés | Pendientes de evidencia: no se han inventado métricas; requieren el entorno de prueba acordado, la concurrencia, la duración y los umbrales de aceptación |

Los seis mantenedores (Delegaciones, Roles, Usuarios, Ítems y metas, Tipo de Atención y Sub
Atención) y el ingreso de atención guardan y consultan registros en la base de datos, validan en
el servidor y registran cada cambio en el log de auditoría.

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

Dependencias principales: Django 5.2, mysqlclient, python-dotenv, django-bootstrap5 y openpyxl
(exportación a Excel). Ver `requirements.txt`.

### 4. Configurar variables de entorno

Copiar el archivo de ejemplo y completar los valores reales:

```bash
cp .env.example .env
```

Para generar una `SECRET_KEY` nueva:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

| Variable | Uso | Valor por defecto |
| -------- | --- | ----------------- |
| `SECRET_KEY` | Clave secreta de Django (obligatoria) | — |
| `DEBUG` | Modo desarrollo | `False` |
| `ALLOWED_HOSTS` | Hosts permitidos, separados por coma | `localhost,127.0.0.1` |
| `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Conexión a MySQL | motor MySQL |
| `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | Envío del código de recuperación | correo impreso en la consola |
| `PASSWORD_RESET_CODE_TTL_MINUTES` | Vigencia del código de recuperación | `10` |
| `PASSWORD_RESET_RESEND_WAIT_SECONDS` | Espera mínima entre reenvíos | `45` |
| `PASSWORD_RESET_MAX_ATTEMPTS` | Intentos fallidos por código | `5` |
| `PASSWORD_RESET_MAX_RESENDS` | Reenvíos por código vigente | `3` |
| `LOGIN_MAX_FAILED_ATTEMPTS` | Intentos fallidos de ingreso antes del bloqueo | `5` |
| `LOGIN_LOCKOUT_MINUTES` | Duración del bloqueo de ingreso | `10` |

> El archivo `.env` contiene credenciales y **no se versiona** en Git.
> `settings.py` lee estas variables desde el entorno (con `python-dotenv`); para cambiar de
> base de datos solo se edita el `.env`, nunca el código.

### 5. Crear la base de datos

Desde el cliente de MySQL:

```sql
CREATE DATABASE proyecto_integrado CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

El nombre debe coincidir con `DB_NAME` del `.env`. Para ejecutar las pruebas, el usuario de
`DB_USER` necesita además permiso para crear y eliminar la base `test_<DB_NAME>`.

### 6. Verificar, migrar y cargar datos de demostración

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

## Pruebas

```bash
python manage.py test
```

La suite usa MySQL con una base de pruebas aparte (`test_<DB_NAME>`) que Django crea y elimina,
sin tocar los datos de desarrollo. El detalle de cómo ejecutarlas, la organización por módulo y la
matriz requisito → prueba están en [`TESTING.md`](TESTING.md).

## Cuentas de demostración

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
Cinco intentos fallidos de ingreso seguidos bloquean la cuenta durante diez minutos; un
superusuario puede desbloquearla antes borrando su registro en el Admin («Bloqueos de inicio de
sesión»).

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

### Datos cargados por `seed_demo`

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

## Pantallas

| Anexo | Pantalla | Ruta |
| ----- | -------- | ---- |
| C1 | Ingreso al sistema | `/accounts/login/` |
| C1 | Recuperar contraseña | `/accounts/recuperar/` |
| C2 | Validar código | `/accounts/recuperar/codigo/` |
| C2 | Crear nueva contraseña | `/accounts/recuperar/nueva-clave/` |
| C3 | Delegaciones y Roles | `/accounts/delegaciones/`, `/accounts/roles/` |
| C4 | Usuarios, Funcionarios e Ítems y metas | `/accounts/usuarios/`, `/accounts/funcionarios/`, `/configuration/items/` |
| C5 | Tipo de Atención y Sub Atención | `/configuration/tipos-atencion/`, `/configuration/subatenciones/` |
| C6 | Ingreso y consulta de atención | `/activities/atenciones/nueva/`, `/activities/atenciones/<id>/` |
| — | Maquetas: Cargos, Áreas, Grupos, Períodos y Actividades | `/accounts/cargos/`, `/accounts/areas/`, `/accounts/grupos/`, `/configuration/periodos/`, `/activities/` |

### Patrón común de los mantenedores

- Tabla con el estado en texto, búsqueda parcial sin distinguir mayúsculas en varios campos,
  filtro por estado, paginación de 10 registros que conserva los filtros y total de resultados.
- Búsqueda en tiempo real: al dejar de escribir (unos 400 ms) o al cambiar el estado, se
  actualizan solo la tabla, el total y el paginador, en la página 1, y la URL conserva los
  filtros. Sin JavaScript, el botón Buscar hace la misma búsqueda recargando la página.
- Mensajes distintos para listado vacío y búsqueda sin coincidencias, estado de carga mientras
  responde el servidor y páginas de error 403, 404 y 500 con la identidad del sistema (la de 500
  es autónoma para mostrarse aunque falle la base de datos).
- **Exportar a Excel** (`.xlsx`) con todos los resultados autorizados del filtro aplicado, en todas
  sus páginas, sin contraseñas, tokens ni campos internos.
- Formularios con los campos obligatorios marcados con `*`, Guardar y Cancelar. Los resultados y
  las confirmaciones de activar o desactivar se muestran con SweetAlert2.
- Los registros no se eliminan: se desactivan y reactivan, y conservan su historial. Cada
  creación, edición y cambio de estado queda en `AuditLog` con el valor anterior y el nuevo.
- La cabecera muestra siempre el usuario, su rol y la delegación activa (código y nombre), cada
  uno con texto e ícono. Si el perfil tiene varias delegaciones, el selector solo ofrece las
  autorizadas. La delegación activa filtra las listas y exportaciones de Usuarios y Funcionarios,
  propone la delegación principal al crear usuarios y funcionarios, y fija la delegación del
  ingreso de atención; el mantenedor de Delegaciones muestra todas las del ámbito autorizado. Si
  hay un formulario con cambios sin guardar, cambiar de delegación pide confirmación antes.

### Reglas de negocio destacadas

- **Roles:** el último rol Administrador global con funcionarios activos no se puede desactivar ni
  perder sus permisos privilegiados o su alcance, y desde Usuarios o Funcionarios no se puede
  desactivar ni quitar ese rol a su único titular activo. El Administrador global no se combina con
  otros roles. Asignar roles o permisos privilegiados exige `accounts.change_role`: sin él, las
  casillas aparecen bloqueadas y una petición manipulada recibe 403 y queda auditada. Un rol
  inactivo ya asignado se conserva al editar al funcionario.
- **Ítems:** el código puede escribirse o generarse (`ITM-0001`); al editar no puede quedar vacío.
  Al desactivar, la confirmación informa cuántas actividades usan el ítem.
- **Tipo y Sub Atención:** un tipo con subatenciones activas no se desactiva; una subatención no
  cambia de tipo si ya tiene atenciones registradas.
- **Ingreso de atención:** el solicitante se identifica por RUT u otro identificador (se reutiliza
  si ya existe). La Sub Atención depende del tipo elegido y solo ofrece opciones activas. La
  delegación se toma del contexto autorizado, y el responsable y la fecha y hora los asigna el
  servidor. Un token de un solo uso evita que un doble envío cree dos atenciones. Tras guardar, se
  muestra el identificador (`AS-000001`) con un enlace para consultar la atención registrada.

## Acceso y seguridad

**Ingreso.** Con nombre de usuario o correo y contraseña. Los errores de credenciales muestran un
mensaje genérico. Tras `LOGIN_MAX_FAILED_ATTEMPTS` fallos seguidos, el identificador queda
bloqueado `LOGIN_LOCKOUT_MINUTES`: durante el bloqueo se rechaza incluso la clave correcta, y
también el ingreso por el Admin. Un identificador que no corresponde a ninguna cuenta se bloquea
igual, de modo que la respuesta no revela si la cuenta existe. Un usuario inactivo o un
funcionario Inactivo, Suspendido o archivado no puede ingresar, y si tenía una sesión abierta deja
de ser reconocido en la siguiente petición. El cierre de sesión es por `POST` y las páginas
protegidas se envían sin caché. Los ingresos, los fallos, los bloqueos y los cierres de sesión
quedan en `AuditLog` con la IP de origen, nunca con la contraseña.

**Recuperación de contraseña.** Flujo en tres pasos con el modelo `PasswordResetCode`:

1. Se ingresa el correo. La respuesta es la misma exista o no la cuenta; solo una cuenta
   activa recibe el código de seis dígitos (en la base solo se guarda su hash).
2. Se valida el código: controla vigencia, intentos fallidos, código ya usado, espera entre
   reenvíos y máximo de reenvíos.
3. Solo tras una verificación válida se define la nueva contraseña. Se validan sus requisitos
   en el navegador y en el servidor (mínimo 8 caracteres, mayúscula, minúscula y número, además
   de los validadores de Django). Al guardar se invalida el código, se registra en auditoría y
   se vuelve al login con una confirmación SweetAlert2.

Por defecto el correo se imprime en la consola de `runserver`; para enviarlo a un buzón real se
configuran `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` y las variables `EMAIL_*`.

**Permisos por operación.** Sin sesión, toda pantalla interna redirige al login. Con sesión, cada
vista valida en el servidor el permiso de la operación (ocultar opciones del menú es solo visual).
La exportación usa el permiso de consulta.

| Pantalla | Consultar y exportar | Crear | Editar, activar y desactivar |
| -------- | -------------------- | ----- | ---------------------------- |
| Delegaciones | `accounts.view_delegation` | `accounts.add_delegation` | `accounts.change_delegation` |
| Roles | `accounts.view_role` | `accounts.add_role` | `accounts.change_role` |
| Usuarios | `auth.view_user` | `auth.add_user` | `auth.change_user` |
| Funcionarios | `accounts.view_official` | `accounts.add_official` | `accounts.change_official` |
| Ítems y metas | `configuration.view_item` | `configuration.add_item` | `configuration.change_item` |
| Tipo de Atención | `configuration.view_attentiontype` | `configuration.add_attentiontype` | `configuration.change_attentiontype` |
| Sub Atención | `configuration.view_subattentiontype` | `configuration.add_subattentiontype` | `configuration.change_subattentiontype` |
| Ingreso de atención | `activities.view_socialattention` (consulta) | `activities.add_socialattention` | — |
| Maquetas | `view_position`, `view_area`, `auth.view_group`, `view_period`, `view_activity` | — | — |

Los permisos provienen del usuario, de sus grupos y de los **roles SGR vigentes** (activos y no
archivados) de su funcionario (`accounts.backends.SGRAuthBackend`). Salvo el superusuario, se
exige además un funcionario habilitado. Cada acceso denegado responde 403 y queda en `AuditLog`
(acción «Acceso denegado»).

**Ámbito por delegación.** Delegaciones, Usuarios, Funcionarios y las atenciones registradas se
limitan a las delegaciones autorizadas del actor (todas si tiene un rol vigente de alcance ALL).
Un identificador de otra delegación responde 404, igual que uno inexistente, y el intento queda en
`AuditLog`. Los formularios solo ofrecen delegaciones del ámbito, de modo que un identificador
fuera de él enviado desde el navegador no valida.

## Arquitectura del proyecto

### Apps

| App             | Responsabilidad                                                                                         | Estado                            |
| --------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------- |
| `accounts`      | Usuarios, funcionarios, delegaciones, roles, login y recuperación de contraseña; maquetas de cargos, áreas y grupos | Implementada                      |
| `configuration` | Ítems, catálogos de atención y auditoría; maqueta de períodos                                            | Implementada                      |
| `activities`    | Ingreso y consulta de atenciones; maqueta del listado de actividades                                     | Implementada                      |
| `common`        | `BaseModel`, control de acceso, exportación a Excel, paginación, `get_user_area` y comando `seed_demo` | Implementada                      |
| `agenda`        | Planificación de actividades                                                                           | Reservada para la siguiente etapa |
| `analytics`     | Reportes e indicadores                                                                                   | Reservada para la siguiente etapa |

### Estructura de carpetas

```
proyecto_integrado/
├── manage.py
├── requirements.txt
├── .env.example
├── README.md
├── TESTING.md
├── config/                 # settings y URLs
├── common/                 # BaseModel, acceso, exportación, paginación, seed_demo
├── accounts/               # cuentas, delegaciones, roles, login y recuperación
├── configuration/          # ítems, catálogos de atención y auditoría
├── activities/             # actividades e ingreso de atención
├── agenda/
├── analytics/
├── templates/              # template común (base.html), pantallas y páginas de error
└── static/                 # estilos institucionales y JavaScript de las pantallas
```

## Modelado y auditoría

Todos los modelos heredan de `common.mixins.BaseModel`, que aporta los campos de
auditoría `created_at`, `updated_at` y `deleted_at`. Los modelos y atributos del dominio usan
nomenclatura en inglés; las etiquetas visibles están en español mediante `verbose_name`.

| Modelo     | App             | Tipo      | Descripción |
| ---------- | --------------- | --------- | ----------- |
| `Delegation` | `accounts` | Maestra | Delegación con código automático (`DEL-####`), nombre único, dirección, comuna y estado |
| `Role` | `accounts` | Maestra | Rol SGR con permisos, alcance (ALL, DELEGATION, OWN), estado y funcionarios asignados |
| `Official` | `accounts` | Operativa | Funcionario/a vinculado 1 a 1 con un `User`, con área, cargo, delegación principal, delegaciones autorizadas y estado (Activo / Inactivo / Suspendido) |
| `Position`, `Area` | `accounts` | Maestra | Cargos y áreas (el mantenedor web es una maqueta; se administran en el Admin) |
| `ServiceRecipient` | `accounts` | Operativa | Persona solicitante de una atención, identificada por RUT u otro identificador único |
| `PasswordResetCode` | `accounts` | Operativa | Código de recuperación (solo su hash), vigencia, intentos y reenvíos |
| `LoginThrottle` | `accounts` | Operativa | Intentos fallidos de ingreso y bloqueo temporal |
| `Item` | `configuration` | Maestra | Ítem medible con código manual o automático (`ITM-####`), nombre único y estado |
| `AttentionType`, `SubattentionType` | `configuration` | Maestra | Catálogos de atención con código automático (`TAT-####`, `SAT-####`); la subatención pertenece a un tipo |
| `Period` | `configuration` | Maestra | Período de gestión; valida fechas y solapamientos |
| `AuditLog` | `configuration` | Operativa | Usuario, fecha, IP, acción, tabla, registro y valores anterior y nuevo |
| `Activity` | `activities` | Operativa | Actividad realizada por un funcionario sobre un ítem |
| `SocialAttention` | `activities` | Operativa | Atención con solicitante, tipo, subatención, descripción, delegación, responsable y fecha y hora de registro (identificador `AS-######`) |

Relaciones principales (con `on_delete=PROTECT`, salvo `Official.user` que usa `SET_NULL`):
`Official` 1 — N `Activity`, `Item` 1 — N `Activity`, `AttentionType` 1 — N `SubattentionType`,
y `SocialAttention` referencia a su solicitante, tipo, subatención, delegación y responsable.

## Funcionalidades del Admin

Todos los modelos están registrados en el Admin con `list_display`, `list_filter`,
`search_fields` y `ordering`, mostrando los campos de auditoría en los listados.

| Modelo     | Funcionalidades |
| ---------- | --------------- |
| `Position` | Acciones masivas «Activar cargos seleccionados» y «Desactivar cargos seleccionados» |
| `Official` | `list_select_related`, filtros por estado, área, cargo y `deleted_at`, búsqueda por nombre, RUT, correo, cargo y área. Inline de actividades (`ActivityInline`) |
| `Period`   | Acción masiva «Cerrar períodos seleccionados» y navegación por fecha (`date_hierarchy`) |
| `Activity` | Acción masiva «Archivar actividades seleccionadas» (borrado lógico), `autocomplete_fields` y `list_select_related` |
| `LoginThrottle` | Consulta de bloqueos de ingreso; un superusuario desbloquea borrando el registro |

Las actividades no se eliminan físicamente: el Admin ofrece archivarlas (`deleted_at`). En el
Admin, `Official` y `Activity` se limitan al área del usuario (`common.admin_utils.get_user_area`);
el superusuario es la única excepción explícita y un usuario sin área asignada recibe
`PermissionDenied`: la falta de contexto **nunca** amplía el acceso.

## Flujo de trabajo Git

- **Rama principal:** `main` (solo commit inicial directo; el resto se integra por Pull Request).
- **Ramas de trabajo** de la primera evaluación:
    - `configuration/base-configuraciones`: clase base y configuración
    - `Modelos-iniciales`: modelos del dominio
    - `configuration/seeds`: comando `seed_demo`
    - `feature/admin-basico`: Admin básico
    - `feature/admin-pro`: Admin pro
    - `configuration/models`: renombrado de modelos y campos a inglés
    - `configuration/scoping`: seguridad y scoping por área
- En la segunda evaluación se usa una rama `feature/...` por historia o grupo de historias (por
  ejemplo, `feature/crud-items` o `feature/cierre-parte-a`).
- **Commits:** prefijados con el número de historia de Scrum, p. ej. `Scrum 15: Seguridad Scoping`.

El `.gitignore` excluye `.env`, `.venv/`, `docs/` y otros archivos locales; los documentos de la
asignatura no se versionan.

## Problemas frecuentes

- **`Can't connect to MySQL server`**: MySQL no está corriendo o el `DB_HOST`/`DB_PORT` es incorrecto. Usar `127.0.0.1` en lugar de `localhost` en Windows.
- **`Access denied for user`**: revisar `DB_USER` y `DB_PASSWORD` en el `.env`.
- **`Unknown database`**: crear la base de datos (paso 5).
- **Las pruebas fallan al crear `test_<DB_NAME>`**: el usuario de MySQL necesita permiso para crear y eliminar esa base.
- **Falla la instalación de `mysqlclient`**: en Windows, verificar que el entorno virtual esté activo y que la versión de Python sea compatible. En Linux pueden faltar las librerías de desarrollo (`libmysqlclient-dev`, `pkg-config`, `python3-dev`).
- **`KeyError: 'SECRET_KEY'` o `ImproperlyConfigured`**: falta el archivo `.env` o está incompleto (paso 4).
- **«Demasiados intentos fallidos» al ingresar**: esperar `LOGIN_LOCKOUT_MINUTES` o pedir a un superusuario que borre el bloqueo en el Admin.
- **`403 Forbidden` al entrar al Admin con `funcionario5`**: es el comportamiento esperado; ese usuario no tiene área asignada.
