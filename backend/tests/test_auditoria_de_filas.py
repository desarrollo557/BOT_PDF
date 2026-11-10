"""La auditoría de las filas del inventario: cada fila contra el papel de donde salió (el operador, 2026-11-09).

Una corrida de «Solo inventario» no entrega PDF cortados sino filas, y su
auditoría de cierre salía «muestra: 0 de 0». Ahora la muestra de 100 se hace con
filas, y cada una se compara con lo que **su habilidad** espera de su papel:

- de un acta de consejo, el número, la fecha, la sesión, los folios y los
  nombres de persona del resumen;
- de una persona -- historia, acta de grado, nómina --, su cédula y su nombre;
- de una fila del FUID, su número.

Error es lo que el papel contradice; lo que sólo no confirma es duda, y va a la
IA si la corrida se hizo con ella, que lo decide citando el papel. Los textos
son los de las actas del Consejo de Facultad de Odontología de la Universidad
de Cartagena (caja 00C003284), con su OCR.
"""

from __future__ import annotations

import io
import json
import os
import urllib.error
from dataclasses import asdict
from pathlib import Path

import pytest

from resolutions.adapters import mistral_juez_de_datos as modulo_del_juez
from resolutions.adapters.mistral_juez_de_datos import (
    PROVEEDOR,
    ConfigDelJuezDeDatos,
    MistralJuezDeDatos,
    leer_la_respuesta,
)
from resolutions.api.auditoria import (
    UNIDAD_FILAS,
    EntregaVista,
    auditar_las_filas,
    etapa_de,
    filas_candidatas,
)
from resolutions.api.constancia import Constancia, EstadoDeEntrega, Vigencia
from resolutions.application.acta_consejo import FilaDeActa
from resolutions.application.auditoria_de_filas import (
    auditar_una_fila,
    cita_del_papel,
    nombres_de_persona,
    parece_del_ocr,
)
from resolutions.application.consumo import Consumo
from resolutions.application.control import Cancelled
from resolutions.application.perfiles_de_revision import perfil_de
from resolutions.application.ports import JuezDeDatos, VeredictoDeDato
from resolutions.domain.acta_consejo import MARGEN_DE_FOLIOS
from resolutions.domain.auditoria import (
    BIEN,
    DENTRO_DEL_MARGEN,
    DUDOSO,
    ERROR,
    NO_AUDITADO,
    SIN_CERTEZA,
    margen_de_error,
)
from resolutions.domain.auditoria_de_filas import (
    clase_de_la_fila,
    id_de_la_fila,
    nombre_en_el_texto,
    numero_en_el_texto,
    paginas_de_la_fila,
    revisar_la_fila,
)

# -- el papel de un acta ---------------------------------------------------------------

#: La hoja que abre la sesión 022 de 2012: encabezado con su clase y la tabla de apertura.
APERTURA_022 = (
    "UNIVERSIDAD DE CARTAGENA\n"
    "FACULTAD DE ODONTOLOGÍA\n"
    "ACTA ORDINARIA No. 022\n"
    "FECHA: Lunes 17 de diciembre de 2012\n"
    "HORA: 8:00 a.m.\n"
    "LUGAR: Decanatura de la Facultad\n"
    "ASISTENTES: Luisa Arévalo Tovar, Decana; Eduardo Ordosgoitia Osorio, Vicedecano Académico;\n"
    "Martha Carmona Lorduy, Jefe del Departamento de Odontología Preventiva y Social.\n"
    "ORDEN DEL DÍA\n1. Verificación del quórum\n2. Lectura y aprobación del acta anterior"
)
#: La segunda hoja: el membrete corrido, que nombra el acta pero no abre sesión.
CORRIDA_022 = (
    "Acta No. 022-2012\n"
    "3. Informe de la Decana. La doctora Luisa Arévalo Tovar informa al Consejo sobre el proceso de\n"
    "reacreditación del programa y la visita de pares académicos.\n"
    "4. Solicitudes de profesores. El profesor Eduardo Ordosgoitia Osorio solicita comisión de estudios."
)
#: Un acta cuya hoja no trae el encabezado: el OCR se comió la cabecera.
SIN_ENCABEZADO = (
    "En la ciudad de Cartagena de Indias, siendo las 8:00 a.m., se reunieron los miembros del\n"
    "Consejo de Facultad de Odontología en sesión número veintidós (022) del año en curso,\n"
    "presidida por la Decana Luisa Arévalo Tovar."
)
ANEXO_PREVIO = (
    "lleva delante, como anexo, las páginas 1 a 7 del PDF, escaneadas antes que el acta"
)


def _acta(**cambios) -> dict:
    """La fila de la sesión 022, como la deja ``FilaDeActa`` en la constancia."""
    fila = asdict(
        FilaDeActa(
            archivo="1N°22.pdf",
            acta="ACTA ORDINARIA No. 022",
            fecha="17-12-2012",
            folio_inicial=1,
            folio_final=2,
            folios=2,
            resumen="",
            pagina_inicial=1,
            pagina_final=2,
            numero="022",
        )
    )
    fila.update(cambios)
    return fila


@pytest.fixture(scope="module")
def nombres():
    de_pila, apellidos = nombres_de_persona()
    return {"de_pila": de_pila, "apellidos": apellidos}


# -- domain: un acta de consejo ---------------------------------------------------------


class TestElNumeroDelActa:
    def test_lo_confirma_el_encabezado_que_abre_la_sesion(self):
        revision = revisar_la_fila(_acta(), [APERTURA_022, CORRIDA_022])
        assert "el número del acta" in revision.confirmados
        assert not revision.errores

    def test_lo_confirma_tambien_el_membrete_corrido(self):
        # La hoja de apertura no se escaneó: sólo queda «Acta No. 022-2012».
        revision = revisar_la_fila(_acta(fecha="N/A"), [CORRIDA_022])
        assert "el número del acta" in revision.confirmados

    def test_otro_numero_en_un_encabezado_fuerte_es_error(self):
        revision = revisar_la_fila(
            _acta(numero="045", acta="ACTA ORDINARIA No. 045"),
            [APERTURA_022, CORRIDA_022],
        )
        assert "el acta dice No. 022 y la fila No. 045" in revision.errores

    def test_un_digito_distinto_lo_decide_la_ia(self):
        """El acta 005 que el OCR de la capa leyó 006 (la revisión, 2026-11-09): pregunta, no error."""
        revision = revisar_la_fila(
            _acta(numero="023", acta="ACTA ORDINARIA No. 023"),
            [APERTURA_022, CORRIDA_022],
        )
        assert not revision.errores
        assert [p.campo for p in revision.preguntas] == ["numero"]

    def test_la_diferencia_que_la_fila_ya_registro_entre_el_ocr_y_la_ia_es_pregunta(self):
        fila = _acta(numero="045", acta="ACTA ORDINARIA No. 045")
        fila["observaciones"] = "el OCR leyó 022 y la IA 045; se dejó lo de la IA"
        revision = revisar_la_fila(fila, [APERTURA_022, CORRIDA_022])
        assert not revision.errores and revision.preguntas[0].campo == "numero"
        assert "el número del acta" not in revision.confirmados

    def test_sin_encabezado_es_una_pregunta_no_un_error(self):
        revision = revisar_la_fila(_acta(numero="022"), [SIN_ENCABEZADO])
        assert not revision.errores
        assert [p.campo for p in revision.preguntas if p.campo == "numero"] == ["numero"]
        pregunta = next(p for p in revision.preguntas if p.campo == "numero")
        assert pregunta.valor == "022"
        assert pregunta.duda == "el número 022 no aparece en el encabezado de su acta"

    def test_sin_numero_en_la_fila_no_se_mira(self):
        revision = revisar_la_fila(_acta(numero="N/A"), [APERTURA_022])
        assert "el número del acta" in revision.sin_dato
        assert not any(p.campo == "numero" for p in revision.preguntas)


class TestLaFechaDeLaSesion:
    @pytest.mark.parametrize(
        "escrita",
        [
            "Cartagena, 17 de diciembre de 2012",
            "Fecha de la sesión: 17/12/2012",
            "diciembre 17 de 2012",
        ],
    )
    def test_la_fecha_escrita_en_el_papel_la_confirma(self, escrita):
        revision = revisar_la_fila(
            _acta(numero="N/A"), [f"Consejo de Facultad de Odontología\n{escrita}"]
        )
        assert "la fecha de la sesión" in revision.confirmados
        assert not any(p.campo == "fecha" for p in revision.preguntas)

    @pytest.mark.parametrize(
        "texto",
        [
            "En Cartagena de Indias, a los diecisiete (17) de diciembre de 2012, se reunió el Consejo de Facultad.",
            "a los diecisiete (17) días del mes de diciembre de dos mil doce (2012) se reunió el Consejo.",
            "el 17 de diciembre de dos mil doce (2012) se reunió el Consejo.",
        ],
    )
    def test_la_fecha_con_letras_y_cifras_entre_parentesis_la_confirma(self, texto):
        """La forma de las actas: el número con letras y en cifras, y «días del mes de» (2026-11-09)."""
        revision = revisar_la_fila(_acta(numero="N/A"), [texto])
        assert "la fecha de la sesión" in revision.confirmados

    def test_otra_fecha_en_el_papel_es_pregunta(self):
        revision = revisar_la_fila(_acta(fecha="18-12-2012"), [APERTURA_022])
        pregunta = next(p for p in revision.preguntas if p.campo == "fecha")
        assert pregunta.valor == "18/12/2012"
        assert pregunta.duda == "la fecha 18/12/2012 no es la de la apertura de su acta"
        assert not revision.errores

    def test_la_fecha_que_no_se_leyo_no_se_mira(self):
        revision = revisar_la_fila(_acta(fecha="N/A"), [APERTURA_022])
        assert "la fecha de la sesión" in revision.sin_dato


class TestLaSesion:
    def test_la_misma_clase_se_confirma(self):
        assert (
            "la sesión"
            in revisar_la_fila(_acta(), [APERTURA_022, CORRIDA_022]).confirmados
        )

    def test_otra_clase_en_el_encabezado_es_error(self):
        revision = revisar_la_fila(
            _acta(acta="ACTA EXTRAORDINARIA No. 022"), [APERTURA_022, CORRIDA_022]
        )
        assert (
            "el acta dice sesión ORDINARIA y la fila EXTRAORDINARIA" in revision.errores
        )

    def test_sin_clase_en_el_papel_no_se_juzga(self):
        revision = revisar_la_fila(
            _acta(acta="ACTA EXTRAORDINARIA No. 022"), [SIN_ENCABEZADO]
        )
        assert not any("sesión" in e for e in revision.errores)
        assert "la sesión" not in revision.confirmados


