"""Que lo que dice MuPDF llegue entendible, completo y sin ensuciar la consola.

Los cuatro mensajes que aparecen aquí por su nombre son los que el operador vio
en la consola del backend procesando una caja de resoluciones, y son la razón de
que este módulo exista. Se prueban literales a propósito: si una versión futura
de MuPDF cambia el texto, la traducción deja de coincidir en silencio y la
consola vuelve a llenarse de inglés sin que nadie se entere.
"""

from __future__ import annotations

import logging

import pytest

pymupdf = pytest.importorskip("pymupdf")

from resolutions.adapters.mupdf_messages import drenar, instalar  # noqa: E402
from resolutions.application.diagnostico import (  # noqa: E402
    SIN_TRADUCIR,
    Gravedad,
    agrupar,
    explicar,
    traducir,
)

#: Lo que se leyó en la consola, tal cual, con la gravedad que le corresponde.
#: Todas se recuperan: son defectos del PDF de origen que no cuestan una página.
#:
#: El enlace roto estuvo clasificado como pérdida y estaba mal. El enlace ya
#: venía apuntando a un destino que no existe, así que no copiarlo no quita
#: nada que funcionara: el texto y las imágenes de la página son los mismos.
#: Contarlo como pérdida lo sacaba en la consola del operador con el mismo peso
#: que una página que no se pudo escribir.
MENSAJES_VISTOS = [
    ("format error: object is not a stream", Gravedad.RECUPERADO),
    ("syntax error: invalid ICC colorspace", Gravedad.RECUPERADO),
    ("ignoring broken ICC profile", Gravedad.RECUPERADO),
    ("skipping bad link / annot item 12.", Gravedad.RECUPERADO),
    ("encountered syntax errors; page may not be correct", Gravedad.RECUPERADO),
]


class TestTraducir:
    @pytest.mark.parametrize("mensaje, gravedad", MENSAJES_VISTOS)
    def test_the_messages_the_operator_saw_are_explained_in_spanish(self, mensaje, gravedad):
        incidencia = traducir(mensaje)
        assert incidencia.explicacion != SIN_TRADUCIR
        assert incidencia.gravedad is gravedad

    @pytest.mark.parametrize("mensaje, _", MENSAJES_VISTOS)
    def test_the_original_text_is_never_thrown_away(self, mensaje, _):
        # Traducir sin conservar lo traducido convierte un mensaje buscable en
        # la documentación de MuPDF en una frase que no lleva a ninguna parte.
        assert traducir(mensaje).original == mensaje
        assert mensaje in str(traducir(mensaje))

    def test_a_graft_failure_says_the_source_table_is_broken(self):
        # El único de los cuatro que costaba páginas. Tiene que decirlo.
        incidencia = traducir("source object number out of range")
        assert incidencia.gravedad is Gravedad.PERDIDA
        assert "referencias cruzadas" in incidencia.explicacion

    def test_an_unknown_message_is_treated_as_a_loss(self):
        # La postura prudente: lo que este módulo no sabe leer puede ser
        # cualquier cosa, y darlo por inofensivo sería afirmar lo que no se ha
        # comprobado.
        incidencia = traducir("una avería que MuPDF todavía no ha inventado")
        assert incidencia.explicacion == SIN_TRADUCIR
        assert incidencia.gravedad is Gravedad.PERDIDA

    def test_the_severity_separates_what_was_saved_from_what_was_lost(self):
        # Es la distinción que hacía ilegible la consola: líneas iguales en las
        # que una costaba una página y las demás no costaban nada.
        assert traducir("invalid ICC colorspace").gravedad is Gravedad.RECUPERADO
        assert traducir("skipping bad link / annot item 3.").gravedad is Gravedad.RECUPERADO
        assert traducir("cannot load content stream").gravedad is Gravedad.PERDIDA
        assert traducir("source object number out of range").gravedad is Gravedad.PERDIDA


class TestExplicar:
    def test_the_exception_the_writer_catches_becomes_a_sentence(self):
        frase = explicar(RuntimeError("code=4: source object number out of range"))
        assert "referencias cruzadas" in frase
        # Y el original detrás, para quien tenga que depurarlo.
        assert "code=4: source object number out of range" in frase

    def test_an_unrecognised_error_keeps_its_own_words(self):
        # Envolver un texto que nadie ha entendido en una explicación genérica
        # sería aparentar un diagnóstico que no existe. Y el nombre de la clase
        # se queda: un KeyError sin él es una cadena suelta entre comillas.
        assert explicar(RuntimeError("vaya cosa rara")) == "RuntimeError: vaya cosa rara"
        assert explicar(KeyError("spa")) == "KeyError: 'spa'"

    def test_an_exception_with_no_message_still_says_something(self):
        assert explicar(RuntimeError()) == "RuntimeError"

    def test_it_accepts_plain_text_too(self):
        assert "referencias cruzadas" in explicar("source object number out of range")


