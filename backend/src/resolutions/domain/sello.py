"""El sello de radicación: dónde empieza cada escrito y con qué número.

Lo dictó el operador: «la mayoría de las veces en la primera página del
documento encontrarás algo como esto, allí está el número de radicado; cada vez
que encuentres un sello nuevo es un nuevo documento». Y después: «cuando no
logres leer muy bien el número en el sello, allí corta hasta ver un nuevo
código de radicado o un nuevo sello».

Hay dos sellos, y se leen distinto:

* **La etiqueta impresa** que la empresa pega al radicar:

      Caribemar de la Costa S.A.S. ESP
      AL CONTESTAR CITE ESTE NUMERO RE3110202139039
      Asunto: 03 RECLAMO   Folios: 3
      Fecha: 08/09/2021 09:17:47.0

  Es letra de máquina, chica: la lectura de la página entera la deja en
  «NUMF.nORK3110202139039», y la del recorte, a 400 ppp, en
  «NUMERORF31 10202140544». De ella sale el radicado y la fecha.
* **El sello de tinta** de la oficina -- «RECIBIDO NO IMPLICA ACEPTACIÓN»,
  «FECHA DE RECIBIDO», «No. DE RADICACIÓN» -- con el número escrito a mano. Se
  reconoce que está, y eso basta para saber que ahí empieza un escrito; el
  número manuscrito no se adivina.

Aquí no se lee papel: entra el texto del recorte donde va el sello.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

#: La etiqueta impresa: «AL CONTESTAR CITE ESTE NUMERO», o «Caribemar de la
#: Costa» -- en una palabra, como la imprime la etiqueta y no como la escribe
#: una carta -- con su «Asunto: 03» o sus «Folios:». Con lo que la OCR hace de
#: cada palabra: «CONTHSTAR», «Cartbomar Je lu Custa», «Tollos:3».
#: Con la puntuación que la OCR mete entre las letras: «CONTRSTAR C'ÍTF».
_CONTESTAR = re.compile(
    r"CONT[EHIR]\w?STA[RN]\W{0,3}C\W{0,2}[IÍ1L]?\W{0,2}T|\bC\W?IT[EF]?\W{0,2}(?:ESTF?|F\.STF)"
    # Partida en dos: «CONTES TnR CITE» (UPD3102756 pág. 51).
    r"|CONT[EHIR]S\s?T[AN][RN]\W{0,3}C\W{0,2}[IÍ1L]?\W{0,2}T"
)
_CARIBEMAR = re.compile(r"C[AU]R[IT]?B[OE]?MA[RS]\s+[DJ][EI]\s+L[AU]\s+C[OU]STA")
_CAMPOS_DE_LA_ETIQUETA = re.compile(r"AS\w{0,2}N?T?O\W{0,2}\s*0\d|[FTIL]\w?L[IL]?OS\s*[:;.]\s*\d")
#: El sello de tinta de la oficina.
_TINTA = re.compile(
    r"RECIBIDO\s+NO|NO\s+IM[PB]LICA|IM[PB]LICA\s*A?C?EPTACI|FECHA\s+[DC]E\s+RECIBIDO"
    # «No. DE RADICACIÓN» del sello, no la «radicación» de cualquier carta.
    r"|N\W{0,3}\s*D[EF]\s+RADICACI"
    # Y sus otros rótulos, cuando la capa rompe los de arriba: «No DE FOLIOS;
    # OIR. NOTIFLCACIGV» (7975593, UPD3126960 pág. 44, 2026-11-12).
    r"|\bN\W?[O0]\s*D[EF]\s+F[O0]L[I1L][O0]S\W{0,2}\s*[DO0]\W?[I1]?R\W{0,3}\s*N[O0]TIF"
)

#: Trece cifras seguidas -- con algún espacio que mete la OCR -- detrás de una
#: letra: «RORF3 110202139039», «NUMFRORE3 110202145449», «KORL3110202250347».
_TRECE_CIFRAS = re.compile(r"(?<=[A-Z\W])(\d(?:\s?\d){12})(?!\s?\d)")
#: La fecha de la etiqueta, que lleva la hora detrás: «17/09/2021 12:32:59.0».
_FECHA_CON_HORA = re.compile(r"(\d{1,2})\s?/\s?(\d{1,2})\s?/\s?(\d{4})\s+\d{1,2}:\d{2}")
#: La línea «Fecha:» como la deja la OCR: «16/03,2022 15:17:44.0»,
#: «09/12/2020) 14:54:26.0», «002/07 2021 17:05:49.0)» (caja 108C000033).
_FECHA_DEL_SELLO = re.compile(
    r"F\w?CH[AI1]\W{0,3}(\d{1,3})\s?[/,.]\s?(\d{1,2})\s?[/,. ]\s?(20\d{2})\W{0,2}\s+\d{1,2}\W?\d{2}"
)
#: «Folios: 3», «lolios:2», «Tollos:3».
_FOLIOS = re.compile(r"[FTIL]?\w?L[IL]?OS\s*[:;.]\s*(\d{1,2})\b")
#: Y como la deja en la caja 108C000033: «Tolios: 4», «Volios: 2»,
#: «Tiolios: 9», «lollos: 2».
_FOLIOS_ROTOS = re.compile(r"(?:\b|[FTVIKL]{1,2})[O0][LI][IL1]?[O0U]S\W{0,2}\s*(\d{1,2})\b")


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.upper())


@dataclass(frozen=True, slots=True)
class Sello:
    """Lo que dice el sello de una hoja."""

    #: «impreso» -- la etiqueta --, «tinta» -- el de la oficina -- o «sspd» --
    #: el radicado de la Superintendencia, que no trae RE --.
    clase: str
    #: «RE3110202139039», o ``None`` si no se pudo leer.
    radicado: str | None = None
    fecha: date | None = None
    #: Cuántas hojas dice que trae el escrito.
    folios: int | None = None

    @property
    def legible(self) -> bool:
        return self.radicado is not None


def _radicado(plano: str) -> str | None:
    """Las trece cifras del radicado: oficina, año (20…) y consecutivo.

    Uno que ya viene con su forma manda sobre uno cuya oficina hubo que
    deducir: «131 0202137028» -- un «3110» al que la OCR comió una cifra --
    daba «4310» aunque más abajo la misma lectura trajera limpio el
    «RE3110202137028» (UPD2326468 p1).
    """
    hallados = [re.sub(r"\s", "", h.group(1)) for h in _TRECE_CIFRAS.finditer(plano)]
    for cifras in hallados:
        if cifras[:4] in OFICINAS_CONOCIDAS and cifras[4:6] == "20":
            return f"RE{cifras}"
    # Oficina (empieza por 2, 3 o 4: «2310», «3110», «4310»), año 20… y
    # consecutivo. «RE7110…» son lecturas malas, no radicados.
    for cifras in map(_con_la_oficina, hallados):
        if cifras[4:6] == "20" and cifras[0] in "234":
            return f"RE{cifras}"
    return None


#: Lo que la OCR hace de cada cifra en la letra chica de la etiqueta, medido en
#: la caja 108C000033: «RE31l0202212114», «RE? i 10202108100»,
#: «LES 110202269A85». Cada carácter, con las cifras que puede ser.
_CIFRAS_PARECIDAS: dict[str, str] = {
    **{d: d for d in "0123456789"},
    "L": "1", "I": "1", "|": "1", "!": "1", "J": "1",
    "O": "0", "D": "0", "Q": "0", "U": "0",
    "A": "4",
    "S": "53",
    "B": "8",
    "Z": "2",
    "G": "6",
    "?": "37",
}
#: Detrás de qué se busca: «NUMERO», como lo deja la OCR («NUMF.NORK»,
#: «NUMERORF»).
_NUMERO = re.compile(r"NU\W?[MVW]|MER[O0]|C\W?ITE\W+ESTE")
#: Las oficinas que radican: «3110» (Valledupar), «3120», «4310»… -- empiezan
#: por 3 o 4 --, el año y el consecutivo.
_FORMA_DEL_RADICADO = re.compile(r"[234]\d{3}20(1[89]|2\d)\d{5}")


#: El número interno que la etiqueta imprime encima del radicado empieza por el
#: año: «202260026584» es de 2022, «202100014084» de 2021. Sirve de fecha cuando la OCR perdió la línea
#: «Fecha:» (UPD2326302 p1).
_NUMERO_INTERNO = re.compile(r"(?<!\d)(20(?:1[89]|2\d))\d{8}(?!\d)")


def anio_del_sello(texto: str, fecha: date | None = None) -> int | None:
    """El año de la etiqueta: el de su fecha, o el de su número interno."""
    if fecha is not None:
        return fecha.year
    hallado = _NUMERO_INTERNO.search(_plano(texto or ""))
    return int(hallado.group(1)) if hallado else None


#: Las oficinas que radican, por las tres cifras que siguen a la primera. La
#: OCR yerra la primera más que ninguna -- «RE2|10…», «RE7110…» --, y las
#: otras tres bastan para saber cuál es.
_OFICINAS = {"110": "3110", "120": "3120", "310": "4310"}
#: Las oficinas que radican, enteras, y que no se corrigen. La 2310 es la de
#: Bolívar Sur (Magangué): «RE2310202321592» a mano en el sello de UPD3102756.
#: Su «310» es también el de la 4310, y deducir la oficina por esas tres cifras
#: convertía el RE2310… en un RE4310… que no existe.
OFICINAS_CONOCIDAS = frozenset({"3110", "3120", "4310", "2310"})
#: Las oficinas que radican, para validar el RE escrito a mano en un sello de
#: tinta: las conocidas, la 2311 de Santa Rosa del Sur (los sellos de 1005965,
#: «RE2311202302499» y «RE2311202302952») y las que se repiten impresas en el
#: corpus de Afinia (9233, 9234, 8310). No corrige la lectura de nada: sólo
#: decide si se cree un RE a mano. Se suman las de los RE impresos de la caja.
OFICINAS_QUE_RADICAN = OFICINAS_CONOCIDAS | frozenset({"2311", "9233", "9234", "8310"})
_RE_ENTERO = re.compile(r"RE\d{13}")


def validar_el_re_a_mano(
    radicado: str | None, fecha: date | None, oficinas_de_la_caja: Iterable[str] = ()
) -> tuple[str | None, str]:
    """El RE escrito a mano de un sello, si se cree, y por qué; ``(None, motivo)`` si no.

    La validación del agente (2026-11-11), sobre lo que la IA leyó a mano:

    - un RE entero, «RE» y trece cifras;
    - su año, el de la fecha del sello si se leyó: «RE2311**2023**02952» con «28-08-23»;
    - su oficina, una que radica (``OFICINAS_QUE_RADICAN`` y las de la caja).
      Si no lo es pero está a una sola cifra de una única que sí, es ésa: la IA
      leyó «RE2371202302499» por «RE2311202302499» (1005965 p1). Si está a una
      cifra de dos, o de ninguna, no se cree.
    """
    if not radicado or not _RE_ENTERO.fullmatch(radicado.upper()):
        return None, "no es un RE entero"
    radicado = radicado.upper()
    if fecha is not None and radicado[6:10] != str(fecha.year):
        return None, f"su año ({radicado[6:10]}) no es el de la fecha del sello ({fecha.year})"
    validas = OFICINAS_QUE_RADICAN | frozenset(oficinas_de_la_caja)
    oficina = radicado[2:6]
    if oficina in validas:
        return radicado, ""
    cercanas = sorted(o for o in validas if len(o) == 4 and sum(a != b for a, b in zip(o, oficina, strict=True)) == 1)
    if len(cercanas) == 1:
        return f"RE{cercanas[0]}{radicado[6:]}", f"oficina {oficina} leída por {cercanas[0]}"
    return None, f"la oficina {oficina} no es ninguna que radique"


#: «No DE RADICACION: RE 23102021094662», «No DE RADIACION LE 23102021041663»:
#: el número a mano del sello de tinta como lo transcribe la IA.
_NUMERO_DE_RADICACION = re.compile(r"RADI\w{0,5}N\W{0,3}\s*(?:[RL]\s?[EF]\W?\s*)?((?:\d\s?){13,15})")


def radicado_con_una_cifra_de_mas(
    texto: str, conocidos: Iterable[str] = (), anio: int | None = None, oficinas: Iterable[str] = ()
) -> str | None:
    """El RE a mano del sello de tinta cuando la IA lo leyó con una cifra de más.

    En 7975593 (2026-11-12) la IA leyó «RE 23102021094662» por RE2310202104662
    y «LE 23102021041663» por RE2310202104663: catorce cifras. Se prueba a
    quitar cada una; vale la que deja un RE de una oficina que radica, del año
    del sello. Si quedan varias, la que ya está escrita en la caja; si no, no se
    adivina.
    """
    validas = OFICINAS_QUE_RADICAN | frozenset(oficinas)
    conocidos = {c.upper() for c in conocidos}
    for hallado in _NUMERO_DE_RADICACION.finditer(_plano(texto or "")):
        cifras = re.sub(r"\D", "", hallado.group(1))
        if len(cifras) == 13:
            candidatas = {cifras}
        elif len(cifras) == 14:
            candidatas = {cifras[:i] + cifras[i + 1 :] for i in range(14)}
        else:
            continue
        posibles = sorted(
            c for c in candidatas if c[:4] in validas and c[4:6] == "20" and (anio is None or c[4:8] == str(anio))
        )
        en_la_caja = [c for c in posibles if f"RE{c}" in conocidos]
        if len(en_la_caja) == 1:
            return f"RE{en_la_caja[0]}"
        if len(posibles) == 1:
            return f"RE{posibles[0]}"
    return None


#: Un radicado impreso en el texto de la caja, con «RE» o sin él: «RE 2310202321859»,
#: «… ES RECLAMACION No- 2310202403978».
_RADICADO_IMPRESO = re.compile(r"(?<![\d])(?:RE\s?)?(\d{4})(20\d{7})(?!\d)")


def radicados_impresos(texto: str) -> set[str]:
    """Los RE que trae impresos -- o a máquina -- el texto de una hoja, de una oficina que radica."""
    return {
        f"RE{oficina}{resto}"
        for oficina, resto in _RADICADO_IMPRESO.findall((texto or "").upper())
        if oficina in OFICINAS_QUE_RADICAN
    }


def el_impreso_a_una_cifra(leido: str | None, impresos: Iterable[str]) -> str | None:
    """El RE impreso en la caja que está a una sola cifra del leído a mano en un sello, si es uno solo; si no, ``None``.

    Lo impreso es texto fiable; la letra a mano, no. En 7975593 (UPD3126960,
    2026-11-13) la IA leyó «…03578» en el sello de la reclamación de B33, y el
    recurso de B44 dice impreso «ES RECLAMACION No- 2310202403978»; leyó
    «…21059» en el de B9, y la hoja trae impreso «RE 2310202321859». Leído
    igual a uno impreso, o a una cifra de dos, no se toca.
    """
    if not leido or not _RE_ENTERO.fullmatch(leido.upper()):
        return None
    leido = leido.upper()
    impresos = {i.upper() for i in impresos if _RE_ENTERO.fullmatch(i.upper())}
    if leido in impresos:
        return None
    cerca = [i for i in impresos if sum(a != b for a, b in zip(i, leido, strict=True)) == 1]
    return cerca[0] if len(cerca) == 1 else None


#: Lo que la IA transcribe tras «RE» en la letra a mano: «REB3102021034V2»,
#: «RE 23/02021/03442», «KEP310202105408».
_RE_DIFUSO = re.compile(r"\b[RKL]\s?[EF]\s?[-.:]?\s?([0-9A-Z/][0-9A-Z/ ]{10,17})")
#: Cuántos cambios -- letras por cifras, una barra de más -- se le perdonan a
#: la lectura a mano para casarla con un RE de la caja, y cuántos más tiene que
#: tener el segundo más parecido para que no haya duda.
CAMBIOS_QUE_SE_PERDONAN = 2
VENTAJA_SOBRE_EL_SEGUNDO = 2
#: Con menos caracteres que estos, la lectura no se casa con ningún RE.
LARGO_MINIMO_DE_LA_LECTURA = 11


def _cambios(una: str, otra: str) -> int:
    """La distancia de edición entre dos cadenas: cuántas letras hay que cambiar, quitar o poner."""
    anterior = list(range(len(otra) + 1))
    for i, a in enumerate(una, start=1):
        actual = [i]
        for j, b in enumerate(otra, start=1):
            actual.append(min(anterior[j] + 1, actual[j - 1] + 1, anterior[j - 1] + (a != b)))
        anterior = actual
    return anterior[-1]


#: Desde cuántas cifras lo que sigue a «RE» es un RE a mano y no una palabra:
#: «RECIBIDO NO IMPLICA» no tiene ninguna; «KEP310202105408», doce.
CIFRAS_DE_UN_RE_A_MANO = 8


def _lecturas_de_un_re(texto: str) -> list[str]:
    """Lo que sigue a cada «RE» de la lectura y tiene cifras de RE, sin los blancos."""
    return [
        re.sub(r"\s", "", hallado.group(1))[:16]
        for hallado in _RE_DIFUSO.finditer((texto or "").upper())
        if sum(c.isdigit() for c in hallado.group(1)) >= CIFRAS_DE_UN_RE_A_MANO
    ]


def trae_un_re_a_mano(texto: str) -> bool:
    """Si la lectura del sello trae algo escrito como un RE, se lea o no: «KEP310202105408»."""
    return bool(_lecturas_de_un_re(texto))


def el_conocido_por_la_lectura(texto: str, conocidos: Iterable[str]) -> str | None:
    """El RE de la caja que casa con la lectura a mano ilegible del sello, si casa uno solo y sin duda.

    La IA deja la letra a mano con letras por cifras y barras de más:
    «REB3102021034V2» y «RE 23/02021/03442» son el RE2310202103442 que el
    escrito imprime en sus propias hojas (7975593, UPD2460819 págs. 52 y 95;
    2026-11-13). Vale el RE a ``CAMBIOS_QUE_SE_PERDONAN`` cambios o menos, si el
    segundo más parecido está a ``VENTAJA_SOBRE_EL_SEGUNDO`` más. ``conocidos``
    son los RE impresos en las hojas que cubren los folios del sello, no los
    de toda la caja: contra toda la caja la hoja 52 quedaba a dos del suyo y a
    tres del RE…05402, y «KEP310202105408» (hoja 176) a uno de la errata
    RE8310202105408 que el cliente repite en sus cartas.
    """
    conocidos = sorted({c.upper()[2:] for c in conocidos if _RE_ENTERO.fullmatch(c.upper())})
    if not conocidos:
        return None
    for leido in _lecturas_de_un_re(texto):
        # Sin los blancos puede quedar corto: «RE 2 3 1 0 …» con huecos. Un RE
        # tiene trece cifras; con menos de once no hay con qué casarlo.
        if len(leido) < LARGO_MINIMO_DE_LA_LECTURA:
            continue
        largos = range(min(12, len(leido)), len(leido) + 1)
        distancias = sorted((min(_cambios(leido[:largo], c) for largo in largos), c) for c in conocidos)
        mejor, cual = distancias[0]
        segundo = distancias[1][0] if len(distancias) > 1 else None
        if mejor <= CAMBIOS_QUE_SE_PERDONAN and (segundo is None or segundo >= mejor + VENTAJA_SOBRE_EL_SEGUNDO):
            return f"RE{cual}"
    return None


def el_de_su_tramite(leido: str | None, del_tramite: str | None) -> str | None:
    """El RE del trámite del documento cuando el de su sello, leído a mano, está a una sola cifra de él; si no, ``None``.

    El recurso se radica con el RE de la reclamación que recurre. En 7975593
    (UPD3126960 pág. 9, 2026-11-13) la IA leyó «Re 231020232-1059» en el sello
    del recurso del trámite RE2310202321859: una cifra cambiada. Sólo contra el
    RE de su propio trámite, nunca contra cualquiera de la caja: en la misma
    caja RE2310202403578 y RE2310202403978 son a una cifra y pueden ser dos.
    """
    if not leido or not del_tramite:
        return None
    leido, del_tramite = leido.upper(), del_tramite.upper()
    if not (_RE_ENTERO.fullmatch(leido) and _RE_ENTERO.fullmatch(del_tramite)) or leido == del_tramite:
        return None
    return del_tramite if sum(a != b for a, b in zip(leido, del_tramite, strict=True)) == 1 else None


def re_del_sello(sello: Sello, oficinas_de_la_caja: Iterable[str] = ()) -> tuple[str | None, str]:
    """El RE de un sello que se cree, y la nota del agente: el impreso tal cual, el de tinta validado."""
    if sello.clase != "tinta":
        impreso = (sello.radicado or "").strip().upper()
        return (impreso if _RE_ENTERO.fullmatch(impreso) else None), ""
    if not sello.radicado:
        return None, ""
    return validar_el_re_a_mano(sello.radicado, sello.fecha, oficinas_de_la_caja)


#: Desde cuántos sellos con RE distinto en un mismo PDF se avisa y lo revisa el
#: agente (el operador, 2026-11-12: «cuando me dividas un PDF y tenga más de 2
#: sellos, me avises»; precisó: desde 2, contando cada RE una vez).
SELLOS_PARA_AVISAR = 2


def res_del_documento(paginas: Iterable[int], res: Mapping[int, str]) -> list[tuple[int, str]]:
    """Los RE distintos de los sellos de un documento, cada uno con su primera hoja, en el orden del papel.

    ``res`` es, por hoja, el RE de su sello que se cree (``re_del_sello``). El
    mismo RE en varias hojas -- el sello repetido en la copia -- cuenta una vez.
    """
    vistos: dict[str, int] = {}
    for pagina in sorted(paginas):
        radicado = res.get(pagina)
        if radicado and radicado not in vistos:
            vistos[radicado] = pagina
    return [(pagina, radicado) for radicado, pagina in vistos.items()]


#: Cuántas letras se aceptan en lugar de cifras al leer un radicado roto.
LETRAS_QUE_SE_PERDONAN = 2


def _con_la_oficina(cifras: str) -> str:
    """Las cifras con su oficina deducida de las tres que siguen a la primera.

    «7110…», «2110…», «4110…»: no hay oficina 4110; con «110» detrás es la
    3110. Una oficina conocida no se toca, y las que no se conocen se dejan
    como vienen.
    """
    if cifras[:4] in OFICINAS_CONOCIDAS:
        return cifras
    if cifras[1:4] in _OFICINAS and cifras[:4] != _OFICINAS[cifras[1:4]]:
        return _OFICINAS[cifras[1:4]] + cifras[4:]
    return cifras


def _radicado_aproximado(plano: str, fecha: date | None) -> str | None:
    """El radicado que la OCR dejó con letras en lugar de cifras, o ``None``.

    Sólo detrás de «NUMERO», y sólo si lo que resulta tiene la forma exacta de
    un radicado y su año es el de la fecha del mismo sello: con esa doble
    comprobación una lectura dudosa se descarta en vez de inventar un número.
    Sin fecha legible en el sello no se aproxima nada.
    """
    anio = anio_del_sello(plano, fecha)
    if anio is None:
        return None
    for ancla in _NUMERO.finditer(plano):
        ventana = re.sub(r"[\s.,:;'\"`´-]", "", plano[ancla.end() : ancla.end() + 34])
        for inicio in range(0, min(len(ventana), 14)):
            trozo = ventana[inicio : inicio + 13]
            if len(trozo) < 13 or any(c not in _CIFRAS_PARECIDAS for c in trozo):
                continue
            # Pocas letras y casi ninguna en el consecutivo: con más, la lectura
            # ya no es de un número sino ruido que casualmente encaja
            # («RE J 11020212SOI3» daba un radicado que no existe, UPD2326310).
            letras = [i for i, c in enumerate(trozo) if not c.isdigit()]
            if len(letras) > LETRAS_QUE_SE_PERDONAN or sum(i >= 8 for i in letras) > 1:
                continue
            candidatos = [""]
            for c in trozo:
                candidatos = [hecho + d for hecho in candidatos for d in _CIFRAS_PARECIDAS[c]]
                if len(candidatos) > 64:
                    break
            for cifras in candidatos:
                cifras = _con_la_oficina(cifras)
                if _FORMA_DEL_RADICADO.fullmatch(cifras) and int(cifras[4:8]) == anio:
                    return f"RE{cifras}"
    return None


def radicado_aproximado(texto: str, fecha: date | None) -> str | None:
    """El radicado de un texto del sello con las cifras que la OCR volvió letras."""
    return _radicado_aproximado(_plano(texto or ""), fecha)


#: Cuántas cifras finales tienen que coincidir para reconocer un radicado de la
#: caja en una lectura que perdió el principio: el año y el consecutivo.
CIFRAS_DE_LA_COLA = 9


def radicado_por_la_cola(texto: str, conocidos: Iterable[str]) -> str | None:
    """El radicado de la caja cuya cola aparece limpia en la lectura del sello.

    «…%IOREBU0202269485» (UPD2326307 p3) perdió «311» pero dejó «0202269485»,
    y la caja cita en otra hoja «RE3110202269485». Sólo si un único radicado
    conocido termina así: con dos candidatos no se elige.
    """
    plano = _plano(texto or "")
    colas = {m.group(0) for m in re.finditer(rf"\d{{{CIFRAS_DE_LA_COLA},}}", plano.replace(" ", ""))}
    hallados = {
        conocido
        for conocido in conocidos
        for cola in colas
        if len(cola) >= CIFRAS_DE_LA_COLA and conocido.endswith(cola[-CIFRAS_DE_LA_COLA:])
        and cola[-CIFRAS_DE_LA_COLA:][:2] == "20"
    }
    return hallados.pop() if len(hallados) == 1 else None


#: El RE escrito junto al sello -- a mano encima del sello de tinta o impreso
#: en la etiqueta --: «RE2310202321592», «RE 2310 2023 21592», «NUMERORE2310…»,
#: y como la IA lee la letra a mano: «RE23102023214Y3», «RE 23/0 2024 003 48».
#: Sin pasar de renglón: lo de debajo -- el «DIR.» de «DIR. NOTIFICACIÓN» --
#: no es parte del número (UPD3102756 pág. 42 daba RE…00301 con ese «DI»).
_RE_ESCRITO = re.compile(r"R[ \t]?[EF£][ \t]?[-.:]?[ \t]?((?:[0-9OILYSZBGQTD|/](?:[ \t]|[.-](?=\d))?){11,16})")
#: Lo que la letra a mano hace de cada cifra al leerla (UPD3102756, sellos de
#: Bolívar Sur leídos por la IA): la Y es un 4, la D un 0.
_LETRA_POR_CIFRA = {
    "O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1",
    "Z": "2", "Y": "4", "S": "5", "G": "6", "T": "7", "B": "8",
}
#: Y la que puede ser dos cifras: la barra es un 1 en «23/0» (la oficina 2310)
#: y un 4 en «003/8» (RE…00348, UPD3102756 pág. 42). Sólo se acepta donde hay
#: con qué comprobarla: en la oficina, que tiene que ser una conocida, y en el
#: año, que tiene que ser el del sello. En el consecutivo no se adivina.
_LETRA_DUDOSA = {"/": "14"}
#: «FECHA DE RECIBIDO: 10-11-2023» del sello de tinta: su año valida el RE.
_FECHA_DE_RECIBIDO = re.compile(r"RECIBID[O0]\W{0,4}(\d{1,2})\s?[-/.]\s?(\d{1,2})\s?[-/.]\s?(20\d{2})")


def _del_anio(cifras: str, anio: int | None) -> bool:
    if not _FORMA_DEL_RADICADO.fullmatch(cifras):
        return False
    return anio is None or int(cifras[4:8]) in (anio, anio + 1)


def _trece_comprobadas(crudo: str, anio: int | None) -> str | None:
    """Las trece cifras de una lectura con sus letras dudosas resueltas, o ``None``.

    Cada letra dudosa da varias lecturas; vale la única que cuadra, y sólo si
    las dudas caen en la oficina (que tiene que ser una conocida) o en el año
    (que tiene que ser el del sello).
    """
    dudosas = [i for i, c in enumerate(crudo) if c in _LETRA_DUDOSA]
    if any(i >= 8 for i in dudosas) or (any(4 <= i < 8 for i in dudosas) and anio is None):
        return None
    lecturas = [""]
    for c in crudo:
        lecturas = [hecho + d for hecho in lecturas for d in _LETRA_DUDOSA.get(c, _LETRA_POR_CIFRA.get(c, c))]
    validas = {
        cifras
        for cifras in lecturas
        if _del_anio(cifras, anio)
        and (not any(i < 4 for i in dudosas) or cifras[:4] in OFICINAS_CONOCIDAS)
        and (not any(4 <= i < 8 for i in dudosas) or int(cifras[4:8]) == anio)
    }
    return validas.pop() if len(validas) == 1 else None


def radicado_escrito(texto: str, anio: int | None = None) -> str | None:
    """El RE que trae escrito una lectura del sello, si cuadra; ``None`` si no.

    Cuadra si tiene oficina (cuatro cifras que empiezan por 2, 3 o 4), el año
    entre 2018 y 2029 y, si se sabe ``anio`` -- el de la carta que radica, o si
    no el de la «FECHA DE RECIBIDO» del propio sello --, ese año o el siguiente
    (la carta del 28 de diciembre se radica en enero). Así una lectura mala de
    la letra a mano se descarta en vez de inventar un número: el operador
    quiere el RE del sello, no uno parecido.

    Se perdonan hasta ``LETRAS_QUE_SE_PERDONAN`` letras en lugar de cifras
    («214Y3» → «21443», «23/0» → «2310»), una cifra repetida en el
    consecutivo, sólo si hay una sola manera de quitarla («…2024114223» →
    «…202414223»), y una cifra que falte **en el año**, sólo si se sabe el año
    y hay una sola manera de ponerla («RE231020202596» con el sello del
    08-02-2024 → RE2310202402596). El consecutivo nunca se completa: ahí no
    hay con qué comprobarlo.

    El número sólo termina donde termina uno de sus grupos: la IA deja la
    letra a mano en grupos -- «RE23 10 20 24 07 55D» -- y lo que viene detrás
    -- el «09» de la dirección en «RE231020202596 09#18-04» -- no es parte de él.
    """
    plano = (texto or "").upper()
    if anio is None and (recibido := _FECHA_DE_RECIBIDO.search(plano)):
        anio = int(recibido.group(3))
    for hallado in _RE_ESCRITO.finditer(plano):
        # Los finales posibles: donde acaba cada grupo, con no más letras de
        # las que se perdonan. El punto y el guion entre grupos también los
        # separan: «RE23102024.03978», «Re 231020232-1059» (7975593, UPD3126960
        # págs. 44 y 9; 2026-11-13).
        crudos: dict[int, str] = {}
        crudo = ""
        for grupo in re.sub(r"(?<=\d)[.-](?=\d)", " ", hallado.group(1)).split():
            # Un grupo sin cifras ya es otra palabra: la «O» de «OFICINA».
            if not any(c.isdigit() for c in grupo):
                break
            crudo += grupo
            if sum(not c.isdigit() for c in crudo) > LETRAS_QUE_SE_PERDONAN:
                break
            crudos[len(crudo)] = crudo
        # Trece cifras, como se escribió.
        if 13 in crudos and (trece := _trece_comprobadas(crudos[13], anio)):
            return f"RE{trece}"
        # Lo que hay que reparar -- una cifra de más o de menos -- no se repara
        # sobre una letra dudosa: serían dos conjeturas sobre el mismo número.
        finales = {
            largo: "".join(_LETRA_POR_CIFRA.get(c, c) for c in crudo)
            for largo, crudo in crudos.items()
            if not any(c in _LETRA_DUDOSA for c in crudo)
        }
        # Catorce, con una cifra del consecutivo repetida.
        if 14 in finales:
            catorce = finales[14]
            quitando = {
                catorce[:i] + catorce[i + 1 :] for i in range(8, 14) if catorce[i] == catorce[i - 1]
            }
            validos = {c for c in quitando if _del_anio(c, anio)}
            if len(validos) == 1:
                return f"RE{validos.pop()}"
        # Doce, con la cifra que falta en el año.
        if 12 in finales and anio is not None:
            doce = finales[12]
            puestas = {doce[:i] + cifra + doce[i:] for i in range(4, 9) for cifra in "0123456789"}
            validas = {c for c in puestas if _FORMA_DEL_RADICADO.fullmatch(c) and int(c[4:8]) == anio}
            if len(validas) == 1:
                return f"RE{validas.pop()}"
    return None


def radicado_del_texto(texto: str) -> str | None:
    """El radicado de trece cifras que trae un texto del sello, o ``None``."""
    return _radicado(_plano(texto or ""))


#: La fecha a mano del sello de tinta, como la transcribe la IA del recorte:
#: «FECHA DE RECIBIDO: 20/12/2023 11:37», «21-02-2022.», «24-06-2022. FECHA
#: DE RECIBIDO» (el rótulo detrás de su cifra), o al pie del recuadro,
#: «FUNCIONARIO RECEPTOR: 27-01-2022» (2026-11-10, sobre ocho sellos reales).
_FECHA_A_MANO = re.compile(r"(?<![\d/.-])(\d{1,2})\s?[/.-]\s?(\d{1,2})\s?[/.-]\s?(\d{4}|\d{2})(?![\d/-])")
_RECIBIDO = re.compile(r"F\w?CH[AI1]\s+D[EF]\s+RECIB")
#: Cuánto texto alrededor del rótulo «FECHA DE RECIBIDO» es suyo.
_ALREDEDOR_DEL_RECIBIDO = 90


def fecha_del_sello_de_tinta(texto: str, *, hoy: date | None = None) -> date | None:
    """La fecha escrita a mano en el sello de tinta, leída por la IA del recorte.

    Sólo para la lectura de la IA: Tesseract deja esa letra en «0aa Z- O -
    2027», y una cifra inventada fecharía mal el documento, porque el sello
    manda (el operador, 2026-11-10). La más cercana al rótulo «FECHA DE
    RECIBIDO»; sin rótulo legible, la única fecha del recorte -- si hay dos,
    no se sabe cuál es --.
    """
    plano = _plano(texto or "")
    if not _TINTA.search(plano):
        return None
    hoy = hoy or date.today()

    def valida(hallado: re.Match[str]) -> date | None:
        dia, mes, anio = (int(g) for g in hallado.groups())
        anio = anio + 2000 if anio < 100 else anio
        try:
            fecha = date(anio, mes, dia)
        except ValueError:
            return None
        return fecha if date(2000, 1, 1) <= fecha <= hoy else None

    fechas = [(h.start(), f) for h in _FECHA_A_MANO.finditer(plano) if (f := valida(h))]
    if not fechas:
        return None
    rotulo = _RECIBIDO.search(plano)
    if rotulo:
        cerca = [(abs(i - rotulo.end()), f) for i, f in fechas if abs(i - rotulo.end()) <= _ALREDEDOR_DEL_RECIBIDO]
        if cerca:
            return min(cerca, key=lambda par: par[0])[1]
    distintas = {f for _, f in fechas}
    return distintas.pop() if len(distintas) == 1 else None


_NUMEROS_EN_LETRA = {
    "UNO": 1, "UN": 1, "DOS": 2, "TRES": 3, "CUATRO": 4, "CINCO": 5, "SEIS": 6, "SIETE": 7, "OCHO": 8,
    "NUEVE": 9, "DIEZ": 10, "ONCE": 11, "DOCE": 12, "TRECE": 13, "CATORCE": 14, "QUINCE": 15,
    "DIECISEIS": 16, "DIECISIETE": 17, "DIECIOCHO": 18, "DIECINUEVE": 19, "VEINTE": 20,
}
#: «No DE FOLIOS: DOCE (12) FOLIOS», «DOS(2)», «(Cuatro (4) Folios)»: la
#: palabra y la cifra entre paréntesis, como se llena a mano el sello de tinta.
_FOLIOS_A_MANO = re.compile(r"\b([A-Z]{2,12})\s*\(\s*(\d{1,2})\s*\)")


def folios_del_sello_de_tinta(texto: str) -> int | None:
    """Los folios escritos a mano en el sello de tinta, leídos por la IA del recorte.

    Sólo si la palabra y la cifra dicen lo mismo: un «DOCE (42)» -- así lo
    dejó Tesseract en UPD2365925 p36 -- retendría treinta hojas ajenas detrás
    del escrito (regla F2b). Con «OCR + IA», 2026-11-11.
    """
    plano = _plano(texto or "")
    if not _TINTA.search(plano):
        return None
    for hallado in _FOLIOS_A_MANO.finditer(plano):
        palabra, cifra = hallado.group(1), int(hallado.group(2))
        if _NUMEROS_EN_LETRA.get(palabra) == cifra and cifra > 0:
            return cifra
    # Y como se llena en Magangué (7975593, 2026-11-12): «(5) cinco Folios»,
    # con la cifra delante y la palabra que dice lo mismo; «8 folios.» o «No DE
    # FOLIOS: 10», la cifra sola junto a la palabra «folios». Nunca un número
    # largo: el «No DE FOLIOS: 202260173102» es el número interno, corrido de
    # renglón.
    for hallado in _CIFRA_Y_PALABRA.finditer(plano):
        cifra, palabra = int(hallado.group(1)), hallado.group(2)
        if _NUMEROS_EN_LETRA.get(palabra) == cifra and cifra > 0:
            return cifra
    for patron in (_CIFRA_Y_FOLIOS, _FOLIOS_Y_CIFRA):
        if (hallado := patron.search(plano)) and 0 < int(hallado.group(1)) <= FOLIOS_DE_UN_ESCRITO:
            return int(hallado.group(1))
    return None


#: «(5) CINCO FOLIOS».
_CIFRA_Y_PALABRA = re.compile(r"\(\s*(\d{1,2})\s*\)\s*([A-Z]{2,12})")
#: «8 FOLIOS».
_CIFRA_Y_FOLIOS = re.compile(r"(?<![\d.,/-])(\d{1,2})\s*F[O0]L[I1L][O0]S?\b")
#: «No DE FOLIOS: 10».
_FOLIOS_Y_CIFRA = re.compile(r"D[EF]\s+F[O0]L[I1L][O0]S\W{0,3}\s*(\d{1,2})(?![\d.,/-])")
#: Más folios que éstos no los declara un escrito de la caja: es una lectura mala.
FOLIOS_DE_UN_ESCRITO = 60


def _fecha(plano: str) -> date | None:
    for hallado in (*_FECHA_CON_HORA.finditer(plano), *_FECHA_DEL_SELLO.finditer(plano)):
        try:
            # «002/07» es el 02: el día son sus dos últimas cifras.
            return date(int(hallado.group(3)), int(hallado.group(2)), int(hallado.group(1)[-2:]))
        except ValueError:
            continue
    return None


#: El radicado de la Superintendencia de Servicios Públicos en el escrito que
#: se le presenta por internet: «SSPD Número de Radicado 20215290025562». Su
#: «Al contestar cite el número» se parece a la etiqueta de la empresa, pero no
#: trae RE ni lo traerá nunca (UPD2326352 p5, UPD2326389 p9). La sola mención
#: de la SSPD no cuenta: el formulario de la empresa dice «apelación ante la
#: SSPD».
_RADICADO_SSPD = re.compile(r"SSPD\W{0,3}N\W?U\W?M\w{0,4}\s+D[EF]\s+RADICAD[O0]\W{0,3}(\d{10,14})")


def es_radicado_de_la_superintendencia(texto: str) -> bool:
    """Si el recorte trae el radicado de la SSPD, no el sello de la empresa."""
    return bool(_RADICADO_SSPD.search(_plano(texto)))


def numero_de_la_superintendencia(texto: str) -> str | None:
    """El número que la SSPD le dio al escrito: «SSPD Número de Radicado 20238004468522»."""
    hallado = _RADICADO_SSPD.search(_plano(texto))
    return hallado.group(1) if hallado else None


def leer_sello(texto: str) -> Sello | None:
    """El sello que trae el recorte, o ``None`` si no trae ninguno."""
    plano = _plano(texto)
    if _RADICADO_SSPD.search(plano):
        return Sello(clase="sspd", fecha=_fecha(plano))
    impreso = bool(_CONTESTAR.search(plano)) or (
        bool(_CARIBEMAR.search(plano)) and bool(_CAMPOS_DE_LA_ETIQUETA.search(plano))
    )
    if impreso:
        folios = _FOLIOS.search(plano) or _FOLIOS_ROTOS.search(plano)
        fecha = _fecha(plano)
        return Sello(
            clase="impreso",
            radicado=_radicado(plano) or _radicado_aproximado(plano, fecha),
            fecha=fecha,
            folios=int(folios.group(1)) if folios else None,
        )
    if _TINTA.search(plano):
        return Sello(clase="tinta")
    return None


# -- la guía de envío de LECTA ------------------------------------------------------
#
# Lo dictó el operador después del sello: la carta de la empresa que lleva
# pegada la etiqueta de envío de LECTA -- el recuadro con «No. Guía», «Orden de
# Servicio», «Remitente», «Destinatario» -- es un documento aparte; y la guía de
# entrega de hoja entera -- «FECHA DE ENTREGA O INTENTO DE ENTREGA» -- que va
# justo antes de esa carta es de ella, no del documento anterior.

#: Lo que identifica a LECTA aunque la OCR le rompa el nombre («JJÍCTA»,
#: «l.i:CTA»): su NIT, su dirección y su página.
_LECTA = re.compile(r"806\W?003\W?042|PIE\s+DEL\s+CERRO|L[EA]CTA\W?COM|\bLECTA\b|N[O0]\W{0,2}GU[I1]A")
#: La guía de entrega de hoja entera.
_GUIA_DE_ENTREGA = re.compile(r"(?:FECHA\s+[DO]E\s+ENTREGA|INTENTO\s+[DO]E\s+E)")
#: Lo que imprime la carta de la empresa.
_CARTA = re.compile(r"\bCONSECUTIVO\s+N|\bASUNTO\b")
#: Dónde se buscan: en la cabecera de la hoja.
CABEZA_DEL_ENVIO = 900


def es_guia_de_envio(texto: str) -> bool:
    """La guía de entrega de LECTA de hoja entera: no es una carta."""
    cabeza = _plano(texto)[:CABEZA_DEL_ENVIO]
    return bool(_GUIA_DE_ENTREGA.search(cabeza)) and not _CARTA.search(cabeza)


def lleva_etiqueta_de_envio(texto: str) -> bool:
    """La carta de la empresa con la etiqueta de LECTA pegada: abre documento."""
    cabeza = _plano(texto)[:CABEZA_DEL_ENVIO]
    return bool(_LECTA.search(cabeza)) and bool(_CARTA.search(_plano(texto))) and not es_guia_de_envio(texto)


def _distancia(una: str, otra: str) -> int:
    return sum(a != b for a, b in zip(una, otra, strict=True)) if len(una) == len(otra) else 99


#: Cuántas cifras puede errar la OCR del sello para tomar el radicado bien
#: escrito de la caja: «RE3110202202487» leído contra el «RE3110202202887» que
#: trae la citación.
CIFRAS_QUE_SE_PERDONAN = 1


def con_los_conocidos(radicado: str | None, conocidos: Iterable[str]) -> str | None:
    """El radicado del sello, corregido con uno bien leído de la caja si hay uno solo cerca."""
    if radicado is None:
        return None
    conocidos = set(conocidos)
    if radicado in conocidos:
        return radicado
    cercanos = [c for c in conocidos if _distancia(c, radicado) <= CIFRAS_QUE_SE_PERDONAN]
    return cercanos[0] if len(cercanos) == 1 else radicado


#: El número de guía de LECTA, entre asteriscos como lo imprime el código de
#: barras: «*78725339023*». La OCR lo deja «•7e725339023*» en la etiqueta de la
#: carta y «*78725339023*» en su guía de entrega (UPD2326321 p2 y p3).
_NUMERO_DE_GUIA = re.compile(r"[*•‘'’]\s?(7[0-9A-Za-z]{10})(?![0-9A-Za-z])|(?<![0-9A-Za-z])(7[0-9A-Za-z]{10})\s?[*‘'’]")
_LETRAS_DE_LA_GUIA = str.maketrans({"e": "8", "E": "8", "B": "8", "O": "0", "o": "0", "D": "0",
                                    "l": "1", "I": "1", "i": "1", "S": "5", "s": "5", "Z": "2"})
#: Con cuántas cifras finales se reconoce la misma guía.
CIFRAS_DE_LA_GUIA = 8


def numero_de_guia(texto: str) -> str | None:
    """Las últimas cifras del número de guía de LECTA de una hoja, o ``None``."""
    for hallado in _NUMERO_DE_GUIA.finditer((texto or "")[:CABEZA_DEL_ENVIO]):
        cifras = (hallado.group(1) or hallado.group(2)).translate(_LETRAS_DE_LA_GUIA)
        if cifras.isdigit():
            return cifras[-CIFRAS_DE_LA_GUIA:]
    return None


#: La fecha y la hora en que LECTA admitió el envío, que imprime igual en la
#: etiqueta de la carta y en su guía de entrega: «20220117» y «12:15:17». En la
#: guía de hoja entera el número va con las cifras separadas -- «* 7 8 7 3 3 7 6
#: 5 6 5 2 *» -- y la OCR no lo deja leer; la fecha y la hora sí (UPD2326502).
_FECHA_DEL_ENVIO = re.compile(r"(?<!\d)20[12]\d(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?!\d)")
#: Sin los segundos: la OCR deja «11:40:48» donde la etiqueta dice «11:40:49».
_HORA_DEL_ENVIO = re.compile(r"(?<!\d)([01]\d|2[0-3]):([0-5]\d):[0-5]\d(?!\d)")
#: Hasta cuántas combinaciones de fecha y hora se aceptan: más es una hoja con
#: muchas fechas, no una etiqueta.
COMBINACIONES_DEL_ENVIO = 4


def claves_del_envio(texto: str) -> frozenset[str]:
    """Lo que identifica el envío de LECTA de una hoja: su número de guía y la
    fecha con la hora en que se admitió. La carta y su guía comparten alguna."""
    cabeza = (texto or "")[: CABEZA_DEL_ENVIO * 2]
    claves: set[str] = set()
    if numero := numero_de_guia(texto):
        claves.add(f"guia:{numero}")
    fechas = set(_FECHA_DEL_ENVIO.findall(cabeza))
    horas = {f"{h}:{m}" for h, m in _HORA_DEL_ENVIO.findall(cabeza)}
    if fechas and horas and len(fechas) * len(horas) <= COMBINACIONES_DEL_ENVIO:
        claves |= {f"envio:{fecha} {hora}" for fecha in fechas for hora in horas}
    return frozenset(claves)


# -- el acta de suspensión, corte y reconexión ------------------------------------
#
# Lo dictó el operador: «ese tipo de documentos en específico van separados».
# Cada acta lleva su número impreso -- «No. S-21 927720», «No.S-221222941» -- y
# varias seguidas son varios documentos (UPD2326309: tres actas, tres archivos).

_ACTA_DE_SUSPENSION = re.compile(r"\W?CTA\s+DE\s+SUSPENSI")
_NUMERO_DEL_ACTA = re.compile(r"N\W{0,2}[O0]\W{0,3}\s*S\s*-\s*(\d{2})\s*(\d{6,7})(?!\d)")


def numero_del_acta_de_suspension(texto: str) -> str | None:
    """El número del acta de suspensión de una hoja, «S-21927720», o ``None``."""
    plano = _plano(texto or "")
    if not _ACTA_DE_SUSPENSION.search(plano):
        return None
    hallado = _NUMERO_DEL_ACTA.search(plano)
    return f"S-{hallado.group(1)}{hallado.group(2)}" if hallado else None
