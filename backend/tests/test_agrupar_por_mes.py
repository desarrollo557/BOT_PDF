"""Caja de correspondencia: un archivo por mes en vez de uno por documento.

El corte no cambia. Lo que el operador elige es qué se entrega después, y lo
fue precisando con el papel delante: que la OCR busque la fecha **en cada
página**; que las páginas del **mismo mes** se unan, aunque sean de días
distintos y estén separadas en la caja; y que la página sin fecha se una **a la
anterior**. La que queda entre dos meses distintos se declara en revisión.

Estas pruebas fijan esas reglas, que la fecha sale de la OCR cuando la página es
un escaneo, que con la opción apagada no cambia nada, y que la elección viaja
desde la pantalla hasta el worker por los dos caminos: la subida y la carpeta.
"""

from __future__ import annotations

import time
from datetime import date

import pytest
from fakes import FakeOcr, FakePage, FakePageSource

from resolutions.application.agrupacion import (
    Agrupacion,
    agrupar_por_mes,
    leer_paginas,
    mes_de,
)
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode


def documento(codigo: str, paginas: list[int], tipo: str = "OFICIO") -> PageGroup:
    return PageGroup(
        code=ResolutionCode(value=codigo, raw=codigo),
        page_numbers=paginas,
        title=f"páginas {paginas[0]}-{paginas[-1]}",
        kind=tipo,
    )


def caja(*documentos: PageGroup) -> GroupingResult:
    return GroupingResult(groups=list(documentos))


def un_documento_por_pagina(paginas: int) -> GroupingResult:
    return caja(*(documento(f"{n:02d}", [n]) for n in range(1, paginas + 1)))


def d(texto: str) -> date:
    return date.fromisoformat(texto)


class TestLaEleccion:
    def test_por_omision_es_un_archivo_por_documento(self):
        """Lo que hacía la habilidad antes de que existiera la elección."""
        assert Agrupacion.parse(None) is Agrupacion.DOCUMENTO
        assert Agrupacion.parse("") is Agrupacion.DOCUMENTO

    def test_no_distingue_mayusculas_ni_espacios(self):
        assert Agrupacion.parse("  MES ") is Agrupacion.MES

    def test_lo_desconocido_no_se_adivina(self):
        with pytest.raises(ValueError, match="documento, mes"):
            Agrupacion.parse("semana")

    def test_el_mes_de_una_fecha(self):
        assert mes_de(d("2023-05-28")) == "2023-05"
        assert mes_de("2023-05-28") == "2023-05"


class TestUnMesEsUnArchivo:
    def test_paginas_de_dias_distintos_del_mismo_mes_van_juntas(self):
        """«diferentes fechas, mismo mes, agruparlos»."""
        grupos = agrupar_por_mes(
            un_documento_por_pagina(3),
            {1: d("2023-05-03"), 2: d("2023-05-15"), 3: d("2023-05-28")},
        ).grupos
        assert [grupo.page_numbers for grupo in grupos.groups] == [[1, 2, 3]]

    def test_se_unen_aunque_esten_separadas_por_otro_mes(self):
        grupos = agrupar_por_mes(
            un_documento_por_pagina(4),
            {1: d("2023-05-03"), 2: d("2023-05-10"), 3: d("2023-06-07"), 4: d("2023-05-28")},
        ).grupos
        assert [grupo.code.value for grupo in grupos.groups] == ["2023-05", "2023-06"]
        assert [grupo.page_numbers for grupo in grupos.groups] == [[1, 2, 4], [3]]

    def test_la_fecha_es_de_cada_pagina_y_no_del_documento(self):
        """Un documento del corte cuyas hojas son de dos meses se reparte entre los dos."""
        grupos = agrupar_por_mes(
            caja(documento("01", [1, 2, 3])),
            {1: d("2023-05-03"), 2: d("2023-06-07"), 3: d("2023-06-08")},
        ).grupos
        assert [grupo.page_numbers for grupo in grupos.groups] == [[1], [2, 3]]

    def test_meses_distintos_quedan_en_archivos_distintos(self):
        grupos = agrupar_por_mes(
            un_documento_por_pagina(2), {1: d("2023-05-31"), 2: d("2023-06-01")}
        ).grupos
        assert len(grupos.groups) == 2

    def test_el_mismo_mes_de_otro_ano_es_otro_archivo(self):
        grupos = agrupar_por_mes(
            un_documento_por_pagina(2), {1: d("2023-05-03"), 2: d("2024-05-03")}
        ).grupos
        assert [grupo.code.value for grupo in grupos.groups] == ["2023-05", "2024-05"]

    def test_los_archivos_salen_en_orden_de_mes(self):
        """Así el informe y la carpeta listan igual, y la carpeta es cronológica."""
        grupos = agrupar_por_mes(
            un_documento_por_pagina(2), {1: d("2023-06-01"), 2: d("2023-05-03")}
        ).grupos
        assert [grupo.code.value for grupo in grupos.groups] == ["2023-05", "2023-06"]

    def test_la_fecha_del_archivo_es_la_mas_reciente_de_sus_paginas(self):
        """La columna Fecha del inventario es la fecha extrema final de la unidad."""
        [grupo] = agrupar_por_mes(
            un_documento_por_pagina(3),
            {1: d("2023-05-03"), 2: d("2023-05-28"), 3: d("2023-05-15")},
        ).grupos.groups
        assert grupo.fecha == "2023-05-28"

    def test_cada_pagina_queda_en_un_solo_archivo(self):
        agrupar_por_mes(
            un_documento_por_pagina(5),
            {1: d("2023-05-03"), 2: None, 3: d("2023-06-07"), 4: d("2023-05-28"), 5: None},
        ).grupos.verify_integrity(5)


