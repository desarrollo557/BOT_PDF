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


def _motor(ajustes, registro, *, mal_partidos=(), con_su_titulo=False):
    """Como la caja de correspondencia: parte cada UPD y deja su índice.

    Los de ``mal_partidos`` se parten con la hoja 2 sola, cortando el
    contrato entre su cláusula SEGUNDO y la TERCERO. Con ``con_su_titulo``
    cada fila del índice lleva el título de su PDF, como en la caja de verdad
    («DOCUMENTO» para «01_DOCUMENTO.pdf»), y la auditoría casa sus fechas.
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
                FilaDelIndice(nombre="DOCUMENTO" if con_su_titulo else f"DOCUMENTO {n}", fecha_creacion=date(2023, 1, 12),
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


# -- las fechas de lo entregado (el revisor de fechas, 2026-11-10) ----------------------------
#
# «Estar muy seguro de cada fecha en cada documento, sin importar la habilidad»,
# también en la muestra de PDF: cada PDF entregado, con su fila de la
# constancia, contra el texto de sus hojas del original. Lo corregido con
# prueba es error; lo dudoso, a la IA de los datos en una pregunta por PDF.

from resolutions.api import auditoria as auditoria_api  # noqa: E402
from resolutions.api.auditoria import EntregaVista, auditar_la_muestra  # noqa: E402
from resolutions.api.constancia import Constancia, EstadoDeEntrega, Vigencia  # noqa: E402
from resolutions.application import auditoria_de_la_entrega as entrega_app  # noqa: E402
from resolutions.application.control import Cancelled  # noqa: E402
from resolutions.application.ports import VeredictoDeDato  # noqa: E402
from resolutions.domain.auditoria import PdfAuditado  # noqa: E402
from resolutions.domain.conciliacion import ArchivoEntregado  # noqa: E402

CARTAS = {
    1: "Señores: reclamo por el cobro de la factura.\nMagangué, 30 de agosto de 2021",
    2: "Respuesta al reclamo.\nCartagena, 5 de mayo de 2020",
    3: "Magangué 12 de enero de 2023\nSeñores:\nRef.: Reconocimiento de deuda.",
}
RESOLUCION_EXPEDIDA = (
    "UNIVERSIDAD DE CARTAGENA\nRESOLUCIÓN No. 031 DE 2005\nEL RECTOR, en uso de sus facultades...\n"
    "RESUELVE: ARTÍCULO PRIMERO: reconocer.\n"
    "Dada en Cartagena de Indias, a los quince (15) días del mes de marzo de 2005."
)


def _fila(archivo: str | None, fecha: str, **mas) -> dict:
    return {"archivo_generado": archivo, "fecha_inicial": fecha, "fecha_final": fecha, **mas}


class _JuezDeDatos:
    """Un juez de datos que contesta lo que se le dicte y anota cada pregunta."""

    def __init__(self, respuestas=None, *, falla: BaseException | None = None):
        self.respuestas = respuestas
        self.falla = falla
        self.preguntas: list[tuple[str, list[dict]]] = []

    def verificar(self, texto, datos):
        self.preguntas.append((texto, datos))
        if self.falla is not None:
            raise self.falla
        return self.respuestas


class TestLaFilaDeCadaPdfEntregado:
    def test_por_su_nombre_sin_la_carpeta_ni_las_mayusculas(self):
        fila = _fila("UPD1\\01_RECLAMO.PDF", "12/01/2023")
        assert entrega_app.fila_del_archivo(ArchivoEntregado("UPD1/01_reclamo.pdf", (1,)), [fila]) is fila

    def test_por_la_hoja_en_que_empieza_si_ninguna_lo_nombra(self):
        """Las filas del FUID de un legajo guardan su página, no su archivo."""
        resolucion = {"tipo": "FILA DEL FUID", "fuid": {"pagina_inicial": 3, "fecha_inicial": "15/03/2005"}}
        assert entrega_app.fila_del_archivo(ArchivoEntregado("02.pdf", (3, 4)), [resolucion]) is resolucion

    def test_dos_filas_en_la_misma_hoja_no_se_adivinan(self):
        filas = [_fila(None, "12/01/2023", pagina_inicial=3), _fila(None, "13/01/2023", pagina_inicial=3)]
        assert entrega_app.fila_del_archivo(ArchivoEntregado("02.pdf", (3,)), filas) is None

    def test_la_fila_de_otro_archivo_no_se_casa_por_la_hoja(self):
        otra = _fila("09.pdf", "12/01/2023", pagina_inicial=3)
        assert entrega_app.fila_del_archivo(ArchivoEntregado("02.pdf", (3,)), [otra]) is None


class TestLasFechasDeUnPdfAuditado:
    def test_cada_pdf_contra_sus_hojas(self):
        filas = [_fila("01.pdf", "12/01/2023"), _fila(None, "12/01/2023", pagina_inicial=3)]
        resultado = auditar_un_pdf(
            "UPD1.pdf", [A, B, C], CARTAS, {"01.pdf": [A, B], "02.pdf": [C]}, filas_de_la_constancia=filas
        )
        # La del 02 está en su hoja; la del 01 no está en las suyas (sí en la 3, que no es suya).
        assert resultado.estado == DUDOSO
        assert any(h.startswith("«01.pdf»: la fecha 12/01/2023 no está escrita en el documento") for h in resultado.hallazgos)
        assert not any("02.pdf" in h for h in resultado.hallazgos)
        assert resultado.extra["fechas"] == {"en duda": 1, "confirmadas": 1}

    def test_sin_filas_no_cambia_nada(self):
        resultado = auditar_un_pdf("UPD1.pdf", [A, B, C, D], CONTRATO, {"01.pdf": [A, B], "02.pdf": [C, D]})
        assert resultado.estado == BIEN and resultado.extra == {}

    def test_lo_que_el_papel_corrige_con_prueba_es_error(self, monkeypatch):
        monkeypatch.setattr(entrega_app, "regla_de_fechas_de", lambda habilidad: "expedicion")
        fila = {"tipo": "FILA DEL FUID", "fuid": {"pagina_inicial": 1, "fecha_inicial": "01/02/2005", "fecha_final": "01/02/2005"}}
        resultado = auditar_un_pdf(
            "LEGAJO.pdf", [A], {1: RESOLUCION_EXPEDIDA}, {"01.pdf": [A]}, habilidad="resoluciones", filas_de_la_constancia=[fila]
        )
        assert resultado.estado == ERROR
        assert resultado.hallazgos == (
            "«01.pdf»: la fecha dice 01/02/2005 y el papel 15/03/2005 (la fórmula de expedición («Dada en…») "
            "dice 15/03/2005 y 01/02/2005 no está escrita en el documento)",
        )
        assert resultado.extra["fechas"] == {"con error": 1}

    def test_lo_dudoso_de_todos_sus_pdf_en_una_sola_pregunta(self):
        filas = [_fila("01.pdf", "12/01/2023"), _fila("02.pdf", "12/01/2023")]
        juez = _JuezDeDatos(
            {
                "d1_fecha_inicial": VeredictoDeDato("no_esta", "Magangué, 30 de agosto de 2021"),
                "d2_fecha_inicial": VeredictoDeDato("no_se", ""),
            }
        )
        resultado = auditar_un_pdf(
            "UPD1.pdf",
            [A, B],
            {1: CARTAS[1], 2: CARTAS[2]},
            {"01.pdf": [A], "02.pdf": [B]},
            filas_de_la_constancia=filas,
            juez_de_datos=juez,
        )
        [(texto, datos)] = juez.preguntas
        # Una fecha que va en las dos puntas se pregunta una vez, con una clave
        # corta: con el nombre del PDF en ella, la IA podía copiarla mal y la
        # respuesta se perdía (2026-11-10). El rótulo de cada texto dice cuál es.
        assert datos == [
            {"campo": "d1_fecha_inicial", "valor": "12/01/2023"},
            {"campo": "d2_fecha_inicial", "valor": "12/01/2023"},
        ]
        assert "=== DOCUMENTO d1: «01.pdf» ===" in texto and "=== DOCUMENTO d2: «02.pdf» ===" in texto
        assert resultado.estado == ERROR
        assert (
            "«01.pdf»: la fecha dice 12/01/2023 y el papel 30/08/2021 "
            "(la IA lo cita del papel: «Magangué, 30 de agosto de 2021»)"
        ) in resultado.hallazgos
        assert any(h.startswith("«02.pdf»: la fecha 12/01/2023 no está escrita en el documento") for h in resultado.hallazgos)
        assert resultado.preguntadas_a_la_ia == 1
        assert resultado.extra["fechas"] == {"con error": 1, "en duda": 1}

    def test_la_cita_de_otro_pdf_no_vale_para_este(self):
        """La respuesta es de todos, pero cada cita se busca en las hojas de su PDF."""
        juez = _JuezDeDatos({"d1_fecha_inicial": VeredictoDeDato("no_esta", "Magangué, 30 de agosto de 2021")})
        resultado = auditar_un_pdf(
            "UPD1.pdf",
            [A, B],
            {1: CARTAS[1], 2: CARTAS[2]},
            {"01.pdf": [A], "02.pdf": [B]},
            filas_de_la_constancia=[_fila("02.pdf", "12/01/2023")],
            juez_de_datos=juez,
        )
        assert resultado.estado == DUDOSO
        assert resultado.extra["fechas"] == {"en duda": 1}

    def test_la_ia_que_falla_deja_la_duda_y_detener_no_se_traga(self):
        filas = [_fila("01.pdf", "12/01/2023")]
        args = ("UPD1.pdf", [A], {1: CARTAS[1]}, {"01.pdf": [A]})
        caida = auditar_un_pdf(*args, filas_de_la_constancia=filas, juez_de_datos=_JuezDeDatos(falla=RuntimeError("503")))
        assert caida.estado == DUDOSO
        assert any("(la IA no respondió)" in h for h in caida.hallazgos)
        with pytest.raises(Cancelled):
            auditar_un_pdf(*args, filas_de_la_constancia=filas, juez_de_datos=_JuezDeDatos(falla=Cancelled("detenida")))

    def test_sin_texto_en_sus_hojas_no_dice_nada(self):
        resultado = auditar_un_pdf(
            "UPD1.pdf", [A], {1: ""}, {"01.pdf": [A]}, filas_de_la_constancia=[_fila("01.pdf", "12/01/2023")]
        )
        assert resultado.estado == BIEN
        assert resultado.extra["fechas"] == {"sin fechas": 1}


def _vista(tmp_path: Path, nombre: str, actas: list[dict]) -> EntregaVista:
    """Un original de tres hojas entregado en dos PDF, con las filas que aportó en su constancia."""
    origen = tmp_path / "origen" / nombre
    _pdf(origen, [CARTAS[1], CARTAS[2], CARTAS[3]])
    base = tmp_path / "destino" / Path(nombre).stem
    documento = pymupdf.open(origen)
    for numero, paginas in ((1, (0, 1)), (2, (2, 2))):
        nuevo = pymupdf.open()
        nuevo.insert_pdf(documento, from_page=paginas[0], to_page=paginas[1])
        base.mkdir(parents=True, exist_ok=True)
        nuevo.save(base / f"0{numero}.pdf")
        nuevo.close()
    documento.close()
    constancia = Constancia(
        origen=nombre,
        tamano=1,
        modificado_ns=1,
        estado=EstadoDeEntrega.COMPLETA,
        archivos=[{"ruta": "01.pdf", "bytes": 1}, {"ruta": "02.pdf", "bytes": 1}],
        habilidad="",
        actas=actas,
    )
    return EntregaVista(origen, nombre, Vigencia.VIGENTE, constancia, base, "")


class TestLaRevisionAdversarialDeLasFechas:
    """Lo que dejó la revisión adversarial del revisor de fechas en la auditoría (2026-11-10).

    Todas las habilidades -- también la correspondencia y Kingspan, que no
    dejan filas en la constancia --, la ventana del libro en las dos muestras,
    y lo que no es error de la entrega -- la letra a mano -- fuera del margen.
    """

    def test_el_titulo_de_un_pdf_sin_su_numero_ni_su_origen(self):
        titulo = entrega_app.titulo_del_archivo
        assert titulo("04_RECLAMO-RE2310202405234.pdf") == "RECLAMORE2310202405234"
        assert titulo("01_NIC 5940155-11_01_DOCUMENTO.pdf", "NIC 5940155-11") == "DOCUMENTO"
        assert titulo("UPD2998726_01_DOCUMENTO.pdf") == "DOCUMENTO"
        assert titulo("02_RECONOCIMIENTO-DE-DEUDA.pdf") == titulo("RECONOCIMIENTO DE DEUDA")

    def test_las_filas_del_indice_se_casan_por_titulo_y_paginas(self):
        """El índice va en orden de fecha y no de hojas: se casa por título y páginas, sin adivinar."""
        archivos = [
            ArchivoEntregado("01_DOCUMENTO.pdf", (1, 2, 3)),
            ArchivoEntregado("02_RECLAMO.pdf", (4,)),
            ArchivoEntregado("03_RECLAMO.pdf", (5,)),
            ArchivoEntregado("04_CARTA.pdf", (6,)),
            ArchivoEntregado("05_CARTA.pdf", (7,)),
        ]
        indice = [
            {"nombre": "RECLAMO", "fecha_creacion": "2021-10-21", "paginas": 1},
            {"nombre": "DOCUMENTO", "fecha_creacion": "2021-10-28", "paginas": 3},
            {"nombre": "RECLAMO", "fecha_creacion": "2021-10-21", "paginas": 1},
            # Dos cartas de una hoja con fechas distintas: cuál es cuál no se sabe.
            {"nombre": "CARTA", "fecha_creacion": "2021-11-01", "paginas": 1},
            {"nombre": "CARTA", "fecha_creacion": "2021-11-05", "paginas": 1},
            {"nombre": "SIN FECHA", "fecha_creacion": None, "paginas": 1},
        ]
        casadas = entrega_app.filas_del_indice_con_su_pdf(indice, archivos)
        assert {(f["archivo_generado"], f["fecha_inicial"]) for f in casadas} == {
            ("01_DOCUMENTO.pdf", "2021-10-28"),
            ("02_RECLAMO.pdf", "2021-10-21"),
            ("03_RECLAMO.pdf", "2021-10-21"),
        }

    def test_la_correspondencia_se_audita_por_su_indice(self, ajustes, tmp_path):
        """P1-2: la caja de correspondencia quedaba fuera del muestreo de fechas."""
        _pdf(tmp_path / "origen" / "1000265" / "UPD1.pdf", TEXTOS_DE_LA_CAJA)
        run = _correr(_motor(ajustes, JobRegistry(), con_su_titulo=True), tmp_path / "origen", tmp_path / "destino")
        muestra = run.auditoria["muestra"]
        # La carta del 12 de enero lo dice; el contrato de las hojas 1-2 no trae fecha: duda, no error.
        assert muestra["fechas"]["documentos"] == 2
        assert (muestra["fechas"]["confirmadas"], muestra["fechas"]["en duda"], muestra["fechas"]["con error"]) == (1, 1, 0)
        assert muestra["errores"] == 0

    def test_kingspan_por_sus_puntas_contra_todo_el_original(self):
        """Cada punta, una fecha contra todas las hojas: la final anterior a la inicial no es un error."""
        hojas = {1: "001-CEE-00000557 Fecha: 14/10/2023 COMPROBANTE DE EGRESO", 2: "Anexo", 3: "001-CEE-00000650 Fecha: 02/03/2022 COMPROBANTE DE EGRESO"}
        puntas = [
            {entrega_app.DE_TODO_EL_ORIGINAL: True, "punta": "001-CEE-00000557", "fecha_inicial": "14/10/2023",
             "fecha_final": "14/10/2023", "pagina_inicial": 1, "pagina_final": 10**6},
            {entrega_app.DE_TODO_EL_ORIGINAL: True, "punta": "001-CEE-00000650", "fecha_inicial": "02/03/2022",
             "fecha_final": "02/03/2022", "pagina_inicial": 1, "pagina_final": 10**6},
        ]
        fechas = entrega_app.auditar_las_fechas(
            [ArchivoEntregado("001-CEE-00000557.pdf", (1, 2)), ArchivoEntregado("001-CEE-00000650.pdf", (3,))],
            hojas, puntas, regla="extremos",
        )
        assert fechas.cuentas == {"confirmadas": 2} and not fechas.dudas and not fechas.errores

    def test_cada_punta_contra_las_hojas_que_traen_su_numero(self):
        """Contra toda la UPD, la fecha de otro documento la confirmaba: 12 de 23 puntas corridas un día seguían bien."""
        hojas = {
            1: "COMPROBANTE DE EGRESO 001-CEE-00000557 Fecha: 14/10/2023 pago a proveedores",
            2: "COMPROBANTE DE EGRESO 001-CEE-00000558 Fecha: 15/10/2023 pago a proveedores",
        }
        corrida = {
            entrega_app.DE_TODO_EL_ORIGINAL: True, "punta": "001-CEE-00000557", "su_numero": "001-CEE-00000557",
            "fecha_inicial": "15/10/2023", "fecha_final": "15/10/2023", "pagina_inicial": 1, "pagina_final": 10**6,
        }
        assert entrega_app.hojas_de_la_punta(corrida, hojas, (1, 2)) == (hojas[1],)
        fechas = entrega_app.auditar_las_fechas([], hojas, [corrida], regla="extremos")
        assert fechas.cuentas == {"en duda": 1}
        # Sin su número en ninguna hoja, todo el tramo.
        assert entrega_app.hojas_de_la_punta({**corrida, "su_numero": "001-CEE-9"}, hojas, (1, 2)) == (hojas[1], hojas[2])

    def test_las_puntas_del_inventario_de_kingspan_entregado(self, tmp_path):
        from resolutions.api.worker.kingspan import HOJA, PRIMERA_FILA

        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.title = HOJA
        fila = [None] * 27
        fila[9:14] = ["COMPROBANTES DE EGRESO", "001-CEE-1", "001-CEE-9", "14/10/2023", "02/03/2022"]
        sin_numeros = [None] * 27
        sin_numeros[9:14] = ["CONCILIACION", "N/A", "N/A", "01/01/2020", "31/12/2020"]
        for columna, valor in enumerate(fila, start=1):
            hoja.cell(PRIMERA_FILA, columna, valor)
        for columna, valor in enumerate(sin_numeros, start=1):
            hoja.cell(PRIMERA_FILA + 1, columna, valor)
        (tmp_path / "UPD1").mkdir()
        libro.save(tmp_path / "UPD1" / "UPD1_INVENTARIO_KINGSPAN.xlsx")
        constancia = Constancia(
            origen="UPD1.pdf", tamano=1, modificado_ns=1, estado=EstadoDeEntrega.COMPLETA,
            archivos=[{"ruta": "UPD1_INVENTARIO_KINGSPAN.xlsx", "bytes": 1}], habilidad="Kingspan",
        )
        vista = EntregaVista(tmp_path / "UPD1.pdf", "UPD1.pdf", Vigencia.VIGENTE, constancia, tmp_path / "UPD1", "")
        assert auditoria_api.es_de_kingspan(vista)
        puntas = auditoria_api._filas_de_kingspan(vista, 30)
        assert [(p["punta"], p["fecha_inicial"], p["fecha_final"]) for p in puntas] == [
            ("COMPROBANTES DE EGRESO · 001-CEE-1", "14/10/2023", "14/10/2023"),
            ("COMPROBANTES DE EGRESO · 001-CEE-9", "02/03/2022", "02/03/2022"),
            ("CONCILIACION", "01/01/2020", "31/12/2020"),
        ]
        assert all(p["pagina_final"] == 30 and "nombre" not in p for p in puntas)
        # En la muestra de filas, el inventario de Kingspan es una candidata.
        [(nombre, (entrega, candidata))] = auditoria_api.filas_candidatas([vista]).items()
        assert nombre == "UPD1.pdf · inventario de Kingspan" and candidata[entrega_app.DE_TODO_EL_ORIGINAL]

    def test_la_letra_a_mano_no_es_duda_ni_paga_la_ia(self):
        """#10: con la capa de un escaneo de letra a mano, lo que no se encuentra queda sin dato."""
        a_mano = {
            1: "REGISTRO DEL ESTUDIANTE ¿i/eJuyU /c<úy¿ir/ ^^y^AjiUAA. &0 - <s> Luga/ A/^'cu y/r> A-S\" ^ B/c At - Ji/é "
            "Cy pó í/íP íU i-í J44^ dS4 3a<f Í4í/ ;«*»* 7i^ rwv, /■■?f/- ¿// - i»W /-gf/ ^JLuccdd^ Tl ->■ rz> ‘i",
        }
        juez = _JuezDeDatos({})
        resultado = auditar_un_pdf(
            "UPD1.pdf", [A], a_mano, {"01.pdf": [A]},
            filas_de_la_constancia=[_fila("01.pdf", "12/01/2023")], juez_de_datos=juez,
        )
        assert resultado.estado == BIEN and resultado.extra["fechas"] == {"sin fechas": 1}
        assert not juez.preguntas

    def test_la_ventana_del_libro_tambien_en_la_muestra_de_pdf(self):
        """#9: ACOSTA BELLO, 1994-2001 en «HISTORIAS ACADEMICAS 1986», se veía al procesar y no al cerrar."""
        fila = {"archivo_generado": "01_ACOSTA BELLO.pdf", "anio_inicial": 1994, "anio_final": 2001}
        juez = _JuezDeDatos({})
        resultado = auditar_un_pdf(
            "CAJA/UPD3859727-1HISTORIAS ACADEMICAS 1986.pdf", [A], {1: "ACOSTA BELLO ADOLFO. Ingreso 1994. Grado 2001."},
            {"01_ACOSTA BELLO.pdf": [A]}, habilidad="historias", filas_de_la_constancia=[fila], juez_de_datos=juez,
        )
        assert resultado.extra["fechas"] == {"en duda": 1}
        assert any("2001 cae fuera de los años del libro (1974-1992)" in h for h in resultado.hallazgos)
        assert not juez.preguntas


