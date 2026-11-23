"""Prueba de carga simple del SGR (B16 / B18), solo con la biblioteca estándar.

Simula N usuarios simultáneos. Cada usuario virtual abre su propia sesión (inicia sesión con el
formulario normal, con su token CSRF) y luego consulta «Mi desempeño» y «Actividades» hasta
completar el total de solicitudes. Al final informa, por operación, la cantidad, los errores, el
promedio, el p95 y el máximo de los tiempos de respuesta, y cuántos usuarios virtuales alcanzaron a
hacer al menos una consulta. Un fallo de red se registra con el tiempo que realmente tardó en fallar.

Uso (servidor local levantado con `python manage.py runserver`):

    PowerShell: $env:SGR_CLAVE_PRUEBA = "<clave de las cuentas de prueba>"
    python scripts/prueba_carga.py --url http://127.0.0.1:8000 \
        --usuarios adminA,editorA,readerA,readerB --concurrencia 20 --solicitudes 200

Cada cuenta debe poder abrir ambas pantallas: una cuenta sin permiso de desempeño (por ejemplo
adminEvalA) recibe 403 en «Mi desempeño» y el script lo cuenta como error.

La contraseña se lee de la variable de entorno SGR_CLAVE_PRUEBA o de --archivo-clave; nunca se
pasa como argumento (quedaría en el historial y en la lista de procesos). Si hay menos cuentas que
usuarios virtuales, las cuentas se reparten en rueda: cada usuario virtual tiene su propia sesión.

Contra un servidor que no sea local se exige --permitir-remoto. Úsalo solo en el entorno de
prueba autorizado y con carga baja; el script no intenta superar límites ni hacer estrés.
"""
import argparse
import json
import math
import os
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

