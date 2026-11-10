"""Levantar el inventario de un documento sin partirlo.

Dos maneras de no partir nada, y la diferencia está en qué se considera la
unidad documental.

`_inventory_job` lee un libro empastado de registros de diplomas -- nadie lo va
a desencuadernar -- y saca una fila por registro de dentro. `_inventory_file_job`
lee un PDF que **ya es** un documento y saca una sola fila: la del archivo. Los
dos dejan el original exactamente como llegó y los dos escriben sólo el FUID.

Confundirlos da los dos errores simétricos: un libro de cuatrocientos diplomas
anotado en un renglón, o una nota de ajuste de dos hojas repartida en doce.
"""

from __future__ import annotations

import errno
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from ...application.progress import Stage
from .planillas import _escribir_fuid, _escribir_fuid_de_archivo
from .taller import Taller, _anunciar

if TYPE_CHECKING:
    from ...application.acta_consejo import FilaDeActa, SesionDeActa
    from ...application.fuid import FuidRow
    from ...application.revisor_de_fechas import FechasRevisadas

logger = logging.getLogger(__name__)


def _inventory_job(payload: dict) -> dict:
    """Leer el documento y dejar sólo su FUID, con el original intacto."""
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...application.inventory_document import InventoryDocument
    from ...application.task import TaskKind
    from ...application.tipo_pedido import TipoPedido

    taller = Taller.desde(payload)

    # 1. Leer: la misma cascada que parte resoluciones, puesta a reconocer
    #    registros. De ahí salen las filas del inventario. Con los mismos
    #    ajustes con que se partiría el libro -- el criterio de corte, el
    #    rastreo local de la cédula, el mosaico de la lectura de ahorro --,
    #    porque inventariar sin partir es la misma lectura sin escribir PDF, y
    #    leerla distinto daría un inventario que no cuadra con la carpeta que
    #    saldría del mismo libro.
    ocr = taller.ocr()
    use_case = InventoryDocument(
        ocr=ocr,
        pipeline=taller.pipeline(ocr),
        progress=taller.progress,
        control=taller.control,
        workers=int(taller.settings.get("page_workers") or 8),
        criterio=taller.criterio(),
        rastreo=taller.rastreo(),
        mosaico=taller.mosaico(),
        # Y la repesca de la cédula en franjas, para lo que la lectura
        # entera deje sin ella.
        mosaico_de_cedulas=taller.mosaico_de_cedulas(),
        # Y la repesca de la fecha en el pie del diploma.
        mosaico_de_fechas=taller.mosaico_de_fechas(),
        lectura_de_ahorro=taller.lectura_de_ahorro(),
        # Resúmenes de actas con Mistral
        mistral_summary=taller.mistral_summary(),
    )
    source = PyMuPDFPageSource(taller.source, taller.name)
    try:
        outcome = use_case.execute(
            source,
            document_name=taller.name,
            ubicacion=taller.ubicacion(),
            # Si el operador dijo qué es, no se muestrea: se le cree.
            declarado=TipoPedido.parse(payload.get("tipo")).document_type,
        )
    finally:
        source.close()

    # Si lo que se reconoció son actas de consejo, su inventario es el de actas:
    # una fila por PDF con el acta, la fecha, los folios y el resumen.
    from ...domain.doctype import DocumentType

    if outcome.document_type is DocumentType.ACTA_CONSEJO:
        return _acta_consejo_job(payload)

    # Y aquí el desvío que evita el peor resultado posible de esta pantalla: un
    # trabajo que termina en verde sin haber escrito nada. Esta ruta sólo sabe
    # sacar filas de dentro de un libro de registros de la Universidad; cuando
    # el papel no es ninguno de los que reconoce -- una nota de ajuste, un
    # comprobante de egreso, cualquier PDF que ya es un documento -- devolvía
    # cero filas, y cero filas es un FUID que no se escribe. El operador pedía
    # "solo inventariar", veía las doce páginas pasar, y se quedaba sin
    # inventario y sin un motivo.
    #
    # Lo que se hace en su lugar es lo que el operador pidió, leído de la otra
    # manera: si el documento no se deja repartir en filas, el documento **es**
    # la fila. Es el mismo desvío que ya hace «Dividir en documentos» cuando no
    # reconoce el tipo, y por el mismo motivo.
    if not outcome.rows:
        logger.info(
            "%s: no se reconoció ningún registro que inventariar; se inventaría "
            "el archivo entero como una sola unidad documental",
            taller.name,
        )
        _anunciar(
            payload,
            Stage.IDENTIFYING,
            detail="sin registros reconocibles: se inventaría el archivo entero",
        )
        return _inventory_file_job(payload)

    # 2. El revisor de fechas (2026-11-10): la fecha inicial y la final de cada
    #    fila contra el papel de sus páginas, con la regla de su habilidad, antes
    #    de escribir el FUID. El texto que leyó la lectura no se guarda, así que
    #    se toma la capa de texto -- sin OCR: nada se vuelve a pagar ni a leer
    #    con Tesseract --, y lo que salió de una página leída por OCR no se da
    #    por contradicho sólo porque la capa no lo traiga.
    revisor = _RevisorDeFechas(taller, _HABILIDAD_DEL_TIPO.get(str(outcome.document_type)))
    paginas = _paginas_de_cada_fila(outcome)
    _anunciar(payload, Stage.INVENTORYING, detail="revisando las fechas de cada documento")
    outcome.rows = _revisar_las_filas_del_fuid(
        revisor,
        outcome.rows,
        paginas,
        _capa_de_texto(taller, (p for suyas in paginas.values() for p in suyas)),
        # Todas las páginas por la capa: es justo lo que se leyó.
        completas=_todo_por_la_capa(outcome.provenance),
        minimo=_MIN_CHARS_DE_LA_CAPA,
    )

    report = outcome.as_dict()
    report["task"] = str(TaskKind.INVENTORY)
    revisor.anotar(report)

    # 3. La planilla: aquí no hay PDF que escribir, sólo el FUID.
    _escribir_fuid(
        report,
        outcome.rows,
        settings=taller.settings,
        destination=taller.destination,
        name=taller.name,
        document_type=outcome.document_type,
        control=taller.control,
        payload=payload,
    )
    _anunciar(payload, Stage.DONE)
    return report


