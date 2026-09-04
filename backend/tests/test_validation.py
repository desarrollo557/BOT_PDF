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

    def test_un_campo_ausente_es_un_error_y_no_un_aviso(self):
        hallazgos = validate_diplomas([registro(1, degree=None)])
        assert any(h.severity is Severity.ERROR for h in hallazgos)


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
    def test_una_cedula_de_forma_imposible_se_señala(self):
        """Cuatro cifras es un folio que se coló, no un documento de identidad."""
        hallazgos = validate_diplomas([registro(1, identity_number="348")])
        documento = [h for h in hallazgos if h.field == "documento"]
        assert documento and documento[0].severity is Severity.ERROR

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
