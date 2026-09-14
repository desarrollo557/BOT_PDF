"""Los tres perfiles, y lo que cada uno puede hacer con el FUID.

El archivo pidió que el técnico y el de calidad pudieran **mirar** el Formato
Único de Inventario Documental sin poder **llevárselo**: una planilla que sale
de la máquina en un archivo de Excel deja de estar bajo control del archivo en
cuanto se copia a un correo, y las dos personas que la revisan no son las que la
firman.

Lo que fijan estas pruebas, además de las reglas de alta, es que la restricción
viva en el **servicio** y no sólo en la pantalla. Una que únicamente esconde un
botón la esquiva cualquiera que escriba la dirección a mano, y entonces no es ni
siquiera una barrera de uso: es la apariencia de una, que es peor porque hace
creer que algo está cerrado.

Lo que estas pruebas NO dicen es que esto sea control de acceso. Se entra con
cédula y correo, sin contraseña, y quien sepa los de un compañero entra como él.
"""

from __future__ import annotations

import pytest

from resolutions.domain.perfil import Perfil
from resolutions.domain.usuario import (
    Usuario,
    UsuarioInvalido,
    normalizar_cedula,
    normalizar_correo,
)

pytest.importorskip("httpx")

FUID_SUFFIX = "__FUID.xlsx"


def _con_planilla(main, job_id="job1"):
    """Un documento que ya dejó su FUID escrito en el disco."""
    carpeta = main.contexto.settings.output_dir / job_id
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"libro{FUID_SUFFIX}").write_bytes(b"planilla")
    return job_id


# -----------------------------------------------------------------------------
#  El dominio
# -----------------------------------------------------------------------------


class TestQuePuedeCadaPerfil:
    def test_solo_el_administrador_administra_usuarios(self):
        assert Perfil.ADMINISTRADOR.administra_usuarios
        assert not Perfil.TECNICO.administra_usuarios
        assert not Perfil.CALIDAD.administra_usuarios

    def test_solo_el_administrador_descarga_la_planilla(self):
        assert Perfil.ADMINISTRADOR.descarga_planillas
        assert not Perfil.TECNICO.descarga_planillas
        assert not Perfil.CALIDAD.descarga_planillas

    def test_los_tres_la_ven_en_pantalla(self):
        # Revisar un inventario sin verlo no es revisarlo, y esconderlo no
        # protege nada: son los datos que la pantalla de Archivo ya enseña.
        assert all(perfil.ve_planillas for perfil in Perfil)

    def test_un_perfil_desconocido_no_se_adivina(self):
        # Y sobre todo no cae al más poderoso, que es como una restricción deja
        # de existir sin que nadie lo note.
        with pytest.raises(ValueError, match="perfil desconocido"):
            Perfil.parse("jefe")

    def test_ni_uno_vacio(self):
        with pytest.raises(ValueError):
            Perfil.parse(None)

    def test_se_lee_sin_importar_mayusculas_ni_espacios(self):
        assert Perfil.parse("  Tecnico ") is Perfil.TECNICO


class TestComoSeEscribeUnaPersona:
    def test_la_cedula_se_guarda_en_digitos(self):
        # La misma persona la teclea con puntos hoy y sin ellos mañana.
        assert normalizar_cedula("1.047.382.991") == "1047382991"

    def test_la_cedula_vacia_no_identifica_a_nadie(self):
        with pytest.raises(UsuarioInvalido, match="vacía"):
            normalizar_cedula("   ")

    def test_una_cedula_demasiado_corta_se_rechaza(self):
        with pytest.raises(UsuarioInvalido, match="dígitos"):
            normalizar_cedula("123")

    def test_el_correo_se_guarda_en_minusculas(self):
        assert normalizar_correo("  Jefe@Archivo.EDU.co ") == "jefe@archivo.edu.co"

    def test_lo_que_no_tiene_forma_de_correo_se_rechaza(self):
        with pytest.raises(UsuarioInvalido, match="forma de correo"):
            normalizar_correo("jefe.archivo")

    def test_las_dos_cosas_tienen_que_cuadrar_para_entrar(self):
        usuario = Usuario.crear("1047382991", "jefe@archivo.edu.co", "administrador")
        assert usuario.identifica("1.047.382.991", "JEFE@archivo.edu.co")
        assert not usuario.identifica("1047382991", "otro@archivo.edu.co")

    def test_con_la_cedula_sola_no_basta(self):
        # Está impresa en cualquier planilla, así que sería el peor secreto.
        usuario = Usuario.crear("1047382991", "jefe@archivo.edu.co", "tecnico")
        assert not usuario.identifica("1047382991", None)

    def test_quien_no_da_nombre_se_nombra_por_su_cedula(self):
        # Nunca vacío: una fila del libro mayor que no dice quién la produjo es
        # la que obliga a preguntar por el pasillo dentro de tres años.
        assert Usuario.crear("1047382991", "j@a.co", "calidad").etiqueta == "1047382991"


