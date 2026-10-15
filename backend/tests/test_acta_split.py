"""Tests para inventariar actas de grado."""

from __future__ import annotations

import pytest

from resolutions.adapters.mistral_summary import (
    FRASE_PROHIBIDA as FRASE_PROHIBIDA_ADAPTER,
)
from resolutions.adapters.mistral_summary import (
    SYSTEM_PROMPT,
    MistralSummaryAdapter,
)
from resolutions.application.acta_fuid import filas_de_actas
from resolutions.application.acta_split import (
    ACTA_NUMERO_RE,
    FECHA_ACTA_RE,
    FRASE_PROHIBIDA,
    MESES,
    ActaData,
    ActaSplit,
)
from resolutions.application.fuid import FuidRow

# ActaData, con otro nombre para las anotaciones de las pruebas.
ActaDataForTest = ActaData


class TestActaNumeroRegex:
    """Regex para detectar número de acta en variantes reales."""

    def test_numero_con_simbolo_grado(self):
        texto = "ACTA DE GRADO N°. 054251325"
        match = ACTA_NUMERO_RE.search(texto)
        assert match is not None
        assert match.group(1) == "054251325"

    def test_numero_sin_simbolo(self):
        texto = "ACTA DE GRADO N 054251326"
        match = ACTA_NUMERO_RE.search(texto)
        assert match is not None
        assert match.group(1) == "054251326"

    def test_numero_con_comillas_izquierda(self):
        texto = 'ACTA DE GRADO N". 054251327'
        match = ACTA_NUMERO_RE.search(texto)
        assert match is not None
        assert match.group(1) == "054251327"

    def test_numero_con_comillas_derecha(self):
        texto = 'ACTA DE GRADO N". 054251328'
        match = ACTA_NUMERO_RE.search(texto)
        assert match is not None
        assert match.group(1) == "054251328"

    def test_case_insensitive(self):
        texto = "acta de grado n° 054251325"
        match = ACTA_NUMERO_RE.search(texto)
        assert match is not None
        assert match.group(1) == "054251325"


class TestFechaActaRegex:
    """Regex para extraer fecha del primer párrafo del acta."""

    def test_fecha_diciembre_2025(self):
        texto = "En la ciudad de Cartagena a los dieciséis (16) días del mes de diciembre del año 2025"
        match = FECHA_ACTA_RE.search(texto)
        assert match is not None
        dia = int(match.group(1))
        mes_nombre = match.group(2).lower()
        año = int(match.group(3))
        assert dia == 16
        assert mes_nombre == "diciembre"
        assert año == 2025
        assert MESES[mes_nombre] == 12

    def test_fecha_marzo_2025(self):
        texto = "a los veintiocho (28) días del mes de marzo del año 2025"
        match = FECHA_ACTA_RE.search(texto)
        assert match is not None
        dia = int(match.group(1))
        mes_nombre = match.group(2).lower()
        año = int(match.group(3))
        assert dia == 28
        assert mes_nombre == "marzo"
        assert año == 2025

    def test_fecha_julio_2024(self):
        texto = "a los veintisiete (27) días del mes de julio del año 2024"
        match = FECHA_ACTA_RE.search(texto)
        assert match is not None
        assert int(match.group(1)) == 27
        assert match.group(2).lower() == "julio"
        assert int(match.group(3)) == 2024


class TestMesesMapping:
    """Mapeo de nombres de mes a número."""

    def test_todos_los_meses(self):
        assert MESES["enero"] == 1
        assert MESES["febrero"] == 2
        assert MESES["marzo"] == 3
        assert MESES["abril"] == 4
        assert MESES["mayo"] == 5
        assert MESES["junio"] == 6
        assert MESES["julio"] == 7
        assert MESES["agosto"] == 8
        assert MESES["septiembre"] == 9
        assert MESES["octubre"] == 10
        assert MESES["noviembre"] == 11
        assert MESES["diciembre"] == 12


class TestFraseProhibida:
    """Verificar que la frase prohibida está definida."""

    def test_frase_definida(self):
        assert FRASE_PROHIBIDA == "LLAMADO A LISTA Y VERIFICACIÓN DEL QUORUM"
        assert FRASE_PROHIBIDA_ADAPTER == FRASE_PROHIBIDA