class TestLaPaginaSinFecha:
    def test_se_une_a_la_anterior(self):
        grupos = agrupar_por_mes(
            un_documento_por_pagina(4),
            {1: d("2023-05-03"), 2: d("2023-06-07"), 3: None, 4: d("2023-06-20")},
        ).grupos
        assert [grupo.page_numbers for grupo in grupos.groups] == [[1], [2, 3, 4]]

    def test_entre_dos_paginas_del_mismo_mes_no_se_manda_a_revision(self):
        """Ahí unirla a la anterior no es una elección: no pudo ser de otro mes."""
        resultado = agrupar_por_mes(
            un_documento_por_pagina(3), {1: d("2023-05-03"), 2: None, 3: d("2023-05-20")}
        )
        assert [pagina.page for pagina in resultado.sin_fecha] == [2]
        assert resultado.en_revision == []

    def test_entre_dos_meses_distintos_se_declara_para_revision(self):
        resultado = agrupar_por_mes(
            un_documento_por_pagina(3), {1: d("2023-05-03"), 2: None, 3: d("2023-06-07")}
        )
        [dudosa] = resultado.en_revision
        assert dudosa.page == 2
        assert dudosa.mes == "2023-05"
        assert dudosa.motivo == "sin fecha legible: se unió al mes 2023-05, el de la página anterior"

    def test_la_ultima_de_la_caja_no_tiene_con_que_dudar(self):
        resultado = agrupar_por_mes(un_documento_por_pagina(2), {1: d("2023-05-03"), 2: None})
        assert resultado.en_revision == []

    def test_la_primera_de_la_caja_se_une_a_la_siguiente_y_se_declara(self):
        resultado = agrupar_por_mes(un_documento_por_pagina(2), {1: None, 2: d("2023-06-07")})
        assert [grupo.page_numbers for grupo in resultado.grupos.groups] == [[1, 2]]
        [primera] = resultado.en_revision
        assert primera.al_anterior is False
        assert "siguiente" in primera.motivo

    def test_no_le_cambia_la_fecha_al_archivo(self):
        [grupo] = agrupar_por_mes(
            un_documento_por_pagina(2), {1: d("2023-05-03"), 2: None}
        ).grupos.groups
        assert grupo.fecha == "2023-05-03"

    def test_sin_ninguna_fecha_en_la_caja_no_se_toca_nada(self):
        """Juntarlas sería tratar la ausencia de un dato como un mismo mes."""
        original = un_documento_por_pagina(2)
        resultado = agrupar_por_mes(original, {1: None, 2: None})

        assert resultado.grupos.groups == original.groups
        assert resultado.sin_fecha == []
        assert resultado.agrupo is False
        assert "ninguna página" in resultado.aviso()


