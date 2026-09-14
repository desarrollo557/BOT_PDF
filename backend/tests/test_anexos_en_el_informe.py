"""De qué documento es cada anexo, en el informe que lee la pantalla.

`Entregado.grupos_para_el_informe` arma las unidades como las lee la pantalla, y
es el sitio por donde pasan las cuatro rutas. Leía los anexos de un atributo de
la agrupación que ningún grupo tiene: el reparto lo conoce la ruta que decidió
el corte -- es un veredicto de la costura, no un hecho del grupo -- y se perdía
por el camino, así que esa clave salía siempre vacía.

La ruta de correspondencia lo notó antes que nadie y se armó su propio informe a
mano, que es como se quedó fuera de todo arreglo que entrara por el camino
común: le faltaba la fecha de cada unidad, que la pantalla ya sabía leer.
"""

from __future__ import annotations

from pathlib import Path

from fakes import FakeAssembler

from resolutions.application.entrega import Destino, entregar
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode


def _grupos():
    """Un acta de dos hojas con dos fotografías detrás, y un cobro aparte."""
    return GroupingResult(
        groups=[
            PageGroup(
                code=ResolutionCode(value="01", raw="01"),
                page_numbers=[1, 2, 3, 4],
                title="páginas 1-4",
            ),
            PageGroup(
                code=ResolutionCode(value="02", raw="02"),
                page_numbers=[5],
                title="página 5",
            ),
        ]
    )


def _entregar(tmp_path, anexos=None):
    return entregar(
        _grupos(),
        origen=tmp_path / "caja.pdf",
        nombre="caja.pdf",
        paginas=5,
        destino=Destino(directorio=tmp_path / "out"),
        assembler=FakeAssembler(),
        anexos=anexos,
    )


class TestLosAnexosLleganAlInforme:
    def test_el_reparto_que_se_le_dio_es_el_que_sale(self, tmp_path):
        entregado = _entregar(tmp_path, anexos={"01": [3, 4]})

        grupos = {g["code"]: g for g in entregado.grupos_para_el_informe}
        assert grupos["01"]["attachments"] == [3, 4]

    def test_una_unidad_sin_anexos_los_declara_vacios(self, tmp_path):
        entregado = _entregar(tmp_path, anexos={"01": [3, 4]})

        grupos = {g["code"]: g for g in entregado.grupos_para_el_informe}
        assert grupos["02"]["attachments"] == []

    def test_sin_anexos_ninguna_unidad_los_inventa(self, tmp_path):
        entregado = _entregar(tmp_path)

        assert all(g["attachments"] == [] for g in entregado.grupos_para_el_informe)

    def test_el_informe_no_comparte_la_lista_con_quien_la_dio(self, tmp_path):
        # Un informe que devuelve la misma lista que le pasaron deja que quien
        # la lea la modifique, y entonces dos vistas de lo mismo discrepan.
        dados = {"01": [3, 4]}
        entregado = _entregar(tmp_path, anexos=dados)

        entregado.grupos_para_el_informe[0]["attachments"].append(99)

        assert dados["01"] == [3, 4]

    def test_y_el_inventario_dice_lo_mismo(self, tmp_path):
        # Las dos salidas se arman del mismo dato a propósito: un inventario y
        # un informe que discrepan sobre qué hoja es anexo de qué no se pueden
        # auditar, porque nada dice cuál de los dos miente.
        entregado = _entregar(tmp_path, anexos={"01": [3, 4]})

        filas = {item.code: item for item in entregado.inventario.items}
        del_informe = {g["code"]: g["attachments"] for g in entregado.grupos_para_el_informe}
        assert filas["01"].attachment_pages == del_informe["01"]


class TestLaFechaDeCadaUnidad:
    def test_el_informe_la_trae_siempre(self, tmp_path):
        # La pantalla la lee, y la ruta de correspondencia no la mandaba por
        # tener su propio informe escrito a mano.
        entregado = _entregar(tmp_path)

        assert all("fecha" in g for g in entregado.grupos_para_el_informe)


class TestLaCajaRevueltaUsaElCaminoComun:
    """La ruta de correspondencia arma su informe donde lo arman las otras tres."""

    def test_el_worker_no_vuelve_a_escribir_los_grupos_a_mano(self):
        # Se lee del módulo instalado y no de una ruta relativa: la suite se
        # corre desde `backend/` y desde la raíz, y una prueba que sólo pasa
        # desde un sitio es una prueba que falla en CI por el sitio.
        from resolutions.api.worker import correspondencia

        fuente = Path(correspondencia.__file__).read_text(encoding="utf-8")
        assert "entregado.grupos_para_el_informe" in fuente
        assert '"code": group.code.value' not in fuente, (
            "los grupos del informe se arman en entrega.py, no aquí"
        )
