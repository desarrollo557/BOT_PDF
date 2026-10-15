"""Comprueba que la bóveda de Obsidian sigue describiendo este código.

El contexto del proyecto -- por qué una regla corta donde corta, qué fija cada
prueba, cómo se opera -- no vive en el repositorio sino en una bóveda de
Obsidian, con una nota por archivo de código, una por endpoint y una por tabla.
Esa separación es deliberada: el repositorio lleva el código y la bóveda lleva
el porqué. El precio de separarlas es que se desincronizan en silencio, y una
nota que describe un archivo borrado engaña más que la ausencia de nota.

Esto lo detecta. Cada nota declara en su frontmatter el archivo real que
describe (`archivo: backend/src/...`), así que basta con cruzar las dos listas.

    python scripts/obsidian_check.py

La bóveda está fuera del repositorio. Se busca en OBSIDIAN_VAULT y, si no está
definida, en la ruta de costumbre. **Si no se encuentra, el script no falla**:
en CI la bóveda no existe y bloquear un PR por eso no tendría sentido.

Sale con código 1 si encuentra deriva, y lista cada caso.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PROYECTO = "10-Proyectos/BOT-PDF"

BOVEDA_POR_DEFECTO = Path.home() / "Documents" / "Obsidian" / "Eduver-Vault"

# Qué archivos del repositorio se espera que tengan nota. Lo demás es ruido:
# los `__init__.py` están vacíos, los tests se documentan en las notas de
# Pruebas/ (una por suite, no una por archivo) y los `+page.ts` de SvelteKit
# sólo declaran opciones de renderizado.
PATRONES_DE_CODIGO = (
    "backend/src/**/*.py",
    "web/src/**/*.ts",
    "web/src/**/*.svelte",
)
SIN_NOTA_ESPERADO = (
    re.compile(r"__init__\.py$"),
    re.compile(r"\.test\.ts$"),
    re.compile(r"\+(page|layout)\.ts$"),
)

ENLACE = re.compile(r"\[\[([^\]]+)\]\]")
CAMPO_ARCHIVO = re.compile(r"^archivo:\s*(.+?)\s*$", re.MULTILINE)


def localizar_boveda() -> Path | None:
    """La bóveda, o None si no está en esta máquina."""
    candidata = Path(os.environ.get("OBSIDIAN_VAULT", "")) if os.environ.get("OBSIDIAN_VAULT") else BOVEDA_POR_DEFECTO
    return candidata if (candidata / PROYECTO).is_dir() else None


def notas_de(carpeta: Path) -> list[Path]:
    return sorted(p for p in carpeta.rglob("*.md") if p.is_file())


def destino_del_enlace(crudo: str) -> str:
    """`[[nota|alias]]` y `[[nota#seccion]]` apuntan los dos a `nota`."""
    return crudo.split("|")[0].split("#")[0].strip()


def archivos_de_codigo() -> list[str]:
    """Los archivos que git tiene rastreados, no los que hay en el disco.

    Un `.venv` o un `node_modules` dentro del árbol multiplicaría la lista por
    mil y llenaría la salida de ruido que nadie va a documentar.
    """
    salida = subprocess.run(
        ["git", "ls-files", *PATRONES_DE_CODIGO],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )
    return sorted(linea for linea in salida.stdout.splitlines() if linea)


def revisar(boveda: Path) -> list[tuple[str, list[str]]]:
    """Devuelve (título del problema, casos) por cada comprobación que falla."""
    carpeta = boveda / PROYECTO
    notas = notas_de(carpeta)
    textos = {n: n.read_text(encoding="utf-8") for n in notas}

    nombres_del_proyecto = {n.stem for n in notas}
    nombres_de_la_boveda = {
        p.stem for p in boveda.rglob("*.md") if ".obsidian" not in p.parts
    }

    enlazados: set[str] = set()
    for texto in textos.values():
        for crudo in ENLACE.findall(texto):
            enlazados.add(destino_del_enlace(crudo))

    documentados = {
        m.group(1) for texto in textos.values() for m in CAMPO_ARCHIVO.finditer(texto)
    }

    problemas: list[tuple[str, list[str]]] = []

    def apuntar(titulo: str, casos: list[str]) -> None:
        if casos:
            problemas.append((titulo, sorted(casos)))

    # 1. La nota describe un archivo que ya no está: el código se movió o se
    #    borró y la nota se quedó contando algo que no existe.
    apuntar(
        "Notas que describen archivos que ya no existen",
        [f"{ruta}  (nota: {n.stem})"
         for n in notas
         for ruta in CAMPO_ARCHIVO.findall(textos[n])
         if not (RAIZ / ruta).is_file()],
    )

    # 2. Código nuevo que nadie documentó.
    apuntar(
        "Archivos de código sin nota",
        [ruta for ruta in archivos_de_codigo()
         if ruta not in documentados
         and not any(p.search(ruta) for p in SIN_NOTA_ESPERADO)],
    )

    # 3. Enlaces que no resuelven: los círculos rojos del grafo.
    apuntar(
        "Enlaces rotos",
        [f"[[{destino}]]" for destino in enlazados if destino not in nombres_de_la_boveda],
    )

    # 4. Notas a las que no llega nadie. Existen, pero no se puede llegar a
    #    ellas recorriendo el grafo, que es para lo que se escribieron.
    apuntar(
        "Notas que nadie enlaza",
        [nombre for nombre in nombres_del_proyecto if nombre not in enlazados],
    )

    # 5. Obsidian lee lo que sigue al punto como extensión de archivo.
    apuntar(
        "Nombres de nota con punto",
        [n.stem for n in notas if "." in n.stem],
    )

    # 6. Obsidian resuelve los enlaces por nombre en TODA la bóveda. Un nombre
    #    repetido en otro proyecto hace que un enlace salte de proyecto.
    otros = [p for p in boveda.rglob("*.md")
             if ".obsidian" not in p.parts and not p.is_relative_to(carpeta)]
    apuntar(
        "Nombres que chocan con otra nota de la bóveda",
        [f"{n.stem}  (también en {o.parent.relative_to(boveda)})"
         for n in notas for o in otros if o.stem == n.stem],
    )

    # 7. Cada clic en un círculo rojo deja una nota vacía en la bandeja.
    apuntar(
        "Notas vacías (un clic en un nodo sin resolver las crea)",
        [str(p.relative_to(boveda)) for p in boveda.rglob("*.md")
         if ".obsidian" not in p.parts and p.stat().st_size == 0],
    )

    return problemas


def main() -> int:
    boveda = localizar_boveda()
    if boveda is None:
        print("No encuentro la bóveda; no hay nada que comprobar.")
        print(f"  Se buscó en: {os.environ.get('OBSIDIAN_VAULT', BOVEDA_POR_DEFECTO)}")
        print("  Define OBSIDIAN_VAULT si la tienes en otro sitio.")
        return 0

    notas = notas_de(boveda / PROYECTO)
    problemas = revisar(boveda)

    if not problemas:
        print(f"La bóveda describe el código: {len(notas)} notas, sin deriva.")
        return 0

    total = 0
    for titulo, casos in problemas:
        print(f"\n{titulo}:")
        for caso in casos:
            print(f"  {caso}")
        total += len(casos)

    print(f"\n{total} caso(s) en {len(problemas)} comprobación(es). Bóveda: {boveda}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