class TestLosFolios:
    def test_las_paginas_de_anexo_escaneadas_delante_suman(self):
        # UPD3859787: siete páginas de anexo delante de la primera acta, que su fila cuenta.
        paginas = [APERTURA_022, CORRIDA_022] + [
            "Anexo: oficio de la Vicerrectoría Académica."
        ] * 20
        fila = _acta(
            folio_inicial=1,
            folio_final=15,
            folios=22,
            pagina_final=22,
            observaciones=ANEXO_PREVIO,
        )
        revision = revisar_la_fila(fila, paginas)
        assert "los folios" in revision.confirmados
        assert not revision.errores

    def test_sin_el_anexo_previo_la_cuenta_no_suma(self):
        paginas = [APERTURA_022, CORRIDA_022] + ["Anexo."] * 20
        fila = _acta(folio_inicial=1, folio_final=15, folios=22, pagina_final=22)
        revision = revisar_la_fila(fila, paginas)
        assert "los folios 1 a 15 son 15 y la fila dice 22" in revision.errores

    def test_un_anexo_previo_que_tampoco_alcanza_se_dice(self):
        paginas = [APERTURA_022] * 25
        fila = _acta(
            folio_inicial=1,
            folio_final=15,
            folios=25,
            pagina_final=25,
            observaciones=ANEXO_PREVIO,
        )
        revision = revisar_la_fila(fila, paginas)
        assert (
            "los folios 1 a 15 son 15 más 7 de anexo y la fila dice 25"
            in revision.errores
        )

    def test_el_folio_final_menor_que_el_inicial_es_error(self):
        revision = revisar_la_fila(
            _acta(folio_inicial=12, folio_final=3, folios=2), [APERTURA_022, CORRIDA_022]
        )
        assert "el folio final 3 es menor que el inicial 12" in revision.errores

    def test_mas_folios_que_paginas_dentro_de_la_tolerancia_es_pregunta(self):
        # Diez páginas: la tolerancia es la absoluta, dos folios.
        paginas = [APERTURA_022] + [CORRIDA_022] * 9
        fila = _acta(
            folio_inicial=1,
            folio_final=10 + MARGEN_DE_FOLIOS,
            folios=10 + MARGEN_DE_FOLIOS,
        )
        revision = revisar_la_fila(fila, paginas)
        assert not revision.errores
        pregunta = next(p for p in revision.preguntas if p.campo == "folios")
        assert (
            pregunta.duda
            == "la fila dice 12 folios y el acta tiene 10 páginas (dentro del margen de los folios)"
        )

    def test_mas_folios_que_paginas_fuera_de_la_tolerancia_es_error(self):
        paginas = [APERTURA_022] + [CORRIDA_022] * 9
        fila = _acta(folio_inicial=1, folio_final=13, folios=13)
        revision = revisar_la_fila(fila, paginas)
        assert "la fila dice 13 folios y el acta tiene 10 páginas" in revision.errores

    def test_en_un_acta_larga_la_tolerancia_es_el_diez_por_ciento(self):
        paginas = [APERTURA_022] + [CORRIDA_022] * 39
        dentro = revisar_la_fila(
            _acta(folio_inicial=1, folio_final=44, folios=44), paginas
        )
        fuera = revisar_la_fila(
            _acta(folio_inicial=1, folio_final=45, folios=45), paginas
        )
        assert not dentro.errores and any(p.campo == "folios" for p in dentro.preguntas)
        assert "la fila dice 45 folios y el acta tiene 40 páginas" in fuera.errores


class TestLosNombresDelResumen:
    RESUMEN = (
        "Presidió la sesión la Decana Luisa Arévalo Tovar. Se aprobó la comisión de estudios del profesor "
        "Eduardo Ordosgoitia Osorio a la Universidad de Burdeos y la programación de Semiología y Diagnóstico"
    )

    def test_los_nombres_que_estan_en_el_acta_se_confirman(self, nombres):
        revision = revisar_la_fila(
            _acta(resumen=self.RESUMEN), [APERTURA_022, CORRIDA_022], **nombres
        )
        assert "los nombres del resumen" in revision.confirmados
        assert not any(p.campo.startswith("nombre:") for p in revision.preguntas)

    def test_un_nombre_que_el_acta_no_trae_se_pregunta(self, nombres):
        resumen = (
            self.RESUMEN + ". La estudiante Carolina Mendoza Pájaro presentó su renuncia"
        )
        revision = revisar_la_fila(
            _acta(resumen=resumen), [APERTURA_022, CORRIDA_022], **nombres
        )
        preguntas = [p for p in revision.preguntas if p.campo.startswith("nombre:")]
        assert [p.valor for p in preguntas] == ["Carolina Mendoza Pájaro"]
        assert (
            preguntas[0].duda
            == "«Carolina Mendoza Pájaro», del resumen, no aparece en su acta"
        )
        assert "los nombres del resumen" not in revision.confirmados
        assert not revision.errores

    def test_un_nombre_con_una_letra_del_ocr_sigue_siendo_el_mismo(self, nombres):
        papel = APERTURA_022.replace("Ordosgoitia", "Ordosgoitla")
        revision = revisar_la_fila(_acta(resumen=self.RESUMEN), [papel], **nombres)
        assert "los nombres del resumen" in revision.confirmados

    def test_con_la_lista_de_nombres_ni_instituciones_ni_temas_se_preguntan(
        self, nombres
    ):
        # Ni «Universidad de Burdeos» ni «Semiología y Diagnóstico» están en el acta, y no son personas.
        revision = revisar_la_fila(_acta(resumen=self.RESUMEN), [APERTURA_022], **nombres)
        valores = {p.valor for p in revision.preguntas}
        assert "Universidad de Burdeos" not in valores
        assert not any("Semiolog" in v for v in valores)

    def test_un_nombre_al_final_de_la_oracion_no_se_pega_a_la_siguiente(self, nombres):
        """Lo encontraron las pruebas (2026-11-09): el punto dentro de la palabra unía dos oraciones."""
        resumen = "Se aceptó la renuncia de la profesora Carolina Mendoza Pájaro. Consejo Académico aprobó el calendario"
        revision = revisar_la_fila(
            _acta(resumen=resumen), [APERTURA_022, CORRIDA_022], **nombres
        )
        assert "Carolina Mendoza Pájaro" in {p.valor for p in revision.preguntas}

    def test_sin_la_lista_se_buscan_todas_las_frases(self):
        revision = revisar_la_fila(_acta(resumen=self.RESUMEN), [APERTURA_022])
        assert "Universidad de Burdeos" in {p.valor for p in revision.preguntas}


# -- domain: una persona y una fila del FUID --------------------------------------------

FICHA = (
    "UNIVERSIDAD DE CARTAGENA\nFACULTAD DE ODONTOLOGÍA\nHOJA DE VIDA ACADÉMICA DEL ESTUDIANTE\n"
    "Nombre: MARIA FERNANDA PERES GOMEZ\n"
    "Documento de identidad: C.C. No. 45.466.499 de Cartagena\n"
    "Código: 0120410023    Programa: ODONTOLOGÍA"
)


class TestUnaPersona:
    def test_la_cedula_con_puntos_y_el_nombre_con_una_letra_cambiada_se_confirman(self):
        fila = {
            "tipo": "HISTORIA ACADEMICA",
            "nombre": "MARIA FERNANDA PEREZ GOMEZ",
            "cedula": "45466499",
        }
        revision = revisar_la_fila(fila, [FICHA])
        assert clase_de_la_fila(fila) == "persona"
        assert set(revision.confirmados) == {"la cédula", "el nombre"}
        assert not revision.preguntas and not revision.errores

    def test_el_codigo_tambien_se_busca(self):
        fila = {"nombre": "MARIA FERNANDA PEREZ GOMEZ", "codigo": "0120410023"}
        assert "el código" in revisar_la_fila(fila, [FICHA]).confirmados

    def test_una_cedula_que_el_papel_no_trae_es_pregunta(self):
        fila = {
            "tipo": "HISTORIA ACADEMICA",
            "nombre": "MARIA FERNANDA PEREZ GOMEZ",
            "cedula": "45.466.498",
        }
        revision = revisar_la_fila(fila, [FICHA])
        assert [(p.campo, p.valor) for p in revision.preguntas] == [
            ("cedula", "45466498")
        ]
        assert revision.preguntas[0].duda == "la cédula 45466498 no aparece en su papel"
        assert not revision.errores

    def test_otro_estudiante_es_pregunta(self):
        fila = {"nombre": "JUAN CARLOS HERRERA BLANCO", "cedula": "45466499"}
        revision = revisar_la_fila(fila, [FICHA])
        assert [p.campo for p in revision.preguntas] == ["nombre"]

    def test_un_numero_corto_no_prueba_nada_y_no_se_busca(self):
        revision = revisar_la_fila(
            {"nombre": "MARIA FERNANDA PEREZ GOMEZ", "cedula": "499"}, [FICHA]
        )
        assert "la cédula" not in revision.confirmados
        assert not any(p.campo == "cedula" for p in revision.preguntas)

    def test_el_acta_de_grado_se_revisa_como_persona(self):
        fila = {
            "tipo": "ACTA DE GRADO",
            "numero": "015",
            "acta": "ACTA DE GRADO No. 015",
            "nombre": "MARIA PEREZ",
        }
        assert clase_de_la_fila(fila) == "persona"


RESOLUCION = (
    "UNIVERSIDAD DE CARTAGENA\nRESOLUCIÓN No. 031\n(15 de marzo de 2005)\n"
    "Por la cual se reconoce un título. EL RECTOR DE LA UNIVERSIDAD DE CARTAGENA, en uso de sus facultades..."
)


class TestUnaFilaDelFuid:
    def test_el_numero_con_ceros_delante_es_el_mismo(self):
        fila = {
            "tipo": "FILA DEL FUID",
            "fuid": {"consecutivo_inicial": "00031", "pagina_inicial": 5, "folios": 2},
        }
        revision = revisar_la_fila(fila, [RESOLUCION])
        assert clase_de_la_fila(fila) == "fuid"
        assert revision.confirmados == ("el número del documento",)

    def test_el_papel_con_ceros_y_la_fila_sin_ellos(self):
        fila = {"fuid": {"consecutivo_inicial": "31"}}
        assert revisar_la_fila(fila, ["RESOLUCION 00031 DE 2005"]).confirmados == (
            "el número del documento",
        )

    def test_otro_numero_es_pregunta(self):
        revision = revisar_la_fila(
            {"fuid": {"consecutivo_inicial": "0045"}}, [RESOLUCION]
        )
        assert [(p.campo, p.valor) for p in revision.preguntas] == [("consecutivo", "0045")]

    def test_sin_numero_no_se_mira(self):
        assert revisar_la_fila(
            {"fuid": {"consecutivo_inicial": "N/A"}}, [RESOLUCION]
        ).sin_dato == ("el número del documento",)


