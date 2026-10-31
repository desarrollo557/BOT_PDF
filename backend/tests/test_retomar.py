"""Retomar una carpeta de libros de diplomas: qué llegó al destino y qué falta.

Lo pidió el operador el 2026-10-15 con una corrida a medias delante: tres
libros completos, tres con el libro entero en un solo archivo, tres cancelados
y dos sin empezar. El bot tiene que saber, mirando el disco, qué está
entregado, y seguir sólo con lo que falta -- página a página si hace falta --.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")
pytest.importorskip("openpyxl")

from resolutions.adapters.fuid_inventory import FuidInventory  # noqa: E402
from resolutions.adapters.fuid_reader import filas_de_fuid  # noqa: E402
from resolutions.adapters.huellas_pdf import huellas_de  # noqa: E402
from resolutions.api.folders import FolderError, FolderRunner  # noqa: E402
from resolutions.api.jobs import JobRegistry  # noqa: E402
from resolutions.api.retomar import Retomar, que_hacer  # noqa: E402
from resolutions.api.settings import Settings  # noqa: E402
from resolutions.application.diploma_split import group_by_record  # noqa: E402
from resolutions.application.fuid import FuidRow  # noqa: E402
from resolutions.application.inventory_document import template_for  # noqa: E402
from resolutions.application.read_diploma_book import ReadDiplomaBook  # noqa: E402
from resolutions.domain.conciliacion import (  # noqa: E402
    EstadoDeEntrega,
    Huella,
    conciliar,
    rangos,
)
from resolutions.domain.diploma import TextLine  # noqa: E402
from resolutions.domain.doctype import DocumentType  # noqa: E402

# -- ayudantes ---------------------------------------------------------------


def libro(ruta: Path, paginas: int) -> Path:
    """Un libro de diplomas de mentira: una cara por graduado, con capa de texto."""
    documento = pymupdf.open()
    for numero in range(1, paginas + 1):
        pagina = documento.new_page()
        pagina.insert_text(
            (72, 72),
            f"UNIVERSIDAD DE CARTAGENA - LIBRO DE REGISTRO DE DIPLOMAS - graduado numero {numero}",
            fontsize=9,
        )
    ruta.parent.mkdir(parents=True, exist_ok=True)
    documento.save(ruta)
    documento.close()
    return ruta


def nombre_de(numero: int) -> str:
    return f"P{numero:03d}_DIPLOMA.pdf"


def partir(origen: Path, carpeta: Path, paginas) -> list[str]:
    """Lo que hace el escritor: una cara del origen por PDF, copiada tal cual."""
    carpeta.mkdir(parents=True, exist_ok=True)
    fuente = pymupdf.open(origen)
    nombres = []
    for numero in paginas:
        salida = pymupdf.open()
        salida.insert_pdf(fuente, from_page=numero - 1, to_page=numero - 1)
        salida.save(carpeta / nombre_de(numero), garbage=3, deflate=True)
        salida.close()
        nombres.append(nombre_de(numero))
    fuente.close()
    return nombres


def fuid(carpeta: Path, nombre: str, paginas) -> Path:
    filas = [
        FuidRow(orden=i, asunto=f"GRADUADO {n}", notas=f"Archivo: {nombre_de(n)}")
        for i, n in enumerate(paginas, start=1)
    ]
    return FuidInventory(template_for(DocumentType.DIPLOMA)).write(
        filas, carpeta / f"{nombre}__FUID.xlsx"
    )


# -- el cruce, sin abrir un PDF -----------------------------------------------


def h(texto: str | None = None, imagen: str | None = None) -> Huella:
    return Huella(texto=texto, imagen=imagen)


class TestConciliar:
    ORIGEN = [h("a"), h("b"), h("c"), h(imagen="x"), h("e")]

    def test_sin_nada_en_el_destino_falta_todo(self):
        c = conciliar(self.ORIGEN, {})
        assert c.estado is EstadoDeEntrega.SIN_PROCESAR
        assert c.faltantes == (1, 2, 3, 4, 5)

    def test_todo_entregado_esta_completo(self):
        c = conciliar(self.ORIGEN, {f"{i}.pdf": [hu] for i, hu in enumerate(self.ORIGEN)})
        assert c.estado is EstadoDeEntrega.COMPLETO
        assert not c.faltantes

    def test_a_medias_dice_que_paginas_faltan(self):
        c = conciliar(self.ORIGEN, {"1.pdf": [h("a")], "2.pdf": [h("b")]})
        assert c.estado is EstadoDeEntrega.INCOMPLETO
        assert c.faltantes == (3, 4, 5)

    def test_la_pagina_sin_texto_se_reconoce_por_su_imagen(self):
        c = conciliar(self.ORIGEN, {"4.pdf": [h(imagen="x")]})
        assert c.entregadas == frozenset({4})

    def test_una_hoja_escaneada_dos_veces_cuenta_por_dos(self):
        """Dos caras con la misma huella: cada copia del destino se lleva una."""
        origen = [h("a"), h("a"), h("b")]
        assert conciliar(origen, {"1.pdf": [h("a")]}).faltantes == (2, 3)
        assert conciliar(origen, {"1.pdf": [h("a")], "2.pdf": [h("a")]}).faltantes == (3,)

    def test_lo_entregado_dos_veces_se_dice(self):
        c = conciliar([h("a"), h("b")], {"1.pdf": [h("a"), h("b")], "2.pdf": [h("b")]})
        assert c.repetidas == (2,)

    def test_un_archivo_que_no_es_de_este_origen_es_ajeno(self):
        c = conciliar(self.ORIGEN, {"otro.pdf": [h("zzz")]})
        assert c.ajenos == ("otro.pdf",)

    def test_el_libro_entero_en_un_archivo_esta_entregado_pero_sin_partir(self):
        """UPD3858080: 396 caras en un solo PDF."""
        c = conciliar(self.ORIGEN, {"todo.pdf": list(self.ORIGEN)})
        assert c.estado is EstadoDeEntrega.COMPLETO
        assert [a.nombre for a in c.sin_partir] == ["todo.pdf"]

    def test_cada_archivo_sabe_su_primera_pagina(self):
        c = conciliar(self.ORIGEN, {"c.pdf": [h("c")], "a.pdf": [h("a"), h("b")]})
        assert c.pagina_de("c.pdf") == 3
        assert c.pagina_de("a.pdf") == 1


class TestRangos:
    def test_como_lo_diria_una_persona(self):
        assert rangos([1, 2, 3, 7, 9, 10]) == "1-3, 7, 9-10"

    def test_sin_paginas_no_dice_nada(self):
        assert rangos([]) == ""


class TestQueHacer:
    def test_completo_no_se_procesa(self):
        assert que_hacer(conciliar([h("a")], {"1.pdf": [h("a")]}))[0] == []

    def test_sin_procesar_se_procesa_entero(self):
        assert que_hacer(conciliar([h("a")], {}))[0] is None

    def test_a_medias_solo_lo_que_falta(self):
        paginas, accion = que_hacer(conciliar([h("a"), h("b"), h("c")], {"1.pdf": [h("a")]}))
        assert paginas == [2, 3]
        assert "2-3" in accion


# -- las huellas, sobre PDF de verdad --------------------------------------------


class TestHuellas:
    def test_una_cara_partida_tiene_la_huella_de_su_origen(self, tmp_path):
        origen = libro(tmp_path / "LIBRO.pdf", 4)
        partir(origen, tmp_path / "destino", [2, 4])
        entregados = {p.name: huellas_de(p) for p in sorted((tmp_path / "destino").glob("*.pdf"))}
        c = conciliar(huellas_de(origen), entregados)
        assert c.entregadas == frozenset({2, 4})
        assert c.faltantes == (1, 3)

    def test_una_cara_sin_capa_de_texto_se_reconoce_por_su_imagen(self, tmp_path):
        documento = pymupdf.open()
        for color in ((1, 0, 0), (0, 0, 1)):
            pagina = documento.new_page()
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), 0)
            pixmap.set_rect(pixmap.irect, tuple(int(255 * c) for c in color))
            pagina.insert_image(pagina.rect, pixmap=pixmap)
        documento.save(tmp_path / "ESCANEO.pdf")
        partir(tmp_path / "ESCANEO.pdf", tmp_path / "d", [2])
        c = conciliar(huellas_de(tmp_path / "ESCANEO.pdf"), {"x": huellas_de(tmp_path / "d" / nombre_de(2))})
        assert c.entregadas == frozenset({2})


# -- leer sólo unas caras ----------------------------------------------------------


class FuenteDeCuatro:
    page_count = 4

    def lines_of(self, page_number):
        return [TextLine(text="LIBRO DE REGISTRO DE DIPLOMAS", y=0.0)]

    def render(self, page_number, band=None, dpi=200):
        return b""


class TestLeerSoloLoQueFalta:
    def test_solo_se_leen_esas_caras_con_su_numero(self):
        registros, stats = ReadDiplomaBook(ocr=None).execute(FuenteDeCuatro(), paginas=[2, 4])
        assert [r.page_number for r in registros] == [2, 4]
        assert stats.pages == 2

    def test_cuadran_contra_las_caras_leidas(self):
        registros, _ = ReadDiplomaBook(ocr=None).execute(FuenteDeCuatro(), paginas=[3])
        agrupacion = group_by_record(registros, por_pagina=True)
        agrupacion.verify_integrity(total_pages=4, paginas=[3])
        # Sin cédula ni nombre se llama por su página, no por ser la primera.
        assert agrupacion.groups[0].code.value == "003"


# -- la carpeta retomada, de punta a punta ----------------------------------------


@pytest.fixture
def workspace(tmp_path):
    settings = replace(
        Settings(),
        upload_dir=tmp_path / "uploads",
        output_dir=tmp_path / "outputs",
        ledger_path=tmp_path / "inventory.jsonl",
    )
    settings.ensure_directories()
    return settings


def runner_de_diplomas(workspace, registry):
    """Un procesamiento que hace lo que el de verdad: una cara por PDF, y su FUID."""
    procesados: list[tuple[str, list[int] | None]] = []

    async def run_job(job):
        procesados.append((Path(job.filename).name, job.paginas))
        salida = workspace.output_dir / job.id
        fuente = pymupdf.open(job.source)
        paginas = job.paginas or list(range(1, fuente.page_count + 1))
        fuente.close()
        nombres = partir(Path(job.source), salida, paginas)
        nombre_fuid = fuid(salida, Path(job.filename).stem, paginas).name
        registry.mark_done(
            job,
            {
                "fuid": nombre_fuid,
                "stats": {"document_type": "diploma"},
                "groups": [{"code": n} for n in nombres],
                "inventory": {
                    "items": [
                        {"file_name": nombre, "first_page": n, "page_count": 1}
                        for nombre, n in zip(nombres, paginas, strict=True)
                    ]
                },
                "review_queue": [],
            },
        )

    return FolderRunner(registry, workspace, run_job, watch_interval=0.01), procesados


def drain(engine, source, destination, **kwargs):
    async def go():
        run = engine.start(str(source), str(destination), **kwargs)
        for _ in range(1500):
            if not run.active:
                return run
            await asyncio.sleep(0.01)
        return run

    return asyncio.run(go())


@pytest.fixture
def entrega_a_medias(tmp_path):
    """A completo, B con dos de tres caras, C sin nada: la corrida que se cortó."""
    origen, destino = tmp_path / "origen", tmp_path / "destino"
    for nombre in ("A", "B", "C"):
        libro(origen / f"{nombre}.pdf", 3)
    partir(origen / "A.pdf", destino / "A", [1, 2, 3])
    fuid(destino / "A", "A", [1, 2, 3])
    partir(origen / "B.pdf", destino / "B", [1, 2])
    fuid(destino / "B", "B", [1, 2])
    return origen, destino


class TestRetomarLaCarpeta:
    def test_solo_se_procesa_lo_que_falta(self, workspace, entrega_a_medias):
        origen, destino = entrega_a_medias
        engine, procesados = runner_de_diplomas(workspace, JobRegistry())
        run = drain(engine, origen, destino, tipo="diploma", task="both", retomar="faltantes")

        assert sorted(procesados) == [("B.pdf", [3]), ("C.pdf", None)]
        assert run.ya_entregados == 1

    def test_al_terminar_todo_esta_en_el_destino(self, workspace, entrega_a_medias):
        origen, destino = entrega_a_medias
        engine, _ = runner_de_diplomas(workspace, JobRegistry())
        run = drain(engine, origen, destino, tipo="diploma", task="both", retomar="faltantes")

        assert sorted(p.name for p in (destino / "B").glob("*.pdf")) == [
            nombre_de(1), nombre_de(2), nombre_de(3)
        ]
        assert all(
            control.ultima.estado is EstadoDeEntrega.COMPLETO for control in run.controles.values()
        )

    def test_el_fuid_del_libro_retomado_suma_lo_que_ya_estaba(self, workspace, entrega_a_medias):
        origen, destino = entrega_a_medias
        engine, _ = runner_de_diplomas(workspace, JobRegistry())
        drain(engine, origen, destino, tipo="diploma", task="both", retomar="faltantes")

        filas, _ = filas_de_fuid(destino / "B" / "B__FUID.xlsx")
        assert [f.asunto for f in filas] == ["GRADUADO 1", "GRADUADO 2", "GRADUADO 3"]
        assert [f.orden for f in filas] == [1, 2, 3]

    def test_queda_el_control_y_el_fuid_general(self, workspace, entrega_a_medias):
        origen, destino = entrega_a_medias
        engine, _ = runner_de_diplomas(workspace, JobRegistry())
        run = drain(engine, origen, destino, tipo="diploma", task="both", retomar="faltantes")

        assert (destino / "00.CONTROL DE ENTREGA.xlsx").is_file()
        assert run.control and run.control.endswith("00.CONTROL DE ENTREGA.xlsx")
        general, _ = filas_de_fuid(destino / "00.FUID GENERAL.xlsx")
        # Los tres libros, también el que se saltó por completo.
        assert len(general) == 9
        assert general[0].notas == ""  # NOTAS va vacía (2026-10-30)

    def test_revisar_no_procesa_nada(self, workspace, entrega_a_medias):
        origen, destino = entrega_a_medias
        engine, procesados = runner_de_diplomas(workspace, JobRegistry())
        run = drain(engine, origen, destino, tipo="diploma", task="both", retomar="revisar")

        assert procesados == []
        estados = {pdf: str(c.antes.estado) for pdf, c in run.controles.items()}
        assert estados == {"A.pdf": "completo", "B.pdf": "incompleto", "C.pdf": "sin procesar"}
        assert run.controles["B.pdf"].antes.faltantes == (3,)
        assert (destino / "00.CONTROL DE ENTREGA.xlsx").is_file()

    def test_un_pdf_a_medio_escribir_no_cuenta_como_entregado(self, workspace, entrega_a_medias):
        """El que quedó a medias cuando se cortó la luz: sus páginas se vuelven a hacer."""
        origen, destino = entrega_a_medias
        (destino / "B" / nombre_de(2)).write_bytes(b"%PDF-1.4 cortado")
        engine, procesados = runner_de_diplomas(workspace, JobRegistry())
        run = drain(engine, origen, destino, tipo="diploma", task="both", retomar="revisar")

        assert run.controles["B.pdf"].antes.faltantes == (2, 3)
        assert run.controles["B.pdf"].ilegibles == (nombre_de(2),)

    def test_otra_habilidad_no_se_puede_retomar(self, workspace, tmp_path):
        engine, _ = runner_de_diplomas(workspace, JobRegistry())
        (tmp_path / "o").mkdir()
        with pytest.raises(FolderError, match="libros de diplomas"):
            engine.start(str(tmp_path / "o"), str(tmp_path / "d"), tipo="auto", retomar="faltantes")

    def test_un_modo_desconocido_se_rechaza(self, workspace, tmp_path):
        engine, _ = runner_de_diplomas(workspace, JobRegistry())
        (tmp_path / "o").mkdir()
        with pytest.raises(FolderError, match="desconocido"):
            engine.start(str(tmp_path / "o"), str(tmp_path / "d"), tipo="diploma", retomar="x")

    def test_los_modos(self):
        assert Retomar.parse(None) is Retomar.NO
        assert Retomar.parse("FALTANTES") is Retomar.FALTANTES
