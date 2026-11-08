# Proyecto Integrado
 
Sistema de Gestión de Resultados (SGR) de la Municipalidad de La Serena: aplicación web en Django
con Django Admin personalizado y base de datos MySQL. Proyecto de la asignatura Programación Back
End (TI3041) – Evaluación Sumativa III.

**Equipo:** `Amaru Marin/Sebastian Alzamora/Benjamin Ocaranza/Vicente Ibarra`
**Sección:** `P2-C1`

## Estado de los módulos

| Módulo | Estado |
| ------ | ------ |
| Ingreso al sistema, cierre de sesión y rutas protegidas | Operativo, con bloqueo temporal por intentos fallidos y auditoría |
| Recuperar contraseña por enlace, cambiar la contraseña y editar nombre y correo propios | Operativo |
| Delegaciones | Operativo con persistencia real |
| Roles | Operativo con persistencia real |
| Usuarios y Funcionarios | Operativo con persistencia real |
| Ítems y metas | Operativo con persistencia real (las metas por cargo aún no forman parte del mantenedor) |
| Tipo de Atención | Operativo con persistencia real |
| Sub Atención | Operativo con persistencia real |
| Ingreso de atención y consulta de la atención registrada | Operativo con persistencia real |
| Cargos, Áreas, Grupos, Períodos y Actividades | Operativos con persistencia, validación, Excel y auditoría |
| Agenda, evidencias, cálculos y tableros | Pendientes para la siguiente etapa |
| Pruebas de estrés | Pendientes de evidencia: no se han inventado métricas; requieren el entorno de prueba acordado, la concurrencia, la duración y los umbrales de aceptación |

