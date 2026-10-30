"""Una carpeta con varias habilidades deja un solo FUID por subcarpeta y uno general.

«18-RESOLUCIONES INTERNAS Y ACTAS 3303» trae resoluciones y libros de actas en la
misma caja. Las resoluciones llegan con sus filas ya hechas
(``informe["filas_del_fuid"]``) y las actas con las suyas
(``informe["inventario_actas"]``): las dos tienen que acabar en el FUID de su
subcarpeta y en el general, numeradas seguidas y con la oficina de la carpeta.
Que una de las dos se quedara en su planilla suelta es justo lo que el operador
pidió evitar (2026-10-29: «el mismo inventario general, el mismo FUID»).
"""

from __future__ import annotations

import pytest

pytest.importorskip("openpyxl")

from resolutions.adapters.fuid_reader import leer_fuid  # noqa: E402

CARPETA = "18-RESOLUCIONES INTERNAS Y ACTAS 3303"
CAJA = "00C003303"


@pytest.fixture
def corrida(tmp_path):
    from dataclasses import replace

    from resolutions.api.folders import FolderRun, FolderRunner
    from resolutions.api.jobs import JobRegistry
    from resolutions.api.settings import Settings

    settings = replace(Settings(), output_dir=tmp_path / "outputs")
    (tmp_path / CARPETA / CAJA).mkdir(parents=True)
    (tmp_path / "destino").mkdir()
    runner = FolderRunner(JobRegistry(), settings, run_job=None)
    run = FolderRun(
        id="r1",
        source=tmp_path / CARPETA,
        destination=tmp_path / "destino",
        task="both",
        oficina="FACULTAD DE DERECHO Y CIENCIAS POLITICAS",
        oficina_mirada=True,
    )
    return runner, run, settings


def _resolucion(numero: str, pagina: int) -> dict:
    return {
        "orden": 1,
        "asunto": f"RESOLUCION {numero} POR LA CUAL SE CONVOCA",
        "codigo_trd": "N/A",
        "consecutivo_inicial": numero,
        "consecutivo_final": numero,
        "fecha_inicial": "02-09-2010",
        "fecha_final": "02-09-2010",
        "caja": "N/A",
        "carpeta": "N/A",
        "tomo": "N/A",
        "otro": "N/A",
        "folios": 2,
        "folios_siar": 2,
        "soporte": "N/A",
        "frecuencia": "N/A",
        "notas": f"Archivo: 0{pagina}_RESOLUCION-{numero}.pdf",
        "pagina_inicial": pagina,
    }


def _entregar_las_dos(runner, run, settings):
    from resolutions.api.jobs import Job

    caja = run.source / CAJA
    resoluciones = caja / "UPD3859990-RESOLUCIONES INTERNAS 2010 N°30-31-32.pdf"
    actas = caja / "UPD3859988-ACTAS N° 02 AL 10- Y 13.pdf"
    for pdf in (resoluciones, actas):
        pdf.write_bytes(b"%PDF")

    producido = settings.output_dir / "res"
    producido.mkdir(parents=True)
    for nombre in ("01_RESOLUCION-00030.pdf", "03_RESOLUCION-00031.pdf"):
        (producido / nombre).write_bytes(b"%PDF")
    trabajo = Job(id="res", filename=f"{CAJA}/{resoluciones.name}", source=resoluciones, owns_source=False)
    trabajo.task = "both"
    trabajo.report = {
        "stats": {"document_type": "resolucion"},
        "filas_del_fuid": [_resolucion("00030", 1), _resolucion("00031", 3)],
    }
    runner._deliver(run, trabajo, resoluciones)

    libro = Job(id="act", filename=f"{CAJA}/{actas.name}", source=actas, owns_source=False)
    libro.report = {
        "inventario_actas": [
            {"archivo": actas.name, "acta": "ACTA ORDINARIA", "numero": "02", "fecha": "22-01-2004",
             "folio_inicial": "N/A", "folio_final": "N/A", "folios": 7, "resumen": "N/A",
             "observaciones": "", "pagina_inicial": 1, "pagina_final": 7},
        ],
    }
    runner._deliver(run, libro, actas)
    runner._escribir_inventario_de_actas(run)


