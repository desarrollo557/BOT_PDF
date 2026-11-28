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


# -- el clasificador por PDF (2026-11-27) -------------------------------------------------
#
# «8. ACTA 9 FACULTAD DE ODONTOLOGIA CALIFICACIONES 3194 - 3198»: libros de
# calificaciones, de actas de grado (dos manuscritos) y tomos de resoluciones en
# la misma carpeta, lanzada entera con «Detectar automáticamente» o con una sola
# habilidad declarada. Nombres inventados, con la forma del papel.

#: La lista de la promoción con que abre el libro.
LISTA_DE_LA_PROMOCION = (
    "UNIVERSIDAD DE CARTAGENA\nFACULTAD DE ODONTOLOGIA\nALUMNOS X SEMESTRE DE ODONTOLOGIA 2o. PERIODO 1995\n"
    + "\n".join(f"{orden}. 90100{70 + orden} APELLIDO{orden} OTRO NOMBRE{orden} M." for orden in range(1, 8))
)
ALUMNOS = (
    "LIZETH M. ALVAREZ ZAPATA",
    "JUAN C. BARRIOS PEREZ",
    "ANA M. CASTRO DIAZ",
    "LUIS A. DURAN GOMEZ",
    "MARTA E. ESPITIA RUIZ",
    "CARLOS J. FUENTES MORA",
)


def _constancia(nombre: str) -> str:
    return (
        "UNIVERSIDAD DE CARTAGENA\nEL SECRETARIO ACADÉMICO DE LA FACULTAD DE ODONTOLOGIA DE LA UNIVERSIDAD "
        f"DE CARTAGENA\nHACE CONSTAR\nQue, {nombre}, cursó y aprobó en esta Facultad, el 1o., 2o., 3o. y 10o. "
        "semestre de Odontología, con las siguientes calificaciones:\n1er. SEMESTRE 1990 - Bioquímica 3.10"
    )


def _continuacion(nombre: str) -> str:
    return f"Continuación Calificaciones de {nombre}\nX SEMESTRE 1994 - Clínica Integral 4.00 cuatro-cero-cero"


LIBRO_DE_CALIFICACIONES = [LISTA_DE_LA_PROMOCION] + [
    hoja for nombre in ALUMNOS for hoja in (_constancia(nombre), _continuacion(nombre))
]
#: Una resolución de Decanatura que pide la ceremonia y nombra a sus graduandos.
RESOLUCION_DE_DECANATURA = (
    "Resolución No. 016 Hoja No. 1\nPor la cual se solicita la ceremonia de grado de los graduandos\n"
    "LA DECANA DE LA FACULTAD DE ODONTOLOGIA\nRESUELVE:\nExpedir las actas de grado de los graduandos.\n"
    "Comuníquese y cúmplase"
)
#: Lo que deja el escáner de un acta manuscrita: ninguna palabra de ningún tipo.
MANUSCRITO = (
    "cmmjG mmcTWO tt tá ubh beíiiad im cArnTmmm Sí WJ m ám m Humlta e y cmmmwknmyt I Cmmi lrt etír F ewlttKl é C4a"
)


