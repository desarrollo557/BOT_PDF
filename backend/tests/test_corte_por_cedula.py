"""Cortar un libro de diplomas por número de cédula en vez de por folio.

El operador puede elegir con qué señal del papel se parte su libro, porque no
todos los empastes están armados igual y quien lo tiene delante lo sabe:

* **Por folio** — la unidad es la *hoja de papel*. La cara que lleva folio
  escrito en la esquina abre documento; la que llega con la esquina limpia es su
  vuelta y va en el mismo archivo. Se decide contando tinta, sin leer.
* **Por cédula** — la unidad es la *persona*. Mientras la cédula no cambie, las
  caras son del mismo documento; cuando aparece otra, empieza uno nuevo.

Lo que se fija aquí es que las dos den lo que prometen, que ninguna corte por lo
que falta, y que el inventario cuente exactamente lo mismo que la carpeta.
"""

from resolutions.application.diploma_fuid import filas_del_libro
from resolutions.application.diploma_split import group_by_record
from resolutions.domain.diploma import (
    CriterioDeCorte,
    DiplomaRecord,
    mismo_graduado,
)
from resolutions.domain.folio_manuscrito import MarcaDeFolio

POR_CEDULA = CriterioDeCorte.CEDULA
POR_FOLIO = CriterioDeCorte.FOLIO
POR_PERSONA = CriterioDeCorte.NOMBRE_Y_CEDULA


def cara(pagina, cedula=None, marca=MarcaDeFolio.AUSENTE):
    """Una cara del libro. Por omisión, con la esquina limpia."""
    return DiplomaRecord(
        page_number=pagina,
        identity_number=cedula,
        folio_mark=marca,
        name="ANA MARIA GOMEZ" if cedula else None,
    )


def paginas(grupos):
    return [grupo.page_numbers for grupo in grupos]


class TestLaCedulaDecideDondeTerminaCadaDocumento:
    def test_mientras_no_cambie_las_caras_son_del_mismo(self):
        libro = [
            cara(1, "7882907"),
            cara(2, "7882907"),
            cara(3, "7882907"),
        ]
        grupos = group_by_record(libro, POR_CEDULA).groups
        assert paginas(grupos) == [[1, 2, 3]]
        assert grupos[0].code.value == "7882907"

    def test_cuando_aparece_otra_empieza_un_documento(self):
        libro = [
            cara(1, "7882907"),
            cara(2, "7882907"),
            cara(3, "45437535"),
            cara(4, "45437535"),
        ]
        grupos = group_by_record(libro, POR_CEDULA).groups
        assert paginas(grupos) == [[1, 2], [3, 4]]
        assert [grupo.code.value for grupo in grupos] == ["7882907", "45437535"]

    def test_una_cara_por_persona_tambien_vale(self):
        """El caso del libro 7: cada cara es el diploma de otro graduado."""
        libro = [cara(n, f"908995{n}") for n in range(1, 7)]
        grupos = group_by_record(libro, POR_CEDULA).groups
        assert paginas(grupos) == [[1], [2], [3], [4], [5], [6]]

    def test_la_esquina_ya_no_pinta_nada(self):
        """Cortando por cédula, la tinta de la esquina no decide.

        Es la diferencia de fondo entre los dos criterios, y conviene fijarla:
        aquí la unidad es la persona, no la hoja, así que una cara con folio
        escrito se une igual si es del mismo graduado.
        """
        libro = [
            cara(1, "7882907", MarcaDeFolio.PRESENTE),
            cara(2, "7882907", MarcaDeFolio.PRESENTE),
        ]
        assert paginas(group_by_record(libro, POR_CEDULA).groups) == [[1, 2]]
        # Y por folio, esas dos marcas son dos documentos.
        assert paginas(group_by_record(libro, POR_FOLIO).groups) == [[1], [2]]


