"""Los casos de 7975593 (UPD2460819) que el operador pidió cubrir el 2026-11-12: «analiza muy bien la carpeta y cubre todos los escenarios».

Cada prueba lleva el texto real que dejó la capa o la IA en esa hoja.
"""

from __future__ import annotations

from datetime import date

from resolutions.api.worker.correspondencia import _copias_de_formularios
from resolutions.application.sellos import hojas_que_pueden_llevar_sello
from resolutions.domain.asunto_del_documento import (
    NOTIFICACION_PERSONAL,
    formulario_que_abre,
)
from resolutions.domain.fecha_por_estructura import fecha_por_estructura
from resolutions.domain.sello import radicado_con_una_cifra_de_mas

CONOCIDOS = {"RE2310202104662", "RE2310202104663", "RE2310202105403"}

CARTA_DEL_52 = (
    "OFICINA MAGANGUE BOLIVAR SUR RECIBIDO NO IMPLICA ACEPTACIÓN\n"
    "Magangue - Bolívar, Mayo 20 de 2021.\nSEÑORES:\nCARIBE MAR DE LA COSTA S.A.S E.S.P.\n"
    "REFERENCIA: RECURSO DE REPOSICION EN CONTRA DE LA DECISION\n"
)
CARTA_DEL_136 = (
    "C/>Pil56W»R DE Li CDSTA S A S E S DIR. SOTIFICACliv _ FUSCIO‘<ASIOn:C;”:R\n"
    "Magangue - Bolívar, Mayo 28 de 2021.\nSEÑORES: CARIBE MAR DE LA COSTA S.A.S E.S.P.\n"
    "REFERENCIA: RECURSO DE REPOSICION Y EN SUBSIDIO APELACION EN CONTRA DE LA FACTURA\n"
)
NOTIFICACION = (
    "Grupo-epm\nNOTIFICACIÓN PERSONAL DE ACEPTACIÓN DEL DESISTIMIENTO\n"
    "Ciudad y fecha: Magangué 29 de agosto de 2022\n"
    "Número del radicado del caso; RE2310202104662. RE2310202105403. RE2310202106112\n"
    "Dirección: CL 6 CR 3 30 APTO 1 B SUR. Se notifica personalmente la aceptación del desistimiento.\n"
)
CORREO = (
    "De: Coordinador De Lecturas Mangangué <piedad.cordero@ecasas.com.co>\n"
    "Enviado: viernes, 9 de julio de 202111:01 a. m.\nPara: Aldemar Acuna Glenn <alacunag@afinia.com.co>\n"
)


class TestLasFechas:
    def test_el_sello_anterior_a_la_carta_no_se_cree(self):
        """Hoja 52: el sello dice «20-05-2020» y la carta «Mayo 20 de 2021»."""
        hallada = fecha_por_estructura([52], {52: CARTA_DEL_52}, sellos={52: date(2020, 5, 20)})
        assert hallada.fecha == date(2021, 5, 20)

    def test_el_sello_posterior_a_la_carta_manda(self):
        hallada = fecha_por_estructura([136], {136: CARTA_DEL_136}, sellos={136: date(2021, 5, 31)})
        assert hallada.fecha == date(2021, 5, 31)

    def test_la_ciudad_sin_coma_antes_de_la_fecha(self):
        assert fecha_por_estructura([306], {306: NOTIFICACION}).fecha == date(2022, 8, 29)

    def test_el_correo_con_el_anio_pegado_a_la_hora(self):
        assert fecha_por_estructura([274], {274: CORREO}).fecha == date(2021, 7, 9)


class TestElSello:
    def test_la_carta_que_reclama_contra_la_factura_tambien_se_mira(self):
        assert hojas_que_pueden_llevar_sello({136: CARTA_DEL_136}) == [136]

    def test_el_re_a_mano_con_una_cifra_de_mas(self):
        assert radicado_con_una_cifra_de_mas("No DE RADICACION: RE 23102021094662", CONOCIDOS, 2021) == "RE2310202104662"
        assert radicado_con_una_cifra_de_mas("No DE RADIACION LE 23102021041663", CONOCIDOS, 2021) == "RE2310202104663"

    def test_sin_uno_solo_posible_no_se_adivina(self):
        assert radicado_con_una_cifra_de_mas("No DE RADICACION: RE 23102021094662", set(), 2021) is None


