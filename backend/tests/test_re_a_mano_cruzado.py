"""El RE que el bot no sacaba en la prueba piloto de Magangué (2026-11-20).

- **El sello a mano que todos leen igual de mal** (1000690, UPD2437824 pág. 3):
  doce lecturas del sello -- OCR de pago y visión -- leen «RE23D20210565», el
  «10» hecho una «D» y el «7» perdido; la respuesta de la empresa del
  18-06-2021 dice impreso «Reclamación No. RE2310202105657». El operador:
  «ponerlo si el agente lo cruza» con el único RE impreso de su trámite.
- **La publicación y la notificación por aviso** llevan el RE que citan
  («Radicado número: RE…»), como la notificación personal.
- **La constancia que el escáner deja en «cgnstancia»** y «N^POR» (4132560,
  UPD2427617 pág. 2) no se reconocía y salía pegada a la autorización de delante.

Los nombres y los NIC de las hojas son inventados.
"""

from __future__ import annotations

from datetime import date

from resolutions.domain.asunto_del_documento import (
    CONSTANCIA_DE_RECLAMACION,
    NOTIFICACION_POR_AVISO,
    PUBLICACION_DEL_AVISO,
    formulario_que_abre,
)
from resolutions.domain.evidencia import (
    Estado,
    EvidenciaDeRE,
    decidir_el_re,
    distancia_de_la_mano,
    lo_leido_tras_el_re,
    re_impreso_que_casa,
)
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.nombre_oficial import lleva_re_en_el_nombre
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.sello import Sello

RE = "RE2310202105657"
OTRO = "RE2310202103443"
SELLO = date(2021, 6, 16)
#: Lo que leyeron el OCR de pago y la visión en el sello de 1000690 pág. 3.
LECTURAS = (
    ("ocr de pago", "No DE RADICACION: 202160064741\nFUNCIONARIO RECEPTOR: RE23D20210565 / NIC: 100 00 01"),
    ("visión", "FECHA DE RECIBIDO: 16-06-2021\nNo. DE FOLIOS: 1\nRE: RE23020210565"),
    ("ocr de pago", "FUNCIONARIO RECEPTOR: RE23D20210565P"),
    ("visión", "RE: RE23D20210565"),
)
IMPRESOS = {RE: [(8, date(2021, 6, 18))], OTRO: [(1, date(2021, 4, 12)), (5, date(2021, 6, 3))]}


class TestLoLeidoALaMano:
    def test_lo_que_sigue_al_re_con_las_letras_de_la_mano(self):
        assert lo_leido_tras_el_re(LECTURAS[0][1]) == ["23D20210565"]
        assert lo_leido_tras_el_re("RE 2310 2021 05657") == ["2310202105657"]

    def test_las_palabras_que_empiezan_por_re_no_son_un_re(self):
        assert lo_leido_tras_el_re("RECIBIDO NO IMPLICA ACEPTACION DIRECCION RELIGIOSO") == []

    def test_la_d_por_10_y_la_cifra_perdida_cuestan_poco(self):
        assert distancia_de_la_mano("23D20210565", RE[2:]) == 1.5
        assert distancia_de_la_mano("23D20210565P", RE[2:]) == 1.0
        assert distancia_de_la_mano("23D20210565", OTRO[2:]) > 4


class TestElCruce:
    def test_casa_con_el_unico_impreso_de_su_tramite(self):
        cruce = re_impreso_que_casa(LECTURAS, IMPRESOS, fecha_del_sello=SELLO)
        assert cruce.valor == RE and cruce.se_cree
        assert "RE23D20210565 (×2)" in cruce.porque and "pág. 8 del 18-06-2021" in cruce.porque

    def test_dos_impresos_parecidos_no_se_cree(self):
        impresos = {**IMPRESOS, "RE2310202105667": [(9, date(2021, 6, 20))]}
        cruce = re_impreso_que_casa(LECTURAS, impresos, fecha_del_sello=SELLO)
        assert cruce is None or not cruce.se_cree

    def test_el_impreso_anterior_al_sello_no_es_de_su_tramite(self):
        cruce = re_impreso_que_casa(LECTURAS, {RE: [(8, date(2021, 5, 1))]}, fecha_del_sello=SELLO)
        assert not cruce.se_cree and "posterior" in cruce.porque

    def test_lo_que_el_agente_no_valida_no_se_cree(self):
        cruce = re_impreso_que_casa(LECTURAS, IMPRESOS, fecha_del_sello=SELLO, valido=lambda _v: "año imposible")
        assert not cruce.se_cree

    def test_una_sola_lectura_no_basta(self):
        cruce = re_impreso_que_casa(LECTURAS[:1], IMPRESOS, fecha_del_sello=SELLO)
        assert not cruce.se_cree and "una sola lectura" in cruce.porque

    def test_la_lectura_que_trae_entero_otro_re_lo_contradice(self):
        lecturas = (*LECTURAS, ("visión", "RE: RE2310202105658"))
        assert not re_impreso_que_casa(lecturas, IMPRESOS, fecha_del_sello=SELLO).se_cree

    def test_sin_nada_parecido_no_hay_cruce(self):
        assert re_impreso_que_casa(LECTURAS, {OTRO: [(1, date(2021, 7, 1))]}, fecha_del_sello=SELLO) is None


