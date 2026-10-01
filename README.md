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

Abrir el Admin en: <http://127.0.0.1:8000/admin/>

## Cuentas de prueba

Creadas por el comando `seed_demo` (solo para demostración). Todas usan la contraseña `demo1234`.

| Usuario                        | Rol                         | Área         | Alcance                                                                                                                                         |
| ------------------------------ | --------------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `admin_demo`                   | Superusuario                | Todas        | Acceso completo (incluye eliminar y ver registros archivados)                                                                                   |
| `funcionario1`, `funcionario2` | Staff, grupo `Funcionarios` | Área Norte   | Ve y gestiona actividades de su área; solo consulta funcionarios e ítems                                                                        |
| `funcionario3`, `funcionario4` | Staff, grupo `Funcionarios` | Área Sur     | Ve y gestiona actividades de su área; solo consulta funcionarios e ítems                                                                        |
| `funcionario5`                 | Staff, grupo `Funcionarios` | Sin contexto | Su funcionario asociado está archivado y sin usuario vinculado: **acceso denegado** (demuestra que la falta de contexto nunca amplía el acceso) |
| `consulta_norte`               | Staff, grupo `Consulta`     | Área Norte   | Solo lectura sobre actividades, funcionarios e ítems de su área                                                                                 |

Grupos y permisos (definidos en `seed_demo`):

| Grupo          | Permisos                                                                                           |
| -------------- | -------------------------------------------------------------------------------------------------- |
| `Funcionarios` | `view`, `add` y `change` sobre Actividad; `view` sobre Funcionario e Ítem. Sin permiso de eliminar |
| `Consulta`     | Solo `view` sobre Actividad, Funcionario e Ítem                                                    |

## Datos cargados por `seed_demo`

- 5 áreas (Norte, Sur, Centro, Cordillera, Costa), 5 cargos, 5 ítems y 5 períodos (tablas maestras)
- 6 funcionarios: 2 en Área Norte, 2 en Área Sur, 1 en Área Centro (archivado) y 1 de consulta en Área Norte
- 10 actividades (2 por cada uno de los 5 funcionarios principales)
- 1 funcionario con `deleted_at` como evidencia de borrado lógico
- Áreas Norte y Sur con funcionarios y actividades, para demostrar el scoping por área

## Arquitectura del proyecto

### Apps

| App             | Responsabilidad                                                          | Estado                            |
| --------------- | ------------------------------------------------------------------------ | --------------------------------- |
| `accounts`      | Cargos, áreas y funcionarios                                             | Implementada                      |
| `configuration` | Ítems y períodos (tablas maestras)                                       | Implementada                      |
| `activities`    | Registro de actividades                                                  | Implementada                      |
| `common`        | `BaseModel` (auditoría), `get_user_area` (scoping) y comando `seed_demo` | Implementada                      |
| `agenda`        | Planificación de actividades                                             | Reservada para la siguiente etapa |
| `analytics`     | Reportes e indicadores                                                   | Reservada para la siguiente etapa |

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
