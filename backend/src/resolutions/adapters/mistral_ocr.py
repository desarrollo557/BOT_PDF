"""El OCR de documentos de Mistral, sobre HTTP pelado.

Sin SDK, por el mismo motivo que el adaptador de bordes: esto es un POST con un
cuerpo JSON, y agregar una dependencia a la instalación para eso sería pagar en
instalación lo que la biblioteca estándar ya hace.

Lo que aporta, y que ningún otro peldaño de esta casa sabe hacer, es **leer lo
escrito a mano**. Tesseract no lo lee -- en el libro 7 de diplomas, 1982, falla
el folio en 228 de sus 398 páginas -- y en un archivo histórico lo manuscrito no
es un detalle: es el nombre del graduado, su cédula, el título, la fecha y el
folio. Todo lo impreso en esos libros es el formulario; todo lo que identifica
al documento está escrito a mano encima.

Medido sobre las esquinas del folio de ese libro: de veintiuna caras seguidas,
ninguna petición rechazada, un segundo y medio cada una, y el folio legible en
dos de cada tres. Dos de cada tres no es una lectura fiable por sí sola, y por
eso el folio que sale de aquí se comprueba después contra la progresión del
libro en vez de creerse: quien valida es `domain/folio_manuscrito.py`, no este
archivo, que se limita a decir lo que el proveedor contestó.

Satisface `OcrEngine`, que es el puerto que ya usaban todas las habilidades. De
ahí que agregarlo no obligue a tocar ninguna: la ruta de resoluciones le pide el
número impreso del encabezado, la de registros el folio de la esquina, la de
correspondencia el texto con que decide las costuras y la de inventario el
encabezado del archivo. Cada una le pregunta lo suyo, y este adaptador no sabe
cuál de las cuatro está preguntando.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from ..application.consumo import Consumo
from ..application.ports import OcrResult
from .pymupdf_source import CALIDAD_JPEG

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.mistral.ai/v1/ocr"

#: Con qué nombre aparece este motor en las cuentas del trabajo.
PROVEEDOR = "mistral-ocr"

#: Respuestas del proveedor que son "ahora no" y no "no". El 429 marca el paso;
#: las cinco centenas son suyas y pasan solas. Cualquier otra -- una llave mala,
#: una petición mal formada -- no mejora por repetirla.
_SE_REINTENTA = frozenset({429, 500, 502, 503, 504})

#: Se acabó el crédito de la cuenta. No es un fallo de esta página ni de esta
#: petición: es la cuenta, y por eso no se vuelve a preguntar.
_SIN_PRESUPUESTO = 402


@dataclass(frozen=True, slots=True)
class MistralOcrConfig:
    #: El modelo de OCR, que no es un modelo de chat: no razona sobre la imagen,
    #: la transcribe. Es la diferencia que hace que esto se pueda pedir por
    #: página sin que el trabajo se vuelva caro.
    model: str = "mistral-ocr-latest"
    timeout_seconds: int = 120
    #: Cuántas veces se reintenta un rechazo por ritmo antes de darse por
    #: vencido con esa página.
    #:
    #: Cinco y no tres, porque leyendo en paralelo el 429 deja de ser raro: el
    #: proveedor marca el paso y con ocho lectores se le pisa. Medido sobre el
    #: libro 7 con doce lectores, un rechazo agotaba los tres intentos y esa
    #: página volvía sin texto -- sin cédula, sin nombre y sin fecha -- para
    #: ganar siete segundos en cuarenta páginas. Esperar es más barato que
    #: perder la lectura, así que se espera.
    reintentos: int = 5
    #: La primera espera tras un 429, que se dobla en cada reintento: 2, 4, 8,
    #: 16. Un minuto largo de paciencia en total, que es lo que tarda en pasar
    #: una ráfaga.
    espera_inicial: float = 2.0


class MistralOcrError(RuntimeError):
    """El proveedor contestó con un error, y esto es lo que dijo."""


class MistralOcr:
    """Una imagen entra, su texto sale. Satisface `OcrEngine`.

    La confianza que devuelve es siempre cero, y conviene saber por qué: el
    endpoint de OCR no informa ninguna. Inventar un número aquí sería fabricar
    la única medida que existe para desconfiar de una lectura. Ninguna decisión
    del sistema la consume hoy; quien llegue a consumirla tiene que enterarse de
    que este motor no la da, y un cero declarado se nota, mientras que un 0.9
    inventado no.
    """

    def __init__(
        self,
        api_key: str | None = None,
        config: MistralOcrConfig | None = None,
        consumo: Consumo | None = None,
        turnos: AbstractContextManager | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        self._config = config or MistralOcrConfig()
        #: El tope común de llamadas a la vez de todo el servicio, si lo hay. Se
        #: toma sólo mientras la petición está en el aire: esperar un reintento
        #: con el turno tomado se lo quitaría a otro documento para nada.
        self._turnos = turnos
        #: Dónde se anota lo que este motor le cuesta al trabajo. Lo comparte
        #: con los demás adaptadores del mismo trabajo; sin él se lee igual y
        #: no se cuenta nada.
        self._consumo = consumo
        #: Si el proveedor ya dijo que no queda crédito. Se recuerda porque la
        #: respuesta vale para la cuenta entera y no para una página: sin esto,
        #: un libro de 398 hojas preguntaba 398 veces algo que ya se sabía, y el
        #: registro se llenaba de cuatrocientas líneas idénticas que tapaban
        #: cualquier otro problema.
        self._sin_presupuesto = False
        #: Si ya se dijo que el tope del trabajo se agotó. Una vez y no una por
        #: página: en un libro de 398 hojas serían cientos de líneas idénticas
        #: tapando cualquier otro problema, que es el mismo motivo por el que
        #: "sin presupuesto" se recuerda en vez de volver a preguntarse.
        self._tope_anunciado = False

    @property
    def disponible(self) -> bool:
        return bool(self._api_key)

    @property
    def consumo(self) -> Consumo | None:
        return self._consumo

    @property
    def sin_presupuesto(self) -> bool:
        """Si el proveedor declaró que la cuenta se quedó sin crédito."""
        return self._sin_presupuesto

    def read(self, image_png: bytes) -> OcrResult:
        if not self._api_key or self._sin_presupuesto:
            # Sin llave o sin crédito no se falla el documento: se contesta que
            # aquí no se leyó nada, que es exactamente lo que pasó.
            return OcrResult(text="", mean_confidence=0.0)

        # Ni una página más de las que el operador autorizó para este trabajo.
        # Se mira antes de gastar y no después, que es la diferencia entre un
        # tope y un aviso: un tope que se comprueba al volver ya pagó.
        if self._sin_cupo():
            return OcrResult(text="", mean_confidence=0.0)

        imagen = _aligerada(image_png)
        cuerpo = json.dumps(
            {
                "model": self._config.model,
                "document": {
                    "type": "image_url",
                    "image_url": f"data:{_tipo_de(imagen)};base64,"
                    + base64.b64encode(imagen).decode(),
                },
            }
        ).encode()

        respuesta = self._pedir(cuerpo)
        if respuesta is None:
            return OcrResult(text="", mean_confidence=0.0)
        # Lo que el proveedor dice haber cobrado, no lo que se le mandó: una
        # imagen es una página, pero es él quien lleva la cuenta.
        facturadas = (respuesta.get("usage_info") or {}).get("pages_processed") or 1
        self._anotar(facturadas)
        return OcrResult(text=_texto_de(respuesta), mean_confidence=0.0)


    def read_many(self, imagenes: list[bytes]) -> list[str]:
        """Varias páginas en **una sola petición**, en el orden en que llegaron.

        El proveedor acepta un documento entero además de una imagen suelta, y
        devuelve una entrada por página con su índice. Así que las páginas
        pendientes se encuadernan en un PDF de usar y tirar y se mandan juntas:
        donde antes iban 398 peticiones ahora van unas veinte.

        Lo que **no** cambia es la factura. El proveedor cobra por página
        procesada y sigue cobrando lo mismo; lo que se ahorra es la latencia de
        cada ida y vuelta, y sobre todo los rechazos por ritmo, que aparecen
        cuando se le pisa con muchas peticiones a la vez y obligan a reintentar.

        Devuelve una cadena por imagen, en el mismo orden. Una página que el
        proveedor no contestó vuelve vacía, igual que si se hubiera pedido sola:
        quien lee ya sabe tratar una página sin texto, y perder la tanda entera
        por una página sería cambiar un hueco por veinte.
        """
        if not imagenes:
            return []
        if not self._api_key or self._sin_presupuesto or self._sin_cupo():
            return ["" for _ in imagenes]

        documento = _encuadernadas(imagenes)
        if documento is None:
            # Sin poder armar el PDF se cae a una por una, que es lo que se
            # hacía antes de que existieran las tandas. Más lento, nunca peor.
            return [self.read(imagen).text for imagen in imagenes]

        cuerpo = json.dumps(
            {
                "model": self._config.model,
                "document": {
                    "type": "document_url",
                    "document_url": "data:application/pdf;base64,"
                    + base64.b64encode(documento).decode(),
                },
            }
        ).encode()

        respuesta = self._pedir(cuerpo)
        if respuesta is None:
            return ["" for _ in imagenes]

        facturadas = (respuesta.get("usage_info") or {}).get("pages_processed") or len(
            imagenes
        )
        self._anotar(facturadas, cuantas=len(imagenes))
        return _textos_por_pagina(respuesta, len(imagenes))

    def _sin_cupo(self) -> bool:
        """Si el tope de páginas de este trabajo ya se agotó, dicho una vez."""
        if self._consumo is None or not self._consumo.tope_alcanzado:
            return False
        if not self._tope_anunciado:
            self._tope_anunciado = True
            logger.warning(
                "se alcanzó el tope de %s páginas facturadas de este trabajo; "
                "lo que falte se leerá sólo con el motor local",
                self._consumo.tope_de_paginas,
            )
        return True

    def _anotar(self, facturadas: int, cuantas: int = 1) -> None:
        """Lo que el proveedor dice haber cobrado, y una línea que lo cuente."""
        if self._consumo is None:
            acumulado = "?"
        else:
            self._consumo.peticion(PROVEEDOR, paginas=facturadas)
            acumulado = self._consumo.as_dict().get("paginas_facturadas")
        logger.info(
            "IA en uso: OCR de Mistral leyó %s página%s en una petición "
            "(%s facturada%s; %s en este trabajo)",
            cuantas,
            "" if cuantas == 1 else "s",
            facturadas,
            "" if facturadas == 1 else "s",
            acumulado,
        )

    def _pedir(self, cuerpo: bytes) -> dict | None:
        """La petición, con la paciencia que el proveedor exige.

        Un 429 no es un fallo del documento: es el proveedor diciendo "más
        despacio". Se espera y se repite. Cualquier otro error se registra y
        devuelve ``None``, porque una página que no se pudo leer es una página
        sin texto y no un trabajo roto.
        """
        espera = self._config.espera_inicial
        for intento in range(1, self._config.reintentos + 1):
            peticion = urllib.request.Request(
                ENDPOINT,
                data=cuerpo,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with (
                    self._turnos or nullcontext(),
                    urllib.request.urlopen(
                        peticion, timeout=self._config.timeout_seconds
                    ) as conexion,
                ):
                    return json.load(conexion)
            except urllib.error.HTTPError as error:
                if error.code in _SE_REINTENTA and intento < self._config.reintentos:
                    if self._consumo is not None:
                        self._consumo.rechazo(PROVEEDOR)
                    logger.debug(
                        "Mistral contestó %s; se espera %.1fs (intento %d)",
                        error.code,
                        espera,
                        intento,
                    )
                    time.sleep(espera)
                    espera *= 2
                    continue
                detalle = error.read()[:200].decode("utf-8", "replace")
                if self._consumo is not None:
                    self._consumo.fallo(PROVEEDOR)
                if error.code == _SIN_PRESUPUESTO:
                    # Una sola vez, y en voz alta: esto no lo arregla reintentar
                    # ni cambiar de página. Hay que recargar la cuenta.
                    self._sin_presupuesto = True
                    logger.error(
                        "Mistral no tiene presupuesto: se deja de pedirle lecturas y "
                        "lo que falte se leerá sólo con el motor local. %s",
                        detalle,
                    )
                    return None
                logger.warning("el OCR de Mistral respondió %s: %s", error.code, detalle)
                return None
            except Exception as error:  # noqa: BLE001 - una red caída no rompe nada
                # Y tampoco se da por perdida a la primera. Leyendo ocho páginas
                # a la vez, el proveedor corta conexiones: llegan
                # `RemoteDisconnected` e `IncompleteRead` en mitad de una
                # respuesta, que no son un "no" sino una llamada que hay que
                # repetir. Tratarlas como definitivas era lo que hacía que un
                # libro entero se diera por leído en trece segundos, con las
                # 398 páginas vacías y sin una sola cédula: cada corte volvía al
                # instante, así que el trabajo terminaba a la velocidad de los
                # fallos.
                if intento < self._config.reintentos:
                    logger.debug(
                        "se cortó la conexión con Mistral (%s); se espera %.1fs (intento %d)",
                        type(error).__name__,
                        espera,
                        intento,
                    )
                    time.sleep(espera)
                    espera *= 2
                    continue
                if self._consumo is not None:
                    self._consumo.fallo(PROVEEDOR)
                logger.warning(
                    "no se pudo pedir el OCR de Mistral tras %d intentos",
                    self._config.reintentos,
                    exc_info=True,
                )
                return None
        return None


#: Los primeros bytes con que se reconoce cada formato. Se mira la imagen en
#: vez de exigir que quien la manda declare su formato: el puerto `OcrEngine`
#: recibe bytes y nada más, y añadirle un parámetro obligaría a las cuatro
#: habilidades a saber en qué formato lee un motor que ninguna sabe cuál es.
_FIRMAS = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG", "image/png"))

#: La calidad con que se recomprime lo que sale hacia el proveedor vive junto a
#: quien rasteriza, porque es la misma con la que la fuente ya produce JPEG
#: cuando se le pide: dos constantes con el mismo número acabarían por no serlo.
__all__ = ["CALIDAD_JPEG", "MistralOcr", "MistralOcrConfig", "MistralOcrError"]

#: Por debajo de este tamaño no se toca la imagen. Una banda de encabezado o la
#: esquina de un folio pesan pocos kilobytes, y decodificarlas y volver a
#: comprimirlas costaría más tiempo del que ahorrarían en la red.
_MINIMO_PARA_RECOMPRIMIR = 256 * 1024


def _tipo_de(imagen: bytes) -> str:
    """Qué clase de imagen es ésta, según sus primeros bytes.

    PNG cuando no se reconoce, que es lo que manda el resto de la casa y lo que
    este adaptador suponía siempre antes de que la hubiera de otra clase.
    """
    for firma, tipo in _FIRMAS:
        if imagen.startswith(firma):
            return tipo
    return "image/png"


def _aligerada(imagen: bytes) -> bytes:
    """La misma imagen, pesando lo que puede pesar para viajar por la red.

    Una página a 300 dpi son 2,6 MB en PNG y 718 KB en JPEG de calidad 85, y en
    base64 lo que viaja es además un tercio más. Con ocho lectores en vuelo esa
    diferencia es la que hay entre una conversación normal con el proveedor y la
    ráfaga de conexiones cortadas -- `RemoteDisconnected`, `IncompleteRead` --
    que este mismo archivo tiene que reintentar más abajo. Sobre un libro de 398
    caras son unos 750 MB que dejan de subirse.

    Se comprobó que no cuesta lectura antes de adoptarlo, y sobre el caso
    difícil: la cara 3 del libro 7, manuscrita, devuelve la misma cédula
    (7882907), el mismo nombre, los mismos folios y la misma fecha en los dos
    formatos.

    Va aquí y no en la fuente que rasteriza porque es **este** adaptador el que
    paga la red. Puesto allá, cada habilidad tendría que declarar en qué formato
    lee un motor que ninguna sabe cuál es; puesto aquí, las cuatro se abaratan
    sin tocar ninguna, que es cómo está montado el proveedor en esta casa.

    **Se manda la más pequeña de las dos, no siempre la JPEG.** La diferencia no
    es teórica y costó una prueba descubrirla: sobre el escaneo de un libro,
    donde hay grano y grises, la JPEG pesa 3,7 veces menos; sobre una imagen
    sintética de texto nítido -- que es lo que produce una prueba, y también lo
    que produce un PDF nativo rasterizado -- el PNG gana, y por bastante: 931 KB
    contra 1,7 MB. Comprimir a ciegas habría hecho más pesadas justamente las
    páginas que ya iban ligeras.

    Nunca levanta. Una imagen que no se deja recomprimir se manda tal como vino:
    ahorrar ancho de banda no puede costar una lectura.
    """
    if len(imagen) < _MINIMO_PARA_RECOMPRIMIR or _tipo_de(imagen) == "image/jpeg":
        return imagen
    try:
        import pymupdf

        comprimida = pymupdf.Pixmap(imagen).tobytes("jpeg", jpg_quality=CALIDAD_JPEG)
    except Exception:  # noqa: BLE001 - abaratar jamás puede costar una lectura
        logger.debug("no se pudo recomprimir la imagen; se manda tal cual", exc_info=True)
        return imagen
    return comprimida if len(comprimida) < len(imagen) else imagen


def _encuadernadas(imagenes: list[bytes]) -> bytes | None:
    """Las imágenes en un PDF de usar y tirar, una por página y en su orden.

    Es sólo un sobre para mandarlas juntas: no se guarda, no se enseña y no
    sobrevive a la petición. Cada página toma el tamaño de su imagen, de modo
    que no se escala ni se recorta nada -- lo que el proveedor ve es exactamente
    lo que vería si se le hubiera mandado suelta.

    Cada imagen viaja **tan ligera como viajaría sola**, que es lo que la
    petición de una sola página ya hacía y ésta no: se aligera a JPEG y se
    incrusta tal cual, sin decodificarla ni volverla a comprimir. Sin esto, doce
    caras a 300 ppp eran un sobre de treinta megas que subía en base64 --
    cuarenta --, y con esto son ocho. Y el tamaño de la página se lee de la
    cabecera de la imagen, no de sus píxeles: decodificar una cara entera para
    saber cuánto mide era el otro tercio del tiempo de armar la tanda.

    ``None`` cuando no se pudo armar, y entonces quien llama se cae a pedirlas
    una por una. Empaquetar es una optimización; no puede costar una lectura.
    """
    try:
        import pymupdf

        documento = pymupdf.open()
        try:
            for imagen in imagenes:
                ligera = _aligerada(imagen)
                ancho, alto = _tamano_de(ligera)
                pagina = documento.new_page(width=ancho, height=alto)
                pagina.insert_image(pagina.rect, stream=ligera)
            return documento.tobytes(deflate=True)
        finally:
            documento.close()
    except Exception:  # noqa: BLE001 - se cae a pedirlas de una en una
        logger.debug("no se pudo encuadernar la tanda; se pedirá página a página", exc_info=True)
        return None


def _tamano_de(imagen: bytes) -> tuple[int, int]:
    """El ancho y el alto de una imagen, leyendo sólo su cabecera."""
    with Image.open(BytesIO(imagen)) as abierta:
        return abierta.size


def _textos_por_pagina(respuesta: dict, cuantas: int) -> list[str]:
    """Una cadena por página pedida, colocada por el índice que declara.

    Por el índice y no por el orden de llegada: el proveedor los numera y
    fiarse del orden sería dar por hecho algo que nadie promete. Una página que
    no venga en la respuesta vuelve vacía, que es lo mismo que contestaba una
    petición suelta que falló.
    """
    textos = [""] * cuantas
    paginas = respuesta.get("pages")
    if not isinstance(paginas, list):
        return textos
    for orden, pagina in enumerate(paginas):
        if not isinstance(pagina, dict):
            continue
        indice = pagina.get("index")
        indice = indice if isinstance(indice, int) else orden
        if 0 <= indice < cuantas:
            textos[indice] = (pagina.get("markdown") or "").strip()
    return textos


def _texto_de(respuesta: dict) -> str:
    """El texto de las páginas que contestó, en el orden en que vinieron.

    El proveedor devuelve Markdown, que para una esquina con un folio escrito es
    el folio y poco más, pero para una página entera trae la tabla del formulario
    con sus barras y sus almohadillas. No se limpia aquí: quien extrae los campos
    ya sabe descartar lo que no es un valor, y borrar el formato sería quitarle
    información a quien viene detrás.
    """
    paginas = respuesta.get("pages")
    if not isinstance(paginas, list):
        return ""
    trozos = [
        pagina.get("markdown", "")
        for pagina in paginas
        if isinstance(pagina, dict) and pagina.get("markdown")
    ]
    return "\n".join(trozos).strip()
