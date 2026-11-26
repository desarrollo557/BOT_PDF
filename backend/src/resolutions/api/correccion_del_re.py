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

import copy
import dataclasses
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


# -- el RE que cita el expediente (2026-11-24) ------------------------------------------

#: Cómo queda dicho en la evidencia el RE que corrigió el expediente.
CITADO_EN_EL_EXPEDIENTE = "citado en otro documento del expediente"
#: Lo impreso no se corrige así: la etiqueta y el PQR de la constancia se leen enteros.
_IMPRESO = ("impres", "etiqueta", "PQR", CONFIRMADO, CITADO_EN_EL_EXPEDIENTE)


def _se_corrige_por_el_expediente(evidencia: Mapping) -> bool:
    """Si el RE del nombre salió de una lectura a mano o de una decisión del agente: lo que el expediente puede corregir.

    Nunca lo impreso (``FUENTES_IMPRESAS``): el «Número de la PQR» que imprime
    la notificación personal de 7741276 («citado en su texto») se cambiaba por
    lo que la capa leyó mal en la etiqueta del recurso (2026-11-24).
    """
    from ..domain.evidencia import FUENTES_IMPRESAS

    if not evidencia or str(evidencia.get("estado") or "") == Estado.VERIFICADO.value:
        return False
    metodo = str(evidencia.get("metodo") or "")
    return not any(marca in metodo for marca in (*_IMPRESO, *FUENTES_IMPRESAS))


def _textos_de_los_pdf(carpeta: Path, rutas: list[str]) -> dict[str, str]:
    """El texto de cada PDF entregado de la carpeta del NIC, por su ruta: su capa, que es gratis."""
    from ..adapters.pymupdf_source import PyMuPDFPageSource

    textos: dict[str, str] = {}
    for ruta in rutas:
        pdf = constancias.ruta_de_entrega(carpeta, ruta)
        if pdf is None or not pdf.exists():
            continue
        try:
            with PyMuPDFPageSource(pdf) as fuente:
                textos[ruta] = "\n".join(fuente.text_of(p) or "" for p in range(1, fuente.page_count + 1))
        except Exception:  # noqa: BLE001 - un PDF ilegible no para la carpeta
            continue
    return textos


def citas_del_pdf(pdf: Path) -> list[list[str]] | None:
    """Las citas de trece cifras de un PDF (``citas_del_texto``), de su capa de texto; ``None`` si no se lee.

    Se sacan de la copia local al entregarlo y van en su constancia, junto a su
    archivo: así el cruce con el expediente no vuelve a abrir el PDF por la red.
    """
    from ..adapters.pymupdf_source import PyMuPDFPageSource
    from ..domain.resolutor_del_re import citas_del_texto

    try:
        with PyMuPDFPageSource(pdf) as fuente:
            texto = "\n".join(fuente.text_of(p) or "" for p in range(1, fuente.page_count + 1))
    except Exception:  # noqa: BLE001 - un PDF ilegible no para la entrega
        return None
    return [[numero, fragmento] for numero, fragmento in citas_del_texto(texto)]


def _citas_guardadas(archivo: Mapping) -> list[tuple[str, str]] | None:
    citas = archivo.get("citas")
    if not isinstance(citas, list):
        return None
    validas = []
    for cita in citas:
        if isinstance(cita, list | tuple) and len(cita) == 2 and all(isinstance(parte, str) for parte in cita):
            validas.append((cita[0], cita[1]))
        else:
            return None
    return validas


