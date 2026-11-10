"""El revisor de fechas en las historias, las nóminas y los certificados (el operador, 2026-11-10).

«Necesito estar muy seguro de cada fecha en cada documento, sin importar la
habilidad», «corregir sólo con prueba» y «saber manejar un margen de errores».
Esta suite fija cómo se engancha el núcleo (``application/revisor_de_fechas``)
en los tres trabajos de la Universidad que comparten ``asegurar_las_fechas``
(``api/worker/nominas.py``), en el orden en que trabaja:

1. **Lo ya leído** (``el_papel_de_la_fila``): las fechas cortas del texto
   crudo -- «3.07.84», «AÑO 90» -- van escritas enteras; sin releer nada y sin
   lo que el trabajo dedujo de él, que confirmaría a la fila consigo misma (la
   revisión adversarial, 2026-11-10).
2. **Lo que viene de fuera de sus hojas** (``tomada_del_libro``, ``derivadas``):
   el año del libro o del código no se busca en un papel que no lo trae ni se le
   pregunta a la IA, salvo que caiga fuera de la ventana -- ACOSTA BELLO --.
3. **Cada regla**: los años de las historias y las nóminas se confirman o se
   preguntan; la firma del certificado corrige con dos pruebas; la IA corrige
   sólo citando el papel. Lo corregido se escribe con el formato de cada fila.
4. **Nunca tumba el trabajo**: un revisor o una IA que fallan dejan la fila
   como estaba; la cancelación sí sube.

Y la comprobación barata de ``domain/datos_esperados``: un documento con los
años fuera de los de su caja es una duda, al procesar y al auditar.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from resolutions.api.worker.nominas import (
    _con_el_nombre_asegurado,
    asegurar_las_fechas,
    el_papel_de_la_fila,
    nombre_del_pdf,
    tomada_del_libro,
)
from resolutions.application.control import Cancelled
from resolutions.application.ports import VeredictoDeDato
from resolutions.application.revisor_de_fechas import CLAVE_DEL_INFORME
from resolutions.domain.datos_esperados import (
    DUDA,
    FECHAS,
    DatosDeUnaHistoria,
    anios_de_la_caja,
    fuera_de_los_anios_de_la_caja,
    revisar_entre_documentos,
    revisar_nominas_entre_si,
)
from resolutions.domain.historia_academica import HISTORIA_ACADEMICA


class JuezDeMentira:
    """La IA del trabajo: contesta lo que se le dé y apunta cada pregunta."""

    def __init__(self, respuesta=None):
        self.respuesta = respuesta
        self.preguntas: list[list[dict[str, str]]] = []

    def verificar(self, texto, datos):
        self.preguntas.append(datos)
        return self.respuesta


def _taller(juez=None):
    return SimpleNamespace(juez_de_datos=lambda: juez)


def _nomina(**cambios) -> dict:
    fila = {
        "tipo": "nomina",
        "clase": "persona",
        "fecha_inicial": "01/01/1975",
        "fecha_final": "31/12/1975",
        "pagina_inicial": 3,
        "pagina_final": 4,
        "archivo": "NOMINA 1975.pdf",
        "archivo_generado": "03_CASTELLAR-MEZA-TULIO-9064111.pdf",
        "observaciones": "",
    }
    fila.update(cambios)
    return fila


def _historia(**cambios) -> dict:
    fila = {
        "tipo": HISTORIA_ACADEMICA,
        "nombre": "ACOSTA BELLO ADOLFO MANUEL",
        "anio_inicial": 1980,
        "anio_final": 1984,
        "fecha_exacta": None,
        "pagina_inicial": 10,
        "pagina_final": 14,
        "archivo": "UPD3859727.pdf",
        "archivo_generado": "05_ACOSTA-BELLO-ADOLFO-MANUEL.pdf",
        "observaciones": "",
    }
    fila.update(cambios)
    return fila


def _revisar(filas, textos, *, habilidad="nominas", juez=None, **kwargs) -> dict:
    report: dict = {"review_queue": []}
    asegurar_las_fechas(report, filas, textos, habilidad=habilidad, taller=_taller(juez), **kwargs)
    return report


# -- 1. lo ya leído --------------------------------------------------------------------------


class TestLoYaLeido:
    def test_las_fechas_cortas_del_papel_van_escritas_enteras_y_cada_hoja_una_vez(self):
        papel = el_papel_de_la_fila(["NOMINA 3.07.84 PAG. 1", "NOMINA 3.07.84 PAG. 1", "", "TARJETA AÑO 75"])
        assert len(papel) == 2
        assert papel[0].endswith("LEIDO EN LA HOJA: 03/07/1984")
        assert papel[1].endswith("LEIDO EN LA HOJA: 1975")

    def test_el_siglo_dudoso_no_se_escribe_salvo_con_la_ventana(self):
        """«AÑO 05» es 1905 o 2005: sin los años del libro no se escribe ninguno."""
        assert el_papel_de_la_fila(["AÑO 05"]) == ["AÑO 05"]
        assert el_papel_de_la_fila(["AÑO 05"], (2004, 2006))[0].endswith("LEIDO EN LA HOJA: 2005")

    @pytest.mark.parametrize(
        ("de_donde", "del_libro"),
        [
            ("el año 1975 del libro: la hoja no lo dice", True),
            ("los años 1993 a 1994 del libro: no se leyó la fecha de la firma", True),
            ("la hoja dice 1927, fuera de los años del libro: va el año 1975 del libro; revísela", True),
            # Los años de la hoja, aunque se descarte uno fuera del libro: son del papel.
            ("la hoja dice 1927, fuera de los años del libro: revísela", False),
            # El hablador es la primera hoja del paquete: su año es del papel.
            ("el año 1984 del hablador", False),
            (None, False),
        ],
    )
    def test_que_fechas_salieron_del_libro(self, de_donde, del_libro):
        assert tomada_del_libro(de_donde) is del_libro


# -- 2. las nóminas --------------------------------------------------------------------------


class TestNominas:
    def test_la_tarjeta_con_su_anio_escrito_se_confirma(self):
        report = _revisar([_nomina()], [["APELLIDOS CASTELLAR MEZA NOMBRE TULIO C.C. 9064111 AÑO 1975"]])
        resumen = report[CLAVE_DEL_INFORME]
        assert (resumen["revisados"], resumen["confirmada"], resumen["a revisión"]) == (1, 1, 0)
        assert report["review_queue"] == []

    def test_el_listado_con_la_fecha_corta_se_confirma_con_su_papel(self):
        """«3.07.84»: el contraste no entiende años de dos cifras; escrita entera desde el mismo texto, sí."""
        fila = _nomina(clase="paquete", fecha_inicial="03/07/1984", fecha_final="03/07/1984")
        crudo = _revisar([dict(fila)], [["NOMINA DE SUELDOS 3.07.84 PAG. 1"]])
        entero = _revisar([dict(fila)], [el_papel_de_la_fila(["NOMINA DE SUELDOS 3.07.84 PAG. 1"])])
        assert crudo[CLAVE_DEL_INFORME]["a revisión"] == 1
        assert entero[CLAVE_DEL_INFORME]["confirmada"] == 1

    def test_la_fila_no_se_confirma_con_lo_que_dedujo_el_trabajo(self):
        """El papel dice «2.07.81» y la fila 02/07/1984: lo que leyó el lector no es otra prueba.

        La revisión adversarial (2026-11-10): con lo deducido metido en el texto
        salía confirmada. Con el papel solo, es una duda.
        """
        fila = _nomina(clase="paquete", fecha_inicial="02/07/1984", fecha_final="02/07/1984")
        report = _revisar([fila], [el_papel_de_la_fila(["NOMINA DE PERSONAL DOCENTE FECHA 2.07.81 PAGINA 3"])])
        assert report[CLAVE_DEL_INFORME]["confirmada"] == 0
        assert report[CLAVE_DEL_INFORME]["a revisión"] == 1
        assert fila["fecha_inicial"] == "02/07/1984"

    def test_se_puede_detener_entre_una_fila_y_la_siguiente(self):
        class Detenido:
            def check(self):
                raise Cancelled()

        with pytest.raises(Cancelled):
            asegurar_las_fechas(
                {}, [_nomina()], [["AÑO 1975"]], habilidad="nominas",
                taller=SimpleNamespace(juez_de_datos=lambda: None, control=Detenido()),
            )

    def test_cada_hoja_se_le_manda_una_vez_a_la_ia(self):
        juez = JuezDeMentira()
        textos_vistos = []
        juez.verificar = lambda texto, datos: textos_vistos.append(texto)
        _revisar([_nomina()], [["APELLIDOS CASTELLAR AÑO 1957", "APELLIDOS CASTELLAR AÑO 1957"]], juez=juez)
        assert textos_vistos and textos_vistos[0].count("CASTELLAR") == 1


    def test_el_anio_del_libro_no_se_busca_ni_se_pregunta_ni_va_a_revision(self):
        """La tarjeta deja la casilla del año vacía: lo normal, y la fila ya lo dice (``NOTA_DEL_ANIO``)."""
        juez = JuezDeMentira()
        report = _revisar(
            [_nomina(observaciones="fechas: el año 1975 del libro: la hoja no lo dice")],
            [["APELLIDOS CASTELLAR MEZA NOMBRE TULIO"]],
            juez=juez, ventana=(1974, 1976), derivadas=[(True, True)],
        )
        assert report[CLAVE_DEL_INFORME]["sin dato"] == 1
        assert report["review_queue"] == []
        assert juez.preguntas == []

    def test_lo_dudoso_va_a_revision_con_su_motivo_y_la_fila_no_cambia(self):
        fila = _nomina()
        report = _revisar([fila], [["APELLIDOS CASTELLAR MEZA AÑO 1957"]])
        assert report[CLAVE_DEL_INFORME]["a revisión"] == 1
        (entrada,) = report["review_queue"]
        assert entrada["page"] == 3
        assert entrada["reason"].startswith("revisor de fechas, 03_CASTELLAR-MEZA-TULIO-9064111.pdf")
        assert (fila["fecha_inicial"], fila["fecha_final"]) == ("01/01/1975", "31/12/1975")

    def test_la_ia_corrige_citando_el_papel_y_la_fila_queda_con_su_formato(self):
        juez = JuezDeMentira(
            {
                "fecha_inicial": VeredictoDeDato("no_esta", "CASTELLAR MEZA AÑO 1957"),
                "fecha_final": VeredictoDeDato("no_esta", "CASTELLAR MEZA AÑO 1957"),
            }
        )
        fila = _nomina()
        report = _revisar([fila], [["APELLIDOS CASTELLAR MEZA AÑO 1957"]], juez=juez)
        assert report[CLAVE_DEL_INFORME]["corregida"] == 1
        assert len(juez.preguntas) == 1, "una pregunta por documento, con todo lo dudoso"
        assert (fila["fecha_inicial"], fila["fecha_final"]) == ("01/01/1957", "31/12/1957")
        assert "fecha inicial corregida: 1975 → 1957" in fila["observaciones"]
        assert any(aviso.startswith("Fecha corregida en 03_CASTELLAR") for aviso in report["notices"])

    def test_una_cita_corta_de_la_ia_no_corrige(self):
        """«AÑO 1957» sola no prueba de dónde salió el año (podría ser el de nacimiento): a Revisión."""
        juez = JuezDeMentira({"fecha_inicial": VeredictoDeDato("no_esta", "AÑO 1957")})
        fila = _nomina()
        report = _revisar([fila], [["APELLIDOS CASTELLAR MEZA AÑO 1957"]], juez=juez)
        assert report[CLAVE_DEL_INFORME]["corregida"] == 0
        assert (fila["fecha_inicial"], fila["fecha_final"]) == ("01/01/1975", "31/12/1975")

    def test_una_cita_que_el_papel_no_trae_no_corrige(self):
        juez = JuezDeMentira({"fecha_inicial": VeredictoDeDato("no_esta", "AÑO 1960")})
        fila = _nomina()
        report = _revisar([fila], [["APELLIDOS CASTELLAR MEZA AÑO 1957"]], juez=juez)
        assert report[CLAVE_DEL_INFORME]["a revisión"] == 1
        assert fila["fecha_inicial"] == "01/01/1975"


class TestElNombreDelListado:
    """El listado se llama por su fecha: corregida, el PDF sale con la corregida (P1-1, 2026-11-10)."""

    @staticmethod
    def _paquete():
        from resolutions.domain import nomina as n

        return SimpleNamespace(clase=n.PAQUETE, plantilla=n.LISTADO, fechas=[(3, 7, 1984)], anio=None, paginas=[5, 6])

    def test_el_nombre_lleva_la_fecha_asegurada(self):
        documento = self._paquete()
        assert nombre_del_pdf(5, documento) == "05_NOMINA-03-07-1984.pdf"
        assert nombre_del_pdf(5, documento, inicial=(13, 7, 1984)) == "05_NOMINA-13-07-1984.pdf"

    def test_la_fila_la_cola_y_lo_anotado_dicen_el_nombre_nuevo(self):
        documento = self._paquete()
        fila = {"fecha_inicial": "13/07/1984", "archivo_generado": "05_NOMINA-03-07-1984.pdf"}
        cola = [{"page": 5, "reason": "05_NOMINA-03-07-1984.pdf: no se leyó el total"}]
        aparte = {
            "notices": ["Fecha corregida en 05_NOMINA-03-07-1984.pdf: fecha inicial corregida"],
            CLAVE_DEL_INFORME: {"detalle": [{"documento": "05_NOMINA-03-07-1984.pdf"}]},
        }
        (hecho,) = _con_el_nombre_asegurado(
            [(5, documento, "05_NOMINA-03-07-1984.pdf", "03/07/1984")], [fila], cola, aparte, None
        )
        assert hecho[2] == fila["archivo_generado"] == "05_NOMINA-13-07-1984.pdf"
        assert cola[0]["reason"].startswith("05_NOMINA-13-07-1984.pdf: ")
        assert "05_NOMINA-13-07-1984.pdf" in aparte["notices"][0]
        assert aparte[CLAVE_DEL_INFORME]["detalle"][0]["documento"] == "05_NOMINA-13-07-1984.pdf"

    def test_sin_correccion_el_nombre_no_cambia(self):
        documento = self._paquete()
        fila = {"fecha_inicial": "03/07/1984", "archivo_generado": "05_NOMINA-03-07-1984.pdf"}
        (hecho,) = _con_el_nombre_asegurado([(5, documento, "05_NOMINA-03-07-1984.pdf", "03/07/1984")], [fila], [], {}, None)
        assert hecho[2] == "05_NOMINA-03-07-1984.pdf"


# -- 3. los certificados ---------------------------------------------------------------------

FIRMA = "Para constancia se firma el presente certificado en Cartagena a los 27 días del mes de Enero de 1993."


class TestCertificados:
    def test_la_firma_confirma_la_fecha_de_la_fila(self):
        fila = _nomina(plantilla="certificado", fecha_inicial="27/01/1993", fecha_final="27/01/1993")
        report = _revisar([fila], [[FIRMA]], habilidad="certificados", ventana=(1993, 1993))
        assert report[CLAVE_DEL_INFORME]["confirmada"] == 1

    def test_la_confirmada_por_su_propio_lector_se_cuenta_aparte(self):
        """La fecha la leyó el lector de la firma sobre el mismo texto: confirmarla no es otra prueba."""
        fila = _nomina(plantilla="certificado", fecha_inicial="27/01/1993", fecha_final="27/01/1993")
        report = _revisar(
            [fila], [[FIRMA]], habilidad="certificados", ventana=(1993, 1993), de_su_lector=[True]
        )
        resumen = report[CLAVE_DEL_INFORME]
        assert (resumen["confirmada"], resumen["confirmadas_por_su_lector"]) == (1, 1)

    def test_la_firma_corrige_con_dos_pruebas_la_fecha_que_el_papel_no_trae(self):
        """El lector de la firma dice el 27 de enero, y el 10 de mayo no está escrito en ninguna parte."""
        fila = _nomina(plantilla="certificado", fecha_inicial="10/05/1993", fecha_final="10/05/1993")
        report = _revisar([fila], [[FIRMA]], habilidad="certificados", ventana=(1993, 1993))
        assert report[CLAVE_DEL_INFORME]["corregida"] == 1
        assert (fila["fecha_inicial"], fila["fecha_final"]) == ("27/01/1993", "27/01/1993")
        assert "la firma del certificado dice 27/01/1993" in fila["observaciones"]

    def test_un_digito_del_ocr_no_se_corrige_se_pregunta(self):
        """El 17 por el 27: el margen del OCR es duda, no error."""
        fila = _nomina(plantilla="certificado", fecha_inicial="17/01/1993", fecha_final="17/01/1993")
        report = _revisar([fila], [[FIRMA]], habilidad="certificados", ventana=(1993, 1993))
        assert report[CLAVE_DEL_INFORME]["a revisión"] == 1
        assert fila["fecha_inicial"] == "17/01/1993"

    def test_los_anios_del_libro_sin_firma_leida_quedan_sin_dato(self):
        fila = _nomina(
            plantilla="certificado", fecha_inicial="01/01/1993", fecha_final="31/12/1994",
            observaciones="fechas: los años 1993 a 1994 del libro: no se leyó la fecha de la firma",
        )
        report = _revisar(
            [fila], [["CERTIFICADO No. 014 HACE CONSTAR"]], habilidad="certificados", ventana=(1993, 1994),
            derivadas=[(True, True)],
        )
        assert report[CLAVE_DEL_INFORME]["sin dato"] == 1
        assert report["review_queue"] == []


# -- 4. las historias ------------------------------------------------------------------------


class TestHistorias:
    def test_acosta_bello_fuera_de_la_ventana_va_a_revision(self):
        """UPD3859727: 1994-2001 en un libro de 1978-1988; el inicial, del código; el final, de la IA."""
        fila = _historia(
            anio_inicial=1994, anio_final=2001,
            observaciones="fecha inicial 1994: el año de ingreso que dice el código 549410044",
        )
        report = _revisar(
            [fila], [["HISTORIA ACADEMICA 1994 2001"]], habilidad="historias", ventana=(1976, 1990),
            derivadas=[(True, False)],
        )
        assert report[CLAVE_DEL_INFORME]["a revisión"] == 1
        (entrada,) = report["review_queue"]
        assert "cae fuera de los años del libro (1976-1990)" in entrada["reason"]
        assert (fila["anio_inicial"], fila["anio_final"]) == (1994, 2001)

    def test_el_anio_del_codigo_dentro_de_la_ventana_no_se_pregunta(self):
        juez = JuezDeMentira()
        report = _revisar(
            [_historia(anio_inicial=1980, anio_final=1984)], [["SEGUNDO SEMESTRE 1984"]],
            habilidad="historias", juez=juez, ventana=(1976, 1990), derivadas=[(True, False)],
        )
        assert report[CLAVE_DEL_INFORME]["confirmada"] == 1
        assert juez.preguntas == []

    def test_los_anios_cortos_de_la_hoja_de_notas_se_confirman_con_su_papel(self):
        textos = el_papel_de_la_fila(["AÑO 90 PRIMER SEMESTRE ... AÑO 93"], (1985, 1995))
        report = _revisar([_historia(anio_inicial=1990, anio_final=1993)], [textos], habilidad="historias")
        assert report[CLAVE_DEL_INFORME]["confirmada"] == 1

    def test_un_anio_que_la_hoja_no_dice_no_se_confirma(self):
        """La fila dice 1994; la hoja, «AÑO 90 … AÑO 93»: duda, aunque el lector hubiera deducido 1994."""
        textos = el_papel_de_la_fila(["AÑO 90 PRIMER SEMESTRE ... AÑO 93"], (1985, 1995))
        report = _revisar([_historia(anio_inicial=1990, anio_final=1994)], [textos], habilidad="historias")
        assert report[CLAVE_DEL_INFORME]["a revisión"] == 1

    def test_la_hoja_suelta_corregida_por_la_ia_lleva_su_fecha_exacta_y_su_anio(self):
        juez = JuezDeMentira(
            {
                "fecha_inicial": VeredictoDeDato("no_esta", "Cartagena, 12/03/1991"),
                "fecha_final": VeredictoDeDato("no_esta", "Cartagena, 12/03/1991"),
            }
        )
        fila = _historia(clase="recibo", fecha_exacta="15/08/1991", anio_inicial=1991, anio_final=1991)
        report = _revisar(
            [fila], [["RECIBO DE CAJA Cartagena, 12/03/1991 MATRICULA"]], habilidad="historias", juez=juez
        )
        assert report[CLAVE_DEL_INFORME]["corregida"] == 1
        assert (fila["fecha_exacta"], fila["anio_inicial"], fila["anio_final"]) == ("12/03/1991", 1991, 1991)

    def test_la_correccion_de_anios_se_escribe_en_anio_inicial_y_final(self):
        juez = JuezDeMentira({"fecha_final": VeredictoDeDato("no_esta", "EGRESO DEL PROGRAMA EN 1991")})
        fila = _historia(anio_inicial=1980, anio_final=1984)
        _revisar([fila], [["INGRESO 1980 EGRESO DEL PROGRAMA EN 1991"]], habilidad="historias", juez=juez)
        assert (fila["anio_inicial"], fila["anio_final"]) == (1980, 1991)
        assert "fecha final corregida: 1984 → 1991" in fila["observaciones"]

    def test_ni_la_ia_corrige_lo_que_se_aparta_como_el_ocr(self):
        """1984 por 1986: un dígito. El margen de error es duda, nunca corrección."""
        juez = JuezDeMentira({"fecha_final": VeredictoDeDato("no_esta", "EGRESO 1986")})
        fila = _historia(anio_inicial=1980, anio_final=1984)
        report = _revisar([fila], [["INGRESO 1980 EGRESO 1986"]], habilidad="historias", juez=juez)
        assert report[CLAVE_DEL_INFORME]["a revisión"] == 1
        assert fila["anio_final"] == 1984


    def test_el_trabajo_entero_revisa_cada_estudiante_antes_del_fuid(self, tmp_path):
        """De punta a punta: un PDF de dos estudiantes, con «Solo OCR», sale con su revisión de fechas."""
        import fitz
        from test_historia_academica import FICHA_1996, FICHA_2003, NOTAS_1993, NOTAS_2003

        from resolutions.api.worker.historias import historias_academicas_job

        origen = tmp_path / "historias.pdf"
        with fitz.open() as doc:
            for texto in (FICHA_1996, NOTAS_1993, FICHA_2003, NOTAS_2003):
                doc.new_page().insert_textbox(fitz.Rect(30, 30, 560, 800), texto, fontsize=9)
            doc.save(origen)
        informe = historias_academicas_job(
            {
                "job_id": "t", "source": str(origen), "filename": "historias.pdf", "task": "inventory",
                "settings": {"ocr_language": "spa", "output_dir": str(tmp_path / "salida")},
            }
        )
        resumen = informe[CLAVE_DEL_INFORME]
        assert resumen["revisados"] == 2
        assert resumen["corregida"] == 0, "sin IA y sin lector fuerte, los años de una historia no se corrigen"
        assert resumen["revisados"] == sum(resumen[e] for e in ("confirmada", "corregida", "a revisión", "sin dato"))

    def test_la_ficha_no_es_el_papel_de_sus_anios(self, tmp_path):
        """La ficha trae el nacimiento y el año del bachillerato. El trabajo saca los años de las notas, y
        el revisor también: con la ficha, una fila buena iba a Revisión y, con IA, se «corregía» al año
        del bachillerato (la revisión adversarial, 2026-11-10)."""
        import fitz
        from test_historia_academica import FICHA_1996, NOTAS_1993

        from resolutions.api.worker.historias import historias_academicas_job

        # El bachillerato (1987) cae dentro de la ventana de la caja, que da su nombre: 1985-1995.
        ficha = f"{FICHA_1996} Bachiller del colegio INEM. Fecha de Grado: 1987. Fecha de Nacimiento: 12-03-1968"
        origen = tmp_path / "HISTORIAS 1985-1995.pdf"
        with fitz.open() as doc:
            for texto in (ficha, NOTAS_1993):
                doc.new_page().insert_textbox(fitz.Rect(30, 30, 560, 800), texto, fontsize=9)
            doc.save(origen)
        informe = historias_academicas_job(
            {
                "job_id": "t", "source": str(origen), "filename": origen.name, "task": "inventory",
                "settings": {"ocr_language": "spa", "output_dir": str(tmp_path / "salida")},
            }
        )

        resumen = informe[CLAVE_DEL_INFORME]
        motivos = [item["reason"] for item in informe.get("review_queue", []) if "revisor de fechas" in item["reason"]]
        assert resumen["revisados"] == 1
        assert resumen["confirmada"] == 1, motivos
        assert not any("1987" in motivo or "1968" in motivo for motivo in motivos)


# -- 5. nunca tumba el trabajo ---------------------------------------------------------------


class TestNuncaTumbaElTrabajo:
    def test_una_ia_que_no_se_puede_preparar_deja_lo_dudoso_a_revision(self):
        def roto():
            raise RuntimeError("sin llave")

        report: dict = {}
        asegurar_las_fechas(
            report, [_nomina()], [["AÑO 1957"]], habilidad="nominas", taller=SimpleNamespace(juez_de_datos=roto)
        )
        assert report[CLAVE_DEL_INFORME]["a revisión"] == 1

    def test_un_revisor_roto_deja_la_fila_como_estaba_y_sigue_con_la_siguiente(self, monkeypatch, caplog):
        import resolutions.application.revisor_de_fechas as revisor

        original = revisor.revisar_las_fechas
        llamadas = []

        def a_veces_roto(fechas, textos, **kwargs):
            llamadas.append(1)
            if len(llamadas) == 1:
                raise ValueError("fecha imposible")
            return original(fechas, textos, **kwargs)

        monkeypatch.setattr(revisor, "revisar_las_fechas", a_veces_roto)
        primera, segunda = _nomina(), _nomina(archivo_generado="04_OTRA.pdf")
        report = _revisar([primera, segunda], [["AÑO 1957"], ["AÑO 1975"]])
        assert primera["fecha_inicial"] == "01/01/1975"
        assert report[CLAVE_DEL_INFORME]["revisados"] == 1
        assert "el revisor de fechas falló en 03_CASTELLAR" in caplog.text

    def test_la_cancelacion_sube(self):
        class Cancelador(JuezDeMentira):
            def verificar(self, texto, datos):
                raise Cancelled()

        with pytest.raises(Cancelled):
            _revisar([_nomina()], [["AÑO 1957"]], juez=Cancelador())

    def test_la_fila_sin_fechas_cuenta_sin_dato(self):
        report = _revisar([{"tipo": "pdf-entero", "archivo": "X.pdf", "pagina_inicial": 1}], [["NADA"]])
        assert report[CLAVE_DEL_INFORME]["sin dato"] == 1
        assert report["review_queue"] == []

    def test_sin_filas_no_hace_nada(self):
        report: dict = {}
        asegurar_las_fechas(report, [], [], habilidad="historias", taller=_taller())
        assert report == {}


# -- 6. los años de la caja (datos_esperados) ------------------------------------------------


def _caja(*anios) -> list[DatosDeUnaHistoria]:
    return [DatosDeUnaHistoria(nombre=f"ESTUDIANTE {i}", anio_inicial=a, anio_final=b) for i, (a, b) in enumerate(anios)]


LIBRO_1978_1988 = [(1978, 1982), (1979, 1983), (1980, 1984), (1981, 1985), (1982, 1986), (1983, 1987), (1984, 1988), (1980, 1985)]


class TestLosAniosDeLaCaja:
    def test_acosta_bello_es_una_duda_de_sus_fechas(self):
        datos = _caja(*LIBRO_1978_1988, (1994, 2001))
        fuera = fuera_de_los_anios_de_la_caja(datos)
        assert list(fuera) == [8]
        assert (fuera[8].campo, fuera[8].gravedad) == (FECHAS, DUDA)
        assert "1994-2001 caen fuera de los de la caja (1978-1988)" in fuera[8].texto

    def test_un_documento_mal_leido_no_ensancha_la_caja(self):
        assert anios_de_la_caja(_caja(*LIBRO_1978_1988, (1994, 2001))) == (1978, 1988)

    def test_con_pocos_documentos_no_se_dice_nada(self):
        assert fuera_de_los_anios_de_la_caja(_caja(*LIBRO_1978_1988[:6], (1994, 2001))) == {}

    def test_dentro_de_la_holgura_no_es_duda(self):
        assert fuera_de_los_anios_de_la_caja(_caja(*LIBRO_1978_1988, (1986, 1991))) == {}

    def test_entre_documentos_de_historias_y_de_nominas(self):
        datos = _caja(*LIBRO_1978_1988, (1994, 2001))
        assert [h.campo for h in revisar_entre_documentos(datos)[8]] == [FECHAS]
        assert [h.campo for h in revisar_nominas_entre_si(datos)[8]] == [FECHAS]
