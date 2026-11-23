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
    #: Las hojas del origen de cada archivo, en el orden de ``filas``
    #: (``Constancia.documentos``, desde el 2026-11-20). Las constancias de
    #: antes no las traen: su evidencia se casa por la fecha, el RE y el tipo.
    documentos: list[Mapping] = field(default_factory=list)
    #: El trabajo que lo entregó: con él se sabe de qué corrida es (2026-11-20).
    job_id: str = ""
    #: Lo que el agente decidió por su cuenta, con su auditor (2026-11-23).
    decisiones: list[Mapping] = field(default_factory=list)


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
    #: La auditoría (2026-11-20): una fila por documento entregado, con su
    #: fecha, su RE y su Revisión juntos (``auditar``).
    auditoria: list[dict] = field(default_factory=list)
    #: Una fila por PDF de origen, con lo que le falta.
    por_upd: list[dict] = field(default_factory=list)

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


# -- la auditoría: una fila por documento (2026-11-20) -------------------------------
#
# El operador: «necesito un Excel con sus filtros donde pueda ver el detalle del
# procesamiento, por ejemplo qué UPD o qué NIC no tiene fecha, cuáles no tienen
# RE… una auditoría en un Excel bien organizada». La evidencia va por la primera
# hoja de cada documento y por parámetro; aquí se junta, por documento, lo que
# el operador mira: su fecha, su RE y su Revisión.

SI, NO, NO_APLICA = "Sí", "No", "No aplica"
#: El RE con que termina el nombre de una fila: «RECLAMO-RE2310202403286».
_RE_AL_FINAL = re.compile(r"-(RE\d{13})$", re.IGNORECASE)


def _hora_local(iso: object) -> str:
    """«2026-11-19T21:56:10+00:00» a la hora local: «2026-11-19 16:56»."""
    from datetime import datetime

    try:
        return f"{datetime.fromisoformat(str(iso)).astimezone():%Y-%m-%d %H:%M}"
    except (TypeError, ValueError):
        return str(iso or "")[:16].replace("T", " ")


def _pagina(clave: object) -> int:
    return int(clave) if str(clave).isdigit() else 0


def _casar_por_lo_que_dicen(filas: list[Mapping], evidencia: Mapping[str, Mapping]) -> list[str | None]:
    """La primera hoja de cada fila, en las constancias que no la guardan: por su fecha, su RE y su tipo.

    Cada fila toma la hoja libre cuya evidencia más se le parece; a igual
    parecido, la primera del papel -- es el orden del índice a igual fecha --.
    """
    hojas = sorted({str(h) for p in PARAMETROS for h in (evidencia.get(p) or {})}, key=_pagina)
    usadas: set[str] = set()
    primeras: list[str | None] = []
    for fila in filas:
        nombre = str(fila.get("nombre") or "").strip().upper()
        con_re = _RE_AL_FINAL.search(nombre)
        tipo = nombre[: con_re.start()] if con_re else nombre

        def parecido(hoja: str, tipo: str = tipo, con_re: re.Match | None = con_re, fila: Mapping = fila) -> int:
            fecha = (evidencia.get("fecha") or {}).get(hoja) or {}
            del_re = (evidencia.get("re") or {}).get(hoja) or {}
            del_tipo = (evidencia.get("tipo") or {}).get(hoja) or {}
            puntos = 2 if str(fecha.get("valor") or "") == str(fila.get("fecha_creacion") or "") else 0
            puntos += 2 if (del_re.get("valor") or None) == (con_re.group(1).upper() if con_re else None) else 0
            puntos += 1 if str(del_tipo.get("valor") or "").upper() == tipo else 0
            return puntos

        libres = [h for h in hojas if h not in usadas]
        if not libres:
            primeras.append(None)
            continue
        elegida = max(libres, key=lambda h: (parecido(h), -_pagina(h)))
        usadas.add(elegida)
        primeras.append(elegida)
    return primeras


def _como(hallazgo: Mapping) -> str:
    """Cómo salió un valor: «sello de radicación, pág. 3»; o, si no salió, qué se buscó."""
    metodo = str(hallazgo.get("metodo") or "").strip()
    if metodo:
        return metodo + (f", pág. {hallazgo['pagina']}" if hallazgo.get("pagina") and "pág." not in metodo else "")
    return _causa(hallazgo)


