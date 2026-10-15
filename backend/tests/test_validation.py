"""Las comprobaciones que se hacen sobre lo leído, por tipo de documento.

La razón de que existan es que un dato mal leído no se distingue de uno bien
leído mirando el resultado: "5" donde el papel dice "543" y "ALANCETE" donde
dice "ALANDETE" salen del OCR con el mismo aspecto que un acierto. Lo que se
fija aquí es que cada contradicción interna del documento se convierta en un
hallazgo con su página, y que ninguna se corrija sola.
"""

from resolutions.domain.diploma import DiplomaRecord
from resolutions.domain.grouping import GroupingEngine
from resolutions.domain.page import PageClassification, Provenance
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.validation import (
    Severity,
    summarise,
    validate_diplomas,
    validate_resolutions,
)


def registro(pagina, **campos):
    base = {
        "folio": str(pagina),
        "registered_folio": str(pagina),
        "book": "8",
        "name": "GRADUANDO DE PRUEBA",
        "degree": "ESPECIALISTA EN ALGO",
        "graduation_date": "29/03/2012",
        "identity_number": "45519891",
    }
    base.update(campos)
    return DiplomaRecord(page_number=pagina, **base)


def campos(hallazgos):
    return {hallazgo.field for hallazgo in hallazgos}


class TestDiplomasSinProblemas:
    def test_un_libro_bien_leido_no_produce_hallazgos(self):
        libro = [registro(n) for n in range(1, 6)]
        assert validate_diplomas(libro) == []


class TestCamposQueFaltan:
    def test_cada_campo_ausente_se_señala_con_su_pagina(self):
        hallazgos = validate_diplomas([registro(1, name=None, graduation_date=None)])
        assert campos(hallazgos) == {"nombre", "fecha"}
        assert all(h.page_number == 1 for h in hallazgos)

    def test_los_avisos_que_dejo_el_lector_llegan_al_informe(self):
        """El lector ya detectó la contradicción al leer la página; no se pierde."""
        dudoso = registro(1, warnings=["el folio del encabezado no coincide con el del pie"])
        hallazgos = validate_diplomas([dudoso])
        assert any(h.field == "lectura" and h.severity is Severity.ERROR for h in hallazgos)

    def test_un_campo_ausente_es_un_aviso_y_no_un_error(self):
        """Una ausencia va al FUID como N/A; un error es algo que se leyó mal.

        Como error, en el libro 7 de 1982 la cola de revisión traía 398 páginas
        de 398, porque la fecha, el título y el libro están escritos a mano. Una
        cola donde está todo no señala nada.
        """
        hallazgos = validate_diplomas([registro(1, degree=None)])
        assert hallazgos and all(h.severity is Severity.WARNING for h in hallazgos)

    def test_la_vuelta_de_una_hoja_no_produce_hallazgos(self):
        """Sus datos son los de la cara que la abre; pedírselos a un reverso en
        blanco ponía cinco hallazgos por cada página par del libro.

        Cortando por folio, que es el criterio en que una cara de esquina limpia
        es la vuelta de la anterior. Cortando cara a cara no hay vueltas: cada
        página es un diploma y se le exige lo mismo que a las demás.
        """
        from resolutions.domain.diploma import CriterioDeCorte
        from resolutions.domain.folio_manuscrito import MarcaDeFolio

        cara = registro(1)
        vuelta = registro(
            2,
            folio=None,
            registered_folio=None,
            name=None,
            degree=None,
            graduation_date=None,
            book=None,
            folio_mark=MarcaDeFolio.AUSENTE,
        )
        hallazgos = validate_diplomas([cara, vuelta], CriterioDeCorte.FOLIO)
        assert [h.page_number for h in hallazgos] == []

    def test_cortando_cara_a_cara_la_esquina_limpia_tambien_es_un_diploma(self):
        """La misma vuelta, con el criterio en que no es una vuelta: se declara
        que queda sin cédula y sin nombre, como cualquier otra cara."""
        from resolutions.domain.diploma import CriterioDeCorte
        from resolutions.domain.folio_manuscrito import MarcaDeFolio

        cara = registro(1)
        vuelta = registro(
            2, name=None, identity_number=None, folio_mark=MarcaDeFolio.AUSENTE
        )
        hallazgos = validate_diplomas([cara, vuelta], CriterioDeCorte.PAGINA)
        assert [h.field for h in hallazgos if h.page_number == 2 and h.field == "identidad"]


