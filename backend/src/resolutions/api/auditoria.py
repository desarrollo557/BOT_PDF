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

Nunca reprocesa ni lee con OCR: el origen y lo entregado se abren para su huella
y su capa de texto. Lo que no se deja leer se dice; nada de esto tumba la corrida.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from ..adapters import red_smb
from ..adapters.huellas_pdf import huellas_de, huellas_y_textos
from ..adapters.indice_electronico import NOMBRE_DEL_INDICE, leer_indice
from ..application.auditoria_de_la_entrega import auditar_un_pdf
from ..domain.auditoria import (
    BIEN,
    DENTRO_DEL_MARGEN,
    DUDOSO,
    ERROR,
    FUERA_DEL_MARGEN,
    MARGEN_ACEPTABLE,
    NO_AUDITADO,
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


def margen_aceptable() -> float:
    """El error que se acepta en una corrida: ``BOTPDF_MARGEN_ACEPTABLE`` en por ciento, o el 5 %."""
    try:
        valor = float(os.environ.get("BOTPDF_MARGEN_ACEPTABLE", "").replace(",", ".")) / 100
    except ValueError:
        return MARGEN_ACEPTABLE
    return valor if 0 < valor < 1 else MARGEN_ACEPTABLE


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
    cuantos: int = TAMANO_DE_LA_MUESTRA,
    detener: Callable[[], bool] = lambda: False,
    avance=None,
) -> dict:
    """100 PDF entregados al azar, abiertos y revisados; otros 100 si alguno salió con error."""
    por_relativa = {
        e.relativa: e
        for e in entregas
        if e.vigencia is Vigencia.VIGENTE and e.constancia is not None and e.base is not None and e.pdf_entregados
    }
    indices: dict[Path, tuple[int | None, int | None]] = {}

    def auditar(relativa: str) -> PdfAuditado:
        if detener():
            return PdfAuditado(relativa, NO_AUDITADO, ("la corrida se detuvo antes de auditarlo",))
        try:
            return _auditar_uno(por_relativa[relativa], juez, indices)
        except Exception as error:  # noqa: BLE001 - un PDF que no se deja auditar se dice
            logger.warning("no se pudo auditar %s", relativa, exc_info=True)
            return PdfAuditado(relativa, NO_AUDITADO, (f"no se pudo auditar: {error}",))

    resultados: list[PdfAuditado] = []

    def ronda(elegidos: list[str]) -> None:
        with ThreadPoolExecutor(max_workers=AUDITAR_A_LA_VEZ) as hilos:
            for resultado in hilos.map(auditar, elegidos):
                resultados.append(resultado)
                if avance is not None:
                    avance(len(resultados), resultado)

    aceptable = margen_aceptable()

    def medir():
        cuentas = Counter(r.estado for r in resultados)
        revisados = len(resultados) - cuentas.get(NO_AUDITADO, 0)
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
        "pdfs": [r.as_dict() for r in resultados],
    }


def _auditar_uno(entrega: EntregaVista, juez, indices: dict) -> PdfAuditado:
    """Abre el original y lo que se entregó de él, y los audita."""
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
    return auditar_un_pdf(
        entrega.relativa,
        huellas,
        textos,
        entregados,
        habilidad=entrega.constancia.habilidad,
        juez=juez,
        filas_del_indice=filas,
        pdf_en_su_carpeta=pdfs,
    )


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
    if muestra and muestra.get("revisados"):
        partes.append(f"muestra: {muestra['bien']} de {muestra['revisados']} bien")
        if margen.get("texto_del_dictamen"):
            partes.append(str(margen["texto_del_dictamen"]).split(":")[0].lower())
    detalle = " · ".join(partes)
    if comparacion and not comparacion["completa"]:
        return "Terminado con faltantes", detalle
    if margen.get("dictamen") == FUERA_DEL_MARGEN:
        return "Terminado: error fuera del margen", detalle
    if muestra and muestra.get("errores"):
        if margen.get("dictamen") == DENTRO_DEL_MARGEN:
            return "Terminado: errores dentro del margen", detalle
        return "Terminado con errores en la muestra", detalle
    return "Terminado", detalle