def _lo_leido(hallazgo: Mapping) -> str:
    """Lo que el bot leyó de un parámetro que no se creyó: lo leído tal cual o sus candidatos."""
    candidatos = "; ".join(
        f"{c.get('valor')} ({c.get('motivo')})" if c.get("motivo") else str(c.get("valor"))
        for c in hallazgo.get("candidatos") or []
        if isinstance(c, Mapping) and c.get("valor")
    )
    original = str(hallazgo.get("valor_original") or "").strip()
    return " · ".join(x for x in (original, f"candidatos: {candidatos}" if candidatos else "") if x)


def auditar(pdf: PdfEntregado) -> tuple[list[dict], dict]:
    """Las filas de la auditoría de un PDF de origen -- una por documento entregado -- y su fila por UPD."""
    from ..domain.nombre_oficial import lleva_re_en_el_nombre

    nic, _, upd = pdf.documento.replace("\\", "/").rpartition("/")
    evidencia = {p: (pdf.evidencia.get(p) or {}) if isinstance(pdf.evidencia.get(p), Mapping) else {} for p in PARAMETROS}
    exactas = len(pdf.documentos) == len(pdf.filas) and all(d.get("hojas") for d in pdf.documentos)
    hojas_de: list[list[int]] = [[int(h) for h in d.get("hojas") or []] for d in pdf.documentos] if exactas else []
    if exactas:
        primeras = [
            next((str(h) for h in hojas if str(h) in evidencia["re"] or str(h) in evidencia["fecha"]), str(hojas[0]))
            for hojas in hojas_de
        ]
    else:
        primeras = _casar_por_lo_que_dicen(pdf.filas, evidencia)
    archivos = sorted(a.rsplit("/", 1)[-1] for a in pdf.archivos if a.lower().endswith(".pdf"))
    # La Revisión de cada documento: la de sus hojas; sin sus hojas, la de la
    # última primera hoja que no pasa de la del aviso.
    de_cada_uno: list[list[str]] = [[] for _ in pdf.filas]
    # Lo que el agente resolvió (``resuelto``, 2026-11-23) ya no está en
    # Revisión: va aparte, con lo que hizo.
    resueltos_de_cada_uno: list[list[dict]] = [[] for _ in pdf.filas]
    decision_de_cada_uno: list[Mapping | None] = [None for _ in pdf.filas]

    def puesto_de(pagina: int) -> int | None:
        if exactas:
            return next((i for i, hojas in enumerate(hojas_de) if pagina in hojas), None)
        antes = [(i, _pagina(p)) for i, p in enumerate(primeras) if p is not None and _pagina(p) <= pagina]
        return max(antes, key=lambda par: par[1])[0] if antes else (0 if pdf.filas else None)

    for entrada in pdf.revision:
        pagina = _pagina(entrada.get("page"))
        motivo = f"pág. {pagina}: {entrada.get('reason') or ''}".strip()
        puesto = puesto_de(pagina)
        if puesto is None:
            continue
        resuelto = entrada.get("resuelto")
        if isinstance(resuelto, Mapping):
            resueltos_de_cada_uno[puesto].append({"aviso": motivo, **resuelto})
        else:
            de_cada_uno[puesto].append(motivo)
    for decision in pdf.decisiones:
        puesto = puesto_de(_pagina(decision.get("page")))
        if puesto is not None:
            decision_de_cada_uno[puesto] = decision
    filas: list[dict] = []
    for i, fila in enumerate(pdf.filas):
        nombre = str(fila.get("nombre") or "").strip()
        con_re = _RE_AL_FINAL.search(nombre)
        tipo = nombre[: con_re.start()] if con_re else nombre
        primera = primeras[i] if i < len(primeras) else None
        de_la_fecha = evidencia["fecha"].get(primera) or {} if primera else {}
        del_re = evidencia["re"].get(primera) or {} if primera else {}
        fecha = str(fila.get("fecha_creacion") or "")
        lleva = lleva_re_en_el_nombre(tipo)
        radicado = con_re.group(1).upper() if con_re else ""
        motivos = de_cada_uno[i]
        alertas = [
            *(["Sin fecha"] if not fecha else []),
            *(["Sin RE"] if lleva and not radicado else []),
            *(["RE por confirmar"] if str(del_re.get("estado") or "") == "requiere validación" else []),
            *(["En Revisión"] if motivos else []),
        ]
        filas.append(
            {
                "nic": nic,
                "upd": upd,
                "orden": i + 1,
                "archivo": archivos[i] if len(archivos) == len(pdf.filas) else "",
                "tipo": tipo,
                "paginas": int(fila.get("paginas") or 0),
                "hojas": (
                    f"{hojas_de[i][0]}-{hojas_de[i][-1]}" if exactas and len(hojas_de[i]) > 1
                    else str(hojas_de[i][0]) if exactas
                    else ""
                ),
                "fecha": fecha,
                "tiene_fecha": SI if fecha else NO,
                "fecha_como": _como(de_la_fecha) if de_la_fecha else "",
                "re": radicado,
                "lleva_re": SI if lleva else NO,
                "tiene_re": SI if radicado else (NO if lleva else NO_APLICA),
                "re_estado": str(del_re.get("estado") or ""),
                "re_como": _como(del_re) if del_re else "",
                "en_revision": SI if motivos else NO,
                "motivos": " | ".join(motivos),
                "alerta": " · ".join(alertas) or "OK",
                # El detalle de lo que no se tomó, para la hoja «Faltantes».
                "avisos": list(motivos),
                "resueltos": resueltos_de_cada_uno[i],
                "decision": decision_de_cada_uno[i],
                "primera": _pagina(primera) if primera else None,
                "fecha_estado": str(de_la_fecha.get("estado") or ""),
                "fecha_leido": _lo_leido(de_la_fecha),
                "fecha_hoja": de_la_fecha.get("pagina") or (_pagina(primera) if primera else None),
                "fecha_buscado": str(de_la_fecha.get("buscado") or de_la_fecha.get("motivo") or ""),
                "re_leido": _lo_leido(del_re),
                "re_hoja": del_re.get("pagina") or (_pagina(primera) if primera else None),
                "re_buscado": str(del_re.get("buscado") or del_re.get("motivo") or ""),
            }
        )
    proceso = pdf.proceso or {}
    resumen = {
        "nic": nic,
        "upd": upd,
        "estado": pdf.estado,
        "lectura": str(proceso.get("lectura") or ""),
        "paginas": int(proceso.get("paginas") or 0),
        "documentos": len(filas),
        "sin_fecha": sum(1 for f in filas if f["tiene_fecha"] == NO),
        "sin_re": sum(1 for f in filas if f["tiene_re"] == NO),
        "en_revision": sum(1 for f in filas if f["en_revision"] == SI),
        "avisos": sum(len(f["avisos"]) for f in filas),
        "paginas_pagadas": int(proceso.get("paginas_pagadas") or 0),
        "duracion": str(proceso.get("duracion") or ""),
        "procesado": _hora_local(proceso.get("inicio")),
    }
    resumen["alerta"] = (
        " · ".join(
            texto
            for n, texto in (
                (resumen["sin_fecha"], f"{resumen['sin_fecha']} sin fecha"),
                (resumen["sin_re"], f"{resumen['sin_re']} sin RE"),
                (resumen["en_revision"], f"{resumen['en_revision']} en Revisión"),
            )
            if n
        )
        or "OK"
    )
    return filas, resumen


