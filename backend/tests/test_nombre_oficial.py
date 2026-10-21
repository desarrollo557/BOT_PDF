"""El nombre oficial: el del catálogo del cliente, en el archivo y en el índice.

Lo pidió el operador el 2026-10-21 al ver UPD3102756: «colócale el nombre al
documento según el nombre oficial del documento del trámite, por ejemplo
derecho de petición, reclamo, pagaré, notificación personal, tanto en el nombre
del documento como en el inventario».
"""

from __future__ import annotations

from resolutions.domain.catalogo import POR_NOMBRE
from resolutions.domain.nombre_oficial import (
    AL_CATALOGO,
    nombre_del_asunto,
    nombre_oficial,
)
from resolutions.domain.titulo_impreso import titulo_impreso


class TestElCatalogo:
    def test_cada_traduccion_llega_a_un_tipo_del_catalogo(self):
        assert all(nombre in POR_NOMBRE for nombre in AL_CATALOGO.values())

    def test_reclamacion_es_reclamo(self):
        assert nombre_oficial("RECLAMACION", "Reclamo por alto consumo y alto costo en la factura") == "RECLAMO"

    def test_el_reclamo_por_estimado_es_el_del_catalogo(self):
        asunto = "RECLAMO POR COBRO DE SERVICIO ENERGIA POR ESTIMADO, VIOLACION ART.146 LEY 142"
        assert nombre_oficial("RECLAMACION", asunto) == "RECLAMO POR CONSUMO ESTIMADO"

    def test_los_que_ya_son_del_catalogo_no_cambian(self):
        for nombre in ("DERECHO DE PETICION", "PAGARE", "NOTIFICACION PERSONAL", "RECURSO DE REPOSICION EN SUBSIDIO DE APELACION"):
            assert nombre_oficial(nombre, None) == nombre

    def test_el_acuerdo_de_pago_y_la_autorizacion(self):
        assert nombre_oficial("RECONOCIMIENTO DE DEUDA Y ACUERDO DE PAGO") == (
            "RECONOCIMIENTO DE DEUDA Y PROPUESTA DE ACUERDO DE PAGO"
        )
        assert nombre_oficial("AUTORIZACION DE NOTIFICACION ELECTRONICA") == (
            "AUTORIZACION PARA LA NOTIFICACION ELECTRONICA"
        )


class TestLoQueElCatalogoNoTiene:
    def test_la_solicitud_se_llama_por_lo_que_solicita(self):
        asunto = "Solicitud de reconocimiento de silencio administrativo positivo por no dar respuesta dentro de los terminos ."
        assert nombre_oficial("SOLICITUD", asunto) == "SOLICITUD DE RECONOCIMIENTO DE SILENCIO ADMINISTRATIVO POSITIVO"

    def test_la_solicitud_que_el_catalogo_conoce(self):
        assert nombre_oficial("SOLICITUD", "Solicitud de rompimiento de solidaridad del NIC 123") == (
            "SOLICITUD DE ROMPIMIENTO DE SOLIDARIDAD"
        )

    def test_la_carta_sin_titulo_por_su_ref(self):
        asunto = "NOTIFICACION DEL REPORTE DEL SILENCIO ADMINISTRATIVO POSITIVO A LA SUPER SERVICIOS."
        assert nombre_oficial("DOCUMENTO", asunto) == "NOTIFICACION DEL REPORTE DEL SILENCIO ADMINISTRATIVO POSITIVO"

    def test_sin_titulo_ni_asunto_no_hay_nombre(self):
        assert nombre_oficial("DOCUMENTO", None) is None
        assert nombre_oficial("SOLICITUD", None) == "SOLICITUD"

    def test_el_asunto_que_no_dice_nada(self):
        assert nombre_del_asunto("No. RE3110202138312") is None
        assert nombre_del_asunto("COBRO EXCESIVO DEL SERVICIO DE ENERGIA") == "COBRO EXCESIVO DEL SERVICIO DE ENERGIA"


class TestElMembrete:
    def test_el_membrete_del_comite_no_es_un_titulo(self):
        """UPD3102756 pág. 23 salía «PUBLICOS DOMICILIARIOS DE MAGANGUE BOLIVAR»."""
        texto = (
            "COMITE DE DESARROLLO Y CONTROL SOCIAL DE LOS SERVICIOS\n"
            "PUBLICOS DOMICILIARIOS DE MAGANGUE BOLIVAR\n"
            "Magangue Bolívar 22 de Noviembre del 2023\n"
        )
        assert titulo_impreso(texto) is None


class TestElNombreDelArchivo:
    """«Número-título», sin el RE (el operador, 2026-10-21: «quita el RE del título»)."""

    def test_el_re_del_tramite_no_va_en_el_nombre(self):
        from resolutions.domain.naming import output_filename
        from resolutions.domain.resolution_code import ResolutionCode

        codigo = ResolutionCode(value="01 RE3110202212114", raw="RE3110202212114")
        nombre = output_filename(
            codigo, None, prefix=None, kind="DERECHO DE PETICION", mayusculas=True, sin_radicado=True
        )
        assert nombre == "01_DERECHO-DE-PETICION.pdf"

    def test_sin_re_igual(self):
        from resolutions.domain.naming import output_filename
        from resolutions.domain.resolution_code import ResolutionCode

        nombre = output_filename(
            ResolutionCode(value="02", raw="02"), None, prefix=None, kind="RECLAMO", mayusculas=True, sin_radicado=True
        )
        assert nombre == "02_RECLAMO.pdf"