LOGIN = "/accounts/login/"
OPERACIONES = (("Mi desempeño", "/analytics/mi-desempeno/"), ("Actividades", "/activities/"))
LOCALES = {"127.0.0.1", "localhost", "::1"}
CSRF_INPUT = re.compile(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"')


class Registro:
    """Tiempos y errores por operación, compartidos entre hilos."""

    def __init__(self):
        self.lock = threading.Lock()
        self.tiempos = {}
        self.errores = {}
        self.detalle_errores = {}
        self.con_consulta = set()

    def anotar(self, operacion, segundos, error=None, usuario=None):
        with self.lock:
            self.tiempos.setdefault(operacion, []).append(segundos)
            if usuario is not None and not error:
                self.con_consulta.add(usuario)
            if error:
                self.errores[operacion] = self.errores.get(operacion, 0) + 1
                clave = f"{operacion}: {error}"
                self.detalle_errores[clave] = self.detalle_errores.get(clave, 0) + 1


def percentil(valores, p):
    """Percentil por rango más cercano (sin interpolar)."""
    ordenados = sorted(valores)
    indice = max(0, math.ceil(p / 100 * len(ordenados)) - 1)
    return ordenados[indice]


class FalloRed(Exception):
    """Fallo de red o de tiempo de espera, con los segundos que transcurrieron hasta el fallo."""

    def __init__(self, error, segundos):
        super().__init__(str(error))
        self.tipo = type(error).__name__
        self.segundos = segundos


def solicitar(opener, url, timeout, datos=None, referer=None):
    """Devuelve (código, url final, cuerpo, segundos). Un error HTTP también se mide; un fallo de red
    lanza FalloRed con el tiempo real transcurrido (no el máximo de espera)."""
    cabeceras = {"User-Agent": "SGR-prueba-carga/1.0"}
    if referer:
        cabeceras["Referer"] = referer
    cuerpo = urlencode(datos).encode() if datos is not None else None
    inicio = time.perf_counter()
    try:
        with opener.open(Request(url, data=cuerpo, headers=cabeceras), timeout=timeout) as respuesta:
            contenido = respuesta.read()
            return respuesta.status, respuesta.geturl(), contenido, time.perf_counter() - inicio
    except HTTPError as error:
        return error.code, url, b"", time.perf_counter() - inicio
    except (URLError, TimeoutError, OSError) as error:
        raise FalloRed(error, time.perf_counter() - inicio) from error


def iniciar_sesion(base, usuario, clave, timeout, registro):
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    url_login = urljoin(base, LOGIN)
    try:
        codigo, _, html, segundos = solicitar(opener, url_login, timeout)
        token = CSRF_INPUT.search(html.decode("utf-8", "replace")) if codigo == 200 else None
        registro.anotar("Formulario de inicio de sesión", segundos, None if token else f"HTTP {codigo}")
        if not token:
            return None
        codigo, final, _, segundos = solicitar(
            opener, url_login, timeout, referer=url_login,
            datos={"csrfmiddlewaretoken": token.group(1), "username": usuario, "password": clave},
        )
        # Credenciales válidas: 302 a la portada. Si se queda en /accounts/login/, falló el ingreso.
        fallo = None if codigo == 200 and LOGIN not in urlparse(final).path else f"ingreso rechazado (HTTP {codigo})"
        registro.anotar("Inicio de sesión", segundos, fallo)
        return None if fallo else opener
    except FalloRed as fallo:
        registro.anotar("Inicio de sesión", fallo.segundos, fallo.tipo)
        return None


def usuario_virtual(numero, base, cuentas, clave, timeout, pendientes, registro):
    opener = iniciar_sesion(base, cuentas[numero % len(cuentas)], clave, timeout, registro)
    if opener is None:
        return
    turno = numero
    while pendientes.tomar():
        nombre, ruta = OPERACIONES[turno % len(OPERACIONES)]
        turno += 1
        try:
            codigo, final, _, segundos = solicitar(opener, urljoin(base, ruta), timeout)
            error = None
            if codigo != 200:
                error = f"HTTP {codigo}"
            elif LOGIN in urlparse(final).path:
                error = "redirigido al inicio de sesión"
            registro.anotar(nombre, segundos, error, usuario=numero)
        except FalloRed as fallo:
            registro.anotar(nombre, fallo.segundos, fallo.tipo)


class Cupo:
    """Total de consultas (después del inicio de sesión) repartido entre los usuarios virtuales."""

    def __init__(self, total):
        self.restantes = total
        self.lock = threading.Lock()

    def tomar(self):
        with self.lock:
            if self.restantes <= 0:
                return False
            self.restantes -= 1
            return True


def leer_clave(archivo):
    if archivo:
        with open(archivo, encoding="utf-8") as origen:
            return origen.read().strip()
    clave = os.environ.get("SGR_CLAVE_PRUEBA", "")
    if not clave:
        sys.exit("Falta la contraseña: define SGR_CLAVE_PRUEBA o usa --archivo-clave.")
    return clave


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="URL base del SGR.")
    parser.add_argument("--usuarios", required=True, help="Cuentas de prueba separadas por coma.")
    parser.add_argument("--archivo-clave", help="Archivo con la contraseña de las cuentas de prueba.")
    parser.add_argument("--concurrencia", type=int, default=20, help="Usuarios virtuales simultáneos.")
    parser.add_argument("--solicitudes", type=int, default=200,
                        help="Consultas en total (Mi desempeño y Actividades), sin contar el inicio de sesión.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Segundos máximos por solicitud.")
    parser.add_argument("--json", help="Guarda el resumen en este archivo JSON.")
    parser.add_argument("--permitir-remoto", action="store_true",
                        help="Necesario para un servidor que no sea local (solo entorno de prueba autorizado).")
    args = parser.parse_args()

    host = urlparse(args.url).hostname or ""
    if host not in LOCALES and not args.permitir_remoto:
        sys.exit(f"{host} no es local. Agrega --permitir-remoto solo si es el entorno de prueba autorizado.")
    if args.concurrencia < 1 or args.solicitudes < 1:
        sys.exit("La concurrencia y las solicitudes deben ser mayores que cero.")
    cuentas = [cuenta.strip() for cuenta in args.usuarios.split(",") if cuenta.strip()]
    if not cuentas:
        sys.exit("Indica al menos una cuenta en --usuarios.")
    clave = leer_clave(args.archivo_clave)

    # Un ingreso de prueba por cuenta antes de lanzar la carga (no entra en los totales): con una clave
    # equivocada, el reparto en rueda repetiría el fallo y el bloqueo por intentos (5 por cuenta)
    # dejaría la cuenta bloqueada.
    for cuenta in dict.fromkeys(cuentas):
        if iniciar_sesion(args.url, cuenta, clave, args.timeout, Registro()) is None:
            sys.exit(f"El ingreso de prueba con {cuenta} falló; no se lanza la carga para no bloquear cuentas.")

    registro, cupo = Registro(), Cupo(args.solicitudes)
    inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrencia) as hilos:
        tareas = [hilos.submit(usuario_virtual, numero, args.url, cuentas, clave, args.timeout, cupo, registro)
                  for numero in range(args.concurrencia)]
    duracion = time.perf_counter() - inicio
    for tarea in tareas:
        # Una excepción inesperada dentro de un hilo no puede pasar como ejecución limpia.
        if (fallo := tarea.exception()) is not None:
            registro.anotar("Usuario virtual", 0.0, f"excepción {type(fallo).__name__}")

    filas = []
    for operacion, tiempos in registro.tiempos.items():
        filas.append({
            "operacion": operacion, "solicitudes": len(tiempos), "errores": registro.errores.get(operacion, 0),
            "promedio_ms": round(statistics.mean(tiempos) * 1000, 1),
            "p95_ms": round(percentil(tiempos, 95) * 1000, 1), "maximo_ms": round(max(tiempos) * 1000, 1),
        })
    total = sum(fila["solicitudes"] for fila in filas)
    errores = sum(fila["errores"] for fila in filas)
    consultas = sum(len(registro.tiempos.get(nombre, [])) for nombre, _ in OPERACIONES)
    resumen = {
        "url": args.url, "usuarios_virtuales": args.concurrencia, "cuentas": len(cuentas),
        "consultas_pedidas": args.solicitudes, "solicitudes_totales": total, "errores": errores,
        "usuarios_con_consulta": len(registro.con_consulta),
        "duracion_s": round(duracion, 2), "solicitudes_por_segundo": round(total / duracion, 2) if duracion else None,
        "operaciones": filas, "detalle_errores": registro.detalle_errores,
    }

    print(f"URL: {args.url} · usuarios virtuales: {args.concurrencia} · cuentas: {len(cuentas)}")
    print(f"Duración: {resumen['duracion_s']} s · solicitudes: {total} · "
          f"por segundo: {resumen['solicitudes_por_segundo']} · errores: {errores}")
    print(f"Usuarios virtuales que alcanzaron a consultar: {len(registro.con_consulta)} de {args.concurrencia}")
    print(f"{'Operación':32} {'N':>5} {'Errores':>8} {'Prom. ms':>9} {'p95 ms':>9} {'Máx. ms':>9}")
    for fila in filas:
        print(f"{fila['operacion']:32} {fila['solicitudes']:>5} {fila['errores']:>8} "
              f"{fila['promedio_ms']:>9} {fila['p95_ms']:>9} {fila['maximo_ms']:>9}")
    for detalle, cantidad in registro.detalle_errores.items():
        print(f"  Error · {detalle}: {cantidad}")
    if consultas < args.solicitudes:
        print(f"Solo se hicieron {consultas} de {args.solicitudes} consultas pedidas.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as destino:
            json.dump(resumen, destino, ensure_ascii=False, indent=2)
    return 1 if errores or consultas < args.solicitudes else 0


if __name__ == "__main__":
    sys.exit(main())
