"""El reclamo y su constancia con su RE, y el índice por fecha con el expediente = NIC.

Lo dictó el operador el 2026-11-04. Primero lo hizo ``scripts/renombrar_reclamaciones.py``
sobre las cajas de MAGANGUE ya entregadas; después, ante unas carpetas que el bot
no había procesado: «incluye los cambios, que los reclamos o constancias de
reclamación lleven su RE, el NIC en el Excel, en el nombre de expediente y en el
NIC, y el orden de fecha». Lo que entrega el bot tiene que quedar como lo deja el
script: aquí se comprueba también que el script ya no encuentra nada que cambiar.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

from resolutions.adapters.indice_electronico import FilaDelIndice, en_orden_cronologico
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.naming import output_filename
from resolutions.domain.nombre_oficial import (
    CON_RE_EN_EL_NOMBRE,
    es_re,
    lleva_re_en_el_nombre,
    re_del_archivo,
)
from resolutions.domain.orden_del_indice import orden_cronologico
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.sello import Sello

RE = "RE2310202007709"
OTRO = "RE2310202405234"


def _nombre(valor: str, kind: str, **opciones) -> str:
    raw = valor.split()[-1] if " " in valor else valor
    return output_filename(
        ResolutionCode(value=valor, raw=raw),
        None,
        prefix=None,
        kind=kind,
        mayusculas=True,
        sin_radicado=True,
        radicado_en=CON_RE_EN_EL_NOMBRE,
        **opciones,
    )


class TestElNombreDelArchivo:
    def test_el_reclamo_y_la_constancia_llevan_su_re_detras(self):
        assert _nombre(f"03 {RE}", "RECLAMO") == f"03_RECLAMO-{RE}.pdf"
        assert (
            _nombre(f"01 {RE}", "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION")
            == f"01_CONSTANCIA-DEL-CONTENIDO-DE-LA-RECLAMACION-{RE}.pdf"
        )

    def test_los_demas_siguen_numero_titulo(self):
        # «Solo los 2 exactos» (el operador, 2026-11-04).
        assert _nombre(f"02 {RE}", "DERECHO DE PETICION") == "02_DERECHO-DE-PETICION.pdf"
        assert _nombre(f"02 {RE}", "NOTIFICACION PERSONAL RECLAMOS") == "02_NOTIFICACION-PERSONAL-RECLAMOS.pdf"
        assert _nombre(f"02 {RE}", "RESPUESTA A RECLAMACION") == "02_RESPUESTA-A-RECLAMACION.pdf"
        assert _nombre(f"02 {RE}", "RECLAMO POR CONSUMO ESTIMADO") == "02_RECLAMO-POR-CONSUMO-ESTIMADO.pdf"

    def test_sin_re_o_con_un_p_queda_sin_nada_detras(self):
        assert _nombre("04", "RECLAMO") == "04_RECLAMO.pdf"
        assert _nombre("04 P43102019110005", "RECLAMO") == "04_RECLAMO.pdf"

    def test_al_apretar_el_nombre_el_re_no_se_toca(self):
        nombre = _nombre(f"01 {RE}", "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION", budget=40)
        assert nombre.endswith(f"-{RE}.pdf") and len(nombre) <= 40
        assert _nombre(f"01 {RE}", "RECLAMO", budget=24) == f"01_{RE}.pdf"

    def test_sin_radicado_en_ningun_tipo_lo_lleva(self):
        nombre = output_filename(
            ResolutionCode(value=f"03 {RE}", raw=RE), None, prefix=None, kind="RECLAMO", mayusculas=True, sin_radicado=True
        )
        assert nombre == "03_RECLAMO.pdf"


class TestLosTitulosConRe:
    def test_solo_los_dos_exactos(self):
        assert lleva_re_en_el_nombre("RECLAMO")
        assert lleva_re_en_el_nombre("Constancia del contenido de la reclamación")
        assert not lleva_re_en_el_nombre("RECLAMO POR CONSUMO ESTIMADO")
        assert not lleva_re_en_el_nombre("NOTIFICACION PERSONAL RECLAMOS")
        assert not lleva_re_en_el_nombre(None)

    def test_un_re_es_re_y_trece_cifras(self):
        assert es_re(RE)
        assert not es_re("RE231020200770")
        assert not es_re("P43102019110005")
        assert not es_re(None)

    def test_el_re_del_archivo(self):
        assert re_del_archivo(f"UPD1/03_RECLAMO-{RE}.pdf") == RE
        assert re_del_archivo("03_RECLAMO.pdf") is None


class TestElOrdenPorFecha:
    def test_lo_antiguo_primero_y_sin_fecha_al_final(self):
        fechas = [date(2024, 2, 20), None, date(2024, 1, 31), date(2024, 1, 31)]
        # A igual fecha, el orden de las hojas.
        assert orden_cronologico(fechas) == [2, 3, 0, 1]

    def test_ordenar_dos_veces_da_lo_mismo(self):
        fechas = [date(2024, 2, 20), None, date(2024, 1, 31), date(2024, 1, 31)]
        una = [fechas[i] for i in orden_cronologico(fechas)]
        assert orden_cronologico(una) == [0, 1, 2, 3]

    def test_las_filas_se_renumeran(self):
        filas = [
            FilaDelIndice("CONSTANCIA", date(2024, 2, 20), None, 1, 1),
            FilaDelIndice("PAGARE", None, None, 2, 1),
            FilaDelIndice("NOTIFICACION", date(2024, 1, 31), None, 3, 1),
        ]
        assert [(f.orden, f.nombre) for f in en_orden_cronologico(filas)] == [
            (1, "NOTIFICACION"),
            (2, "CONSTANCIA"),
            (3, "PAGARE"),
        ]


class TestElReDelWorker:
    """``_poner_el_re_en_el_nombre``: de lo ya leído, sin volver a leer nada."""

    @staticmethod
    def _grupos(*grupos: tuple[str, list[int], str]) -> GroupingResult:
        return GroupingResult(
            groups=[
                PageGroup(code=ResolutionCode(value=valor, raw=valor.split()[-1]), page_numbers=paginas, kind=kind)
                for valor, paginas, kind in grupos
            ],
            quarantine=[],
            repairs=[],
        )

    @staticmethod
    def _poner(grupos, anexos=None, *, textos=None, sellos=None, sin_re=(), abren=()):
        from resolutions.api.worker.correspondencia import _poner_el_re_en_el_nombre

        return _poner_el_re_en_el_nombre(
            grupos, anexos or {}, textos=textos or {}, sellos=sellos or {}, sin_re=set(sin_re), abren=set(abren)
        )

    def test_el_de_su_tramite_se_queda(self):
        grupos, _, hallados = self._poner(self._grupos((f"01 {RE}", [1], "RECLAMO")), textos={1: f"cita {OTRO}"})
        assert grupos.groups[0].code.value == f"01 {RE}"
        assert hallados == {"1": f"{RE}: el de su trámite"}

    def test_sin_tramite_toma_el_de_su_sello(self):
        grupos, anexos, hallados = self._poner(
            self._grupos(("01", [1, 2], "RECLAMO")),
            {"01": [2]},
            sellos={1: Sello(clase="impreso", radicado=RE)},
        )
        assert grupos.groups[0].code.value == f"01 {RE}"
        # Sus anexos siguen siendo suyos con el código nuevo.
        assert anexos == {f"01 {RE}": [2]}
        assert hallados == {"1": f"{RE}: del sello de la pág. 1"}

    def test_la_constancia_toma_el_que_imprime_su_texto(self):
        grupos, _, _ = self._poner(
            self._grupos(("01", [1], "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION")),
            textos={1: f"RECIBI CONSTANCIA DEL CONTENIDO ... N° PQR {RE}"},
        )
        assert grupos.groups[0].code.value == f"01 {RE}"

    def test_la_hoja_con_sello_ilegible_no_toma_el_re_que_cita(self):
        # El RE que cita el texto de una hoja con sello es el de otro trámite.
        grupos, _, hallados = self._poner(
            self._grupos(("01", [1], "RECLAMO")),
            textos={1: f"contra la reclamación {OTRO}"},
            sellos={1: Sello(clase="tinta", radicado=None)},
        )
        assert grupos.groups[0].code.value == "01" and hallados == {}

    def test_las_copias_y_los_anexos_no_dan_re(self):
        grupos, _, _ = self._poner(
            self._grupos(("01", [1, 2, 3], "RECLAMO")),
            {"01": [3]},
            textos={2: f"copia {OTRO}", 3: f"anexo {OTRO}"},
            sin_re={2},
        )
        assert grupos.groups[0].code.value == "01"

    def test_los_demas_tipos_no_se_tocan(self):
        grupos, _, hallados = self._poner(
            self._grupos(("01", [1], "DERECHO DE PETICION")), sellos={1: Sello(clase="impreso", radicado=RE)}
        )
        assert grupos.groups[0].code.value == "01" and hallados == {}


def _el_script():
    ruta = Path(__file__).resolve().parents[2] / "scripts" / "renombrar_reclamaciones.py"
    spec = importlib.util.spec_from_file_location("renombrar_reclamaciones", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class TestElIndiceDeLaCaja:
    openpyxl = pytest.importorskip("openpyxl")

    @staticmethod
    def _report() -> dict:
        def item(numero: int, nombre: str, tipo: str, fecha: str | None) -> dict:
            return {
                "file_name": f"UPD1/{nombre}",
                "code": f"{numero:02d}",
                "type": tipo,
                "fecha": fecha,
                "page_count": 1,
                "page_numbers": [numero],
            }

        # La caja 7285349 del pantallazo del operador, como sale del bot.
        return {
            "agrupar": "tramite",
            "inventory": {
                "items": [
                    item(1, f"01_CONSTANCIA-DEL-CONTENIDO-DE-LA-RECLAMACION-{RE}.pdf",
                         "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION", "2024-02-20"),
                    item(2, "02_NOTIFICACION-PERSONAL-RECLAMOS.pdf", "NOTIFICACION PERSONAL RECLAMOS", "2024-01-31"),
                    item(3, "03_RECLAMO.pdf", "RECLAMO", "2024-01-31"),
                    item(4, "04_PAGARE.pdf", "PAGARE", None),
                ]
            },
            "piezas": [],
        }

    def _escribir(self, carpeta: Path) -> Path:
        from resolutions.adapters.indice_electronico import NOMBRE_DEL_INDICE
        from resolutions.api.worker.planillas import _escribir_indice

        payload = {
            "operator": "SIAR",
            "destination": str(carpeta.parent),
            "source": r"C:\FUENTE\MAGANGUE\7285349\UPD1.pdf",
        }
        _escribir_indice(self._report(), carpeta, payload)
        return carpeta / NOMBRE_DEL_INDICE

    def test_por_fecha_con_el_re_y_el_expediente_igual_al_nic(self, tmp_path):
        hoja = self.openpyxl.load_workbook(self._escribir(tmp_path / "7285349")).active
        assert hoja["B3"].value == hoja["B4"].value == 7285349
        filas = [tuple(hoja.cell(fila, c).value for c in (1, 2, 4)) for fila in range(8, 12)]
        assert filas == [
            ("NOTIFICACION PERSONAL RECLAMOS", "31/01/2024", 1),
            ("RECLAMO", "31/01/2024", 2),
            (f"CONSTANCIA DEL CONTENIDO DE LA RECLAMACION-{RE}", "20/02/2024", 3),
            ("PAGARE", "S.F.", 4),
        ]

    def test_el_script_ya_no_encuentra_nada_que_cambiar(self, tmp_path):
        script = _el_script()
        raiz = tmp_path / "MAGANGUE PROCESADO"
        caja = raiz / "7285349"
        self._escribir(caja)
        (caja / f"01_CONSTANCIA-DEL-CONTENIDO-DE-LA-RECLAMACION-{RE}.pdf").write_bytes(b"%PDF-1.4")
        respaldo = tmp_path / "respaldo"

        indice = script.paso_indice(str(caja), str(raiz), str(respaldo), False)
        assert indice["estado"] == "ya estaba bien"
        filas = script.paso_re(str(caja), str(raiz), str(raiz), str(respaldo), False, None, "eng")
        assert [(f["archivo_antes"], f["estado"]) for f in filas] == [
            (f"01_CONSTANCIA-DEL-CONTENIDO-DE-LA-RECLAMACION-{RE}.pdf", "ya tenía RE")
        ]
