"""El agente se asegura antes de dar un dato por faltante: Enfermería, 2026-11-06.

El operador, con la segunda corrida de Enfermería: «mira qué pasó con este
documento que no tomó el código… todavía hay falta de cédulas y de códigos,
verifica bien todo», y «haz que los agentes se aseguren cuando en realidad no
encuentren algo». Lo que se encontró en el papel:

- COTA ZAMBRANO (UPD3859734, 1993): «Código. 54-9010033», con guion, no se
  leía; y su «Fecha de Grado 1989» es la del bachillerato, que adelantaba su
  fecha inicial a 1989 con notas de 1990 a 1993.
- CONDE DIAZ (UPD3859765, Retirados 2003): salió con la cédula 22809768 de
  VILLALOBOS GARI, cuando su ficha la trae en blanco; su código va en «Carné
  Estudiantil N°», y su último año en «Fecha de Deserción».
- SOTO CHAQUIR: «599010022» entre veinte códigos «54…».

Esto fija que se leen, que ningún estudiante se queda con el número de otro, que
lo que falta se busca otra vez -- gratis y, con la IA, sólo lo escrito en el
texto -- y que lo que de verdad no está se dice como tal, también en la
auditoría.
"""

from __future__ import annotations

from types import SimpleNamespace

from resolutions.api.worker.historias import _Asegurador, _sin_numeros_ajenos
from resolutions.application.fuid import FuidRow
from resolutions.application.integridad_de_los_datos import (
    DE_UNA_HISTORIA,
    auditar_los_datos,
    revisar_los_datos,
)
from resolutions.domain.datos_esperados import DatosDeUnaHistoria, revisar_una_historia
from resolutions.domain.historia_academica import (
    EN_BLANCO,
    ILEGIBLE,
    LEIDO,
    Ficha,
    anios_de_la_ficha,
    leer_ficha,
    leer_la_verificacion,
)

#: La ficha de COTA ZAMBRANO como la lee la IA.
COTA = (
    "UNIVERSIDAD DE CARTAGENA ENFERMERIA\nNombre del estudiante Cota Zambrano Andres Eloy\n"
    "Bachiller del colegio: Benjamin Herrera de Arjona Ciudad: Arjona\n"
    "Fecha de Grado. Dic 7 de 1989 Cédula No. 73.556.911 de: Arjona\n"
    "Código. 54-9010033 Libreta Militar: 73 556.911 Distrito 14\n"
    "Grado en el mes de: Diciembre 10/93 Fecha:\nActa número: Diploma número:"
)
#: La de CONDE DIAZ: la identificación en blanco.
CONDE = (
    "Ficha Historia Académica de Estudiante\nApellidos: Conde Diaz Nombres: Alix Stella\n"
    "Documento de Identificación: C. C. ( ) T.I ( ) Cedula Extranjería ( ) Pasaporte ( )\nN° Expedida en:\n"
    "Teléfono(s): 6710073\nAño de ingreso 2003 Período de Ingreso 1°. (X)\n"
    "Puesto de Ingreso N° 20 Carné Estudiantil N°: 5420030020\n"
    "Fecha de Graduación: / / Acta N°\nFecha de Deserción: I /PA /2004 Motivo: Problemas familiares"
)
VILLALOBOS = (
    "ESTUDIANTE Villalobos Gari Yesenia del Carmen SEXO F ESTADO CIVIL Soltera "
    "CEDULA No. 22'809.768 LIB. MILITAR"
)


def _historia(**cambios) -> DatosDeUnaHistoria:
    datos = {
        "nombre": "AGUAS GARRIDO CLARENA LUCIA",
        "identificacion": "45755189",
        "tipo_de_identificacion": "cédula",
        "codigo": "549310044",
        "anio_inicial": 1993,
        "anio_final": 1996,
    }
    return DatosDeUnaHistoria(**{**datos, **cambios})


