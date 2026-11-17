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
| Foto de perfil con recorte Croppr y portal del cliente con solicitudes propias | Operativos, con validación y acceso por propietario |
| Actualización de tablas mediante Django Channels y WebSocket | Operativa en un único proceso ASGI con canal en memoria |
| Delegaciones | Operativo con persistencia real |
| Roles | Operativo con persistencia real |
| Usuarios y Funcionarios | Operativo con persistencia real |
| Ítems y metas | Operativo con persistencia real (las metas por cargo aún no forman parte del mantenedor) |
| Tipo de Atención | Operativo con persistencia real |
| Sub Atención | Operativo con persistencia real |
| Ingreso de atención y consulta de la atención registrada | Operativo con persistencia real |
| Cargos, Áreas, Grupos, Períodos y Actividades | Operativos con persistencia, validación, Excel y auditoría |
| Tipos de actividad y Servicios | Catálogos por área para clasificar el registro manual |
| Planes de medición, evidencias, cálculo de desempeño y panel «Mi desempeño» | Operativos: metas y ponderadores reales por cargo, semáforo accesible y congelamiento al cerrar el período (ver «Medición del desempeño») |
| Tablero de delegación | Consolida resultados del equipo y permite consultar el detalle por funcionario |
| Vista por cargo y actividad reciente | Operativas en Desempeño, con filtros de período y ámbito |
| Comentarios internos y alertas | Hilos en Actividades y Casos sociales, avisos por revisión de evidencia y seguimiento de desempeño |
| Agenda colectiva | Registro, asignación, seguimiento, alertas de vencimiento y medición del tubo |
| Pruebas de estrés | Pendientes de evidencia: no se han inventado métricas; requieren el entorno de prueba acordado, la concurrencia, la duración y los umbrales de aceptación |

Los mantenedores operativos y el ingreso de atención guardan y consultan registros en la base de datos, validan en
el servidor y registran cada cambio en el log de auditoría.

## Requisitos previos

- Python 3.11 o superior (requerido por Pillow 13.0.0)
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

Dependencias principales: Django 5.2, mysqlclient, python-dotenv, django-bootstrap5, openpyxl
(Excel), Pillow (imágenes), Channels y Daphne (HTTP y WebSocket mediante ASGI).
Las versiones están fijadas en `requirements.txt`.

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
| `SEED_DEMO_PASSWORD` | Clave de las cuentas ficticias. Requerida por `seed_demo` y al crear `adminEvalA` con `prepare_evaluation_admin` | — |
| `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | Envío del enlace de recuperación | correo impreso en la consola |
| `PORTAL_INVITATION_TIMEOUT_HOURS` | Vigencia de la invitación opcional al portal desde atención presencial | `24` |
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

Definir `SEED_DEMO_PASSWORD` en el `.env` del entorno donde se ejecutará la carga, incluido el
servidor de AWS. Usar comillas simples alrededor del valor para mantener caracteres como `$`.

```bash
python manage.py check
python manage.py migrate
python manage.py seed_demo
```

> Las migraciones ya están versionadas en el repositorio, por lo que no es necesario
> ejecutar `makemigrations` para levantar el proyecto.
> `seed_demo` carga 2.000 registros de negocio ficticios del caso SGR, además de sus catálogos.
> Repetirlo no crea nuevos lotes y aplica `SEED_DEMO_PASSWORD` solo a sus siete cuentas de demostración.
> Para comprobar la carga sin conservarla, usar
> `python manage.py seed_demo --dry-run`. No elimina datos previos ni fuerza conflictos.
> La distribución y las precauciones están en «Cuentas y datos de demostración», más abajo.

### 7. Levantar HTTP y WebSocket en desarrollo

```bash
python manage.py runserver --noreload
```

Abrir el sitio en <http://127.0.0.1:8000/>. El Admin está disponible en
<http://127.0.0.1:8000/admin/> y requiere una cuenta técnica con `is_staff` y permisos;
las siete cuentas de semilla no tienen acceso a Django Admin.

Con el entorno virtual activo, MySQL disponible y `DEBUG=True` en el `.env`, este comando sirve
la interfaz, los estáticos y las imágenes locales. `daphne` está al inicio de `INSTALLED_APPS`,
por lo que proporciona el comando `runserver` ASGI. La aplicación es
`config.asgi.application`, definida en `ASGI_APPLICATION`. HTTP y WebSocket se ejecutan juntos;
no se necesita iniciar un servidor de chat aparte. Con `--noreload`, reiniciar el comando
manualmente después de cambiar código.

Para iniciar explícitamente Daphne como alternativa al comando anterior:

```bash
daphne -b 127.0.0.1 -p 8000 config.asgi:application
```

Ejecutar **solo una de las dos alternativas**. Daphne directo no sirve automáticamente los
estáticos de las aplicaciones como `runserver`; requiere que los estáticos se sirvan aparte.
Para la demostración local con interfaz completa, usar `runserver --noreload`.

#### Canal en memoria y recorrido del evento

La configuración actual utiliza `channels.layers.InMemoryChannelLayer` en `CHANNEL_LAYERS`
(`config/settings.py`). No necesita Redis ni otro servicio de mensajería: solo MySQL y un
único proceso ASGI que reciba tanto los guardados HTTP como las conexiones WebSocket.

El canal y el registro de suscriptores de `common/realtime.py` viven en la memoria del proceso.
No comparten eventos entre varios workers, servidores o instancias. Esta demostración debe
mantenerse en **un único proceso**, sin repartir HTTP y WebSocket entre procesos diferentes.
Al reiniciarlo se pierden las conexiones y avisos pendientes; los registros guardados permanecen
en MySQL. Para varios procesos habrá que adaptar tanto la capa de canales como el registro de
suscriptores; ese cambio aún no forma parte de la configuración actual.

| Ruta WebSocket | Uso |
| --- | --- |
| `/ws/activities/` | Listado de Actividades |
| `/ws/maintainers/<module>/` | Otros mantenedores; por ejemplo `official` para Funcionarios |

La conexión utiliza `ws://` con HTTP y `wss://` con HTTPS. El navegador elige el protocolo y
el host de la página. `AllowedHostsOriginValidator` restringe el origen según `ALLOWED_HOSTS`
y `AuthMiddlewareStack` recupera la sesión. El servidor verifica el permiso de consulta y
asigna el grupo `maintainers.<module>.user.<id>`; el navegador no elige una delegación ni
puede suscribirse libremente a grupos ajenos.

Flujo: guardar y validar en el servidor → confirmar la transacción → ejecutar
`transaction.on_commit` → notificar solo a suscriptores autorizados → recibir
`activities.changed` o `maintainer.changed` → consultar la vista HTTP protegida y reemplazar
tabla, total y paginador. `static/js/maintainer-states.js` conserva los filtros, el orden y la
página. No hay consultas periódicas para sustituir WebSocket ni recarga completa del listado
del lector. La búsqueda de 400 ms se activa al escribir y es un flujo distinto.

