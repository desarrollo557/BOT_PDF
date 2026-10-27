"""Un Excel se guarda entero o no se guarda: nunca a medias con su nombre final."""

from __future__ import annotations

import errno

import pytest

openpyxl = pytest.importorskip("openpyxl")

from resolutions.adapters.guardar_libro import guardar_libro  # noqa: E402


def _libro(texto: str):
    libro = openpyxl.Workbook()
    libro.active["A1"] = texto
    return libro


def test_guarda_y_se_puede_leer(tmp_path):
    ruta = guardar_libro(_libro("hola"), tmp_path / "00.FUID GENERAL.xlsx")

    assert openpyxl.load_workbook(ruta).active["A1"].value == "hola"
    assert [p.name for p in tmp_path.iterdir()] == ["00.FUID GENERAL.xlsx"]


def test_un_guardado_cortado_deja_el_anterior_intacto(tmp_path, monkeypatch):
    ruta = guardar_libro(_libro("el bueno"), tmp_path / "a.xlsx")
    libro = _libro("el nuevo")

    def cortado(destino):
        with open(destino, "wb") as archivo:
            archivo.write(b"PK\x03\x04 a medias")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(libro, "save", cortado)
    with pytest.raises(OSError):
        guardar_libro(libro, ruta)

    assert openpyxl.load_workbook(ruta).active["A1"].value == "el bueno"
    assert [p.name for p in tmp_path.iterdir()] == ["a.xlsx"]


def test_si_el_destino_no_se_deja_reemplazar_el_temporal_no_queda(tmp_path, monkeypatch):
    import os

    def abierto(desde, hasta):
        raise PermissionError(errno.EACCES, "Permission denied", str(hasta))

    monkeypatch.setattr(os, "replace", abierto)
    with pytest.raises(PermissionError):
        guardar_libro(_libro("x"), tmp_path / "a.xlsx")

    assert list(tmp_path.iterdir()) == []
