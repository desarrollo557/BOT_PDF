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
    from resolutions.api import main
    from resolutions.api.janitor import IdleJanitor
    from resolutions.api.jobs import JobRegistry

    registry = JobRegistry()
    settings = replace(
        main.settings,
        upload_dir=tmp_path / "uploads",
        output_dir=tmp_path / "outputs",
        ledger_path=tmp_path / "inventory.jsonl",
        # Long enough that the background ticker never fires mid-test; the sweep
        # is exercised directly instead, where its timing is not a coin flip.
        sweep_seconds=3600.0,
    )
    ledger = InventoryLedger(settings.ledger_path)

    monkeypatch.setattr(main, "registry", registry)
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "ledger", ledger)
    monkeypatch.setattr(
        main, "janitor", IdleJanitor(registry, settings, referenced=ledger.job_ids)
    )
    with TestClient(main.app) as running:
        yield running