def test_cada_fuid_va_con_sus_pdf_y_el_general_las_junta_todas(corrida):
    """Las resoluciones, donde quedan sus PDF; las actas, en su espejo; el general, con todas.

    Los PDF de una resolución partida se entregan en ``DESTINO\\<caja>\\<pdf>\\``
    y los de las actas en el espejo con la carpeta elegida delante: cada FUID va
    con los suyos, y no en un árbol aparte que sólo tenga el FUID (2026-10-30).
    """
    runner, run, settings = corrida
    _entregar_las_dos(runner, run, settings)

    de_las_resoluciones = leer_fuid(run.destination / CAJA / f"{CAJA}__FUID.xlsx")
    assert [fila[2] for fila in de_las_resoluciones.filas] == [
        "RESOLUCION 00030 POR LA CUAL SE CONVOCA",
        "RESOLUCION 00031 POR LA CUAL SE CONVOCA",
    ]
    # La caja y la UPD de su ruta, que la resolución no sabía.
    assert [(fila[7], fila[8]) for fila in de_las_resoluciones.filas] == [(CAJA, "UPD3859990")] * 2
    # Cada resolución dice su archivo partido, no el del original.
    assert de_las_resoluciones.filas[0][15] == "Archivo: 01_RESOLUCION-00030.pdf"
    assert de_las_resoluciones.oficina_productora.endswith("FACULTAD DE DERECHO Y CIENCIAS POLITICAS")

    de_las_actas = leer_fuid(run.destination / CARPETA / CAJA / f"{CAJA}__FUID.xlsx")
    assert [fila[2] for fila in de_las_actas.filas] == ["ACTA DE CONSEJO DE FACULTAD No. 02 - ORDINARIA"]

    runner._escribir_el_fuid_general(run, [], list(run.inventario_filas))
    general = run.destination / CARPETA / "00.FUID GENERAL.xlsx"
    assert run.inventario == str(general)
    planilla = leer_fuid(general)
    assert planilla.oficina_productora.endswith("FACULTAD DE DERECHO Y CIENCIAS POLITICAS")
    assert [fila[0] for fila in planilla.filas] == ["1", "2", "3"]
    assert sorted(fila[2] for fila in planilla.filas) == [
        "ACTA DE CONSEJO DE FACULTAD No. 02 - ORDINARIA",
        "RESOLUCION 00030 POR LA CUAL SE CONVOCA",
        "RESOLUCION 00031 POR LA CUAL SE CONVOCA",
    ]


def test_un_pdf_que_se_rehace_no_suma_sus_filas_dos_veces(corrida):
    """La vuelta final rehace una entrega incompleta: sus filas se cambian, no se duplican."""
    runner, run, settings = corrida
    _entregar_las_dos(runner, run, settings)
    antes = len(run.inventario_filas)

    from resolutions.api.jobs import Job

    resoluciones = run.source / CAJA / "UPD3859990-RESOLUCIONES INTERNAS 2010 N°30-31-32.pdf"
    otra_vez = Job(id="res", filename=f"{CAJA}/{resoluciones.name}", source=resoluciones, owns_source=False)
    otra_vez.task = "both"
    otra_vez.report = {
        "stats": {"document_type": "resolucion"},
        "filas_del_fuid": [_resolucion("00030", 1), _resolucion("00031", 3)],
    }
    runner._deliver(run, otra_vez, resoluciones)

    assert len(run.inventario_filas) == antes


