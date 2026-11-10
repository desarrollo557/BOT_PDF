"""El análisis de la entrega con la muestra de filas del inventario (2026-11-09).

Una corrida que sólo inventaría no entrega PDF cortados sino filas, y la
auditoría de cierre revisa 100 filas al azar contra sus páginas del original.
El Excel lo tiene que decir así: «Muestra auditada (filas del inventario)», la
hoja con las columnas de una fila -- sin PDF entregados, costuras ni «dentro del
margen», que en una fila no existen --, lo que se preguntó a la IA y lo que
costó, y una muestra vacía dicha en palabras, nunca como «< 0 % de error». El
caso de PDF queda como estaba.
"""

from __future__ import annotations

import openpyxl
import pytest

from resolutions.adapters.analisis_de_la_entrega import (
    PROCESADO,
    SIN_MUESTRA,
    FilaDelAnalisis,
    escribir_analisis,
    por_que_no_hay_muestra,
)
from resolutions.domain.auditoria import (
    BIEN,
    ERROR,
    NO_AUDITADO,
    PdfAuditado,
    margen_de_error,
)

FILA = "00C003284/UPD3859771/1N°22.pdf · págs. 1-22 · acta 022"


def _muestra_de_filas(resultados: list[PdfAuditado], **extra) -> dict:
    """El dict que deja ``auditar_las_filas`` en ``run.auditoria["muestra"]``."""
    revisados = sum(r.estado != NO_AUDITADO for r in resultados)
    errores = sum(r.estado == ERROR for r in resultados)
    margen = margen_de_error(errores, revisados, aceptable=0.05).as_dict()
    return {
        "unidad": "filas",
        "semilla": 7,
        "candidatos": 40,
        "revisados": revisados,
        "bien": sum(r.estado == BIEN for r in resultados),
        "errores": errores,
        "dudosos": 0,
        "no_auditados": sum(r.estado == NO_AUDITADO for r in resultados),
        "ampliada": False,
        "margen": margen,
        "por_habilidad": [
            {
                "clave": "actas_consejo",
                "habilidad": "Actas de consejo",
                "revisados": revisados,
                "bien": sum(r.estado == BIEN for r in resultados),
                "errores": errores,
                "dudosos": 0,
                "no_auditados": sum(r.estado == NO_AUDITADO for r in resultados),
                "margen": margen,
            }
        ],
        "preguntadas_a_la_ia": sum(r.preguntadas_a_la_ia for r in resultados),
        "pdfs": [r.as_dict() for r in resultados],
        **extra,
    }


def _leer(tmp_path, muestra: dict) -> tuple[dict, list[str], list[tuple], list[str]]:
    """El resumen como {concepto: cantidad}, la cabecera y las filas de «Muestra auditada», y las hojas."""
    escribir_analisis(
        tmp_path,
        [FilaDelAnalisis("00C003284", "1N°22.pdf", "Procesar", "nuevo", PROCESADO, documentos=1, paginas=22)],
        origen="X:/origen",
        fecha="2026-11-09 10:00",
        muestra=muestra,
    )
    libro = openpyxl.load_workbook(tmp_path / "00.ANALISIS DE LA ENTREGA.xlsx", read_only=True)
    try:
        resumen = {fila[0]: fila[1] for fila in libro["Resumen"].iter_rows(values_only=True)}
        filas = list(libro["Muestra auditada"].iter_rows(values_only=True))
        hojas = list(libro.sheetnames)
    finally:
        libro.close()
    return resumen, list(filas[0]), filas[1:], hojas


