"""Diez nombres por página facturada, en vez de uno.

El OCR de pago cobra por **página procesada**, no por petición. Esa distinción
es la que decide lo que cuesta un libro manuscrito, y cuesta trabajo verla:
agrupar páginas en un PDF baja las llamadas de cuatrocientas a veinte y no
ahorra un céntimo, porque el proveedor sigue contando cuatrocientas páginas.

Lo que sí ahorra es **mandar menos papel por página facturada**. De una cara de
diploma, lo único que hace falta para nombrar el archivo es la franja donde está
escrito el nombre: un ocho por ciento de la hoja. Diez de esas franjas apiladas
caben holgadamente en una imagen, y esa imagen es **una** página procesada.

Medido sobre el libro de posgrados 3858080 -- manuscrito, de los años setenta y
sin una sola cédula en el papel --: cinco bandas en un mosaico, una página
facturada, los cinco nombres legibles y cada uno devuelto a su página. Sobre el
libro entero eso es pasar de ciento noventa y siete páginas facturadas a unas
veinte.

Lo que se pierde, y conviene decirlo porque es una decisión y no un descuido:
del mosaico sale **sólo el nombre**. El folio, la fecha y el título de esas
caras no se leen. En estos libros da igual -- van manuscritos y salen ilegibles
de todos modos, así que el FUID los escribe N/A con mosaico y sin él -- pero en
un libro donde esos campos se leyeran, esto los dejaría fuera.
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from statistics import median

from ..application.ports import Band
from ..domain.diploma import cedula_tras_el_rotulo, lines_from_text, nombre_suelto

logger = logging.getLogger(__name__)

#: Cuántos mosaicos se le piden al proveedor a la vez. Leer es esperar: cada
#: mosaico son unos segundos de proveedor durante los que este proceso no
#: hace nada, y un libro de cuatrocientas caras son cuarenta mosaicos. Cuatro
#: en vuelo son cuarenta franjas en camino, que el proveedor contesta sin
#: pedir que se le espere.
LECTORES = 4

#: Cuántas franjas van en cada mosaico.
#:
#: Diez. Es el número que decide el ahorro -- cada mosaico es una página
#: facturada -- pero no se puede subir sin más: el mosaico también es la unidad
#: de pérdida, porque una petición que se cae deja sin nombre a las diez caras
#: que llevaba. Y por encima de una docena la imagen se vuelve tan alta que el
#: proveedor la reduce de escala, y entonces la letra manuscrita deja de leerse,
#: que es precisamente lo que se le está pidiendo.
TAMANO_DEL_MOSAICO = 10

#: A cuánto se rasteriza cada franja. Igual que una página entera: lo que se
#: recorta es pequeño y no hay ninguna razón para darle menos resolución que la
#: que tendría dentro de la hoja.
DPI = 300

#: Las leyendas impresas detrás de las cuales el formulario escribe el nombre.
#:
#: Son el ancla que dice **dónde recortar**. Van impresas, de modo que la capa
#: de texto las trae aunque el nombre de al lado esté manuscrito, que es
#: exactamente el caso que este mosaico existe para resolver.
LEYENDAS = (
    "ATENCION A QUE EL",
    "NOMBRES Y APELLIDOS DEL GRADUANDO",
)

#: Cuánto papel se recorta, en fracción de la altura de la hoja.
#:
#: Generoso por arriba y por abajo: el nombre va escrito a mano sobre el renglón
#: impreso, y una firma larga se sale por los dos lados. Recortar justo sería
#: ahorrar unos píxeles a cambio de cortarle la cabeza a las mayúsculas.
ALTO_DE_LA_BANDA = 0.085
MARGEN_ARRIBA = 0.012

#: El número de página que lleva cada franja escrito al lado.
#:
#: Se puso primero como forma de devolver cada nombre a su página, y **no
#: funciona para eso**: el proveedor lee esa columna de números como un bloque
#: aparte y la devuelve separada de las franjas, de modo que los rótulos llegan
#: todos juntos y ninguno pegado a su nombre. Medido sobre ocho franjas del
#: libro de posgrados: los ocho nombres correctos y en orden, un solo rótulo
#: emparejado.
#:
#: Se conserva porque sigue sirviendo para lo otro: abrir el mosaico y
#: comprobar a ojo de qué cara salió cada nombre cuando algo no cuadra.

#: Lo que separa visualmente una franja de la siguiente, en puntos.
_SEPARACION = 14

#: Cuánto sitio se deja a la izquierda para la etiqueta.
_ANCHO_DE_LA_ETIQUETA = 150


def _plano(texto: str) -> str:
    import unicodedata

    return "".join(
        caracter
        for caracter in unicodedata.normalize("NFD", texto.upper())
        if not unicodedata.combining(caracter)
    )


class MosaicoDeNombres:
    """Lee los nombres de muchas caras pagando por unas pocas páginas.

    Recibe la función de lectura en vez del motor entero -- `leer(bytes) -> str`
    -- porque lo único que necesita del proveedor es que transcriba una imagen.
    Así puede usarse con el motor de pago, con uno local o con un doble de
    prueba, y esta clase no sabe cuál le tocó.
    """

    #: Qué campo lee este mosaico, para decirlo en el registro.
    CAMPO = "nombres"
    #: Las leyendas impresas que anclan la franja, y su geometría.
    LEYENDAS = LEYENDAS
    ALTO = ALTO_DE_LA_BANDA
    MARGEN = MARGEN_ARRIBA

    def __init__(
        self,
        leer: Callable[[bytes], str],
        tamano: int = TAMANO_DEL_MOSAICO,
        dpi: int = DPI,
        lectores: int = LECTORES,
    ) -> None:
        self._leer = leer
        self._tamano = max(1, tamano)
        self._dpi = dpi
        self._lectores = max(1, lectores)

    def leer_franjas(self, source, paginas: Sequence[int]) -> dict[int, str]:
        """El campo de cada una de esas caras, hasta donde el papel lo suelte.

        Los mosaicos se arman en este hilo -- MuPDF no promete ser seguro entre
        hilos sobre el mismo documento -- y se leen en varios: mientras el
        proveedor contesta por uno, aquí se recorta el siguiente. Iban uno
        detrás de otro, y en un libro de cuatrocientas caras eran cuarenta
        esperas en fila.

        Nunca levanta. Un mosaico que falla deja sin nombre a las caras que
        llevaba y no toca a las demás: cada uno es una petición independiente, y
        perder una tanda es perder diez nombres, no el libro.
        """
        bandas = self._bandas(source, paginas)
        if not bandas:
            logger.info(
                "ninguna de las %d caras dice dónde está su nombre; no hay mosaico "
                "que armar",
                len(paginas),
            )
            return {}

        encontrados: dict[int, str] = {}
        ordenadas = [pagina for pagina in paginas if pagina in bandas]
        tandas = [
            ordenadas[arranque : arranque + self._tamano]
            for arranque in range(0, len(ordenadas), self._tamano)
        ]
        vuelo: dict = {}

        def recoger(todo: bool = False) -> None:
            while vuelo and (todo or len(vuelo) >= self._lectores):
                listos, _ = wait(list(vuelo), return_when=FIRST_COMPLETED)
                for futuro in listos:
                    tanda = vuelo.pop(futuro)
                    texto = futuro.result()
                    if texto is not None:
                        encontrados.update(self._repartir_texto(texto, tanda))

        with ThreadPoolExecutor(max_workers=self._lectores) as pool:
            for tanda in tandas:
                recoger()
                imagen = self._armar(source, tanda, bandas)
                if imagen is None:
                    continue
                vuelo[pool.submit(self._leer_protegido, imagen, len(tanda))] = tanda
            recoger(todo=True)

        logger.info(
            "mosaico de %s: %d leídos de %d caras en %d páginas facturadas",
            self.CAMPO,
            len(encontrados),
            len(ordenadas),
            (len(ordenadas) + self._tamano - 1) // self._tamano,
        )
        return encontrados

    #: El nombre de siempre para el mosaico de siempre.
    nombres = leer_franjas

    def otra_mirada(self) -> MosaicoDeNombres:
        """El mismo mosaico con otro recorte y otra resolución: una segunda lectura
        que no repite la primera.

        Hace falta porque el proveedor es **determinista**: la misma franja
        devuelve el mismo texto -- medido sobre 353 caras del libro 7, 353
        iguales --, así que repetirla no es una segunda opinión. Con más
        margen alrededor del renglón y a 420 ppp la imagen es otra, y sobre 74
        cédulas en disputa contestó distinto de la primera franja en 21: trece
        veces dando la razón a la página entera y ocho dejando la duda en pie.
        """
        clon = copy.copy(self)
        clon._dpi = int(self._dpi * 1.4)
        clon.ALTO = self.ALTO * 1.35
        clon.MARGEN = self.MARGEN * 1.7
        return clon

    def _repartir_texto(self, texto: str, tanda: Sequence[int]) -> dict[int, str]:
        return _repartir(texto, tanda)

    def _leer_protegido(self, imagen: bytes, cuantas: int) -> str | None:
        """Una lectura que falla es un mosaico sin nombres, no un libro sin leer."""
        try:
            return self._leer(imagen)
        except Exception:  # noqa: BLE001 - una tanda, no el libro
            logger.warning("falló el mosaico de %d caras", cuantas, exc_info=True)
            return None

    # -- dónde recortar --------------------------------------------------------

    def _bandas(self, source, paginas: Sequence[int]) -> dict[int, Band]:
        """Dónde vive el nombre en cada cara, y qué hacer con las que no lo dicen.

        Las caras cuya capa de texto trae la leyenda impresa lo dicen ellas
        mismas. Las que no -- un escaneo que se comió esa línea -- heredan la
        **altura mediana de las que sí**, porque estos libros son cien veces el
        mismo formulario y el renglón del nombre está siempre a la misma altura.

        Es una deducción y no una suposición: se calcula con las caras de este
        libro y no con una constante escrita aquí. Si ninguna cara dice dónde
        mirar, no se inventa: no hay mosaico.
        """
        alturas: dict[int, float] = {}
        for pagina in paginas:
            altura = self._altura_de_la_leyenda(source, pagina)
            if altura is not None:
                alturas[pagina] = altura

        if not alturas:
            return {}

        habitual = median(alturas.values())
        return {
            pagina: self._banda(alturas.get(pagina, habitual)) for pagina in paginas
        }

    def _banda(self, arriba: float) -> Band:
        desde = max(0.0, arriba - self.MARGEN)
        return Band(0.0, desde, 1.0, min(1.0, desde + self.ALTO + self.MARGEN))

    def _altura_de_la_leyenda(self, source, pagina: int) -> float | None:
        """A qué altura está la leyenda impresa que ancla la franja."""
        leer = getattr(source, "boxes_of", None)
        if leer is None:
            return None
        try:
            cajas = leer(pagina)
        except Exception:  # noqa: BLE001 - sin cajas, esta cara hereda la mediana
            return None
        for caja in cajas:
            texto = _plano(caja.text or "")
            if any(leyenda in texto for leyenda in self.LEYENDAS):
                return caja.top
        return None

    # -- cómo se arma ----------------------------------------------------------

    def _armar(self, source, tanda: Sequence[int], bandas: dict[int, Band]) -> bytes | None:
        """Las franjas de esas caras apiladas en una imagen, cada una rotulada."""
        try:
            import pymupdf
        except Exception:  # noqa: BLE001 - sin MuPDF no hay mosaico, y no pasa nada
            logger.debug("no se pudo importar pymupdf para el mosaico", exc_info=True)
            return None

        recortes = []
        for pagina in tanda:
            try:
                recortes.append(
                    (pagina, pymupdf.Pixmap(source.render(pagina, bandas[pagina], self._dpi)))
                )
            except Exception:  # noqa: BLE001 - una franja, no la tanda
                logger.debug("no se pudo recortar el nombre de la página %s", pagina)
        if not recortes:
            return None

        ancho = max(pix.width for _, pix in recortes) + _ANCHO_DE_LA_ETIQUETA + _SEPARACION
        alto = sum(pix.height + _SEPARACION for _, pix in recortes) + _SEPARACION
        lienzo = pymupdf.open()
        try:
            hoja = lienzo.new_page(width=ancho, height=alto)
            hoja.draw_rect(hoja.rect, color=(1, 1, 1), fill=(1, 1, 1))
            y = _SEPARACION
            for pagina, pix in recortes:
                # El rótulo, en tipografía limpia: es lo único de esta imagen
                # que el OCR va a leer sin esfuerzo, y es lo que devuelve cada
                # nombre a su página aunque vuelvan desordenados.
                hoja.insert_text((_SEPARACION, y + pix.height / 2), f"[{pagina}]", fontsize=44)
                hoja.insert_image(
                    pymupdf.Rect(
                        _ANCHO_DE_LA_ETIQUETA, y, _ANCHO_DE_LA_ETIQUETA + pix.width, y + pix.height
                    ),
                    pixmap=pix,
                )
                y += pix.height + _SEPARACION
            return hoja.get_pixmap(alpha=False).tobytes("jpeg", jpg_quality=88)
        except Exception:  # noqa: BLE001 - armar el mosaico no puede tumbar el libro
            logger.warning("no se pudo armar el mosaico", exc_info=True)
            return None
        finally:
            lienzo.close()


class MosaicoDeCedulas(MosaicoDeNombres):
    """La cédula de muchas caras en franjas ampliadas, diez por página facturada.

    Existe porque a página entera el motor de pago **se come dígitos** de la
    cédula manuscrita -- "45425" donde el papel dice 45.425.748 -- y ese
    número no se sostiene, así que el archivo se queda sin ella. En la franja
    del renglón "C.C. No.", recortada y ampliada, los lee casi todos: medido
    sobre diez caras del libro 7 que la lectura entera había dejado sin
    cédula, **diez de diez** creíbles y los ocho comprobables contra el papel,
    correctos. Y cuesta una página facturada por cada diez caras.

    Lo que devuelve es sólo lo que sigue al rótulo impreso y se sostiene como
    cédula. Un número con una letra dentro -- "4V.425.748" -- no se recorta ni
    se arregla: se deja para que lo mire alguien.
    """

    CAMPO = "cédulas"
    #: El rótulo impreso del formulario tras el que va escrita la cédula.
    LEYENDAS = ("C.C", "CC.", "CEDULA", "IDENTIFICADO CON")
    #: El renglón de la cédula es uno solo y va justo detrás del rótulo.
    ALTO = 0.045
    MARGEN = 0.012

    cedulas = MosaicoDeNombres.leer_franjas

    def _repartir_texto(self, texto: str, tanda: Sequence[int]) -> dict[int, str]:
        return _repartir_cedulas(texto, tanda)


#: La etiqueta con el número de página que lleva cada franja a la izquierda.
_ETIQUETA = re.compile(r"\[(\d{1,4})\]")

#: El rótulo de la cédula, para trocear la respuesta cuando viene sin etiquetas.
_RENGLON_CON_ROTULO = re.compile(r"C\.?\s?C\.?\s*N[O°º.]|[I¡]DENT[I¡]F[I¡]CAD[OA]\s+CON", re.I)

#: Las leyendas del nombre, para quitarlas cuando el proveedor las pega en el
#: mismo renglón que el nombre (pasa cuando contesta en forma de tabla).
_LEYENDA_DEL_NOMBRE = re.compile(
    r"atenci[oó]n\s+a\s+que\s+el(\s+se[ñn]or)?|nombres\s+y\s+apellidos\s+del\s+graduando",
    re.I,
)


def _por_etiqueta(texto: str, tanda: Sequence[int]) -> dict[int, str] | None:
    """Los trozos por la etiqueta de cada franja, cuando volvió pegada a su renglón.

    El proveedor contesta unas veces en prosa y otras como una tabla con la
    etiqueta en la primera columna: ``| [98] | C.C. No. 7.454.012 ... |``. En
    la tabla cada renglón lleva su etiqueta y no hay nada que alinear. Sólo
    vale cuando **todas** las franjas volvieron así; si las etiquetas llegaron
    sueltas en un bloque aparte -- que es lo otro que hace -- se contesta
    ``None`` y se reparte por la leyenda, como siempre.
    """
    esperadas = {int(pagina) for pagina in tanda}
    trozos: dict[int, str] = {}
    for renglon in texto.splitlines():
        etiquetas = [int(e) for e in _ETIQUETA.findall(renglon) if int(e) in esperadas]
        if len(etiquetas) != 1:
            continue
        resto = _ETIQUETA.sub(" ", renglon).replace("|", " ").strip(" -")
        if resto:
            trozos.setdefault(etiquetas[0], resto)
    if set(trozos) != esperadas:
        return None
    return trozos


def _repartir_cedulas(texto: str, tanda: Sequence[int]) -> dict[int, str]:
    """Cada cédula de vuelta a su página: por etiqueta, o por el rótulo en orden."""
    trozos = _por_etiqueta(texto, tanda)
    if trozos is None:
        renglones = [
            renglon for renglon in texto.splitlines() if _RENGLON_CON_ROTULO.search(renglon)
        ]
        if len(renglones) != len(tanda):
            logger.info(
                "el mosaico de cédulas devolvió %d renglones con rótulo para %d "
                "franjas; no se reparte ninguno",
                len(renglones),
                len(tanda),
            )
            return {}
        trozos = dict(zip(tanda, renglones, strict=True))
    encontradas: dict[int, str] = {}
    for pagina, trozo in trozos.items():
        cedula = cedula_tras_el_rotulo(trozo)
        if cedula:
            encontradas[pagina] = cedula
    return encontradas


def _repartir(texto: str, tanda: Sequence[int]) -> dict[int, str]:
    """Cada nombre de vuelta a su página, troceando por la leyenda impresa.

    Cuando el proveedor contesta como tabla, con la etiqueta de cada franja
    pegada a su renglón, se reparte por la etiqueta y se le quita la leyenda
    si vino en el mismo renglón que el nombre.

    El peligro de este reparto es un error que no se ve: si una franja no soltó
    su nombre y los de abajo se corren una posición, cada archivo sale con el
    nombre del graduado siguiente y **nada lo delata**. Un nombre que falta se
    nota -- el archivo se llama por su folio y la unidad queda en revisión --;
    uno corrido, no.

    La primera versión se defendía de eso contando: si no volvían tantos nombres
    como franjas, no se repartía ninguno. Es seguro y **no sirve**, porque casi
    nunca cuadra. Medido sobre una corrida real del libro de posgrados: once
    nombres para diez franjas, nueve para diez, cero para diez. El ahorro no
    llegaba nunca.

    Lo que sí alinea es **la leyenda impresa**. Va tipografiada en el
    formulario, el OCR la lee sin fallar y aparece una vez por franja, de modo
    que trocear por ella da un trozo por franja **aunque su nombre sea
    ilegible**. Una cara que no suelta su nombre se queda sin él y no arrastra a
    las de abajo, que es exactamente lo que hacía falta.

    Del trozo se toma el primer renglón que pueda ser una persona: en estos
    libros el nombre va escrito a mano justo debajo de la leyenda.
    """
    por_etiqueta = _por_etiqueta(texto, tanda)
    if por_etiqueta is not None:
        encontrados: dict[int, str] = {}
        for pagina, trozo in por_etiqueta.items():
            nombre = nombre_suelto(lines_from_text(_LEYENDA_DEL_NOMBRE.split(trozo)[-1]))
            if nombre:
                encontrados[pagina] = nombre
        return encontrados

    trozos = _por_leyenda(texto)
    if not trozos:
        logger.info(
            "el mosaico volvió sin ninguna leyenda que separe las %d franjas; "
            "no se reparte nada",
            len(tanda),
        )
        return {}
    if len(trozos) != len(tanda):
        # Sin un trozo por franja no hay manera de saber cuál es cuál, y
        # repartir en orden pondría cada nombre en la página de al lado.
        logger.info(
            "el mosaico devolvió %d bloques para %d franjas; no se reparte ninguno "
            "porque no hay forma de saber cuál falta",
            len(trozos),
            len(tanda),
        )
        return {}

    encontrados: dict[int, str] = {}
    for pagina, trozo in zip(tanda, trozos, strict=True):
        nombre = nombre_suelto(lines_from_text(trozo))
        if nombre:
            encontrados[pagina] = nombre
    return encontrados


def _por_leyenda(texto: str) -> list[str]:
    """El texto partido en un trozo por franja, usando la leyenda como tijera.

    Lo que venga antes de la primera leyenda se descarta: es el borde superior
    del mosaico, no pertenece a ninguna franja.
    """
    trozos: list[list[str]] = []
    for renglon in texto.splitlines():
        if any(leyenda in _plano(renglon) for leyenda in LEYENDAS):
            trozos.append([])
            continue
        if trozos:
            trozos[-1].append(renglon)
    return ["\n".join(trozo) for trozo in trozos]


class MosaicoDeCampo(MosaicoDeNombres):
    """El mosaico para cualquier campo de cualquier formulario, descrito por su :class:`Franja`.

    Es el de los diplomas generalizado (2026-10-30): cada habilidad dice dónde
    está su nombre, su cédula o su número, y la segunda lectura sale igual
    para todas -- diez renglones ampliados por página facturada --. La respuesta
    se reparte por la etiqueta de cada franja o, si vuelve sin ellas, por el
    rótulo impreso de cada renglón, en el orden en que se apilaron.
    """

    def __init__(self, franja, **opciones) -> None:
        super().__init__(**opciones)
        self.CAMPO = franja.campo
        self.LEYENDAS = franja.leyendas
        self.ALTO = franja.alto
        self.MARGEN = franja.margen
        self._rotulo = re.compile(franja.rotulo, re.I)

    def _repartir_texto(self, texto: str, tanda: Sequence[int]) -> dict[int, str]:
        if (por_etiqueta := _por_etiqueta(texto, tanda)) is not None:
            return por_etiqueta
        inicios = [hallado.start() for hallado in self._rotulo.finditer(texto)]
        if len(inicios) != len(tanda):
            # Sin saber qué renglón es de quién, nada: un dato devuelto a otro
            # estudiante es peor que una segunda lectura que falta.
            logger.info("el mosaico de %s volvió con %d rótulos para %d franjas", self.CAMPO, len(inicios), len(tanda))
            return {}
        return {
            pagina: texto[desde:hasta]
            for pagina, desde, hasta in zip(tanda, inicios, [*inicios[1:], len(texto)], strict=True)
        }
