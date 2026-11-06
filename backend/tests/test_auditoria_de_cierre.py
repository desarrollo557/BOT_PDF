"""La auditoría de cierre de una corrida de carpeta (el operador, 2026-11-05).

«Así como vigila durante el procesamiento y hace su trabajo, también lo haga al
finalizar»: que lo de la fuente esté en el destino, y que 100 PDF entregados al
azar se revisen otra vez con los patrones y el margen de error; si la muestra
encuentra errores, otros 100. «Todo manejando un margen de errores»: el error de
la corrida se dice con su intervalo y se juzga contra un margen aceptable.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import openpyxl
import pytest

pymupdf = pytest.importorskip("pymupdf")

from resolutions.application.auditoria_de_la_entrega import auditar_un_pdf  # noqa: E402
from resolutions.application.ports import VeredictoDeCostura  # noqa: E402
from resolutions.domain.auditoria import (  # noqa: E402
    BIEN,
    DENTRO_DEL_MARGEN,
    DUDOSO,
    ERROR,
    FUERA_DEL_MARGEN,
    NO_AUDITADO,
    SIN_CERTEZA,
    elegir_la_muestra,
    margen_de_error,
)
from resolutions.domain.conciliacion import Huella  # noqa: E402

# -- el margen de error ------------------------------------------------------


class TestElMargenDeError:
    def test_cien_de_cien_bien_no_es_cero_por_ciento(self):
        margen = margen_de_error(0, 100)
        assert margen.tasa == 0
        assert margen.hasta == pytest.approx(0.037, abs=0.001)
        assert margen.texto() == "0 de 100 con error: el de la corrida, menos del 3,7 % (95 % de confianza)"
        assert margen.dictamen == DENTRO_DEL_MARGEN

    def test_un_error_en_cien_no_alcanza_para_asegurar_el_margen(self):
        assert margen_de_error(1, 100).dictamen == SIN_CERTEZA

    def test_ampliada_a_doscientos_si_alcanza(self):
        margen = margen_de_error(1, 200)
        assert margen.hasta < 0.05
        assert margen.dictamen == DENTRO_DEL_MARGEN

    def test_muchos_errores_quedan_fuera_aun_en_el_mejor_caso(self):
        margen = margen_de_error(10, 100)
        assert margen.desde > 0.05
        assert margen.dictamen == FUERA_DEL_MARGEN
        assert margen.texto_del_dictamen().startswith("Fuera del margen aceptable (5 %)")

    def test_el_margen_aceptable_se_puede_cambiar(self):
        assert margen_de_error(1, 100, aceptable=0.08).dictamen == DENTRO_DEL_MARGEN

    def test_sin_muestra_no_se_juzga(self):
        assert margen_de_error(0, 0).dictamen == SIN_CERTEZA


class TestLaMuestra:
    def test_la_misma_semilla_da_la_misma_muestra(self):
        pdfs = [f"caja/UPD{n}.pdf" for n in range(500)]
        assert elegir_la_muestra(pdfs, 100, 7) == elegir_la_muestra(list(reversed(pdfs)), 100, 7)
        assert len(elegir_la_muestra(pdfs, 100, 7)) == 100

    def test_la_segunda_ronda_no_repite_la_primera(self):
        pdfs = [f"UPD{n}.pdf" for n in range(300)]
        primera = elegir_la_muestra(pdfs, 100, 1)
        segunda = elegir_la_muestra(pdfs, 100, 2, excluir=primera)
        assert not set(primera) & set(segunda)

    def test_con_menos_de_cien_van_todos(self):
        assert elegir_la_muestra(["b", "a", "c"], 100, 3) == ["a", "b", "c"]


# -- un PDF auditado ---------------------------------------------------------

A, B, C, D = (Huella(texto=letra * 8) for letra in "abcd")
CONTRATO = {
    1: "PRIMERO: EL CLIENTE cancelará la suma.\nSEGUNDO: El CLIENTE pagará en cuotas.",
    2: "TERCERO: Para garantizar el pago de las cuotas.\nCUARTO: fin del procedimiento.",
    3: "Magangué 12 de enero de 2023\nSeñores:\nRef.: Reconocimiento de deuda y propuesta de acuerdo de pago.",
    4: "PAGARE No. 1004569 -3",
}


class _Juez:
    def __init__(self, decision):
        self.decision = decision
        self.preguntas = []

    def decidir(self, hojas, costuras, reglas):
        self.preguntas.append(costuras)
        return {c: VeredictoDeCostura(self.decision, "TERCERO: Para garantizar") for c in costuras}


class TestUnPdfAuditado:
    def test_bien_partido_y_entero(self):
        resultado = auditar_un_pdf("caja/UPD1.pdf", [A, B, C, D], CONTRATO, {"01.pdf": [A, B], "02.pdf": [C, D]})
        assert resultado.estado == BIEN
        assert resultado.costuras == 3 and resultado.dentro_del_margen == 3

    def test_una_hoja_que_no_llego_al_destino(self):
        resultado = auditar_un_pdf("UPD1.pdf", [A, B, C, D], CONTRATO, {"01.pdf": [A, B], "02.pdf": [C]})
        assert resultado.estado == ERROR
        assert "no están en ningún PDF entregado: 4" in resultado.hallazgos[0]

    def test_una_hoja_entregada_dos_veces_y_una_ajena(self):
        ajena = Huella(texto="zzzzzzzz")
        resultado = auditar_un_pdf("UPD1.pdf", [A, B, C, D], CONTRATO, {"01.pdf": [A, B, B], "02.pdf": [C, D, ajena]})
        assert resultado.estado == ERROR
        assert any("más de un PDF: 2" in h for h in resultado.hallazgos)
        assert any("«02.pdf» trae hojas que no son de este original" in h for h in resultado.hallazgos)

    def test_un_pdf_que_no_se_deja_abrir(self):
        resultado = auditar_un_pdf("UPD1.pdf", [A, B, C, D], CONTRATO, {"01.pdf": [A, B, C, D], "02.pdf": None})
        assert resultado.estado == ERROR
        assert "«02.pdf» no se dejó abrir" in resultado.hallazgos

    def test_el_indice_que_no_cuadra_con_la_carpeta(self):
        resultado = auditar_un_pdf(
            "UPD1.pdf", [A, B, C, D], CONTRATO, {"01.pdf": [A, B], "02.pdf": [C, D]}, filas_del_indice=3, pdf_en_su_carpeta=2
        )
        assert resultado.estado == ERROR
        assert "el índice de su carpeta tiene 3 filas y la carpeta 2 PDF" in resultado.hallazgos

    def test_el_corte_de_la_clausula_es_una_duda_sin_ia(self):
        # El contrato partido entre la SEGUNDO y la TERCERO: una prueba fuerte.
        resultado = auditar_un_pdf("UPD1.pdf", [A, B, C, D], CONTRATO, {"01.pdf": [A], "02.pdf": [B], "03.pdf": [C, D]})
        assert resultado.estado == DUDOSO
        assert "TERCERO" in resultado.hallazgos[0]

    def test_la_ia_lo_decide_si_la_corrida_la_usa(self):
        juez = _Juez("continua")
        resultado = auditar_un_pdf(
            "UPD1.pdf", [A, B, C, D], CONTRATO, {"01.pdf": [A], "02.pdf": [B], "03.pdf": [C, D]}, juez=juez
        )
        assert resultado.estado == ERROR
        assert "la IA" in resultado.hallazgos[0]
        assert juez.preguntas == [[(1, 2)]]
        confirmado = auditar_un_pdf(
            "UPD1.pdf", [A, B, C, D], CONTRATO, {"01.pdf": [A], "02.pdf": [B], "03.pdf": [C, D]}, juez=_Juez("abre")
        )
        assert confirmado.estado == BIEN

    def test_una_frase_que_sigue_sola_no_es_una_duda_sin_ia(self):
        """1000224 pág. 2: el membrete mal leído parece una frase que sigue."""
        textos = {
            1: "PARA LA EMPRESA\nRecibí constancia del contenido\nNombre del cliente que reclama aquí de",
            2: "a la prosperidad de todos los clientes\nTalaigua Nuevo 16 de Mayo de 2021",
        }
        assert auditar_un_pdf("UPD1.pdf", [A, B], textos, {"01.pdf": [A], "02.pdf": [B]}).estado == BIEN
        juez = _Juez("abre")
        assert auditar_un_pdf("UPD1.pdf", [A, B], textos, {"01.pdf": [A], "02.pdf": [B]}, juez=juez).estado == BIEN
        assert juez.preguntas == [[(1, 2)]]

    def test_sin_nada_entregado_no_se_audita(self):
        assert auditar_un_pdf("UPD1.pdf", [A], {1: ""}, {}).estado == NO_AUDITADO


# -- la corrida entera, de punta a punta ------------------------------------

from resolutions.adapters.indice_electronico import NOMBRE_DEL_INDICE  # noqa: E402
from resolutions.api.folders import FolderRunner, RunState  # noqa: E402
from resolutions.api.jobs import JobRegistry  # noqa: E402
from resolutions.api.settings import Settings  # noqa: E402

TEXTOS_DE_LA_CAJA = [
    "CONTRATO DE TRANSACCION\nPRIMERO: EL CLIENTE cancelará la suma.\nSEGUNDO: El CLIENTE pagará en cuotas.",
    "TERCERO: Para garantizar el pago de las cuotas mensuales.\nCUARTO: fin del procedimiento.",
    "Magangué 12 de enero de 2023\nSeñores:\nRef.: Reconocimiento de deuda y propuesta de acuerdo de pago.",
]


@pytest.fixture
def ajustes(tmp_path):
    settings = replace(
        Settings(),
        upload_dir=tmp_path / "uploads",
        output_dir=tmp_path / "outputs",
        ledger_path=tmp_path / "inventory.jsonl",
        pausa_tras_fallos=0.01,
        vueltas_de_reintento=0,
    )
    settings.ensure_directories()
    return settings


def _pdf(ruta: Path, textos: list[str]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    documento = pymupdf.open()
    for texto in textos:
        documento.new_page().insert_textbox(pymupdf.Rect(56, 56, 540, 760), texto, fontsize=11)
    documento.save(ruta)
    documento.close()


def _motor(ajustes, registro, *, mal_partidos=()):
    """Como la caja de correspondencia: parte cada UPD y deja su índice.

    Los de ``mal_partidos`` se parten con la hoja 2 sola, cortando el
    contrato entre su cláusula SEGUNDO y la TERCERO.
    """
    from datetime import date

    from resolutions.adapters.indice_electronico import FilaDelIndice, escribir_indice

    async def run_job(job):
        upd = Path(job.filename).stem
        salida = ajustes.output_dir / job.id / upd
        salida.mkdir(parents=True, exist_ok=True)
        origen = pymupdf.open(job.source)
        cortes = [[0], [1], [2]] if upd in mal_partidos else [[0, 1], [2]]
        for numero, paginas in enumerate(cortes, start=1):
            nuevo = pymupdf.open()
            for pagina in paginas:
                nuevo.insert_pdf(origen, from_page=pagina, to_page=pagina)
            nuevo.save(salida / f"{numero:02d}_DOCUMENTO.pdf")
            nuevo.close()
        origen.close()
        escribir_indice(
            salida,
            [
                FilaDelIndice(nombre=f"DOCUMENTO {n}", fecha_creacion=date(2023, 1, 12),
                              fecha_incorporacion=date(2026, 11, 5), orden=n, paginas=len(p))
                for n, p in enumerate(cortes, start=1)
            ],
            nic=Path(job.filename).parent.name,
            territorial="MAGANGUE",
            nombre_del_expediente=upd,
        )
        registro.mark_done(
            job,
            {"groups": [{"code": f"{n:02d}"} for n in range(1, len(cortes) + 1)], "review_queue": [],
             "indice_electronico": NOMBRE_DEL_INDICE},
        )

    return FolderRunner(registro, ajustes, run_job, watch_interval=0.01)


def _correr(motor, origen, destino):
    async def ir():
        run = motor.start(str(origen), str(destino), task="segment")
        for _ in range(3000):
            if not run.active:
                break
            await asyncio.sleep(0.01)
        tarea = motor._tasks.get(run.id)
        if tarea is not None:
            await asyncio.gather(tarea, return_exceptions=True)
        return run

    return asyncio.run(ir())


class TestLaAuditoriaDeUnaCorrida:
    def test_todo_entregado_y_bien_partido(self, ajustes, tmp_path):
        for caja, upd in (("1000265", "UPD1"), ("1000265", "UPD2"), ("210847", "UPD3")):
            _pdf(tmp_path / "origen" / caja / f"{upd}.pdf", TEXTOS_DE_LA_CAJA)
        (tmp_path / "origen" / "6909379").mkdir()
        run = _correr(_motor(ajustes, JobRegistry()), tmp_path / "origen", tmp_path / "destino")

        assert run.state is RunState.DONE
        comparacion = run.comparacion
        assert (comparacion["pdf_origen"], comparacion["pdf_entregados"]) == (3, 3)
        assert comparacion["documentos_entregados"] == comparacion["filas_del_indice"] == 6
        assert (comparacion["carpetas_con_pdf"], comparacion["carpetas_completas"]) == (2, 2)
        assert comparacion["completa"] is True
        assert comparacion["sin_pdf"] == [
            {"carpeta": "6909379", "motivo": "carpeta totalmente vacía", "evidencia": "0 archivos al listarla"}
        ]
        muestra = run.auditoria["muestra"]
        assert (muestra["revisados"], muestra["bien"], muestra["errores"]) == (3, 3, 0)
        assert run.etapa == "Terminado"
        assert "1 carpetas vacías" in run.etapa_detalle
        # Y en el análisis de la entrega.
        libro = openpyxl.load_workbook(tmp_path / "destino" / "00.ANALISIS DE LA ENTREGA.xlsx", read_only=True)
        try:
            assert {"Origen y destino", "Muestra auditada"} <= set(libro.sheetnames)
            resumen = {fila[0]: fila[1] for fila in libro["Resumen"].iter_rows(values_only=True)}
            muestras = list(libro["Muestra auditada"].iter_rows(min_row=2, values_only=True))
        finally:
            libro.close()
        assert resumen["Entrega completa"] == "Sí"
        assert resumen["Muestra · bien"] == 3
        assert len(muestras) == 3 and all(fila[2] == "bien" for fila in muestras)
        # El margen de cada habilidad, contra el de su perfil (2026-11-05).
        [suya] = muestra["por_habilidad"]
        assert (suya["clave"], suya["revisados"], suya["errores"]) == ("correspondencia", 3, 0)
        assert resumen["Margen · Caja de correspondencia"].startswith(suya["margen"]["texto"])

    def test_un_pdf_mal_partido_se_caza_y_se_amplia_la_muestra(self, ajustes, tmp_path):
        for upd in ("UPD1", "UPD2", "UPD3"):
            _pdf(tmp_path / "origen" / "1000265" / f"{upd}.pdf", TEXTOS_DE_LA_CAJA)
        run = _correr(_motor(ajustes, JobRegistry(), mal_partidos={"UPD2"}), tmp_path / "origen", tmp_path / "destino")

        muestra = run.auditoria["muestra"]
        mal = [p for p in muestra["pdfs"] if p["estado"] != BIEN]
        # Sin IA, el contrato partido por su cláusula queda como duda, nombrada.
        assert [p["pdf"] for p in mal] == [str(Path("1000265") / "UPD2.pdf")]
        assert "TERCERO" in mal[0]["hallazgos"][0]
        assert muestra["margen"]["dictamen"] == SIN_CERTEZA

    def test_una_hoja_perdida_en_el_destino_es_un_error(self, ajustes, tmp_path, monkeypatch):
        _pdf(tmp_path / "origen" / "1000265" / "UPD1.pdf", TEXTOS_DE_LA_CAJA)
        _pdf(tmp_path / "origen" / "1000265" / "UPD2.pdf", TEXTOS_DE_LA_CAJA)
        motor = _motor(ajustes, JobRegistry())
        # Justo antes de auditar, alguien cambia un PDF entregado por otro de una hoja.
        original = FolderRunner._auditar_al_cerrar

        async def cambiar_y_auditar(self, run):
            entregado = next((tmp_path / "destino").rglob("01_DOCUMENTO.pdf"))
            _pdf(entregado, TEXTOS_DE_LA_CAJA[:1])
            await original(self, run)

        monkeypatch.setattr(FolderRunner, "_auditar_al_cerrar", cambiar_y_auditar)
        run = _correr(motor, tmp_path / "origen", tmp_path / "destino")

        # La constancia ya no cuadra (cambió el tamaño): falta en el destino.
        assert run.comparacion["completa"] is False
        assert (run.comparacion["carpetas_con_pdf"], run.comparacion["carpetas_completas"]) == (1, 0)
        assert run.etapa == "Terminado con faltantes"

    def test_si_la_auditoria_falla_la_corrida_termina_igual(self, ajustes, tmp_path, monkeypatch):
        from resolutions.api import auditoria

        _pdf(tmp_path / "origen" / "1000265" / "UPD1.pdf", TEXTOS_DE_LA_CAJA)

        def rota(*_a, **_k):
            raise RuntimeError("se cayó el disco")

        monkeypatch.setattr(auditoria, "cuadrar", rota)
        run = _correr(_motor(ajustes, JobRegistry()), tmp_path / "origen", tmp_path / "destino")
        assert run.state is RunState.DONE
        assert run.auditoria["estado"] == "no se pudo"
        assert any("auditoría de cierre no se pudo hacer" in aviso for aviso in run.avisos)