class TestLasFechasEnLaMuestraDePdf:
    def test_el_pdf_de_la_muestra_lleva_las_filas_de_su_constancia(self, tmp_path):
        vista = _vista(tmp_path, "UPD1.pdf", [_fila("01.pdf", "30/08/2021"), _fila("02.pdf", "05/06/2021")])
        resultado = auditoria_api._auditar_uno(vista, None, {})
        assert resultado.estado == DUDOSO
        [hallazgo] = resultado.hallazgos
        assert hallazgo.startswith("«02.pdf»: la fecha 05/06/2021 no está escrita en el documento")
        assert resultado.extra["fechas"] == {"confirmadas": 1, "en duda": 1}

    def test_la_muestra_dice_como_quedaron_las_fechas_y_respeta_el_plazo(self, tmp_path, monkeypatch):
        vistas = [_vista(tmp_path, f"UPD{n}.pdf", []) for n in (1, 2, 3)]

        def auditar(entrega, juez, indices, *, juez_de_datos=None):
            if entrega.relativa == "UPD3.pdf":
                raise Cancelled("detenida mientras se le preguntaba a la IA")
            return PdfAuditado(entrega.relativa, BIEN, habilidad="", extra={"fechas": {"confirmadas": 2, "en duda": 1}})

        monkeypatch.setattr(auditoria_api, "_auditar_uno", auditar)
        plazos = []

        class _ConPlazo:
            def hasta(self, agotado):
                plazos.append(agotado)

        muestra = auditar_la_muestra(None, None, vistas, semilla=1, juez_de_datos=_ConPlazo(), tiempo_maximo=60)
        assert len(plazos) == 1 and plazos[0]() is False
        assert muestra["fechas"] == {
            "documentos": 6,
            "revisados": 6,
            "confirmadas": 4,
            "con error": 0,
            "en duda": 2,
            "sin fechas": 0,
        }
        detenido = next(p for p in muestra["pdfs"] if p["pdf"] == "UPD3.pdf")
        assert (detenido["estado"], detenido["hallazgos"]) == (NO_AUDITADO, ["la corrida se detuvo"])
        assert muestra["por_habilidad"][0]["fechas"]["confirmadas"] == 4
        assert muestra["preguntadas_a_la_ia"] == 0