def _fila(**cambios) -> dict:
    datos = {
        "tipo": "HISTORIA ACADEMICA",
        "nombre": "AGUAS GARRIDO CLARENA LUCIA",
        "cedula": "45755189",
        "codigo": "549310044",
        "anio_inicial": 1993,
        "anio_final": 1996,
        "pagina_inicial": 3,
        "pagina_final": 6,
        "archivo_generado": "02_AGUAS-GARRIDO-CLARENA-LUCIA-45755189.pdf",
    }
    return {**datos, **cambios}


def _del_fuid(asunto, inicial, final, desde, hasta) -> FuidRow:
    return FuidRow(
        orden=1, asunto=asunto, consecutivo_inicial=inicial, consecutivo_final=final, fecha_inicial=desde, fecha_final=hasta
    )


class TestLaLecturaDeLasFichas:
    def test_el_codigo_con_guion_y_sin_el_grado_del_bachillerato(self):
        ficha = leer_ficha(COTA)
        assert (ficha.cedula, ficha.codigo, ficha.libreta) == ("73556911", "549010033", None)
        # 1989 es cuando salió del colegio: su carrera va de 1990 a 1993.
        assert anios_de_la_ficha(COTA) == (None, 1993)
        assert ficha.anio_de_grado is None

    def test_la_ficha_de_2003(self):
        ficha = leer_ficha(CONDE)
        assert (ficha.identificacion, ficha.codigo) == (None, "5420030020")
        assert anios_de_la_ficha(CONDE) == (2003, 2004)
        con_cedula = leer_ficha(CONDE.replace("N° Expedida", "N° 1.047.382.991 Expedida"))
        assert con_cedula.identificacion == ("cédula", "1047382991")
        con_tarjeta = leer_ficha(CONDE.replace("T.I ( )", "T.I (X)").replace("N° Expedida", "N° 86022203314 Expedida"))
        assert con_tarjeta.identificacion[0] == "tarjeta de identidad"


class TestLaRespuestaDeLaIa:
    def test_solo_se_toma_lo_que_esta_escrito(self):
        respuesta = (
            '```json\n{"cedula": "VACIO", "tarjeta": "VACIO", "libreta": "NO_APARECE", "codigo": "5420030020", '
            '"anio_ingreso": "2003", "anio_final": "2004"}\n```'
        )
        v = leer_la_verificacion(respuesta, CONDE)
        assert v.estados["cedula"] == EN_BLANCO and v.estados["codigo"] == LEIDO
        assert v.numeros == {"codigo": "5420030020"}
        assert (v.anio_ingreso, v.anio_final) == (2003, 2004)
        # Un número que el texto no trae no se toma: alguien tiene que mirarlo.
        inventada = leer_la_verificacion('{"cedula": "22809768", "anio_final": "2010"}', CONDE)
        assert inventada.estados["cedula"] == ILEGIBLE and "cedula" not in inventada.numeros
        assert inventada.anio_final is None
        # Con sus separadores de miles también está escrito.
        assert leer_la_verificacion('{"cedula": "22809768"}', VILLALOBOS).numeros == {"cedula": "22809768"}

    def test_una_respuesta_rota_no_inventa_nada(self):
        v = leer_la_verificacion("no sé", CONDE)
        assert v.numeros == {} and v.anio_ingreso is None


class TestLoQueFaltaVerificado:
    def test_en_blanco_no_es_una_duda(self):
        datos = _historia(
            identificacion=None,
            tipo_de_identificacion=None,
            verificado={"cedula": "en blanco", "tarjeta": "en blanco", "libreta": "no aparece"},
        )
        [hallazgo] = revisar_una_historia(datos, este_anio=2026)
        assert hallazgo.gravedad == "en blanco" and "verificado" in hallazgo.texto

    def test_ilegible_y_sin_verificar_son_para_mirar(self):
        [ilegible] = revisar_una_historia(_historia(codigo=None, verificado={"codigo": "ilegible"}), este_anio=2026)
        assert ilegible.gravedad == "duda" and "no se pudo confirmar" in ilegible.texto
        [sin_ia] = revisar_una_historia(_historia(codigo=None, verificado={"codigo": "sin verificar"}), este_anio=2026)
        assert sin_ia.gravedad == "duda" and "sin IA" in sin_ia.texto

    def test_las_casillas_en_blanco_cuentan_aparte(self):
        filas = [
            _fila(
                cedula=None,
                verificado={"cedula": "en blanco", "tarjeta": "en blanco", "libreta": "en blanco"},
                archivo_generado="02_AGUAS-GARRIDO-CLARENA-LUCIA.pdf",
            )
        ]
        integridad = revisar_los_datos(filas, DE_UNA_HISTORIA)
        assert (integridad.completos, integridad.con_dudas, integridad.con_en_blanco) == (1, 0, 1)
        assert integridad.por_campo["identificacion"]["en_blanco"] == 1