class TestComoSeNombraElArchivo:
    def test_el_codigo_es_el_mes(self):
        """Hay un archivo por mes, así que el mes es su identidad."""
        [grupo] = agrupar_por_mes(un_documento_por_pagina(1), {1: d("2023-05-03")}).grupos.groups
        assert grupo.code.value == "2023-05"

    def test_lleva_el_tipo_cuando_todas_sus_paginas_lo_comparten(self):
        [grupo] = agrupar_por_mes(
            caja(documento("01", [1], "FACTURA"), documento("02", [2], "FACTURA")),
            {1: d("2023-05-03"), 2: d("2023-05-20")},
        ).grupos.groups
        assert grupo.kind == "FACTURA"
        assert grupo.title == "FACTURA"

    def test_si_mezcla_tipos_no_se_nombra_por_ninguno(self):
        """Un oficio con una factura no es ninguna de las dos cosas."""
        [grupo] = agrupar_por_mes(
            caja(documento("01", [1], "OFICIO"), documento("02", [2], "FACTURA")),
            {1: d("2023-05-03"), 2: d("2023-05-20")},
        ).grupos.groups
        assert grupo.kind == "DOCUMENTO"
        assert grupo.title == "OFICIO; FACTURA"

    def test_sin_nada_que_declarar_el_titulo_dice_los_tramos(self):
        """Y no un rango: «páginas 1-4» diría que trae la hoja 3, que es de otro mes."""
        [primero, _] = agrupar_por_mes(
            caja(*(documento(f"{n:02d}", [n], "DOCUMENTO") for n in range(1, 5))),
            {1: d("2023-05-03"), 2: d("2023-05-04"), 3: d("2023-06-07"), 4: d("2023-05-28")},
        ).grupos.groups
        assert primero.title == "páginas 1-2, 4"

    def test_el_titulo_dice_el_tipo_y_el_asunto_de_cada_documento(self):
        """Lo que el operador pidió ver junto al tipo documental."""
        [grupo] = agrupar_por_mes(
            un_documento_por_pagina(3),
            {1: d("2021-05-25"), 2: d("2021-05-25"), 3: d("2021-05-20")},
            tipos={1: "PETICION", 2: None, 3: None},
            asuntos={1: "Petición No. RE9411202102942", 2: None, 3: "Retiro de Guaya"},
        ).grupos.groups
        assert grupo.title == "PETICION: No. RE9411202102942; Retiro de Guaya"

    def test_el_asunto_no_repite_lo_que_ya_dice_el_tipo(self):
        [grupo] = agrupar_por_mes(
            un_documento_por_pagina(1),
            {1: d("2021-06-04")},
            tipos={1: "NOTIFICACION POR AVISO"},
            asuntos={1: "Notificación por aviso"},
        ).grupos.groups
        assert grupo.title == "NOTIFICACION POR AVISO"

    def test_la_misma_carta_en_dos_paginas_se_nombra_una_vez(self):
        [grupo] = agrupar_por_mes(
            un_documento_por_pagina(2),
            {1: d("2021-05-25"), 2: d("2021-05-25")},
            tipos={1: "PETICION", 2: "PETICION"},
            asuntos={1: "Petición No. 1", 2: "Petición No. 1"},
        ).grupos.groups
        assert grupo.title == "PETICION: No. 1"

    def test_una_hoja_que_nadie_reconocio_quita_el_tipo_al_archivo(self):
        """No se sabe que todo el archivo sea una petición si una hoja no dice qué es."""
        [grupo] = agrupar_por_mes(
            un_documento_por_pagina(2),
            {1: d("2021-05-25"), 2: d("2021-05-26")},
            tipos={1: "PETICION", 2: None},
        ).grupos.groups
        assert grupo.kind == "DOCUMENTO"

    def test_los_anexos_viajan_al_archivo_en_que_acaba_su_pagina(self):
        resultado = agrupar_por_mes(
            caja(documento("01", [1, 2]), documento("02", [3, 4])),
            {1: d("2023-05-03"), 2: None, 3: d("2023-06-07"), 4: None},
            {"01": [2], "02": [4]},
        )
        assert resultado.anexos == {"2023-05": [2], "2023-06": [4]}


class TestElAviso:
    def test_cuenta_cuantas_paginas_quedaron_en_cuantos_archivos(self):
        resultado = agrupar_por_mes(
            un_documento_por_pagina(3),
            {1: d("2023-05-03"), 2: d("2023-05-28"), 3: d("2023-06-07")},
        )
        assert resultado.aviso() == (
            "Agrupado por mes: las 3 páginas quedaron en 2 archivos, uno por mes."
        )

    def test_y_las_que_no_tenian_fecha(self):
        resultado = agrupar_por_mes(
            un_documento_por_pagina(4),
            {1: d("2023-05-03"), 2: None, 3: d("2023-06-07"), 4: None},
        )
        assert "2 páginas sin fecha se unieron a la anterior" in resultado.aviso()
        assert "1 de ellas queda en revisión" in resultado.aviso()