class TestLasPaginasYElNombreDeLaFila:
    def test_la_fila_del_acta_dice_sus_paginas(self):
        assert paginas_de_la_fila(_acta(pagina_inicial=1, pagina_final=22)) == (1, 22)
        assert paginas_de_la_fila(
            _acta(pagina_inicial=40, pagina_final=50), total=45
        ) == (40, 45)
        assert (
            paginas_de_la_fila(_acta(pagina_inicial=50, pagina_final=55), total=45)
            is None
        )

    def test_la_fila_del_fuid_va_hasta_donde_digan_sus_folios(self):
        assert paginas_de_la_fila({"fuid": {"pagina_inicial": 5, "folios_siar": 3}}) == (
            5,
            7,
        )
        assert paginas_de_la_fila({"fuid": {"pagina_inicial": 5}}) == (5, 5)
        assert paginas_de_la_fila({"fuid": {}}) is None

    def test_el_nombre_de_la_fila_en_la_muestra(self):
        fila = _acta(pagina_inicial=1, pagina_final=22)
        assert id_de_la_fila("00C003284/UPD3859771/1N°22.pdf", fila) == (
            "00C003284/UPD3859771/1N°22.pdf · págs. 1-22 · acta 022"
        )
        persona = {
            "nombre": "MARIA FERNANDA PEREZ GOMEZ",
            "pagina_inicial": 3,
            "pagina_final": 3,
        }
        assert (
            id_de_la_fila("caja/UPD1.pdf", persona)
            == "caja/UPD1.pdf · pág. 3 · MARIA FERNANDA PEREZ GOMEZ"
        )

    def test_los_numeros_y_los_nombres_en_el_texto(self):
        assert numero_en_el_texto("45466499", "C.C. 45.466.499")
        assert numero_en_el_texto("45466499", "C.C. 45 466 499")
        assert not numero_en_el_texto("4546649", "C.C. 45466499")
        assert nombre_en_el_texto(
            "LUISA LEONOR ARÉVALO TOVAR", "la Decana Luisa Arévalo Tovar"
        )
        assert not nombre_en_el_texto("LUISA TOVAR", "la Decana Luisa Arévalo")


# -- application: la fila con la IA -----------------------------------------------------


class _JuezFalso:
    """Un juez que contesta lo que se le dicte, y anota lo que se le preguntó."""

    def __init__(self, respuestas: dict[str, VeredictoDeDato] | None):
        self.respuestas = respuestas
        self.preguntas: list[tuple[str, list[dict[str, str]]]] = []

    def verificar(self, texto, datos):
        self.preguntas.append((texto, datos))
        return self.respuestas


#: Sólo el número, que el papel sin encabezado no confirma: lo demás no se lee.
FILA_SIN_ENCABEZADO = {
    "tipo": "ACTA DE CONSEJO",
    "numero": "022",
    "pagina_inicial": 1,
    "pagina_final": 1,
}


class TestUnaFilaConLaIa:
    def test_el_juez_falso_cumple_el_puerto(self):
        assert isinstance(_JuezFalso({}), JuezDeDatos)
        assert isinstance(MistralJuezDeDatos(api_key="x"), JuezDeDatos)

    def test_esta_con_su_cita_es_bien(self):
        juez = _JuezFalso(
            {"numero": VeredictoDeDato("esta", "sesión número veintidós (022)")}
        )
        resultado = auditar_una_fila(
            "UPD1.pdf · pág. 1 · acta 022",
            FILA_SIN_ENCABEZADO,
            [SIN_ENCABEZADO],
            juez=juez,
        )
        assert resultado.estado == BIEN
        assert resultado.hallazgos == ()
        assert resultado.preguntadas_a_la_ia == 1
        texto, datos = juez.preguntas[0]
        assert datos == [{"campo": "numero", "valor": "022"}]
        assert "veintidós (022)" in texto

    def test_no_esta_con_una_cita_que_choca_es_error(self):
        papel = SIN_ENCABEZADO.replace("veintidós (022)", "treinta y cinco (035)")
        juez = _JuezFalso(
            {"numero": VeredictoDeDato("no_esta", "sesión número treinta y cinco (035)")}
        )
        resultado = auditar_una_fila("UPD1.pdf", FILA_SIN_ENCABEZADO, [papel], juez=juez)
        assert resultado.estado == ERROR
        assert resultado.hallazgos == (
            "el número 022 no aparece en el encabezado de su acta: la IA lo confirma, "
            "el papel dice «sesión número treinta y cinco (035)»",
        )

    def test_una_cita_que_no_esta_en_el_texto_no_vale(self):
        juez = _JuezFalso(
            {"numero": VeredictoDeDato("no_esta", "ACTA EXTRAORDINARIA No. 035")}
        )
        resultado = auditar_una_fila(
            "UPD1.pdf", FILA_SIN_ENCABEZADO, [SIN_ENCABEZADO], juez=juez
        )
        assert resultado.estado == DUDOSO
        assert resultado.hallazgos == (
            "el número 022 no aparece en el encabezado de su acta",
        )

    def test_esta_con_una_cita_inventada_tampoco_vale(self):
        juez = _JuezFalso({"numero": VeredictoDeDato("esta", "ACTA ORDINARIA No. 022")})
        assert (
            auditar_una_fila(
                "UPD1.pdf", FILA_SIN_ENCABEZADO, [SIN_ENCABEZADO], juez=juez
            ).estado
            == DUDOSO
        )

    def test_un_anio_con_un_digito_del_ocr_es_duda_y_no_error(self):
        # «16 DE ENERO DE 2000» frente a 16/01/2009: el OCR del escaneo viejo.
        fila = {
            "tipo": "ACTA DE CONSEJO",
            "numero": "N/A",
            "fecha": "16-01-2009",
            "pagina_inicial": 1,
        }
        papel = "CONSEJO DE FACULTAD ORDINARIO\nCartagena, 16 DE ENERO DE 2000\nSe verificó el quórum."
        juez = _JuezFalso({"fecha": VeredictoDeDato("no_esta", "16 DE ENERO DE 2000")})
        resultado = auditar_una_fila("UPD1.pdf", fila, [papel], juez=juez)
        assert resultado.estado == DUDOSO
        assert resultado.hallazgos == (
            "la fecha 16/01/2009 no es la de la apertura de su acta: el texto dice «16 DE ENERO DE 2000», "
            "que puede ser el OCR: revíselo en el papel",
        )

    def test_un_dia_que_el_ocr_deshizo_es_duda(self):
        fila = {
            "tipo": "ACTA DE CONSEJO",
            "numero": "N/A",
            "fecha": "13-12-2007",
            "pagina_inicial": 1,
        }
        papel = "ACTA CONSEJO DE FACULTAD\nCartagena, I3DF, DICIEMBRE DE 2007\nSe verificó el quórum."
        juez = _JuezFalso(
            {"fecha": VeredictoDeDato("no_esta", "I3DF, DICIEMBRE DE 2007")}
        )
        resultado = auditar_una_fila("UPD1.pdf", fila, [papel], juez=juez)
        assert resultado.estado == DUDOSO
        assert "puede ser el OCR" in resultado.hallazgos[0]

    def test_no_se_sigue_en_duda(self):
        juez = _JuezFalso(
            {"numero": VeredictoDeDato("no_se", "sesión número veintidós (022)")}
        )
        resultado = auditar_una_fila(
            "UPD1.pdf", FILA_SIN_ENCABEZADO, [SIN_ENCABEZADO], juez=juez
        )
        assert resultado.estado == DUDOSO

    def test_sin_juez_lo_dudoso_queda_en_duda(self):
        resultado = auditar_una_fila(
            "UPD1.pdf", FILA_SIN_ENCABEZADO, [SIN_ENCABEZADO], juez=None
        )
        assert resultado.estado == DUDOSO
        assert resultado.preguntadas_a_la_ia == 0
        assert resultado.hallazgos == (
            "el número 022 no aparece en el encabezado de su acta",
        )

    def test_el_juez_que_no_responde_se_dice(self):
        resultado = auditar_una_fila(
            "UPD1.pdf", FILA_SIN_ENCABEZADO, [SIN_ENCABEZADO], juez=_JuezFalso(None)
        )
        assert resultado.estado == DUDOSO
        assert resultado.hallazgos == (
            "el número 022 no aparece en el encabezado de su acta (la IA no respondió)",
        )

    def test_lo_que_el_papel_confirma_no_se_le_pregunta(self):
        juez = _JuezFalso({})
        resultado = auditar_una_fila(
            "UPD1.pdf", _acta(), [APERTURA_022, CORRIDA_022], juez=juez
        )
        assert resultado.estado == BIEN
        assert juez.preguntas == []
        assert "el número del acta" in resultado.extra["confirmados"]

    def test_las_paginas_sin_texto_se_dicen_cuando_algo_no_se_encontro(self):
        resultado = auditar_una_fila(
            "UPD1.pdf", FILA_SIN_ENCABEZADO, [SIN_ENCABEZADO, ""], sin_texto=1
        )
        assert resultado.hallazgos[-1] == "1 página(s) de la fila sin texto que leer"
        assert resultado.paginas == 2

    def test_las_paginas_sin_texto_no_ensucian_una_fila_bien(self):
        resultado = auditar_una_fila(
            "UPD1.pdf", _acta(), [APERTURA_022, CORRIDA_022, ""], sin_texto=1
        )
        assert resultado.estado == BIEN and resultado.hallazgos == ()

    def test_la_habilidad_viaja_con_la_fila(self):
        resultado = auditar_una_fila(
            "UPD1.pdf", _acta(), [APERTURA_022], habilidad="actas de consejo"
        )
        assert resultado.as_dict()["habilidad"] == "actas de consejo"
        assert resultado.as_dict()["costuras"] == 0


