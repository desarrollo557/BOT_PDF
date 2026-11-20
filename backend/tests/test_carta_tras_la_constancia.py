"""La carta detrás de una constancia es su propio documento (1005652, UPD2437864, 2026-11-20).

El operador: «una constancia del contenido de la reclamación siempre va sola». En
UPD2437864 la constancia RE8673202203514 (pág. 2) salía con la carta de la pág. 3
-- «REF. Requerimiento», el cambio de titular -- y la cédula de quien la firma:
la carta decía «titular de pago» y «factura de cobro», se leía como factura, y
la regla de que la factura nunca va sola la devolvía a la constancia.
"""

from __future__ import annotations

from resolutions.domain.anexos_declarados import clase_de_la_hoja
from resolutions.domain.carta import abre_carta, asunto_de_la_carta

#: La pág. 3 de UPD2437864 como la leyó Tesseract, con los datos personales cambiados.
CARTA = """Santa Ana, agosto 24 de 2022
Señores AFINIA Grupo EPM
REF. Requerimiento
Me dirijo a ustedes cordialmente con el fin de solicitar el cambio de titular de pago y usuario
en la factura de cobro identificado con el NIC 1000001, que se encuentra bajo el nombre de
PEREZ GOMEZ ANA MARIA, en la dirección CL 1 CR 2 - 3 del barrio Centro en
Santa Ana, Magdalena; de modo que, a partir de esta solicitud, el titular de pago y usuario
quede bajo el nombre de JUAN CARLOS DIAZ MORA.
Sin otro tema que tratar, firmo la presente diligencia a los 24 días de agosto de 2022.
Atentamente,
JUAN CARLOS DIAZ MORA
C.C. 1000000001"""

#: La factura de la pág. 7, con sus rótulos impresos.
FACTURA = """Titular de Pago
PEREZ GOMEZ ANA MARIA
Usuario o suscriptor
Dirección de suministro CL 1 CR 2-3
Total a pagar mes $ 41.540
No. Facturas vencidas: 0
Fecha emisión: 21/06/2022
ID. de Cobros: 1000001020 - 31"""


class TestLaCartaNoEsFactura:
    def test_la_carta_que_nombra_la_factura_no_es_una_factura(self):
        assert abre_carta(CARTA)
        assert clase_de_la_hoja(CARTA) != "factura"

    def test_la_factura_sigue_siendo_factura(self):
        assert clase_de_la_hoja(FACTURA) == "factura"


class TestElAsuntoDeLaCarta:
    def test_el_cuerpo_no_continua_el_asunto(self):
        assert asunto_de_la_carta(CARTA) == "REQUERIMIENTO"

    def test_el_asunto_partido_en_dos_renglones_sigue_entero(self):
        carta = (
            "Magangué, 3 de abril de 2023\nSeñores AFINIA\n"
            "REF: Reclamo por cobro excesivo en la factura del mes de\n"
            "Marzo y cobro de alumbrado\nPor medio de la presente"
        )
        assert asunto_de_la_carta(carta) == "RECLAMO POR COBRO EXCESIVO EN LA FACTURA DEL MES DE MARZO Y COBRO DE ALUMBRADO"