# -- que la auditoría no trabe la corrida (2026-11-10) ----------------------------------------
#
# La revisión adversarial del revisor de fechas midió en Kingspan (UPD3854045,
# 284 hojas) 5,75 s la muestra de filas y 8,07 s la de PDF: cada punta que no
# encuentra su número vuelve a leer todas las hojas, y la muestra de PDF
# contrastaba cada documento dos veces. Y casar 1 600 PDF con sus filas, 10 s:
# cada PDF recorría todas las filas. Se fija lo que no depende de la máquina:
# cuántas veces se lee cada hoja y cuántas se contrasta cada documento.

from pathlib import PurePath  # noqa: E402
from random import Random  # noqa: E402

from resolutions.application import auditoria_de_filas as filas_app  # noqa: E402
from resolutions.application import revisor_de_fechas as revisor_app  # noqa: E402
from resolutions.domain import auditoria_de_filas as filas_del_dominio  # noqa: E402
from resolutions.domain import fechas as fechas_del_dominio  # noqa: E402
from resolutions.domain import fechas_extremas  # noqa: E402

#: Un UPD de Kingspan de 40 hojas, cada una con su número y su fecha.
_UPD = {
    p: f"COMPROBANTE DE EGRESO 001-CEE-{p:08d}\nCartagena, {p % 28 + 1:02d}/10/2023\npago a proveedores" for p in range(1, 41)
}


