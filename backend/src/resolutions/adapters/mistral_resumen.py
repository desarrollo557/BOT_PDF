"""Mistral escribiendo el resumen de un acta de consejo, sobre HTTP pelado.

Sin SDK, igual que los otros adaptadores de Mistral: es un POST con un cuerpo
JSON, y la biblioteca estándar ya lo hace.

Se le manda **texto** al chat, no la imagen al OCR. El texto ya lo sacó la capa
del escaneo o Tesseract, que son gratis; el OCR de pago cobra por página y leer
otra vez veinte hojas mecanografiadas para resumirlas sería pagar dos veces lo
mismo. El chat cobra por token, y lo que se le manda llega ya limpio de
membretes y de ruido.

El modelo es el pequeño: resumir un acta en un párrafo no pide más, y el grande
cuesta varias veces lo mismo por la misma tarea.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from ..application.consumo import Consumo, anotar_uso_json
from ..application.ports import ResumenNoDisponible

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.mistral.ai/v1/chat/completions"

#: Con qué nombre aparece en el consumo del trabajo, aparte del OCR de pago:
#: aquél cuenta páginas y éste tokens, y sumarlos no tendría sentido.
PROVEEDOR = "mistral-resumen"

#: Lo que se le pide al modelo. Las reglas son las del operador: el resumen del
#: documento en general y nunca el llamado a lista ni la verificación del
#: quórum. El texto ya llega sin ellos; decírselo es para que no lo deduzca de
#: lo que queda.
INSTRUCCIONES = (
    "Eres archivista de la Universidad de Cartagena y preparas el Formato Único "
    "de Inventario Documental. Recibes el texto de un acta de sesión de un "
    "consejo u órgano colegiado, a veces con su citación, la lista de asistencia "
    "y sus anexos. El texto viene de un OCR y trae errores de lectura.\n\n"
    "Escribe el resumen del documento para la columna de notas del inventario:\n"
    "- Un solo párrafo en español, de 60 a 140 palabras, en tercera persona y en pasado.\n"
    "- Di qué órgano sesionó y quién presidió, y resume los asuntos tratados, las "
    "decisiones, los compromisos y los anexos que se mencionen.\n"
    "- No menciones el llamado a lista, la verificación del quórum ni la asistencia, "
    "y no enumeres el orden del día.\n"
    "- No repitas el número ni la fecha del acta: ya constan en otras columnas.\n"
    "- No inventes nada que no esté en el texto. Si un nombre está ilegible, omítelo.\n"
    "- Devuelve solo el párrafo, en texto plano, sin títulos, viñetas ni comillas."
)


@dataclass(frozen=True, slots=True)
class MistralResumenConfig:
    model: str = "mistral-small-latest"
    timeout_seconds: int = 120
    #: Un párrafo de ciento cuarenta palabras son unos doscientos cincuenta
    #: tokens. El margen es para que un modelo locuaz no se corte a media frase.
    max_tokens: int = 600
    temperatura: float = 0.2
    #: Cuántas veces se reintenta un «más despacio» (429) o una caída del
    #: proveedor (5xx) antes de dejar el acta sin resumen.
    reintentos: int = 3
    #: Segundos de espera antes de cada reintento.
    esperas: tuple[float, ...] = (2.0, 5.0, 10.0)


class MistralResumidor:
    """Resume actas con Mistral. Satisface `Resumidor`."""

    def __init__(
        self,
        api_key: str,
        config: MistralResumenConfig | None = None,
        consumo: Consumo | None = None,
        esperar: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key
        self._config = config or MistralResumenConfig()
        self._consumo = consumo
        self._esperar = esperar
        #: Por qué ya no se le pide nada más en este trabajo: una llave
        #: rechazada o una cuenta sin saldo no se arreglan reintentando.
        self._cerrado: str | None = None

    def resumir(self, texto: str) -> str:
        if self._cerrado:
            raise ResumenNoDisponible(self._cerrado)
        if not texto.strip():
            raise ResumenNoDisponible("el acta no trae texto legible que resumir")

        cuerpo = json.dumps(
            {
                "model": self._config.model,
                "messages": [
                    {"role": "system", "content": INSTRUCCIONES},
                    {"role": "user", "content": f"Texto del acta:\n\n{texto}"},
                ],
                "max_tokens": self._config.max_tokens,
                "temperature": self._config.temperatura,
            }
        ).encode()

        for intento in range(self._config.reintentos + 1):
            try:
                payload = self._pedir(cuerpo)
            except urllib.error.HTTPError as error:
                if error.code == 429 or error.code >= 500:
                    if intento < self._config.reintentos:
                        if self._consumo is not None:
                            self._consumo.rechazo(PROVEEDOR)
                        self._esperar(self._espera(intento))
                        continue
                    self._fallo()
                    raise ResumenNoDisponible(
                        f"Mistral siguió sin atender (HTTP {error.code}) tras "
                        f"{self._config.reintentos} reintentos"
                    ) from error
                self._fallo()
                raise ResumenNoDisponible(self._rechazo(error.code)) from error
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                # Una caída de red deja esta acta sin resumen, no el trabajo
                # entero: el número y la fecha ya se leyeron del papel.
                self._fallo()
                motivo = getattr(error, "reason", None) or type(error).__name__
                raise ResumenNoDisponible(f"Mistral no respondió ({motivo})") from error

            anotar_uso_json(self._consumo, PROVEEDOR, payload)
            resumen = _texto_de(payload).strip()
            if not resumen:
                raise ResumenNoDisponible("Mistral devolvió un resumen vacío")
            return resumen

        raise ResumenNoDisponible("Mistral no atendió la petición")  # pragma: no cover

    def _pedir(self, cuerpo: bytes) -> dict:
        # La llave va en el encabezado y no en la URL: en la URL termina en el
        # log de cualquier proxy del camino.
        request = urllib.request.Request(
            ENDPOINT,
            data=cuerpo,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as respuesta:
            return json.load(respuesta)

    def _espera(self, intento: int) -> float:
        esperas = self._config.esperas or (1.0,)
        return esperas[min(intento, len(esperas) - 1)]

    def _fallo(self) -> None:
        if self._consumo is not None:
            self._consumo.fallo(PROVEEDOR)

    def _rechazo(self, codigo: int) -> str:
        """Lo que se le dice al operador de un rechazo que no se reintenta.

        Los dos primeros cierran el resumidor para el resto del trabajo: una
        llave mala o una cuenta sin saldo no se arreglan en la siguiente acta, y
        seguir pidiendo sería llenar el registro de los mismos rechazos.
        """
        if codigo in (401, 403):
            self._cerrado = f"Mistral rechazó la llave (HTTP {codigo})"
            return self._cerrado
        if codigo == 402:
            self._cerrado = "la cuenta de Mistral no tiene saldo (HTTP 402)"
            return self._cerrado
        return f"Mistral rechazó la petición (HTTP {codigo})"


def _texto_de(payload: dict) -> str:
    choices = payload.get("choices") or [{}]
    message = choices[0].get("message") or {}
    content = message.get("content")
    return content if isinstance(content, str) else ""