class TestLasNotificaciones:
    def test_la_de_aceptacion_del_desistimiento_va_sola(self):
        assert formulario_que_abre(NOTIFICACION) == NOTIFICACION_PERSONAL

    def test_su_copia_dentro_del_desistimiento_no_abre(self):
        copia = NOTIFICACION.replace("Grupo-epm", "Grupo-epn^")
        formularios = {306: (NOTIFICACION_PERSONAL, None), 309: (NOTIFICACION_PERSONAL, None)}
        assert _copias_de_formularios(formularios, {306: NOTIFICACION, 309: copia}) == [309]

    def test_dos_constancias_parecidas_no_son_copias(self):
        formularios = {272: ("CONSTANCIA DE RECLAMACION", None), 297: ("CONSTANCIA DE RECLAMACION", None)}
        texto = "PARA LA EMPRESA Recibí constancia del contenido de la reclamación presentada ante CARIBEMAR"
        assert _copias_de_formularios(formularios, {272: texto, 297: texto}) == []


# -- UPD3126960 (2026-11-13): los RE a mano contra lo impreso, y el recurso de B44 ---------

from resolutions.api.worker.correspondencia import _con_lo_impreso  # noqa: E402
from resolutions.application.cartas import radicada_por_sus_folios  # noqa: E402
from resolutions.domain.sello import (  # noqa: E402
    Sello,
    el_de_su_tramite,
    el_impreso_a_una_cifra,
    radicado_escrito,
    radicados_impresos,
)


class TestLosRESeparadosYCorregidos:
    def test_el_punto_y_el_guion_separan_los_grupos(self):
        """B44 «No DE FOLIOS: RE23102024.03978» y B9 «Re 231020232-1059», como los transcribió la IA."""
        assert radicado_escrito("No DE FOLIOS: RE23102024.03978\nDIR. NOTIFICACIÓN: 10 Folios", 2024) == "RE2310202403978"
        assert radicado_escrito("Re 231020232-1059\nCARIBEMAR DE LA COSTA", 2023) == "RE2310202321059"

    def test_lo_impreso_corrige_la_cifra_mal_leida_a_mano(self):
        impresos = radicados_impresos("ASUNTO: … ES RECLAMACION No- 2310202403978.") | radicados_impresos(
            "RECLAMACION RE 2310202321859 DEL 16/11/2023"
        )
        assert impresos == {"RE2310202403978", "RE2310202321859"}
        assert el_impreso_a_una_cifra("RE2310202403578", impresos) == "RE2310202403978"
        assert el_impreso_a_una_cifra("RE2310202321059", impresos) == "RE2310202321859"
        # Igual a uno impreso, o lejos de todos: no se toca.
        assert el_impreso_a_una_cifra("RE2310202403978", impresos) is None
        assert el_impreso_a_una_cifra("RE2310202403955", impresos) is None

    def test_a_una_cifra_de_dos_impresos_no_se_adivina(self):
        assert el_impreso_a_una_cifra("RE2310202403578", {"RE2310202403978", "RE2310202403570"}) is None

    def test_solo_el_sello_de_tinta_se_corrige_y_queda_dicho(self):
        sellos = {33: Sello("tinta", "RE2310202403578", date(2024, 2, 23), 2), 1: Sello("etiqueta", "RE2310202403570")}
        textos = {44: "ES RECLAMACION No- 2310202403978", 1: ""}
        corregidos_sellos, _al_pie, notas = _con_lo_impreso(sellos, {}, textos)
        assert corregidos_sellos[33].radicado == "RE2310202403978"
        assert corregidos_sellos[1].radicado == "RE2310202403570"
        assert "RE2310202403578" in notas[33]

    def test_el_de_su_tramite_a_una_cifra(self):
        assert el_de_su_tramite("RE2310202321059", "RE2310202321859") == "RE2310202321859"
        assert el_de_su_tramite("RE2310202403955", "RE2310202321859") is None