class TestLaFechaSaleDeLaOcr:
    """Estas cajas son escaneos: sin OCR no habría una sola fecha."""

    def test_una_pagina_sin_capa_de_texto_se_lee_con_ocr(self):
        fuente = FakePageSource([FakePage(text="", body="Cartagena, 25/05/2021 Señor")])
        ocr = FakeOcr()

        leidas = leer_paginas(fuente, ocr)

        assert leidas.fechas == {1: d("2021-05-25")}
        assert leidas.con_ocr == 1
        assert ocr.calls == 1

    def test_de_la_misma_lectura_salen_el_tipo_y_el_asunto(self):
        """Una sola pasada de OCR por página: el tipo y el asunto no la repiten."""
        fuente = FakePageSource(
            [FakePage(body="Cartagena, 04-06-2021\nAsunto: Notificación por aviso\nSeñor")]
        )
        ocr = FakeOcr()

        leidas = leer_paginas(fuente, ocr)

        assert leidas.tipos == {1: "NOTIFICACION POR AVISO"}
        assert leidas.asuntos == {1: "Notificación por aviso"}
        assert ocr.calls == 1

    def test_una_pagina_con_capa_de_texto_no_gasta_ocr(self):
        """Con el motor de pago se paga por página: leer lo ya leído es tirarlo."""
        capa = "Cartagena, 25/05/2021. " + "Texto de la carta que ya viene en el PDF. " * 3
        fuente = FakePageSource([FakePage(text=capa)])
        ocr = FakeOcr()

        leidas = leer_paginas(fuente, ocr)

        assert leidas.fechas == {1: d("2021-05-25")}
        assert leidas.con_ocr == 0
        assert ocr.calls == 0

    def test_se_lee_por_tandas_y_se_cuenta_el_avance(self):
        fuente = FakePageSource(
            [FakePage(body=f"Sahagun, {n:02d}/05/2021") for n in range(1, 11)]
        )
        avances = []

        leidas = leer_paginas(fuente, FakeOcr(), workers=2, avance=lambda h, t: avances.append(h))

        assert [leidas.fechas[n].day for n in range(1, 11)] == list(range(1, 11))
        assert avances[-1] == 10
        assert avances == sorted(avances)

    def test_una_pagina_que_la_ocr_no_puede_leer_queda_sin_fecha(self):
        class OcrQueFalla:
            def read(self, imagen):
                raise RuntimeError("tesseract no está")

        leidas = leer_paginas(FakePageSource([FakePage(body="Cartagena, 25/05/2021")]), OcrQueFalla())
        assert leidas.fechas == {1: None}

    def test_cancelar_detiene_la_lectura(self):
        from resolutions.application.control import Cancelled

        class Cancelado:
            def check(self):
                raise Cancelled()

        with pytest.raises(Cancelled):
            leer_paginas(FakePageSource([FakePage(body="x")]), FakeOcr(), control=Cancelado())


# -- de punta a punta ---------------------------------------------------------

pymupdf = pytest.importorskip("pymupdf")

CUERPO = (
    "Por medio de la presente me permito dar respuesta a la solicitud radicada "
    "en el asunto de la referencia, en los terminos que se exponen a "
    "continuacion y con base en la normatividad vigente."
)

#: Cinco hojas con capa de texto: la 1 del 3 de mayo, la 2 sin fecha, la 3 del
#: 7 de junio, la 4 del 28 de mayo -- otro día, mismo mes que la 1 -- y la 5 sin
#: fecha. La fecha va al final del cuerpo y sin ciudad delante, para no
#: convertirse en un «Ciudad, fecha» que también decidiría cortes.
HOJAS = [
    ("RESPUESTA A RECLAMACION", "Página 1 de 2", "fechado el 03/05/2023"),
    ("", "Página 2 de 2", ""),
    ("FACTURA DE VENTA", "Página 1 de 1", "fechado el 07/06/2023"),
    ("RESPUESTA A RECLAMACION", "Página 1 de 1", "fechado el 28/05/2023"),
    ("FACTURA DE VENTA", "Página 1 de 1", ""),
]