def _punta(numero: str, fecha: str) -> dict:
    return {
        entrega_app.DE_TODO_EL_ORIGINAL: True, "punta": f"COMPROBANTES DE EGRESO · {numero}", "su_numero": numero,
        "fecha_inicial": fecha, "fecha_final": fecha, "pagina_inicial": 1, "pagina_final": len(_UPD),
    }


#: Tres puntas cuyo número el OCR deformó -- caen a todo el original -- y una que está en la hoja 7.
_PUNTAS = [
    _punta("001-CEE-00009991", "02/10/2023"),
    _punta("001-CEE-00009992", "10/10/2023"),
    _punta("001-CEE-00009993", "28/10/2023"),
    _punta("001-CEE-00000007", "08/10/2023"),
]


def _la_fila_de_antes(archivo, filas):
    """``fila_del_archivo`` como era: cada PDF recorre todas las filas."""
    nombre = PurePath(str(archivo.nombre).replace("\\", "/")).name.upper()
    for fila in filas:
        generado = str(fila.get("archivo_generado") or "")
        if generado and PurePath(generado.replace("\\", "/")).name.upper() == nombre:
            return fila
    if archivo.primera is None:
        return None
    suyas = [
        fila
        for fila in filas
        if not fila.get("archivo_generado")
        and (paginas := entrega_app.paginas_de_la_fila(fila))
        and paginas[0] == archivo.primera
    ]
    return suyas[0] if len(suyas) == 1 else None