class TestLaMuestraDeFilas:
    def test_el_resumen_dice_filas_y_lo_que_costo_la_ia(self, tmp_path):
        muestra = _muestra_de_filas(
            [
                PdfAuditado(FILA, BIEN, paginas=22, preguntadas_a_la_ia=2, habilidad="actas_consejo"),
                PdfAuditado(
                    "00C003284/UPD3859771/1N°23.pdf · págs. 1-9 · acta 023",
                    ERROR,
                    ("la fecha 12/03/1998 no está en el acta",),
                    paginas=9,
                    habilidad="actas_consejo",
                ),
            ],
            con_ia=True,
            consumo_ia={"peticiones": 1, "tokens_entrada": 900, "tokens_salida": 120, "tokens": 1020},
        )
        resumen, cabecera, filas, _ = _leer(tmp_path, muestra)

        assert resumen["Muestra auditada (filas del inventario)"] == 2
        assert "Muestra auditada (PDF)" not in resumen
        assert (resumen["Muestra · bien"], resumen["Muestra · con error"]) == (1, 1)
        assert resumen["Margen de error de la corrida"] == muestra["margen"]["texto"]
        assert resumen["IA de la auditoría · datos que contestó"] == 2
        assert resumen["IA de la auditoría · tokens"] == 1020
        assert resumen["Margen · Actas de consejo"].startswith(muestra["margen"]["texto"])

        # Las columnas de una fila: nada de PDF entregados, costuras ni margen.
        assert cabecera == ["Fila", "Habilidad", "Resultado", "Páginas", "Preguntadas a la IA", "Hallazgos"]
        assert filas[0] == (FILA, "actas_consejo", BIEN, 22, 2, None)
        assert filas[1][2:] == (ERROR, 9, 0, "la fecha 12/03/1998 no está en el acta")

    def test_la_ia_que_no_respondio_se_dice(self, tmp_path):
        """Una llave mala o una caída: el Excel no puede decir que la IA revisó (la revisión, 2026-11-09)."""
        muestra = _muestra_de_filas(
            [PdfAuditado(FILA, BIEN, paginas=22, habilidad="actas_consejo")],
            con_ia=True,
            consumo_ia={"peticiones": 0, "tokens_entrada": 0, "tokens_salida": 0, "tokens": 0, "fallos": 3},
        )
        resumen, _, _, _ = _leer(tmp_path, muestra)
        assert resumen["IA de la auditoría · datos que contestó"] == 0
        assert resumen["IA de la auditoría · filas sin respuesta"] == 3

    def test_sin_ia_lo_dice_y_no_da_tokens(self, tmp_path):
        muestra = _muestra_de_filas(
            [PdfAuditado(FILA, BIEN, paginas=22, habilidad="actas_consejo")], con_ia=False
        )
        resumen, _, _, _ = _leer(tmp_path, muestra)

        assert "IA de la auditoría: no (la corrida se hizo sin IA)" in resumen
        assert "IA de la auditoría · tokens" not in resumen
        assert "IA de la auditoría · datos que contestó" not in resumen

    def test_una_muestra_vacia_se_dice_en_palabras(self, tmp_path):
        muestra = _muestra_de_filas([], con_ia=False, candidatos=0)
        resumen, cabecera, filas, _ = _leer(tmp_path, muestra)

        assert resumen["Muestra auditada (filas del inventario)"] == 0
        assert resumen["Muestra · por qué está vacía"] == por_que_no_hay_muestra(muestra)
        assert "no dejó filas del inventario que auditar" in resumen["Muestra · por qué está vacía"]
        # Ni «< 0 %», ni cuentas en cero que parezcan una corrida perfecta.
        assert resumen["Margen de error de la corrida"] == "Sin muestra: no hay margen de error que dar"
        assert "Muestra · bien" not in resumen
        assert not any("menos del 0" in str(valor) for valor in resumen.values())
        # La hoja no se queda con la cabecera sola.
        assert len(cabecera) == 6
        [vacia] = filas
        assert vacia[2] == SIN_MUESTRA and "Sin muestra no hay margen" in vacia[-1]

    def test_si_ninguna_elegida_se_pudo_auditar_lo_explica(self, tmp_path):
        muestra = _muestra_de_filas(
            [PdfAuditado(FILA, NO_AUDITADO, ("no se pudo abrir su PDF: permiso denegado",), habilidad="actas_consejo")],
            con_ia=False,
        )
        resumen, _, filas, _ = _leer(tmp_path, muestra)

        assert "la fila elegida no se pudo auditar" in resumen["Muestra · por qué está vacía"]
        dos = _muestra_de_filas(
            [PdfAuditado(f"{FILA} ({n})", NO_AUDITADO, ("la corrida se detuvo",)) for n in range(2)]
        )
        assert "las 2 filas elegidas no se pudieron auditar" in por_que_no_hay_muestra(dos)
        # El motivo de cada una sigue en la hoja.
        assert filas[0][2] == NO_AUDITADO and "permiso denegado" in filas[0][-1]
        assert resumen["Margen · Actas de consejo"].startswith("No se revisó ninguna fila.")


class TestElCasoDePdfNoCambia:
    def test_columnas_y_resumen_de_siempre(self, tmp_path):
        muestra = _muestra_de_filas(
            [PdfAuditado("00C003284/UPD1.pdf", BIEN, paginas=4, archivos=2, costuras=1, habilidad="correspondencia")]
        )
        del muestra["unidad"]
        del muestra["preguntadas_a_la_ia"]
        resumen, cabecera, filas, hojas = _leer(tmp_path, muestra)

        assert resumen["Muestra auditada (PDF)"] == 1
        assert "Muestra auditada (filas del inventario)" not in resumen
        assert not any(str(concepto).startswith("IA de la auditoría") for concepto in resumen)
        assert cabecera == [
            "PDF", "Habilidad", "Resultado", "Páginas", "PDF entregados",
            "Costuras", "Dentro del margen", "Preguntadas a la IA", "Hallazgos",
        ]
        assert filas == [("00C003284/UPD1.pdf", "correspondencia", BIEN, 4, 2, 1, 0, 0, None)]
        assert "Margen por habilidad" in hojas

    @pytest.mark.parametrize("unidad", ["pdf", None])
    def test_una_muestra_de_pdf_vacia_tambien_se_explica(self, tmp_path, unidad):
        muestra = _muestra_de_filas([], candidatos=0)
        muestra["unidad"] = unidad
        resumen, cabecera, filas, _ = _leer(tmp_path, muestra)

        assert resumen["Muestra auditada (PDF)"] == 0
        assert "no dejó PDF entregados que auditar" in resumen["Muestra · por qué está vacía"]
        assert len(cabecera) == 9
        [vacia] = filas
        assert vacia[0] == "Ninguno" and vacia[2] == SIN_MUESTRA
