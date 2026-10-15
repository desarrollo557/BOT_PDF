"""«Solo OCR» es sólo OCR; «OCR + IA», IA sólo donde haga falta.

Lo pidió el operador: «cuando sea solo OCR, sea solo OCR, cuando sea OCR con
IA, sea OCR con IA… para no gastar de más y sólo lo necesario». El oráculo de
las costuras, el modelo de visión y el resumen consultaban a un proveedor de
pago aunque se hubiera elegido no gastar, con sólo tener la llave cargada.
"""

from __future__ import annotations

import pytest

from resolutions.adapters.boundary_prompt import NullBoundaryOracle
from resolutions.adapters.claude_vision import NullVisionOracle
from resolutions.api.settings import Settings
from resolutions.api.worker.taller import Taller


def _taller(lectura: str, tmp_path) -> Taller:
    settings = Settings.from_env().as_worker_payload()
    settings.update(
        {
            "output_dir": str(tmp_path),
            # Todas las llaves cargadas: lo que decide es la lectura elegida.
            "mistral_api_key": "llave-de-prueba",
            "gemini_api_key": "llave-de-prueba",
            "anthropic_api_key": "llave-de-prueba",
        }
    )
    return Taller.desde(
        {
            "job_id": "trabajo",
            "source": str(tmp_path / "caja.pdf"),
            "settings": settings,
            "oracle": "auto",
            "lectura": lectura,
        }
    )


class TestSoloOcr:
    def test_no_hay_ninguna_ia(self, tmp_path):
        taller = _taller("local", tmp_path)

        assert isinstance(taller.oraculo_de_bordes(), NullBoundaryOracle)
        assert isinstance(taller.vision(), NullVisionOracle)
        assert taller.mistral_summary() is None
        assert taller.resumidor() is None
        assert taller.lector_de_pago() is None
        assert taller.lector_de_folios() is None
        assert taller.mosaico() is None
        assert type(taller.ocr()).__name__ == "HeaderAndPageOcr"


class TestOcrMasIa:
    @pytest.mark.parametrize("lectura", ["mistral", "mistral-nombres"])
    def test_la_ia_queda_disponible(self, lectura, tmp_path):
        taller = _taller(lectura, tmp_path)

        assert not isinstance(taller.oraculo_de_bordes(), NullBoundaryOracle)
        assert taller.lector_de_pago() is not None
        # Tesseract primero; la IA sólo para lo que el de casa no leyó.
        assert type(taller.ocr()).__name__ == "OcrEnCascada"