class TestNadaCortaPorLoQueFalta:
    """La norma de la casa sobrevive al cambio de criterio.

    Sólo la evidencia positiva corta. La ausencia de un dato nunca es evidencia,
    porque partir un documento en dos deja dos archivos de media hoja que nadie
    reconoce, mientras que unir de más deja una hoja señalada en la cola de
    revisión.
    """

    def test_una_cara_sin_cedula_se_queda_con_el_documento_abierto(self):
        libro = [
            cara(1, "7882907"),
            cara(2, None),
            cara(3, None),
        ]
        assert paginas(group_by_record(libro, POR_CEDULA).groups) == [[1, 2, 3]]

    def test_una_cedula_que_no_se_sostiene_tampoco_corta(self):
        """`30761` son cinco dígitos: no es una cédula, es un fragmento.

        Compararla con la del documento abierto es exactamente lo que partía los
        libros de más cuando esta comprobación se probó la primera vez.
        """
        libro = [
            cara(1, "7882907"),
            cara(2, "30761"),
        ]
        assert paginas(group_by_record(libro, POR_CEDULA).groups) == [[1, 2]]

    def test_una_cedula_creible_si_abre_aunque_el_anterior_no_tuviera(self):
        """El caso contrario: unir aquí escondería a un graduado identificado.

        El archivo se llamaría por su orden y esa cédula no aparecería en
        ninguna parte. Abrir deja las dos caras visibles, cada una con su fila.
        """
        libro = [
            cara(1, None),
            cara(2, "7882907"),
        ]
        grupos = group_by_record(libro, POR_CEDULA).groups
        assert paginas(grupos) == [[1], [2]]
        assert grupos[1].code.value == "7882907"


class TestElInventarioCuentaLoMismoQueLaCarpeta:
    """Un archivo, una fila. Si no cuadraran, el FUID prometería de más.

    Es la misma exigencia que ya tenía el corte por folio, y hay que
    comprobarla otra vez porque ahora hay dos maneras de repartir y las dos
    partes tienen que estar de acuerdo sobre cuál se usó.
    """

    def libro(self):
        return [
            cara(1, "7882907"),
            cara(2, "7882907"),
            cara(3, "45437535"),
            cara(4, None),
            cara(5, "9089958"),
        ]

    def test_hay_una_fila_por_archivo(self):
        grupos = group_by_record(self.libro(), POR_CEDULA).groups
        filas = filas_del_libro(
            self.libro(), nombre_del_archivo="UPD3859766.pdf", criterio=POR_CEDULA
        )
        assert len(filas) == len(grupos) == 3

    def test_y_cada_fila_cuenta_los_folios_que_tiene_su_archivo(self):
        grupos = group_by_record(self.libro(), POR_CEDULA).groups
        filas = filas_del_libro(
            self.libro(), nombre_del_archivo="UPD3859766.pdf", criterio=POR_CEDULA
        )
        assert [fila.folios for fila in filas] == [len(g.page_numbers) for g in grupos]

    def test_el_criterio_equivocado_descuadraria(self):
        """La comprobación que hace útil a las dos de arriba.

        Sin pasarle el criterio, el FUID reparte por folio mientras la carpeta
        reparte por cédula, y el inventario deja de describir lo entregado.
        """
        grupos = group_by_record(self.libro(), POR_CEDULA).groups
        por_folio = filas_del_libro(self.libro(), nombre_del_archivo="UPD3859766.pdf")
        assert len(por_folio) != len(grupos)


class TestElCriterioQueLlegaPorLaApi:
    def test_por_omision_cada_cara_es_un_diploma(self):
        """La regla del operador, dada con dos libros reales delante: «cada
        página es un diploma diferente». Es lo que describe su corpus entero, y
        por eso es lo que se hace cuando nadie dice otra cosa."""
        assert CriterioDeCorte.parse(None) is CriterioDeCorte.PAGINA
        assert CriterioDeCorte.parse("") is CriterioDeCorte.PAGINA

    def test_se_entienden_los_dos_nombres(self):
        assert CriterioDeCorte.parse("folio") is POR_FOLIO
        assert CriterioDeCorte.parse("cedula") is POR_CEDULA
        assert CriterioDeCorte.parse("  CEDULA  ") is POR_CEDULA

    def test_lo_desconocido_no_se_adivina(self):
        """Resolverlo como "por folio" devolvería una carpeta cortada por donde
        el operador no pidió, y sin nada que lo dijera."""
        try:
            CriterioDeCorte.parse("por-cedula-mas-o-menos")
        except ValueError as error:
            assert "folio" in str(error) and "cedula" in str(error)
        else:  # pragma: no cover
            raise AssertionError("un criterio inventado tiene que fallar")