def _acta_consejo_job(payload: dict, *, grado: bool = False) -> dict:
    """Inventariar las actas de consejo de un PDF: una fila por acta, en su Excel y en el FUID.

    Si además se pidió dividir -- la acción «Dividir e inventariar» --, cada
    sesión sale en su propio PDF con su portada, su citación, su asistencia, su
    acta y sus anexos dentro. El reparto sale del mismo texto que ya se leyó
    para el inventario, así que dividir no cuesta ninguna lectura más, ni de
    pago ni de casa.

    Su Excel de siempre -- la carpeta, el archivo, las páginas, el acta, su
    fecha, el folio inicial y el final, cuántos folios son y el resumen -- y,
    desde el 2026-10-29, el FUID oficial como todas las habilidades (ver
    ``adapters/fuid_de_la_entrega.py``). Un PDF de un acta da una fila; un
    libro, una por cada acta que trae. Quedan junto al trabajo, y en una
    corrida de carpeta se juntan con los demás PDF en los de su subcarpeta y en
    los generales. El original no se toca.

    Las actas de grado (``grado``) son el mismo trabajo con otro perfil, y su
    inventario es sólo el FUID: una fila por graduado.
    """
    from ...adapters.excel_actas import SUFIJO, escribir_inventario_de_actas
    from ...adapters.huellas_pdf import huellas_de
    from ...adapters.pymupdf_assembler import PyMuPDFAssembler
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...adapters.tesseract_ocr import HeaderAndPageOcr
    from ...application.acta_consejo import (
        CONSEJO,
        GRADO,
        SIN_IA,
        InventariarActa,
        dividir_actas,
        reparto_de_las_actas,
        resultado_de_cada_acta,
    )
    from ...application.control import Cancelled
    from ...application.perfiles_de_revision import perfil_de
    from ...application.revisor_de_cortes import anotar_en_el_informe, revisar_sin_romper

    # Las actas de grado son el mismo trabajo con otro perfil: otro
    # encabezado, otra fecha y sin resumen.
    perfil = GRADO if grado else CONSEJO
    from ...application.task import TaskKind
    from ...domain.naming import document_folder, sheet_filename

    taller = Taller.desde(payload)
    # La carpeta del PDF -- la UPD -- cuando viene de una corrida de carpeta,
    # que es cuando el original sigue en su sitio. Una subida está en la
    # carpeta de subidas, que no dice nada.
    carpeta = taller.source.parent.name if payload.get("destination") else ""

    source = PyMuPDFPageSource(taller.source, taller.name)
    try:
        outcome = InventariarActa(
            # El OCR de casa y nada más para leer el texto, elija lo que elija
            # el operador: el acta es mecanografiada, y la ayuda de pago entra
            # para lo que el de casa no sabe leer -- el folio manuscrito --, para
            # cruzar cada dato de la fila con una segunda lectura y para escribir
            # el resumen a partir del texto ya leído.
            ocr=HeaderAndPageOcr(language=taller.settings["ocr_language"]),
            resumidor=taller.resumidor(),
            lector_de_folios=taller.lector_de_folios(),
            progress=taller.progress,
            control=taller.control,
            workers=int(taller.settings.get("page_workers") or 8),
            motivo_sin_resumidor=taller.motivo_sin_resumidor(),
            perfil=perfil,
            # Con «OCR + IA», la IA lee también la hoja de cada acta -- de consejo
            # y de grado -- para cruzar cada dato con el OCR (2026-10-31).
            relector_de_pago=taller.lector_de_pago(),
            lector_de_cifras=_lector_de_cifras(taller) if grado else None,
            lector_de_franja=_lector_de_franja(taller) if grado else None,
            lectores_de_tinta_clara=_lectores_de_tinta_clara(taller),
            lector_de_datos=taller.lector_del_acta_de_grado() if grado else None,
        ).execute(source, document_name=Path(taller.name).name, carpeta=carpeta)
    finally:
        source.close()

    # El revisor de fechas (2026-11-10), con la regla de lo que de verdad es --
    # la apertura de la sesión o la fecha del acta de grado --: cada fila contra
    # el texto de sus páginas, el que ya se leyó para el inventario. **Antes de
    # dividir**: el PDF de cada sesión se llama por su acta y su fecha
    # («03_ACTA-…-16-08-2012.pdf»), y revisada después salía con la fecha vieja
    # mientras su fila y el FUID llevaban la corregida (la revisión adversarial,
    # 2026-11-10). Y antes del informe y del FUID, que también la llevan.
    revisor = _RevisorDeFechas(taller, outcome.tipo_documental)
    _anunciar(payload, Stage.INVENTORYING, detail="revisando las fechas de cada acta")
    leidas = list(outcome.filas)
    outcome.filas, primera_corregida = _revisar_las_actas(revisor, outcome.filas, outcome.textos)
    outcome.sesiones = _sesiones_con_su_fecha(outcome.sesiones, leidas, outcome.filas)

    # Dividir sólo lo que hay que dividir: un libro con varias actas. Un PDF
    # que ya es un acta -- porque alguien lo dividió antes -- se inventaría y
    # nada más; partirlo daría el mismo PDF con otro nombre.
    pidio_dividir = payload.get("task") in (str(TaskKind.SPLIT), str(TaskKind.BOTH))
    # El agente revisor (2026-11-05), con el perfil de su habilidad -- de grado
    # o de consejo, por lo que de verdad es --: cada costura entre sesiones del
    # libro contra lo que dice el papel, se divida o sólo se inventaríe, porque
    # cada sesión es una fila. Señala y no mueve: el nombre y la fila de cada
    # acta salen de leerla. Lo que sale del margen lo decide la IA si se eligió.
    del_revisor = perfil_de(outcome.tipo_documental)
    revision = aviso_del_revisor = None
    if outcome.reparto.es_libro and len(outcome.sesiones) > 1:
        revision, aviso_del_revisor = revisar_sin_romper(
            reparto_de_las_actas(outcome),
            outcome.textos,
            del_revisor.patrones(outcome.textos),
            juez=taller.juez_de_costuras(),
        )
    division = None
    no_se_dividio: str | None = None
    if pidio_dividir and outcome.reparto.es_libro:
        # En una carpeta con el nombre del PDF de origen, como las demás
        # habilidades: con varios libros en el mismo trabajo, cada uno en la
        # suya.
        sesiones = len(outcome.sesiones)
        _anunciar(
            payload, Stage.ASSEMBLING, detail=f"escribiendo {sesiones} PDF", done=0, total=sesiones
        )
        try:
            division = dividir_actas(
                outcome,
                assembler=PyMuPDFAssembler(
                    control=taller.control,
                    progress=taller.progress,
                    naming_prefix=None,
                    mayusculas=True,
                    nombre=taller.name,
                ),
                source=taller.source,
                # Recortada como la de las demás habilidades: con el nombre
                # entero de un PDF largo -- «SESION ORDINARIA Y EXTRAORDINARIA
                # DE CONSEJO DE FACULTAD DEPARTAMENTO ACADEMICO 2015- ACTAS 7 Y
                # 8» -- la ruta del espejo pasaba de lo que Windows deja crear.
                destino=taller.destination / document_folder(Path(taller.name).name),
                raiz=taller.destination,
                # Cada PDF escrito, vuelto a abrir y casado con el libro.
                huellas=huellas_de,
            )
        except Cancelled:
            raise
        except Exception as error:  # noqa: BLE001 - lo leído sirve igual
            # Una ruta que Windows no deja crear o un PDF dañado a mitad: lo
            # leído no se pierde por eso. El Excel se escribe con cada acta y
            # el motivo en su columna, y la pantalla lo avisa.
            #
            # Un disco lleno no: tampoco cabría el Excel, y el documento tiene
            # que fallar con su motivo en vez de terminar como si nada.
            if isinstance(error, OSError) and error.errno == errno.ENOSPC:
                raise
            logger.warning("no se pudo dividir %s", taller.name, exc_info=True)
            no_se_dividio = f"{type(error).__name__}: {error}"
    outcome.filas = resultado_de_cada_acta(
        outcome.filas,
        division.salidas if division else None,
        pidio_dividir=pidio_dividir,
        no_se_dividio=no_se_dividio,
    )

    report = outcome.as_dict()
    if primera_corregida:
        # La pantalla de Archivo lee la fecha de la primera acta del informe.
        report["fecha_inicial"] = report["fecha_final"] = outcome.filas[0].fecha
    revisor.anotar(report)
    # Para el libro mayor es un archivo inventariado entero, que es lo que es:
    # así aparece en la pantalla de Archivo con su acta y su fecha.
    report["task"] = str(TaskKind.INVENTORY_FILE)
    report["tipo"] = "acta" if grado else "acta-consejo"
    if no_se_dividio:
        report["division_error"] = no_se_dividio
        report.setdefault("notices", []).append(f"no se pudo dividir el libro: {no_se_dividio}")
    if division is not None:
        report["outputs"] = division.salidas
        report["unwritable_pages"] = division.ilegibles
        report["dividido"] = True
    if revision is not None or aviso_del_revisor or division is not None:
        anotar_en_el_informe(
            report,
            revision,
            aviso_del_revisor,
            division.comprobacion if division is not None else None,
            perfil=del_revisor.as_dict(),
        )

    _anunciar(payload, Stage.INVENTORYING, detail="escribiendo el FUID", done=0, total=1)
    taller.control.check()
    from ...adapters.fuid_de_la_entrega import SUFIJO_DEL_FUID, escribir_fuid

    # Con el nombre del PDF y no con su ruta: en una corrida de carpeta el
    # nombre llega con la carpeta delante, y el Excel caía en una subcarpeta
    # donde el botón de descarga no lo buscaba.
    def junto_al_trabajo(sufijo: str) -> Path:
        return taller.destination / sheet_filename(
            Path(taller.name).name, sufijo, directory_length=len(str(taller.destination))
        )

    filas = [asdict(fila) for fila in outcome.filas]
    try:
        if grado:
            # Las actas de grado: su inventario es el FUID, una fila por graduado.
            report["inventario"] = escribir_fuid(
                filas, junto_al_trabajo(SUFIJO), oficina=payload.get("oficina")
            ).name
        else:
            # Las de consejo, su Excel de siempre, con el resumen de cada acta,
            # y además el FUID, como todas las habilidades desde el 2026-10-29.
            report["inventario"] = escribir_inventario_de_actas(
                outcome.filas,
                junto_al_trabajo(SUFIJO),
                nota=None if taller.con_ia() else SIN_IA,
                titulo=perfil.titulo,
                con_resumen=perfil.con_resumen,
            ).name
            report["fuid_de_actas"] = escribir_fuid(
                filas, junto_al_trabajo(SUFIJO_DEL_FUID), oficina=payload.get("oficina")
            ).name
    except Exception as error:  # noqa: BLE001 - la lectura sirvió igual
        logger.warning("no se pudo escribir el inventario del acta", exc_info=True)
        report["inventario_error"] = f"{type(error).__name__}: {error}"
    _anunciar(payload, Stage.DONE)
    return report


