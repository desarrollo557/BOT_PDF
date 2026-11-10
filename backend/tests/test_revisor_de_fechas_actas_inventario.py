"""El revisor de fechas en los trabajos de inventario: actas de consejo y de grado, el archivo entero y el FUID.

Lo pidió el operador el 2026-11-10: «estar muy seguro de cada fecha en cada
documento, sin importar la habilidad», «corregir sólo con prueba» (si no, a
Revisión con su motivo) y «saber manejar un margen de errores». Aquí se fija
cómo lo hacen ``_acta_consejo_job``, ``_inventory_file_job`` y
``_inventory_job`` (``api/worker/inventario.py``):

- lo que el papel confirma queda como está;
- lo que el papel contradice con dos pruebas se corrige, en el formato de su
  fila, con el aviso en el informe (en las actas, no en sus «Observaciones»,
  que van en el Excel que se entrega);
- lo que cae dentro del margen (un dígito, o una fecha escrita pero que no es la
  de la regla) va a Revisión con su motivo, o a la IA si la corrida la tiene;
- un fallo del revisor no tumba el trabajo, y la cancelación sí se propaga.

Los PDF llevan capa de texto, hechos con pymupdf: ninguna prueba lee con OCR ni
le habla a un proveedor.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from resolutions.application.control import Cancelled, NullRunControl
from resolutions.application.fuid import FuidRow
from resolutions.application.ports import VeredictoDeDato


def hoja(texto: str) -> str:
    """Una hoja del acta, con el membrete y el pie que llevan todas."""
    return (
        f"Universidad\nde Cartagena\nFundada en 1827\n{texto}\n"
        "Facultad de Odontologia - Departamento Academico"
    )


# El acta del ejemplo del operador (17 de diciembre de 2012), recortada, con la
# próxima reunión escrita: una fecha que está en el papel y no es la de la sesión.
CITACION = (
    "Universidad\nde Cartagena\nCONSEJO DE FACULTAD\nSESION ORDINARIA\n"
    "FECHA: LUNES 17 DE DICIEMBRE DE 2012\nLUGAR: DECANATURA\nHORA: 09:30 HORAS.\n"
    "ORDEN DEL DIA:\n1. LLAMADO A LISTA Y VERIFICACION DEL QUORUM\n2. ASUNTOS ACADEMICOS"
)
ENCABEZADO = hoja(
    "ACTA ORDINARIA No. 022 \nLunes 17 de diciembre de 2012\nCONSEJO DE FACULTAD\n"
    "Fecha\n17 de diciembre 2012\nDra. LUISA AREVALO TOVAR- DECANA"
)
CUERPO = hoja(
    "Acta No. 022-2012 \nConsejo de Facultad\n"
    "1, LLAMADO A LISTA Y VERIFICACION DEL\nQUORUM\n"
    "La senora decana da inicio a la sesion y se verifica el quorum.\n"
    "Proxima reunion: 05 de diciembre de 2012."
)
CIERRE = hoja("Siendo las 11:30 a.m., finaliza la sesion.\nLa presente acta consta de 3 folios")
ACTA = [CITACION, ENCABEZADO, CUERPO, CIERRE]

NOTA_DE_AJUSTE = (
    "NOTA DE AJUSTE No. 118\nCartagena, 15 de marzo de 2019\n"
    "Se ajusta el valor facturado del periodo segun lo acordado con el cliente.\n"
    "Recibido en la oficina de cartera el 20 de abril de 2019."
)


def _pdf(destino: Path, paginas: list[str]) -> Path:
    import fitz

    with fitz.open() as doc:
        for texto in paginas:
            doc.new_page().insert_text((30, 50), texto, fontsize=8)
        doc.save(destino)
    return destino


def _payload(origen: Path, salida: Path, task: str = "inventory") -> dict:
    return {
        "job_id": "t",
        "source": str(origen),
        "filename": origen.name,
        "task": task,
        "settings": {"ocr_language": "spa", "output_dir": str(salida)},
    }


@pytest.fixture
def acta(tmp_path) -> dict:
    return _payload(_pdf(tmp_path / "acta.pdf", ACTA), tmp_path / "salida")


def _con_la_fecha(monkeypatch, fecha: str) -> None:
    """La lectura del acta deja en la fila otra fecha: lo que haría un OCR o un respaldo equivocado."""
    from resolutions.application import acta_consejo

    original = acta_consejo.InventariarActa.execute

    def leida(self, *args, **kwargs):
        outcome = original(self, *args, **kwargs)
        outcome.filas = [replace(fila, fecha=fecha) for fila in outcome.filas]
        return outcome

    monkeypatch.setattr(acta_consejo.InventariarActa, "execute", leida)


class JuezFalso:
    """La IA de mentira: contesta lo que se le diga y cuenta las preguntas."""

    def __init__(self, respuesta: dict[str, VeredictoDeDato] | None) -> None:
        self.respuesta = respuesta
        self.preguntas: list[list[dict[str, str]]] = []

    def verificar(self, texto: str, datos: list[dict[str, str]]):
        self.preguntas.append(datos)
        return self.respuesta


# -----------------------------------------------------------------------------
#  Actas de consejo: la fecha de la apertura de la sesión
# -----------------------------------------------------------------------------


class TestLasActasDeConsejo:
    def test_la_fecha_que_dice_el_papel_se_confirma(self, acta):
        from resolutions.api.worker import inventario as trabajo

        informe = trabajo._acta_consejo_job(acta)

        revision = informe["revision_de_fechas"]
        assert revision["revisados"] == len(informe["inventario_actas"]) == 1
        assert revision["confirmada"] == 1
        assert revision["corregida"] == revision["a revisión"] == 0
        assert informe["inventario_actas"][0]["fecha"] == "17-12-2012"
        assert not any("revisor de fechas" in r["reason"] for r in informe.get("review_queue", []))

    def test_corrige_con_dos_pruebas_y_en_el_formato_de_la_fila(self, acta, monkeypatch):
        """La apertura dice 17/12/2012 y el 17/11/2011 de la fila no está escrito en ninguna parte."""
        from resolutions.api.worker import inventario as trabajo

        _con_la_fecha(monkeypatch, "17-11-2011")

        informe = trabajo._acta_consejo_job(acta)

        fila = informe["inventario_actas"][0]
        assert fila["fecha"] == "17-12-2012"
        # La nota de la prueba no va a «Observaciones» del Excel de actas, que se
        # entrega (la revisión, 2026-11-10): queda en el aviso y en la cuenta.
        assert "corregida" not in (fila.get("observaciones") or "")
        assert informe["revision_de_fechas"]["corregida"] == 1
        assert any(aviso.startswith("Fecha corregida en") for aviso in informe["notices"])
        # La pantalla de Archivo lee la fecha de la primera acta del informe.
        assert informe["fecha_inicial"] == informe["fecha_final"] == "17-12-2012"
        # Y el Excel y el FUID salieron con ella.
        assert informe.get("inventario") and informe.get("fuid_de_actas")

    def test_el_pdf_de_la_sesion_se_llama_con_la_fecha_corregida(self, tmp_path, monkeypatch):
        """El PDF se llama por su acta y su fecha: corregida, sale con la corregida (P1-1, 2026-11-10).

        Antes el revisor corría después de dividir: la fila y el FUID decían
        17-12-2012 y el PDF seguía llamándose «…-17-11-2011.pdf».
        """
        from resolutions.api.worker import inventario as trabajo
        from resolutions.application import acta_consejo

        segunda = [
            "Universidad\nde Cartagena\nCONSEJO DE FACULTAD\nSESION ORDINARIA\n"
            "FECHA: LUNES 21 DE ENERO DE 2013\nLUGAR: DECANATURA\nHORA: 09:30 HORAS.\nORDEN DEL DIA:\n1. LLAMADO A LISTA",
            hoja("ACTA ORDINARIA No. 001 \nLunes 21 de enero de 2013\nCONSEJO DE FACULTAD\nFecha\n21 de enero 2013"),
            hoja("Acta No. 001-2013 \nConsejo de Facultad\nLa senora decana da inicio a la sesion."),
            hoja("Siendo las 11:30 a.m., finaliza la sesion.\nLa presente acta consta de 3 folios"),
        ]
        original = acta_consejo.InventariarActa.execute

        def leida(self, *args, **kwargs):
            # La lectura deja otra fecha en la primera acta, y su sesión se
            # llama por ella, como al leerla de verdad.
            outcome = original(self, *args, **kwargs)
            outcome.filas = [replace(outcome.filas[0], fecha="17-11-2011"), *outcome.filas[1:]]
            outcome.sesiones = [
                replace(outcome.sesiones[0], nombre=acta_consejo.nombre_de_la_sesion(outcome.filas[0])),
                *outcome.sesiones[1:],
            ]
            return outcome

        monkeypatch.setattr(acta_consejo.InventariarActa, "execute", leida)
        payload = _payload(_pdf(tmp_path / "libro.pdf", ACTA + segunda), tmp_path / "salida", task="both")

        informe = trabajo._acta_consejo_job(payload)

        primera = informe["inventario_actas"][0]
        assert primera["fecha"] == "17-12-2012"
        assert informe["outputs"][0].endswith("17-12-2012.pdf")
        assert "17-12-2012.pdf" in primera["resultado"]
        escritos = sorted(ruta.name for ruta in (tmp_path / "salida").rglob("*.pdf"))
        assert not any("2011" in nombre for nombre in escritos)
        assert informe["sesiones"][0]["nombre"].endswith("17-12-2012")

    def test_un_digito_es_margen_del_ocr_y_va_a_revision(self, acta, monkeypatch):
        from resolutions.api.worker import inventario as trabajo

        _con_la_fecha(monkeypatch, "17-12-2013")

        informe = trabajo._acta_consejo_job(acta)

        assert informe["inventario_actas"][0]["fecha"] == "17-12-2013"
        assert informe["revision_de_fechas"]["a revisión"] == 1
        motivos = [r["reason"] for r in informe["review_queue"] if "revisor de fechas" in r["reason"]]
        assert motivos and "17/12/2012" in motivos[0]

    def test_una_fecha_escrita_que_no_es_la_de_la_sesion_no_se_corrige_sin_ia(
        self, acta, monkeypatch
    ):
        """El 05/12/2012 está en el papel (la próxima reunión): una sola prueba, a Revisión."""
        from resolutions.api.worker import inventario as trabajo

        _con_la_fecha(monkeypatch, "05-12-2012")

        informe = trabajo._acta_consejo_job(acta)

        assert informe["inventario_actas"][0]["fecha"] == "05-12-2012"
        assert informe["revision_de_fechas"]["a revisión"] == 1
        assert informe["revision_de_fechas"]["detalle"][0]["estado"] == "a revisión"

    def test_la_ia_corrige_citando_el_papel_en_una_pregunta(self, acta, monkeypatch):
        from resolutions.api.worker import inventario as trabajo
        from resolutions.api.worker.taller import Taller

        _con_la_fecha(monkeypatch, "05-12-2012")
        cita = VeredictoDeDato("no_esta", cita="Lunes 17 de diciembre de 2012")
        juez = JuezFalso({"fecha_inicial": cita, "fecha_final": cita})
        monkeypatch.setattr(Taller, "juez_de_datos", lambda self: juez)

        informe = trabajo._acta_consejo_job(acta)

        assert informe["inventario_actas"][0]["fecha"] == "17-12-2012"
        revision = informe["revision_de_fechas"]
        assert revision["corregida"] == 1 and revision["preguntadas_a_la_ia"] == 2
        # Una sola pregunta por documento, con lo dudoso y nada más.
        assert len(juez.preguntas) == 1
        assert {d["campo"] for d in juez.preguntas[0]} == {"fecha_inicial", "fecha_final"}

    def test_la_ia_no_se_paga_si_el_papel_ya_confirma(self, acta, monkeypatch):
        from resolutions.api.worker import inventario as trabajo
        from resolutions.api.worker.taller import Taller

        juez = JuezFalso(None)
        monkeypatch.setattr(Taller, "juez_de_datos", lambda self: juez)

        informe = trabajo._acta_consejo_job(acta)

        assert informe["revision_de_fechas"]["confirmada"] == 1
        assert juez.preguntas == []

    def test_un_fallo_del_revisor_no_tumba_el_trabajo(self, acta, monkeypatch):
        from resolutions.api.worker import inventario as trabajo
        from resolutions.application import revisor_de_fechas

        def roto(*_a, **_k):
            raise RuntimeError("el revisor se cayó")

        monkeypatch.setattr(revisor_de_fechas, "revisar_las_fechas", roto)

        informe = trabajo._acta_consejo_job(acta)

        assert informe["inventario_actas"][0]["fecha"] == "17-12-2012"
        assert informe.get("inventario"), informe.get("inventario_error")
        assert "revision_de_fechas" not in informe

    def test_la_cancelacion_si_se_propaga(self, acta, monkeypatch):
        from resolutions.api.worker import inventario as trabajo
        from resolutions.application import revisor_de_fechas

        def cancelado(*_a, **_k):
            raise Cancelled("el operador canceló")

        monkeypatch.setattr(revisor_de_fechas, "revisar_las_fechas", cancelado)

        with pytest.raises(Cancelled):
            trabajo._acta_consejo_job(acta)


# -----------------------------------------------------------------------------
#  Actas de grado: la fecha del acta
# -----------------------------------------------------------------------------

ACTA_DE_GRADO = (
    "UNIVERSIDAD DE CARTAGENA\nACTA DE GRADO N°. 054231116\n"
    "En la ciudad de Cartagena de Indias, a los doce (12) dias del mes de "
    "Diciembre del año 2023, se reunieron en ceremonia de graduacion..."
)


class TestLasActasDeGrado:
    def test_cada_graduado_con_su_fecha_revisada(self, tmp_path):
        from resolutions.api.worker import inventario as trabajo

        payload = _payload(_pdf(tmp_path / "grado.pdf", [ACTA_DE_GRADO]), tmp_path / "salida")

        informe = trabajo._acta_consejo_job(payload, grado=True)

        revision = informe["revision_de_fechas"]
        assert revision["revisados"] == len(informe["inventario_actas"])
        filas_con_fecha = [f for f in informe["inventario_actas"] if f["fecha"] not in ("", "N/A")]
        assert revision["confirmada"] == len(filas_con_fecha) >= 1
        assert revision["corregida"] == revision["a revisión"] == 0


# -----------------------------------------------------------------------------
#  El archivo entero: la más antigua y la más reciente
# -----------------------------------------------------------------------------


class TestElArchivoEntero:
    def test_las_fechas_extremas_que_dice_el_papel_se_confirman(self, tmp_path):
        from resolutions.api.worker import inventario as trabajo

        payload = _payload(_pdf(tmp_path / "nota.pdf", [NOTA_DE_AJUSTE]), tmp_path / "salida")

        informe = trabajo._inventory_file_job(payload)

        assert informe["revision_de_fechas"]["confirmada"] == 1
        assert (informe["fecha_inicial"], informe["fecha_final"]) == ("15-03-2019", "20-04-2019")

    def test_una_fecha_que_no_esta_en_el_papel_va_a_revision_sin_tocarla(
        self, tmp_path, monkeypatch
    ):
        """Sin lector fuerte -- los extremos -- no hay segunda prueba: no se corrige."""
        from resolutions.api.worker import inventario as trabajo
        from resolutions.application import inventory_file

        original = inventory_file.InventoryFile.execute

        def leida(self, *args, **kwargs):
            outcome = original(self, *args, **kwargs)
            outcome.row = replace(outcome.row, fecha_final="20-06-2018")
            return outcome

        monkeypatch.setattr(inventory_file.InventoryFile, "execute", leida)
        payload = _payload(_pdf(tmp_path / "nota.pdf", [NOTA_DE_AJUSTE]), tmp_path / "salida")

        informe = trabajo._inventory_file_job(payload)

        assert informe["fecha_final"] == "20-06-2018"
        assert informe["revision_de_fechas"]["a revisión"] == 1
        assert any("20/06/2018" in r["reason"] for r in informe["review_queue"])

    def test_con_paginas_leidas_por_ocr_la_capa_no_prueba_nada_en_contra(
        self, tmp_path, monkeypatch
    ):
        """La fecha salió de una página que se leyó por OCR: sin ese texto no hay motivo ni prueba."""
        from resolutions.api.worker import inventario as trabajo
        from resolutions.application import inventory_file

        original = inventory_file.InventoryFile.execute

        def leida(self, *args, **kwargs):
            outcome = original(self, *args, **kwargs)
            outcome.row = replace(outcome.row, fecha_final="20-06-2018")
            outcome.ocr_pages = 1
            return outcome

        monkeypatch.setattr(inventory_file.InventoryFile, "execute", leida)
        payload = _payload(_pdf(tmp_path / "nota.pdf", [NOTA_DE_AJUSTE]), tmp_path / "salida")

        informe = trabajo._inventory_file_job(payload)

        revision = informe["revision_de_fechas"]
        assert revision["sin dato"] == 1 and revision["a revisión"] == 0
        assert not any("revisor de fechas" in r["reason"] for r in informe.get("review_queue", []))


# -----------------------------------------------------------------------------
#  Las filas del FUID de `_inventory_job`: cada habilidad, su regla y su formato
# -----------------------------------------------------------------------------

#: Con su número y su año en el encabezado: sin el año, la fórmula no es lector
#: fuerte (podría ser la de la copia que viene detrás; la revisión, 2026-11-10).
RESOLUCION = (
    "RESOLUCION No. 045 DE 2011\nEl Rector de la Universidad de Cartagena, en uso de sus facultades,\n"
    "RESUELVE\nARTICULO PRIMERO: Aprobar el calendario academico del periodo.\n"
    "Dada en Cartagena de Indias, a los quince (15) dias del mes de marzo de 2011.\n"
    "COMUNIQUESE Y CUMPLASE"
)


def _revisor(habilidad: str, juez=None):
    from resolutions.api.worker.inventario import _RevisorDeFechas

    taller = SimpleNamespace(control=NullRunControl(), juez_de_datos=lambda: juez)
    return _RevisorDeFechas(taller, habilidad)


class TestLasFilasDelFuid:
    def test_la_resolucion_se_corrige_por_su_formula_de_expedicion(self):
        from resolutions.api.worker.inventario import _revisar_las_filas_del_fuid

        revisor = _revisor("resoluciones")
        fila = FuidRow(
            orden=1, asunto="RESOLUCION 045", fecha_inicial="01-06-2009",
            fecha_final="01-06-2009", pagina_inicial=1,
        )

        (hecha,) = _revisar_las_filas_del_fuid(
            revisor, [fila], {1: [1]}, {1: RESOLUCION}, completas=True, minimo=80
        )

        assert (hecha.fecha_inicial, hecha.fecha_final) == ("15-03-2011", "15-03-2011")
        assert "fórmula de expedición" in hecha.notas
        informe: dict = {}
        revisor.anotar(informe)
        assert informe["revision_de_fechas"]["corregida"] == 1

    def test_sin_el_anio_en_su_encabezado_la_formula_no_corrige(self):
        """Sin «DE 2011» en el encabezado la fórmula no prueba que sea de esta resolución: a Revisión."""
        from resolutions.api.worker.inventario import _revisar_las_filas_del_fuid

        revisor = _revisor("resoluciones")
        fila = FuidRow(
            orden=1, asunto="RESOLUCION 045", fecha_inicial="01-06-2009",
            fecha_final="01-06-2009", pagina_inicial=1,
        )
        sin_anio = RESOLUCION.replace("RESOLUCION No. 045 DE 2011", "RESOLUCION No. 045")

        (hecha,) = _revisar_las_filas_del_fuid(
            revisor, [fila], {1: [1]}, {1: sin_anio}, completas=True, minimo=80
        )

        assert (hecha.fecha_inicial, hecha.fecha_final) == ("01-06-2009", "01-06-2009")
        informe: dict = {}
        revisor.anotar(informe)
        assert informe["revision_de_fechas"]["corregida"] == 0

    def test_una_capa_corta_no_es_lo_que_se_leyo(self):
        """Con menos de 80 caracteres la página se leyó por OCR: sin ese texto, sin dato."""
        from resolutions.api.worker.inventario import _revisar_las_filas_del_fuid

        revisor = _revisor("resoluciones")
        fila = FuidRow(
            orden=1, asunto="RESOLUCION 045", fecha_inicial="01-06-2009",
            fecha_final="01-06-2009", pagina_inicial=1,
        )

        (hecha,) = _revisar_las_filas_del_fuid(
            revisor, [fila], {1: [1, 2]}, {1: RESOLUCION, 2: "folio 2"},
            completas=True, minimo=80,
        )

        assert hecha.fecha_inicial == "01-06-2009"
        assert revisor.revisiones[0][2].estado == "sin dato"

    def test_la_matricula_confirma_sus_anios(self):
        from resolutions.api.worker.inventario import _revisar_las_filas_del_fuid

        revisor = _revisor("matriculas")
        texto = "REGISTRO DE MATRICULA\nPRIMER AÑO 1.950\nSEXTO AÑO 1.955\n" + "x" * 80
        fila = FuidRow(
            orden=1, asunto="PEREZ JUAN", fecha_inicial="1950", fecha_final="1955",
            pagina_inicial=3,
        )

        (hecha,) = _revisar_las_filas_del_fuid(
            revisor, [fila], {3: [3]}, {3: texto}, completas=True, minimo=80
        )

        assert hecha == fila
        assert revisor.revisiones[0][2].estado == "confirmada"

    def test_una_fila_sin_fechas_queda_sin_dato(self):
        from resolutions.api.worker.inventario import _revisar_las_filas_del_fuid

        revisor = _revisor("diplomas")
        fila = FuidRow(orden=1, asunto="SIN FECHA", pagina_inicial=1)

        _revisar_las_filas_del_fuid(revisor, [fila], {1: [1]}, {1: "x" * 100}, completas=True, minimo=80)

        assert revisor.revisiones[0][2].estado == "sin dato"


class TestElFormatoDeCadaFila:
    @pytest.mark.parametrize(
        ("molde", "campo", "precision", "esperada"),
        [
            ("01-06-2009", "fecha_inicial", "dia", "15-03-2011"),
            ("01/06/2009", "fecha_inicial", "dia", "15/03/2011"),
            ("2009-06-01", "fecha_final", "dia", "2011-03-15"),
            ("1950", "fecha_inicial", "anio", "2011"),
            # Un año escrito como día lleva el relleno del año.
            ("01/01/1977", "fecha_inicial", "anio", "01/01/2011"),
            ("31/12/1983", "fecha_final", "anio", "31/12/2011"),
            ("N/A", "fecha_inicial", "dia", "15-03-2011"),
        ],
    )
    def test_se_escribe_como_la_escribe_su_fila(self, molde, campo, precision, esperada):
        from datetime import date

        from resolutions.api.worker.inventario import _en_su_formato

        assert _en_su_formato(molde, date(2011, 3, 15), precision, campo) == esperada


class TestLasPaginasDeCadaFila:
    def test_por_su_grupo_o_hasta_la_siguiente(self):
        from resolutions.api.worker.inventario import _paginas_de_cada_fila

        outcome = SimpleNamespace(
            grouping=SimpleNamespace(groups=[SimpleNamespace(page_numbers=(1, 2))]),
            rows=[
                FuidRow(orden=1, asunto="A", pagina_inicial=1),
                FuidRow(orden=2, asunto="B", pagina_inicial=4),
                FuidRow(orden=3, asunto="C", pagina_inicial=6),
            ],
            page_count=7,
        )

        assert _paginas_de_cada_fila(outcome) == {1: [1, 2], 4: [4, 5], 6: [6, 7]}

    def test_todo_por_la_capa(self):
        from resolutions.api.worker.inventario import _todo_por_la_capa

        assert _todo_por_la_capa({"text_layer": 12})
        assert not _todo_por_la_capa({"text_layer": 10, "local_ocr": 2})
        assert not _todo_por_la_capa({})
