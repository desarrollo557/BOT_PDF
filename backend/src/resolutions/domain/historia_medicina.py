"""Las historias académicas de la Facultad de Medicina: un expediente por estudiante, unido por su nombre.

Lo pidió el operador el 2026-11-03 para «17. FACULTAD DE MEDICINA 3261- 3268 P»:
49 PDF de historias académicas, de 1941 a 2002, en las cajas 00C003261 a
00C003266. La regla de Enfermería (``historia_academica.py``) no sirve aquí:

* **Cada estudiante trae una o varias cartulinas**, y cada cartulina son dos
  páginas: delante la ficha «UNIVERSIDAD DE CARTAGENA - Facultad de Medicina ·
  REGISTRO DE MATRICULA · Nombre del alumno», con foto; detrás el «REGISTRO DE
  ESTUDIOS», con el nombre a máquina al pie. La segunda cartulina trae la ficha
  en blanco o sólo con el nombre. Con «una ficha abre siempre» cada estudiante
  salía partido en dos.
* **El orden del escaneo no es fiable**: las notas de Ferrer Triana van antes
  de su ficha (INTERNADOS ROTATORIO 1978-1984, págs. 3 y 4), y la segunda
  cartulina de Flórez de la Hoz va antes de la primera (págs. 5 a 8).

Lo que dice quién es cada página es **su nombre**, que la ficha escribe con los
nombres primero -- «ALVARO ANIBAL YAMHURE MURILLO» -- y el pie de las notas con
los apellidos primero -- «YAMHURE MURILLO ALVARO ANIBAL» --. El operador lo
señaló así (2026-11-03): «de esta manera podríamos relacionar; usemos la IA
para leer los nombres». La capa de texto no basta: de 98 páginas de internados
sólo dejaba relacionar 5 pares. La IA, leyendo sólo esos dos renglones en
mosaico, los leyó casi todos.

Cuando el mismo estudiante vuelve a aparecer más adelante, separado por otro
-- Baleta, Ballestas y otra vez Baleta (UPD 3859613, págs. 1 a 6) --, cada tramo
sale en su PDF y la nota lo dice: el operador prefirió no reordenar el escaneo
(2026-11-03).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from .doble_lectura import Franja
from .historia_academica import Expediente, Ficha, plano
from .text_distance import damerau_levenshtein

#: Qué es cada página de una historia de Medicina.
FICHA_DE_MEDICINA = "FICHA DE MEDICINA"
NOTAS_DE_MEDICINA = "NOTAS DE MEDICINA"

#: Los rótulos que sólo trae la ficha de Medicina, de 1941 a 2002. Con dos
#: basta: la capa de texto rompe a veces «Nombre del alumno» («Nombre drl
#: alumno»).
LEYENDAS_DE_LA_FICHA = (
    "NOMBRE DEL ALUMNO",
    "REGISTRO DE MATRICULA",
    "NOMBRE DEL PADRE",
    "NOMBRE DE LA MADRE",
    "COLEGIO DONDE TERMINO",
    "DIRECCION DEL ALUMNO",
    "RETRATO",
    "PADRES O ACUDIENTES",
)
#: El «REGISTRO DE ESTUDIOS» cuando la capa perdió el título: la cabecera de
#: su tabla.
_CABECERA_DE_NOTAS = ("HABILITACION", "REVALIDACION", "CALIFICACION DEFINITIVA", "SUPLETORIO")


def clase_de_pagina(texto: str) -> str | None:
    """Si la página es la ficha, la hoja de notas o ninguna de las dos (una carta, la portada)."""
    p = plano(texto)
    if "REGISTRO DE ESTUDIOS" in p or ("ASIGNATURAS" in p and any(c in p for c in _CABECERA_DE_NOTAS)):
        return NOTAS_DE_MEDICINA
    if "NOMBRE DEL ALUMNO" in p or "REGISTRO DE MATRICULA" in p:
        return FICHA_DE_MEDICINA
    if sum(1 for leyenda in LEYENDAS_DE_LA_FICHA if leyenda in p) >= 2:
        return FICHA_DE_MEDICINA
    return None


#: «REGISTRO DE ESTUDIOS» de una hoja escaneada al revés, tal como lo deja la
#: capa de texto: «soianxsa aa oaxsioaa», «soiaaisa m oaxsioaH» (INTERNADOS
#: ROTATORIO 1978-1984, págs. 30, 59, 65 y 96).
_NOTAS_AL_REVES = re.compile(r"\bSO[IL1]A\w{2,4}\s+\w{1,2}\s+O\w{1,3}SIO\w{1,2}\b")
#: Lo que la ficha imprime al revés en su mitad de arriba -- el «Registro de
#: actividades» --: si se lee derecho y la matrícula no, la ficha está al revés.
_ACTIVIDADES = ("NOMBRE DE LA TESIS", "EXAMENES PREPARATORIOS", "CONDUCTA QUE HA OBSERVADO", "GRADO DE DOCTOR")


def al_reves(texto: str) -> bool:
    """Si la página de Medicina se escaneó cabeza abajo, por lo que dice su capa de texto."""
    p = plano(texto)
    if _NOTAS_AL_REVES.search(p):
        return True
    return (
        "REGISTRO DE ACTIVIDADES" in p
        and clase_de_pagina(texto) is None
        and any(leyenda in p for leyenda in _ACTIVIDADES)
    )


#: Cuántas páginas de Medicina tiene que traer un PDF para ser de Medicina.
MINIMO_DE_PAGINAS = 0.25
#: El margen de la ventana de años del PDF (``ventana_de_anios``): los años van
#: a máquina, y con el de Enfermería, de 2, el «PRIMER AÑO 1989» de Ferrer
#: Triana quedaba fuera de «INTERNADOS ROTATORIO 1978-1984».
MARGEN_DE_MEDICINA = 6


def es_de_medicina(textos: Sequence[str]) -> bool:
    """Si el PDF son historias de Medicina: alguna ficha y una cuarta parte de fichas y notas.

    La ficha de Enfermería dice «Nombre del estudiante» y «Nombre de los
    padres», nunca «Nombre del alumno» ni «Nombre del padre».
    """
    clases = [clase_de_pagina(texto) for texto in textos]
    fichas = clases.count(FICHA_DE_MEDICINA)
    return fichas > 0 and fichas + clases.count(NOTAS_DE_MEDICINA) >= MINIMO_DE_PAGINAS * len(textos)


# -- el renglón del nombre ----------------------------------------------------------

#: Los dos renglones que la IA lee de cada página, diez por página facturada.
#: El de la ficha va justo debajo de «REGISTRO DE MATRICULA»; el del pie, en la
#: última franja de la hoja de notas, con «Matrícula No.» al lado. En las de
#: los 80 y 90 el nombre va un renglón por debajo del rótulo: por eso el del pie
#: es más alto.
FRANJA_DEL_ALUMNO = Franja(
    campo="el nombre de la ficha",
    leyendas=("ALUMNO",),
    rotulo=r"NOMBRE\W+DEL\W+ALUMNO",
    alto=0.03,
    margen=0.015,
)
FRANJA_DEL_PIE = Franja(
    campo="el nombre al pie de las notas",
    leyendas=("NOMBRE", "MATRICULA"),
    # Sin excluir «NOMBRE DE…»: el pie no trae padre ni madre, y «NOMBRE /
    # DEL PORTILLO RONCALLO» quedaba sin rótulo y descuadraba el mosaico.
    rotulo=r"\bNOMBRE\b",
    alto=0.065,
    # Poco por encima del rótulo: más arriba está la última asignatura, que se
    # pegaba al nombre («OROZCO CABEZA JAIRO MEDICINA LEGAL», UPD0077293).
    margen=0.008,
)
#: Desde qué altura se busca cada rótulo: la mitad de arriba de la ficha es el
#: «Registro de actividades», impreso al revés, y el pie va abajo del todo.
DESDE_LA_ALTURA = {FRANJA_DEL_ALUMNO.campo: 0.35, FRANJA_DEL_PIE.campo: 0.75}

_ROTULO_DEL_NOMBRE = re.compile(r"\bNOMBRE\b(?:\W+DEL\W+ALUMNO)?(?!\W+DE(?:L\W+PADRE|\W+LA\W+MADRE))")
#: Lo que acompaña al nombre en su renglón y no es nombre. «DE» y «DEL» no:
#: tras el rótulo son del apellido, «DEL PORTILLO RONCALLO LUIS ADOLFO».
_NO_SON_NOMBRE = frozenset({
    "NOMBRE", "ALUMNO", "MATRICULA", "NO", "N", "CODIGO", "COD", "REGISTRO", "PROFESION",
})
_CONECTORES = frozenset({"DE", "DEL", "LA", "LAS", "LOS", "Y", "SAN", "SANTA"})
#: Las asignaturas que van justo encima del pie y se pegan al nombre en el
#: mismo renglón: el nombre acaba antes de ellas.
_DE_ASIGNATURA = frozenset({
    "MEDICINA", "ETICA", "MEDICA", "LEGAL", "CIRUGIA", "PEDIATRIA", "INTERNA", "SALUD", "CLINICA",
    "DEONTOLOGIA", "UROLOGICA", "OBSTETRICIA", "HIGIENE", "RADIOLOGIA", "PATOLOGIA", "TERAPEUTICA",
    "PSIQUIATRIA", "ORTOPEDIA", "GINECOLOGIA", "EPIDEMIOLOGIA", "DERMATOLOGIA", "OFTALMOLOGIA",
})


def _plenas(palabras: Sequence[str]) -> list[str]:
    return [p for p in palabras if len(p) >= 3 and re.search(r"[AEIOUY]", p) and p not in _CONECTORES]


def _solo_el_nombre(renglon: str) -> str | None:
    """Las palabras del renglón sin rótulos ni cifras, si son por lo menos dos con vocales."""
    palabras = [p for p in re.findall(r"[A-Z]+", renglon) if p not in _NO_SON_NOMBRE]
    if corte := next((i for i, p in enumerate(palabras) if p in _DE_ASIGNATURA), None):
        palabras = palabras[:corte]
    while palabras and palabras[-1] in _CONECTORES:
        palabras.pop()
    return " ".join(palabras) if len(_plenas(palabras)) >= 2 else None


def nombre_del_renglon(texto: str) -> str | None:
    """El nombre que dice el renglón leído: lo que sigue a «Nombre del alumno» o a «Nombre».

    Si el rótulo va solo, el nombre está en uno de los renglones de abajo: en
    las hojas de notas de los 80 va debajo, y la IA devuelve a veces «Matrícula
    No.» en medio. Lo que trae otro rótulo de la ficha -- «Nombre del padre» --
    no es el nombre del estudiante.

    Si el trozo trae además el nombre completo de **otra** persona, no se sabe
    cuál es el suyo y no se da ninguno: el proveedor devuelve a veces los
    nombres de un mosaico juntos, lejos de sus rótulos, y un nombre dado a la
    página de al lado une a dos estudiantes.
    """
    renglones = [plano(renglon) for renglon in (texto or "").splitlines() if renglon.strip()]
    for numero, renglon in enumerate(renglones):
        if not (hallado := _ROTULO_DEL_NOMBRE.search(renglon)):
            continue
        for candidato in [renglon[hallado.end():], *renglones[numero + 1 : numero + 4]]:
            if re.search(r"NOMBRE\W+DE(?:L\W+PADRE|\W+LA\W+MADRE)|PROFESION", candidato):
                break
            if nombre := _solo_el_nombre(candidato):
                return None if _otro_nombre_completo(renglones, nombre) else nombre
        return None
    return None


def _otro_nombre_completo(renglones: Sequence[str], nombre: str) -> bool:
    """Si algún renglón trae el nombre completo -- tres palabras o más -- de alguien que no es ``nombre``.

    Tres palabras: el del padre, que a veces se cuela en la franja de la ficha
    («Alejandro Elijardo»), lleva dos.
    """
    for renglon in renglones:
        if re.search(r"NOMBRE\W+DE(?:L\W+PADRE|\W+LA\W+MADRE)|PROFESION", renglon):
            continue
        otro = _solo_el_nombre(_ROTULO_DEL_NOMBRE.sub(" ", renglon))
        if otro and len(_plenas(otro.split())) >= 3 and mismo_estudiante(nombre, otro) is False:
            return True
    return False


# -- la cédula de la ficha -----------------------------------------------------------

#: El número de una cédula como se escribe en la ficha: «877851», «39' 693.597».
_NUMERO = r"(\d{1,3}(?:\s?[.,'’]\s?\d{3}){1,2}|\d{6,10})(?![\d\-])"
#: «Cédula - Tarjeta No. 877851» (de 1941 a 1965) y «C. de C. No. 8'748.124» (de los 70 en adelante).
_CEDULA_TRAS_EL_ROTULO = re.compile(r"(?:CEDULA\W+TARJETA|\bC\.?\s?DE\s?C\.?)\s*N[O0]?\.?\s*" + _NUMERO)
#: La cédula escrita a mano encima del renglón «C. de C. No.»: en el texto queda delante.
_CEDULA_ANTES_DEL_ROTULO = re.compile(_NUMERO + r"[^\d]{0,30}?\bC\.?\s?DE\s?C\.?\s*N[O0]?\b")
_CIFRAS_DE_CEDULA = range(6, 9)


def cedula_de_la_ficha(texto: str) -> str | None:
    """La cédula que escribe la ficha de Medicina, sin puntos; ``None`` si no la trae o no parece una.

    Detrás de su rótulo, o delante si se escribió encima del renglón («39'
    693.597» sobre «C. de C. No.», INTERNADOS ROTATORIO 1978-1984, pág. 1). De
    6 a 8 cifras, o 10 si empieza por 1; la tarjeta de identidad la lee
    ``leer_ficha``.
    """
    p = plano(texto)
    for patron in (_CEDULA_TRAS_EL_ROTULO, _CEDULA_ANTES_DEL_ROTULO):
        if hallado := patron.search(p):
            cifras = re.sub(r"\D", "", hallado.group(1))
            if len(cifras) in _CIFRAS_DE_CEDULA or (len(cifras) == 10 and cifras.startswith("1")):
                return cifras
    return None


# -- el mismo estudiante -------------------------------------------------------------

#: Cuánto se tienen que parecer dos palabras para ser la misma mal leída:
#: «PAYARES» y «PALLARES» (el papel de Cantillo escribe las dos), «CASTILLC» y
#: «CASTILLO».
PARECIDO_DE_PALABRA = 0.75
#: Una palabra que no llega a eso pero se le acerca cuenta media: «VELESEUZ»
#: por VELASQUEZ (UPD 3859597, pág. 66). La de un hermano no: «LUIS» y
#: «ARMANDO» no se parecen en nada.
PARECIDO_A_MEDIAS = 0.6
#: Qué parte de las palabras del nombre más corto tiene que estar en el otro.
#: Tres de tres, o tres de cuatro: dos hermanos «CASTILLO CASTILLO» comparten
#: dos palabras y no son la misma persona.
PARTE_COMUN = 0.75


def _palabras(nombre: str) -> list[str]:
    return [p for p in re.findall(r"[A-Z]+", plano(nombre)) if len(p) >= 3 and p not in _CONECTORES]


def _parecidas(una: str, otra: str) -> bool:
    return una == otra or SequenceMatcher(None, una, otra).ratio() >= PARECIDO_DE_PALABRA


def _a_medias(una: str, otra: str) -> bool:
    """Por la distancia de edición: «VELESEUZ» y «VELASQUEZ» son tres cambios en nueve letras."""
    return 1 - damerau_levenshtein(una, otra) / max(len(una), len(otra)) >= PARECIDO_A_MEDIAS


def mismo_estudiante(uno: str | None, otro: str | None) -> bool | None:
    """Si dos nombres son del mismo estudiante, en cualquier orden; ``None`` si alguno no se leyó.

    «ALVARO ANIBAL YAMHURE MURILLO» (la ficha) y «YAMHURE MURILLO ALVARO
    ANIBAL» (el pie de sus notas) son el mismo. Cada palabra del más corto
    busca su pareja en el otro, una sola vez: una palabra, o dos seguidas que
    la IA leyó pegadas («FELIXMARTIN», UPD0077293, pág. 49).
    """
    if not uno or not otro:
        return None
    unas, otras = _palabras(uno), _palabras(otro)
    if len(unas) < 2 or len(otras) < 2:
        return None
    if len(unas) > len(otras):
        unas, otras = otras, unas
    libres: list[str | None] = list(otras)
    comunes = 0
    sueltas = []
    for palabra in unas:
        if (sola := next((i for i, otra in enumerate(libres) if otra and _parecidas(palabra, otra)), None)) is not None:
            libres[sola] = None
            comunes += 1
            continue
        for i in range(len(libres) - 1):
            if libres[i] and libres[i + 1] and _parecidas(palabra, libres[i] + libres[i + 1]):
                libres[i] = libres[i + 1] = None
                comunes += 1
                break
        else:
            sueltas.append(palabra)
    medias = sum(0.5 for palabra in sueltas if any(otra and _a_medias(palabra, otra) for otra in libres))
    return comunes >= 2 and comunes + medias >= PARTE_COMUN * len(unas)


# -- el nombre correcto --------------------------------------------------------------
#
# El operador (2026-11-03): «si el nombre está mal escrito, que la IA tenga la
# habilidad de colocarle una aproximación correcta y muy cercana». Tres pasos,
# del más seguro al más libre, y la fila dice siempre qué se leyó:
#
# 1. Las lecturas del mismo estudiante votan cada palabra: la ficha y el pie de
#    cada hoja de notas lo escriben dos a cuatro veces («LEIDY» en la ficha,
#    «LEYDY» al pie). En un empate desempata la lista de nombres conocidos.
# 2. Si queda una palabra que nada confirma, se vuelve a mirar el renglón del
#    PDF con zoom, y esa lectura vota también (``historias (worker)``).
# 3. Lo que siga sin confirmar lo corrige la IA: sólo esas palabras, y sólo a
#    una muy cercana a la leída. Una aproximación, nunca otro nombre.
#
# Lo que el papel confirma no se toca, y la lista nunca corrige por su cuenta:
# en INTERNADOS ROTATORIO 1978-1984, pág. 63, el renglón dice «BARCENAS
# CIFUENTES ARGELINA», y la lista lo volvía FUENTES ANGELINA (2026-11-03).


@dataclass(frozen=True, slots=True)
class NombreVotado:
    """El nombre que queda, lo que se leyó, y las palabras que nada confirma."""

    nombre: str | None
    #: La lectura de la que se partió, tal cual: la que va en la nota si cambia.
    leido: str | None
    #: Las palabras que ni otra lectura ni la lista confirman: las que la IA puede corregir.
    sin_confirmar: tuple[str, ...] = ()

    @property
    def corregido(self) -> bool:
        return bool(self.nombre and self.leido and self.nombre != self.leido)


def nombre_por_consenso(lecturas: Sequence[str | None], conocidas: Collection[str] = ()) -> NombreVotado:
    """El nombre que dicen las lecturas del mismo estudiante, palabra por palabra.

    Se parte de la primera -- el pie de las notas, con los apellidos primero --
    y cada palabra suya se vota con su pareja en las demás lecturas, en
    cualquier orden. Gana la grafía con más lecturas; en un empate, la de la
    lista de nombres conocidos y si no, la de la primera. Una palabra que no
    confirma ni otra lectura ni la lista queda como se leyó y en
    ``sin_confirmar``: la lista no corrige por su cuenta («CIFUENTES
    ARGELINA» no es FUENTES ANGELINA). Una palabra que otra lectura parte en
    dos -- «FELIXMARTIN» y «FELIX MARTIN» -- se parte.
    """
    leidas = [lectura.split() for lectura in lecturas if lectura and lectura.split()]
    if not leidas:
        return NombreVotado(None, None)
    base, otras = leidas[0], leidas[1:]
    votado: list[str] = []
    sin_confirmar: list[str] = []
    for palabra in base:
        if palabra in _CONECTORES or len(palabra) < 3:
            votado.append(palabra)
            continue
        partida = next(
            (otra[i : i + 2] for otra in otras for i in range(len(otra) - 1)
             if otra[i] + otra[i + 1] == palabra),
            None,
        )
        if partida:
            votado.extend(partida)
            continue
        votos = Counter({palabra: 1})
        for otra in otras:
            pareja = max(
                (p for p in otra if p not in _CONECTORES),
                key=lambda p: SequenceMatcher(None, palabra, p).ratio(),
                default=None,
            )
            if pareja and (_parecidas(palabra, pareja) or _a_medias(palabra, pareja)):
                votos[pareja] += 1
        ganadora = max(votos, key=lambda p: (votos[p], p in conocidas, p == palabra))
        # Un empate que la lista no decide tampoco confirma nada: «NIMMEER» al
        # pie y «NIMMLER» en la ficha, dos y dos (internados, págs. 1 y 2).
        empatadas = [p for p in votos if votos[p] == votos[ganadora]]
        empate = len(empatadas) > 1 and sum(1 for p in empatadas if p in conocidas) != 1
        if (votos[ganadora] < 2 or empate) and ganadora not in conocidas:
            sin_confirmar.append(ganadora)
        votado.append(ganadora)
    return NombreVotado(" ".join(votado), " ".join(base), tuple(sin_confirmar))


#: Lo que se le pide a la IA cuando, después de votar, al nombre le quedan
#: palabras que nada confirma.
INSTRUCCIONES_PARA_CORREGIR_EL_NOMBRE = (
    "Eres archivista de la Universidad de Cartagena (Colombia). Recibes una o varias lecturas OCR del "
    "nombre de UNA misma persona, tomadas de distintas hojas de su expediente. El OCR confunde letras "
    "(O/Q/D, I/L/1, E/F, M/N, RN/M, U/V, C/G, S/5), pega o parte palabras, y el orden puede variar "
    "(nombres primero o apellidos primero).\n\n"
    "Devuelve solo el nombre completo correcto más probable, en mayúsculas y sin tildes, con los "
    "apellidos primero y luego los nombres. Por ejemplo, de «VELESEUZ CANO RAFAEL» devuelve "
    "VELASQUEZ CANO RAFAEL.\n"
    "- Corrige solo los errores de lectura: cada palabra tiene que ser la forma correcta, de un nombre o "
    "apellido real, de una palabra leída, y parecerse mucho a ella.\n"
    "- Si varias lecturas dicen la misma palabra de dos maneras, elige la que es un nombre o apellido real.\n"
    "- No cambies un nombre o apellido por otro distinto, no agregues ni quites palabras, no inventes.\n"
    "- Si una palabra ya es un nombre o apellido real, déjala como está.\n"
    "- Si no puedes corregir con seguridad, devuelve la primera lectura tal cual."
)

#: Cuánto puede alejarse una palabra corregida por la IA de una leída: dos de
#: cada cinco letras, y al menos una. «VELESEUZ» → VELASQUEZ son tres de ocho;
#: «SIPOZ» → LOPEZ, tres de cinco, ya no es lo que dice el renglón (el
#: operador, 2026-11-03: «lo más parecido a lo que se pueda leer en el
#: renglón»). Para eso está la relectura del renglón con zoom.
DISTANCIA_DE_LA_IA = 0.4


def aproximacion_de_la_ia(respuesta: str, lecturas: Sequence[str | None]) -> str | None:
    """El nombre corregido por la IA, si es una aproximación de lo leído; ``None`` si no.

    Cada palabra de la respuesta tiene que estar cerca de una palabra leída
    -- a ``DISTANCIA_DE_LA_IA`` de sus letras --; alguna lectura tiene que
    tener cada palabra suya en la respuesta, y la respuesta no puede traer más
    palabras que la lectura más larga. Así la IA arregla «VELESEUZ» y «KARL»
    o elige entre dos lecturas del renglón, pero no cambia a la persona.
    """
    palabras = [p for p in re.findall(r"[A-Z]+", plano(respuesta)) if p != "NINGUNO"]
    por_lectura = [[p for p in lectura.split() if p not in _CONECTORES] for lectura in lecturas if lectura]
    leidas = [p for lectura in lecturas if lectura for p in lectura.split()]
    if not palabras or not leidas:
        return None
    if len([p for p in palabras if p not in _CONECTORES]) > max(len(lectura) for lectura in por_lectura):
        return None

    def cerca(una: str, otra: str) -> bool:
        return damerau_levenshtein(una, otra) <= max(1, round(DISTANCIA_DE_LA_IA * len(otra)))

    if not all(p in _CONECTORES or any(cerca(p, leida) for leida in leidas) for p in palabras):
        return None
    if not any(all(any(cerca(p, leida) for p in palabras) for leida in lectura) for lectura in por_lectura):
        return None
    return " ".join(palabras)


def _corrige_a(corregida: str, leida: str) -> bool:
    """Si ``corregida`` es la misma palabra que ``leida`` bien escrita: cerca, y con una letra de más o de menos como mucho.

    Quitar o poner dos letras ya es otra palabra: «CIFUENTES» no es FUENTES.
    """
    return abs(len(corregida) - len(leida)) <= 1 and damerau_levenshtein(corregida, leida) <= max(
        1, round(DISTANCIA_DE_LA_IA * len(leida))
    )


def corregir_con_la_ia(votado: NombreVotado, respuesta: str, lecturas: Sequence[str | None]) -> str | None:
    """El nombre votado con las palabras sin confirmar cambiadas por las de la IA; ``None`` si no cambia nada.

    Sólo esas palabras: lo que el papel confirma no lo toca la IA (el renglón
    de la pág. 54 de internados dice LEIDY; el de la 63, CIFUENTES ARGELINA).
    Y sólo si la respuesta entera es una aproximación de lo leído
    (``aproximacion_de_la_ia``) y cada palabra cambiada corrige a la suya
    (``_corrige_a``).
    """
    if not votado.nombre or not votado.sin_confirmar or not aproximacion_de_la_ia(respuesta, lecturas):
        return None
    libres = [p for p in re.findall(r"[A-Z]+", plano(respuesta)) if p not in _CONECTORES]
    resultado = []
    for palabra in votado.nombre.split():
        if palabra in votado.sin_confirmar and libres:
            mejor = min(libres, key=lambda propuesta: damerau_levenshtein(propuesta, palabra))
            if mejor != palabra and _corrige_a(mejor, palabra):
                resultado.append(mejor)
                libres.remove(mejor)
                continue
        resultado.append(palabra)
    corregido = " ".join(resultado)
    return corregido if corregido != votado.nombre else None


# -- las hojas sueltas ---------------------------------------------------------------
#
# Las cajas 00C003267 y 00C003268 no son historias: son legajos de hojas sueltas,
# una por estudiante -- la matrícula de cada uno, su certificado, su recibo de
# caja --, detrás de una portada escrita a mano. El operador pidió un PDF por
# hoja (2026-10-30), y que el asunto del FUID diga qué hoja es (2026-11-03):
# «ALVAREZ OROZCO HAROLD ANTONIO - CERTIFICADO DE MATRICULA».

CERTIFICADO_DE_MATRICULA = "CERTIFICADO DE MATRICULA"
CERTIFICADO_DE_NOTAS = "CERTIFICADO DE NOTAS"
MATRICULA_ACADEMICA = "MATRICULA ACADEMICA"
RECIBO_DE_CAJA = "RECIBO DE CAJA"

#: «Admisiones Registro y Control Académico», el membrete de la matrícula,
#: como lo deja la capa: «Registro 7 Control», «Contool», «Contsol».
_MEMBRETE_DE_MATRICULA = re.compile(r"REGISTRO\s*[Y7]?\s*CON\w{2,4}\s*AC\w*D")
_MATRICULA = re.compile(r"\bMA\W?\w?\W?R\W?I\W?C\W?U\W?[LR]\W?A\W+ACA\W?D\w*M\W?I\W?C\W?A")


def tipo_de_hoja(texto: str) -> str | None:
    """Qué hoja suelta es la página, o ``None`` si no es ninguna (la portada, una carta)."""
    p = plano(texto)
    if re.search(r"CERTIFICADO DE [NW]OTAS", p):
        return CERTIFICADO_DE_NOTAS
    if "CERTIFICADO DE MATRICULA" in p:
        return CERTIFICADO_DE_MATRICULA
    if "RECIBO DE CAJA" in p or ("LA SUMA DE" in p and "POR CONCEPTO DE" in p):
        return RECIBO_DE_CAJA
    if _MATRICULA.search(p) or _MEMBRETE_DE_MATRICULA.search(p):
        return MATRICULA_ACADEMICA
    return None


#: Cuántas páginas tienen que ser hojas sueltas para que el PDF sea un legajo de ellas.
MINIMO_DE_HOJAS = 0.5


def es_de_hojas_sueltas(textos: Sequence[str]) -> bool:
    """Si el PDF es un legajo de matrículas, certificados o recibos: la mitad de sus páginas lo son."""
    return bool(textos) and sum(1 for texto in textos if tipo_de_hoja(texto)) >= MINIMO_DE_HOJAS * len(textos)


def hojas_sueltas(tipos: Sequence[str | None]) -> list[Expediente]:
    """Un expediente por hoja: cada hoja con tipo abre el suyo, y lo demás sigue al anterior.

    Lo que no es una hoja -- una carta o la certificación de otra universidad
    archivada con la matrícula -- va con la hoja de antes. Lo de antes de la
    primera, la portada, no es de nadie.
    """
    resultado: list[Expediente] = []
    for numero, tipo in enumerate(tipos, start=1):
        if tipo is not None:
            resultado.append(Expediente(paginas=[numero], ficha=Ficha(), plantilla=tipo, pagina_de_la_ficha=numero))
        elif resultado:
            resultado[-1].paginas.append(numero)
        else:
            resultado.append(Expediente(paginas=[numero], ficha=None))
    return resultado


@dataclass(frozen=True, slots=True)
class Hoja:
    """Lo que dice una hoja suelta. Lo que no se leyó, ``None``."""

    nombre: str | None = None
    codigo: str | None = None
    #: La fecha de la hoja, día, mes y año, si la trae entera.
    fecha: tuple[int, int, int] | None = None
    #: El año, si sólo se sabe el año: el del período «1o-91».
    anio: int | None = None


#: El código del estudiante: «51-8810043», «519210037».
_CODIGO_DE_HOJA = re.compile(r"(?<![\d\-])(5\d\s?[-.]\s?\d{7,8}|5\d{8,9})(?![\d\-])")
#: «APELLIDOS: ARRIETA VALENCIA | NOMBRES: LEONARDO ANTONIO».
#: Con el punto de una inicial: «NOMBRES: CESAR J.» (EXONERADOS 1991, pág. 7).
_APELLIDOS = re.compile(r"APELLIDOS\W{0,3}([A-Z][A-Z .]{1,40}?)\s*(?:\||NOMBRES|$)", re.M)
_NOMBRES = re.compile(r"NOMBRES\W{0,3}([A-Z][A-Z .]{1,40}?)\s*(?:\||CARRERA|SEM|PERIODO|$)", re.M)
#: «RECIBIDO DE Beleno González Edinson Medicina», «RECIBO DE Martinez RuP2 Alvaro. Medicina.».
_RECIBIDO_DE = re.compile(r"RECIBI?D?O DE\W{0,3}([A-Z][A-Z0-9 .]{4,60}?)\s*(?:\||DIRECCION|$)", re.M)
#: «Cartagena 08-08-96»: la fecha del recibo en cifras.
_FECHA_EN_CIFRAS = re.compile(r"FECHA\W{0,3}[A-Z ,]{0,20}?(\d{1,2})\s?[-/.]\s?(\d{1,2})\s?[-/.]\s?(\d{2}|\d{4})\b")
#: «FECHA EXPEDICION … DIA 26 | MES 03 | AÑO 92».
_FECHA_DE_EXPEDICION = re.compile(r"DIA\W{0,3}(\d{1,2})\W{1,6}MES\W{0,3}(\d{1,2})\W{1,6}ANO\W{0,3}(\d{2,4})")
#: El período de la matrícula: «10-91», «1o-91», «20/93», «1/88».
_PERIODO = re.compile(r"PERIODO\W{0,6}([12])\s?[O0°]?\s?[-/]\s?(\d{2})\b")
#: «Cartagena, Nov. 18 de 1.996», «julio 30 de 1996».
_FECHA_ESCRITA = re.compile(r"\b(\d{1,2})\s*(?:DE\s+)?([A-Z]{3})[A-Z]*\.?\s*(?:DE|DEL)?\s*([12])\.?\s?(\d{3})\b")
_FECHA_ESCRITA_MES_PRIMERO = re.compile(r"\b([A-Z]{3})[A-Z]*\.?\s*(\d{1,2})\s*(?:DE|DEL)\s*([12])\.?\s?(\d{3})\b")
_MESES = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8,
          "SEP": 9, "SET": 9, "OCT": 10, "NOV": 11, "DIC": 12}
#: Lo que la matrícula, el certificado y el recibo ponen detrás del nombre.
_DESPUES_DEL_NOMBRE = frozenset({"MEDICINA", "CARRERA", "SEM", "SEMEST", "PERIODO", "ANO", "CODIGO"})


_ANIO = re.compile(r"(?<!\d)(19[2-9]\d|20[0-3]\d)(?!\d)")


def _anios_de(nombre: str, portada: str) -> list[int]:
    return [int(anio) for anio in _ANIO.findall(nombre or "")] or [
        int(anio) for anio in _ANIO.findall(re.sub(r"(?<=\b[12])\.(?=\d{3}\b)", "", portada or ""))
    ]


def anios_del_legajo(nombre: str, portada: str = "") -> tuple[int | None, int | None]:
    """El primer y el último año del legajo: los del nombre del PDF o, si no trae, los de su portada.

    «CUARTO AÑO 1996 - 1997» es 1996-1997. Es lo que dice el inventario del
    cliente, y la fecha de la hoja que no deja leer la suya: ninguna fila sin
    fecha.
    """
    anios = _anios_de(nombre, portada)
    return (min(anios), max(anios)) if anios else (None, None)


def ventana_del_legajo(nombre: str, portada: str = "") -> tuple[int, int]:
    """Los años posibles de las hojas: los del legajo, con margen.

    «RECIBOS DE CAJA» no dice años en el nombre; su portada, «05-09-1995
    18-11-1996». Sin ninguno, de 1950 a 2030.
    """
    anios = _anios_de(nombre, portada)
    return (min(anios) - 3, max(anios) + 3) if anios else (1950, 2030)


def _nombre_limpio(palabras: str, *, cortar: bool = False) -> str | None:
    """Las palabras del nombre; con ``cortar``, hasta lo que la hoja pone detrás de él.

    Sólo en el recibo, que es texto libre: en la matrícula y el certificado el
    nombre viene en su celda, y «CARRERA» puede ser un apellido («DE LA
    CARRERA ALVARADO CESAR J.», EXONERADOS 1991, pág. 7).
    """
    lista = []
    for palabra in re.findall(r"[A-Z]+", palabras):
        if cortar and palabra in _DESPUES_DEL_NOMBRE:
            break
        lista.append(palabra)
    if cortar and lista and _a_medias(lista[-1], "MEDICINA"):
        # La carrera escrita a mano detrás del nombre, mal leída: «MEDICINE»,
        # «MODICINA», «PIEDICINA» (RECIBOS DE CAJA, 2026-11-03).
        lista.pop()
    return " ".join(lista) if len(_plenas(lista)) >= 2 else None


def _siglo(corto: int) -> int:
    return corto if corto >= 100 else (1900 + corto if corto >= 30 else 2000 + corto)


def _celdas_de_la_fila_de(p: str, rotulo: str) -> list[str]:
    """Las celdas de la fila de valores que sigue a la cabecera con ``rotulo``, en una tabla del OCR."""
    renglones = [r for r in p.splitlines() if r.strip()]
    for numero, renglon in enumerate(renglones):
        if rotulo in renglon and "|" in renglon:
            for siguiente in renglones[numero + 1 : numero + 3]:
                if "|" in siguiente and not re.fullmatch(r"[\s|\-:]+", siguiente):
                    return [celda.strip() for celda in siguiente.strip().strip("|").split("|")]
    return []


def leer_hoja(texto: str, tipo: str | None, *, ventana: tuple[int, int] | None = None) -> Hoja:
    """El nombre, el código y la fecha de una hoja suelta, de lo que leyó la IA o la capa.

    ``ventana`` son los años posibles del legajo: el «1.476» del recibo es un
    1996 mal leído, y un año fuera de la ventana no se da.
    """
    p = "\n".join(plano(renglon) for renglon in (texto or "").splitlines())
    nombre = None
    if tipo == MATRICULA_ACADEMICA:
        apellidos, nombres = _APELLIDOS.search(p), _NOMBRES.search(p)
        if apellidos and nombres:
            nombre = _nombre_limpio(f"{apellidos.group(1)} {nombres.group(1)}")
    elif tipo in (CERTIFICADO_DE_MATRICULA, CERTIFICADO_DE_NOTAS):
        celdas = _celdas_de_la_fila_de(p, "NOMBRE DEL ESTUDIANTE")
        nombre = _nombre_limpio(" ".join(c for c in celdas if not re.search(r"\d", c)))
    elif tipo == RECIBO_DE_CAJA and (hallado := _RECIBIDO_DE.search(p)):
        nombre = _nombre_limpio(hallado.group(1), cortar=True)
    codigo = None
    if hallado := _CODIGO_DE_HOJA.search(p):
        codigo = re.sub(r"\s", "", hallado.group(1))

    def en_la_ventana(anio: int) -> bool:
        return ventana is None or ventana[0] <= anio <= ventana[1]

    fecha = anio = None
    if (hallado := _FECHA_DE_EXPEDICION.search(p)) and 1 <= int(hallado.group(2)) <= 12:
        candidata = (int(hallado.group(1)), int(hallado.group(2)), _siglo(int(hallado.group(3))))
        if 1 <= candidata[0] <= 31 and en_la_ventana(candidata[2]):
            fecha = candidata
    if fecha is None and tipo == RECIBO_DE_CAJA and (hallado := _FECHA_EN_CIFRAS.search(p)):
        dia, mes, anio_escrito = int(hallado.group(1)), int(hallado.group(2)), _siglo(int(hallado.group(3)))
        if 1 <= dia <= 31 and 1 <= mes <= 12 and en_la_ventana(anio_escrito):
            fecha = (dia, mes, anio_escrito)
    if fecha is None and tipo == RECIBO_DE_CAJA:
        for patron, dia_mes in ((_FECHA_ESCRITA, (1, 2)), (_FECHA_ESCRITA_MES_PRIMERO, (2, 1))):
            if (hallado := patron.search(p)) and (mes := _MESES.get(hallado.group(dia_mes[1]))):
                anio_escrito = int(hallado.group(3) + hallado.group(4))
                dia = int(hallado.group(dia_mes[0]))
                if 1 <= dia <= 31 and en_la_ventana(anio_escrito):
                    fecha = (dia, mes, anio_escrito)
                    break
    if fecha is None and (hallado := _PERIODO.search(p)) and en_la_ventana(_siglo(int(hallado.group(2)))):
        anio = _siglo(int(hallado.group(2)))
    return Hoja(nombre=nombre, codigo=codigo, fecha=fecha, anio=fecha[2] if fecha else anio)


# -- los expedientes -----------------------------------------------------------------


def _nombre_siguiente(clases: Sequence[str | None], nombres: Mapping[int, str], desde: int) -> str | None:
    """El nombre de la hoja de notas que sigue a una ficha en blanco: el reverso de su cartulina."""
    for numero in range(desde + 1, min(desde + 3, len(clases)) + 1):
        if clases[numero - 1] == FICHA_DE_MEDICINA:
            return None
        if clases[numero - 1] == NOTAS_DE_MEDICINA:
            return nombres.get(numero)
    return None


def expedientes_de_medicina(
    clases: Sequence[str | None], nombres: Mapping[int, str]
) -> list[Expediente]:
    """Los expedientes de un PDF de Medicina, por el nombre de cada ficha y de cada hoja de notas.

    ``clases`` dice qué es cada página (``clase_de_pagina``), en orden, y
    ``nombres`` el nombre que se leyó en las que lo dicen. Una página con un
    nombre distinto del estudiante en curso abre otro expediente; con el mismo,
    o sin nombre, sigue. Una ficha en blanco -- la de la segunda cartulina --
    va con quien diga la hoja de notas de su reverso. Las cartas y lo que no es
    ni ficha ni notas siguen al estudiante en curso. Lo de antes del primer
    estudiante no es de nadie, como en Enfermería.
    """
    resultado: list[Expediente] = []
    del_expediente: list[str | None] = []

    def abrir(numero: int, nombre: str | None, ficha_en: int | None) -> None:
        resultado.append(Expediente(paginas=[numero], ficha=Ficha(nombre=nombre), pagina_de_la_ficha=ficha_en))
        del_expediente.append(nombre)

    for numero, clase in enumerate(clases, start=1):
        actual = resultado[-1] if resultado and resultado[-1].ficha is not None else None
        if clase is None:
            if resultado:
                resultado[-1].paginas.append(numero)
            else:
                resultado.append(Expediente(paginas=[numero], ficha=None))
                del_expediente.append(None)
            continue
        nombre = nombres.get(numero)
        en_blanco = clase == FICHA_DE_MEDICINA and nombre is None
        quien = _nombre_siguiente(clases, nombres, numero) if en_blanco else nombre
        ficha_en = numero if clase == FICHA_DE_MEDICINA else None
        if actual is None:
            abrir(numero, quien, ficha_en)
            continue
        igual = mismo_estudiante(del_expediente[-1], quien)
        if igual is False:
            abrir(numero, quien, ficha_en)
            continue
        actual.paginas.append(numero)
        if del_expediente[-1] is None and quien:
            del_expediente[-1] = quien
        if ficha_en and (actual.pagina_de_la_ficha is None or (nombre and not nombres.get(actual.pagina_de_la_ficha))):
            actual.pagina_de_la_ficha = ficha_en
        if en_blanco and quien is None and igual is None:
            actual.dudas.append(
                f"la ficha de la página {numero} no deja leer el nombre: va con el estudiante de la página anterior"
            )

    for expediente in resultado:
        if expediente.ficha is not None:
            expediente.ficha = Ficha(nombre=_nombre_del_expediente(expediente, clases, nombres))
    _avisar_los_tramos(resultado)
    return resultado


def _nombre_del_expediente(expediente: Expediente, clases: Sequence[str | None], nombres: Mapping[int, str]) -> str | None:
    """El del pie de sus notas, que va con los apellidos primero, como el FUID; si no, el de su ficha."""
    for clase in (NOTAS_DE_MEDICINA, FICHA_DE_MEDICINA):
        for numero in expediente.paginas:
            if clases[numero - 1] == clase and nombres.get(numero):
                return nombres[numero]
    return None


def _avisar_los_tramos(expedientes: Sequence[Expediente]) -> None:
    """El mismo estudiante en dos tramos separados: cada uno dice dónde está el otro.

    El operador prefirió no reordenar el escaneo (2026-11-03): un PDF por
    tramo, cada uno con su fila, y la nota que lo avisa.
    """
    con_nombre = [e for e in expedientes if e.ficha is not None and e.ficha.nombre]
    for uno in con_nombre:
        for otro in con_nombre:
            if otro is not uno and mismo_estudiante(uno.ficha.nombre, otro.ficha.nombre):
                uno.dudas.append(
                    f"el mismo estudiante aparece también en las páginas {otro.paginas[0]} a {otro.paginas[-1]}"
                )