Los mantenedores operativos y el ingreso de atención guardan y consultan registros en la base de datos, validan en
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
| `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | Envío del enlace de recuperación | correo impreso en la consola |
| `PASSWORD_RESET_TIMEOUT` | Vigencia del enlace de recuperación, en segundos | `3600` |
| `PASSWORD_RESET_RESEND_WAIT_SECONDS` | Espera mínima entre dos enlaces a la misma cuenta | `45` |
| `PASSWORD_RESET_MIN_RESPONSE_SECONDS` | Tiempo mínimo de respuesta de la solicitud | `1` |
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
> `seed_demo` carga 2.000 registros de negocio ficticios del caso SGR, además de sus catálogos.
> Repetirlo no crea nuevos lotes y restablece `demo1234` solo en sus seis cuentas de demostración.
> Para comprobar la carga sin conservarla, usar
> `python manage.py seed_demo --dry-run`. No elimina datos previos ni fuerza conflictos.
> Ver [catálogos, distribución y precauciones de la semilla](SEMILLA_SGR.md).

### 7. Levantar el servidor

```bash
python manage.py runserver
```

Abrir el sitio en <http://127.0.0.1:8000/>. El Admin está disponible en
<http://127.0.0.1:8000/admin/>.

### Archivos subidos (`/media/`)

Las fotos de perfil se guardan en `MEDIA_ROOT` (por defecto `media/`, configurable en el `.env`).
Con `DEBUG=True`, `runserver` las sirve en `/media/` (`config/urls.py`). Con `DEBUG=False` Django
no las sirve: en el servidor de AWS lo hace Nginx con un bloque como este dentro del `server`,
reemplazando `<MEDIA_ROOT>` por la ruta absoluta configurada:

```nginx
location /media/ {
    alias <MEDIA_ROOT>/;
}
```

La configuración de Nginx vive en el servidor, no en este repositorio.

### Páginas de error

Con `DEBUG=False` el sistema usa sus propias páginas para 400 (solicitud no válida, por ejemplo un
`Host` que no está en `ALLOWED_HOSTS`), 403, 404 y 500 (`templates/`). Con `DEBUG=True` Django
muestra en su lugar su página técnica de depuración. Para revisarlas en local sin tocar el `.env`:

```bash
DEBUG=False python manage.py runserver --insecure
```

`--insecure` hace que `runserver` siga sirviendo los estáticos con `DEBUG=False`.


## Cuentas y datos de demostración

La semilla actual crea `adminA`, `editorA`, `readerA`, `readerB`, `clientA` y `clientB`.
Las seis cuentas de esta semilla usan temporalmente **`demo1234`** para las pruebas del equipo.
Al repetir la carga se restablece esa clave solo en ellas; los usuarios ajenos no se modifican.
`adminA` es administrador del SGR sin ser superusuario; `editorA` puede crear y editar
Actividades y Funcionarios de Las Compañías; los lectores consultan su propia delegación;
los clientes acceden a solicitudes propias del portal.

| Usuario | Contraseña | Acceso |
| --- | --- | --- |
| `adminA` | `demo1234` | Administrador SGR; todas las delegaciones mediante el selector del encabezado |
| `editorA` | `demo1234` | Crear y editar Actividades y Funcionarios de Las Compañías |
| `readerA` | `demo1234` | Solo lectura de Las Compañías |
| `readerB` | `demo1234` | Solo lectura de Antena |
| `clientA` | `demo1234` | Portal del cliente; solicitudes propias de Latorre, Las Compañías |
| `clientB` | `demo1234` | Portal del cliente; solicitudes propias de Alfalfares, Antena |

Estas credenciales se aplican después de ejecutar `python manage.py seed_demo` correctamente.

Los **2.000 registros de negocio** son 100 funcionarios, 1.200 actividades, 300 personas
usuarias, 300 atenciones sociales y 100 solicitudes ciudadanas. Hay 50 funcionarios por
delegación y suficientes actividades para varias páginas de 30. Las personas son ficticias;
los catálogos geográficos se limitan a **Las Compañías y Antena, con ocho territorios**.
Los siete cargos se basan en el descriptor y los seis roles de acceso en la guía del caso.
Todos los mantenedores visibles reciben datos, incluido un grupo `Consulta SGR` con los dos
lectores. Hay 2 tipos de atención y 7 subatenciones dependientes, sin inflar catálogos para alcanzar el volumen requerido.

[Ver detalle, fuentes y ejecución segura](SEMILLA_SGR.md). Si la base ya contiene la semilla
anterior (`admin_demo`, `funcionario1`, Centro/Norte/Sur/Rural), sus datos permanecen intactos;
no se migran ni se eliminan automáticamente y el total global puede ser mayor.

## Pantallas

| Anexo | Pantalla | Ruta |
| ----- | -------- | ---- |
| C1 | Ingreso al sistema | `/accounts/login/` |
| C1 | Recuperar contraseña | `/accounts/recuperar/` |
| C2 | Crear nueva contraseña (enlace del correo) | `/accounts/recuperar/<uidb64>/<token>/` |
| C2 | Cambiar contraseña con la sesión iniciada | `/accounts/mi-perfil/cambiar-clave/` |
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

**Recuperación de contraseña.** Por enlace con token (`django.contrib.auth.tokens`):

1. Se ingresa el correo. La respuesta y el tiempo mínimo de respuesta
   (`PASSWORD_RESET_MIN_RESPONSE_SECONDS`) son los mismos exista o no la cuenta; solo una cuenta
   que puede ingresar recibe el enlace, y como máximo uno cada `PASSWORD_RESET_RESEND_WAIT_SECONDS`.
   Cada solicitud queda en `AuditLog` con el correo enmascarado.
2. El enlace es absoluto, con el host de la petición (validado contra `ALLOWED_HOSTS`), vence a
   los `PASSWORD_RESET_TIMEOUT` segundos y deja de valer en cuanto cambia la contraseña, así que
   sirve una sola vez. No se guarda nada en la base. Un enlace inválido, vencido o ya usado
   muestra un mensaje claro y ofrece pedir otro.
3. Se define la nueva contraseña. Se validan sus requisitos en el navegador y en el servidor
   (mínimo 8 caracteres, mayúscula, minúscula y número, además de los validadores de Django). Al
   guardar se registra en auditoría y se vuelve al login con una confirmación SweetAlert2.

**Cambio de contraseña y datos propios.** Con la sesión iniciada, funcionarios y clientes cambian
su contraseña en `/accounts/mi-perfil/cambiar-clave/` (contraseña actual, nueva y confirmación).
Una contraseña actual incorrecta suma al mismo contador de bloqueo del inicio de sesión. Tras el
cambio la sesión sigue abierta y las de otros dispositivos se cierran; queda en `AuditLog`. En
«Mi perfil» cada uno edita sus nombres, apellidos, correo y teléfono: el nombre completo del
perfil es «nombres apellidos» y nombre y correo se copian al usuario de acceso.

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


## Flujo de trabajo Git

- **Rama principal:** `main` (solo commit inicial directo; el resto se integra por Pull Request).
- **Ramas de trabajo** de la primera evaluación:
    - `configuration/base-configuraciones`: clase base y configuración
    - `Modelos-iniciales`: modelos del dominio
    - `common/management/commands/seed_demo.py`: comando `seed_demo`
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