class TestLoQueDiceUnPdfEntero:
    def test_las_actas_decada_son_actas_de_grado_por_su_nombre(self):
        assert pista_del_nombre("ACTAS DE GRADO\\ACTAS DECADA. 1980-1984 TOMO I.pdf") is T.ACTA
        assert pista_del_nombre("ACTAS DECADA. 1996-1998-1999 TOMO II.pdf") is T.ACTA

    def test_la_resolucion_que_cita_a_los_graduandos_no_es_un_acta_de_grado(self):
        from resolutions.domain.patrones import hojas_de_cada_tipo

        # Por la hoja, su núcleo lo trae; en el PDF entero no cuenta: no abre ningún acta.
        assert T.ACTA in tipos_de_la_pagina(RESOLUCION_DE_DECANATURA)
        assert hojas_de_cada_tipo([RESOLUCION_DE_DECANATURA] * 3) == Counter({T.RESOLUCION: 3})
        assert hojas_de_cada_tipo([ACTA_DE_GRADO] * 2)[T.ACTA] == 2

    def test_lo_que_arrolla_a_lo_declarado(self):
        from resolutions.domain.patrones import lo_que_lo_arrolla

        # «RESOLUCIONES DE RECTORIA 03272-03275» (2026-10-29): 48 hojas de actas
        # de consejo de soporte contra 50 de resoluciones. No se contradice.
        rectoria = Counter({T.RESOLUCION: 50, T.ACTA_CONSEJO: 48})
        assert lo_que_lo_arrolla(rectoria, T.RESOLUCION) is None
        assert lo_que_lo_arrolla(rectoria, T.DIPLOMA) is T.RESOLUCION
        # Un tomo de resoluciones declarado como actas de grado.
        assert lo_que_lo_arrolla(Counter({T.RESOLUCION: 28}), T.ACTA) is T.RESOLUCION
        # Una hoja suelta no arrolla nada.
        assert lo_que_lo_arrolla(Counter({T.ACTA_CONSEJO: 1}), T.ACTA) is None

    def test_la_capa_de_un_manuscrito_no_dice_nada(self):
        from resolutions.domain.patrones import capa_que_no_dice_nada, hojas_de_cada_tipo

        basura = [MANUSCRITO] * 9 + [""]
        assert capa_que_no_dice_nada(basura, hojas_de_cada_tipo(basura))
        # Un escaneo sin capa no es basura: ése lo lee Tesseract.
        assert not capa_que_no_dice_nada(["", "", MANUSCRITO], Counter())
        assert not capa_que_no_dice_nada([ACTA_DE_GRADO] * 3, hojas_de_cada_tipo([ACTA_DE_GRADO] * 3))


@pytest.fixture
def rutas_del_despachador(monkeypatch):
    """Cada habilidad sustituida por un marcador: a cuál va el PDF, y con qué payload."""
    from resolutions.api import worker
    from resolutions.api.worker import historias

    llamadas: list[tuple[str, dict]] = []

    def marca(nombre):
        def hecho(payload, *_a, **_k):
            llamadas.append((nombre, payload))
            return {"ruta": nombre}

        return hecho

    monkeypatch.setattr(
        worker,
        "_acta_consejo_job",
        lambda payload, grado=False: marca("actas-de-grado" if grado else "actas-de-consejo")(payload),
    )
    monkeypatch.setattr(worker, "_split_job", marca("resoluciones"))
    monkeypatch.setattr(worker, "_record_split_job", marca("registros"))
    monkeypatch.setattr(historias, "historias_academicas_job", marca("historias"))
    monkeypatch.setattr(worker, "_anunciar", lambda *a, **k: None)
    monkeypatch.setattr(worker, "_recognise", lambda _p: pytest.fail("el orquestador no hacía falta"))
    return llamadas


def _payload(pdf, nombre, tipo="auto", task="both"):
    return {"source": str(pdf), "filename": nombre, "task": task, "tipo": tipo, "settings": {"ocr_language": "spa"}}


