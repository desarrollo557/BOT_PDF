"""Verifica la dirección de las dependencias entre capas.

La regla que sostiene el diseño de `backend/src/resolutions` es que las flechas
apuntan hacia adentro: el dominio no sabe que existe una base de datos, un
framework web ni un motor de OCR. Un `import` en el sentido contrario compila
igual y sólo se nota meses después, cuando cambiar de adaptador obliga a tocar
las reglas de negocio. Por eso se comprueba en CI y no por revisión visual.

    dominio      -> nada del proyecto salvo el propio dominio
    aplicación   -> dominio
    adaptadores  -> aplicación, dominio
    api          -> todo lo anterior

Sale con código 1 y lista cada violación con archivo y línea.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / "backend" / "src" / "resolutions"

# Qué capa puede importar a qué otra capa del propio paquete.
PERMITIDO: dict[str, set[str]] = {
    "domain": {"domain"},
    "application": {"domain", "application"},
    "adapters": {"domain", "application", "adapters"},
    "api": {"domain", "application", "adapters", "api"},
}

# Paquetes de terceros que no pueden aparecer en el núcleo. El dominio y la
# aplicación se prueban sin instalar nada de esto.
TERCEROS_PROHIBIDOS = {
    "fastapi",
    "starlette",
    "uvicorn",
    "fitz",
    "pymupdf",
    "pytesseract",
    "PIL",
    "anthropic",
    "pymysql",
    "openpyxl",
    "httpx",
}
NUCLEO = {"domain", "application"}


def capa_de(archivo: Path) -> str:
    return archivo.relative_to(RAIZ).parts[0]


def modulos_importados(arbol: ast.AST, capa: str) -> list[tuple[int, str]]:
    """Devuelve (línea, módulo) de cada import, resolviendo los relativos."""
    encontrados: list[tuple[int, str]] = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                encontrados.append((nodo.lineno, alias.name))
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level == 0:
                encontrados.append((nodo.lineno, nodo.module or ""))
            elif nodo.level == 1:
                # `from .anchor import ...` — dentro de la misma capa.
                encontrados.append((nodo.lineno, f"{capa}.{nodo.module or ''}"))
            else:
                # `from ..domain.grouping import ...` — sube al paquete raíz.
                encontrados.append((nodo.lineno, nodo.module or ""))
    return encontrados


def main() -> int:
    if not RAIZ.is_dir():
        print(f"no encuentro {RAIZ}", file=sys.stderr)
        return 2

    violaciones: list[str] = []
    for archivo in sorted(RAIZ.rglob("*.py")):
        if "__pycache__" in archivo.parts:
            continue
        capa = capa_de(archivo)
        if capa not in PERMITIDO:
            continue
        relativo = archivo.relative_to(RAIZ.parent.parent.parent)
        arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))

        for linea, modulo in modulos_importados(arbol, capa):
            if not modulo:
                continue
            cabeza = modulo.split(".")[0]

            if cabeza in PERMITIDO and cabeza not in PERMITIDO[capa]:
                violaciones.append(
                    f"{relativo}:{linea}: {capa} importa {cabeza} "
                    f"(permitido: {', '.join(sorted(PERMITIDO[capa]))})"
                )
            if capa in NUCLEO and cabeza in TERCEROS_PROHIBIDOS:
                violaciones.append(
                    f"{relativo}:{linea}: {capa} importa {cabeza}; "
                    "el núcleo no depende de librerías de infraestructura"
                )

    if violaciones:
        print("Dependencias en el sentido equivocado:\n")
        for v in violaciones:
            print(f"  {v}")
        print(f"\n{len(violaciones)} violación(es).")
        return 1

    print("Capas correctas: el dominio no importa infraestructura.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
