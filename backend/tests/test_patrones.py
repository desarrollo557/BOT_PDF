"""El patrón de cada tipo de documento: núcleo, veto y nombre.

Con texto de mentira que imita lo que se midió en la carpeta de Odontología:
actas de consejo con anexos de Admisiones, actas de grado, y archivos que sólo
se reconocen por su nombre.
"""

from __future__ import annotations

from collections import Counter

import pytest

from resolutions.domain.doctype import DocumentType as T
from resolutions.domain.doctype import TypeVerdict, classify_pages
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

    def test_las_historias_de_medicina_se_sugieren_con_su_habilidad(self, client, tmp_path):
        """«17. FACULTAD DE MEDICINA 3261- 3268 P» (2026-11-03): historias y hojas sueltas."""
        (tmp_path / "CAJA00C003261").mkdir()
        (tmp_path / "CAJA00C003268").mkdir()
        _pdf(tmp_path / "CAJA00C003261" / "UPD 3859597 HISTORIAS ACADEMICAS.pdf", [FICHA_DE_MEDICINA, NOTAS_DE_MEDICINA] * 2)
        _pdf(tmp_path / "CAJA00C003268" / "UPD0077193 - PRIMER AÑO 1992.pdf", ["Primer Año 1992", *[CERTIFICADO] * 3])

        datos = client.post("/api/reconocer-carpeta", json={"ruta": str(tmp_path)}).json()

        assert datos["por_tipo"] == [
            {"tipo": "historia-academica", "etiqueta": "Historias académicas", "cantidad": 2}
        ]

    def test_un_pdf_de_red_muy_grande_se_dice_por_su_nombre(self):
        from resolutions.api.routers.reconocer import _muy_grande

        grande = _muy_grande("CAJA00C003263/INTERNADOS ROTATORIO 1978-1984.pdf", 77 * 1024 * 1024)
        assert (grande["tipo"], grande["por"]) == ("historia-academica", "nombre")
        assert "77 MB" in grande["motivo"]
        assert _muy_grande("CAJA/sin pista.pdf", 30 * 1024 * 1024)["tipo"] == "desconocido"


#: La ficha y la hoja de notas de Medicina, y un certificado de matrícula de 1992.
FICHA_DE_MEDICINA = "UNIVERSIDAD DE CARTAGENA Facultad de Medicina REGISTRO DE MATRICULA Nombre del alumno Nombre del padre"
NOTAS_DE_MEDICINA = "REGISTRO DE ESTUDIOS ASIGNATURAS Calificación Definitiva PRIMER AÑO 1.957 Nombre CASTILLO"
CERTIFICADO = "UNIVERSIDAD DE CARTAGENA CERTIFICADO DE MATRICULA ACADEMICA CODIGO NOMBRE DEL ESTUDIANTE"


