"""Mistral contestando la pregunta de bordes, sobre HTTP pelado.

Sin SDK, igual que el adaptador de Gemini: esto es un POST con un cuerpo JSON, y
agregar una dependencia a la instalación para eso sería pagar en instalación algo
que la biblioteca estándar ya hace.

Es el tercero en la fila y el último en preferencia, y la razón es de costo, no
de calidad. Claude cachea las instrucciones, que en una caja se pagan una vez por
página. Gemini tiene una capa gratuita que aguanta una caja entera. Mistral no
trae ninguna de las dos cosas, así que se usa cuando es la llave que hay.

Una petición por caja, no una por costura. Además de más barato, es lo que
mantiene la corrida dentro de los límites del proveedor: medido contra un
expediente real, 124 llamadas costura por costura chocan con un 429 a la sexta;
la misma caja preguntada de una sola vez pasa.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from .boundary_prompt import (
    INSTRUCTIONS,
    build_question,
    describe_failure,
    parse_answer,
)

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.mistral.ai/v1/chat/completions"


@dataclass(frozen=True, slots=True)
class MistralConfig:
    #: El barato a propósito. Lo que se le pide es un veredicto binario sobre una
    #: huella de página ya comprimida, no redactar: el modelo grande cuesta
    #: bastante más por la misma decisión.
    model: str = "mistral-small-latest"
    timeout_seconds: int = 120
    max_tokens: int = 8000


class MistralBoundaryOracle:
    """Judges undecided seams with Mistral. Satisfies `BoundaryOracle`."""

    def __init__(self, api_key: str | None = None, config: MistralConfig | None = None) -> None:
        self._api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        self._config = config or MistralConfig()

    def judge(
        self,
        pages: list[dict[str, object]],
        seams: list[tuple[int, int]],
    ) -> dict[tuple[int, int], bool]:
        if not seams or not self._api_key:
            return {}

        body = json.dumps(
            {
                "model": self._config.model,
                "messages": [
                    {"role": "system", "content": INSTRUCTIONS},
                    {"role": "user", "content": build_question(pages, seams)},
                ],
                # Sin esto el modelo contesta prosa alrededor del JSON, y una
                # respuesta que no se puede leer manda a revisión una caja que
                # estaba bien decidida.
                "response_format": {"type": "json_object"},
                "max_tokens": self._config.max_tokens,
            }
        ).encode()

        # La llave va en el encabezado y no en la URL: en la URL termina en el
        # log de cualquier proxy del camino.
        request = urllib.request.Request(
            ENDPOINT,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            # Una caída degrada la corrida a "estas costuras las mira un humano".
            # Nunca falla la caja: todo lo que la estructura resolvió sigue
            # siendo un corte válido. El aviso nombra la causa porque un 429 se
            # espera, un 401 se cambia la llave y un plazo vencido se sube.
            logger.warning(
                "Mistral no respondió (%s); las costuras dudosas van a revisión",
                describe_failure(error),
            )
            return {}

        return parse_answer(_text_of(payload), seams)


def _text_of(payload: dict) -> str:
    choices = payload.get("choices") or [{}]
    message = choices[0].get("message") or {}
    content = message.get("content")
    return content if isinstance(content, str) else ""
