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


def _entregar_las_dos(runner, run, settings, *, resumen: str = "N/A"):
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
             "folio_inicial": "N/A", "folio_final": "N/A", "folios": 7, "resumen": resumen,
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
    # NOTAS va vacía en el FUID que se entrega al cliente (2026-10-30).
    assert de_las_resoluciones.filas[0][15] == ""
    assert de_las_resoluciones.oficina_productora.endswith("FACULTAD DE DERECHO Y CIENCIAS POLITICAS")

    de_las_actas = leer_fuid(run.destination / CARPETA / CAJA / f"{CAJA}__FUID.xlsx")
    assert [fila[2] for fila in de_las_actas.filas] == ["ACTA DE CONSEJO DE FACULTAD - ORDINARIA"]

    runner._escribir_el_fuid_general(run, [], list(run.inventario_filas))
    general = run.destination / CARPETA / "00.FUID GENERAL.xlsx"
    assert run.inventario == str(general)
    planilla = leer_fuid(general)
    assert planilla.oficina_productora.endswith("FACULTAD DE DERECHO Y CIENCIAS POLITICAS")
    assert [fila[0] for fila in planilla.filas] == ["1", "2", "3"]
    assert sorted(fila[2] for fila in planilla.filas) == [
        "ACTA DE CONSEJO DE FACULTAD - ORDINARIA",
        "RESOLUCION 00030 POR LA CUAL SE CONVOCA",
        "RESOLUCION 00031 POR LA CUAL SE CONVOCA",
    ]


def test_en_la_carpeta_de_la_corrida_un_solo_fuid_con_las_dos_y_su_resumen(tmp_path):
    """La entrega real de la 3303 (2026-11-03): DESTINO = «<carpeta> - PROCESADO».

    Las resoluciones y las actas caen en la misma carpeta, ``DESTINO\\00C003303``,
    pero las actas la anotaban «18-RESOLUCIONES…\\00C003303» y las resoluciones
    «00C003303»: dos FUID en el mismo archivo, y el segundo pisaba al primero.
    El de la 3303 salió con sus 307 resoluciones y sin sus 10 actas, que sólo
    quedaron en el Excel de actas. El operador (2026-11-05): «que los unas y me
    des un solo resultado», con el resumen en el FUID.
    """
    from dataclasses import replace

    from openpyxl import load_workbook

    from resolutions.api.folders import FolderRun, FolderRunner
    from resolutions.api.jobs import JobRegistry
    from resolutions.api.settings import Settings

    settings = replace(Settings(), output_dir=tmp_path / "outputs")
    (tmp_path / CARPETA / CAJA).mkdir(parents=True)
    destino = tmp_path / f"{CARPETA} - PROCESADO"
    destino.mkdir()
    runner = FolderRunner(JobRegistry(), settings, run_job=None)
    run = FolderRun(
        id="r1",
        source=tmp_path / CARPETA,
        destination=destino,
        task="both",
        oficina="FACULTAD DE DERECHO Y CIENCIAS POLITICAS",
        oficina_mirada=True,
    )
    _entregar_las_dos(runner, run, settings, resumen="SE APROBO EL PLAN DE ESTUDIOS")

    ruta = destino / CAJA / f"{CAJA}__FUID.xlsx"
    fuid = leer_fuid(ruta)
    # El asunto del acta lleva detrás su resumen (el operador, 2026-11-09).
    assert sorted(fila[2] for fila in fuid.filas) == [
        "ACTA DE CONSEJO DE FACULTAD - ORDINARIA - SE APROBO EL PLAN DE ESTUDIOS",
        "RESOLUCION 00030 POR LA CUAL SE CONVOCA",
        "RESOLUCION 00031 POR LA CUAL SE CONVOCA",
    ]
    # Ni un FUID aparte en un árbol con la carpeta elegida delante.
    assert not (destino / CARPETA).exists()
    # El resumen del acta va en su asunto, y el FUID es el formato original:
    # nada a la derecha de NOTAS (el operador, 2026-11-09: «un FUID limpio»).
    hoja = load_workbook(ruta)["INVENTARIO"]
    assert all(hoja.cell(row=f, column=c).value is None for f in range(12, 17) for c in range(17, 21))


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
    # Y ninguna planilla suelta al lado: el FUID es el único Excel (2026-11-11).
    assert not list(run.destination.rglob("*__inventario.xlsx"))


def test_en_la_universidad_dos_tipos_en_una_carpeta_un_solo_fuid(corrida, tmp_path):
    """El operador, 2026-11-11: «documentos de Universidad de Cartagena, un único FUID»; «para aquellas
    carpetas en las que existan diferentes tipos de documentos, agruparlo en un solo FUID manejando el
    mismo formato».

    Con el destino de toda corrida, «<carpeta> - PROCESADO» (``destino_de_la_corrida``): la caja con
    resoluciones y actas lleva un FUID con las dos, y nada más que él y el general. Ni la planilla de
    la resolución ni el Excel de actas.
    """
    runner, run, settings = corrida
    run.destination = tmp_path / f"{CARPETA} - PROCESADO"
    run.destination.mkdir()
    _entregar_las_dos(runner, run, settings)
    runner._escribir_el_fuid_general(run, [], list(run.inventario_filas))

    excels = sorted(p.relative_to(run.destination).as_posix() for p in run.destination.rglob("*.xlsx"))
    assert excels == ["00.FUID GENERAL.xlsx", f"{CAJA}/{CAJA}__FUID.xlsx"]
    de_la_caja = leer_fuid(run.destination / CAJA / f"{CAJA}__FUID.xlsx")
    assert sorted(fila[2] for fila in de_la_caja.filas) == [
        "ACTA DE CONSEJO DE FACULTAD - ORDINARIA",
        "RESOLUCION 00030 POR LA CUAL SE CONVOCA",
        "RESOLUCION 00031 POR LA CUAL SE CONVOCA",
    ]
    # El mismo formato para los dos: el FO-GD-008 con la oficina de la carpeta.
    assert de_la_caja.oficina_productora.endswith("FACULTAD DE DERECHO Y CIENCIAS POLITICAS")


def test_fuera_de_la_universidad_la_planilla_sigue(corrida):
    """Sin la oficina de una facultad, la corrida no es de la Universidad: su planilla se entrega como siempre."""
    runner, run, settings = corrida
    run.oficina = None
    _entregar_las_dos(runner, run, settings)

    assert list((run.destination / CAJA).rglob("*__inventario.xlsx"))