def _sin_lo_ya_leido() -> None:
    fechas_extremas._escritas.cache_clear()
    fechas_extremas._anios_escritos.cache_clear()
    fechas_extremas._fechas_propias.cache_clear()
    filas_del_dominio._basura.cache_clear()
    entrega_app._planos.cache_clear()


class TestLaAuditoriaNoTrabaLaCorrida:
    def test_las_puntas_que_caen_a_todo_el_original_leen_cada_hoja_una_vez(self, monkeypatch):
        """Antes: 3 × 40 + 1 hojas en la muestra de filas, y el doble en la de PDF; ahora, 40 + 1 en cada una."""
        leidas: list[str] = []
        original = fechas_del_dominio.fecha_de_la_pagina
        monkeypatch.setattr(
            fechas_del_dominio, "fecha_de_la_pagina", lambda texto, **k: leidas.append(texto) or original(texto, **k)
        )
        # La muestra de PDF.
        _sin_lo_ya_leido()
        de_pdf = entrega_app.auditar_las_fechas([], _UPD, _PUNTAS, regla="extremos")
        assert len(leidas) == len(_UPD) + 1
        assert de_pdf.cuentas == {"confirmadas": 4}
        # La muestra de filas, punta por punta, como la arma ``api/auditoria``.
        _sin_lo_ya_leido()
        leidas.clear()
        de_filas = []
        for punta in _PUNTAS:
            suyas = list(entrega_app.hojas_de_la_punta(punta, _UPD, (1, len(_UPD))))
            de_filas.append(filas_app.auditar_una_fila(punta["punta"], punta, suyas, habilidad="kingspan"))
        assert len(leidas) == len(_UPD) + 1
        assert [r.estado for r in de_filas] == [BIEN] * 4
        # La basura de sus hojas, una vez por documento: el original entero y la hoja 7.
        assert filas_del_dominio._basura.cache_info().misses == 2

    def test_el_texto_plano_de_cada_hoja_una_vez_por_documento(self, monkeypatch):
        llanos: list[object] = []
        original = entrega_app.plano
        monkeypatch.setattr(entrega_app, "plano", lambda texto: llanos.append(texto) or original(texto))
        _sin_lo_ya_leido()
        suyas = [entrega_app.hojas_de_la_punta(punta, _UPD, (1, len(_UPD))) for punta in _PUNTAS]
        assert [len(s) for s in suyas] == [40, 40, 40, 1] and suyas[3] == (_UPD[7],)
        # Su número, una vez por punta; cada hoja, una vez.
        assert len(llanos) == len(_PUNTAS) + len(_UPD)

    def test_la_muestra_de_pdf_contrasta_cada_documento_una_vez(self, monkeypatch):
        contrastes: list[int] = []
        original = entrega_app.contrastar_las_fechas

        def contado(*args, **kwargs):
            contrastes.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(entrega_app, "contrastar_las_fechas", contado)
        monkeypatch.setattr(revisor_app, "contrastar_las_fechas", contado)
        filas = [_fila("01.pdf", "12/01/2023"), _fila("02.pdf", "12/01/2023")]
        juez = _JuezDeDatos({"d1_fecha_inicial": VeredictoDeDato("no_esta", "Magangué, 30 de agosto de 2021")})
        resultado = auditar_un_pdf(
            "UPD1.pdf",
            [A, B],
            {1: CARTAS[1], 2: CARTAS[2]},
            {"01.pdf": [A], "02.pdf": [B]},
            filas_de_la_constancia=filas,
            juez_de_datos=juez,
        )
        assert len(contrastes) == 2
        # Y decide lo mismo: la IA corrige la del 01 citando su hoja, la del 02 queda en duda.
        assert resultado.extra["fechas"] == {"con error": 1, "en duda": 1}
        assert resultado.preguntadas_a_la_ia == 1

    def test_la_fila_de_cada_pdf_es_la_misma_que_elegia_antes(self):
        """Nombres repetidos, filas sin nombre en la misma hoja, nombres vacíos: el mismo casamiento, también en los empates."""
        azar = Random(5)
        for _ in range(400):
            archivos = [
                ArchivoEntregado(azar.choice(["a", "B", "c\\d", "D/E"]) + f"{azar.randint(0, 6)}.pdf", (azar.randint(1, 8),))
                for _ in range(azar.randint(1, 12))
            ] + [ArchivoEntregado("sin hojas.pdf", ())]
            filas: list[dict] = []
            for _ in range(azar.randint(0, 14)):
                fila: dict = {"fecha_inicial": "01/01/2020"}
                if azar.random() < 0.5:
                    fila["archivo_generado"] = azar.choice(["", None, f"X/{azar.choice('abcDE')}{azar.randint(0, 6)}.PDF"])
                if azar.random() < 0.7:
                    fila["pagina_inicial"] = azar.choice([azar.randint(1, 8), "3", None, 0])
                if azar.random() < 0.2:
                    fila = {"fuid": {"pagina_inicial": azar.randint(1, 8)}, "fecha_inicial": "01/01/2020"}
                filas.append(fila)
            la_suya = entrega_app.filas_por_archivo(filas)
            for archivo in archivos:
                assert la_suya(archivo) is _la_fila_de_antes(archivo, filas)
                assert entrega_app.fila_del_archivo(archivo, filas) is _la_fila_de_antes(archivo, filas)

    def test_mil_seiscientos_pdf_se_casan_leyendo_cada_fila_una_vez(self, monkeypatch):
        """Antes cada PDF recorría todas las filas: 1 600 × 1 600 páginas de fila calculadas."""
        calculadas: list[int] = []
        original = entrega_app.paginas_de_la_fila
        monkeypatch.setattr(entrega_app, "paginas_de_la_fila", lambda fila, *a: calculadas.append(1) or original(fila, *a))
        archivos = [ArchivoEntregado(f"{i:04d}_ACTA DE GRADO {i}.pdf", (i,)) for i in range(1, 1601)]
        filas = [{"pagina_inicial": i, "fecha": "17-12-2012"} for i in range(1, 1601)]
        la_suya = entrega_app.filas_por_archivo(filas)
        assert [la_suya(a) for a in archivos] == filas
        assert len(calculadas) == len(filas)


