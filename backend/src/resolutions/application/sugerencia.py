"""Qué parece ser un PDF, dicho antes de procesarlo.

Es la misma pregunta que se hace el orquestador cuando el trabajo ya corre,
hecha antes y más barata: sólo la capa de texto que el PDF trae -- leerla no
cuesta nada y tarda milisegundos -- y el nombre del archivo. No pasa ninguna
página por OCR: un escaneo sin capa de texto se sugiere por su nombre o no se
sugiere, y lo dice. Es una sugerencia para el operador, no una decisión: la
que manda sigue siendo la del trabajo, con su OCR y sus validaciones.
"""

from __future__ import annotations

from ..domain.doctype import classify_pages
from ..domain.patrones import (
    PAGINAS_DEL_NUCLEO,
    Reconocimiento,
    paginas_con_nucleo,
    reconocer,
)
from .orquestador import SAMPLE_PAGES, muestrear
from .ports import PageSource


def sugerir(source: PageSource, nombre: str = "") -> Reconocimiento:
    """El tipo que parece, con el motivo, sin leer ninguna imagen."""
    marcadores = classify_pages(muestrear(source, None, paginas=SAMPLE_PAGES))
    texto = muestrear(source, None, paginas=PAGINAS_DEL_NUCLEO)
    return reconocer(marcadores, paginas_con_nucleo([pagina for _n, pagina in texto]), nombre)
