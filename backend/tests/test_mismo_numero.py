"""Un mismo número de resolución, dentro de un PDF y entre PDF distintos.

La regla la fijó quien opera el software: si el número aparece dos veces en el
**mismo** PDF, esas páginas son una sola resolución y salen en un solo archivo,
aunque estén separadas en el documento. Si el mismo número aparece en PDF
**distintos** -- lo normal cuando son de años distintos, porque la numeración se
reinicia cada año -- son resoluciones diferentes y cada una sale como archivo
independiente, sin mezclarse ni pisarse en el inventario.
"""

from __future__ import annotations

from resolutions.adapters.ledger import InventoryLedger


def report(document: str, code: str, file_name: str, pages: list[int]):
    return {
        "document": document,
        "inventory": {
            "source_document": document,
            "source_pages": max(pages),
            "items": [
                {
                    "file_name": file_name,
                    "code": code,
                    "title": "Por medio de la cual se hace un nombramiento",
                    "page_count": len(pages),
                    "first_page": pages[0],
                    "last_page": pages[-1],
                    "page_numbers": pages,
                }
            ],
        },
    }


class TestDentroDelMismoPdf:
    def test_las_paginas_separadas_del_mismo_numero_salen_en_un_solo_archivo(self):
        """Una resolución interrumpida por otra sigue siendo una sola.

        En el expediente real las resoluciones se intercalan: 00072 ocupa las
        páginas 1 a 10, aparece 00073, y 00072 vuelve más adelante. Es un
        documento, no dos.
        """
        from resolutions.domain.grouping import GroupingEngine
        from resolutions.domain.page import PageClassification
        from resolutions.domain.resolution_code import ResolutionCode

        uno = ResolutionCode.parse("00072")
        otro = ResolutionCode.parse("00073")
        # La intercalada tiene dos páginas a propósito: una resolución de una
        # sola página rodeada por otra la trata el motor como error de lectura y
        # la absorbe, que es una regla distinta y deliberada.
        paginas = [
            PageClassification(page_number=1, code=uno),
            PageClassification(page_number=2, code=uno),
            PageClassification(page_number=3, code=otro),
            PageClassification(page_number=4, code=otro),
            PageClassification(page_number=5, code=uno),
            PageClassification(page_number=6, code=uno),
        ]

        resultado = GroupingEngine().group(paginas)

        porcodigo = {g.code.value: g.page_numbers for g in resultado.groups}
        assert porcodigo["00072"] == [1, 2, 5, 6], "un número, un archivo"
        assert porcodigo["00073"] == [3, 4]
        assert len(resultado.groups) == 2


class TestEntrePdfDistintos:
    def test_el_mismo_numero_en_dos_pdf_son_dos_resoluciones(self, tmp_path):
        # La numeración se reinicia cada año: 00072 de 2023 y 00072 de 2024 son
        # documentos distintos que nada tiene por qué unir.
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")

        ledger.record("job-2023", report("RESOLUCIONES 2023.pdf", "00072", "00072__a.pdf", [1, 2]))
        ledger.record("job-2024", report("RESOLUCIONES 2024.pdf", "00072", "00072__b.pdf", [5]))

        filas = [row for row in ledger.rows() if row["code"] == "00072"]
        assert len(filas) == 2, "cada PDF aporta su propia resolución"
        assert {row["source_document"] for row in filas} == {
            "RESOLUCIONES 2023.pdf",
            "RESOLUCIONES 2024.pdf",
        }

    def test_cada_una_conserva_sus_propias_paginas(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")

        ledger.record("job-2023", report("RESOLUCIONES 2023.pdf", "00072", "00072__a.pdf", [1, 2]))
        ledger.record("job-2024", report("RESOLUCIONES 2024.pdf", "00072", "00072__b.pdf", [5]))

        porduento = {row["source_document"]: row for row in ledger.rows()}
        assert porduento["RESOLUCIONES 2023.pdf"]["pages"] == "1-2"
        assert porduento["RESOLUCIONES 2024.pdf"]["pages"] == "5"

    def test_los_archivos_generados_no_se_pisan(self, tmp_path):
        # Van a carpetas distintas -- una por documento procesado -- así que dos
        # resoluciones con el mismo número nunca se sobrescriben.
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")

        ledger.record("job-2023", report("RESOLUCIONES 2023.pdf", "00072", "00072__a.pdf", [1]))
        ledger.record("job-2024", report("RESOLUCIONES 2024.pdf", "00072", "00072__b.pdf", [1]))

        assert {row["job_id"] for row in ledger.rows()} == {"job-2023", "job-2024"}
