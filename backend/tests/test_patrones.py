"""El patrón de cada tipo de documento: núcleo, veto y nombre.

Con texto de mentira que imita lo que se midió en la carpeta de Odontología:
actas de consejo con anexos de Admisiones, actas de grado, y archivos que sólo
se reconocen por su nombre.
"""

from __future__ import annotations

from collections import Counter

from resolutions.domain.doctype import DocumentType as T
from resolutions.domain.doctype import classify_pages
from resolutions.domain.patrones import (
    paginas_con_nucleo,
    pista_del_nombre,
    reconocer,
    tipos_de_la_pagina,
)

ACTA_DE_CONSEJO = (
    "CONSEJO DE FACULTAD\nACTA No. 21\nFECHA: 10 DE DICIEMBRE DE 2013\nHORA: 8:00\n"
    "LUGAR: Decanatura\nASISTENTES: Dra. Luisa Arévalo\n"
)
SESION = "SESION EXTRAORDINARIA\nFECHA: JUEVES 16 DE AGOSTO DE 2012\nLUGAR: Decanatura\nORDEN DEL DIA"
FORMATO_DE_ADMISIONES = (
    "UNIVERSIDAD DE CARTAGENA\nCENTRO DE ADMISIONES REGISTRO Y CONTROL ACADEMICO\n"
    "FORMATO SOLICITUD INCLUSION Y/O CORRECCION DE NOTAS\nCOD ESTUDIANTE\nASIGNATURAS\n"
    "FIRMA ALUMNO\nPROMEDIO SEMESTRAL\n"
)
ACTA_DE_GRADO = (
    "ACTA DE GRADO N° 05\nSe llevó a cabo ceremonia solemne de graduación, en la cual se "
    "otorga el título de Odontólogo a JUAN PEREZ, portador de la cédula 1.047.382, quien "
    "prestó el juramento de rigor.\n"
)


class TestElNucleoDeCadaPagina:
    def test_el_encabezado_de_sesion_es_nucleo_del_acta_de_consejo(self):
        assert T.ACTA_CONSEJO in tipos_de_la_pagina(ACTA_DE_CONSEJO)

    def test_un_formato_de_admisiones_no_es_nucleo_de_matricula(self):
        # Trae palabras de matrícula, no su núcleo: es el anexo de un acta.
        assert T.MATRICULA not in tipos_de_la_pagina(FORMATO_DE_ADMISIONES)

    def test_un_acta_de_grado_no_cuenta_como_acta_de_consejo(self):
        assert tipos_de_la_pagina(ACTA_DE_GRADO) == {T.ACTA}


class TestReconocer:
    def test_el_veto_corrige_lo_que_puntuaron_los_anexos(self):
        # Un acta de consejo cuyos anexos son formatos de Admisiones: los
        # marcadores dicen matrícula; el núcleo, acta de consejo.
        paginas = [ACTA_DE_CONSEJO, SESION] + [FORMATO_DE_ADMISIONES] * 6
        veredicto = classify_pages(enumerate(paginas, start=1))

        resultado = reconocer(veredicto, paginas_con_nucleo(paginas))

        assert resultado.tipo is T.ACTA_CONSEJO
        assert resultado.por in ("veto", "nucleo", "marcadores")

    def test_si_los_marcadores_no_deciden_decide_el_nucleo(self):
        paginas = [ACTA_DE_GRADO, ACTA_DE_GRADO, "texto suelto"]
        veredicto = classify_pages([(1, "nada"), (2, "nada")])

        resultado = reconocer(veredicto, paginas_con_nucleo(paginas))

        assert (resultado.tipo, resultado.por) == (T.ACTA, "nucleo")

    def test_una_sola_pagina_de_nucleo_no_decide(self):
        veredicto = classify_pages([(1, "nada")])

        resultado = reconocer(veredicto, Counter({T.ACTA_CONSEJO: 1}))

        assert resultado.tipo is T.DESCONOCIDO

    def test_sin_contenido_queda_el_nombre_y_se_dice(self):
        veredicto = classify_pages([(1, "")])

        resultado = reconocer(veredicto, Counter(), "UPD3859802-ACTAS DE GRADO 1988-2012.pdf")

        assert (resultado.tipo, resultado.por) == (T.ACTA, "nombre")
        assert "revisarlo" in resultado.motivo


