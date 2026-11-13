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

import difflib
import logging
import math
import re
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from functools import lru_cache
from pathlib import Path

from ..domain.acta_consejo import (
    BANDA_DEL_FOLIO,
    TRAZO_DE_FOLIO,
    ActaDeConsejo,
    ActasDelPdf,
    FoliosDelActa,
    TramoDeActa,
    acta_del_nombre,
    actas_del_pdf,
    depurar_resumen,
    fechas_fuera_de_lugar,
    foliacion_por_pagina,
    folio_de_la_pagina,
    folios_del_libro,
    folios_por_continuidad,
    folios_que_cuadran,
    leer_acta,
    numeros_del_nombre,
    numeros_escritos,
    renglones_repetidos,
    sin_actas_ajenas_al_nombre,
    sin_anexos_anteriores,
    texto_para_resumir,
)
from ..domain.acta_grado import (
    CORREGIDO,
    DEDUCIDO,
    ROTULO_DE_CEREMONIA,
    ActaDelLibro,
    GraduadoDelActa,
    acta_anulada,
    acta_sin_terminar,
    actas_de_grado_del_pdf,
    actas_del_libro_colectivo,
    asunto_del_graduado,
    completar_acta,
    con_la_franja,
    datos_de_la_ia,
    es_acta_abreviada,
    es_acta_colectiva,
    es_acta_de_examen,
    es_libro_de_actas_colectivas,
    es_un_titulo,
    estudiantes_declarados,
    fecha_de_grado,
    folio_del_texto,
    folios_de_la_foliacion,
    graduados_de_la_lista,
    juntar_graduados,
    le_falta_algo,
    lectura_colectiva_de_la_ia,
    lecturas_del_nombre,
    leer_acta_de_grado,
    mejor_lectura,
    nombre_de_tres_lecturas,
    numero_en_el_encabezado,
    numero_y_rango,
    numeros_de_los_graduados,
    orden_del_libro,
    paginas_compartidas,
    puestos_de_la_lista,
    rango_reparado,
    renglones_en_bucle,
    reparto_del_libro_colectivo,
    rotulo_del_acta_colectiva,
    sin_quien_firma,
    titulo_del_examen,
)
from ..domain.acta_grado import (
    FINAL as EXAMEN_FINAL,
)
from ..domain.acta_grado import (
    PREPARATORIO as EXAMEN_PREPARATORIO,
)
from ..domain.acta_grado import (
    ROTULO as ROTULO_DE_GRADO,
)
from ..domain.acta_grado import (
    SIN_DECIR as EXAMEN_SIN_DECIR,
)
from ..domain.doble_lectura import decidir_con_la_ia
from ..domain.fechas import fechas_de
from ..domain.formulario import recuadro_tras, texto_del_formulario
from ..domain.graduado import (
    VOCABULARIO_DE_LOS_TITULOS,
    dudas_de,
    firmantes_del_libro,
    nombre_con_la_cola_del_renglon,
    nombre_limpio,
    nombre_y_titulo_separados,
    sin_firmantes,
    titulo_del_vocabulario,
    titulo_limpio,
    titulos_unificados,
)
from ..domain.graduado import cedula as cedula_leida
from ..domain.grouping import GroupingResult, PageGroup
from ..domain.nombres import (
    calidad,
    clave,
    consenso,
    consenso_de_cedulas,
    palabras_de,
    parece_palabra_de_nombre,
    sin_perder_conocidas,
    zona_del_nombre,
)
from ..domain.orden_por_el_folio import tramos_seguidos
from ..domain.piezas_de_acta import (
    ACTA,
    ANEXO,
    PORTADA,
    SIN_SESION,
    PiezaDeActa,
    piezas_de_la_sesion,
    resumen_de_piezas,
)
from ..domain.razonamiento import (
    corregir_anio,
    igual_a_los_lados,
    mes_y_anio,
    mismo_numero,
    vecinas_de,
)
from ..domain.resolution_code import ResolutionCode
from .control import (
    ESPERA_ENTRE_CONSULTAS,
    NullRunControl,
    RunControl,
    aguardar,
    alguno_listo,
    completados,
    hilos,
)
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
TIPO_DE_GRADO = "ACTA DE GRADO"

#: A qué resolución se pasa por OCR una página sin capa de texto. La misma que
#: usa `inventory_file`: el acta es mecanografiada y a 200 ppp se lee entera.
DPI_DE_LECTURA = 200
#: A cuánto lee la IA un libro escrito a mano: la letra pide más que la máquina.
DPI_DEL_MANUSCRITO = 300
def _renglon(source: PageSource, pagina: int, banda: Band, dpi: int, girar: bool) -> bytes:
    """La banda de la página, girada media vuelta si ``girar``: la hoja escaneada de cabeza.

    Gira la fuente al rasterizar (``render_girada``): aquí no se toca la
    imagen, porque el núcleo no depende de librerías de imagen. Una fuente que
    no sabe girar da la banda como está.
    """
    if girar and (render_girada := getattr(source, "render_girada", None)) is not None:
        return render_girada(pagina, banda, dpi)
    return source.render(pagina, banda, dpi)


#: Y el renglón del nombre, solo y más grande, para la tercera lectura.
DPI_DEL_RENGLON_DEL_NOMBRE = 500
#: Las dos mitades en que se relee, con más zoom, la hoja que la IA leyó en
#: bucle (``renglones_en_bucle``): la hoja 80 de UPD3859802 (2026-11-13).
MITADES_DE_LA_HOJA = (Band(0.0, 0.0, 1.0, 0.5), Band(0.0, 0.5, 1.0, 1.0))
DPI_DE_LA_MITAD = 400
#: La franja del medio del acta a mano de 1988-2012, donde va el nombre (2026-11-13).
DPI_DE_LA_FRANJA_DEL_NOMBRE = 400
#: Cuánto se tienen que parecer los nombres de pila de dos lecturas para votarlos.
PARECIDO_DE_LOS_NOMBRES_DE_PILA = 0.75
#: Las palabras que deja en la capa cualquier acta impresa o a máquina.
_PALABRAS_DE_UN_ACTA_IMPRESA = (
    "UNIVERSIDAD", "CIUDAD", "CARTAGENA", "GRADO", "ACTA", "TITULO", "CEDULA", "PORTADOR", "ESTUDIANTE",
)
#: Un libro a máquina las trae en casi todas sus hojas; uno a mano, en sus
#: portadas impresas y nada más.
PARTE_IMPRESA_DE_UN_LIBRO_A_MAQUINA = 0.3
PAGINAS_PARA_JUZGAR_LA_LETRA = 5
#: A cuánto se rasteriza el recuadro de un dato: es pequeño, y las cifras a
#: máquina necesitan altura para que el OCR las distinga.
DPI_DE_RECUADRO = 400
#: Y la franja del graduado: la letra de máquina se lee bien a 300 ppp.
DPI_DE_LA_FRANJA = 300
#: Hasta dónde baja la franja si no se encuentra el renglón de la cédula.
FRANJA_POR_DEFECTO = 0.62


#: Cuántas imágenes se le pasan a Tesseract por arranque. Arrancarlo cuesta
#: 0,22 s, que es cargar el modelo del idioma; cuatro por arranque se lo
#: ahorran tres veces de cada cuatro sin dejar lectores sin trabajo.
IMAGENES_POR_LLAMADA = 4


def _lotes(elementos: list, lectores: int, por_llamada: int) -> list[list]:
    """Los elementos en lotes de hasta ``por_llamada``, sin dejar lectores parados.

    Con pocas páginas el lote se achica: cinco páginas en lotes de cuatro
    serían dos lectores trabajando y seis mirando.
    """
    if not elementos:
        return []
    tamano = max(1, min(por_llamada, math.ceil(len(elementos) / max(1, lectores))))
    return [elementos[i : i + tamano] for i in range(0, len(elementos), tamano)]


def _leer_lote(motor, imagenes: list[bytes], *, varias: str = "read_varias", una: str = "read"):
    """Las imágenes leídas en un arranque si el motor sabe; si no, o si el lote falla, de una en una.

    Devuelve, por imagen, ``(lectura, None)`` o ``(None, error)``: de una en una
    se sabe cuál era la que no se dejaba leer, y las demás no pierden su texto.
    """
    lote = getattr(motor, varias, None)
    if lote is not None and len(imagenes) > 1:
        try:
            return [(leida, None) for leida in lote(imagenes)]
        except Exception:  # noqa: BLE001 - se reintenta imagen por imagen
            logger.warning("un lote de OCR falló; se lee imagen por imagen", exc_info=True)
    leer = getattr(motor, una)
    salida = []
    for imagen in imagenes:
        try:
            salida.append((leer(imagen), None))
        except Exception as error:  # noqa: BLE001 - cuenta para esa imagen sola
            salida.append((None, error))
    return salida


def _resultados_del_lote(futuro: Future, cuantos: int) -> list:
    """Lo que devolvió un lote, o el mismo fallo para cada una si el hilo reventó."""
    try:
        return futuro.result()
    except Exception as error:  # noqa: BLE001 - se anota en cada página del lote
        return [(None, error)] * cuantos


def _franja_del_graduado(trozos, ancho: float, alto: float) -> Band:
    """La parte de la hoja del encabezado al renglón de la cédula, en fracciones."""
    abajo = [t.y1 for t in trozos if "ciudadan" in t.texto.lower()]
    hasta = (max(abajo) + 12) / alto if abajo and alto else FRANJA_POR_DEFECTO
    return Band(0.0, 0.0, 1.0, min(1.0, hasta + 0.02))

#: Lo que se escribe en una celda cuyo dato no se pudo leer. Nunca en blanco:
#: una celda vacía no dice si no había dato o si alguien se olvidó de ponerlo.
NO_APLICA = "N/A"

#: Lo que se dice cuando el folio no se pudo leer porque no se pidió la IA.
SIN_IA_PARA_EL_FOLIO = "el folio está escrito a mano y sólo se lee con «OCR + IA»"

#: Cuántas lecturas de pago van a la vez en un libro: folios y resúmenes de
#: varias actas. Cuatro mantienen el ritmo sin que el proveedor pida esperar.
LECTURAS_A_LA_VEZ = 4

#: Cuántas esquinas van en un mosaico de folios de grado: una página
#: facturada por cada diez graduados.
FOLIOS_POR_MOSAICO = 10


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
    #: «ACTA DE CONSEJO» o «ACTA DE GRADO».
    tipo: str = TIPO_DOCUMENTAL
    #: De un acta de grado, el graduado: lo que lleva su fila del FUID.
    nombre: str = ""
    titulo: str = ""
    cedula: str = ""
    #: El orden del PDF en que va la fila. Un acta colectiva da una fila por
    #: graduado, todas en el PDF de su acta (UPD3859802, 2026-11-12); 0 en los
    #: informes de antes, donde la fila N es el PDF N.
    sesion: int = 0
    #: De un acta colectiva, su rótulo -- «ACTA DE GRADO 05408120 A 05408124» --,
    #: que con la fecha nombra su PDF.
    acta_colectiva: str = ""
    #: En las filas de un acta colectiva que no son la primera: el graduado en
    #: cuya fila van los folios del acta. En el FUID, sus folios van en 0.
    folios_en: str = ""
    #: Las páginas de su PDF en su orden, cuando no son de ``pagina_inicial`` a
    #: ``pagina_final`` seguidas: el acta del libro colectivo que sigue en la
    #: hoja del folio siguiente, lejos en el escaneo -- «98, 2» --, o que lleva
    #: la hoja que comparte con la siguiente (UPD3859802, 2026-11-13).
    hojas_del_pdf: tuple[int, ...] = ()
    #: Las hojas de su PDF que van también en el de otra acta y se cuentan allí,
    #: en la que empieza en ella: la suma de los folios no las cuenta dos veces.
    hojas_contadas_en_otra: tuple[int, ...] = ()


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
    #: «ACTA DE CONSEJO» o «ACTA DE GRADO»: lo que va en la columna de tipo.
    tipo_documental: str = TIPO_DOCUMENTAL
    #: El texto de cada página, ya leído para el inventario: con él el agente
    #: revisor mira las costuras del libro sin leer nada más. No va al informe.
    textos: dict[int, str] = field(default_factory=dict, repr=False)
    #: Si es un libro de actas colectivas (UPD3859802): sus PDF llevan a varios
    #: graduados, y el revisor no cuenta dos cédulas como dos personas.
    colectivo: bool = False
    #: Las hojas que van en dos PDF: la que comparten el cierre de un acta y el
    #: comienzo de la siguiente (lo decidió el operador el 2026-11-13). La
    #: comprobación, la auditoría de cierre y retomar no las cuentan como error.
    paginas_compartidas: list[int] = field(default_factory=list)
    #: Las hojas que van en su PDF lejos de su vecina del escaneo porque el
    #: libro sigue por su folio impreso: su salto no es un error de corte.
    cruces_por_el_folio: list[int] = field(default_factory=list)

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
            "tipo_documental": self.tipo_documental,
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
            # Las hojas que van en dos PDF a propósito, y las que van lejos de su
            # vecina del escaneo por su folio: la constancia las guarda para la
            # auditoría de cierre y para retomar (2026-11-13).
            "paginas_compartidas": list(self.paginas_compartidas),
            "cruces_por_el_folio": list(self.cruces_por_el_folio),
        }


@dataclass(frozen=True, slots=True)
class SesionDeActa:
    """Una sesión del libro: el PDF en que se entrega y las piezas que lleva dentro."""

    #: El orden en el libro, que va delante del nombre del archivo.
    orden: int
    #: «ACTA EXTRAORDINARIA No. 017 - 16-08-2012».
    nombre: str
    piezas: tuple[PiezaDeActa, ...]
    #: Si el PDF lleva ``nombre`` tal cual, con sus espacios, y no en guiones: el
    #: del graduado se llama igual que su asunto en el FUID (2026-11-05).
    literal: bool = False
    #: Sus hojas que van también en el PDF de otra sesión: la que comparte el
    #: cierre de un acta colectiva con el comienzo de la siguiente (2026-11-13).
    compartidas: tuple[int, ...] = ()

    @property
    def desde(self) -> int:
        return self.piezas[0].desde

    @property
    def hasta(self) -> int:
        return self.piezas[-1].hasta

    @property
    def paginas(self) -> tuple[int, ...]:
        """Sus páginas en el orden en que van en su PDF: el de sus piezas, que en el libro colectivo es el del folio."""
        return tuple(pagina for pieza in self.piezas for pagina in pieza.paginas)

    def as_dict(self) -> dict[str, object]:
        datos: dict[str, object] = {
            "orden": self.orden,
            "nombre": self.nombre,
            "desde": self.desde,
            "hasta": self.hasta,
            "piezas": [
                {"tipo": pieza.tipo, "nombre": pieza.nombre, "desde": pieza.desde, "hasta": pieza.hasta}
                for pieza in self.piezas
            ],
        }
        if self.paginas != tuple(range(self.desde, self.hasta + 1)):
            # Las que no son de «desde» a «hasta» seguidas, en el orden del PDF.
            datos["paginas"] = list(self.paginas)
        if self.compartidas:
            datos["compartidas"] = list(self.compartidas)
        return datos


#: Lo que Windows no admite en el nombre de una carpeta.
_NO_VALE_EN_UNA_CARPETA = re.compile(r'[<>:"/\\|?*]+')


def nombre_de_la_sesion(fila: FilaDeActa) -> str:
    """«ACTA EXTRAORDINARIA No. 017 - 16-08-2012»: el acta y su fecha.

    Es lo que lleva el PDF de la sesión detrás de su número de orden, y es por
    lo que se busca.
    """
    if fila.acta_colectiva:
        # El acta colectiva lleva a todos sus graduados: su PDF se llama por el
        # acta y su fecha, «ACTA DE GRADO 05408120 A 05408124 - 26-09-2008»
        # (el operador, 2026-11-12).
        partes = [fila.acta_colectiva, *([fila.fecha] if fila.fecha != NO_APLICA else [])]
        return _NO_VALE_EN_UNA_CARPETA.sub("-", " - ".join(partes)).strip(" .")
    if fila.tipo == TIPO_DE_GRADO:
        # El graduado: «MARTHA LUCIA HERRERA VILLAMIZAR - ESPECIALISTA EN
        # GESTION DE LA CALIDAD…», el nombre como va en el acta y el título que
        # se le otorga. El mismo texto que su asunto en el FUID: lo pidió el
        # operador el 2026-11-05, «que el nombre del PDF sea el mismo que vaya
        # en el FUID», nombre y especialidad. La cédula y el número del acta
        # van en sus columnas del FUID, ya no en el nombre.
        def leido(valor: str | None) -> str | None:
            return valor if valor and valor != NO_APLICA else None

        return asunto_del_graduado(
            leido(fila.nombre), leido(fila.titulo), acta=leido(fila.acta), cedula=leido(fila.cedula)
        )
    partes = [fila.acta if fila.acta != NO_APLICA else "ACTA SIN NUMERO"]
    if fila.fecha != NO_APLICA:
        partes.append(fila.fecha)
    return _NO_VALE_EN_UNA_CARPETA.sub("-", " - ".join(partes)).strip(" .")


def _con_nombre_literal(fila: FilaDeActa) -> bool:
    """Si el PDF de esta fila se llama con su nombre tal cual: el del graduado y las hojas de su ceremonia.

    El graduado se llama igual que su asunto en el FUID, «01_MARTHA LUCIA
    HERRERA - ENFERMERA.pdf» (2026-11-05), y la ceremonia de su libro, con el
    mismo formato. El acta manuscrita de examen (caja 3362) sigue como se
    entregó: su asunto en el FUID es otro, el examen primero.
    """
    if fila.tipo == ROTULO_DE_CEREMONIA or fila.acta_colectiva:
        return True
    return fila.tipo == TIPO_DE_GRADO and not es_acta_de_examen(fila.acta)


#: Lo que va delante de la primera sesión de un libro de grado: portada,
#: cartas de remisión. Sale aparte. En uno de consejo son los anexos de la
#: primera sesión y van dentro de ella (``_con_las_previas``).
PAGINAS_PREVIAS = "PAGINAS PREVIAS"


@dataclass(slots=True)
class DivisionDeActas:
    """Lo que se escribió al dividir: rutas relativas a la carpeta del trabajo."""

    salidas: list[str] = field(default_factory=list)
    ilegibles: dict[int, str] = field(default_factory=dict)
    #: Cada PDF escrito, vuelto a abrir y casado hoja por hoja con el libro.
    comprobacion: dict[str, object] = field(default_factory=dict)


def reparto_de_las_actas(outcome: ActaOutcome, *, cada_hoja_una_vez: bool = False) -> GroupingResult:
    """El libro repartido en sesiones, como se va a escribir: un grupo por PDF.

    Con ``cada_hoja_una_vez``, la hoja compartida queda sólo en el acta que
    empieza en ella: es como la mira el revisor de cortes, que casa cada hoja
    con un documento (2026-11-13).
    """
    duenas: dict[int, int] = {}
    if cada_hoja_una_vez:
        for sesion in outcome.sesiones:
            if sesion.compartidas and sesion.paginas[0] in sesion.compartidas:
                duenas.setdefault(sesion.paginas[0], sesion.orden)
        for sesion in outcome.sesiones:
            for pagina in sesion.compartidas:
                duenas.setdefault(pagina, sesion.orden)
    grupos = []
    for sesion in outcome.sesiones:
        paginas = [p for p in sesion.paginas if duenas.get(p, sesion.orden) == sesion.orden]
        if not paginas:
            continue
        grupos.append(
            PageGroup(
                code=ResolutionCode(value=f"{sesion.orden:02d}", raw=f"{sesion.orden:02d}"),
                # En el orden del PDF: el del folio impreso en el libro colectivo.
                page_numbers=paginas,
                kind=sesion.nombre,
                nombre_literal=sesion.literal,
            )
        )
    return GroupingResult(groups=grupos)