def _lector_de_cifras(taller: Taller):
    """Tesseract para un renglón de cifras escritas a máquina: el número del acta, la cédula."""
    from ...adapters.tesseract_ocr import TesseractConfig, TesseractOcr

    return TesseractOcr(
        TesseractConfig(
            language=taller.settings["ocr_language"],
            psm=7,
            whitelist="0123456789/-.,'",
            escala=2,
        )
    )


#: Desde qué gris se toma un píxel por tinta en la relectura. Medido sobre
#: UPD3859806 y UPD3859813, donde la fecha y el nombre van a máquina en gris
#: claro: con 220 aparecen las fechas que la lectura normal no veía
#: (04-04-1997, 21-12-1995, 16-12-1994).
UMBRAL_DE_TINTA_CLARA = 220
#: Lo más que espera la relectura por una hoja: un escaneo sucio no puede
#: detener el inventario.
SEGUNDOS_POR_HOJA_RELEIDA = 12.0


def _lectores_de_tinta_clara(taller: Taller):
    """Tesseract para la última búsqueda de lo que falta: la hoja con la tinta realzada.

    Dos pasadas: la primera borra las motas que el umbral vuelve tinta -- en un
    escaneo sucio tarda la mitad y además lee fechas que sin el filtro no
    salían --, y la segunda, sólo para lo que siga faltando, lee sin el
    filtro, que a veces se come un trazo fino.
    """
    from ...adapters.tesseract_ocr import TesseractConfig, TesseractOcr

    comun = {
        "language": taller.settings["ocr_language"],
        "psm": 6,
        "min_word_confidence": 0,
        "umbral": UMBRAL_DE_TINTA_CLARA,
        "timeout_seconds": SEGUNDOS_POR_HOJA_RELEIDA,
    }
    return (
        TesseractOcr(TesseractConfig(**comun, mediana=3)),
        TesseractOcr(TesseractConfig(**comun)),
    )