def test_los_libros_de_diplomas_no_suman_filas_hechas(corrida):
    """Su FUID va junto al libro y el general lo lee del disco: sumarlas las contaría dos veces."""
    runner, run, settings = corrida
    from resolutions.api.jobs import Job

    libro = run.source / CAJA / "UPD3858079 REGISTRO DE DIPLOMAS.pdf"
    libro.write_bytes(b"%PDF")
    (settings.output_dir / "dip").mkdir(parents=True)
    trabajo = Job(id="dip", filename=libro.name, source=libro, owns_source=False, tipo="diploma")
    trabajo.task = "both"
    trabajo.report = {"stats": {"document_type": "diploma"}, "filas_del_fuid": [_resolucion("1", 1)]}
    runner._deliver(run, trabajo, libro)

    assert run.inventario_filas == []


def test_los_pdf_sueltos_en_la_raiz_dejan_su_fuid_junto_al_general(tmp_path):
    """«20.ACTAS DE GRADO 3362» trae sus dos PDF sueltos, sin subcarpeta de caja.

    Su FUID caía en la raíz del destino con el nombre del destino -- fuera del
    espejo de la carpeta, donde dos carpetas lanzadas al mismo destino se lo
    pisan -- y con la caja vacía. Va junto al general, con la caja y las hojas
    que el Excel del cliente anota de cada UPD (2026-10-30).
    """
    from dataclasses import replace

    from resolutions.api.folders import FolderRun, FolderRunner
    from resolutions.api.jobs import Job, JobRegistry
    from resolutions.api.settings import Settings

    carpeta = "20.ACTAS DE GRADO 3362"
    settings = replace(Settings(), output_dir=tmp_path / "outputs")
    (tmp_path / carpeta).mkdir()
    (tmp_path / "destino").mkdir()
    runner = FolderRunner(JobRegistry(), settings, run_job=None)
    run = FolderRun(
        id="r1",
        source=tmp_path / carpeta,
        destination=tmp_path / "destino",
        task="inventory_file",
        oficina="FACULTAD DE MEDICINA",
        oficina_mirada=True,
        folios_del_cliente={"UPD3860000": 101},
        cajas_del_cliente={"UPD3860000": "00C003362"},
        folios_mirados=True,
    )
    examenes = run.source / "UPD3860000-EXAMENES PREPARATORIOS DE GRADO 1924-46.pdf"
    examenes.write_bytes(b"%PDF")
    (settings.output_dir / "exa").mkdir(parents=True)
    trabajo = Job(id="exa", filename=examenes.name, source=examenes, owns_source=False)
    trabajo.task = "inventory_file"
    trabajo.report = {
        "task": "inventory_file",
        "filas_del_fuid": [
            {
                "orden": 1,
                "asunto": "Documento sin identificar",
                "fecha_inicial": "N/A",
                "fecha_final": "N/A",
                "caja": "N/A",
                "carpeta": "N/A",
                "folios": 199,
                "folios_siar": 199,
                "notas": "",
                "pagina_inicial": 1,
            }
        ],
    }
    runner._deliver(run, trabajo, examenes)
    runner._escribir_inventario_de_actas(run)

    fuid = leer_fuid(run.destination / carpeta / f"{carpeta}__FUID.xlsx")
    assert [fila[2] for fila in fuid.filas] == ["EXAMENES PREPARATORIOS DE GRADO 1924-46"]
    assert [(fila[7], fila[8]) for fila in fuid.filas] == [("00C003362", "UPD3860000")]
    # Opción B: las hojas del cliente en «No. de folios» y las páginas en SIAR.
    assert [(fila[11], fila[12]) for fila in fuid.filas] == [("101", "199")]
    assert not list(run.destination.glob("*__FUID.xlsx"))

    runner._escribir_el_fuid_general(run, [], list(run.inventario_filas))
    general = leer_fuid(run.destination / carpeta / "00.FUID GENERAL.xlsx")
    assert [(fila[7], fila[8]) for fila in general.filas] == [("00C003362", "UPD3860000")]
