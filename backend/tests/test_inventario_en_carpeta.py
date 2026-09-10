"""Una unidad que vive en una subcarpeta, corregida desde la pantalla.

Los documentos de una caja se entregan juntos, en una carpeta con el nombre del
PDF de origen, así que lo que identifica a un archivo dentro de su trabajo ya no
es su nombre sino su ruta: "UPD2366126/01_FACTURA.pdf".

Eso tiene que sobrevivir a una corrección. El renombrado guardaba en el
inventario sólo el nombre del archivo, sin la carpeta: el enlace de descarga
pasaba a contestar 404, y un segundo intento de corregir la misma unidad no
encontraba la fila, porque la busca justamente por ese nombre.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("httpx")


def una_caja_separada(carpeta: str = "UPD2366126", code: str = "01"):
    """Un trabajo terminado de separación, con su PDF dentro de su carpeta."""
    from resolutions.api import main

    nombre = f"{carpeta}.pdf"
    job = main.registry.create(nombre, Path(nombre))
    ruta = f"{carpeta}/{code}_FACTURA.pdf"
    report = {
        "document": nombre,
        "page_count": 2,
        "groups": [
            {
                "code": code,
                "title": "páginas 1-2",
                "type": "FACTURA",
                "pages": [1, 2],
                "size": 2,
            }
        ],
        "review_queue": [],
        "outputs": [ruta],
        "inventory": {
            "source_document": nombre,
            "source_pages": 2,
            "items": [
                {
                    "file_name": ruta,
                    "code": code,
                    "title": "páginas 1-2",
                    "type": "FACTURA",
                    "page_count": 2,
                    "first_page": 1,
                    "last_page": 2,
                    "page_numbers": [1, 2],
                    "attachments": [],
                }
            ],
        },
    }
    main.registry.mark_done(job, report)
    main.ledger.record(job.id, report)

    directorio = main.settings.output_dir / job.id / carpeta
    directorio.mkdir(parents=True, exist_ok=True)
    (directorio / f"{code}_FACTURA.pdf").write_bytes(b"%PDF-1.4 out")
    return job, ruta


class TestSeDescargaPorSuRuta:
    def test_el_pdf_de_una_caja_se_baja_con_la_carpeta_delante(self, client):
        job, ruta = una_caja_separada()
        assert client.get(f"/api/jobs/{job.id}/outputs/{ruta}").status_code == 200

    def test_el_inventario_guarda_esa_misma_ruta(self, client):
        _, ruta = una_caja_separada()
        filas = client.get("/api/inventory").json()["rows"]
        assert [fila["file_name"] for fila in filas] == [ruta]

    def test_y_guarda_el_tipo_documental(self, client):
        una_caja_separada()
        filas = client.get("/api/inventory").json()["rows"]
        assert filas[0]["type"] == "FACTURA"


class TestCorregirNoDesarmaLaRuta:
    def test_la_fila_conserva_la_carpeta_despues_de_renombrar(self, client):
        job, ruta = una_caja_separada()
        respuesta = client.patch(
            f"/api/jobs/{job.id}/outputs/{ruta}", json={"code": "00086"}
        )
        assert respuesta.status_code == 200
        assert respuesta.json()["file_name"] == "UPD2366126/RESOLUCION_00086.pdf"

    def test_el_archivo_renombrado_se_sigue_pudiendo_bajar(self, client):
        job, ruta = una_caja_separada()
        nuevo = client.patch(
            f"/api/jobs/{job.id}/outputs/{ruta}", json={"code": "00086"}
        ).json()["file_name"]
        assert client.get(f"/api/jobs/{job.id}/outputs/{nuevo}").status_code == 200

    def test_y_el_inventario_apunta_a_donde_esta(self, client):
        job, ruta = una_caja_separada()
        client.patch(f"/api/jobs/{job.id}/outputs/{ruta}", json={"code": "00086"})
        filas = client.get("/api/inventory").json()["rows"]
        assert filas[0]["file_name"] == "UPD2366126/RESOLUCION_00086.pdf"

    def test_se_puede_corregir_dos_veces_seguidas(self, client):
        """La segunda corrección busca la fila por el nombre que dejó la primera.

        Con la carpeta perdida, esa búsqueda fallaba y la segunda corrección
        movía el archivo sin tocar el inventario: el disco y el registro
        dejaban de decir lo mismo.
        """
        job, ruta = una_caja_separada()
        primero = client.patch(
            f"/api/jobs/{job.id}/outputs/{ruta}", json={"code": "00086"}
        ).json()["file_name"]
        segundo = client.patch(
            f"/api/jobs/{job.id}/outputs/{primero}", json={"code": "00087"}
        ).json()["file_name"]

        assert segundo == "UPD2366126/RESOLUCION_00087.pdf"
        filas = client.get("/api/inventory").json()["rows"]
        assert [fila["code"] for fila in filas] == ["00087"]
        assert filas[0]["file_name"] == segundo

    def test_el_renombrado_no_saca_el_archivo_de_su_carpeta(self, client):
        """Corregir un número no es mover el archivo de sitio."""
        from resolutions.api import main

        job, ruta = una_caja_separada()
        client.patch(f"/api/jobs/{job.id}/outputs/{ruta}", json={"code": "00086"})
        carpeta = main.settings.output_dir / job.id / "UPD2366126"
        assert (carpeta / "RESOLUCION_00086.pdf").is_file()
        assert not (main.settings.output_dir / job.id / "RESOLUCION_00086.pdf").exists()


class TestBorrarTambienEntiendeLaRuta:
    def test_borrar_se_lleva_el_archivo_y_su_fila(self, client):
        job, ruta = una_caja_separada()
        respuesta = client.request("DELETE", f"/api/jobs/{job.id}/outputs/{ruta}")
        assert respuesta.status_code == 200
        assert respuesta.json()["was_recorded"] is True
        assert client.get("/api/inventory").json()["total"] == 0
