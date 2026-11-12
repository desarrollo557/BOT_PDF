"""El reclamo y su constancia con su RE, y el índice por fecha con el expediente = NIC.

Lo dictó el operador el 2026-11-04. Primero lo hizo ``scripts/renombrar_reclamaciones.py``
sobre las cajas de MAGANGUE ya entregadas; después, ante unas carpetas que el bot
no había procesado: «incluye los cambios, que los reclamos o constancias de
reclamación lleven su RE, el NIC en el Excel, en el nombre de expediente y en el
NIC, y el orden de fecha». Lo que entrega el bot tiene que quedar como lo deja el
script: aquí se comprueba también que el script ya no encuentra nada que cambiar.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

from resolutions.adapters.indice_electronico import FilaDelIndice, en_orden_cronologico
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.naming import output_filename
from resolutions.domain.nombre_oficial import (
    CON_RE_EN_EL_NOMBRE,
    es_re,
    lleva_re_en_el_nombre,
    re_del_archivo,
)
from resolutions.domain.orden_del_indice import orden_cronologico
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.sello import Sello

RE = "RE2310202007709"
OTRO = "RE2310202405234"


def _nombre(valor: str, kind: str, **opciones) -> str:
    raw = valor.split()[-1] if " " in valor else valor
    return output_filename(
        ResolutionCode(value=valor, raw=raw),
        None,
        prefix=None,
        kind=kind,
        mayusculas=True,
        sin_radicado=True,
        radicado_en=CON_RE_EN_EL_NOMBRE,
        **opciones,
    )


class TestElNombreDelArchivo:
    def test_el_reclamo_y_la_constancia_llevan_su_re_detras(self):
        assert _nombre(f"03 {RE}", "RECLAMO") == f"03_RECLAMO-{RE}.pdf"
        assert (
            _nombre(f"01 {RE}", "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION")
            == f"01_CONSTANCIA-DEL-CONTENIDO-DE-LA-RECLAMACION-{RE}.pdf"
        )

    def test_el_documento_con_su_sello_lleva_su_re_sea_del_tipo_que_sea(self):
        assert _nombre(f"01 {RE}", "DERECHO DE PETICION", con_su_re=True) == f"01_DERECHO-DE-PETICION-{RE}.pdf"
        assert _nombre(f"01 {RE}", "DERECHO DE PETICION") == "01_DERECHO-DE-PETICION.pdf"

    def test_la_contestacion_a_reclamacion_lleva_su_re(self):
        assert (
            _nombre(f"02 {RE}", "CONTESTACION A RECLAMACION")
            == f"02_CONTESTACION-A-RECLAMACION-{RE}.pdf"
        )

    def test_los_demas_siguen_numero_titulo(self):
        # «Solo los 2 exactos» (el operador, 2026-11-04).
        assert _nombre(f"02 {RE}", "DERECHO DE PETICION") == "02_DERECHO-DE-PETICION.pdf"
        assert _nombre(f"02 {RE}", "NOTIFICACION PERSONAL RECLAMOS") == "02_NOTIFICACION-PERSONAL-RECLAMOS.pdf"
        assert _nombre(f"02 {RE}", "RESPUESTA A RECLAMACION") == "02_RESPUESTA-A-RECLAMACION.pdf"
        assert _nombre(f"02 {RE}", "RECLAMO POR CONSUMO ESTIMADO") == "02_RECLAMO-POR-CONSUMO-ESTIMADO.pdf"

    def test_sin_re_o_con_un_p_queda_sin_nada_detras(self):
        assert _nombre("04", "RECLAMO") == "04_RECLAMO.pdf"
        assert _nombre("04 P43102019110005", "RECLAMO") == "04_RECLAMO.pdf"

    def test_al_apretar_el_nombre_el_re_no_se_toca(self):
        nombre = _nombre(f"01 {RE}", "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION", budget=40)
        assert nombre.endswith(f"-{RE}.pdf") and len(nombre) <= 40
        assert _nombre(f"01 {RE}", "RECLAMO", budget=24) == f"01_{RE}.pdf"

    def test_sin_radicado_en_ningun_tipo_lo_lleva(self):
        nombre = output_filename(
            ResolutionCode(value=f"03 {RE}", raw=RE), None, prefix=None, kind="RECLAMO", mayusculas=True, sin_radicado=True
        )
        assert nombre == "03_RECLAMO.pdf"


class TestLosTitulosConRe:
    def test_solo_los_tres_exactos(self):
        assert lleva_re_en_el_nombre("RECLAMO")
        assert lleva_re_en_el_nombre("Constancia del contenido de la reclamación")
        # La respuesta de la empresa a una reclamación, con el nombre del operador (2026-11-11).
        assert lleva_re_en_el_nombre("CONTESTACION A RECLAMACION")
        assert not lleva_re_en_el_nombre("RESPUESTA A RECLAMACION")
        assert not lleva_re_en_el_nombre("RECLAMO POR CONSUMO ESTIMADO")
        assert not lleva_re_en_el_nombre("NOTIFICACION PERSONAL RECLAMOS")
        assert not lleva_re_en_el_nombre(None)

    def test_un_re_es_re_y_trece_cifras(self):
        assert es_re(RE)
        assert not es_re("RE231020200770")
        assert not es_re("P43102019110005")
        assert not es_re(None)

    def test_el_re_del_archivo(self):
        assert re_del_archivo(f"UPD1/03_RECLAMO-{RE}.pdf") == RE
        assert re_del_archivo("03_RECLAMO.pdf") is None


class TestElOrdenPorFecha:
    def test_lo_antiguo_primero_y_sin_fecha_al_final(self):
        fechas = [date(2024, 2, 20), None, date(2024, 1, 31), date(2024, 1, 31)]
        # A igual fecha, el orden de las hojas.
        assert orden_cronologico(fechas) == [2, 3, 0, 1]

    def test_ordenar_dos_veces_da_lo_mismo(self):
        fechas = [date(2024, 2, 20), None, date(2024, 1, 31), date(2024, 1, 31)]
        una = [fechas[i] for i in orden_cronologico(fechas)]
        assert orden_cronologico(una) == [0, 1, 2, 3]

    def test_las_filas_se_renumeran(self):
        filas = [
            FilaDelIndice("CONSTANCIA", date(2024, 2, 20), None, 1, 1),
            FilaDelIndice("PAGARE", None, None, 2, 1),
            FilaDelIndice("NOTIFICACION", date(2024, 1, 31), None, 3, 1),
        ]
        assert [(f.orden, f.nombre) for f in en_orden_cronologico(filas)] == [
            (1, "NOTIFICACION"),
            (2, "CONSTANCIA"),
            (3, "PAGARE"),
        ]


class TestElReDelWorker:
    """``_poner_el_re_en_el_nombre``: de lo ya leído, sin volver a leer nada."""

    @staticmethod
    def _grupos(*grupos: tuple[str, list[int], str]) -> GroupingResult:
        return GroupingResult(
            groups=[
                PageGroup(code=ResolutionCode(value=valor, raw=valor.split()[-1]), page_numbers=paginas, kind=kind)
                for valor, paginas, kind in grupos
            ],
            quarantine=[],
            repairs=[],
        )

    @staticmethod
    def _poner(grupos, anexos=None, *, textos=None, sellos=None, sin_re=(), abren=(), rechazados=None):
        from resolutions.api.worker.correspondencia import _poner_el_re_en_el_nombre

        return _poner_el_re_en_el_nombre(
            grupos,
            anexos or {},
            textos=textos or {},
            sellos=sellos or {},
            sin_re=set(sin_re),
            abren=set(abren),
            rechazados=rechazados,
        )

    def test_el_de_su_tramite_se_queda(self):
        grupos, _, hallados = self._poner(self._grupos((f"01 {RE}", [1], "RECLAMO")), textos={1: f"cita {OTRO}"})
        assert grupos.groups[0].code.value == f"01 {RE}"
        assert hallados == {"1": f"{RE}: el de su trámite"}

    def test_sin_tramite_toma_el_de_su_sello(self):
        grupos, anexos, hallados = self._poner(
            self._grupos(("01", [1, 2], "RECLAMO")),
            {"01": [2]},
            sellos={1: Sello(clase="impreso", radicado=RE)},
        )
        assert grupos.groups[0].code.value == f"01 {RE}"
        # Sus anexos siguen siendo suyos con el código nuevo.
        assert anexos == {f"01 {RE}": [2]}
        assert hallados == {"1": f"{RE}: del sello de la pág. 1"}

    def test_la_constancia_toma_el_que_imprime_su_texto(self):
        grupos, _, _ = self._poner(
            self._grupos(("01", [1], "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION")),
            textos={1: f"RECIBI CONSTANCIA DEL CONTENIDO ... N° PQR {RE}"},
        )
        assert grupos.groups[0].code.value == f"01 {RE}"

    def test_la_hoja_con_sello_ilegible_no_toma_el_re_que_cita(self):
        # El RE que cita el texto de una hoja con sello es el de otro trámite.
        grupos, _, hallados = self._poner(
            self._grupos(("01", [1], "RECLAMO")),
            textos={1: f"contra la reclamación {OTRO}"},
            sellos={1: Sello(clase="tinta", radicado=None)},
        )
        assert grupos.groups[0].code.value == "01" and hallados == {}

    def test_las_copias_y_los_anexos_no_dan_re(self):
        grupos, _, _ = self._poner(
            self._grupos(("01", [1, 2, 3], "RECLAMO")),
            {"01": [3]},
            textos={2: f"copia {OTRO}", 3: f"anexo {OTRO}"},
            sin_re={2},
        )
        assert grupos.groups[0].code.value == "01"

    def test_cualquier_documento_con_su_sello_lleva_su_re(self):
        """El operador, 2026-11-11: «cuando un documento tenga su sello… agarra el RE para el nombre»."""
        grupos, _, hallados = self._poner(
            self._grupos(("01", [1], "DERECHO DE PETICION")), sellos={1: Sello(clase="impreso", radicado=RE)}
        )
        assert grupos.groups[0].code.value == f"01 {RE}" and grupos.groups[0].re_en_el_nombre
        assert hallados == {"1": f"{RE}: del sello de la pág. 1"}
        # Sin sello, el RE que cita su texto no basta: es el de otro papel.
        grupos, _, hallados = self._poner(self._grupos(("01", [1], "DERECHO DE PETICION")), textos={1: f"cita {OTRO}"})
        assert grupos.groups[0].code.value == "01" and hallados == {}
        # Ni el sello de una copia aportada como prueba.
        grupos, _, _ = self._poner(
            self._grupos(("01", [1, 2], "DERECHO DE PETICION")),
            sellos={2: Sello(clase="impreso", radicado=RE)},
            sin_re={2},
        )
        assert grupos.groups[0].code.value == "01"

    def test_el_re_a_mano_lo_valida_el_agente(self):
        """1005965 p1: la IA leyó «RE2371202302499» en el sello que dice «RE2311202302499»."""
        rechazados: list = []
        grupos, _, hallados = self._poner(
            self._grupos(("01", [1], "DERECHO DE PETICION"), ("02", [2], "DERECHO DE PETICION")),
            sellos={
                1: Sello(clase="tinta", radicado="RE2371202302499", fecha=date(2023, 7, 19)),
                # Otro año que el de su sello: no se cree.
                2: Sello(clase="tinta", radicado="RE2311202202952", fecha=date(2023, 8, 28)),
            },
            rechazados=rechazados,
        )
        assert [g.code.value for g in grupos.groups] == ["01 RE2311202302499", "02"]
        assert "oficina 2371 leída por 2311" in hallados["1"]
        assert [r["page"] for r in rechazados] == [2] and "no se cree" in rechazados[0]["reason"]


#: La respuesta de la empresa de 1016215 (UPD2437946 p7), tal como la deja la capa.
CONTESTACION = (
    "Consecutivo No. 9234202200564\nSANTA ROSA DEL SUR, 13 de octubre de 2022\nSeñor(a)\n"
    "YORLENE RIAPIRA PARADA\nDirección: CL 3 CR 2 64, SAN LUCAS, SANTA ROSA DEL SUR\nNIC: 1016215\n"
    "ASUNTO: Reclamación No. RE9234202200564\nEstimado Señor(a) YORLENE RIAPIRA PARADA:\n"
    "En atención a su petición presentada en nuestras instalaciones el 13 de octubre de 2022,"
)
#: La carta del cliente de la misma caja (p1), de 2021 y de otra persona.
CARTA_DEL_CLIENTE = (
    "Santa Rosa del Sur - Bolívar. Julio 15 de 2021\nSeñores\nCARIBEMAR S.A.S. E.S.P.\nSANTA ROSA DEL SUR\n"
    "CAMBIO DE ESTRATO\nREF.\nSaludo Cordial;\nPor medio de la presente me permito hacerle la siguiente solicitud:"
)


class TestLaContestacionAReclamacion:
    """El operador, 2026-11-11, ante 1016215: «cuando un documento tenga este formato, le colocarás el RE
    y como nombre contestación a reclamación»; y que no se pegue a lo que no es de su trámite."""

    def test_se_reconoce_por_su_consecutivo_y_su_asunto(self):
        from resolutions.domain.asunto_del_documento import es_contestacion_a_reclamacion

        assert es_contestacion_a_reclamacion(CONTESTACION)
        # Sin consecutivo en la cabeza, o con otro asunto, no.
        assert not es_contestacion_a_reclamacion(CONTESTACION.replace("Consecutivo No. 9234202200564\n", ""))
        assert not es_contestacion_a_reclamacion(CONTESTACION.replace("Reclamación No.", "Recurso No."))
        assert not es_contestacion_a_reclamacion(CARTA_DEL_CLIENTE)

    @staticmethod
    def _sigue(grupos, textos, sellos=None):
        from resolutions.api.worker.correspondencia import _sigue_con_lo_de_delante

        return _sigue_con_lo_de_delante(7, "RE9234202200564", grupos, textos, sellos or {})

    @staticmethod
    def _grupo(paginas):
        return PageGroup(code=ResolutionCode(value="01", raw="01"), page_numbers=paginas, kind="")

    def test_no_sigue_a_la_carta_de_otro_tramite(self):
        # La carta de 2021 y su anexo sin fecha (la compraventa) delante de la respuesta de 2022.
        textos = {1: CARTA_DEL_CLIENTE, 5: "CONTRATO DE COMPRA VENTA DE UN PREDIO RURAL", 7: CONTESTACION}
        assert not self._sigue([self._grupo([1, 2, 3, 4]), self._grupo([5, 6])], textos)

    def test_sigue_al_escrito_con_su_re_o_de_su_fecha(self):
        mismo_re = {1: "Reclamo por consumo estimado RE9234202200564", 7: CONTESTACION}
        assert self._sigue([self._grupo([1, 2])], mismo_re)
        de_su_fecha = {1: CARTA_DEL_CLIENTE.replace("Julio 15 de 2021", "Octubre 10 de 2022"), 7: CONTESTACION}
        assert self._sigue([self._grupo([1, 2])], de_su_fecha)

    def test_un_escrito_que_abre_sin_fecha_no_se_salta(self):
        # UPD2366126: el recurso con sello de fecha ilegible delante de la publicación del aviso.
        # Saltarlo llevaba a un acta de abril y partía la publicación de su escrito.
        from resolutions.api.worker.correspondencia import _sigue_con_lo_de_delante

        textos = {1: "ACTA DE REVISION Fecha: 20/04/2021", 5: "recurso de la usuaria", 7: CONTESTACION}
        grupos = [self._grupo([1, 2, 3, 4]), self._grupo([5, 6])]
        assert _sigue_con_lo_de_delante(7, "RE9234202200564", grupos, textos, {}, abren={5})
        # Sin abrir nada -- un anexo --, sí se salta.
        assert not _sigue_con_lo_de_delante(
            7, "RE9234202200564", grupos, {**textos, 1: CARTA_DEL_CLIENTE}, {}, abren=set()
        )

    def test_ante_la_duda_sigue(self):
        # Nada de delante trae fecha ni RE: como siempre, sigue con lo de delante.
        assert self._sigue([self._grupo([5, 6])], {5: "CONTRATO DE COMPRA VENTA", 7: CONTESTACION})
        assert self._sigue([], {7: CONTESTACION})

    def test_la_carta_del_cliente_se_fecha_y_se_nombra_por_su_ref(self):
        from resolutions.domain.carta import asunto_de_la_carta
        from resolutions.domain.fecha_por_estructura import fecha_de_la_hoja

        # «Ciudad. Mes DD de AAAA»: salía «S.F.».
        assert fecha_de_la_hoja(CARTA_DEL_CLIENTE) == date(2021, 7, 15)
        # El asunto que la capa dejó encima de «REF.», no el saludo de debajo.
        assert asunto_de_la_carta(CARTA_DEL_CLIENTE) == "CAMBIO DE ESTRATO"
        # Sin asunto, y encima el destinatario: ni el saludo ni la empresa.
        assert asunto_de_la_carta("Señores\nCARIBEMAR S.A.S. E.S.P.\nREF.\nCordial saludo,\nPor medio de la presente") is None
        assert asunto_de_la_carta("Señores\nAFINIA\nREF.\nCordial saludo,\nPor medio de la presente") is None


#: Las dos cartas de 1005965 (UPD3102771), tal como las deja la capa: «Asunto» suelto.
PETICION_DE_JULIO = (
    "Santa Rosa del Sur - Bolívar. Julio 11 de 2023\nSeñores\nCARIBEMAR\nCOORDINADOR DE IRREGULARIDADES\n"
    "LA CIUDAD\nART. 23 DEL CÓDIGO CONTENCIOSO\nADMINISTRATIVO Y A LA CONSTITUCIÓN POLÍTICA\n"
    "1994, ARTICULO 11.\nAsunto\nSOLICITUD SE REALICE CORRECCION DEL VALOR EN LA\nFACTURA\nReferencia\n"
    "mayor de edad, vecino de este municipio, con cédula\nNIXON FERNEY ARIZA MOYA\n"
    "de ciudadanía N° 7.925.433, dentro del término legal llego ante el despacho a su digno cargo, con el objeto\n"
    "de interponer DERECHO DE PETICION ante CARIBEMAR, realiza cobro por aumento de\n"
)


class TestLasDosPeticionesDe1005965:
    """Dos derechos de petición, de julio y de agosto, con su sello cada uno, salían en un solo PDF."""

    def test_el_asunto_suelto_abre_la_carta(self):
        from resolutions.domain.carta import abre_carta, asunto_de_la_carta

        assert abre_carta(PETICION_DE_JULIO)
        assert asunto_de_la_carta(PETICION_DE_JULIO) == "SOLICITUD SE REALICE CORRECCION DEL VALOR EN LA FACTURA"
        # El «asunto» de la prosa, en minúscula y partido en renglones, no (UPD2460819 p203).
        prosa = "Señores\nAFINIA\nREF: recurso\nnotificada por medio del CONSECUTIVO 23/06/2021,\ncuyo\nasunto\nes reclamación"
        assert asunto_de_la_carta(prosa) == "RECURSO NOTIFICADA POR MEDIO DEL CONSECUTIVO 23/06/2021,"

    def test_la_solicitud_que_interpone_un_escrito_abre_su_tramite(self):
        from resolutions.application.cartas import Cartas

        agosto = PETICION_DE_JULIO.replace("Julio 11 de 2023", "Agosto 28 de 2023")
        cartas = Cartas.de({1: PETICION_DE_JULIO, 2: agosto}, {})
        assert cartas.que_abren({}) == {1, 2}
        # La «SOLICITUD» que no interpone nada sigue sin abrir.
        sola = PETICION_DE_JULIO.replace("de interponer DERECHO DE PETICION ante CARIBEMAR", "de pedir")
        assert Cartas.de({1: sola}, {}).que_abren({}) == frozenset()
        # Y la misma carta repetida -- la misma fecha y el mismo asunto -- es copia, no abre.
        assert Cartas.de({1: PETICION_DE_JULIO, 2: PETICION_DE_JULIO}, {}).que_abren({}) == {1}

    def test_la_validacion_del_re_a_mano(self):
        from resolutions.domain.sello import validar_el_re_a_mano

        assert validar_el_re_a_mano("RE2311202302952", date(2023, 8, 28)) == ("RE2311202302952", "")
        assert validar_el_re_a_mano("RE2371202302499", date(2023, 7, 19))[0] == "RE2311202302499"
        assert validar_el_re_a_mano("RE2311202202952", date(2023, 8, 28))[0] is None
        # Una oficina a una cifra de dos que radican (2310 y 2311 desde 2312): no se elige.
        assert validar_el_re_a_mano("RE2312202302952", date(2023, 8, 28))[0] is None
        # Lejos de todas: tampoco. Salvo que la caja la traiga impresa.
        assert validar_el_re_a_mano("RE5555202302952", None)[0] is None
        assert validar_el_re_a_mano("RE5555202302952", None, {"5555"})[0] == "RE5555202302952"
        assert validar_el_re_a_mano("RE231120230295", None)[0] is None


class TestElSelloAlPie:
    """1005965 p2: el sello de tinta clara junto a la firma, que la capa no dejó ver."""

    class _Fuente:
        def render(self, pagina, banda, dpi, formato="png"):
            import struct

            # Una cabecera PNG de 1000 x 1000 basta para el recorte.
            return b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 1000, 1000) + b"\x00" * 8

    class _Realzado:
        def __init__(self, palabras):
            self._palabras = palabras

        def palabras(self, imagen):
            return self._palabras

    class _Pago:
        def __init__(self, texto):
            self.texto = texto
            self.leidas = 0

        def read(self, imagen):
            self.leidas += 1
            return type("Lectura", (), {"text": self.texto})()

    FIRMA = "en constancia firma\nNIXON FERNEY ARIZA MOYA\nC.C. N° 7.925.433"
    SELLO = [("OFICINA", 300, 500, 100, 20), ("ACEPTACIÓN", 300, 540, 120, 20), ("Grupo-epm", 450, 540, 90, 20)]

    def test_lo_halla_con_la_ia_lee_su_re_y_no_abre_nada(self):
        from resolutions.application.sellos import sellos_al_pie

        pago = self._Pago("OFICINA SANTA ROSA DEL SUR\nFECHA DE RECIBIDO 28-08-23 11:22 am\nRE2311202302952")
        hallados = sellos_al_pie(
            self._Fuente(), {1: "hoja del cuerpo de la carta", 2: self.FIRMA, 3: self.FIRMA}, {3},
            lector_realzado=self._Realzado(self.SELLO), de_pago=pago,
        )
        # Sólo la hoja de firma sin sello: la 1 no firma y la 3 ya traía el suyo.
        assert list(hallados) == [2] and pago.leidas == 1
        assert (hallados[2].clase, hallados[2].radicado, hallados[2].fecha) == ("tinta", "RE2311202302952", date(2023, 8, 28))

    def test_sin_dos_senales_no_hay_sello_y_sin_ia_no_hay_re(self):
        from resolutions.application.sellos import sellos_al_pie

        una_sola = sellos_al_pie(
            self._Fuente(), {2: self.FIRMA}, set(), lector_realzado=self._Realzado([("OFICINA", 1, 1, 1, 1)])
        )
        assert una_sola == {}
        sin_ia = sellos_al_pie(self._Fuente(), {2: self.FIRMA}, set(), lector_realzado=self._Realzado(self.SELLO))
        assert sin_ia[2].radicado is None


def test_la_fila_del_indice_lleva_el_re_de_su_archivo():
    from resolutions.api.worker.planillas import _nombre_de_la_fila

    item = {"type": "DERECHO DE PETICION", "file_name": f"UPD1/01_DERECHO-DE-PETICION-{RE}.pdf"}
    assert _nombre_de_la_fila(item, {}) == f"DERECHO DE PETICION-{RE}"
    assert _nombre_de_la_fila({"type": "DERECHO DE PETICION", "file_name": "01_DERECHO-DE-PETICION.pdf"}, {}) == (
        "DERECHO DE PETICION"
    )


def _el_script():
    ruta = Path(__file__).resolve().parents[2] / "scripts" / "renombrar_reclamaciones.py"
    spec = importlib.util.spec_from_file_location("renombrar_reclamaciones", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class TestElIndiceDeLaCaja:
    openpyxl = pytest.importorskip("openpyxl")

    @staticmethod
    def _report() -> dict:
        def item(numero: int, nombre: str, tipo: str, fecha: str | None) -> dict:
            return {
                "file_name": f"UPD1/{nombre}",
                "code": f"{numero:02d}",
                "type": tipo,
                "fecha": fecha,
                "page_count": 1,
                "page_numbers": [numero],
            }

        # La caja 7285349 del pantallazo del operador, como sale del bot.
        return {
            "agrupar": "tramite",
            "inventory": {
                "items": [
                    item(1, f"01_CONSTANCIA-DEL-CONTENIDO-DE-LA-RECLAMACION-{RE}.pdf",
                         "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION", "2024-02-20"),
                    item(2, "02_NOTIFICACION-PERSONAL-RECLAMOS.pdf", "NOTIFICACION PERSONAL RECLAMOS", "2024-01-31"),
                    item(3, "03_RECLAMO.pdf", "RECLAMO", "2024-01-31"),
                    item(4, "04_PAGARE.pdf", "PAGARE", None),
                ]
            },
            "piezas": [],
        }

    def _escribir(self, carpeta: Path) -> Path:
        from resolutions.adapters.indice_electronico import NOMBRE_DEL_INDICE
        from resolutions.api.worker.planillas import _escribir_indice

        payload = {
            "operator": "SIAR",
            "destination": str(carpeta.parent),
            "source": r"C:\FUENTE\MAGANGUE\7285349\UPD1.pdf",
        }
        _escribir_indice(self._report(), carpeta, payload)
        return carpeta / NOMBRE_DEL_INDICE

    def test_por_fecha_con_el_re_y_el_expediente_igual_al_nic(self, tmp_path):
        hoja = self.openpyxl.load_workbook(self._escribir(tmp_path / "7285349")).active
        assert hoja["B3"].value == hoja["B4"].value == 7285349
        filas = [tuple(hoja.cell(fila, c).value for c in (1, 2, 4)) for fila in range(8, 12)]
        assert filas == [
            ("NOTIFICACION PERSONAL RECLAMOS", "31/01/2024", 1),
            ("RECLAMO", "31/01/2024", 2),
            (f"CONSTANCIA DEL CONTENIDO DE LA RECLAMACION-{RE}", "20/02/2024", 3),
            ("PAGARE", "S.F.", 4),
        ]

    def test_el_script_ya_no_encuentra_nada_que_cambiar(self, tmp_path):
        script = _el_script()
        raiz = tmp_path / "MAGANGUE PROCESADO"
        caja = raiz / "7285349"
        self._escribir(caja)
        (caja / f"01_CONSTANCIA-DEL-CONTENIDO-DE-LA-RECLAMACION-{RE}.pdf").write_bytes(b"%PDF-1.4")
        respaldo = tmp_path / "respaldo"

        indice = script.paso_indice(str(caja), str(raiz), str(respaldo), False)
        assert indice["estado"] == "ya estaba bien"
        filas = script.paso_re(str(caja), str(raiz), str(raiz), str(respaldo), False, None, "eng")
        assert [(f["archivo_antes"], f["estado"]) for f in filas] == [
            (f"01_CONSTANCIA-DEL-CONTENIDO-DE-LA-RECLAMACION-{RE}.pdf", "ya tenía RE")
        ]
