"""Ninguna celda del inventario se entrega vacía sin haberlo intentado todo.

El operador revisó el Excel general y encontró fechas, números y folios en
blanco que el papel sí traía. Esto fija lo que el bot hace antes de entregar:
volver al papel con la tinta realzada, razonar con las actas vecinas -- el año
mal leído, la fecha y el número de la misma ceremonia, el día que el
encabezado no trae --, reconocer las constancias que copian actas antiguas,
pedir otra vez lo que el proveedor no atendió por saturado, y decir el porqué
de lo que de verdad falta. Ninguna prueba llama a un proveedor de pago.
"""

from __future__ import annotations

import io
import urllib.error
from concurrent.futures import Future
from datetime import date

import pytest
from test_acta_consejo import ENCABEZADO, Fuente, hoja

from resolutions.application.acta_consejo import (
    CONSEJO,
    GRADO,
    InventariarActa,
    _es_pasajero,
    explicar_lo_que_falta,
    validar_inventario,
)
from resolutions.application.ports import OcrResult, ResumenNoDisponible
from resolutions.domain.acta_grado import constancia, fecha_de_grado
from resolutions.domain.razonamiento import (
    corregir_anio,
    igual_a_los_lados,
    mes_y_anio,
    mismo_numero,
)

ACTA_DE_GRADO = (
    "ACTA DE GRADO No. {numero}\nEn la ciudad de Cartagena, a los cuatro (4) días del mes "
    "de abril de mil novecientos noventa y siete (1.997), se realizó la graduación colectiva\n"
    "el título de ESPECIALISTA EN SALUD OCUPACIONAL al estudiante {nombre}\n"
    "portador de la cédula de ciudadanía No. {cedula} expedida en Cartagena"
)
#: La misma hoja con el día y el año en gris claro: la primera lectura no los ve.
SIN_FECHA = (
    "ACTA DE GRADO No. {numero}\nEn la ciudad de Cartagena, a los días del mes "
    "de de mil novecientos , se realizó la graduación colectiva\n"
    "el título de ESPECIALISTA EN SALUD OCUPACIONAL al estudiante {nombre}\n"
    "portador de la cédula de ciudadanía No. {cedula} expedida en Cartagena"
)


def _grado(numero, nombre, cedula, *, con_fecha=True):
    plantilla = ACTA_DE_GRADO if con_fecha else SIN_FECHA
    return plantilla.format(numero=numero, nombre=nombre, cedula=cedula)


class TestRazonarConLasVecinas:
    def test_el_anio_de_una_cifra_mal_leida(self):
        vecinas = [date(1997, 4, 4), date(1997, 4, 4), date(1997, 5, 23)]
        assert corregir_anio(date(1927, 4, 4), vecinas) == date(1997, 4, 4)

    def test_la_misma_ceremonia_a_los_dos_lados(self):
        assert corregir_anio(
            date(1977, 4, 4), [date(1997, 4, 4)], a_los_lados=date(1997, 4, 4)
        ) == date(1997, 4, 4)

    def test_con_vecinas_de_anios_distintos_no_se_elige(self):
        # El 14-12 de 1981 y el de 1982: no hay forma de saber cuál era.
        vecinas = [date(1981, 12, 14), date(1981, 12, 14), date(1982, 12, 14), date(1983, 12, 14)]
        assert corregir_anio(date(1947, 12, 14), vecinas) is None

    def test_igual_a_los_lados_exige_las_dos_vecinas(self):
        assert igual_a_los_lados(["03", None, "03"], 1) == "03"
        assert igual_a_los_lados(["03", None, "04"], 1) is None
        assert igual_a_los_lados([None, None, "03"], 1) is None

    def test_el_mismo_numero_con_y_sin_ceros(self):
        assert mismo_numero("03", "3")
        assert not mismo_numero("03", "04")
        assert not mismo_numero(None, "03")

    def test_el_mes_y_el_anio_de_un_encabezado_sin_dia(self):
        assert mes_y_anio("ACTA CONSEJO DE FACULTAD ORDINARIO No. 017\nDiciembre de 2006") == (12, 2006)
        assert mes_y_anio("ACTA No. 017 sin fecha") is None


