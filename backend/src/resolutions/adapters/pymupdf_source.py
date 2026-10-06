from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image

from ..application.ports import Band, LineBox
from ..domain.diploma import TextLine
from .mupdf_messages import drenar

#: PDF user space is 72 dpi. Every render scales from there.
_PDF_DPI = 72.0

#: Con qué calidad se comprime una página que va a viajar por la red. Ochenta y
#: cinco y no setenta y cinco: la diferencia de peso es de 140 KB por página, y
#: lo que se lee son trazos de pluma donde el artefacto de compresión cae justo
#: encima del dato. Comprobado sobre la cara 3 del libro 7, manuscrita: misma
#: cédula, mismo nombre, mismos folios y misma fecha que en PNG.
CALIDAD_JPEG = 85

#: Cuánto puede apartarse la imagen de fondo del tamaño de la hoja, en puntos,
#: para seguir considerándola la hoja entera. Dos: lo que deja un escáner al
#: redondear.
_TOLERANCIA_DE_COBERTURA = 2.0

#: Por encima de este peso no se manda el escaneo original: un JPEG de 600 ppp
#: a color pesa más que la copia en gris a 300 que se mandaría en su lugar, y
#: lo que se gana en rasterizado se pierde subiéndolo. Un libro de la
#: Universidad escaneado en gris a 300 ppp da medio mega por cara.
_PESO_MAXIMO_ESCANEADA = 1_500_000

#: A cuánto se rasteriza para contar tinta. No se va a leer nada con esto: se
#: va a preguntar si la esquina está escrita o en blanco, y para eso sobra.
_INK_DPI = 144.0

#: Por debajo de este lado en píxeles la banda no da para contar columnas.
_INK_MIN_SIDE = 10

#: Cuánto más oscuro que el papel de la banda para contar como entintado. Sobre
#: el gris que devuelve el escáner en las hojas pegadas al lomo, menos de esto
#: empieza a contar la propia textura del papel.
_INK_CONTRAST = 45

#: Y a partir de cuánto ya no es tinta de nadie. Lo escrito a mano sale gris
#: medio; el canto del libro y la sombra del alimentador salen negro saturado.
_INK_SATURATION = 150

#: Qué parte de la columna tiene que estar entintada para que deje de ser un
#: trazo. Una columna llena de arriba abajo es el canto, no una letra.
_INK_FULL_COLUMN = 0.50

#: Cuántas columnas a cada lado de esa franja se descartan con ella. El borde
#: negro deja un halo gris alrededor que tiene el tono de la escritura, y sin
#: esto ese halo se contaba como folio en las hojas más deterioradas del libro.
_INK_HALO = 20


