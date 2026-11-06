"""El agente revisor y la auditoría, iguales en todas las habilidades.

Lo pidió el operador el 2026-11-05: «centralizar el agente de revisión y el de
auditoría, estandarizarlos para todas las habilidades, ya que nos guiaremos del
margen de error, y cada habilidad tiene sus patrones: allí sabremos cómo crear
el margen de error». Esto fija:

- que cada habilidad que el bot sabe nombrar tiene su perfil, con sus patrones
  y su margen aceptable, y que sólo la caja de correspondencia corrige;
- que las rutas que escriben por su cuenta -- historias, Kingspan, actas -- se
  comprueban en el disco igual que las demás, cobertura incluida;
- que la auditoría juzga cada habilidad contra su margen, y que la que se sale
  del suyo se dice aunque la corrida entera no se salga.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import fitz
import pytest

from resolutions.adapters.huellas_pdf import huellas_de
from resolutions.api.auditoria import etapa_de, margen_aceptable, margenes_por_habilidad
from resolutions.api.indices import habilidad_del_proceso
from resolutions.application.entrega import comprobar_archivos
from resolutions.application.perfiles_de_revision import GENERICO, PERFILES, perfil_de
from resolutions.domain.auditoria import (
    BIEN,
    DENTRO_DEL_MARGEN,
    ERROR,
    FUERA_DEL_MARGEN,
    NO_AUDITADO,
    PdfAuditado,
)

#: Cómo nombra ``habilidad_del_proceso`` cada habilidad: la constancia y el
#: informe las guardan así, y así llegan a la auditoría.
HABILIDADES = (
    "Caja de correspondencia",
    "Libro de diplomas",
    "Actas de grado",
    "Actas de consejo",
    "Historias académicas",
    "Legajo de resoluciones",
    "Legajo de matrículas",
    "Kingspan",
    "Archivos ya separados",
)


class TestElRegistro:
    @pytest.mark.parametrize("habilidad", HABILIDADES)
    def test_cada_habilidad_tiene_su_perfil(self, habilidad):
        perfil = perfil_de(habilidad)
        assert perfil is not GENERICO
        assert perfil.nombre == habilidad

    @pytest.mark.parametrize(
        ("como_llega", "clave"),
        [
            ("diploma", "diplomas"),
            ("matricula", "matriculas"),
            ("acta", "actas-de-grado"),
            ("ACTA DE GRADO", "actas-de-grado"),
            ("acta-consejo", "actas-de-consejo"),
            ("ACTA DE CONSEJO", "actas-de-consejo"),
            ("historia-academica", "historias"),
            ("resolucion", "resoluciones"),
            ("segment", "correspondencia"),
        ],
    )
    def test_por_como_la_nombra_la_peticion_o_el_tipo(self, como_llega, clave):
        assert perfil_de(como_llega).clave == clave

    def test_lo_que_no_se_reconoce_va_con_los_patrones_de_cualquier_papel(self):
        assert perfil_de("—") is GENERICO
        assert perfil_de(None) is GENERICO

    def test_solo_corrige_la_caja_de_correspondencia(self):
        """Las demás nombran y fechan cada PDF al leerlo: mover una hoja los dejaría mal."""
        assert [p.clave for p in PERFILES if p.corrige] == ["correspondencia"]

    def test_una_persona_por_pdf(self):
        assert {p.clave for p in PERFILES if p.una_persona_por_pdf} == {
            "diplomas",
            "actas-de-grado",
            "historias",
            "matriculas",
        }

    def test_cada_perfil_trae_sus_reglas_para_la_ia(self):
        assert all(p.reglas for p in PERFILES)

    def test_los_patrones_de_una_habilidad_que_solo_senala(self):
        patrones = perfil_de("Actas de grado").patrones({})
        assert patrones.una_persona_por_pdf
        assert not patrones.puede_mover and not patrones.puede_partir
        assert "acta" in patrones.reglas.lower()

    def test_los_cruces_salen_del_titulo_si_la_ruta_no_los_dice(self):
        """La auditoría no ve las reglas de la corrida: la Habeas Data cruza por su título."""
        textos = {1: "RECONOCIMIENTO DE DEUDA", 2: "AUTORIZACION LEY HABEAS DATA\nLEY 1581 DE 2012"}
        assert 2 in perfil_de("Caja de correspondencia").patrones(textos).cruces

    def test_los_de_la_ruta_mandan(self):
        """Al procesar, la ruta ya calculó sus cruces: no se le añade nada."""
        textos = {2: "AUTORIZACION LEY HABEAS DATA\nLEY 1581 DE 2012"}
        patrones = perfil_de("correspondencia").patrones(textos, cruces=frozenset({7}), abren=frozenset({3}))
        assert patrones.cruces == frozenset({7})
        assert patrones.abren == frozenset({3})
        assert patrones.puede_mover


class TestElMargenAceptable:
    def test_el_cinco_por_ciento_por_omision(self, monkeypatch):
        monkeypatch.delenv("BOTPDF_MARGEN_ACEPTABLE", raising=False)
        monkeypatch.delenv("BOTPDF_MARGEN_ACEPTABLE_DIPLOMAS", raising=False)
        assert margen_aceptable("Libro de diplomas") == pytest.approx(0.05)
        assert margen_aceptable() == pytest.approx(0.05)

    def test_uno_para_todas_y_otro_para_una(self, monkeypatch):
        monkeypatch.setenv("BOTPDF_MARGEN_ACEPTABLE", "8")
        monkeypatch.setenv("BOTPDF_MARGEN_ACEPTABLE_ACTAS_DE_GRADO", "2,5")
        assert margen_aceptable("Actas de grado") == pytest.approx(0.025)
        assert margen_aceptable("Libro de diplomas") == pytest.approx(0.08)

    def test_un_valor_sin_sentido_no_cuenta(self, monkeypatch):
        monkeypatch.setenv("BOTPDF_MARGEN_ACEPTABLE", "ciento")
        monkeypatch.delenv("BOTPDF_MARGEN_ACEPTABLE_KINGSPAN", raising=False)
        assert margen_aceptable("Kingspan") == pytest.approx(0.05)


def _auditados(habilidad: str, bien: int, errores: int, no_auditados: int = 0) -> list[PdfAuditado]:
    return (
        [PdfAuditado(f"{habilidad}/{n}.pdf", BIEN, (), habilidad=habilidad) for n in range(bien)]
        + [PdfAuditado(f"{habilidad}/e{n}.pdf", ERROR, ("mal",), habilidad=habilidad) for n in range(errores)]
        + [PdfAuditado(f"{habilidad}/x{n}.pdf", NO_AUDITADO, ("no",), habilidad=habilidad) for n in range(no_auditados)]
    )


class TestElMargenPorHabilidad:
    def test_cada_habilidad_contra_el_suyo(self):
        resultados = _auditados("Caja de correspondencia", 90, 0) + _auditados("Libro de diplomas", 7, 3, 1)
        por = {h["clave"]: h for h in margenes_por_habilidad(resultados)}
        assert por["correspondencia"]["revisados"] == 90
        assert por["correspondencia"]["margen"]["dictamen"] == DENTRO_DEL_MARGEN
        assert (por["diplomas"]["revisados"], por["diplomas"]["errores"], por["diplomas"]["no_auditados"]) == (10, 3, 1)
        assert por["diplomas"]["margen"]["dictamen"] == FUERA_DEL_MARGEN
        assert por["diplomas"]["habilidad"] == "Libro de diplomas"
        # La más revisada primero.
        assert [h["clave"] for h in margenes_por_habilidad(resultados)] == ["correspondencia", "diplomas"]

    def test_la_que_se_sale_se_dice_aunque_la_corrida_no(self):
        muestra = {
            "revisados": 100,
            "bien": 97,
            "errores": 3,
            "margen": {"dictamen": "sin certeza", "texto_del_dictamen": "Sin certeza: …"},
            "por_habilidad": [
                {"habilidad": "Caja de correspondencia", "margen": {"dictamen": DENTRO_DEL_MARGEN}},
                {"habilidad": "Libro de diplomas", "margen": {"dictamen": FUERA_DEL_MARGEN}},
            ],
        }
        etapa, detalle = etapa_de(None, muestra)
        assert etapa == "Terminado: error fuera del margen"
        assert "fuera de su margen: Libro de diplomas" in detalle

    def test_sin_habilidades_fuera_sigue_como_antes(self):
        muestra = {
            "revisados": 100,
            "bien": 100,
            "errores": 0,
            "margen": {"dictamen": DENTRO_DEL_MARGEN, "texto_del_dictamen": "Dentro del margen: …"},
            "por_habilidad": [{"habilidad": "Kingspan", "margen": {"dictamen": DENTRO_DEL_MARGEN}}],
        }
        assert etapa_de(None, muestra)[0] == "Terminado"


class TestLaHabilidadDelProceso:
    def test_kingspan_con_su_nombre(self):
        job = SimpleNamespace(report={"stats": {"kingspan_rows": 1}}, tipo=None, task="both", tipo_documento="kingspan")
        assert habilidad_del_proceso(job) == "Kingspan"

    def test_las_matriculas_con_su_nombre(self):
        job = SimpleNamespace(report={"stats": {"document_type": "matricula"}}, tipo=None, task="both")
        assert habilidad_del_proceso(job) == "Legajo de matrículas"

    def test_un_legajo_sigue_siendo_de_resoluciones(self):
        job = SimpleNamespace(report={"stats": {"document_type": "resolucion"}}, tipo=None, task="both")
        assert habilidad_del_proceso(job) == "Legajo de resoluciones"


def _pdf(ruta, textos):
    with fitz.open() as doc:
        for texto in textos:
            doc.new_page().insert_textbox(fitz.Rect(30, 30, 560, 800), texto, fontsize=9)
        doc.save(ruta)
    return ruta


def _escribir(origen, destino, paginas):
    with fitz.open(origen) as original, fitz.open() as nuevo:
        for pagina in paginas:
            nuevo.insert_pdf(original, from_page=pagina - 1, to_page=pagina - 1)
        nuevo.save(destino)


class TestLaComprobacionDeLoQueSeEscribePorSuCuenta:
    TEXTOS = [f"Hoja {n} del original, con su texto propio y distinto: {'abcdefghij'[n]} " * 3 for n in range(1, 6)]

    def test_todo_en_su_sitio_y_en_su_orden(self, tmp_path):
        origen = _pdf(tmp_path / "o.pdf", self.TEXTOS)
        _escribir(origen, tmp_path / "a.pdf", [2, 1])
        _escribir(origen, tmp_path / "b.pdf", [3, 4, 5])
        resultado = comprobar_archivos(
            origen, {"a.pdf": [2, 1], "b.pdf": [3, 4, 5]}, tmp_path, huellas_de, paginas_del_original=5
        )
        assert resultado["comprobada"] and resultado["problemas"] == []
        assert resultado["hojas"] == 5

    def test_una_hoja_en_dos_pdf_y_otra_en_ninguno(self, tmp_path):
        origen = _pdf(tmp_path / "o.pdf", self.TEXTOS)
        _escribir(origen, tmp_path / "a.pdf", [1, 2, 3])
        _escribir(origen, tmp_path / "b.pdf", [3, 4])
        resultado = comprobar_archivos(
            origen, {"a.pdf": [1, 2, 3], "b.pdf": [3, 4]}, tmp_path, huellas_de, paginas_del_original=5
        )
        textos = [p["texto"] for p in resultado["problemas"]]
        assert "hojas del original en ningún PDF: 5" in textos
        assert "hojas del original en más de un PDF: 3" in textos

    def test_la_hoja_que_no_es_la_que_tocaba(self, tmp_path):
        origen = _pdf(tmp_path / "o.pdf", self.TEXTOS)
        _escribir(origen, tmp_path / "a.pdf", [1, 3])
        resultado = comprobar_archivos(origen, {"a.pdf": [1, 2]}, tmp_path, huellas_de)
        assert [p["pagina"] for p in resultado["problemas"]] == [2]


def _documento(codigo: str, pagina: int):
    from resolutions.domain.kingspan import Documento

    serie = codigo.split("-")[1]
    documento = Documento(pagina=pagina, serie=serie, numero=int(codigo.rsplit("-", 1)[1]), fecha=date(2024, 5, 5))
    assert documento.codigo == codigo
    return documento


class TestLosTramosDeKingspan:
    def test_una_serie_con_su_portada(self):
        from resolutions.api.worker.kingspan import _tramos
        from resolutions.domain.kingspan import FilaKingspan

        fila = FilaKingspan(asunto="NOTAS", documentos=(_documento("001-NI-00000001", 2), _documento("001-NI-00000002", 5)))
        assert _tramos([fila], 7) == [("001-NI-00000001.pdf", 1, 4), ("001-NI-00000002.pdf", 5, 7)]

    def test_dos_series_no_se_pisan(self):
        """Con dos filas, el último de la primera llegaba hasta el final y se
        llevaba las hojas de la segunda: salían en dos PDF."""
        from resolutions.api.worker.kingspan import _tramos
        from resolutions.domain.kingspan import FilaKingspan

        notas = FilaKingspan(asunto="NOTAS", documentos=(_documento("001-NI-00000001", 1), _documento("001-NI-00000002", 3)))
        facturas = FilaKingspan(asunto="FACTURAS", documentos=(_documento("001-FV-00000010", 5), _documento("001-FV-00000011", 7)))
        tramos = _tramos([notas, facturas], 8)
        assert tramos == [
            ("001-NI-00000001.pdf", 1, 2),
            ("001-NI-00000002.pdf", 3, 4),
            ("001-FV-00000010.pdf", 5, 6),
            ("001-FV-00000011.pdf", 7, 8),
        ]
        hojas = [p for _, inicio, fin in tramos for p in range(inicio, fin + 1)]
        assert hojas == list(range(1, 9))

    def test_dos_numeros_en_la_misma_hoja_abren_un_solo_pdf(self):
        from resolutions.api.worker.kingspan import _tramos
        from resolutions.domain.kingspan import FilaKingspan

        fila = FilaKingspan(
            asunto="NOTAS",
            documentos=(_documento("001-NI-00000001", 1), _documento("001-NI-00000009", 1), _documento("001-NI-00000002", 3)),
        )
        assert _tramos([fila], 4) == [("001-NI-00000001.pdf", 1, 2), ("001-NI-00000002.pdf", 3, 4)]
