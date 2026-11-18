"""Las métricas de la extracción de una entrega, de lo que dejó escrito: sus constancias.

Lo pidió el operador el 2026-11-18 para su segunda ejecución integral: el total
de documentos, los procesados, los fallidos; los parámetros encontrados, no
encontrados y por validar; los verificados y los contradictorios; los tiempos;
el rendimiento de cada estrategia; la comparación con la primera ejecución; y
la lista de lo que no se recuperó, con su causa. «No declares una ejecución
exitosa simplemente porque terminó sin errores técnicos.»

Todo sale de las constancias de la entrega (``.bot-entrega-*.json``), que
guardan la evidencia y la Revisión de cada PDF: sirve tras un reinicio, días
después, y para comparar dos entregas.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .verificador_de_evidencia import Reparo, verificar

#: Los parámetros, en el orden en que se cuentan.
PARAMETROS = ("re", "fecha", "tipo", "corte")
#: Las familias de la Revisión, por su motivo.
_FAMILIAS = (
    ("RE por confirmar", re.compile(r"^RE por confirmar", re.IGNORECASE)),
    ("RE ilegible en el sello", re.compile(r"RE escrito a mano|el RE leído a mano|sello de radicación al pie", re.IGNORECASE)),
    ("Sin su RE", re.compile(r"sin su RE|no trae su RE", re.IGNORECASE)),
    ("Fecha", re.compile(r"fecha", re.IGNORECASE)),
    ("Anexos", re.compile(r"anexo", re.IGNORECASE)),
    ("Cortes", re.compile(r"cort|costura|revisor de cortes", re.IGNORECASE)),
)
#: «1 min 05 s», «42 s».
_DURACION = re.compile(r"(?:(\d+)\s*min)?\s*(?:(\d+)\s*s)?")
#: El RE al final de un nombre: «RECLAMO-RE2310202403286».
_RE_DEL_NOMBRE = re.compile(r"-RE\d{13}$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PdfEntregado:
    """Lo que la constancia de un PDF dice de él."""

    #: La carpeta del NIC y el PDF de origen: «1005122/UPD3102765».
    documento: str
    estado: str
    archivos: list[str]
    evidencia: Mapping
    revision: list[Mapping]
    proceso: Mapping
    filas: list[Mapping]


@dataclass(slots=True)
class Metricas:
    pdf: int = 0
    pdf_por_estado: Counter = field(default_factory=Counter)
    documentos: int = 0
    paginas: int = 0
    paginas_pagadas: int = 0
    segundos: int = 0
    #: (parámetro, estado) → cuántos.
    por_estado: Counter = field(default_factory=Counter)
    #: (parámetro, método, estado) → cuántos.
    por_metodo: Counter = field(default_factory=Counter)
    #: Familia del lector del RE que se cree → cuántos.
    lectores_del_re: Counter = field(default_factory=Counter)
    revision: Counter = field(default_factory=Counter)
    reparos: list[Reparo] = field(default_factory=list)
    #: Lo no recuperado: (documento, parámetro, estado, causa).
    no_recuperados: list[tuple[str, str, str, str]] = field(default_factory=list)
    #: Una fila por documento y parámetro, con su evidencia.
    evidencia: list[dict] = field(default_factory=list)

    @property
    def segundos_por_pdf(self) -> float:
        return self.segundos / self.pdf if self.pdf else 0.0

    @property
    def segundos_por_documento(self) -> float:
        return self.segundos / self.documentos if self.documentos else 0.0


def segundos_de(duracion: object) -> int:
    """«1 min 05 s» en segundos; 0 si no se entiende."""
    hallado = _DURACION.fullmatch(str(duracion or "").strip())
    if not hallado or not any(hallado.groups()):
        return 0
    return int(hallado.group(1) or 0) * 60 + int(hallado.group(2) or 0)


def familia_de_la_revision(motivo: str) -> str:
    return next((nombre for nombre, patron in _FAMILIAS if patron.search(motivo or "")), "Otros")


def _metodo(hallazgo: Mapping) -> str:
    """El método sin la hoja: «sello de radicación (pág. 4)» es «sello de radicación»."""
    return re.sub(r"\s*\(p[aá]g\.\s*\d+\)", "", str(hallazgo.get("metodo") or "—")).strip()


def _causa(hallazgo: Mapping) -> str:
    candidatos = "; ".join(
        f"{c.get('valor')} ({c.get('motivo')})" for c in hallazgo.get("candidatos") or [] if isinstance(c, Mapping)
    )
    if candidatos:
        return f"candidatos: {candidatos}"
    return f"se buscó: {hallazgo.get('buscado')}" if hallazgo.get("buscado") else str(hallazgo.get("motivo") or "")


def medir(entregados: Iterable[PdfEntregado]) -> Metricas:
    """Las métricas de una entrega."""
    metricas = Metricas()
    for pdf in entregados:
        metricas.pdf += 1
        metricas.pdf_por_estado[pdf.estado] += 1
        metricas.documentos += sum(1 for a in pdf.archivos if a.lower().endswith(".pdf"))
        metricas.paginas += int(pdf.proceso.get("paginas") or 0)
        metricas.paginas_pagadas += int(pdf.proceso.get("paginas_pagadas") or 0)
        metricas.segundos += segundos_de(pdf.proceso.get("duracion"))
        for entrada in pdf.revision:
            metricas.revision[familia_de_la_revision(str(entrada.get("reason") or ""))] += 1
        metricas.reparos += verificar(pdf.evidencia, pdf.documento)
        for parametro in PARAMETROS:
            por_hoja = pdf.evidencia.get(parametro) or {}
            if not isinstance(por_hoja, Mapping):
                continue
            for primera, hallazgo in sorted(
                por_hoja.items(), key=lambda par: int(par[0]) if str(par[0]).isdigit() else 0
            ):
                if not isinstance(hallazgo, Mapping):
                    continue
                estado = str(hallazgo.get("estado") or "—")
                metricas.por_estado[(parametro, estado)] += 1
                metricas.por_metodo[(parametro, _metodo(hallazgo), estado)] += 1
                if parametro == "re" and estado in ("verificado", "encontrado"):
                    for lector in hallazgo.get("lectores") or []:
                        metricas.lectores_del_re[str(lector)] += 1
                donde = f"{pdf.documento} · hoja {primera}"
                if estado in ("requiere validación", "no encontrado", "contradictorio") and parametro in ("re", "fecha"):
                    metricas.no_recuperados.append((donde, parametro, estado, _causa(hallazgo)))
                metricas.evidencia.append(
                    {
                        "documento": donde,
                        "parametro": parametro,
                        "estado": estado,
                        "valor": hallazgo.get("valor"),
                        "original": hallazgo.get("valor_original"),
                        "pagina": hallazgo.get("pagina"),
                        "fragmento": hallazgo.get("fragmento"),
                        "metodo": hallazgo.get("metodo"),
                        "lectores": ", ".join(map(str, hallazgo.get("lectores") or [])),
                        "confianza": hallazgo.get("confianza"),
                        "candidatos": _causa(hallazgo) if hallazgo.get("candidatos") else None,
                    }
                )
    return metricas


# -- la comparación de dos entregas -------------------------------------------------


@dataclass(frozen=True, slots=True)
class ComparacionDeUnNic:
    nic: str
    documentos_antes: int
    documentos_ahora: int
    con_re_antes: int
    con_re_ahora: int
    sin_fecha_antes: int
    sin_fecha_ahora: int
    solo_antes: list[str]
    solo_ahora: list[str]


def _nombres(filas: Iterable[Mapping]) -> Counter:
    return Counter(str(f.get("nombre") or "").strip().upper() for f in filas)


def comparar(antes: Iterable[PdfEntregado], ahora: Iterable[PdfEntregado]) -> list[ComparacionDeUnNic]:
    """Por NIC (la carpeta de su constancia): cuántos documentos, cuántos con RE y sin fecha, y qué nombres cambiaron."""

    def por_nic(entregados: Iterable[PdfEntregado]) -> dict[str, list[Mapping]]:
        nics: dict[str, list[Mapping]] = {}
        for pdf in entregados:
            nic = str(PurePosixPath(pdf.documento.replace("\\", "/")).parent)
            nics.setdefault(nic, []).extend(pdf.filas)
        return nics

    viejos, nuevos = por_nic(antes), por_nic(ahora)
    filas = []
    for nic in sorted(set(viejos) | set(nuevos)):
        a, b = viejos.get(nic, []), nuevos.get(nic, [])
        na, nb = _nombres(a), _nombres(b)
        filas.append(
            ComparacionDeUnNic(
                nic=nic,
                documentos_antes=len(a),
                documentos_ahora=len(b),
                con_re_antes=sum(1 for f in a if _RE_DEL_NOMBRE.search(str(f.get("nombre") or ""))),
                con_re_ahora=sum(1 for f in b if _RE_DEL_NOMBRE.search(str(f.get("nombre") or ""))),
                sin_fecha_antes=sum(1 for f in a if not f.get("fecha_creacion")),
                sin_fecha_ahora=sum(1 for f in b if not f.get("fecha_creacion")),
                solo_antes=sorted((na - nb).elements()),
                solo_ahora=sorted((nb - na).elements()),
            )
        )
    return filas
