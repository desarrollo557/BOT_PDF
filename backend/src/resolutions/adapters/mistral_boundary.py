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

import http.client
import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from ..application.consumo import Consumo, anotar_uso_json
from .boundary_prompt import (
    INSTRUCTIONS,
    build_question,
    describe_failure,
    describe_unusable,
    parse_answer,
)

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.mistral.ai/v1/chat/completions"

#: Cortes con la pregunta sin mandar: urllib envuelve en ``URLError`` sólo lo
#: que falla dentro de ``h.request()`` (conectar o enviar). Un ``HTTPError`` --
#: un 401, un 429 -- también es un ``URLError``, pero es una respuesta y va
#: antes, sin repetirse.
_SIN_ENVIAR = (urllib.error.URLError,)

#: Cortes con la pregunta ya enviada: llegan crudos de ``getresponse()`` o al
#: leer el cuerpo (el plazo de lectura, ``RemoteDisconnected``, ``IncompleteRead``).
_TRAS_ENVIAR = (TimeoutError, ConnectionError, http.client.HTTPException)


@dataclass(frozen=True, slots=True)
class MistralConfig:
    #: El barato a propósito. Lo que se le pide es un veredicto binario sobre una
    #: huella de página ya comprimida, no redactar: el modelo grande cuesta
    #: bastante más por la misma decisión.
    model: str = "mistral-small-latest"
    timeout_seconds: int = 120
    max_tokens: int = 8000
    #: Cuántas veces se repite la pregunta si se cortó la red sin enviarla
    #: antes de mandar las dudas a revisión (2026-11-26): un corte no es un «no»
    #: del proveedor. Un corte con la pregunta ya enviada, una sola vez.
    reintentos: int = 2
    #: Segundos de espera antes de cada reintento.
    esperas: tuple[float, ...] = (1.0, 2.0)


class MistralBoundaryOracle:
    """Judges undecided seams with Mistral. Satisfies `BoundaryOracle`."""

    def __init__(
        self,
        api_key: str | None = None,
        config: MistralConfig | None = None,
        consumo: Consumo | None = None,
        *,
        esperar: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        self._config = config or MistralConfig()
        self._consumo = consumo
        #: Cómo se espera entre reintentos; las pruebas no duermen de verdad.
        self._esperar = esperar

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

        payload = self._preguntar(request)
        if payload is None:
            return {}

        anotar_uso_json(self._consumo, "mistral-bordes", payload)
        texto = _text_of(payload)
        answers = parse_answer(texto, seams)
        unusable = describe_unusable(texto, seams, answers)
        if unusable:
            logger.warning("Mistral contestó y no se entendió: %s", unusable)
        return answers

    def _preguntar(self, request: urllib.request.Request) -> dict | None:
        """La respuesta de Mistral, o ``None`` si no llegó.

        Un corte sin enviar (``URLError``) se repite hasta ``reintentos`` porque
        no llegó y es gratis; uno ya enviado, una sola vez, porque Mistral pudo
        cobrarlo (2026-11-26: «Mistral no respondió (timed out)» del otro PC era
        un ``URLError``).

        Un ``HTTPError`` o un cuerpo que no es JSON no se repiten: repetir la
        misma pregunta no cambia la respuesta. Sin respuesta, la corrida se
        degrada a "estas costuras las mira un humano" y nunca falla la caja: lo
        que la estructura resolvió sigue siendo un corte válido. El aviso nombra
        la causa porque un 429 se espera, un 401 se cambia la llave y un plazo
        vencido se sube.
        """
        repetida_tras_enviar = False
        for intento in range(self._config.reintentos + 1):
            try:
                with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                    return json.load(response)
            except (urllib.error.HTTPError, json.JSONDecodeError) as error:
                logger.warning(
                    "Mistral no respondió (%s); las costuras dudosas van a revisión",
                    describe_failure(error),
                )
                break
            except _SIN_ENVIAR as error:
                # No llegó: repetirla es gratis.
                if intento < self._config.reintentos:
                    espera = self._espera(intento)
                    logger.debug(
                        "no se pudo mandar la pregunta a Mistral (%s); se espera %.1f s (intento %d)",
                        describe_failure(error),
                        espera,
                        intento + 1,
                    )
                    self._esperar(espera)
                    continue
                _avisar_sin_respuesta(error, intento + 1)
                break
            except _TRAS_ENVIAR as error:
                # Llegó y pudo cobrarse: una vez más como mucho, y que se vea.
                if intento < self._config.reintentos and not repetida_tras_enviar:
                    repetida_tras_enviar = True
                    espera = self._espera(intento)
                    logger.warning(
                        "la pregunta de bordes a Mistral pudo cobrarse y no llegó la respuesta "
                        "(%s); se repite una sola vez en %.1f s",
                        describe_failure(error),
                        espera,
                    )
                    self._esperar(espera)
                    continue
                _avisar_sin_respuesta(error, intento + 1)
                break
        if self._consumo is not None:
            self._consumo.fallo("mistral-bordes")
        return None

    def _espera(self, intento: int) -> float:
        esperas = self._config.esperas or (1.0,)
        return esperas[min(intento, len(esperas) - 1)]


def _avisar_sin_respuesta(error: BaseException, intentos: int) -> None:
    logger.warning(
        "Mistral no respondió (%s) tras %d %s; las costuras dudosas van a revisión",
        describe_failure(error),
        intentos,
        "intento" if intentos == 1 else "intentos",
    )


def _text_of(payload: dict) -> str:
    choices = payload.get("choices") or [{}]
    message = choices[0].get("message") or {}
    content = message.get("content")
    return content if isinstance(content, str) else ""