# -- lo que no se tomó, parámetro por parámetro (2026-11-20) -------------------------
#
# El operador: «necesito saber qué archivos no tomaron o no encontraron los
# parámetros… una auditoría de revisión bien estructurada por proceso
# ejecutado». Un renglón por documento y parámetro que falta o se tomó con
# duda: qué leyó el bot, en qué hoja, dónde buscó y qué hacer.

FECHA, RE_, TIPO = "Fecha", "RE", "Tipo documental"
NO_SE_ENCONTRO = "No se encontró"
POR_CONFIRMAR = "Tomado, por confirmar"
ILEGIBLE = "Ilegible: no se tomó"
NO_COINCIDEN = "Lecturas que no coinciden: no se tomó"
SIN_CATALOGO = "Sin nombre del catálogo"
NO_SE_PROCESO = "El PDF no se procesó"
#: El nombre que se da a un documento que no se pudo nombrar.
_SIN_NOMBRE = frozenset({"", "DOCUMENTO"})


def _situacion(estado: str, *, tomado: bool) -> str | None:
    """La situación de un parámetro por el estado de su evidencia; ``None`` si está bien."""
    if tomado:
        return POR_CONFIRMAR if estado in ("requiere validación", "contradictorio") else None
    return {"requiere validación": ILEGIBLE, "contradictorio": NO_COINCIDEN}.get(estado, NO_SE_ENCONTRO)


