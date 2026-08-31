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

    from resolutions.api import main
    from resolutions.api.jobs import JobRegistry

    monkeypatch.setattr(main, "registry", JobRegistry())
    monkeypatch.setattr(
        main,
        "settings",
        replace(main.settings, upload_dir=tmp_path / "uploads", output_dir=tmp_path / "outputs"),
    )
    with TestClient(main.app) as running:
        yield running