class TestEntreDocumentos:
    def test_la_misma_cedula_en_dos_estudiantes_es_un_error(self):
        filas = [
            _fila(nombre="VILLALOBOS GARI YESENIA", cedula="22809768", codigo="549920073", archivo_generado="02_V-22809768.pdf"),
            _fila(nombre="CONDE DIAZ ALIX STELLA", cedula="22809768", codigo="5420030020", archivo_generado="03_C-22809768.pdf"),
        ]
        integridad = revisar_los_datos(filas, DE_UNA_HISTORIA)
        assert integridad.con_errores == 2
        assert any("sale también en 03_C-22809768.pdf" in h["texto"] for h in integridad.hallazgos)

    def test_un_codigo_que_no_empieza_como_los_demas(self):
        nombres = ["ANA PEREZ RUIZ", "LUIS GOMEZ DIAZ", "MARIA LOPEZ SOTO", "JOSE ROJAS VEGA", "ROSA DIAZ MORA", "LUZ VERA PAZ"]
        filas = [
            _fila(nombre=nombre, cedula=f"4550{n:04d}", codigo=f"54901{n:04d}", archivo_generado=f"{n:02d}_X-4550{n:04d}.pdf")
            for n, nombre in enumerate(nombres, start=1)
        ]
        filas.append(
            _fila(
                nombre="SOTO CHAQUIR MERCY", cedula="34998073", codigo="599010022", anio_inicial=1990,
                archivo_generado="27_SOTO-34998073.pdf",
            )
        )
        integridad = revisar_los_datos(filas, DE_UNA_HISTORIA)
        de_soto = [h for h in integridad.hallazgos if h["documento"] == "27_SOTO-34998073.pdf"]
        assert [h["gravedad"] for h in de_soto] == ["duda"]
        assert "no empieza como los demás" in de_soto[0]["texto"]


class _Taller:
    def __init__(self, verificador):
        self._verificador = verificador

    def verificador_de_fichas(self):
        return self._verificador


class _Verificador:
    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.textos: list[str] = []

    def resumir(self, texto):
        self.textos.append(texto)
        return self.respuesta


def _unidad(paginas, ficha):
    return SimpleNamespace(paginas=paginas, pagina_de_la_ficha=paginas[0], ficha=ficha, dudas=[])


