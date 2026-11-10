"""Mistral buscando en el texto de una fila del inventario los datos que la auditoría no confirmó.

Lo usa la auditoría de las filas (``application/auditoria_de_filas.py``,
2026-11-09), sólo si la corrida se hizo con IA. Es una pregunta por fila, al chat
y no al OCR: se manda el texto que ya se leyó de sus páginas, y se paga por
tokens, no por página. Hecho como ``MistralJuezDeCosturas``: HTTP pelado, el
turno común de la IA, «Detener» antes de cada petición y los reintentos ante un
«ahora no».
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from ..application.consumo import Consumo, anotar_uso_json
from ..application.control import Cancelled
from ..application.ports import VeredictoDeDato
from .turnos import turno

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.mistral.ai/v1/chat/completions"
PROVEEDOR = "mistral-auditoria"
_SE_REINTENTA = frozenset({429, 500, 502, 503, 504})
DECISIONES = frozenset({"esta", "no_esta", "no_se"})

INSTRUCCIONES = """Eres el auditor de un inventario documental de la Universidad de Cartagena. Recibes el texto, leído por OCR, de las páginas de un documento (un acta, una ficha, una resolución) y unos datos que el inventario dice de él.

Para CADA dato decide si el texto lo dice:
- "esta": el texto lo dice, aunque esté escrito de otra forma (una fecha con letras, un número con o sin ceros o puntos, un nombre con una letra cambiada por el OCR).
- "no_esta": el texto dice OTRA cosa en ese lugar (otro número de acta, otra fecha de sesión, otro nombre).
- "no_se": el texto no lo trae o no se entiende.

"cita" es el trozo del texto, copiado tal cual, en que te apoyas: corto, de unas pocas palabras. Sin cita, "no_se". No inventes.

Usa EXACTAMENTE el "campo" de cada dato que te doy, sin cambiarlo, y no añadas datos que no te pregunté.

