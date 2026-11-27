"""El monitoreo de equipos por HTTP (2026-11-26): quién está conectado y pararlo.

El operador: «un monitoreo para ver los que están conectados y poder
desconectarlos». La pantalla lo pide cada 5 s y desde ahí da «Parar con calma»
o «Parar ya»; la próxima actualización de los siete PC se hace con «Parar
todos con calma». Lo que fija cada clase:

- ``TestLaLista``: ``GET /api/folder-runs/{id}/equipos`` contesta 404 de una
  corrida que no existe y, de una que va sola, ``compartida: false``, sin
  equipos, sin principal y con la velocidad en ceros (2026-11-27). De una
  compartida, el principal -- el primero en lanzar --, la velocidad por minuto,
  los recursos de cada PC y el aviso si otro PC tiene más núcleos.
- ``TestPararUnEquipo``: ``POST /api/folder-runs/{id}/equipos/{equipo}/parar``
  exige haber entrado (401); dice 404, 409 y 422 con su motivo; y sobre una
  corrida compartida de verdad para con calma al propio equipo, contesta la
  lista con la orden puesta, y la corrida entrega lo que tenía en curso y
  termina detenida diciendo por quién. Al equipo que se retiró después de la
  última mirada -- la lista aún lo da por vivo -- contesta 409 con el motivo,
  no 500: ``OrdenNoPermitida`` es una sola clase.
- ``TestElServicioLoAnuncia``: la revisión 26 y sus dos capacidades; la 27,
  con «pc-principal» y «velocidad-por-minuto».

Las corridas usan un trabajo falso y lento en lugar del pipeline: nada se lee
ni se paga.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from resolutions.application.coordinacion import (
    CORRIDA_TERMINADA,
    NO_ES_COMPARTIDA,
    NO_ESTA_EN_LA_CORRIDA,
)

#: Entrar como «siar»: la cabecera que cada endpoint lee (``identidad.quien_manda``).
SIAR = {"X-Cedula": "siar"}
#: Lo que tarda el trabajo falso en «leer» un PDF.
TARDA = 0.3


def _esperar(condicion, segundos: float = 20.0):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        valor = condicion()
        if valor:
            return valor
        time.sleep(0.02)
    return condicion()


@pytest.fixture
def motor(client, monkeypatch):
    """El ``FolderRunner`` del servicio, con un trabajo falso y lento y un latido corto."""
    from resolutions.api import main
    from resolutions.api.folders import FolderRunner

    registro = main.contexto.registry
    ajustes = main.contexto.settings

    async def run_job(job):
        await asyncio.sleep(TARDA)
        if job.state.value == "cancelled":
            return
        carpeta = ajustes.output_dir / job.id
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"01_{Path(job.filename).stem}.pdf").write_bytes(f"%PDF {job.filename}".encode())
        registro.mark_done(job, {"groups": [{"code": "01"}], "review_queue": []})

    nuevo = FolderRunner(registro, ajustes, run_job, watch_interval=0.01)
    nuevo.SEGUNDOS_DEL_LATIDO = 0.05
    nuevo.ESPERA_DE_LOS_OTROS = 0.05
    nuevo.ESPERA_AL_VACIARSE = 0.05
    monkeypatch.setattr(main.contexto, "folders", nuevo)
    return nuevo


def _carpetas(tmp_path: Path, *, pdfs: int) -> tuple[Path, Path]:
    origen, destino = tmp_path / "MAGANGUE", tmp_path / "destino"
    origen.mkdir()
    destino.mkdir()
    for numero in range(pdfs):
        nic = origen / f"70000{numero // 3:02d}"
        nic.mkdir(exist_ok=True)
        (nic / f"UPD70{numero:03d}.pdf").write_bytes(f"%PDF-1.4 {numero}".encode())
    return origen, destino


def _lanzar(client, origen: Path, destino: Path, **opciones) -> str:
    respuesta = client.post(
        "/api/folder-runs", json={"source": str(origen), "destination": str(destino), **opciones}
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _terminada(client, run_id: str) -> dict:
    estado = _esperar(
        lambda: (
            corrida
            if (corrida := client.get(f"/api/folder-runs/{run_id}").json())["state"] in ("done", "stopped", "failed")
            else None
        )
    )
    assert estado, "la corrida no terminó"
    return estado


class TestLaLista:
    def test_una_corrida_que_no_existe_es_404(self, client):
        respuesta = client.get("/api/folder-runs/no-existe/equipos")
        assert respuesta.status_code == 404
        assert respuesta.json()["detail"] == "El proceso de carpeta no existe"

    def test_una_corrida_que_va_sola_no_tiene_equipos(self, client, motor, tmp_path, monkeypatch):
        from resolutions.api.corrida_compartida import version_del_bot

        monkeypatch.setenv("BOTPDF_COORDINACION", "no")
        origen, destino = _carpetas(tmp_path, pdfs=0)
        # Vigilada, para que siga activa mientras se pregunta.
        run_id = _lanzar(client, origen, destino, watch=True)
        try:
            respuesta = client.get(f"/api/folder-runs/{run_id}/equipos")
            assert respuesta.status_code == 200
            assert respuesta.json() == {
                "compartida": False,
                "corrida": None,
                "version": version_del_bot(),
                "este": None,
                "activa": True,
                "principal": None,
                "velocidad": {
                    "pc_activos": 0,
                    "actual": {"total": None, "por_pc": None, "pc": 0},
                    "acumulada": {"total": None, "por_pc": None, "pc": 0},
                },
                "aviso_de_recursos": None,
                "equipos": [],
            }
        finally:
            client.post(f"/api/folder-runs/{run_id}/stop")

    def test_una_compartida_trae_el_principal_la_velocidad_y_los_recursos(self, client, motor, tmp_path, monkeypatch):
        import os

        from resolutions.adapters.coordinacion_en_disco import Coordinacion
        from resolutions.api.corrida_compartida import opciones_de, version_del_bot
        from resolutions.application.coordinacion import (
            CLAVES_DE_LOS_RECURSOS,
            equipo_en_palabras,
        )

        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = _carpetas(tmp_path, pdfs=0)
        # Vigilada, para que siga activa mientras se pregunta.
        run_id = _lanzar(client, origen, destino, watch=True)
        run = motor.get(run_id)
        nucleos = os.cpu_count() or 1
        # Otro PC con más núcleos, que se une después: el principal sigue siendo el primero.
        otro = None
        try:
            assert _esperar(lambda: run.coordinacion is not None), "la corrida no se unió"
            este = run.coordinacion.id

            def con_recursos() -> dict | None:
                lista = client.get(f"/api/folder-runs/{run_id}/equipos").json()
                return lista if (lista["equipos"] and lista["equipos"][0]["recursos"]) else None

            lista = _esperar(con_recursos)
            assert lista, "el latido no llegó a medir los recursos"
            assert lista["principal"] == este
            assert lista["velocidad"]["pc_activos"] == 1 and lista["aviso_de_recursos"] is None
            (fila,) = lista["equipos"]
            assert fila["principal"] and fila["entregados"] == 0
            # Recién unido: ni la velocidad de ahora ni la acumulada dicen nada todavía.
            assert fila["pdf_por_minuto"] is None and fila["pdf_por_minuto_promedio"] is None
            recursos = fila["recursos"]
            assert tuple(recursos) == CLAVES_DE_LOS_RECURSOS
            assert recursos["nucleos"] == nucleos
            assert recursos["disco_total"] >= recursos["disco_libre"] > 0 and recursos["disco"]

            otro = Coordinacion(
                run.destination,
                equipo="PC2",
                version=version_del_bot(),
                latido=0.05,
                medir_recursos=lambda: {"nucleos": nucleos + 8},
            )
            assert otro.unirse(opciones_de(run), origen=run.source.name)["id"] == run.coordinacion.corrida["id"]

            def con_los_dos() -> dict | None:
                lista = client.get(f"/api/folder-runs/{run_id}/equipos").json()
                fila = next((e for e in lista["equipos"] if e["id"] == otro.id), None)
                return lista if (fila and fila["vivo"] and fila["recursos"] and lista["aviso_de_recursos"]) else None

            lista = _esperar(con_los_dos)
            assert lista, "la lista no llegó a ver al otro con sus recursos"
            assert lista["principal"] == este and lista["velocidad"]["pc_activos"] == 2
            assert {e["id"]: e["principal"] for e in lista["equipos"]} == {este: True, otro.id: False}
            assert lista["aviso_de_recursos"] == (
                f"El principal {equipo_en_palabras(este)} tiene menos núcleos ({nucleos}) que {equipo_en_palabras(otro.id)} ({nucleos + 8}): "
                "conviene lanzar primero en el PC con más recursos."
            )
        finally:
            if otro is not None:
                otro.parar()
            client.post(f"/api/folder-runs/{run_id}/stop")


class TestPararUnEquipo:
    URL = "/api/folder-runs/{run_id}/equipos/{equipo}/parar"

    def test_sin_haber_entrado_es_401(self, client):
        respuesta = client.post(self.URL.format(run_id="no-existe", equipo="PC1-abc"), json={"modo": "calma"})
        assert respuesta.status_code == 401
        assert "siar" in respuesta.json()["detail"]

    def test_una_corrida_que_no_existe_es_404(self, client):
        respuesta = client.post(
            self.URL.format(run_id="no-existe", equipo="PC1-abc"), json={"modo": "calma"}, headers=SIAR
        )
        assert respuesta.status_code == 404
        assert respuesta.json()["detail"] == "El proceso de carpeta no existe"

    def test_un_modo_que_no_vale_es_422(self, client):
        respuesta = client.post(
            self.URL.format(run_id="no-existe", equipo="PC1-abc"), json={"modo": "despacio"}, headers=SIAR
        )
        assert respuesta.status_code == 422
        assert "«calma» o «ya»" in respuesta.json()["detail"]

    def test_una_corrida_que_va_sola_es_409(self, client, motor, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPDF_COORDINACION", "no")
        origen, destino = _carpetas(tmp_path, pdfs=0)
        run_id = _lanzar(client, origen, destino, watch=True)
        try:
            respuesta = client.post(self.URL.format(run_id=run_id, equipo="PC1-abc"), json={}, headers=SIAR)
            assert respuesta.status_code == 409
            assert respuesta.json()["detail"] == NO_ES_COMPARTIDA
        finally:
            client.post(f"/api/folder-runs/{run_id}/stop")

    def test_una_corrida_terminada_es_409(self, client, motor, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPDF_COORDINACION", "no")
        origen, destino = _carpetas(tmp_path, pdfs=0)
        run_id = _lanzar(client, origen, destino)
        _terminada(client, run_id)
        respuesta = client.post(self.URL.format(run_id=run_id, equipo="PC1-abc"), json={"modo": "ya"}, headers=SIAR)
        assert respuesta.status_code == 409
        assert respuesta.json()["detail"] == CORRIDA_TERMINADA

    def test_con_calma_al_propio_equipo_entrega_lo_suyo_y_se_detiene(self, client, motor, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = _carpetas(tmp_path, pdfs=12)
        run_id = _lanzar(client, origen, destino, paralelo=1)

        def leyendo():
            corrida = client.get(f"/api/folder-runs/{run_id}").json()
            return corrida if corrida["processed"] >= 1 and corrida["en_curso"] else None

        assert _esperar(leyendo), "la corrida no llegó a leer nada"
        lista = client.get(f"/api/folder-runs/{run_id}/equipos").json()
        assert lista["compartida"] and lista["activa"] and lista["corrida"]
        este = lista["este"]
        (fila,) = lista["equipos"]
        assert fila["id"] == este and fila["este"] and fila["vivo"] and fila["de_esta_corrida"]
        assert fila["misma_version"] and fila["estado"] == "procesando" and fila["unido"]
        assert fila["se_puede_parar"] and fila["por_que_no"] is None and fila["orden"] is None

        # Un equipo que no está en la corrida: 404, con el motivo.
        ajeno = client.post(self.URL.format(run_id=run_id, equipo="PC7-desconocido"), json={}, headers=SIAR)
        assert ajeno.status_code == 404
        assert ajeno.json()["detail"] == NO_ESTA_EN_LA_CORRIDA

        # Sin cuerpo, «calma». Contesta lo mismo que la lista, con la orden puesta.
        respuesta = client.post(
            self.URL.format(run_id=run_id, equipo=este), headers={**SIAR, "X-Operator": "Quien prueba"}
        )
        assert respuesta.status_code == 200, respuesta.text
        cuerpo = respuesta.json()
        assert set(cuerpo) == set(lista)
        (propio,) = cuerpo["equipos"]
        assert propio["orden"]["modo"] == "calma" and propio["orden"]["operador"] == "Quien prueba"
        assert propio["orden"]["por"] == este
        # Al propio equipo, directo: nada escrito en el destino.
        area = next(destino.rglob(".botpdf-coordinacion"))
        assert not list((area / "ordenes").glob("*.json"))

        # Entrega lo que estaba leyendo, no toma nada más y termina detenida, diciendo por quién.
        final = _terminada(client, run_id)
        assert final["state"] == "stopped"
        assert final["parando"]["modo"] == "calma"
        assert "Parar con calma" in final["detenido_por"] and "Quien prueba" in final["detenido_por"]
        assert 1 <= final["processed"] < 12 and final["failed"] == 0
        # Ya terminada, no se le ordena nada más.
        otra_vez = client.post(self.URL.format(run_id=run_id, equipo=este), json={"modo": "ya"}, headers=SIAR)
        assert otra_vez.status_code == 409
        # Y se retiró de la corrida compartida: su latido ya no está.
        assert _esperar(lambda: not (area / "equipos" / f"{este}.json").exists(), segundos=5)

    def test_al_que_se_retiro_tras_la_ultima_mirada_es_409_y_no_500(self, client, motor, tmp_path, monkeypatch):
        # La coordinación lo ve en el destino al ir a dejar la orden y lanza
        # ``OrdenNoPermitida``; con una copia de la clase en la API, salía un 500.
        import json

        from resolutions.adapters.coordinacion_en_disco import Coordinacion
        from resolutions.api import folders
        from resolutions.api.corrida_compartida import opciones_de, version_del_bot
        from resolutions.application import coordinacion as reglas

        assert folders.OrdenNoPermitida is reglas.OrdenNoPermitida
        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = _carpetas(tmp_path, pdfs=0)
        # Vigilada, para que siga activa mientras se pregunta.
        run_id = _lanzar(client, origen, destino, watch=True)
        run = motor.get(run_id)
        otro = None
        try:
            assert _esperar(lambda: run.coordinacion is not None), "la corrida no se unió"
            propia = run.coordinacion
            otro = Coordinacion(run.destination, equipo="PC2", version=version_del_bot(), latido=0.05)
            assert otro.unirse(opciones_de(run), origen=run.source.name)["id"] == propia.corrida["id"]

            def su_fila() -> dict | None:
                lista = client.get(f"/api/folder-runs/{run_id}/equipos").json()
                return next((e for e in lista["equipos"] if e["id"] == otro.id), None)

            assert _esperar(lambda: (su_fila() or {}).get("vivo")), "la lista no llegó a verlo"
            # La mirada de este equipo, quieta: lo que sigue pasa después de la
            # última. Va en un solo hilo, así que en cuanto da una vuelta quieta
            # la que estuviera en marcha ya acabó.
            quietas: list[int] = []
            monkeypatch.setattr(propia, "_mirar_a_los_demas", lambda: quietas.append(1))
            assert _esperar(lambda: quietas)
            otro.parar()
            fila = su_fila()
            assert fila["vivo"] and fila["se_puede_parar"], "la lista todavía lo da por vivo"
            url = self.URL.format(run_id=run_id, equipo=otro.id)
            respuesta = client.post(url, json={"modo": "calma"}, headers=SIAR)
            assert respuesta.status_code == 409, respuesta.text
            assert "ya se retiró" in respuesta.json()["detail"]
            # El que se retiró sin poder borrar su latido lo deja diciendo «terminado».
            (propia.area / "equipos" / f"{otro.id}.json").write_text(
                json.dumps({"id": otro.id, "equipo": "PC2", "estado": "terminado", "contador": 99}), encoding="utf-8"
            )
            respuesta = client.post(url, json={"modo": "ya"}, headers=SIAR)
            assert respuesta.status_code == 409, respuesta.text
            assert "ya se retiró" in respuesta.json()["detail"]
            # Ninguna orden quedó en el destino, para nadie.
            assert not list((propia.area / "ordenes").glob("*.json"))
        finally:
            if otro is not None:
                otro.parar()
            client.post(f"/api/folder-runs/{run_id}/stop")


class TestElServicioLoAnuncia:
    def test_la_revision_26_trae_el_monitoreo(self, client):
        salud = client.get("/api/health").json()
        assert salud["api_revision"] >= 26
        assert {"equipos-de-la-corrida", "parar-un-equipo"} <= set(salud["features"])

    def test_la_revision_27_trae_el_principal_y_la_velocidad(self, client):
        # La pantalla exige la 27 (REQUIRED_API_REVISION) para pintar el principal,
        # la velocidad por minuto y los recursos de cada PC (2026-11-27).
        salud = client.get("/api/health").json()
        assert salud["api_revision"] >= 27
        assert {"pc-principal", "velocidad-por-minuto"} <= set(salud["features"])
