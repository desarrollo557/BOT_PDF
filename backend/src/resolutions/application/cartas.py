"""Las cartas de una caja: cuáles abren un trámite y qué va con cada una.

Lo pidió el operador el 2026-10-21 ante UPD3102756: «cada trámite va solo,
obviamente con sus respectivos anexos», y los trámites duplicados en un mismo
PDF «la mayoría de veces son anexos a trámites diferentes, o sea como pruebas».
Las señales de cada hoja salen de :mod:`~resolutions.domain.carta`; aquí se
cruzan con las de sus vecinas y con los sellos que se leyeron, que es lo que
una hoja sola no sabe:

- **la copia** lo es de algo que ya apareció antes en la caja: una carta con su
  misma fecha y su mismo asunto, o un sello con su mismo RE;
- **la hoja que sigue a la carta** sólo lo es detrás de la carta o de otra hoja
  que la sigue;
- **la constancia citada** es el radicado de la Superintendencia que la carta de
  delante copia en su cuerpo.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..domain.asunto_del_documento import (
    ESCRITOS_DEL_TRAMITE,
    PIEZAS_DEL_ACUERDO,
    es_carta_de_la_empresa,
    titulo_del_documento,
)
from ..domain.carta import (
    abre_carta,
    cita_el_numero,
    continua_la_carta,
    es_la_misma_carta,
    huella_de_la_carta,
)
from ..domain.sello import Sello, numero_de_la_superintendencia

#: Cuántas hojas hacia atrás se busca la carta que cita la constancia.
HOJAS_DE_LA_CITA = 2


@dataclass(frozen=True, slots=True)
class Cartas:
    """Lo que las cartas de una caja deciden sobre su corte."""

    #: La primera hoja de cada carta.
    primeras: frozenset[int] = field(default_factory=frozenset)
    #: Las que son un escrito del trámite -- reclamo, petición, queja, recurso --:
    #: las únicas que abren documento por ser carta.
    de_tramite: frozenset[int] = field(default_factory=frozenset)
    #: Las que son copia de una carta o de un sello anteriores de la caja.
    copias: frozenset[int] = field(default_factory=frozenset)
    #: Las que empiezan a mitad de la carta de delante.
    siguen: frozenset[int] = field(default_factory=frozenset)
    #: Los radicados de la Superintendencia que la carta de delante cita.
    citadas: frozenset[int] = field(default_factory=frozenset)
    #: Las que trae la empresa -- su respuesta, su citación --, no el cliente.
    de_la_empresa: frozenset[int] = field(default_factory=frozenset)

    @classmethod
    def de(cls, textos: Mapping[int, str | None], sellos: Mapping[int, Sello]) -> Cartas:
        orden = sorted(textos)
        # El reconocimiento de deuda también se escribe como carta, y no abre:
        # va con su pagaré y su habeas data en el acuerdo de pago, que junta
        # F4b (UPD2326302 pág. 11, UPD2346029 pág. 8).
        primeras = {
            p
            for p in orden
            if abre_carta(textos.get(p) or "")
            and titulo_del_documento(textos.get(p) or "") not in PIEZAS_DEL_ACUERDO
        }
        copias: set[int] = set()
        vistas: list[tuple[str, str | None]] = []
        for pagina in sorted(primeras):
            huella = huella_de_la_carta(textos.get(pagina) or "")
            if huella is None:
                continue
            if any(es_la_misma_carta(huella, vista) for vista in vistas):
                copias.add(pagina)
            else:
                vistas.append(huella)
        # Un sello con un RE ya visto NO es una copia: la ventanilla radica el
        # recurso con el RE de la reclamación que recurre (UPD2326360: la
        # reclamación de la pág. 3 y su recurso de la 10, los dos con
        # RE3110202262573). Lo que delata la copia es la carta repetida.
        siguen: set[int] = set()
        for pagina in orden:
            if (
                pagina not in primeras
                and (pagina - 1 in primeras or pagina - 1 in siguen)
                and continua_la_carta(textos.get(pagina) or "")
            ):
                siguen.add(pagina)
        citadas = set()
        for pagina in orden:
            numero = numero_de_la_superintendencia(textos.get(pagina) or "")
            if numero and any(
                cita_el_numero(textos.get(antes) or "", numero)
                for antes in range(pagina - HOJAS_DE_LA_CITA, pagina)
                if antes in textos
            ):
                citadas.add(pagina)
        de_la_empresa = {p for p in primeras if es_carta_de_la_empresa(textos.get(p) or "")}
        return cls(
            primeras=frozenset(primeras),
            de_tramite=frozenset(
                p
                for p in primeras - de_la_empresa
                if titulo_del_documento(textos.get(p) or "") in ESCRITOS_DEL_TRAMITE
            ),
            copias=frozenset(copias),
            siguen=frozenset(siguen),
            citadas=frozenset(citadas),
            de_la_empresa=frozenset(de_la_empresa),
        )

    @property
    def pruebas(self) -> frozenset[int]:
        """Lo que va como anexo del documento que lo trae: copias y constancias citadas."""
        return self.copias | self.citadas

    @property
    def no_abren(self) -> frozenset[int]:
        """Las hojas cuyo sello no abre documento."""
        return self.siguen | self.pruebas

    def que_abren(self, sellos: Mapping[int, Sello]) -> frozenset[int]:
        """Las cartas que abren documento: ni copias, ni citadas, ni dentro de unos folios.

        ``sellos`` son los que abren: lo que la ventanilla recibió como un solo
        escrito -- «Folios: 19» -- no lo parte una carta de dentro.
        """
        cubiertas = {
            p
            for inicio, sello in sellos.items()
            if sello.folios and sello.folios > 1
            for p in range(inicio + 1, inicio + sello.folios)
        }
        return frozenset(self.de_tramite - self.pruebas - cubiertas)

    def escritos(self, que_abren: frozenset[int]) -> frozenset[int]:
        """Las que abren y son del cliente: ningún trámite se les une por su RE."""
        return frozenset(que_abren - self.de_la_empresa)
