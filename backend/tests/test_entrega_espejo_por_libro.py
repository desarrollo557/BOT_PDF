"""El destino es espejo de la fuente, con una carpeta por libro dividido.

Lo pidió el operador el 2026-11-27 sobre «8. ACTA 9 FACULTAD DE ODONTOLOGIA
CALIFICACIONES 3194 - 3198»: «todo lo que está aquí se procesará, y la idea es
que el bot lo deje como está en la fuente, pero dividido, y bien organizado,
con sus carpetas y subcarpetas». Eligió este árbol viendo los dos:

    <DESTINO>\\8. ACTA 9 … 3194 - 3198 - PROCESADO\\
        00.FUID GENERAL.xlsx
        ACTAS DE GRADO\\ (su FUID) \\ ACTAS DECADA. 1990-1994 TOMO II\\01_….pdf
        CALIFICACIONES\\FACULTAD DE ODONTOLOGIA CALIFICACIONES 1995\\ (su FUID)
            \\ 1 CALIFICACIONES ODONTOLOGIA 1995\\01_LISTA DE ALUMNOS….pdf
        RESOLUCIONES\\RESOLUCIONES DECANATURA 1995-2002\\UPD3860101\\ (su FUID)
            \\ 07-115 TOMO 1\\01_RESOLUCION 007-1995 - ….pdf

Aquí, con trabajos falsos que dejan lo que deja cada habilidad -- las actas de
grado y las calificaciones por ``inventario_actas`` y ``outputs``, las
resoluciones por ``filas_del_fuid`` y sus PDF --, la corrida entera por la
pantalla de carpeta: el árbol, un FUID en cada carpeta con PDF de origen y
ninguno en las intermedias, el tomo de la ruta, el cuadre de la auditoría y el
relanzamiento que no rehace nada. Los nombres y las cédulas son inventados.

**Los nombres van acortados donde no cambian la forma del árbol** -- la carpeta
elegida, «8. ODONTOLOGIA 3194 - 3198», el libro de la promoción y lo que
resuelve cada resolución --: Windows sin las rutas largas activadas
(``LongPathsEnabled = 0``, como esta máquina) no deja pasar de 259 caracteres,
y el árbol real entregado en ``C:\\Users\\…\\Desktop\\PROCESADOS`` deja de 28 a
102 caracteres para el nombre de cada PDF (medido el 2026-11-27). Las
subcarpetas sí son las reales: es su anidamiento lo que se prueba.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("openpyxl")

from resolutions.adapters.fuid_actas_de_grado import ACTA_DE_GRADO  # noqa: E402
from resolutions.adapters.fuid_de_la_entrega import (  # noqa: E402
    PDF_ENTERO,
    tomo_de_la_ruta,
)
from resolutions.adapters.fuid_reader import leer_fuid  # noqa: E402
from resolutions.api.folders import (  # noqa: E402
    FolderRunner,
    RunState,
    destino_de_la_corrida,
)
from resolutions.api.jobs import JobRegistry  # noqa: E402
from resolutions.api.settings import Settings  # noqa: E402
from resolutions.domain.historia_academica import HISTORIA_ACADEMICA  # noqa: E402
from resolutions.domain.naming import document_folder  # noqa: E402

CARPETA = "8. ODONTOLOGIA 3194 - 3198"
DECANATURA = "RESOLUCIONES/RESOLUCIONES DECANATURA 1995-2002"
PROMOCION = f"{DECANATURA}/UPD3860100/PROMOCION 2003 - UPD3860100.pdf"

#: Cada PDF de la fuente, con lo que sale de él. Un subconjunto del árbol real:
#: una carpeta con varios libros (ACTAS DE GRADO), subcarpetas anidadas, PDF con
#: la UPD en la ruta y sin ella, un nombre con dos espacios, un libro de
#: calificaciones dentro de la carpeta de resoluciones (UPD3860100) y dos PDF
#: que son un solo documento, que quedan como hoy.
LIBROS: dict[str, tuple[str, list]] = {
    # El manuscrito leído sin IA: entero, con su fila (un solo documento).
    "ACTAS DE GRADO/ACTAS DE GRADO 1952 - 1959.pdf": ("entero", []),
    "ACTAS DE GRADO/ACTAS DECADA. 1990-1994 TOMO II.pdf": (
        "actas",
        [("ELAINE MARGARITA AMARIS JIMENEZ", "39013744", "01", "17-12-1993"),
         ("CARLOS ALBERTO BARRIOS PATERNINA", "73141230", "02", "17-12-1993")],
    ),
    "ACTAS DE GRADO/ACTAS DECADA. 1996-1998-1999 TOMO I.pdf": (
        "actas",
        [("LUZ MARINA CASTRO PEREZ", "45466499", "01", "13-12-1996"),
         ("JORGE LUIS DIAZ ORTEGA", "9064111", "02", "13-12-1996")],
    ),
    "CALIFICACIONES/FACULTAD DE ODONTOLOGIA CALIFICACIONES 1995/1 CALIFICACIONES ODONTOLOGIA 1995.pdf": (
        "calificaciones",
        [("ALFARO ZOLA LIZELIA MARIA", "9010072", 1995), ("BELTRAN MEZA OMAR ENRIQUE", "9010081", 1995)],
    ),
    # Dos espacios en el nombre: la carpeta del libro lleva uno (``document_folder``).
    "CALIFICACIONES/FACULTAD DE ODONTOLOGIA CALIFICACIONES 1996/1 CALIFICACIONES ODONTOLOGIA  1996.pdf": (
        "calificaciones",
        [("CARDENAS RUIZ ANA LUCIA", "9110029", 1996), ("DURANGO PAEZ LUIS FERNANDO", "9110035", 1996)],
    ),
    f"{DECANATURA}/RESOLUCIONES DECANATURA 1995-2002 TOMO 2/1992-2002- tomo 2.pdf": (
        "resoluciones",
        [("062", 1998, "SUPLETORIOS"), ("063", 1998, "GRADOS")],
    ),
    f"{DECANATURA}/RESOLUCIONES DECANATURA 2003-2010 TOMO 1/TOMO 1 2003-2010.pdf": (
        "resoluciones",
        [("016", 2003, "CALENDARIO"), ("001", 2004, "JURADO")],
    ),
    PROMOCION: (
        "calificaciones",
        [("ESPINOSA VEGA MARTA", "52199810009", 2002), ("FUENTES ROJAS PEDRO", "52199810011", 2002)],
    ),
    f"{DECANATURA}/UPD3860101/07-115 TOMO 1.pdf": (
        "resoluciones",
        [("007", 1995, "EXAMENES"), ("008", 1995, "CURSO")],
    ),
    # Una sola resolución: su carpeta con un PDF, como hoy.
    f"{DECANATURA}/UPD3860105/01-046 TOMO 3.pdf": (
        "resoluciones",
        [("001", 1999, "CALENDARIO")],
    ),
}


def _escribir(carpeta: Path, nombre: str) -> str:
    (carpeta / nombre).parent.mkdir(parents=True, exist_ok=True)
    # Cada uno con su contenido: el control de repetidos compara byte a byte.
    (carpeta / nombre).write_bytes(b"%PDF-1.4 salida " + nombre.encode())
    return nombre


def _actas(libro: str, salida: Path, graduados: list) -> dict:
    """Lo que deja ``inventario.py`` con un libro de actas de grado dividido."""
    carpeta = document_folder(libro)
    filas, salidas = [], []
    for orden, (nombre, cedula, numero, fecha) in enumerate(graduados, start=1):
        pdf = f"{orden:02d}_{nombre} - ODONTOLOGO.pdf"
        salidas.append(_escribir(salida, f"{carpeta}/{pdf}"))
        filas.append(
            {"tipo": ACTA_DE_GRADO, "archivo": libro, "acta": f"ACTA DE GRADO No. {numero}", "numero": numero,
             "nombre": nombre, "titulo": "ODONTOLOGO", "cedula": cedula, "fecha": fecha,
             "pagina_inicial": orden, "pagina_final": orden, "archivo_generado": pdf, "observaciones": ""}
        )
    return {"tipo": "acta", "task": "inventory_file", "inventario_actas": filas, "outputs": salidas, "dividido": True}


def _calificaciones(libro: str, salida: Path, alumnos: list) -> dict:
    """Lo que deja ``historias.py`` con un libro de calificaciones: la lista y un PDF por alumno."""
    carpeta = document_folder(libro)
    anio = alumnos[0][2]
    lista = f"01_LISTA DE ALUMNOS - 2 PERIODO {anio}.pdf"
    salidas = [_escribir(salida, f"{carpeta}/{lista}")]
    filas = [
        {"tipo": "LISTA DE ALUMNOS", "asunto": lista[3:-4], "archivo": libro, "archivo_generado": lista,
         "fecha_inicial": anio, "fecha_final": anio, "folios": 2, "pagina_inicial": 1, "pagina_final": 2}
    ]
    for orden, (nombre, codigo, ultimo) in enumerate(alumnos, start=2):
        pdf = f"{orden:02d}_{nombre} - ODONTOLOGIA.pdf"
        salidas.append(_escribir(salida, f"{carpeta}/{pdf}"))
        filas.append(
            {"tipo": HISTORIA_ACADEMICA, "nombre": f"{nombre} - ODONTOLOGIA", "codigo": codigo, "anio_inicial": 1990,
             "anio_final": ultimo, "folios": 2, "archivo": libro, "archivo_generado": pdf,
             "pagina_inicial": 2 * orden - 1, "pagina_final": 2 * orden}
        )
    return {
        "tipo": "historia-academica", "habilidad": "Calificaciones", "task": "inventory_file",
        "inventario_actas": filas, "groups": [{"code": fila["archivo_generado"]} for fila in filas],
        "outputs": salidas, "dividido": True,
    }


def _resoluciones(libro: str, salida: Path, resoluciones: list) -> dict:
    """Lo que deja la habilidad de resoluciones: sus PDF y sus filas del FUID ya hechas."""
    carpeta = document_folder(libro)
    filas = []
    for orden, (numero, anio, resuelve) in enumerate(resoluciones, start=1):
        asunto = f"RESOLUCION {numero}-{anio} - {resuelve}"
        pdf = _escribir(salida, f"{carpeta}/{orden:02d}_{asunto}.pdf").split("/")[-1]
        filas.append(
            {"orden": orden, "asunto": asunto, "codigo_trd": "N/A", "consecutivo_inicial": f"{numero}-{anio}",
             "consecutivo_final": f"{numero}-{anio}", "fecha_inicial": f"02-02-{anio}", "fecha_final": f"02-02-{anio}",
             "caja": "N/A", "carpeta": "N/A", "tomo": "N/A", "otro": "N/A", "folios": 2, "folios_siar": 2,
             "soporte": "N/A", "frecuencia": "N/A", "notas": f"Archivo: {pdf}", "pagina_inicial": 2 * orden - 1}
        )
    return {
        "stats": {"document_type": "resolucion"}, "filas_del_fuid": filas,
        "groups": [{"code": fila["consecutivo_inicial"]} for fila in filas],
    }


HABILIDADES = {"actas": _actas, "calificaciones": _calificaciones, "resoluciones": _resoluciones}


@pytest.fixture
def entorno(tmp_path_factory):
    # Una base corta: la de cada prueba lleva su nombre delante (ver arriba).
    base = tmp_path_factory.mktemp("e")
    settings = replace(
        Settings(),
        upload_dir=base / "u",
        output_dir=base / "o",
        ledger_path=base / "inventory.jsonl",
        pausa_tras_fallos=0.01,
    )
    settings.ensure_directories()
    origen = base / "F" / CARPETA
    for relativa in LIBROS:
        (origen / relativa).parent.mkdir(parents=True, exist_ok=True)
        (origen / relativa).write_bytes(b"%PDF-1.4 libro " + relativa.encode())
    registry = JobRegistry()
    procesados: list[str] = []

    async def run_job(job):
        relativa = Path(job.filename).as_posix()
        procesados.append(relativa)
        clase, documentos = LIBROS[relativa]
        libro = Path(relativa).name
        salida = settings.output_dir / job.id
        salida.mkdir(parents=True, exist_ok=True)
        if clase == "entero":
            informe = {
                "tipo": "acta", "task": "inventory_file",
                "inventario_actas": [{"tipo": PDF_ENTERO, "archivo": libro, "folios": 299, "pagina_inicial": 1}],
            }
        else:
            informe = HABILIDADES[clase](libro, salida, documentos)
        registry.mark_done(job, {"review_queue": [], **informe})

    runner = FolderRunner(registry, settings, run_job, watch_interval=0.01)
    destino = Path(destino_de_la_corrida(str(origen), str(base / "D")))
    return runner, origen, destino, procesados


def _correr(runner, origen: Path, destino: Path):
    async def go():
        run = runner.start(str(origen), str(destino), task="both")
        for _ in range(3000):
            if not run.active:
                return run
            await asyncio.sleep(0.01)
        return run

    return asyncio.run(go())


def _arbol(destino: Path) -> list[str]:
    """Lo que ve el operador al abrir el destino: sin las constancias ocultas del bot."""
    return sorted(
        ruta.relative_to(destino).as_posix()
        for ruta in destino.rglob("*")
        if ruta.is_file() and not any(parte.startswith(".") for parte in ruta.relative_to(destino).parts)
    )


def _pdfs(libro: str) -> list[str]:
    """Los «NN_<asunto>.pdf» que deja el trabajo falso de un libro."""
    clase, documentos = LIBROS[libro]
    nombre = Path(libro).name
    if clase == "actas":
        return [f"{orden:02d}_{d[0]} - ODONTOLOGO.pdf" for orden, d in enumerate(documentos, start=1)]
    if clase == "calificaciones":
        return [f"01_LISTA DE ALUMNOS - 2 PERIODO {documentos[0][2]}.pdf"] + [
            f"{orden:02d}_{d[0]} - ODONTOLOGIA.pdf" for orden, d in enumerate(documentos, start=2)
        ]
    if clase == "resoluciones":
        return [f"{orden:02d}_RESOLUCION {d[0]}-{d[1]} - {d[2]}.pdf" for orden, d in enumerate(documentos, start=1)]
    return [nombre]


def _esperado() -> list[str]:
    """El árbol que eligió el operador: espejo de la fuente, una carpeta por libro dividido, un FUID por carpeta."""
    arbol = {"00.FUID GENERAL.xlsx"}
    for libro, (clase, _documentos) in LIBROS.items():
        carpeta = Path(libro).parent
        arbol.add(f"{carpeta.as_posix()}/{carpeta.name}__FUID.xlsx")
        if clase == "entero":
            # El PDF que es un solo documento queda como hoy: tal cual, en su espejo.
            arbol.add(libro)
            continue
        for pdf in _pdfs(libro):
            arbol.add(f"{carpeta.as_posix()}/{document_folder(Path(libro).name)}/{pdf}")
    return sorted(arbol)


class TestElDestinoEsEspejoConUnaCarpetaPorLibro:
    def test_deja_el_arbol_que_eligio_el_operador(self, entorno):
        runner, origen, destino, procesados = entorno
        assert destino.name == f"{CARPETA} - PROCESADO"

        run = _correr(runner, origen, destino)

        assert run.state is RunState.DONE, (run.state, run.error, run.avisos)
        assert sorted(procesados) == sorted(LIBROS)
        # Los generales del bot que no son el FUID siguen en la raíz, como siempre.
        assert [r for r in _arbol(destino) if "/" not in r and r != "00.FUID GENERAL.xlsx"] == [
            "00.ANALISIS DE LA ENTREGA.xlsx",
            "00.INVENTARIO GENERAL DE PROCESOS.xlsx",
        ]
        assert [r for r in _arbol(destino) if "/" in r or r == "00.FUID GENERAL.xlsx"] == _esperado()
        # El libro de dos espacios, con uno en su carpeta; y ninguna «(2)».
        assert (
            destino / "CALIFICACIONES" / "FACULTAD DE ODONTOLOGIA CALIFICACIONES 1996" / "1 CALIFICACIONES ODONTOLOGIA 1996"
        ).is_dir()
        assert not [r for r in _arbol(destino) if "(2)" in r]

    def test_un_fuid_en_cada_carpeta_con_pdf_y_ninguno_en_las_intermedias(self, entorno):
        runner, origen, destino, _ = entorno
        _correr(runner, origen, destino)

        fuids = sorted(r for r in _arbol(destino) if r.endswith("__FUID.xlsx"))
        con_pdf = sorted({Path(libro).parent.as_posix() for libro in LIBROS})
        assert [Path(r).parent.as_posix() for r in fuids] == con_pdf
        # «RESOLUCIONES», «RESOLUCIONES\\RESOLUCIONES DECANATURA 1995-2002» y
        # «CALIFICACIONES» no traen PDF propio: no llevan FUID.
        for intermedia in ("RESOLUCIONES", DECANATURA, "CALIFICACIONES"):
            assert not list((destino / intermedia).glob("*.xlsx")), intermedia

        # Cada FUID con las filas de todos sus PDF: los dos libros de actas
        # dividos y el manuscrito entero en el de «ACTAS DE GRADO».
        actas = leer_fuid(destino / "ACTAS DE GRADO" / "ACTAS DE GRADO__FUID.xlsx")
        assert len(actas.filas) == 5
        assert actas.oficina_productora.endswith("FACULTAD DE ODONTOLOGIA")
        upd = leer_fuid(destino / DECANATURA / "UPD3860101" / "UPD3860101__FUID.xlsx")
        assert [fila[2] for fila in upd.filas] == [
            "RESOLUCION 007-1995 - EXAMENES",
            "RESOLUCION 008-1995 - CURSO",
        ]

        general = leer_fuid(destino / "00.FUID GENERAL.xlsx")
        por_carpeta = sum(len(leer_fuid(destino / r).filas) for r in fuids)
        assert len(general.filas) == por_carpeta == 5 + 3 + 3 + 2 + 2 + 3 + 2 + 1
        assert [fila[0] for fila in general.filas] == [str(n) for n in range(1, por_carpeta + 1)]

    def test_el_tomo_y_la_upd_salen_de_la_ruta_y_la_caja_no_se_inventa(self, entorno):
        runner, origen, destino, _ = entorno
        _correr(runner, origen, destino)

        def columnas(relativa: str) -> set[tuple[str, str, str]]:
            # Caja, UPD y tomo de cada fila.
            return {(fila[7], fila[8], fila[9]) for fila in leer_fuid(destino / relativa).filas}

        assert columnas("ACTAS DE GRADO/ACTAS DE GRADO__FUID.xlsx") == {("", "", ""), ("", "", "II"), ("", "", "I")}
        cal = "CALIFICACIONES/FACULTAD DE ODONTOLOGIA CALIFICACIONES 1995"
        assert columnas(f"{cal}/FACULTAD DE ODONTOLOGIA CALIFICACIONES 1995__FUID.xlsx") == {("", "", "")}
        # Las filas que trae hechas la habilidad de resoluciones conservan, como
        # hoy, el «N/A» de su caja y su UPD cuando la ruta no las dice
        # (``fila_hecha``); el tomo, si la ruta no lo dice, va vacío en todas.
        tomo2 = f"{DECANATURA}/RESOLUCIONES DECANATURA 1995-2002 TOMO 2"
        assert columnas(f"{tomo2}/RESOLUCIONES DECANATURA 1995-2002 TOMO 2__FUID.xlsx") == {("N/A", "N/A", "2")}
        tomo1 = f"{DECANATURA}/RESOLUCIONES DECANATURA 2003-2010 TOMO 1"
        assert columnas(f"{tomo1}/RESOLUCIONES DECANATURA 2003-2010 TOMO 1__FUID.xlsx") == {("N/A", "N/A", "1")}
        assert columnas(f"{DECANATURA}/UPD3860100/UPD3860100__FUID.xlsx") == {("", "UPD3860100", "")}
        assert columnas(f"{DECANATURA}/UPD3860101/UPD3860101__FUID.xlsx") == {("N/A", "UPD3860101", "1")}
        assert columnas(f"{DECANATURA}/UPD3860105/UPD3860105__FUID.xlsx") == {("N/A", "UPD3860105", "3")}

    def test_la_auditoria_cuadra_y_relanzar_no_rehace_nada(self, entorno):
        runner, origen, destino, procesados = entorno
        primera = _correr(runner, origen, destino)
        assert primera.comparacion is not None
        assert primera.comparacion["pdf_origen"] == primera.comparacion["pdf_entregados"] == len(LIBROS)
        assert primera.comparacion["sobran"] == [] and primera.comparacion["faltan"] == []
        antes = _arbol(destino)
        filas = len(leer_fuid(destino / "00.FUID GENERAL.xlsx").filas)

        segunda = _correr(runner, origen, destino)

        # Cada PDF encuentra su constancia -- la de su carpeta de libro o la de
        # sus actas en el espejo -- y se salta sin volver a leerse.
        assert segunda.state is RunState.DONE
        assert segunda.ya_entregados == len(LIBROS)
        assert len(procesados) == len(LIBROS)
        assert _arbol(destino) == antes
        # Y los FUID, reescritos con lo que guardan las constancias, no pierden filas.
        assert len(leer_fuid(destino / "00.FUID GENERAL.xlsx").filas) == filas
        assert len(leer_fuid(destino / "ACTAS DE GRADO" / "ACTAS DE GRADO__FUID.xlsx").filas) == 5

    def test_un_libro_que_cambio_se_rehace_en_su_carpeta_sin_dejar_dos(self, entorno):
        """Lo de antes se aparta a «_reemplazados» -- en el espejo las actas, en su carpeta la resolución --."""
        runner, origen, destino, procesados = entorno
        _correr(runner, origen, destino)
        antes = _arbol(destino)
        filas = len(leer_fuid(destino / "00.FUID GENERAL.xlsx").filas)
        actas = "ACTAS DE GRADO/ACTAS DECADA. 1990-1994 TOMO II.pdf"
        resolucion = f"{DECANATURA}/UPD3860101/07-115 TOMO 1.pdf"
        for cambiado in (actas, resolucion):
            (origen / cambiado).write_bytes(b"%PDF-1.4 otro escaneo, mas largo " + cambiado.encode())

        segunda = _correr(runner, origen, destino)

        assert segunda.state is RunState.DONE
        assert sorted(procesados[len(LIBROS):]) == sorted([actas, resolucion])
        assert segunda.rehechos == 2 and segunda.ya_entregados == len(LIBROS) - 2
        # El mismo árbol, sin «(2)»: lo entregado antes quedó apartado, no al lado.
        assert [r for r in _arbol(destino) if "_reemplazados" not in r] == antes
        assert list((destino / "ACTAS DE GRADO" / "_reemplazados").rglob("01_*.pdf"))
        assert list((destino / DECANATURA / "UPD3860101" / "07-115 TOMO 1" / "_reemplazados").rglob("01_*.pdf"))
        assert len(leer_fuid(destino / "00.FUID GENERAL.xlsx").filas) == filas


@pytest.mark.parametrize(
    ("carpeta", "archivo", "tomo"),
    [
        ("8. ACTA 9\\ACTAS DE GRADO", "ACTAS DECADA. 1990-1994 TOMO II.pdf", "II"),
        ("8. ACTA 9\\ACTAS DE GRADO", "ACTAS DECADA. 1980-1984 TOMO I.pdf", "I"),
        ("X\\RESOLUCIONES DECANATURA 1995-2002 TOMO 2", "1992-2002- tomo 2.pdf", "2"),
        ("X\\RESOLUCIONES DECANATURA 2003-2010 TOMO 1", "TOMO 1 2003-2010.pdf", "1"),
        ("X/UPD3860106", "001-034-TOMO 1.pdf", "1"),
        ("X/UPD3860105", "01-046 TOMO 3.pdf", "3"),
        # El PDF no lo dice y su carpeta sí.
        ("X\\LIBROS TOMO 4", "RESOLUCIONES 2001.pdf", "4"),
        # El del PDF manda sobre el de su carpeta.
        ("X\\TOMO 2", "LIBRO TOMO 3.pdf", "3"),
        ("X", "LIBRO TOMO N° 05.pdf", "5"),
        # Nada inventado: sin tomo, vacío; un año no es un tomo; «TOMOS» ni
        # «ESTOMODEO» tampoco, ni un romano que no lo es.
        ("8. ACTA 9\\ACTAS DE GRADO", "ACTAS DE GRADO 1952 - 1959.pdf", ""),
        ("X", "LIBRO TOMO 2003.pdf", ""),
        ("X", "TOMOS 1 Y 2.pdf", ""),
        ("X", "ESTOMODEO 2.pdf", ""),
        ("X", "TOMO CIVIL.pdf", ""),
        ("", "", ""),
    ],
)
def test_el_tomo_es_el_que_dice_la_ruta(carpeta, archivo, tomo):
    assert tomo_de_la_ruta(carpeta, archivo) == tomo


def test_la_fila_toma_el_tomo_de_su_ruta_y_respeta_el_que_trae():
    from resolutions.adapters.fuid_de_la_entrega import FILA_HECHA, fila_del_fuid

    hecha = {
        "tipo": FILA_HECHA,
        "fuid": {"orden": 1, "asunto": "RESOLUCION 007-1995 - X", "tomo": "N/A", "notas": "Archivo: 01_R.pdf"},
        "carpeta": "8. ACTA 9\\RESOLUCIONES\\RESOLUCIONES DECANATURA 1995-2002\\UPD3860101",
        "archivo": "07-115 TOMO 1.pdf",
    }
    assert fila_del_fuid(hecha).tomo == "1"
    # La de una carpeta sin tomo: vacía, no «N/A».
    assert fila_del_fuid({**hecha, "archivo": "PROMOCION 2003.pdf"}).tomo == ""
    # Y el tomo que el conversor sacó del papel no se pisa con el de la ruta.
    assert fila_del_fuid({**hecha, "fuid": {**hecha["fuid"], "tomo": "IV"}}).tomo == "IV"


@pytest.mark.skipif(os.name != "nt", reason="el límite de ruta es de Windows")
class TestLaRutaLargaEnWindows:
    """El espejo anidado deja rutas al borde del límite de Windows (259 sin las rutas largas)."""

    def test_un_pdf_que_cabe_justo_se_copia_aunque_su_part_no_cupiera(self, tmp_path_factory):
        from resolutions.api.folders import LARGO_DE_RUTA_EN_WINDOWS, _copiar

        carpeta = tmp_path_factory.mktemp("p")
        while len(str(carpeta)) < 225:
            carpeta = carpeta / "SUBCARPETA DEL ESPEJO"
        carpeta.mkdir(parents=True)
        cabe = LARGO_DE_RUTA_EN_WINDOWS - len(str(carpeta)) - 1
        nombre = ("01_RESOLUCION 062-1998 - " + "SUPLETORIOS " * 20)[: cabe - 4].rstrip() + ".pdf"
        hasta = carpeta / nombre.replace(" .pdf", ".pdf")
        # El PDF cabe; con «.<marca>.part» detrás de su nombre, no.
        assert len(str(hasta)) <= LARGO_DE_RUTA_EN_WINDOWS < len(str(hasta)) + len(".12345678.part")
        origen = carpeta.parent / "libro.pdf"
        origen.write_bytes(b"%PDF-1.4 libro")

        _copiar(origen, hasta)

        assert hasta.read_bytes() == b"%PDF-1.4 libro"
        assert not [n for n in os.listdir(carpeta) if n.endswith(".part")]

    def test_la_copia_que_no_cabe_lo_dice_en_vez_de_dar_el_pdf_por_borrado(self):
        from resolutions.api.folders import _explicar_la_entrega

        larga = "C:\\DESTINO\\" + "RESOLUCIONES DECANATURA 1995-2002\\" * 8 + "01_RESOLUCION 062-1998.pdf"
        assert len(larga) > 259
        mensaje = _explicar_la_entrega(FileNotFoundError(2, "No such file or directory", larga), Path(larga))
        assert "Windows no deja pasar de 259" in mensaje and "se movió" not in mensaje
        # Lo que falló cabe -- el origen se borró de verdad --: la explicación de siempre.
        origen = FileNotFoundError(2, "No such file or directory", "C:\\Fuentes\\libro.pdf")
        assert "se movió" in _explicar_la_entrega(origen, Path(larga))
        # Y un archivo abierto o sin permiso no es una ruta larga.
        assert "Windows no deja pasar" not in _explicar_la_entrega(PermissionError(13, "denied", larga), Path(larga))

    def test_la_carpeta_del_libro_que_no_cabe_tambien_lo_dice(self, tmp_path_factory):
        """Una carpeta de 248 a 259 caracteres: como archivo cabría, pero Windows contesta WinError 206."""
        from resolutions.api.folders import _explicar_la_entrega

        base = tmp_path_factory.mktemp("c")
        carpeta = base / ("1992-2002-TOMO-2-" * 20)[: 250 - len(str(base)) - 1]
        assert 247 < len(str(carpeta)) <= 259
        try:
            carpeta.mkdir(parents=True)
        except OSError as error:
            assert "Windows no deja pasar de 259" in _explicar_la_entrega(error, carpeta)
        else:
            pytest.skip("este equipo tiene activadas las rutas largas de Windows")
