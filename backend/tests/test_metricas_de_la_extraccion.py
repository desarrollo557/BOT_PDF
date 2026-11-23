"""Las métricas de la extracción y el verificador independiente, de las constancias de una entrega (2026-11-18).

El operador: «No declares una ejecución exitosa simplemente porque terminó sin
errores técnicos». Las métricas cuentan cada parámetro por su estado y su
método, lo que no pasó el verificador y lo no recuperado con su causa, y
comparan NIC por NIC con la entrega anterior.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from resolutions.adapters.metricas_de_la_extraccion import (
    NOMBRE_DE_LA_EVIDENCIA,
    NOMBRE_DE_LAS_METRICAS,
)
from resolutions.api import constancia as constancias
from resolutions.api.metricas import entregados_en, escribir_las_metricas
from resolutions.application.metricas_de_la_extraccion import comparar, medir, segundos_de
from resolutions.application.verificador_de_evidencia import reparos_del_hallazgo

RE = "RE2310202402908"


def _hallazgo(**datos) -> dict:
    return {"parametro": "re", "estado": "encontrado", "candidatos": [], "lectores": [], **datos}


def _constancia(carpeta: Path, upd: str, evidencia: dict, filas: list[dict], *, revision=(), duracion="1 min 05 s"):
    carpeta.mkdir(parents=True, exist_ok=True)
    constancias.escribir(
        carpeta / f".bot-entrega-{upd}.json",
        constancias.Constancia(
            origen=f"{carpeta.name}/{upd}.pdf",
            tamano=1,
            modificado_ns=1,
            estado=constancias.EstadoDeEntrega.COMPLETA,
            archivos=[{"ruta": f"0{n}_{f['nombre']}.pdf", "bytes": 1} for n, f in enumerate(filas, start=1)],
            proceso={"paginas": 10, "paginas_pagadas": 4, "duracion": duracion},
            indice={"filas": filas},
            evidencia=evidencia,
            revision=list(revision),
        ),
    )


class TestElVerificador:
    def test_el_re_que_se_cree_tiene_que_estar_en_su_fragmento(self):
        assert reparos_del_hallazgo(_hallazgo(valor=RE, fragmento=f"No DE RADICACION: {RE}")) == []
        assert reparos_del_hallazgo(_hallazgo(valor=RE, fragmento="RE2310202402909")) == [
            f"{RE} no aparece tal cual en su fragmento"
        ]
        # El que confirmó una persona no tiene fragmento.
        assert reparos_del_hallazgo(_hallazgo(valor=RE, metodo="confirmado por el operador")) == []

    def test_la_fecha_posible_y_dicha_por_su_fragmento(self):
        fecha = {"parametro": "fecha", "estado": "encontrado", "candidatos": []}
        assert reparos_del_hallazgo({**fecha, "valor": "2023-10-27", "fragmento": "MAGANGUE, 27/10/2023"}) == []
        assert reparos_del_hallazgo({**fecha, "valor": "2030-01-01"}, hoy=date(2026, 11, 18)) == [
            "la fecha 2030-01-01 es futura"
        ]
        assert "no dice la fecha" in reparos_del_hallazgo({**fecha, "valor": "2023-10-27", "fragmento": "MAGANGUE, 2023"})[0]

    def test_lo_que_no_se_cree_dice_que_propone_o_que_busco(self):
        assert reparos_del_hallazgo(_hallazgo(estado="requiere validación")) == ["requiere validación sin ningún candidato"]
        assert reparos_del_hallazgo(_hallazgo(estado="no encontrado")) == ["no encontrado sin decir qué se buscó"]


class TestLasMetricas:
    def test_cuenta_por_parametro_metodo_y_estado_y_lo_no_recuperado(self, tmp_path):
        destino = tmp_path / "destino"
        _constancia(
            destino / "1005122",
            "UPD3102765",
            {
                "re": {
                    "1": _hallazgo(estado="requiere validación", candidatos=[{"valor": RE, "motivo": "corregido"}]),
                    "14": _hallazgo(
                        estado="verificado",
                        valor="RE2310202409991",
                        fragmento="RE: RE2310202409991",
                        metodo="sello de tinta",
                        lectores=["ocr de pago", "visión"],
                    ),
                },
                "fecha": {
                    "1": {"parametro": "fecha", "estado": "encontrado", "valor": "2024-02-12", "metodo": "sello de radicación (pág. 1)"},
                    "14": {"parametro": "fecha", "estado": "no encontrado", "buscado": "las hojas 14"},
                },
            },
            [{"nombre": "RECLAMO", "fecha_creacion": "2024-02-12"}, {"nombre": "RECLAMO-RE2310202409991", "fecha_creacion": None}],
            revision=[{"page": 1, "reason": "RE por confirmar, el nombre va sin él: …"}],
        )
        metricas = medir(entregados_en(destino))
        assert (metricas.pdf, metricas.documentos, metricas.paginas_pagadas, metricas.segundos) == (1, 2, 4, 65)
        assert metricas.por_estado[("re", "verificado")] == 1 and metricas.por_estado[("re", "requiere validación")] == 1
        assert metricas.por_metodo[("fecha", "sello de radicación", "encontrado")] == 1
        assert metricas.lectores_del_re == {"ocr de pago": 1, "visión": 1}
        assert metricas.revision == {"RE por confirmar": 1}
        assert [(d, p, e) for d, p, e, _ in metricas.no_recuperados] == [
            ("1005122/UPD3102765 · hoja 1", "re", "requiere validación"),
            ("1005122/UPD3102765 · hoja 14", "fecha", "no encontrado"),
        ]
        assert metricas.no_recuperados[0][3] == f"candidatos: {RE} (corregido)"
        assert metricas.reparos == []

    def test_los_dos_libros_y_la_comparacion_con_la_entrega_anterior(self, tmp_path):
        from openpyxl import load_workbook

        antes, ahora = tmp_path / "antes", tmp_path / "ahora"
        _constancia(antes / "1001389", "UPD3102735", {}, [{"nombre": "RECLAMO", "fecha_creacion": None}, {"nombre": "RECLAMO-RE2310202403286", "fecha_creacion": "2024-04-01"}])
        _constancia(ahora / "1001389", "UPD3102735", {"re": {"1": _hallazgo(valor="RE2320202403286", fragmento="RE2320202403286")}}, [{"nombre": "RECLAMO-RE2320202403286", "fecha_creacion": "2024-04-01"}])
        rutas = escribir_las_metricas(ahora, antes)
        assert [r.name for r in rutas] == [NOMBRE_DE_LAS_METRICAS, NOMBRE_DE_LA_EVIDENCIA]
        libro = load_workbook(ahora / NOMBRE_DE_LAS_METRICAS, read_only=True)
        assert {"Resumen", "Por parámetro", "Por método", "Revisión", "Verificador", "No recuperados", "Comparación"} <= set(libro.sheetnames)
        [fila] = comparar(entregados_en(antes), entregados_en(ahora))
        assert (fila.nic, fila.documentos_antes, fila.documentos_ahora, fila.sin_fecha_antes, fila.sin_fecha_ahora) == (
            "1001389", 2, 1, 1, 0,
        )
        assert fila.solo_antes == ["RECLAMO", "RECLAMO-RE2310202403286"] and fila.solo_ahora == ["RECLAMO-RE2320202403286"]

    def test_la_duracion_en_segundos(self):
        assert (segundos_de("1 min 05 s"), segundos_de("42 s"), segundos_de("—")) == (65, 42, 0)


class TestLaAuditoria:
    """El operador, 2026-11-20: «un Excel con sus filtros… qué UPD o qué NIC no tiene fecha, cuáles no tienen RE»."""

    def _pdf(self, *, documentos=()):
        from resolutions.application.metricas_de_la_extraccion import PdfEntregado

        return PdfEntregado(
            documento="1000001/UPD1",
            estado="completa",
            archivos=["01_RECLAMO-RE2310202402908.pdf", "02_PUBLICACION-DEL-AVISO.pdf", "03_ACTA.pdf"],
            evidencia={
                "re": {"1": _hallazgo(valor=RE, metodo="sello de radicación", pagina=1),
                       "4": _hallazgo(estado="no encontrado", buscado="sello y etiqueta en las hojas 4")},
                "fecha": {"1": _hallazgo(parametro="fecha", valor="2024-02-01"),
                          "4": _hallazgo(parametro="fecha", valor="2024-03-01"),
                          "6": _hallazgo(parametro="fecha", estado="no encontrado", buscado="la hoja 6")},
            },
            revision=[{"page": 6, "reason": "la fecha del documento no se pudo leer"}],
            proceso={"paginas": 6, "paginas_pagadas": 2, "duracion": "12 s", "lectura": "OCR + IA"},
            filas=[
                {"nombre": f"RECLAMO-{RE}", "fecha_creacion": "2024-02-01", "paginas": 3},
                {"nombre": "PUBLICACION DEL AVISO", "fecha_creacion": "2024-03-01", "paginas": 2},
                {"nombre": "ACTA", "fecha_creacion": None, "paginas": 1},
            ],
            documentos=list(documentos),
        )  # fmt: skip

    def test_una_fila_por_documento_con_lo_que_le_falta(self):
        from resolutions.application.metricas_de_la_extraccion import auditar

        filas, upd = auditar(self._pdf(documentos=[{"hojas": [1, 2, 3]}, {"hojas": [4, 5]}, {"hojas": [6]}]))
        assert [f["alerta"] for f in filas] == ["OK", "Sin RE", "Sin fecha · En Revisión"]
        assert [f["hojas"] for f in filas] == ["1-3", "4-5", "6"]
        assert filas[0]["re_como"] == "sello de radicación, pág. 1"
        assert (upd["sin_fecha"], upd["sin_re"], upd["en_revision"]) == (1, 1, 1)

    def test_sin_las_hojas_se_casa_por_la_fecha_y_el_re(self):
        from resolutions.application.metricas_de_la_extraccion import auditar

        filas, _ = auditar(self._pdf())
        assert [f["re_estado"] for f in filas[:2]] == ["encontrado", "no encontrado"]
        assert filas[2]["en_revision"] == "Sí"

    def test_el_libro_trae_la_auditoria_al_frente_con_sus_filtros(self, tmp_path):
        from openpyxl import load_workbook

        _constancia(
            tmp_path / "1000001",
            "UPD1",
            {"re": {"1": _hallazgo(valor=RE)}},
            [{"nombre": f"RECLAMO-{RE}", "fecha_creacion": None, "paginas": 1}],
        )
        escribir_las_metricas(tmp_path)
        libro = load_workbook(tmp_path / NOMBRE_DE_LAS_METRICAS)
        assert libro.sheetnames[:6] == ["Faltantes", "Avisos de Revisión", "Decisiones del agente", "Documentos", "Por UPD", "Por NIC"]
        documentos = libro["Documentos"]
        assert documentos.auto_filter.ref and documentos.freeze_panes == "A2"
        assert documentos["I2"].value == "No" and documentos["I2"].fill.start_color.rgb.endswith("F8CBAD")
        assert (libro["Faltantes"]["F2"].value, libro["Faltantes"]["G2"].value) == ("Fecha", "No se encontró")


class TestLaAuditoriaDeLaCorrida:
    """El operador, 2026-11-20: «necesito saber qué archivos no tomaron o no encontraron los parámetros… por proceso ejecutado»."""

    def test_un_renglon_por_archivo_y_parametro_que_no_se_tomo(self):
        from resolutions.application.metricas_de_la_extraccion import (
            auditar,
            faltantes,
            por_parametro,
        )

        filas, _ = auditar(TestLaAuditoria()._pdf(documentos=[{"hojas": [1, 2, 3]}, {"hojas": [4, 5]}, {"hojas": [6]}]))
        lo_que_falta = faltantes(filas, {"/origen/1000002/UPD9.pdf": "el PDF está dañado"})
        assert [(x["archivo"], x["parametro"], x["situacion"]) for x in lo_que_falta] == [
            ("02_PUBLICACION-DEL-AVISO.pdf", "RE", "No se encontró"),
            ("03_ACTA.pdf", "Fecha", "No se encontró"),
            ("UPD9.pdf", "El PDF entero", "El PDF no se procesó"),
        ]
        sin_re, sin_fecha, fallido = lo_que_falta
        assert (sin_re["hoja"], sin_re["buscado"]) == ("4", "sello y etiqueta en las hojas 4")
        assert sin_fecha["hoja"] == "6" and "hoja 6 del UPD1" in sin_fecha["que_hacer"]
        assert (fallido["nic"], fallido["upd"], fallido["buscado"]) == ("1000002", "UPD9", "el PDF está dañado")
        fecha, re_, tipo = por_parametro(filas)
        assert (fecha["tomado"], fecha["no_tomado"]) == (2, 1)
        assert (re_["tomado"], re_["no_tomado"], re_["no_aplica"]) == (1, 1, 1)
        assert tipo["no_tomado"] == 0

    def test_lo_tomado_con_duda_y_lo_ilegible(self):
        from resolutions.application.metricas_de_la_extraccion import faltantes

        base = {"nic": "1", "upd": "UPD1", "orden": 1, "archivo": "01_RECLAMO.pdf", "tipo": "RECLAMO", "hojas": "1",
                "tiene_fecha": "Sí", "fecha": "2024-01-01", "lleva_re": "Sí"}  # fmt: skip
        dudoso = {**base, "re": RE, "re_estado": "requiere validación"}
        ilegible = {**base, "re": "", "re_estado": "requiere validación", "re_leido": "candidatos: RE23D20210565"}
        sin_nombre = {**base, "re": RE, "tipo": "DOCUMENTO"}
        assert [x["situacion"] for x in faltantes([dudoso, ilegible, sin_nombre])] == [
            "Tomado, por confirmar",
            "Ilegible: no se tomó",
            "Sin nombre del catálogo",
        ]
        assert faltantes([ilegible])[0]["leido"] == "candidatos: RE23D20210565"

    def test_el_libro_es_de_la_corrida_y_no_del_destino_entero(self, tmp_path):
        from openpyxl import load_workbook

        from resolutions.api.metricas import escribir_la_auditoria
        from resolutions.application.metricas_de_la_extraccion import LaCorrida

        for upd, trabajo in (("UPD1", "de-esta"), ("UPD2", "de-otra")):
            carpeta = tmp_path / "1000001"
            _constancia(carpeta, upd, {}, [{"nombre": "RECLAMO", "fecha_creacion": None, "paginas": 1}])
            ruta = carpeta / f".bot-entrega-{upd}.json"
            constancia = constancias.leer(ruta)
            constancias.escribir(ruta, replace(constancia, job_id=trabajo))
        corrida = LaCorrida(inicio="2026-11-20T19:30:00+00:00", fin="2026-11-20T20:00:00+00:00", origen="o", destino="d")
        ruta = escribir_la_auditoria(tmp_path, corrida, ["de-esta"])
        assert ruta.name.startswith("00.AUDITORIA DE LA CORRIDA 2026-11-20 ") and ruta.suffix == ".xlsx"
        libro = load_workbook(ruta, read_only=True)
        assert libro.sheetnames[:3] == ["Corrida", "Faltantes", "Avisos de Revisión"]
        assert "Por parámetro" in libro.sheetnames
        faltan = list(libro["Faltantes"].iter_rows(min_row=2, values_only=True))
        assert [(f[1], f[5]) for f in faltan] == [("UPD1", "Fecha"), ("UPD1", "RE")]