class TestLaCitaYElOcr:
    def test_la_cita_se_busca_sin_tildes_ni_signos(self):
        assert cita_del_papel("SESION NUMERO VEINTIDOS (022)", SIN_ENCABEZADO)
        assert not cita_del_papel("ab", SIN_ENCABEZADO)
        assert not cita_del_papel("sesión número treinta", SIN_ENCABEZADO)

    def test_un_numero_que_choca_en_dos_digitos_no_es_del_ocr(self):
        assert not parece_del_ocr("022", "ACTA No. 035")
        assert parece_del_ocr("022", "ACTA No. 023")

    def test_un_nombre_con_una_letra_cambiada_es_del_ocr_y_otro_apellido_no(self):
        assert parece_del_ocr(
            "EDUARDO ORDOSGOITIA", "el profesor Eduardo Ordosgoitla Osorio"
        )
        assert not parece_del_ocr("EDUARDO ORDOGOITIA", "Eduardo Ordóñez Ordoñez")


# -- adapter: el juez de Mistral --------------------------------------------------------


class TestLaRespuestaDeMistral:
    def test_una_respuesta_entera(self):
        texto = json.dumps(
            {
                "datos": [
                    {
                        "campo": "fecha",
                        "decision": "esta",
                        "cita": "diecisiete (17) de diciembre de 2012",
                    },
                    {
                        "campo": "numero",
                        "decision": "no_esta",
                        "cita": "ACTA ORDINARIA No. 023",
                    },
                ]
            }
        )
        assert leer_la_respuesta(texto, ["fecha", "numero"]) == {
            "fecha": VeredictoDeDato("esta", "diecisiete (17) de diciembre de 2012"),
            "numero": VeredictoDeDato("no_esta", "ACTA ORDINARIA No. 023"),
        }

    def test_cortada_se_rescatan_las_entradas_enteras(self):
        texto = (
            '{"datos":[{"campo":"numero","decision":"esta","cita":"ACTA ORDINARIA No. 022"},'
            '{"campo":"nombre:Luisa Arévalo Tovar","decision":"esta","cita":"Luisa Arévalo Tovar"},'
            '{"campo":"fecha","decision":"no_es'
        )
        respuesta = leer_la_respuesta(
            texto, ["numero", "nombre:Luisa Arévalo Tovar", "fecha"]
        )
        assert respuesta == {
            "numero": VeredictoDeDato("esta", "ACTA ORDINARIA No. 022"),
            "nombre:Luisa Arévalo Tovar": VeredictoDeDato("esta", "Luisa Arévalo Tovar"),
        }

    def test_un_campo_repetido_se_queda_con_la_primera(self):
        texto = json.dumps(
            {
                "datos": [
                    {"campo": "numero", "decision": "esta", "cita": "ACTA No. 022"},
                    {"campo": "numero", "decision": "no_esta", "cita": "ACTA No. 023"},
                ]
            }
        )
        assert leer_la_respuesta(texto, ["numero"]) == {
            "numero": VeredictoDeDato("esta", "ACTA No. 022")
        }

    def test_un_campo_que_no_se_pregunto_se_ignora(self):
        texto = json.dumps(
            {
                "datos": [
                    {"campo": "numero", "decision": "esta", "cita": "ACTA No. 022"},
                    {"campo": "lugar", "decision": "esta", "cita": "Decanatura"},
                ]
            }
        )
        assert set(leer_la_respuesta(texto, ["numero"])) == {"numero"}

    def test_una_decision_desconocida_es_no_se(self):
        texto = json.dumps(
            {
                "datos": [
                    {"campo": "numero", "decision": "quizás", "cita": "ACTA No. 022"},
                    {"campo": "fecha", "decision": " ESTA ", "cita": "17/12/2012"},
                    {"campo": "folios"},
                ]
            }
        )
        respuesta = leer_la_respuesta(texto, ["numero", "fecha", "folios"])
        assert respuesta["numero"] == VeredictoDeDato("no_se", "ACTA No. 022")
        assert respuesta["fecha"].decision == "esta"
        assert respuesta["folios"] == VeredictoDeDato("no_se", "")

    def test_lo_que_no_se_entiende_no_da_nada(self):
        assert leer_la_respuesta("Lo siento, no puedo ayudar con eso.", ["numero"]) == {}
        assert leer_la_respuesta("", ["numero"]) == {}
        assert leer_la_respuesta('["numero"]', ["numero"]) == {}


def _respuesta_de_mistral(contenido: dict, uso: dict | None = None) -> io.BytesIO:
    cuerpo = {"choices": [{"message": {"content": json.dumps(contenido)}}]}
    if uso is not None:
        cuerpo["usage"] = uso
    return io.BytesIO(json.dumps(cuerpo).encode())