def persona(pagina, cedula=None, nombre=None):
    """Una cara con su nombre propio, para el criterio que compara los dos.

    Distinta de `cara`, que pone siempre el mismo nombre de relleno: aquí el
    nombre es justamente una de las dos señales que deciden, así que cada
    prueba tiene que poder darle el suyo.
    """
    return DiplomaRecord(
        page_number=pagina,
        identity_number=cedula,
        name=nombre,
        folio_mark=MarcaDeFolio.AUSENTE,
    )


class TestDosNombresLeidosPorUnEscaner:
    """Comparar nombres es comparar personas leídas, no cadenas.

    Exigir igualdad exacta diría que cada nombre mal leído es otro graduado, y
    en estos libros el nombre está escrito a mano sobre un formulario impreso.
    """

    def test_el_dano_del_escaner_dentro_de_las_palabras_se_perdona(self):
        """Ceros por oes, eles por íes: el ruido típico de un escaneo."""
        assert mismo_graduado(
            "ALBERTO FERNANDEZ PADILLA", "ALBERT0 FERNANDEZ PADILIA"
        )

    def test_los_acentos_y_las_mayusculas_no_cuentan(self):
        assert mismo_graduado("JOSÉ MARÍA GÓMEZ", "jose maria gomez")

    def test_un_apellido_que_no_se_leyo_no_hace_otra_persona(self):
        """Pasa cuando una de las dos caras corta el nombre por el margen."""
        assert mismo_graduado("JUAN PEREZ", "JUAN PEREZ GOMEZ")

    def test_dos_personas_distintas_no_pasan_por_una(self):
        """El caso que tumbó la primera versión de esta comparación.

        Midiendo la distancia entre los nombres enteros, "GOMEZ" contra "LOPEZ"
        son dos ediciones sobre dieciséis caracteres -- menos que muchas erratas
        de OCR --, así que cualquier tolerancia que perdonara un apellido mal
        leído perdonaba también uno distinto. Comparando palabra por palabra,
        GOMEZ simplemente no tiene pareja.
        """
        assert not mismo_graduado("JUAN PEREZ GOMEZ", "JUAN PEREZ LOPEZ")
        assert not mismo_graduado("ANTONIA RUEDA PENA", "ALVARO RHOADS REZA")

    def test_un_apellido_sustituido_entero_se_lee_como_otra_persona(self):
        """Y conviene fijar también lo que esta regla **no** resuelve.

        Cuando el OCR cambia un apellido entero -- "PADILLA" devuelto "PUCELA"
        -- no hay forma barata de distinguirlo de un hermano, y aquí se cuenta
        como otra persona. Por eso el criterio no corta sólo con el nombre:
        hace falta que la cédula también sea otra.
        """
        assert not mismo_graduado(
            "ALBERTO FERNANDEZ PADILLA", "ALBERTO FERNANDEZ PUCELA"
        )

    def test_un_nombre_que_falta_no_es_igual_a_nada(self):
        """Ni igual ni distinto: es una ausencia, y quien pregunta decide."""
        assert not mismo_graduado(None, "JUAN PEREZ")
        assert not mismo_graduado("JUAN PEREZ", "")