class TestAgrupar:
    def test_repetitions_are_counted_instead_of_repeated(self):
        # Un escaneo de cuatrocientas páginas con el perfil de color roto lo
        # dice cuatrocientas veces, y cuatrocientas líneas iguales no informan
        # más que una con su cuenta al lado.
        incidencias = agrupar("invalid link destination\n... repeated 5 times...")
        assert len(incidencias) == 1
        assert incidencias[0].veces == 5

    def test_the_same_message_twice_is_one_entry_of_two(self):
        incidencias = agrupar("invalid ICC colorspace\nobject is not a stream\ninvalid ICC colorspace")
        assert [i.veces for i in incidencias] == [2, 1]

    def test_different_messages_keep_the_order_they_appeared_in(self):
        incidencias = agrupar("cannot find startxref\ntrying to repair broken xref")
        assert [i.original for i in incidencias] == [
            "cannot find startxref",
            "trying to repair broken xref",
        ]

    def test_an_empty_store_yields_nothing(self):
        assert agrupar("") == []
        assert agrupar("\n  \n") == []


@pytest.fixture
def truncado(tmp_path):
    """Un PDF cortado por la mitad, que es lo que hace hablar a MuPDF de verdad.

    Nada de esto está simulado: la biblioteca emite sus propios mensajes al
    abrirlo y son los que el módulo tiene que recoger.
    """
    document = pymupdf.open()
    for numero in range(4):
        document.new_page().insert_text((72, 100), f"pagina {numero + 1}")
    entero = tmp_path / "entero.pdf"
    document.save(entero)
    document.close()

    crudo = entero.read_bytes()
    path = tmp_path / "truncado.pdf"
    path.write_bytes(crudo[: int(len(crudo) * 0.82)])
    return path


class TestDrenar:
    def test_what_mupdf_said_comes_back_translated(self, truncado):
        drenar()  # el almacén es del proceso: se parte de cero
        with pymupdf.open(truncado) as document:
            document[0].get_text()

        incidencias = drenar("truncado.pdf")

        assert incidencias, "MuPDF tenía algo que decir de un PDF cortado"
        assert all(i.explicacion != SIN_TRADUCIR for i in incidencias)

    def test_the_store_is_left_empty(self, truncado):
        # PyMuPDF acumula cada mensaje en una lista global que nadie vacía. Un
        # worker que procese una caja entera la iría llenando documento tras
        # documento durante toda la vida del proceso.
        drenar()
        with pymupdf.open(truncado) as document:
            document[0].get_text()
        assert drenar("truncado.pdf")
        assert drenar() == []

    def test_the_document_is_named_in_the_log(self, truncado, caplog):
        # Un aviso sin documento delante es inútil cuando hay ocho corriendo a
        # la vez.
        drenar()
        with pymupdf.open(truncado) as document:
            document[0].get_text()

        with caplog.at_level(logging.INFO, logger="resolutions.adapters.mupdf_messages"):
            drenar("truncado.pdf")

        assert caplog.records
        assert all(r.getMessage().startswith("truncado.pdf: ") for r in caplog.records)

    def test_a_healthy_document_says_nothing(self, tmp_path):
        drenar()
        document = pymupdf.open()
        document.new_page().insert_text((72, 100), "todo en orden")
        path = tmp_path / "sano.pdf"
        document.save(path)
        document.close()
        with pymupdf.open(path) as sano:
            sano[0].get_text()
        assert drenar("sano.pdf") == []


class TestInstalacion:
    def test_mupdf_no_longer_prints_to_the_console(self):
        # El punto de partida: los mensajes en inglés salían por la salida de
        # error del proceso, mezclados con los fallos que sí importan.
        assert pymupdf.TOOLS.mupdf_display_errors() is False
        assert pymupdf.TOOLS.mupdf_display_warnings() is False

    def test_installing_twice_does_not_chain_one_redirect_on_another(self):
        antes = pymupdf._g_out_message
        instalar()
        assert pymupdf._g_out_message is antes