class TestLasConstancias:
    COPIA = (
        "LA SUSCRITA SECRETARIA ACADEMICA DE LA FACULTAD DE ENFERMERIA\nHACE CONSTAR:\n"
        "Que en el Libro de Actas de Grado de la Facultad de Enfermería aparece el Acta Nº 55 "
        "bajo el folio 110 que a la letra dice: En la ciudad de Cartagena a los 23 días del mes "
        "de Marzo de 1,961 se reunió el Consejo Examinador ... a la Señorita ESPERANZA VIANA "
        "SILVA. - Este Jurado estaba integrado por ... la Srita. GRACIELA PICOT C., Secretaria ... "
        "Es fiel copia de su original expedida en Cartagena a los quince (15) días del mes de "
        "Septiembre de 1.981."
    )

    def test_el_anio_con_coma(self):
        assert fecha_de_grado("a los 23 días del mes de Marzo de 1,961") == date(1961, 3, 23)

    def test_numero_nombre_y_las_dos_fechas(self):
        hecha = constancia(self.COPIA)
        assert hecha is not None
        assert (hecha.numero, hecha.nombre) == ("55", "ESPERANZA VIANA SILVA")
        assert hecha.expedida == date(1981, 9, 15)
        assert hecha.del_acta == date(1961, 3, 23)
        assert not hecha.colectiva

    def test_quien_preside_no_es_la_graduada(self):
        texto = self.COPIA.replace(
            "a la Señorita ESPERANZA VIANA SILVA. -", "presidido por la Srita. VILMA MERCADO V.DECANA de la Facultad, a la Señorita ESPERANZA VIANA SILVA. -"
        )
        assert constancia(texto).nombre == "ESPERANZA VIANA SILVA"

    def test_una_colectiva_no_inventa_un_nombre(self):
        texto = self.COPIA.replace(
            "a la Señorita ESPERANZA VIANA SILVA.", "a las ocho (8) señoritas de la promoción."
        )
        assert constancia(texto).colectiva

    def test_un_acta_no_es_una_constancia(self):
        assert constancia(_grado("05", "ANA RUIZ", "45366705")) is None

    def test_la_fila_dice_que_no_trae_cedula_ni_titulo(self):
        outcome = InventariarActa(perfil=GRADO).execute(Fuente([self.COPIA]), document_name="x.pdf")
        fila = outcome.filas[0]
        assert (fila.numero, fila.nombre, fila.fecha) == ("55", "ESPERANZA VIANA SILVA", "15-09-1981")
        assert "la constancia no trae la cédula" in fila.observaciones
        assert "copia el acta Nº 55 del 23-03-1961" in fila.observaciones


class _TintaClara:
    """Una relectura que sí ve lo que la primera no: la hoja completa."""

    def __init__(self, completas: dict[str, str]):
        self.completas = completas
        self.leidas = 0

    def read(self, imagen):
        self.leidas += 1
        return OcrResult(text=self.completas.get(imagen.decode(), ""))


class _FuentePorPagina(Fuente):
    """Cada página se rasteriza como su número, para saber cuál se releyó."""

    def render(self, numero, band=None, dpi=200):
        return str(numero).encode()