Responde SOLO con JSON, una entrada por CADA dato, sin dejar ninguno: {"datos":[{"campo":"fecha","decision":"esta","cita":"diecisiete (17) de diciembre de 2012"}]}"""


@dataclass(frozen=True, slots=True)
class ConfigDelJuezDeDatos:
    #: El pequeño: buscar unos datos en un texto y citarlo, no redactar.
    model: str = "mistral-small-latest"
    timeout_seconds: int = 60
    #: Un dato contestado con su cita son unos 40 tokens, pero el modelo a
    #: veces se extiende: con 700 se cortaban respuestas (2026-11-09).
    max_tokens: int = 1500
    intentos: int = 3
    espera_inicial: float = 2.0


class MistralJuezDeDatos:
    """Busca con Mistral los datos dudosos de una fila en su texto. Cumple ``JuezDeDatos``."""

    def __init__(
        self,
        api_key: str | None = None,
        config: ConfigDelJuezDeDatos | None = None,
        consumo: Consumo | None = None,
        turnos: AbstractContextManager | None = None,
        antes_de_pedir: Callable[[], None] | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        self._config = config or ConfigDelJuezDeDatos()
        self._consumo = consumo
        self._turnos = turnos
        #: ``Cancelled`` si el operador detuvo la corrida: no se paga nada más.
        self._antes_de_pedir = antes_de_pedir
        #: Si se acabó el tiempo de la auditoría: no se pide ni se reintenta
        #: más. Sin él, tres intentos de 60 s pasaban el plazo en tres minutos
        #: (la segunda revisión, 2026-11-09).
        self._agotado: Callable[[], bool] = lambda: False

    def hasta(self, agotado: Callable[[], bool]) -> None:
        """Hasta cuándo se le puede preguntar: lo fija la auditoría con su plazo."""
        self._agotado = agotado

    def verificar(self, texto: str, datos: list[dict[str, str]]) -> dict[str, VeredictoDeDato] | None:
        if not datos:
            return {}
        if not self._api_key:
            return None
        pregunta = json.dumps({"datos": datos, "texto": texto}, ensure_ascii=False, separators=(",", ":"))
        cuerpo = json.dumps(
            {
                "model": self._config.model,
                "messages": [
                    {"role": "system", "content": INSTRUCCIONES},
                    {"role": "user", "content": pregunta},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
                "max_tokens": self._config.max_tokens,
            }
        ).encode()
        payload = self._pedir(cuerpo)
        if payload is None:
            return None
        try:
            anotar_uso_json(self._consumo, PROVEEDOR, payload)
        except Exception:  # noqa: BLE001 - un «usage» con otra forma no se lleva la respuesta
            logger.debug("no se pudo anotar el consumo de la auditoría", exc_info=True)
        return leer_la_respuesta(_texto_de(payload), [str(d.get("campo")) for d in datos])

    def _pedir(self, cuerpo: bytes) -> dict | None:
        espera = self._config.espera_inicial
        for intento in range(1, self._config.intentos + 1):
            if self._agotado():
                return None
            peticion = urllib.request.Request(
                ENDPOINT,
                data=cuerpo,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    # La llave en el encabezado, nunca en la URL.
                    "Authorization": f"Bearer {self._api_key}",
                },
            )
            if self._antes_de_pedir is not None:
                self._antes_de_pedir()
            try:
                with turno(self._turnos):
                    if self._antes_de_pedir is not None:
                        self._antes_de_pedir()
                    with urllib.request.urlopen(peticion, timeout=self._config.timeout_seconds) as respuesta:
                        return json.load(respuesta)
            except Cancelled:
                raise
            except urllib.error.HTTPError as error:
                if error.code in _SE_REINTENTA and intento < self._config.intentos:
                    if self._consumo is not None:
                        self._consumo.rechazo(PROVEEDOR)
                    time.sleep(espera)
                    espera *= 2
                    continue
                logger.warning("Mistral respondió %s al auditor de datos: la fila queda en duda", error.code)
            except Exception as error:  # noqa: BLE001 - una red caída no tumba la auditoría
                if intento < self._config.intentos:
                    time.sleep(espera)
                    espera *= 2
                    continue
                logger.warning("Mistral no respondió al auditor de datos (%s): la fila queda en duda", type(error).__name__)
            break
        if self._consumo is not None:
            self._consumo.fallo(PROVEEDOR)
        return None


def leer_la_respuesta(texto: str, campos: list[str]) -> dict[str, VeredictoDeDato]:
    """Los veredictos de los datos que se preguntaron; lo demás se ignora."""
    try:
        datos = json.loads(texto or "{}")
        items = (datos.get("datos") or []) if isinstance(datos, dict) else []
        # «{"datos": 5}»: otra forma no se lee, no rompe (la revisión, 2026-11-09).
        items = items if isinstance(items, list) else []
    except json.JSONDecodeError:
        # Cortada o con basura detrás: se rescatan las entradas que llegaron enteras.
        items = []
        for trozo in re.findall(r"\{[^{}]*\"campo\"[^{}]*\}", texto or ""):
            try:
                items.append(json.loads(trozo))
            except json.JSONDecodeError:
                continue
        if not items:
            logger.warning("El auditor de datos no entendió la respuesta de Mistral: %r", (texto or "")[:200])
            return {}
    pedidos = set(campos)
    veredictos: dict[str, VeredictoDeDato] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        campo = str(item.get("campo") or "")
        if campo not in pedidos or campo in veredictos:
            continue
        decision = str(item.get("decision") or "no_se").strip().lower()
        veredictos[campo] = VeredictoDeDato(
            decision if decision in DECISIONES else "no_se", str(item.get("cita") or "")
        )
    return veredictos


def _texto_de(payload: object) -> str:
    """El texto de la respuesta, o vacío si llegó con otra forma: «choices» como texto, una lista rara."""
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    primera = choices[0] if isinstance(choices, list) and choices else {}
    mensaje = primera.get("message") if isinstance(primera, dict) else None
    content = mensaje.get("content") if isinstance(mensaje, dict) else None
    return content if isinstance(content, str) else ""
