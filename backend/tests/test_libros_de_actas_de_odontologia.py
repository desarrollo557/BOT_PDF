"""Los libros de actas de grado de Odontología de 1952 a 1999 (caja 3194-3198, 2026-11-27).

Medido hoja por hoja con «Solo OCR» sobre los diez libros de «ACTAS DE GRADO»:
los ocho «ACTAS DECADA.» de 1980 a 1999 traen, cosido entre las actas del
formulario, lo que hasta hoy iba pegado al graduado de delante -- la lista de
alumnos del semestre o de la promoción, la portada «ACTAS» de cada ceremonia,
la copia del acta del Consejo Directivo de 1980, la carta con que un graduado
autoriza a otro a recibir su diploma, la constancia de calificaciones --; los
dos manuscritos de 1952-1971 son exámenes de grado que sólo lee la IA.

Los textos tienen la forma del papel y de su capa; los nombres y las cédulas
son inventados. Ninguna prueba llama a un proveedor de pago.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from resolutions.adapters.fuid_actas_de_grado import fila_de_la_ceremonia
from resolutions.adapters.fuid_de_la_entrega import PDF_ENTERO as PDF_ENTERO_DEL_FUID
from resolutions.adapters.fuid_de_la_entrega import filas_del_fuid
from resolutions.application.acta_consejo import (
    GRADO,
    PDF_ENTERO,
    SE_ENTREGA_ENTERO,
    SIN_IA_EL_MANUSCRITO,
    FilaDeActa,
    InventariarActa,
    _con_el_titulo_del_libro,
    _listas_con_su_anio,
    nombre_de_la_sesion,
    resultado_de_cada_acta,
)
from resolutions.application.ports import OcrResult
from resolutions.domain.acta_grado import (
    DOCTOR_EN_ODONTOLOGIA,
    actas_de_grado_del_pdf,
    calificaciones_del_alumno,
    clase_de_hoja,
    documento_de_una_persona,
    encabezado_de_la_ceremonia,
    es_portada,
    examen_de_grado,
    leer_acta_de_grado,
    numero_del_examen,
    titulo_de_la_lista,
    titulo_de_las_hojas,
    titulo_del_examen,
)
from resolutions.domain.graduado import parecido_de_la_letra, sin_el_relleno_del_renglon


def acta(nombre: str, cedula: str, numero: str = "2") -> str:
    """La hoja del formulario de 1980-1999, como la deja la capa del escáner."""
    return (
        "LA UNIVERSIDAD DE CARTAGENA\nCartagena-Colombia\n"
        f"ACTA DE GRADO No. {numero}\n"
        "En la ciudad de Cartagena, a los SEIS (6) días del mes de NOVIEMBRE de mil novecientos ochenta y CUATRO "
        "(1984), se realizó la graduación COLECTIVA en ceremonia SOLEMNE a solicitud del Decano de la Facultad DE "
        "ODONTOLOGIA a la Rectoría, quien autorizó el acto mediante Resolución No. 545 de fecha 6 de NOVIEMBRE de "
        "1984 por medio de la cual, otorga, de acuerdo a la Ley y los Estatutos de la Universidad,\n"
        f"el título de ODONTOLOGO al estudiante {nombre}\nportador de la cédula de ciudadanía\nNo. {cedula}\n"
        "expedida en CARTAGENA (BOLIVAR) a quien se le tomó el juramento de rigor y se le hizo entrega del "
        "Diploma que lo autoriza para el ejercicio de la profesión de ODONTOLOGO según las disposiciones vigentes."
    )


PORTADA = "ACTAS\nNO 198 DE MARZO\nUNIVERSIDAD DE CARTAGENA"
#: La primera hoja de la lista de 1984, con la cabeza revuelta y el año ilegible
#: (1985-1986-1987 TOMO I pág. 2), y su continuación, que sí dice el semestre.
LISTA_1 = (
    "^^^MESTfE DE ODONTOUDGIA - CORRESPONDIENTE AL ler, PERIDO DE 1.93^\n. LISTA DEL\n"
    + "".join(f"{n}.\n79-01{n:02d}\nAPELLIDO{n} SEGUNDO NOMBRE\n" for n in range(1, 13))
)
LISTA_2 = (
    "CONTINUACION DE LA LISTA DE ALUMNOS DEL IX SEMESTRE DE ODONTOLOGIA - ler. P./84\n"
    + "".join(f"{n}.\n79-01{n:02d}\nAPELLIDO{n} SEGUNDO NOMBRE\n" for n in range(36, 46))
)
#: La carta de un graduado que no está en el libro (1996-1998-1999 TOMO II pág. 1).
CARTA = (
    "201\nSINCELEJO, ABRIL 15 DE 1999.\nYo, JULIO ANDRES DE LA HOZ SALCEDO, identificado con cédula de "
    "ciudadanía # 92’111.222 expedida en Sincelejo, autorizo al señor MARIO ENRIQUE COHEN ARTEAGA, identificado "
    "con cédula de ciudadanía # 73’000.111 expedida en la ciudad de Cartagena, para reclamar mi acta de grado."
)
#: La constancia de calificaciones con el nombre a mano sobre la raya.
CONSTANCIA_A_MANO = (
    "UNIVERSIDAD DE CARTAGENA\nEL SECRETARIO ACADEMICO DE LA FACULTAD DE ODONTOLOGIA DE LA UNIVERSIDAD DE "
    "CARTAGENA\nHACE CONSTAR\n______ ^cursó y aprobó\nen esta Facultad, el lo., 2o., 3o. y 10o. semestre de "
    "Odontología, con las siguientes calificaciones;\n1er. SEMESTRE - 1991\n- Bioquímica\nX SEMESTRE - 1995"
)


class TestLaLista:
    """«La lista de la promoción: su PDF y su fila» (el operador, 2026-11-27)."""

    def test_el_titulo_impreso_normalizado(self):
        casos = {
            "LISTA DEL DECIMO SEMESTRE DE ODONTOLOGIA, CORRESPONDIENTE AL PRIMER PERIODO DE 1986\nCOD. No.":
                "LISTA DE ALUMNOS X SEMESTRE DE ODONTOLOGIA - 1 PERIODO 1986",
            # La capa de 1987: «LISTA» leída «USIA», el periodo «PRUER», el año «1387».
            "USIA DEL DECIMa SEiESTBE DE OCOMTai^GIA, CCBRESPaJCIENTE AL PRUER PERIODO DE 1387. I COD. No.":
                "LISTA DE ALUMNOS X SEMESTRE DE ODONTOLOGIA - 1 PERIODO",
            "UNIVERSIDAD DE CARTAGENA\nALUMNOS X SEMESTRE DE ODONTOLOGIA\n2o. periodo de 1996":
                "LISTA DE ALUMNOS X SEMESTRE DE ODONTOLOGIA - 2 PERIODO 1996",
            "PROMOCION 17 DE DICIEMBRE DE 1999\nNo.de Orden No. de Diploma": "PROMOCION 17-12-1999",
            "EGRESADOS EL 12 DE DICIEMBRE DE 1997\n1. PEREZ GOMEZ ANA": "EGRESADOS 12-12-1997",
            "UNIVERSIDAD DE CARTAGENA\nLISTA DE EGRESADOS PROMOCION DICIEMBRE DE 1994\n1. ALEAN":
                "LISTA DE EGRESADOS - PROMOCION 12-1994",
            "RELACION DE EGRESADOS QUE ENTREGARON LAS BANDAS\nNOMBRE FECHA DE DEVOLUCION":
                "RELACION DE EGRESADOS QUE ENTREGARON LAS BANDAS",
        }
        for texto, titulo in casos.items():
            assert titulo_de_la_lista(texto) == titulo, texto
        # La promoción que se cita en una constancia no es la cabeza de una lista.
        assert titulo_de_la_lista("CERTIFICO QUE HE RECIBIDO EL ACTA DE GRADO DE LA PROMOCION DEL 16 DE DICIEMBRE DE 1994") is None

    def test_las_hojas_de_una_lista_se_completan(self):
        assert titulo_de_las_hojas(
            [titulo_de_la_lista(LISTA_1), titulo_de_la_lista(LISTA_2)]
        ) == "LISTA DE ALUMNOS IX SEMESTRE DE ODONTOLOGIA - 1 PERIODO 1984"

    def test_la_lista_y_la_portada_van_en_su_pdf_y_la_lista_con_su_fila(self):
        paginas = [PORTADA, LISTA_1, LISTA_2, acta("ANA MARIA PEREZ GOMEZ", "45.111.222"), acta("LUIS CARLOS DIAZ ROA", "73.111.222")]
        reparto = actas_de_grado_del_pdf(paginas, foliadas=range(1, 6))
        assert [(t.desde, t.hasta, t.ceremonia) for t in reparto.tramos] == [
            (1, 1, True), (2, 3, True), (4, 4, False), (5, 5, False),
        ]
        assert es_portada(PORTADA) and encabezado_de_la_ceremonia([PORTADA]) is None
        lista = leer_acta_de_grado(paginas[1:3])
        assert lista.sesion == "LISTA DE ALUMNOS IX SEMESTRE DE ODONTOLOGIA - 1 PERIODO 1984"
        assert lista.fecha == date(1984, 1, 1)

    def test_la_fila_de_la_lista(self):
        base = {"tipo": "CEREMONIA DE GRADO", "carpeta": "ACTAS DE GRADO", "archivo": "ACTAS DECADA. 1985-1986-1987 TOMO I.pdf",
                "pagina_inicial": 2, "pagina_final": 3}
        lista = fila_de_la_ceremonia({**base, "acta": "LISTA DE ALUMNOS IX SEMESTRE DE ODONTOLOGIA - 1 PERIODO 1984",
                                      "fecha": "01-01-1984"})
        assert lista.asunto == "LISTA DE ALUMNOS IX SEMESTRE DE ODONTOLOGIA - 1 PERIODO 1984"
        assert (lista.consecutivo_inicial, lista.consecutivo_final) == ("N/A", "N/A")
        assert (lista.fecha_inicial, lista.fecha_final) == ("01/01/1984", "31/12/1984")
        promocion = fila_de_la_ceremonia({**base, "acta": "PROMOCION 17-12-1999", "fecha": "17-12-1999"})
        assert (promocion.fecha_inicial, promocion.fecha_final) == ("17/12/1999", "17/12/1999")
        del_mes = fila_de_la_ceremonia({**base, "acta": "LISTA DE EGRESADOS - PROMOCION 12-1994", "fecha": "01-12-1994"})
        assert (del_mes.fecha_inicial, del_mes.fecha_final) == ("01/12/1994", "31/12/1994")
        # La portada y la hoja de la ceremonia siguen sin fila.
        assert fila_de_la_ceremonia({**base, "acta": "CEREMONIA DE GRADO", "fecha": "N/A"}) is None

    def test_el_anio_que_no_se_lee_es_el_de_las_actas_que_la_siguen(self):
        def fila(**datos) -> FilaDeActa:
            return FilaDeActa(archivo="l.pdf", folio_inicial="N/A", folio_final="N/A", folios=1, resumen="N/A", **datos)

        filas = [
            fila(acta="LISTA DE ALUMNOS X SEMESTRE DE ODONTOLOGIA - 2 PERIODO", fecha="N/A", tipo="CEREMONIA DE GRADO"),
            fila(acta="ACTA DE GRADO No. 1", fecha="18-03-1983", tipo="ACTA DE GRADO", pagina_inicial=157),
        ]
        lista = _listas_con_su_anio(filas)[0]
        assert lista.fecha == "01-01-1983"
        assert "es el de las actas que la siguen (pág. 157" in lista.observaciones


class TestLoCosidoEntreLasActas:
    def test_el_acta_del_consejo_directivo_de_1980_es_un_graduado(self):
        """«ACTA No. 782 … verificaran las calificaciones de la alumna … DIAZ» (1980-1984 TOMO I pág. 18)."""
        copia = (
            "ACTA No. 782.-\nRepública de Colombia, Departamento de Bolívar, Universidad de Cartagena, Facultad de "
            "Odontología, en la ciudad de Cartagena, a los 18 días del mes de Diciembre de 1.980, se reunieron en el "
            "Decanato de la Facultad de Odontología los Honorables Miembros del Consejo Directivo con el fin de "
            "acordar lo relacionado con la Graduación de los alumnos del 10o. Semestre, según Resolución No. 527 "
            "emanada de la rectoría, abierta la sesión se nombró una comisión de examinadores para que verificaran "
            "las calificaciones dela alumna ROSA MARIA NAVAS - DIAZ, la cual fué de (3,45), se le hará entrega del "
            "Diploma de Grado que la acredita como ODONTOLOGO CIRUJANO. Es fiel copia del Original."
        )
        assert clase_de_hoja(copia) == "graduado"
        hoja = leer_acta_de_grado([copia])
        assert (hoja.numero, hoja.nombre, hoja.titulo, hoja.fecha) == (
            "782", "ROSA MARIA NAVAS DIAZ", "ODONTOLOGO CIRUJANO", date(1980, 12, 18),
        )
        # El OCR se come la coma de «…, la cual fue de»; y la inicial del medio no acaba el nombre.
        from resolutions.domain.acta_grado import acta_del_consejo_directivo

        sin_coma = copia.replace("ROSA MARIA NAVAS - DIAZ, la cual", "ROSA MARIA NAVAS)!^ cual")
        assert acta_del_consejo_directivo(sin_coma)[1] == "ROSA MARIA NAVAS"
        con_inicial = copia.replace("dela alumna ROSA MARIA NAVAS - DIAZ", "de la alumna ROSA DEL C. NAVAS DIAZ")
        assert acta_del_consejo_directivo(con_inicial)[1] == "ROSA DEL NAVAS DIAZ"
        # La segunda copia de la misma acta va en su PDF; la de otra acta, en el suyo.
        otra = copia.replace("782", "807").replace("ROSA MARIA NAVAS", "LUISA FERNANDA PATERNINA")
        reparto = actas_de_grado_del_pdf([copia, copia, otra], foliadas=[1, 2, 3])
        assert [(t.desde, t.hasta, t.ceremonia) for t in reparto.tramos] == [(1, 2, False), (3, 3, False)]

    def test_la_carta_de_un_graduado_que_no_esta_en_el_libro_va_en_su_pdf_con_su_fila(self):
        paginas = [CARTA, acta("SANDRA MILENA DIAZ CARDENAS", "45.761.923", "01")]
        reparto = actas_de_grado_del_pdf(paginas, foliadas=[1, 2])
        assert [(t.desde, t.hasta, t.ceremonia) for t in reparto.tramos] == [(1, 1, True), (2, 2, False)]
        carta = leer_acta_de_grado(paginas[:1])
        assert carta.sesion == "AUTORIZACION PARA RECIBIR EL DIPLOMA - JULIO ANDRES DE LA HOZ SALCEDO"
        assert (carta.cedula, carta.fecha) == ("92111222", date(1999, 4, 15))
        fila = fila_de_la_ceremonia(
            {"tipo": "CEREMONIA DE GRADO", "acta": carta.sesion, "fecha": "15-04-1999", "cedula": carta.cedula,
             "carpeta": "ACTAS DE GRADO", "archivo": "TOMO II.pdf", "pagina_inicial": 1, "pagina_final": 1,
             "resultado": f"Dividido en 01_{carta.sesion}.pdf"}
        )
        assert fila.asunto == "AUTORIZACION PARA RECIBIR EL DIPLOMA - JULIO ANDRES DE LA HOZ SALCEDO"
        assert (fila.consecutivo_inicial, fila.consecutivo_final, fila.fecha_inicial) == ("N/A", "92111222", "15/04/1999")

    def test_la_carta_del_graduado_va_con_su_acta_delante_o_detras(self):
        suya = acta("JULIO ANDRES DE LA HOZ SALCEDO", "92.111.222")
        otra = acta("SANDRA MILENA DIAZ CARDENAS", "45.761.923")
        # Detrás de su acta: es su anexo.
        detras = actas_de_grado_del_pdf([otra, suya, CARTA], foliadas=[1, 2, 3])
        assert [(t.desde, t.hasta) for t in detras.tramos] == [(1, 1), (2, 3)]
        # Delante de su acta y detrás de la de otro: va con la suya, no con la de delante.
        delante = actas_de_grado_del_pdf([otra, CARTA, suya], foliadas=[1, 2, 3])
        assert [(t.desde, t.hasta) for t in delante.tramos] == [(1, 1), (2, 3)]

    def test_la_carta_que_nombra_el_acta_de_grado_no_es_un_acta(self):
        """«… autorizo a … para recibir en mi nombre … mi Acta de Grado … a los (26) días del mes» (1990-1994 TOMO I pág. 139)."""
        carta = (
            "16 MARTA ELENA BLANCO RUIZ, identificada con Cedula de Ciudadania No 50.111.222 de Cereté, autorizo a "
            "TATIANA BLANCO BLANCO, para recibir en mi nombre los Certificados de Estudios y mi Acta de Grado los "
            "cuales son necesarios para tramitar mi año rural. Para constancia se firma en Cereté, a los Veintiseis "
            "(26) días del mes de Enero de mil novecientos noventa y tres (1.993)."
        )
        assert clase_de_hoja(carta) == "sigue"
        documento = documento_de_una_persona(carta)
        assert (documento.nombre, documento.cedula) == ("MARTA ELENA BLANCO RUIZ", "50111222")
        suya = acta("MARTA ELENA BLANCO RUIZ", "50.111.222", "02")
        otra = acta("SANDRA MILENA DIAZ CARDENAS", "45.761.923", "02")
        assert [(t.desde, t.hasta) for t in actas_de_grado_del_pdf([suya, carta], foliadas=[1, 2]).tramos] == [(1, 2)]
        reparto = actas_de_grado_del_pdf([otra, carta], foliadas=[1, 2], conocidas={"MARTA", "ELENA", "BLANCO", "RUIZ"})
        assert [(t.desde, t.hasta, t.ceremonia) for t in reparto.tramos] == [(1, 1, False), (2, 2, True)]

    def test_la_carta_que_no_dice_de_quien_es_sigue_a_la_de_delante(self):
        """Ante la duda se une: el nombre que el OCR dejó en letras sueltas no separa nada."""
        borrosa = CARTA.replace("JULIO ANDRES DE LA HOZ SALCEDO", "EFBAUI JAJITODIO OLAIFFIE")
        reparto = actas_de_grado_del_pdf(
            [acta("SANDRA MILENA DIAZ CARDENAS", "45.761.923"), borrosa], foliadas=[1, 2], conocidas={"SANDRA", "MILENA", "JULIO"}
        )
        assert [(t.desde, t.hasta) for t in reparto.tramos] == [(1, 2)]

    def test_la_constancia_de_calificaciones_va_con_su_alumno(self):
        paginas = [acta("VICTOR ANDRES MENDOZA TAMARA", "73.165.633", "1"), CONSTANCIA_A_MANO, acta("ANA MARIA PEREZ GOMEZ", "45.111.222", "1")]
        reparto = actas_de_grado_del_pdf(paginas, foliadas=[1, 2, 3])
        # El nombre va a mano: no se lee, y sigue a la de delante.
        assert [(t.desde, t.hasta, t.ceremonia) for t in reparto.tramos] == [(1, 2, False), (3, 3, False)]
        assert calificaciones_del_alumno([CONSTANCIA_A_MANO]) is not None

    def test_la_constancia_de_otro_alumno_va_en_su_pdf_con_su_fila_de_calificaciones(self):
        a_maquina = CONSTANCIA_A_MANO.replace("______ ^cursó", "Que, CARLOS ALBERTO RUIZ MENDOZA, cursó")
        paginas = [acta("ANA MARIA PEREZ GOMEZ", "45.111.222", "1"), a_maquina]
        reparto = actas_de_grado_del_pdf(paginas, foliadas=[1, 2])
        assert [(t.desde, t.hasta, t.ceremonia) for t in reparto.tramos] == [(1, 1, False), (2, 2, True)]
        hecha = calificaciones_del_alumno([a_maquina])
        assert (hecha.nombre, hecha.anio_inicial, hecha.anio_final) == ("CARLOS ALBERTO RUIZ MENDOZA", 1991, 1995)
        outcome = InventariarActa(perfil=GRADO).execute(_Libro(paginas), document_name="ACTAS DECADA. 1996.pdf")
        fila = outcome.filas[1]
        assert (fila.tipo, fila.nombre, fila.especialidad, fila.anio_inicial, fila.anio_final) == (
            "CALIFICACIONES", "CARLOS ALBERTO RUIZ MENDOZA", "ODONTOLOGIA", 1991, 1995,
        )
        assert nombre_de_la_sesion(fila) == "CARLOS ALBERTO RUIZ MENDOZA - ODONTOLOGIA"
        escritas = resultado_de_cada_acta(
            outcome.filas, ["libro/01_ANA.pdf", "libro/02_CARLOS ALBERTO RUIZ MENDOZA - ODONTOLOGIA.pdf"], pidio_dividir=True
        )
        assert escritas[1].archivo_generado == "02_CARLOS ALBERTO RUIZ MENDOZA - ODONTOLOGIA.pdf"

    def test_la_constancia_de_paz_y_salvo_y_la_copia_de_la_cedula(self):
        paz = (
            "UNIVERSIDAD DE CARTAGENA - FACULTAD DE ODONTOLOGIA\nEL COORDINADOR DE CLINICAS HACE C O N S T A R\n"
            "Que el Señor (Srta.) Doctor RAUL ANDRES ESPINOSA TORO, egresado de esta Facultad, se encuentra a PAZ Y "
            "SALVO con la Oficina de Coordinación de Clínicas."
        )
        documento = documento_de_una_persona(paz)
        assert (documento.clase, documento.nombre) == ("CONSTANCIA DE PAZ Y SALVO", "RAUL ANDRES ESPINOSA TORO")
        cedula = (
            "REPUBLICA DE COLOMBIA IDENTIFICACION PERSONAL CEDULA DE CIUDADANIA\nNUMERO 45.111.222\n"
            "apellidos PEREZ GOMEZ nombres ANA MARIA"
        )
        copia = documento_de_una_persona(cedula)
        assert copia.anexo and copia.cedula == "45111222"
        # La copia de la cédula nunca va sola.
        reparto = actas_de_grado_del_pdf([acta("LUIS CARLOS DIAZ ROA", "73.111.222"), cedula], foliadas=[1, 2])
        assert [(t.desde, t.hasta) for t in reparto.tramos] == [(1, 2)]


class TestLaResolucionDeVariasHojas:
    """Cada hoja repite el membrete «Resolución No. … de 1.9…»: una resolución, no una por hoja."""

    HOJA_1 = (
        "UNIVERSIDAD DE CARTAGENA\nCartagena - Colombia\nResolución No. de 1.9\n0 289\nEL RECTOR DE LA UNIVERSIDAD "
        "en uso de sus facultades legales, y CONSIDERANDO: A) Que el Decano mediante Resolución No. 014 del 21 de "
        "febrero/02 ha solicitado autorización para celebrar ceremonia de graduación; RESUELVE: ARTICULO 1o.- "
        "Autorizar la ceremonia de graduación para otorgar el titulo de ODONTOLOGO a los siguientes egresados: "
        "1. PEREZ GOMEZ ANA"
    )
    HOJA_2 = "UNIVERSIDAD DE CARTAGENA\nResolución No. de 1.9 Hoja 2\n33. RUIZ DIAZ LUIS\nARTICULO 2o.- Advertir a los graduandos"

    def test_la_hoja_2_y_el_mismo_numero_van_con_su_resolucion(self):
        reparto = actas_de_grado_del_pdf([self.HOJA_1, self.HOJA_2, acta("ANA PEREZ GOMEZ", "45.111.222")], foliadas=[1, 2, 3])
        assert [(t.desde, t.hasta, t.ceremonia) for t in reparto.tramos] == [(1, 2, True), (3, 3, False)]
        assert encabezado_de_la_ceremonia([self.HOJA_1, self.HOJA_2]).startswith("RESOLUCION 0289 - ")
        misma = self.HOJA_1.replace("0 289", "0 289\nHoja de la misma")
        reparto = actas_de_grado_del_pdf([self.HOJA_1, misma], foliadas=[1, 2])
        assert [(t.desde, t.hasta) for t in reparto.tramos] == [(1, 2)]


class TestElNombrePartidoAlFinalDelRenglon:
    def test_se_une_la_mitad_del_renglon_siguiente(self):
        from resolutions.domain.acta_grado import con_las_palabras_unidas

        assert "LIBARDO ALVAREZ MANTILLA" in con_las_palabras_unidas("al estudiante LIBARDO AL-\nVAREZ MANTILLA portador")
        assert "CARLOS MONSALVE PORTO" in con_las_palabras_unidas("al estudiante CARLOS MON -\nSALVE PORTO portador")
        assert "DORIS DEL SOCORRO" in con_las_palabras_unidas("al estudiante DORIS DEL SO \xad\nCORRO BULA")
        # Un enlace con su guion suelto no se pega a lo que sigue, ni la raya del formulario al rótulo.
        assert con_las_palabras_unidas("Facultad DE -\nCARTAGENA") == "Facultad DE -\nCARTAGENA"
        assert con_las_palabras_unidas("ODONTOLOGO -\nal estudiante") == "ODONTOLOGO -\nal estudiante"
        hoja = acta("LIBARDO AL-\nVAREZ MANTILLA", "73.086.321")
        assert leer_acta_de_grado([hoja]).nombre == "LIBARDO ALVAREZ MANTILLA"


class TestElTituloYElNombreDelLibro:
    def test_el_titulo_mal_leido_es_el_del_libro(self):
        assert parecido_de_la_letra("QD0NT0U3B0", "ODONTOLOGO") >= 0.6
        assert parecido_de_la_letra("ESPECIALISTA EN ORTODONCIA", "ODONTOLOGO") < 0.6

        def fila(titulo: str) -> FilaDeActa:
            return FilaDeActa(archivo="l.pdf", acta="ACTA DE GRADO No. 2", fecha="06-11-1984", folio_inicial="N/A",
                              folio_final="N/A", folios=1, resumen="N/A", tipo="ACTA DE GRADO", titulo=titulo)

        filas = [fila("ODONTOLOGO")] * 6 + [fila("OOONTOLOSO"), fila("CEREMONIA"), fila("ODONTOLOGO DE FECHA"),
                                             fila("ESPECIALISTA EN ORTODONCIA"), fila("")]
        hechas = _con_el_titulo_del_libro(filas)
        assert [f.titulo for f in hechas[6:]] == ["ODONTOLOGO", "ODONTOLOGO", "ODONTOLOGO", "ESPECIALISTA EN ORTODONCIA", "ODONTOLOGO"]
        assert "se leyó «OOONTOLOSO»" in hechas[6].observaciones
        assert "no se leyó" in hechas[10].observaciones
        # En un libro de varias especialidades no se adivina la que no se lee, ni
        # se cambia el género: «ENFERMERO» no es «ENFERMERA» mal leída.
        mezclado = [fila("ENFERMERA")] * 6 + [fila(f"ESPECIALISTA EN SALUD {n}") for n in range(4)] + [fila("FECHA"), fila("ENFERMERO")]
        assert [f.titulo for f in _con_el_titulo_del_libro(mezclado)[10:]] == ["FECHA", "ENFERMERO"]

    def test_la_raya_del_formulario_detras_del_nombre(self):
        casos = {
            "ROCIO CRISTINA MENDOZA BALLESTAS EEMANNMEMNON": "ROCIO CRISTINA MENDOZA BALLESTAS",
            "GUILLERMO DARIO LEGUIZAMO FLOREZ OOAO": "GUILLERMO DARIO LEGUIZAMO FLOREZ",
            "JURYS FUENTES GARCIA ANN": "JURYS FUENTES GARCIA",
            "RODOR ROJAS LEAL ANN ONO": "RODOR ROJAS LEAL",
            "MARTHA LUZ FERNANDEZ GONZALEZ EOE": "MARTHA LUZ FERNANDEZ GONZALEZ",
            # Lo que sí es un apellido se queda.
            "ELSA ANTONIA BOSSA OJEDA": "ELSA ANTONIA BOSSA OJEDA",
            "CARLOS MARIO CANO": "CARLOS MARIO CANO",
            "CECILIA CURE JANNA": "CECILIA CURE JANNA",
            "PELICIANO PUERTA MEZA DORIDOR DE LA DE": "PELICIANO PUERTA MEZA",
            "PELICIANO PUERTA MEZA DORIDOR DE LA DE OBII": "PELICIANO PUERTA MEZA",
            "LUIS CARLOS AMADOR DE LA HOZ": "LUIS CARLOS AMADOR DE LA HOZ",
            "HELLA SOFIA PARDO DURANGO DOIDOR DE LA DE SOSASSB": "HELLA SOFIA PARDO DURANGO",
            "LUIS EDUARDO GRANOBLES SEGOVIA ESOCANECONACA": "LUIS EDUARDO GRANOBLES SEGOVIA",
            "MARIA FERNANDA SANCLEMENTE": "MARIA FERNANDA SANCLEMENTE",
            "LUIS ARMANDO VILA SIERRA NOADOR DE LA DE": "LUIS ARMANDO VILA SIERRA",
            "JORGE LUIS TORRADO": "JORGE LUIS TORRADO",
            "MANUEL JOSE SAAVEDRA": "MANUEL JOSE SAAVEDRA",
            "LIGIA MARGARITA DICKSON LORA": "LIGIA MARGARITA DICKSON LORA",
        }
        for leido, limpio in casos.items():
            assert sin_el_relleno_del_renglon(leido) == limpio, leido


#: Lo que trae la capa de los libros manuscritos: nada que leer.
BASURA = "•V- ) 'ñ (P i*!? ~ ,,"
#: Como transcribe la IA las actas de examen de Odontología de 1952-1971.
EXAMEN_1953 = """Acta No. 1

