from __future__ import annotations

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient with its own registry and its own directories.

    The API keeps job state in a module-level registry. Handing each test a fresh
    one is what stops a batch created in one test from showing up in the next.
    """
    pytest.importorskip("httpx")
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from resolutions.adapters.ledger import InventoryLedger
    from resolutions.adapters.user_store import FileUserStore
    from resolutions.api import main
    from resolutions.api.janitor import IdleJanitor
    from resolutions.api.jobs import JobRegistry
    from resolutions.application.usuarios import Usuarios

    registry = JobRegistry()
    settings = replace(
        main.contexto.settings,
        upload_dir=tmp_path / "uploads",
        output_dir=tmp_path / "outputs",
        ledger_path=tmp_path / "inventory.jsonl",
        # Y las altas también. Sin esto una prueba leería -- y escribiría -- el
        # archivo de usuarios de la máquina de quien la corre.
        users_path=tmp_path / "usuarios.jsonl",
        # Long enough that the background ticker never fires mid-test; the sweep
        # is exercised directly instead, where its timing is not a coin flip.
        sweep_seconds=3600.0,
    )
    ledger = InventoryLedger(settings.ledger_path)

    monkeypatch.setattr(main.contexto, "registry", registry)
    monkeypatch.setattr(main.contexto, "settings", settings)
    monkeypatch.setattr(main.contexto, "ledger", ledger)
    monkeypatch.setattr(
        main.contexto, "usuarios", Usuarios(FileUserStore(settings.users_path))
    )
    monkeypatch.setattr(
        main.contexto, "janitor", IdleJanitor(registry, settings, referenced=ledger.job_ids)
    )
    with TestClient(main.app) as running:
        yield running


@pytest.fixture
def administrador(client):
    """Un administrador dado de alta, y la cabecera con que se identifica.

    Sobre un almacén vacío la primera entrada queda como administradora, así que
    basta con entrar. Devuelve la cabecera lista para pasarla a cualquier
    petición que exija perfil.
    """
    respuesta = client.post(
        "/api/sesion", json={"cedula": "1047382991", "correo": "jefe@archivo.edu.co"}
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["perfil"] == "administrador"
    return {"X-Cedula": "1047382991"}


@pytest.fixture
def tecnico(client, administrador):
    """Alguien de perfil técnico, dado de alta por el administrador."""
    respuesta = client.post(
        "/api/usuarios",
        headers=administrador,
        json={
            "cedula": "52814663",
            "correo": "tecnico@archivo.edu.co",
            "perfil": "tecnico",
            "nombre": "Quien procesa",
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return {"X-Cedula": "52814663"}


@pytest.fixture
def calidad(client, administrador):
    """Alguien de perfil calidad, dado de alta por el administrador."""
    respuesta = client.post(
        "/api/usuarios",
        headers=administrador,
        json={
            "cedula": "39158204",
            "correo": "calidad@archivo.edu.co",
            "perfil": "calidad",
            "nombre": "Quien revisa",
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return {"X-Cedula": "39158204"}