# -----------------------------------------------------------------------------
#  Entrar
# -----------------------------------------------------------------------------


class TestEntrar:
    def test_el_primero_que_entra_a_un_archivo_vacio_queda_de_administrador(self, client):
        # Si no, el sistema nace cerrado con la llave dentro y sólo se abre
        # editando un archivo del disco a mano.
        respuesta = client.post(
            "/api/sesion", json={"cedula": "1047382991", "correo": "jefe@archivo.edu.co"}
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["perfil"] == "administrador"

    def test_y_se_dice_que_acaba_de_pasar(self, client):
        # Un permiso que se concede en silencio es el que nadie revisa después.
        respuesta = client.post(
            "/api/sesion", json={"cedula": "1047382991", "correo": "jefe@archivo.edu.co"}
        )

        assert respuesta.json()["primer_administrador"] is True

    def test_el_segundo_ya_no(self, client, administrador):
        respuesta = client.post(
            "/api/sesion", json={"cedula": "52814663", "correo": "otro@archivo.edu.co"}
        )

        assert respuesta.status_code == 401
        assert "administrador" in respuesta.json()["detail"]

    def test_quien_esta_dado_de_alta_entra_con_su_perfil(self, client, tecnico):
        respuesta = client.post(
            "/api/sesion", json={"cedula": "52814663", "correo": "tecnico@archivo.edu.co"}
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["perfil"] == "tecnico"

    def test_con_el_correo_de_otro_no_se_entra(self, client, tecnico, calidad):
        respuesta = client.post(
            "/api/sesion", json={"cedula": "52814663", "correo": "calidad@archivo.edu.co"}
        )

        assert respuesta.status_code == 401

    def test_la_cedula_con_puntos_es_la_misma_persona(self, client, tecnico):
        respuesta = client.post(
            "/api/sesion", json={"cedula": "52.814.663", "correo": "tecnico@archivo.edu.co"}
        )

        assert respuesta.status_code == 200

    def test_lo_que_no_tiene_forma_de_cedula_se_explica(self, client, administrador):
        respuesta = client.post(
            "/api/sesion", json={"cedula": "abc", "correo": "x@y.co"}
        )

        assert respuesta.status_code == 422
        assert "cédula" in respuesta.json()["detail"].lower()


# -----------------------------------------------------------------------------
#  Administrar
# -----------------------------------------------------------------------------


class TestDarDeAlta:
    def test_el_administrador_da_de_alta(self, client, administrador):
        respuesta = client.post(
            "/api/usuarios",
            headers=administrador,
            json={
                "cedula": "52814663",
                "correo": "tecnico@archivo.edu.co",
                "perfil": "tecnico",
                "nombre": "Quien procesa",
            },
        )

        assert respuesta.status_code == 201
        assert respuesta.json()["perfil_label"] == "Técnico"

    def test_el_tecnico_no(self, client, tecnico):
        respuesta = client.post(
            "/api/usuarios",
            headers=tecnico,
            json={"cedula": "111111", "correo": "x@y.co", "perfil": "calidad", "nombre": "Alguien"},
        )

        assert respuesta.status_code == 403

    def test_el_de_calidad_tampoco(self, client, calidad):
        respuesta = client.post(
            "/api/usuarios",
            headers=calidad,
            json={"cedula": "111111", "correo": "x@y.co", "perfil": "calidad", "nombre": "Alguien"},
        )

        assert respuesta.status_code == 403

    def test_y_nadie_sin_identificarse(self, client, administrador):
        respuesta = client.post(
            "/api/usuarios",
            json={"cedula": "111111", "correo": "x@y.co", "perfil": "calidad", "nombre": "Alguien"},
        )

        assert respuesta.status_code == 401

    def test_el_mismo_correo_de_otra_cedula_se_rechaza(self, client, administrador, tecnico):
        # Es el segundo dato con que se entra: dos personas con el mismo correo
        # hacen que entrar dependa de a cuál se mire primero.
        respuesta = client.post(
            "/api/usuarios",
            headers=administrador,
            json={
                "cedula": "999999999",
                "correo": "tecnico@archivo.edu.co",
                "perfil": "calidad",
                "nombre": "Otra persona",
            },
        )

        assert respuesta.status_code == 422
        assert "ya es de la cédula" in respuesta.json()["detail"]

    def test_dar_de_alta_dos_veces_la_misma_cedula_la_actualiza(self, client, administrador):
        for perfil in ("tecnico", "calidad"):
            client.post(
                "/api/usuarios",
                headers=administrador,
                json={"cedula": "52814663", "correo": "t@a.co", "perfil": perfil, "nombre": "Quien sea"},
            )

        listado = client.get("/api/usuarios", headers=administrador).json()["usuarios"]
        cuantas = [u for u in listado if u["cedula"] == "52814663"]
        assert len(cuantas) == 1, "dos filas con la misma cédula no tienen un perfil"
        assert cuantas[0]["perfil"] == "calidad"

    def test_un_perfil_inventado_no_se_da_de_alta(self, client, administrador):
        respuesta = client.post(
            "/api/usuarios",
            headers=administrador,
            json={"cedula": "52814663", "correo": "t@a.co", "perfil": "jefe", "nombre": "Quien sea"},
        )

        assert respuesta.status_code == 422


class TestDarDeBaja:
    def test_el_administrador_da_de_baja(self, client, administrador, tecnico):
        assert client.delete("/api/usuarios/52814663", headers=administrador).status_code == 200

    def test_una_cedula_que_no_esta_dice_que_no_esta(self, client, administrador):
        assert client.delete("/api/usuarios/999999999", headers=administrador).status_code == 404

    def test_nunca_al_ultimo_administrador(self, client, administrador):
        # Dejaría el archivo sin nadie que pueda dar de alta a nadie, y la única
        # salida sería editar un archivo del disco a mano.
        respuesta = client.delete("/api/usuarios/1047382991", headers=administrador)

        assert respuesta.status_code == 409
        assert "sin administrador" in respuesta.json()["detail"]

    def test_ni_quitandole_el_perfil(self, client, administrador):
        respuesta = client.patch(
            "/api/usuarios/1047382991", headers=administrador, json={"perfil": "tecnico"}
        )

        assert respuesta.status_code == 409

    def test_con_otro_administrador_si(self, client, administrador):
        client.post(
            "/api/usuarios",
            headers=administrador,
            json={"cedula": "52814663", "correo": "otro@a.co", "perfil": "administrador", "nombre": "La otra"},
        )

        assert client.delete("/api/usuarios/1047382991", headers=administrador).status_code == 200


class TestCambiarleElPerfilAAlguien:
    def test_se_le_cambia_y_se_nota_al_entrar(self, client, administrador, tecnico):
        client.patch("/api/usuarios/52814663", headers=administrador, json={"perfil": "calidad"})

        entrada = client.post(
            "/api/sesion", json={"cedula": "52814663", "correo": "tecnico@archivo.edu.co"}
        )
        assert entrada.json()["perfil"] == "calidad"

    def test_la_cedula_de_alguien_que_no_esta_se_dice(self, client, administrador):
        respuesta = client.patch(
            "/api/usuarios/999999999", headers=administrador, json={"perfil": "calidad"}
        )

        assert respuesta.status_code == 422


# -----------------------------------------------------------------------------
#  El FUID: quién se lo lleva y quién sólo lo mira
# -----------------------------------------------------------------------------


class TestLaDescargaDelFuid:
    def test_el_administrador_se_la_lleva(self, client, administrador):
        from resolutions.api import main

        job = _con_planilla(main)

        respuesta = client.get(f"/api/jobs/{job}/fuid.xlsx", headers=administrador)

        assert respuesta.status_code == 200
        assert respuesta.content == b"planilla"

    def test_el_tecnico_no(self, client, tecnico):
        from resolutions.api import main

        job = _con_planilla(main)

        respuesta = client.get(f"/api/jobs/{job}/fuid.xlsx", headers=tecnico)

        assert respuesta.status_code == 403

    def test_el_de_calidad_tampoco(self, client, calidad):
        from resolutions.api import main

        job = _con_planilla(main)

        assert client.get(f"/api/jobs/{job}/fuid.xlsx", headers=calidad).status_code == 403

    def test_y_el_mensaje_dice_qué_sí_puede_hacer(self, client, tecnico):
        # Un 403 que sólo niega manda al operador a preguntar por el pasillo si
        # el sistema está roto. Éste le dice que la planilla está en pantalla.
        from resolutions.api import main

        job = _con_planilla(main)

        detalle = client.get(f"/api/jobs/{job}/fuid.xlsx", headers=tecnico).json()["detail"]

        assert "Técnico" in detalle
        assert "pantalla" in detalle

    def test_sin_identificarse_tampoco_se_descarga(self, client, administrador):
        # Si la ausencia de cabecera concediera el permiso, bastaría con no
        # mandarla, y la restricción no sería nada.
        from resolutions.api import main

        job = _con_planilla(main)

        assert client.get(f"/api/jobs/{job}/fuid.xlsx").status_code == 401

    def test_el_permiso_se_mira_antes_que_la_existencia(self, client, tecnico):
        # Un documento que no tiene planilla tampoco se le enseña a quien no
        # podría descargarla: comprobar el perfil primero es lo que evita
        # contestar preguntas que no le tocaba hacer.
        assert client.get("/api/jobs/no-existe/fuid.xlsx", headers=tecnico).status_code == 403


class TestMirarElFuidEnPantalla:
    """Lo que sí pueden los tres, y de dónde sale."""

    @staticmethod
    def _planilla_de_verdad(main, job_id="job1"):
        """Una planilla escrita con el escritor de verdad, no un archivo falso."""
        pytest.importorskip("openpyxl")
        from resolutions.adapters.fuid_inventory import FuidInventory
        from resolutions.application.fuid import FuidRow
        from resolutions.application.inventory_document import default_template

        carpeta = main.contexto.settings.output_dir / job_id
        carpeta.mkdir(parents=True, exist_ok=True)
        FuidInventory(default_template()).write(
            [
                FuidRow(orden=1, asunto="DERECHO DE PETICION", folios=8),
                FuidRow(orden=2, asunto="ACTA DE IRREGULARIDAD", folios=3),
            ],
            carpeta / f"caja{FUID_SUFFIX}",
        )
        return job_id

    def test_el_tecnico_la_ve(self, client, tecnico):
        from resolutions.api import main

        job = self._planilla_de_verdad(main)

        respuesta = client.get(f"/api/jobs/{job}/fuid.tabla", headers=tecnico)

        assert respuesta.status_code == 200
        assert respuesta.json()["total"] == 2

    def test_el_de_calidad_tambien(self, client, calidad):
        from resolutions.api import main

        job = self._planilla_de_verdad(main)

        assert client.get(f"/api/jobs/{job}/fuid.tabla", headers=calidad).status_code == 200

    def test_trae_los_asuntos_que_se_escribieron(self, client, tecnico):
        from resolutions.api import main

        job = self._planilla_de_verdad(main)

        cuerpo = client.get(f"/api/jobs/{job}/fuid.tabla", headers=tecnico).json()
        asuntos = [fila[2] for fila in cuerpo["filas"]]

        assert asuntos == ["DERECHO DE PETICION", "ACTA DE IRREGULARIDAD"]

    def test_y_los_nombres_de_las_columnas_del_formato(self, client, tecnico):
        from resolutions.api import main

        job = self._planilla_de_verdad(main)

        columnas = client.get(f"/api/jobs/{job}/fuid.tabla", headers=tecnico).json()["columnas"]

        assert len(columnas) == 16
        assert columnas[0] == "No. de Orden"
        # Los dos niveles del formato, juntos: sin eso salen dos columnas
        # llamadas "Final" sin decir final de qué.
        assert "CONSECUTIVO Final" in columnas
        assert any("FECHAS EXTREMAS" in c and "Final" in c for c in columnas)

    def test_la_cabecera_llega_con_sus_dos_niveles(self, client, tecnico):
        # El formato agrupa columnas, y aplanarlas obliga a leer «FECHAS
        # EXTREMAS Final» y «CONSECUTIVO Final» para saber final de qué.
        from resolutions.api import main

        job = self._planilla_de_verdad(main)

        cuerpo = client.get(f"/api/jobs/{job}/fuid.tabla", headers=tecnico).json()
        titulos = [grupo["titulo"] for grupo in cuerpo["grupos"]]

        assert "CONSECUTIVO" in titulos
        assert "UNIDAD DE CONSERVACION" in titulos

    def test_y_los_grupos_cubren_las_dieciseis_columnas(self, client, tecnico):
        # Si no suman, la cabecera queda desalineada del cuerpo y cada celda
        # aparece bajo el nombre de otra columna.
        from resolutions.api import main

        job = self._planilla_de_verdad(main)

        cuerpo = client.get(f"/api/jobs/{job}/fuid.tabla", headers=tecnico).json()

        assert sum(grupo["ancho"] for grupo in cuerpo["grupos"]) == 16
        assert len(cuerpo["subcolumnas"]) == 16

    def test_una_columna_de_un_solo_nivel_no_trae_subcolumna(self, client, tecnico):
        from resolutions.api import main

        job = self._planilla_de_verdad(main)

        cuerpo = client.get(f"/api/jobs/{job}/fuid.tabla", headers=tecnico).json()

        # «No. de Orden» es la primera y no se subdivide.
        assert cuerpo["subcolumnas"][0] == ""
        # Las del consecutivo sí.
        assert cuerpo["subcolumnas"][3] == "Inicial"
        assert cuerpo["subcolumnas"][4] == "Final"

    def test_no_lee_el_bloque_de_firmas_como_si_fueran_registros(self, client, tecnico):
        from resolutions.api import main

        job = self._planilla_de_verdad(main)

        filas = client.get(f"/api/jobs/{job}/fuid.tabla", headers=tecnico).json()["filas"]

        assert not any("elaborado" in " ".join(fila).lower() for fila in filas)

    def test_le_dice_a_la_pantalla_si_puede_descargarla(self, client, tecnico):
        # Para que el botón no esté y la pantalla no tenga que deducirlo por su
        # cuenta: la decisión vive en el dominio y la pantalla la obedece.
        from resolutions.api import main

        job = self._planilla_de_verdad(main)

        cuerpo = client.get(f"/api/jobs/{job}/fuid.tabla", headers=tecnico).json()

        assert cuerpo["descargable"] is False

    def test_y_al_administrador_le_dice_que_sí(self, client, administrador):
        from resolutions.api import main

        job = self._planilla_de_verdad(main)

        cuerpo = client.get(f"/api/jobs/{job}/fuid.tabla", headers=administrador).json()

        assert cuerpo["descargable"] is True

    def test_un_documento_sin_planilla_lo_dice(self, client, tecnico):
        respuesta = client.get("/api/jobs/no-existe/fuid.tabla", headers=tecnico)

        assert respuesta.status_code == 404
        assert "Solo inventariar" in respuesta.json()["detail"]


class TestNingunCampoEnBlanco:
    """Un alta no entra con un campo vacío, ni por la pantalla ni por la API.

    El nombre era opcional y dejó de serlo a petición del archivo: un alta sin
    nombre deja una fila que sólo se sabe leer por su cédula, y nadie vuelve
    sobre ella para completarla. La pantalla apaga el botón hasta que estén los
    cuatro campos; esto fija que el servicio tampoco la acepte, porque una regla
    que sólo vive en el formulario la esquiva cualquier petición escrita a mano.
    """

    def test_sin_nombre_no_se_da_de_alta(self, client, administrador):
        respuesta = client.post(
            "/api/usuarios",
            headers=administrador,
            json={"cedula": "52814663", "correo": "t@a.co", "perfil": "tecnico"},
        )

        assert respuesta.status_code == 422

    def test_con_el_nombre_en_blanco_tampoco(self, client, administrador):
        respuesta = client.post(
            "/api/usuarios",
            headers=administrador,
            json={"cedula": "52814663", "correo": "t@a.co", "perfil": "tecnico", "nombre": "  "},
        )

        assert respuesta.status_code == 422

    def test_ni_con_el_correo_en_blanco(self, client, administrador):
        respuesta = client.post(
            "/api/usuarios",
            headers=administrador,
            json={"cedula": "52814663", "correo": "", "perfil": "tecnico", "nombre": "Quien sea"},
        )

        assert respuesta.status_code == 422

    def test_ni_con_la_cedula_en_blanco(self, client, administrador):
        respuesta = client.post(
            "/api/usuarios",
            headers=administrador,
            json={"cedula": "", "correo": "t@a.co", "perfil": "tecnico", "nombre": "Quien sea"},
        )

        assert respuesta.status_code == 422

    def test_con_los_cuatro_sí(self, client, administrador):
        respuesta = client.post(
            "/api/usuarios",
            headers=administrador,
            json={
                "cedula": "52814663",
                "correo": "t@a.co",
                "perfil": "tecnico",
                "nombre": "Quien procesa",
            },
        )

        assert respuesta.status_code == 201

    def test_un_cambio_no_borra_el_nombre_escribiendo_nada(self, client, administrador, tecnico):
        # Ausente significa «no lo toques»; la cadena vacía sería borrar un dato
        # escribiendo nada, que es lo que esta regla existe para impedir.
        respuesta = client.patch(
            "/api/usuarios/52814663", headers=administrador, json={"nombre": ""}
        )

        assert respuesta.status_code == 422

    def test_pero_cambiar_solo_el_perfil_sigue_valiendo(self, client, administrador, tecnico):
        respuesta = client.patch(
            "/api/usuarios/52814663", headers=administrador, json={"perfil": "calidad"}
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["nombre"] == "Quien procesa", "no se tocó lo que no se mandó"