class TestVolverAlPapel:
    def test_la_tinta_realzada_llena_lo_que_faltaba_y_lo_dice(self):
        paginas = [
            _grado("06", "ANA RUIZ", "45366705"),
            _grado("06", "LUIS PEREZ", "73081842", con_fecha=False),
            _grado("06", "EVA DIAZ", "33149632"),
        ]
        relectura = _TintaClara({"2": _grado("06", "LUIS PEREZ", "73081842")})
        outcome = InventariarActa(perfil=GRADO, lectores_de_tinta_clara=(relectura,)).execute(
            _FuentePorPagina(paginas), document_name="libro.pdf"
        )
        segunda = outcome.filas[1]
        assert segunda.fecha == "04-04-1997"
        assert "la fecha se leyó en una segunda lectura de la hoja con la tinta realzada" in (
            segunda.observaciones
        )
        assert relectura.leidas == 1  # sólo la que lo necesitaba

    def test_sin_relectura_la_fecha_es_la_de_su_ceremonia(self):
        paginas = [
            _grado("06", "ANA RUIZ", "45366705"),
            _grado("06", "LUIS PEREZ", "73081842", con_fecha=False),
            _grado("06", "EVA DIAZ", "33149632"),
        ]
        outcome = InventariarActa(perfil=GRADO).execute(Fuente(paginas), document_name="libro.pdf")
        segunda = outcome.filas[1]
        assert segunda.fecha == "04-04-1997"
        assert "es la de su ceremonia (04-04-1997)" in segunda.observaciones

    def test_el_numero_de_la_ceremonia(self):
        paginas = [
            _grado("03", "ANA RUIZ", "45366705"),
            _grado("03", "LUIS PEREZ", "73081842").replace("ACTA DE GRADO No. 03", "ACTA DE GRADO"),
            _grado("03", "EVA DIAZ", "33149632"),
        ]
        outcome = InventariarActa(perfil=GRADO).execute(Fuente(paginas), document_name="libro.pdf")
        assert outcome.filas[1].numero == "03"
        assert "es el de su ceremonia (No. 03)" in outcome.filas[1].observaciones

    def test_con_vecinas_que_no_coinciden_no_se_deduce(self):
        paginas = [
            _grado("03", "ANA RUIZ", "45366705"),
            _grado("03", "LUIS PEREZ", "73081842").replace("ACTA DE GRADO No. 03", "ACTA DE GRADO"),
            _grado("04", "EVA DIAZ", "33149632"),
        ]
        outcome = InventariarActa(perfil=GRADO).execute(Fuente(paginas), document_name="libro.pdf")
        assert outcome.filas[1].numero == ""
        assert "no se pudo leer el número del acta" in outcome.filas[1].observaciones


class TestLaFechaDelConsejo:
    def _acta(self, cabeza):
        return [hoja(cabeza), hoja("Acta No. 017\nSe aprobó el calendario.")]

    def test_mes_y_anio_sin_dia(self):
        cabeza = "ACTA ORDINARIA No. 017\nCONSEJO DE FACULTAD\nDiciembre de 2006\n07:00 HORAS"
        outcome = InventariarActa(perfil=CONSEJO).execute(Fuente(self._acta(cabeza)), document_name="x.pdf")
        fila = outcome.filas[0]
        assert fila.fecha == "12-2006"
        assert "sólo dice el mes y el año" in fila.observaciones
        assert "no se encontró la fecha" not in fila.observaciones

    def test_el_campo_fecha_en_blanco(self):
        cabeza = "ACTA ORDINARIA No. 007\nCONSEJO DE FACULTAD\nFECHA:\nHORA:\n07:00 HORAS"
        outcome = InventariarActa(perfil=CONSEJO).execute(Fuente(self._acta(cabeza)), document_name="x.pdf")
        fila = outcome.filas[0]
        assert fila.fecha == "N/A"
        assert "«FECHA:» en blanco" in fila.observaciones

    def test_falta_la_primera_hoja(self):
        cabeza = "Pagina 02\nACTA ORDINARIA No. 018\nSe ha tenido un atraso en otras actividades"
        outcome = InventariarActa(perfil=CONSEJO).execute(Fuente(self._acta(cabeza)), document_name="x.pdf")
        assert "falta la primera hoja del acta en el escaneo" in outcome.filas[0].observaciones