class TestCoherenciaDelLibro:
    def test_una_pagina_que_dice_otro_libro_se_señala(self):
        """Un empaste es un libro. Dos números distintos significan un mal leído."""
        libro = [registro(1), registro(2), registro(3, book="1")]
        hallazgos = [h for h in validate_diplomas(libro) if h.field == "libro"]
        assert len(hallazgos) == 1
        assert hallazgos[0].page_number == 3
        assert hallazgos[0].observed == "1"

    def test_no_se_queja_cuando_todo_el_libro_dice_lo_mismo(self):
        libro = [registro(n) for n in range(1, 4)]
        assert not [h for h in validate_diplomas(libro) if h.field == "libro"]

    def test_un_folio_repetido_se_señala_como_aviso(self):
        libro = [registro(1, folio="348", registered_folio="348"),
                 registro(2, folio="348", registered_folio="348")]
        hallazgos = [h for h in validate_diplomas(libro) if h.field == "folio"]
        assert hallazgos[0].severity is Severity.WARNING
        assert "348" in hallazgos[0].reason

    def test_un_hueco_en_la_numeracion_se_señala(self):
        libro = [registro(1, folio="10", registered_folio="10"),
                 registro(2, folio="14", registered_folio="14")]
        hallazgos = [h for h in validate_diplomas(libro) if "faltan" in h.reason]
        assert "faltan 3 folios entre el 10 y el 14" in hallazgos[0].reason

    def test_folios_consecutivos_no_dejan_hueco(self):
        libro = [registro(1, folio="10", registered_folio="10"),
                 registro(2, folio="11", registered_folio="11")]
        assert not [h for h in validate_diplomas(libro) if "faltan" in h.reason]

    def test_el_sello_anulado_se_declara(self):
        hallazgos = validate_diplomas([registro(1, annulled=True)])
        assert any(h.field == "anulado" for h in hallazgos)


class TestNumeroDeIdentificacion:
    def test_una_cedula_de_forma_imposible_se_señala_como_aviso(self):
        """Cuatro cifras es un folio que se coló, no un documento de identidad.

        Aviso y no error: ese número no se sostiene, así que ni nombra el
        archivo ni va al FUID. Como error mandaba a revisión hojas que habían
        salido con su nombre por un número que ya se había descartado.
        """
        hallazgos = validate_diplomas([registro(1, identity_number="348")])
        documento = [h for h in hallazgos if h.field == "documento"]
        assert documento and documento[0].severity is Severity.WARNING

    def test_una_cedula_normal_pasa(self):
        assert not [
            h for h in validate_diplomas([registro(1, identity_number="45519891")])
            if h.field == "documento"
        ]

    def test_una_cedula_de_extranjeria_corta_pasa(self):
        assert not [
            h for h in validate_diplomas([registro(1, identity_number="393598")])
            if h.field == "documento"
        ]