class TestElClasificadorPorPdf:
    """Cada PDF a su habilidad por su papel, también contra lo declarado (2026-11-27)."""

    @pytest.mark.parametrize("task", ["both", "inventory"])
    def test_un_libro_de_calificaciones_va_a_calificaciones(self, tmp_path, rutas_del_despachador, task):
        """Los de 1995-1997 se partían como resoluciones; los de 1998-2003, como historias."""
        from resolutions.api import worker

        pdf = _pdf(tmp_path / "libro.pdf", LIBRO_DE_CALIFICACIONES)
        payload = _payload(pdf, "CALIFICACIONES\\1995\\1 CALIFICACIONES ODONTOLOGIA 1995.pdf", task=task)

        assert worker._despachar(payload) == {"ruta": "historias"}
        assert rutas_del_despachador[0][1]["tipo"] == "calificaciones"
        assert payload["reconocimiento"]["tipo"] == "calificaciones"
        assert "6 constancias" in payload["reconocimiento"]["motivo"]

    def test_un_manuscrito_va_a_actas_de_grado_por_su_ruta(self, tmp_path, rutas_del_despachador):
        """La capa es basura y sólo la ruta lo dice: sin pasar por el orquestador."""
        from resolutions.api import worker

        pdf = _pdf(tmp_path / "manuscrito.pdf", [MANUSCRITO] * 6)
        payload = _payload(pdf, "ACTAS DE GRADO\\ACTAS DE GRADO 1952 - 1959.pdf")

        assert worker._despachar(payload) == {"ruta": "actas-de-grado"}
        assert payload["reconocimiento"]["decidido_por"] == "nombre"

    @pytest.mark.parametrize("declarado", ["resolucion", "acta", "historia-academica", "acta-consejo", "diploma"])
    def test_un_libro_de_calificaciones_declarado_como_otra_cosa_va_a_lo_suyo(
        self, tmp_path, rutas_del_despachador, declarado
    ):
        """La PROMOCION 2003 vive en la carpeta de las resoluciones."""
        from resolutions.api import worker

        pdf = _pdf(tmp_path / "promocion.pdf", LIBRO_DE_CALIFICACIONES)
        nombre = "RESOLUCIONES\\RESOLUCIONES DECANATURA 1995-2002\\UPD3860100\\PROMOCION 2003.pdf"

        informe = worker._despachar(_payload(pdf, nombre, tipo=declarado))

        assert rutas_del_despachador[0][0] == "historias"
        assert rutas_del_despachador[0][1]["tipo"] == "calificaciones"
        assert informe["reconocimiento"]["declarado"] == declarado
        assert informe["reconocimiento"]["tipo"] == "calificaciones"
        assert any("Calificaciones" in aviso for aviso in informe["notices"])

    def test_un_tomo_de_resoluciones_declarado_como_actas_de_grado_va_a_resoluciones(
        self, tmp_path, rutas_del_despachador
    ):
        """Sus resoluciones nombran a los graduandos, pero ninguna hoja abre un acta."""
        from resolutions.api import worker

        pdf = _pdf(tmp_path / "tomo.pdf", [RESOLUCION_DE_DECANATURA] * 4)

        informe = worker._despachar(_payload(pdf, "UPD3860107\\001-029 TOMO 2.pdf", tipo="acta"))

        assert informe["ruta"] == "resoluciones"
        assert informe["reconocimiento"]["declarado"] == "acta"

    def test_un_libro_de_actas_declarado_como_resoluciones_va_a_actas_de_grado(
        self, tmp_path, rutas_del_despachador
    ):
        from resolutions.api import worker

        pdf = _pdf(tmp_path / "actas.pdf", [ACTA_DE_GRADO] * 4)
        nombre = "ACTAS DE GRADO\\ACTAS DECADA. 1980-1984 TOMO I.pdf"
        assert worker._despachar(_payload(pdf, nombre, tipo="resolucion"))["ruta"] == "actas-de-grado"
        # Y el manuscrito, por su ruta.
        pdf = _pdf(tmp_path / "manuscrito.pdf", [MANUSCRITO] * 4)
        nombre = "ACTAS DE GRADO\\ACTAS DE GRADO 1960-1965.pdf"
        assert worker._despachar(_payload(pdf, nombre, tipo="resolucion"))["ruta"] == "actas-de-grado"

    def test_lo_que_lo_declarado_tiene_no_se_desvia(self, tmp_path, rutas_del_despachador):
        """Un legajo de resoluciones con actas de soporte (2026-10-29), y unas historias declaradas."""
        from resolutions.api import worker

        legajo = _pdf(tmp_path / "legajo.pdf", [RESOLUCION_INTERNA, ACTA_DE_CONSEJO, SESION, SESION, SESION])
        nombre = "1RESOLUCIONES DE RECTORIA 03272-03275.pdf"
        assert worker._despachar(_payload(legajo, nombre, tipo="resolucion")) == {"ruta": "resoluciones"}
        historias = _pdf(tmp_path / "historias.pdf", [FICHA_DE_MEDICINA, NOTAS_DE_MEDICINA] * 3 + [ACTA_DE_GRADO] * 2)
        declaradas = _payload(historias, "UPD 3859597.pdf", tipo="historia-academica")
        assert worker._despachar(declaradas) == {"ruta": "historias"}

    def test_sin_el_nombre_que_lo_confirma_el_acta_de_consejo_que_arrolla_si_se_desvia(
        self, tmp_path, rutas_del_despachador
    ):
        from resolutions.api import worker

        pdf = _pdf(tmp_path / "sesion.pdf", [ACTA_DE_CONSEJO, SESION, SESION, SESION])
        informe = worker._despachar(_payload(pdf, "UPD3747381.pdf", tipo="resolucion"))
        assert informe["ruta"] == "actas-de-consejo"
        assert informe["reconocimiento"]["declarado"] == "resolucion"

    def test_un_papel_sin_evidencia_se_queda_con_lo_declarado(self, tmp_path, rutas_del_despachador):
        """Nunca por descarte: un escaneo sin capa ni nombre que diga nada."""
        from resolutions.api import worker

        pdf = _pdf(tmp_path / "escaneo.pdf", ["", "", ""])
        assert worker._despachar(_payload(pdf, "UPD1.pdf", tipo="calificaciones")) == {"ruta": "historias"}