def _lector_de_franja(taller: Taller):
    """Tesseract para la franja del graduado: un bloque de texto a máquina."""
    from ...adapters.tesseract_ocr import TesseractConfig, TesseractOcr

    return TesseractOcr(
        TesseractConfig(language=taller.settings["ocr_language"], psm=6, min_word_confidence=0)
    )


def _inventory_file_job(payload: dict) -> dict:
    """Anotar el archivo entero en el inventario, sin abrirlo en pedazos.

    Una fila, la del PDF: su asunto, sus fechas extremas -- la más antigua y la
    más reciente que aparezcan en cualquiera de sus hojas -- y sus folios. No se
    escribe ningún PDF y el original no se toca.
    """
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...application.inventory_file import InventoryFile
    from ...application.task import TaskKind

    taller = Taller.desde(payload)

    source = PyMuPDFPageSource(taller.source, taller.name)
    try:
        outcome = InventoryFile(
            ocr=taller.ocr(),
            progress=taller.progress,
            control=taller.control,
        ).execute(
            source, document_name=taller.name, ubicacion=taller.ubicacion()
        )
    finally:
        source.close()

    # El revisor de fechas (2026-11-10): las fechas extremas del archivo contra
    # su papel, con la regla de los archivos ya separados -- la más antigua y la
    # más reciente --. La capa de texto es exactamente lo que se leyó si ninguna
    # página pasó por OCR; si alguna pasó, lo que la capa no traiga no prueba
    # nada en contra.
    revisor = _RevisorDeFechas(taller, "archivos-separados")
    paginas = list(range(1, outcome.page_count + 1))
    _anunciar(payload, Stage.INVENTORYING, detail="revisando las fechas del archivo")
    (outcome.row,) = _revisar_las_filas_del_fuid(
        revisor,
        [outcome.row],
        {outcome.row.pagina_inicial: paginas},
        _capa_de_texto(taller, paginas),
        completas=outcome.ocr_pages == 0,
        minimo=0,
    )

    report = outcome.as_dict()
    report["task"] = str(TaskKind.INVENTORY_FILE)
    revisor.anotar(report)

    _escribir_fuid_de_archivo(
        report,
        outcome.rows,
        settings=taller.settings,
        destination=taller.destination,
        name=taller.name,
        control=taller.control,
        payload=payload,
    )
    _anunciar(payload, Stage.DONE)
    return report


