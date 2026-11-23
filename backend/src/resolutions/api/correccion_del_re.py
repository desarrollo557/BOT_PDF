"""El RE que confirma o escribe el operador, llevado a lo entregado: la constancia entera y, sin la corrida, el disco (2026-11-23).

El operador: «implementa los pendientes». Lo que el agente decide ya no espera
un «Confirmar», pero el operador puede cambiar un RE a mano -- sobre todo los
decididos con confianza baja, que audita por muestreo --, y eso tiene que llegar
a todo lo entregado:

- **La constancia entera** (``re_en_la_constancia``): la ruta del archivo y el
  nombre de su fila, y además su evidencia -- verificado por el operador --,
  sus avisos del RE -- cerrados por él, nunca los de otros agentes -- y la
  decisión del agente, que queda con lo que puso el operador. Sin esto, las
  métricas y la auditoría seguían viendo «RE por confirmar».
- **El disco, sin la corrida** (``corregir_re_en_el_destino``): con las rutas
  que la entrega guardó -- en el informe, y en disco para después de un
  reinicio --: el PDF entregado, su constancia, la celda de su fila en el
  índice del NIC y en el general de la raíz. Sólo si la constancia sigue
  siendo de ese trabajo: si la carpeta se reprocesó, no se toca. Un destino de
  red sin la corrida no tiene credenciales: se dice.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping
from pathlib import Path

from ..adapters import red_smb
from ..domain.evidencia import Estado, Hallazgo
from ..domain.nombre_oficial import con_su_re, con_su_re_en_la_ruta
from ..domain.resolutor_del_re import AVISO_DEL_RE
from . import constancia as constancias
from .errores import explicar_fallo

#: Lo que el operador hizo con un aviso del RE: así lo lee la Revisión y el Excel.
CONFIRMADO = "confirmado por el operador"
#: Los avisos de otros agentes, que pueden nombrar el sello o el RE sin ser del RE.
_DE_OTRO_AGENTE = ("revisor de cortes:", "revisor de fechas", "datos de ", "comprobación de la entrega:")

#: Un cerrojo por carpeta del NIC para todo el proceso: ordenar la caja y
#: corregir un RE no se cruzan sobre la misma constancia.
_cerrojos: dict[str, threading.RLock] = {}
_cerrojo_de_los_cerrojos = threading.Lock()


def cerrojo_de_la_carpeta(carpeta: Path | str) -> threading.RLock:
    clave = os.path.normcase(os.path.abspath(str(carpeta)))
    with _cerrojo_de_los_cerrojos:
        return _cerrojos.setdefault(clave, threading.RLock())


def _hojas_del_documento(constancia, posicion: int) -> list[int]:
    documentos = constancia.documentos or []
    if posicion < len(documentos) and isinstance(documentos[posicion], dict):
        return [int(h) for h in documentos[posicion].get("hojas") or []]
    return []


def _pdfs_en_orden(constancia) -> list[dict]:
    from .folders import _orden_del_archivo, _prefijo_de_la_constancia

    prefijo = _prefijo_de_la_constancia(constancia)
    return sorted(
        (a for a in constancia.archivos if str(a.get("ruta") or "").lower().endswith(".pdf")),
        key=lambda a: _orden_del_archivo(a, prefijo),
    )


def es_aviso_del_re(razon: str) -> bool:
    """Si un aviso de la Revisión es del RE de su documento -- no de otro agente que nombre el sello --."""
    razon = razon or ""
    return not razon.startswith(_DE_OTRO_AGENTE) and AVISO_DEL_RE.search(razon) is not None


def re_en_la_constancia(constancia, posicion: int, radicado: str, quien: str | None = None) -> list[str]:
    """Lleva a la constancia el RE del documento ``posicion``: su archivo, su fila, su evidencia, su Revisión y la decisión del agente.

    No renombra nada en el disco: eso lo hace quien la llama. Devuelve lo que no se pudo.
    """
    avisos: list[str] = []
    pdfs = _pdfs_en_orden(constancia)
    if posicion < len(pdfs):
        pdfs[posicion]["ruta"] = con_su_re_en_la_ruta(str(pdfs[posicion].get("ruta") or ""), radicado)
    filas = (constancia.indice or {}).get("filas")
    if isinstance(filas, list) and posicion < len(filas) and isinstance(filas[posicion], dict):
        filas[posicion]["nombre"] = con_su_re(str(filas[posicion].get("nombre") or ""), radicado)
    else:
        avisos.append("la fila de este documento no está en la constancia: el índice del NIC no cambió")
    hojas = _hojas_del_documento(constancia, posicion)
    if hojas:
        primera = str(min(hojas))
        de_antes = (constancia.evidencia.get("re") or {}).get(primera) or {}
        constancia.evidencia.setdefault("re", {})[primera] = {
            **Hallazgo(
                parametro="re",
                estado=Estado.VERIFICADO,
                valor=radicado,
                valor_original=radicado,
                pagina=int(primera),
                metodo=CONFIRMADO,
                lectores=("operador",),
                confianza="alta",
                motivo=f"antes: {de_antes.get('estado') or 'sin evidencia'}",
            ).as_dict(),
            "quien": quien,
        }
        for aviso in constancia.revision:
            if (
                isinstance(aviso, dict)
                and int(aviso.get("page") or 0) in hojas
                and es_aviso_del_re(str(aviso.get("reason") or ""))
            ):
                aviso["resuelto"] = {"accion": CONFIRMADO, "conclusion": f"puso {radicado}"}
        for decision in constancia.decisiones_del_agente:
            if isinstance(decision, dict) and set(decision.get("paginas") or [decision.get("page")]) & set(hojas):
                decision.update({"valor": radicado, "auditor": CONFIRMADO})
    return avisos


def corregir_re_en_el_destino(
    donde: Mapping[str, str] | None,
    posicion: int,
    radicado: str,
    quien: str | None = None,
    *,
    job_id: str | None = None,
) -> list[str]:
    """Lleva el RE a lo entregado por las rutas guardadas, sin la corrida. Devuelve lo que no se pudo hacer.

    ``job_id``: el trabajo que corrige. Si la constancia que está ahora en el
    destino la escribió otro -- la carpeta se reprocesó --, no se toca nada.
    """
    if not donde or not donde.get("constancia") or not donde.get("carpeta"):
        return ["no se guardó dónde se entregó este documento: el PDF entregado y el índice del NIC no cambiaron"]
    if any(red_smb.por_smb(str(ruta)) for ruta in donde.values() if ruta):
        return [
            "el destino es una carpeta de red y su corrida ya no está abierta: sin sus credenciales no se "
            "puede escribir en él. El RE quedó en el trabajo"
        ]
    ruta, carpeta = Path(donde["constancia"]), Path(donde["carpeta"])
    with cerrojo_de_la_carpeta(carpeta):
        constancia = constancias.leer(ruta)
        if constancia is None:
            return [f"no está la constancia «{ruta.name}» en el destino: el PDF entregado no se renombró"]
        if job_id is not None and constancia.job_id and constancia.job_id != job_id:
            return [
                f"la entrega de «{ruta.name}» es ahora de otro trabajo (se reprocesó): lo entregado no se tocó. "
                "El RE quedó en este trabajo"
            ]
        pdfs = _pdfs_en_orden(constancia)
        if posicion >= len(pdfs):
            return [f"la constancia «{ruta.name}» no trae ese documento: el PDF entregado no se renombró"]
        actual = str(pdfs[posicion].get("ruta") or "")
        antes = constancias.ruta_de_entrega(carpeta, actual)
        despues = constancias.ruta_de_entrega(carpeta, con_su_re_en_la_ruta(actual, radicado))
        if antes is None or despues is None:
            return [f"la ruta de «{Path(actual).name}» no es de la carpeta del NIC: no se renombró"]
        renombrado = False
        try:
            if despues.exists() and despues != antes:
                return [f"en el destino ya hay un «{despues.name}»: no se renombró «{antes.name}»"]
            if antes.exists() and despues != antes:
                os.replace(antes, despues)
                renombrado = True
        except OSError as error:
            return [f"no se pudo renombrar «{antes.name}» en el destino: {explicar_fallo(error)}"]
        filas = (constancia.indice or {}).get("filas") or []
        viejo = (
            str(filas[posicion].get("nombre") or "")
            if posicion < len(filas) and isinstance(filas[posicion], dict)
            else ""
        )
        avisos = re_en_la_constancia(constancia, posicion, radicado, quien)
        try:
            constancias.escribir(ruta, constancia)
        except OSError as error:
            aviso = f"no se pudo actualizar la constancia «{ruta.name}»: {explicar_fallo(error)}"
            if renombrado:
                # Sin su constancia, el PDF vuelve a su nombre: nada queda a medias.
                try:
                    os.replace(despues, antes)
                    aviso += "; el PDF entregado y el índice del NIC no cambiaron"
                except OSError as deshacer:
                    aviso += f"; «{despues.name}» quedó con el RE y no se pudo devolver: {explicar_fallo(deshacer)}"
            return [*avisos, aviso]
        nuevo = con_su_re(viejo, radicado)
        avisos += _en_el_indice_del_nic(carpeta, viejo, nuevo)
        upd = Path(str(constancia.origen or "")).stem
        avisos += _en_el_indice_general(donde.get("raiz"), (carpeta.name, upd), viejo, nuevo)
    return avisos


def _en_el_indice_del_nic(carpeta: Path, viejo: str, nuevo: str) -> list[str]:
    """La celda de su fila en el índice del NIC; si varias se llaman igual, no se adivina cuál."""
    from ..adapters.indice_electronico import (
        NOMBRE_DEL_INDICE,
        cambiar_el_nombre,
        leer_indice,
    )

    if not viejo or viejo == nuevo:
        return []
    indice = carpeta / NOMBRE_DEL_INDICE
    try:
        if not indice.is_file():
            return ["no está el índice del NIC: se rehace al reprocesar"]
        iguales = [f for f in leer_indice(indice).filas if f.nombre == viejo]
        if len(iguales) != 1:
            return [f"el índice del NIC tiene {len(iguales)} filas «{viejo}»: no se cambió ninguna; se rehace al reprocesar"]
        if not cambiar_el_nombre(indice, viejo, nuevo):
            return ["la fila de este documento no está en el índice del NIC"]
    except Exception as error:  # noqa: BLE001 - el PDF y la constancia ya se corrigieron; se dice qué faltó
        return [f"no se pudo corregir el índice del NIC: {explicar_fallo(error)}"]
    return []


def _en_el_indice_general(raiz: str | None, hojas_suyas: tuple[str, ...], viejo: str, nuevo: str) -> list[str]:
    """La celda de su fila en el índice general de la raíz: en la hoja de su NIC o de su UPD, si es única.

    El general puede ir partido en libros; se mira cada uno. Lo que no se pueda
    cambiar con certeza se dice: se rehace al relanzar la carpeta.
    """
    if not viejo or viejo == nuevo:
        return []
    if not raiz:
        return ["no se guardó la raíz del destino: el índice general no cambió; se rehace al relanzar la carpeta"]
    with cerrojo_de_la_carpeta(raiz):
        return _en_el_indice_general_bajo_cerrojo(raiz, hojas_suyas, viejo, nuevo)


def _en_el_indice_general_bajo_cerrojo(raiz: str, hojas_suyas: tuple[str, ...], viejo: str, nuevo: str) -> list[str]:
    from openpyxl import load_workbook

    from ..adapters.guardar_libro import guardar_libro
    from ..adapters.indice_electronico import (
        COLUMNA_DEL_NOMBRE,
        NOMBRE_DEL_INDICE,
        PRIMERA_FILA,
    )

    aviso = ["el índice general de la raíz no cambió: se rehace al relanzar la carpeta"]
    try:
        libros = sorted(p for p in Path(raiz).glob(f"{Path(NOMBRE_DEL_INDICE).stem}*.xlsx") if p.is_file())
        if not libros:
            return []
        cambiado = False
        claves = tuple(h for h in hojas_suyas if h)
        for ruta in libros:
            libro = load_workbook(ruta)
            try:
                celdas = [
                    (hoja, numero)
                    for hoja in libro.worksheets
                    if any(clave in hoja.title for clave in claves)
                    for numero in range(PRIMERA_FILA, (hoja.max_row or 0) + 1)
                    if str(hoja[f"{COLUMNA_DEL_NOMBRE}{numero}"].value or "").strip() == viejo
                ]
                if len(celdas) == 1:
                    hoja, numero = celdas[0]
                    hoja[f"{COLUMNA_DEL_NOMBRE}{numero}"].value = nuevo
                    guardar_libro(libro, ruta)
                    cambiado = True
            finally:
                libro.close()
        return [] if cambiado else aviso
    except Exception:  # noqa: BLE001 - lo demás ya se corrigió; se dice qué faltó
        return aviso