8/V

República de Colombia - Universidad de Cartagena - Facultad de Odontología

En la Ciudad de Cartagena, a los trece días del mes de Mayo de mil novecientos cincuenta y tres (1953) se constituyó en el Paraninfo de la Universidad el Consejo Examinador integrado por los doctores Pedro Ruiz Mendoza y Carlos Vélez Arango, con el fin de practicar el examen final de Grado del alumno Francisco Laguna Pérez, quien presentó su Tesis titulada «La caries dental en el escolar». Terminado el examen el Consejo acordó la calificación de Cinco (5), y en consecuencia se le confirió el Título de Doctor en Odontología.
"""
EXAMEN_1962 = """Acta Nº 132

79/V

En la ciudad de Cartagena, a los veinte (20) días del mes de Noviembre de mil novecientos sesenta y dos (1962), se constituyó en el Decanato de la Facultad de Odontología el Jurado Examinador para verificar el examen de Grado del alumno Rodrigo Andrés Palacio Ruiz.
El Jurado aprobó su tesis y se le confirió el título de Doctor en Odontología.
"""


class _Libro:
    """El PDF de mentira: la capa de cada página y, rasterizada, cuál es."""

    def __init__(self, capas, foliadas=None):
        self._capas = capas
        self._foliadas = foliadas

    @property
    def page_count(self):
        return len(self._capas)

    def text_of(self, numero):
        return self._capas[numero - 1]

    def render(self, numero, band=None, dpi=200):
        return f"P{numero}".encode() if band is None else b"FRANJA"

    def ink_of(self, numero, band):
        return (0.02, 0.0)


class _IaDePago:
    def __init__(self, paginas):
        self._paginas = paginas

    def read(self, imagen):
        if imagen.startswith(b"P"):
            return OcrResult(text=self._paginas[int(imagen[1:]) - 1])
        return OcrResult(text="")


class TestLosManuscritos:
    def test_el_examen_de_odontologia_se_reconoce_y_se_lee(self):
        for texto in (EXAMEN_1953, EXAMEN_1962):
            assert clase_de_hoja(texto) == "graduado"
            assert examen_de_grado(texto) == "FINAL"
        primera, segunda = leer_acta_de_grado([EXAMEN_1953]), leer_acta_de_grado([EXAMEN_1962])
        assert (primera.numero, primera.nombre, primera.titulo, primera.fecha) == (
            "1", "FRANCISCO LAGUNA PEREZ", DOCTOR_EN_ODONTOLOGIA, date(1953, 5, 13),
        )
        assert (segunda.numero, segunda.nombre, segunda.titulo, segunda.fecha) == (
            "132", "RODRIGO ANDRES PALACIO RUIZ", DOCTOR_EN_ODONTOLOGIA, date(1962, 11, 20),
        )
        assert numero_del_examen("En la ciudad de Cartagena, a los 4 días") is None

    def test_doctor_en_odontologia_no_es_doctor_en_medicina(self):
        assert titulo_del_examen("FINAL", "DOCTOR EN ODONTOLOGIA") == DOCTOR_EN_ODONTOLOGIA
        assert titulo_del_examen("FINAL", "Doctor en Odontolojía, al Señor") == DOCTOR_EN_ODONTOLOGIA
        assert titulo_del_examen("FINAL", "Odontólogo") == "ODONTOLOGO"
        # La 3362 sigue igual.
        assert titulo_del_examen("FINAL", "DOCTOREN") == "DOCTOR EN MEDICINA Y CIRUGIA"

    def test_con_ocr_e_ia_cada_acta_es_su_pdf_con_su_fila(self):
        paginas = [EXAMEN_1953, "Firmas del Consejo Examinador", EXAMEN_1962, "", "", ""]
        outcome = InventariarActa(perfil=GRADO, relector_de_pago=_IaDePago(paginas)).execute(
            _Libro([BASURA] * len(paginas)), document_name="ACTAS DE GRADO 1952 - 1959.pdf", carpeta="ACTAS DE GRADO"
        )
        examenes = [fila for fila in outcome.filas if fila.tipo == "ACTA DE GRADO"]
        assert [(f.pagina_inicial, f.nombre, f.numero) for f in examenes] == [
            (1, "FRANCISCO LAGUNA PEREZ", "1"), (3, "RODRIGO ANDRES PALACIO RUIZ", "132"),
        ]
        nombres = [sesion.nombre for sesion in outcome.sesiones]
        assert "FRANCISCO LAGUNA PEREZ - DOCTOR EN ODONTOLOGIA" in nombres
        asuntos = {fila.asunto: (fila.consecutivo_inicial, fila.fecha_inicial) for fila in filas_del_fuid([asdict(f) for f in outcome.filas])}
        assert asuntos["RODRIGO ANDRES PALACIO RUIZ - DOCTOR EN ODONTOLOGIA"] == ("132", "20/11/1962")

    def test_sin_ia_el_libro_se_entrega_entero_con_su_fila_y_el_aviso(self):
        assert PDF_ENTERO == PDF_ENTERO_DEL_FUID
        libro = _Libro([BASURA] * 12)
        outcome = InventariarActa(perfil=GRADO).execute(
            libro, document_name="ACTAS DE GRADO 1952 - 1959.pdf", carpeta="ACTAS DE GRADO"
        )
        assert not outcome.reparto.es_libro and len(outcome.sesiones) == 1
        (fila,) = outcome.filas
        assert (fila.tipo, fila.entero, fila.pagina_inicial, fila.pagina_final) == (PDF_ENTERO, True, 1, 12)
        informe = outcome.as_dict()
        assert informe["notices"] == [SIN_IA_EL_MANUSCRITO]
        assert informe["asunto"] == "ACTAS DE GRADO 1952 - 1959"
        (entregada,) = resultado_de_cada_acta(outcome.filas, None, pidio_dividir=True)
        assert entregada.resultado == SE_ENTREGA_ENTERO
        (del_fuid,) = filas_del_fuid([asdict(entregada)])
        assert del_fuid.asunto == "ACTAS DE GRADO 1952 - 1959"
        assert (del_fuid.fecha_inicial, del_fuid.fecha_final) == ("01/01/1952", "31/12/1959")
        assert del_fuid.notas.startswith(SIN_IA_EL_MANUSCRITO)

    def test_un_libro_a_maquina_sin_capa_no_es_un_manuscrito(self):
        """Tesseract lo lee: el criterio es lo leído, no la capa del escáner."""

        class Tesseract:
            def read(self, imagen):
                return OcrResult(text=acta("ANA MARIA PEREZ GOMEZ", "45.111.222"))

        outcome = InventariarActa(ocr=Tesseract(), perfil=GRADO).execute(_Libro([""] * 6), document_name="libro.pdf")
        assert all(fila.tipo != PDF_ENTERO for fila in outcome.filas)