# -----------------------------------------------------------------------------
#  El revisor de fechas (2026-11-10)
# -----------------------------------------------------------------------------
#  El operador: «necesito estar muy seguro de cada fecha en cada documento, sin
#  importar la habilidad», «corregir sólo con prueba» y «saber manejar un margen
#  de errores». La decisión es de ``application/revisor_de_fechas.py`` y la
#  misma en todas las habilidades; aquí sólo se le da a cada fila lo suyo -- la
#  regla de su habilidad, el texto de sus páginas, un juez por trabajo -- y se
#  escribe lo corregido con el formato de su fila.
#
#  Optimizado: el texto es el que ya se leyó (las actas lo guardan) o la capa
#  de texto del PDF, nunca una lectura nueva con OCR; la IA sólo ve lo dudoso,
#  una pregunta por documento, y sólo si la corrida se hizo con «OCR + IA».

#: La habilidad de cada tipo que reconoce `_inventory_job`: su regla de fechas.
_HABILIDAD_DEL_TIPO = {
    "diploma": "diplomas",
    "resolucion": "resoluciones",
    "matricula": "matriculas",
    "acta": "actas-de-grado",
}

#: Desde cuántos caracteres la capa de texto de una página es lo que se leyó:
#: el umbral con que la lectura decide no pasar la página por OCR
#: (``application/inventory_file.MIN_CHARS``).
_MIN_CHARS_DE_LA_CAPA = 80