class TestElJuezDeMistral:
    DATOS = [
        {"campo": "numero", "valor": "022"},
        {"campo": "fecha", "valor": "17/12/2012"},
    ]

    def test_pregunta_con_la_llave_en_el_encabezado_y_anota_el_consumo(self, monkeypatch):
        capturado = {}

        def urlopen_falso(peticion, timeout=None):
            capturado["url"] = peticion.full_url
            capturado["auth"] = peticion.get_header("Authorization")
            capturado["cuerpo"] = json.loads(peticion.data)
            return _respuesta_de_mistral(
                {
                    "datos": [
                        {
                            "campo": "numero",
                            "decision": "esta",
                            "cita": "sesión número veintidós (022)",
                        }
                    ]
                },
                {"prompt_tokens": 1200, "completion_tokens": 40},
            )

        monkeypatch.setattr(modulo_del_juez.urllib.request, "urlopen", urlopen_falso)
        consumo = Consumo()
        juez = MistralJuezDeDatos(api_key="llave-de-prueba", consumo=consumo)

        respuesta = juez.verificar(SIN_ENCABEZADO, self.DATOS)

        assert respuesta == {
            "numero": VeredictoDeDato("esta", "sesión número veintidós (022)")
        }
        assert capturado["url"] == modulo_del_juez.ENDPOINT
        assert "llave-de-prueba" not in capturado["url"]
        assert capturado["auth"] == "Bearer llave-de-prueba"
        assert capturado["cuerpo"]["temperature"] == 0
        assert capturado["cuerpo"]["response_format"] == {"type": "json_object"}
        pregunta = json.loads(capturado["cuerpo"]["messages"][1]["content"])
        assert pregunta == {"datos": self.DATOS, "texto": SIN_ENCABEZADO}
        cuentas = consumo.as_dict()
        assert cuentas["proveedores"][PROVEEDOR]["peticiones"] == 1
        assert (
            cuentas["tokens_entrada"],
            cuentas["tokens_salida"],
            cuentas["tokens"],
        ) == (1200, 40, 1240)

    def test_sin_datos_no_pregunta(self, monkeypatch):
        monkeypatch.setattr(modulo_del_juez.urllib.request, "urlopen", pytest.fail)
        assert MistralJuezDeDatos(api_key="x").verificar(SIN_ENCABEZADO, []) == {}

    def test_sin_llave_no_responde(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setattr(modulo_del_juez.urllib.request, "urlopen", pytest.fail)
        assert (
            MistralJuezDeDatos(api_key="").verificar(SIN_ENCABEZADO, self.DATOS) is None
        )

    def test_detener_antes_de_pedir_no_paga_nada(self, monkeypatch):
        llamadas = []
        monkeypatch.setattr(
            modulo_del_juez.urllib.request, "urlopen", lambda *a, **k: llamadas.append(a)
        )

        def detenido():
            raise Cancelled("el operador detuvo la corrida")

        juez = MistralJuezDeDatos(api_key="x", antes_de_pedir=detenido)
        with pytest.raises(Cancelled):
            juez.verificar(SIN_ENCABEZADO, self.DATOS)
        assert llamadas == []

    def test_un_ahora_no_se_reintenta(self, monkeypatch):
        intentos = []

        def urlopen_falso(peticion, timeout=None):
            intentos.append(1)
            if len(intentos) == 1:
                raise urllib.error.HTTPError(peticion.full_url, 429, "despacio", {}, None)
            return _respuesta_de_mistral(
                {"datos": [{"campo": "fecha", "decision": "no_se", "cita": ""}]}
            )

        monkeypatch.setattr(modulo_del_juez.urllib.request, "urlopen", urlopen_falso)
        monkeypatch.setattr(modulo_del_juez.time, "sleep", lambda _s: None)
        consumo = Consumo()
        juez = MistralJuezDeDatos(
            api_key="x", consumo=consumo, config=ConfigDelJuezDeDatos(espera_inicial=0)
        )
        assert juez.verificar(SIN_ENCABEZADO, self.DATOS) == {
            "fecha": VeredictoDeDato("no_se", "")
        }
        assert len(intentos) == 2
        assert consumo.as_dict()["proveedores"][PROVEEDOR]["rechazos"] == 1

    def test_un_error_que_no_se_reintenta_deja_la_fila_en_duda(self, monkeypatch):
        def urlopen_falso(peticion, timeout=None):
            raise urllib.error.HTTPError(peticion.full_url, 401, "llave mala", {}, None)

        monkeypatch.setattr(modulo_del_juez.urllib.request, "urlopen", urlopen_falso)
        consumo = Consumo()
        assert (
            MistralJuezDeDatos(api_key="x", consumo=consumo).verificar(
                SIN_ENCABEZADO, self.DATOS
            )
            is None
        )
        assert consumo.as_dict()["fallos"] == 1


# -- api: la muestra de filas de una corrida --------------------------------------------


@pytest.fixture
def margen_de_fabrica(monkeypatch):
    """Los márgenes de los perfiles, sin lo que diga el entorno de quien corre las pruebas."""
    for nombre in list(os.environ):
        if nombre.startswith("BOTPDF_MARGEN_ACEPTABLE"):
            monkeypatch.delenv(nombre)


def _papel_de_la_sesion(numero: int) -> list[str]:
    return [
        f"ACTA ORDINARIA No. {numero:03d}\nFECHA: Lunes 17 de diciembre de 2012\nHORA: 8:00 a.m.\n"
        "LUGAR: Decanatura de la Facultad\nPresidió la Decana Luisa Arévalo Tovar.",
        f"Acta No. {numero:03d}-2012\nSe levanta la sesión.",
    ]


def _fila_de_la_sesion(numero: int, *, dice: int | None = None) -> dict:
    """La fila de la sesión ``numero``, en sus páginas 2n-1 y 2n; ``dice`` es otro número leído mal."""
    leido = f"{dice if dice is not None else numero:03d}"
    return _acta(
        archivo="1N°22.pdf",
        acta=f"ACTA ORDINARIA No. {leido}",
        numero=leido,
        pagina_inicial=2 * numero - 1,
        pagina_final=2 * numero,
        resumen="Presidió la Decana Luisa Arévalo Tovar.",
    )


def _entrega(
    relativa: str,
    filas: list[dict],
    *,
    habilidad="actas de consejo",
    vigencia=Vigencia.VIGENTE,
):
    constancia = Constancia(
        origen=relativa,
        tamano=1024,
        modificado_ns=1,
        estado=EstadoDeEntrega.COMPLETA,
        habilidad=habilidad,
        actas=filas,
    )
    return EntregaVista(
        path=Path("C:/origen") / relativa,
        relativa=relativa,
        vigencia=vigencia,
        constancia=constancia,
        base=None,
        motivo="",
    )


def _libros(
    cuantos_pdf: int, *, actas_por_libro: int = 10, malas: frozenset[int] = frozenset()
) -> list[EntregaVista]:
    """Libros de actas de la caja 00C003284: en cada uno, la sesión ``n`` en sus páginas 2n-1 y 2n."""
    return [
        _entrega(
            f"00C003284/UPD{3859771 + k}/LIBRO.pdf",
            [
                _fila_de_la_sesion(n, dice=n + 50 if n in malas else None)
                for n in range(1, actas_por_libro + 1)
            ],
        )
        for k in range(cuantos_pdf)
    ]


def _leer_actas(
    origen: Path, tramos: list[tuple[int, int]]
) -> list[tuple[list[str], int]]:
    """El texto de cada tramo, como lo daría la capa del libro: la sesión que abre en su primera página."""
    return [(_papel_de_la_sesion((desde + 1) // 2), 0) for desde, _hasta in tramos]


class TestLasFilasCandidatas:
    def test_salen_de_la_constancia_con_su_nombre_en_la_muestra(self):
        entrega = _entrega(
            "00C003284/UPD3859771/1N°22.pdf", [_acta(pagina_inicial=1, pagina_final=22)]
        )
        candidatas = filas_candidatas([entrega])
        assert list(candidatas) == [
            "00C003284/UPD3859771/1N°22.pdf · págs. 1-22 · acta 022"
        ]
        vista, fila = candidatas["00C003284/UPD3859771/1N°22.pdf · págs. 1-22 · acta 022"]
        assert vista is entrega and fila["numero"] == "022"

    def test_ni_las_entregas_que_no_estan_vigentes_ni_las_filas_sin_paginas(self):
        incompleta = _entrega("caja/UPD1.pdf", [_acta()], vigencia=Vigencia.INCOMPLETA)
        sin_paginas = _entrega(
            "caja/UPD2.pdf", [_acta(pagina_inicial=0), "no es una fila", _acta()]
        )
        candidatas = filas_candidatas([incompleta, sin_paginas])
        assert list(candidatas) == ["caja/UPD2.pdf · págs. 1-2 · acta 022"]

    def test_dos_filas_con_el_mismo_nombre_no_se_pisan(self):
        entrega = _entrega("caja/UPD1.pdf", [_acta(), _acta()])
        assert list(filas_candidatas([entrega])) == [
            "caja/UPD1.pdf · págs. 1-2 · acta 022",
            "caja/UPD1.pdf · págs. 1-2 · acta 022 #2",
        ]


@pytest.mark.usefixtures("margen_de_fabrica")
class TestLaMuestraDeFilas:
    def test_de_ciento_cincuenta_filas_se_revisan_cien(self):
        muestra = auditar_las_filas(
            None, None, _libros(15), semilla=20261109, leer_textos=_leer_actas
        )
        assert muestra["unidad"] == UNIDAD_FILAS
        assert (muestra["candidatos"], muestra["revisados"], muestra["bien"]) == (
            150,
            100,
            100,
        )
        assert (muestra["errores"], muestra["dudosos"], muestra["no_auditados"]) == (
            0,
            0,
            0,
        )
        assert muestra["ampliada"] is False
        assert muestra["preguntadas_a_la_ia"] == 0
        assert muestra["margen"]["dictamen"] == DENTRO_DEL_MARGEN
        assert len(muestra["pdfs"]) == 100
        primero = muestra["pdfs"][0]
        assert " · págs. " in primero["pdf"] and " · acta " in primero["pdf"]
        assert (
            primero["costuras"],
            primero["archivos"],
            primero["dentro_del_margen"],
        ) == (0, 0, 0)
        assert primero["paginas"] == 2
        assert primero["habilidad"] == "actas de consejo"

    def test_la_misma_semilla_da_las_mismas_filas(self):
        libros = _libros(15)
        una = auditar_las_filas(None, None, libros, semilla=7, leer_textos=_leer_actas)
        otra = auditar_las_filas(
            None, None, list(reversed(libros)), semilla=7, leer_textos=_leer_actas
        )
        distinta = auditar_las_filas(
            None, None, libros, semilla=8, leer_textos=_leer_actas
        )
        nombres = sorted(p["pdf"] for p in una["pdfs"])
        assert nombres == sorted(p["pdf"] for p in otra["pdfs"])
        assert nombres != sorted(p["pdf"] for p in distinta["pdfs"])
        assert una["semilla"] == 7

    def test_con_errores_se_revisan_otras_cien_sin_repetir(self):
        # La sesión 5 de cada libro se inventarió con el número de otra: un error de cada diez.
        muestra = auditar_las_filas(
            None,
            None,
            _libros(25, malas=frozenset({5})),
            semilla=3,
            leer_textos=_leer_actas,
        )
        assert muestra["ampliada"] is True
        assert muestra["revisados"] == 200
        nombres = [p["pdf"] for p in muestra["pdfs"]]
        assert len(set(nombres)) == 200
        assert (
            muestra["errores"]
            == sum(1 for p in muestra["pdfs"] if p["estado"] == ERROR)
            > 0
        )
        mala = next(p for p in muestra["pdfs"] if p["estado"] == ERROR)
        assert mala["hallazgos"] == ["el acta dice No. 005 y la fila No. 055"]
        assert muestra["margen"]["dictamen"] != DENTRO_DEL_MARGEN

    def test_sin_errores_no_se_amplia(self):
        muestra = auditar_las_filas(
            None, None, _libros(25), semilla=3, leer_textos=_leer_actas
        )
        assert muestra["ampliada"] is False and muestra["revisados"] == 100

    def test_cada_habilidad_contra_el_margen_de_su_perfil(self, monkeypatch):
        # Las actas aceptan el 8 %; las historias, el de fábrica. La muestra se
        # juzga con el más estricto y cada habilidad con el suyo.
        monkeypatch.setenv("BOTPDF_MARGEN_ACEPTABLE_ACTAS_DE_CONSEJO", "8")
        historias = _entrega(
            "00C003286/UPD1/HISTORIAS.pdf",
            [
                {
                    "tipo": "HISTORIA ACADEMICA",
                    "nombre": "MARIA FERNANDA PEREZ GOMEZ",
                    "cedula": "45466499",
                    "pagina_inicial": 1,
                    "pagina_final": 1,
                }
            ],
            habilidad="historias academicas",
        )
        libros = _libros(2)

        def leer(origen, tramos):
            if origen == historias.path:
                return [([FICHA], 0) for _ in tramos]
            return _leer_actas(origen, tramos)

        muestra = auditar_las_filas(
            None, None, [*libros, historias], semilla=1, leer_textos=leer
        )
        por_clave = {h["clave"]: h for h in muestra["por_habilidad"]}
        assert set(por_clave) == {"actas-de-consejo", "historias"}
        assert por_clave["actas-de-consejo"]["revisados"] == 20
        assert por_clave["actas-de-consejo"]["margen"]["aceptable"] == pytest.approx(0.08)
        assert por_clave["historias"]["revisados"] == 1
        assert por_clave["historias"]["margen"]["aceptable"] == pytest.approx(
            perfil_de("historias").margen
        )
        assert muestra["margen"]["aceptable"] == pytest.approx(
            min(0.08, perfil_de("historias").margen)
        )

    def test_un_original_que_no_se_abre_no_se_audita_y_no_tumba_la_corrida(self):
        def roto(origen, tramos):
            raise OSError("el recurso de red no responde")

        muestra = auditar_las_filas(None, None, _libros(15), semilla=1, leer_textos=roto)
        assert muestra["no_auditados"] == 100
        assert muestra["revisados"] == 0
        assert muestra["ampliada"] is False
        assert all(p["estado"] == NO_AUDITADO for p in muestra["pdfs"])
        assert muestra["pdfs"][0]["hallazgos"] == [
            "no se pudo abrir su PDF: el recurso de red no responde"
        ]
        # Una muestra vacía no se juzga: nunca «menos del 0 %».
        assert muestra["margen"]["dictamen"] == SIN_CERTEZA
        assert "0 %" not in muestra["margen"]["texto"]

    def test_detenida_no_audita(self):
        muestra = auditar_las_filas(
            None,
            None,
            _libros(2),
            semilla=1,
            leer_textos=_leer_actas,
            detener=lambda: True,
        )
        assert muestra["no_auditados"] == 20 and muestra["revisados"] == 0

    def test_con_el_tiempo_acabado_no_se_traba_y_lo_que_falta_no_se_audita(self):
        """El operador, 2026-11-09: «que todo esté optimizado y el flujo no se trabe».

        Un original lento -- la red, Tesseract -- no deja la corrida esperando:
        al acabarse el tiempo, lo que falta queda «no auditado», no cuenta para
        el margen, no hay segunda ronda y la IA ya no se pregunta.
        """
        import time

        preguntas = []

        class Juez:
            def verificar(self, texto, datos):
                preguntas.append(datos)
                return {}

        def lento(origen, tramos):
            time.sleep(0.2)
            return _leer_actas(origen, tramos)

        empezo = time.monotonic()
        muestra = auditar_las_filas(
            None, None, _libros(15), semilla=1, leer_textos=lento, juez=Juez(), tiempo_maximo=0.05
        )
        assert time.monotonic() - empezo < 5
        assert muestra["no_auditados"] > 0
        assert any(
            "se acabó el tiempo de la auditoría" in h for p in muestra["pdfs"] for h in p["hallazgos"]
        )
        assert muestra["ampliada"] is False
        assert muestra["revisados"] + muestra["no_auditados"] == len(muestra["pdfs"])

    def test_el_avance_se_cuenta_fila_por_fila(self):
        vistos = []
        auditar_las_filas(
            None,
            None,
            _libros(2),
            semilla=1,
            leer_textos=_leer_actas,
            avance=lambda n, r: vistos.append(n),
        )
        assert vistos == list(range(1, 21))

    def test_sin_filas_la_muestra_esta_vacia(self):
        muestra = auditar_las_filas(None, None, [], semilla=1, leer_textos=_leer_actas)
        assert (muestra["candidatos"], muestra["revisados"], muestra["pdfs"]) == (
            0,
            0,
            [],
        )
        assert etapa_de(None, muestra) == ("Terminado", "")


class TestLaEtapaConFilas:
    def _muestra(self, **cambios) -> dict:
        muestra = {
            "revisados": 100,
            "bien": 97,
            "errores": 0,
            "dudosos": 3,
            "margen": margen_de_error(0, 100).as_dict(),
            "por_habilidad": [],
        }
        muestra.update(cambios)
        return muestra

    def test_dice_que_la_muestra_es_de_filas(self):
        etapa, detalle = etapa_de(None, self._muestra(unidad=UNIDAD_FILAS))
        assert etapa == "Terminado"
        assert "muestra: 97 de 100 filas bien" in detalle
        assert "dentro del margen aceptable (5 %)" in detalle

    def test_sin_unidad_es_de_pdf_como_siempre(self):
        _, detalle = etapa_de(None, self._muestra())
        assert "muestra: 97 de 100 bien" in detalle and "filas" not in detalle

    def test_una_muestra_sin_revisados_no_se_anuncia(self):
        _, detalle = etapa_de(
            None,
            self._muestra(
                unidad=UNIDAD_FILAS,
                revisados=0,
                bien=0,
                margen=margen_de_error(0, 0).as_dict(),
            ),
        )
        assert "muestra" not in detalle


class TestLoQueCazoLaSegundaRevision:
    """La segunda revisión (2026-11-09) alteró a propósito 1.361 datos de 104 actas reales de
    Odontología y midió lo que pasaba sin verse. Cada caso, fijado."""

    def test_una_sesion_no_la_confirma_cualquier_cita(self):
        from resolutions.application.auditoria_de_filas import cita_con_el_dato
        from resolutions.domain.auditoria_de_filas import Pregunta

        pregunta = Pregunta("sesion", "EXTRAORDINARIA", "")
        assert not cita_con_el_dato(pregunta, "LISTA DE ASISTENCIA")
        assert cita_con_el_dato(pregunta, "ACTA EXTRAORDINARIA No. 012")
        # «ORDINARIA» va dentro de «EXTRAORDINARIA»: no la confirma.
        assert not cita_con_el_dato(Pregunta("sesion", "ORDINARIA", ""), "ACTA EXTRAORDINARIA No. 012")

    def test_el_numero_del_acta_va_tras_su_rotulo(self):
        from resolutions.application.auditoria_de_filas import cita_con_el_dato
        from resolutions.domain.auditoria_de_filas import Pregunta

        pregunta = Pregunta("numero", "007", "")
        for suelta in ("07:30 HORAS", "Resolución No. 07", "3. PROPOSICIONES O VARIOS. 7"):
            assert not cita_con_el_dato(pregunta, suelta), suelta
        assert cita_con_el_dato(pregunta, "ACTA No. 007")
        assert cita_con_el_dato(pregunta, "sesión número siete (07)")

    def test_la_fecha_de_un_anexo_no_confirma_la_del_acta(self):
        from resolutions.application.auditoria_de_filas import cita_con_el_dato
        from resolutions.domain.auditoria_de_filas import Pregunta

        apertura = APERTURA_022
        pregunta = Pregunta("fecha", "17/12/2012", "")
        assert cita_con_el_dato(pregunta, "17 de diciembre de 2012", apertura=apertura)
        assert not cita_con_el_dato(pregunta, "FECHA: LUNES 17 DE DICIEMBRE DE 2012 citación", apertura=apertura)

    def test_otra_fecha_de_la_hoja_de_apertura_no_confirma(self):
        papel = APERTURA_022.replace(
            "ORDEN DEL DÍA", "Se informa la resolución de fecha 18 de diciembre de 2012.\nORDEN DEL DÍA"
        )
        revision = revisar_la_fila(_acta(fecha="18-12-2012"), [papel, CORRIDA_022])
        assert "la fecha de la sesión" not in revision.confirmados
        assert any(p.campo == "fecha" for p in revision.preguntas)

    def test_la_sesion_que_el_encabezado_no_dice_tambien_se_revisa(self):
        papel = APERTURA_022.replace("ACTA ORDINARIA No. 022", "ACTA No. 022\nSESIÓN ORDINARIA")
        bien = revisar_la_fila(_acta(), [papel, CORRIDA_022])
        assert "la sesión" in bien.confirmados
        invertida = revisar_la_fila(_acta(acta="ACTA EXTRAORDINARIA No. 022"), [papel, CORRIDA_022])
        assert "la sesión" not in invertida.confirmados
        assert any(p.campo == "sesion" for p in invertida.preguntas) or invertida.errores

    def test_el_nombre_de_pila_no_puede_ser_el_que_falta(self):
        texto = "Asistió la doctora Helena Muskus López, jefe del departamento."
        assert nombre_en_el_texto("Helena Muskus López", texto)
        assert not nombre_en_el_texto("Raúl Muskus López", texto)
        assert not nombre_en_el_texto("Katherine Muskus López", texto)


class TestLoQueCazoElRevisorDeRobustez:
    """La segunda revisión de robustez (2026-11-09), con los libros grandes de Odontología."""

    def test_una_muestra_sin_auditar_no_cierra_terminado_sin_mas(self):
        muestra = {"revisados": 0, "candidatos": 72, "bien": 0, "errores": 0, "dudosos": 0,
                   "margen": margen_de_error(0, 0).as_dict(), "por_habilidad": [], "unidad": UNIDAD_FILAS}
        etapa, detalle = etapa_de(None, muestra)
        assert etapa == "Terminado: muestra sin auditar"
        assert "ninguna de 72 se pudo auditar" in detalle
        # La muestra de PDF termina como siempre: lo fija la especificación del 2026-10-28.
        assert etapa_de(None, {**muestra, "unidad": "pdf"})[0] == "Terminado"

    def test_una_muestra_con_dudas_que_pueden_sacarla_del_margen_se_avisa(self):
        margen = margen_de_error(0, 20, dudosos=20, unidad="fila").as_dict()
        muestra = {"revisados": 20, "candidatos": 20, "bien": 0, "errores": 0, "dudosos": 20,
                   "margen": margen, "por_habilidad": [], "unidad": UNIDAD_FILAS}
        assert etapa_de(None, muestra)[0] == "Terminado con dudas en la muestra"

    def test_si_la_ia_falla_no_se_pierde_lo_que_la_regla_ya_probo(self):
        class Roto:
            def verificar(self, texto, datos):
                raise ValueError("choices no es una lista")

        fila = _acta(folio_inicial=9, folio_final=3, acta="ACTA EXTRAORDINARIA No. 022")
        resultado = auditar_una_fila("UPD1.pdf", fila, [APERTURA_022, CORRIDA_022], juez=Roto())
        assert resultado.estado == ERROR
        assert any("folio final 3 es menor" in h for h in resultado.hallazgos)
        assert resultado.preguntadas_a_la_ia == 0

    def test_solo_cuenta_lo_que_la_ia_contesto_citando_el_papel(self):
        juez = _JuezFalso({"otro_campo": VeredictoDeDato("esta", "ACTA ORDINARIA No. 022")})
        resultado = auditar_una_fila("UPD1.pdf · pág. 1 · acta 022", FILA_SIN_ENCABEZADO, [SIN_ENCABEZADO], juez=juez)
        assert resultado.preguntadas_a_la_ia == 0

    def test_las_paginas_que_no_estan_en_el_pdf_se_dicen(self):
        fila = _acta(pagina_inicial=1, pagina_final=4)
        resultado = auditar_una_fila("UPD1.pdf", fila, [APERTURA_022, CORRIDA_022], paginas_pedidas=(1, 4))
        assert "2 de sus 4 páginas no están en el PDF" in resultado.hallazgos

    def test_el_plazo_corto_se_dice_en_segundos(self):
        import time

        def lento(origen, tramos):
            time.sleep(0.2)
            return _leer_actas(origen, tramos)

        muestra = auditar_las_filas(None, None, _libros(15), semilla=1, leer_textos=lento, tiempo_maximo=0.05)
        motivos = {h for p in muestra["pdfs"] for h in p["hallazgos"] if "tiempo" in h}
        assert motivos == {"se acabó el tiempo de la auditoría (0 s)"}

    def test_un_pdf_de_la_red_que_no_baja_se_intenta_una_sola_vez(self, monkeypatch):
        from types import SimpleNamespace

        from resolutions.adapters import red_smb

        intentos = []

        def traer(origen, destino):
            intentos.append(origen)
            raise OSError("el servidor no responde")

        monkeypatch.setattr(red_smb, "por_smb", lambda ruta: True)
        monkeypatch.setattr(red_smb, "traer", traer)
        runner = SimpleNamespace(_settings=SimpleNamespace(ocr_language="spa"))
        muestra = auditar_las_filas(runner, None, _libros(1), semilla=1)
        assert len(intentos) == 1
        assert muestra["no_auditados"] == 10

    def test_una_cita_con_basura_del_ocr_no_prueba_otra_persona(self):
        """«MALRICIO RLBZ» por Mauricio Rivas (acta 05 de 2000-2006): duda, no error."""
        assert parece_del_ocr("Mauricio Rivas", "MALRICIO RLBZ")
        assert not parece_del_ocr("Eduardo Ordóñez Ordoñez", "Dr. EDUARDO ORDOGOITIA Decano")


# -- las fechas extremas de toda fila (el revisor de fechas, 2026-11-10) -----------------------
#
# El operador: «estar muy seguro de cada fecha en cada documento, sin importar la
# habilidad», con los dos agentes, y que los auditores cubran «todas las
# habilidades, todos los documentos, todos los patrones, todo el margen de
# errores». La auditoría de filas contrasta la fecha inicial y la final de toda
# fila con la regla de su habilidad: lo corregido con prueba es error, lo
# dudoso va a la IA en la misma pregunta que los demás datos.

from datetime import date  # noqa: E402

import resolutions.application.auditoria_de_filas as auditoria_de_filas_app  # noqa: E402
from resolutions.domain.auditoria_de_filas import (  # noqa: E402
    Pregunta,
    basura_del_texto,
    texto_legible,
)
from resolutions.domain.fechas_extremas import ANIOS, EXPEDICION  # noqa: E402

#: Una resolución con su fórmula de expedición: la fecha está donde va.
RESOLUCION_EXPEDIDA = (
    "UNIVERSIDAD DE CARTAGENA\nRESOLUCIÓN No. 031 DE 2005\n"
    "Por la cual se reconoce un título. EL RECTOR DE LA UNIVERSIDAD DE CARTAGENA, en uso de sus facultades...\n"
    "RESUELVE: ARTÍCULO PRIMERO: reconocer.\n"
    "Dada en Cartagena de Indias, a los quince (15) días del mes de marzo de 2005."
)


def _resolucion(fecha: str) -> dict:
    return {
        "tipo": "FILA DEL FUID",
        "fuid": {"consecutivo_inicial": "031", "fecha_inicial": fecha, "fecha_final": fecha, "pagina_inicial": 1},
    }


HISTORIA = {"nombre": "MARIA FERNANDA PEREZ GOMEZ", "anio_inicial": "1986", "anio_final": "1991", "pagina_inicial": 1}
FICHA_CON_ANIOS = "Nombre: MARIA FERNANDA PEREZ GOMEZ\nIngresó en 1986. Grado: 1991"


class TestLasFechasDeTodaFila:
    def test_la_fecha_que_dice_la_formula_de_expedicion_se_confirma_una_vez(self):
        revision = revisar_la_fila(_resolucion("15/03/2005"), [RESOLUCION_EXPEDIDA], regla_de_fechas=EXPEDICION)
        # Una sola fecha en las dos puntas: se dice una vez, «la fecha».
        assert revision.confirmados == ("el número del documento", "la fecha")
        assert not revision.preguntas and not revision.errores

    def test_otra_fecha_con_dos_pruebas_del_papel_es_error(self):
        revision = revisar_la_fila(_resolucion("01/02/2005"), [RESOLUCION_EXPEDIDA], regla_de_fechas=EXPEDICION)
        assert revision.errores == (
            "la fecha dice 01/02/2005 y el papel 15/03/2005 (la fórmula de expedición («Dada en…») dice "
            "15/03/2005 y 01/02/2005 no está escrita en el documento)",
        )
        assert not revision.preguntas

    def test_un_digito_del_ocr_es_pregunta_con_lo_que_dice_el_lector(self):
        """El margen de error: 15/03/2006 frente a 15/03/2005 es la lectura, no el papel."""
        revision = revisar_la_fila(_resolucion("15/03/2006"), [RESOLUCION_EXPEDIDA], regla_de_fechas=EXPEDICION)
        assert not revision.errores
        [pregunta] = revision.preguntas
        assert (pregunta.campo, pregunta.valor) == ("fecha_inicial", "15/03/2006")
        assert pregunta.duda == "la fecha 15/03/2006, pero la fórmula de expedición («Dada en…») dice 15/03/2005"
        assert pregunta.dice_el_papel == date(2005, 3, 15)

    def test_sin_lector_fuerte_nunca_corrige_solo_pregunta(self):
        """La regla genérica (los extremos) confirma o pregunta: nunca da por error lo que no sabe leer."""
        revision = revisar_la_fila(_resolucion("01/02/2005"), [RESOLUCION_EXPEDIDA])
        assert not revision.errores
        assert [p.campo for p in revision.preguntas] == ["fecha_inicial"]

    def test_los_anios_de_una_historia(self):
        confirmada = revisar_la_fila(HISTORIA, [FICHA_CON_ANIOS], regla_de_fechas=ANIOS)
        assert {"el nombre", "la fecha inicial", "la fecha final"} == set(confirmada.confirmados)
        sin_el_final = revisar_la_fila(HISTORIA, ["Nombre: MARIA FERNANDA PEREZ GOMEZ\nIngresó en 1986."], regla_de_fechas=ANIOS)
        assert [(p.campo, p.valor, p.duda) for p in sin_el_final.preguntas] == [
            ("fecha_final", "1991", "la fecha final 1991 no está escrita en el documento")
        ]

    def test_la_fila_sin_otra_cosa_que_sus_fechas_tambien_se_audita(self):
        """Antes «la fila no trae datos que buscar en el papel»: no auditada, fuera del margen."""
        fila = {"fecha_inicial": "12/01/2023", "fecha_final": "12/01/2023", "pagina_inicial": 1}
        assert clase_de_la_fila(fila) == "otra"
        resultado = auditar_una_fila("caja/UPD1.pdf · pág. 1", fila, ["Magangué 12 de enero de 2023"])
        assert resultado.estado == BIEN
        assert resultado.extra["confirmados"] == ["la fecha"]
        assert resultado.extra["fechas"] == {"confirmadas": 1}

    def test_la_fecha_tomada_de_otra_parte_no_infla_el_margen(self):
        """Tras la revisión adversarial (2026-11-10): no está en su papel a propósito; ni duda ni IA, sin dato."""
        fila = {
            "fecha_inicial": "12/01/2023",
            "fecha_final": "12/01/2023",
            "pagina_inicial": 1,
            "observaciones": "fecha de su trámite",
        }
        revision = revisar_la_fila(fila, ["Señores: reclamo por el cobro de la factura de energía del mes"])
        assert not revision.preguntas and not revision.errores
        assert any("de su trámite" in s for s in revision.sin_dato)
        juez = _JuezFalso({})
        resultado = auditar_una_fila("UPD1.pdf · pág. 1", fila, ["Señores: reclamo por el cobro"], juez=juez)
        assert resultado.estado == NO_AUDITADO and not juez.preguntas

    def test_la_fecha_fuera_de_los_anios_del_libro_es_duda_sin_la_ia(self):
        """ACOSTA BELLO: 1994-2001 en «HISTORIAS ACADEMICAS 1986»; se veía al procesar y no al cerrar (2026-11-10)."""
        fila = {**HISTORIA, "anio_inicial": "1994", "anio_final": "2001"}
        papel = "Nombre: MARIA FERNANDA PEREZ GOMEZ\nIngresó en 1994. Grado: 2001"
        ventana = auditoria_de_filas_app.ventana_de_la_auditoria("historias", "CAJA/UPD1-HISTORIAS ACADEMICAS 1986.pdf")
        juez = _JuezFalso({})
        resultado = auditar_una_fila("UPD1.pdf", fila, [papel], habilidad="historias", juez=juez, ventana=ventana)
        assert resultado.estado == DUDOSO
        assert any("2001 cae fuera de los años del libro" in h for h in resultado.hallazgos)
        assert not juez.preguntas
        # Sin la ventana, el papel la confirma.
        assert auditar_una_fila("UPD1.pdf", fila, [papel], habilidad="historias").estado == BIEN

    def test_la_ventana_de_la_auditoria_es_la_del_libro_y_mas_ancha(self):
        """Medido en 404 filas de Enfermería (2026-11-10): con la de procesar caían fuera 19; con ésta, 2."""
        ventana = auditoria_de_filas_app.ventana_de_la_auditoria
        assert ventana("historias", "CAJA/UPD3859727-1HISTORIAS ACADEMICAS 1986.pdf") == (1974, 1992)
        assert ventana("historias", "CAJA/UPD1-HISTORIAS ACADEMICAS.pdf") is None
        assert ventana("historias", "UPD1.pdf", ["NOTAS 1980", "1981 1982", "1983 1984 1985", "1986 1987 1988"]) is not None
        assert ventana("nominas", "NOMINA 1977-1984.pdf") == (1976, 1985)
        assert ventana("actas-de-consejo", "ACTAS 2007-2009.pdf") is None

    def test_la_letra_a_mano_deja_sin_dato_lo_que_no_encuentra(self):
        """#10: las 88 filas de Enfermería escritas a mano salían «en duda» sin alterar nada."""
        a_mano = (
            "REGISTRO DEL ESTUDIANTE ¿i/eJuyU /c<úy¿ir/ Nombre del estudiante. ^^y^AjiUAA. 3 2 &0 - <s> "
            "Luga/ A/^'cu y/r> A-S\" ^ B/c At - Ji/é Cy pó í/íP íU i-í J44^ dS4 3a<f Í4í/ ;«*»* 7i^ rwv, "
            "/■■?f/- ¿// - i»W /-gf/ ^JLuccdd^ -tf 17 / ;■ - ■/ 'X -rrtc-i iíjJl í^6~> f^cy ¡O^ ií^"
        )
        assert not texto_legible([a_mano])
        juez = _JuezFalso({})
        resultado = auditar_una_fila("UPD1.pdf · págs. 1-2", HISTORIA, [a_mano], habilidad="historias", juez=juez)
        assert resultado.estado == NO_AUDITADO
        assert "no se dejan leer" in resultado.hallazgos[0]
        assert not juez.preguntas
        # Lo que sí trae, lo confirma igual.
        con_el_nombre = f"{a_mano}\nMARIA FERNANDA PEREZ GOMEZ"
        assert auditar_una_fila("UPD1.pdf", HISTORIA, [con_el_nombre]).extra["confirmados"] == ["el nombre"]

    def test_la_capa_impresa_se_deja_leer(self):
        """Las actas de Odontología, Afinia y Kingspan, con sus códigos, pasan por legibles."""
        assert texto_legible([RESOLUCION_EXPEDIDA, FICHA_CON_ANIOS])
        assert texto_legible(["COMPROBANTE DE EGRESO 001-CEE-00000557 Fecha: 2023/10/14 NIT 802014471 $70.000.000"])
        assert basura_del_texto([""]) == 1.0

    def test_la_fila_sin_fechas_no_dice_nada_de_ellas(self):
        """Las filas sin fechas siguen igual: nada de más en ``sin_dato`` ni en los confirmados."""
        revision = revisar_la_fila(
            {"fuid": {"consecutivo_inicial": "N/A"}}, [RESOLUCION_EXPEDIDA], regla_de_fechas=EXPEDICION
        )
        assert revision.sin_dato == ("el número del documento",)
        assert revisar_la_fila({"tipo": "OTRA"}, [RESOLUCION_EXPEDIDA]).sin_dato == (
            "la fila no trae datos que buscar en el papel",
        )

    def test_el_acta_corregida_por_la_apertura_es_error_sin_otra_pregunta(self):
        """La regla de la sesión, la misma que al procesar: la apertura dice otra y ésta no está escrita."""
        revision = revisar_la_fila(_acta(fecha="05-03-2012"), [APERTURA_022, CORRIDA_022])
        assert revision.errores == (
            "la fecha de la sesión dice 05/03/2012 y el papel 17/12/2012 (la apertura de la sesión dice "
            "17/12/2012 y 05/03/2012 no está escrita en el documento)",
        )
        assert not any(p.campo.startswith("fecha") for p in revision.preguntas)

    def test_el_acta_del_mismo_mes_sigue_siendo_pregunta(self):
        """El 18 por el 17 de diciembre: el mes y el año están escritos, no hay dos pruebas."""
        revision = revisar_la_fila(_acta(fecha="18-12-2012"), [APERTURA_022, CORRIDA_022])
        assert not revision.errores
        assert [p.campo for p in revision.preguntas] == ["fecha"]


class TestLasFechasConLaIa:
    def test_van_en_la_misma_pregunta_que_los_demas_datos(self):
        fila = {**HISTORIA, "cedula": "45466498"}
        papel = "Nombre: MARIA FERNANDA PEREZ GOMEZ\nC.C. 45.466.499\nIngresó en 1986. Grado: mil novecientos noventa y uno"
        juez = _JuezFalso({})
        resultado = auditar_una_fila("UPD1.pdf", fila, [papel], juez=juez)
        # Una pregunta por fila: la cédula y la fecha final juntas, no dos.
        [(_, datos)] = juez.preguntas
        assert datos == [{"campo": "cedula", "valor": "45466498"}, {"campo": "fecha_final", "valor": "1991"}]
        assert resultado.estado == DUDOSO
        assert resultado.extra["fechas"] == {"en duda": 1}

    def test_lo_que_el_papel_confirma_no_se_pregunta(self):
        juez = _JuezFalso({})
        resultado = auditar_una_fila("UPD1.pdf", HISTORIA, [FICHA_CON_ANIOS], juez=juez)
        assert resultado.estado == BIEN and juez.preguntas == []

    def test_la_ia_que_cita_otra_fecha_lo_vuelve_error(self):
        fila = {"fecha_inicial": "12/01/2023", "fecha_final": "12/01/2023", "pagina_inicial": 1}
        papel = "Señores: reclamo.\nMagangué, 30 de agosto de 2021"
        juez = _JuezFalso({"fecha_inicial": VeredictoDeDato("no_esta", "Magangué, 30 de agosto de 2021")})
        resultado = auditar_una_fila("UPD1.pdf", fila, [papel], juez=juez)
        # La misma fecha en las dos puntas se pregunta una vez.
        assert juez.preguntas[0][1] == [{"campo": "fecha_inicial", "valor": "12/01/2023"}]
        assert resultado.estado == ERROR
        assert resultado.hallazgos == (
            "la fecha 12/01/2023 no está escrita en el documento: la IA lo confirma, "
            "el papel dice «Magangué, 30 de agosto de 2021»",
        )
        assert resultado.extra["fechas"] == {"con error": 1}

    def test_un_esta_cuya_cita_no_trae_la_fecha_no_vale(self):
        fila = {"fecha_inicial": "12/01/2023", "fecha_final": "12/01/2023", "pagina_inicial": 1}
        papel = "Señores: reclamo.\nMagangué, 30 de agosto de 2021"
        juez = _JuezFalso({"fecha_inicial": VeredictoDeDato("esta", "Señores: reclamo")})
        assert auditar_una_fila("UPD1.pdf", fila, [papel], juez=juez).estado == DUDOSO

    def test_un_anio_con_un_digito_del_ocr_no_es_error_y_dos_si(self):
        papel = "Nombre: MARIA FERNANDA PEREZ GOMEZ\nIngresó en 1986. Grado en 1997. Libro de 1975"
        del_ocr = _JuezFalso({"fecha_final": VeredictoDeDato("no_esta", "Grado en 1997")})
        resultado = auditar_una_fila("UPD1.pdf", HISTORIA, [papel], juez=del_ocr)
        # 1991 y 1997: un dígito, lo que el OCR cambia: duda, no error.
        assert resultado.estado == DUDOSO
        assert "puede ser el OCR" in resultado.hallazgos[0]
        otro = _JuezFalso({"fecha_final": VeredictoDeDato("no_esta", "Libro de 1975")})
        assert auditar_una_fila("UPD1.pdf", HISTORIA, [papel], juez=otro).estado == ERROR

    def test_la_cita_tiene_que_traer_la_del_lector_de_la_regla(self):
        """La próxima reunión o la fecha de la plantilla no contradicen: si el lector dijo una, la cita trae ésa."""
        lector = date(2005, 3, 15)
        plantilla = Pregunta("fecha_inicial", "01/02/2005", "", lector)
        assert not auditoria_de_filas_app.contradice(plantilla, "VERSIÓN 00 FECHA 04-05-2011")
        assert auditoria_de_filas_app.contradice(plantilla, "a los quince (15) días del mes de marzo de 2005")
        assert auditoria_de_filas_app.cita_con_el_dato(Pregunta("fecha_final", "1991", ""), "Grado: 1.991")
        assert not auditoria_de_filas_app.cita_con_el_dato(Pregunta("fecha_final", "1991", ""), "Grado")

    def test_la_regla_es_la_del_perfil_de_su_habilidad(self, monkeypatch):
        """La de la constancia: con la expedición, la fecha que el papel contradice con prueba es error."""
        monkeypatch.setattr(auditoria_de_filas_app, "regla_de_fechas_de", lambda habilidad: EXPEDICION)
        resultado = auditar_una_fila(
            "UPD1.pdf", _resolucion("01/02/2005"), [RESOLUCION_EXPEDIDA], habilidad="resoluciones"
        )
        assert resultado.estado == ERROR
        assert resultado.hallazgos[0].startswith("la fecha dice 01/02/2005 y el papel 15/03/2005")

    def test_un_perfil_sin_regla_audita_con_la_de_los_extremos(self, monkeypatch):
        from types import SimpleNamespace

        from resolutions.application import perfiles_de_revision

        monkeypatch.setattr(perfiles_de_revision, "perfil_de", lambda habilidad: SimpleNamespace(datos=None))
        assert auditoria_de_filas_app.regla_de_fechas_de("lo que sea") == "extremos"


@pytest.mark.usefixtures("margen_de_fabrica")
class TestLasFechasEnLaMuestraDeFilas:
    def test_la_muestra_dice_como_quedaron_las_fechas_en_total_y_por_habilidad(self):
        muestra = auditar_las_filas(None, None, _libros(2, actas_por_libro=5), semilla=1, leer_textos=_leer_actas)
        # Las diez actas, todas del 17 de diciembre de 2012 como su apertura.
        assert muestra["fechas"] == {
            "documentos": 10,
            "revisados": 10,
            "confirmadas": 10,
            "con error": 0,
            "en duda": 0,
            "sin fechas": 0,
        }
        [suya] = muestra["por_habilidad"]
        assert suya["fechas"]["confirmadas"] == 10

    def test_un_acta_con_otra_fecha_cuenta_como_error_de_la_muestra(self):
        libros = _libros(1, actas_por_libro=3)
        libros[0].constancia.actas[1]["fecha"] = "05-03-2012"
        muestra = auditar_las_filas(None, None, libros, semilla=1, leer_textos=_leer_actas)
        assert (muestra["errores"], muestra["fechas"]["con error"], muestra["fechas"]["confirmadas"]) == (1, 1, 2)
        [mala] = [p for p in muestra["pdfs"] if p["estado"] == ERROR]
        assert mala["hallazgos"][0].startswith("la fecha de la sesión dice 05/03/2012 y el papel 17/12/2012")


# -- que la auditoría no trabe la corrida (2026-11-10) ----------------------------------------
#
# La revisión adversarial del revisor de fechas midió ``_CODIGO`` creciendo al
# cuadrado con una ficha larga sin espacios -- «1» × 12 000 + «x», 2,9 s en
# ``basura_del_texto`` --, las puntas de Kingspan pidiendo la basura de las
# mismas cientos de hojas una vez cada una, y la primera hoja de un acta sin
# encabezado leída con las regex cuadráticas de ``fechas_del_texto``.

import re  # noqa: E402
import time  # noqa: E402

from resolutions.domain import auditoria_de_filas as filas_del_dominio  # noqa: E402


class TestLaAuditoriaDeFilasNoTrabaLaCorrida:
    def test_el_codigo_reconoce_las_mismas_fichas(self):
        """La búsqueda por delante no vuelve atrás; el primer tramo sigue necesitando una cifra."""
        viejo = re.compile(r"[A-Z0-9]*\d[A-Z0-9]*(?:[-/.][A-Z0-9]+)*[.,;:]?")
        fichas = [
            "RE2310202405234", "001-FC-00012345", "UPD3859724;", "001-CEE-00000557", "ABC", "AB-1", "1-AB",
            "A1.B2.", "X1Y", "x1", "1.", "1..", "-1", "1/2/3", "1-", "A-1", "2023/10/14", "NIT802014471",
            "1" * 300 + "x", "1A" * 50 + "!", "1" * 300, "Ñ1", "1,", "1;:", "ABC-",
        ]
        for ficha in fichas:
            assert bool(filas_del_dominio._CODIGO.fullmatch(ficha)) == bool(viejo.fullmatch(ficha)), ficha

    def test_una_ficha_de_200_000_cifras_no_traba_la_basura(self):
        """«1» × 12 000 + «x» tardaba 2,9 s y crecía al cuadrado: 200 000 eran minutos."""
        inicio = time.perf_counter()
        assert basura_del_texto(["1" * 200_000 + "x"]) == 1.0
        assert time.perf_counter() - inicio < 3.0

    def test_la_basura_de_un_documento_se_cuenta_una_vez(self):
        """Cada punta de Kingspan contra todo el original la pedía de las mismas hojas."""
        hojas = [f"COMPROBANTE DE EGRESO 001-CEE-{p:08d} pago a proveedores" for p in range(1, 41)]
        cuenta = filas_del_dominio._basura
        cuenta.cache_clear()
        primera = basura_del_texto(hojas)
        for _ in range(3):
            assert texto_legible(list(hojas)) and basura_del_texto(tuple(hojas)) == primera
        assert (cuenta.cache_info().misses, cuenta.cache_info().hits) == (1, 6)

    def test_la_primera_hoja_de_un_acta_sin_encabezado_no_traba_su_apertura(self):
        """Sin encabezado, la apertura es la primera fecha de la primera hoja: «y » × 10 000 en ella pasaba de 5 s."""
        from resolutions.domain.acta_consejo import primera_fecha

        hoja = "Cartagena, 17 de diciembre de 2012\nSe reunió el Consejo de Facultad. Próxima: 6 de marzo de 2013"
        apertura = filas_del_dominio.fechas_de_la_apertura
        assert apertura([hoja], []) == {primera_fecha(hoja)} == {date(2012, 12, 17)}
        inicio = time.perf_counter()
        assert apertura(["y " * 100_000 + "\n" + hoja], []) == {date(2012, 12, 17)}
        assert time.perf_counter() - inicio < 3.0
