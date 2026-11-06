"""La habilidad «Nóminas»: los libros de nómina de la Universidad de Cartagena.

El operador, 2026-11-06, sobre «21. NOMINAS» del REPOSITORIO UDC y su
«ESTRUCTURA LIBROS UNICARTAGENA.pdf»: la tarjeta de la Oficina de Personal
(«NOMINAS + NOMBRE», documento = cédula, fechas = año de acumulación), la hoja
manuscrita («LIBRO DE ANOTACIONES + NOMBRE»), la relación de empleados («paquete
completo cuando las fechas son iguales»), el hablador («divide las nóminas de
cada año») y el certificado de tiempo de servicio, con sus anexos. Esto fija:

- qué es cada hoja por lo que dice (``plantilla_de``);
- cómo se leen sus datos de lo que devuelve la IA, con las lecturas reales;
- cómo se juntan en documentos, y la defensa contra la cédula que la IA copia
  de la tarjeta de abajo;
- las fechas extremas y el nombre de cada PDF;
- la fila del FUID y lo que revisan los dos agentes.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from resolutions.adapters.fuid_de_la_entrega import fila_del_fuid as fila_de_la_entrega
from resolutions.adapters.fuid_nominas import fila_del_fuid
from resolutions.adapters.mosaico_de_cabeceras import repartir
from resolutions.api.worker.nominas import _nada_escrito, nombre_del_pdf
from resolutions.application.fuid import FuidRow
from resolutions.application.integridad_de_los_datos import (
    DE_UNA_NOMINA,
    auditar_los_datos,
    nomina_del_fuid,
    revisar_los_datos,
)
from resolutions.application.perfiles_de_revision import perfil_de
from resolutions.application.tipo_pedido import TipoPedido
from resolutions.domain import nomina as n
from resolutions.domain.datos_esperados import (
    DUDA,
    ERROR,
    DatosDeUnaHistoria,
    revisar_una_nomina,
)

# -- lo que devolvió la IA de verdad, el 2026-11-06 ---------------------------------------

#: El mosaico de diez cabeceras de la nómina de 1975 (UPD3860695), sus tres primeras.
TARJETAS_1975 = """PAGINA 2

|  Apellidos CASTELLAR MEZA | Nombre TULIO  |
| --- | --- |
|  C. C. O NIT No. 9064111 | Lugar de Expedición Copia  |
|  Cargo ALUCENINA Dedicación TC | Año de Acumulación 1975  |

PAGINA 3

|  Apellidos SOTOMAYOR H. | Nombre CARMELINA  |
| --- | --- |
|  C. C. O NIT No. 21013744 | Lugar de Expedición  |
|  Cargo AUX II ALM. Dedicación TC | Año de Acumulación  |

PAGINA 4

