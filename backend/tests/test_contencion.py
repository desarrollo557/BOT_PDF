"""Lo que llega del cliente no sale de donde el servicio puede escribir.

El servicio se publica en la red del cliente sin contraseña (2026-10-27): toda
ruta, id o texto que llega en una petición puede venir de cualquier equipo.
Esto fija que ninguno de ellos lleve a leer, escribir o borrar fuera de su
sitio, ni a ejecutar nada.
"""

from __future__ import annotations

import pytest

from resolutions.adapters import red_smb


class TestUnaRutaDeRedNoSubeCarpetas:
    @pytest.mark.parametrize(
        "ruta",
        [
            r"\\..\r\x",
            r"\\servidor\..\x",
            r"\\servidor\recurso\..\..\equipo\c\Users",
            r"\\servidor\recurso\a\.\b",
        ],
    )
    def test_puntos_en_la_ruta_no_son_una_ruta_de_red(self, ruta):
        """La copia local se arma con estos trozos: «..» la sacaba de su carpeta y pisaba archivos del equipo."""
        assert red_smb.partes(ruta) is None

    def test_una_ruta_normal_sigue_siendolo(self):
        partes = red_smb.partes(r"\\200.100.20.97\afinia\REPOSITORIO\MAGANGUE")
        assert partes is not None and partes.resto == r"REPOSITORIO\MAGANGUE"

    def test_la_copia_local_no_sale_de_su_carpeta(self, tmp_path, monkeypatch):
        from dataclasses import replace
        from pathlib import Path

        from resolutions.api.folders import FolderRun, FolderRunner
        from resolutions.api.jobs import JobRegistry
        from resolutions.api.settings import Settings

        # Como en Docker, donde las carpetas de red se leen con el cliente SMB.
        monkeypatch.setattr(red_smb, "por_smb", lambda ruta: red_smb.es_de_red(ruta))
        motor = FolderRunner(JobRegistry(), replace(Settings(), upload_dir=tmp_path / "u"), run_job=None)
        run = FolderRun(id="r", source=Path(r"\\s\r"), destination=tmp_path / "d")
        copia = motor._copia_local(run, Path(r"\\s\r\UPD1.pdf"))
        assert (tmp_path / "u").resolve() in copia.resolve().parents


class TestElFuidDeUnTrabajo:
    def test_el_id_no_sale_de_la_carpeta_de_salidas(self, client, tmp_path):
        from resolutions.api import main
        from resolutions.api.worker import FUID_SUFFIX

        salidas = main.contexto.settings.output_dir
        salidas.mkdir(parents=True, exist_ok=True)
        (salidas.parent / f"secreto{FUID_SUFFIX}").write_bytes(b"x")

        respuesta = client.get("/api/jobs/%2E%2E/fuid")
        assert respuesta.status_code != 200 or not respuesta.json().get("ready")


class TestBorrarUnDocumento:
    def test_solo_borra_carpetas_de_trabajos(self, client):
        """Un nombre que no es un id de trabajo borraba con rmtree cualquier carpeta de salidas."""
        from resolutions.api import main

        lote = main.contexto.settings.output_dir / "lote-generales"
        lote.mkdir(parents=True)
        (lote / "00.FUID GENERAL.xlsx").write_bytes(b"x")

        respuesta = client.delete("/api/documents/lote-generales")

        assert respuesta.status_code == 404
        assert lote.exists()


class TestElSelectorNativo:
    def test_el_titulo_no_viaja_en_la_linea_de_comandos(self, monkeypatch):
        """En PowerShell 5.1 lo que va tras -Command se concatena al script y se ejecuta."""
        import subprocess

        from resolutions.api import native_picker

        visto: dict = {}

        def ejecutar(argumentos, **opciones):
            visto["argumentos"] = argumentos
            visto["env"] = opciones.get("env") or {}
            return subprocess.CompletedProcess(argumentos, 0, stdout="", stderr="")

        monkeypatch.setattr(native_picker.os, "name", "nt")
        monkeypatch.setattr(native_picker.subprocess, "run", ejecutar)
        titulo = "x'; Remove-Item C:\\ -Recurse; '"

        native_picker.ask_directory(titulo)

        assert titulo not in " ".join(visto["argumentos"])
        assert visto["env"].get("BOTPDF_TITULO") == titulo


class TestLasCarpetasDelServicio:
    """Origen o destino dentro de las carpetas del propio servicio: borraría o pisaría sus datos."""

    def test_no_son_ni_origen_ni_destino(self, tmp_path):
        from resolutions.api.folders import FolderError, validate_folders

        datos = tmp_path / "data"
        (datos / "uploads").mkdir(parents=True)
        afuera = tmp_path / "caja"
        afuera.mkdir()
        internas = [datos]

        with pytest.raises(FolderError):
            validate_folders(str(datos / "uploads"), str(tmp_path / "salida"), internas=internas)
        with pytest.raises(FolderError):
            validate_folders(str(afuera), str(datos / "outputs" / "x"), internas=internas)
        # Un origen por encima de los datos los recorrería: con «Borrarlo», los borraría.
        with pytest.raises(FolderError):
            validate_folders(str(tmp_path), str(tmp_path.parent / "salida-aparte"), internas=internas)
        # Lo de siempre sigue valiendo.
        origen, destino = validate_folders(str(afuera), str(tmp_path / "salida"), internas=internas)
        assert origen == afuera.resolve()