class TestResoluciones:
    def clasificar(self, pares):
        return [
            PageClassification(
                page_number=n,
                code=ResolutionCode.parse(codigo) if codigo else None,
                provenance=Provenance.TEXT_LAYER,
                title="Un asunto cualquiera" if codigo else None,
            )
            for n, codigo in pares
        ]

    def test_una_lectura_limpia_no_produce_hallazgos(self):
        paginas = self.clasificar([(1, "00412"), (2, None), (3, "00413")])
        resultado = GroupingEngine().group(paginas)
        assert validate_resolutions(paginas, resultado) == []

    def test_una_pagina_sin_dueño_es_un_error(self):
        paginas = self.clasificar([(1, None), (2, "00412")])
        resultado = GroupingEngine().group(paginas)
        hallazgos = validate_resolutions(paginas, resultado)
        assert hallazgos[0].page_number == 1
        assert hallazgos[0].severity is Severity.ERROR

    def test_una_pagina_con_codigos_en_conflicto_es_un_error(self):
        paginas = [
            PageClassification(
                page_number=1,
                code=ResolutionCode.parse("00412"),
                provenance=Provenance.TEXT_LAYER,
                ambiguous=True,
                title="Un asunto",
            )
        ]
        resultado = GroupingEngine().group(paginas)
        hallazgos = [h for h in validate_resolutions(paginas, resultado) if h.field == "codigo"]
        assert hallazgos and hallazgos[0].severity is Severity.ERROR

    def test_una_resolucion_sin_titulo_se_avisa(self):
        paginas = [
            PageClassification(
                page_number=1,
                code=ResolutionCode.parse("00412"),
                provenance=Provenance.TEXT_LAYER,
            )
        ]
        resultado = GroupingEngine().group(paginas)
        hallazgos = [h for h in validate_resolutions(paginas, resultado) if h.field == "titulo"]
        assert hallazgos and hallazgos[0].severity is Severity.WARNING

    def test_unas_paginas_no_consecutivas_se_avisan(self):
        """Un número que reaparece más adelante casi siempre es un mal leído.

        Los códigos van lejos unos de otros a propósito: a dos ediciones de
        distancia el sistema los absorbe como ruido de OCR, y entonces las
        páginas sí quedan consecutivas y no hay nada que avisar.
        """
        paginas = self.clasificar([(1, "00412"), (2, "00999"), (3, "00412")])
        resultado = GroupingEngine().group(paginas)
        hallazgos = [h for h in validate_resolutions(paginas, resultado) if "consecutivas" in h.reason]
        assert hallazgos

    def test_una_correccion_aplicada_se_declara(self):
        """Una corrección silenciosa es indistinguible de un error."""
        paginas = self.clasificar([(1, "00412"), (2, "00413"), (3, "00412")])
        # 00413 entre dos 00412 y a una edición de distancia: se absorbe.
        resultado = GroupingEngine().group(paginas)
        assert resultado.repairs
        hallazgos = validate_resolutions(paginas, resultado)
        assert any("se leyó" in h.reason for h in hallazgos)


class TestResumen:
    def test_cuenta_errores_y_avisos_por_separado(self):
        hallazgos = validate_diplomas([registro(1, name=None, annulled=True)])
        resumen = summarise(hallazgos)
        assert resumen["total"] == len(hallazgos)
        assert resumen["errores"] + resumen["avisos"] == resumen["total"]

    def test_lista_las_paginas_afectadas(self):
        hallazgos = validate_diplomas([registro(1, degree=None), registro(2, name=None)])
        assert summarise(hallazgos)["paginas"] == [1, 2]

    def test_sin_hallazgos_no_hay_nada_que_resumir(self):
        assert summarise([])["total"] == 0


class TestSoloLosErroresRealesVanARevision:
    """«Necesito que ninguna página pase a revisión, y la que sí pase que sea en
    realidad por algún error verdaderamente real», dijo el operador con el
    libro 7 delante: cincuenta caras en la cola por una cédula a la que el OCR
    le comió dígitos, cuando el archivo había salido con su nombre."""

    def test_una_cedula_que_no_se_sostiene_es_un_aviso_y_no_un_error(self):
        from resolutions.domain.diploma import extract_diploma_warnings

        leido = extract_diploma_warnings(registro(1, identity_number="45425"))
        assert leido.warnings, "el aviso existe..."
        hallazgos = [h for h in validate_diplomas([leido]) if h.field == "lectura"]
        assert hallazgos and all(h.severity is Severity.WARNING for h in hallazgos)

    def test_un_nombre_con_acento_grave_no_es_un_nombre_danado(self):
        assert registro(1, name="BEATRIZ EUGÈNE VERGARA").nombre_creible

    def test_un_nombre_con_un_digito_si(self):
        assert not registro(1, name="WILHELM S. AUGUST 15").nombre_creible
