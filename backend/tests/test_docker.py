"""BOT_PDF dentro de Docker: rutas del equipo, página única y paquete completo.

En el contenedor el servicio corre en Linux y ve los discos de Windows montados
en /equipo/<letra>. Lo que el operador pega o elige sigue siendo «C:\\…», y lo
que se le enseña también. Fuera de Docker (sin BOTPDF_UNIDADES) nada cambia.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from resolutions.api import rutas_del_equipo as rutas
from resolutions.api.rutas_del_equipo import al_operador, al_servicio, raices

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def en_docker(monkeypatch, tmp_path):
    c = tmp_path / "equipo" / "c"
    z = tmp_path / "equipo" / "z"
    c.mkdir(parents=True)
    z.mkdir(parents=True)
    montajes = {"C": c.as_posix(), "Z": z.as_posix()}
    monkeypatch.setenv(rutas.VARIABLE, ";".join(f"{letra}:={montaje}" for letra, montaje in montajes.items()))
    return montajes


class TestLasRutasDelEquipo:
    def test_fuera_de_docker_nada_cambia(self, monkeypatch):
        monkeypatch.delenv(rutas.VARIABLE, raising=False)
        assert al_servicio(r"C:\Users\ana\ENTRADA") == r"C:\Users\ana\ENTRADA"
        assert al_operador("/data/x") == "/data/x"
        assert raices() == []

    def test_la_ruta_de_windows_se_encuentra_en_el_contenedor(self, monkeypatch):
        monkeypatch.setenv(rutas.VARIABLE, "C:=/equipo/c;Z:=/equipo/z")
        assert al_servicio(r"C:\Users\ana\ENTRADA") == "/equipo/c/Users/ana/ENTRADA"
        assert al_servicio("z:/Shared with Me/REPOSITORIO UDC") == "/equipo/z/Shared with Me/REPOSITORIO UDC"
        assert al_servicio("C:\\") == "/equipo/c"
        assert al_servicio("C:") == "/equipo/c"

    def test_y_se_le_ensena_al_operador_como_la_conoce(self, monkeypatch):
        monkeypatch.setenv(rutas.VARIABLE, "C:=/equipo/c;Z:=/equipo/z")
        assert al_operador("/equipo/c/Users/ana/ENTRADA") == r"C:\Users\ana\ENTRADA"
        assert al_operador("/equipo/z") == "Z:\\"
        # Lo que no es de un disco montado pasa tal cual.
        assert al_operador("/data/outputs") == "/data/outputs"
        assert al_operador("/equipo/cc/otra") == "/equipo/cc/otra"

    def test_una_unidad_no_montada_pasa_tal_cual(self, monkeypatch):
        monkeypatch.setenv(rutas.VARIABLE, "C:=/equipo/c")
        assert al_servicio(r"D:\fotos") == r"D:\fotos"

    def test_las_unidades_son_los_puntos_de_partida(self, monkeypatch):
        monkeypatch.setenv(rutas.VARIABLE, "Z:=/equipo/z;C:=/equipo/c")
        assert raices() == [
            {"name": "Disco C:", "path": "C:\\"},
            {"name": "Disco Z:", "path": "Z:\\"},
        ]


class TestUnaCorridaConRutasDeWindows:
    def test_valida_y_ensena_las_rutas_del_operador(self, en_docker):
        from resolutions.api.folders import FolderRun, validate_folders

        (Path(en_docker["C"]) / "ENTRADA").mkdir()
        origen, destino = validate_folders(r"C:\ENTRADA", r"C:\DESTINO")

        assert origen == Path(en_docker["C"]) / "ENTRADA"
        assert destino.is_dir()
        aviso = FolderRun(id="r", source=origen, destination=destino).as_dict()
        assert aviso["source"] == r"C:\ENTRADA"
        assert aviso["destination"] == r"C:\DESTINO"

    def test_el_explorador_lista_las_unidades_y_sus_carpetas(self, en_docker):
        import asyncio
        from types import SimpleNamespace

        from resolutions.api.routers.carpetas import browse

        (Path(en_docker["Z"]) / "Shared with Me").mkdir()
        inicio = asyncio.run(browse(SimpleNamespace(), None))
        assert [d["path"] for d in inicio["drives"]] == ["C:\\", "Z:\\"]

        z = asyncio.run(browse(SimpleNamespace(), "Z:\\"))
        assert z["path"] == "Z:\\"
        assert z["parent"] is None
        assert z["folders"] == [{"name": "Shared with Me", "path": r"Z:\Shared with Me"}]


class TestLaPaginaUnica:
    def test_recargar_una_ruta_del_front_sirve_la_pagina(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from resolutions.api.main import _Pantalla

        (tmp_path / "index.html").write_text("<html>BOT_PDF</html>", encoding="utf-8")
        (tmp_path / "app.js").write_text("console.log(1)", encoding="utf-8")
        app = FastAPI()

        @app.get("/api/health")
        def salud():
            return {"status": "ok"}

        app.mount("/", _Pantalla(directory=str(tmp_path), html=True), name="frontend")
        cliente = TestClient(app)

        assert cliente.get("/api/health").json() == {"status": "ok"}
        assert cliente.get("/app.js").text == "console.log(1)"
        assert "BOT_PDF" in cliente.get("/archivo").text
        assert "BOT_PDF" in cliente.get("/revision/123").text
        # Una ruta de la API que no existe sigue siendo un 404.
        assert cliente.get("/api/no-existe").status_code == 404
        # Y un archivo que no existe también: un .js viejo que recibía HTML
        # hacía fallar el script y la pestaña se recargaba sin parar.
        assert cliente.get("/_app/immutable/chunks/viejo.js").status_code == 404
        assert cliente.get("/favicon-que-no-existe.png").status_code == 404


class TestElPaqueteLlevaSusPlantillas:
    def test_las_plantillas_estan_declaradas_y_existen(self):
        """Instalado con pip -- como en la imagen -- sin esto no viajaban."""
        proyecto = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
        patrones = proyecto["tool"]["setuptools"]["package-data"]["resolutions"]
        paquete = RAIZ / "src" / "resolutions"
        incluidas = {p.relative_to(paquete).as_posix() for patron in patrones for p in paquete.glob(patron)}
        en_assets = {
            p.relative_to(paquete).as_posix() for p in (paquete / "assets").rglob("*") if p.is_file()
        }
        assert en_assets <= incluidas


class TestLosArchivosDeDocker:
    def test_las_variables_del_contenedor_existen_en_el_codigo(self):
        """El Dockerfile y el compose sólo fijan variables que el servicio lee."""
        import re

        codigo = "\n".join(p.read_text(encoding="utf-8") for p in (RAIZ / "src").rglob("*.py"))
        for archivo in ("Dockerfile", "docker-compose.yml"):
            texto = (RAIZ.parent / archivo).read_text(encoding="utf-8")
            # Las ${...} las interpreta Docker Compose (el puerto), no el servicio.
            texto = re.sub(r"\$\{[^}]*\}", "", texto)
            # Y los comentarios sólo explican.
            texto = re.sub(r"(?m)^\s*#.*$", "", texto)
            for variable in set(re.findall(r"\b((?:RESOLUTIONS|BOTPDF)_[A-Z_]+)\b", texto)):
                assert f'"{variable}"' in codigo or f"'{variable}'" in codigo, f"{archivo}: {variable} no la lee nadie"
