"""Los pendientes del agente (2026-11-23): el juez de la IA, la relectura girada y el «Confirmar» que no falla.

El operador: «implementa los pendientes, el juez de IA y lo demás». Los RE y
los nombres son inventados.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from resolutions.adapters.indice_electronico import leer_indice
from resolutions.domain.evidencia import Candidato
from resolutions.domain.resolutor_del_re import (
    MEDIA,
    ContextoDelRe,
    destinos_de,
    eleccion_del_juez,
    resolver_sin_certeza,
)
from resolutions.domain.sello import OFICINAS_QUE_RADICAN, Sello

RE = "RE2310202408897"
OTRO = "RE2310202408877"


class TestElJuezDeLaIA:
    def test_solo_vale_uno_de_lo_leido(self):
        assert eleccion_del_juez(f"El que se ve es {RE}", [RE, OTRO]) == RE
        assert eleccion_del_juez("RE 2310 2024 08897", [RE, OTRO]) == RE
        assert eleccion_del_juez("ninguno", [RE, OTRO]) is None
        # Un RE que nadie leyó no vale, aunque el juez lo diga.
        assert eleccion_del_juez("RE2310202408899", [RE, OTRO]) is None
        # Dos de la lista: no eligió.
        assert eleccion_del_juez(f"{RE} o {OTRO}", [RE, OTRO]) is None

    def test_lo_que_elige_decide_el_empate(self):
        candidatos = [Candidato(OTRO, "los lectores leen RE distintos", 1), Candidato(RE, "los lectores leen RE distintos", 1)]
        contexto = ContextoDelRe(oficinas_que_radican=frozenset(OFICINAS_QUE_RADICAN), elegido_por_el_juez=RE)
        decision = resolver_sin_certeza(candidatos, contexto)
        assert (decision.valor, decision.confianza) == (RE, MEDIA) and "juez" in decision.regla
        # Lo que no está entre lo leído no lo toma.
        otro = replace(contexto, elegido_por_el_juez="RE2310202408899")
        assert resolver_sin_certeza(candidatos, otro).valor == OTRO

    def test_las_opciones_incluyen_la_correccion(self):
        candidatos = [Candidato("RE2673202100532", "oficina 2673 leída por 8673: sería RE8673202100532", 1)]
        assert destinos_de(candidatos) == ["RE8673202100532"]


class TestLaRelecturaGirada:
    class _Fuente:
        def render(self, pagina, banda, dpi, formato="png"):
            return b"imagen"

    class _DePago:
        def read(self, imagen):
            return type("R", (), {"text": "FECHA DE RECIBO 29-04-2024"})()

    def test_si_derecho_no_sale_lee_girado(self):
        from resolutions.application.sellos import releer_la_zona_del_sello

        sello = Sello("tinta", None, None, zona=(0.6, 0.7, 0.9, 0.9))
        giradas = []

        def girada(imagen):
            giradas.append(imagen)
            return f"RE: {RE}"

        releidos = releer_la_zona_del_sello(
            self._Fuente(), {1: sello}, de_pago=self._DePago(), vision=lambda _: "RE: no hay", vision_girada=girada, workers=1
        )
        assert len(giradas) == 1
        assert ("visión girada", f"RE: {RE}") in releidos[1].lecturas

    def test_si_derecho_sale_no_gira(self):
        from resolutions.application.sellos import releer_la_zona_del_sello

        sello = Sello("tinta", None, None, zona=(0.6, 0.7, 0.9, 0.9))
        giradas = []
        releer_la_zona_del_sello(
            self._Fuente(),
            {1: sello},
            de_pago=self._DePago(),
            vision=lambda _: f"RE: {RE}",
            vision_girada=lambda imagen: giradas.append(imagen) or "",
            workers=1,
        )
        assert giradas == []


class TestLaConstanciaEntera:
    def test_el_re_del_operador_cierra_su_revision_y_su_decision(self):
        from resolutions.api import constancia as constancias
        from resolutions.api.correccion_del_re import CONFIRMADO, re_en_la_constancia

        constancia = constancias.Constancia(
            origen="1001051/UPD1.pdf",
            tamano=1,
            modificado_ns=1,
            estado=constancias.EstadoDeEntrega.COMPLETA,
            archivos=[{"ruta": "01_RECLAMO.pdf", "bytes": 1}],
            indice={"filas": [{"nombre": "RECLAMO"}]},
            evidencia={"re": {"1": {"estado": "requiere validación"}}},
            revision=[{"page": 1, "reason": "RE por confirmar, el nombre va sin él…"}, {"page": 2, "reason": "la fecha no se leyó"}],
            decisiones_del_agente=[{"page": 1, "paginas": [1, 2], "valor": OTRO, "regla": "el más votado"}],
            documentos=[{"hojas": [1, 2]}],
        )
        assert re_en_la_constancia(constancia, 0, RE, "SIAR") == []
        assert constancia.archivos[0]["ruta"] == f"01_RECLAMO-{RE}.pdf"
        assert constancia.indice["filas"][0]["nombre"] == f"RECLAMO-{RE}"
        assert constancia.evidencia["re"]["1"]["estado"] == "verificado"
        assert constancia.evidencia["re"]["1"]["metodo"] == CONFIRMADO
        assert constancia.revision[0]["resuelto"]["accion"] == CONFIRMADO
        assert "resuelto" not in constancia.revision[1]
        assert constancia.decisiones_del_agente[0]["valor"] == RE


class TestSinLaCorrida:
    def test_el_re_llega_al_destino_por_las_rutas_guardadas(self, tmp_path):
        from test_entrega_plana import _caja, _indice

        from resolutions.api import constancia as constancias
        from resolutions.api.correccion_del_re import corregir_re_en_el_destino
        from resolutions.api.folders import FolderRunner, RunState
        from resolutions.api.jobs import JobRegistry
        from resolutions.api.settings import Settings

        ajustes = replace(
            Settings(),
            upload_dir=tmp_path / "uploads",
            output_dir=tmp_path / "outputs",
            ledger_path=tmp_path / "inventory.jsonl",
            pausa_tras_fallos=0.01,
        )
        ajustes.ensure_directories()
        registro = JobRegistry()

        async def run_job(job):
            salida = ajustes.output_dir / job.id / "UPD1"
            salida.mkdir(parents=True, exist_ok=True)
            (salida / "01_RECLAMO.pdf").write_bytes(b"%PDF-1.4 reclamo")
            _indice(salida, "UPD1", "RECLAMO")
            registro.mark_done(
                job, {"groups": [{"code": "01", "pages": [1]}], "review_queue": [], "indice_electronico": "00.INDICE ELECTRONICO.xlsx"}
            )

        motor = FolderRunner(registro, ajustes, run_job, watch_interval=0.01)
        _caja(tmp_path / "origen", "1001051", "UPD1")

        async def ir():
            run = motor.start(str(tmp_path / "origen"), str(tmp_path / "destino"), task="segment")
            for _ in range(800):
                if not run.active:
                    return run
                await asyncio.sleep(0.01)
            return run

        run = asyncio.run(ir())
        assert run.state is RunState.DONE
        job = next(j for j in registro.list() if j.filename.endswith("UPD1.pdf"))
        donde = job.report["donde_se_entrega_el_re"]
        # La corrida ya no está: por las rutas guardadas.
        motor._runs.clear()
        assert not motor.tiene_la_corrida(job)
        assert corregir_re_en_el_destino(donde, 0, RE, "SIAR") == []
        caja = tmp_path / "destino" / "1001051"
        assert (caja / f"01_RECLAMO-{RE}.pdf").is_file() and not (caja / "01_RECLAMO.pdf").exists()
        constancia = constancias.leer(caja / ".bot-entrega-UPD1.json")
        assert [a["ruta"] for a in constancia.archivos if a["ruta"].endswith(".pdf")] == [f"01_RECLAMO-{RE}.pdf"]
        assert [f.nombre for f in leer_indice(caja / "00.INDICE ELECTRONICO.xlsx").filas] == [f"RECLAMO-{RE}"]

    def test_la_red_sin_la_corrida_se_dice(self, monkeypatch):
        from resolutions.adapters import red_smb
        from resolutions.api.correccion_del_re import corregir_re_en_el_destino

        # En Docker la red se lee con el cliente propio, con credenciales en memoria.
        monkeypatch.setattr(red_smb, "por_smb", lambda ruta: str(ruta).startswith("//"))
        avisos = corregir_re_en_el_destino({"carpeta": "//servidor/afinia/1001051", "constancia": "//servidor/x.json"}, 0, RE)
        assert avisos and "red" in avisos[0]
        assert "no se guardó" in corregir_re_en_el_destino(None, 0, RE)[0]


class TestLoQueCorrigioLaRevision:
    """La revisión adversarial del 2026-11-23: 14 fallos confirmados, cada uno fijado aquí."""

    def test_el_juez_que_descarta_no_elige(self):
        assert eleccion_del_juez(f"Ninguno, el más parecido es {RE}.", [RE, OTRO]) is None
        assert eleccion_del_juez(f"No es {RE}", [RE, OTRO]) is None
        # El prefijo de un número más largo no es un RE.
        assert eleccion_del_juez(f"{RE}9", [RE, OTRO]) is None
        assert eleccion_del_juez(f"X{RE}", [RE, OTRO]) is None
        assert eleccion_del_juez(f"«{RE}».", [RE, OTRO]) == RE

    def test_lo_del_juez_que_el_auditor_no_sostiene_no_desplaza_a_las_reglas(self):
        candidatos = [
            Candidato("RE8673202100532", "los lectores leen RE distintos", 1),
            Candidato("RE8673201900532", "los lectores leen RE distintos", 1),
        ]
        contexto = ContextoDelRe(
            oficinas_que_radican=frozenset(OFICINAS_QUE_RADICAN), anio=2021, elegido_por_el_juez="RE8673201900532"
        )
        decision = resolver_sin_certeza(candidatos, contexto)
        assert decision.valor == "RE8673202100532" and "juez" not in decision.regla

    def test_las_opciones_son_lo_que_el_agente_puede_elegir(self):
        candidatos = [
            Candidato(RE, "hallado en el barrido de la hoja: el reclamo cita RE de otras reclamaciones", 1),
            Candidato(OTRO, "los lectores leen RE distintos", 1),
        ]
        assert destinos_de(candidatos, ContextoDelRe()) == [OTRO]

    def test_la_girada_sola_no_se_cree(self):
        from resolutions.application.sellos import re_que_se_cree
        from resolutions.domain.evidencia import (
            LECTOR_GIRADO,
            EvidenciaDeRE,
            decidir_el_re,
        )

        sello = Sello("tinta", None, None, lecturas=((LECTOR_GIRADO, f"RE: {RE}"),))
        assert re_que_se_cree(sello) is None
        hallazgo = decidir_el_re([EvidenciaDeRE(1, "sello de tinta", None, ((LECTOR_GIRADO, f"RE: {RE}"),))])
        assert not hallazgo.se_cree and hallazgo.candidatos[0].motivo == "leído sólo con la imagen girada"

    def test_la_girada_no_toma_el_re_que_la_carta_cita(self):
        from resolutions.application.sellos import releer_la_zona_del_sello

        class DePagoConCita:
            def read(self, imagen):
                return type("R", (), {"text": f"según la reclamación radicada {RE} del mes pasado"})()

        sello = Sello("tinta", None, None, zona=(0.6, 0.7, 0.9, 0.9))
        releidos = releer_la_zona_del_sello(
            TestLaRelecturaGirada._Fuente(),
            {1: sello},
            de_pago=DePagoConCita(),
            vision=lambda _: "RE: no hay",
            vision_girada=lambda _: f"RE: {RE}",
            workers=1,
        )
        assert all(lector != "visión girada" for lector, _ in releidos.get(1, sello).lecturas)

    def test_lo_ya_girado_no_se_vuelve_a_girar(self):
        from resolutions.application.sellos import releer_la_zona_del_sello

        giradas = []
        releer_la_zona_del_sello(
            TestLaRelecturaGirada._Fuente(),
            {1: Sello("tinta", None, None, zona=(0.6, 0.7, 0.9, 0.9))},
            de_pago=TestLaRelecturaGirada._DePago(),
            vision=lambda _: "RE: no hay",
            vision_girada=lambda imagen: giradas.append(imagen) or "",
            ya_girados={1},
            workers=1,
        )
        assert giradas == []

    def test_los_avisos_de_otros_agentes_no_los_cierra_el_operador(self):
        from resolutions.api.correccion_del_re import es_aviso_del_re

        assert es_aviso_del_re("RE por confirmar, el nombre va sin él: …")
        assert es_aviso_del_re("trae sello de radicación al pie con el RE escrito a mano y la IA no lo leyó")
        assert not es_aviso_del_re("revisor de cortes: la hoja 3 trae sello de radicación al pie con el RE…")

    def test_la_entrega_de_otro_trabajo_no_se_toca(self, tmp_path):
        from resolutions.api import constancia as constancias
        from resolutions.api.correccion_del_re import corregir_re_en_el_destino

        carpeta = tmp_path / "1001051"
        carpeta.mkdir()
        (carpeta / "01_RECLAMO.pdf").write_bytes(b"%PDF-1.4")
        ruta = carpeta / ".bot-entrega-UPD1.json"
        constancias.escribir(
            ruta,
            constancias.Constancia(
                origen="1001051/UPD1.pdf", tamano=1, modificado_ns=1, estado=constancias.EstadoDeEntrega.COMPLETA,
                archivos=[{"ruta": "01_RECLAMO.pdf", "bytes": 1}], job_id="B", indice={"filas": [{"nombre": "RECLAMO"}]},
            ),
        )  # fmt: skip
        avisos = corregir_re_en_el_destino({"carpeta": str(carpeta), "constancia": str(ruta)}, 0, RE, job_id="A")
        assert avisos and "otro trabajo" in avisos[0]
        assert (carpeta / "01_RECLAMO.pdf").is_file()


class TestTrasUnReinicio:
    def test_el_re_decidido_se_cambia_con_el_trabajo_guardado(self, client, administrador, tmp_path):
        from resolutions.api import main
        from resolutions.api.routers.radicados import guardar_los_re_decididos

        job = main.contexto.registry.create("UPD1.pdf", tmp_path / "ya-no-esta.pdf")
        carpeta = main.contexto.settings.output_dir / job.id / "UPD1"
        carpeta.mkdir(parents=True)
        (carpeta / f"01_RECURSO-DE-QUEJA-{OTRO}.pdf").write_bytes(b"%PDF-1.4")
        main.contexto.registry.mark_done(
            job,
            {
                "groups": [{"code": f"01 {OTRO}", "pages": [1, 2]}],
                "outputs": [f"UPD1/01_RECURSO-DE-QUEJA-{OTRO}.pdf"],
                "inventory": {"items": [{"file_name": f"UPD1/01_RECURSO-DE-QUEJA-{OTRO}.pdf", "page_numbers": [1, 2]}]},
                "review_queue": [],
                "decisiones_del_agente": [
                    {"page": 1, "paginas": [1, 2], "valor": OTRO, "regla": "el más votado entre lecturas que no coinciden",
                     "confianza": "baja", "por_que": "leído", "auditor": "verificada por el auditor", "opciones": [OTRO, RE]}
                ],
            },
        )  # fmt: skip
        guardar_los_re_decididos(main.contexto, job)
        # El reinicio: el trabajo ya no está en memoria.
        main.contexto.registry.remove(job.id)
        listado = client.get("/api/re-decididos").json()
        assert [(r["job_id"], r["pagina"], r["valor"]) for r in listado] == [(job.id, 1, OTRO)]
        respuesta = client.put(f"/api/jobs/{job.id}/re/1", json={"re": RE}, headers=administrador)
        assert respuesta.status_code == 200, respuesta.text
        assert (carpeta / f"01_RECURSO-DE-QUEJA-{RE}.pdf").is_file()
        guardado = main.contexto.re_por_revisar.leer(job.id)
        assert guardado["informe"]["decisiones_del_agente"][0]["valor"] == RE
        assert client.get("/api/re-decididos").json() == []


class TestLaGiradaNuncaEsSegundoLector:
    """La verificación del 2026-11-23: con el OCR de pago, la girada no hacía «dos lectores»."""

    def test_no_confirma_la_oficina_ni_verifica(self):
        from resolutions.domain.evidencia import (
            LECTOR_GIRADO,
            EvidenciaDeRE,
            decidir_el_re,
            oficina_confirmada,
        )

        lecturas = (("ocr de pago", "RE2810202402908"), (LECTOR_GIRADO, "RE: RE2810202402908"))
        assert not oficina_confirmada("RE2810202402908", lecturas)
        hallazgo = decidir_el_re([EvidenciaDeRE(1, "sello de tinta", None, lecturas)])
        assert hallazgo.estado.value != "verificado"
        assert "visión" not in hallazgo.lectores


class TestLaVerificacionDelConfirmar:
    """La verificación del 2026-11-23 sobre el «Confirmar» con el trabajo guardado."""

    def _guardado(self, client, tmp_path, decisiones, review_queue=()):
        from resolutions.api import main
        from resolutions.api.routers.radicados import guardar_los_re_decididos

        job = main.contexto.registry.create("UPD1.pdf", tmp_path / "ya-no-esta.pdf")
        carpeta = main.contexto.settings.output_dir / job.id / "UPD1"
        carpeta.mkdir(parents=True)
        items = []
        for n, d in enumerate(decisiones, start=1):
            nombre = f"UPD1/0{n}_RECLAMO-{d['valor']}.pdf"
            (main.contexto.settings.output_dir / job.id / nombre).write_bytes(b"%PDF-1.4")
            items.append({"file_name": nombre, "page_numbers": d["paginas"]})
        main.contexto.registry.mark_done(
            job,
            {
                "groups": [{"code": f"0{n} {d['valor']}", "pages": d["paginas"]} for n, d in enumerate(decisiones, start=1)],
                "outputs": [i["file_name"] for i in items],
                "inventory": {"items": items},
                "review_queue": list(review_queue),
                "decisiones_del_agente": decisiones,
            },
        )
        guardar_los_re_decididos(main.contexto, job)
        main.contexto.registry.remove(job.id)
        return job

    def test_dos_confirmar_seguidos_no_se_pisan(self, client, administrador, tmp_path):
        from resolutions.api import main

        decision = {"regla": "el más votado", "confianza": "baja", "por_que": "", "auditor": "verificada por el auditor"}
        job = self._guardado(
            client,
            tmp_path,
            [{**decision, "page": 1, "paginas": [1], "valor": OTRO}, {**decision, "page": 2, "paginas": [2], "valor": "RE2310202408878"}],
        )
        assert client.put(f"/api/jobs/{job.id}/re/1", json={"re": RE}, headers=administrador).status_code == 200
        assert client.put(f"/api/jobs/{job.id}/re/2", json={"re": "RE2310202408899"}, headers=administrador).status_code == 200
        valores = [d["valor"] for d in main.contexto.re_por_revisar.leer(job.id)["informe"]["decisiones_del_agente"]]
        assert valores == [RE, "RE2310202408899"]

    def test_los_avisos_de_otros_agentes_se_quedan(self, client, administrador, tmp_path):
        from resolutions.api import main

        decision = {"page": 1, "paginas": [1], "valor": OTRO, "regla": "r", "confianza": "baja", "por_que": "", "auditor": "a"}
        cortes = {"page": 1, "reason": "revisor de cortes: la hoja 1 trae sello de radicación al pie con el RE…"}
        job = self._guardado(client, tmp_path, [decision], [cortes, {"page": 1, "reason": "RE por confirmar, el nombre…"}])
        assert client.put(f"/api/jobs/{job.id}/re/1", json={"re": RE}, headers=administrador).status_code == 200
        assert main.contexto.re_por_revisar.leer(job.id)["informe"]["review_queue"] == [cortes]

    def test_la_raiz_se_avisa_si_no_se_guardo(self):
        from resolutions.api.correccion_del_re import _en_el_indice_general

        assert "raíz" in _en_el_indice_general(None, ("1001051",), "RECLAMO", f"RECLAMO-{RE}")[0]