class TestElRecursoQueRepiteLaCarta:
    def test_su_sello_con_folios_que_cierran_el_pdf_lo_hace_radicado(self):
        """B44: el recurso repite la carta de B40 y su sello dice 10 folios: 44 + 10 - 1 = 53, la última hoja."""
        sellos = {40: Sello("tinta", None, date(2024, 3, 22), 5), 44: Sello("tinta", "RE2310202403978", date(2024, 3, 22), 10)}
        assert radicada_por_sus_folios(44, sellos, 53)

    def test_o_que_cierran_justo_antes_del_sello_siguiente(self):
        sellos = {44: Sello("tinta", None, None, 10), 54: Sello("tinta", None, None, 3)}
        assert radicada_por_sus_folios(44, sellos, 80)

    def test_la_copia_aportada_trae_folios_que_no_cuadran(self):
        sellos = {44: Sello("tinta", None, None, 7)}
        assert not radicada_por_sus_folios(44, sellos, 53)
        assert not radicada_por_sus_folios(44, {44: Sello("tinta", None, None, 1)}, 44)
        assert not radicada_por_sus_folios(44, {}, 53)


# -- UPD2460819 (2026-11-13): el RE a mano ilegible, el sello sin RE y la fecha errada ------

from resolutions.api.worker.correspondencia import _poner_el_re_en_el_nombre  # noqa: E402
from resolutions.domain.grouping import GroupingResult, PageGroup  # noqa: E402
from resolutions.domain.resolution_code import ResolutionCode  # noqa: E402
from resolutions.domain.sello import el_conocido_por_la_lectura  # noqa: E402

#: Los RE de la caja, impresos o leídos en sus sellos: …05408 no está; su
#: errata RE8310… sí, impresa en las cartas del cliente.
DE_LA_CAJA = [
    "RE2310202103442", "RE2310202104662", "RE2310202104663", "RE2310202105402", "RE2310202105403",
    "RE2310202106812", "RE8310202105408",
]


def _grupos(*grupos):
    return GroupingResult(
        groups=[
            PageGroup(code=ResolutionCode(value=valor, raw=valor.split()[-1]), page_numbers=paginas, kind=kind)
            for valor, paginas, kind in grupos
        ],
        quarantine=[],
        repairs=[],
    )


class TestElREIlegibleCasadoConLoImpreso:
    def test_contra_lo_que_imprime_el_escrito_en_sus_hojas(self):
        """Hojas 52 y 95: «REB3102021034V2» y «RE 23/02021/03442»; el recurso imprime RE2310202103442."""
        suyos = {"RE2310202103442", "RE2310202104663"}
        assert el_conocido_por_la_lectura("FUNCIONARIO RECEPTOR: REB3102021034V2.", suyos) == "RE2310202103442"
        assert el_conocido_por_la_lectura("RE 23/02021/03442\n2021 600 53 251", suyos) == "RE2310202103442"

    def test_contra_toda_la_caja_hay_duda_y_no_se_adivina(self):
        """Contra toda la caja, la hoja 52 queda a dos del suyo y a tres del …05402."""
        assert el_conocido_por_la_lectura("FUNCIONARIO RECEPTOR: REB3102021034V2.", DE_LA_CAJA) is None

    def test_la_errata_del_cliente_no_gana_por_parecerse(self):
        """Hoja 176: «KEP310202105408» queda a uno de la errata RE8310… y a dos de otros dos."""
        assert el_conocido_por_la_lectura("FUNCIONARIO RECEPTOR: KEP310202105408", DE_LA_CAJA) is None

    def test_las_palabras_del_sello_no_son_un_re(self):
        assert el_conocido_por_la_lectura("RECIBIDO NO IMPLICA ACEPTACION\nREFERENCIA: RECURSO", DE_LA_CAJA) is None

    def test_la_lectura_corta_no_revienta(self):
        """Una lectura con huecos -- «RE 2 3 1 0 2 0» -- queda corta sin los blancos: no se casa ni tumba la caja."""
        assert el_conocido_por_la_lectura("RE 2 3 1 0 2 0 2 1 0 3", DE_LA_CAJA) is None