@pytest.fixture
def pdf(tmp_path):
    document = pymupdf.open()
    for encabezado, paginacion, fecha in HOJAS:
        page = document.new_page()
        if encabezado:
            page.insert_textbox(
                pymupdf.Rect(56, 64, 540, 96),
                encabezado,
                fontsize=12,
                align=pymupdf.TEXT_ALIGN_CENTER,
            )
        cuerpo = f"{CUERPO} {fecha}".strip()
        # insert_textbox no escribe nada si no cabe y sólo lo dice devolviendo
        # un negativo: una hoja en blanco aquí haría pasar la prueba por nada.
        assert page.insert_textbox(pymupdf.Rect(56, 110, 540, 700), cuerpo, fontsize=11) >= 0
        page.insert_textbox(pymupdf.Rect(56, 720, 540, 760), paginacion, fontsize=9)
    path = tmp_path / "caja.pdf"
    document.save(path)
    document.close()
    return path


def procesar(pdf, tmp_path, **opciones):
    from resolutions.api.settings import Settings
    from resolutions.api.worker import process_document_job
    from resolutions.application.task import TaskKind

    return process_document_job(
        {
            "job_id": "trabajo",
            "source": str(pdf),
            "filename": "caja.pdf",
            "task": str(TaskKind.SEGMENT),
            "settings": Settings(output_dir=tmp_path / "outputs").as_worker_payload(),
            **opciones,
        }
    )


class TestLaCajaDePuntaAPunta:
    def test_sin_elegir_nada_sale_un_archivo_por_documento(self, pdf, tmp_path):
        """Con la opción apagada no cambia nada de lo que ya había."""
        informe = procesar(pdf, tmp_path)

        assert informe["outputs"] == [
            "caja/01_DOCUMENTO.pdf",
            "caja/02_FACTURA.pdf",
            "caja/03_FACTURA.pdf",
            "caja/04_FACTURA.pdf",
        ]
        assert informe["agrupar"] == "documento"
        assert informe["notices"] == []
        assert "pages_dated_by_ocr" not in informe["stats"]

    def test_por_mes_sale_un_archivo_por_mes(self, pdf, tmp_path):
        informe = procesar(pdf, tmp_path, agrupar="mes")

        assert informe["outputs"] == [
            "caja/2023-05_DOCUMENTO.pdf",
            "caja/2023-06_FACTURA.pdf",
        ]
        assert [grupo["pages"] for grupo in informe["groups"]] == [[1, 2, 4, 5], [3]]
        assert informe["agrupar"] == "mes"
        assert informe["stats"]["documents"] == 2

    def test_las_paginas_con_capa_de_texto_no_pasan_por_ocr(self, pdf, tmp_path):
        informe = procesar(pdf, tmp_path, agrupar="mes")
        assert informe["stats"]["pages_dated_by_ocr"] == 0

    def test_el_pdf_escrito_trae_exactamente_esas_hojas(self, pdf, tmp_path):
        procesar(pdf, tmp_path, agrupar="mes")
        carpeta = tmp_path / "outputs" / "trabajo" / "caja"
        with pymupdf.open(carpeta / "2023-05_DOCUMENTO.pdf") as unido:
            textos = [pagina.get_text() for pagina in unido]
        assert len(textos) == 4
        assert any("03/05/2023" in texto for texto in textos)
        assert any("28/05/2023" in texto for texto in textos)
        # La hoja 3 es de junio y no puede estar aquí dentro.
        assert not any("07/06/2023" in texto for texto in textos)

    def test_a_revision_va_solo_la_pagina_sin_fecha_entre_dos_meses(self, pdf, tmp_path):
        """La 2 está entre mayo y junio; la 5 es la última y no tiene con qué dudar."""
        informe = procesar(pdf, tmp_path, agrupar="mes")
        assert [entrada["page"] for entrada in informe["review_queue"]] == [2]
        assert "sin fecha legible" in informe["review_queue"][0]["reason"]

    def test_el_inventario_dice_lo_mismo_que_la_carpeta(self, pdf, tmp_path):
        """Cada fila nombra su archivo y lleva la fecha más reciente de su mes."""
        informe = procesar(pdf, tmp_path, agrupar="mes")
        filas = [
            (fila["file_name"], fila["fecha"]) for fila in informe["inventory"]["items"]
        ]
        assert filas == [
            ("caja/2023-05_DOCUMENTO.pdf", "2023-05-28"),
            ("caja/2023-06_FACTURA.pdf", "2023-06-07"),
        ]

    def test_sin_ninguna_fecha_se_entrega_y_se_declara_por_documento(self, tmp_path):
        """Decir «mes» en el informe de una caja que no se agrupó sería mentir."""
        documento = pymupdf.open()
        for _ in range(2):
            pagina = documento.new_page()
            assert pagina.insert_textbox(pymupdf.Rect(56, 110, 540, 700), CUERPO, fontsize=11) >= 0
        sin_fechas = tmp_path / "sin fechas.pdf"
        documento.save(sin_fechas)
        documento.close()

        informe = procesar(sin_fechas, tmp_path, agrupar="mes")

        assert informe["agrupar"] == "documento"
        assert "ninguna página" in informe["notices"][0]
        assert all(salida.split("/")[-1][:2].isdigit() for salida in informe["outputs"])

    def test_el_informe_lo_explica(self, pdf, tmp_path):
        informe = procesar(pdf, tmp_path, agrupar="mes")
        [aviso] = informe["notices"]
        assert "las 5 páginas quedaron en 2 archivos, uno por mes" in aviso


