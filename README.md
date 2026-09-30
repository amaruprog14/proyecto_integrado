# Proyecto Integrado

Aplicación web en Django con Django Admin personalizado y base de datos MySQL.
Proyecto de la asignatura Programación Back End (TI3041) – Evaluación Sumativa II.

**Equipo:** `<NOMBRES DE LOS INTEGRANTES>`
**Sección:** `<SECCIÓN>`

## Requisitos previos

- Python 3.10 o superior
- Git
- MySQL en ejecución
- En Windows se recomienda usar Git Bash

## Instalación y ejecución

### 1. Clonar el repositorio

```bash
git clone <URL_DEL_REPOSITORIO>
cd proyecto_integrado/
```

### 2. Crear y activar el entorno virtual

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows (Git Bash)
# source .venv/bin/activate        # Linux / macOS
```

### 3. Instalar dependencias

```bash
python -m pip install -r requirements.txt
```

### 4. Configurar variables de entorno

Copiar el archivo de ejemplo y completar los valores reales:

```bash
cp .env.example .env
```

Contenido del `.env`:

```
SECRET_KEY=
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DB_ENGINE=django.db.backends.mysql
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=127.0.0.1
DB_PORT=3306
```

Para generar una `SECRET_KEY` nueva:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

> El archivo `.env` contiene credenciales y **no se versiona** en Git.
> `settings.py` lee todas estas variables desde el entorno; para cambiar de base de datos
> solo se edita el `.env`, nunca el código.

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

### 7. Levantar el servidor

```bash
python manage.py runserver
```

Abrir el Admin en: <http://127.0.0.1:8000/admin/>

## Cuentas de prueba

Creadas por el comando `seed_demo` (solo para demostración):

| Usuario | Contraseña | Rol | Área | Alcance |
|---|---|---|---|---|
| `admin_demo` | `demo1234` | Superusuario | Todas | Acceso completo |
| `funcionario1` a `funcionario5` | `demo1234` | Usuario limitado (staff) | `<PENDIENTE: área de cada uno>` | `<PENDIENTE: qué puede ver/editar>` |

## Datos cargados por `seed_demo`

- 5 áreas, 5 cargos, 5 ítems y 5 períodos (tablas maestras)
- 5 funcionarios y 5 actividades (tablas operativas)
- 1 funcionario con `deleted_at` como evidencia de borrado lógico
- `<PENDIENTE: al menos 2 áreas con funcionarios y actividades en cada una, para demostrar el scoping>`


## Arquitectura del proyecto

### Apps

| App | Responsabilidad | Estado |
|---|---|---|
| `accounts` | Cargos, áreas y funcionarios | Implementada |
| `configuration` | Ítems y períodos (tablas maestras) | Implementada |
| `activities` | Registro de actividades | Implementada |
| `common` | `BaseModel` (auditoría) y comando `seed_demo` | Implementada |
| `agenda` | Planificación de actividades | Reservada para la siguiente etapa |
| `analytics` | Reportes e indicadores | Reservada para la siguiente etapa |

### Estructura de carpetas


```
proyecto_integrado/
├── manage.py
├── requirements.txt
├── .env.example
├── .gitignore
├── config/                     # settings.py, urls.py, wsgi.py
├── common/
│   ├── mixins.py               # BaseModel (created_at, updated_at, deleted_at)
│   └── management/commands/
│       └── seed_demo.py        # Carga de datos de prueba
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
├── agenda/                     # Reservada
└── analytics/                  # Reservada
```

## Modelado y auditoría

Todos los modelos heredan de `common.mixins.BaseModel`, que aporta los campos de
auditoría `created_at`, `updated_at` y `deleted_at`.

Los modelos y atributos del dominio usan nomenclatura en inglés; las etiquetas visibles
en el Admin están en español mediante `verbose_name`.

| Modelo | App | Descripción |
|---|---|---|
| `Area` | `accounts` | `<PENDIENTE>` |
| `Position` | `accounts` | `<PENDIENTE>` |
| `Employee` | `accounts` | `<PENDIENTE>` |
| `Item` | `configuration` | `<PENDIENTE>` |
| `Period` | `configuration` | `<PENDIENTE>` |
| `Activity` | `activities` | `<PENDIENTE>` |

> **PENDIENTE:** confirmar que los nombres de modelos coinciden con el código.

Diagrama entidad-relación: `<PENDIENTE: enlace o ruta, p. ej. docs/er.png>`

## Funcionalidades del Admin

> **PENDIENTE:** completar cuando estén implementadas. No documentar nada que no exista en el código.

### Admin Básico


### Admin Pro




## Seguridad y roles



## Flujo de trabajo Git

- **Rama principal:** `main` (solo commit inicial directo; el resto se integra por merge o Pull Request).
- **Ramas de trabajo:** `<PENDIENTE: p. ej. feature/admin-basico, feature/admin-pro, feature/security-scoping>`
- **Integración:** `<PENDIENTE: merge o Pull Request>`

El `.gitignore` excluye `.env`, `.venv/` y otros archivos locales.

## Problemas frecuentes

- **`Can't connect to MySQL server`**: MySQL no está corriendo o el `DB_HOST`/`DB_PORT` es incorrecto. Usar `127.0.0.1` en lugar de `localhost` en Windows.
- **`Access denied for user`**: revisar `DB_USER` y `DB_PASSWORD` en el `.env`.
- **`Unknown database`**: crear la base de datos (paso 5).
- **Falla la instalación de `mysqlclient`**: en Windows, verificar que el entorno virtual esté activo y que la versión de Python sea compatible.
- **`KeyError: 'SECRET_KEY'`**: falta el archivo `.env` o está incompleto (paso 4).
