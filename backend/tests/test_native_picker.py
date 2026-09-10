"""El explorador de carpetas de Windows, abierto por el servicio.

Un navegador no puede entregar una ruta absoluta: ni `showDirectoryPicker` ni
`webkitdirectory` la exponen, por diseño. El servicio sí puede, porque corre en
la misma máquina que el escritorio donde aparece la ventana. Eso también marca
su límite, y es lo que estos tests fijan: cuando no hay escritorio que usar, la
respuesta lo dice en vez de colgarse.
"""

from __future__ import annotations

import pytest

pytest.importorskip("httpx")

from resolutions.api import native_picker  # noqa: E402


def _en_windows(monkeypatch, *, powershell="C:/Windows/powershell.exe", estacion=True):
    """Windows, con o sin PowerShell, con o sin escritorio que enseñar."""
    monkeypatch.setattr(native_picker.os, "name", "nt")
    monkeypatch.setattr(native_picker.shutil, "which", lambda name: powershell)
    monkeypatch.setattr(native_picker, "_estacion_visible", lambda: estacion)


class TestDisponibilidad:
    def test_fuera_de_windows_no_hay_dialogo(self, monkeypatch):
        monkeypatch.setattr(native_picker.os, "name", "posix")
        assert native_picker.available() is False
        with pytest.raises(native_picker.PickerUnavailable, match="Windows"):
            native_picker.ask_directory("Elija")

    def test_en_el_escritorio_del_operador_si_lo_hay(self, monkeypatch):
        _en_windows(monkeypatch)
        assert native_picker.available() is True

    def test_un_servicio_sin_escritorio_no_ofrece_dialogo(self, monkeypatch):
        # El error que esto fija: `available()` terminaba en `... or True` y
        # contestaba que sí en cualquier Windows. La pantalla abría entonces un
        # diálogo en una estación que nadie ve, y la petición se quedaba
        # esperando los cinco minutos del temporizador en vez de caer en el
        # explorador propio del navegador.
        _en_windows(monkeypatch, estacion=False)
        assert native_picker.available() is False

    def test_sin_powershell_tampoco(self, monkeypatch):
        # Es quien abre el diálogo: sin él `ask_directory` sólo sabe fallar, y
        # anunciarlo disponible es prometer algo que no se puede cumplir.
        _en_windows(monkeypatch, powershell=None)
        assert native_picker.available() is False

    def test_no_poder_preguntar_no_es_un_no(self, monkeypatch):
        # La duda se resuelve como la máquina del operador, que es el caso
        # normal: perder el explorador nativo por una consulta que falló sería
        # cambiar una comodidad probada por una precaución sin medir.
        _en_windows(monkeypatch, estacion=None)
        assert native_picker.available() is True


class TestElEndpoint:
    def test_devuelve_la_ruta_elegida(self, client, monkeypatch, tmp_path):
        from resolutions.api import main

        monkeypatch.setattr(
            main.native_picker, "ask_directory", lambda title, initial: str(tmp_path)
        )
        payload = client.post("/api/folders/pick", json={"title": "Origen"}).json()
        assert payload["path"] == str(tmp_path)
        assert payload["cancelled"] is False

    def test_cancelar_no_es_un_error(self, client, monkeypatch):
        # Cerrar el diálogo sin elegir es una respuesta legítima, no un fallo.
        from resolutions.api import main

        monkeypatch.setattr(main.native_picker, "ask_directory", lambda title, initial: None)
        payload = client.post("/api/folders/pick", json={}).json()
        assert payload["path"] is None
        assert payload["cancelled"] is True

    def test_sin_escritorio_responde_501_y_no_500(self, client, monkeypatch):
        # 501 es lo que la pantalla mira para caer en su propio explorador. Un
        # 500 la dejaría mostrando un error en vez de la alternativa.
        from resolutions.api import main

        def sin_ventana(title, initial):
            raise native_picker.PickerUnavailable("No hay escritorio")

        monkeypatch.setattr(main.native_picker, "ask_directory", sin_ventana)
        response = client.post("/api/folders/pick", json={})
        assert response.status_code == 501
        assert "escritorio" in response.json()["detail"]

    def test_la_carpeta_inicial_llega_limpia(self, client, monkeypatch, tmp_path):
        # La misma tolerancia que el resto: si viene entrecomillada, se limpia
        # antes de que el diálogo intente abrirla.
        from resolutions.api import main

        visto = {}

        def recordar(title, initial):
            visto["initial"] = initial
            return None

        monkeypatch.setattr(main.native_picker, "ask_directory", recordar)
        client.post("/api/folders/pick", json={"initial": f'"{tmp_path}"'})
        assert visto["initial"] == str(tmp_path)

    def test_un_titulo_absurdo_se_recorta(self, client, monkeypatch):
        from resolutions.api import main

        visto = {}

        def recordar(title, initial):
            visto["title"] = title
            return None

        monkeypatch.setattr(main.native_picker, "ask_directory", recordar)
        client.post("/api/folders/pick", json={"title": "x" * 500})
        assert len(visto["title"]) == 120

    def test_health_dice_si_hay_explorador_nativo(self, client):
        # La pantalla no tiene por qué descubrirlo fallando.
        assert "native_picker" in client.get("/api/health").json()