class _RevisorDeFechas:
    """El revisor de fechas de un trabajo: la regla de su habilidad, un juez y lo decidido.

    Nunca tumba el trabajo: un fallo deja la fila como se leyó, con un aviso
    en el registro. La cancelación sí se propaga.
    """

    def __init__(self, taller: Taller, habilidad: str | None) -> None:
        from ...application.perfiles_de_revision import perfil_de
        from ...domain.fechas_extremas import EXTREMOS

        # La regla del perfil; sin ella, la de cualquier papel (las puntas), que
        # sólo confirma o pregunta y nunca corrige sin la IA.
        self.regla = getattr(perfil_de(habilidad), "regla_de_fechas", None) or EXTREMOS
        self._control = taller.control
        # Un juez para todo el trabajo, con su plazo: con «Solo OCR», ninguno.
        # El de las rutas que parten (``juez_del_trabajo``), que deja subir la
        # cancelación: aquí se la tragaba un ``except Exception`` (la revisión
        # adversarial, 2026-11-10).
        from .fechas_aseguradas import juez_del_trabajo

        self._juez = juez_del_trabajo(taller)
        self.revisiones: list[tuple[str, int | None, FechasRevisadas]] = []

    def revisar(
        self,
        documento: str,
        pagina: int | None,
        fila: Mapping[str, object],
        textos: Sequence[str],
        *,
        completo: bool = True,
    ) -> FechasRevisadas | None:
        """Las fechas de una fila contra sus páginas; ``None`` si el revisor falló.

        Con ``completo=False`` -- el texto no es todo lo que se leyó -- sólo
        cuenta lo que el papel confirma: sin la página que se leyó por OCR no
        hay prueba para corregir ni motivo para mandar a Revisión, y la IA no
        se paga sobre medio texto.
        """
        from ...application.control import Cancelled
        from ...application.revisor_de_fechas import revisar_las_fechas
        from ...domain.fechas_extremas import fechas_de_la_fila
        from .fechas_aseguradas import sin_repetir, solo_lo_confirmado

        try:
            self._control.check()
            fechas = fechas_de_la_fila(fila)
            # Cada hoja una vez: la IA se paga por token (2026-11-10).
            revisadas = revisar_las_fechas(
                fechas, sin_repetir(textos), regla=self.regla, juez=self._juez if completo else None
            )
            if not completo:
                revisadas = solo_lo_confirmado(revisadas, fechas)
        except Cancelled:
            raise
        except Exception:  # noqa: BLE001 - la fila queda como se leyó
            logger.warning(
                "el revisor de fechas falló en %s; queda como se leyó", documento, exc_info=True
            )
            return None
        self.revisiones.append((documento, pagina, revisadas))
        return revisadas

    def anotar(self, report: dict) -> None:
        """Lo decidido, en el informe: cuentas, avisos de lo corregido y la cola de Revisión."""
        from ...application.revisor_de_fechas import anotar_en_el_informe

        for documento, pagina, revisadas in self.revisiones:
            try:
                anotar_en_el_informe(report, documento, pagina, revisadas)
            except Exception:  # noqa: BLE001 - el informe sale igual
                logger.warning(
                    "no se pudo anotar la revisión de fechas de %s", documento, exc_info=True
                )


