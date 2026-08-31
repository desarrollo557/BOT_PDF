"""El inventario guardado en MySQL.

Dos capas de prueba, a propósito. Las de arriba usan un conector falso y corren
en cualquier máquina: fijan la forma de las filas y que una corrección quede
marcada como tal. La de abajo habla con la base de verdad y se salta sola cuando
no hay ninguna configurada, porque una prueba que sólo corre en un equipo no
puede ser la única que cubra la escritura.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from resolutions.adapters.mysql_inventory import (
    MySQLInventory,
    _compact,
    settings_from_env,
)

FILAS = [
    (
        datetime(2026, 8, 31, 14, 30, 5),
        "RESOLUCIONES 00072-00094.pdf",
        "00072",
        "Por medio de la cual se hace un nombramiento",
        "00072__por-medio-de-la-cual.pdf",
        10, 1, 10, "1-10",
        "job-1", "María Martínez", 222, 5_242_880, 2,
    )
]

COLUMNAS = [
    "recorded_at", "source_document", "code", "title", "file_name",
    "page_count", "first_page", "last_page", "pages",
    "job_id", "operator", "source_pages", "source_bytes", "review",
]


class CursorFalso:
    def __init__(self, filas):
        self._filas = filas
        self.description = [(nombre,) for nombre in COLUMNAS]
        self.ejecutado: list[tuple[str, tuple]] = []
        self.lastrowid = 1
        self.rowcount = 1

    def execute(self, sql, params=()):
        self.ejecutado.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self._filas

    def fetchone(self):
        return self._filas[0] if self._filas else None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class ConexionFalsa:
    def __init__(self, filas):
        self._cursor = CursorFalso(filas)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class ConectorFalso:
    def __init__(self, filas=()):
        self.conexion = ConexionFalsa(list(filas))
        self.recibido = None

    def connect(self, **kwargs):
        self.recibido = kwargs
        return self.conexion


def almacen(filas=()):
    conector = ConectorFalso(filas)
    tienda = MySQLInventory(
        {"host": "h", "port": 3306, "user": "u", "password": "p", "database": "robotpdf"},
        connector=conector,
    )
    return tienda, conector


class TestLaFormaDeLasFilas:
    def test_una_fila_de_mysql_se_ve_igual_que_una_del_archivo(self):
        """La pantalla no puede notar cuál de los dos almacenes está detrás."""
        tienda, _ = almacen(FILAS)

        fila = tienda.rows()[0]

        assert set(fila) == set(COLUMNAS)
        assert fila["code"] == "00072"
        assert fila["source_document"] == "RESOLUCIONES 00072-00094.pdf"
        assert fila["pages"] == "1-10"

    def test_la_fecha_llega_como_texto_iso_y_no_como_objeto(self):
        # El archivo guarda texto ISO; la base devuelve datetime. Quien lee no
        # tiene por qué saberlo.
        tienda, _ = almacen(FILAS)

        assert tienda.rows()[0]["recorded_at"] == "2026-08-31T14:30:05"

    def test_los_numeros_llegan_como_numeros(self):
        tienda, _ = almacen(FILAS)
        fila = tienda.rows()[0]

        assert fila["page_count"] == 10
        assert fila["source_pages"] == 222
        assert fila["source_bytes"] == 5_242_880
        assert fila["review"] == 2

    def test_lo_derivado_se_calcula_igual_que_sobre_el_archivo(self):
        tienda, _ = almacen(FILAS)

        assert tienda.summary() == {
            "resolutions": 1,
            "documents": 1,
            "codes": 1,
            "pages": 10,
        }
        assert tienda.job_ids() == {"job-1"}
        assert tienda.documents()[0]["source_document"] == "RESOLUCIONES 00072-00094.pdf"


class TestLasCorrecciones:
    def test_corregir_deja_marcada_la_resolucion(self):
        """Una corrección tiene que poder distinguirse de una lectura.

        Si no queda marcada, el inventario no puede decir qué leyó la máquina y
        qué arregló una persona, que es la mitad del valor de tener inventario.
        """
        tienda, conector = almacen(FILAS)

        tienda.update("job-1", "00072__a.pdf", {"code": "00073"})

        sentencias = [sql for sql, _ in conector.conexion.cursor().ejecutado]
        assert any("corregida = 1" in sql for sql in sentencias)

    def test_un_cambio_vacio_no_escribe_nada(self):
        tienda, conector = almacen(FILAS)

        tienda.update("job-1", "00072__a.pdf", {})

        sentencias = [sql for sql, _ in conector.conexion.cursor().ejecutado]
        assert not any(sql.startswith("UPDATE resolucion") for sql in sentencias)


class TestLaConfiguracion:
    def test_sin_contrasena_no_se_intenta_conectar(self):
        """Un servicio contra la base equivocada es peor que uno sin base."""
        assert settings_from_env({}) is None

    def test_la_contrasena_del_entorno_arma_la_conexion(self):
        config = settings_from_env({"RESOLUTIONS_DB_PASSWORD": "x"})

        assert config is not None
        assert config["database"] == "robotpdf"
        assert config["port"] == 3306

    def test_se_puede_apuntar_a_otro_servidor(self):
        config = settings_from_env(
            {
                "RESOLUTIONS_DB_PASSWORD": "x",
                "RESOLUTIONS_DB_HOST": "10.0.0.5",
                "RESOLUTIONS_DB_PORT": "3307",
                "RESOLUTIONS_DB_NAME": "otra",
            }
        )

        assert (config["host"], config["port"], config["database"]) == ("10.0.0.5", 3307, "otra")

    def test_la_descripcion_nunca_incluye_la_contrasena(self):
        tienda, _ = almacen()

        assert "p" not in tienda.describe.split("@")[0].replace("mysql://", "")
        assert tienda.describe == "mysql://u@h:3306/robotpdf"


class TestLosRangosDePaginas:
    def test_las_paginas_seguidas_se_escriben_como_rango(self):
        assert _compact([1, 2, 3, 8, 9]) == "1-3,8-9"

    def test_una_pagina_suelta_se_escribe_sola(self):
        assert _compact([5]) == "5"

    def test_sin_paginas_no_hay_rango(self):
        assert _compact([]) == ""


@pytest.mark.skipif(
    not (os.environ.get("RESOLUTIONS_DB_PASSWORD") or os.environ.get("MYSQL_PWD")),
    reason="no hay base configurada en el entorno",
)
class TestContraLaBaseDeVerdad:
    def test_se_puede_hablar_con_la_base(self):
        pytest.importorskip("pymysql")
        tienda = MySQLInventory(settings_from_env())

        tienda.check()

        assert tienda.describe.endswith("/robotpdf")

    def test_lo_que_se_graba_se_vuelve_a_leer(self):
        pytest.importorskip("pymysql")
        tienda = MySQLInventory(settings_from_env())
        job = f"prueba{os.getpid():026d}"[:32]
        informe = {
            "document": "prueba de integración.pdf",
            "page_count": 3,
            "review_queue": [],
            "inventory": {
                "source_document": "prueba de integración.pdf",
                "source_pages": 3,
                "items": [
                    {
                        "file_name": "00099__prueba.pdf",
                        "code": "00099",
                        "title": "Prueba de integración",
                        "page_count": 3,
                        "first_page": 1,
                        "last_page": 3,
                        "page_numbers": [1, 2, 3],
                    }
                ],
            },
        }

        try:
            assert tienda.record(job, informe, operator=None, source_bytes=1234) == 1

            grabada = tienda._one(job, "00099__prueba.pdf")
            assert grabada is not None
            assert grabada["code"] == "00099"
            assert grabada["pages"] == "1-3"
            assert grabada["source_bytes"] == 1234
        finally:
            tienda.remove(job, "00099__prueba.pdf")
