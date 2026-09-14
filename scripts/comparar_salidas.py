"""Corre las cuatro rutas sobre los PDF reales y compara lo que sale con lo que salía.

Es la red de seguridad de cualquier refactor o de cualquier optimización: una
que cambie un corte, un tipo, una fecha, un nombre de archivo o una fila del
inventario no es una optimización, es una regresión, y este script es quien lo
dice antes de que lo diga el operador.

Uso, desde la raíz del repositorio y con el intérprete del backend:

    backend/.venv/Scripts/python scripts/comparar_salidas.py --guardar    # fija la referencia
    backend/.venv/Scripts/python scripts/comparar_salidas.py              # compara contra ella
    backend/.venv/Scripts/python scripts/comparar_salidas.py --casos upd  # sólo los casos con "upd"

La referencia queda en backend/data/referencia/ (ignorado por git) y se
regenera sólo a mano, cuando un cambio de comportamiento es deliberado.

Corre sin claves de ningún modelo: lo que se compara es lo que el sistema
decide solo, que es lo único determinista.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend" / "src"))

PRUEBAS = Path("C:/Users/desarrollo.SIAR/Desktop/PRUEBACARPETA")
REFERENCIA = RAIZ / "backend" / "data" / "referencia"

#: (nombre del caso, PDF, tarea). Una por ruta, y las dos cajas UPD porque son
#: el corpus real y el que más reglas ejercita.
CASOS: list[tuple[str, Path, str]] = [
    ("resoluciones-00072", PRUEBAS / "PRUEBA RESOLUCIONES" / "RESOLUCIONES 00072-00094.pdf", "split"),
    ("resoluciones-00960", PRUEBAS / "PRUEBA RESOLUCIONES" / "RESOLUCIONES 00960-00979.pdf", "split"),
    ("diplomas-2013", PRUEBAS / "PRUEBA DIPLO" / "1. 3858079 REGISTRO DE DIPLOMAS N°08 2013.pdf", "split"),
    ("diplomas-2011", PRUEBAS / "PRUEBA DIPLO" / "5.3858083 REGISTRO DE DIPLOMAS N°08 2011.pdf", "split"),
    (
        "diplomas-2013-inventario",
        PRUEBAS / "PRUEBA DIPLO" / "1. 3858079 REGISTRO DE DIPLOMAS N°08 2013.pdf",
        "inventory",
    ),
    ("upd2365925", PRUEBAS / "PRUEBA UPD" / "UPD2365925.pdf", "segment"),
    ("upd2366126", PRUEBAS / "PRUEBA UPD" / "UPD2366126.pdf", "segment"),
]

#: Claves que cambian de una corrida a otra sin que cambie el resultado.
VOLATILES = ("seconds", "elapsed", "started", "finished", "duration", "timestamp", "recorded_at")


def _sin_volatiles(valor, salida: str):
    """El informe sin relojes ni rutas absolutas, listo para comparar."""
    if isinstance(valor, dict):
        return {
            clave: _sin_volatiles(contenido, salida)
            for clave, contenido in valor.items()
            if not any(marca in str(clave).lower() for marca in VOLATILES)
        }
    if isinstance(valor, list):
        return [_sin_volatiles(elemento, salida) for elemento in valor]
    if isinstance(valor, str) and salida in valor:
        return valor.replace(salida, "<SALIDA>")
    return valor


def _archivos(carpeta: Path) -> list[str]:
    return sorted(
        str(ruta.relative_to(carpeta)).replace(os.sep, "/")
        for ruta in carpeta.rglob("*")
        if ruta.is_file()
    )


def correr(caso: str, pdf: Path, tarea: str) -> tuple[dict, float]:
    """Una ruta sobre un PDF, en una carpeta de salida limpia."""
    from resolutions.api.settings import Settings
    from resolutions.api.worker import process_document_job

    salida = Path(tempfile.mkdtemp(prefix=f"referencia-{caso}-"))
    try:
        ajustes = Settings(output_dir=salida).as_worker_payload()
        for clave in ("anthropic_api_key", "gemini_api_key", "mistral_api_key"):
            ajustes[clave] = None
        payload = {
            "job_id": caso,
            "source": str(pdf),
            "filename": pdf.name,
            "operator": "referencia",
            "task": tarea,
            "settings": ajustes,
        }
        inicio = time.perf_counter()
        informe = process_document_job(payload)
        segundos = time.perf_counter() - inicio
        resumen = _sin_volatiles(informe, str(salida))
        resumen["archivos"] = _archivos(salida)
        return resumen, segundos
    finally:
        shutil.rmtree(salida, ignore_errors=True)


def _corto(valor) -> str:
    return json.dumps(valor, ensure_ascii=False)[:140]


def diferencias(esperado, obtenido, ruta: str = "") -> list[str]:
    """Dónde difieren dos informes, con la ruta de cada diferencia."""
    if isinstance(esperado, dict) and isinstance(obtenido, dict):
        lineas: list[str] = []
        for clave in sorted(set(esperado) | set(obtenido), key=str):
            aqui = f"{ruta}.{clave}" if ruta else str(clave)
            if clave not in esperado:
                lineas.append(f"{aqui}: nuevo = {_corto(obtenido[clave])}")
            elif clave not in obtenido:
                lineas.append(f"{aqui}: desapareció (era {_corto(esperado[clave])})")
            else:
                lineas.extend(diferencias(esperado[clave], obtenido[clave], aqui))
        return lineas
    if isinstance(esperado, list) and isinstance(obtenido, list):
        if len(esperado) != len(obtenido):
            return [f"{ruta}: {len(esperado)} elementos antes, {len(obtenido)} ahora"]
        lineas = []
        for indice, (antes, ahora) in enumerate(zip(esperado, obtenido, strict=True)):
            lineas.extend(diferencias(antes, ahora, f"{ruta}[{indice}]"))
        return lineas
    if esperado != obtenido:
        return [f"{ruta}: {_corto(esperado)} -> {_corto(obtenido)}"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--guardar", action="store_true", help="fijar la referencia en vez de comparar"
    )
    parser.add_argument(
        "--casos", default="", help="sólo los casos cuyo nombre contenga este texto"
    )
    parser.add_argument("--tope", type=int, default=40, help="cuántas diferencias enseñar")
    argumentos = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    REFERENCIA.mkdir(parents=True, exist_ok=True)
    casos = [caso for caso in CASOS if argumentos.casos.lower() in caso[0].lower()]
    if not casos:
        print(f"ningún caso contiene {argumentos.casos!r}")
        return 2

    fallos = 0
    for nombre, pdf, tarea in casos:
        if not pdf.exists():
            print(f"-- {nombre}: no está {pdf}")
            fallos += 1
            continue
        resumen, segundos = correr(nombre, pdf, tarea)
        unidades = len(resumen.get("outputs") or [])
        destino = REFERENCIA / f"{nombre}.json"
        if argumentos.guardar:
            destino.write_text(
                json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            print(f"ok {nombre}: {unidades} unidades, {segundos:.1f} s -> guardado")
            continue
        if not destino.exists():
            print(f"-- {nombre}: sin referencia; corra con --guardar")
            fallos += 1
            continue
        esperado = json.loads(destino.read_text(encoding="utf-8"))
        distintas = diferencias(esperado, resumen)
        if distintas:
            fallos += 1
            print(f"XX {nombre}: {len(distintas)} diferencia(s), {unidades} unidades, {segundos:.1f} s")
            for linea in distintas[: argumentos.tope]:
                print(f"     {linea}")
            if len(distintas) > argumentos.tope:
                print(f"     ... y {len(distintas) - argumentos.tope} más")
        else:
            print(f"ok {nombre}: idéntico, {unidades} unidades, {segundos:.1f} s")

    print()
    print("todo idéntico" if fallos == 0 else f"{fallos} caso(s) con diferencias")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