class TestElAgenteSeAsegura:
    def test_la_cedula_de_otra_estudiante_se_quita_y_la_ia_dice_que_esta_en_blanco(self):
        textos = [VILLALOBOS, "notas de villalobos", CONDE, "notas de conde"]
        villalobos = _unidad([1, 2], Ficha(nombre="VILLALOBOS GARI YESENIA DEL CARMEN", cedula="22809768", codigo="549920073"))
        conde = _unidad([3, 4], Ficha(nombre="CONDE DIAZ ALIX STELLA", cedula="22809768", codigo="5420030020"))
        verificador = _Verificador('{"cedula": "VACIO", "tarjeta": "VACIO", "libreta": "NO_APARECE", "codigo": "5420030020"}')
        leidas: list[int] = []

        def leer_pagina(numero):
            # El OCR de pago de la ficha: aquí, su texto.
            leidas.append(numero)
            return textos[numero - 1]

        asegurador = _Asegurador(_Taller(verificador), textos, {}, {}, leer_pagina=leer_pagina)

        _sin_numeros_ajenos([villalobos, conde], asegurador)
        asegurador.numeros({}, [villalobos, conde])

        assert villalobos.ficha.cedula == "22809768"
        assert conde.ficha.cedula is None
        assert "es de VILLALOBOS GARI YESENIA DEL CARMEN" in conde.dudas[0]
        assert asegurador.estados[3] == {"cedula": "en blanco", "tarjeta": "en blanco", "libreta": "no aparece"}
        # Sólo se le preguntó por la que le faltaba, sobre una lectura de verdad de su ficha.
        assert len(verificador.textos) == 1 and "Conde Diaz" in verificador.textos[0]
        assert leidas == [3]

    def test_sin_una_lectura_de_verdad_no_se_da_nada_por_verificado(self):
        """Sobre la capa del escáner, la IA decía «no aparece» a lo que estaba (UPD3859734, págs. 13, 26 y 28)."""
        conde = _unidad([1, 2], Ficha(nombre="CONDE DIAZ ALIX STELLA", codigo="5420030020"))
        verificador = _Verificador('{"cedula": "NO_APARECE", "tarjeta": "NO_APARECE", "libreta": "NO_APARECE"}')
        asegurador = _Asegurador(_Taller(verificador), [CONDE, "notas"], {}, {}, leer_pagina=lambda _n: "")
        asegurador.numeros({}, [conde])
        assert verificador.textos == []
        assert set(asegurador.estados[1].values()) == {"sin verificar"}

    def test_lo_que_estaba_en_sus_hojas_se_encuentra_sin_pagar(self):
        cota = _unidad([1, 2], Ficha(nombre="COTA ZAMBRANO ANDRES ELOY", cedula="73556911"))
        verificador = _Verificador("{}")
        asegurador = _Asegurador(_Taller(verificador), [COTA, "notas"], {}, {})
        asegurador.numeros({}, [cota])
        assert cota.ficha.codigo == "549010033"
        assert verificador.textos == []

    def test_sin_ia_se_dice_sin_verificar(self):
        conde = _unidad([1, 2], Ficha(nombre="CONDE DIAZ ALIX STELLA", codigo="5420030020"))
        asegurador = _Asegurador(_Taller(None), [CONDE, "notas"], {}, {})
        asegurador.numeros({}, [conde])
        assert asegurador.estados[1] == {"cedula": "sin verificar", "tarjeta": "sin verificar", "libreta": "sin verificar"}

    def test_los_anios_que_faltan_de_la_ia(self):
        conde = _unidad([1, 2], Ficha(nombre="CONDE DIAZ ALIX STELLA"))
        verificador = _Verificador('{"anio_ingreso": "2003", "anio_final": "2004"}')
        asegurador = _Asegurador(_Taller(verificador), [CONDE, "notas"], {1: CONDE}, {})
        assert asegurador.anios(conde, 2003, None) == (2003, 2004, "fechas extremas completadas al verificar la ficha con la IA")
        assert asegurador.anios(conde, 2003, 2004)[2] is None


class TestLaAuditoriaSabeLoVerificado:
    def test_la_casilla_en_blanco_no_es_duda_en_la_muestra(self):
        fuid = [_del_fuid("CONDE DIAZ ALIX STELLA", "N/A", "5420030020", "01/01/2003", "31/12/2004")]
        pdf = "UPD/03_CONDE-DIAZ-ALIX-STELLA.pdf"
        _, dudas = auditar_los_datos([pdf], fuid, DE_UNA_HISTORIA)
        assert dudas  # sin saber nada, para mirar
        errores, dudas = auditar_los_datos(
            [pdf],
            fuid,
            DE_UNA_HISTORIA,
            verificados={"03_CONDE-DIAZ-ALIX-STELLA.pdf": {"cedula": "en blanco", "tarjeta": "en blanco", "libreta": "en blanco"}},
        )
        assert (errores, dudas) == ([], [])

    def test_la_cedula_imposible_con_su_tipo_de_la_constancia(self):
        """PAJARO MARTINEZ: «415467824» en el FUID; en el papel, 45.467.824. Sólo con el tipo se sabe que no es una cédula."""
        fuid = [_del_fuid("PAJARO MARTINEZ EDELIA MARIA", "415467824", "549010014", "01/01/1990", "31/12/1993")]
        pdf = "UPD/17_PAJARO-MARTINEZ-EDELIA-MARIA-415467824.pdf"
        assert auditar_los_datos([pdf], fuid, DE_UNA_HISTORIA)[0] == []
        errores, _ = auditar_los_datos(
            [pdf], fuid, DE_UNA_HISTORIA, tipos={"17_PAJARO-MARTINEZ-EDELIA-MARIA-415467824.pdf": "cédula"}
        )
        assert errores == ["«17_PAJARO-MARTINEZ-EDELIA-MARIA-415467824.pdf»: la cédula 415467824 tiene 9 cifras: ninguna cédula tiene tantas"]

    def test_la_misma_cedula_en_dos_filas_del_fuid(self):
        fuid = [
            _del_fuid("VILLALOBOS GARI YESENIA", "22809768", "549920073", "01/01/1999", "31/12/2002"),
            _del_fuid("CONDE DIAZ ALIX STELLA", "22809768", "5420030020", "01/01/2003", "31/12/2004"),
        ]
        errores, _ = auditar_los_datos(["UPD/03_CONDE-DIAZ-ALIX-STELLA-22809768.pdf"], fuid, DE_UNA_HISTORIA)
        assert any("sale también en VILLALOBOS GARI YESENIA" in e for e in errores)