class TestDetectarAutomaticamente:
    """Con «Detectar automáticamente», cada PDF de historias va a su habilidad (2026-11-03)."""

    def test_las_historias_se_detectan_por_su_capa(self, tmp_path):
        from resolutions.api.worker import _familia_de_historias
        from resolutions.domain.historia_medicina import (
            HISTORIAS_DE_MEDICINA,
            HOJAS_DE_MATRICULA,
        )

        historias = _pdf(tmp_path / "historias.pdf", [FICHA_DE_MEDICINA, NOTAS_DE_MEDICINA] * 3)
        legajo = _pdf(tmp_path / "legajo.pdf", ["Primer Año 1992", *[CERTIFICADO] * 4])

        assert _familia_de_historias({"source": str(historias), "filename": "historias.pdf"}) == HISTORIAS_DE_MEDICINA
        assert _familia_de_historias({"source": str(legajo), "filename": "legajo.pdf"}) == HOJAS_DE_MATRICULA

    def test_lo_demas_sigue_su_camino(self, tmp_path):
        from resolutions.api.worker import _familia_de_historias

        consejo = _pdf(tmp_path / "consejo.pdf", [ACTA_DE_CONSEJO, SESION, SESION])
        grado = _pdf(tmp_path / "grado.pdf", [ACTA_DE_GRADO] * 3)

        assert _familia_de_historias({"source": str(consejo)}) is None
        assert _familia_de_historias({"source": str(grado)}) is None
        assert _familia_de_historias({"source": str(tmp_path / "no-existe.pdf")}) is None

    @pytest.mark.parametrize("task", ["inventory", "both"])
    def test_un_acta_con_anexos_de_matricula_va_a_actas_de_consejo(self, tmp_path, monkeypatch, task):
        """Odontología, 2026-11-11: la sesión 019 traía de anexos certificados de matrícula con el
        membrete de la Universidad, y con «No estoy seguro» se fue a «Historias académicas» (siete
        filas «MATRICULA ACADEMICA»). El patrón gratis decía acta de consejo y se pregunta primero.
        """
        from resolutions.api import worker
        from resolutions.api.worker import historias

        # Como la 019: catorce hojas, siete de acta y siete certificados.
        sesion = _pdf(tmp_path / "1SESION EXTRAORDINARIA N° 019.pdf", [ACTA_DE_CONSEJO, *[SESION] * 6, *[CERTIFICADO] * 7])
        # Lo que pasaba: la familia de historias la reclamaba.
        assert worker._familia_de_historias({"source": str(sesion), "filename": sesion.name}) is not None

        llamadas: list[str] = []
        monkeypatch.setattr(worker, "_acta_consejo_job", lambda payload: llamadas.append("actas") or {"ok": 1})
        monkeypatch.setattr(historias, "historias_academicas_job", lambda payload: llamadas.append("historias"))
        payload = {"source": str(sesion), "filename": sesion.name, "task": task, "tipo": "auto", "settings": {}}

        assert worker._despachar(payload) == {"ok": 1}
        assert llamadas == ["actas"]
        assert payload["reconocimiento"]["tipo"] == "acta-consejo"
        assert payload["reconocimiento"]["decidido_por"] == "patron"


RESOLUCION_INTERNA = (
    "Resolución Interna N° 015 de 2022\nPor la cual se solicita autorización para ceremonia de grado\n"
    "EL CONSEJO DE FACULTAD\nRESUELVE:\nSolicitar a la Rectoría autorización para graduar a los graduandos "
    "de la lista\nComuníquese, publíquese y cúmplase\n"
)


class TestLasResolucionesInternas:
    """Caja 00C003303 (2026-11-03): las de 2022 piden ceremonias de grado."""

    def test_por_la_cual_y_resuelve_son_nucleo_de_resolucion(self):
        assert T.RESOLUCION in tipos_de_la_pagina(RESOLUCION_INTERNA)

    def test_el_nombre_que_confirma_a_los_marcadores_no_se_veta(self):
        # Los marcadores dicen resolución y 5 páginas traen el núcleo de actas de
        # grado (las listas de graduandos): con el nombre «RESOLUCIONES» no hay veto.
        veredicto = TypeVerdict(document_type=T.RESOLUCION, confidence=0.8)
        nombre = "UPD3859996-RESOLUCIONES INTERNAS 2022 N° 01-71.pdf"
        assert reconocer(veredicto, Counter({T.ACTA: 5}), nombre).tipo is T.RESOLUCION
        # Sin ese nombre, el veto sigue como antes.
        assert reconocer(veredicto, Counter({T.ACTA: 5}), "UPD1.pdf").tipo is T.ACTA


class TestLosExamenesManuscritos:
    """Caja 00C003362 (2026-11-04): la capa de texto es basura y sólo queda el nombre."""

    def test_el_nombre_los_manda_a_actas_de_grado(self):
        for nombre in (
            "UPD3859999-EXAMENES PREPARATORIOS DE GRADO 1926-1395.pdf",
            "UPD3860000-EXAMENES PREPARATORIOS DE GRADO 1924-46.pdf",
        ):
            assert pista_del_nombre(nombre) is T.ACTA
            sin_marcadores = TypeVerdict(document_type=T.DESCONOCIDO, confidence=0.0)
            assert reconocer(sin_marcadores, Counter(), nombre).tipo is T.ACTA
