"""Inventariar actas de consejo: una fila por acta, con su número, su fecha, sus folios y su resumen.

No se parte nada: el PDF queda como llegó. Lo que sale son filas de un
inventario sencillo -- no el FUID --, con las columnas que el operador pidió:
la carpeta, el archivo, las páginas, el acta («ACTA ORDINARIA No. 022»), su
fecha («Lunes 17 de diciembre de 2012»), el folio inicial y el final, cuántos
folios son y un resumen de lo que se trató.

Un PDF puede traer un acta -- los de la carpeta UPD3859771 -- o un libro entero
de ellas -- los de UPD3859772 a UPD3859778, con doce a sesenta actas cada uno
--. `actas_del_pdf` decide cuáles son y qué páginas lleva cada una, y aquí se
lee cada una por separado: un acta es una fila, la traiga sola o encuadernada.

Cada cosa se lee con lo más barato que la sabe leer:

* el acta y la fecha están impresas, y salen de la capa de texto del escaneo o
  de Tesseract, gratis;
* qué hojas están foliadas se sabe contando tinta en la esquina, sin leer, y
  de ahí sale el número de folios;
* el folio está **escrito a mano** y Tesseract no lo lee -- sobre el acta de
  ejemplo acertó una esquina de veintiuna --, así que lo lee el OCR de pago,
  pero sólo la esquina de la primera hoja foliada y la de la última de cada
  acta, apiladas en una imagen: una página facturada por acta;
* el resumen lo escribe un modelo de lenguaje a partir del **texto que ya sacó
  el OCR de casa**, nunca de la imagen, limpio de membretes, de ruido y del
  llamado a lista, que el operador pidió no ver.

En un libro, las lecturas de pago de sus actas van varias a la vez: son esperas
al proveedor, y una tras otra harían de un libro de sesenta actas diez minutos.

Sin la ayuda de pago -- «Solo OCR», o sin llave -- se inventaría igual: el acta,
la fecha y el número de folios salen del papel, y las observaciones dicen qué
faltó y por qué.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from ..domain.acta_consejo import (
    BANDA_DEL_FOLIO,
    TRAZO_DE_FOLIO,
    ActaDeConsejo,
    ActasDelPdf,
    FoliosDelActa,
    TramoDeActa,
    actas_del_pdf,
    depurar_resumen,
    folios_del_libro,
    folios_por_continuidad,
    folios_que_cuadran,
    leer_acta,
    numeros_escritos,
    renglones_repetidos,
    texto_para_resumir,
)
from ..domain.grouping import GroupingResult, PageGroup
from ..domain.piezas_de_acta import (
    PORTADA,
    SIN_SESION,
    PiezaDeActa,
    piezas_de_la_sesion,
    resumen_de_piezas,
)
from ..domain.resolution_code import ResolutionCode
from .control import NullRunControl, RunControl
from .inventory_file import MIN_CHARS
from .ports import (
    Band,
    DocumentAssembler,
    LectorDeEsquinas,
    OcrEngine,
    PageSource,
    ResumenNoDisponible,
    Resumidor,
)
from .progress import NullProgressReporter, ProgressEvent, ProgressReporter, Stage

logger = logging.getLogger(__name__)

#: Cómo llama el archivo a lo que entra por aquí. Es lo que sale en la columna
#: de tipo de la pantalla de Archivo, junto a los demás documentos del sistema.
TIPO_DOCUMENTAL = "ACTA DE CONSEJO"

#: A qué resolución se pasa por OCR una página sin capa de texto. La misma que
#: usa `inventory_file`: el acta es mecanografiada y a 200 ppp se lee entera.
DPI_DE_LECTURA = 200

#: Lo que se escribe en una celda cuyo dato no se pudo leer. Nunca en blanco:
#: una celda vacía no dice si no había dato o si alguien se olvidó de ponerlo.
NO_APLICA = "N/A"

#: Lo que se dice cuando el folio no se pudo leer porque no se pidió la IA.
SIN_IA_PARA_EL_FOLIO = "el folio está escrito a mano y sólo se lee con «OCR + IA»"

#: Lo que dice la cabecera del Excel de una corrida leída sin la ayuda de pago,
#: una sola vez en vez de en cada fila.
SIN_IA = "Leído con «Solo OCR»: el folio manuscrito y el resumen se leen con «OCR + IA»"

#: Cuántas lecturas de pago van a la vez en un libro: folios y resúmenes de
#: varias actas. Cuatro mantienen el ritmo sin que el proveedor pida esperar.
LECTURAS_A_LA_VEZ = 4


@dataclass(frozen=True, slots=True)
class FilaDeActa:
    """Una fila del inventario de actas: lo que el operador pidió ver de cada acta."""

    archivo: str
    #: «ACTA ORDINARIA No. 022».
    acta: str
    #: Día-mes-año de la sesión: «17-12-2012».
    fecha: str
    folio_inicial: int | str
    folio_final: int | str
    #: Cuántos folios tiene: del primero al último leídos, o las hojas que
    #: llevan folio en la esquina si el número no se leyó.
    folios: int
    resumen: str
    #: Lo que no se pudo leer y por qué. Vacío cuando todo salió.
    observaciones: str = ""
    #: La carpeta de la que salió el PDF: la UPD, cuando una corrida recorre una
    #: caja con varias.
    carpeta: str = ""
    #: Qué páginas del PDF son esta acta. En un acta suelta, todas.
    pagina_inicial: int = 1
    pagina_final: int = 1
    #: El número del acta solo, para ordenar y buscar: «022».
    numero: str = ""
    #: Las piezas de la sesión con sus páginas: «Portada p. 42 · Citación p. 43
    #: · Registro de asistencia p. 44 · Acta pp. 46-48 · Resolución pp. 49-50».
    #: Es lo que deja ir de la fila al papel sin abrir el PDF entero.
    piezas: str = ""
    #: Qué se hizo con ella: «Dividido en 03_ACTA-….pdf», «Ya era un acta:
    #: inventariada sin dividir» o «Inventariado». Vacío en informes viejos.
    resultado: str = ""


@dataclass(slots=True)
class ActaOutcome:
    """Lo que se averiguó de un PDF, y la fila de cada una de sus actas."""

    document: str
    page_count: int
    filas: list[FilaDeActa]
    #: La primera acta, que en un PDF de un acta es la única.
    acta: ActaDeConsejo
    folios: FoliosDelActa
    reparto: ActasDelPdf
    resumen: str | None = None
    sin_resumen: str | None = None
    ocr_pages: int = 0
    unreadable: list[int] = field(default_factory=list)
    #: Cómo se reparte el PDF para dividirlo: un PDF por sesión, con sus piezas
    #: anotadas, y delante las páginas que no son de ninguna, si las hay.
    sesiones: list[SesionDeActa] = field(default_factory=list)

    @property
    def fila(self) -> FilaDeActa:
        """La primera fila; en un PDF de un acta, la única."""
        return self.filas[0]

    @property
    def incidents(self) -> list[str]:
        """Lo que hay que advertirle a quien revise, en su idioma."""
        avisos = [
            f"{fila.acta}: {fila.observaciones}" if self.reparto.es_libro else fila.observaciones
            for fila in self.filas
            if fila.observaciones
        ]
        return avisos

    def as_dict(self) -> dict[str, object]:
        fecha = self.acta.fecha.strftime("%d-%m-%Y") if self.acta.fecha else NO_APLICA
        libro = self.reparto.es_libro
        return {
            "document": self.document,
            "page_count": self.page_count,
            "records": len(self.filas),
            # Lo que lee la pantalla de Archivo de un archivo inventariado
            # entero: el asunto, el tipo, la fecha y el número. De un libro, cuántas
            # actas trae y de cuál a cuál.
            "asunto": (
                f"LIBRO DE {len(self.filas)} ACTAS: {self.filas[0].acta} a {self.filas[-1].acta}"
                if libro
                else self.acta.asunto
            ),
            "tipo_documental": TIPO_DOCUMENTAL,
            "fecha_inicial": fecha,
            "fecha_final": fecha,
            "consecutivo_inicial": self.acta.numero or NO_APLICA,
            "consecutivo_final": self.acta.numero or NO_APLICA,
            # Las páginas del PDF, que es lo que el libro mayor cuenta como
            # páginas. Los folios del archivo van aparte.
            "folios": self.page_count,
            "folio_inicial": self.folios.inicial,
            "folio_final": self.folios.final,
            "cantidad_folios": self.fila.folios,
            "paginas_foliadas": self.folios.foliadas,
            "actas": len(self.filas),
            "ocr_pages": self.ocr_pages,
            "unreadable_pages": list(self.unreadable),
            "incidents": self.incidents,
            "acta": {
                "numero": self.acta.numero,
                "sesion": self.acta.sesion,
                "fecha": self.acta.fecha.isoformat() if self.acta.fecha else None,
                "fecha_larga": self.acta.fecha_larga,
                "pagina": self.acta.pagina,
            },
            "resumen": self.resumen,
            "sin_resumen": self.sin_resumen,
            # Las filas, para que quien recorre una carpeta las junte en un solo
            # inventario sin volver a leer ninguna.
            "inventario_actas": [asdict(fila) for fila in self.filas],
            # Las piezas de cada sesión, con sus páginas: lo que se escribe al
            # dividir, y lo que la pantalla enseña aunque sólo se inventaríe.
            "sesiones": [sesion.as_dict() for sesion in self.sesiones],
        }


@dataclass(frozen=True, slots=True)
class SesionDeActa:
    """Una sesión del libro: el PDF en que se entrega y las piezas que lleva dentro."""

    #: El orden en el libro, que va delante del nombre del archivo.
    orden: int
    #: «ACTA EXTRAORDINARIA No. 017 - 16-08-2012».
    nombre: str
    piezas: tuple[PiezaDeActa, ...]

    @property
    def desde(self) -> int:
        return self.piezas[0].desde

    @property
    def hasta(self) -> int:
        return self.piezas[-1].hasta

    def as_dict(self) -> dict[str, object]:
        return {
            "orden": self.orden,
            "nombre": self.nombre,
            "desde": self.desde,
            "hasta": self.hasta,
            "piezas": [
                {"tipo": pieza.tipo, "nombre": pieza.nombre, "desde": pieza.desde, "hasta": pieza.hasta}
                for pieza in self.piezas
            ],
        }


#: Lo que Windows no admite en el nombre de una carpeta.
_NO_VALE_EN_UNA_CARPETA = re.compile(r'[<>:"/\\|?*]+')


def nombre_de_la_sesion(fila: FilaDeActa) -> str:
    """«ACTA EXTRAORDINARIA No. 017 - 16-08-2012»: el acta y su fecha.

    Es lo que lleva el PDF de la sesión detrás de su número de orden, y es por
    lo que se busca.
    """
    partes = [fila.acta if fila.acta != NO_APLICA else "ACTA SIN NUMERO"]
    if fila.fecha != NO_APLICA:
        partes.append(fila.fecha)
    return _NO_VALE_EN_UNA_CARPETA.sub("-", " - ".join(partes)).strip(" .")


#: Lo que va delante de la primera sesión: portada del libro, cartas de
#: remisión. No es de ninguna sesión y no se mete en ninguna; sale aparte.
PAGINAS_PREVIAS = "PAGINAS PREVIAS"


@dataclass(slots=True)
class DivisionDeActas:
    """Lo que se escribió al dividir: rutas relativas a la carpeta del trabajo."""

    salidas: list[str] = field(default_factory=list)
    ilegibles: dict[int, str] = field(default_factory=dict)


def dividir_actas(
    outcome: ActaOutcome,
    *,
    assembler: DocumentAssembler,
    source: Path,
    destino: Path,
    raiz: Path,
) -> DivisionDeActas:
    """Un PDF por sesión, con todo lo suyo dentro.

    Es el corte que pidió el operador: un libro sale en tantas sesiones como
    traiga, cada una con su portada, su citación, su asistencia, su acta y sus
    anexos, y nombrada por el acta y su fecha, ambas leídas del propio papel:
    ``03_ACTA-EXTRAORDINARIA-NO-017-16-08-2012.pdf``, con el orden del libro
    delante para que la carpeta se liste como venía. Las piezas no se parten:
    quedan anotadas con sus páginas en la fila del inventario.

    ``destino`` es la carpeta del PDF de origen dentro del trabajo, y ``raiz`` la
    del trabajo: las salidas se anotan relativas a ella, que es como las sirve
    la descarga. Ninguna hoja se queda fuera ni se repite: se comprobó al
    repartir, antes de llegar aquí.
    """
    reparto = GroupingResult(
        groups=[
            PageGroup(
                code=ResolutionCode(value=f"{sesion.orden:02d}", raw=f"{sesion.orden:02d}"),
                page_numbers=list(range(sesion.desde, sesion.hasta + 1)),
                kind=sesion.nombre,
            )
            for sesion in outcome.sesiones
        ]
    )
    escrito = assembler.write(source, reparto, destino)
    return DivisionDeActas(
        salidas=[ruta.relative_to(raiz).as_posix() for ruta in escrito.outputs],
        ilegibles=dict(escrito.unwritable_pages),
    )


YA_ERA_UN_ACTA = "Ya era un acta: inventariada sin dividir"
SOLO_INVENTARIADA = "Inventariada"


def resultado_de_cada_acta(
    filas: Sequence[FilaDeActa], salidas: Sequence[str] | None, *, pidio_dividir: bool
) -> list[FilaDeActa]:
    """Las filas con lo que se hizo con cada acta escrito en su columna.

    De un libro dividido, el PDF en que quedó cada acta: la fila N es el PDF
    que empieza por «NN_», el orden del libro. De un PDF que ya era un acta y se
    pidió dividir, que no hizo falta. Y si sólo se pidió inventariar, eso.
    """
    resultados: list[FilaDeActa] = []
    for orden, fila in enumerate(filas, start=1):
        if salidas:
            prefijo = f"{orden:02d}_"
            pdf = next((ruta.rsplit("/", 1)[-1] for ruta in salidas if ruta.rsplit("/", 1)[-1].startswith(prefijo)), None)
            texto = f"Dividido en {pdf}" if pdf else "Dividido: su PDF no se pudo escribir"
        elif pidio_dividir:
            texto = YA_ERA_UN_ACTA
        else:
            texto = SOLO_INVENTARIADA
        resultados.append(replace(fila, resultado=texto))
    return resultados


def _comprobar_que_cubre(sesiones: Sequence[SesionDeActa], total: int) -> None:
    """Cada página del PDF en exactamente una pieza, o se para antes de escribir."""
    vistas = sorted(pagina for sesion in sesiones for pieza in sesion.piezas for pagina in pieza.paginas)
    if vistas != list(range(1, total + 1)):
        raise ValueError(
            "el reparto en piezas no cubre el PDF entero una sola vez: "
            f"{len(vistas)} páginas repartidas de {total}"
        )


@dataclass(slots=True)
class _Lectura:
    """Lo que se averiguó de un acta antes de volverse fila."""

    tramo: TramoDeActa
    acta: ActaDeConsejo
    foliadas: list[int]
    folios: FoliosDelActa = field(default_factory=FoliosDelActa)
    resumen: str | None = None
    sin_resumen: str | None = None
    deducido: str | None = None
    piezas: list[PiezaDeActa] = field(default_factory=list)
    #: Los números leídos en las esquinas, aunque no cuadraran: en un libro,
    #: la mitad buena de una lectura la confirma el acta vecina.
    numeros: list[int] = field(default_factory=list)


class InventariarActa:
    """Lee un PDF de actas de punta a punta y devuelve la fila de cada una."""

    def __init__(
        self,
        ocr: OcrEngine | None = None,
        resumidor: Resumidor | None = None,
        lector_de_folios: LectorDeEsquinas | None = None,
        progress: ProgressReporter | None = None,
        control: RunControl | None = None,
        workers: int = 4,
        #: Por qué no hay resumidor, cuando quien monta el trabajo lo sabe: «se
        #: leyó con Solo OCR» no es lo mismo que «falta la llave».
        motivo_sin_resumidor: str | None = None,
    ) -> None:
        self._ocr = ocr
        self._resumidor = resumidor
        self._lector_de_folios = lector_de_folios
        self._progress = progress or NullProgressReporter()
        self._control = control or NullRunControl()
        self._workers = max(1, workers)
        self._motivo_sin_resumidor = motivo_sin_resumidor

    def execute(
        self, source: PageSource, *, document_name: str, carpeta: str = ""
    ) -> ActaOutcome:
        total = source.page_count
        self._report(ProgressEvent(stage=Stage.OPENED, page_count=total))

        paginas, con_ocr, ilegibles = self._leer(source)
        reparto = actas_del_pdf(paginas)
        foliadas = _paginas_foliadas(source)
        if foliadas is None:
            # La fuente no sabe medir tinta: se dan por foliadas todas, que es
            # lo normal en estas actas -- cada hoja lleva su número -- y la
            # comprobación de los números sigue protegiendo de una lectura mala.
            foliadas = list(range(1, total + 1))

        lecturas = []
        for tramo in reparto.tramos:
            # Sólo texto ya leído: repartir en piezas no cuesta una lectura más.
            piezas = piezas_de_la_sesion(paginas[tramo.desde - 1 : tramo.hasta], tramo.desde)
            # La portada que separa una sesión de la anterior no se folia. Una
            # mota en su esquina la hacía pasar por foliada: el acta se contaba
            # con una hoja de más y su folio inicial se buscaba en una hoja que
            # no lo tiene, así que no se leía nada.
            portadas = {
                pagina for pieza in piezas if pieza.tipo == PORTADA for pagina in pieza.paginas
            }
            lecturas.append(
                _Lectura(
                    tramo=tramo,
                    acta=leer_acta(paginas[tramo.desde - 1 : tramo.hasta]),
                    foliadas=[
                        p for p in foliadas if tramo.desde <= p <= tramo.hasta and p not in portadas
                    ],
                    piezas=piezas,
                )
            )
        self._report(
            ProgressEvent(
                stage=Stage.IDENTIFYING,
                done=1,
                total=1,
                detail=(
                    f"libro de {len(lecturas)} actas"
                    if reparto.es_libro
                    else lecturas[0].acta.asunto
                ),
            )
        )

        self._leer_folios_y_resumenes(source, paginas, lecturas)
        if reparto.es_libro:
            _encadenar_folios(lecturas)
        _completar_por_continuidad(lecturas)

        self._report(
            ProgressEvent(
                stage=Stage.INVENTORYING,
                done=0,
                total=1,
                detail="anotando las actas en el inventario",
            )
        )
        filas = [
            _fila(
                lectura,
                archivo=document_name,
                carpeta=carpeta,
                ilegibles=[p for p in ilegibles if lectura.tramo.desde <= p <= lectura.tramo.hasta],
                previas=reparto.previas if indice == 0 else None,
                por_eleccion=self._motivo_sin_resumidor,
            )
            for indice, lectura in enumerate(lecturas)
        ]
        sesiones = [
            SesionDeActa(orden, nombre_de_la_sesion(fila), tuple(lectura.piezas))
            for orden, (lectura, fila) in enumerate(zip(lecturas, filas, strict=True), start=1)
        ]
        if reparto.previas:
            desde, hasta = reparto.previas
            sesiones.insert(
                0, SesionDeActa(0, PAGINAS_PREVIAS, (PiezaDeActa(SIN_SESION, desde, hasta),))
            )
        _comprobar_que_cubre(sesiones, total)

        primera = lecturas[0]
        return ActaOutcome(
            document=document_name,
            page_count=total,
            filas=filas,
            acta=primera.acta,
            folios=primera.folios,
            reparto=reparto,
            resumen=primera.resumen,
            sin_resumen=primera.sin_resumen,
            ocr_pages=con_ocr,
            unreadable=ilegibles,
            sesiones=sesiones,
        )

    # -- leer -----------------------------------------------------------------

    def _leer(self, source: PageSource) -> tuple[list[str], int, list[int]]:
        """El texto de cada página: de su capa si la tiene, del OCR si no.

        La página entera y todas las páginas: el resumen es del acta entera, y
        lo que se trató va de la primera hoja a la última. Las que piden OCR se
        rasterizan aquí, en este hilo -- MuPDF no admite más de uno --, y se
        leen en paralelo, que es lo que tarda: Tesseract es un proceso aparte y
        ocho a la vez son ocho veces más rápido. En tandas, para no tener
        rasterizado un libro entero esperando.
        """
        total = source.page_count
        textos: list[str] = [""] * total
        con_ocr = 0
        leidas = 0

        with ThreadPoolExecutor(max_workers=self._workers) as lectores:
            tanda: dict[int, Future] = {}
            for numero in range(1, total + 1):
                self._control.check()
                texto = self._capa(source, numero)
                textos[numero - 1] = texto
                if len(texto.strip()) < MIN_CHARS and self._ocr is not None:
                    try:
                        imagen = source.render(numero, None, DPI_DE_LECTURA)
                        tanda[numero] = lectores.submit(self._ocr.read, imagen)
                    except Exception:  # noqa: BLE001 - una página no tumba el acta
                        logger.warning("no se pudo rasterizar la página %s", numero, exc_info=True)
                        leidas += 1
                        self._pagina(leidas, total, numero, "none", fallo="no se pudo rasterizar")
                else:
                    leidas += 1
                    self._pagina(
                        leidas, total, numero, "text_layer" if texto.strip() else "none"
                    )

                if len(tanda) >= self._workers * 2 or numero == total:
                    for pagina, futuro in sorted(tanda.items()):
                        con_ocr += 1
                        fallo = None
                        try:
                            leido = futuro.result().text
                        except Exception:  # noqa: BLE001 - se anota y se sigue
                            logger.warning("no se pudo pasar por OCR la página %s", pagina, exc_info=True)
                            leido = ""
                            fallo = "falló el OCR de la página"
                        # Lo que diera la capa se conserva junto a lo del OCR:
                        # a veces una trae el número y el otro la fecha.
                        textos[pagina - 1] = f"{textos[pagina - 1]}\n{leido}".strip()
                        leidas += 1
                        self._pagina(leidas, total, pagina, "ocr_full_page", fallo=fallo)
                    tanda.clear()

        ilegibles = [numero for numero, texto in enumerate(textos, start=1) if not texto.strip()]
        return textos, con_ocr, ilegibles

    @staticmethod
    def _capa(source: PageSource, numero: int) -> str:
        try:
            return source.text_of(numero)
        except Exception:  # noqa: BLE001 - una página ilegible no tumba el acta
            logger.debug("no se pudo leer la capa de texto de la página %s", numero, exc_info=True)
            return ""

    def _pagina(
        self,
        hechas: int,
        total: int,
        numero: int,
        procedencia: str,
        *,
        fallo: str | None = None,
    ) -> None:
        """Avisa de una página leída, diciendo de dónde salió su texto.

        Sin la procedencia, la pantalla toma la página por ilegible y la pinta
        «enviada a revisión»: así salían todas las páginas de todas las actas,
        leídas o no. Una cara en blanco que pasó por el OCR no es una página
        por revisar, es el reverso de una hoja; sólo lo es la que no se pudo
        rasterizar o leer.
        """
        self._report(
            ProgressEvent(
                stage=Stage.PAGE,
                done=hechas,
                total=total,
                page_number=numero,
                provenance=procedencia,
                failed=fallo is not None,
                detail=fallo,
            )
        )

    # -- folios y resúmenes ---------------------------------------------------

    def _leer_folios_y_resumenes(
        self, source: PageSource, paginas: list[str], lecturas: list[_Lectura]
    ) -> None:
        """El folio y el resumen de cada acta, con las lecturas de pago a la vez.

        Lo que toca el PDF -- recortar las esquinas -- se hace aquí, en orden;
        lo que es esperar al proveedor va en paralelo. Un acta sin folio
        escrito, o leída sin IA, no gasta nada.
        """
        repetidos = renglones_repetidos(paginas)
        total = len(lecturas)
        hechas = 0
        with ThreadPoolExecutor(max_workers=LECTURAS_A_LA_VEZ) as proveedor:
            pendientes: list[tuple[_Lectura, str, Future]] = []
            for lectura in lecturas:
                self._control.check()
                lectura.folios, futuro = self._pedir_folio(source, lectura, proveedor)
                if futuro is not None:
                    pendientes.append((lectura, "folio", futuro))
                texto = texto_para_resumir(
                    paginas[lectura.tramo.desde - 1 : lectura.tramo.hasta], repetidos=repetidos
                )
                if self._resumidor is None:
                    lectura.sin_resumen = self._motivo_sin_resumidor or "no se pidió a la IA"
                elif not texto:
                    lectura.sin_resumen = "el acta no trae texto legible que resumir"
                else:
                    pendientes.append(
                        (lectura, "resumen", proveedor.submit(self._resumidor.resumir, texto))
                    )

            for lectura, que, futuro in pendientes:
                self._control.check()
                if que == "folio":
                    lectura.folios = self._folios_leidos(lectura, futuro)
                else:
                    lectura.resumen, lectura.sin_resumen = _resumen_de(futuro)
                hechas += 1
                self._report(
                    ProgressEvent(
                        stage=Stage.INVENTORYING,
                        done=min(hechas, len(pendientes)),
                        total=len(pendientes),
                        detail=f"leyendo folios y resúmenes de {total} acta(s)",
                    )
                )

    def _pedir_folio(
        self, source: PageSource, lectura: _Lectura, proveedor: ThreadPoolExecutor
    ) -> tuple[FoliosDelActa, Future | None]:
        """Lo que se sabe del folio sin leer, y la lectura pedida si hace falta."""
        foliadas = lectura.foliadas
        if not foliadas:
            return FoliosDelActa(motivo="ninguna hoja lleva folio escrito en la esquina"), None
        if self._lector_de_folios is None:
            return FoliosDelActa(foliadas=len(foliadas), motivo=SIN_IA_PARA_EL_FOLIO), None

        primera, ultima = foliadas[0], foliadas[-1]
        esquinas = [primera] if primera == ultima else [primera, ultima]
        base = FoliosDelActa(foliadas=len(foliadas))
        armar = getattr(self._lector_de_folios, "armar_mosaico", None)
        leer = getattr(self._lector_de_folios, "leer_mosaico", None)
        try:
            if armar is not None and leer is not None:
                imagen = armar(source, esquinas)
                if not imagen:
                    return replace(base, motivo="no se pudo recortar la esquina del folio"), None
                return base, proveedor.submit(leer, imagen)
            # Un lector que sólo sabe leer de una vez: en este hilo, en orden.
            texto = self._lector_de_folios.leer_esquinas(source, esquinas)
            hecho: Future = Future()
            hecho.set_result(texto)
            return base, hecho
        except Exception:  # noqa: BLE001 - sin folio, el acta se inventaría igual
            logger.warning("no se pudo leer la esquina del folio", exc_info=True)
            return replace(base, motivo="falló la lectura del folio"), None

    @staticmethod
    def _folios_leidos(lectura: _Lectura, futuro: Future) -> FoliosDelActa:
        """El par de folios que cuadra con las hojas foliadas, o el motivo de que no."""
        foliadas = lectura.foliadas
        try:
            texto = futuro.result()
        except Exception:  # noqa: BLE001 - sin folio, el acta se inventaría igual
            logger.warning("no se pudo leer la esquina del folio", exc_info=True)
            return FoliosDelActa(foliadas=len(foliadas), motivo="falló la lectura del folio")
        numeros = numeros_escritos(texto)
        lectura.numeros = numeros
        par = folios_que_cuadran(numeros, len(foliadas))
        if par is None:
            leido = ", ".join(str(numero) for numero in numeros) or "ningún número"
            return FoliosDelActa(
                foliadas=len(foliadas),
                motivo=(
                    f"en las esquinas de las hojas {foliadas[0]} y {foliadas[-1]} se leyó "
                    f"{leido}, que no cuadra con las {len(foliadas)} hojas foliadas"
                ),
            )
        return FoliosDelActa(inicial=par[0], final=par[1], foliadas=len(foliadas))

    def _report(self, event: ProgressEvent) -> None:
        try:
            self._progress.emit(event)
        except Exception:  # noqa: BLE001 - la telemetría nunca rompe el trabajo
            logger.debug("no se pudo informar del progreso", exc_info=True)


def _resumen_de(futuro: Future) -> tuple[str | None, str | None]:
    """El resumen ya escrito y depurado, o por qué no lo hay."""
    try:
        resumen = depurar_resumen(futuro.result())
    except ResumenNoDisponible as error:
        return None, str(error)
    except Exception as error:  # noqa: BLE001 - sin resumen, el acta se inventaría igual
        logger.warning("no se pudo escribir el resumen del acta", exc_info=True)
        return None, f"falló el resumen ({type(error).__name__})"
    if not resumen:
        return None, "la IA no devolvió un resumen utilizable"
    return resumen, None


def _encadenar_folios(lecturas: list[_Lectura]) -> None:
    """Los folios de un libro, cuadrados acta con acta por la foliación seguida.

    Cada frontera entre dos actas se lee dos veces -- el final de una, el
    principio de la siguiente --, y donde coinciden es segura. Lo que no se leyó
    o se leyó mal se deduce contando hojas desde la frontera segura más cercana,
    y esa acta lo dice en sus observaciones para que alguien lo mire.
    """
    cadena = folios_del_libro([(lectura.numeros, len(lectura.foliadas)) for lectura in lecturas])
    if cadena is None:
        return
    for lectura, folio in zip(lecturas, cadena, strict=True):
        if (lectura.folios.inicial, lectura.folios.final) == (folio.inicial, folio.final):
            continue
        leido = ", ".join(str(numero) for numero in lectura.numeros) or "ningún número"
        lectura.folios = FoliosDelActa(
            inicial=folio.inicial, final=folio.final, foliadas=len(lectura.foliadas)
        )
        lectura.deducido = (
            _AJUSTADO if folio.leido else _ENCADENADO
        ).format(leido=leido)


def _completar_por_continuidad(lecturas: list[_Lectura]) -> None:
    """Los folios de las actas de un libro que no se leyeron, deducidos de las vecinas."""
    if len(lecturas) < 2:
        return
    tramos = [
        (lectura.folios.inicial, lectura.folios.final, len(lectura.foliadas))
        for lectura in lecturas
    ]
    for indice, (inicial, final, deducido) in enumerate(folios_por_continuidad(tramos)):
        if not deducido:
            continue
        antes = next(t[1] for t in reversed(tramos[:indice]) if t[1] is not None)
        despues = next(t[0] for t in tramos[indice + 1 :] if t[0] is not None)
        lectura = lecturas[indice]
        lectura.folios = FoliosDelActa(inicial=inicial, final=final, foliadas=len(lectura.foliadas))
        lectura.deducido = _DEDUCIDO.format(antes=antes, despues=despues)


def _paginas_foliadas(source: PageSource) -> list[int] | None:
    """Las páginas con tinta en la esquina del folio, contando píxeles y sin leer.

    ``None`` cuando la fuente no sabe medir, que no es lo mismo que «ninguna
    está foliada»: quien pregunta decide qué hacer sin la medida.
    """
    medir = getattr(source, "ink_of", None)
    if medir is None:
        return None
    banda = Band(*BANDA_DEL_FOLIO)
    foliadas: list[int] = []
    for pagina in range(1, source.page_count + 1):
        try:
            trazo = medir(pagina, banda)
        except Exception:  # noqa: BLE001 - una esquina sin medir no es una sin folio
            logger.debug("no se pudo medir la esquina de la página %s", pagina)
            continue
        if trazo is not None and trazo[0] >= TRAZO_DE_FOLIO:
            foliadas.append(pagina)
    return foliadas


def _fila(
    lectura: _Lectura,
    *,
    archivo: str,
    carpeta: str,
    ilegibles: list[int],
    previas: tuple[int, int] | None,
    por_eleccion: str | None = None,
) -> FilaDeActa:
    """La fila del inventario de un acta.

    Lo que falta porque el operador eligió leer sin la ayuda de pago -- el
    folio manuscrito, el resumen -- no se anota en cada fila: no es una falta
    de esa acta sino de la corrida, y repetido en ciento setenta filas tapaba
    las observaciones que sí piden mirar el papel. Lo dice una vez la cabecera
    del Excel.
    """
    acta, folios, tramo = lectura.acta, lectura.folios, lectura.tramo
    sin_resumen = None if lectura.sin_resumen == por_eleccion else lectura.sin_resumen
    if folios.motivo == SIN_IA_PARA_EL_FOLIO:
        folios = replace(folios, motivo=None)
    avisos = _advertencias(acta, folios, ilegibles, sin_resumen)
    if lectura.deducido:
        avisos = [lectura.deducido, *[a for a in avisos if not a.startswith("sin folio inicial")]]
    if previas:
        avisos.insert(
            0,
            f"las páginas {previas[0]} a {previas[1]} del PDF van antes de la primera acta "
            "(portada, cartas): no son de ninguna",
        )
    return FilaDeActa(
        archivo=archivo,
        acta=acta.encabezado or NO_APLICA,
        # Día, mes y año: «25-10-2012». Es como lo pidió el operador para el
        # inventario, y como se ordena y se filtra en Excel sin traducir nada.
        fecha=acta.fecha.strftime("%d-%m-%Y") if acta.fecha else NO_APLICA,
        folio_inicial=folios.inicial if folios.inicial is not None else NO_APLICA,
        folio_final=folios.final if folios.final is not None else NO_APLICA,
        folios=folios.cantidad or folios.foliadas or tramo.paginas,
        resumen=lectura.resumen or NO_APLICA,
        observaciones="; ".join(avisos),
        carpeta=carpeta,
        pagina_inicial=tramo.desde,
        pagina_final=tramo.hasta,
        numero=acta.numero or "",
        piezas=resumen_de_piezas(lectura.piezas),
    )


def _advertencias(
    acta: ActaDeConsejo,
    folios: FoliosDelActa,
    ilegibles: list[int],
    sin_resumen: str | None,
) -> list[str]:
    avisos: list[str] = []
    if acta.numero is None:
        avisos.append("no se encontró el número del acta en su encabezado")
    if acta.fecha is None:
        avisos.append("no se encontró la fecha de la sesión")
    elif acta.dia_no_cuadra:
        avisos.append(
            f"el papel dice «{acta.dia_impreso}» y el {acta.fecha.strftime('%d-%m-%Y')} "
            "no cae en ese día: revise la fecha"
        )
    if folios.motivo:
        avisos.append(f"sin folio inicial y final: {folios.motivo}")
    if ilegibles:
        avisos.append(
            f"{len(ilegibles)} página(s) sin texto legible: "
            + ", ".join(str(numero) for numero in ilegibles[:10])
        )
    if sin_resumen:
        avisos.append(f"sin resumen: {sin_resumen}")
    return avisos


#: Lo que se escribe en observaciones de un acta cuyos folios se dedujeron.
_ENCADENADO = (
    "folios deducidos de la foliación seguida del libro: en la esquina se leyó "
    "{leido}, y se cuentan las hojas desde el acta vecina bien leída"
)
_AJUSTADO = (
    "folios ajustados a la foliación seguida del libro: en la esquina se leyó "
    "{leido}, y el acta vecina confirma el folio que sigue"
)

_DEDUCIDO = (
    "folios deducidos: la lectura de la esquina no cuadró, y las hojas de las actas "
    "sin leer llenan exacto el hueco entre el folio {antes} y el {despues}"
)


def inventario_de_la_carpeta(filas: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Las filas de las actas de una carpeta, en su orden y con los folios que se deducen.

    En el orden natural -- carpeta, archivo y página --: «1N°…», «2N°…», …,
    «10N°…», que es como se numeran las actas en la carpeta y como va su
    foliación; el orden de las rutas pondría la décima delante de la primera.

    Y con los folios que la lectura no dio pero la carpeta sí: cada carpeta va
    foliada seguida, así que un acta sin leer entre dos bien leídas ocupa el
    hueco que dejan, si sus hojas lo llenan exacto. La continuidad se busca
    dentro de cada carpeta y nunca de una a otra: cada UPD se folia aparte.
    """
    ordenadas = sorted((dict(fila) for fila in filas), key=_orden_natural)
    por_carpeta: dict[str, list[dict[str, object]]] = {}
    for fila in ordenadas:
        por_carpeta.setdefault(str(fila.get("carpeta") or ""), []).append(fila)
    for grupo in por_carpeta.values():
        _deducir_en(grupo)
    return ordenadas


