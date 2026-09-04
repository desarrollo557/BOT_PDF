"""Lecturas comprobadas a mano, que sustituyen a las del OCR.

Existen porque hay daño que no se puede reparar leyendo: "ELI2ABETH" pudo ser
ELIZABETH y el texto no lo demuestra. Alguien abre la página, lee el papel y
deja anotada su lectura; lo que se comprueba aquí es que esa anotación llegue
al inventario y que no arrastre consigo el aviso que ya no corresponde.
"""

import json

from resolutions.application import verified_readings
from resolutions.domain.diploma import DiplomaRecord

LIBRO = "6.3858084 REGISTRO DE DIPLOMAS N°08 2012-2013.pdf"

DAÑADO = DiplomaRecord(
    page_number=265,
    folio="595",
    registered_folio="595",
    book="8",
    name="ELI2ABETH MIRANDA GUERRA",
    degree="ESPECIALISTA EN GERENCIA EN SALUD",
    graduation_date="19/04/2013",
    warnings=["el nombre trae un carácter que no es una letra: ELI2ABETH MIRANDA GUERRA"],
)


def archivo(tmp_path, entradas):
    ruta = tmp_path / "verificaciones.json"
    ruta.write_text(json.dumps(entradas, ensure_ascii=False), encoding="utf-8")
    return ruta


class TestLectura:
    def test_un_archivo_ausente_no_es_un_error(self, tmp_path):
        assert verified_readings.load(tmp_path / "no-existe.json") == []

    def test_lee_las_entradas(self, tmp_path):
        ruta = archivo(tmp_path, [
            {"document": LIBRO, "page": 265, "name": "ELIZABETH MIRANDA GUERRA"}
        ])
        lecturas = verified_readings.load(ruta)
        assert lecturas[0].key == (LIBRO, 265)
        assert lecturas[0].values == {"name": "ELIZABETH MIRANDA GUERRA"}

    def test_descarta_una_entrada_sin_ningun_campo(self, tmp_path):
        ruta = archivo(tmp_path, [{"document": LIBRO, "page": 265, "name": ""}])
        assert verified_readings.load(ruta) == []

    def test_ignora_las_claves_que_no_son_campos_del_registro(self, tmp_path):
        ruta = archivo(tmp_path, [
            {"document": LIBRO, "page": 265, "name": "ALGUIEN", "inventado": "x"}
        ])
        assert verified_readings.load(ruta)[0].values == {"name": "ALGUIEN"}


class TestAplicacion:
    def test_sustituye_lo_que_leyo_la_maquina(self):
        lectura = verified_readings.VerifiedReading(
            document=LIBRO, page_number=265, values={"name": "ELIZABETH MIRANDA GUERRA"}
        )
        registros, corregidas = verified_readings.apply(
            [DAÑADO], [lectura], document=LIBRO
        )
        assert registros[0].name == "ELIZABETH MIRANDA GUERRA"
        assert corregidas == [265]

    def test_retira_el_aviso_que_ya_no_corresponde(self):
        lectura = verified_readings.VerifiedReading(
            document=LIBRO, page_number=265, values={"name": "ELIZABETH MIRANDA GUERRA"}
        )
        registros, _ = verified_readings.apply([DAÑADO], [lectura], document=LIBRO)
        assert registros[0].warnings == []

    def test_no_toca_las_paginas_que_no_se_verificaron(self):
        otra = DiplomaRecord(page_number=266, name="QUIEN SEA")
        lectura = verified_readings.VerifiedReading(
            document=LIBRO, page_number=265, values={"name": "ELIZABETH MIRANDA GUERRA"}
        )
        registros, corregidas = verified_readings.apply(
            [DAÑADO, otra], [lectura], document=LIBRO
        )
        assert registros[1].name == "QUIEN SEA"
        assert corregidas == [265]

    def test_una_verificacion_de_otro_libro_no_se_aplica(self):
        lectura = verified_readings.VerifiedReading(
            document="otro libro.pdf", page_number=265, values={"name": "NO ES ESTE"}
        )
        registros, corregidas = verified_readings.apply(
            [DAÑADO], [lectura], document=LIBRO
        )
        assert registros[0].name == "ELI2ABETH MIRANDA GUERRA"
        assert corregidas == []


class TestVerificacionesDelRepositorio:
    def test_el_archivo_entregado_es_legible_y_completo(self):
        from pathlib import Path

        ruta = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "verificaciones"
            / "diplomas.json"
        )
        lecturas = verified_readings.load(ruta)
        assert lecturas, "las verificaciones hechas a mano no deben perderse"
        # Cada una tiene que decir quién la hizo: una corrección anónima sobre un
        # inventario administrativo no se puede auditar.
        assert all(lectura.verified_by for lectura in lecturas)
        assert all(lectura.values.get("name") for lectura in lecturas)