class TestNadaQueNoEsteEnSuCasilla:
    def test_el_telefono_no_pasa_por_cedula(self):
        """Con la casilla de la cédula en blanco, la IA podía dar el teléfono de al lado."""
        from resolutions.domain.historia_academica import junto_a_su_rotulo

        assert not junto_a_su_rotulo("6710073", CONDE, "cedula")
        assert leer_la_verificacion('{"cedula": "6710073"}', CONDE).estados["cedula"] == ILEGIBLE
        assert junto_a_su_rotulo("22809768", VILLALOBOS, "cedula")
        assert junto_a_su_rotulo("5420030020", CONDE, "codigo")
        # Escritos al margen con su sigla: «#CC: 1042 381 187», «#5420520027» (TORRES PARERNINA).
        margen = "Ficha Historia Académica #5420520027 Apellidos: Torres #CC: 1042 381 187"
        assert junto_a_su_rotulo("1042381187", margen, "cedula") and junto_a_su_rotulo("5420520027", margen, "codigo")

    def test_en_blanco_dicho_de_cualquier_forma(self):
        """MONCADA salía «ilegible» con su cédula en blanco: la IA no siempre dice VACIO."""
        v = leer_la_verificacion('{"cedula": "N/A", "tarjeta": "—", "libreta": "( )", "codigo": "No registra"}', CONDE)
        assert set(v.estados.values()) == {EN_BLANCO}
        assert leer_la_verificacion('{"cedula": null}', CONDE).estados["cedula"] == "no aparece"
        assert leer_la_verificacion('{"cedula": "ilegible"}', CONDE).estados["cedula"] == ILEGIBLE


