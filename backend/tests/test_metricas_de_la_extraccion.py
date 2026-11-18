"""Las métricas de la extracción y el verificador independiente, de las constancias de una entrega (2026-11-18).

El operador: «No declares una ejecución exitosa simplemente porque terminó sin
errores técnicos». Las métricas cuentan cada parámetro por su estado y su
método, lo que no pasó el verificador y lo no recuperado con su causa, y
comparan NIC por NIC con la entrega anterior.
"""

from __future__ import annotations

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
