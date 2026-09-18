"""Lo que un trabajo le pidió a los proveedores de pago, contado.

Hasta acá el sistema sabía cuántas páginas leía y no sabía cuántas pagaba.
Son cosas distintas: una página se lee gratis con Tesseract y se vuelve a leer
con el motor de pago si hizo falta, y la esquina del folio es otra petición
aparte. En un libro de 398 páginas eso son unas seiscientas llamadas, y el
operador no tenía forma de saberlo hasta que la cuenta contestó "sin
presupuesto" en mitad de un libro.

Se cuenta en las unidades en que cobra cada proveedor. El OCR de Mistral cobra
por **página procesada** -- lo dice él mismo en cada respuesta, y es lo que se
anota, no lo que se pidió --; los modelos de chat cobran por **token**, de
entrada y de salida, y Claude distingue los que sirvió de caché porque los
cobra a otro precio. Sumarlo todo en un solo número sería mezclar peras con
manzanas, así que se conserva por proveedor y se totaliza aparte.

El dinero es opcional y lo pone el operador: el precio cambia, varía por cuenta
y por moneda, y un número inventado aquí sería la única cifra de la pantalla que
no sale de una medida. Con un precio por página configurado se estima; sin él,
se enseñan las unidades y ya.

Vive en un solo objeto por trabajo, y lo comparten todos los adaptadores que
ese trabajo construya. Es seguro entre hilos porque las lecturas van en
paralelo y ocho lectores anotando a la vez sin candado perderían cuentas.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class ConsumoDeProveedor:
    """Las cuentas de un proveedor, en sus propias unidades."""

    peticiones: int = 0
    #: Lo que el proveedor de OCR dijo haber facturado, no lo que se le mandó.
    paginas_facturadas: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    #: Los de entrada que se sirvieron desde caché, que Claude cobra aparte.
    tokens_cache: int = 0
    #: Respuestas de "ahora no" -- 429 y cinco centenas -- que se reintentaron.
    rechazos: int = 0
    #: Peticiones que se dieron por perdidas: la página volvió sin texto.
    fallos: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "peticiones": self.peticiones,
            "paginas_facturadas": self.paginas_facturadas,
            "tokens_entrada": self.tokens_entrada,
            "tokens_salida": self.tokens_salida,
            "tokens_cache": self.tokens_cache,
            "rechazos": self.rechazos,
            "fallos": self.fallos,
        }


@dataclass
class Consumo:
    """El consumo de un trabajo entero, proveedor por proveedor."""

    #: Precio de una página de OCR, en la moneda de abajo. ``None`` es "no se
    #: estima dinero", que es distinto de cero.
    precio_por_pagina: float | None = None
    moneda: str = "USD"
    _por_proveedor: dict[str, ConsumoDeProveedor] = field(default_factory=dict)
    _candado: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _de(self, proveedor: str) -> ConsumoDeProveedor:
        return self._por_proveedor.setdefault(proveedor, ConsumoDeProveedor())

    def peticion(
        self,
        proveedor: str,
        *,
        paginas: int = 0,
        tokens_entrada: int = 0,
        tokens_salida: int = 0,
        tokens_cache: int = 0,
    ) -> None:
        """Una petición que el proveedor atendió, con lo que dijo haber cobrado."""
        with self._candado:
            cuenta = self._de(proveedor)
            cuenta.peticiones += 1
            cuenta.paginas_facturadas += max(0, int(paginas or 0))
            cuenta.tokens_entrada += max(0, int(tokens_entrada or 0))
            cuenta.tokens_salida += max(0, int(tokens_salida or 0))
            cuenta.tokens_cache += max(0, int(tokens_cache or 0))

    def rechazo(self, proveedor: str) -> None:
        """Un "más despacio" que se va a reintentar. No cobra, pero cuenta."""
        with self._candado:
            self._de(proveedor).rechazos += 1

    def fallo(self, proveedor: str) -> None:
        """Una petición que se dio por perdida."""
        with self._candado:
            self._de(proveedor).fallos += 1

    @property
    def vacio(self) -> bool:
        with self._candado:
            return not any(
                c.peticiones or c.rechazos or c.fallos for c in self._por_proveedor.values()
            )

    def as_dict(self) -> dict[str, object]:
        """Lo que viaja a la pantalla y al informe.

        Los totales van sumados por unidad y nunca entre unidades: las páginas
        facturadas del OCR no se suman a los tokens de un modelo de chat, porque
        no son la misma cosa ni cuestan lo mismo.
        """
        with self._candado:
            proveedores = {nombre: c.as_dict() for nombre, c in self._por_proveedor.items()}
            total = ConsumoDeProveedor()
            for c in self._por_proveedor.values():
                total.peticiones += c.peticiones
                total.paginas_facturadas += c.paginas_facturadas
                total.tokens_entrada += c.tokens_entrada
                total.tokens_salida += c.tokens_salida
                total.tokens_cache += c.tokens_cache
                total.rechazos += c.rechazos
                total.fallos += c.fallos
            coste = (
                round(total.paginas_facturadas * self.precio_por_pagina, 4)
                if self.precio_por_pagina is not None
                else None
            )
        return {
            "proveedores": proveedores,
            **total.as_dict(),
            "tokens": total.tokens_entrada + total.tokens_salida,
            "coste_estimado": coste,
            "moneda": self.moneda,
        }


def anotar_uso_anthropic(consumo: Consumo | None, proveedor: str, message) -> None:
    """Lo que el SDK de Anthropic dice haber cobrado por un mensaje."""
    if consumo is None:
        return
    uso = getattr(message, "usage", None)
    consumo.peticion(
        proveedor,
        tokens_entrada=getattr(uso, "input_tokens", 0) or 0,
        tokens_salida=getattr(uso, "output_tokens", 0) or 0,
        tokens_cache=getattr(uso, "cache_read_input_tokens", 0) or 0,
    )


def anotar_uso_json(consumo: Consumo | None, proveedor: str, payload: dict) -> None:
    """Lo que un proveedor HTTP dice haber cobrado, en cualquiera de sus formas.

    Mistral y OpenAI lo llaman ``usage`` con ``prompt_tokens`` y
    ``completion_tokens``; Gemini lo llama ``usageMetadata`` con
    ``promptTokenCount`` y ``candidatesTokenCount``. Se leen las dos y se anota
    lo que haya; una respuesta sin cuenta se anota como una petición y cero
    tokens, que es lo que se sabe de ella.
    """
    if consumo is None:
        return
    uso = payload.get("usage") or payload.get("usageMetadata") or {}
    entrada = uso.get("prompt_tokens") or uso.get("promptTokenCount") or 0
    salida = uso.get("completion_tokens") or uso.get("candidatesTokenCount") or 0
    consumo.peticion(proveedor, tokens_entrada=entrada, tokens_salida=salida)