Un formulario inválido o una transacción revertida no anuncia un cambio guardado. Si un registro
se archiva o deja de cumplir el filtro, desaparece de la tabla correspondiente. El usuario que
guarda puede regresar al listado mediante la navegación HTTP habitual; quien lo mantiene abierto
recibe la actualización. La interfaz informa si la conexión se pierde y reintenta conectarse;
durante esa desconexión no se debe considerar el listado actualizado.

#### Comprobación local en sesiones independientes

1. Abrir `editorA`, `readerA` y `readerB` en perfiles de navegador independientes. Dos pestañas
   del mismo perfil comparten sesión y no sirven para representar cuentas distintas.
2. Mantener abierto Funcionarios o Actividades con ambos lectores. En las herramientas de red
   del navegador, filtrar por WebSocket y comprobar la conexión aceptada (HTTP 101).
3. Con `editorA`, editar y guardar un registro de Las Compañías. Para Actividades, elegir una
   manual de un período abierto, sin atención social vinculada.
4. Comprobar que `readerA` ve el cambio sin F5, conserva filtros/orden/página y recibe el aviso.
   `readerB`, de Antena, no debe recibir el aviso ni el contenido de ese registro.
5. Repetir con datos inválidos: el formulario conserva los valores válidos y no se guarda ni
   notifica una modificación. Detener el servidor permite comprobar el estado de desconexión;
   volver a iniciarlo permite comprobar la reconexión.

Pruebas automatizadas relacionadas (usan una base de pruebas independiente):

```bash
python manage.py test activities.test_realtime common.test_realtime accounts.test_evaluation_admin
```

### Archivos subidos (`/media/`)

Las fotos se guardan en `MEDIA_ROOT` (por defecto `media/`, configurable en el `.env`).
Con `DEBUG=True`, `runserver` publica únicamente `profile_photos/`, el directorio de fotos de
funcionarios. Las fotos del portal, incluidas las ya guardadas en `client_profiles/`, se sirven
al titular autenticado desde `/portal/perfil/foto/`. Su ruta directa de archivo devuelve 404.