def _sin_nombre(fila: Mapping) -> bool:
    """Si el documento salió sin tipo documental: sin nombre o «DOCUMENTO».

    Por el nombre entregado, no por el estado de la evidencia del tipo: ésa es
    de la primera hoja casada, y en las constancias sin ``documentos`` puede
    ser la de otro documento (salían «DERECHO DE PETICION» sin catálogo).
    """
    return str(fila.get("tipo") or "").strip().upper() in _SIN_NOMBRE


def _hoja_de(valor: object, fila: Mapping) -> str:
    return str(valor) if valor else str(fila.get("hojas") or "")


def faltantes(auditoria: Iterable[Mapping], fallidos: Mapping[str, str] | None = None) -> list[dict]:
    """Lo que no se tomó -- o se tomó con duda -- de cada documento, y los PDF que no se procesaron."""
    filas: list[dict] = []
    for f in auditoria:
        base = {k: f.get(k) for k in ("nic", "upd", "orden", "archivo", "tipo")}
        situacion = _situacion(f.get("fecha_estado") or "", tomado=f.get("tiene_fecha") == SI)
        if situacion:
            hoja = _hoja_de(f.get("fecha_hoja"), f)
            filas.append(
                {
                    **base,
                    "parametro": FECHA,
                    "situacion": situacion,
                    "valor": f.get("fecha") or "",
                    "leido": f.get("fecha_leido") or "",
                    "hoja": hoja,
                    "buscado": f.get("fecha_buscado") or f.get("fecha_como") or "",
                    "que_hacer": (
                        f"Confirmar la fecha {f.get('fecha')} en la hoja {hoja} del {f.get('upd')}"
                        if situacion == POR_CONFIRMAR
                        else f"Leer la fecha en la hoja {hoja} del {f.get('upd')} y escribirla en el índice del NIC"
                    ),
                }
            )
        if f.get("lleva_re") == SI or f.get("re"):
            situacion = _situacion(f.get("re_estado") or "", tomado=bool(f.get("re")))
            if situacion:
                hoja = _hoja_de(f.get("re_hoja"), f)
                filas.append(
                    {
                        **base,
                        "parametro": RE_,
                        "situacion": situacion,
                        "valor": f.get("re") or "",
                        "leido": f.get("re_leido") or "",
                        "hoja": hoja,
                        "buscado": f.get("re_buscado") or f.get("re_como") or "",
                        "que_hacer": (
                            f"Confirmar el {f.get('re')} contra el sello o la etiqueta de la hoja {hoja}"
                            if situacion == POR_CONFIRMAR
                            else f"Leer el RE del sello o la etiqueta de la hoja {hoja} y ponerlo en el nombre del "
                            "archivo y en el índice"
                        ),
                    }
                )
        if _sin_nombre(f):
            filas.append(
                {
                    **base,
                    "parametro": TIPO,
                    "situacion": SIN_CATALOGO,
                    "valor": f.get("tipo") or "",
                    "leido": "",
                    "hoja": str(f.get("hojas") or f.get("primera") or ""),
                    "buscado": "su asunto, su formato y el catálogo de tipos documentales",
                    "que_hacer": "Nombrar el documento con el tipo del catálogo",
                }
            )
    for pdf, por_que in sorted((fallidos or {}).items()):
        carpeta, _, nombre = str(pdf).replace("\\", "/").rpartition("/")
        filas.append(
            {
                "nic": carpeta.rsplit("/", 1)[-1],
                "upd": PurePosixPath(nombre).stem,
                "orden": None,
                "archivo": nombre,
                "tipo": "",
                "parametro": "El PDF entero",
                "situacion": NO_SE_PROCESO,
                "valor": "",
                "leido": "",
                "hoja": "",
                "buscado": str(por_que or ""),
                "que_hacer": "Volver a procesar el PDF (Retomar: sólo lo que falta)",
            }
        )
    return filas