def _revisar_las_actas(
    revisor: _RevisorDeFechas, filas: Sequence[FilaDeActa], textos: Mapping[int, str]
) -> tuple[list[FilaDeActa], bool]:
    """Las filas de actas con su fecha revisada, y si se corrigió la de la primera.

    El texto es el que ya se leyó para el inventario (``outcome.textos``): está
    entero, así que el revisor trabaja con todo su margen.
    """
    from ...application.revisor_de_fechas import CORREGIDA

    revisadas_filas: list[FilaDeActa] = []
    primera_corregida = False
    for orden, fila in enumerate(filas):
        suyas = range(fila.pagina_inicial, max(fila.pagina_inicial, fila.pagina_final) + 1)
        revisadas = revisor.revisar(
            fila.acta or fila.nombre or fila.archivo,
            fila.pagina_inicial,
            asdict(fila),
            [textos.get(pagina, "") for pagina in suyas],
        )
        if revisadas is not None and revisadas.estado == CORREGIDA:
            inicial, final = _corregidas(revisadas, fila.fecha, fila.fecha)
            # Las actas llevan una sola fecha: la que el papel corrigió. Su nota
            # no va a «Observaciones»: el Excel de actas se entrega, y ahí salía
            # el texto de la prueba, dos veces, y la fila contaba «POR REVISAR»
            # (la revisión, 2026-11-10). La corrección queda en los avisos del
            # trabajo y en ``revision_de_fechas``, como la de las demás filas.
            fila = replace(fila, fecha=inicial if inicial != fila.fecha else final)
            primera_corregida = primera_corregida or orden == 0
        revisadas_filas.append(fila)
    return revisadas_filas, primera_corregida



def _sesiones_con_su_fecha(
    sesiones: Sequence[SesionDeActa], leidas: Sequence[FilaDeActa], revisadas: Sequence[FilaDeActa]
) -> list[SesionDeActa]:
    """Las sesiones del libro con el nombre de su acta revisada: el PDF se llama por su acta y su fecha.

    La sesión ``orden`` es la fila ``orden - 1`` (las páginas previas, la 0, no
    llevan fecha). Sólo se renombra la que el revisor corrigió y conserva el
    nombre que se le dio por su fila: un nombre puesto de otro modo -- el del
    graduado, que no lleva fecha -- queda como estaba (2026-11-10).
    """
    from ...application.acta_consejo import nombre_de_la_sesion

    nuevas: list[SesionDeActa] = []
    for sesion in sesiones:
        indice = sesion.orden - 1
        if 0 <= indice < min(len(leidas), len(revisadas)):
            antes, ahora = leidas[indice], revisadas[indice]
            if antes.fecha != ahora.fecha and sesion.nombre == nombre_de_la_sesion(antes):
                sesion = replace(sesion, nombre=nombre_de_la_sesion(ahora))
        nuevas.append(sesion)
    return nuevas

def _revisar_las_filas_del_fuid(
    revisor: _RevisorDeFechas,
    filas: Sequence[FuidRow],
    paginas: Mapping[int | None, Sequence[int]],
    textos: Mapping[int, str],
    *,
    completas: bool,
    minimo: int,
) -> list[FuidRow]:
    """Las filas del FUID con sus fechas revisadas; lo corregido, en el formato de su fila.

    ``completas`` dice si el trabajo leyó todo por la capa de texto; ``minimo``,
    desde cuántos caracteres la capa de una página es lo que se leyó de ella.
    """
    from ...application.revisor_de_fechas import CORREGIDA

    revisadas_filas: list[FuidRow] = []
    for fila in filas:
        suyos = [textos.get(pagina, "") for pagina in paginas.get(fila.pagina_inicial, ())]
        revisadas = revisor.revisar(
            fila.asunto or f"fila {fila.orden}",
            fila.pagina_inicial,
            {
                "fecha_inicial": fila.fecha_inicial,
                "fecha_final": fila.fecha_final,
                "observaciones": fila.notas,
            },
            suyos,
            completo=completas and all(len(texto.strip()) >= minimo for texto in suyos),
        )
        if revisadas is not None and revisadas.estado == CORREGIDA:
            inicial, final = _corregidas(revisadas, fila.fecha_inicial, fila.fecha_final)
            fila = replace(
                fila,
                fecha_inicial=inicial,
                fecha_final=final,
                notas=_con_nota(fila.notas, revisadas.nota),
            )
        revisadas_filas.append(fila)
    return revisadas_filas