def dividir_actas(
    outcome: ActaOutcome,
    *,
    assembler: DocumentAssembler,
    source: Path,
    destino: Path,
    raiz: Path,
    huellas: Callable[[Path], list] | None = None,
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
    repartir, antes de llegar aquí. Con ``huellas``, cada PDF escrito se vuelve
    a abrir y se casa hoja por hoja con el libro, como en las demás rutas.
    """
    reparto = reparto_de_las_actas(outcome)
    escrito = assembler.write(source, reparto, destino)
    comprobacion: dict[str, object] = {}
    if huellas is not None:
        from .entrega import comprobar_en_el_disco

        comprobacion = comprobar_en_el_disco(source, reparto, escrito, destino, huellas)
    return DivisionDeActas(
        salidas=[ruta.relative_to(raiz).as_posix() for ruta in escrito.outputs],
        ilegibles=dict(escrito.unwritable_pages),
        comprobacion=comprobacion,
    )


YA_ERA_UN_ACTA = "Ya era un acta: inventariada sin dividir"
SOLO_INVENTARIADA = "Inventariada"


def resultado_de_cada_acta(
    filas: Sequence[FilaDeActa],
    salidas: Sequence[str] | None,
    *,
    pidio_dividir: bool,
    no_se_dividio: str | None = None,
) -> list[FilaDeActa]:
    """Las filas con lo que se hizo con cada acta escrito en su columna.

    De un libro dividido, el PDF en que quedó cada acta: el de su sesión
    (``fila.sesion``), que empieza por «NN_», el orden del libro; las filas de
    un acta colectiva, todas el mismo. En los informes de antes, sin sesión, la
    fila N es el PDF N. De un PDF que ya era un acta y se pidió dividir, que no
    hizo falta. Si dividir falló -- ``no_se_dividio`` --, por qué. Y si sólo se
    pidió inventariar, eso.
    """
    resultados: list[FilaDeActa] = []
    for puesto, fila in enumerate(filas, start=1):
        orden = fila.sesion or puesto
        if salidas:
            prefijo = f"{orden:02d}_"
            pdf = next((ruta.rsplit("/", 1)[-1] for ruta in salidas if ruta.rsplit("/", 1)[-1].startswith(prefijo)), None)
            texto = f"Dividido en {pdf}" if pdf else "Dividido: su PDF no se pudo escribir"
        elif no_se_dividio:
            texto = f"No se pudo dividir: {no_se_dividio}. Inventariada sin dividir"
        elif pidio_dividir:
            texto = YA_ERA_UN_ACTA
        else:
            texto = SOLO_INVENTARIADA
        resultados.append(replace(fila, resultado=texto))
    return resultados


def _comprobar_que_cubre(sesiones: Sequence[SesionDeActa], total: int) -> None:
    """Cada página del PDF en exactamente una pieza, o se para antes de escribir.

    Salvo la hoja declarada compartida (``SesionDeActa.compartidas``): va en
    los dos PDF que la comparten, y en ninguno más (2026-11-13).
    """
    vistas = Counter(pagina for sesion in sesiones for pieza in sesion.piezas for pagina in pieza.paginas)
    declaradas = {pagina for sesion in sesiones for pagina in sesion.compartidas}
    de_mas = sorted(
        pagina
        for pagina, veces in vistas.items()
        if veces > 1 and (pagina not in declaradas or veces > sum(pagina in s.paginas for s in sesiones))
    )
    if sorted(vistas) != list(range(1, total + 1)) or de_mas:
        raise ValueError(
            "el reparto en piezas no cubre el PDF entero una sola vez: "
            f"{len(vistas)} páginas repartidas de {total}"
            + (f", repetidas sin declararlas compartidas: {de_mas[:10]}" if de_mas else "")
        )


@dataclass(slots=True)
class _PedidoDeFolios:
    """Los mosaicos de folios ya mandados a leer, y cómo volver de sus hojas a las actas."""

    orden: dict[int, int]
    hoja_de: dict[int, int]
    paginas: list[int]
    vuelo: list[Future]


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
    #: La fecha que se leyó y se descartó por no cuadrar con las vecinas.
    fecha_descartada: str | None = None
    #: Y esa fecha tal cual, para intentar corregirle el año con las vecinas.
    fecha_leida: date | None = None
    #: «12-2006» cuando el acta sólo dice el mes y el año.
    fecha_parcial: str | None = None
    #: Lo que se completó razonando, dicho para observaciones.
    razonado: list[str] = field(default_factory=list)
    #: Cada lectura de la hoja del graduado -- la capa, la franja, la tinta
    #: realzada, la IA -- con su peso, para decidir el nombre y la cédula por
    #: consenso al final.
    textos: list[tuple[str, float]] = field(default_factory=list)
    #: Si el nombre quedó confirmado por más de una lectura o por el diccionario.
    nombre_confirmado: bool = True
    #: Si alguna palabra del nombre no la confirma nada: se dice en observaciones.
    nombre_dudoso: bool = False
    #: El nombre como se leyó antes de votar.
    nombre_leido: str | None = None
    #: Lo que se tomó del nombre del archivo, o en lo que discrepa del papel.
    nota_del_nombre: str | None = None
    #: La hoja leída por la IA, cuando se pidió: con ella se cruza cada campo.
    texto_de_la_ia: str | None = None
    #: Lo que el lector de texto de la IA entendió de esa hoja, validado.
    datos_de_la_ia: dict = field(default_factory=dict)
    #: Del libro de actas colectivas (UPD3859802): el tramo del libro con el
    #: texto de su acta, cortado donde empieza la siguiente.
    del_libro: ActaDelLibro | None = None
    #: Si el acta gradúa a varios: entonces da una fila por graduado, y no se
    #: le decide un nombre como a las demás.
    colectiva: bool = False
    #: Los graduados del acta colectiva, en el orden del acta.
    graduados: list[GraduadoDelActa] = field(default_factory=list)
    #: El último número del rango, «05408124» en «Nº 05408120 a 05408124».
    numero_hasta: str | None = None
    #: Por qué el acta está anulada (``acta_anulada``) o sin terminar
    #: (``acta_sin_terminar``): no gradúa a nadie.
    anulada: str | None = None
    #: Si no la anuló nadie: quedó sin terminar, y su rótulo no dice ANULADA.
    sin_terminar: bool = False


@dataclass(frozen=True, slots=True)
class PerfilDeActas:
    """Lo que distingue a una clase de actas: cómo se reparten, cómo se leen y qué llevan.

    Todo lo demás -- leer el texto, los folios de la esquina y su cadena, la
    fila del inventario, la división en un PDF por acta, la entrega -- es lo
    mismo para un acta de consejo que para una de grado, y se escribe una vez.
    """

    tipo_documental: str
    repartir: Callable[[Sequence[str]], ActasDelPdf]
    leer: Callable[[Sequence[str]], ActaDeConsejo]
    #: Cómo se reparten en piezas las páginas de un acta; sin esto, el acta es
    #: una sola pieza.
    piezas: Callable[[Sequence[str], int], list[PiezaDeActa]] | None = None
    #: Si el inventario lleva el resumen del acta escrito por la IA.
    con_resumen: bool = True
    #: Si se lee el folio manuscrito de la esquina. El FUID de grados no lo
    #: pide -- sólo cuántos folios tiene cada acta --, y leerlo costaría una
    #: página de pago por graduado.
    lee_folio: bool = True
    #: Qué actas se vuelven a leer con otro motor porque les falta algo, y
    #: cómo se completan con lo que ese motor lea.
    le_falta_algo: Callable[[ActaDeConsejo], bool] | None = None
    completar: Callable[[ActaDeConsejo, str], ActaDeConsejo] | None = None
    #: Si el reparto mira qué hojas llevan folio manuscrito: en un libro de
    #: grados la hoja sin folio es el vuelto de la anterior.
    reparte_con_folios: bool = False
    #: Si el folio manuscrito de cada acta se lee hoja por hoja, muchas en una
    #: página facturada: el FUID de grados lleva el folio de cada graduado.
    folio_por_hoja: bool = False
    #: Si el nombre del archivo, cuando declara un acta con su fecha, decide
    #: qué actas de dentro son anexos suyos.
    respeta_el_nombre: bool = False
    #: Si cada hoja se lee también rehecha por su geometría -- el formulario
    #: relleno a máquina -- y se queda la lectura que más dice.
    lee_formulario: bool = False


#: Las actas de consejo: una por sesión, con su folio manuscrito y su resumen.
#: Su inventario es el FUID, con el resumen en el asunto (2026-11-09); el Excel
#: de actas que lo acompañaba se quitó el 2026-11-11.
CONSEJO = PerfilDeActas(
    tipo_documental=TIPO_DOCUMENTAL,
    repartir=actas_del_pdf,
    leer=leer_acta,
    piezas=piezas_de_la_sesion,
    con_resumen=True,
    respeta_el_nombre=True,
)

#: Las actas de grado: una por graduado, para el FUID de grados -- número del
#: acta, nombre y título, cédula, fecha --, sin resumen ni folio de pago. Lo
#: que la capa del escáner no trae se relee con Tesseract y, si se pidió, con
#: la IA.
GRADO = PerfilDeActas(
    tipo_documental=TIPO_DE_GRADO,
    repartir=actas_de_grado_del_pdf,
    leer=leer_acta_de_grado,
    piezas=None,
    con_resumen=False,
    lee_folio=False,
    le_falta_algo=le_falta_algo,
    completar=completar_acta,
    reparte_con_folios=True,
    folio_por_hoja=True,
    lee_formulario=True,
)


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
        perfil: PerfilDeActas = CONSEJO,
        #: Quien relee con la IA la hoja de un acta a la que, después de
        #: Tesseract, todavía le falta algo. Sólo si el operador la pidió.
        relector_de_pago: OcrEngine | None = None,
        #: Quien lee las cifras escritas a máquina de un recuadro del
        #: formulario -- el número del acta, la cédula -- cuando la capa del
        #: escáner se las saltó.
        lector_de_cifras: OcrEngine | None = None,
        #: Quien relee la franja del graduado -- del encabezado a la cédula --
        #: con la confianza de cada palabra, para juntarla con la capa.
        lector_de_franja=None,
        #: Quienes releen la hoja entera con la tinta clara oscurecida, uno
        #: detrás de otro, para lo que a un acta todavía le falta antes de
        #: entregar el inventario: cada uno sólo con lo que dejó el anterior.
        lectores_de_tinta_clara: Sequence[OcrEngine] = (),
        #: Quien lee con la IA, del texto de la hoja, los datos del graduado
        #: (un ``Resumidor`` con las instrucciones del acta de grado).
        lector_de_datos: Resumidor | None = None,
        #: Cuánto se espera antes de volver a pedir los resúmenes que el
        #: proveedor no atendió por estar saturado.
        espera_para_reintentar: float | None = None,
        #: Quien lee con la IA, del texto de un acta colectiva, su número, su
        #: fecha y la lista de sus graduados (un ``Resumidor`` con
        #: ``INSTRUCCIONES_DEL_ACTA_COLECTIVA``). Sin él, la lista se lee por regla.
        lector_de_actas_colectivas: Resumidor | None = None,
    ) -> None:
        self._lector_de_actas_colectivas = lector_de_actas_colectivas
        self._orden_del_libro: list[int] | None = None
        self._espera_para_reintentar = (
            ESPERA_PARA_REINTENTAR if espera_para_reintentar is None else espera_para_reintentar
        )
        self._lector_de_cifras = lector_de_cifras
        self._lector_de_franja = lector_de_franja
        self._lectores_de_tinta_clara = tuple(lectores_de_tinta_clara)
        self._lector_de_datos = lector_de_datos
        self._perfil = perfil
        self._relector_de_pago = relector_de_pago
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

        self._textos_de_la_ia: dict[int, str] = {}
        if self._perfil.reparte_con_folios and self._relector_de_pago is not None and self._es_manuscrito(source):
            # Un libro escrito a mano -- los exámenes de grado de 1924-1946 (20.
            # ACTAS DE GRADO 3362) --: ni la capa ni Tesseract leen la letra, y
            # pasarlo por Tesseract eran minutos para nada. Lo lee la IA
            # directamente, cada página, a más resolución (lo pidió el operador
            # el 2026-10-31: «para ese tipo de documentos, la IA directamente»).
            self._textos_de_la_ia = self._leer_el_libro_con_la_ia(source, total)
        if self._textos_de_la_ia:
            paginas = [self._textos_de_la_ia.get(numero) or self._capa(source, numero) for numero in range(1, total + 1)]
            con_ocr = len(self._textos_de_la_ia)
            ilegibles = [numero for numero, texto in enumerate(paginas, 1) if not texto.strip()]
        else:
            paginas, con_ocr, ilegibles = self._leer(source)
        if self._perfil.lee_formulario:
            paginas = self._por_formulario(source, paginas)
        foliadas = _paginas_foliadas(source)
        if self._perfil.reparte_con_folios:
            reparto = self._perfil.repartir(paginas, foliadas)
        else:
            reparto = self._perfil.repartir(paginas)
        if (
            self._perfil.reparte_con_folios
            and not self._textos_de_la_ia
            and not any(not tramo.ceremonia for tramo in reparto.tramos)
        ):
            # Un libro manuscrito -- los exámenes de grado de 1924-1946 (20.
            # ACTAS DE GRADO 3362) --: ni la capa ni Tesseract leen la letra a
            # mano y no se encontró ningún acta. Con la IA se lee cada página, y
            # se reparte con lo que dice.
            self._textos_de_la_ia = self._leer_el_libro_con_la_ia(source, total)
            if self._textos_de_la_ia:
                paginas = [self._textos_de_la_ia.get(numero) or texto for numero, texto in enumerate(paginas, 1)]
                reparto = self._perfil.repartir(paginas, foliadas)
        # El libro de actas colectivas manuscrito (Odontología, UPD3859802,
        # 2026-11-12): cada acta gradúa a una promoción y empieza a mitad de la
        # hoja en que acaba la anterior. Se reconoce en lo que leyó la IA -- la
        # capa es basura --, y se reparte por acta y no por graduado.
        # Sus hojas van en el orden del folio impreso (2026-11-13): el escaneo de
        # UPD3859802 trae hojas fuera de su sitio, y el acta sigue en la del
        # folio siguiente aunque esté lejos en el PDF.
        del_libro: list[ActaDelLibro | None] = []
        self._orden_del_libro = None
        compartidas: list[int] = []
        if self._perfil.reparte_con_folios and self._textos_de_la_ia:
            de_la_ia = [self._textos_de_la_ia.get(numero) or texto for numero, texto in enumerate(paginas, 1)]
            if es_libro_de_actas_colectivas(de_la_ia):
                paginas = self._con_todo_el_libro_leido(source, de_la_ia)
                self._orden_del_libro = orden_del_libro(paginas)
                partes = reparto_del_libro_colectivo(paginas, self._orden_del_libro)
                reparto = actas_del_libro_colectivo(partes, total)
                del_libro = [None if parte.ceremonia else parte for parte in partes]
                compartidas = paginas_compartidas(partes)
        declarada = acta_del_nombre(document_name) if self._perfil.respeta_el_nombre else None
        if declarada and reparto.es_libro:
            reparto = sin_anexos_anteriores(reparto, paginas, *declarada)
        del_nombre = numeros_del_nombre(document_name) if self._perfil.respeta_el_nombre else None
        if del_nombre and reparto.es_libro:
            reparto = sin_actas_ajenas_al_nombre(reparto, paginas, del_nombre)
        if foliadas is None:
            # La fuente no sabe medir tinta: se dan por foliadas todas, que es
            # lo normal en estas actas -- cada hoja lleva su número -- y la
            # comprobación de los números sigue protegiendo de una lectura mala.
            foliadas = list(range(1, total + 1))

        lecturas = []
        for indice, tramo in enumerate(reparto.tramos):
            # Del libro colectivo, el tramo y su acta van a la par: dos actas que
            # empiezan en la misma hoja tienen el mismo «desde».
            parte = del_libro[indice] if del_libro and not tramo.ceremonia else None
            if parte is not None:
                lecturas.append(_lectura_del_libro_colectivo(tramo, parte, foliadas))
                continue
            # Sólo texto ya leído: repartir en piezas no cuesta una lectura más.
            piezas = (
                self._perfil.piezas(paginas[tramo.desde - 1 : tramo.hasta], tramo.desde)
                if self._perfil.piezas
                else _piezas_del_tramo(tramo)
            )
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
                    acta=self._perfil.leer([paginas[p - 1] for p in tramo.en_el_pdf]),
                    foliadas=[p for p in foliadas if p in tramo.en_el_pdf and p not in portadas],
                    piezas=piezas,
                )
            )
        for lectura in lecturas:
            if lectura.del_libro is not None:
                continue  # el acta del libro colectivo ya trae su texto, cortado
            if lectura.acta.rotulo == ROTULO_DE_GRADO and not lectura.tramo.ceremonia:
                hoja = lectura.tramo.desde + (lectura.acta.pagina or 1) - 1
                if hoja in self._textos_de_la_ia:
                    # Ya la leyó la IA para repartir el libro: no se paga dos veces.
                    lectura.texto_de_la_ia = self._textos_de_la_ia[hoja]
                    lectura.textos.append((paginas[hoja - 1], PESO_DE_LA_IA))
                else:
                    lectura.textos.append((paginas[hoja - 1], PESO_DE_UNA_LECTURA))
        # Los folios de la IA se piden ya, con el reparto hecho, y se recogen
        # al final: mientras el proveedor contesta por la red, Tesseract relee
        # las franjas en la CPU. Uno detrás del otro eran dos esperas.
        with hilos(LECTURAS_A_LA_VEZ) as proveedor:
            # El libro manuscrito ya trae el folio en el texto que leyó la IA
            # (``_folios_del_texto``): no se paga otra lectura de las esquinas.
            pedido = (
                self._pedir_folios(source, lecturas, foliadas, proveedor)
                if self._perfil.folio_por_hoja and not self._manuscrito
                else None
            )
            self._releer_lo_que_falta(source, lecturas)
            self._verificar_con_la_ia(source, lecturas)
            self._leer_las_actas_colectivas(lecturas)
            if declarada and len(lecturas) == 1:
                _contrastar_con_el_nombre(lecturas[0], paginas, *declarada)
            if not self._manuscrito:  # la IA leyó la fecha; la regla es contra el OCR gratis
                _descartar_fechas_fuera_de_lugar(lecturas)
            self._razonar_lo_que_falta(source, paginas, lecturas)
            self._nombres_por_consenso(source, paginas, lecturas)
            self._nombres_manuscritos(source, lecturas)
            self._releer_los_nombres_dudosos(source, lecturas)
            self._fechas_manuscritas(source, lecturas)
            _los_examenes(lecturas)
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
            if pedido is not None:
                self._recoger_folios(pedido, lecturas)
            elif self._perfil.folio_por_hoja and self._manuscrito:
                self._folios_del_texto(lecturas, total)
        if reparto.es_libro:
            _encadenar_folios(lecturas)
        self._folios_hoja_por_hoja(source, lecturas)
        _completar_por_continuidad(lecturas)

        self._report(
            ProgressEvent(
                stage=Stage.INVENTORYING,
                done=0,
                total=1,
                detail="anotando las actas en el inventario",
            )
        )
        # Cada lectura da su fila, y el acta colectiva una por graduado: todas
        # con el orden de su PDF (``sesion``), que es el de su lectura.
        filas = [
            replace(
                fila if fila.tipo == ROTULO_DE_CEREMONIA else replace(fila, tipo=self._perfil.tipo_documental),
                sesion=orden,
            )
            for orden, lectura in enumerate(lecturas, start=1)
            for fila in (
                _filas_de_la_colectiva(
                    lectura,
                    archivo=document_name,
                    carpeta=carpeta,
                    ilegibles=[p for p in ilegibles if p in lectura.tramo.en_el_pdf],
                )
                if lectura.colectiva
                else [
                    _fila(
                        lectura,
                        archivo=document_name,
                        carpeta=carpeta,
                        ilegibles=[p for p in ilegibles if p in lectura.tramo.en_el_pdf],
                        por_eleccion=self._motivo_sin_resumidor,
                    )
                ]
            )
        ]
        # Las hojas de cada PDF en su orden y las que se cuentan en otro: las
        # del libro colectivo que no van seguidas o que comparte con otra acta.
        if self._orden_del_libro is not None:
            filas = _con_sus_hojas(filas, lecturas, compartidas)
        # El rector o el decano del pie que se pegó detrás del graduado: las
        # mismas tres palabras al final de tres nombres o más del libro
        # (Odontología, 2026-11-12: «CARLOS VILLALBA BUSTILLO»).
        # Y con una vez basta si son de quien el libro muestra firmando sobre su
        # cargo (UPD3859813, fila 1802; 2026-11-13).
        sin_el_pie = sin_firmantes([fila.nombre for fila in filas], firmantes_del_libro(paginas))
        filas = [
            replace(fila, nombre=nombre) if nombre != fila.nombre else fila
            for fila, nombre in zip(filas, sin_el_pie, strict=True)
        ]
        if reparto.es_libro and self._perfil.tipo_documental != TIPO_DE_GRADO:
            filas = _con_el_numero_de_la_serie(filas)
        if reparto.previas and filas[0].tipo != TIPO_DE_GRADO and filas[0].tipo != ROTULO_DE_CEREMONIA:
            filas[0] = _con_las_previas(filas[0], lecturas[0], reparto.previas)
        # Un PDF por lectura, nombrado por su primera fila: la del graduado, la
        # de la sesión o la del acta colectiva con todos sus graduados.
        primera_de: dict[int, FilaDeActa] = {}
        for fila in filas:
            primera_de.setdefault(fila.sesion, fila)
        sesiones = [
            SesionDeActa(
                orden,
                nombre_de_la_sesion(primera_de[orden]),
                tuple(lectura.piezas),
                literal=_con_nombre_literal(primera_de[orden]),
                compartidas=tuple(p for p in lectura.tramo.en_el_pdf if p in compartidas),
            )
            for orden, lectura in enumerate(lecturas, start=1)
        ]
        if reparto.previas and sesiones[0].desde != reparto.previas[0]:
            desde, hasta = reparto.previas
            # Con el mismo formato de nombre que las del libro que preceden.
            sesiones.insert(
                0,
                SesionDeActa(
                    0, PAGINAS_PREVIAS, (PiezaDeActa(SIN_SESION, desde, hasta),), literal=sesiones[0].literal
                ),
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
            tipo_documental=self._perfil.tipo_documental,
            textos=dict(enumerate(paginas, start=1)),
            colectivo=any(lectura.colectiva for lectura in lecturas),
            paginas_compartidas=compartidas,
            cruces_por_el_folio=_cruces_por_el_folio(lecturas),
        )

    # -- leer -----------------------------------------------------------------

    def _leer(self, source: PageSource) -> tuple[list[str], int, list[int]]:
        """El texto de cada página: de su capa si la tiene, del OCR si no.

        La página entera y todas las páginas: el resumen es del acta entera, y
        lo que se trató va de la primera hoja a la última. Primero la capa de
        todas, que cuesta milésimas, y así se sabe cuántas piden OCR. Ésas se
        rasterizan aquí, en este hilo -- MuPDF no admite más de uno --, y se
        leen en paralelo, que es lo que tarda.

        En flujo continuo: en cuanto un lector termina recibe lo siguiente.
        Iba por tandas, esperando a que acabara la tanda entera antes de
        preparar la próxima, y los lectores se quedaban quietos esperando a la
        página más lenta. Y por lotes de unas pocas páginas por arranque de
        Tesseract, que es lo que cuesta cargar el modelo del idioma.
        """
        total = source.page_count
        textos: list[str] = [""] * total
        con_ocr = 0
        leidas = 0

        sin_capa: list[int] = []
        for numero in range(1, total + 1):
            self._control.check()
            texto = self._capa(source, numero)
            textos[numero - 1] = texto
            if len(texto.strip()) < MIN_CHARS and self._ocr is not None:
                sin_capa.append(numero)
            else:
                leidas += 1
                self._pagina(leidas, total, numero, "text_layer" if texto.strip() else "none")

        por_llamada = IMAGENES_POR_LLAMADA if hasattr(self._ocr, "read_varias") else 1
        with hilos(self._workers) as lectores:
            vuelo: dict[Future, list[int]] = {}

            def recoger(futuro: Future) -> None:
                nonlocal con_ocr, leidas
                del_lote = vuelo.pop(futuro)
                for pagina, (resultado, error) in zip(
                    del_lote, _resultados_del_lote(futuro, len(del_lote)), strict=True
                ):
                    con_ocr += 1
                    fallo = None
                    if error is not None:
                        logger.warning("no se pudo pasar por OCR la página %s: %s", pagina, error)
                        leido = ""
                        fallo = "falló el OCR de la página"
                    else:
                        leido = resultado.text
                    # Lo que diera la capa se conserva junto a lo del OCR: a
                    # veces una trae el número y el otro la fecha.
                    textos[pagina - 1] = f"{textos[pagina - 1]}\n{leido}".strip()
                    leidas += 1
                    self._pagina(leidas, total, pagina, "ocr_full_page", fallo=fallo)

            for lote in _lotes(sin_capa, self._workers, por_llamada):
                self._control.check()
                imagenes: list[bytes] = []
                suyas: list[int] = []
                for numero in lote:
                    try:
                        imagenes.append(source.render(numero, None, DPI_DE_LECTURA))
                        suyas.append(numero)
                    except Exception:  # noqa: BLE001 - una página no tumba el acta
                        logger.warning("no se pudo rasterizar la página %s", numero, exc_info=True)
                        leidas += 1
                        self._pagina(leidas, total, numero, "none", fallo="no se pudo rasterizar")
                if imagenes:
                    vuelo[lectores.submit(_leer_lote, self._ocr, imagenes)] = suyas
                # Uno más en cola que lectores: nadie espera trabajo, y no hay
                # un libro entero rasterizado ocupando memoria.
                while len(vuelo) > self._workers:
                    for futuro in alguno_listo(vuelo, self._control):
                        recoger(futuro)
            for futuro in completados(list(vuelo), self._control):
                recoger(futuro)

        ilegibles = [numero for numero, texto in enumerate(textos, start=1) if not texto.strip()]
        return textos, con_ocr, ilegibles

    def _por_formulario(self, source: PageSource, paginas: list[str]) -> list[str]:
        """Cada hoja leída también por zonas, quedándose con la lectura que más dice.

        En los libros de grados de 1980 a 2005 los datos se rellenaron a máquina
        por encima del renglón impreso, y la capa del escáner los saca fuera de
        sitio: «03» antes de «ACTA DE GRADO No.», el nombre partido a ambos
        lados de «al estudiante». Rehecha la página por la caja de cada trozo,
        cada dato queda junto a su rótulo.
        """
        trozos_de = getattr(source, "trozos_of", None)
        if trozos_de is None:
            return paginas
        leidas = list(paginas)
        for numero, capa in enumerate(paginas, start=1):
            self._control.check()
            try:
                formulario = texto_del_formulario(trozos_de(numero))
            except Exception:  # noqa: BLE001 - se queda la capa
                logger.debug("no se pudo rehacer la página %s", numero, exc_info=True)
                continue
            leidas[numero - 1] = mejor_lectura(capa, formulario)
        return leidas

    def _pedir_folios(
        self, source: PageSource, lecturas: list[_Lectura], foliadas: list[int], proveedor
    ) -> _PedidoDeFolios | None:
        """Manda a leer el folio manuscrito de la hoja de cada graduado, sin esperarlo.

        Diez hojas por página facturada: las esquinas van en mosaicos con la
        página impresa al lado de cada una («P147»), así que una esquina
        ilegible no descuadra las demás. Los mosaicos se arman aquí -- MuPDF no
        admite más de un hilo -- y se leen en ``proveedor`` mientras el trabajo
        sigue; ``_recoger_folios`` los espera al final. Sin la IA no se pide
        nada y el folio queda en N/A: Tesseract no lee la letra a mano, y contar
        hojas no da el número -- en UPD3859820 la hoja 146 es el folio 139 y
        contando salía 136 --.
        """
        armar = getattr(self._lector_de_folios, "armar_mosaico_etiquetado", None)
        leer = getattr(self._lector_de_folios, "leer_mosaico_etiquetado", None)
        if armar is None or leer is None:
            return None
        orden = {pagina: puesto for puesto, pagina in enumerate(sorted(foliadas), start=1)}
        hoja_de: dict[int, int] = {}
        for indice, lectura in enumerate(lecturas):
            if lectura.tramo.ceremonia:
                continue
            hoja = next(
                (p for p in range(lectura.tramo.desde, lectura.tramo.hasta + 1) if p in orden),
                None,
            )
            if hoja is not None:
                hoja_de[indice] = hoja
        paginas = sorted(hoja_de.values())
        vuelo: list[Future] = []
        for inicio in range(0, len(paginas), FOLIOS_POR_MOSAICO):
            self._control.check()
            tanda = paginas[inicio : inicio + FOLIOS_POR_MOSAICO]
            imagen = armar(source, tanda)
            if imagen:
                vuelo.append(proveedor.submit(leer, imagen, tanda))
        return _PedidoDeFolios(orden=orden, hoja_de=hoja_de, paginas=paginas, vuelo=vuelo)

    def _recoger_folios(self, pedido: _PedidoDeFolios, lecturas: list[_Lectura]) -> None:
        """Lo que leyó la IA de las esquinas, pasado por la foliación seguida del libro.

        La foliación confirma cada lectura, corrige la que no cuadra y da el
        folio de la hoja que no se leyó.
        """
        orden, hoja_de, paginas = pedido.orden, pedido.hoja_de, pedido.paginas
        vuelo = pedido.vuelo
        leidos: dict[int, int] = {}
        for hechas, futuro in enumerate(vuelo, start=1):
            aguardar(futuro, self._control)
            try:
                leidos.update(futuro.result())
            except Exception:  # noqa: BLE001 - esas hojas se quedan sin folio
                logger.warning("no se pudo leer un mosaico de folios", exc_info=True)
            self._report(
                ProgressEvent(
                    stage=Stage.INVENTORYING,
                    done=hechas,
                    total=len(vuelo),
                    detail=f"leyendo el folio de {len(paginas)} hoja(s)",
                )
            )
        folios = folios_de_la_foliacion(leidos, orden)
        for indice, hoja in hoja_de.items():
            if hoja not in folios:
                continue
            folio, como, leido = folios[hoja]
            lectura = lecturas[indice]
            lectura.folios = FoliosDelActa(inicial=folio, final=folio, foliadas=len(lectura.foliadas))
            if como == CORREGIDO:
                lectura.deducido = (
                    f"en la esquina se leyó el folio {leido}, pero por la foliación seguida "
                    f"es el {folio}: revíselo en el papel"
                )
            elif como == DEDUCIDO:
                lectura.deducido = (
                    "el folio no se pudo leer y se dedujo de la foliación seguida de las hojas vecinas"
                )

    def _folios_del_texto(self, lecturas: list[_Lectura], total: int) -> None:
        """El folio de cada acta de un libro manuscrito, del número que la IA ya leyó en sus páginas.

        En los libros de exámenes de 1924-1946 la esquina trae dos números, el
        impreso del libro y la foliación del archivista («1» y «1/V»), y el
        lector de esquinas tomaba uno en unas hojas y el otro en otras: las diez
        primeras actas de UPD3860000 salían sin folio. La IA lee la página
        entera y trae arriba el impreso (``folio_del_texto``). Cada página lleva
        el suyo, así que el acta va del folio de su primera página al de la
        última, y la foliación seguida confirma, corrige o deduce cada uno.
        """
        leidos = {
            pagina: folio
            for pagina, texto in self._textos_de_la_ia.items()
            if (folio := folio_del_texto(texto)) is not None
        }
        # En el orden del libro: en el colectivo, el del folio impreso. Con el
        # del escaneo, el folio 42 de la hoja 1 de UPD3859802 se «corregía» a
        # 39 por la foliación seguida, y era el bueno (2026-11-13).
        orden = self._orden_del_libro or range(1, total + 1)
        folios = folios_de_la_foliacion(leidos, {pagina: puesto for puesto, pagina in enumerate(orden, start=1)})
        for lectura in lecturas:
            if lectura.tramo.ceremonia:
                continue
            hojas = lectura.tramo.en_el_pdf
            desde, hasta = hojas[0], hojas[-1]
            if desde not in folios:
                continue
            inicial, como, leido = folios[desde]
            final = folios[hasta][0] if hasta in folios else inicial + len(hojas) - 1
            lectura.folios = FoliosDelActa(inicial=inicial, final=max(inicial, final), foliadas=len(lectura.foliadas))
            if como == CORREGIDO:
                lectura.deducido = (
                    f"en la esquina se leyó el folio {leido}, pero por la foliación seguida "
                    f"es el {inicial}: revíselo en el papel"
                )
            elif como == DEDUCIDO:
                lectura.deducido = (
                    "el folio no se pudo leer y se dedujo de la foliación seguida de las hojas vecinas"
                )

    def _leer_franjas(self, source: PageSource, lecturas: list[_Lectura]) -> None:
        """La franja de cada graduado releída con Tesseract y juntada con la capa.

        La capa del escáner de los libros de 2003 a máquina sale con las letras
        cambiadas -- «MAHUEL MAKTUIEZ CEFFIÍEÍLO» por PEDRO MANUEL MARTINEZ
        CERMEÑO --, y Tesseract sobre la franja a 300 ppp lo lee bien en medio
        segundo y gratis. Pero también se equivoca a veces, y por eso no se
        reemplaza una lectura por la otra: se juntan palabra a palabra, por la
        confianza con que Tesseract leyó cada una.
        """
        leer = getattr(self._lector_de_franja, "read_con_confianza", None)
        trozos_de = getattr(source, "trozos_of", None)
        medida_de = getattr(source, "size_of", None)
        if leer is None or trozos_de is None or medida_de is None:
            return
        pendientes = [
            lectura
            for lectura in lecturas
            if not lectura.tramo.ceremonia and lectura.acta.rotulo == ROTULO_DE_GRADO
        ]
        lector = self._lector_de_franja
        por_llamada = (
            IMAGENES_POR_LLAMADA if hasattr(lector, "read_con_confianza_varias") else 1
        )
        hechas = 0
        with hilos(self._workers) as lectores:
            vuelo: dict[Future, list[_Lectura]] = {}

            def recoger(futuro: Future) -> None:
                nonlocal hechas
                del_lote = vuelo.pop(futuro)
                for lectura, (leido, error) in zip(
                    del_lote, _resultados_del_lote(futuro, len(del_lote)), strict=True
                ):
                    hechas += 1
                    if error is not None:
                        # Se queda con la capa.
                        logger.debug("no se pudo leer una franja: %s", error)
                        continue
                    texto, confianza = leido
                    lectura.textos.append((texto, PESO_DE_UNA_LECTURA))
                    lectura.acta = con_la_franja(lectura.acta, texto, confianza)
                    if hechas % 10 == 0 or hechas == len(pendientes):
                        self._report(
                            ProgressEvent(
                                stage=Stage.VERIFYING,
                                done=hechas,
                                total=len(pendientes),
                                detail=f"releyendo el graduado de {len(pendientes)} acta(s)",
                            )
                        )

            for lote in _lotes(pendientes, self._workers, por_llamada):
                self._control.check()
                imagenes: list[bytes] = []
                suyas: list[_Lectura] = []
                for lectura in lote:
                    pagina = lectura.tramo.desde + (lectura.acta.pagina or 1) - 1
                    try:
                        banda = _franja_del_graduado(trozos_de(pagina), *medida_de(pagina))
                        imagenes.append(source.render(pagina, banda, DPI_DE_LA_FRANJA))
                        suyas.append(lectura)
                    except Exception:  # noqa: BLE001 - se queda con la capa
                        logger.debug(
                            "no se pudo recortar la franja de la página %s", pagina, exc_info=True
                        )
                        hechas += 1
                if imagenes:
                    futuro = lectores.submit(
                        _leer_lote,
                        lector,
                        imagenes,
                        varias="read_con_confianza_varias",
                        una="read_con_confianza",
                    )
                    vuelo[futuro] = suyas
                while len(vuelo) > self._workers:
                    for listo in alguno_listo(vuelo, self._control):
                        recoger(listo)
            for listo in completados(list(vuelo), self._control):
                recoger(listo)

    # -- razonar lo que falta --------------------------------------------------

    def _razonar_lo_que_falta(
        self, source: PageSource, paginas: list[str], lecturas: list[_Lectura]
    ) -> None:
        """Lo último antes de escribir el inventario: buscar lo que falta y, si no está, razonarlo.

        Ninguna celda se entrega vacía sin haberlo intentado todo. Primero se
        vuelve al papel -- la hoja entera con la tinta clara oscurecida --; lo
        que siga faltando se razona con las actas vecinas: el año mal leído que
        las vecinas corrigen, la fecha y el número de la misma ceremonia, el día
        que el encabezado no trae y el cuerpo sí. Cada cosa razonada se dice en
        observaciones; lo que el papel de verdad no trae, también.
        """
        if self._perfil.completar is None:
            # El de grado ya releyó con tinta clara, antes de la IA.
            self._releer_con_tinta_clara(source, lecturas)
        # Lo releído puede traer una fecha que tampoco cuadra.
        if not self._manuscrito:  # la IA leyó la fecha; la regla es contra el OCR gratis
            _descartar_fechas_fuera_de_lugar(lecturas)
        _corregir_anios(lecturas)
        _por_la_ceremonia(lecturas)
        _por_la_resolucion_de_la_ceremonia(lecturas)
        _fechas_del_cuerpo(paginas, lecturas)

    def _releer_con_tinta_clara(self, source: PageSource, lecturas: list[_Lectura]) -> None:
        """La hoja de cada acta a la que le falta algo, leída otra vez con la tinta oscurecida.

        A 300 ppp y con lo gris pasado a negro: los datos rellenados a máquina en
        gris claro se pierden en la lectura normal. Lo releído sólo llena
        huecos; lo que ya estaba no se toca. En paralelo y por lotes.
        """
        for lector in self._lectores_de_tinta_clara:
            pendientes = [
                lectura
                for lectura in lecturas
                if not lectura.tramo.ceremonia and _faltan(lectura.acta)
            ]
            if not pendientes:
                return
            self._releer_con(lector, source, pendientes)

    def _releer_con(self, lector: OcrEngine, source: PageSource, pendientes: list[_Lectura]) -> None:
        """Una pasada de relectura de la hoja entera, en paralelo y por lotes."""
        por_llamada = IMAGENES_POR_LLAMADA if hasattr(lector, "read_varias") else 1
        hechas = 0
        with hilos(self._workers) as lectores:
            vuelo: dict[Future, list[_Lectura]] = {}

            def recoger(futuro: Future) -> None:
                nonlocal hechas
                del_lote = vuelo.pop(futuro)
                for lectura, (leido, error) in zip(
                    del_lote, _resultados_del_lote(futuro, len(del_lote)), strict=True
                ):
                    hechas += 1
                    if error is not None or not (leido.text or "").strip():
                        continue
                    antes = lectura.acta
                    lectura.textos.append((leido.text, PESO_DE_UNA_LECTURA))
                    lectura.acta = self._con_lo_releido(antes, leido.text)
                    nuevos = [
                        nombre
                        for campo, nombre in _CAMPOS_DEL_ACTA
                        if getattr(antes, campo) is None and getattr(lectura.acta, campo) is not None
                    ]
                    if nuevos:
                        verbo = "se leyó" if len(nuevos) == 1 else "se leyeron"
                        lectura.razonado.append(
                            f"{_enumerar(nuevos)} {verbo} en una segunda lectura de la hoja con "
                            "la tinta realzada: revíselo en el papel"
                        )
                self._report(
                    ProgressEvent(
                        stage=Stage.VERIFYING,
                        done=hechas,
                        total=len(pendientes),
                        detail=f"buscando en el papel lo que falta de {len(pendientes)} acta(s)",
                    )
                )

            for lote in _lotes(pendientes, self._workers, por_llamada):
                self._control.check()
                imagenes: list[bytes] = []
                suyas: list[_Lectura] = []
                for lectura in lote:
                    pagina = lectura.tramo.desde + (lectura.acta.pagina or 1) - 1
                    try:
                        imagenes.append(source.render(pagina, None, DPI_DE_LA_FRANJA))
                        suyas.append(lectura)
                    except Exception:  # noqa: BLE001 - se queda con lo que tenía
                        logger.debug("no se pudo rasterizar la página %s", pagina, exc_info=True)
                        hechas += 1
                if imagenes:
                    vuelo[lectores.submit(_leer_lote, lector, imagenes)] = suyas
                while len(vuelo) > self._workers:
                    for listo in alguno_listo(vuelo, self._control):
                        recoger(listo)
            for listo in completados(list(vuelo), self._control):
                recoger(listo)

    def _con_lo_releido(self, acta: ActaDeConsejo, texto: str) -> ActaDeConsejo:
        """El acta con los huecos llenados de una relectura; lo ya leído no se toca."""
        if self._perfil.completar is not None:
            return self._perfil.completar(acta, texto)
        nuevo = self._perfil.leer([texto])
        return replace(
            acta,
            numero=acta.numero or nuevo.numero,
            sesion=acta.sesion or nuevo.sesion,
            fecha=acta.fecha or nuevo.fecha,
            dia_impreso=acta.dia_impreso or (nuevo.dia_impreso if acta.fecha is None else None),
        )

    def _folios_por_la_pagina(self, source: PageSource, lecturas: list[_Lectura]) -> bool:
        """Los folios de todas las actas, leídos en la esquina de cada página y encadenados.

        La primera lectura -- las dos esquinas de cada acta en un mosaico, sin
        decir de qué hoja es cada número -- falla donde la esquina trae también
        el folio viejo tachado: en UPD3859792 dejó sin folio 8 de 9 actas, y la
        relectura exigía que la cuenta cuadrara exacta con las hojas con tinta,
        que se equivocan por una. Aquí se leen todas las páginas, diez por
        página facturada y con su etiqueta, con todos los números de cada
        esquina, y ``foliacion_por_pagina`` elige la cadena que sigue al libro.

        Devuelve si el libro resultó foliado página a página. Si no -- un libro
        foliado por hoja, con el vuelto sin número --, no toca nada.
        """
        armar = getattr(self._lector_de_folios, "armar_mosaico_etiquetado", None)
        leer = getattr(self._lector_de_folios, "leer_candidatos_etiquetados", None)
        if armar is None or leer is None:
            return False
        paginas = sorted({p for lectura in lecturas for p in range(lectura.tramo.desde, lectura.tramo.hasta + 1)})
        candidatos: dict[int, list[int]] = {}
        with hilos(LECTURAS_A_LA_VEZ) as proveedor:
            vuelo: list[Future] = []
            for inicio in range(0, len(paginas), FOLIOS_POR_MOSAICO):
                self._control.check()
                tanda = paginas[inicio : inicio + FOLIOS_POR_MOSAICO]
                imagen = armar(source, tanda)
                if imagen:
                    vuelo.append(proveedor.submit(leer, imagen, tanda))
            for hechas, futuro in enumerate(vuelo, start=1):
                aguardar(futuro, self._control)
                try:
                    candidatos.update(futuro.result())
                except Exception:  # noqa: BLE001 - esas hojas se quedan sin leer
                    logger.warning("no se pudo leer un mosaico de folios", exc_info=True)
                self._report(
                    ProgressEvent(
                        stage=Stage.INVENTORYING,
                        done=hechas,
                        total=len(vuelo),
                        detail=f"leyendo el folio de cada una de las {len(paginas)} páginas",
                    )
                )
        self._candidatos_de_folio = candidatos
        elegidos = foliacion_por_pagina(candidatos)
        if elegidos is None:
            return False
        for lectura in lecturas:
            # Las hojas con tinta en la esquina, si se midieron: un vuelto en
            # blanco al final no lleva folio y no se cuenta.
            primera = min(lectura.foliadas) if lectura.foliadas else lectura.tramo.desde
            ultima = max(lectura.foliadas) if lectura.foliadas else lectura.tramo.hasta
            inicial, final = folio_de_la_pagina(elegidos, primera), folio_de_la_pagina(elegidos, ultima)
            if inicial is None or final is None or final[0] < inicial[0]:
                continue
            antes = lectura.folios
            lectura.folios = FoliosDelActa(
                inicial=inicial[0], final=final[0], foliadas=len(lectura.foliadas)
            )
            deducidos = [
                que for que, (_folio, leido) in (("inicial", inicial), ("final", final)) if not leido
            ]
            if deducidos:
                lectura.deducido = (
                    f"el folio {' y el '.join(deducidos)} no se leyó en su esquina y se dedujo de la "
                    "foliación seguida del libro: revíselo en el papel"
                )
            elif antes.inicial is not None and (antes.inicial, antes.final) != (inicial[0], final[0]):
                lectura.deducido = (
                    f"en la primera lectura de las esquinas salió {antes.inicial} a {antes.final}; "
                    f"leídas hoja por hoja y encadenadas con el libro son {inicial[0]} a {final[0]}"
                )
            else:
                lectura.deducido = None
        return True

    def _folios_hoja_por_hoja(self, source: PageSource, lecturas: list[_Lectura]) -> None:
        """Las actas de consejo que se quedaron sin folio: la esquina de cada hoja suya, leída.

        La primera y la última esquina no cuadraron con las hojas del acta --
        «en las esquinas de las hojas 92 y 101 se leyó 290, 309» --, y entre
        dos lecturas malas no hay a cuál creerle. Leídas todas sus hojas, diez
        por página facturada y con la página impresa al lado de cada esquina, la
        foliación seguida del libro dice cuál está bien: confirma las que
        cuadran, corrige la que no y deduce la que no se leyó. Sólo con la IA, y
        sólo para las actas que lo necesitan.
        """
        if not self._perfil.lee_folio or self._perfil.folio_por_hoja:
            return
        if self._folios_por_la_pagina(source, lecturas):
            return
        armar = getattr(self._lector_de_folios, "armar_mosaico_etiquetado", None)
        leer = getattr(self._lector_de_folios, "leer_mosaico_etiquetado", None)
        if armar is None or leer is None:
            return
        sin_folio = [
            lectura for lectura in lecturas if lectura.folios.inicial is None and lectura.foliadas
        ]
        if not sin_folio:
            return
        orden = {
            pagina: puesto
            for puesto, pagina in enumerate(
                sorted({p for lectura in lecturas for p in lectura.foliadas}), start=1
            )
        }
        # Lo que ya se sabe, de las actas bien leídas: ancla la foliación.
        leidos: dict[int, int] = {}
        for lectura in lecturas:
            if lectura.foliadas and lectura.folios.inicial is not None:
                leidos[min(lectura.foliadas)] = lectura.folios.inicial
                if lectura.folios.final is not None:
                    leidos[max(lectura.foliadas)] = lectura.folios.final
        paginas = sorted({p for lectura in sin_folio for p in lectura.foliadas})
        ya_leidas = getattr(self, "_candidatos_de_folio", None)
        if ya_leidas:
            # Ya se leyeron todas las páginas buscando la foliación página a
            # página: no se paga dos veces la misma esquina.
            leidos.update({p: ya_leidas[p][0] for p in paginas if ya_leidas.get(p)})
            paginas = []
        with hilos(LECTURAS_A_LA_VEZ) as proveedor:
            vuelo: list[Future] = []
            for inicio in range(0, len(paginas), FOLIOS_POR_MOSAICO):
                self._control.check()
                tanda = paginas[inicio : inicio + FOLIOS_POR_MOSAICO]
                imagen = armar(source, tanda)
                if imagen:
                    vuelo.append(proveedor.submit(leer, imagen, tanda))
            for hechas, futuro in enumerate(vuelo, start=1):
                aguardar(futuro, self._control)
                try:
                    leidos.update(futuro.result())
                except Exception:  # noqa: BLE001 - esas hojas se quedan sin folio
                    logger.warning("no se pudo leer un mosaico de folios", exc_info=True)
                self._report(
                    ProgressEvent(
                        stage=Stage.INVENTORYING,
                        done=hechas,
                        total=len(vuelo),
                        detail=f"releyendo hoja por hoja el folio de {len(sin_folio)} acta(s)",
                    )
                )
        folios = folios_de_la_foliacion(leidos, orden)
        for lectura in sin_folio:
            primera, ultima = min(lectura.foliadas), max(lectura.foliadas)
            if primera not in folios or ultima not in folios:
                continue
            inicial, final = folios[primera][0], folios[ultima][0]
            # Cada hoja foliada es un folio: el acta los ocupa seguidos.
            if final - inicial + 1 != len(lectura.foliadas):
                continue
            lectura.folios = FoliosDelActa(
                inicial=inicial, final=final, foliadas=len(lectura.foliadas)
            )
            lectura.deducido = (
                "folios leídos hoja por hoja en las esquinas y cuadrados con la foliación "
                "seguida del libro (la primera lectura no cuadraba)"
            )

    # -- el nombre y la cédula, por consenso ----------------------------------

    def _nombres_por_consenso(
        self, source: PageSource, paginas: list[str], lecturas: list[_Lectura]
    ) -> None:
        """El nombre y la cédula de cada graduado, votados entre todas las lecturas de su hoja.

        Cada lectura se equivoca en un sitio distinto, y casi siempre alguna
        trae bien cada palabra. Se votan palabra a palabra (``consenso``); lo
        que no queda confirmado se lee otra vez -- la franja del nombre, gratis,
        y con la IA si se pidió -- y se vuelve a votar. Lo que siga dudoso lo
        dicen las observaciones.
        """
        # El acta colectiva no se vota: no decide un nombre sino una lista.
        graduados = [
            lectura
            for lectura in lecturas
            if lectura.acta.rotulo == ROTULO_DE_GRADO
            and not lectura.tramo.ceremonia
            and not lectura.acta.constancia
            and not lectura.colectiva
        ]
        # Las constancias no se votan -- su nombre lo dice la constancia --,
        # pero sí se cruzan con la lectura de la IA, como lo demás.
        for constancia_ in lecturas:
            if constancia_.acta.rotulo == ROTULO_DE_GRADO and constancia_.acta.constancia and not constancia_.colectiva:
                _nombre_de_la_ia(constancia_, nombres_conocidos())
        if not graduados:
            return
        conocidas = nombres_conocidos() | _palabras_del_libro(graduados, paginas, lecturas)
        self._de_pila, self._apellidos = _nombres_del_archivo()
        for lectura in graduados:
            self._decidir_nombre(lectura, conocidas)
        dudosos = [lectura for lectura in graduados if not lectura.nombre_confirmado and not self._manuscrito]
        if dudosos:
            self._releer_franjas_del_nombre(source, dudosos)
            for lectura in dudosos:
                self._decidir_nombre(lectura, conocidas)
        dudosos = [lectura for lectura in graduados if not lectura.nombre_confirmado and not self._manuscrito]
        if dudosos:
            self._nombres_con_la_ia(source, dudosos)
            for lectura in dudosos:
                self._decidir_nombre(lectura, conocidas)
        for lectura in graduados:
            _nombre_de_la_ia(lectura, conocidas)
            if lectura.nombre_dudoso and lectura.acta.nombre:
                lectura.razonado.append(
                    "nombre dudoso: las lecturas de la hoja no coinciden del todo; "
                    "revíselo en el papel"
                )

    def _decidir_nombre(self, lectura: _Lectura, conocidas: set[str]) -> None:
        acta = lectura.acta
        if lectura.nombre_leido is None:
            # Lo que se leyó antes de votar: cada votación parte de ahí y se
            # compara con eso, para que dos pasadas no lo vayan desviando.
            lectura.nombre_leido = acta.nombre or ""
        original = lectura.nombre_leido or None
        candidatos: list[tuple[str | None, float]] = [(original, PESO_DE_UNA_LECTURA)]
        candidatos += [
            (zona_del_nombre(texto, titulo=acta.titulo, conocidas=conocidas), peso)
            for texto, peso in lectura.textos
        ]
        votado = consenso(
            candidatos,
            conocidas,
            titulo=acta.titulo,
            de_pila=getattr(self, "_de_pila", ()),
            apellidos=getattr(self, "_apellidos", ()),
        )
        lectura.nombre_confirmado = votado.confirmado
        lectura.nombre_dudoso = votado.dudoso
        # Sólo se cambia por algo que parezca un nombre al menos tanto como lo
        # que había: el voto no puede empeorar una lectura buena.
        leidas = palabras_de(original, titulo=acta.titulo)
        repuestas = (
            sin_perder_conocidas(leidas, palabras_de(votado.nombre), conocidas)
            if votado.nombre
            else None
        )
        votado = replace(votado, nombre=" ".join(repuestas) if repuestas else None)
        mejora = votado.nombre is not None and calidad(
            palabras_de(votado.nombre), conocidas
        ) >= calidad(leidas, conocidas)
        if not mejora and acta.nombre != original:
            # Una pasada anterior lo cambió y ésta no lo sostiene: vuelve el leído.
            lectura.acta = replace(acta, nombre=original)
        if votado.nombre and votado.nombre != acta.nombre and mejora:
            lectura.acta = replace(
                acta,
                nombre=votado.nombre,
                dudas=(
                    *dudas_de(votado.nombre, acta.titulo),
                    *(d for d in acta.dudas if not d.startswith("el nombre")),
                ),
            )
        cedulas = [(lectura.acta.cedula, PESO_DE_UNA_LECTURA)]
        cedulas += [(cedula_leida(texto), peso) for texto, peso in lectura.textos]
        ganadora, acuerdo = consenso_de_cedulas(cedulas)
        if ganadora and acuerdo and ganadora != lectura.acta.cedula:
            lectura.acta = replace(lectura.acta, cedula=ganadora)

    def _releer_franjas_del_nombre(self, source: PageSource, dudosos: list[_Lectura]) -> None:
        """La franja del nombre de los graduados dudosos, leída otra vez con la tinta realzada."""
        trozos_de = getattr(source, "trozos_of", None)
        medida_de = getattr(source, "size_of", None)
        if not self._lectores_de_tinta_clara or trozos_de is None or medida_de is None:
            return
        trabajo: list[tuple[_Lectura, bytes]] = []
        for lectura in dudosos:
            self._control.check()
            pagina = lectura.tramo.desde + (lectura.acta.pagina or 1) - 1
            try:
                banda = _banda_del_nombre(trozos_de(pagina), *medida_de(pagina))
                if banda is None:
                    continue
                trabajo.append((lectura, source.render(pagina, banda, DPI_DE_RECUADRO)))
            except Exception:  # noqa: BLE001 - se queda con lo que tenía
                logger.debug("no se pudo recortar el nombre de la página %s", pagina, exc_info=True)
        if not trabajo:
            return
        with hilos(self._workers) as lectores:
            vuelo = [
                (lectura, lectores.submit(_leer_lote, lector, [imagen], varias="read_varias"))
                for lector in self._lectores_de_tinta_clara
                for lectura, imagen in trabajo
            ]
            for lectura, futuro in vuelo:
                aguardar(futuro, self._control)
                [(leido, error)] = _resultados_del_lote(futuro, 1)
                if error is None and leido is not None and leido.text.strip():
                    lectura.textos.append((leido.text, PESO_DE_UNA_LECTURA))
        self._report(
            ProgressEvent(
                stage=Stage.VERIFYING,
                done=len(trabajo),
                total=len(trabajo),
                detail=f"releyendo el nombre de {len(trabajo)} graduado(s) dudoso(s)",
            )
        )

    def _nombres_con_la_ia(self, source: PageSource, dudosos: list[_Lectura]) -> None:
        """La franja del nombre de los que siguen dudosos, leída por la IA: diez por página facturada.

        Sólo si el operador pidió la IA -- sin ella no hay lector -- y sólo para
        los nombres que las lecturas gratuitas no confirmaron.
        """
        armar = getattr(self._lector_de_folios, "armar_mosaico_de_franjas", None)
        leer = getattr(self._lector_de_folios, "leer_textos_etiquetados", None)
        trozos_de = getattr(source, "trozos_of", None)
        medida_de = getattr(source, "size_of", None)
        if armar is None or leer is None or trozos_de is None or medida_de is None:
            return
        franjas: list[tuple[int, Band, _Lectura]] = []
        for lectura in dudosos:
            pagina = lectura.tramo.desde + (lectura.acta.pagina or 1) - 1
            try:
                banda = _banda_del_nombre(trozos_de(pagina), *medida_de(pagina))
            except Exception:  # noqa: BLE001 - se queda con lo que tenía
                banda = None
            if banda is not None:
                franjas.append((pagina, banda, lectura))
        if not franjas:
            return
        de_la_pagina = {pagina: lectura for pagina, _b, lectura in franjas}
        with hilos(LECTURAS_A_LA_VEZ) as proveedor:
            vuelo: list[Future] = []
            for inicio in range(0, len(franjas), FOLIOS_POR_MOSAICO):
                self._control.check()
                tanda = franjas[inicio : inicio + FOLIOS_POR_MOSAICO]
                imagen = armar(source, [(pagina, banda) for pagina, banda, _l in tanda])
                if imagen:
                    vuelo.append(proveedor.submit(leer, imagen, [pagina for pagina, _b, _l in tanda]))
            for hechas, futuro in enumerate(vuelo, start=1):
                aguardar(futuro, self._control)
                try:
                    textos = futuro.result()
                except Exception:  # noqa: BLE001 - esos nombres se quedan como estaban
                    logger.warning("no se pudo leer un mosaico de nombres", exc_info=True)
                    continue
                for pagina, texto in textos.items():
                    de_la_pagina[pagina].textos.append((texto, PESO_DE_LA_IA))
                self._report(
                    ProgressEvent(
                        stage=Stage.VERIFYING,
                        done=hechas,
                        total=len(vuelo),
                        detail=f"leyendo con la IA el nombre de {len(franjas)} graduado(s) dudoso(s)",
                    )
                )

    def _leer_recuadros(self, source: PageSource, lecturas: list[_Lectura]) -> None:
        """El número del acta y la cédula leídos en su recuadro, cuando faltan.

        La capa del escáner a veces se salta un dato escrito a máquina -- el
        «04» de «ACTA DE GRADO No. 04» --, y releer la hoja entera no siempre lo
        recupera. El recuadro se sabe por el rótulo impreso, que sí está en la
        capa, y leer sólo ese trozo, con dígitos y a buena resolución, es lo
        que mejor lee el OCR de casa.
        """
        trozos_de = getattr(source, "trozos_of", None)
        medida_de = getattr(source, "size_of", None)
        if self._lector_de_cifras is None or trozos_de is None or medida_de is None:
            return
        for lectura in lecturas:
            acta = lectura.acta
            if lectura.tramo.ceremonia or acta.rotulo != ROTULO_DE_GRADO:
                continue
            if acta.numero and acta.cedula:
                continue
            self._control.check()
            pagina = lectura.tramo.desde + (acta.pagina or 1) - 1
            try:
                trozos = trozos_de(pagina)
                ancho, alto = medida_de(pagina)
            except Exception:  # noqa: BLE001 - se queda con lo que tenía
                continue
            leido = []
            if not acta.numero:
                cifras = self._cifras_en(source, pagina, recuadro_tras(trozos, "ACTA DE GRADO"), ancho, alto)
                if cifras:
                    leido.append(f"ACTA DE GRADO No. {cifras}")
            if not acta.cedula:
                cifras = self._cifras_en(source, pagina, recuadro_tras(trozos, "", antes="CIUDADANIA"), ancho, alto)
                if cifras:
                    leido.append(f"cedula de ciudadania No. {cifras}")
            if leido:
                lectura.acta = self._perfil.completar(acta, "\n".join(leido))

    def _cifras_en(self, source: PageSource, pagina: int, caja, ancho: float, alto: float) -> str | None:
        """Lo que el lector de cifras lee dentro de una caja de la página."""
        if caja is None or not ancho or not alto:
            return None
        x0, y0, x1, y1 = caja
        banda = Band(max(0.0, x0 / ancho), max(0.0, y0 / alto), min(1.0, x1 / ancho), min(1.0, y1 / alto))
        try:
            texto = self._lector_de_cifras.read(source.render(pagina, banda, DPI_DE_RECUADRO)).text
        except Exception:  # noqa: BLE001 - el recuadro no se leyó
            logger.debug("no se pudo leer el recuadro de la página %s", pagina, exc_info=True)
            return None
        return texto.strip() or None

    def _releer_lo_que_falta(self, source: PageSource, lecturas: list[_Lectura]) -> None:
        """Vuelve a leer la hoja de las actas a las que les falta algo.

        La capa de texto del escáner de los libros antiguos sale desordenada y
        rota: el nombre partido, la cédula con letras. Esas hojas se leen otra
        vez con Tesseract, que es gratis, y lo que todavía falte, con la IA si
        el operador la pidió: cada motor llena sólo los huecos que dejó el
        anterior, y la IA se paga sólo por las hojas que de verdad la necesitan.
        """
        falta = self._perfil.le_falta_algo
        completar = self._perfil.completar
        if falta is None or completar is None or self._manuscrito:
            # Un libro manuscrito ya lo leyó la IA entero: Tesseract no lee la
            # letra a mano, y a sus actas les «falta» siempre lo que el papel no
            # trae -- número, cédula --; releerlas era pagar dos veces por nada.
            return
        self._leer_franjas(source, lecturas)
        _unificar_titulos(lecturas)
        self._leer_recuadros(source, lecturas)
        # Gratis antes que de pago: lo que la tinta clara deja leer no se paga.
        self._releer_con_tinta_clara(source, lecturas)
        for motor in (self._ocr, self._relector_de_pago):
            if motor is None:
                continue
            pendientes = [
                lectura
                for lectura in lecturas
                if not lectura.tramo.ceremonia and falta(lectura.acta)
            ]
            if not pendientes:
                return
            with hilos(self._workers) as lectores:
                vuelo: list[tuple[_Lectura, Future]] = []
                for lectura in pendientes:
                    self._control.check()
                    pagina = lectura.tramo.desde + (lectura.acta.pagina or 1) - 1
                    try:
                        imagen = source.render(pagina, None, DPI_DE_LECTURA)
                    except Exception:  # noqa: BLE001 - se queda con lo que tenía
                        logger.warning("no se pudo rasterizar la página %s", pagina, exc_info=True)
                        continue
                    vuelo.append((lectura, lectores.submit(motor.read, imagen)))
                for hechas, (lectura, futuro) in enumerate(vuelo, start=1):
                    aguardar(futuro, self._control)
                    try:
                        texto = futuro.result().text
                    except Exception:  # noqa: BLE001 - se queda con lo que tenía
                        logger.warning("no se pudo releer un acta", exc_info=True)
                        continue
                    peso = PESO_DE_LA_IA if motor is self._relector_de_pago else PESO_DE_UNA_LECTURA
                    if motor is self._relector_de_pago:
                        lectura.texto_de_la_ia = texto
                    lectura.textos.append((texto, peso))
                    lectura.acta = completar(lectura.acta, texto)
                    self._report(
                        ProgressEvent(
                            stage=Stage.VERIFYING,
                            done=hechas,
                            total=len(vuelo),
                            detail=f"releyendo {len(vuelo)} acta(s) a las que les faltaba algo",
                        )
                    )

    def _verificar_con_la_ia(self, source: PageSource, lecturas: list[_Lectura]) -> None:
        """Con «OCR + IA», la IA lee toda hoja que da una fila, y cada dato se cruza con el OCR.

        Hasta aquí la IA leía sólo las hojas a las que les faltaba algo: un
        número de acta o una cédula mal leídos pero completos se entregaban sin
        aviso. Lo pidió el operador el 2026-10-31: «que el bot se asegure de
        que lo que entrega sí es lo que está en el PDF». La hoja del encabezado
        de cada acta -- o la del graduado -- se lee otra vez con la IA, que
        cobra por página (del orden de un dólar por mil), y cada campo se
        decide con ``decidir_con_la_ia``: lo que discrepa va a observaciones
        con las dos lecturas.
        """
        lector = self._relector_de_pago
        if lector is None:
            return
        # Las constancias también: su capa es la peor del libro (UPD3859800,
        # 1981-1983: «ESPERAN^ VIAM» por ESPERANZA VIANA).
        propias = [lectura for lectura in lecturas if not lectura.tramo.ceremonia]
        pendientes = [lectura for lectura in propias if lectura.texto_de_la_ia is None]
        with hilos(self._workers) as lectores:
            vuelo: list[tuple[_Lectura, Future]] = []
            for lectura in pendientes:
                self._control.check()
                pagina = lectura.tramo.desde + (lectura.acta.pagina or 1) - 1
                try:
                    imagen = source.render(pagina, None, DPI_DE_LECTURA)
                except Exception:  # noqa: BLE001 - se queda con lo del OCR
                    logger.warning("no se pudo rasterizar la página %s", pagina, exc_info=True)
                    continue
                vuelo.append((lectura, lectores.submit(lector.read, imagen)))
            for hechas, (lectura, futuro) in enumerate(vuelo, start=1):
                aguardar(futuro, self._control)
                try:
                    lectura.texto_de_la_ia = futuro.result().text or ""
                except Exception:  # noqa: BLE001 - se queda con lo del OCR
                    logger.warning("la IA no pudo leer un acta", exc_info=True)
                    continue
                if lectura.acta.rotulo == ROTULO_DE_GRADO:
                    lectura.textos.append((lectura.texto_de_la_ia, PESO_DE_LA_IA))
                self._report(
                    ProgressEvent(
                        stage=Stage.VERIFYING,
                        done=hechas,
                        total=len(vuelo),
                        detail=f"comprobando con la IA {len(vuelo)} acta(s)",
                    )
                )
        self._leer_los_datos_con_la_ia(propias)
        for lectura in propias:
            # El acta colectiva no se cruza campo a campo: su nombre y su cédula
            # son los de cada graduado de la lista, no los de la hoja.
            if lectura.texto_de_la_ia and not lectura.colectiva:
                self._cruzar_con_la_ia(lectura)
        self._cedulas_con_zoom(source, [lectura for lectura in propias if not lectura.colectiva])

    def _cedulas_con_zoom(self, source: PageSource, lecturas: list[_Lectura]) -> None:
        """La cédula que ni la página entera ni la IA leyeron, buscada en su zona ampliada.

        La máquina de escribir la dejó a veces encima de «juramento», y leída
        con la hoja entera se pierde: «22.793.650» y «45.760.742» en UPD3859808
        (págs. 138 y 156, comprobadas en el papel). Se recorta la franja de
        «portador» a «juramento», se amplía y la lee la IA. Una página
        facturada por hoja, sólo para las que siguen sin cédula.
        """
        lector = self._relector_de_pago
        trozos_de = getattr(source, "trozos_of", None)
        medida_de = getattr(source, "size_of", None)
        if lector is None or trozos_de is None or medida_de is None or self._manuscrito:
            return  # las actas manuscritas de 1924-1946 no llevan cédula
        sin_cedula = [
            lectura
            for lectura in lecturas
            if lectura.acta.rotulo == ROTULO_DE_GRADO
            and not lectura.tramo.ceremonia
            and not lectura.acta.constancia
            and not lectura.acta.cedula
        ]
        for lectura in sin_cedula:
            self._control.check()
            pagina = lectura.tramo.desde + (lectura.acta.pagina or 1) - 1
            try:
                banda = _banda_de_la_cedula(trozos_de(pagina), *medida_de(pagina))
                if banda is None:
                    continue
                texto = lector.read(source.render(pagina, banda, DPI_DE_LA_ZONA)).text or ""
            except Exception:  # noqa: BLE001 - se queda sin cédula, y lo dice
                logger.warning("no se pudo leer la zona de la cédula de la página %s", pagina, exc_info=True)
                continue
            cedula = cedula_leida(texto) or _cedula_suelta(texto)
            if cedula:
                lectura.acta = replace(lectura.acta, cedula=cedula)
                lectura.razonado.append(
                    "la cédula se leyó con la IA en su zona ampliada (la máquina la escribió "
                    "encima del texto impreso): revísela en el papel"
                )

    @property
    def _manuscrito(self) -> bool:
        """Si el libro que se lee es manuscrito y ya lo leyó entero la IA."""
        return bool(getattr(self, "_textos_de_la_ia", None))

    def _es_manuscrito(self, source: PageSource) -> bool:
        """Si el libro está escrito a mano: casi ninguna página trae en su capa las palabras de un acta impresa.

        Un acta a máquina o impresa, por mal escaneada que esté, deja en la capa
        «UNIVERSIDAD», «CIUDAD», «GRADO»… La letra a mano de 1924-1946 deja
        basura («•V- ) 'ñ (P i*!?»). Cuesta milésimas: es la capa.
        """
        total = source.page_count
        if total < PAGINAS_PARA_JUZGAR_LA_LETRA:
            return False
        impresas = 0
        for numero in range(1, total + 1):
            plano = unicodedata.normalize("NFD", self._capa(source, numero)).encode("ascii", "ignore").decode().upper()
            if sum(1 for palabra in _PALABRAS_DE_UN_ACTA_IMPRESA if palabra in plano) >= 2:
                impresas += 1
        return impresas < total * PARTE_IMPRESA_DE_UN_LIBRO_A_MAQUINA

    def _nombres_manuscritos(self, source: PageSource, lecturas: list[_Lectura]) -> None:
        """El nombre de cada acta manuscrita, confirmado entre tres lecturas o mandado a revisión.

        El acta lo escribe dos veces a mano -- arriba como título y en «del
        alumno …» --; si las dos coinciden y el diccionario conoce cada
        palabra, está confirmado. Si no, se lee una tercera vez el renglón de
        arriba, recortado y ampliado, y se vota (``nombre_de_tres_lecturas``).
        Lo que no se confirma va a revisión con las tres lecturas: el operador
        pidió cero errores, y con letra de 1925 eso es no dar por seguro lo que
        no lo es (UPD3860000: «Espiulla», «Espinella», en el papel Espriella).
        """
        if not self._manuscrito or self._relector_de_pago is None:
            return
        conocidas = nombres_conocidos()
        pendientes: list[tuple[_Lectura, str | None, str | None]] = []
        for lectura in lecturas:
            if lectura.tramo.ceremonia or lectura.acta.rotulo != ROTULO_DE_GRADO or not lectura.texto_de_la_ia:
                continue
            if lectura.colectiva:
                continue  # sus graduados son los de su lista, no un nombre por hoja
            # En el libro colectivo el acta no repite el nombre arriba, y lo que
            # hay arriba de su hoja es la cola de la anterior: se lee de su
            # frase, sin pagar el renglón ampliado (UPD3859802, 2026-11-12).
            arriba, del_texto = (None, None) if lectura.del_libro is not None else lecturas_del_nombre(lectura.texto_de_la_ia)
            if not (arriba or del_texto):
                # El acta a mano de 1988-2012, que no repite el nombre arriba:
                # «… a la estudiante NURY VARELA ESCUDERO, portadora de la
                # cédula» en el texto que leyó la IA (UPD3859802 pág. 110,
                # 2026-11-12; se quedaba con la nota al margen «Post-grado»).
                leido = nombre_limpio(
                    leer_acta_de_grado([lectura.texto_de_la_ia]).nombre, lectura.acta.titulo, conocidas
                )
                # El nombre de pila en cursiva se lee mal en la página entera
                # («REARMÉN SIGRÍA» por CARMEN SOFÍA, pág. 1): si el diccionario
                # no confirma cada palabra, se relee la franja del medio
                # ampliada y se vota (el operador, 2026-11-13: «releer el
                # renglón del nombre»). Lo que no se confirma va a revisión.
                if leido and not all(clave(p) in conocidas for p in leido.split()):
                    ampliado = self._franja_del_nombre(source, lectura, leido)
                    votado, duda = nombre_de_tres_lecturas(None, leido, ampliado, conocidas)
                    if votado:
                        leido = nombre_limpio(votado, lectura.acta.titulo, conocidas) or leido
                    if duda:
                        lectura.razonado.append(duda)
                if leido and len(leido.split()) >= 2 and clave(leido) != clave(lectura.acta.nombre or ""):
                    if lectura.acta.nombre:
                        lectura.razonado.append(
                            f"el nombre: se leyó «{lectura.acta.nombre}» y la IA leyó en el acta manuscrita "
                            f"«{leido}»; se dejó lo de la IA: revíselo en el papel"
                        )
                    lectura.acta = replace(lectura.acta, nombre=leido)
                    lectura.nombre_dudoso = False
                continue
            # Las notas del voto general no valen aquí: éste decide el nombre.
            lectura.razonado = [
                r for r in lectura.razonado if not r.startswith(("el nombre:", "nombre dudoso"))
            ]
            if arriba and arriba == del_texto and all(clave(p) in conocidas for p in arriba.split()):
                lectura.acta = replace(lectura.acta, nombre=arriba)
                lectura.nombre_dudoso = False
                continue
            pendientes.append((lectura, arriba, del_texto))
        with hilos(LECTURAS_A_LA_VEZ) as proveedor:
            vuelo = [
                (lectura, arriba, del_texto, proveedor.submit(self._renglon_del_nombre, source, lectura, arriba or del_texto))
                for lectura, arriba, del_texto in pendientes
            ]
            for hechas, (lectura, arriba, del_texto, futuro) in enumerate(vuelo, start=1):
                aguardar(futuro, self._control)
                try:
                    ampliado = futuro.result()
                except Exception:  # noqa: BLE001 - se vota con las dos que hay
                    logger.warning("no se pudo leer ampliado el nombre de un acta", exc_info=True)
                    ampliado = None
                nombre, duda = nombre_de_tres_lecturas(arriba, del_texto, ampliado, conocidas)
                if nombre:
                    lectura.acta = replace(lectura.acta, nombre=nombre)
                lectura.nombre_dudoso = False
                if duda:
                    lectura.razonado.append(duda)
                self._report(
                    ProgressEvent(
                        stage=Stage.VERIFYING,
                        done=hechas,
                        total=len(vuelo),
                        detail=f"confirmando el nombre de {len(vuelo)} acta(s) manuscrita(s)",
                    )
                )

    def _fechas_manuscritas(self, source: PageSource, lecturas: list[_Lectura]) -> None:
        """La fecha de un acta manuscrita que la página entera no dejó leer, en sus renglones ampliados.

        «a ter de Septiembre de 1935», «a parte de setiembre» (UPD3859999): el
        día escrito a mano no se entiende a página entera. Se leen ampliados
        los primeros renglones del acta, sólo de las que siguen sin fecha; si
        tampoco así, queda N/A: no se inventa el día.
        """
        if not self._manuscrito or self._relector_de_pago is None:
            return
        # Las del libro colectivo no: empiezan a mitad de hoja, y los renglones
        # de arriba son la cola de la anterior; se pagaría para leer su fecha.
        sin_fecha = [
            lectura
            for lectura in lecturas
            if not lectura.tramo.ceremonia
            and lectura.acta.rotulo == ROTULO_DE_GRADO
            and lectura.acta.fecha is None
            and lectura.del_libro is None
        ]
        for lectura in sin_fecha:
            self._control.check()
            pagina = lectura.tramo.desde + (lectura.acta.pagina or 1) - 1
            for banda, girar in ((Band(0.0, 0.05, 1.0, 0.25), False), (Band(0.0, 0.75, 1.0, 0.95), True)):
                try:
                    texto = self._relector_de_pago.read(_renglon(source, pagina, banda, DPI_DEL_RENGLON_DEL_NOMBRE, girar)).text or ""
                except Exception:  # noqa: BLE001 - se queda sin fecha, y lo dice
                    logger.warning("no se pudo leer ampliada la fecha de la página %s", pagina, exc_info=True)
                    break
                fecha = fecha_de_grado(texto)
                if fecha is not None:
                    lectura.acta = replace(lectura.acta, fecha=fecha)
                    lectura.razonado.append(
                        "la fecha se leyó en los renglones ampliados del acta (a página entera no se entendía): "
                        "revísela en el papel"
                    )
                    break

    def _releer_los_nombres_dudosos(self, source: PageSource, lecturas: list[_Lectura]) -> None:
        """El nombre en que el OCR y la IA no coinciden, releído en su franja ampliada y votado.

        Lo eligió el operador el 2026-11-13 ante la pág. 1 de UPD3859802: la IA
        leyó «REARMÉN SIGRÍA MENDOZA MORENO» por CARMEN SOFÍA. Sólo con «OCR +
        IA», sólo si las lecturas discreparon en el nombre y el diccionario no
        conoce sus nombres de pila: donde coinciden -- las actas a máquina -- no
        se gasta nada. Una página pagada por acta releída; lo que el voto no
        confirma va a revisión con las lecturas.
        """
        if self._relector_de_pago is None:
            return
        conocidas = nombres_conocidos()
        for lectura in lecturas:
            acta = lectura.acta
            if lectura.tramo.ceremonia or acta.rotulo != ROTULO_DE_GRADO or lectura.colectiva or not acta.nombre:
                continue
            discreparon = any(r.startswith("el nombre:") for r in lectura.razonado)
            de_pila = [clave(p) for p in acta.nombre.split()[:2]]
            if not discreparon or all(p in conocidas for p in de_pila):
                continue
            ampliado = self._franja_del_nombre(source, lectura, acta.nombre)
            if not ampliado:
                continue
            # Si los nombres de pila no se parecen entre las dos lecturas y el
            # diccionario no conoce ninguno, no se adivina: «REARMÉN SIGRÍA»,
            # «KARMAN SIGIA» y el papel dice CARMEN SOFÍA. Va a revisión con las
            # lecturas; los apellidos, que coinciden, se quedan.
            pila_ampliada = [clave(p) for p in ampliado.split()[:2]]
            if not any(p in conocidas for p in pila_ampliada) and any(
                difflib.SequenceMatcher(None, a, b).ratio() < PARECIDO_DE_LOS_NOMBRES_DE_PILA
                for a, b in zip(de_pila, pila_ampliada, strict=False)
            ):
                lectura.razonado.append(
                    f"los nombres de pila no se confirmaron: la página leyó «{acta.nombre}» y su franja ampliada "
                    f"«{ampliado}»; la letra a mano no se deja leer con certeza: revíselo en el papel"
                )
                lectura.nombre_dudoso = True
                continue
            votado, duda = nombre_de_tres_lecturas(None, acta.nombre, ampliado, conocidas)
            votado = nombre_limpio(votado, acta.titulo, conocidas) if votado else None
            if votado and clave(votado) != clave(acta.nombre):
                lectura.razonado.append(
                    f"el nombre: la página dio «{acta.nombre}» y su franja ampliada «{ampliado}»; se votó «{votado}»"
                )
                lectura.acta = replace(acta, nombre=votado)
            if duda:
                lectura.razonado.append(duda)

    def _franja_del_nombre(self, source: PageSource, lectura: _Lectura, referencia: str) -> str | None:
        """El nombre del acta a mano de 1988-2012, de la franja del medio ampliada y leída por la IA.

        En estas actas «al estudiante … portador» cae a media hoja, a una altura
        que cambia de una a otra: se lee la franja del 20 al 70 % de la hoja a
        ``DPI_DE_LA_FRANJA_DEL_NOMBRE``, una página pagada. Vale si comparte
        alguna palabra -- un apellido -- con lo leído en la página entera.
        """
        if self._relector_de_pago is None:
            return None
        pagina = lectura.tramo.desde + (lectura.acta.pagina or 1) - 1
        try:
            imagen = source.render(pagina, Band(0.0, 0.2, 1.0, 0.7), DPI_DE_LA_FRANJA_DEL_NOMBRE)
            texto = self._relector_de_pago.read(imagen).text or ""
        except Exception:  # noqa: BLE001 - se vota con lo que hay
            logger.warning("no se pudo releer la franja del nombre", exc_info=True)
            return None
        leido = leer_acta_de_grado([texto]).nombre
        if leido and set(clave(p) for p in referencia.split()) & set(clave(p) for p in leido.split()):
            return leido
        return None

    def _renglon_del_nombre(self, source: PageSource, lectura: _Lectura, referencia: str) -> str | None:
        """El nombre del renglón de arriba del acta, recortado, ampliado y leído por la IA.

        Arriba; y si ahí no está -- la hoja escaneada de cabeza --, abajo, con
        la imagen girada. Vale si comparte alguna palabra con lo leído en la página.
        """
        from ..domain.acta_grado import _nombre_de_arriba

        pagina = lectura.tramo.desde + (lectura.acta.pagina or 1) - 1
        palabras = set(referencia.split())
        for banda, girar in ((Band(0.1, 0.0, 0.9, 0.1), False), (Band(0.1, 0.9, 0.9, 1.0), True)):
            imagen = _renglon(source, pagina, banda, DPI_DEL_RENGLON_DEL_NOMBRE, girar)
            leido = _nombre_de_arriba(self._relector_de_pago.read(imagen).text or "")
            if leido and palabras & set(leido.split()):
                return leido
        return None

    def _leer_el_libro_con_la_ia(
        self, source: PageSource, total: int, solo: Sequence[int] | None = None
    ) -> dict[int, str]:
        """Cada página del libro leída por la IA: lo que dice, por número de página.

        Sólo con «OCR + IA». La IA lee la letra a mano de los años 20 y 40, y
        también la hoja escaneada de cabeza. Una página facturada por página.
        Con ``solo``, únicamente esas páginas.
        """
        lector = self._relector_de_pago
        if lector is None:
            return {}
        leidas: dict[int, str] = {}
        with hilos(self._workers) as lectores:
            vuelo: list[tuple[int, Future]] = []
            for numero in solo if solo is not None else range(1, total + 1):
                self._control.check()
                try:
                    imagen = source.render(numero, None, DPI_DEL_MANUSCRITO)
                except Exception:  # noqa: BLE001 - esa página se queda como estaba
                    logger.warning("no se pudo rasterizar la página %s", numero, exc_info=True)
                    continue
                vuelo.append((numero, lectores.submit(lector.read, imagen)))
            for hechas, (numero, futuro) in enumerate(vuelo, start=1):
                aguardar(futuro, self._control)
                try:
                    leidas[numero] = futuro.result().text or ""
                except Exception:  # noqa: BLE001 - esa página se queda como estaba
                    logger.warning("la IA no pudo leer la página %s", numero, exc_info=True)
                self._report(
                    ProgressEvent(
                        stage=Stage.VERIFYING,
                        done=hechas,
                        total=len(vuelo),
                        detail=f"leyendo con la IA el libro manuscrito ({len(vuelo)} páginas)",
                    )
                )
        self._releer_los_bucles(source, leidas)
        return leidas

    def _releer_los_bucles(self, source: PageSource, leidas: dict[int, str]) -> None:
        """La hoja que la IA leyó en bucle, releída en dos mitades con más zoom.

        La IA a veces lee bien el principio de la hoja y se queda repitiendo un
        trozo -- «1.1.1.1…» --: la hoja 80 de UPD3859802 trae ocho graduados y
        devolvió uno; los otros siete no llegaban al inventario (2026-11-13).
        Cada mitad es media hoja: la imagen más pequeña no la hace entrar en el
        bucle. Se queda la relectura sólo si trae menos renglones en bucle; si
        no, la de antes, y el acta avisa de los graduados que faltan. Dos
        lecturas de pago por hoja en bucle, nunca más.
        """
        lector = self._relector_de_pago
        en_bucle = sorted(numero for numero, texto in leidas.items() if renglones_en_bucle(texto))
        if lector is None or not en_bucle:
            return
        for numero in en_bucle:
            self._control.check()
            try:
                mitades = [lector.read(source.render(numero, banda, DPI_DE_LA_MITAD)).text or "" for banda in MITADES_DE_LA_HOJA]
            except Exception:  # noqa: BLE001 - la hoja se queda con su primera lectura
                logger.warning("la IA no pudo releer la hoja %s en dos mitades", numero, exc_info=True)
                continue
            releida = "\n".join(mitad for mitad in mitades if mitad.strip())
            if all(mitad.strip() for mitad in mitades) and renglones_en_bucle(releida) < renglones_en_bucle(leidas[numero]):
                logger.info("la hoja %s se leyó en bucle y se releyó en dos mitades", numero)
                leidas[numero] = releida

    def _con_todo_el_libro_leido(self, source: PageSource, paginas: list[str]) -> list[str]:
        """El libro colectivo con todas sus hojas leídas por la IA: la que falló, leída otra vez.

        En el libro colectivo una hoja sin leer parte un acta -- su lista sigue
        en ella -- y la capa no la suple: es basura. Sólo las que la IA no
        devolvió, una vez; no se paga dos veces la misma hoja.
        """
        faltan = [numero for numero in range(1, len(paginas) + 1) if numero not in self._textos_de_la_ia]
        if faltan:
            self._textos_de_la_ia.update(self._leer_el_libro_con_la_ia(source, len(paginas), faltan))
        return [self._textos_de_la_ia.get(numero) or texto for numero, texto in enumerate(paginas, 1)]

    def _leer_las_actas_colectivas(self, lecturas: list[_Lectura]) -> None:
        """El número, la fecha, el título y los graduados de cada acta colectiva, leídos por la IA y por regla.

        El lector de texto de la IA lee el acta entera -- su texto cortado
        donde empieza la siguiente -- como una persona: junta el nombre partido
        entre renglones y no toma al rector por graduado. Lo que devuelve se
        valida contra el texto (``lectura_colectiva_de_la_ia``) y se completa con
        lo que la regla lee de la lista numerada (``graduados_de_la_lista``),
        que es también lo que queda sin la IA. Se paga por tokens, no por página.
        """
        colectivas = [lectura for lectura in lecturas if lectura.colectiva and lectura.del_libro is not None]
        if not colectivas:
            return
        lector = self._lector_de_actas_colectivas
        respuestas: dict[int, str] = {}
        if lector is not None:
            with hilos(LECTURAS_A_LA_VEZ) as proveedor:
                # La anulada y la que quedó sin terminar no traen lista: no se
                # paga por leerla (hojas 138 y 144-145).
                vuelo = [
                    (indice, proveedor.submit(lector.resumir, lectura.del_libro.texto))  # type: ignore[union-attr]
                    for indice, lectura in enumerate(colectivas)
                    if not lectura.anulada
                ]
                for hechas, (indice, futuro) in enumerate(vuelo, start=1):
                    aguardar(futuro, self._control)
                    try:
                        respuestas[indice] = futuro.result()
                    except Exception:  # noqa: BLE001 - se queda con la lista leída por regla
                        logger.warning("la IA no pudo leer la lista de un acta colectiva", exc_info=True)
                    self._report(
                        ProgressEvent(
                            stage=Stage.VERIFYING,
                            done=hechas,
                            total=len(vuelo),
                            detail=f"leyendo con la IA los graduados de {len(vuelo)} acta(s) colectiva(s)",
                        )
                    )
        leidas = {
            id(lectura): lectura_colectiva_de_la_ia(respuestas.get(indice, ""), lectura.del_libro.texto)  # type: ignore[union-attr]
            for indice, lectura in enumerate(colectivas)
        }
        # En el orden del libro: el número de cada acta sigue la serie de la
        # anterior -- 054… las de Enfermería, 120… las de posgrado, que se
        # alternan -- y la abreviada lleva la fecha de la ceremonia de arriba.
        con_respuesta = {id(colectivas[indice]) for indice in respuestas}
        ultimo_de_la_serie: dict[str, str] = {}
        fecha_anterior: date | None = None
        for lectura in lecturas:
            if lectura.del_libro is None or lectura.tramo.ceremonia:
                continue
            if lectura.colectiva:
                self._leer_una_colectiva(
                    lectura,
                    leidas[id(lectura)],
                    sin_la_ia=lector is not None and id(lectura) not in con_respuesta,
                    ultimo_de_la_serie=ultimo_de_la_serie,
                    fecha_anterior=fecha_anterior,
                )
            numero = lectura.acta.numero or ""
            if len(numero) >= LARGO_DE_LA_SERIE:
                ultimo_de_la_serie[numero[:3]] = lectura.numero_hasta or numero
            fecha_anterior = lectura.acta.fecha or fecha_anterior
        _titulo_comun_del_libro(colectivas)

    def _leer_una_colectiva(
        self,
        lectura: _Lectura,
        leida,
        *,
        sin_la_ia: bool,
        ultimo_de_la_serie: Mapping[str, str],
        fecha_anterior: date | None,
    ) -> None:
        """Los graduados, el número, la fecha y el título de un acta colectiva, con lo que la IA leyó y lo que dice la lista.

        Cada cédula con su nombre por su renglón (``juntar_graduados``); el
        número, el del encabezado -- la IA sólo si su número está en el
        encabezado, no el de la resolución -- arreglado con la lista y la serie
        (``rango_reparado``); la lista contra lo que el acta numera o declara:
        el graduado que falta se dice. El acta anulada no lleva graduados.
        """
        texto = lectura.del_libro.texto  # type: ignore[union-attr]
        if lectura.anulada:
            lectura.graduados = []
        else:
            lectura.graduados = sin_quien_firma(
                juntar_graduados(leida.graduados, graduados_de_la_lista(texto), texto), texto
            )
        if sin_la_ia and lectura.graduados:
            lectura.razonado.append(
                "la IA no pudo leer el acta: sus graduados se leyeron de la lista por regla; revíselos en el papel"
            )
        acta = lectura.acta
        desde, hasta = acta.numero, lectura.numero_hasta
        if not desde and leida.desde and numero_en_el_encabezado(leida.desde, texto):
            desde, hasta = leida.desde, leida.hasta
        elif desde and not hasta and leida.hasta and leida.desde == desde:
            # El rango que la regla no vio y la IA sí, empezando por el mismo número.
            hasta = leida.hasta
        cuantos = len(lectura.graduados)
        if desde and len(desde) >= LARGO_DE_LA_SERIE - 1 and cuantos:
            desde, hasta, nota = rango_reparado(desde, hasta, cuantos, ultimo_de_la_serie.get(desde[:3]))
            if nota:
                lectura.razonado.append(nota)
        lectura.numero_hasta = hasta
        if not lectura.anulada:
            esperados = max(puestos_de_la_lista(texto), estudiantes_declarados(texto) or 0)
            if esperados > cuantos:
                lectura.razonado.append(
                    f"la lista del acta numera {esperados} graduado(s) y se leyeron {cuantos}: faltan "
                    f"{esperados - cuantos}; revíselos en el papel"
                )
        fecha = acta.fecha or leida.fecha
        if fecha is None and fecha_anterior is not None and es_acta_abreviada(texto):
            fecha = fecha_anterior
            lectura.razonado.append(
                f"el acta no repite la fecha: es la de la ceremonia del acta anterior "
                f"({fecha_anterior.strftime('%d-%m-%Y')}); revísela en el papel"
            )
        lectura.acta = replace(acta, numero=desde, fecha=fecha, titulo=leida.titulo or acta.titulo)

    def _leer_los_datos_con_la_ia(self, lecturas: list[_Lectura]) -> None:
        """Número, fecha, título, nombre y cédula de cada graduado, leídos por la IA como una persona.

        El texto ya lo sacó el OCR de pago; el lector de texto lo entiende aunque
        la máquina de escribir dejara los datos corridos de sus renglones -- «al
        estudiante FAIMA / LUZ FELFLE CASTILLA», el título en dos renglones
        (UPD3859808, 2026-10-31) --. Se paga por tokens, unos centavos por libro,
        y ``datos_de_la_ia`` sólo deja lo que la hoja dice.
        """
        lector = self._lector_de_datos
        # El acta colectiva no: no tiene un graduado sino una lista, y la lee
        # su propio lector (``_leer_las_actas_colectivas``).
        graduados = [
            lectura
            for lectura in lecturas
            if lectura.texto_de_la_ia
            and lectura.acta.rotulo == ROTULO_DE_GRADO
            and not lectura.tramo.ceremonia
            and not lectura.colectiva
        ]
        if lector is None or not graduados:
            return
        with hilos(LECTURAS_A_LA_VEZ) as proveedor:
            vuelo = [(lectura, proveedor.submit(lector.resumir, lectura.texto_de_la_ia)) for lectura in graduados]
            for hechas, (lectura, futuro) in enumerate(vuelo, start=1):
                aguardar(futuro, self._control)
                try:
                    lectura.datos_de_la_ia = datos_de_la_ia(futuro.result(), lectura.texto_de_la_ia or "")
                except Exception:  # noqa: BLE001 - se queda con lo que leyeron el OCR y la IA
                    logger.warning("la IA no pudo leer los datos de un acta", exc_info=True)
                self._report(
                    ProgressEvent(
                        stage=Stage.VERIFYING,
                        done=hechas,
                        total=len(vuelo),
                        detail=f"leyendo con la IA los datos de {len(vuelo)} graduado(s)",
                    )
                )

    def _cruzar_con_la_ia(self, lectura: _Lectura) -> None:
        """Cada campo del acta decidido entre el OCR y la IA; lo que discrepe, a observaciones."""
        acta = lectura.acta
        leida = self._perfil.leer([lectura.texto_de_la_ia or ""])
        datos = lectura.datos_de_la_ia
        # Lo que el lector de texto entendió manda sobre lo que la regla saca
        # del mismo texto: con los datos corridos, la regla toma el pedazo de
        # otro renglón («FAIMA» por título).
        de_la_ia = replace(leida, **{campo: datos[campo] for campo in ("numero", "fecha", "titulo", "cedula") if campo in datos})
        gratuitas = [
            self._perfil.leer([texto]) for texto, peso in lectura.textos if peso < PESO_DE_LA_IA
        ]
        cambios: dict[str, object] = {}
        for campo, nombre, igual, mostrar in _CAMPOS_QUE_CRUZA_LA_IA:
            if campo == "cedula" and acta.rotulo != ROTULO_DE_GRADO:
                continue
            actual = getattr(acta, campo)
            if campo == "titulo" and actual is not None and not es_un_titulo(actual):
                actual = None  # «FAIMA», «FECHA»: un pedazo de otro renglón, no un título
            apoyos = sum(
                1
                for otra in gratuitas
                if getattr(otra, campo) is not None and actual is not None and igual(getattr(otra, campo), actual)
            )
            # Si el lector de texto y la regla leen lo mismo en la hoja de la IA,
            # son dos lecturas que lo confirman: el «8» que tres lecturas del OCR
            # sacaron de la misma capa rota no les gana (UPD3859808, acta 03).
            confirmada = campo in datos and getattr(leida, campo) is not None and igual(getattr(leida, campo), datos[campo])
            valor, nota = decidir_con_la_ia(
                nombre, actual, getattr(de_la_ia, campo), 0 if confirmada else apoyos, igual=igual, mostrar=mostrar
            )
            if valor is not actual:
                cambios[campo] = valor
            if nota:
                lectura.razonado.append(nota)
        if cambios.get("numero") is not None and acta.rotulo != ROTULO_DE_GRADO:
            # El número de la IA trae su «BIS» y su clase de sesión con él.
            cambios["bis"] = de_la_ia.bis
            cambios["sesion"] = de_la_ia.sesion or acta.sesion
        if cambios:
            lectura.acta = replace(acta, **cambios)
        if self._perfil.completar is not None:
            # Los huecos que siguen -- el nombre, en un graduado -- los llena la IA.
            lectura.acta = self._perfil.completar(lectura.acta, lectura.texto_de_la_ia or "")

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
        with hilos(LECTURAS_A_LA_VEZ) as proveedor:
            pendientes: list[tuple[_Lectura, str, Future]] = []
            for lectura in lecturas:
                self._control.check()
                lectura.folios, futuro = self._pedir_folio(source, lectura, proveedor)
                if futuro is not None:
                    pendientes.append((lectura, "folio", futuro))
                texto = texto_para_resumir(
                    paginas[lectura.tramo.desde - 1 : lectura.tramo.hasta], repetidos=repetidos
                )
                if not self._perfil.con_resumen:
                    # Las actas de grado no llevan resumen: no se pide ni se
                    # anota que falta.
                    lectura.sin_resumen = None
                elif self._resumidor is None:
                    lectura.sin_resumen = self._motivo_sin_resumidor or "no se pidió a la IA"
                elif not texto:
                    lectura.sin_resumen = "el acta no trae texto legible que resumir"
                else:
                    pendientes.append(
                        (lectura, "resumen", proveedor.submit(self._resumidor.resumir, texto))
                    )

            for lectura, que, futuro in pendientes:
                # Una lectura de la IA tarda lo que tarde el proveedor: se
                # espera preguntando, no de un tirón.
                aguardar(futuro, self._control)
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
            self._reintentar_resumenes(paginas, lecturas, repetidos, proveedor)

    def _reintentar_resumenes(self, paginas, lecturas, repetidos, proveedor) -> None:
        """Los resúmenes que el proveedor no atendió por estar saturado, pedidos otra vez.

        Un 429 -- «más despacio» -- o una caída de la red no son un «no»: con
        varios documentos a la vez el proveedor se satura un momento, y el acta
        se quedaba sin resumen para siempre. Se espera a que pase la ráfaga y se
        piden una vez más; lo que falle de nuevo queda dicho en observaciones.
        """
        otra_vez = [
            lectura
            for lectura in lecturas
            if lectura.resumen is None and _es_pasajero(lectura.sin_resumen)
        ]
        if not otra_vez or self._resumidor is None:
            return
        self._report(
            ProgressEvent(
                stage=Stage.INVENTORYING,
                done=0,
                total=len(otra_vez),
                detail=f"el proveedor estaba saturado: se piden otra vez {len(otra_vez)} resumen(es)",
            )
        )
        limite = time.monotonic() + self._espera_para_reintentar
        while time.monotonic() < limite:
            self._control.check()
            time.sleep(min(ESPERA_ENTRE_CONSULTAS, max(0.0, limite - time.monotonic())))
        vuelo = []
        for lectura in otra_vez:
            texto = texto_para_resumir(
                paginas[lectura.tramo.desde - 1 : lectura.tramo.hasta], repetidos=repetidos
            )
            vuelo.append((lectura, proveedor.submit(self._resumidor.resumir, texto)))
        for lectura, futuro in vuelo:
            aguardar(futuro, self._control)
            resumen, motivo = _resumen_de(futuro)
            if resumen:
                lectura.resumen, lectura.sin_resumen = resumen, None
            else:
                lectura.sin_resumen = f"{motivo} (también al pedirlo otra vez)"

    def _pedir_folio(
        self, source: PageSource, lectura: _Lectura, proveedor: ThreadPoolExecutor
    ) -> tuple[FoliosDelActa, Future | None]:
        """Lo que se sabe del folio sin leer, y la lectura pedida si hace falta."""
        foliadas = lectura.foliadas
        if not self._perfil.lee_folio:
            return FoliosDelActa(foliadas=len(foliadas)), None
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


#: Cuánto se espera a que pase una ráfaga de rechazos antes de pedir otra vez.
ESPERA_PARA_REINTENTAR = 20.0
#: Lo que dice un fallo que se arregla esperando: saturación o red.
_PASAJERO = re.compile(r"429|no respondi|sin atender|falló el resumen|5\d\d\)")


def _es_pasajero(motivo: str | None) -> bool:
    return bool(motivo) and bool(_PASAJERO.search(motivo))


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


def _contrastar_con_el_nombre(
    lectura: _Lectura, paginas: Sequence[str], numero: int, fecha: date
) -> None:
    """Lo que el papel no dejó leer, del nombre del archivo; y lo que discrepa, dicho.

    El nombre lo puso el archivista -- «1SESION ORDINARIA N° 001 LUNES DE 19
    ENERO DE 2015» -- y casi siempre acierta, pero no siempre: «ACTA N°14 03
    JULIO 2013 (2)» es la sesión del 26 de junio. Así que manda el papel, y el
    nombre entra sólo donde el papel calla o para confirmar:

    * sin número legible -- el OCR deshizo «ACTA N° 001» en «liiiiia» --, el
      del nombre, y la fila lo dice;
    * con otra fecha, la del nombre si esa fecha está escrita en el papel -- el
      «FECHA: 23/05/2013» era de un formulario anexo, y el 19 de enero de 2015
      está en el acta --; si no está, se queda la leída y la fila avisa.
    """
    acta = lectura.acta
    avisos = []
    if acta.numero is None:
        acta = replace(acta, numero=f"{numero:03d}")
        avisos.append(
            "el número del acta no se pudo leer en su encabezado y se tomó del nombre del archivo"
        )
    if acta.fecha != fecha:
        escritas = {f for pagina in paginas for f in fechas_de(pagina)}
        if fecha in escritas or acta.fecha is None and fecha in escritas:
            acta = replace(acta, fecha=fecha, dia_impreso=None)
        elif acta.fecha is not None:
            avisos.append(
                f"el nombre del archivo dice {fecha.strftime('%d-%m-%Y')} y el acta "
                f"{acta.fecha.strftime('%d-%m-%Y')}: revise cuál es la fecha de la sesión"
            )
    lectura.acta = acta
    if avisos:
        lectura.nota_del_nombre = "; ".join(avisos)


def _unificar_titulos(lecturas: list[_Lectura]) -> None:
    """Los títulos mal leídos, llevados al que se repite en el libro (ver ``titulos_unificados``)."""
    de_grado = [x for x in lecturas if not x.tramo.ceremonia and x.acta.rotulo == ROTULO_DE_GRADO]
    for lectura, titulo in zip(de_grado, titulos_unificados([x.acta.titulo for x in de_grado]), strict=True):
        if titulo != lectura.acta.titulo:
            lectura.acta = replace(lectura.acta, titulo=titulo, dudas=dudas_de(lectura.acta.nombre, titulo))


def _descartar_fechas_fuera_de_lugar(lecturas: list[_Lectura]) -> None:
    """Quita la fecha de un acta que no cuadra con las de su libro, y dice cuál era.

    Una fecha mal puesta es peor que ninguna: el inventario se ordena y se
    filtra por ella. En la columna queda N/A y en observaciones lo que se leyó,
    para que quien mire el papel lo decida.
    """
    fuera = fechas_fuera_de_lugar([lectura.acta.fecha for lectura in lecturas])
    for indice, (desde, hasta) in fuera.items():
        lectura = lecturas[indice]
        leida = lectura.acta.fecha
        rango = str(desde) if desde == hasta else f"{desde} a {hasta}"
        lectura.fecha_descartada = (
            f"se leyó la fecha {leida.strftime('%d-%m-%Y')}, que no cuadra con las actas "
            f"vecinas ({rango}): revise la fecha en el papel"
        )
        lectura.fecha_leida = leida
        lectura.acta = replace(lectura.acta, fecha=None, dia_impreso=None)


#: Los datos de un acta que una relectura puede llenar, con su nombre para las notas.
def _mismo_numero(a: object, b: object) -> bool:
    return str(a).lstrip("0") == str(b).lstrip("0")


def _mismas_cifras(a: object, b: object) -> bool:
    return re.sub(r"\D", "", str(a)) == re.sub(r"\D", "", str(b))


def _mismo_titulo(a: object, b: object) -> bool:
    def letras(titulo: object) -> str:
        return re.sub(r"[^A-Z]", "", clave(titulo_limpio(str(titulo)) or str(titulo)))

    return letras(a) == letras(b)


#: Los campos que se cruzan con la lectura de la IA: cómo se dicen, cuándo dos
#: lecturas son la misma y cómo se escriben en la nota.
_CAMPOS_QUE_CRUZA_LA_IA = (
    ("numero", "el número del acta", _mismo_numero, str),
    ("fecha", "la fecha", lambda a, b: a == b, lambda f: f.strftime("%d-%m-%Y")),
    ("titulo", "el título", _mismo_titulo, str),
    ("cedula", "la cédula", _mismas_cifras, str),
)


_CAMPOS_DEL_ACTA = (
    ("numero", "el número"),
    ("fecha", "la fecha"),
    ("nombre", "el nombre"),
    ("titulo", "el título"),
    ("cedula", "la cédula"),
)


def _enumerar(cosas: list[str]) -> str:
    """«la fecha», «el número y la fecha», «el número, la fecha y la cédula»."""
    if len(cosas) == 1:
        return cosas[0]
    return ", ".join(cosas[:-1]) + " y " + cosas[-1]


#: Cuánto pesa cada lectura del graduado en el consenso; la de la IA, el doble.
PESO_DE_UNA_LECTURA = 1.0
PESO_DE_LA_IA = 2.0
#: Cuántos puntos de margen se dejan por encima y por debajo de la franja del nombre.
MARGEN_DE_LA_FRANJA_DEL_NOMBRE = 6.0


@lru_cache(maxsize=1)
def _nombres_del_archivo() -> tuple[frozenset[str], frozenset[str]]:
    """Los nombres de pila y los apellidos de la lista, cada uno en su sección."""
    ruta = Path(__file__).resolve().parents[1] / "assets" / "nombres_hispanos.txt"
    try:
        renglones = ruta.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.warning("no se encontró la lista de nombres %s", ruta)
        return frozenset(), frozenset()
    de_pila: set[str] = set()
    apellidos: set[str] = set()
    actual = de_pila
    for renglon in renglones:
        limpio = renglon.strip()
        if limpio.startswith("#"):
            if "apellidos" in limpio.lower():
                actual = apellidos
            elif "nombres de pila" in limpio.lower():
                actual = de_pila
            continue
        if limpio:
            actual.add(clave(limpio))
    return frozenset(de_pila), frozenset(apellidos)


def nombres_conocidos() -> set[str]:
    """Nombres y apellidos hispanos frecuentes: sólo para desempatar lecturas."""
    de_pila, apellidos = _nombres_del_archivo()
    return set(de_pila | apellidos)


def _palabras_del_libro(
    graduados: list[_Lectura], paginas: list[str], lecturas: list[_Lectura]
) -> set[str]:
    """Las palabras de nombre que el propio libro confirma.

    Las que aparecen en el nombre de dos graduados distintos -- MARIA, PEREZ,
    MENDOZA -- y las de los listados de graduandos de sus ceremonias, que van
    impresos y salen limpios.
    """
    cuenta: dict[str, int] = {}
    for lectura in graduados:
        for palabra in set(palabras_de(lectura.acta.nombre)):
            cuenta[palabra] = cuenta.get(palabra, 0) + 1
    del_libro = {p for p, n in cuenta.items() if n >= 2 and parece_palabra_de_nombre(p)}
    for lectura in lecturas:
        if not lectura.tramo.ceremonia:
            continue
        for hoja in paginas[lectura.tramo.desde - 1 : lectura.tramo.hasta]:
            for renglon in hoja.splitlines():
                if renglon.strip() and renglon.upper() == renglon and re.search(r"[A-ZÑ]{3}", renglon):
                    del_libro.update(
                        p for p in palabras_de(renglon) if len(p) >= 3 and parece_palabra_de_nombre(p)
                    )
    return del_libro


#: A cuánto se amplía la zona de la cédula para leerla otra vez.
DPI_DE_LA_ZONA = 400
#: Cuánto se toma por encima de «portador» y por debajo de «juramento»: la
#: máquina escribe un poco por encima o por debajo de su renglón.
MARGEN_DE_LA_ZONA = 18.0

#: Una cédula escrita con sus puntos, suelta en el texto: «22.793.650», «50'849.361».
_CEDULA_CON_PUNTOS = re.compile(r"(?<![\d.,'])(\d{1,3}(?:[.,']\d{3}){2,3})(?![\d.,'])")


def _cedula_suelta(texto: str) -> str | None:
    """La cédula con sus puntos que trae la zona, si trae una sola."""
    halladas = {re.sub(r"\D", "", m) for m in _CEDULA_CON_PUNTOS.findall(texto)}
    validas = [c for c in halladas if 6 <= len(c) <= 11]
    return validas[0] if len(validas) == 1 else None


def _banda_de_la_cedula(trozos, ancho: float, alto: float) -> Band | None:
    """La franja de la cédula en la hoja: del renglón de «portador» al de «juramento»."""
    arriba = [t.y0 for t in trozos if "portador" in t.texto.lower()]
    if not arriba or not alto:
        return None
    desde = min(arriba)
    abajo = [t.y1 for t in trozos if re.search(r"juramento|expedida", t.texto, re.IGNORECASE) and t.y0 >= desde]
    hasta = max(abajo) if abajo else desde + alto * 0.1
    return Band(
        0.0,
        max(0.0, (desde - MARGEN_DE_LA_ZONA) / alto),
        1.0,
        min(1.0, (hasta + MARGEN_DE_LA_ZONA) / alto),
    )


def _banda_del_nombre(trozos, ancho: float, alto: float) -> Band | None:
    """La franja del nombre en la hoja: del renglón de «al estudiante» al de «portador»."""
    arriba = [t.y0 for t in trozos if re.search(r"estudiante|profesional", t.texto, re.IGNORECASE)]
    abajo = [t.y1 for t in trozos if "portador" in t.texto.lower()]
    if not arriba or not abajo or not alto:
        return None
    desde, hasta = min(arriba), max(abajo)
    if hasta <= desde:
        return None
    return Band(
        0.0,
        max(0.0, (desde - MARGEN_DE_LA_FRANJA_DEL_NOMBRE) / alto),
        1.0,
        min(1.0, (hasta + MARGEN_DE_LA_FRANJA_DEL_NOMBRE) / alto),
    )


def _faltan(acta: ActaDeConsejo) -> bool:
    """Si al acta le falta algo que su fila del inventario pide y que el papel puede traer."""
    if acta.rotulo == ROTULO_DE_CEREMONIA:
        return False
    if acta.rotulo == ROTULO_DE_GRADO:
        if acta.constancia:
            return not all((acta.numero, acta.fecha, acta.nombre))
        return not all((acta.numero, acta.fecha, acta.nombre, acta.titulo, acta.cedula))
    return acta.numero is None or acta.fecha is None


def _de_graduado(lecturas: list[_Lectura]) -> list[int]:
    """La posición de las actas de graduados, sin las hojas de las ceremonias."""
    return [
        indice
        for indice, lectura in enumerate(lecturas)
        if not lectura.tramo.ceremonia and lectura.acta.rotulo != ROTULO_DE_CEREMONIA
    ]


def _corregir_anios(lecturas: list[_Lectura]) -> None:
    """La fecha descartada por el año, recuperada si las vecinas dicen cuál era.

    «04-04-1927» en medio de una ceremonia del 04-04-1997 es esa ceremonia con
    el 9 mal leído; «16-01-2000» entre actas de 2008 es el 16-01-2008. La regla
    está en `corregir_anio`, y exige que la fecha corregida caiga entre las de
    las vecinas.
    """
    posiciones = _de_graduado(lecturas)
    fechas = [lecturas[i].acta.fecha for i in posiciones]
    for orden, indice in enumerate(posiciones):
        lectura = lecturas[indice]
        if lectura.acta.fecha is not None or lectura.fecha_leida is None:
            continue
        corregida = corregir_anio(
            lectura.fecha_leida,
            vecinas_de(fechas, orden),
            a_los_lados=igual_a_los_lados(fechas, orden),
        )
        if corregida is None:
            continue
        leida = lectura.fecha_leida.strftime("%d-%m-%Y")
        lectura.acta = replace(lectura.acta, fecha=corregida)
        lectura.fecha_descartada = None
        lectura.razonado.append(
            f"en el papel se leyó {leida}; la fecha se corrigió a "
            f"{corregida.strftime('%d-%m-%Y')} por las actas vecinas: revísela en el papel"
        )
        fechas[orden] = corregida


#: Cuántos años lejos de todas sus vecinas tiene que estar la fecha de un acta
#: manuscrita para corregirla: a uno, puede ser de verdad de otro año.
SALTO_DE_ANIO_DE_UN_EXAMEN = 2
#: Cuántas actas finales del libro tienen que decir el mismo título para dárselo
#: a la que no se dejó leer.
TITULOS_PARA_EL_LIBRO = 3


def _fecha_suelta(fechas: Sequence[date | None], orden: int) -> bool:
    """Si la fecha está a dos años o más de la anterior y de la siguiente que se leyeron.

    La primera y la última del libro no lo son: con una sola vecina mal leída
    no se sabe cuál de las dos es la suelta, y dejaban sin vecina a la otra.
    """
    leida = fechas[orden]
    anterior = next((fecha for fecha in reversed(fechas[:orden]) if fecha is not None), None)
    siguiente = next((fecha for fecha in fechas[orden + 1 :] if fecha is not None), None)
    if leida is None or anterior is None or siguiente is None:
        return False
    return all(abs(vecina.year - leida.year) >= SALTO_DE_ANIO_DE_UN_EXAMEN for vecina in (anterior, siguiente))


def _con_el_anio_de_las_vecinas(leida: date, anterior: date, siguiente: date) -> date | None:
    """La fecha con el año de una vecina, si con él cae entre las dos; o con el de las dos, si es el mismo."""
    entre = []
    for anio in sorted({anterior.year, siguiente.year}):
        try:
            candidata = leida.replace(year=anio)
        except ValueError:  # un 29 de febrero
            continue
        if anterior <= candidata <= siguiente:
            entre.append(candidata)
    if len(entre) == 1:
        return entre[0]
    if anterior.year == siguiente.year:
        try:
            return leida.replace(year=anterior.year)
        except ValueError:
            return None
    return None


def _los_examenes(lecturas: list[_Lectura]) -> None:
    """Las actas manuscritas de examen (1924-1946), con el título completo y el año que corrigen sus vecinas.

    La IA lee la cifra a mano y a veces la cambia: «21-03-1921» entre actas del
    20 y el 25 de marzo de 1926 es el 21-03-1926 (UPD3859999). En un libro
    manuscrito no se descarta ninguna fecha -- la leyó la IA, y la regla de las
    fuera de lugar es contra el OCR gratis --: sólo se corrige la que sus
    vecinas corrigen sin dudas, y se dice.

    Sin dudas es: la leída está a dos años o más de la anterior y de la
    siguiente, y con el año de una de ellas cae entre las dos; o las dos son
    del mismo año, y es ése -- en el libro van casi en orden, el 22, el 21, el
    25 de marzo --. A un año, el acta puede ser de verdad del año de al lado; y
    la primera del libro no tiene anterior: el 04-07-1924 que abre UPD3860000
    va antes de las de 1925, y corregido a 1925 quedaba mal. Una fecha suelta
    no sirve de vecina de otra: 05-08-1916 y 16-08-1906 seguidas, entre
    octubre de 1925 y septiembre de 1926 (UPD3860000), son agosto de 1926.
    """
    posiciones = [
        indice
        for indice, lectura in enumerate(lecturas)
        if not lectura.tramo.ceremonia and lectura.acta.examen is not None
    ]
    # El examen que la hoja no dice -- «Preparatorio» ilegible -- es el de sus
    # vecinas, si las dos dicen el mismo: el libro va por tramos, los finales y
    # después los preparatorios. Si discrepan, queda «ACTA DE EXAMEN DE GRADO».
    dichos = [lecturas[indice].acta.examen for indice in posiciones]
    for orden, indice in enumerate(posiciones):
        if dichos[orden] != EXAMEN_SIN_DECIR:
            continue
        anterior = next((examen for examen in reversed(dichos[:orden]) if examen), None)
        siguiente = next((examen for examen in dichos[orden + 1 :] if examen), None)
        examen = anterior if siguiente is None or anterior == siguiente else siguiente if anterior is None else None
        if examen is None:
            continue
        lectura = lecturas[indice]
        lectura.acta = replace(lectura.acta, examen=examen)
        lectura.razonado.append(
            f"la hoja no deja leer qué examen fue; se tomó {examen.lower()}, como las actas vecinas: revíselo en el papel"
        )
    for indice in posiciones:
        acta = lecturas[indice].acta
        titulo = titulo_del_examen(acta.examen, acta.titulo)
        if titulo != acta.titulo:
            # Las dudas del título leído se van con él; las del nombre se quedan.
            viejas, nuevas = dudas_de(acta.nombre, acta.titulo), dudas_de(acta.nombre, titulo)
            dudas = tuple(d for d in acta.dudas if d not in viejas or d in nuevas)
            lecturas[indice].acta = replace(
                acta, titulo=titulo, dudas=(*dudas, *(d for d in nuevas if d not in dudas))
            )
    # El título del final que no se leyó es el que confieren todas las demás
    # actas finales del libro, si todas dicen el mismo: DOCTOR EN MEDICINA Y
    # CIRUGIA en las 136 de UPD3860000 que se leyeron. Se dice.
    finales = [lecturas[indice] for indice in posiciones if lecturas[indice].acta.examen == EXAMEN_FINAL]
    conferidos = {lectura.acta.titulo for lectura in finales if lectura.acta.titulo}
    if len(conferidos) == 1 and sum(1 for lectura in finales if lectura.acta.titulo) >= TITULOS_PARA_EL_LIBRO:
        (conferido,) = conferidos
        for lectura in finales:
            if not lectura.acta.titulo:
                lectura.acta = replace(lectura.acta, titulo=conferido)
                lectura.razonado.append(
                    f"el título no se pudo leer; es el que confieren todas las actas finales del libro, "
                    f"{conferido}: revíselo en el papel"
                )
    fechas = [lecturas[indice].acta.fecha for indice in posiciones]
    sueltas = {orden for orden in range(len(fechas)) if _fecha_suelta(fechas, orden)}
    for orden in sorted(sueltas):
        leida = fechas[orden]
        anterior = next((fechas[otro] for otro in range(orden - 1, -1, -1) if fechas[otro] and otro not in sueltas), None)
        siguiente = next((fechas[otro] for otro in range(orden + 1, len(fechas)) if fechas[otro] and otro not in sueltas), None)
        if leida is None or anterior is None or siguiente is None:
            continue
        corregida = _con_el_anio_de_las_vecinas(leida, anterior, siguiente)
        if corregida is None or corregida == leida:
            continue
        indice = posiciones[orden]
        lectura = lecturas[indice]
        lectura.acta = replace(lectura.acta, fecha=corregida)
        lectura.razonado.append(
            f"en el papel se leyó {leida.strftime('%d-%m-%Y')}; la fecha se corrigió a "
            f"{corregida.strftime('%d-%m-%Y')} por las actas vecinas: revísela en el papel"
        )
        fechas[orden] = corregida


def _por_la_resolucion_de_la_ceremonia(lecturas: list[_Lectura]) -> None:
    """La fecha de un acta de grado que no se leyó: la de las hojas de su ceremonia.

    Cada ceremonia del libro va precedida de su resolución, que dice el día:
    «el día viernes 22 de julio del año 2005». En UPD3859825 35 de 81 actas
    salían sin fecha y sus vecinas tampoco la traían (Secretaría 3292,
    2026-10-31). Sólo para las que no la tienen: una fecha leída no se pisa.
    """
    de_la_ceremonia = None
    for lectura in lecturas:
        if lectura.tramo.ceremonia:
            de_la_ceremonia = lectura.acta.fecha or de_la_ceremonia
            continue
        acta = lectura.acta
        if acta.rotulo != ROTULO_DE_GRADO or acta.fecha is not None or de_la_ceremonia is None:
            continue
        lectura.acta = replace(acta, fecha=de_la_ceremonia)
        lectura.fecha_descartada = None
        lectura.razonado.append(
            f"la fecha no se pudo leer y es la de la resolución de su ceremonia ({de_la_ceremonia.strftime('%d-%m-%Y')})"
        )


def _por_la_ceremonia(lecturas: list[_Lectura]) -> None:
    """La fecha y el número de un acta de grado, de las de su misma ceremonia.

    En un libro de grados las actas de una ceremonia van seguidas y comparten
    número y fecha: decenas de «ACTA DE GRADO No. 03» del 10-09-1999. Un acta
    sin fecha legible entre dos del 10-09-1999 que llevan su mismo número es
    del 10-09-1999; y una sin número entre dos «No. 03» de su misma fecha es la
    03. Con vecinas que no coinciden no se deduce nada.
    """
    # Las actas colectivas no: cada una es su propia ceremonia, con su número
    # (UPD3859802, 2026-11-12).
    posiciones = [
        i for i in _de_graduado(lecturas)
        if lecturas[i].acta.rotulo == ROTULO_DE_GRADO and not lecturas[i].acta.constancia and not lecturas[i].colectiva
    ]
    if len(posiciones) < 3:
        return
    actas = [lecturas[i].acta for i in posiciones]
    fechas = [acta.fecha for acta in actas]
    numeros = [acta.numero for acta in actas]
    for orden, indice in enumerate(posiciones):
        lectura = lecturas[indice]
        acta = lectura.acta
        if acta.fecha is None:
            fecha = igual_a_los_lados(fechas, orden)
            anterior = next((n for f, n in zip(reversed(fechas[:orden]), reversed(numeros[:orden]), strict=True) if f is not None), None)
            if fecha is not None and (acta.numero is None or mismo_numero(acta.numero, anterior)):
                lectura.acta = replace(lectura.acta, fecha=fecha)
                lectura.fecha_descartada = None
                lectura.razonado.append(
                    f"la fecha no se pudo leer y es la de su ceremonia ({fecha.strftime('%d-%m-%Y')}): "
                    "la llevan las actas de antes y de después"
                )
        if acta.numero is None:
            claves = [str(int(re.sub(r"\D", "", n))) if n and re.sub(r"\D", "", n) else None for n in numeros]
            clave = igual_a_los_lados(claves, orden)
            if clave is None:
                continue
            anterior = next(n for n, c in zip(reversed(numeros[:orden]), reversed(claves[:orden]), strict=True) if c == clave)
            fechas_al_lado = {f for f, c in zip(fechas, claves, strict=True) if c == clave and f is not None}
            propia = lectura.acta.fecha
            if propia is None or propia in fechas_al_lado:
                lectura.acta = replace(lectura.acta, numero=anterior)
                lectura.razonado.append(
                    f"el número no se pudo leer y es el de su ceremonia (No. {anterior}): "
                    "lo llevan las actas de antes y de después"
                )


#: El formulario de las actas de 2003 a 2006 con la fecha sin llenar: «FECHA: HORA: 07:00».
_FECHA_EN_BLANCO = re.compile(r"\bFECHA\s*:\s*HORA\s*:")
#: La cabecera de una hoja que no es la primera del acta: «Pagina 02».
_PAGINA_DE_EN_MEDIO = re.compile(r"\bP[AÁ]GINA\s*(0?[2-9]|[1-9]\d)\b")


def _fechas_del_cuerpo(paginas: list[str], lecturas: list[_Lectura]) -> None:
    """La fecha de un acta de consejo cuyo encabezado no trae el día.

    «ACTA CONSEJO DE FACULTAD ORDINARIO No. 017 — Diciembre de 2006»: el día
    se busca en el cuerpo del acta, en una fecha de ese mismo mes y año. Si no
    aparece, se entrega el mes y el año -- «12-2006» --, que es lo que el papel
    dice, en vez de una celda vacía.
    """
    for lectura in lecturas:
        acta = lectura.acta
        if acta.fecha is not None or acta.rotulo != "ACTA" or lectura.fecha_leida is not None:
            continue
        hojas = paginas[lectura.tramo.desde - 1 : lectura.tramo.hasta]
        if not hojas:
            continue
        cabeza = hojas[(acta.pagina or 1) - 1] if acta.pagina and acta.pagina <= len(hojas) else hojas[0]
        parcial = mes_y_anio(cabeza)
        if parcial is None:
            # La capa pone las etiquetas en una columna y los valores en otra
            # -- «FECHA: HORA: LUGAR:» y luego «Diciembre de 2006 07:00» --, así
            # que el campo sólo está en blanco si además no hay fecha ninguna.
            plana = " ".join(cabeza.upper().split())
            sin_primera = _PAGINA_DE_EN_MEDIO.search(plana[:300])
            if sin_primera:
                lectura.razonado.append(
                    f"falta la primera hoja del acta en el escaneo: la primera que hay dice "
                    f"«Página {sin_primera.group(1)}», y la fecha va en la hoja que falta"
                )
            elif _FECHA_EN_BLANCO.search(plana):
                lectura.razonado.append(
                    "el papel trae el campo «FECHA:» en blanco: el acta no dice su fecha"
                )
            continue
        mes, anio = parcial
        del_cuerpo = next(
            (f for hoja in hojas for f in fechas_de(hoja) if (f.month, f.year) == (mes, anio)),
            None,
        )
        if del_cuerpo is not None:
            lectura.acta = replace(acta, fecha=del_cuerpo)
            lectura.razonado.append(
                "el encabezado sólo dice el mes y el año; el día se tomó de la fecha "
                f"del mismo mes que trae el cuerpo del acta ({del_cuerpo.strftime('%d-%m-%Y')}): revísela"
            )
        else:
            lectura.fecha_parcial = f"{mes:02d}-{anio}"
            lectura.razonado.append(
                f"el acta sólo dice el mes y el año ({mes:02d}-{anio}), sin el día"
            )


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
    if acta.rotulo in (ROTULO_DE_CEREMONIA, ROTULO_DE_GRADO):
        return _fila_de_grado(lectura, archivo=archivo, carpeta=carpeta, ilegibles=ilegibles)
    sin_resumen = None if lectura.sin_resumen == por_eleccion else lectura.sin_resumen
    if folios.motivo == SIN_IA_PARA_EL_FOLIO:
        folios = replace(folios, motivo=None)
    avisos = _advertencias(acta, folios, ilegibles, sin_resumen)
    if lectura.fecha_descartada:
        avisos = [
            lectura.fecha_descartada if aviso == "no se encontró la fecha de la sesión" else aviso
            for aviso in avisos
        ]
    if lectura.deducido:
        avisos = [lectura.deducido, *[a for a in avisos if not a.startswith("sin folio inicial")]]
    if lectura.nota_del_nombre:
        avisos.insert(0, lectura.nota_del_nombre)
    if lectura.fecha_parcial or any(
        "«FECHA:» en blanco" in r or "falta la primera hoja" in r for r in lectura.razonado
    ):
        avisos = [a for a in avisos if a != "no se encontró la fecha de la sesión"]
    avisos.extend(lectura.razonado)
    return FilaDeActa(
        archivo=archivo,
        acta=acta.encabezado or NO_APLICA,
        # Día, mes y año: «25-10-2012». Es como lo pidió el operador para el
        # inventario, y como se ordena y se filtra en Excel sin traducir nada.
        fecha=(
            acta.fecha.strftime("%d-%m-%Y") if acta.fecha else (lectura.fecha_parcial or NO_APLICA)
        ),
        folio_inicial=folios.inicial if folios.inicial is not None else NO_APLICA,
        folio_final=folios.final if folios.final is not None else NO_APLICA,
        folios=folios.cantidad or folios.foliadas or tramo.paginas,
        resumen=lectura.resumen or NO_APLICA,
        observaciones="; ".join(avisos),
        carpeta=carpeta,
        pagina_inicial=tramo.desde,
        pagina_final=tramo.hasta,
        # «15 BIS»: el número es el de la sesión anterior, y lo que la distingue
        # tiene que llegar al consecutivo del FUID.
        numero=f"{acta.numero} BIS" if acta.numero and acta.bis else acta.numero or "",
        piezas=resumen_de_piezas(lectura.piezas),
    )


#: Cuántas palabras puede tener un nombre completo.
PALABRAS_DE_UN_NOMBRE = 6


def _lo_completa(nombre: str, otro: str) -> bool:
    """Si ``otro`` es ``nombre`` con más palabras -- todas con forma de nombre --, en el mismo orden."""
    una, otra = [clave(p) for p in nombre.split()], [clave(p) for p in otro.split()]
    if len(otra) <= len(una) or len(otra) > PALABRAS_DE_UN_NOMBRE:
        return False
    sobrantes = list(otra)
    for palabra in una:
        if palabra not in sobrantes:
            return False
        sobrantes.remove(palabra)
    orden = [p for p in otra if p in una]
    return orden == una and all(parece_palabra_de_nombre(p) for p in sobrantes)


def _con_la_cola_del_renglon(lectura: _Lectura) -> None:
    """El nombre del OCR completado con el apellido que la IA ve delante de «portador» (``nombre_con_la_cola_del_renglon``)."""
    acta = lectura.acta
    completo = nombre_con_la_cola_del_renglon(acta.nombre, lectura.texto_de_la_ia or "", acta.titulo)
    if completo is None:
        return
    lectura.razonado.append(
        f"el nombre sigue en el renglón de «portador», que la IA sí leyó: «{acta.nombre}» quedó «{completo}»; "
        "revíselo en el papel"
    )
    lectura.acta = replace(acta, nombre=completo)


def _nombre_de_la_ia(lectura: _Lectura, conocidas: set[str]) -> None:
    """El nombre del graduado, cruzado con el que leyó la IA en su hoja, como los demás datos.

    El voto entre lecturas se quedaba a veces con el del OCR aunque la IA lo
    leyera bien: «IIEI ANA ESTHER» por LILIANA ESTHER, «… SALGUEDO MNANNE» por
    LUZ MARINA HOWARD SALGUEDO (UPD3859803, Odontología, devuelto por el
    cliente; comprobado en el papel el 2026-10-31). Si la IA leyó en la frase
    «al estudiante …» un nombre de dos palabras o más, todas con forma de
    nombre, manda la IA; si discrepa del OCR, se anota para revisarlo.
    """
    if not lectura.texto_de_la_ia:
        return
    acta = lectura.acta
    # La frase «al estudiante …» de los libros de los 90, o el renglón propio
    # del nombre en las actas de hoy, que sólo ve el lector del acta de grado.
    # En una constancia, el que ella señala: la frase de la zona tomaría a la
    # decana o a la secretaria que firman.
    de_la_hoja = leer_acta_de_grado([lectura.texto_de_la_ia]).nombre
    de_la_zona = zona_del_nombre(lectura.texto_de_la_ia, titulo=acta.titulo, conocidas=conocidas)
    if lectura.datos_de_la_ia.get("nombre"):
        # Lo que el lector de texto entendió, ya validado contra la hoja: con
        # el nombre partido o corrido de su renglón es el único que lo junta.
        leido = str(lectura.datos_de_la_ia["nombre"])
    elif acta.constancia:
        leido = de_la_hoja
    else:
        leido = de_la_zona or de_la_hoja
    # «LUZ FELFLE CASTILLA» y, en otra lectura de la misma hoja, «FAIMA LUZ
    # FELFLE CASTILLA»: la que lo dice entero (UPD3859808 pág. 96), si lo que
    # añade tiene forma de nombre.
    for otro in (de_la_hoja, de_la_zona):
        if leido and otro and _lo_completa(leido, otro) and not acta.constancia:
            leido = otro
    palabras = (leido or "").split()
    if len(palabras) < 2 or not all(parece_palabra_de_nombre(clave(palabra)) for palabra in palabras):
        _con_la_cola_del_renglon(lectura)
        return
    # Un renglón del título no es un nombre: la IA leyó «CON ENFASIS EN
    # NEUROCIRUGIA» en el renglón del graduado, ganó, y la limpieza dejó el
    # nombre vacío (Odontología, UPD3859813 pág. 163, 2026-11-12).
    del_titulo = {clave(p) for p in (acta.titulo or "").split()} | VOCABULARIO_DE_LOS_TITULOS | {"CON", "EN"}
    if sum(clave(p) in del_titulo for p in palabras) * 2 >= len(palabras):
        lectura.razonado.append(f"el nombre: la IA leyó «{leido}», que es del título; se dejó el del OCR")
        _con_la_cola_del_renglon(lectura)
        return
    lectura.nombre_dudoso = False
    actual = acta.nombre or ""
    if [clave(p) for p in actual.split()] == [clave(p) for p in palabras]:
        return
    lectura.acta = replace(
        acta, nombre=leido, dudas=tuple(d for d in acta.dudas if not d.startswith("el nombre"))
    )
    if actual:
        lectura.razonado.append(
            f"el nombre: el OCR leyó {actual} y la IA {leido}; se dejó lo de la IA: revíselo en el papel"
        )


def _con_el_numero_de_la_serie(filas: list[FilaDeActa]) -> list[FilaDeActa]:
    """Las filas de un libro con el número truncado deducido de sus vecinas, ya en el trabajo.

    La deducción se hacía sólo al juntar la carpeta: el FUID decía la 013, pero
    el PDF dividido ya se había escrito «04_ACTA-EXTRAORDINARIA-NO-01…»
    (UPD3859789, 2026-10-31). Ahora se hace antes de nombrar las sesiones.
    """
    datos = [
        {"archivo": "", "numero": fila.numero, "fecha": fila.fecha, "observaciones": fila.observaciones}
        for fila in filas
    ]
    _numero_por_la_serie(datos)
    hechas = []
    for fila, dato in zip(filas, datos, strict=True):
        numero = str(dato["numero"])
        if numero != fila.numero and fila.numero:
            fila = replace(
                fila,
                numero=numero,
                acta=re.sub(rf"No\. {re.escape(fila.numero)}\b", f"No. {numero}", fila.acta),
                observaciones=str(dato["observaciones"]),
            )
        hechas.append(fila)
    return hechas


def _con_las_previas(fila: FilaDeActa, lectura: _Lectura, previas: tuple[int, int]) -> FilaDeActa:
    """La primera sesión del libro con las hojas que se escanearon delante de ella.

    En los libros de Odontología medidos (UPD3859787, 3859789, 3859793, 3859796:
    de 31 a 93 páginas) lo que va delante de la primera acta son sus anexos,
    escaneados antes que ella. Salían en un PDF aparte y sin fila, y la UPD
    sumaba en el FUID menos folios de los que cuenta el cliente. Ahora van
    dentro de la primera sesión, como un anexo más, y su fila los cuenta.
    """
    desde, hasta = previas
    lectura.piezas = [PiezaDeActa(ANEXO, desde, hasta), *lectura.piezas]
    paginas = hasta - desde + 1
    aviso = (
        f"lleva delante, como anexo, las páginas {desde} a {hasta} del PDF, "
        "escaneadas antes que el acta"
    )
    return replace(
        fila,
        pagina_inicial=desde,
        folios=fila.folios + paginas,
        observaciones="; ".join(a for a in (aviso, fila.observaciones) if a),
        piezas=resumen_de_piezas(lectura.piezas),
    )


def _fila_de_grado(
    lectura: _Lectura, *, archivo: str, carpeta: str, ilegibles: list[int]
) -> FilaDeActa:
    """La fila de un graduado -- o de las hojas de su ceremonia -- para el FUID.

    Lo que el FUID pide y no se pudo leer se dice en las notas, una cosa por
    falta, para que quien revise sepa qué buscar en el papel.
    """
    acta, tramo = lectura.acta, lectura.tramo
    ceremonia = acta.rotulo == ROTULO_DE_CEREMONIA
    avisos: list[str] = []
    if not ceremonia and acta.examen is not None:
        # El acta manuscrita de examen no trae número ni cédula: no es una falta.
        for valor, falta in (
            (acta.nombre, "no se pudo leer el nombre del alumno"),
            (
                acta.titulo,
                "no se pudo leer el título: cuál preparatorio fue"
                if acta.examen == EXAMEN_PREPARATORIO
                else "no se pudo leer el título conferido",
            ),
        ):
            if not valor:
                avisos.append(falta)
    elif not ceremonia:
        for valor, falta in (
            (acta.numero, "no se pudo leer el número del acta"),
            (acta.nombre, "no se pudo leer el nombre del graduado"),
            (
                acta.titulo,
                "la constancia no dice el título" if acta.constancia else "no se pudo leer el título",
            ),
            (
                acta.cedula,
                "la constancia no trae la cédula" if acta.constancia else "no se pudo leer la cédula",
            ),
        ):
            if not valor:
                avisos.append(falta)
    if not ceremonia:
        if lectura.fecha_descartada:
            avisos.append(lectura.fecha_descartada)
        elif acta.fecha is None:
            avisos.append(f"no se pudo leer la fecha del {'examen' if acta.examen else 'grado'}")
        avisos.extend(acta.dudas)
        avisos.extend(lectura.razonado)
        if lectura.deducido:
            avisos.append(lectura.deducido)
    if ilegibles:
        avisos.append(
            f"{len(ilegibles)} página(s) sin texto legible: "
            + ", ".join(str(numero) for numero in ilegibles[:10])
        )
    # La hoja que no es un acta dice lo que es: la resolución de los grados con
    # su número, o la ceremonia con sus actas (Odontología, 2026-11-12).
    encabezado = (acta.sesion or ROTULO_DE_CEREMONIA) if ceremonia else (acta.encabezado or NO_APLICA)
    nombre_separado, titulo_separado = nombre_y_titulo_separados(acta.nombre, acta.titulo)
    if not ceremonia and not nombre_limpio(nombre_separado, titulo_separado, nombres_conocidos()):
        # Ninguna acta sin nombre si alguna lectura de su hoja lo trae: la de la
        # IA primero y después las demás, por su peso (UPD3859802 pág. 110: la
        # nota al margen «Post-grado» ganaba a «a la estudiante NURY VARELA
        # ESCUDERO», que la IA sí leyó; 2026-11-12).
        lecturas_de_la_hoja = [lectura.texto_de_la_ia or "", *(t for t, _ in sorted(lectura.textos, key=lambda x: -x[1]))]
        for texto in lecturas_de_la_hoja:
            hallado = nombre_limpio(leer_acta_de_grado([texto]).nombre, titulo_separado, nombres_conocidos()) if texto else None
            if hallado and len(hallado.split()) >= 2:
                avisos.append(f"el nombre se tomó de otra lectura de la hoja («{hallado}»): revíselo en el papel")
                nombre_separado = hallado
                break
    return FilaDeActa(
        archivo=archivo,
        acta=encabezado,
        fecha=acta.fecha.strftime("%d-%m-%Y") if acta.fecha else NO_APLICA,
        folio_inicial=lectura.folios.inicial if lectura.folios.inicial is not None else NO_APLICA,
        folio_final=lectura.folios.final if lectura.folios.final is not None else NO_APLICA,
        folios=tramo.hojas or 1,
        resumen=NO_APLICA,
        observaciones="; ".join(avisos),
        carpeta=carpeta,
        pagina_inicial=tramo.desde,
        pagina_final=tramo.hasta,
        numero=acta.numero or "",
        tipo=ROTULO_DE_CEREMONIA if ceremonia else TIPO_DE_GRADO,
        # Sin el título pegado, la basura ni la «X» de chequeo; y el título,
        # sin los renglones del formulario (Secretaría 3292, 2026-10-31).
        # Y sin la cédula vuelta letras, el lugar de expedición ni la cola del
        # título partida en su renglón; el título con sus palabras del
        # vocabulario (Odontología, 2026-11-12).
        nombre=nombre_limpio(nombre_separado, titulo_separado, nombres_conocidos()) or "",
        titulo=titulo_limpio(titulo_del_vocabulario(titulo_separado)) or "",
        cedula=acta.cedula or "",
    )


def _lectura_del_libro_colectivo(tramo: TramoDeActa, parte: ActaDelLibro, foliadas: Sequence[int]) -> _Lectura:
    """La lectura de un acta del libro colectivo, de su texto cortado: la de toda la promoción, o la de un graduado.

    El acta que nombra a uno solo -- «a la estudiante NURY VARELA ESCUDERO»
    (UPD3859802 pág. 110) -- sigue como las demás actas de grado: su nombre se
    decide entre las lecturas y su PDF lleva su nombre. La que gradúa a varios
    (``es_acta_colectiva``) no lleva nombre: lleva su lista, que lee
    ``_leer_las_actas_colectivas``. Las dos leen sólo su texto, sin la cola de
    la anterior que va en su primera hoja.

    Su número es el de su encabezado -- «Acta (de Grado) Nº X» --, nunca el de
    la resolución que la autoriza: el lector general tomaba «Resolución Nº
    1813» cuando el encabezado decía «# Acta 02.» (2026-11-13). El acta anulada
    -- lo dice el papel o su lista está en blanco -- no gradúa a nadie.
    """
    texto = parte.texto
    acta = completar_acta(ActaDeConsejo(rotulo=ROTULO_DE_GRADO, pagina=1), texto)
    desde, hasta = numero_y_rango(texto)
    lectura = _Lectura(
        tramo=tramo,
        acta=acta,
        foliadas=[p for p in foliadas if p in tramo.en_el_pdf],
        piezas=_piezas_del_tramo(tramo),
        del_libro=parte,
        texto_de_la_ia=texto,
    )
    lectura.textos.append((texto, PESO_DE_LA_IA))
    anulada = acta_anulada(texto)
    colectiva = es_acta_colectiva(texto)
    # La colectiva con su lista sin cédulas -- «Con Énfasis en …: Rosio
    # Rodriguez Castro» (hoja 20) -- no está sin terminar: su lista la lee la IA.
    sin_terminar = None if anulada or colectiva else acta_sin_terminar(texto)
    if colectiva or (anulada and not leer_acta_de_grado([texto]).nombre) or sin_terminar:
        lectura.colectiva = True
        lectura.anulada = anulada or sin_terminar
        lectura.sin_terminar = sin_terminar is not None
        lectura.numero_hasta = hasta
        lectura.acta = replace(
            acta, numero=desde, nombre=None, cedula=None, examen=None, constancia=False, dudas=()
        )
    else:
        if desde:
            lectura.acta = replace(acta, numero=desde)
        if anulada:
            lectura.razonado.append(f"{anulada}: revísela en el papel")
    if parte.cierre and not lectura.colectiva:
        lectura.razonado.append(_CIERRE_EN_LA_SIGUIENTE.format(hoja=parte.cierre))
    lectura.razonado.extend(parte.notas)
    return lectura


#: Cuántas cifras tiene el número de un acta de la serie larga del libro --
#: «05408120», «12007003» --: el que sigue la serie de la anterior.
LARGO_DE_LA_SERIE = 8


def _titulo_comun_del_libro(colectivas: Sequence[_Lectura]) -> None:
    """El título de las actas colectivas que no lo dicen: el más común del libro, con su nota.

    El Acta 04 del 26-02-1982 (UPD3859802, hojas 66-68) gradúa «48
    estudiantes» sin escribir el título, y su fila salía sin título (2026-11-13).
    """
    titulos = Counter(
        titulo_limpio(lectura.acta.titulo) for lectura in colectivas if lectura.acta.titulo and not lectura.anulada
    )
    if not titulos:
        return
    comun = titulos.most_common(1)[0][0]
    for lectura in colectivas:
        if not lectura.acta.titulo and not lectura.anulada and comun:
            lectura.acta = replace(lectura.acta, titulo=comun)
            lectura.razonado.append(
                f"el acta no dice el título: se le puso el más común del libro («{comun}»); revíselo en el papel"
            )


#: La nota del acta cuya lista o cuyas firmas siguen en la hoja en que empieza
#: la siguiente: esa hoja va en los dos PDF y se cuenta en el de la siguiente.
_CIERRE_EN_LA_SIGUIENTE = (
    "el cierre del acta (su lista o sus firmas) sigue en la hoja {hoja}, donde empieza la siguiente acta: "
    "va en los dos PDF y se cuenta en el de la siguiente"
)


def _piezas_del_tramo(tramo: TramoDeActa) -> list[PiezaDeActa]:
    """El acta en una pieza por cada tramo seguido de sus hojas, en el orden de su PDF: «98, 2» son dos."""
    return [PiezaDeActa(ACTA, desde, hasta) for desde, hasta in tramos_seguidos(tramo.en_el_pdf)]


def _con_sus_hojas(filas: list[FilaDeActa], lecturas: Sequence[_Lectura], compartidas: Sequence[int]) -> list[FilaDeActa]:
    """Las filas del libro colectivo con las hojas de su PDF y las que se cuentan en otro.

    La hoja compartida se cuenta en el acta que empieza en ella -- la primera,
    si empiezan dos --: su folio y su página no se suman dos veces en el FUID
    (2026-11-13).
    """
    duenos: dict[int, int] = {}
    for orden, lectura in enumerate(lecturas, start=1):
        primera = lectura.tramo.en_el_pdf[0]
        if primera in compartidas:
            duenos.setdefault(primera, orden)
    for orden, lectura in enumerate(lecturas, start=1):
        for pagina in lectura.tramo.en_el_pdf:
            if pagina in compartidas:
                duenos.setdefault(pagina, orden)
    con_hojas: list[FilaDeActa] = []
    for fila in filas:
        hojas = lecturas[fila.sesion - 1].tramo.en_el_pdf
        en_otra = tuple(p for p in hojas if p in compartidas and duenos.get(p) != fila.sesion)
        seguidas = hojas == tuple(range(fila.pagina_inicial, fila.pagina_final + 1))
        con_hojas.append(
            replace(fila, hojas_del_pdf=() if seguidas and not en_otra else hojas, hojas_contadas_en_otra=en_otra)
        )
    return con_hojas


def _cruces_por_el_folio(lecturas: Sequence[_Lectura]) -> list[int]:
    """Las hojas que van en su PDF detrás de una que no es su vecina del escaneo: el acta siguió por su folio."""
    return sorted(
        {
            siguiente
            for lectura in lecturas
            for anterior, siguiente in zip(lectura.tramo.en_el_pdf, lectura.tramo.en_el_pdf[1:], strict=False)
            if siguiente != anterior + 1
        }
    )



def _filas_de_la_colectiva(
    lectura: _Lectura, *, archivo: str, carpeta: str, ilegibles: list[int]
) -> list[FilaDeActa]:
    """Las filas de un acta colectiva: una por graduado, todas en el PDF del acta (UPD3859802, 2026-11-12).

    Lo eligió el operador: un PDF por acta y una fila del FUID por graduado,
    con su asunto «NOMBRE - TÍTULO» como las demás, desde = su número de acta
    -- el del rango que le toca, si el rango cuadra con la lista -- y hasta =
    su cédula. Los folios del acta, sólo en la fila del primero: en las demás
    se dice dónde están, y el FUID las cuenta en 0 (``folios_en``). Sin lista
    legible, una fila del acta, con la nota.
    """
    acta, tramo = lectura.acta, lectura.tramo
    graduados = lectura.graduados or [GraduadoDelActa(orden=1, nombre=None)]
    numeros, nota_del_rango = numeros_de_los_graduados(acta.numero, lectura.numero_hasta, len(graduados))
    rotulo = rotulo_del_acta_colectiva(acta.numero, lectura.numero_hasta)
    comunes: list[str] = []
    anulada = lectura.anulada and not lectura.sin_terminar
    if lectura.sin_terminar:
        # Nadie la anuló: quedó a medio escribir (hoja 138). Su fila lo dice y
        # el rótulo no dice ANULADA, porque el papel no lo dice.
        comunes.append(f"{lectura.anulada}; no gradúa a nadie: revísela en el papel")
    elif anulada:
        # No gradúa a nadie: una fila del acta, sin graduado, que lo dice
        # (UPD3859802, Acta 05 del 12-12-2003; 2026-11-13).
        rotulo = f"{rotulo} {ANULADA}"
        comunes.append(f"acta anulada: {lectura.anulada}; no gradúa a nadie")
    elif not lectura.graduados:
        comunes.append("acta colectiva: no se pudo leer la lista de sus graduados; revísela en el papel")
    if acta.numero is None:
        comunes.append("no se pudo leer el número del acta")
    if lectura.fecha_descartada:
        comunes.append(lectura.fecha_descartada)
    elif acta.fecha is None:
        comunes.append("no se pudo leer la fecha del grado")
    if nota_del_rango:
        comunes.append(nota_del_rango)
    comunes.extend(lectura.razonado)
    if lectura.deducido:
        comunes.append(lectura.deducido)
    if lectura.del_libro is not None and lectura.del_libro.cierre:
        comunes.append(_CIERRE_EN_LA_SIGUIENTE.format(hoja=lectura.del_libro.cierre))
    if ilegibles:
        comunes.append(
            f"{len(ilegibles)} página(s) sin texto legible: " + ", ".join(str(numero) for numero in ilegibles[:10])
        )
    conocidas = nombres_conocidos()
    # Las actas que no escriben cédulas no avisan que no se leyó ninguna: no hay
    # nada que leer (Acta 05410249 a 05410253, hoja 186).
    trae_cedulas = any(g.cedula for g in lectura.graduados)
    filas: list[FilaDeActa] = []
    primero = ""
    for puesto, (graduado_, numero) in enumerate(zip(graduados, numeros, strict=True)):
        nombre, titulo_separado = _nombre_de_la_lista(
            graduado_.nombre, _titulo_del_graduado(graduado_.titulo, acta.titulo), conocidas
        )
        avisos = list(comunes)
        if lectura.graduados:
            if not nombre:
                avisos.append("no se pudo leer el nombre del graduado")
            elif len(nombre.split()) < 2:
                avisos.append(f"el nombre se leyó de una sola palabra («{nombre}»): revíselo en el papel")
            if not graduado_.cedula and trae_cedulas:
                avisos.append("no se pudo leer la cédula")
            if graduado_.nota:
                avisos.append(graduado_.nota)
        if puesto == 0:
            primero = nombre or f"el graduado {graduado_.orden} del acta"
        else:
            avisos.insert(0, f"acta colectiva: folios en la fila de {primero}")
        filas.append(
            FilaDeActa(
                archivo=archivo,
                acta=(f"{ROTULO_DE_GRADO} No. {numero}" if numero else NO_APLICA)
                + (f" {ANULADA}" if anulada else ""),
                fecha=acta.fecha.strftime("%d-%m-%Y") if acta.fecha else NO_APLICA,
                folio_inicial=lectura.folios.inicial if lectura.folios.inicial is not None else NO_APLICA,
                folio_final=lectura.folios.final if lectura.folios.final is not None else NO_APLICA,
                folios=tramo.hojas or tramo.paginas,
                resumen=NO_APLICA,
                observaciones="; ".join(avisos),
                carpeta=carpeta,
                pagina_inicial=tramo.desde,
                pagina_final=tramo.hasta,
                numero=numero or "",
                tipo=TIPO_DE_GRADO,
                nombre=nombre,
                titulo=_con_su_parentesis(titulo_limpio(titulo_del_vocabulario(titulo_separado)) or ""),
                cedula=graduado_.cedula or "",
                acta_colectiva=rotulo,
                folios_en=primero if puesto else "",
            )
        )
    return filas


#: Lo que lleva detrás el rótulo de un acta anulada.
ANULADA = "ANULADA"
#: Lo que la limpieza puede quitarle a un nombre de la lista: lo que no es nombre.
_NO_ES_NOMBRE_DE_LA_LISTA = re.compile(r"^(?:C|CC|CE|NO|N|DE|DEL|LA|Y|COMPLEMENTARI\w*|PROGRAMA|.{1,2})$")


def _nombre_de_la_lista(
    nombre: str | None, titulo: str | None, conocidas: Collection[str]
) -> tuple[str, str | None]:
    """El nombre de un graduado de la lista con la limpieza de siempre, si no le quita nada que sea nombre.

    La limpieza (``nombre_y_titulo_separados``, ``nombre_limpio``) está hecha
    para la frase «al estudiante …» del acta de uno, donde se pegan el título y
    la cédula. En la lista le quitaba palabras del nombre: «EDGAR MERA
    MONTALVO» quedaba EDGAR MONTALVO (por ENFERMERA), «MEDINA ARNEDO JULIA
    TERESA», ARNEDO JULIA TERESA, y «MARÍA DEL CARMEN SÁBADO FREYOS», MARÍA DEL
    CARMEN (UPD3859802, 2026-11-13). Si lo quitado es de su título, de la
    cédula o basura de dos letras, vale; si no, el nombre va como se leyó.
    """
    separado, titulo_separado = nombre_y_titulo_separados(nombre, titulo)
    limpio = nombre_limpio(separado, titulo_separado, conocidas) or ""
    quedan = set(limpio.split())
    quitadas = [palabra for palabra in (nombre or "").split() if palabra not in quedan]
    if any(not es_un_titulo(palabra) and not _NO_ES_NOMBRE_DE_LA_LISTA.match(_plano_del_titulo(palabra)) for palabra in quitadas):
        return " ".join((nombre or "").split()), titulo
    return limpio, titulo_separado


def _titulo_del_graduado(suyo: str | None, del_acta: str | None) -> str | None:
    """El título del graduado: el suyo, el del acta con su énfasis detrás, o el del acta.

    «Con énfasis en Neurocirugía» bajo el título común del acta es «ESPECIALISTA
    EN … CON ENFASIS EN NEUROCIRUGIA» (UPD3859802, hoja 16; 2026-11-13).
    """
    if suyo and _plano_del_titulo(suyo).startswith("CON ENFASIS") and del_acta:
        return f"{del_acta} {suyo}"
    return suyo or del_acta


def _plano_del_titulo(titulo: str) -> str:
    return unicodedata.normalize("NFD", titulo).encode("ascii", "ignore").decode().upper().strip()


def _con_su_parentesis(titulo: str) -> str:
    """El título con el paréntesis que le falta cerrado: «ENFERMERA (O» es «ENFERMERA (O)»."""
    return f"{titulo})" if titulo.count("(") > titulo.count(")") else titulo


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
        if not es_de_actas(fila):
            continue
        por_carpeta.setdefault(str(fila.get("carpeta") or ""), []).append(fila)
    for grupo in por_carpeta.values():
        _numero_por_la_serie(grupo)
        _deducir_en(grupo)
    # Lo último antes de escribir: ninguna celda vacía sin su porqué. Lo que no
    # es un acta -- una historia académica, una matrícula -- no tiene acta ni
    # folio que deducir: trae ya su porqué.
    return [explicar_lo_que_falta(fila) if es_de_actas(fila) else fila for fila in ordenadas]


#: Las clases de fila que son actas: las de consejo, las de grado y las hojas
#: de su ceremonia. Una fila sin tipo es de un informe viejo de consejo.
_DE_ACTAS = frozenset({TIPO_DOCUMENTAL, TIPO_DE_GRADO, ROTULO_DE_CEREMONIA})


def es_de_actas(fila: Mapping[str, object]) -> bool:
    """Si la fila es de un acta, la única clase con folios encadenados y datos que deducir.

    Las demás habilidades -- historias académicas, matrículas, lo que venga --
    dejan sus filas en el mismo inventario, pero cada una llega ya con su porqué.
    """
    return (fila.get("tipo") or TIPO_DOCUMENTAL) in _DE_ACTAS


#: Lo que cada clase de acta lleva en su fila y el papel puede traer, con su
#: nombre para las notas. El folio y el resumen no: con «Solo OCR» no se leen,
#: y eso lo dice una vez la cabecera del Excel y no cada fila.
_DATOS_DE_CONSEJO = (("acta", "el número del acta"), ("fecha", "la fecha"))
_DATOS_DE_GRADO = (
    ("numero", "el número del acta"),
    ("fecha", "la fecha"),
    ("nombre", "el nombre"),
    ("titulo", "el título"),
    ("cedula", "la cédula"),
)
#: El acta manuscrita de examen (1924-1946) no trae número ni cédula.
_DATOS_DEL_EXAMEN = (("fecha", "la fecha"), ("nombre", "el nombre"), ("titulo", "el título"))
#: Con qué palabra la nota de una fila ya habla de cada dato.
_YA_DICHO = {
    "acta": "número",
    "numero": "número",
    "fecha": "fecha",
    "nombre": "nombre",
    "titulo": "título",
    "cedula": "cédula",
}
#: Lo que en observaciones dice que un dato se completó razonando.
_RAZONADO = re.compile(
    r"se corrigi|de su ceremonia|segunda lectura|hoja por hoja|deducid|ajustad|se tomó"
)


def _vacio(valor: object) -> bool:
    return valor is None or str(valor).strip() in ("", NO_APLICA)


def _datos_de(fila: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    tipo = fila.get("tipo")
    # Lo que no es un acta dice en su nota lo que le falta, con sus campos.
    if tipo == ROTULO_DE_CEREMONIA or not es_de_actas(fila):
        return ()
    if tipo == TIPO_DE_GRADO and es_acta_de_examen(fila.get("acta")):
        return _DATOS_DEL_EXAMEN
    return _DATOS_DE_GRADO if tipo == TIPO_DE_GRADO else _DATOS_DE_CONSEJO


def explicar_lo_que_falta(fila: dict[str, object]) -> dict[str, object]:
    """La fila con el porqué de cada dato que le falta, si su nota no lo decía ya.

    El operador pidió que ninguna celda llegue vacía sin explicación: si el
    papel no deja leer un dato, la fila dice cuál y en qué páginas buscarlo.
    """
    nota = str(fila.get("observaciones") or "")
    faltan = [
        nombre
        for campo, nombre in _datos_de(fila)
        if _vacio(fila.get(campo)) and _YA_DICHO[campo] not in nota
    ]
    if faltan:
        desde, hasta = fila.get("pagina_inicial"), fila.get("pagina_final")
        donde = f"la página {desde}" if desde == hasta else f"las páginas {desde} a {hasta}"
        aviso = f"no se encontró {_enumerar(faltan)} en {donde} del PDF: revíselo en el papel"
        fila["observaciones"] = f"{nota}; {aviso}" if nota else aviso
    return fila


def validar_inventario(filas: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """El control de calidad del inventario antes de entregarlo: qué tan completo va.

    Cuenta las filas completas, las que se completaron razonando -- un año
    corregido, la fecha de la ceremonia, una segunda lectura -- y las que
    llevan algún dato que el papel no trae o no deja leer, por dato. Las hojas
    de ceremonia no cuentan: el FUID no les da fila.
    """
    total = completas = razonadas = pendientes = nombres_dudosos = 0
    por_dato: dict[str, int] = {}
    for fila in filas:
        datos = _datos_de(fila)
        if not datos:
            continue
        total += 1
        faltan = [nombre for campo, nombre in datos if _vacio(fila.get(campo))]
        if faltan:
            pendientes += 1
            for nombre in faltan:
                por_dato[nombre] = por_dato.get(nombre, 0) + 1
        else:
            completas += 1
        if _RAZONADO.search(str(fila.get("observaciones") or "")):
            razonadas += 1
        if "nombre dudoso" in str(fila.get("observaciones") or ""):
            nombres_dudosos += 1
    return {
        "filas": total,
        "completas": completas,
        "razonadas": razonadas,
        "pendientes": pendientes,
        "por_dato": por_dato,
        # Los nombres que las lecturas de la hoja no confirmaron del todo.
        "nombres_dudosos": nombres_dudosos,
    }


def _fecha_de_la_fila(valor: object) -> date | None:
    """«12-07-2017» de la fila a una fecha; ``None`` si no hay."""
    hallada = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", str(valor or ""))
    if not hallada:
        return None
    try:
        return date(int(hallada.group(3)), int(hallada.group(2)), int(hallada.group(1)))
    except ValueError:
        return None


def _numero_por_la_serie(filas: list[dict[str, object]]) -> None:
    """El número de un acta que el OCR truncó, deducido de las sesiones vecinas del mismo libro.

    «ACTA N'l?» del 12/07/2017 entre la 16 (07/07) y la 18 (14/08) es la 17;
    «ACTA N° 01.'^» del 11/09/2015 entre la 012 y la 014, la 013 (Odontología,
    UPD3859796 y UPD3859789, 2026-10-30). Sólo cuando falta un número y uno
    solo entre las dos vecinas, lo leído es su comienzo y la fecha cae entre
    las de ellas. Se anota.
    """
    por_libro: dict[str, list[dict[str, object]]] = {}
    for fila in filas:
        por_libro.setdefault(str(fila.get("archivo") or ""), []).append(fila)
    for suyas in por_libro.values():
        for antes, fila, despues in zip(suyas, suyas[1:], suyas[2:], strict=False):
            leidos = [str(x.get("numero") or "") for x in (antes, fila, despues)]
            if not all(leido.isdigit() for leido in leidos):
                continue
            previo, leido, siguiente = (int(x) for x in leidos)
            falta = previo + 1
            if siguiente != falta + 1 or leido == falta or not str(falta).startswith(str(leido)):
                continue
            fechas = [_fecha_de_la_fila(x.get("fecha")) for x in (antes, fila, despues)]
            if None in fechas or not fechas[0] <= fechas[1] <= fechas[2]:
                continue
            ancho = max(len(leidos[0]), len(leidos[2]))
            fila["numero"] = str(falta).zfill(ancho)
            nota = (
                f"el número del acta se leyó «{leidos[1]}» y se dedujo de la serie: "
                f"va entre la {leidos[0]} y la {leidos[2]}"
            )
            fila["observaciones"] = "; ".join(parte for parte in (nota, str(fila.get("observaciones") or "")) if parte)


def _deducir_en(filas: list[dict[str, object]]) -> None:
    tramos = [
        (
            _folio(fila.get("folio_inicial")),
            _folio(fila.get("folio_final")),
            # Un acta de grado puede traer «140-141», el rango de su folio
            # manuscrito, y no un número: entonces no hay folios que encadenar.
            _folio(fila.get("folios")) or 0,
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