class TestLaEvidencia:
    def test_con_su_cruce_se_cree_sin_el_queda_como_hoy(self):
        cruzada = EvidenciaDeRE(3, "sello de tinta cruzado con lo impreso", RE, LECTURAS, cruce="casa con lo impreso")
        hallazgo = decidir_el_re([cruzada])
        assert hallazgo.estado is Estado.ENCONTRADO and hallazgo.valor == RE
        assert hallazgo.metodo == "sello de tinta cruzado con lo impreso"
        sin_cruce = EvidenciaDeRE(3, "sello de tinta", RE, LECTURAS)
        assert decidir_el_re([sin_cruce]).estado is Estado.REQUIERE_VALIDACION


def _grupos(*grupos: tuple[str, list[int], str]) -> GroupingResult:
    return GroupingResult(
        groups=[
            PageGroup(code=ResolutionCode(value=valor, raw=valor), page_numbers=paginas, kind=kind)
            for valor, paginas, kind in grupos
        ],
        quarantine=[],
        repairs=[],
    )


def _poner(grupos, *, textos, sellos=None, rechazados=None):
    from resolutions.api.worker.correspondencia import _poner_el_re_en_el_nombre

    return _poner_el_re_en_el_nombre(
        grupos, {}, textos=textos, sellos=sellos or {}, sin_re=set(), abren=set(), rechazados=rechazados
    )


RESPUESTA = (
    "Consecutivo No. A202170145936\nMagangué, 18 de junio de 2021\nSeñor\nPEDRO PEREZ\n"
    f"ASUNTO: Reclamación No. {RE}\nEn atención a su petición, le informamos"
)
PUBLICACION = (
    "Consecutivo No. PA 202170170241\nPUBLICACIÓN DEL AVISO\nTeniendo en cuenta que el usuario PEDRO PEREZ "
    f"reportó como dirección de notificación para la respuesta a la petición radicada bajo el número {OTRO}\n"
    f"Cartagena, 16-06-2021\nAsunto: Notificación por aviso\nNIC: 1000001\nRadicado número: {OTRO}\n"
)


class TestEnElWorker:
    def test_el_derecho_de_peticion_toma_el_re_cruzado(self):
        grupos, _, hallados = _poner(
            _grupos(("01", [3], "DERECHO DE PETICION"), ("02", [8], "RESPUESTA A LA RECLAMACION")),
            textos={3: "Señores AFINIA\nDerecho de petición", 8: RESPUESTA},
            sellos={3: Sello("tinta", None, SELLO, lecturas=LECTURAS)},
        )
        assert grupos.groups[0].code.value == f"01 {RE}"
        assert "cruzado con lo impreso" in hallados["3"]

    def test_con_solo_ocr_no_hay_cruce(self):
        rechazados: list = []
        solo_tesseract = tuple(("tesseract", texto) for _, texto in LECTURAS)
        grupos, _, _ = _poner(
            _grupos(("01", [3], "DERECHO DE PETICION"), ("02", [8], "RESPUESTA A LA RECLAMACION")),
            textos={3: "Señores AFINIA", 8: RESPUESTA},
            sellos={3: Sello("tinta", None, SELLO, lecturas=solo_tesseract)},
            rechazados=rechazados,
        )
        assert grupos.groups[0].code.value == "01"

    def test_la_publicacion_del_aviso_lleva_el_re_que_cita(self):
        assert lleva_re_en_el_nombre(PUBLICACION_DEL_AVISO) and lleva_re_en_el_nombre(NOTIFICACION_POR_AVISO)
        grupos, _, _ = _poner(_grupos(("06", [7], PUBLICACION_DEL_AVISO)), textos={7: PUBLICACION})
        assert grupos.groups[0].code.value == f"06 {OTRO}"


class TestLaConstanciaQueElEscanerRompe:
    def test_cgnstancia_y_n_por_siguen_siendo_la_constancia(self):
        texto = (
            "PARA LA EMPRESA\nRecibí cgnstancia del contenido de la reclamación presentada ante CARIBEMAR\n"
            "N^POR: RE2310202215824\nFECHA: 02/12/2022\nCODIGO (NIC):1000001\nCAUSA:\nCambio de datos básicos"
        )
        assert formulario_que_abre(texto) == CONSTANCIA_DE_RECLAMACION

    def test_la_autorizacion_del_aseo_se_llama_reclamacion_sin_re(self):
        from resolutions.domain.asunto_del_documento import titulo_del_documento
        from resolutions.domain.nombre_oficial import (
            instrucciones_para_nombrar,
            nombre_oficial,
        )

        texto = (
            "ASEO SAS ESP\nAUT- 5073 -ASEO\nMagangue, 09 de diciembre del 2021\nCordial saludo,\n"
            "A Continuación relaciono usuario para aplicar descuento(s) o Notas Créditos.\n"
            "Esta autorización se otorga porque el usuario presentó una Reclamación"
        )
        nombre = nombre_oficial(titulo_del_documento(texto))
        assert nombre == "RECLAMACION" and not lleva_re_en_el_nombre(nombre)
        # La reclamación del usuario sigue siendo RECLAMO, y la IA no elige RECLAMACION.
        assert nombre_oficial("RECLAMACION") == "RECLAMO"
        assert "- RECLAMACION\n" not in instrucciones_para_nombrar()

    def test_la_autorizacion_de_delante_no_es_una_constancia(self):
        texto = "ASEO SAS ESP\nAUT- 5346 -ASEO\nMagangue, 17 de noviembre del 2022\nA continuación relaciono usuario"
        assert formulario_que_abre(texto) is None
