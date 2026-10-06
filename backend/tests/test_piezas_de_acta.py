"""Dividir un libro de actas de consejo: un PDF por sesión y sus piezas anotadas.

Con páginas de mentira: lo que se prueba son las reglas, no un libro concreto.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resolutions.application.acta_consejo import (
    InventariarActa,
    dividir_actas,
    nombre_de_la_sesion,
)
from resolutions.application.ports import AssemblyResult
from resolutions.domain.piezas_de_acta import (
    ACTA,
    ANEXO,
    ASISTENCIA,
    CITACION,
    FORMATO_DE_NOTAS,
    MICROCURRICULO,
    OFICIO,
    PORTADA,
    RESOLUCION,
    piezas_de_la_sesion,
    resumen_de_piezas,
    tipo_de_pagina,
)

MEMBRETE = (
    "FACULTAD DE ODONTOLOGÍA\nDEPARTAMENTO ACADEMICO\nDirección: Campus de Zaragocilla\n"
    "UNIVERSIDAD DE CARTAGENA\nFUNDADA EN 1827\nNIT 890 480123 -5\n"
)


def portada(numero: str, fecha: str) -> str:
    return f"No. {numero} - {fecha}"


def citacion(sesion: str, fecha: str) -> str:
    return (
        MEMBRETE
        + f"SESION {sesion}\nFECHA: {fecha}\nLUGAR: Oficina Decanatura\nHORA. 07:00 a.m.\n"
        "CONSEJO ORDEN DEL DÍA\n1. LLAMADO A LISTA Y VERIFICACIÓN DEL QUORUM\n"
    )


def asistencia(fecha: str) -> str:
    return (
        "CÓDIGO: FO-DA-002\nVERSIÓN: 00\nREGISTRO DE ASISTENCIA CONSEJO DE FACULTAD\n"
        f"FECHA: {fecha}\nNOMBRE\nCARGO\nFIRMA\n"
    )


def acta(sesion: str, numero: str, fecha: str) -> str:
    return (
        MEMBRETE
        + f"ACTA {sesion} No. {numero}\n{fecha}\nCONSEJO DE FACULTAD\n"
        "ORDEN DEL DÍA\n1. LLAMADO A LISTA Y VERIFICACIÓN DEL QUORUM\n"
        "2. ASUNTOS ACADÉMICOS\nSe revisan los microcurrículos y la convocatoria docente.\n"
    )


def acta_sigue(numero: str, anio: str) -> str:
    return (
        MEMBRETE
        + f"Acta No. {numero}-{anio}\nConsejo de Facultad\n"
        "3. SOLICITUD CONVOCATORIA DE DOCENTE DE CATEDRA\nEl Jefe del Departamento solicita…\n"
    )


def oficio(fecha: str) -> str:
    return (
        f"DECANATURA\nCartagena de Indias, {fecha}\nDoctora\nARLETH HERNANDEZ\n"
        "Asunto: corrección de nota\nCordial saludo.\nAtentamente,\n"
    )


FORMATO = (
    "CENTRO DE ADMISIONES REGISTRO Y\nCONTROL ACADÉMICO\nCÓDIGO:\nFO-DO/AD-005\n"
    "Corrección de Notas\nDocente/Tutor:\n"
)


class TestQueAbreCadaHoja:
    def test_la_portada_separadora(self):
        assert tipo_de_pagina(portada("017", "16 DE AGOSTO DE 2012")) == PORTADA

    def test_la_citacion_y_la_asistencia(self):
        assert tipo_de_pagina(citacion("EXTRAORDINARIA", "JUEVES 16 DE AGOSTO DE 2012")) == CITACION
        assert tipo_de_pagina(asistencia("16 DE AGOSTO DE 2012")) == ASISTENCIA

    def test_el_acta_abre_y_su_encabezado_corrido_la_sigue(self):
        assert tipo_de_pagina(acta("EXTRAORDINARIA", "017", "Jueves 16 de agosto de 2012")) == ACTA
        assert tipo_de_pagina(acta_sigue("017", "2012")) not in (ACTA, MICROCURRICULO, None)

    def test_una_palabra_suelta_en_el_cuerpo_no_abre_nada(self):
        # El acta habla de microcurrículos y de una convocatoria: sigue siendo acta.
        hoja = MEMBRETE + "La señora Decana comenta que los microcurrículos\nse revisen.\n"
        assert tipo_de_pagina(hoja) is None

    def test_un_oficio_y_el_formato_de_notas(self):
        assert tipo_de_pagina(oficio("23 de enero de 2012")) == OFICIO
        assert tipo_de_pagina(FORMATO) == FORMATO_DE_NOTAS

    def test_una_resolucion(self):
        hoja = MEMBRETE + "RESOLUCION No. 019\nPor la cual se fija el Calendario Académico\n"
        assert tipo_de_pagina(hoja) == RESOLUCION


class TestLasPiezasDeUnaSesion:
    def test_cada_hoja_en_una_sola_pieza_y_en_el_orden_del_pdf(self):
        hojas = [
            portada("017", "16 DE AGOSTO DE 2012"),
            citacion("EXTRAORDINARIA", "JUEVES 16 DE AGOSTO DE 2012"),
            asistencia("16 DE AGOSTO DE 2012"),
            acta("EXTRAORDINARIA", "017", "Jueves 16 de agosto de 2012"),
            acta_sigue("017", "2012"),
            "",  # un manuscrito sin texto: sigue el acta
            oficio("14 de agosto de 2012"),
            FORMATO,  # el soporte del oficio va con él
            oficio("15 de agosto de 2012"),  # otra carta: otra pieza
        ]

        piezas = piezas_de_la_sesion(hojas, desde=42)

        assert [(p.tipo, p.desde, p.hasta) for p in piezas] == [
            (PORTADA, 42, 42),
            (CITACION, 43, 43),
            (ASISTENCIA, 44, 44),
            (ACTA, 45, 47),
            (OFICIO, 48, 49),
            (OFICIO, 50, 50),
        ]

    def test_el_orden_de_las_piezas_no_es_fijo(self):
        # La citación y la asistencia pueden ir detrás del acta.
        hojas = [
            acta("EXTRAORDINARIA", "005", "13 de marzo de 2012"),
            citacion("EXTRAORDINARIA", "MARTES 13 DE MARZO DE 2012"),
            asistencia("13 DE MARZO DE 2012"),
        ]

        assert [p.tipo for p in piezas_de_la_sesion(hojas)] == [ACTA, CITACION, ASISTENCIA]

    def test_dos_asistencias_seguidas_son_una(self):
        hojas = [asistencia("23 DE MARZO"), asistencia("23 DE MARZO")]

        assert [(p.tipo, p.desde, p.hasta) for p in piezas_de_la_sesion(hojas)] == [
            (ASISTENCIA, 1, 2)
        ]

    def test_lo_que_no_se_reconoce_al_principio_es_un_anexo(self):
        assert piezas_de_la_sesion(["texto sin nada que lo abra"])[0].tipo == ANEXO

    def test_se_anotan_en_una_linea_para_el_inventario(self):
        hojas = [portada("017", "16 DE AGOSTO DE 2012"), citacion("ORDINARIA", "2 DE FEBRERO")]

        assert resumen_de_piezas(piezas_de_la_sesion(hojas, 42)) == "Portada p. 42 · Citación p. 43"


class _Fuente:
    def __init__(self, paginas):
        self._paginas = paginas

    @property
    def page_count(self):
        return len(self._paginas)

    def text_of(self, numero):
        return self._paginas[numero - 1]

    def render(self, numero, band=None, dpi=200):
        return b""


class _Escritor:
    """Anota lo que se le pide escribir, sin escribir nada."""

    def __init__(self):
        self.pedidos = []

    def write(self, source, result, destination):
        self.pedidos.append((destination, result))
        salidas = [destination / f"{g.code.value}_{g.kind}.pdf" for g in result.groups]
        return AssemblyResult(outputs=salidas)


def _libro():
    """Dos sesiones, cada una con su portada delante."""
    return [
        portada("002", "02 DE FEBRERO DE 2012"),
        citacion("ORDINARIA", "JUEVES 02 DE FEBRERO DE 2012"),
        acta("ORDINARIA", "002", "Jueves 02 de febrero de 2012"),
        oficio("1 de febrero de 2012"),
        portada("017", "16 DE AGOSTO DE 2012"),
        citacion("EXTRAORDINARIA", "JUEVES 16 DE AGOSTO DE 2012"),
        acta("EXTRAORDINARIA", "017", "Jueves 16 de agosto de 2012"),
    ]


class TestDividirUnLibro:
    def test_un_pdf_por_sesion_con_todo_lo_suyo(self, tmp_path):
        outcome = InventariarActa().execute(_Fuente(_libro()), document_name="libro.pdf")
        escritor = _Escritor()

        division = dividir_actas(
            outcome, assembler=escritor, source=Path("libro.pdf"),
            destino=tmp_path / "libro", raiz=tmp_path,
        )

        (destino, reparto), = escritor.pedidos
        assert destino == tmp_path / "libro"
        assert [(g.code.value, g.page_numbers) for g in reparto.groups] == [
            ("01", [1, 2, 3, 4]),
            ("02", [5, 6, 7]),
        ]
        assert [g.kind for g in reparto.groups] == [
            "ACTA ORDINARIA No. 002 - 02-02-2012",
            "ACTA EXTRAORDINARIA No. 017 - 16-08-2012",
        ]
        assert division.salidas[0].startswith("libro/01_")

    def test_la_fila_lleva_sus_piezas_con_paginas(self):
        outcome = InventariarActa().execute(_Fuente(_libro()), document_name="libro.pdf")

        assert outcome.filas[1].piezas == "Portada p. 5 · Citación p. 6 · Acta p. 7"
        assert outcome.as_dict()["sesiones"][1]["desde"] == 5

    def test_el_nombre_no_lleva_lo_que_windows_no_admite(self):
        from resolutions.application.acta_consejo import FilaDeActa

        fila = FilaDeActa(
            archivo="a.pdf", acta="N/A", fecha="N/A", folio_inicial="N/A",
            folio_final="N/A", folios=1, resumen="N/A",
        )
        assert nombre_de_la_sesion(fila) == "ACTA SIN NUMERO"


class TestLaEntregaEnCarpeta:
    @pytest.fixture
    def corrida(self, tmp_path):
        from dataclasses import replace

        from resolutions.api.folders import FolderRun, FolderRunner
        from resolutions.api.jobs import JobRegistry
        from resolutions.api.settings import Settings

        pytest.importorskip("openpyxl")
        settings = replace(Settings(), output_dir=tmp_path / "outputs")
        (tmp_path / "UPD").mkdir()
        (tmp_path / "destino").mkdir()
        runner = FolderRunner(JobRegistry(), settings, run_job=None)
        run = FolderRun(id="r1", source=tmp_path / "UPD", destination=tmp_path / "destino")
        return runner, run, settings

    def test_los_pdf_de_sesion_llegan_al_destino_con_el_excel(self, corrida):
        from resolutions.api.jobs import Job

        runner, run, settings = corrida
        producido = settings.output_dir / "j1" / "libro"
        producido.mkdir(parents=True)
        for nombre in ("01_ACTA-ORDINARIA-NO-002.pdf", "02_ACTA-EXTRAORDINARIA-NO-017.pdf"):
            (producido / nombre).write_bytes(b"%PDF")
        job = Job(id="j1", filename="libro.pdf", source=run.source / "libro.pdf", owns_source=False)
        job.report = {
            "inventario_actas": [
                {"archivo": "libro.pdf", "acta": "ACTA ORDINARIA No. 002", "fecha": "02-02-2012",
                 "folio_inicial": "N/A", "folio_final": "N/A", "folios": 4, "resumen": "N/A",
                 "observaciones": "", "pagina_inicial": 1, "pagina_final": 4},
            ],
            "outputs": ["libro/01_ACTA-ORDINARIA-NO-002.pdf", "libro/02_ACTA-EXTRAORDINARIA-NO-017.pdf"],
        }

        runner._deliver(run, job, run.source / "libro.pdf")

        entregados = sorted(p.relative_to(run.destination).as_posix() for p in run.destination.rglob("*.*"))
        # Espejo de la fuente: la carpeta elegida delante, el libro dividido
        # dentro y el Excel de la carpeta junto a él.
        assert entregados == [
            "UPD/ACTAS UPD__inventario.xlsx",
            "UPD/libro/01_ACTA-ORDINARIA-NO-002.pdf",
            "UPD/libro/02_ACTA-EXTRAORDINARIA-NO-017.pdf",
        ]

    def test_un_acta_que_ya_estaba_dividida_se_copia_tal_cual(self, corrida):
        from resolutions.api.jobs import Job

        runner, run, _settings = corrida
        run.task = "both"
        sub = run.source / "UPD2"
        sub.mkdir()
        (sub / "acta.pdf").write_bytes(b"%PDF suelta")
        job = Job(id="j2", filename="UPD2/acta.pdf", source=sub / "acta.pdf", owns_source=False)
        job.report = {
            "inventario_actas": [
                {"archivo": "acta.pdf", "acta": "ACTA ORDINARIA No. 003", "fecha": "01-03-2012",
                 "folio_inicial": 1, "folio_final": 4, "folios": 4, "resumen": "N/A",
                 "observaciones": "", "pagina_inicial": 1, "pagina_final": 4},
            ],
        }

        runner._deliver(run, job, sub / "acta.pdf")

        entregados = sorted(p.relative_to(run.destination).as_posix() for p in run.destination.rglob("*.*"))
        assert entregados == [
            "UPD/ACTAS UPD__inventario.xlsx",
            "UPD/UPD2/ACTAS UPD2__inventario.xlsx",
            "UPD/UPD2/acta.pdf",
        ]


class TestLosFoliosDeUnLibro:
    """Un libro se folia seguido: cada frontera entre actas se lee dos veces."""

    def test_la_mitad_buena_de_una_lectura_la_confirma_la_vecina(self):
        from resolutions.domain.acta_consejo import folios_del_libro

        # La primera esquina leyó bien el final (110) y mal el principio (40);
        # la segunda empieza en 111, que confirma ese 110.
        cadena = folios_del_libro([([40, 110], 10), ([111, 120], 10), ([121, 125], 5)])

        assert [(f.inicial, f.final) for f in cadena] == [(101, 110), (111, 120), (121, 125)]
        assert [f.leido for f in cadena] == [False, True, True]

    def test_lo_que_no_se_leyo_se_cuenta_desde_la_frontera_segura(self):
        from resolutions.domain.acta_consejo import folios_del_libro

        cadena = folios_del_libro([([1, 10], 10), ([11, 20], 10), ([], 4), ([25, 30], 6)])

        assert [(f.inicial, f.final) for f in cadena] == [(1, 10), (11, 20), (21, 24), (25, 30)]

    def test_entre_dos_lecturas_se_cree_la_que_cuadra_con_las_hojas(self):
        from resolutions.domain.acta_consejo import folios_del_libro

        # La frontera entre la segunda y la tercera se leyó 60 y 58: con 49 y 9
        # hojas desde las fronteras seguras, la buena es la 58.
        cadena = folios_del_libro([([1, 9], 9), ([10, 59], 49), ([58, 66], 9), ([67, 70], 4)])

        assert (cadena[1].final, cadena[2].inicial) == (57, 58)

    def test_sin_dos_lecturas_que_se_confirmen_no_se_inventa_nada(self):
        from resolutions.domain.acta_consejo import folios_del_libro

        assert folios_del_libro([([], 10), ([], 8)]) is None
        assert folios_del_libro([([1, 10], 10)]) is None


class TestElInventarioDeUnLibroDividido:
    def test_una_fila_por_pdf_de_sesion(self):
        from resolutions.application.inventory import rows_of

        informe = {
            "task": "inventory_file",
            "dividido": True,
            "tipo_documental": "ACTA DE CONSEJO",
            "inventario_actas": [
                {"acta": "ACTA ORDINARIA No. 002", "fecha": "02-02-2012", "numero": "002"},
                {"acta": "ACTA EXTRAORDINARIA No. 017", "fecha": "16-08-2012", "numero": "017"},
            ],
            "sesiones": [
                {"orden": 1, "nombre": "ACTA ORDINARIA No. 002 - 02-02-2012", "desde": 1, "hasta": 4},
                {"orden": 2, "nombre": "ACTA EXTRAORDINARIA No. 017 - 16-08-2012", "desde": 5, "hasta": 7},
            ],
            "outputs": ["libro/01_ACTA-ORDINARIA-NO-002.pdf", "libro/02_ACTA-EXTRAORDINARIA-NO-017.pdf"],
        }

        filas = rows_of(informe)

        assert [(f["code"], f["file_name"], f["first_page"], f["last_page"]) for f in filas] == [
            ("002", "libro/01_ACTA-ORDINARIA-NO-002.pdf", 1, 4),
            ("017", "libro/02_ACTA-EXTRAORDINARIA-NO-017.pdf", 5, 7),
        ]
        assert filas[1]["fecha"] == "16-08-2012"

    def test_sin_dividir_sigue_siendo_una_fila(self):
        from resolutions.application.inventory import rows_of

        informe = {"task": "inventory_file", "inventario": "a__inventario.xlsx", "page_count": 7}

        assert len(rows_of(informe)) == 1


class TestLaPortadaNoSeFolia:
    def test_no_cuenta_como_hoja_foliada(self):
        # Sin medir tinta todas las hojas cuentan como foliadas, menos la
        # portada separadora: una mota en su esquina no la vuelve folio.
        outcome = InventariarActa().execute(_Fuente(_libro()), document_name="libro.pdf")

        assert [fila.folios for fila in outcome.filas] == [3, 2]


def test_la_tarjeta_lista_los_pdf_y_el_excel_del_trabajo(client):
    from resolutions.api import main

    carpeta = main.contexto.settings.output_dir / "trabajo1" / "libro"
    carpeta.mkdir(parents=True)
    for nombre in ("10_ACTA-C.pdf", "02_ACTA-B.pdf", "01_ACTA-A.pdf"):
        (carpeta / nombre).write_bytes(b"%PDF-1.4")
    (carpeta.parent / "libro__inventario.xlsx").write_bytes(b"xlsx")

    respuesta = client.get("/api/jobs/trabajo1/archivos").json()

    assert [a["ruta"] for a in respuesta["archivos"]] == [
        "libro/01_ACTA-A.pdf",
        "libro/02_ACTA-B.pdf",
        "libro/10_ACTA-C.pdf",
    ]
    assert respuesta["inventario"] == "libro__inventario.xlsx"
    assert client.get("/api/jobs/no-existe/archivos").status_code == 404