class TestCortarPorNombreYCedulaALaVez:
    """El criterio prudente: hacen falta **las dos** señales para partir.

    Lo pidió el operador -- "que divida por nombre diferente, y que tenga cedula
    diferente" -- y resuelve el problema que tiene el corte por cédula sola: la
    cédula de estos libros está manuscrita y el OCR le come dígitos, así que un
    número mal leído partía un documento por la mitad.
    """

    def test_otro_nombre_y_otra_cedula_abren_documento(self):
        libro = [
            persona(1, "7882907", "ALBERTO FERNANDEZ PADILLA"),
            persona(2, "45437535", "ANTONIA RUEDA PENA"),
        ]
        assert paginas(group_by_record(libro, POR_PERSONA).groups) == [[1], [2]]

    def test_el_mismo_graduado_se_queda_junto(self):
        libro = [
            persona(1, "7882907", "ALBERTO FERNANDEZ PADILLA"),
            persona(2, "7882907", "ALBERTO FERNANDEZ PADILLA"),
        ]
        assert paginas(group_by_record(libro, POR_PERSONA).groups) == [[1, 2]]

    def test_una_cedula_mal_leida_ya_no_parte_el_documento(self):
        """El caso que justifica todo este criterio.

        El nombre dice que es el mismo graduado; el número dice que no. Lo que
        cambió fue el OCR, no la persona, y la cara se queda donde estaba.
        Cortando sólo por cédula, esta misma pareja se parte en dos.
        """
        libro = [
            persona(1, "7882907", "ALBERTO FERNANDEZ PADILLA"),
            persona(2, "7862907", "ALBERTO FERNANDEZ PADILLA"),
        ]
        assert paginas(group_by_record(libro, POR_PERSONA).groups) == [[1, 2]]
        assert paginas(group_by_record(libro, POR_CEDULA).groups) == [[1], [2]]

    def test_un_nombre_mal_leido_tampoco(self):
        """Y el simétrico: misma cédula, nombre que el escáner destrozó."""
        libro = [
            persona(1, "7882907", "ALBERTO FERNANDEZ PADILLA"),
            persona(2, "7882907", "A1BERT0 FERNANDEZ PADI11A"),
        ]
        assert paginas(group_by_record(libro, POR_PERSONA).groups) == [[1, 2]]

    def test_sin_las_dos_senales_la_cara_se_une(self):
        """La norma de la casa: la ausencia de un dato nunca es evidencia."""
        libro = [
            persona(1, "7882907", "ALBERTO FERNANDEZ PADILLA"),
            persona(2, "45437535", None),
            persona(3, None, "ANTONIA RUEDA PENA"),
        ]
        assert paginas(group_by_record(libro, POR_PERSONA).groups) == [[1, 2, 3]]

    def test_una_cara_identificada_no_se_esconde_en_un_documento_sin_nombre(self):
        libro = [
            persona(1, None, None),
            persona(2, "7882907", "ALBERTO FERNANDEZ PADILLA"),
        ]
        grupos = group_by_record(libro, POR_PERSONA).groups
        assert paginas(grupos) == [[1], [2]]
        assert grupos[1].code.value == "7882907"


class TestElInventarioSigueCuadrandoConLaCarpeta:
    def test_una_fila_por_archivo_tambien_con_este_criterio(self):
        libro = [
            persona(1, "7882907", "ALBERTO FERNANDEZ PADILLA"),
            persona(2, "7882907", "ALBERTO FERNANDEZ PADILLA"),
            persona(3, "45437535", "ANTONIA RUEDA PENA"),
        ]
        grupos = group_by_record(libro, POR_PERSONA).groups
        filas = filas_del_libro(
            libro, nombre_del_archivo="UPD3859766.pdf", criterio=POR_PERSONA
        )
        assert len(filas) == len(grupos) == 2
        assert [fila.folios for fila in filas] == [2, 1]


class TestElTercerCriterioLlegaPorLaApi:
    def test_se_entiende_su_nombre(self):
        assert CriterioDeCorte.parse("nombre-cedula") is POR_PERSONA

    def test_y_tiene_etiqueta_para_la_pantalla(self):
        assert POR_PERSONA.label == "Por nombre y cédula"

    def test_el_error_nombra_los_tres(self):
        try:
            CriterioDeCorte.parse("por-lo-que-sea")
        except ValueError as error:
            mensaje = str(error)
            assert "folio" in mensaje
            assert "cedula" in mensaje
            assert "nombre-cedula" in mensaje
        else:  # pragma: no cover
            raise AssertionError("un criterio inventado tiene que fallar")