|  Apellidos SOTOMAYOR H | Nombre CARMELINA  |
| --- | --- |
|  C. C. O NIT No. | Lugar de Expedición  |
|  Cargo Dedicación | Año de Acumulación  |
"""

#: El libro de anotaciones de 1972 (UPD3860692): el nombre arriba y el año en su casilla.
HOJA_1972 = """|  Julio Castellar M. $2.351,71 c  |   |   |   |   |   |
| --- | --- | --- | --- | --- | --- |
|  1.972 | Cargo |  |  | P.SERV. | √  |
|  En. 12 | Jere Coenra | Jueldo derengado | 1.175,85 |  |   |"""

#: Las anotaciones de pago de 1974 (UPD3860694): el nombre con su «C.C.», que la IA lee «CO/».
HOJA_1974 = """SEBASTIAN, MEDIANO MEZA CO/9645668
|  4/7 | DETALLES | Juntado Numeral | Juntado Demirgado | 5% | Oficina  |"""


class TestQueEsCadaHoja:
    @pytest.mark.parametrize(
        ("texto", "plantilla"),
        [
            ("UNIVERSIDAD DE CARTAGENA Oficina de Personal Apellidos Nombre C.C. o NIT Año de Acumulación", n.TARJETA),
            # La capa rota de la tarjeta: con dos rótulos basta.
            ("Apellidoa^^^ Nombro UNIVERSIDAD Lugar (ie Expedición Inicial Primer Apellido", n.TARJETA),
            ("RELACION DE EMPLEADOS POR CODIGO.- U. DE C.GEN 3.07.84 PAG. 19", n.LISTADO),
            ("DV DP EMPL NOMBRE DEL EMPLEADO NUM.IDEN. C A R G O", n.LISTADO),
            ("LISTADO DE NOMINA PERSONAL UNIVERSIDAD DE CARTAGENA AÑO 1992", n.HABLADOR),
            ("INDICE AÑO 1.975 ALMACEN de la pagina 1 a la pagina 15 BIBLIOTECA de la pagina 19 a la pagina 41", n.INDICE),
            ("PEREZ MUNOZ CARLOS 30.0 SUELDO SOBRETASA CAJA PREVISION 910125 T O T A L CAP.DE PAGO", n.COMPROBANTE),
            ("CERTIFICADO No. 166 SECRETARIA GENERAL H A C E  C O N S T A R Que el Doctor", n.CERTIFICADO),
            # La hoja manuscrita no dice nada impreso.
            ("^LlW 3 7^2 f 4 z", None),
        ],
    )
    def test_por_lo_que_dice(self, texto, plantilla):
        assert n.plantilla_de(texto) == plantilla

    def test_la_tarjeta_que_imprime_caja_prevision_no_es_un_comprobante(self):
        assert n.plantilla_de("Oficina de Personal Apellidos % Caja Previsión Retención en la Fuente") == n.TARJETA

    def test_el_libro_sin_nada_impreso_es_de_hojas_manuscritas(self):
        assert n.plantilla_del_libro([None, None, n.INDICE, None]) == n.HOJA
        assert n.plantilla_del_libro([n.INDICE, n.TARJETA, None, n.TARJETA]) == n.TARJETA
        assert n.plantilla_del_libro([n.HABLADOR, n.LISTADO, None]) == n.LISTADO


class TestLasFechas:
    @pytest.mark.parametrize(
        ("texto", "fecha"),
        [
            ("RELACION DE EMPLEADOS POR CODIGO.- U. DE C.GEN 3.07.84 PAG. 19", (3, 7, 1984)),
            ("RELACION DE EMPLEADOS POR CECOI!EO: INIVDECE 14,06,82 PaG 8", (14, 6, 1982)),
            ("CENTRO SISTEMATIZACION FECHA 17.05.89 PAG. 25", (17, 5, 1989)),
            # Recursos Humanos, 2000: con barras y el año en dos cifras.
            ("Universidad de Cartagena Division de Recursos Humanos Pagina: 1 Fecha: 08/06/00", (8, 6, 2000)),
            # Los renglones del listado empiezan por «26-10-0001»: no es una fecha.
            ("26-10-0001 *ABADIA PINO CESAR ENRIQUE 9069061", None),
        ],
    )
    def test_la_del_listado(self, texto, fecha):
        assert n.fecha_del_listado(texto) == fecha

    def test_la_pagina_del_listado(self):
        assert n.pagina_del_listado("U. DE C.GENA 10.10.79 PAG. 19") == 19

    def test_las_de_pago_de_los_comprobantes(self):
        texto = "5530 63000 PEREZ MUNOZ CARLOS 910125 T O T A L 8 38,931.50 ... 910128 TOTAL"
        assert n.fechas_de_pago(texto) == [(25, 1, 1991), (28, 1, 1991)]

    def test_el_anio_del_hablador_y_del_indice(self):
        assert n.anio_del_hablador("LISTADO DE NOMINA PERSONAL UNIVERSIDAD DE CARTAGENA AÑO 1992") == 1992
        assert n.anio_del_hablador("INDICE AÑO 1.975") == 1975
        assert n.anio_del_hablador("LISTADO DE NOMINA PERSONAL AÑO 2000") == 2000


class TestLoQueSeLee:
    def test_la_cabecera_de_la_tarjeta(self):
        trozos = repartir(TARJETAS_1975, [2, 3, 4])
        assert n.leer_la_tarjeta(trozos[2]) == n.DatosDeLaHoja("CASTELLAR MEZA TULIO", "9064111", 1975)
        assert n.leer_la_tarjeta(trozos[3]) == n.DatosDeLaHoja("SOTOMAYOR H CARMELINA", "21013744", None)
        # La segunda tarjeta repite el nombre sin la cédula.
        assert n.leer_la_tarjeta(trozos[4]) == n.DatosDeLaHoja("SOTOMAYOR H CARMELINA", None, None)

    def test_la_tarjeta_en_cursiva(self):
        texto = "|  Apellidos *CASTELLAR MEZA* | Nombre *TULIO*  |\n|  C. C. O NIT No. *906411* | Lugar |"
        assert n.leer_la_tarjeta(texto).nombre == "CASTELLAR MEZA TULIO"

    def test_la_hoja_de_1972_y_su_anio(self):
        assert n.leer_la_hoja(HOJA_1972) == n.DatosDeLaHoja("JULIO CASTELLAR M", None, 1972)

    def test_la_hoja_de_1974_con_su_cedula(self):
        assert n.leer_la_hoja(HOJA_1974) == n.DatosDeLaHoja("SEBASTIAN MEDIANO MEZA", "9645668", None)

    def test_el_rotulo_de_la_cedula_no_es_del_nombre(self):
        assert n.leer_la_hoja("RICARDO MORALES BOID CCI\n| DETALLES |").nombre == "RICARDO MORALES BOID"

    def test_un_importe_no_es_un_anio(self):
        assert n.leer_la_hoja("Pedro Perez Lopez $1.958,56\n| x |").anio is None

    def test_el_certificado(self):
        texto = (
            "CERTIFICADO No. 166 HACE CONSTAR Que el Doctor JAVIER SEGOVIA FUENTES identificado con la "
            "cédula de ciudadanía No. 73.088.568 de Cartagena, presta servicios ... Para constancia se firma "
            "en Cartagena, a los veintidos (22) dias del mes de Mayo del Dos Mil (2.000)"
        )
        assert n.leer_el_certificado(texto) == n.DatosDeLaHoja("JAVIER SEGOVIA FUENTES", "73088568", 2000, (22, 5, 2000))


class TestElMosaico:
    def test_cada_franja_vuelve_a_su_pagina(self):
        trozos = repartir(TARJETAS_1975, [2, 3, 4])
        assert set(trozos) == {2, 3, 4}
        assert "TULIO" in trozos[2] and "CARMELINA" in trozos[3]

    def test_si_falta_una_etiqueta_no_se_reparte_nada(self):
        assert repartir(TARJETAS_1975, [2, 3, 4, 5]) is None

    def test_la_franja_tomada_por_foto_queda_sin_texto(self):
        trozos = repartir("PAGINA 7\n![img-0.jpeg](img-0.jpeg)\nPAGINA 8\nJUAN PEREZ", [7, 8])
        assert trozos == {7: "", 8: "JUAN PEREZ"}


class TestLosDocumentos:
    def _tarjetas(self, *lecturas):
        return [n.Hoja(numero=i + 2, plantilla=n.TARJETA, datos=d) for i, d in enumerate(lecturas)]

    def test_la_misma_persona_en_dos_tarjetas_va_junta(self):
        hojas = [
            n.Hoja(numero=1, plantilla=n.INDICE, anio=1975),
            *self._tarjetas(
                n.DatosDeLaHoja("SOTOMAYOR H. CARMELINA", "21013744"),
                n.DatosDeLaHoja("SOTOMAYOR H CARMELINA"),
                n.DatosDeLaHoja("MERCADO SANTANA BENITO", "3790622"),
            ),
        ]
        documentos = n.documentos(hojas)
        assert [d.paginas for d in documentos] == [[1], [2, 3], [4]]
        assert [d.clase for d in documentos] == [n.DEL_INDICE, n.PERSONA, n.PERSONA]
        assert documentos[1].cedula == "21013744"

    def test_dos_cedulas_distintas_son_dos_personas(self):
        hojas = self._tarjetas(n.DatosDeLaHoja("PEREZ LOPEZ JUAN", "9064111"), n.DatosDeLaHoja("PEREZ LOPEZ JUAN", "33133308"))
        assert len(n.documentos(hojas)) == 2

    def test_una_cifra_mal_leida_no_parte_a_la_persona(self):
        hojas = self._tarjetas(n.DatosDeLaHoja("CASTELLAR MEZA TULIO", "9064111"), n.DatosDeLaHoja("CASTELLAR MEZA TULIO", "906411"))
        assert len(n.documentos(hojas)) == 1

    def test_la_hoja_sin_nombre_leido_abre_y_la_vacia_se_une(self):
        hojas = self._tarjetas(n.DatosDeLaHoja("PEREZ LOPEZ JUAN"), None, n.DatosDeLaHoja("GOMEZ DIAZ ANA"))
        assert [d.paginas for d in n.documentos(hojas)] == [[2], [3], [4]]
        hojas[1].vacia = True
        assert [d.paginas for d in n.documentos(hojas)] == [[2, 3], [4]]

    def test_la_cedula_que_la_ia_copio_de_la_tarjeta_de_abajo(self):
        """1975, 2026-11-06: la segunda tarjeta de SOTOMAYOR salió con la cédula de MERCADO."""
        lecturas = [
            n.DatosDeLaHoja("SOTOMAYOR H CARMELINA", "21013744"),
            n.DatosDeLaHoja("SOTOMAYOR H CARMELINA", "3790622"),
            n.DatosDeLaHoja("MERCADO SANTANA BENITO", "3790622"),
            # Copiada con una cifra cambiada.
            n.DatosDeLaHoja("MERCADO SANTANA BENITO", "3313330"),
            n.DatosDeLaHoja("GOMEZ PATERNOSTRO AMELIA", "33133308"),
        ]
        limpias, quitadas = n.sin_cedulas_copiadas(lecturas)
        assert quitadas == {1: "3790622", 3: "3313330"}
        assert limpias[2].cedula == "3790622" and limpias[4].cedula == "33133308"
        documentos = n.documentos(self._tarjetas(*limpias))
        assert [d.paginas for d in documentos] == [[2, 3], [4, 5], [6]]

    def test_el_listado_va_junto_mientras_dice_la_misma_fecha(self):
        hojas = [n.Hoja(numero=i, plantilla=n.LISTADO, fecha=(3, 7, 1984) if i % 3 == 0 else None) for i in range(1, 13)]
        hojas += [n.Hoja(numero=13, plantilla=n.LISTADO), n.Hoja(numero=14, plantilla=n.LISTADO, fecha=(14, 6, 1983), pagina=2)]
        hojas += [n.Hoja(numero=15, plantilla=n.LISTADO, fecha=(14, 6, 1983))]
        documentos = n.documentos(hojas, tolerante=False)
        # La 13 sin leer es del listado nuevo: la 14 dice «PAG. 2».
        assert [d.paginas[0] for d in documentos] == [1, 13]
        assert n.fechas_extremas(documentos[1])[:2] == ((14, 6, 1983), (14, 6, 1983))

    def test_una_fecha_mal_leida_por_tesseract_no_abre_otro_listado(self):
        """NOMINA 1977-1984: «2.07.84» y «3.07.84» en la misma relación."""
        fechas = [(2, 7, 1984), (3, 7, 1984), (3, 7, 1984), (16, 6, 1983), (14, 6, 1983), (14, 6, 1983)]
        hojas = [n.Hoja(numero=i + 1, plantilla=n.LISTADO, fecha=f) for i, f in enumerate(fechas)]
        documentos = n.documentos(hojas, tolerante=True)
        assert [d.paginas for d in documentos] == [[1, 2, 3], [4, 5, 6]]
        assert documentos[0].clave == (1984, 7, 3)
        assert documentos[1].clave == (1983, 6, 14)

    def test_el_hablador_abre_su_anio_y_la_tapa_va_con_el_primero(self):
        hojas = [
            n.Hoja(numero=1, plantilla=None),
            n.Hoja(numero=2, plantilla=n.HABLADOR, anio=1991),
            n.Hoja(numero=3, plantilla=n.LISTADO, fecha=(4, 6, 1991)),
            n.Hoja(numero=4, plantilla=n.HABLADOR, anio=1990),
            n.Hoja(numero=5, plantilla=n.LISTADO),
        ]
        documentos = n.documentos(hojas)
        assert [d.paginas for d in documentos] == [[1, 2, 3], [4, 5]]
        assert n.asunto(documentos[0]) == n.ASUNTO_DEL_HABLADOR
        assert n.fechas_extremas(documentos[1])[:2] == ((1, 1, 1990), (31, 12, 1990))

    def test_los_comprobantes_por_mes_de_pago(self):
        hojas = [
            n.Hoja(numero=1, plantilla=n.COMPROBANTE, fechas=((23, 1, 1991),)),
            n.Hoja(numero=2, plantilla=n.COMPROBANTE, fechas=((25, 1, 1991), (23, 1, 1991))),
            n.Hoja(numero=3, plantilla=n.COMPROBANTE, fechas=((4, 4, 1991),)),
            n.Hoja(numero=4, plantilla=n.COMPROBANTE, fechas=((8, 4, 1991),)),
        ]
        documentos = n.documentos(hojas, tolerante=False)
        assert [d.paginas for d in documentos] == [[1, 2], [3, 4]]
        assert n.fechas_extremas(documentos[0])[:2] == ((23, 1, 1991), (25, 1, 1991))

    def test_el_certificado_lleva_sus_anexos(self):
        hojas = [
            n.Hoja(numero=1, plantilla=n.CERTIFICADO, datos=n.DatosDeLaHoja("JAVIER SEGOVIA FUENTES", "73088568", 2000, (22, 5, 2000))),
            n.Hoja(numero=2, plantilla=n.CERTIFICADO if False else None),
            n.Hoja(numero=3, plantilla=n.CERTIFICADO, datos=n.DatosDeLaHoja("ANA DIAZ PEREZ", "33140688")),
        ]
        documentos = n.documentos(hojas)
        assert [d.paginas for d in documentos] == [[1, 2], [3]]
        assert n.asunto(documentos[0]) == "CERTIFICADO DE TIEMPO DE SERVICIO - JAVIER SEGOVIA FUENTES"


class TestElAsuntoYLasFechas:
    def test_el_asunto_de_cada_documento(self):
        tarjeta = n.Documento(clase=n.PERSONA, plantilla=n.TARJETA, lecturas=[n.DatosDeLaHoja("GUERRERO FIGUEROA ROBERTO")])
        hoja = n.Documento(clase=n.PERSONA, plantilla=n.HOJA, lecturas=[n.DatosDeLaHoja("BEATRIZ BARRIOS J")])
        sin_nombre = n.Documento(clase=n.PERSONA, plantilla=n.TARJETA)
        assert n.asunto(tarjeta) == "NOMINAS - GUERRERO FIGUEROA ROBERTO"
        assert n.asunto(hoja, tipo_de_hoja="LIBRO DE ANOTACIONES") == "LIBRO DE ANOTACIONES - BEATRIZ BARRIOS J"
        assert n.asunto(sin_nombre) == "NOMINAS"
        assert n.asunto(n.Documento(clase=n.PAQUETE, plantilla=n.LISTADO)) == "NOMINA"
        assert n.asunto(n.Documento(clase=n.DEL_INDICE, plantilla=n.INDICE)) == "INDICE"

    @pytest.mark.parametrize(
        ("libro", "tipo"),
        [
            ("UPD3860692-LIBRO DE ANOTACIONES 1972 TOMO 1.pdf", "LIBRO DE ANOTACIONES"),
            ("UPD3860694-ANOTACIONES DE PAGO 1974.pdf", "ANOTACIONES DE PAGO"),
            ("UPD3860711-LIBRO DE REGISTROS 1981-2.pdf", "LIBRO DE REGISTROS"),
        ],
    )
    def test_el_tipo_de_la_hoja_es_el_nombre_del_libro(self, libro, tipo):
        assert n.tipo_de_la_hoja(libro) == tipo

    def test_el_anio_y_los_anios_del_libro(self):
        assert n.anio_del_libro("UPD3860695-NOMINA 1975 TOMO 1.pdf") == 1975
        assert n.anio_del_libro("UPD3860742-NOMINA 1977-1984.pdf") is None
        assert n.anio_del_libro("x.pdf", [1972, 1972]) == 1972
        assert n.ventana_del_libro("UPD3860742-NOMINA 1977-1984.pdf") == (1977, 1984)

    def test_la_tarjeta_sin_anio_lleva_el_del_libro_y_lo_dice(self):
        documento = n.Documento(clase=n.PERSONA, plantilla=n.TARJETA, lecturas=[n.DatosDeLaHoja("ANA DIAZ PEREZ")])
        inicial, final, nota = n.fechas_extremas(documento, anio_del_libro=1975)
        assert (inicial, final) == ((1, 1, 1975), (31, 12, 1975))
        assert "del libro" in nota

    def test_un_anio_fuera_del_libro_no_se_toma(self):
        """1972: la IA leyó «1927» en la hoja de RAUL GOMEZ B."""
        documento = n.Documento(clase=n.PERSONA, plantilla=n.HOJA, lecturas=[n.DatosDeLaHoja("RAUL GOMEZ B", anio=1927)])
        inicial, final, nota = n.fechas_extremas(documento, anio_del_libro=1972, ventana=(1972, 1972))
        assert (inicial, final) == ((1, 1, 1972), (31, 12, 1972))
        assert "1927" in nota and "revísela" in nota

    def test_el_nombre_de_cada_pdf(self):
        persona = n.Documento(clase=n.PERSONA, plantilla=n.TARJETA, paginas=[2, 3], lecturas=[n.DatosDeLaHoja("CASTELLAR MEZA TULIO", "9064111")])
        sin_nombre = n.Documento(clase=n.PERSONA, plantilla=n.TARJETA, paginas=[12])
        listado = n.Documento(clase=n.PAQUETE, plantilla=n.LISTADO, paginas=[5, 6], fechas=[(3, 7, 1984)])
        mes = n.Documento(clase=n.PAQUETE, plantilla=n.COMPROBANTE, paginas=[1], fechas=[(25, 1, 1991)])
        hablador = n.Documento(clase=n.PAQUETE, plantilla=n.HABLADOR, paginas=[8], anio=1990)
        assert nombre_del_pdf(3, persona) == "03_CASTELLAR-MEZA-TULIO-9064111.pdf"
        assert nombre_del_pdf(7, sin_nombre) == "07_PAGINAS-12-12.pdf"
        assert nombre_del_pdf(5, listado) == "05_NOMINA-03-07-1984.pdf"
        assert nombre_del_pdf(1, mes) == "01_NOMINA-01-1991.pdf"
        assert nombre_del_pdf(2, hablador) == "02_LISTADO-DE-NOMINA-PERSONAL-1990.pdf"
        assert nombre_del_pdf(1, n.Documento(clase=n.DEL_INDICE, plantilla=n.INDICE, paginas=[1])) == "01_INDICE.pdf"

    def test_nada_escrito_en_la_cabecera(self):
        vacia = "|  C.C. O NIT No. Lugar de Expedición  |\n|  Cargo Dedicación |"
        assert _nada_escrito(vacia, n.DatosDeLaHoja())
        assert not _nada_escrito("| Apellidos ILEGIBLE XQ | Nombre |", n.DatosDeLaHoja())


def _fila(**cambios):
    fila = {
        "tipo": n.NOMINA,
        "clase": n.PERSONA,
        "plantilla": n.TARJETA,
        "asunto": "NOMINAS - CASTELLAR MEZA TULIO",
        "nombre": "CASTELLAR MEZA TULIO",
        "cedula": "9064111",
        "pide_cedula": True,
        "fecha_inicial": "01/01/1975",
        "fecha_final": "31/12/1975",
        "folios": 2,
        "pagina_inicial": 2,
        "pagina_final": 3,
        "archivo": "UPD3860695-NOMINA 1975 TOMO 1.pdf",
        "carpeta": "21. NOMINAS",
        "archivo_generado": "02_CASTELLAR-MEZA-TULIO-9064111.pdf",
        "observaciones": "",
    }
    fila.update(cambios)
    return fila


class TestElFuid:
    def test_la_fila_de_una_persona(self):
        fila = fila_del_fuid(_fila())
        assert fila.asunto == "NOMINAS - CASTELLAR MEZA TULIO"
        # «No. Documento Desde - Hasta»: la cédula en los dos.
        assert (fila.consecutivo_inicial, fila.consecutivo_final) == ("9064111", "9064111")
        assert (fila.fecha_inicial, fila.fecha_final) == ("01/01/1975", "31/12/1975")
        assert fila.carpeta == "UPD3860695"
        assert fila.folios == 2

    def test_la_fila_de_un_listado_sin_cedula(self):
        fila = fila_del_fuid(
            _fila(clase=n.PAQUETE, plantilla=n.LISTADO, asunto="NOMINA", nombre=None, cedula=None,
                  fecha_inicial="03/07/1984", fecha_final="03/07/1984")
        )
        assert (fila.asunto, fila.consecutivo_inicial, fila.fecha_inicial) == ("NOMINA", "N/A", "03/07/1984")

    def test_va_por_el_fuid_de_la_entrega(self):
        assert fila_de_la_entrega(_fila()).asunto == "NOMINAS - CASTELLAR MEZA TULIO"


class TestLosAgentes:
    def test_la_habilidad_se_declara_y_tiene_su_perfil(self):
        assert TipoPedido.parse("nomina") is TipoPedido.NOMINA
        assert TipoPedido.NOMINA.label == "Nóminas"
        perfil = perfil_de("Nóminas")
        assert perfil.clave == "nominas" and perfil.datos is DE_UNA_NOMINA
        # Un listado trae cientos de cédulas: no es una persona por PDF.
        assert not perfil.una_persona_por_pdf

    def test_el_inventario_de_procesos_la_nombra(self):
        from resolutions.api.indices import habilidad_del_proceso

        assert habilidad_del_proceso(SimpleNamespace(report={"tipo": "nomina"}, tipo="nomina", task="both")) == "Nóminas"
        assert habilidad_del_proceso(SimpleNamespace(report=None, tipo="nomina", task="both")) == "Nóminas"

    def test_una_persona_completa(self):
        integridad = revisar_los_datos([_fila()], DE_UNA_NOMINA)
        assert (integridad.documentos, integridad.completos) == (1, 1)

    def test_lo_que_no_cuadra(self):
        filas = [
            _fila(nombre=None, archivo_generado="02_PAGINAS-2-3.pdf"),
            _fila(cedula=None, archivo_generado="03_CASTELLAR-MEZA-TULIO.pdf"),
            # La hoja de 1972 no trae cédula: no se pide.
            _fila(plantilla=n.HOJA, pide_cedula=False, cedula=None, archivo_generado="04_CASTELLAR-MEZA-TULIO.pdf"),
            _fila(cedula="415467824", archivo_generado="05_CASTELLAR-MEZA-TULIO-415467824.pdf"),
            _fila(fecha_inicial=None, cedula="9064112", archivo_generado="06_CASTELLAR-MEZA-TULIO-9064112.pdf"),
            # El listado no es de una persona: no se juzga como una.
            _fila(clase=n.PAQUETE, plantilla=n.LISTADO, asunto="NOMINA", nombre=None, cedula=None),
        ]
        integridad = revisar_los_datos(filas, DE_UNA_NOMINA)
        assert integridad.documentos == 5
        textos = {(h["documento"], h["gravedad"], h["campo"]) for h in integridad.hallazgos}
        assert ("02_PAGINAS-2-3.pdf", ERROR, "nombre") in textos
        assert ("03_CASTELLAR-MEZA-TULIO.pdf", DUDA, "identificacion") in textos
        assert not any(d == "04_CASTELLAR-MEZA-TULIO.pdf" for d, _, _ in textos)
        assert ("05_CASTELLAR-MEZA-TULIO-415467824.pdf", ERROR, "identificacion") in textos
        assert ("06_CASTELLAR-MEZA-TULIO-9064112.pdf", ERROR, "fechas") in textos

    def test_una_cedula_corta_es_para_mirar(self):
        datos = DatosDeUnaHistoria(nombre="LUIS CARLOS SEBA", identificacion="3731", anio_inicial=1974, anio_final=1974)
        assert [(h.campo, h.gravedad) for h in revisar_una_nomina(datos, este_anio=2026)] == [("identificacion", DUDA)]

    def test_la_misma_cedula_con_otro_nombre_es_para_mirar(self):
        filas = [
            _fila(),
            _fila(nombre="MERCADO SANTANA BENITO", archivo_generado="03_MERCADO-SANTANA-BENITO-9064111.pdf"),
        ]
        integridad = revisar_los_datos(filas, DE_UNA_NOMINA)
        assert integridad.con_dudas == 2 and integridad.con_errores == 0

    def test_la_auditoria_casa_cada_pdf_con_su_fila_y_salta_los_listados(self):
        fuid = [
            FuidRow(orden=1, asunto="INDICE", codigo_trd="", consecutivo_inicial="N/A", consecutivo_final="N/A",
                    fecha_inicial="01/01/1975", fecha_final="31/12/1975", caja="", carpeta="", tomo="", otro="",
                    folios=1, folios_siar=1, soporte="", frecuencia="", notas=""),
            FuidRow(orden=2, asunto="NOMINAS - CASTELLAR MEZA TULIO", codigo_trd="", consecutivo_inicial="9064111",
                    consecutivo_final="9064111", fecha_inicial="01/01/1975", fecha_final="31/12/1975", caja="",
                    carpeta="", tomo="", otro="", folios=2, folios_siar=2, soporte="", frecuencia="", notas=""),
            FuidRow(orden=3, asunto="NOMINA", codigo_trd="", consecutivo_inicial="N/A", consecutivo_final="N/A",
                    fecha_inicial="03/07/1984", fecha_final="03/07/1984", caja="", carpeta="", tomo="", otro="",
                    folios=9, folios_siar=9, soporte="", frecuencia="", notas=""),
        ]
        assert nomina_del_fuid(fuid[0]) is None and nomina_del_fuid(fuid[2]) is None
        errores, dudas = auditar_los_datos(
            ["UPD/01_INDICE.pdf", "UPD/02_CASTELLAR-MEZA-TULIO-9064111.pdf", "UPD/03_NOMINA-03-07-1984.pdf"],
            fuid,
            DE_UNA_NOMINA,
        )
        assert errores == [] and dudas == []