class TestElNombre:
    def test_lo_que_dice_el_nombre(self):
        assert pista_del_nombre("00C003288/ACTAS DE GRADO PREGRADO 1990.pdf") is T.ACTA
        assert pista_del_nombre("1SESION EXTRAORDINARIA N° 019.pdf") is T.ACTA_CONSEJO
        assert pista_del_nombre("REGISTRO DE DIPLOMAS N°08 2013.pdf") is T.DIPLOMA
        assert pista_del_nombre("GRADUADOS POSTGRADO Y PREGRADO 1997.pdf") is T.ACTA

    def test_alumnos_no_graduados_no_es_un_acta_de_grado(self):
        assert pista_del_nombre("ALUMNOS NO GRADUADOS 1981.pdf") is None


def _pdf(ruta, paginas):
    import pymupdf

    doc = pymupdf.open()
    for texto in paginas:
        pagina = doc.new_page()
        pagina.insert_textbox(pymupdf.Rect(40, 40, 560, 800), texto, fontsize=10)
    doc.save(ruta)
    doc.close()
    return ruta


class TestLaHabilidadQueNoAplica:
    def test_un_acta_de_grado_declarada_como_acta_de_consejo_se_detecta(self, tmp_path):
        from resolutions.api.worker import _el_patron_lo_contradice

        pdf = _pdf(tmp_path / "grado.pdf", [ACTA_DE_GRADO] * 4)

        assert _el_patron_lo_contradice({"source": str(pdf), "filename": "grado.pdf"}, T.ACTA_CONSEJO) is T.ACTA

    def test_lo_que_si_es_lo_declarado_no_se_toca(self, tmp_path):
        from resolutions.api.worker import _el_patron_lo_contradice

        pdf = _pdf(tmp_path / "consejo.pdf", [ACTA_DE_CONSEJO, SESION, FORMATO_DE_ADMISIONES])

        assert _el_patron_lo_contradice({"source": str(pdf)}, T.ACTA_CONSEJO) is None

    def test_sin_capa_de_texto_manda_lo_declarado(self, tmp_path):
        from resolutions.api.worker import _el_patron_lo_contradice

        pdf = _pdf(tmp_path / "escaneo.pdf", ["", ""])

        assert _el_patron_lo_contradice({"source": str(pdf)}, T.ACTA_CONSEJO) is None


class TestLaSugerenciaAntesDeProcesar:
    def test_un_archivo_soltado(self, client, tmp_path):
        pdf = _pdf(tmp_path / "grado.pdf", [ACTA_DE_GRADO] * 3)

        respuesta = client.post(
            "/api/reconocer", files={"file": ("ACTA DE GRADO 2023.pdf", pdf.read_bytes(), "application/pdf")}
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["tipo"] == "acta"

    def test_una_carpeta_con_subcarpetas_mezcladas(self, client, tmp_path):
        (tmp_path / "consejo").mkdir()
        (tmp_path / "grado").mkdir()
        _pdf(tmp_path / "consejo" / "sesion.pdf", [ACTA_DE_CONSEJO, SESION, SESION])
        _pdf(tmp_path / "grado" / "acta.pdf", [ACTA_DE_GRADO] * 3)

        datos = client.post("/api/reconocer-carpeta", json={"ruta": f'"{tmp_path}"'}).json()

        assert datos["total"] == 2
        assert {fila["tipo"]: fila["cantidad"] for fila in datos["por_tipo"]} == {
            "acta-consejo": 1,
            "acta": 1,
        }

    def test_una_carpeta_que_no_existe(self, client, tmp_path):
        assert client.post("/api/reconocer-carpeta", json={"ruta": str(tmp_path / "no")}).status_code == 404
