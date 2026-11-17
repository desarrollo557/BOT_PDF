"""La Revisión de los nombres de las historias académicas (2026-11-17).

El operador: «la idea es tener los nombres de manera correcta». Lo que la
máquina no asegura lo mira una persona: la pantalla enseña el renglón y corregir
mueve todo junto -- el PDF, la fila, el FUID del trabajo, el del destino, la
constancia y el padrón --.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from resolutions.api.folders import FolderRunner
from resolutions.api.jobs import JobRegistry
from resolutions.api.settings import Settings

VIEJO = "CAMPO TERNEGROZA ETDRIA LEONOR"
NUEVO = "CAMPO TORREGROZA ETILVIA LEONOR"
PDF_VIEJO = "01_CAMPO-TERNEGROZA-ETDRIA-LEONOR-49731465.pdf"
PDF_NUEVO = "01_CAMPO-TORREGROZA-ETILVIA-LEONOR-49731465.pdf"
DUDA = f"el nombre se leyó distinto en cada zona: «{VIEJO}» / «CAMPO TORREGROZA SILVIA»"


def _pdf(ruta: Path, paginas: int = 2) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as documento:
        for numero in range(paginas):
            pagina = documento.new_page()
            pagina.insert_text((72, 90), "Nombre del estudiante. Campo Torregroza Etilvia Leonor" if numero == 0 else "Campo Torregroza Silvia")
        documento.save(ruta)


def _informe(carpeta_del_pdf: str = "UPD1") -> dict:
    return {
        "tipo": "historia-academica",
        "groups": [{"code": PDF_VIEJO}],
        "review_queue": [{"page": 23, "reason": DUDA}, {"page": 23, "reason": "la cédula se leyó distinto: revísela"}],
        "outputs": [f"{carpeta_del_pdf}/{PDF_VIEJO}"],
        "inventario_actas": [
            {
                "tipo": "HISTORIA ACADEMICA",
                "nombre": VIEJO,
                "cedula": "49731465",
                "codigo": "820414",
                "anio_inicial": 1982,
                "anio_final": 1987,
                "folios": 2,
                "pagina_inicial": 23,
                "pagina_final": 24,
                "archivo": "UPD1.pdf",
                "archivo_generado": PDF_VIEJO,
                "observaciones": "",
                "revision_del_nombre": {
                    "estado": "duda", "pagina_de_la_ficha": 23, "leido": VIEJO,
                    "lecturas": [VIEJO, "CAMPO TORREGROZA SILVIA"],
                },
            }
        ],
    }


# -- la pantalla: el renglón y la corrección ----------------------------------------


@pytest.fixture
def trabajo(client, tmp_path):
    from resolutions.api import main

    job = main.contexto.registry.create("UPD1.pdf", tmp_path / "ya-no-esta.pdf")
    _pdf(main.contexto.settings.output_dir / job.id / "UPD1" / PDF_VIEJO)
    informe = _informe()
    main.contexto.registry.mark_done(job, informe)
    return job


def test_el_renglon_del_nombre_se_ve_sin_abrir_el_pdf(client, trabajo):
    respuesta = client.get(f"/api/jobs/{trabajo.id}/nombres/1/renglon.jpg")
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-type"] == "image/jpeg" and respuesta.content[:2] == b"\xff\xd8"
    assert client.get(f"/api/jobs/{trabajo.id}/nombres/99/renglon.jpg").status_code == 404
    assert client.get("/api/jobs/nada/nombres/1/renglon.jpg").status_code == 404


def test_corregir_el_nombre_mueve_todo_junto(client, trabajo, administrador):
    from resolutions.api import main

    assert client.put(f"/api/jobs/{trabajo.id}/nombres/1", json={"nombre": NUEVO}).status_code == 401
    assert client.put(f"/api/jobs/{trabajo.id}/nombres/1", json={"nombre": "X"}, headers=administrador).status_code == 422

    respuesta = client.put(f"/api/jobs/{trabajo.id}/nombres/1", json={"nombre": NUEVO.lower()}, headers=administrador)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["archivo_generado"] == PDF_NUEVO

    carpeta = main.contexto.settings.output_dir / trabajo.id / "UPD1"
    assert (carpeta / PDF_NUEVO).is_file() and not (carpeta / PDF_VIEJO).exists()
    informe = main.contexto.registry.get(trabajo.id).report
    (fila,) = informe["inventario_actas"]
    assert (fila["nombre"], fila["archivo_generado"]) == (NUEVO, PDF_NUEVO)
    assert fila["revision_del_nombre"]["estado"] == "corregido por el operador"
    assert VIEJO in fila["observaciones"]
    assert informe["outputs"] == [f"UPD1/{PDF_NUEVO}"] and informe["groups"] == [{"code": PDF_NUEVO}]
    # Sale de la cola la duda del nombre, no la de la cédula.
    assert [entrada["reason"] for entrada in informe["review_queue"]] == ["la cédula se leyó distinto: revísela"]
    # Y al padrón, con su cédula: la próxima vez esa cédula trae su nombre.
    (persona,) = main.contexto.padron.personas()
    assert (persona.nombre, persona.cedula, persona.fuente) == (NUEVO, "49731465", "corregido por el operador")


def test_confirmar_el_nombre_no_renombra_nada(client, trabajo, administrador):
    from resolutions.api import main

    respuesta = client.put(f"/api/jobs/{trabajo.id}/nombres/1", json={"nombre": VIEJO}, headers=administrador)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado"] == "confirmado por el operador"
    assert (main.contexto.settings.output_dir / trabajo.id / "UPD1" / PDF_VIEJO).is_file()
    informe = main.contexto.registry.get(trabajo.id).report
    assert not any(entrada["reason"] == DUDA for entrada in informe["review_queue"])
    (persona,) = main.contexto.padron.personas()
    assert persona.fuente == "confirmado por el operador"


def test_el_fuid_del_trabajo_se_reescribe_con_el_nombre_corregido(client, administrador, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from resolutions.adapters.fuid_de_la_entrega import escribir_fuid
    from resolutions.api import main

    job = main.contexto.registry.create("UPD1.pdf", tmp_path / "ya-no-esta.pdf")
    _pdf(main.contexto.settings.output_dir / job.id / "UPD1" / PDF_VIEJO)
    informe = {**_informe(), "inventario": "UPD1__inventario.xlsx"}
    escribir_fuid(informe["inventario_actas"], main.contexto.settings.output_dir / job.id / "UPD1__inventario.xlsx")
    main.contexto.registry.mark_done(job, informe)

    respuesta = client.put(f"/api/jobs/{job.id}/nombres/1", json={"nombre": NUEVO}, headers=administrador)
    assert respuesta.status_code == 200 and not respuesta.json()["avisos"], respuesta.text
    hoja = openpyxl.load_workbook(main.contexto.settings.output_dir / job.id / "UPD1__inventario.xlsx").active
    celdas = {str(celda.value) for fila in hoja.iter_rows() for celda in fila if celda.value}
    assert any(NUEVO in celda for celda in celdas) and not any(VIEJO in celda for celda in celdas)


# -- las demás habilidades: el nombre dentro del de su PDF y de su asunto ------------


def test_corregir_el_nombre_de_una_nomina(client, administrador, tmp_path):
    """Una nómina: el renglón por las zonas de su regla y el nombre cambiado dentro del PDF y del asunto."""
    from resolutions.api import main

    viejo, nuevo = "CASTELLAR AGUA TULIO", "CASTELLAR MEZA TULIO"
    pdf_viejo, pdf_nuevo = "01_CASTELLAR-AGUA-TULIO-9064111.pdf", "01_CASTELLAR-MEZA-TULIO-9064111.pdf"
    job = main.contexto.registry.create("NOMINAS 1972.pdf", tmp_path / "ya-no-esta.pdf")
    _pdf(main.contexto.settings.output_dir / job.id / "NOMINAS 1972" / pdf_viejo, paginas=1)
    main.contexto.registry.mark_done(job, {
        "tipo": "nomina",
        "outputs": [f"NOMINAS 1972/{pdf_viejo}"],
        "groups": [{"code": pdf_viejo}],
        "review_queue": [{"page": 7, "reason": f"{DUDA}"}],
        "inventario_actas": [
            {"tipo": "INDICE", "asunto": "INDICE", "pagina_inicial": 1, "pagina_final": 1},
            {
                "tipo": "NOMINA", "asunto": f"NOMINAS - {viejo}", "nombre": viejo, "cedula": "9064111",
                "folios": 1, "pagina_inicial": 7, "pagina_final": 7, "archivo": "NOMINAS 1972.pdf",
                "archivo_generado": pdf_viejo, "observaciones": "",
                "revision_del_nombre": {"estado": "duda", "pagina_de_la_ficha": 7, "leido": viejo},
            },
        ],
    })

    # La fila 1 es el índice, que no es de una persona.
    assert client.get(f"/api/jobs/{job.id}/nombres/1/renglon.jpg").status_code == 404
    respuesta = client.get(f"/api/jobs/{job.id}/nombres/2/renglon.jpg")
    assert respuesta.status_code == 200 and respuesta.content[:2] == b"\xff\xd8", respuesta.text

    respuesta = client.put(f"/api/jobs/{job.id}/nombres/2", json={"nombre": nuevo}, headers=administrador)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["archivo_generado"] == pdf_nuevo
    carpeta = main.contexto.settings.output_dir / job.id / "NOMINAS 1972"
    assert (carpeta / pdf_nuevo).is_file() and not (carpeta / pdf_viejo).exists()
    informe = main.contexto.registry.get(job.id).report
    fila = informe["inventario_actas"][1]
    assert (fila["nombre"], fila["asunto"], fila["archivo_generado"]) == (nuevo, f"NOMINAS - {nuevo}", pdf_nuevo)
    assert informe["outputs"] == [f"NOMINAS 1972/{pdf_nuevo}"] and informe["review_queue"] == []


def test_el_pdf_del_acta_colectiva_no_cambia_de_nombre(client, administrador, tmp_path):
    """El graduado de un acta colectiva: su fila y su asunto cambian; el PDF del acta, que es de todos, no."""
    from resolutions.api import main

    pdf = "01_ACTA DE GRADO 12 - 1990.pdf"
    job = main.contexto.registry.create("LIBRO.pdf", tmp_path / "ya-no-esta.pdf")
    _pdf(main.contexto.settings.output_dir / job.id / "LIBRO" / pdf, paginas=1)
    graduado = {
        "tipo": "ACTA DE GRADO", "acta_colectiva": True, "nombre": "PEREZ GOMEZ JUANA",
        "asunto": "ACTA DE GRADO 12 - PEREZ GOMEZ JUANA", "pagina_inicial": 3, "pagina_final": 3,
        "archivo_generado": pdf, "revision_del_nombre": {"estado": "duda", "pagina_de_la_ficha": 3},
    }
    main.contexto.registry.mark_done(job, {
        "tipo": "acta", "outputs": [f"LIBRO/{pdf}"],
        "inventario_actas": [graduado, {**graduado, "nombre": "RUIZ DIAZ PEDRO", "asunto": "ACTA DE GRADO 12 - RUIZ DIAZ PEDRO"}],
    })
    assert client.get(f"/api/jobs/{job.id}/nombres/2/renglon.jpg").status_code == 200

    respuesta = client.put(f"/api/jobs/{job.id}/nombres/1", json={"nombre": "PEREZ GOMEZ JUANITA"}, headers=administrador)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["archivo_generado"] == pdf
    assert (main.contexto.settings.output_dir / job.id / "LIBRO" / pdf).is_file()
    primera, segunda = main.contexto.registry.get(job.id).report["inventario_actas"]
    assert primera["asunto"] == "ACTA DE GRADO 12 - PEREZ GOMEZ JUANITA"
    assert segunda["nombre"] == "RUIZ DIAZ PEDRO"


# -- el destino de una corrida de carpeta -------------------------------------------


def test_la_correccion_llega_al_destino_de_la_corrida(tmp_path):
    """El PDF en el espejo, su constancia y el FUID de la subcarpeta y el general: todo junto."""
    openpyxl = pytest.importorskip("openpyxl")
    from resolutions.api import constancia as constancias

    settings = replace(
        Settings(), upload_dir=tmp_path / "uploads", output_dir=tmp_path / "outputs",
        ledger_path=tmp_path / "inventory.jsonl", pausa_tras_fallos=0.01,
    )
    settings.ensure_directories()
    origen, destino = tmp_path / "origen", tmp_path / "destino"
    (origen / "CAJA 1").mkdir(parents=True)
    destino.mkdir()
    (origen / "CAJA 1" / "UPD1.pdf").write_bytes(b"%PDF-1.4 fake")
    registro = JobRegistry()

    async def procesar(job):
        _pdf(settings.output_dir / job.id / "UPD1" / PDF_VIEJO)
        registro.mark_done(job, _informe())

    motor = FolderRunner(registro, settings, procesar, watch_interval=0.01)

    async def correr():
        run = motor.start(str(origen), str(destino), task="both")
        for _ in range(400):
            if not run.active:
                return run
            await asyncio.sleep(0.01)
        return run

    run = asyncio.run(correr())
    job = registro.get(run.job_ids[0])
    entregado = next(destino.rglob(PDF_VIEJO))

    avisos = motor.corregir_nombre(
        job, 23,
        {"nombre": VIEJO, "archivo_generado": PDF_VIEJO, "salida": f"UPD1/{PDF_VIEJO}"},
        {"nombre": NUEVO, "archivo_generado": PDF_NUEVO, "salida": f"UPD1/{PDF_NUEVO}"},
    )
    assert avisos == []
    assert (entregado.parent / PDF_NUEVO).is_file() and not entregado.exists()
    # La constancia sabe cómo se llama ahora: la corrida siguiente no lo da por faltante.
    (ruta,) = list(destino.rglob(f"{constancias.CARPETA_DE_ACTAS}/*.json"))
    constancia = constancias.leer(ruta)
    assert f"UPD1/{PDF_NUEVO}" in [archivo["ruta"] for archivo in constancia.archivos]
    assert [fila["nombre"] for fila in constancia.actas] == [NUEVO]
    # El FUID de la subcarpeta y el general, con el nombre corregido.
    for fuid in [*destino.rglob("*__FUID.xlsx"), *destino.rglob("00.FUID GENERAL.xlsx")]:
        hoja = openpyxl.load_workbook(fuid).active
        celdas = " ".join(str(celda.value) for fila in hoja.iter_rows() for celda in fila if celda.value)
        assert NUEVO in celdas and VIEJO not in celdas, fuid.name
    assert list(destino.rglob("00.FUID GENERAL.xlsx")) and list(destino.rglob("*__FUID.xlsx"))
    # Fuera de una corrida, nada.
    otro = registro.create("suelto.pdf", tmp_path / "suelto.pdf")
    assert motor.corregir_nombre(otro, 23, {}, {"nombre": NUEVO}) == []
