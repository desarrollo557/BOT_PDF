"""Un fallo del procesamiento se cuenta en español y con qué hacer.

«PermissionError: [Errno 13] Permission denied: 'C:\\...\\inventario.xlsx'» no le
dice al operador que el Excel está abierto y basta con cerrarlo. Esto fija que
los fallos que se saben explicar se expliquen, y que ninguno enseñe la ruta
entera del disco del servicio.
"""

from __future__ import annotations

import errno

import pytest

from resolutions.api.errores import explicar_fallo, fallo_conocido


class TestLosFallosConocidos:
    def test_un_excel_abierto_dice_que_se_cierre(self):
        error = PermissionError(13, "Permission denied", r"C:\secreto\destino\inventario.xlsx")
        mensaje = explicar_fallo(error)
        assert "«inventario.xlsx»" in mensaje
        assert "ciérrelo" in mensaje
        assert "secreto" not in mensaje

    def test_un_archivo_que_desaparece(self):
        error = FileNotFoundError(2, "No such file", "/srv/origen/UPD123.pdf")
        assert "«UPD123.pdf»" in explicar_fallo(error)
        assert "se borró" in explicar_fallo(error)

    def test_tesseract_sin_instalar(self):
        error = FileNotFoundError(2, "No such file", "tesseract.exe")
        assert "Tesseract" in explicar_fallo(error)

    def test_el_disco_lleno(self):
        assert "sin espacio" in explicar_fallo(OSError(errno.ENOSPC, "No space left on device"))

    def test_la_memoria(self):
        assert "memoria" in explicar_fallo(MemoryError())

    def test_un_proceso_que_muere(self):
        from concurrent.futures.process import BrokenProcessPool

        assert "se cerró de golpe" in explicar_fallo(BrokenProcessPool("boom"))

    @pytest.mark.parametrize("error", [TimeoutError(), ConnectionResetError()])
    def test_la_red_y_las_esperas(self, error):
        assert "Vuelva a intentarlo" in explicar_fallo(error) or "red" in explicar_fallo(error)


class TestLosDemas:
    def test_el_mensaje_para_el_operador_va_tal_cual(self):
        class Propio(ValueError):
            para_el_operador = True

        assert explicar_fallo(Propio("El PDF está protegido con contraseña.")) == (
            "El PDF está protegido con contraseña."
        )

    def test_un_proveedor_se_nombra(self):
        class TesseractError(RuntimeError):
            pass

        mensaje = explicar_fallo(TesseractError("código 1"))
        assert mensaje.startswith("El OCR (Tesseract)")
        assert "código 1" in mensaje

    def test_uno_desconocido_conserva_su_texto_recortado(self):
        mensaje = explicar_fallo(RuntimeError("x" * 1000))
        assert mensaje.startswith("RuntimeError: ")
        assert len(mensaje) < 400

    def test_uno_desconocido_no_es_conocido(self):
        assert fallo_conocido(RuntimeError("C:/secreto")) is None


def test_la_respuesta_500_explica_lo_conocido_y_trae_referencia(client, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from resolutions.api import main

    def revienta():
        raise PermissionError(13, "Permission denied", "C:/secreto/inventory.jsonl")

    monkeypatch.setattr(main.contexto.ledger, "rows", revienta)
    respuesta = TestClient(main.app, raise_server_exceptions=False).get("/api/inventory")

    assert respuesta.status_code == 500
    detalle = respuesta.json()["detail"]
    assert "No hay permiso" in detalle
    assert "Referencia del error:" in detalle
    assert "secreto" not in detalle