class TestMistralSummaryAdapter:
    """Tests del adaptador de resumen con Mistral."""

    def test_system_prompt_contiene_regla_absoluta(self):
        assert "REGLA ABSOLUTA" in SYSTEM_PROMPT
        assert FRASE_PROHIBIDA in SYSTEM_PROMPT
        assert "NUNCA uses ni menciones" in SYSTEM_PROMPT

    def test_limpiar_texto_elimina_frase_prohibida(self):
        adapter = MistralSummaryAdapter(api_key="test-key")
        texto = "Texto normal. LLAMADO A LISTA Y VERIFICACIÓN DEL QUORUM. Más texto."
        limpio = adapter._limpiar_texto(texto)
        assert "LLAMADO A LISTA Y VERIFICACIÓN DEL QUORUM" not in limpio
        assert "llamado a lista y verificación del quorum" not in limpio.lower()

    def test_limpiar_texto_case_insensitive(self):
        adapter = MistralSummaryAdapter(api_key="test-key")
        variantes = [
            "LLAMADO A LISTA Y VERIFICACIÓN DEL QUORUM",
            "llamado a lista y verificación del quorum",
            "Llamado A Lista Y Verificación Del Quorum",
        ]
        for v in variantes:
            texto = f"Antes {v} después"
            limpio = adapter._limpiar_texto(texto)
            assert "LLAMADO" not in limpio.upper()
            assert "LISTA" not in limpio.upper()

    def test_limpiar_resumen_elimina_si_se_cola(self):
        adapter = MistralSummaryAdapter(api_key="test-key")
        resumen = "Resumen normal. LLAMADO A LISTA Y VERIFICACIÓN DEL QUORUM. Fin."
        limpio = adapter._limpiar_resumen(resumen)
        assert "LLAMADO A LISTA Y VERIFICACIÓN DEL QUORUM" not in limpio


class TestActaFuid:
    """Tests de construcción de filas FUID para actas."""

    def test_fila_tiene_campos_correctos(self):
        actas = [
            ActaData(
                numero="054251325",
                fecha="2025-12-16",
                folio="73360",
                texto_completo="texto",
                paginas=[1],
            )
        ]
        # Agregar resumen manualmente para el test
        actas[0].resumen = "Resumen de prueba"

        filas = filas_de_actas(actas, "test.pdf")

        assert len(filas) == 1
        fila = filas[0]
        assert isinstance(fila, FuidRow)
        assert fila.asunto == "ACTA DE GRADO N° 054251325"
        assert fila.fecha_inicial == "2025-12-16"
        assert fila.fecha_final == "2025-12-16"
        assert fila.consecutivo_inicial == "73360"
        assert fila.consecutivo_final == "73360"
        assert fila.notas == "Resumen de prueba"
        assert fila.folios == 1

    def test_folio_sin_folio_usa_na(self):
        actas = [
            ActaData(
                numero="054251325",
                fecha="2025-12-16",
                folio="SIN FOLIO",
                texto_completo="texto",
                paginas=[1],
            )
        ]
        actas[0].resumen = "Resumen"

        filas = filas_de_actas(actas, "test.pdf")
        fila = filas[0]

        from resolutions.application.fuid import NO_APLICA
        assert fila.consecutivo_inicial == NO_APLICA
        assert fila.consecutivo_final == NO_APLICA

    def test_fecha_sin_fecha_usa_na(self):
        actas = [
            ActaData(
                numero="054251325",
                fecha="SIN FECHA",
                folio="73360",
                texto_completo="texto",
                paginas=[1],
            )
        ]
        actas[0].resumen = "Resumen"

        filas = filas_de_actas(actas, "test.pdf")
        fila = filas[0]

        from resolutions.application.fuid import NO_APLICA
        assert fila.fecha_inicial == NO_APLICA
        assert fila.fecha_final == NO_APLICA


class TestActaSplitSplitActas:
    """Tests del método _split_actas."""

    def test_split_detecta_multiples_actas(self):
        textos = [
            "Portada",
            "ACTA DE GRADO N°. 054251325\nContenido acta 1",
            "ACTA DE GRADO N°. 054251326\nContenido acta 2",
            "ACTA DE GRADO N°. 054251327\nContenido acta 3",
        ]
        folios = {1: "SIN FOLIO", 2: "73360", 3: "73361", 4: "73362"}

        split = ActaSplit(ocr=None, mistral_summary=None)
        actas = split._split_actas(textos, folios)

        assert len(actas) == 3
        assert actas[0].numero == "054251325"
        assert actas[1].numero == "054251326"
        assert actas[2].numero == "054251327"
        assert actas[0].paginas == [2]
        assert actas[1].paginas == [3]
        assert actas[2].paginas == [4]
        assert actas[0].folio == "73360"
        assert actas[1].folio == "73361"
        assert actas[2].folio == "73362"

    def test_split_sin_actas_devuelve_lista_vacia(self):
        textos = ["Portada", "Índice", "Otro contenido"]
        folios = {1: "SIN FOLIO", 2: "SIN FOLIO", 3: "SIN FOLIO"}

        split = ActaSplit(ocr=None, mistral_summary=None)
        actas = split._split_actas(textos, folios)

        assert actas == []


class TestActaSplitExtraerFecha:
    """Tests de extracción de fecha."""

    def test_extraer_fecha_valida(self):
        split = ActaSplit(ocr=None, mistral_summary=None)
        texto = "En la ciudad de Cartagena a los dieciséis (16) días del mes de diciembre del año 2025 se llevó a cabo..."
        fecha = split._extraer_fecha(texto)
        assert fecha == "2025-12-16"

    def test_extraer_fecha_sin_match(self):
        split = ActaSplit(ocr=None, mistral_summary=None)
        texto = "Texto sin fecha válida"
        fecha = split._extraer_fecha(texto)
        assert fecha == "SIN FECHA"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])