def _paginas_de_cada_fila(outcome) -> dict[int | None, list[int]]:
    """Las páginas de cada fila de `_inventory_job`, por la página que la abre.

    Las de su grupo si la lectura agrupó (diplomas, resoluciones, matrículas);
    si no, de la que la abre a la anterior a la siguiente fila.
    """
    suyas: dict[int | None, list[int]] = {}
    for grupo in outcome.grouping.groups if outcome.grouping else ():
        if grupo.page_numbers:
            suyas.setdefault(grupo.page_numbers[0], list(grupo.page_numbers))
    inicios = sorted({fila.pagina_inicial for fila in outcome.rows if fila.pagina_inicial})
    for orden, inicio in enumerate(inicios):
        if inicio not in suyas:
            fin = inicios[orden + 1] - 1 if orden + 1 < len(inicios) else outcome.page_count
            suyas[inicio] = list(range(inicio, fin + 1))
    return suyas


def _todo_por_la_capa(procedencia: Mapping[str, int]) -> bool:
    """Si la lectura sacó todas las páginas de la capa de texto: la capa es lo que se leyó."""
    from ...domain.page import Provenance

    return bool(procedencia) and all(
        cantidad == 0
        for peldano, cantidad in procedencia.items()
        if peldano != str(Provenance.TEXT_LAYER)
    )


def _capa_de_texto(taller: Taller, paginas: Iterable[int]) -> dict[int, str]:
    """La capa de texto de esas páginas, sin OCR: lo que ya trae el PDF, nada que pagar.

    Si el PDF no se deja abrir, ninguna: las filas quedan sin dato y el
    trabajo sigue.
    """
    from ...adapters.pymupdf_source import PyMuPDFPageSource

    textos: dict[int, str] = {}
    try:
        source = PyMuPDFPageSource(taller.source, taller.name)
    except Exception:  # noqa: BLE001 - sin texto, el revisor no tiene en qué buscar
        logger.warning("no se pudo abrir %s para revisar sus fechas", taller.name, exc_info=True)
        return textos
    try:
        for pagina in sorted(set(paginas)):
            try:
                textos[pagina] = source.text_of(pagina)
            except Exception:  # noqa: BLE001 - una página sin capa es una página sin texto
                textos[pagina] = ""
    finally:
        source.close()
    return textos


def _corregidas(revisadas: FechasRevisadas, inicial: str, final: str) -> tuple[str, str]:
    """La fecha inicial y la final con lo corregido, cada una en el formato de su fila."""
    from ...domain.fechas_extremas import leer_fecha

    hechas = {c.campo: c.dice_el_papel for c in revisadas.correcciones}

    def una(campo: str, original: str, la_otra: str) -> str:
        if campo not in hechas:
            return original
        # El formato de la fila: el suyo, o el de su pareja si era N/A.
        molde = original if leer_fecha(original)[0] is not None else la_otra
        return _en_su_formato(molde, hechas[campo], revisadas.precision, campo)

    return una("fecha_inicial", inicial, final), una("fecha_final", final, inicial)


def _en_su_formato(molde: str, fecha: date, precision: str, campo: str) -> str:
    """La fecha como la escribe su fila: «AAAA», ISO, «dd/mm/aaaa» o «dd-mm-aaaa» (el del FUID)."""
    from ...domain.fechas_extremas import ANIO

    texto = str(molde or "").strip()
    if re.fullmatch(r"\d{4}", texto):
        return str(fecha.year)
    if precision == ANIO:
        # Un año escrito como día lleva el relleno del año: 01/01 y 31/12.
        fecha = date(fecha.year, 1, 1) if campo == "fecha_inicial" else date(fecha.year, 12, 31)
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}.*", texto):
        return fecha.isoformat()
    # Con barras sólo si es una fecha: «N/A» también lleva una.
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", texto):
        return fecha.strftime("%d/%m/%Y")
    return fecha.strftime("%d-%m-%Y")


def _con_nota(texto: str, nota: str) -> str:
    return "; ".join(parte for parte in (texto, nota) if parte)
