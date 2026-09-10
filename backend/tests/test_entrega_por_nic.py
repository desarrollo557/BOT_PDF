"""La carpeta de destino se llama con el NIC del expediente.

Lo pidió el operador para las corridas sobre carpeta local: un PDF de origen
corresponde en el destino a una carpeta nueva, nombrada con el número de cuenta
del suscriptor, y allí van todos los documentos que salieron de él.

Tiene sentido y es lo que el archivo busca: el NIC lo llevan todas las hojas de
la caja, identifica al cliente y es lo que alguien va a teclear dentro de tres
años. El nombre del PDF de origen es el que le puso el escáner.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resolutions.api.folders import FolderRun, FolderRunner
from resolutions.api.jobs import Job
from resolutions.domain.fingerprint import (
    NIC_MIN_HOJAS,
    fingerprint_page,
    nic_de_la_caja,
)


class TestElNicDeLaCaja:
    """Es de la caja entera y no de ninguno de sus documentos.

    Eso es justo lo que lo hace inútil para decidir dónde se corta -- lo llevan
    todas las hojas -- y útil para nombrar la carpeta en que se entrega.
    """

    @staticmethod
    def _huellas(nics):
        return [
            fingerprint_page(numero, f"NIC: {nic}" if nic else "hoja sin nic")
            for numero, nic in enumerate(nics, start=1)
        ]

    def test_gana_el_que_mas_hojas_comparten(self):
        """Medido: el NIC bueno salía en 27 hojas y el ruido del OCR en una."""
        huellas = self._huellas(["5825181"] * 27 + ["5820137"])
        assert nic_de_la_caja(huellas) == "5825181"

    def test_un_nic_que_sale_una_sola_vez_no_es_el_de_la_caja(self):
        """Con una aparición no hay forma de distinguirlo de la basura."""
        assert nic_de_la_caja(self._huellas(["5825181"])) is None

    def test_hacen_falta_al_menos_dos_hojas(self):
        huellas = self._huellas(["5825181"] * NIC_MIN_HOJAS)
        assert nic_de_la_caja(huellas) == "5825181"

    def test_una_caja_sin_nic_no_lo_inventa(self):
        assert nic_de_la_caja(self._huellas([None, None])) is None


class TestDondeCaenLosDocumentosDeUnaCaja:
    @staticmethod
    def _run(tmp_path):
        return FolderRun(
            id="corrida",
            source=tmp_path / "origen",
            destination=tmp_path / "destino",
        )

    @staticmethod
    def _job(report):
        trabajo = Job(id="t", filename="UPD2365925.pdf", source=Path("UPD2365925.pdf"))
        trabajo.report = report
        return trabajo

    def test_la_carpeta_se_llama_con_el_nic(self, tmp_path):
        run = self._run(tmp_path)
        origen = run.source / "108C000094" / "UPD2365925.pdf"
        carpeta = FolderRunner._output_dir(run, origen, self._job({"nic": "5825181"}))
        assert carpeta == run.destination / "108C000094" / "5825181"

    def test_sin_nic_se_cae_al_nombre_del_origen(self, tmp_path):
        """Que es lo que había antes y siempre existe."""
        run = self._run(tmp_path)
        origen = run.source / "108C000094" / "UPD2365925.pdf"
        carpeta = FolderRunner._output_dir(run, origen, self._job({}))
        assert carpeta == run.destination / "108C000094" / "UPD2365925"

    def test_un_nic_que_no_es_un_numero_no_nombra_una_carpeta(self, tmp_path):
        """Sólo dígitos: así ningún resto de OCR acaba en un nombre imposible."""
        run = self._run(tmp_path)
        origen = run.source / "UPD2365925.pdf"
        carpeta = FolderRunner._output_dir(run, origen, self._job({"nic": "58/25*181"}))
        assert carpeta == run.destination / "UPD2365925"

    def test_se_conserva_la_carpeta_de_la_que_salio(self, tmp_path):
        """El archivo entrega en cajas y cincuenta cajas no caben en un montón."""
        run = self._run(tmp_path)
        origen = run.source / "caja 12" / "sub" / "UPD2365925.pdf"
        carpeta = FolderRunner._output_dir(run, origen, self._job({"nic": "5825181"}))
        assert carpeta == run.destination / "caja 12" / "sub" / "5825181"

    def test_sin_informe_todavia_no_revienta(self, tmp_path):
        run = self._run(tmp_path)
        origen = run.source / "UPD2365925.pdf"
        assert FolderRunner._output_dir(run, origen, None) == (
            run.destination / "UPD2365925"
        )


class TestElInformeLlevaElNic:
    def test_una_caja_separada_publica_su_nic(self, tmp_path):
        """Va al informe para que la entrega pueda agrupar por él sin volver a
        abrir el PDF."""
        pymupdf = pytest.importorskip("pymupdf")
        from resolutions.api.settings import Settings
        from resolutions.api.worker import process_document_job
        from resolutions.application.task import TaskKind

        documento = pymupdf.open()
        for numero in (1, 2):
            page = documento.new_page()
            page.insert_textbox(
                pymupdf.Rect(56, 64, 540, 120),
                f"NOTIFICACION POR AVISO\nNIC: 5825181\nPágina {numero} de 2",
                fontsize=11,
            )
        caja = tmp_path / "caja.pdf"
        documento.save(caja)
        documento.close()

        informe = process_document_job(
            {
                "job_id": "t",
                "source": str(caja),
                "filename": "UPD2365925.pdf",
                "task": str(TaskKind.SEGMENT),
                "settings": Settings(output_dir=tmp_path / "out").as_worker_payload(),
            }
        )
        assert informe["nic"] == "5825181"
