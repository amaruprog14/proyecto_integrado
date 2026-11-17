# API REST de desempeño del SGR

La API devuelve los indicadores de los tableros del SGR. Las consultas usan el período vigente cuando se omite `periodo` y entregan el resultado congelado cuando el período está cerrado. El JSON representa los decimales con dos posiciones. Un aviso y valores `null` indican que faltan datos para calcular el resultado.

## Puesta en marcha local

Activa el entorno virtual del proyecto, configura la base en `.env` y usa `DEBUG=True` para abrir la documentación en local.

```powershell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver --noreload
```

## Probar en Swagger o Postman

1. Inicia sesión en la web del SGR con una cuenta que tenga permiso de desempeño. En el mismo navegador abre `http://127.0.0.1:8000/api/swagger/`. ReDoc está en `/api/redoc/` y el esquema en `/api/schema/`.
2. En Swagger abre **Obtener tokens del SGR** y pulsa **Try it out**. Envía tu usuario o correo en `username` y tu contraseña en `password`. La respuesta contiene `access` y `refresh`.
3. Pulsa **Authorize** y pega solo el valor de `access`. Si usas Postman, envía `Authorization: Bearer <access>` en cada consulta.
4. Ejecuta `GET /api/v1/periodos/`. Usa un ID devuelto para probar `GET /api/v1/mi-desempeno/?periodo=3`, reemplazando `3` por el ID correspondiente.
5. Con un supervisor autorizado, prueba `GET /api/v1/delegaciones/2/desempeno/?periodo=3`, reemplazando ambos identificadores. Puedes obtener el ID de la delegación desde su detalle en el mantenedor. Compara los datos con el tablero de esa delegación y período.
6. Para renovar el acceso, envía `{"refresh":"…"}` a `POST /api/token/refresh/`. Conserva el token de renovación en el cliente y reemplaza el de acceso por el que devuelve la respuesta.

El acceso dura 5 minutos y la renovación 1 día. Los permisos actuales se consultan al recibir cada solicitud. La API responde `401` por falta de autenticación, `403` por permiso insuficiente y `404` si la delegación queda fuera del alcance o el período no está disponible. Un parámetro de período inválido devuelve `400`.

Al cambiar o recuperar la contraseña, los tokens de acceso y renovación anteriores responden
`401`. El cliente debe obtener otro par con la nueva contraseña. Esta comprobación también
rechaza los tokens emitidos antes de habilitar la revocación por cambio de contraseña, por lo
que al actualizar el servicio los clientes de la API deben volver a autenticarse.

## Reconciliar el resultado final

`GET /api/v1/mi-desempeno/` mantiene todos sus campos anteriores (`total_ponderado` sigue siendo el resultado final) y agrega estos para explicar la cifra:

| Campo | Significado |
| --- | --- |
| `total_base` | Suma de `resultado_ponderado` de los ítems, sin reclamos ni felicitaciones. |
| `ajustes_computables` | Suma de `puntos_computables` de los reclamos y felicitaciones aprobados. |
| `tope_resultado_final` | Tope del resultado final configurado en la versión del plan (`150.00` por defecto). |
| `ajustes` | Detalle de cada ajuste aprobado: `tipo` (Felicitación o Reclamo), `fecha` del hecho, `puntos_autorizados`, `puntos_computables` y `excluido_por_limite`. |

La regla es `total_ponderado = min(total_base + ajustes_computables, tope_resultado_final)`. Solo computan las tres primeras felicitaciones aprobadas del período; las siguientes aparecen con `excluido_por_limite: true` y `puntos_computables: "0.00"`. Un reclamo tiene puntos negativos. En un corte intermedio solo cuentan los ajustes validados hasta la fecha de corte. En un período congelado `total_ponderado`, `total_base`, `ajustes_computables` y `ajustes` salen del resumen guardado al cierre y no cambian aunque después se modifiquen los ajustes, igual que `tope_resultado_final` (los resúmenes congelados antes de que el tope fuera configurable informan 150, la regla vigente entonces). En resultados congelados antes de existir ese resumen, el total es la suma de los ítems sin ajustes y `tope_resultado_final` es `null`, porque no se aplicó tope. Sin indicadores, `total_base`, `ajustes_computables` y `tope_resultado_final` son `null` y `ajustes` es una lista vacía. Los valores se redondean a dos decimales al mostrarlos, por lo que la suma puede diferir en un centésimo.

## Actualizar en EC2

Después de incorporar los cambios, ejecuta estos comandos desde la carpeta del proyecto con el mismo entorno virtual que usa el servicio.

```sh
python -m pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py check
```

Mantén `DEBUG=False`. Para servir Swagger, ReDoc y el esquema, configura `SGR_API_DOCS_ENABLED=True` en el entorno del servicio. Simple JWT usa `SECRET_KEY` por defecto. Puedes configurar una clave de firma independiente mediante `SGR_API_JWT_SIGNING_KEY`. Aplica las variables y reinicia el servicio existente.

Comprueba por HTTPS que el proxy dirija `/api/` a Django, entregue el encabezado `Authorization` y sirva los estáticos recopilados. Abre Swagger con una sesión web autorizada, ejecuta las tres consultas y compara los resultados con la web usando el mismo período. Usa las cuentas y datos disponibles en esa instancia.

## Verificación automatizada

```sh
python manage.py spectacular --validate --fail-on-warn
python manage.py test sgr_api analytics.test_performance_panel
```