class TestElNombreConLoQueDiceElSello:
    def test_el_sello_sin_re_no_toma_el_del_tramite(self):
        """Hoja 12: el sello trae fecha, folios y el radicado «20216003 6696», y ningún RE."""
        grupos, _, hallados = _poner_el_re_en_el_nombre(
            _grupos(("02 RE2310202104662", [12, 13], "RECLAMO")),
            {},
            textos={12: "", 13: ""},
            sellos={12: Sello("tinta", None, date(2021, 4, 12), 10)},
            sin_re=set(),
            abren={12},
            sellos_sin_re={12},
        )
        assert grupos.groups[0].code.value == "02"
        assert hallados["12"].startswith("sin RE")

    def test_la_fecha_errada_del_sello_no_tumba_el_re_impreso(self):
        """Hoja 52: «20-05-2020» en el sello de un recurso de 2021 con su RE impreso en sus hojas."""
        grupos, _, hallados = _poner_el_re_en_el_nombre(
            _grupos(("05", [52, 61], "RECURSO DE REPOSICION")),
            {},
            textos={52: "", 61: "SE RADICO CON RE2310202103442"},
            sellos={52: Sello("tinta", "RE2310202103442", date(2020, 5, 20), 44)},
            sin_re=set(),
            abren={52},
        )
        assert grupos.groups[0].code.value == "05 RE2310202103442"
        assert "impreso" in hallados["52"]

    def test_sin_imprimirlo_la_fecha_errada_si_lo_tumba(self):
        rechazados: list = []
        grupos, _, _ = _poner_el_re_en_el_nombre(
            _grupos(("05", [52], "RECURSO DE REPOSICION")),
            {},
            textos={52: ""},
            sellos={52: Sello("tinta", "RE2310202103442", date(2020, 5, 20), 44)},
            sin_re=set(),
            abren={52},
            rechazados=rechazados,
        )
        assert grupos.groups[0].code.value == "05"
        assert rechazados and "año" in rechazados[0]["reason"]


class TestElSelloSinRE:
    def test_el_radicado_en_su_renglon_dice_que_se_radico_sin_re(self):
        """Hoja 12: «No DE RADICACIÓN: 202160036696», leído entero y sin RE."""
        from resolutions.api.worker.correspondencia import (
            _RADICACION_SIN_RE,
            _plano_del_sello,
        )

        assert _RADICACION_SIN_RE.search(_plano_del_sello("FECHA DE RECIBIDO: 12/04/2021\nNo DE RADICACIÓN: 202160036696"))

    def test_con_los_campos_corridos_no(self):
        """Hoja 255: el RE a mano se perdió en la lectura; el radicado cayó en la casilla de los folios."""
        from resolutions.api.worker.correspondencia import (
            _RADICACION_SIN_RE,
            _plano_del_sello,
        )

        leido = "No DE RADICACIÓN: 2021002106\nNo DE FOLIOS: 2021600 95 115\nDIR. NOTIFICACIÓN: 1640405"
        assert not _RADICACION_SIN_RE.search(_plano_del_sello(leido))

    def test_un_re_a_mano_ilegible_en_otra_casilla_dice_que_lo_trae(self):
        """Hoja 176: «No DE RADICACIÓN: 202160061377» y, en la casilla del funcionario, «KEP310202105408»."""
        from resolutions.domain.sello import trae_un_re_a_mano

        assert trae_un_re_a_mano("No DE RADICACIÓN: 202160061377\nFUNCIONARIO RECEPTOR: KEP310202105408")
        assert not trae_un_re_a_mano("RECIBIDO NO IMPLICA ACEPTACIÓN\nRECLAMACION EN CONTRA DE LA FACTURA 01/03/2021")
