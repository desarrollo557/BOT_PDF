"""Resumen de actas de grado con Mistral (chat completions).

Prohíbe explícitamente la frase "LLAMADO A LISTA Y VERIFICACIÓN DEL QUORUM"
en el resumen. Usa mistral-small-latest (barato, suficiente para resumen).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from ..application.consumo import Consumo

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.mistral.ai/v1/chat/completions"

# Frase que NUNCA debe aparecer en el resumen
FRASE_PROHIBIDA = "LLAMADO A LISTA Y VERIFICACIÓN DEL QUORUM"

# Prompt del sistema para el resumen
SYSTEM_PROMPT = (
    "Eres un secretario académico de la Universidad de Cartagena. "
    "Tu tarea es resumir actas de grado en 3-4 líneas máximo. "
    "El resumen debe incluir: quién se gradúa, qué título recibe, "
    "fecha de la ceremonia, resolución que autoriza. "
    "REGLA ABSOLUTA: NUNCA uses ni menciones la frase "
    "'LLAMADO A LISTA Y VERIFICACIÓN DEL QUORUM' ni ninguna variante "
    "(mayúsculas/minúsculas, con/sin tildes). Si el texto la contiene, omítela completamente. "
    "Devuelve SOLO el resumen en texto plano, sin etiquetas, sin JSON, sin preámbulos."
)


@dataclass(frozen=True, slots=True)
class MistralSummaryConfig:
    model: str = "mistral-small-latest"
    timeout_seconds: int = 60
    max_tokens: int = 500
    temperatura: float = 0.1


class MistralSummaryError(RuntimeError):
    """Error al pedir resumen a Mistral."""


class MistralSummaryAdapter:
    """Genera resúmenes de actas de grado usando Mistral chat completions."""

    def __init__(
        self,
        api_key: str | None = None,
        config: MistralSummaryConfig | None = None,
        consumo: Consumo | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        self._config = config or MistralSummaryConfig()
        self._consumo = consumo
        self._sin_presupuesto = False

    @property
    def disponible(self) -> bool:
        return bool(self._api_key) and not self._sin_presupuesto

    def summarize(self, texto_acta: str) -> str:
        """Genera un resumen de 3-4 líneas para una acta de grado."""
        if not self._api_key or self._sin_presupuesto:
            return "SIN RESUMEN (sin API key)"

        # Doble seguridad: eliminar la frase prohibida del input
        texto_limpio = self._limpiar_texto(texto_acta)

        body = json.dumps({
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Acta de grado:\n\n{texto_limpio}\n\nResumen:"},
            ],
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperatura,
        }).encode()

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
        except urllib.error.HTTPError as error:
            detalle = error.read()[:200].decode("utf-8", "replace")
            if error.code == 402:
                self._sin_presupuesto = True
                logger.error("Mistral sin presupuesto: %s", detalle)
                return "SIN RESUMEN (sin presupuesto)"
            if error.code == 429:
                logger.warning("Mistral rate limit (429): %s", detalle)
                return "SIN RESUMEN (rate limit)"
            logger.warning("Mistral HTTP %s: %s", error.code, detalle)
            return "SIN RESUMEN (error HTTP)"
        except Exception as error:  # noqa: BLE001
            logger.warning("Mistral request failed: %s", error)
            return "SIN RESUMEN (error de red)"

        # Extraer respuesta
        try:
            choices = payload.get("choices") or []
            if not choices:
                return "SIN RESUMEN (respuesta vacía)"
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            resumen = content.strip()

            # Verificación final: si la frase prohibida se coló, eliminarla
            resumen = self._limpiar_resumen(resumen)

            # Registrar consumo
            if self._consumo is not None:
                usage = payload.get("usage") or {}
                tokens = usage.get("total_tokens") or 0
                self._consumo.peticion("mistral-summary", paginas=0, tokens=tokens)

            return resumen if resumen else "SIN RESUMEN (vacío)"

        except Exception as error:  # noqa: BLE001
            logger.warning("error parseando respuesta Mistral: %s", error)
            return "SIN RESUMEN (parse error)"

    def _limpiar_texto(self, texto: str) -> str:
        """Elimina la frase prohibida del texto de entrada (case-insensitive)."""
        import re
        # Variantes comunes de la frase prohibida
        patrones = [
            re.escape(FRASE_PROHIBIDA),
            re.escape(FRASE_PROHIBIDA.lower()),
            re.escape(FRASE_PROHIBIDA.upper()),
            r"LLAMADO\s+A\s+LISTA\s+Y\s+VERIFICACI[OÓ]N\s+DEL\s+QUORUM",
            r"Llamado\s+a\s+lista\s+y\s+verificaci[oó]n\s+del\s+quorum",
        ]
        limpio = texto
        for pat in patrones:
            limpio = re.sub(pat, "", limpio, flags=re.IGNORECASE)
        return limpio

    def _limpiar_resumen(self, resumen: str) -> str:
        """Elimina la frase prohibida si Mistral la incluyó en el output."""
        import re
        patrones = [
            re.escape(FRASE_PROHIBIDA),
            re.escape(FRASE_PROHIBIDA.lower()),
            re.escape(FRASE_PROHIBIDA.upper()),
            r"LLAMADO\s+A\s+LISTA\s+Y\s+VERIFICACI[OÓ]N\s+DEL\s+QUORUM",
        ]
        limpio = resumen
        for pat in patrones:
            limpio = re.sub(pat, "", limpio, flags=re.IGNORECASE)
        # Limpiar espacios dobles y saltos de línea excesivos
        limpio = re.sub(r"\n{3,}", "\n\n", limpio)
        limpio = re.sub(r" {2,}", " ", limpio)
        return limpio.strip()