def corregir_con_el_expediente(
    carpeta: Path, *, leidas: list[tuple[Path, object]] | None = None, en_el_orden: bool = False
) -> list[str]:
    """El RE leído a mano que otro documento del mismo NIC cita distinto se corrige en lo entregado (2026-11-24).

    El operador, ante 4251556: la petición de 2022 salió RE2311202207568 -- el
    «1» a mano con su gancho leído «7» -- y la de 2023, en otro UPD, dice
    «Derecho de Petición numerado según oficio 2311202201568». Cada UPD se
    procesa solo y no veía al otro: al ordenar la carpeta del NIC están todos.

    Para cada PDF cuyo RE salió de una lectura a mano o de una decisión del
    agente (nunca lo impreso ni lo que confirmó el operador), se busca en el
    texto de los demás PDF del NIC un número que lo corrija
    (``domain.resolutor_del_re.re_citado_en_el_expediente``). Si lo hay, se
    renombra el PDF, su fila y su evidencia -- «citado en otro documento del
    expediente», con la cita --. El índice del NIC lo reescribe quien ordena la
    carpeta, con las filas de las constancias. Devuelve lo que corrigió.

    Rápido, porque corre en cada entrega de la carpeta (2026-11-26):

    - primero se miran los candidatos -- un RE leído a mano que se pueda
      corregir --, y sin ninguno no se lee nada;
    - el texto de cada PDF sale de las citas guardadas en su constancia
      (``citas_del_pdf``); sólo se abre por la red el de una entrega de antes
      que no las trae;
    - ``leidas``: las constancias completas que ya leyó quien ordena la carpeta,
      para no volver a listarlas ni leerlas; se corrigen en el sitio;
    - ``en_el_orden``: lo llama quien ordena la carpeta, que reescribe enseguida
      el índice del NIC con las constancias ya corregidas, y el general lo rehace
      el escritor de los generales: no se parchea ninguno de los dos aquí.
    """
    from ..domain.nombre_oficial import re_del_archivo
    from ..domain.resolutor_del_re import citas_del_texto, re_citado_entre_citas

    hechos: list[str] = []
    with cerrojo_de_la_carpeta(carpeta):
        if leidas is None:
            try:
                rutas = sorted(carpeta.glob(f"{Path(constancias.NOMBRE).stem}-*.json"))
            except OSError:
                return hechos
            leidas = [
                (ruta, constancia)
                for ruta in rutas
                if (constancia := constancias.leer(ruta)) is not None
                and constancia.estado == constancias.EstadoDeEntrega.COMPLETA
            ]
        archivos = [a for _, c in leidas for a in _pdfs_en_orden(c)]
        if len(archivos) < 2:
            return hechos
        # Sin ningún RE que se pueda corregir, no hace falta ningún texto.
        if not any(
            re_del_archivo(str(archivo.get("ruta") or ""))
            and (hojas := _hojas_del_documento(constancia, posicion))
            and _se_corrige_por_el_expediente((constancia.evidencia.get("re") or {}).get(str(min(hojas))) or {})
            for _, constancia in leidas
            for posicion, archivo in enumerate(_pdfs_en_orden(constancia))
        ):
            return hechos
        citas_de: dict[str, list[tuple[str, str]]] = {}
        sin_citas: list[str] = []
        for archivo in archivos:
            ruta = str(archivo.get("ruta") or "")
            guardadas = _citas_guardadas(archivo)
            if guardadas is None:
                sin_citas.append(ruta)
            else:
                citas_de[ruta] = guardadas
        for ruta, texto in _textos_de_los_pdf(carpeta, sin_citas).items():
            citas_de[ruta] = citas_del_texto(texto)
        for ruta_de_la_constancia, constancia in leidas:
            renombrados: list[tuple[Path, Path]] = []
            hechos_de_esta: list[str] = []
            celdas: list[tuple[str, str]] = []
            # Cómo estaba: si no se puede guardar, vuelve a estar así también en
            # memoria. Quien ordena la carpeta sigue con este mismo objeto, y con
            # los cambios a medias numeraba y escribía el índice con un RE que el
            # archivo no lleva (la revisión, 2026-11-26).
            respaldo = copy.deepcopy(constancia)
            for posicion, archivo in enumerate(_pdfs_en_orden(constancia)):
                ruta = str(archivo.get("ruta") or "")
                actual = re_del_archivo(ruta)
                hojas = _hojas_del_documento(constancia, posicion)
                if not actual or not hojas:
                    continue
                primera = str(min(hojas))
                evidencia = (constancia.evidencia.get("re") or {}).get(primera) or {}
                if not _se_corrige_por_el_expediente(evidencia):
                    continue
                candidatos = [
                    str(c.get("valor") if isinstance(c, Mapping) else c) for c in evidencia.get("candidatos") or []
                ]
                otros = {Path(r).name: c for r, c in citas_de.items() if r != ruta}
                cita = re_citado_entre_citas(actual, candidatos, otros)
                if cita is None:
                    continue
                antes = constancias.ruta_de_entrega(carpeta, ruta)
                despues = constancias.ruta_de_entrega(carpeta, con_su_re_en_la_ruta(ruta, cita.radicado))
                if antes is None or despues is None or (despues.exists() and despues != antes):
                    continue
                try:
                    if antes.exists():
                        os.replace(antes, despues)
                        renombrados.append((antes, despues))
                except OSError as error:
                    hechos.append(f"«{antes.name}»: el expediente cita {cita.radicado} y no se pudo renombrar: {explicar_fallo(error)}")
                    continue
                filas = (constancia.indice or {}).get("filas") or []
                viejo = (
                    str(filas[posicion].get("nombre") or "")
                    if posicion < len(filas) and isinstance(filas[posicion], dict)
                    else ""
                )
                re_en_la_constancia(constancia, posicion, cita.radicado, CITADO_EN_EL_EXPEDIENTE)
                if viejo:
                    celdas.append((viejo, con_su_re(viejo, cita.radicado)))
                constancia.evidencia["re"][primera].update(
                    {
                        "metodo": f"{CITADO_EN_EL_EXPEDIENTE}: «{cita.fuente}»",
                        "lectores": ["sello", "expediente"],
                        "fragmento": cita.fragmento,
                        "motivo": f"antes {actual}, leído a mano",
                    }
                )
                citas_de[con_su_re_en_la_ruta(ruta, cita.radicado)] = citas_de.pop(ruta, [])
                hechos_de_esta.append(f"«{Path(ruta).name}»: {actual} → {cita.radicado}, como lo cita «{cita.fuente}»")
            if not hechos_de_esta:
                continue
            try:
                constancias.escribir(ruta_de_la_constancia, constancia)
            except OSError as error:
                # Sin su constancia, los PDF vuelven a su nombre y la constancia
                # en memoria a como estaba: nada queda a medias.
                for antes, despues in reversed(renombrados):
                    try:
                        os.replace(despues, antes)
                    except OSError:
                        pass
                for campo in dataclasses.fields(respaldo):
                    setattr(constancia, campo.name, getattr(respaldo, campo.name))
                hechos.append(f"no se pudo actualizar «{ruta_de_la_constancia.name}»: {explicar_fallo(error)}")
                continue
            hechos.extend(hechos_de_esta)
            # Su celda en el índice del NIC y en el general de la raíz, como la
            # corrección del operador: quien ordena la carpeta rehace el del NIC.
            from ..adapters.indice_electronico import NOMBRE_DEL_INDICE

            if en_el_orden:
                # Quien ordena la carpeta reescribe enseguida el índice del NIC
                # con estas constancias, y el general lo rehace su escritor.
                continue
            upd = Path(str(constancia.origen or "")).stem
            for viejo, nuevo in celdas:
                if (carpeta / NOMBRE_DEL_INDICE).is_file():
                    hechos.extend(_en_el_indice_del_nic(carpeta, viejo, nuevo))
                hechos.extend(_en_el_indice_general(str(carpeta.parent), (carpeta.name, upd), viejo, nuevo))
    return hechos