class _ResumidorSaturado:
    """Contesta 429 la primera vez y resume la segunda."""

    def __init__(self):
        self.pedidos = 0

    def resumir(self, texto):
        self.pedidos += 1
        if self.pedidos == 1:
            raise ResumenNoDisponible("Mistral siguió sin atender (HTTP 429) tras 3 reintentos")
        return "Sesionó el consejo y aprobó el calendario."


class TestLoQueElProveedorNoAtendio:
    def test_un_429_se_pide_otra_vez_al_final(self):
        resumidor = _ResumidorSaturado()
        outcome = InventariarActa(
            perfil=CONSEJO, resumidor=resumidor, espera_para_reintentar=0
        ).execute(Fuente([ENCABEZADO, hoja("Se aprobó el calendario académico del semestre.")]), document_name="x.pdf")
        assert resumidor.pedidos == 2
        assert outcome.filas[0].resumen.startswith("Sesionó el consejo")

    def test_lo_pasajero_y_lo_que_no(self):
        assert _es_pasajero("Mistral siguió sin atender (HTTP 429) tras 3 reintentos")
        assert _es_pasajero("Mistral no respondió (timed out)")
        assert not _es_pasajero("la cuenta de Mistral no tiene saldo (HTTP 402)")
        assert not _es_pasajero(None)


class TestElControlDeCalidadDelInventario:
    def _fila(self, **cambios):
        base = {
            "tipo": "ACTA DE GRADO",
            "numero": "03",
            "fecha": "10-09-1999",
            "nombre": "ANA RUIZ",
            "titulo": "ENFERMERA",
            "cedula": "45366705",
            "observaciones": "",
            "pagina_inicial": 7,
            "pagina_final": 8,
        }
        return {**base, **cambios}

    def test_lo_que_falta_sin_porque_se_dice(self):
        fila = explicar_lo_que_falta(self._fila(cedula="N/A"))
        assert fila["observaciones"] == (
            "no se encontró la cédula en las páginas 7 a 8 del PDF: revíselo en el papel"
        )

    def test_lo_ya_explicado_no_se_repite(self):
        fila = explicar_lo_que_falta(self._fila(cedula="", observaciones="no se pudo leer la cédula"))
        assert fila["observaciones"] == "no se pudo leer la cédula"

    def test_la_ceremonia_no_cuenta(self):
        fila = explicar_lo_que_falta(self._fila(tipo="CEREMONIA DE GRADO", nombre=""))
        assert fila["observaciones"] == ""

    def test_el_resumen_de_la_validacion(self):
        filas = [
            self._fila(),
            self._fila(fecha="N/A", observaciones="no se pudo leer la fecha del grado"),
            self._fila(observaciones="la fecha no se pudo leer y es la de su ceremonia (10-09-1999)"),
            self._fila(tipo="CEREMONIA DE GRADO"),
        ]
        assert validar_inventario(filas) == {
            "filas": 3,
            "completas": 2,
            "razonadas": 1,
            "pendientes": 1,
            "por_dato": {"la fecha": 1},
            "nombres_dudosos": 0,
        }


class TestLaTintaRealzada:
    def test_el_umbral_pasa_lo_gris_a_negro(self):
        pytest.importorskip("PIL")
        from PIL import Image

        from resolutions.adapters.tesseract_ocr import TesseractConfig, TesseractOcr

        gris = Image.new("L", (4, 1), 255)
        gris.putpixel((0, 0), 200)  # tinta clara
        salida = io.BytesIO()
        gris.save(salida, "PNG")
        lector = TesseractOcr(TesseractConfig(umbral=220, autocontrast=False))
        preparada = lector._prepare(salida.getvalue())
        assert preparada.getpixel((0, 0)) == 0
        assert preparada.getpixel((1, 0)) == 255


def test_un_futuro_es_un_futuro():
    # Ancla de importaciones de la prueba del 429: el tipo existe.
    assert Future and urllib.error
