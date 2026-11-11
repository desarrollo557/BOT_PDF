"""La auditoría de cierre de una corrida de carpeta: el cuadre del origen con el destino y la muestra.

Lo pidió el operador el 2026-11-05: que el bot, así como vigila cada PDF mientras
procesa, lo haga también **al terminar**: «que se asegure que el mismo número de
registros que está en la fuente esté en el destino» y que «agarre
aleatoriamente unos 100 documentos y valide el margen de errores y los PDF
divididos según los patrones y el margen establecidos». Eligió 100 fijos, que si
la muestra encuentra errores revise otros 100, y el informe dentro de
«00.ANALISIS DE LA ENTREGA.xlsx».

Dos pasos, con lo que hay en el disco y no con lo que la corrida recuerda:

1. **El cuadre**, de todo. El origen se vuelve a listar con los mismos listados
   de la corrida, y cada PDF se verifica contra su constancia de entrega, como
   al relanzar: sin abrir nada. Cuenta las carpetas de cada lado y dice, con su
   evidencia, las carpetas vacías o sin PDF del origen, los archivos sueltos en
   su raíz, lo que sobra en el destino y lo que falta, y que cada índice tenga
   una fila por PDF entregado. Retoma la especificación que dictó el operador el
   2026-10-28 ante MAGANGUE («30 005 carpetas en el origen y 29 974 en el
   destino, y la corrida se dio por terminada»).
2. **La muestra**, de 100 PDF entregados al azar con una semilla anotada: cada
   uno se abre, se casa hoja por hoja con su original y sus cortes se revisan
   otra vez con los patrones y el margen (``application/auditoria_de_la_entrega``).
   Si alguno sale con error, otros 100. De ahí, el margen de error de la corrida.

**Las fechas** (2026-11-10, el revisor de fechas): en las dos muestras, cada
documento -- cada PDF entregado de la muestra de PDF, cada fila de la de filas --
contrasta su fecha inicial y su final con su papel, con la regla de su
habilidad y el mismo margen que al procesar. El operador: que los auditores
cubran «todas las habilidades, todos los documentos, todos los patrones, todo
el margen de errores, de una manera muy optimizada y súper estructurada». Lo
que el papel corrige con prueba es error del documento; lo dudoso, a la IA de
los datos si la corrida se hizo con ella (una pregunta por PDF o por fila), y si
no, duda. Cada muestra dice cómo quedaron (``"fechas"``), en total y por
habilidad.

Nunca reprocesa ni lee con OCR: el origen y lo entregado se abren para su huella
y su capa de texto. Lo que no se deja leer se dice; nada de esto tumba la corrida.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import threading
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from ..adapters import red_smb
from ..adapters.huellas_pdf import huellas_de, huellas_y_textos
from ..adapters.indice_electronico import NOMBRE_DEL_INDICE, leer_indice
from ..application.auditoria_de_la_entrega import auditar_un_pdf
from ..application.perfiles_de_revision import perfil_de
from ..domain.auditoria import (
    BIEN,
    DENTRO_DEL_MARGEN,
    DUDOSO,
    ERROR,
    FUERA_DEL_MARGEN,
    NO_AUDITADO,
    SIN_CERTEZA,
    TAMANO_DE_LA_MUESTRA,
    PdfAuditado,
    elegir_la_muestra,
    margen_de_error,
)
from . import constancia as constancias
from .constancia import Constancia, Vigencia

logger = logging.getLogger(__name__)

#: Cuántos PDF de la muestra se auditan a la vez: lo que se abre va por la red.
AUDITAR_A_LA_VEZ = 4
#: Cuántos PDF se verifican a la vez en el cuadre (como al relanzar).
VERIFICAR_A_LA_VEZ = 8
#: Cuántos faltantes y sobrantes se guardan con su detalle: el resto se cuenta.
DETALLE_MAXIMO = 500


@dataclass(slots=True)
class EntregaVista:
    """Un PDF del origen tal como está en el destino."""

    path: Path
    relativa: str
    vigencia: Vigencia
    constancia: Constancia | None
    #: Dónde se resuelven las rutas de sus archivos entregados.
    base: Path | None
    motivo: str

    @property
    def pdf_entregados(self) -> list[str]:
        return [
            str(archivo.get("ruta"))
            for archivo in (self.constancia.archivos if self.constancia else [])
            if str(archivo.get("ruta", "")).lower().endswith(".pdf")
        ]


def margen_aceptable(habilidad: str | None = None) -> float:
    """El error que se acepta en una habilidad: el de su perfil (``perfiles_de_revision``).

    ``BOTPDF_MARGEN_ACEPTABLE_<CLAVE>`` lo cambia para una habilidad y
    ``BOTPDF_MARGEN_ACEPTABLE`` para todas, en por ciento; si no, el 5 %.
    """
    return perfil_de(habilidad).margen


#: Los estados de las fechas de un documento auditado, en el orden en que se dicen.
ESTADOS_DE_LAS_FECHAS = ("confirmadas", "con error", "en duda", "sin fechas")


def resumen_de_las_fechas(resultados: list[PdfAuditado]) -> dict:
    """Cómo quedaron las fechas de los documentos auditados: cuántos en cada estado (2026-11-10).

    Cuenta documentos -- los PDF entregados de la muestra de PDF, las filas de
    la de filas --, no PDF de la muestra: un original con veinte cartas son
    veinte fechas revisadas. ``revisados`` son los que traían fechas y texto.
    """
    cuentas: Counter[str] = Counter()
    for resultado in resultados:
        for estado, cuantos in (resultado.extra.get("fechas") or {}).items():
            cuentas[estado] += int(cuantos)
    documentos = sum(cuentas.values())
    return {
        "documentos": documentos,
        "revisados": documentos - cuentas.get("sin fechas", 0),
        **{estado: cuentas.get(estado, 0) for estado in ESTADOS_DE_LAS_FECHAS},
    }


def margenes_por_habilidad(resultados: list[PdfAuditado], *, con_dudas: bool = False) -> list[dict]:
    """La muestra partida por habilidad, cada una juzgada contra el margen de su perfil.

    Lo pidió el operador el 2026-11-05: «cada habilidad tiene sus patrones; allí
    sabremos cómo crear el margen de error». Una corrida de carpeta puede
    mezclar habilidades -- un repositorio con diplomas, actas e historias --, y
    el error de una no se diluye en los aciertos de las otras.
    """
    grupos: dict[str, list[PdfAuditado]] = {}
    perfiles = {}
    for resultado in resultados:
        perfil = perfil_de(resultado.habilidad)
        perfiles[perfil.clave] = perfil
        grupos.setdefault(perfil.clave, []).append(resultado)
    salida = []
    for clave, suyos in grupos.items():
        perfil = perfiles[clave]
        cuentas = Counter(r.estado for r in suyos)
        revisados = len(suyos) - cuentas.get(NO_AUDITADO, 0)
        salida.append(
            {
                "clave": clave,
                "habilidad": perfil.nombre,
                "revisados": revisados,
                "bien": cuentas.get(BIEN, 0),
                "errores": cuentas.get(ERROR, 0),
                "dudosos": cuentas.get(DUDOSO, 0),
                "no_auditados": cuentas.get(NO_AUDITADO, 0),
                "margen": margen_de_error(
                    cuentas.get(ERROR, 0),
                    revisados,
                    aceptable=perfil.margen,
                    # En la muestra de filas, lo dudoso sin decidir cuenta en el peor caso.
                    dudosos=cuentas.get(DUDOSO, 0) if con_dudas else 0,
                    unidad="fila" if con_dudas else "PDF",
                ).as_dict(),
                "fechas": resumen_de_las_fechas(suyos),
            }
        )
    salida.sort(key=lambda h: (-h["revisados"], h["habilidad"]))
    return salida


def _base_de_la_constancia(runner, run, path: Path) -> Path | None:
    """La carpeta desde la que se resuelven los archivos de la constancia de un PDF."""
    for actas in (False, True):
        ruta = runner._ruta_de_la_constancia(run, path, actas=actas)
        if ruta.exists():
            return ruta.parent.parent if actas else ruta.parent
    if runner._plana(run):
        antes = runner._entrega_de_antes(run, path)
        if (antes / constancias.NOMBRE).exists():
            return antes
    return None


def _listar(ruta: Path) -> tuple[list[str], list[str]]:
    """Las subcarpetas y los archivos de una carpeta, por nombre, por SMB o del sistema."""
    if red_smb.por_smb(ruta):
        carpetas = red_smb.carpetas(str(ruta))
        archivos = [Path(str(a).replace("\\", "/")).name for a in red_smb.archivos(str(ruta), "")]
        return carpetas, sorted(archivos, key=str.lower)
    carpetas, archivos = [], []
    with os.scandir(ruta) as entradas:
        for entrada in entradas:
            (carpetas if entrada.is_dir() else archivos).append(entrada.name)
    return sorted(carpetas, key=str.lower), sorted(archivos, key=str.lower)


def _evidencia_de(carpeta: Path) -> tuple[str, str]:
    """Por qué una carpeta del origen no trajo ningún PDF: «carpeta totalmente vacía», o qué tiene."""
    extensiones: Counter[str] = Counter()
    try:
        if red_smb.por_smb(carpeta):
            pila = [carpeta]
            while pila:
                actual = pila.pop()
                subcarpetas, archivos = _listar(actual)
                extensiones.update(Path(nombre).suffix.lower() or "(sin extensión)" for nombre in archivos)
                pila.extend(actual / nombre for nombre in subcarpetas)
        else:
            for _, _, archivos in os.walk(carpeta):
                extensiones.update(Path(nombre).suffix.lower() or "(sin extensión)" for nombre in archivos)
    except OSError as error:
        return "no se pudo listar", f"{error.strerror or error}"
    total = sum(extensiones.values())
    if not total:
        return "carpeta totalmente vacía", "0 archivos al listarla"
    detalle = ", ".join(f"{cuantos} {ext}" for ext, cuantos in extensiones.most_common(5))
    return "no tiene ningún PDF", f"{total} archivos ({detalle})"


def cuadrar(runner, run, *, detener: Callable[[], bool] = lambda: False, avance=None) -> tuple[dict, list[EntregaVista]]:
    """El origen contra el destino: cada PDF con su entrega, cada carpeta de cada lado."""
    from .folders import CONSUMED_DIR

    fuente = runner._pdfs_en_la_red(run) if red_smb.por_smb(run.source) else runner._pdfs_locales(run)
    paths: list[Path] = []
    for path, huella in fuente:
        paths.append(path)
        if huella is not None:
            run.huellas_del_origen.setdefault(str(path), huella)
        if detener():
            break

    def ver(path: Path) -> EntregaVista:
        try:
            vigencia, constancia = runner._vigencia(run, path)
            base = _base_de_la_constancia(runner, run, path) if constancia is not None else None
        except OSError as error:
            vigencia, constancia, base = Vigencia.INCOMPLETA, None, None
            run.motivos[str(path)] = f"no se pudo comprobar su entrega ({error})"
        return EntregaVista(
            path=path,
            relativa=str(runner._relative(run, path)),
            vigencia=vigencia,
            constancia=constancia,
            base=base,
            motivo=run.motivos.get(str(path), ""),
        )

    entregas: list[EntregaVista] = []
    with ThreadPoolExecutor(max_workers=VERIFICAR_A_LA_VEZ) as hilos:
        for numero, entrega in enumerate(hilos.map(ver, paths), start=1):
            entregas.append(entrega)
            if avance is not None and numero % 200 == 0:
                avance(numero, len(paths))

    # Las carpetas de la raíz de cada lado.
    carpetas_origen, archivos_origen = _listar(run.source)
    carpetas_origen = [c for c in carpetas_origen if c != CONSUMED_DIR]
    pdf_por_carpeta: Counter[str] = Counter()
    for entrega in entregas:
        partes = Path(entrega.relativa).parts
        if len(partes) > 1:
            pdf_por_carpeta[partes[0]] += 1
    sin_pdf = []
    for carpeta in carpetas_origen:
        if pdf_por_carpeta.get(carpeta):
            continue
        motivo, evidencia = _evidencia_de(run.source / carpeta)
        sin_pdf.append({"carpeta": carpeta, "motivo": motivo, "evidencia": evidencia})
    archivos_en_la_raiz = [{"carpeta": nombre} for nombre in archivos_origen if not nombre.lower().endswith(".pdf")]

    esperadas: set[str] = set()
    for entrega in entregas:
        try:
            relativa = runner._output_dir(run, entrega.path).relative_to(run.destination)
        except ValueError:
            continue
        if relativa.parts:
            esperadas.add(relativa.parts[0])
    try:
        carpetas_destino, _ = _listar(run.destination) if run.destination.exists() else ([], [])
    except OSError:
        carpetas_destino = []
    carpetas_destino = [c for c in carpetas_destino if not c.startswith((".", "_"))]
    sobran = []
    for carpeta in carpetas_destino:
        if carpeta in esperadas or carpeta in pdf_por_carpeta:
            continue
        try:
            _, archivos = _listar(run.destination / carpeta)
            pdfs = sum(1 for nombre in archivos if nombre.lower().endswith(".pdf"))
        except OSError:
            pdfs = 0
        sobran.append(
            {"carpeta": carpeta, "motivo": "está en el destino y no en la raíz del origen", "evidencia": f"{pdfs} PDF"}
        )

    # Lo que falta, por carpeta, con su motivo y su evidencia.
    sin_entregar = [e for e in entregas if e.vigencia is not Vigencia.VIGENTE]
    faltan_por_carpeta: dict[str, list[EntregaVista]] = {}
    for entrega in sin_entregar:
        partes = Path(entrega.relativa).parts
        faltan_por_carpeta.setdefault(partes[0] if len(partes) > 1 else "(raíz)", []).append(entrega)
    def fallo_de(entrega: EntregaVista) -> str | None:
        """Por qué falló al procesarse, si falló: el que se reintenta está en
        ``fallidos``; el que no, en su fila del proceso con estado «Falló»."""
        if str(entrega.path) in run.fallidos:
            return run.fallidos[str(entrega.path)]
        fila = run.procesos.get(entrega.relativa)
        if fila is not None and getattr(fila, "estado", "") == "Falló":
            return getattr(fila, "observaciones", "") or "sin detalle"
        return None

    faltan = []
    for carpeta, suyas in sorted(faltan_por_carpeta.items()):
        fallaron = [(e, motivo) for e in suyas if (motivo := fallo_de(e)) is not None]
        if fallaron:
            motivo = f"{len(fallaron)} PDF fallaron al procesarse"
            evidencia = "; ".join(motivo_del_fallo for _, motivo_del_fallo in fallaron[:3])
        else:
            motivo = f"{len(suyas)} PDF sin entregar"
            evidencia = "; ".join(e.motivo for e in suyas[:3] if e.motivo)
        faltan.append({"carpeta": carpeta, "motivo": motivo, "evidencia": evidencia})
    pdf_sin_entregar = [
        {
            "pdf": e.relativa,
            "motivo": fallo_de(e) or e.motivo or str(e.vigencia),
            "intentado": fallo_de(e) is not None or e.relativa in run.procesos,
        }
        for e in sin_entregar
    ]

    # Los registros: una fila del índice por PDF entregado.
    documentos = filas = 0
    no_cuadran = []
    for entrega in entregas:
        if entrega.vigencia is not Vigencia.VIGENTE or entrega.constancia is None:
            continue
        pdfs = len(entrega.pdf_entregados)
        documentos += pdfs
        indice = entrega.constancia.indice
        if isinstance(indice, dict) and isinstance(indice.get("filas"), list):
            suyas = len(indice["filas"])
            filas += suyas
            if suyas != pdfs:
                no_cuadran.append(
                    {"pdf": entrega.relativa, "motivo": f"{suyas} filas en el índice y {pdfs} PDF entregados"}
                )

    entregados = len(entregas) - len(sin_entregar)
    # Las carpetas del origen que traen PDF, y cuántas los tienen todos
    # entregados: vale con cualquier forma del destino (plano, espejo, UPD).
    con_faltantes = {
        Path(e.relativa).parts[0] for e in sin_entregar if len(Path(e.relativa).parts) > 1
    }
    comparacion = {
        "entradas_origen": len(carpetas_origen) + len(archivos_origen),
        "carpetas_origen": len(carpetas_origen),
        "carpetas_destino": len(carpetas_destino),
        "carpetas_con_pdf": len(pdf_por_carpeta),
        "carpetas_completas": len(set(pdf_por_carpeta) - con_faltantes),
        "pdf_origen": len(entregas),
        "pdf_entregados": entregados,
        "documentos_entregados": documentos,
        "filas_del_indice": filas,
        "sin_pdf": sin_pdf[:DETALLE_MAXIMO],
        "archivos_en_la_raiz": archivos_en_la_raiz[:DETALLE_MAXIMO],
        "sobran": sobran[:DETALLE_MAXIMO],
        "faltan": faltan[:DETALLE_MAXIMO],
        "pdf_sin_entregar": pdf_sin_entregar[:DETALLE_MAXIMO],
        "registros_que_no_cuadran": no_cuadran[:DETALLE_MAXIMO],
        "completa": not sin_entregar and not no_cuadran,
    }
    return comparacion, entregas


def auditar_la_muestra(
    runner,
    run,
    entregas: list[EntregaVista],
    *,
    semilla: int,
    juez=None,
    juez_de_datos=None,
    cuantos: int = TAMANO_DE_LA_MUESTRA,
    detener: Callable[[], bool] = lambda: False,
    avance=None,
    tiempo_maximo: float | None = None,
) -> dict:
    """100 PDF entregados al azar, abiertos y revisados; otros 100 si alguno salió con error.

    ``juez_de_datos`` es la IA que decide las fechas dudosas de sus PDF
    entregados (2026-11-10). No pregunta más allá del plazo de la auditoría
    (``tiempo_maximo``, el de la muestra de filas): pasado, lo dudoso se queda
    en duda y la muestra sigue -- la huella y los cortes no cuestan nada --.
    """
    import time

    from ..application.control import Cancelled

    if juez_de_datos is not None and hasattr(juez_de_datos, "hasta"):
        limite = time.monotonic() + (tiempo_maximo if tiempo_maximo is not None else _tiempo_de_la_muestra())
        juez_de_datos.hasta(lambda: time.monotonic() > limite)
    por_relativa = {
        e.relativa: e
        for e in entregas
        if e.vigencia is Vigencia.VIGENTE and e.constancia is not None and e.base is not None and e.pdf_entregados
    }
    indices: dict[Path, tuple[int | None, int | None]] = {}

    def auditar(relativa: str) -> PdfAuditado:
        # Con su habilidad aunque no se deje auditar: cuenta en la suya.
        habilidad = por_relativa[relativa].constancia.habilidad or ""
        if detener():
            return PdfAuditado(
                relativa, NO_AUDITADO, ("la corrida se detuvo antes de auditarlo",), habilidad=habilidad
            )
        try:
            return _auditar_uno(por_relativa[relativa], juez, indices, juez_de_datos=juez_de_datos)
        except Cancelled:
            # «Detener» mientras se le preguntaba a la IA: no se audita, no es un fallo.
            return PdfAuditado(relativa, NO_AUDITADO, ("la corrida se detuvo",), habilidad=habilidad)
        except Exception as error:  # noqa: BLE001 - un PDF que no se deja auditar se dice
            logger.warning("no se pudo auditar %s", relativa, exc_info=True)
            return PdfAuditado(relativa, NO_AUDITADO, (f"no se pudo auditar: {error}",), habilidad=habilidad)

    resultados: list[PdfAuditado] = []

    def ronda(elegidos: list[str]) -> None:
        with ThreadPoolExecutor(max_workers=AUDITAR_A_LA_VEZ) as hilos:
            for resultado in hilos.map(auditar, elegidos):
                resultados.append(resultado)
                if avance is not None:
                    avance(len(resultados), resultado)

    def medir():
        cuentas = Counter(r.estado for r in resultados)
        revisados = len(resultados) - cuentas.get(NO_AUDITADO, 0)
        # El de toda la corrida, contra el más estricto de las habilidades que
        # trae: el que se acepta en una no tapa el de otra.
        aceptable = min(
            (margen_aceptable(r.habilidad) for r in resultados if r.estado != NO_AUDITADO),
            default=margen_aceptable(),
        )
        return cuentas, revisados, margen_de_error(cuentas.get(ERROR, 0), revisados, aceptable=aceptable)

    primera = elegir_la_muestra(list(por_relativa), cuantos, semilla)
    ronda(primera)
    ampliada = False
    _, _, margen = medir()
    if margen.errores and margen.dictamen != DENTRO_DEL_MARGEN and not detener():
        # La muestra encontró errores y no alcanza para asegurar que la corrida
        # esté dentro del margen: otros 100 para medir cuánto afectan (lo eligió
        # el operador).
        segunda = elegir_la_muestra(list(por_relativa), cuantos, semilla + 1, excluir=primera)
        if segunda:
            ampliada = True
            ronda(segunda)

    cuentas, revisados, margen = medir()
    return {
        "semilla": semilla,
        "candidatos": len(por_relativa),
        "revisados": revisados,
        "bien": cuentas.get(BIEN, 0),
        "errores": cuentas.get(ERROR, 0),
        "dudosos": cuentas.get(DUDOSO, 0),
        "no_auditados": cuentas.get(NO_AUDITADO, 0),
        "ampliada": ampliada,
        "margen": margen.as_dict(),
        "por_habilidad": margenes_por_habilidad(resultados),
        "fechas": resumen_de_las_fechas(resultados),
        "preguntadas_a_la_ia": sum(r.preguntadas_a_la_ia for r in resultados),
        "pdfs": [r.as_dict() for r in resultados],
    }


def _auditar_uno(entrega: EntregaVista, juez, indices: dict, *, juez_de_datos=None) -> PdfAuditado:
    """Abre el original y lo que se entregó de él, y los audita.

    Las filas que el PDF aportó al inventario van con él (2026-11-10): con ellas
    se auditan las fechas de cada PDF entregado contra sus hojas.
    """
    assert entrega.constancia is not None and entrega.base is not None
    temporal = None
    try:
        origen = entrega.path
        if red_smb.por_smb(origen):
            # Del servidor, a un temporal: sólo para leer su huella y su capa.
            temporal = Path(tempfile.mkdtemp(prefix="auditoria-"))
            origen = red_smb.traer(str(entrega.path), temporal / entrega.path.name)
        huellas, textos = huellas_y_textos(origen)
    finally:
        if temporal is not None:
            shutil.rmtree(temporal, ignore_errors=True)

    entregados: dict[str, list | None] = {}
    for ruta in entrega.pdf_entregados:
        destino = constancias.ruta_de_entrega(entrega.base, ruta)
        try:
            entregados[ruta] = huellas_de(destino) if destino is not None else None
        except Exception:  # noqa: BLE001 - el PDF que no se abre es el hallazgo
            entregados[ruta] = None

    if entrega.base not in indices:
        indices[entrega.base] = _filas_y_pdf_de(entrega.base)
    filas, pdfs = indices[entrega.base]
    # El FUID entregado en su carpeta, para las habilidades que esperan datos
    # de cada documento (2026-11-06): una vez por carpeta.
    del_fuid = None
    if perfil_de(entrega.constancia.habilidad).datos is not None:
        clave = ("fuid", entrega.base)
        if clave not in indices:
            indices[clave] = _filas_del_fuid_de(entrega.base)
        del_fuid = indices[clave]
    return auditar_un_pdf(
        entrega.relativa,
        huellas,
        textos,
        entregados,
        habilidad=entrega.constancia.habilidad,
        juez=juez,
        filas_del_indice=filas,
        pdf_en_su_carpeta=pdfs,
        filas_del_fuid=del_fuid,
        # Cómo quedó al procesar cada casilla que el agente buscó otra vez, de
        # las filas que guarda la constancia (2026-11-06).
        verificados={
            str(fila.get("archivo_generado")): dict(fila.get("verificado") or {})
            for fila in entrega.constancia.actas or []
            if fila.get("archivo_generado") and fila.get("verificado")
        },
        tipos={
            str(fila.get("archivo_generado")): tipo
            for fila in entrega.constancia.actas or []
            if fila.get("archivo_generado") and (tipo := _tipo_de_identificacion(fila))
        },
        filas_de_la_constancia=[fila for fila in entrega.constancia.actas or [] if isinstance(fila, dict)]
        # Kingspan no deja filas en la constancia: sus puntas, del inventario
        # que se entregó, contra todo el original (2026-11-10).
        + _filas_de_kingspan(entrega, len(huellas)),
        juez_de_datos=juez_de_datos,
        # Ni la caja de correspondencia: su Índice Electrónico (2026-11-10).
        filas_del_indice_electronico=_filas_del_indice_electronico(entrega, indices),
        # Lo que la IA o el sello leyeron para fechar y la capa no trae (2026-11-11).
        lo_leido=entrega.constancia.lo_leido,
    )


def _filas_del_indice_electronico(entrega: EntregaVista, indices: dict) -> list[dict]:
    """Las filas del Índice Electrónico de un PDF: las de su constancia, o las del índice que se entregó con él.

    En la carpeta de un NIC la constancia guarda las de su UPD (``indice``);
    entregado aparte, el índice va entre sus archivos. El que se lee se guarda
    en ``indices`` (una vez por archivo). Sin índice, ninguna.
    """
    constancia = entrega.constancia
    if constancia is None:
        return []
    if isinstance(constancia.indice, dict):
        return [fila for fila in constancia.indice.get("filas") or [] if isinstance(fila, dict)]
    for archivo in constancia.archivos:
        ruta = str(archivo.get("ruta") or "")
        nombre = Path(ruta.replace("\\", "/")).name
        if not (nombre.upper().startswith("00.INDICE ELECTRONICO") and nombre.lower().endswith(".xlsx")):
            continue
        destino = constancias.ruta_de_entrega(entrega.base, ruta) if entrega.base is not None else None
        if destino is None:
            return []
        clave = ("indice", destino)
        if clave not in indices:
            try:
                leido = leer_indice(destino)
                indices[clave] = [
                    {
                        "nombre": fila.nombre,
                        "fecha_creacion": fila.fecha_creacion.isoformat() if fila.fecha_creacion else None,
                        "paginas": fila.paginas,
                    }
                    for fila in leido.filas
                ]
            except Exception:  # noqa: BLE001 - un índice que no se lee deja sus fechas sin auditar
                logger.warning("no se pudo leer el índice %s para auditar sus fechas", destino, exc_info=True)
                indices[clave] = []
        return indices[clave]
    return []


#: Las columnas del inventario de Kingspan que dicen sus puntas (``celdas_kingspan``):
#: el asunto (J), el DESDE (K), el HASTA (L) y sus fechas (M y N).
_ASUNTO, _DESDE, _HASTA, _INICIAL, _FINAL = 9, 10, 11, 12, 13


def es_de_kingspan(entrega: EntregaVista) -> bool:
    """Si lo que se entregó de un PDF es un inventario de Kingspan."""
    from .worker.kingspan import INVENTORY_SUFFIX

    return entrega.constancia is not None and any(
        str(archivo.get("ruta") or "").upper().endswith(INVENTORY_SUFFIX.upper())
        for archivo in entrega.constancia.archivos
    )


def _filas_de_kingspan(entrega: EntregaVista, paginas: int | None) -> list[dict]:
    """Las puntas del inventario de Kingspan de un PDF, cada una una fecha contra todo el original (2026-11-10).

    Kingspan no deja filas en la constancia: su inventario es el Excel que se
    entregó, una fila por paquete con el DESDE y el HASTA y la fecha de cada
    uno. Al procesar se revisa **cada punta como el documento que es**; aquí,
    contra todo el original -- la regla de los extremos: la fecha propia de
    alguna de sus hojas --, porque el Excel no dice en qué hoja va cada una.
    Por separado: la final puede ser anterior a la inicial (el oficial trae 65
    filas así) y no es un error. La fila sin documentos numerados va entera:
    sus fechas son las puntas de todo el archivo. Un inventario que no se deja
    leer no da ninguna.
    """
    from ..application.auditoria_de_la_entrega import DE_TODO_EL_ORIGINAL
    from .worker.kingspan import INVENTORY_SUFFIX, _filas_escritas

    if entrega.constancia is None or entrega.base is None:
        return []
    filas: list[dict] = []
    for archivo in entrega.constancia.archivos:
        ruta = str(archivo.get("ruta") or "")
        if not ruta.upper().endswith(INVENTORY_SUFFIX.upper()):
            continue
        destino = constancias.ruta_de_entrega(entrega.base, ruta)
        try:
            valores = _filas_escritas(destino) if destino is not None else []
        except Exception:  # noqa: BLE001 - un inventario que no se lee deja sus fechas sin auditar
            logger.warning("no se pudo leer el inventario %s para auditar sus fechas", destino, exc_info=True)
            continue
        for fila in valores:
            fila = list(fila) + [None] * max(0, _FINAL + 1 - len(fila))
            asunto = str(fila[_ASUNTO] or "").strip()
            # «punta» y no «nombre»: con «nombre» la fila pasaba por la de una
            # persona y se buscaba el asunto como un nombre en el papel.
            comun = {
                DE_TODO_EL_ORIGINAL: True,
                "pagina_inicial": 1,
                "pagina_final": paginas or 10**6,
                "archivo": entrega.path.name,
            }
            if not (_dicho(fila[_DESDE]) or _dicho(fila[_HASTA])):
                # Sin documentos numerados la fila va de punta a punta del
                # archivo (``_sin_numeros``): sus dos fechas son la más antigua
                # y la más reciente de todo él, como las de un archivo entero.
                if _dicho(fila[_INICIAL]) or _dicho(fila[_FINAL]):
                    filas.append(
                        {
                            **comun,
                            "punta": asunto or "sin documentos numerados",
                            "fecha_inicial": fila[_INICIAL] if _dicho(fila[_INICIAL]) else None,
                            "fecha_final": fila[_FINAL] if _dicho(fila[_FINAL]) else None,
                        }
                    )
                continue
            for codigo, fecha in dict.fromkeys(((fila[_DESDE], fila[_INICIAL]), (fila[_HASTA], fila[_FINAL]))):
                if _dicho(fecha):
                    punta = " · ".join(str(p) for p in (asunto, codigo) if _dicho(p))
                    filas.append(
                        {**comun, "punta": punta, "su_numero": codigo, "fecha_inicial": fecha, "fecha_final": fecha}
                    )
    return filas


def _dicho(valor: object) -> bool:
    """Si una celda del inventario dice algo: ni vacía ni «N/A»."""
    return valor not in (None, "") and str(valor).strip().upper() != "N/A"


def _tipo_de_identificacion(fila: dict) -> str | None:
    """Si la identificación de una fila de la constancia es una cédula, una tarjeta o una libreta."""
    from ..domain.historia_academica import Ficha

    identificacion = Ficha(
        cedula=fila.get("cedula") or None, tarjeta=fila.get("tarjeta") or None, libreta=fila.get("libreta") or None
    ).identificacion
    return identificacion[0] if identificacion else None


def _filas_del_fuid_de(carpeta: Path) -> list | None:
    """Las filas del FUID entregado en una carpeta -- o en la de encima --; ``None`` si no hay o no se deja leer."""
    from ..adapters.fuid_reader import filas_de_fuid
    from .retomar import fuid_del_libro

    for donde in (carpeta, carpeta.parent):
        if (ruta := fuid_del_libro(donde)) is not None:
            try:
                return filas_de_fuid(ruta)[0]
            except Exception:  # noqa: BLE001 - un FUID que no se deja leer es como no tenerlo
                logger.warning("no se pudo leer el FUID %s para auditar", ruta, exc_info=True)
                return None
    return None


def _filas_y_pdf_de(carpeta: Path) -> tuple[int | None, int | None]:
    """Las filas del Índice Electrónico de una carpeta y los PDF que hay en ella; nada si no tiene índice."""
    indice = carpeta / NOMBRE_DEL_INDICE
    try:
        if not indice.exists():
            return None, None
        filas = len(leer_indice(indice).filas)
        _, archivos = _listar(carpeta)
    except Exception:  # noqa: BLE001 - un índice que no se lee no se compara
        logger.warning("no se pudo leer el índice de %s", carpeta, exc_info=True)
        return None, None
    pdfs = sum(1 for nombre in archivos if nombre.lower().endswith(".pdf") and not nombre.startswith("."))
    return filas, pdfs


def etapa_de(comparacion: dict | None, muestra: dict | None) -> tuple[str, str]:
    """Cómo termina la corrida, y el detalle de lo que hay que saber."""
    partes = []
    if comparacion:
        vacias = sum(1 for c in comparacion["sin_pdf"] if c["motivo"] == "carpeta totalmente vacía")
        sin_pdf = len(comparacion["sin_pdf"]) - vacias
        if vacias:
            partes.append(f"{vacias} carpetas vacías")
        if sin_pdf:
            partes.append(f"{sin_pdf} sin PDF")
        if comparacion["archivos_en_la_raiz"]:
            partes.append(f"{len(comparacion['archivos_en_la_raiz'])} archivos sueltos en la raíz")
        if comparacion["sobran"]:
            partes.append(f"{len(comparacion['sobran'])} carpetas de más en el destino")
        if comparacion["pdf_sin_entregar"]:
            partes.append(f"faltan {len(comparacion['pdf_sin_entregar'])} PDF")
        if comparacion["registros_que_no_cuadran"]:
            partes.append(f"{len(comparacion['registros_que_no_cuadran'])} índices que no cuadran")
    margen = (muestra or {}).get("margen") or {}
    # La habilidad que se sale de su margen aunque la corrida entera no: sus
    # errores no se diluyen en los aciertos de las demás.
    fuera = [
        h["habilidad"]
        for h in (muestra or {}).get("por_habilidad") or []
        if (h.get("margen") or {}).get("dictamen") == FUERA_DEL_MARGEN
    ]
    if muestra and muestra.get("revisados"):
        de_filas = " filas" if muestra.get("unidad") == UNIDAD_FILAS else ""
        partes.append(f"muestra: {muestra['bien']} de {muestra['revisados']}{de_filas} bien")
        if margen.get("texto_del_dictamen"):
            partes.append(str(margen["texto_del_dictamen"]).split(":")[0].lower())
        if fuera:
            partes.append("fuera de su margen: " + ", ".join(fuera))
    # Sólo en la muestra de filas: la de PDF termina como siempre -- lo fija la
    # especificación del operador del 2026-10-28 (test_comprobar_la_entrega) --.
    de_filas = bool(muestra) and muestra.get("unidad") == UNIDAD_FILAS
    if de_filas and not muestra.get("revisados") and muestra.get("candidatos"):
        partes.append(f"muestra: ninguna de {muestra['candidatos']} se pudo auditar")
    detalle = " · ".join(partes)
    if comparacion and not comparacion["completa"]:
        return "Terminado con faltantes", detalle
    if margen.get("dictamen") == FUERA_DEL_MARGEN or fuera:
        return "Terminado: error fuera del margen", detalle
    if muestra and muestra.get("errores"):
        if margen.get("dictamen") == DENTRO_DEL_MARGEN:
            return "Terminado: errores dentro del margen", detalle
        return "Terminado con errores en la muestra", detalle
    # Una muestra que no se pudo auditar, o que quedó en dudas que pueden sacar
    # el error del margen, no es «Terminado» sin más: se avisa (la segunda
    # revisión, 2026-11-09: el plazo agotado o un PDF que no abre cerraban así).
    if de_filas and not muestra.get("revisados") and muestra.get("candidatos"):
        return "Terminado: muestra sin auditar", detalle
    if de_filas and muestra.get("dudosos") and margen.get("dictamen") == SIN_CERTEZA:
        return "Terminado con dudas en la muestra", detalle
    return "Terminado", detalle


# -- la muestra de filas del inventario (2026-11-09) ---------------------------------------

#: De qué es la muestra: de PDF cortados o de filas del inventario.
UNIDAD_PDF = "pdf"
UNIDAD_FILAS = "filas"
#: Cuántas páginas sin capa de texto de una fila se leen con Tesseract, las
#: primeras: el encabezado del acta con su número, su fecha y su sesión; la
#: ficha. Gratis, pero no instantáneo: con libros escaneados sin capa, doce por
#: fila eran 2.400 páginas en una muestra de 200 (el operador, 2026-11-09:
#: «que todo esté optimizado y el flujo no se trabe»).
OCR_POR_FILA = 6
#: Cuánto puede durar la muestra de filas, en segundos: lo que falte al
#: acabarse queda «no auditado» -- no cuenta para el margen -- y la corrida
#: termina igual. ``BOTPDF_TIEMPO_DE_LA_AUDITORIA`` lo cambia. Medido en
#: Odontología (227 filas, capa de texto): 20 s sin IA.
TIEMPO_DE_LA_MUESTRA = 600.0


def _tiempo_de_la_muestra() -> float:
    try:
        return max(30.0, float(os.environ.get("BOTPDF_TIEMPO_DE_LA_AUDITORIA", TIEMPO_DE_LA_MUESTRA)))
    except ValueError:
        return TIEMPO_DE_LA_MUESTRA
#: Lo mínimo que tiene que traer la capa de una página para no leerla con Tesseract.
CAPA_MINIMA = 80
#: Cuántas filas se leen a la vez: Tesseract va en su propio proceso y el
#: servicio, al cerrar la corrida, ya no tiene documentos en curso.
FILAS_A_LA_VEZ = max(2, min(8, (os.cpu_count() or 4) // 2))


#: La fila candidata que es todo el inventario de Kingspan de un PDF.
_DE_KINGSPAN = "inventario_de_kingspan"


def filas_candidatas(entregas: list[EntregaVista]) -> dict[str, tuple[EntregaVista, dict]]:
    """Las filas del inventario de las entregas vigentes, cada una con su nombre en la muestra.

    Salen de la constancia de cada PDF -- las filas que aportó, con sus páginas
    del original --, no del Excel: el FUID no dice de qué páginas salió cada fila.
    """
    from ..application.auditoria_de_la_entrega import DE_TODO_EL_ORIGINAL
    from ..domain.auditoria_de_filas import id_de_la_fila, paginas_de_la_fila

    candidatas: dict[str, tuple[EntregaVista, dict]] = {}
    for entrega in entregas:
        if entrega.vigencia is not Vigencia.VIGENTE or entrega.constancia is None:
            continue
        if not entrega.constancia.actas and es_de_kingspan(entrega):
            # Kingspan no deja filas en la constancia (2026-11-10): su
            # inventario -- una fila por paquete -- se lee al auditarlo, contra
            # todo el original. Se elige como una fila; abrir aquí el Excel de
            # cada UPD de la corrida sería leer mil para auditar cien.
            paginas = int((entrega.constancia.proceso or {}).get("paginas") or 0)
            fila = {
                _DE_KINGSPAN: True,
                DE_TODO_EL_ORIGINAL: True,
                "pagina_inicial": 1,
                "pagina_final": paginas or 10**6,
                "archivo": entrega.path.name,
            }
            candidatas[f"{entrega.relativa} · inventario de Kingspan"] = (entrega, fila)
            continue
        for indice, fila in enumerate(entrega.constancia.actas or []):
            if not isinstance(fila, dict) or paginas_de_la_fila(fila) is None:
                continue
            nombre = id_de_la_fila(entrega.relativa, fila)
            if nombre in candidatas:
                nombre = f"{nombre} #{indice + 1}"
            candidatas[nombre] = (entrega, fila)
    return candidatas


def auditar_las_filas(
    runner,
    run,
    entregas: list[EntregaVista],
    *,
    semilla: int,
    juez=None,
    cuantos: int = TAMANO_DE_LA_MUESTRA,
    detener: Callable[[], bool] = lambda: False,
    avance=None,
    leer_textos: Callable[[Path, list[tuple[int, int]]], list[tuple[list[str], int]]] | None = None,
    tiempo_maximo: float | None = None,
) -> dict:
    """100 filas del inventario al azar, cada una contra sus páginas; otras 100 si alguna salió con error.

    Es la muestra de una corrida que no corta PDF -- «Solo inventario» --: lo
    que entrega son filas. Mismo contrato que ``auditar_la_muestra`` -- semilla,
    Wilson, el margen de cada habilidad --, con ``"unidad": "filas"``.
    """
    import time

    from ..application.auditoria_de_filas import auditar_una_fila, ventana_de_la_auditoria
    from ..application.control import Cancelled
    from ..domain.auditoria_de_filas import paginas_de_la_fila

    candidatas = filas_candidatas(entregas)
    plazo = tiempo_maximo if tiempo_maximo is not None else _tiempo_de_la_muestra()
    limite = time.monotonic() + plazo

    def agotado() -> bool:
        return time.monotonic() > limite

    duracion = f"{plazo / 60:.0f} min" if plazo >= 120 else f"{plazo:.0f} s"
    agotado_dicho = f"se acabó el tiempo de la auditoría ({duracion})"
    # La IA tampoco se pasa del plazo: no pide ni reintenta después de él.
    if juez is not None and hasattr(juez, "hasta"):
        juez.hasta(agotado)

    resultados: list[PdfAuditado] = []
    # El original de la red se baja una sola vez, aunque lo pidan varias filas
    # a la vez: un cerrojo por PDF. Si no baja, no se vuelve a intentar fila a
    # fila -- veinte filas eran veinte intentos de 5 s, en serie --, y su
    # temporal se borra cuando termina su última fila, no al final: doscientos
    # PDF de 100 MB llenaban el disco de Docker (la segunda revisión, 2026-11-09).
    locales: dict[Path, Path | BaseException] = {}
    temporales: dict[Path, Path] = {}
    pendientes: Counter[Path] = Counter()
    cerrojos: dict[Path, threading.Lock] = {}
    cerrojo_de_los_cerrojos = threading.Lock()

    def seguir() -> bool:
        return not (detener() or agotado())

    def local(origen: Path) -> Path:
        if not red_smb.por_smb(origen):
            return origen
        with cerrojo_de_los_cerrojos:
            cerrojo = cerrojos.setdefault(origen, threading.Lock())
        with cerrojo:
            if origen not in locales:
                if not seguir():
                    raise TimeoutError("la auditoría ya no baja más PDF")
                temporal = Path(tempfile.mkdtemp(prefix="auditoria-filas-"))
                temporales[origen] = temporal
                try:
                    locales[origen] = red_smb.traer(str(origen), temporal / origen.name)
                except Exception as error:  # noqa: BLE001 - el fallo se recuerda para las demás filas
                    locales[origen] = error
            guardado = locales[origen]
            if isinstance(guardado, BaseException):
                raise guardado
            return guardado

    def terminada(origen: Path) -> None:
        """Una fila menos de ese PDF; con la última, su temporal se borra."""
        with cerrojo_de_los_cerrojos:
            pendientes[origen] -= 1
            temporal = temporales.pop(origen, None) if pendientes[origen] <= 0 else None
        if temporal is not None:
            shutil.rmtree(temporal, ignore_errors=True)

    def una(nombre: str) -> PdfAuditado:
        """Una fila: sus páginas leídas y auditadas, en su propio hilo."""
        try:
            return _una(nombre)
        finally:
            terminada(candidatas[nombre][0].path)

    def _una(nombre: str) -> PdfAuditado:
        entrega, fila = candidatas[nombre]
        habilidad = (entrega.constancia.habilidad if entrega.constancia else "") or ""
        if detener():
            return PdfAuditado(nombre, NO_AUDITADO, ("la corrida se detuvo antes de auditarla",), habilidad=habilidad)
        if agotado():
            return PdfAuditado(nombre, NO_AUDITADO, (agotado_dicho,), habilidad=habilidad)
        tramo = paginas_de_la_fila(fila) or (1, 1)
        try:
            if leer_textos is not None:
                ((paginas, sin_texto),) = leer_textos(entrega.path, [tramo])
                saltadas = 0
            else:
                paginas, sin_texto, saltadas = _texto_de_una_fila(runner, local(entrega.path), tramo, seguir=seguir)
        except Exception as error:  # noqa: BLE001 - un original que no se abre se dice
            logger.warning("no se pudo abrir %s para auditar sus filas", entrega.relativa, exc_info=True)
            return PdfAuditado(nombre, NO_AUDITADO, (f"no se pudo abrir su PDF: {error}",), habilidad=habilidad)
        if saltadas:
            # Las páginas sin capa que ya no se leyeron por el tiempo o por
            # «Detener»: la fila no se leyó entera, así que no se audita.
            motivo = "la corrida se detuvo antes de auditarla" if detener() else agotado_dicho
            return PdfAuditado(nombre, NO_AUDITADO, (motivo,), habilidad=habilidad)
        # Los años de su libro, del nombre de su PDF: la misma ventana que en la
        # muestra de PDF (2026-11-10).
        ventana = ventana_de_la_auditoria(habilidad, entrega.relativa)
        try:
            # Con el tiempo acabado, la regla sí -- es inmediata -- pero no la
            # IA: lo dudoso se queda en duda y la muestra cierra.
            if fila.get(_DE_KINGSPAN):
                return _auditar_el_inventario_de_kingspan(
                    nombre, entrega, paginas, habilidad=habilidad, juez=None if agotado() else juez,
                    sin_texto=sin_texto, ventana=ventana,
                )
            return auditar_una_fila(
                nombre,
                fila,
                paginas,
                habilidad=habilidad,
                juez=None if agotado() else juez,
                sin_texto=sin_texto,
                paginas_pedidas=tramo,
                ventana=ventana,
            )
        except Cancelled:
            return PdfAuditado(nombre, NO_AUDITADO, ("la corrida se detuvo",), habilidad=habilidad)
        except Exception as error:  # noqa: BLE001 - una fila que no se deja auditar se dice
            logger.warning("no se pudo auditar la fila %s", nombre, exc_info=True)
            return PdfAuditado(nombre, NO_AUDITADO, (f"no se pudo auditar: {error}",), habilidad=habilidad)

    def ronda(elegidas: list[str]) -> None:
        """Las filas elegidas, varias a la vez, con el avance contado fila a fila según terminan.

        Por fila y no por PDF: con las cien filas de un mismo libro escaneado,
        un hilo por PDF las leía todas en fila y la pantalla se quedaba en «0
        de 100» hasta el final (la revisión, 2026-11-09).
        """
        hechas: dict[str, PdfAuditado] = {}
        with cerrojo_de_los_cerrojos:
            pendientes.update(candidatas[nombre][0].path for nombre in elegidas)
        with ThreadPoolExecutor(max_workers=FILAS_A_LA_VEZ) as hilos:
            futuros = {hilos.submit(una, nombre): nombre for nombre in elegidas}
            for futuro in as_completed(futuros):
                resultado = futuro.result()
                hechas[futuros[futuro]] = resultado
                if avance is not None:
                    avance(len(resultados) + len(hechas), resultado)
        resultados.extend(hechas[nombre] for nombre in elegidas)

    def medir():
        cuentas = Counter(r.estado for r in resultados)
        revisados = len(resultados) - cuentas.get(NO_AUDITADO, 0)
        # Contra el más estricto de las habilidades de la muestra: el margen
        # que se acepta en una no tapa el de otra.
        aceptable = min(
            (margen_aceptable(r.habilidad) for r in resultados if r.estado != NO_AUDITADO),
            default=margen_aceptable(),
        )
        # Las dudas sin decidir cuentan en el peor caso: cien dudas no son
        # «dentro del margen» porque no haya errores (la revisión, 2026-11-09).
        return cuentas, revisados, margen_de_error(
            cuentas.get(ERROR, 0), revisados, aceptable=aceptable, dudosos=cuentas.get(DUDOSO, 0), unidad="fila"
        )

    try:
        primera = elegir_la_muestra(list(candidatas), cuantos, semilla)
        ronda(primera)
        ampliada = False
        _, _, margen = medir()
        if margen.errores and margen.dictamen != DENTRO_DEL_MARGEN and not detener() and not agotado():
            # Con errores y sin poder asegurar que la corrida esté dentro del
            # margen: otras 100, sin repetir (lo eligió el operador, 2026-11-05).
            segunda = elegir_la_muestra(list(candidatas), cuantos, semilla + 1, excluir=primera)
            if segunda:
                antes = len(resultados)
                ronda(segunda)
                # Ampliada si de verdad se revisó algo más: con el tiempo
                # acabado, la segunda ronda puede quedar entera sin auditar.
                ampliada = any(r.estado != NO_AUDITADO for r in resultados[antes:])
    finally:
        for temporal in list(temporales.values()):
            shutil.rmtree(temporal, ignore_errors=True)

    cuentas, revisados, margen = medir()
    return {
        "unidad": UNIDAD_FILAS,
        "semilla": semilla,
        "candidatos": len(candidatas),
        "revisados": revisados,
        "bien": cuentas.get(BIEN, 0),
        "errores": cuentas.get(ERROR, 0),
        "dudosos": cuentas.get(DUDOSO, 0),
        "no_auditados": cuentas.get(NO_AUDITADO, 0),
        "ampliada": ampliada,
        "margen": margen.as_dict(),
        "por_habilidad": margenes_por_habilidad(resultados, con_dudas=True),
        "fechas": resumen_de_las_fechas(resultados),
        "preguntadas_a_la_ia": sum(r.preguntadas_a_la_ia for r in resultados),
        "pdfs": [r.as_dict() for r in resultados],
    }


def _auditar_el_inventario_de_kingspan(
    nombre: str,
    entrega: EntregaVista,
    textos: list[str],
    *,
    habilidad: str,
    juez=None,
    sin_texto: int = 0,
    ventana: tuple[int, int] | None = None,
) -> PdfAuditado:
    """Las puntas del inventario de Kingspan de un PDF, cada una contra sus hojas, dichas como una fila (2026-11-10).

    Cada punta se audita por su lado (``_filas_de_kingspan``) contra las hojas
    que traen su número (``hojas_de_la_punta``), o todo el original si ninguna
    lo trae, y se juntan: el estado más grave, sus hallazgos y cuántas fechas
    quedaron en cada estado.
    """
    from ..application.auditoria_de_filas import auditar_una_fila
    from ..application.auditoria_de_la_entrega import hojas_de_la_punta

    puntas = _filas_de_kingspan(entrega, len(textos))
    if not puntas:
        return PdfAuditado(
            nombre, NO_AUDITADO, ("su inventario no trae fechas que auditar",), paginas=len(textos), habilidad=habilidad
        )
    por_hoja = dict(enumerate(textos, start=1))
    resultados = []
    for punta in puntas:
        suyas = list(hojas_de_la_punta(punta, por_hoja, (1, len(textos))))
        resultados.append(
            auditar_una_fila(
                f"{nombre} · {punta['punta']}",
                punta,
                suyas,
                habilidad=habilidad,
                juez=juez,
                # Las de sus hojas, no las de todo el original.
                sin_texto=sin_texto if len(suyas) == len(textos) else sum(len(t.strip()) < CAPA_MINIMA for t in suyas),
                ventana=ventana,
            )
        )
    auditadas = [r for r in resultados if r.estado != NO_AUDITADO]
    if not auditadas:
        return PdfAuditado(nombre, NO_AUDITADO, resultados[0].hallazgos, paginas=len(textos), habilidad=habilidad)
    estados = {r.estado for r in auditadas}
    fechas: Counter[str] = Counter()
    for resultado in auditadas:
        fechas.update(resultado.extra.get("fechas") or {})
    return PdfAuditado(
        pdf=nombre,
        estado=ERROR if ERROR in estados else DUDOSO if DUDOSO in estados else BIEN,
        hallazgos=tuple(
            f"«{punta['punta']}»: {hallazgo}"
            for punta, resultado in zip(puntas, resultados, strict=True)
            if resultado.estado != NO_AUDITADO
            for hallazgo in resultado.hallazgos
        ),
        paginas=len(textos),
        preguntadas_a_la_ia=sum(r.preguntadas_a_la_ia for r in auditadas),
        habilidad=habilidad,
        extra={"fechas": dict(fechas)},
    )


def _capa_util(texto: str) -> bool:
    """Si la capa de texto de una página se puede leer: con las letras suficientes y palabras de verdad.

    La capa del escáner sobre letra a mano son a veces ochenta caracteres de
    basura («Ii,~ lI' ¡¡ :'.»), y con sólo contarlos no se releía con Tesseract
    (la revisión, 2026-11-09: 50 de 60 historias de Enfermería, dudosas).
    """
    if len(texto.strip()) < CAPA_MINIMA:
        return False
    fichas = re.findall(r"\S+", texto)
    palabras = [f for f in fichas if re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}[.,;:]?", f) and re.search(r"[AEIOUaeiouÁÉÍÓÚáéíóú]", f)]
    return len(palabras) >= 8 and len(palabras) >= 0.35 * len(fichas)


def _texto_de_una_fila(
    runner, origen: Path, tramo: tuple[int, int], *, seguir: Callable[[], bool] = lambda: True
) -> tuple[list[str], int, int]:
    """El texto de las páginas de una fila, cuántas quedaron sin texto y cuántas sin leer por el tiempo.

    La capa de texto primero, que es gratis y es lo que leyó la corrida. Las
    páginas sin capa útil -- escaneadas, o con basura sobre letra a mano -- se
    leen con Tesseract, gratis también, y sólo las ``OCR_POR_FILA`` primeras:
    nunca el OCR de pago. Cada fila abre el original por su cuenta -- abrirlo es
    inmediato -- y así varias se leen a la vez.
    """
    from ..adapters.pymupdf_source import PyMuPDFPageSource
    from ..adapters.tesseract_ocr import HeaderAndPageOcr

    desde, hasta = tramo
    textos: list[str] = []
    sin_texto = saltadas = leidas_con_ocr = 0
    ocr = None
    with PyMuPDFPageSource(Path(origen)) as fuente:
        total = fuente.page_count
        for pagina in range(max(1, desde), min(hasta, total) + 1):
            texto = fuente.text_of(pagina) or ""
            if not _capa_util(texto) and leidas_con_ocr < OCR_POR_FILA:
                if not seguir():
                    saltadas += 1
                else:
                    leidas_con_ocr += 1
                    try:
                        if ocr is None:
                            ocr = HeaderAndPageOcr(language=getattr(runner._settings, "ocr_language", "spa"))
                        leido = ocr.read(fuente.render(pagina, None, dpi=200)).text or ""
                        texto = f"{texto}\n{leido}" if texto.strip() else leido
                    except Exception:  # noqa: BLE001 - una página que Tesseract no lee se cuenta
                        logger.debug("Tesseract no leyó la página %s de %s", pagina, origen, exc_info=True)
            if len(texto.strip()) < CAPA_MINIMA:
                sin_texto += 1
            textos.append(texto)
    return textos, sin_texto, saltadas