def avisos_de_revision(auditoria: Iterable[Mapping]) -> list[dict]:
    """Un renglón por aviso de Revisión, con su documento."""
    return [
        {k: f.get(k) for k in ("nic", "upd", "orden", "archivo", "tipo")} | {"aviso": aviso}
        for f in auditoria
        for aviso in f.get("avisos") or []
    ]


def por_parametro(auditoria: list[Mapping]) -> list[dict]:
    """Cada parámetro contado por documento: tomado, por confirmar, no tomado y no aplica."""
    cuenta = {p: Counter() for p in (FECHA, RE_, TIPO)}
    dudosos = {(x["parametro"], x["upd"], x["orden"]) for x in faltantes(auditoria) if x["situacion"] == POR_CONFIRMAR}
    for f in auditoria:
        clave = (f.get("upd"), f.get("orden"))
        cuenta[FECHA]["tomado" if f.get("tiene_fecha") == SI else "no"] += 1
        if f.get("re"):
            cuenta[RE_]["tomado"] += 1
        else:
            cuenta[RE_]["no" if f.get("lleva_re") == SI else "no_aplica"] += 1
        cuenta[TIPO]["no" if _sin_nombre(f) else "tomado"] += 1
        for parametro in (FECHA, RE_):
            if (parametro, *clave) in dudosos:
                cuenta[parametro]["dudoso"] += 1
    filas = []
    for parametro, c in cuenta.items():
        aplica = c["tomado"] + c["no"]
        filas.append(
            {
                "parametro": parametro,
                "documentos": aplica + c["no_aplica"],
                "tomado": c["tomado"] - c["dudoso"],
                "por_confirmar": c["dudoso"],
                "no_tomado": c["no"],
                "no_aplica": c["no_aplica"],
                "porcentaje": round((c["tomado"] - c["dudoso"]) / aplica, 4) if aplica else None,
            }
        )
    return filas


def decisiones_del_agente(auditoria: Iterable[Mapping]) -> list[dict]:
    """Lo que el agente hizo por su cuenta, documento por documento: el RE que decidió y cada aviso que cerró."""
    filas: list[dict] = []
    for f in auditoria:
        base = {k: f.get(k) for k in ("nic", "upd", "orden", "archivo", "tipo")}
        if decision := f.get("decision"):
            filas.append(
                {
                    **base,
                    "parametro": "RE",
                    "antes": decision.get("antes") or "",
                    "accion": "decidido por el agente" if decision.get("valor") else "revertido por el auditor",
                    "valor": decision.get("valor") or (
                        f"(propuso {decision['propuesto']})" if decision.get("propuesto") else ""
                    ),
                    "regla": decision.get("regla") or "",
                    "confianza": decision.get("confianza") or "",
                    "auditor": decision.get("auditor") or "",
                    "por_que": decision.get("por_que") or "",
                }
            )
        for resuelto in f.get("resueltos") or []:
            if decision and resuelto.get("accion") in ("decidido por el agente", "revertido por el auditor"):
                continue
            filas.append(
                {
                    **base,
                    "parametro": "Aviso",
                    "antes": resuelto.get("aviso") or "",
                    "accion": resuelto.get("accion") or "",
                    "valor": "",
                    "regla": "",
                    "confianza": "",
                    "auditor": "",
                    "por_que": resuelto.get("conclusion") or "",
                }
            )
    return filas


@dataclass(frozen=True, slots=True)
class LaCorrida:
    """La ficha de una corrida, para la cabeza de su auditoría."""

    inicio: str
    fin: str
    origen: str
    destino: str
    #: PDF del origen que vio la corrida, los que procesó, los que ya estaban
    #: entregados y no tocó, y los que fallaron con su porqué.
    encontrados: int = 0
    procesados: int = 0
    ya_entregados: int = 0
    fallidos: Mapping[str, str] = field(default_factory=dict)
    operador: str = ""
    habilidad: str = ""
    lectura: str = ""
    entrega: str = ""
    #: El dictamen de la auditoría de cierre, si se hizo.
    dictamen: str = ""


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
            if not isinstance(entrada.get("resuelto"), Mapping):
                metricas.revision[familia_de_la_revision(str(entrada.get("reason") or ""))] += 1
        metricas.reparos += verificar(pdf.evidencia, pdf.documento)
        filas, resumen = auditar(pdf)
        metricas.auditoria += filas
        metricas.por_upd.append(resumen)
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