class TestLaSugerenciaDeLasCalificaciones:
    def test_un_libro_soltado_se_sugiere_como_calificaciones(self, client, tmp_path):
        pdf = _pdf(tmp_path / "libro.pdf", LIBRO_DE_CALIFICACIONES)

        respuesta = client.post(
            "/api/reconocer",
            files={"file": ("1 CALIFICACIONES ODONTOLOGIA 1995.pdf", pdf.read_bytes(), "application/pdf")},
        )

        assert respuesta.status_code == 200
        assert (respuesta.json()["tipo"], respuesta.json()["etiqueta"]) == ("calificaciones", "Calificaciones")

    @pytest.mark.parametrize(
        ("relativa", "tipo"),
        [
            ("CALIFICACIONES/FACULTAD DE ODONTOLOGIA CALIFICACIONES 1995/1 CALIFICACIONES ODONTOLOGIA 1995.pdf", "calificaciones"),
            ("RESOLUCIONES/RESOLUCIONES DECANATURA 1995-2002/UPD3860100/PROMOCION 2003 - FACULTAD DE ODONTOLOGIA.1 - UPD3860100.pdf", "calificaciones"),
            ("RESOLUCIONES/RESOLUCIONES DECANATURA 1995-2002/UPD3860101/07-115 TOMO 1.pdf", "resolucion"),
            ("ACTAS DE GRADO/ACTAS DECADA. 1980-1984 TOMO I.pdf", "acta"),
            ("ACTAS DE GRADO/ACTAS DE GRADO 1952 - 1959.pdf", "acta"),
            # El nombre más hondo manda: la carpeta de arriba dice «CALIFICACIONES» para los 26.
            ("8. ACTA 9 FACULTAD DE ODONTOLOGIA CALIFICACIONES 3194 - 3198/ACTAS DE GRADO/ACTAS DECADA. 1990-1994 TOMO II.pdf", "acta"),
        ],
    )
    def test_un_pdf_de_red_muy_grande_se_dice_por_su_nombre_mas_hondo(self, relativa, tipo):
        """Odontología 3194-3198 (2026-11-27): de 17 a 300 MB, no se bajan para sugerir."""
        from resolutions.api.routers.reconocer import _muy_grande

        assert _muy_grande(relativa, 60 * 1024 * 1024)["tipo"] == tipo
