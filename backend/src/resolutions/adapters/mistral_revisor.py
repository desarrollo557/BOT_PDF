"""Mistral decidiendo las costuras que el revisor de cortes no pudo validar solo.

Lo pidió el operador el 2026-11-05: que el agente del bot revise cada PDF y que
«cuando un caso se salga del margen de error se lo envíe a la IA, la IA lo
analice y decida», «consumiendo pocos tokens». Eligió Mistral, la llave que ya
está cargada.

Por eso la pregunta es corta a propósito:

- **Una petición por PDF**, con todas sus costuras dudosas juntas, no una por
  costura: además de más barato, es lo que no choca con el límite del proveedor
  (ver ``mistral_boundary.py``: 124 llamadas costura por costura daban un 429).
- **Sólo la huella** de las hojas de alrededor de cada costura -- cómo empieza y
  cómo termina cada una --, nunca la caja entera ni el título que le puso el bot.
- **El modelo pequeño**, con la respuesta en JSON y temperatura cero: se le pide
  un veredicto con su cita, no redactar.

Sin SDK, sobre HTTP pelado, como los otros adaptadores de Mistral. Una caída
devuelve ``None``: el revisor manda esas costuras a revisión y la caja sigue.
"""

from __future__ import annotations

import json
import logging
import os
import time
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from ..application.consumo import Consumo, anotar_uso_json
from ..application.control import Cancelled
from ..application.ports import VeredictoDeCostura
from .turnos import turno

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.mistral.ai/v1/chat/completions"
PROVEEDOR = "mistral-revisor"
#: «Ahora no», no «no»: se espera y se repite.
_SE_REINTENTA = frozenset({429, 500, 502, 503, 504})

INSTRUCCIONES = """Eres el revisor final de un archivo que divide expedientes escaneados en sus documentos.

Te doy la huella de unas hojas seguidas del original -- p: número de hoja; ini: cómo empieza; fin: cómo termina; es: qué clase de soporte es -- y unas costuras: pares de hojas seguidas [izquierda, derecha].

Para cada costura decide si la hoja derecha CONTINÚA el mismo documento que la izquierda o ABRE otro documento.
- Continúa: la numeración sigue (cláusula SEGUNDO y luego TERCERO, «página 2 de 3» y luego «3 de 3»), la frase queda partida entre las dos, la derecha cierra con las firmas del documento de la izquierda, o es un anexo suyo que va detrás (cédula, factura).
- Abre: un encabezado nuevo (ciudad y fecha, «Señores», un título, un sello de radicación, un formulario), otra persona u otro asunto.

Las reglas del archivo mandan sobre todo lo demás; vienen en "reglas".

Responde SOLO con JSON, con una entrada por CADA costura que te listo, sin dejar ninguna: {"costuras":[{"izq":3,"der":4,"decision":"continua","cita":"TERCERO: Para garantizar el pago"}]}
"decision" es "continua", "abre" o "no_se". "cita" es el texto corto de la hoja que lo prueba, copiado del papel. Ante la duda, "no_se"."""


@dataclass(frozen=True, slots=True)
class ConfigDelRevisor:
    #: El pequeño: un veredicto con su cita sobre unas huellas, no redactar.
    model: str = "mistral-small-latest"
    timeout_seconds: int = 60
    #: Una costura contestada son unos 40 tokens; el revisor no manda más de
    #: ``COSTURAS_POR_PREGUNTA`` en una petición.
    max_tokens: int = 700
    #: Tres intentos: leyendo cajas en paralelo el 429 no es raro.
    intentos: int = 3
    #: La primera espera tras un «ahora no»; se dobla en cada intento: 2, 4.
    espera_inicial: float = 2.0


class MistralJuezDeCosturas:
    """Decide con Mistral las costuras fuera del margen. Cumple ``JuezDeCosturas``."""

    def __init__(
        self,
        api_key: str | None = None,
        config: ConfigDelRevisor | None = None,
        consumo: Consumo | None = None,
        turnos: AbstractContextManager | None = None,
        antes_de_pedir: Callable[[], None] | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        #: El control del trabajo: ``Cancelled`` si el operador lo detuvo. Se
        #: pregunta antes de cada petición de pago (2026-11-09).
        self._antes_de_pedir = antes_de_pedir
        self._config = config or ConfigDelRevisor()
        self._consumo = consumo
        #: El turno común de llamadas a la IA del pool: el revisor de muchas
        #: cajas a la vez no tiene que provocar una lluvia de 429.
        self._turnos = turnos

    def decidir(
        self,
        hojas: list[dict[str, object]],
        costuras: list[tuple[int, int]],
        reglas: str,
    ) -> dict[tuple[int, int], VeredictoDeCostura] | None:
        if not costuras:
            return {}
        if not self._api_key:
            return None
        pregunta = json.dumps(
            {"reglas": reglas, "hojas": hojas, "costuras": [list(c) for c in costuras]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
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
        anotar_uso_json(self._consumo, PROVEEDOR, payload)
        return leer_la_respuesta(_texto_de(payload), costuras)

    def _pedir(self, cuerpo: bytes) -> dict | None:
        """La petición, con el turno común de IA y la paciencia que pide el proveedor.

        Un 429, un 5xx o una conexión cortada son «ahora no»: se espera y se
        repite, con la espera doblándose. Lo demás -- una llave mala, sin
        presupuesto -- no lo arregla reintentar. Sin respuesta, ``None``.
        """
        espera = self._config.espera_inicial
        for intento in range(1, self._config.intentos + 1):
            # La llave en el encabezado, nunca en la URL.
            peticion = urllib.request.Request(
                ENDPOINT,
                data=cuerpo,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
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
                logger.warning("Mistral respondió %s al revisor de cortes: las costuras van a revisión", error.code)
            except Exception as error:  # noqa: BLE001 - una red caída no rompe la caja
                if intento < self._config.intentos:
                    time.sleep(espera)
                    espera *= 2
                    continue
                logger.warning(
                    "Mistral no respondió al revisor de cortes (%s): las costuras van a revisión",
                    type(error).__name__,
                )
            break
        if self._consumo is not None:
            self._consumo.fallo(PROVEEDOR)
        return None


def leer_la_respuesta(
    texto: str, costuras: list[tuple[int, int]]
) -> dict[tuple[int, int], VeredictoDeCostura]:
    """Los veredictos de las costuras que se preguntaron; lo demás se ignora."""
    try:
        datos = json.loads(texto or "{}")
    except json.JSONDecodeError:
        logger.warning("El revisor de cortes no entendió la respuesta de Mistral: %r", (texto or "")[:200])
        return {}
    pedidas = set(costuras)
    veredictos: dict[tuple[int, int], VeredictoDeCostura] = {}
    for item in (datos.get("costuras") or []) if isinstance(datos, dict) else []:
        if not isinstance(item, dict):
            continue
        try:
            clave = (int(item.get("izq")), int(item.get("der")))
        except (TypeError, ValueError):
            continue
        if clave not in pedidas:
            continue
        decision = _normal(str(item.get("decision") or ""))
        if decision not in ("continua", "abre", "no_se"):
            decision = "no_se"
        veredictos[clave] = VeredictoDeCostura(decision=decision, cita=str(item.get("cita") or ""))
    return veredictos


def _normal(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.strip().lower().replace(" ", "_")


def _texto_de(payload: dict) -> str:
    choices = payload.get("choices") or [{}]
    contenido = (choices[0].get("message") or {}).get("content")
    return contenido if isinstance(contenido, str) else ""