def _deducir_en(filas: list[dict[str, object]]) -> None:
    tramos = [
        (
            _folio(fila.get("folio_inicial")),
            _folio(fila.get("folio_final")),
            int(fila.get("folios") or 0),
        )
        for fila in filas
    ]
    for indice, (inicial, final, deducido) in enumerate(folios_por_continuidad(tramos)):
        if not deducido:
            continue
        fila = filas[indice]
        antes = next(t[1] for t in reversed(tramos[:indice]) if t[1] is not None)
        despues = next(t[0] for t in tramos[indice + 1 :] if t[0] is not None)
        fila["folio_inicial"], fila["folio_final"] = inicial, final
        fila["folios"] = final - inicial + 1
        avisos = [
            aviso
            for aviso in str(fila.get("observaciones") or "").split("; ")
            if aviso and not aviso.startswith("sin folio inicial y final")
        ]
        fila["observaciones"] = "; ".join(
            [_DEDUCIDO.format(antes=antes, despues=despues), *avisos]
        )


def _folio(valor: object) -> int | None:
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def _orden_natural(fila: Mapping[str, object]) -> list[object]:
    """Por carpeta, archivo y página; los números del nombre como números."""
    clave: list[object] = []
    for campo in ("carpeta", "archivo"):
        clave.extend(
            (0, int(trozo)) if trozo.isdigit() else (1, trozo.lower())
            for trozo in re.split(r"(\d+)", str(fila.get(campo) or ""))
            if trozo
        )
        clave.append((2, ""))
    clave.append((0, int(fila.get("pagina_inicial") or 0)))
    return clave