# -- el contrato con la pantalla ----------------------------------------------

pytest.importorskip("httpx")

CAJA = {"file": ("caja.pdf", b"%PDF-1.4 ...", "application/pdf")}


class TestLoQueAnunciaElServicio:
    def test_la_capacidad_se_anuncia(self, client):
        """Un servicio viejo ignoraría el parámetro callado: la pantalla lo mira."""
        assert "agrupar-por-mes" in client.get("/api/health").json()["features"]

    def test_la_revision_sube(self, client):
        assert client.get("/api/health").json()["api_revision"] >= 19


class TestLaEleccionViaja:
    def test_sin_elegir_nada_es_por_documento(self, client):
        respuesta = client.post("/api/jobs?task=segment", files=CAJA)
        assert respuesta.status_code == 202
        assert respuesta.json()["agrupar"] == "documento"

    def test_por_mes_se_acepta_y_se_recuerda(self, client):
        creado = client.post("/api/jobs?task=segment&agrupar=mes", files=CAJA).json()
        assert creado["agrupar"] == "mes"
        assert client.get(f"/api/jobs/{creado['id']}").json()["agrupar"] == "mes"

    def test_una_agrupacion_desconocida_es_422_y_no_deja_nada_en_disco(self, client):
        from resolutions.api import main

        respuesta = client.post("/api/jobs?task=segment&agrupar=semana", files=CAJA)
        assert respuesta.status_code == 422
        assert "documento, mes" in respuesta.json()["detail"]
        assert list(main.contexto.settings.upload_dir.glob("*.pdf")) == []


class TestUnaCarpetaPideLoMismo:
    def test_una_agrupacion_desconocida_es_422(self, client):
        respuesta = client.post(
            "/api/folder-runs",
            json={"source": ".", "destination": ".", "agrupar": "semana"},
        )
        assert respuesta.status_code == 422

    def test_la_eleccion_llega_a_cada_archivo_de_la_carpeta(self, client, tmp_path, pdf):
        """Pasa por cuatro manos: endpoint, corrida, `_consume` y el trabajo.

        Perder una de ellas deja la carpeta saliendo un archivo por documento
        sin que nadie se entere, así que se mira el trabajo que se creó y no
        sólo la corrida.
        """
        origen = tmp_path / "origen"
        destino = tmp_path / "destino"
        origen.mkdir()
        destino.mkdir()
        (origen / "caja.pdf").write_bytes(pdf.read_bytes())

        respuesta = client.post(
            "/api/folder-runs",
            json={
                "source": str(origen),
                "destination": str(destino),
                "task": "segment",
                "agrupar": "mes",
            },
        )
        assert respuesta.status_code == 201
        assert respuesta.json()["agrupar"] == "mes"

        trabajos = []
        limite = time.monotonic() + 10
        while not trabajos and time.monotonic() < limite:
            trabajos = client.get("/api/jobs").json()["jobs"]
            if not trabajos:
                time.sleep(0.05)
        assert [trabajo["agrupar"] for trabajo in trabajos] == ["mes"]

        # Que la corrida no siga viva cuando el cliente cierre el pool de
        # procesos debajo de ella: se dejaría un error de apagado en la salida.
        client.post(f"/api/folder-runs/{respuesta.json()['id']}/stop")
        limite = time.monotonic() + 30
        while time.monotonic() < limite:
            estados = [trabajo["state"] for trabajo in client.get("/api/jobs").json()["jobs"]]
            if all(estado in ("done", "failed", "cancelled") for estado in estados):
                break
            time.sleep(0.1)