class TestElPatronDeLaCaja:
    NOMBRES = [
        "ALVAREZ CUADRADO INDIRA", "ANDRADE MADIEDO NAPOLEON", "ARRIETA SAA INDIRA", "BONFANTE ZARATE MARILYN",
        "GUERRA AROCHA LILLYSTH", "TEHERAN ROTA LORETT", "MANJARRES MORENO ALBA", "PENA GUZMAN JOSE",
        "PERDOMO HERNANDEZ MIRIAM", "CASTRO REYES JACQUELINE", "RIOS DIAZ MARIA", "ROBLES ROYET ROCIO",
        "RUIZ BALLESTA YANINE", "SANTOS ARRIETA LIGIA", "SOTO CHAQUIR MERCY", "VALDERRAMA PEREZ LUZ",
    ]

    def test_el_nombre_fuera_del_orden_alfabetico(self):
        """Entre PERDOMO y RIOS el papel dice «Reyes Castro Jacqueline»."""
        from resolutions.domain.datos_esperados import revisar_entre_documentos

        hallazgos = revisar_entre_documentos([DatosDeUnaHistoria(nombre=n) for n in self.NOMBRES])
        fuera = {self.NOMBRES[i] for i in hallazgos}
        assert fuera == {"TEHERAN ROTA LORETT", "CASTRO REYES JACQUELINE"}
        assert "orden alfabético" in hallazgos[9][0].texto

    def test_una_caja_sin_orden_no_se_juzga(self):
        from resolutions.domain.datos_esperados import revisar_entre_documentos

        desordenados = ["MONCADA R A", "VILLALOBOS G Y", "CONDE D A", "MARTINEZ V M", "ORTEGA G H", "PADILLA D A",
                        "QUINTANA J A", "RAMIREZ R K", "SANCHEZ J J", "GARCIA T B", "HERNANDEZ C K", "TORRES P H"]
        assert revisar_entre_documentos([DatosDeUnaHistoria(nombre=n) for n in desordenados]) == {}

    def test_el_codigo_se_corrige_con_dos_pruebas(self):
        from resolutions.domain.datos_esperados import (
            codigo_por_el_patron,
            patron_de_los_codigos,
        )

        patron = patron_de_los_codigos([f"5490100{n:02d}" for n in range(20)])
        assert patron == "54"
        assert codigo_por_el_patron("599010022", patron, 1990) == "549010022"  # SOTO CHAQUIR
        assert codigo_por_el_patron("649010005", patron, 1990) == "549010005"  # VALDERRAMA
        assert codigo_por_el_patron("599010022", patron, 1996) is None  # el año no cuadra
        assert codigo_por_el_patron("689010022", patron, 1990) is None  # dos cifras distintas
        assert codigo_por_el_patron("549010022", patron, 1990) is None  # ya está bien
        assert patron_de_los_codigos(["549010022", "649010005"]) is None  # muy pocos para saberlo

    def test_los_apellidos_al_derecho_por_el_orden_de_la_caja(self):
        """«CASTRO REYES» entre PERDOMO y RIOS es «Reyes Castro» en el papel; TEHERAN no se arregla trocando."""
        from resolutions.domain.datos_esperados import apellidos_al_derecho

        corregidos = apellidos_al_derecho(self.NOMBRES)
        assert corregidos == {9: "REYES CASTRO JACQUELINE"}

    def test_dos_vecinos_que_empiezan_igual_no_rompen_el_orden(self):
        """El archivista pone ESPRIELLA antes de ESPAÑA: no es un error."""
        from resolutions.domain.datos_esperados import revisar_entre_documentos

        nombres = ["AGUAS G", "ALMANZA A", "AREVALO S", "AVILA C", "BALLESTAS L", "BARRIOS S", "BENITEZ P",
                   "CASIANI C", "ESPRIELLA M", "ESPANA G", "GALARCIO M", "JIMENEZ B"]
        assert revisar_entre_documentos([DatosDeUnaHistoria(nombre=n) for n in nombres]) == {}


class TestLaFichaDe2003:
    def test_la_tabla_de_periodos_cuando_el_ingreso_va_en_blanco(self):
        """QUINTANA JIMENEZ: «Año de ingreso» en blanco, la tabla dice 03 II y 04 I."""
        texto = (
            "Apellidos: Quintana Jimenez Nombres: Amaury del Jesus\nAño de ingreso Período de Ingreso 1°. ( ) 2°. ( )\n"
            "| Periodo Académico | Año | Periodo | Año | Periodo |\n| | 03 | II | 04 | I |\nFecha de Graduación: / / Acta N°"
        )
        assert anios_de_la_ficha(texto) == (2003, 2004)

    def test_por_que_no_se_tomo_el_numero_de_la_ia(self):
        v = leer_la_verificacion('{"cedula": "6710073", "tarjeta": "20", "codigo": "99887766"}', CONDE)
        assert v.motivos == {
            "cedula": "un número de otra casilla (TELEFONO)",
            "tarjeta": "la IA dio un número de 2 cifras, de otra casilla",
            "codigo": "un número que el texto no trae",
        }
        # El número corto -- el «Puesto de Ingreso N° 20» de CONDE -- es de otra casilla: la suya, en blanco.
        assert v.estados["tarjeta"] == EN_BLANCO