class PyMuPDFPageSource:
    """A PDF opened once, read page by page.

    Pixmaps are produced on demand and dropped immediately. Rendering a 400-page
    scan eagerly would cost hundreds of megabytes per document, and multiplying
    that by the worker count is how a machine falls over under load.
    """

    def __init__(self, path: Path, nombre: str | None = None) -> None:
        self._path = path
        #: Cómo llamó el operador al archivo. Las subidas se guardan en disco
        #: con un nombre generado, y un aviso que dice "6ea93142663d.pdf" no le
        #: sirve a nadie para saber qué documento venía defectuoso.
        self._nombre = nombre or path.name
        self._document = pymupdf.open(path)
        #: La capa de texto ya extraída, por número de página.
        self._textos: dict[int, str] = {}
        #: Los renglones de cada página con su geometría, en las dos formas en
        #: que se piden, sacados de una sola pasada sobre la estructura de la
        #: página. ``lines_of`` y ``boxes_of`` recorrían esa estructura cada
        #: uno por su cuenta, y en un libro de diplomas se piden las dos --
        #: y ``boxes_of`` varias veces: al rastrear la cédula y al recortar el
        #: nombre --, de modo que MuPDF reconstruía la misma página tres o
        #: cuatro veces por cara.
        self._renglones: dict[int, tuple[list[TextLine], list[LineBox]]] = {}

    @property
    def page_count(self) -> int:
        return self._document.page_count

    def text_of(self, page_number: int) -> str:
        """La capa de texto de una página, extraída una sola vez.

        Se guarda lo extraído porque el mismo texto se pide tres veces por
        página en el recorrido normal: al calcular la huella que decide los
        cortes, al preguntarle al catálogo qué clase de papel es cada unidad, y
        al buscarle la fecha. Medido sobre un expediente de 97 páginas eran 249
        extracciones para 97 hojas, y MuPDF vuelve a recorrer la página entera
        cada vez.

        La memoria es acotada y muere con la fuente: el texto plano de ese
        expediente son unos 300 KB, y un `PyMuPDFPageSource` vive lo que dura
        un documento. Guardarlo aquí y no en la aplicación es deliberado --
        el coste es de esta implementación, no del caso de uso, y así ninguna
        firma de `application/` cambia para resolverlo.
        """
        guardado = self._textos.get(page_number)
        if guardado is None:
            guardado = self._document[page_number - 1].get_text("text")
            self._textos[page_number] = guardado
        return guardado

    def sheet_of(self, page_number: int) -> tuple[int, int]:
        """El tamaño físico de la hoja, en puntos enteros.

        Redondeado porque lo que interesa es de qué lote de escaneo salió, no su
        medida exacta: un alimentador no entrega dos veces el mismo decimal.
        """
        rect = self._document[page_number - 1].rect
        return (round(rect.width), round(rect.height))

    def boxes_of(self, page_number: int) -> list[LineBox]:
        """Dónde está cada renglón de la página, en el orden de :meth:`text_of`.

        Es lo que permite distinguir un encabezado de una frase que empieza por
        la palabra "Resolución". Un encabezado va centrado y arriba; en el acta
        de comité del folio 245 del libro 00960-00979, la frase "La Dra. Rosaura
        Arrieta Flórez realiza la respectiva sustentación de la…" parte a mitad
        de página y su segundo renglón empieza justamente por "Resolución No.
        00520 de 202.". En texto plano ese renglón es indistinguible de un
        encabezado; en la página está a media altura y pegado al margen
        izquierdo, y ahí no hay ninguna duda.

        El orden tiene que ser el de ``text_of`` porque las candidatas se
        localizan por número de renglón. MuPDF construye los dos de la misma
        estructura interna, así que coinciden; aun así el llamador comprueba el
        texto antes de fiarse de la caja, porque una geometría mal alineada
        descartaría encabezados de verdad y perder una resolución en silencio es
        exactamente lo que esto viene a evitar.
        """
        return list(self._renglones_de(page_number)[1])

    def lines_of(self, page_number: int) -> list[TextLine]:
        """The page's lines with enough geometry to know what sits above what.

        ``text_of`` is not enough for a form. These books hand back their lines
        in an order that puts the registration date before the graduate's name,
        so a reader that trusts reading order picks the wrong line off the page.
        The position does not lie.
        """
        return list(self._renglones_de(page_number)[0])

    def _renglones_de(self, page_number: int) -> tuple[list[TextLine], list[LineBox]]:
        guardado = self._renglones.get(page_number)
        if guardado is None:
            guardado = self._extraer_renglones(page_number)
            self._renglones[page_number] = guardado
        return guardado

    def _extraer_renglones(self, page_number: int) -> tuple[list[TextLine], list[LineBox]]:
        """Una pasada por la estructura de la página, y de ella las dos listas."""
        page = self._document[page_number - 1]
        rect = page.rect
        con_medida = bool(rect.width and rect.height)
        lines: list[TextLine] = []
        cajas: list[LineBox] = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", ()):
                texto = "".join(span["text"] for span in line["spans"])
                x0, y0, x1, _ = line["bbox"]
                if con_medida:
                    cajas.append(
                        LineBox(
                            text=texto,
                            center_x=((x0 + x1) / 2 - rect.x0) / rect.width,
                            top=(y0 - rect.y0) / rect.height,
                        )
                    )
                limpio = texto.strip()
                if limpio:
                    lines.append(TextLine(text=limpio, y=y0, x=x0))
        lines.sort(key=lambda item: (item.y, item.x))
        return lines, cajas

    def ink_of(self, page_number: int, band: Band) -> tuple[float, float] | None:
        """Cuánta tinta hay en esa banda, por columnas y sin leer nada.

        Dos cuentas, las dos en proporción de columnas de la banda: cuántas
        llevan tinta de espesor de escritura y cuántas están oscuras de arriba
        abajo. La segunda existe porque el canto del libro y la sombra del
        alimentador entran en la banda tan negros como un trazo, y sólo se
        distinguen por la forma: una firma se reparte a lo ancho, un defecto de
        escaneo llena la columna entera.

        El umbral es relativo al papel de la propia banda, no un valor fijo: el
        escaneo de un libro encuadernado cambia de tono de una hoja a la
        siguiente -- la que estaba junto al lomo sale gris -- y un umbral
        absoluto leería esa hoja entera como tinta.

        Se rasteriza a 144 ppp, que es poco para leer y de sobra para saber si
        hay algo escrito. A esa escala la banda del folio son unos cuarenta mil
        píxeles y el libro entero se mide en once segundos.
        """
        page = self._document[page_number - 1]
        rect = page.rect
        clip = pymupdf.Rect(
            rect.x0 + band.x0 * rect.width,
            rect.y0 + band.y0 * rect.height,
            rect.x0 + band.x1 * rect.width,
            rect.y0 + band.y1 * rect.height,
        )
        zoom = _INK_DPI / _PDF_DPI
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(zoom, zoom),
            clip=clip,
            colorspace=pymupdf.csGRAY,
            alpha=False,
        )
        ancho, alto, muestras = pixmap.width, pixmap.height, pixmap.samples
        if ancho < _INK_MIN_SIDE or alto < _INK_MIN_SIDE:
            return None

        # El papel de esta banda, no un blanco de referencia: la hoja pegada al
        # lomo sale gris entera y un umbral absoluto la leería como tinta.
        papel = _mediana(muestras, ancho, alto)
        entintado = papel - _INK_CONTRAST
        saturado = papel - _INK_SATURATION

        # Cada píxel se clasifica de una vez con una tabla de 256 entradas, y
        # cada columna se suma sobre un corte con paso. Es la misma cuenta que
        # hacía un bucle en Python píxel a píxel, y da los mismos números en
        # todas las páginas contra las que se comprobó; lo que cambia es que
        # el libro entero se mide en un segundo en vez de en diez.
        #
        # Lo escrito a mano sale en grises; lo que pone el escáner -- canto,
        # sombra, borde de la hoja levantada -- sale negro del todo. Quedarse
        # con los grises descarta casi todo el defecto de escaneo sin tocar la
        # escritura: eso es la segunda tabla.
        es_oscuro = bytes(1 if valor < entintado else 0 for valor in range(256))
        es_trazo = bytes(1 if saturado <= valor < entintado else 0 for valor in range(256))
        oscuros = muestras.translate(es_oscuro)
        trazos = muestras.translate(es_trazo)
        oscuras = [sum(oscuros[x::ancho]) for x in range(ancho)]
        trazo = [sum(trazos[x::ancho]) for x in range(ancho)]

        # Una columna entintada de arriba abajo no es un trazo: es el canto del
        # libro. Se veta ella y lo que tiene al lado, porque alrededor de esa
        # franja queda un halo gris que sí tiene tono de escritura.
        vetadas: set[int] = set()
        for x in range(ancho):
            if oscuras[x] > _INK_FULL_COLUMN * alto:
                vetadas.update(range(max(0, x - _INK_HALO), min(ancho, x + _INK_HALO + 1)))

        tinta = sum(trazo[x] for x in range(ancho) if x not in vetadas)
        # Normalizado por el cuadrado del alto -- "cuántos caracteres caben en
        # esto" -- y no por el área de la banda: medido en fracción de ancho, un
        # folio de un dígito se perdía por pequeño al lado de uno de tres.
        return (tinta / (alto * alto), len(vetadas) / ancho)

    def render(
        self,
        page_number: int,
        band: Band | None = None,
        dpi: int = 200,
        formato: str = "png",
    ) -> bytes:
        """La página, o una banda de ella, rasterizada en gris.

        ``formato`` es ``"png"`` para lo que va a leer el motor de casa -- que
        lo lee un 20 % más rápido que otra cosa -- y ``"jpeg"`` para lo que va
        a viajar al proveedor de pago, que lo recibe igual pero pesa cuatro
        veces menos y, sobre todo, se codifica cinco veces más rápido: sobre
        una cara de 300 ppp, escribir el PNG cuesta un cuarto de segundo del
        hilo que rasteriza, y ese hilo es el único que puede rasterizar.
        """
        page = self._document[page_number - 1]
        clip = None
        if band is not None:
            rect = page.rect
            clip = pymupdf.Rect(
                rect.x0 + band.x0 * rect.width,
                rect.y0 + band.y0 * rect.height,
                rect.x0 + band.x1 * rect.width,
                rect.y0 + band.y1 * rect.height,
            )

        zoom = dpi / _PDF_DPI
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(zoom, zoom),
            clip=clip,
            # Greyscale: Tesseract binarises anyway, and it is a third of the
            # bytes to move around per page.
            colorspace=pymupdf.csGRAY,
            alpha=False,
        )
        if formato == "jpeg":
            # Con PIL y no con MuPDF: el codificador de MuPDF tarda 160 ms en
            # una cara de 300 ppp y el de PIL -- libjpeg-turbo -- catorce, y
            # los dos producen el mismo JPEG a la misma calidad.
            salida = BytesIO()
            Image.frombuffer(
                "L", (pixmap.width, pixmap.height), pixmap.samples, "raw", "L", 0, 1
            ).save(salida, "JPEG", quality=CALIDAD_JPEG)
            return salida.getvalue()
        return pixmap.tobytes("png")

    def imagen_escaneada(self, page_number: int) -> bytes | None:
        """El JPEG con que se escaneó esta cara, tal cual está dentro del PDF.

        Un libro escaneado es, página por página, una sola imagen que cubre la
        hoja entera, y rasterizarla para mandarla al proveedor es decodificar
        ese JPEG, volver a muestrearlo y volver a comprimirlo: 170 ms de este
        hilo por cara -- el único que puede rasterizar -- para obtener una copia
        peor de lo que ya había. Sacar la imagen tal cual cuesta un milisegundo
        y es la misma tinta que vio el escáner.

        Sólo cuando es seguro que lo que hay dentro es lo que se ve: una única
        imagen, en JPEG, que cubre la página, sin rotación ni en la página ni
        en su colocación, y de un peso que compense mandarla entera. Cualquier
        otra cosa -- dos imágenes, una girada, un escaneo a 600 ppp de cinco
        megas -- devuelve ``None`` y quien pregunta rasteriza como siempre.
        """
        page = self._document[page_number - 1]
        if page.rotation:
            return None
        imagenes = page.get_images(full=True)
        if len(imagenes) != 1:
            return None
        xref = imagenes[0][0]
        try:
            colocaciones = page.get_image_rects(xref, transform=True)
        except Exception:  # noqa: BLE001 - sin colocación no se sabe qué se ve
            return None
        if len(colocaciones) != 1:
            return None
        rect, matriz = colocaciones[0]
        hoja = page.rect
        if abs(rect.width - hoja.width) > _TOLERANCIA_DE_COBERTURA or abs(
            rect.height - hoja.height
        ) > _TOLERANCIA_DE_COBERTURA:
            return None
        if abs(matriz.b) > 1e-6 or abs(matriz.c) > 1e-6 or matriz.a <= 0 or matriz.d <= 0:
            return None
        try:
            extraida = self._document.extract_image(xref)
        except Exception:  # noqa: BLE001 - una imagen que no se deja sacar se rasteriza
            return None
        if extraida.get("ext") not in ("jpeg", "jpg"):
            return None
        # Gris o RGB. Un JPEG en CMYK es de imprenta, no de escáner, y no todo
        # el mundo lo decodifica como se ve.
        if int(extraida.get("colorspace") or 0) > 3:
            return None
        imagen = extraida.get("image") or b""
        if not imagen or len(imagen) > _PESO_MAXIMO_ESCANEADA:
            return None
        return imagen

    def close(self) -> None:
        self._document.close()
        # Y con él, el texto que se guardó de sus páginas: la fuente se cierra
        # cuando el documento está entregado, y a partir de ahí nadie va a
        # volver a pedirlo.
        self._textos.clear()
        self._renglones.clear()
        # Lo que MuPDF fue anotando mientras se leía el documento -- un perfil
        # de color roto, un objeto que no está donde dice -- traducido y con el
        # nombre del archivo delante. Aquí y no en cada página: las páginas se
        # leen en varios hilos sobre este mismo PDF y el almacén de MuPDF es uno
        # solo para todo el proceso, así que decir de qué página vino cada aviso
        # sería adjudicarlo al azar.
        drenar(self._nombre)

    def __enter__(self) -> PyMuPDFPageSource:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _mediana(muestras: bytes, ancho: int, alto: int) -> int:
    """El tono de gris que parte la banda por la mitad, sin ordenar los píxeles.

    Se cuenta un histograma de 256 celdas y se recorre hasta pasar la mitad.
    Ordenar cuarenta mil bytes para quedarse con el del medio costaba más que
    todo el resto de la medida.
    """
    histograma = Image.frombuffer("L", (ancho, alto), muestras, "raw", "L", 0, 1).histogram()
    mitad = len(muestras) // 2
    acumulado = 0
    for valor, cuenta in enumerate(histograma):
        acumulado += cuenta
        if acumulado > mitad:
            return valor
    return 255


class PyMuPDFDocumentStore:
    def __init__(self, nombre: str | None = None) -> None:
        #: El nombre con que se informa de lo que traiga el documento. Lo pone
        #: quien monta el trabajo, que es el único que sabe cómo se llamaba el
        #: archivo antes de subirlo.
        self._nombre = nombre

    def open(self, document: Path) -> PyMuPDFPageSource:
        return PyMuPDFPageSource(document, self._nombre)
