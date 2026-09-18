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
from dataclasses import dataclass

from ..application.consumo import Consumo
from ..application.ports import OcrResult

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
    ) -> None:
        self._api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        self._config = config or MistralOcrConfig()
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

        cuerpo = json.dumps(
            {
                "model": self._config.model,
                "document": {
                    "type": "image_url",
                    "image_url": "data:image/png;base64,"
                    + base64.b64encode(image_png).decode(),
                },
            }
        ).encode()

        respuesta = self._pedir(cuerpo)
        if respuesta is None:
            return OcrResult(text="", mean_confidence=0.0)
        facturadas = (respuesta.get("usage_info") or {}).get("pages_processed") or 1
        if self._consumo is not None:
            # Lo que el proveedor dice haber cobrado, no lo que se le mandó: una
            # imagen es una página, pero es él quien lleva la cuenta.
            self._consumo.peticion(PROVEEDOR, paginas=facturadas)
            acumulado = self._consumo.as_dict().get("paginas_facturadas")
        else:
            acumulado = "?"
        # Una línea por cada vez que se usa la IA, con el acumulado del trabajo:
        # es lo que permite ver desde la consola que el motor de pago está
        # trabajando y cuánto lleva gastado, sin esperar al informe.
        logger.info(
            "IA en uso: OCR de Mistral leyó una imagen (%s facturada%s; %s en este trabajo)",
            facturadas,
            "" if facturadas == 1 else "s",
            acumulado,
        )
        return OcrResult(text=_texto_de(respuesta), mean_confidence=0.0)

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
                with urllib.request.urlopen(
                    peticion, timeout=self._config.timeout_seconds
                ) as conexion:
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