class TestLoLeidoFueraDeLaCapa:
    """La fecha leída a mano por la IA no es «no escrita» para la auditoría (3807860, 2026-11-11).

    La auditoría contrastaba la fecha entregada sólo con la capa del PDF, y la
    capa deja el «El Banco, 23 de 12 de 2020» manuscrito del reconocimiento en
    «ÜD _ , ^ de de»: el documento bien fechado salía dudoso.
    """

    CAPA = {
        1: "ÜD _ , ^ de de Grupo*epnp Señores: CARIBEMAR DE LA COSTA S.A.S E.S.P. La Ciudad Ref.: Reconocimiento "
        "de deuda y propuesta de acuerdo de pago Yo, identificado como aparece al pie de mi firma, reconozco "
        "como deuda clara, expresa y actualmente exigible a favor de CARIBEMAR DE LA COSTA la suma"
    }
    FILA = {"archivo_generado": "01_RECONOCIMIENTO.pdf", "fecha_inicial": "2020-12-23", "fecha_final": "2020-12-23"}

    def _auditar(self, lo_leido=()):
        from resolutions.domain.fechas_extremas import EXTREMOS

        return entrega_app.auditar_las_fechas(
            [ArchivoEntregado("01_RECONOCIMIENTO.pdf", (1,))], self.CAPA, [self.FILA], regla=EXTREMOS, lo_leido=lo_leido
        )

    def test_sin_lo_leido_la_fecha_a_mano_queda_en_duda(self):
        assert any("no está escrita" in duda for duda in self._auditar().dudas)

    def test_con_lo_que_leyo_la_ia_se_confirma(self):
        leido = [{"paginas": [1], "texto": "El Banco, 23 de 12 de 2020 Señores: CARIBEMAR Ref.: Reconocimiento de deuda"}]
        auditadas = self._auditar(leido)
        assert auditadas.dudas == [] and auditadas.errores == []

    def test_lo_leido_de_otra_hoja_no_cuenta(self):
        leido = [{"paginas": [7], "texto": "El Banco, 23 de 12 de 2020"}]
        assert any("no está escrita" in duda for duda in self._auditar(leido).dudas)

    def test_la_caja_guarda_solo_lo_que_no_esta_en_la_capa(self):
        from resolutions.api.worker.correspondencia import lo_leido_fuera_de_la_capa

        piezas = [
            {"fecha": "2020-12-23", "fecha_pagina": 4, "fecha_via": "ia"},
            {"fecha": "2023-12-20", "fecha_pagina": 9, "fecha_via": "sello"},
            {"fecha": "2021-05-03", "fecha_pagina": 12, "fecha_via": "texto"},
            {"fecha": "2022-01-14", "fecha_pagina": 15, "fecha_via": "texto"},
            {"fecha": None, "fecha_pagina": None},
        ]
        leido = lo_leido_fuera_de_la_capa(
            piezas, releidas={4: ["El Banco, 23 de 12 de 2020"]}, leidas_por_ocr={15: "Cartagena, 14/01/2022"}
        )
        assert leido == [
            {"paginas": [4], "texto": "El Banco, 23 de 12 de 2020"},
            {"paginas": [9], "texto": "SELLO DE RADICACION: 20/12/2023"},
            {"paginas": [15], "texto": "Cartagena, 14/01/2022"},
        ]

    def test_cada_relectura_va_aparte(self):
        # Juntas, el encabezado era el de la de Tesseract y la de la IA no se
        # leía: el reconocimiento de 1000883 salía en duda (2026-11-11).
        from resolutions.api.worker.correspondencia import lo_leido_fuera_de_la_capa
        from resolutions.domain.fechas_extremas import ESTRUCTURA

        tesseract = "Ci Cu lo ¡So de 03 de Zo22 Señores: CARIBEMAR Ref.: Reconocimiento de deuda"
        ia = "Magangué, 30 de 08 de 2022 Señores: CARIBEMAR Ref.: Reconocimiento de deuda y propuesta de acuerdo de pago"
        leido = lo_leido_fuera_de_la_capa(
            [{"fecha": "2022-08-30", "fecha_pagina": 1, "fecha_via": "ia"}], releidas={1: [tesseract, ia]}, leidas_por_ocr={}
        )
        assert [x["texto"] for x in leido] == [tesseract, ia]
        fila = {"archivo_generado": "01_RECONOCIMIENTO.pdf", "fecha_inicial": "2022-08-30", "fecha_final": "2022-08-30"}
        auditadas = entrega_app.auditar_las_fechas(
            [ArchivoEntregado("01_RECONOCIMIENTO.pdf", (1,))], self.CAPA, [fila], regla=ESTRUCTURA, lo_leido=leido
        )
        assert auditadas.dudas == [] and auditadas.errores == []

    def test_con_la_regla_de_la_caja_tambien_se_confirma(self):
        from resolutions.domain.fechas_extremas import ESTRUCTURA

        leido = [{"paginas": [1], "texto": "El Banco, 23 de 12 de 2020 Señores: CARIBEMAR Ref.: Reconocimiento de deuda"}]
        auditadas = entrega_app.auditar_las_fechas(
            [ArchivoEntregado("01_RECONOCIMIENTO.pdf", (1,))], self.CAPA, [self.FILA], regla=ESTRUCTURA, lo_leido=leido
        )
        assert auditadas.dudas == [] and auditadas.errores == []

    def test_la_constancia_lo_guarda_y_la_vieja_se_lee_sin_el(self, tmp_path):
        import json

        from resolutions.api import constancia as constancias

        ruta = tmp_path / ".bot-entrega-UPD1.json"
        constancias.escribir(ruta, constancias.Constancia("UPD1.pdf", 1, 1, lo_leido=[{"paginas": [4], "texto": "x"}]))
        assert constancias.leer(ruta).lo_leido == [{"paginas": [4], "texto": "x"}]
        # La de antes del 2026-11-11, sin el campo (en otro archivo: Windows no deja pisar la oculta).
        vieja = {k: v for k, v in json.loads(ruta.read_text(encoding="utf-8")).items() if k != "lo_leido"}
        otra = tmp_path / "vieja.json"
        otra.write_text(json.dumps(vieja), encoding="utf-8")
        assert constancias.leer(otra).lo_leido == []