Con `DEBUG=False`, si se necesita servir las fotos de funcionarios desde Nginx, sustituir el
bloque que publica todo `MEDIA_ROOT` por estas rutas dentro de `server`. Usar la ruta absoluta
de `MEDIA_ROOT` en el `alias`. [Directivas de ubicación de Nginx](https://nginx.org/en/docs/http/ngx_http_core_module.html#location)

```nginx
location ^~ /media/profile_photos/ {
    alias <MEDIA_ROOT>/profile_photos/;
}

location ^~ /media/ {
    return 404;
}
```

Mantener `/portal/perfil/foto/` en el proxy a Django. La configuración de Nginx vive en el
servidor y se debe actualizar allí si todavía publica todo `MEDIA_ROOT`.

Las evidencias de Actividades se guardan en `EVIDENCE_ROOT` (por defecto `private_evidence/`).
Configura esta ruta fuera de los directorios públicos y en un volumen persistente en producción.
Las imágenes se consultan mediante Django con los permisos y el alcance de la actividad.
En **Actividades → Detalle**, cada evidencia registra una etapa, una descripción y de 1 a 10
imágenes JPG o PNG. Desde **Casos sociales → Historial del caso**, cada gestión enlaza a las
evidencias de su actividad. El rol Funcionario de la semilla puede adjuntar y el rol Verificador
puede revisar dentro de su ámbito. Los roles existentes pueden configurarse desde Roles con
`activities.view_evidence`, `activities.add_evidence` y `activities.add_evidencevalidation`
según las operaciones que necesiten, junto con `activities.view_activity`.

### Páginas de error

Con `DEBUG=False` el sistema usa sus propias páginas para 400 (solicitud no válida, por ejemplo un
`Host` que no está en `ALLOWED_HOSTS`), 403, 404 y 500 (`templates/`). Con `DEBUG=True` Django
muestra en su lugar su página técnica de depuración. Para revisarlas en local sin tocar el `.env`:

```bash
DEBUG=False python manage.py runserver --insecure
```

`--insecure` hace que `runserver` siga sirviendo los estáticos con `DEBUG=False`.


## Cuentas y datos de demostración

La semilla actual crea las seis cuentas de evaluación `adminEvalA`, `editorA`, `readerA`,
`readerB`, `clientA` y `clientB`, además del administrador global `adminA`.
Las siete cuentas de esta semilla comparten temporalmente la clave de demostración para las pruebas del equipo.
Al repetir la carga se restablece esa clave solo en ellas; los usuarios ajenos no se modifican.
`adminA` es administrador del SGR sin ser superusuario; `editorA` puede crear y editar
Actividades y Funcionarios de Las Compañías; los lectores consultan su propia delegación;
los clientes acceden a solicitudes propias del portal.

`adminEvalA` usa el rol independiente «Administrador evaluación A», con alcance `DELEGATION`
solo en Las Compañías. Puede listar, crear, consultar, editar, archivar y exportar Funcionarios
y Actividades; en Actividades también consulta archivadas y restaura cuando el período lo permite.
No tiene acceso a Roles, Grupos, al mantenedor de Usuarios ni a Django Admin y no puede asignar
roles privilegiados. La gestión de permisos y cuentas privilegiadas queda reservada a `adminA`.
Ambas cuentas son usuarios normales de Django: ninguna es superusuario ni `staff`.

En una base que ya tiene la semilla, preparar **solo esta nueva cuenta**, sin repetir la carga:

```bash
python manage.py prepare_evaluation_admin --dry-run
python manage.py prepare_evaluation_admin
```

El comando vincula el funcionario ficticio 006 de Las Compañías, que antes no tenía cuenta.
No agrega funcionarios ni operaciones, conserva los 2.000 registros de negocio y no cambia
el rol global. Repetirlo no duplica datos ni restablece contraseñas; rechaza colisiones o una
configuración modificada en lugar de sobrescribirla. `seed_demo`, en cambio, sí restablece la
clave de las siete cuentas de semilla. Entregar la clave de evaluación al docente por un medio privado.

Recorrido de `adminEvalA`: ingresar → crear/editar un funcionario y una actividad manual →
consultar detalles y exportar → archivar con confirmación → consultar/restaurar la actividad →
intentar una URL o relación de Antena y recibir rechazo sin modificaciones. Las actividades
vinculadas a atenciones o de períodos cerrados continúan siendo de solo consulta.

Funcionarios permite listar, consultar detalle, crear y editar mediante modal y archivar con
confirmación. El archivado usa `deleted_at`: conserva actividades e historial, retira el
funcionario de listados, exportaciones y selectores habituales e impide que su cuenta ingrese.
El estado laboral (Activo/Inactivo/Suspendido) se conserva por separado. Se protege el perfil
propio y al último administrador global. La semilla otorga `accounts.archive_official` al rol
Administrador; editor y lectores no reciben ese permiso ni pueden asignar un rol que lo otorgue
sin autorización para administrar roles.

Al actualizar una base existente, ejecutar `python manage.py migrate` para registrar el permiso
de la migración `0013_official_archive_permission`. En Roles, habilitar «Funcionarios: Archivar»
únicamente en los roles administradores que corresponda. `seed_demo` también completa ese
permiso en el Administrador de la semilla anterior si el resto de sus permisos coincide
exactamente; no amplía roles personalizados ni cambia su alcance.

Actividades permite crear y editar registros manuales mediante modal, consultar su detalle,
buscar, filtrar, ordenar y exportar las actividades sin archivar. Editor y lectores no pueden
archivar ni restaurar. El permiso `activities.archive_activity` habilita al administrador para
archivar, consultar el filtro «Archivada» y restaurar dentro de su ámbito. Las archivadas no
aparecen en el listado habitual ni se exportan; intentar exportar desde el historial muestra
un aviso para volver a Vigente. Las actividades de períodos cerrados y las vinculadas a una
atención social permanecen de solo consulta, conservando su origen e historial.

Para registrar manualmente una actividad nueva se indica el asunto o problema, la acción ejecutada
y el tipo de actividad vigente del área del funcionario. El nombre o referencia de contacto y el
teléfono se registran cuando corresponde. El formulario exige el siguiente nivel si el catálogo
seleccionado tiene opciones vigentes: **tipo de actividad → servicio → tipo de atención →
subatención**. **Configuración → Tipos de actividad / Servicios** administra los primeros niveles.
En **Tipo de Atención** se puede asociar un servicio. Los tipos de atención generales ya usados por
el portal y por Ingreso de atención siguen disponibles en esos flujos.

Si se desactiva un catálogo, las relaciones históricas de las actividades se conservan. Las
actividades anteriores pueden seguir consultándose sin completar una clasificación retroactiva.
Desde el detalle manual se puede crear un compromiso y consultar los compromisos vinculados para
los que se tenga permiso de Agenda.

Al cerrar un caso, sus actividades se muestran con el estado «Resuelta» en el listado,
el detalle y el Excel. En el listado, el filtro «Resuelta» se aplica a las actividades y solicitudes
según el origen seleccionado.

Desde Actividades, **Registrar atención** abre una gestión y **Casos sociales** permite continuar el
seguimiento. El caso reúne hasta tres gestiones, el responsable, el próximo paso y el historial.
Para una solicitud en línea, **Cerrar y responder** cierra el caso y publica la respuesta en el portal.
**Mis solicitudes y atenciones** muestra el historial publicado de los casos propios, incluido el presencial.
La ficha se reutiliza por RUT. Si la persona acepta una invitación presencial, activa su cuenta mediante
el enlace enviado por el mismo servicio de correo del SGR. Sin ubicación vigente, puede consultar el
seguimiento y completar su ubicación con un administrador antes de enviar una solicitud en línea.

Ejecutar `python manage.py migrate` al actualizar para agrupar las gestiones históricas vinculadas a un
folio y asignar un caso individual a cada gestión presencial anterior.

La migración `activities.0008_activity_archive_permission` registra este permiso; después de
`python manage.py migrate`, habilitar «Actividades: Archivar» en el rol administrador pertinente.
La semilla completa los permisos nuevos de archivado del Administrador anterior solo si el
resto de su configuración coincide. No ejecutarla para modificar datos de trabajo sin revisar
sus condiciones. WebSocket avisa después del commit y respeta los ámbitos, filtros y páginas;
al archivar, la fila desaparece del lector autorizado y un rollback no envía el aviso.

| Usuario | Acceso |
| --- | --- |
| `adminEvalA` | Administrador de evaluación; ambos CRUD solo de Las Compañías, sin gestión de roles/permisos |
| `adminA` | Administrador SGR; todas las delegaciones mediante el selector del encabezado |
| `editorA` | Crear y editar Actividades y Funcionarios de Las Compañías |
| `readerA` | Solo lectura de Las Compañías |
| `readerB` | Solo lectura de Antena |
| `clientA` | Portal del cliente; solicitudes propias de Latorre, Las Compañías |
| `clientB` | Portal del cliente; solicitudes propias de Alfalfares, Antena |

La clave se aplica después de ejecutar `python manage.py seed_demo` correctamente. Compártela
con el docente por privado.

### Responsabilidades y recorridos de las cuentas

Ámbito A equivale a **Las Compañías** y ámbito B a **Antena**. Los dos CRUD evaluados son
**Funcionarios y Actividades**. «Consultar» incluye sus listados y detalles; las exportaciones
de ambos CRUD respetan filtros y permisos y excluyen registros archivados.

| Alias / rol | Ámbito o propietario | Responsabilidad | Acciones permitidas | Acciones restringidas | Recorrido de prueba y resultado esperado |
| --- | --- | --- | --- | --- | --- |
| `adminEvalA` / Administrador evaluación A | Solo Las Compañías; alcance `DELEGATION` | Administrar los registros del ámbito A durante la evaluación | Crear, listar, consultar, editar, archivar y exportar ambos CRUD; consultar archivadas y restaurar Actividades cuando proceda; editar su perfil y foto | Acceder a Antena; cambiar de ámbito; gestionar Roles, Grupos o el mantenedor de Usuarios; asignar roles privilegiados; entrar a Django Admin | Login → crear/editar en ambos CRUD → cancelar una confirmación (sin cambios) → confirmar archivado → comprobar exclusión del listado/Excel → consultar/restaurar actividad → intentar URL o relación de Antena: rechazo sin escritura |
| `editorA` / Funcionario | Las Compañías; alcance `DELEGATION` | Registrar y corregir la gestión de A | Consultar, crear, editar y exportar ambos CRUD; registrar atenciones autorizadas; editar su perfil y foto | Archivar/restaurar; consultar historial de actividades archivadas; acceder a B; asignar roles privilegiados | Login → crear/editar una actividad manual y un funcionario → comprobar persistencia y cambio sin F5 en `readerA` → intentar POST de archivado: 403 y registro intacto |
| `readerA` / Usuario consulta | Las Compañías; alcance `DELEGATION` | Consultar y exportar información autorizada de A | Listados, detalles, búsquedas, filtros, orden y Excel de ambos CRUD; recibir avisos autorizados; editar su perfil y foto | Crear, editar o archivar registros del negocio; restaurar; consultar B o historial de archivadas | Login → filtrar/paginar/exportar → abrir detalle y volver conservando estado → observar edición de `editorA` sin F5 → intentar crear/archivar: 403; objeto de B: 404 |
| `readerB` / Usuario consulta | Antena; alcance `DELEGATION` | Consultar y exportar información autorizada de B | Las mismas consultas y exportaciones del lector A, dentro de B; editar su perfil y foto | Escribir en los CRUD; acceder a A o recibir sus eventos | Login en sesión independiente → comprobar registros de Antena → mantener listado abierto mientras A guarda: no recibe el evento de A → URL directa de A: 404 |
| `clientA` / Cliente | Propietario de sus solicitudes; Latorre, Las Compañías | Ingresar y consultar sus solicitudes ciudadanas | Listado y detalle propios en el portal; crear solicitudes; editar nombre/contacto y foto propios con Croppr; cambiar su contraseña | Listados administrativos, solicitudes/perfiles ajenos, cambiar propietario, rol, permisos o estado de tramitación | Login → portal con sus 50 solicitudes iniciales → detalle propio → recortar foto, guardar y recargar: persiste → intentar detalle de `clientB`: 404; mantenedor administrativo: 403 |
| `clientB` / Cliente | Propietario de sus solicitudes; Alfalfares, Antena | Ingresar y consultar un conjunto propio distinto del Cliente 1 | Las mismas funciones del Cliente 1, filtradas por su usuario autenticado | Acceder a solicitudes/perfil de `clientA` o funciones administrativas; alterar propietario o permisos | Login en otra sesión → comprobar sus 50 solicitudes iniciales distintas → detalle propio → cancelar recorte: conserva la foto anterior → intentar detalle de `clientA`: 404 |
| `adminA` / Administrador (adicional) | Todas las delegaciones; alcance `ALL` | Administrar globalmente el caso y mantener las cuentas y permisos de prueba | Mantenedores autorizados, gestión de usuarios/roles y selección de delegación; operaciones sujetas a las reglas del negocio | Django Admin (no es `staff`); eliminación física desde los CRUD; editar actividades de períodos cerrados o vinculadas a atenciones | Login → seleccionar Las Compañías y después Antena → comprobar acceso a ambos ámbitos y gestión de roles. Esta cuenta adicional no sustituye a `adminEvalA` en la prueba de aislamiento |

Las restricciones se aplican en el servidor, incluso al manipular URLs o formularios. Un usuario
autenticado sin permiso recibe 403; un registro inexistente o ajeno puede responder 404. Las
reglas de períodos cerrados, actividades de origen automático y protección del propio funcionario
siguen vigentes aunque el rol tenga permisos de edición o archivado. El portal filtra por
propietario, no solo por delegación; las pruebas también incluyen dos clientes de la misma delegación.

En Funcionarios y Usuarios, los editores solo pueden asignar roles locales con permisos que ya
ejercen en las delegaciones autorizadas. Los roles globales, incluidos los de solo lectura, y los
roles con permisos privilegiados requieren administrar roles con alcance global. Un envío que
intenta asignar un rol bloqueado se rechaza con 403.

### Distribución y ejecución segura de la semilla

| Modelo de negocio | Registros de la semilla |
| --- | ---: |
| `Official` (Funcionarios) | 100 |
| `Activity` (Actividades) | 1.200 |
| `ServiceRecipient` (Personas usuarias) | 300 |
| `SocialAttention` (Atenciones sociales) | 300 |
| `ClientRequest` (Solicitudes ciudadanas) | 100 |
| **Total de negocio** | **2.000** |

Hay 50 funcionarios por delegación y suficientes actividades para varias páginas de 30.
Los totales no incluyen cuentas de acceso, permisos, sesiones, eventos de seguimiento ni auditoría.
Las personas son ficticias;
los catálogos geográficos se limitan a **Las Compañías y Antena, con ocho territorios**.
Los siete cargos se basan en el descriptor y los seis roles de acceso en la guía del caso;
se agrega el rol independiente «Administrador evaluación A» para demostrar el aislamiento.
Todos los mantenedores visibles reciben datos, incluido un grupo `Consulta SGR` con los dos
lectores. Hay 2 tipos de atención y 7 subatenciones dependientes, sin inflar catálogos para alcanzar el volumen requerido.

Los catálogos están transcritos en `common/sgr_seed_data.py`: geografía, indicadores y atenciones
de la matriz SGR trimestral; cargos del descriptor de funciones y roles de la guía del proyecto.
No se requiere abrir los documentos originales ni instalar un lector de Excel para ejecutar la carga.
Se incluyen 2 delegaciones, 8 territorios, 7 cargos, 7 áreas, 7 funciones, 22 ítems, 2 tipos de
atención, 7 subatenciones, 2 períodos, 7 roles y el grupo `Consulta SGR`. Estos catálogos no se
inflan para alcanzar los 2.000 registros de negocio.

La carga usa una transacción: ante colisiones o cambios incompatibles en cuentas, roles,
asociaciones o períodos, informa el problema y revierte la ejecución. `--dry-run` valida la
carga y revierte también los datos y restablecimientos de claves. Revisar primero esa simulación
si la base contiene datos de trabajo; no ejecutar la semilla para resolver un conflicto sin revisarlo.

Si la base ya contiene la semilla anterior (`admin_demo`, `funcionario1`, Centro/Norte/Sur/Rural), sus datos permanecen intactos;
no se migran ni se eliminan automáticamente y el total global puede ser mayor.

## Pantallas

| Anexo | Pantalla | Ruta |
| ----- | -------- | ---- |
| C1 | Ingreso al sistema | `/accounts/login/` |
| C1 | Recuperar contraseña | `/accounts/recuperar/` |
| C2 | Crear nueva contraseña (enlace del correo) | `/accounts/recuperar/<uidb64>/<token>/` |
| C2 | Cambiar contraseña con la sesión iniciada | `/accounts/mi-perfil/cambiar-clave/` |
| — | Perfil propio y foto con Croppr (funcionarios) | `/accounts/mi-perfil/` |
| — | Portal: listado, creación y detalle propios | `/portal/`, `/portal/nueva/`, `/portal/<id>/` |
| — | Perfil y foto propios del cliente | `/portal/perfil/` |
| C3 | Delegaciones y Roles | `/accounts/delegaciones/`, `/accounts/roles/` |
| C4 | Usuarios, Funcionarios e Ítems y metas | `/accounts/usuarios/`, `/accounts/funcionarios/`, `/configuration/items/` |
| — | Detalle de funcionario | `/accounts/funcionarios/<id>/` |
| C5 | Tipo de Atención y Sub Atención | `/configuration/tipos-atencion/`, `/configuration/subatenciones/` |
| C6 | Ingreso y consulta de atención | `/activities/atenciones/nueva/`, `/activities/atenciones/<id>/` |
| — | Cargos, Áreas, Grupos, Períodos y Actividades | `/accounts/cargos/`, `/accounts/areas/`, `/accounts/grupos/`, `/configuration/periodos/`, `/activities/` |

### Patrón común de los mantenedores

- Tabla con el estado en texto, búsqueda parcial sin distinguir mayúsculas en varios campos,
  filtros de negocio y tamaños de página **5, 15 y 30** (15 por defecto). El orden inicial es por
  creación descendente, con id descendente como desempate; las columnas habilitadas permiten
  orden ascendente/descendente mediante una lista explícita de campos permitidos.
- Página, tamaño, búsqueda, filtros y orden se conservan en sesión por módulo y contexto.
  Al volver desde un detalle, edición o desde otro módulo se recuperan. Cambiar búsqueda o
  filtros vuelve a la página 1; una página que deja de existir se ajusta a una válida.
- Búsqueda en tiempo real: al dejar de escribir (unos 400 ms) o al cambiar el estado, se
  actualizan solo la tabla, el total y el paginador, en la página 1, y la URL conserva los
  filtros. Sin JavaScript, el botón Buscar hace la misma búsqueda recargando la página.
- Mensajes distintos para listado vacío y búsqueda sin coincidencias, estado de carga mientras
  responde el servidor y páginas de error 400, 403, 404 y 500 con la identidad del sistema (la de 500
  es autónoma para mostrarse aunque falle la base de datos).
- **Exportar a Excel** (`.xlsx`) con todos los resultados autorizados del filtro aplicado, en todas
  sus páginas, sin contraseñas, tokens ni campos internos.
- Formularios con los campos obligatorios marcados con `*`, Guardar y Cancelar. Los resultados y
  las confirmaciones de activar o desactivar se muestran con SweetAlert2.
- Los registros no se eliminan físicamente: según el módulo se desactivan/reactivan,
  se archivan o se cierran. Funcionarios usa archivado; Actividades permite restaurar con permiso
  administrativo; los períodos cerrados no se reabren. Cada
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

1. Se ingresa el correo de la cuenta (`User.email`). El enlace se envía a esa dirección. Editar
   el correo de contacto desde Funcionarios no cambia la dirección de recuperación. El titular
   puede actualizar el correo de su cuenta en «Mi perfil». Las cuentas antiguas sin correo de
   cuenta deben configurarlo antes de usar la recuperación. La respuesta y el tiempo mínimo de respuesta
   (`PASSWORD_RESET_MIN_RESPONSE_SECONDS`) son los mismos exista o no la cuenta; solo una cuenta
   que puede ingresar recibe el enlace, y como máximo uno cada `PASSWORD_RESET_RESEND_WAIT_SECONDS`.
   Cada solicitud queda en `AuditLog` con el correo enmascarado.
2. El enlace es absoluto, con el host de la petición (validado contra `ALLOWED_HOSTS`), vence a
   los `PASSWORD_RESET_TIMEOUT` segundos y deja de valer en cuanto cambia la contraseña, así que
   sirve una sola vez. No se guarda nada en la base. Un enlace inválido, vencido o ya usado
   muestra un mensaje claro y ofrece pedir otro. Los enlaces emitidos antes del cambio a correo
   de cuenta deben solicitarse de nuevo.
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
| Funcionarios | `accounts.view_official` | `accounts.add_official` | `accounts.change_official` para editar; `accounts.archive_official` para archivar |
| Ausencias (licencias, vacaciones, emergencias, compensatorios) | `accounts.view_officialabsence` | `accounts.manage_absence` (más el de consulta) | `accounts.manage_absence` para editar y archivar; solo funcionarios visibles y gestionables por el alcance del rol; bloqueado en períodos cerrados o congelados |
| Actividades | `activities.view_activity` (Excel de actividades sin archivar) | `activities.add_activity` | `activities.change_activity` para editar; `activities.archive_activity` para archivar, consultar historial y restaurar |
| Ítems y metas | `configuration.view_item` | `configuration.add_item` | `configuration.change_item` |
| Tipo de Atención | `configuration.view_attentiontype` | `configuration.add_attentiontype` | `configuration.change_attentiontype` |
| Sub Atención | `configuration.view_subattentiontype` | `configuration.add_subattentiontype` | `configuration.change_subattentiontype` |
| Ingreso de atención | `activities.view_socialattention` (consulta) | `activities.add_socialattention` | — |
| Otros mantenedores | `view_position`, `view_area`, `auth.view_group`, `view_period` | Según permisos del modelo | Según permisos del modelo |

Los permisos provienen del usuario, de sus grupos y de los **roles SGR vigentes** (activos y no
archivados) de su funcionario (`accounts.backends.SGRAuthBackend`). Salvo el superusuario, se
exige además un funcionario habilitado. Cada acceso denegado responde 403 y queda en `AuditLog`
(acción «Acceso denegado»).

**Ámbito por delegación.** Delegaciones, Usuarios, Funcionarios y las atenciones registradas se
limitan a las delegaciones autorizadas del actor (todas si tiene un rol vigente de alcance ALL).
Un identificador de otra delegación responde 404, igual que uno inexistente, y el intento queda en
`AuditLog`. Los formularios solo ofrecen delegaciones del ámbito, de modo que un identificador
fuera de él enviado desde el navegador no valida.

## Medición del desempeño

Las metas y ponderadores salen de los planes de medición publicados por cargo y período
(`MeasurementPlan` → `MeasurementVersion` → `MeasurementItem`, con `MeasurementAdjustment`
individual). `analytics/services.py::CalculadorDesempenoService.calculate(funcionario, período, fecha)`
devuelve, por ítem, meta, avance, cumplimiento con tope, ponderado, meta esperada en unidades,
diferencia y semáforo, además del total del funcionario.

- **Versión aplicada.** Meta, ponderador, umbrales y tope son los de la versión publicada y no archivada vigente a
  la fecha de cálculo para el cargo actual del funcionario. Cada actividad cuenta solo si su ítem
  está en la versión que regía en la fecha de la actividad para el cargo con que se registró; un
  ítem retirado del plan deja de contar desde la nueva vigencia.
- **Ajuste individual.** Si existe, reemplaza la meta o el ponderador de la línea solo para ese funcionario.
- **Avance.** Actividades vigentes del funcionario, ítem y período, con fecha hasta la fecha de
  cálculo y al menos una imagen con validación aprobada no anulada (RN-009). Cada actividad cuenta
  una vez. El resultado cambia solo al aprobar o anular evidencia, al registrar o archivar
  actividades o al cambiar la fecha de cálculo.
- **Fórmulas.** Cumplimiento = avance / meta × 100; computable = mínimo entre cumplimiento y
  `max_computable` (150 % por defecto); ponderado = ponderador × computable / 100; total = suma de
  ponderados. Meta esperada = días computables transcurridos / días computables del período × 100.
- **Semáforo (RN-008).** Compara el cumplimiento sin tope con la meta esperada, ambos en %:
  verde desde `green_threshold` % de lo esperado (100), ámbar desde `amber_threshold` % (60) y rojo
  bajo ese límite. El total usa la misma regla. Se conserva la precisión interna y se redondea a
  dos decimales, con mitad hacia arriba (5,545 → 5,55), solo al mostrar o persistir; los límites del
  semáforo se comparan sin redondear (con esperado 50 %: 29,99 rojo, 30 ámbar, 49,99 ámbar, 50 verde).
- **Sin división por cero.** Una meta nula o igual a 0 (solo posible forzándola en la base) marca
  «Meta no válida» y el ítem no aporta. Un funcionario sin cargo o sin plan publicado recibe un aviso.

### Panel «Mi desempeño» (`/analytics/mi-desempeno/`)

- **Contenido.** Selector de período (por defecto el vigente) y, por ítem: meta, avance,
  cumplimiento, ponderador, ponderado, meta esperada al día, diferencia y semáforo. Total ponderado
  con su semáforo y contadores de evidencias pendientes, rechazadas y con corrección solicitada, y de
  compromisos abiertos, vencidos y realizados. Muestra la delegación del funcionario y las otras en
  que está autorizado. Cada ítem enlaza al listado de Actividades filtrado por ese funcionario, ítem,
  período (hasta hoy si está abierto) y «Solo las que cuentan en la medición»: evidencia aprobada e
  ítem incluido en la versión del plan que rige en su fecha para el cargo con que se registró. Es el
  mismo criterio del avance (`analytics.services.computable_activities`), así que el total del
  listado coincide con el Avance del ítem. El ítem porcentual del tubo no tiene enlace
  porque proviene de la agenda.
- **Semáforo accesible.** Siempre texto + ícono («Verde: en meta» ✓, «Ámbar: bajo lo esperado» !,
  «Rojo: bajo el umbral» ✕); el color solo refuerza.
- **Actividad reciente (RF-030).** Muestra la fecha de la última actividad computable hasta el corte,
  los días transcurridos desde esa actividad, la cantidad de registros válidos del período y el
  promedio diario. El promedio usa días corridos desde el inicio hasta el corte, ambos incluidos.
  El corte es hoy o el término del período, lo que ocurra primero. Con
  `PERFORMANCE_INACTIVITY_DAYS` se puede destacar la inactividad desde el umbral indicado
  (por defecto `0`, desactivado). Si nunca hubo registros válidos, el aviso usa los días desde
  el inicio del período.
- **Acceso.** `analytics.view_indicatorsnapshot` permite ver el propio resultado.
  `analytics.view_team_performance` permite elegir otro funcionario dentro del alcance del rol
  (delegación o global). Un identificador fuera del alcance responde 404 y queda en la auditoría.
  En la semilla: Funcionario, Usuario consulta y Verificador ven solo lo propio; Delegado,
  Coordinador del sistema y Administrador eligen dentro de su alcance. (Usuario consulta no recibe el
  permiso de equipo para que `editorA` pueda seguir asignando ese rol: nadie asigna permisos que no tiene.) El rol «Administrador
  evaluación A» no recibe el panel. `seed_demo` agrega estos permisos a los roles de demostración de
  una base ya cargada sin abortar; solo a los creados por la semilla (descripción con el marcador
  `[SGR seed v1]`). Un rol personalizado con el mismo nombre no se modifica y la carga se detiene.
- Un funcionario sin cargo o sin plan publicado ve un aviso, no un error.

### Tablero de delegación (`/analytics/desempeno-delegacion/`)

Disponible en Desempeño para quienes tienen permiso de consulta de equipo con alcance de delegación
o global. Permite seleccionar la delegación y el período y abrir el detalle por funcionario.
El total de actividades válidas cuenta los registros computables en la delegación donde se
realizaron y abre el listado que respalda esa cifra. Ingreso de atención toma la delegación de la
atención. En un registro manual se elige entre las delegaciones habilitadas del funcionario.
Las actividades manuales anteriores se atribuyen a su delegación principal al migrar, si existe,
y aparecen como estimadas. El listado de respaldo requiere permiso de consulta de actividades.

La tabla de funcionarios se agrupa por delegación principal y mantiene los avances individuales.
El resultado del equipo promedia los puntos de quienes tienen ítems medidos. Los compromisos de
un período abierto se muestran aparte.

Los nuevos cierres guardan los registros exactos que respaldan el total territorial. Los cierres
anteriores conservan sus resultados individuales y muestran un aviso cuando carecen de ese respaldo.

### Vista por cargo (`/analytics/desempeno-cargos/`)

Reutiliza el permiso de consulta de equipo y permite filtrar por período y por una delegación
autorizada o por todas las disponibles para el usuario. Agrupa por cargo y delegación principal
vigentes, o por los registrados en el resultado al cierre de un período. Desde un cargo se puede
consultar las metas y avances del equipo por ítem, el semáforo y la actividad reciente de cada
funcionario, y abrir su panel individual cuando el alcance actual lo permite.

Las cantidades se suman y los porcentajes se promedian por funcionario con dato disponible.
Los indicadores de actividad reciente se calculan con los registros vigentes dentro del alcance
de consulta, incluso cuando el resultado ponderado se muestra congelado.

### Comentarios internos y alertas (RF-035, RF-037)

En el detalle de Actividades y Casos sociales se pueden consultar los comentarios internos con
autor y fecha. Para publicar se requiere permiso de modificación sobre el registro. Los casos
cerrados y las actividades archivadas quedan en consulta. El portal ciudadano muestra sus propios
mensajes de seguimiento y respuestas.

En **Operación → Alertas**, cada funcionario habilitado consulta sus avisos y puede marcarlos como
revisados. Al adjuntar evidencia, se avisa a los verificadores habilitados que pueden revisar ese
registro según sus roles y su ámbito. Una decisión de revisión resuelve el aviso y conserva el
historial. La bandeja vuelve a comprobar permisos sobre los registros enlazados.

Las alertas de desempeño se generan para funcionarios medidos y supervisores autorizados en el
período vigente. El aviso de inactividad usa `PERFORMANCE_INACTIVITY_DAYS` y el de bajo avance usa
el semáforo rojo del plan. Para actualizar ambos:

```bash
python manage.py refresh_performance_alerts
```

Para ejecutarlo automáticamente, programa el comando en el entorno de operación. Puede repetirse:
mantiene un aviso por tipo, destinatario, período y funcionario, y lo resuelve cuando la condición
deja de cumplirse. El mismo comando actualiza los avisos de vencimiento de la Agenda colectiva.

### Agenda colectiva (RF-016 a RF-021)

En **Operación → Agenda colectiva** se pueden registrar compromisos internos o crearlos desde el
detalle de un caso o una actividad. El compromiso conserva su delegación, territorio, responsable,
solicitante, área de apoyo cuando corresponda y registro de origen. El listado y su resumen
comparten filtros de delegación, territorio, responsable, estado y rango de fechas.

El estado inicial es **Ingresado**. Un funcionario autorizado puede avanzar la gestión o dejarla
pendiente con una observación. **Realizado** es el cierre operativo y registra fecha, autor y
observación. Los roles de supervisión pueden reasignar compromisos aún abiertos con motivo
auditable. El cálculo del tubo usa compromisos realizados sobre el total del funcionario por fecha
comprometida. Un compromiso se puede terminar después del cierre del período asociado y conserva
la fecha real, mientras la medición congelada sigue mostrando su resultado al cierre.

El aviso al responsable y a supervisores autorizados se programa con
`COMMITMENT_DUE_WARNING_DAYS` (3 días por defecto). Los avisos se actualizan al crear, reasignar o
cambiar el estado, y al ejecutar `refresh_performance_alerts` para detectar el avance del calendario.
La migración agrega permisos de agenda a los roles de demostración marcados por `seed_demo`.
Los roles personalizados se configuran desde el mantenedor de roles.

### Congelamiento de períodos cerrados (RN-013)

Al cerrar un período (`Period.close_period`, usado por el mantenedor y el admin) se guarda, en la
misma transacción, un `IndicatorSnapshot` congelado por funcionario medible e ítem, calculado al día
de término: meta, avance (también el % del tubo), cumplimiento con y sin tope, ponderador, ponderado
ya calculado, meta esperada, diferencia, semáforo del ítem, semáforo del total y versión del plan.
El cierre fija además `Period.frozen_at`, aunque no haya ningún funcionario medible: esa marca, y no
la existencia de filas, indica que el período está congelado. Los funcionarios archivados no se
congelan. Un período cerrado se muestra
**siempre** desde esos snapshots: archivar o reasignar compromisos, aprobar evidencia o cambiar
planes después del cierre no lo altera. Si se reabre y se vuelve a cerrar, los snapshots anteriores
se archivan y se congela de nuevo; cerrar un período que ya está cerrado no hace nada. Los contadores
de compromisos del panel cuentan los de fecha comprometida dentro del período elegido. Para períodos
cerrados antes de esta función:

```bash
python manage.py freeze_period <id_del_período>
```

Es idempotente: si el período ya tiene `frozen_at` no cambia nada (tampoco si después del cierre
se asigna un cargo con plan a alguien). Mientras no se
ejecute, el panel avisa que el período cerrado no tiene resultados congelados (no los recalcula).

`GoalThreshold` y `Weighting` quedan **obsoletos**: el calculador ya no los consulta. Se conservan
sin migrar ni borrar datos para no perder información; no deben recibir usos nuevos.

## Supuestos y limitaciones

- **Días computables.** Se usan días corridos. Toda la regla vive en
  `analytics.services.computable_days(period, official=None, until=None, include_start_day=False)`.
  - Por defecto (`include_start_day=False`) se cuenta como el ejemplo de la guía: (fecha − inicio).
    1/07–30/09 da 91 días y al 26/08 van 56 (61,54 %); el día de inicio la meta esperada es 0 %.
  - Con `include_start_day=True` el conteo es inclusivo, como el lote de ensayo CAL-D:
    1–30/10 da 30 días; el 1/10 va 3,33 %, el 15/10 va 50 %; antes del inicio 0 % y después del término 100 %.
  - **Divergencia.** Los dos ejemplos son incompatibles: con el conteo por defecto CAL-D da 48,28 %
    al 15/10, y con el inclusivo el ejemplo de la guía daría 92 días y 61,96 %. CAL-D es un dato de
    ensayo propuesto por el plan de pruebas, no una regla institucional, por lo que el sistema usa
    el ejemplo de la guía y deja el modo inclusivo disponible y probado: `calculate(...,
    include_start_day=True)` reproduce CAL-D completo con el resultado del funcionario.
  - RF-005 (guía, tabla de requisitos funcionales): «Configurar períodos de medición. El sistema
    deberá definir fecha de inicio, fecha de término, estado y días computables de cada período. El
    período calcula sus días y rechaza una fecha de término anterior al inicio».
    Los días del período no cambian; las ausencias (A1) solo descuentan los días de cada funcionario.
  - La guía nombra los días computables (RF-005, RN-007) sin definir qué se descuenta; el Excel
    descuenta licencias, vacaciones, emergencias y compensatorios. No se descuentan festivos. Las
    fechas se toman en la zona horaria del proyecto (`timezone.localdate`). Con `official` se
    descuentan licencias, vacaciones, emergencias y compensatorios registrados en `OfficialAbsence`.
    **Supuesto A1:** los rangos incluyen ambas fechas, se recortan al intervalo contado y no se
    superponen. En la convención de 91 días el primer día ya está excluido y no se descuenta otra
    vez. Las ausencias reducen los días del denominador y los días transcurridos del esperado;
    no prorratean las metas del plan. No se encontró una instrucción de prorrateo en las fuentes
    consultadas. Un funcionario sin días computables no tiene semáforo ni participa del promedio.
    Altas, ediciones y archivo de ausencias están bloqueados si el rango anterior o nuevo afecta
    períodos cerrados o congelados. Los días usados se conservan en `IndicatorSnapshot`.
- **Ítems porcentuales.** «Soluciones de ingresos al tubo» tiene meta 80 % y su avance es el % de
  compromisos del funcionario con fecha comprometida en el período que están Realizados (CAL-C y
  CAL-F: 8 de 10 realizados con meta 80 % = 100 %). Sin compromisos no hay denominador: el ítem
  muestra un aviso y no aporta. Al calcular a una fecha pasada solo cuentan los compromisos creados
  hasta ese día, cada uno con el estado que tenía según su historial. El semáforo compara ese
  cumplimiento con la meta esperada del día.
- **Felicitaciones y reclamos (parámetros sujetos a aprobación institucional).** Se propone felicitación =
  +10 puntos sobre el total ponderado (máximo 3 por funcionario y período) y reclamo = −20 puntos
  (el Excel usa −0,2 y −0,3 según la hoja). La guía pide no fijar automáticamente esos valores y
  aplicarlos solo con reglas parametrizadas aprobadas: serán parámetros de la versión del plan y
  los valores +10/−20 son solo los propuestos por defecto hasta que la institución los apruebe.
- **Pendientes en tubo (A2, documentación prevalece).** La matriz SGR del trimestre 2026 (archivo
  de la institución, no incluido en el repositorio), hoja `SALON`, celdas C23/G23, define el
  indicador y su fórmula: cumplimiento 100 % si pendientes ≤ 10 %, 50 % si
  10 % < pendientes ≤ 50 %, y 0 % sobre 50 %. Esto reemplaza el supuesto proporcional 10/valor.
  `MAX_PERCENTAGE` permite definir la meta máxima sin cambiar los planes publicados ni sus pesos;
  para este indicador se configura meta 10. El semáforo compara esos escalones contra 100 %.
  **Supuesto del denominador:** compromisos del funcionario con fecha comprometida en el período
  y creados al corte; pendientes son los no realizados, excluyendo del denominador los cancelados
  con justificación. Sin compromisos computables no se evalúa. El estado al corte usa su historial.
- **Cambio de cargo por tramos (A3).** `OfficialPositionPeriod` conserva fechas inclusivas y sin
  superposición. Los mantenedores de funcionarios y usuarios registran el cambio con su fecha y
  auditan el cierre del tramo anterior y el nuevo. El cargo histórico rige por fecha de actividad;
  cada tramo usa la versión publicada del plan de su cargo vigente al corte del tramo (el mismo
  criterio que el cálculo sin historial aplica a todo el período, así un único tramo da el mismo
  resultado) y sus ausencias. El total es la media de los resultados de los tramos ponderada por
  sus días computables; las metas de cada plan no se prorratean. El cumplimiento de un ítem que
  solo existe en un tramo se mide en ese tramo, y su aporte al total se pondera por los días de
  ese tramo sobre los del período. El formulario de actividades ofrece los ítems del cargo
  vigente en la fecha de la actividad. Se muestra y congela el detalle por tramo.
  Si la meta de un ítem difiere entre tramos, la fila integrada no muestra una meta única (queda
  vacía también al congelar) y el detalle por tramo conserva cada meta. El semáforo de esa fila
  compara contra el esperado de los tramos donde el ítem se evaluó.
  **Limitación de rendimiento:** con historial de cargo, los compromisos de los ítems porcentuales
  se consultan por funcionario y tramo (el resto de los datos se carga en bloque).
  **Reversión de `analytics/0006`:** antes de achicar las columnas convierte `MAX_PERCENTAGE` en
  `PERCENTAGE` y las metas nulas de snapshots por tramos en 0 (el esquema anterior no las admite);
  esa conversión no se deshace al volver a migrar.
  **Supuesto de inicio:** al primer cambio sin historial se registra el cargo anterior desde el
  inicio del primer período abierto conocido, sin extenderlo a períodos ya congelados. Los datos
  anteriores sin historial conservan el comportamiento previo. Un intervalo sin cargo histórico
  se informa y no inventa un plan. La institución debe confirmar la regla de no prorrateo por tramo.
- **Gestión y planificación.** El Excel suma 85 % (falta una fila); se normaliza proporcionalmente
  a 100 %: 17,65 / 35,29 / 5,88 / 41,18. El Delegado usa la misma tabla.
- **Gestor de compras y proyectos.** El Excel no trae su hoja: se asume Reunión semanal 50 % / meta 12
  e Informe trabajo 50 % / meta 12.
- **Emergencia.** El Excel la trae con meta variable; se usa meta 1.
- **Hoja «AP ADM.».** En el Excel su total excluye la fila Emergencia; el SGR suma todas las filas (RF-024).
- **Organizaciones comunitarias.** La fila «Atención de usuario» usa el ítem «Atención de usuario
  teléfono y presencial».
- **Base existente.** `seed_demo` no reemplaza planes ya creados: en una base cargada antes de este
  cambio los planes conservan los ponderadores repartidos en partes iguales. Para aplicar los valores
  reales, crea una revisión del plan desde la pantalla de medición o carga la semilla en una base nueva.
- **Funcionario autorizado en varias delegaciones.** El desempeño es del funcionario completo: el
  total y el avance suman todas sus actividades, aunque se registren en otra delegación. Quien lo
  consulta con alcance de delegación ve ese total, pero el enlace al detalle de actividades queda
  limitado a su alcance y la fila avisa «Incluye N actividades de otra delegación que no puedes ver».
  Con alcance global no hay actividades ocultas.
- **Período futuro.** Antes de que empiece un período, su meta esperada y su avance son 0. El enlace
  a las actividades usa como corte la fecha de inicio, de modo que puede listar actividades fechadas
  ese día (si se registraran por adelantado) que el avance todavía no cuenta.
- **Filtro «Solo las que cuentan en la medición» en archivadas.** El filtro aplica la regla del ítem
  y la evidencia, pero no excluye por sí mismo las actividades archivadas: en el historial de
  archivadas (estado «Archivada») muestra actividades que el avance no cuenta porque están archivadas.
  El enlace del panel siempre abre las vigentes.
- **Actividades antiguas sin cargo registrado.** Las actividades creadas antes de guardar el cargo al
  registrar (`registration_position_captured` falso) se miden con el cargo **actual** del
  funcionario. Si después cambia de cargo, el avance en vivo, el enlace y el aviso de actividades
  ocultas usan el plan del cargo nuevo; un período ya congelado conserva su resultado, pero su enlace
  y su aviso se calculan con ese cargo actual.
- **Datos en vivo en un período cerrado.** El resultado se lee de lo congelado, pero los contadores de
  evidencias y compromisos y la desviación se calculan al consultar.
- **Datos.** Solo datos ficticios: no se cargan nombres ni teléfonos del Excel.

## Arquitectura del proyecto

### Apps

| App             | Responsabilidad                                                                                         | Estado                            |
| --------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------- |
| `accounts`      | Usuarios, funcionarios, delegaciones, territorios, roles, cargos, áreas, grupos, perfil/foto y autenticación | Implementada                      |
| `configuration` | Ítems, catálogos de atención, períodos y auditoría                                                       | Implementada                      |
| `activities`    | CRUD de actividades, ingreso/consulta de atenciones, portal y solicitudes del cliente, consumidores WebSocket | Implementada                      |
| `common`        | `BaseModel`, control de acceso, exportación a Excel, paginación, `get_user_area` y comando `seed_demo` | Implementada                      |
| `agenda`        | Agenda colectiva, comentarios internos y alertas                                                       | Implementada                      |
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
- **Sin acceso a Django Admin con una cuenta de semilla**: es el comportamiento esperado;
  ninguna de las siete cuentas es `staff`. Usar los mantenedores del sitio; el Admin requiere
  una cuenta técnica independiente.
- **La tabla no se actualiza sin F5**: comprobar JavaScript, sesión, estado de conexión y que
  HTTP y WebSocket usen el mismo proceso ASGI; verificar la conexión en la pestaña de red y
  que el host esté permitido. El canal en memoria no comunica procesos distintos.

