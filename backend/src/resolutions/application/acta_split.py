"""Inventariar actas de grado: una fila por acta, sin partir el PDF.

El PDF trae varias actas de grado correlativas (una por graduado).
Cada acta empieza con "ACTA DE GRADO N° XXXXXX" y ocupa 1-2 páginas.
Se extrae: número de acta, fecha de la ceremonia, folio manuscrito (esquina sup. der.),
y un resumen generado por Mistral (prohibida la frase "LLAMADO A LISTA Y VERIFICACIÓN DEL QUORUM").
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from ..application.ports import HEADER_BAND, OcrEngine, PageSource
from ..application.progress import (
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
    Stage,
)
from ..domain.folio_manuscrito import (
    BANDA_DEL_FOLIO,
    folio_de_la_esquina,
    folios_comprobados,
)
from .control import NullRunControl, RunControl
from .fuid import Ubicacion

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Resultado del split de actas (para evitar import circular con inventory_document)
# -----------------------------------------------------------------------------

@dataclass(slots=True)
class ActaSplitResult:
    """Resultado bruto del split de actas, para envolver en InventoryOutcome."""
    actas: list[ActaData]
    issues: list[dict]
    page_count: int

@dataclass(slots=True)
class ActaData:
    """Datos extraídos de una acta individual."""
    numero: str
    fecha: str  # ISO YYYY-MM-DD
    folio: str  # folio manuscrito o "SIN FOLIO"
    texto_completo: str
    paginas: list[int]
    resumen: str = field(default="", repr=False)
# Regex para detectar el inicio de cada acta y extraer su número
# -----------------------------------------------------------------------------
# Cubre variantes vistas: "ACTA DE GRADO N°. 054251325", "ACTA DE GRADO N 054251326",
# "ACTA DE GRADO N“. 054251327", "ACTA DE GRADO N”. 054251328",
# y también con comillas ASCII: 'ACTA DE GRADO N". 054251327'
ACTA_NUMERO_RE = re.compile(r"ACTA DE GRADO N[°.\u201c\u201d\"]?\.?\s*(\d+)", re.IGNORECASE)

# Fecha en el primer párrafo: "a los dieciséis (16) días del mes de diciembre del año 2025"
FECHA_ACTA_RE = re.compile(
    r"a los\s+\w+\s+\((\d+)\)\s+d[íi]as\s+del\s+mes\s+de\s+(\w+)\s+del\s+año\s+(\d{4})",
    re.IGNORECASE,
)

MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

# Frase que NUNCA debe aparecer en el resumen
FRASE_PROHIBIDA = "LLAMADO A LISTA Y VERIFICACIÓN DEL QUORUM"


class ActaSplit:
    """Lee un PDF de actas de grado y devuelve los datos de cada acta para inventario."""

    def __init__(
        self,
        ocr: OcrEngine | None = None,
        mistral_summary=None,  # MistralSummaryAdapter
        progress: ProgressReporter | None = None,
        control: RunControl | None = None,
        workers: int = 4,
    ) -> None:
        self._ocr = ocr
        self._mistral_summary = mistral_summary
        self._progress = progress or NullProgressReporter()
        self._control = control or NullRunControl()
        self._workers = max(1, workers)

    def execute(
        self,
        source: PageSource,
        *,
        document_name: str,
        ubicacion: Ubicacion | None = None,
    ) -> ActaSplitResult:
        self._report(ProgressEvent(stage=Stage.OPENED, page_count=source.page_count))

        # 1. Leer TODAS las páginas con OCR cascada (Tesseract + Mistral para esquinas)
        self._report(ProgressEvent(stage=Stage.READING, done=0, total=source.page_count, detail="leyendo páginas"))
        textos_paginas = self._leer_todas_paginas(source)

        # 2. Detectar folios en esquina sup. der. (una pasada ligera por página)
        self._report(ProgressEvent(stage=Stage.READING, done=0, total=source.page_count, detail="detectando folios"))
        folios_por_pagina = self._detectar_folios(source)

        # 3. Split por "ACTA DE GRADO N°" → límites de cada acta
        actas = self._split_actas(textos_paginas, folios_por_pagina)

        # 4. Por cada acta: extraer fecha + pedir resumen a Mistral
        self._report(ProgressEvent(stage=Stage.CLASSIFYING, done=0, total=len(actas), detail="procesando actas"))
        actas_procesadas: list[ActaData] = []
        for i, acta in enumerate(actas):
            if self._control.debe_parar():
                break
            fecha = self._extraer_fecha(acta.texto_completo)
            resumen = self._pedir_resumen(acta.texto_completo)
            actas_procesadas.append(ActaData(
                numero=acta.numero,
                fecha=fecha,
                folio=acta.folio,
                texto_completo=acta.texto_completo,
                paginas=acta.paginas,
                resumen=resumen,
            ))
            self._report(ProgressEvent(stage=Stage.CLASSIFYING, done=i + 1, total=len(actas), detail=f"acta {acta.numero}"))

        # 5. Validaciones (las filas FUID se construyen en inventory_document)
        issues = self._validar(actas_procesadas, source.page_count)

        return ActaSplitResult(
            actas=actas_procesadas,
            issues=issues,
            page_count=source.page_count,
        )

    # -------------------------------------------------------------------------
    # Lectura de páginas
    # -------------------------------------------------------------------------
    def _leer_todas_paginas(self, source: PageSource) -> list[str]:
        """Lee todas las páginas con el OCR disponible (cascada si hay Mistral)."""
        textos: list[str] = []
        for pagina in range(1, source.page_count + 1):
            if self._control.debe_parar():
                textos.append("")
                continue
            try:
                # Usar el OCR cascada si está disponible (lee banda + página completa)
                if hasattr(self._ocr, "read"):
                    # OcrEngine simple (Tesseract)
                    texto = source.text_of(pagina)
                    if len(texto) < 80 and self._ocr is not None:
                        imagen = source.render(pagina, HEADER_BAND, 200)
                        texto = self._ocr.read(imagen).text
                else:
                    texto = source.text_of(pagina)
            except Exception:  # noqa: BLE001
                logger.debug("no se pudo leer página %s", pagina, exc_info=True)
                texto = ""
            textos.append(texto)
        return textos

    def _detectar_folios(self, source: PageSource) -> dict[int, str]:
        """Detecta folio manuscrito en esquina sup. der. de cada página.
        
        Usa MistralOCR (lee manuscrito) sobre la banda del folio.
        Devuelve dict {pagina: folio} o "SIN FOLIO".
        """
        folios: dict[int, str] = {}
        lecturas_para_validar: list[tuple[int, str | None]] = []

        for pagina in range(1, source.page_count + 1):
            if self._control.debe_parar():
                folios[pagina] = "SIN FOLIO"
                continue
            try:
                # Renderizar solo la banda del folio (esquina sup. der.)
                imagen = source.render(pagina, BANDA_DEL_FOLIO, 300)
                if self._ocr is not None and hasattr(self._ocr, "read"):
                    # Si es OcrEnCascada, usar el remoto (Mistral) para manuscrito
                    # El método read usa la cascada automáticamente
                    resultado = self._ocr.read(imagen)
                    texto = resultado.text
                else:
                    texto = ""
                folio = folio_de_la_esquina(texto, pagina)
                lecturas_para_validar.append((pagina, folio))
                folios[pagina] = folio or "SIN FOLIO"
            except Exception:  # noqa: BLE001
                logger.debug("no se pudo detectar folio en página %s", pagina, exc_info=True)
                folios[pagina] = "SIN FOLIO"
                lecturas_para_validar.append((pagina, None))

        # Validar folios contra progresión del libro
        comprobados = folios_comprobados(lecturas_para_validar)
        for pagina, folio_valido in comprobados.items():
            folios[pagina] = folio_valido

        return folios

    # -------------------------------------------------------------------------
    # Split y extracción
    # -------------------------------------------------------------------------
    def _split_actas(self, textos: list[str], folios: dict[int, str]) -> list[ActaData]:
        """Divide el documento en actas individuales por número de acta."""
        # Encontrar páginas donde empieza cada acta
        inicios: list[tuple[int, str]] = []  # (pagina_1_based, numero_acta)
        for i, texto in enumerate(textos):
            match = ACTA_NUMERO_RE.search(texto)
            if match:
                inicios.append((i + 1, match.group(1)))

        if not inicios:
            logger.warning("no se detectó ninguna acta en %s páginas", len(textos))
            return []

        # Construir rangos de páginas por acta
        actas: list[ActaData] = []
        for idx, (pag_ini, numero) in enumerate(inicios):
            pag_fin = (inicios[idx + 1][0] - 1) if idx + 1 < len(inicios) else len(textos)
            paginas = list(range(pag_ini, pag_fin + 1))
            texto_completo = "\n\n".join(textos[p - 1] for p in paginas)
            # Folio de la primera página del acta (donde está el número)
            folio = folios.get(pag_ini, "SIN FOLIO")
            actas.append(ActaData(
                numero=numero,
                fecha="",  # se llena después
                folio=folio,
                texto_completo=texto_completo,
                paginas=paginas,
            ))
        return actas

    def _extraer_fecha(self, texto: str) -> str:
        """Extrae la fecha de la ceremonia del primer párrafo del acta."""
        match = FECHA_ACTA_RE.search(texto)
        if not match:
            return "SIN FECHA"
        dia = int(match.group(1))
        mes_nombre = match.group(2).lower()
        año = int(match.group(3))
        mes = MESES.get(mes_nombre, 1)
        try:
            return date(año, mes, dia).isoformat()
        except ValueError:
            return "FECHA INVÁLIDA"

    def _pedir_resumen(self, texto: str) -> str:
        """Pide resumen a Mistral con prompt que prohíbe la frase prohibida."""
        if self._mistral_summary is None:
            return "SIN RESUMEN (sin Mistral)"
        try:
            # Eliminar la frase prohibida del texto antes de enviarlo
            texto_limpio = texto.replace(FRASE_PROHIBIDA, "").replace(
                FRASE_PROHIBIDA.lower(), ""
            ).replace(FRASE_PROHIBIDA.upper(), "")
            return self._mistral_summary.summarize(texto_limpio)
        except Exception as e:  # noqa: BLE001
            logger.warning("error pidiendo resumen a Mistral: %s", e)
            return "ERROR EN RESUMEN"

    def _validar(self, actas: list[ActaData], total_paginas: int) -> list[dict]:
        """Valida integridad: todas las páginas cubiertas, actas con datos."""
        issues = []
        paginas_cubiertas = set()
        for acta in actas:
            for p in acta.paginas:
                paginas_cubiertas.add(p)
        faltantes = set(range(1, total_paginas + 1)) - paginas_cubiertas
        if faltantes:
            issues.append({
                "field": "cobertura",
                "reason": f"páginas sin asignar a acta: {sorted(faltantes)}",
                "severity": "WARNING",
            })
        for acta in actas:
            if acta.folio == "SIN FOLIO":
                issues.append({
                    "field": "folio",
                    "reason": f"acta {acta.numero}: folio no detectado",
                    "severity": "WARNING",
                })
            if acta.fecha == "SIN FECHA":
                issues.append({
                    "field": "fecha",
                    "reason": f"acta {acta.numero}: fecha no detectada",
                    "severity": "WARNING",
                })
        return issues

    def _report(self, event: ProgressEvent) -> None:
        try:
            self._progress.emit(event)
        except Exception:  # noqa: BLE001
            logger.debug("progress report failed", exc_info=True)