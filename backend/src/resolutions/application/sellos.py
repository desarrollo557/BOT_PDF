"""Leer el sello de radicación de cada hoja y cortar la caja por él.

El sello -- la etiqueta que la empresa pega al radicar un escrito -- dice dónde
empieza cada documento y con qué número (ver ``domain.sello``). Lo dictó el
operador: «cada vez que encuentres un sello nuevo es un nuevo documento». Y
pidió leerlo «perfectamente y más rápido»: haciéndole zoom.

La lectura de la página entera no lo ve: es letra de máquina de dos milímetros.
Se lee en tres pasos, del más barato al más caro:

1. **Ubicar.** La capa de texto del escáner trae cada palabra con su caja, y
   aunque deje el número roto -- «NUMF.nORK3110202139039» -- deja bien dónde
   está: el renglón de «CONTESTAR CITE ESTE NUMERO». Sin OCR.
2. **Zoom.** Se recorta sólo la etiqueta, con su margen, y se lee a 600 ppp con
   el OCR de casa: una imagen chica, que se lee en una fracción de segundo.
3. **Votar.** El número del recorte, el de la capa de texto y los radicados
   bien escritos en la caja: se queda el que cuadra con los demás.

La hoja sin capa de texto -- un escaneo puro -- no se puede ubicar así, y se
lee la franja de la cabecera entera. La hoja que trae capa y en ella no hay
nada de un sello se salta: no lo lleva.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace

from ..domain.anexos_declarados import HOJA_MUDA, clase_de_la_hoja
from ..domain.grouping import GroupingResult, PageGroup
from ..domain.sello import (
    Sello,
    con_los_conocidos,
    leer_sello,
    radicado_aproximado,
    radicado_del_texto,
    radicado_escrito,
    radicado_por_la_cola,
)
from .anexos_declarados import SOPORTES
from .control import NullRunControl, RunControl, hilos, mapear
from .ports import Band, OcrEngine

#: Dónde va el sello cuando no se puede ubicar: la cabecera, de la mitad hacia
#: la derecha.
BANDA_DEL_SELLO = Band(0.35, 0.0, 1.0, 0.25)
#: 400 y no 300: a 300 se pierde la etiqueta de UPD2320047 p8.
DPI_DE_LA_BANDA = 400
#: Y a cuánto se relee, con el OCR de casa, la etiqueta de la hoja que la trae.
DPI_DE_LA_RELECTURA = 400
#: A cuánto viaja la etiqueta al OCR de pago: la resolución del escaneo.
DPI_DEL_PAGO = 300
#: Hasta dónde se busca el sello: va en la mitad de arriba.
ALTURA_DEL_SELLO = 0.45

#: Lo que la capa de texto deja del sello, por roto que esté: el renglón de
#: «AL CONTESTAR CITE ESTE NUMERO RE…» de la etiqueta, o el «RECIBIDO NO IMPLICA
#: ACEPTACIÓN» del sello de tinta.
#: Sólo lo que de verdad es del sello: «CITE», «Asunto» o «Folios» sueltos
#: daban sellos que no estaban (UPD2326399 p2).
_ANCLA = re.compile(
    # «CONTESTAR CITE», no la «contestación de la petición» de un recurso.
    # Pegado también: «ALCONTESTARCITE» (UPD2326323 p1).
    r"CONT[EHIR]\W?STA[RN]\W{0,3}C|N\W?[UV]\W?[MVWI\\]{1,2}\W?[EF]\W?[RN]\W?[O0]\W?[RK]\W?[EFK]?\W?\d"
    # El sello de tinta por su frase, no por una palabra suelta: «le implica
    # otras» está en el cuerpo de un recurso (UPD2326324 p9).
    r"|NO\s+IM[PB]LICA|IM[PB]LICA\s*A?C?EPTACI|RECIBIDO\s+NO|N\W{0,3}\s*D[EF]\s+RADICACI"
    # La primera línea de la etiqueta, que la capa deja pegada por lo chica de
    # su letra: «CaribemardelaCostaS AS ESP» (UPD3102756 pág. 51). Una carta
    # escribe el nombre con sus espacios.
    r"|C[AU]R[IT]?B[OE]?MA[RS]D[EI]LAC[OU]STA",
    re.IGNORECASE,
)
#: Lo que sólo dice un sello, para buscarlo fuera de la cabecera.
_ANCLA_ESTRICTA = re.compile(
    r"CONT[EHIR]\W?STA[RN]\W{1,3}C\W{0,2}[IÍ1L]\W{0,2}T|NO\s+IM[PB]LICA\s*A?C?EPTACI|RECIBIDO\s+NO\s+IM",
    re.IGNORECASE,
)
#: Y los campos de la etiqueta, que sólo valen como ancla a la derecha de la
#: hoja y con su número: «Asunto: 03», no el «Asunto:» de una carta.
_ANCLA_A_LA_DERECHA = re.compile(r"\bASUNTO\s*:\s*0\d\b", re.IGNORECASE)
_TINTA = re.compile(r"IM[PB]LICA|RECIBIDO|[O0]\W?[FPR]\W?[IÍ1L]\W?C\W?[IÍ1L]\W?N\W?A", re.IGNORECASE)
#: El sello de tinta de una oficina por su rótulo, que es lo único que la capa
#: deja entero de su letra diminuta: «OFICINA / BOLIVAR SUR» (UPD3102756:
#: «OPICINA», «oficina'», «3CLIVAR SUR»). Debajo, «SUR»; o al lado, lo que
#: sólo dice el sello. No la «Oficina Magangué Bolívar» de la dirección de una
#: carta, que no lleva ninguna de las dos.
_OFICINA = re.compile(r"[O0]\W?[FPR]\W?[IÍ1L]\W?C\W?[IÍ1L]\W?N\W?A", re.IGNORECASE)
_SUR = re.compile(r"^\W*SUR\b", re.IGNORECASE)
_DEL_SELLO = re.compile(r"RECIB|IM[PB]LICA|ACEPTACI|GRUPO\W?EP", re.IGNORECASE)
#: El recorte del sello de oficina, desde su rótulo: con el RE que se escribe a
#: mano encima (hasta tres renglones de carta) y los campos de debajo.
SOBRE_EL_ROTULO = 0.075
#: Y desde su «RECIBIDO NO IMPLICA ACEPTACIÓN», que va dos renglones más abajo.
SOBRE_EL_SELLO_DE_TINTA = 0.10
BAJO_EL_ROTULO = 0.13
ANCHO_DEL_SELLO = 0.34

#: Las clases de hoja que nunca abren un escrito, y por eso no se miran.
_NO_LLEVAN_SELLO = {*SOPORTES, HOJA_MUDA}


def hojas_que_pueden_llevar_sello(textos: Mapping[int, str]) -> list[int]:
    """Las hojas cuyo sello vale la pena leer: las que no son un soporte ni una foto."""
    # La hoja cuya capa nombra un sello se mira siempre, parezca lo que
    # parezca: la carta escaneada torcida queda «muda» y la que enumera
    # «certificado de tradición» en su cabecera parece un certificado
    # (UPD2326310 p10, UPD2326323 p1), y las dos traen su sello.
    return [
        p
        for p, texto in sorted(textos.items())
        if clase_de_la_hoja(texto or "") not in _NO_LLEVAN_SELLO or _ANCLA_ESTRICTA.search(texto or "")
    ]


def ubicar_sello(source, pagina: int) -> tuple[Band, str] | None:
    """Dónde está el sello en la hoja, por su capa de texto, y lo que la capa leyó.

    ``None`` si la capa no nombra ningún sello, o si la fuente no da cajas.
    """
    trozos_of = getattr(source, "trozos_of", None)
    if trozos_of is None:
        return None
    ancho, alto = source.size_of(pagina)
    todos = [t for t in trozos_of(pagina) if t.texto.strip()]

    def anclas_de(trozos, ancla, con_campos: bool) -> list:
        # El ancla se busca en el renglón entero y no trozo a trozo: hay
        # etiquetas cuya capa trae cada palabra suelta -- «CONTESTAR» y
        # «C'ITF.» en dos trozos (UPD2326302 p4) --, y la frase sólo existe al
        # juntarlas.
        renglones: list[list] = []
        for trozo in sorted(trozos, key=lambda t: (t.y0, t.x0)):
            alto_del_trozo = (trozo.y1 - trozo.y0) or 1
            if renglones and abs(renglones[-1][0].y0 - trozo.y0) < alto_del_trozo * 0.6:
                renglones[-1].append(trozo)
            else:
                renglones.append([trozo])
        halladas = []
        for renglon in renglones:
            texto = " ".join(t.texto.strip() for t in sorted(renglon, key=lambda t: t.x0))
            a_la_derecha = min(t.x0 for t in renglon) > ancho * 0.35
            if ancla.search(texto) or (
                con_campos and _ANCLA_A_LA_DERECHA.search(texto) and a_la_derecha
            ):
                halladas.extend(renglon)
        return halladas

    # Arriba primero, que es donde va casi siempre. Si arriba no hay nada, en
    # toda la hoja, pero sólo con la frase entera del sello -- «de radicación»
    # o «recibido» sueltos están en el cuerpo de cualquier escrito (UPD2326300
    # p3) --: el recurso que se radica con la etiqueta al pie (UPD2326321 p1,
    # UPD2326312 p1) y el sello de tinta de la oficina, que se estampa abajo a
    # la derecha (UPD2326315 p14, UPD2326316 p8).
    trozos = [t for t in todos if t.y0 < alto * ALTURA_DEL_SELLO]
    anclas = anclas_de(trozos, _ANCLA, con_campos=True)
    if not anclas:
        trozos = todos
        anclas = anclas_de(todos, _ANCLA_ESTRICTA, con_campos=False)
    if not anclas:
        return _sello_de_oficina(todos, ancho, alto)
    x0, x1 = min(t.x0 for t in anclas), max(t.x1 for t in anclas)
    y0, y1 = min(t.y0 for t in anclas), max(t.y1 for t in anclas)
    # La etiqueta con su margen: dos renglones encima del de «CONTESTAR» --
    # la empresa y el consecutivo -- y tres debajo -- el asunto, la oficina, el
    # código de barras y la fecha --. El sello de tinta, más arriba: encima de
    # su «RECIBIDO NO IMPLICA» van el rótulo de la oficina y el RE escrito a
    # mano (UPD3102756 págs. 23, 49, 57: el recorte lo dejaba fuera).
    tinta = any(_TINTA.search(t.texto) for t in anclas)
    banda = Band(
        max(0.0, x0 / ancho - 0.10),
        max(0.0, y0 / alto - (SOBRE_EL_SELLO_DE_TINTA if tinta else 0.05)),
        min(1.0, x1 / ancho + 0.08),
        min(1.0, y1 / alto + 0.09),
    )
    cerca = " ".join(
        t.texto
        for t in trozos
        if t.y0 >= y0 - alto * 0.05 and t.y1 <= y1 + alto * 0.09 and t.x1 >= x0 - ancho * 0.10
    )
    return banda, cerca


def _sello_de_oficina(trozos, ancho: float, alto: float) -> tuple[Band, str] | None:
    """El sello de tinta de una oficina por su rótulo, en cualquier parte de la hoja.

    Va casi siempre al pie de la hoja de firmas, y su letra es tan chica que la
    capa la deja rota -- «NoDEFCLICS», «DiR. NCTIFICACIÓS» --; el rótulo
    «OFICINA / BOLIVAR SUR» sí queda. El recorte incluye el RE que se escribe a
    mano encima del sello (UPD3102756 págs. 8, 23, 39, 45, 49, 57).
    """
    for rotulo in (t for t in trozos if _OFICINA.search(t.texto)):
        cerca = [
            t
            for t in trozos
            if -alto * 0.01 <= t.y0 - rotulo.y0 <= alto * 0.06 and abs(t.x0 - rotulo.x0) <= ancho * 0.30
        ]
        debajo = [
            t for t in cerca if 0 < t.y0 - rotulo.y0 <= alto * 0.035 and _SUR.search(t.texto)
        ]
        if not debajo and not any(_DEL_SELLO.search(t.texto) for t in cerca):
            continue
        x0, y0 = rotulo.x0 / ancho, rotulo.y0 / alto
        banda = Band(
            max(0.0, x0 - 0.06),
            max(0.0, y0 - SOBRE_EL_ROTULO),
            min(1.0, x0 + ANCHO_DEL_SELLO),
            min(1.0, y0 + BAJO_EL_ROTULO),
        )
        return banda, " ".join(t.texto for t in cerca)
    return None


#: El renglón del número en la capa: «AL CONTESTAR CITE ESTE NUMERO RE…».
_RENGLON_DEL_NUMERO = re.compile(r"CONTEST|C\W?ITE\W+ESTE|NU\W?[MVW]\w*RO\s*R", re.IGNORECASE)
#: A cuánto se relee ese renglón solo: la letra de la etiqueta es tan chica que
#: a 400 dpi Tesseract junta o parte cifras (UPD2326422 p1, UPD2326391 p4).
DPI_DEL_RENGLON = 600


def renglon_del_numero(source, pagina: int) -> Band | None:
    """El renglón de la etiqueta que trae el radicado, ceñido, o ``None``.

    Arriba primero, como el sello; si arriba no está, en toda la hoja.
    """
    trozos_of = getattr(source, "trozos_of", None)
    if trozos_of is None:
        return None
    ancho, alto = source.size_of(pagina)
    todos = [t for t in trozos_of(pagina) if t.texto.strip()]
    anclas = [t for t in todos if t.y0 < alto * ALTURA_DEL_SELLO and _RENGLON_DEL_NUMERO.search(t.texto)]
    anclas = anclas or [t for t in todos if _RENGLON_DEL_NUMERO.search(t.texto)]
    if not anclas:
        return None
    y0, y1 = min(t.y0 for t in anclas), max(t.y1 for t in anclas)
    if y1 - y0 > alto * 0.04:
        # Anclas en renglones lejanos: no es una etiqueta sino un escrito que
        # nombra el número; se queda la de más arriba.
        primera = min(anclas, key=lambda t: t.y0)
        anclas = [t for t in anclas if abs(t.y0 - primera.y0) < (primera.y1 - primera.y0)]
        y0, y1 = min(t.y0 for t in anclas), max(t.y1 for t in anclas)
    renglon = [t for t in todos if t.y0 < y1 and t.y1 > y0]
    x0 = min(t.x0 for t in anclas)
    x1 = max(max(t.x1 for t in renglon), x0 + ancho * 0.42)
    margen = (y1 - y0) * 0.3
    return Band(
        max(0.0, (x0 - 5) / ancho),
        max(0.0, (y0 - margen) / alto),
        min(1.0, (x1 + 40) / ancho),
        min(1.0, (y1 + margen) / alto),
    )


def releer_el_renglon(source, pagina: int, lectores: Sequence[OcrEngine]) -> str | None:
    """El radicado del renglón del número, si todas las lecturas lo dan igual.

    Último intento sin pago para la etiqueta que ninguna lectura dejó entera:
    el renglón solo, a ``DPI_DEL_RENGLON``, leído de varias maneras -- un
    renglón, un bloque --. Sólo se acepta si coinciden: una lectura sola de
    letra tan chica todavía puede cambiar una cifra (UPD2326336 p1 da «…821»
    o «…823» según cómo se lea, y se deja ilegible).
    """
    if len(lectores) < 2:
        return None
    banda = renglon_del_numero(source, pagina)
    if banda is None:
        return None
    imagen = source.render(pagina, banda, DPI_DEL_RENGLON)
    leidos = set()
    for lector in lectores:
        try:
            leidos.add(radicado_del_texto(lector.read(imagen).text))
        except Exception:  # noqa: BLE001 - una lectura fallida no da número
            return None
    return leidos.pop() if len(leidos) == 1 else None


def _votar(lecturas: list[str], conocidos: set[str]) -> str | None:
    """El radicado en que cuadran las lecturas del sello y los de la caja."""
    candidatos = [r for r in (radicado_del_texto(t) for t in lecturas) if r]
    if not candidatos:
        return None
    corregidos = [con_los_conocidos(r, conocidos) for r in candidatos]
    for radicado in corregidos:
        if radicado in conocidos:
            return radicado
    # Sin uno conocido: el que más lecturas dan; a igualdad, el del zoom, que
    # va primero.
    return max(corregidos, key=lambda r: (corregidos.count(r), -corregidos.index(r)))


def leer_sellos(
    source,
    ocr: OcrEngine,
    paginas: list[int],
    *,
    de_pago: OcrEngine | None = None,
    conocidos: set[str] | frozenset[str] = frozenset(),
    workers: int = 4,
    control: RunControl | None = None,
    avance: Callable[[int, int], None] | None = None,
    lectores_del_renglon: Sequence[OcrEngine] = (),
    avance_del_numero: Callable[[int, int], None] | None = None,
) -> dict[int, Sello]:
    """El sello de cada hoja que lo trae, en dos pasos.

    1. **Detectar**, con el OCR de casa: la cabecera de cada hoja candidata, en
       tandas que el binario lee en una sola llamada -- arrancarlo es lo que más
       cuesta --, y lo que la capa de texto ya dice del sello. Sólo decide si
       hay sello y de qué clase.
    2. **Leer el número.** Con ``de_pago`` -- el OCR de pago, si el operador
       eligió «OCR + IA» -- sólo la etiqueta de cada hoja con sello, en
       paralelo: medido sobre siete etiquetas reales, acierta las siete en
       radicado, fecha y folios, donde el de casa erraba una cifra en cinco.
       Es una página facturada por sello, no por hoja. Sin él, el número se
       vota entre la lectura de casa, la capa de texto y los radicados bien
       escritos de la caja.

    ``conocidos`` son esos radicados bien escritos: la cifra que el de casa
    leyó mal se corrige contra ellos.

    ``avance_del_numero`` cuenta las etiquetas leídas con el de pago, una a
    una. Sin él, catorce sellos de Magangué fueron casi nueve minutos sin una
    noticia: la tarjeta decía «Sin novedades» y el vigilante podía darlo por
    atascado (2026-10-28).
    """
    control = control or NullRunControl()
    conocidos = set(conocidos)
    leer_varias = getattr(ocr, "read_varias", None)

    def leer_tanda(imagenes: list[bytes]) -> list[str]:
        try:
            if leer_varias is not None:
                return [r.text for r in leer_varias(imagenes)]
            return [ocr.read(imagen).text for imagen in imagenes]
        except Exception:  # noqa: BLE001 - una tanda ilegible no para la caja
            return ["" for _ in imagenes]

    # 1. Detectar.
    ubicados = {p: ubicar_sello(source, p) for p in paginas}
    detectados: dict[int, tuple[Sello, str, str, Band]] = {}
    tanda = max(1, workers) * 4
    hechas = 0
    for inicio in range(0, len(paginas), tanda):
        control.check()
        lote = paginas[inicio : inicio + tanda]
        # La esquina de arriba a la derecha, que es donde va la etiqueta, y
        # además donde la capa dice que está el sello, si lo dice: cada
        # recorte lee bien lo que el otro lee mal, y el número se vota entre
        # los dos.
        imagenes = [source.render(p, BANDA_DEL_SELLO, DPI_DE_LA_BANDA) for p in lote]
        con_ubicacion = [p for p in lote if ubicados.get(p)]
        de_la_ubicacion = dict(
            zip(
                con_ubicacion,
                leer_tanda(
                    [source.render(p, ubicados[p][0], DPI_DE_LA_BANDA) for p in con_ubicacion]
                ),
                strict=True,
            )
        )
        for pagina, texto in zip(lote, leer_tanda(imagenes), strict=True):
            if de_la_ubicacion.get(pagina):
                texto = f"{texto}\n{de_la_ubicacion[pagina]}"
            ubicado = ubicados.get(pagina)
            de_la_capa = ubicado[1] if ubicado else ""
            sello = leer_sello(texto) or (leer_sello(de_la_capa) if de_la_capa else None)
            if sello is None and de_la_capa:
                # La capa nombró el sello aunque la lectura no lo deje ver: está.
                sello = Sello("tinta" if _TINTA.search(de_la_capa) else "impreso")
            if sello is not None:
                banda = ubicado[0] if ubicado else BANDA_DEL_SELLO
                detectados[pagina] = (sello, texto, de_la_capa, banda)
        hechas += len(lote)
        if avance:
            avance(hechas, len(paginas))

    # 2. Leer el número.
    relecturas: dict[int, str] = {}
    if de_pago is None and DPI_DE_LA_RELECTURA > DPI_DE_LA_BANDA:
        # Sin el de pago, el de casa relee más fino sólo las etiquetas.
        impresas = [p for p, (sello, *_) in detectados.items() if sello.clase == "impreso"]
        for inicio in range(0, len(impresas), tanda):
            control.check()
            lote = impresas[inicio : inicio + tanda]
            imagenes = [source.render(p, detectados[p][3], DPI_DE_LA_RELECTURA) for p in lote]
            relecturas.update(zip(lote, leer_tanda(imagenes), strict=True))
    pagados: dict[int, str] = {}
    if de_pago is not None and detectados:
        import threading

        leidas = [0]
        cerrojo = threading.Lock()

        def leer_de_pago(imagen: bytes) -> str:
            try:
                return de_pago.read(imagen).text
            except Exception:  # noqa: BLE001 - se queda la lectura de casa
                return ""
            finally:
                if avance_del_numero:
                    with cerrojo:
                        leidas[0] += 1
                        avance_del_numero(leidas[0], len(detectados))

        orden = list(detectados)
        # Donde está el sello, no la esquina de arriba: el de tinta va al pie
        # de la hoja de firmas, y leyendo arriba la IA nunca lo veía
        # (UPD3102756: de trece sellos, sólo leía el de la pág. 11).
        imagenes = [source.render(p, detectados[p][3], DPI_DEL_PAGO, "jpeg") for p in orden]
        with hilos(max(1, workers)) as pool:
            for pagina, texto in zip(orden, mapear(pool, leer_de_pago, imagenes, control), strict=True):
                pagados[pagina] = texto

    sellos: dict[int, Sello] = {}
    for pagina, (sello, texto, de_la_capa, _) in detectados.items():
        del_pago = leer_sello(pagados[pagina]) if pagados.get(pagina) else None
        if del_pago is not None and del_pago.radicado:
            # La lectura de pago manda: no se corrige contra los conocidos,
            # que podrían ser el radicado vecino de otro trámite.
            sellos[pagina] = Sello(
                sello.clase if sello.clase == "tinta" else del_pago.clase,
                del_pago.radicado,
                del_pago.fecha or sello.fecha,
                del_pago.folios or sello.folios,
            )
            continue
        radicado = None
        if sello.clase == "impreso":
            radicado = _votar([relecturas.get(pagina, ""), texto, de_la_capa], conocidos)
        if radicado is None and pagados.get(pagina):
            # El sello de tinta lleva el número a mano: el de casa no lo lee;
            # el de pago sí, con lo que la letra a mano le hace a cada cifra
            # -- «RE23102023214Y3», «RE 23/0 2024 003 48» -- y el año de la
            # «FECHA DE RECIBIDO» del propio sello para validarlo.
            radicado = radicado_del_texto(pagados[pagina]) or radicado_escrito(pagados[pagina])
        de_la_capa_leido = leer_sello(de_la_capa) if de_la_capa else None
        releido = leer_sello(relecturas[pagina]) if relecturas.get(pagina) else None
        fecha = (
            sello.fecha
            or (releido.fecha if releido else None)
            or (del_pago.fecha if del_pago else None)
            or (de_la_capa_leido.fecha if de_la_capa_leido else None)
        )
        radicado = radicado or sello.radicado
        if radicado is None and sello.clase == "impreso":
            # Ninguna lectura dejó las trece cifras limpias: la que las dejó con
            # letras -- «RE31l0202212114» -- se acepta si su año es el de la
            # fecha del sello, y se corrige contra los radicados de la caja.
            for lectura in (relecturas.get(pagina, ""), texto, de_la_capa):
                aproximado = radicado_aproximado(lectura, fecha)
                if aproximado:
                    radicado = con_los_conocidos(aproximado, conocidos)
                    break
            if radicado is None:
                for lectura in (relecturas.get(pagina, ""), texto, de_la_capa):
                    if radicado := radicado_por_la_cola(lectura, conocidos):
                        break
            if radicado is None and lectores_del_renglon:
                releido_el_renglon = releer_el_renglon(source, pagina, lectores_del_renglon)
                # Y su año tiene que ser el de la fecha del sello, si se leyó.
                if releido_el_renglon and (fecha is None or releido_el_renglon[6:10] == str(fecha.year)):
                    radicado = con_los_conocidos(releido_el_renglon, conocidos)
        sellos[pagina] = Sello(
            sello.clase,
            radicado,
            fecha,
            sello.folios
            or (releido.folios if releido else None)
            or (del_pago.folios if del_pago else None)
            or (de_la_capa_leido.folios if de_la_capa_leido else None),
        )
    return sellos


def cortar_por_sellos(
    grupos: GroupingResult,
    sellos: Mapping[int, Sello],
    anexos: dict[str, list[int]] | None = None,
    *,
    etiquetas: set[int] | frozenset[int] = frozenset(),
    guias: set[int] | frozenset[int] = frozenset(),
    numeros_de_guia: Mapping[int, str | None] | None = None,
    envios: Mapping[int, frozenset[str]] | None = None,
) -> tuple[GroupingResult, dict[str, list[int]], list[int]]:
    """Abre un documento en cada hoja con sello o con etiqueta de envío.

    Tres señales, las tres dictadas por el operador:

    * **El sello de radicación** abre un documento: el escrito que la empresa
      recibió.
    * **La etiqueta de envío de LECTA** pegada en una carta de la empresa abre
      un documento: la citación o la respuesta que se le mandó al cliente.
    * **La guía de entrega de LECTA** de hoja entera que va justo antes de esa
      carta es de ella: el documento empieza en la guía y no en la carta. En
      UPD2321099 la guía de la hoja 9 va con la citación de la 10, no con la
      petición de la 1 a la 8.

    Devuelve los documentos, sus anexos con el código nuevo y las hojas en que
    se abrió un documento que el corte no había abierto.
    """
    anexos = anexos or {}
    paginas = [p for g in grupos.groups for p in g.page_numbers]
    originales = {g.page_numbers[0]: g for g in grupos.groups}
    inicios = set(originales) | set(sellos) | set(etiquetas)
    # Lo que identifica el envío de cada hoja: el número de guía y la fecha
    # con la hora de admisión (``claves_del_envio``).
    claves: dict[int, frozenset[str]] = dict(envios or {})
    for pagina, numero in (numeros_de_guia or {}).items():
        if numero:
            claves[pagina] = claves.get(pagina, frozenset()) | {f"guia:{numero}"}
    puesto = {p: i for i, p in enumerate(paginas)}

    def mismo_envio(una: int, otra: int) -> bool:
        return bool(claves.get(una, frozenset()) & claves.get(otra, frozenset()))

    def es_de_la_anterior(guia: int) -> bool:
        """Si la guía es del envío de la carta con etiqueta que tiene detrás.

        La guía es de la carta cuyo envío lleva -- número de guía o fecha y
        hora de admisión --, no de la que tenga más cerca: el envío manda sobre
        la posición. Una guía entre dos cartas con etiqueta (UPD2326321: carta
        en la 2, guía en la 3, carta en la 4) es de la de su número; y la de una
        carta de varias hojas va detrás de la última, con las hojas de la carta
        de por medio (UPD2326502: carta de la 3 a la 6, guía en la 7). Entre la
        carta y su guía no puede haber otro sello ni otra etiqueta: serían otro
        documento.
        """
        if guia not in puesto:
            return False
        delante = paginas[: puesto[guia]]
        carta = next((p for p in reversed(delante) if p in etiquetas), None)
        if carta is None or any(p in sellos for p in delante[puesto[carta] + 1 :]):
            return False
        return mismo_envio(guia, carta) and not (guia + 1 in etiquetas and mismo_envio(guia, guia + 1))

    for etiqueta in etiquetas:
        anterior = etiqueta - 1
        if anterior in guias and anterior in paginas and not es_de_la_anterior(anterior):
            # La guía abre el documento de su carta, y la carta deja de abrirlo.
            inicios.add(anterior)
            if etiqueta not in sellos:
                inicios.discard(etiqueta)
    for guia in guias:
        # Y la guía que va después de su carta -- UPD2320047: citación en la 5,
        # guía en la 6; UPD2326502: carta de la 3 a la 6, guía en la 7 -- es
        # de esa carta, salvo que abra la siguiente. Una guía nunca va sola.
        if (
            guia not in sellos
            and paginas
            and guia != paginas[0]
            and (guia + 1 not in etiquetas or es_de_la_anterior(guia))
        ):
            inicios.discard(guia)
    tramos: list[list[int]] = []
    for pagina in paginas:
        if not tramos or pagina in inicios:
            tramos.append([])
        tramos[-1].append(pagina)
    if [t[0] for t in tramos] == [g.page_numbers[0] for g in grupos.groups] and len(tramos) == len(
        grupos.groups
    ):
        return grupos, dict(anexos), []

    cortes = [t[0] for t in tramos if t[0] not in originales]
    de_la_hoja = {p: g for g in grupos.groups for p in g.page_numbers}
    numerados = all(g.code.value.isdigit() for g in grupos.groups)
    ancho = len(grupos.groups[0].code.value) if grupos.groups else 2
    salida: list[PageGroup] = []
    nuevos_anexos: dict[str, list[int]] = {}
    for puesto, tramo in enumerate(tramos, start=1):
        original = originales.get(tramo[0])
        mismo = original is not None and original.page_numbers == tramo
        if numerados:
            codigo = type(grupos.groups[0].code)(value=f"{puesto:0{ancho}d}", raw=f"{puesto:0{ancho}d}")
        else:
            base = de_la_hoja[tramo[0]].code
            codigo = (
                base
                if original is not None
                else type(base)(value=f"{base.value}-{tramo[0]}", raw=f"{base.raw}-{tramo[0]}")
            )
        salida.append(
            PageGroup(
                code=codigo,
                page_numbers=tramo,
                title=original.title if original is not None else None,
                kind=original.kind if mismo else None,
                fecha=original.fecha if mismo else None,
            )
        )
        propios = sorted(p for p in tramo if p in set(anexos.get(de_la_hoja[p].code.value, [])))
        if propios:
            nuevos_anexos[codigo.value] = propios
    resultado = GroupingResult(
        groups=salida, quarantine=list(grupos.quarantine), repairs=list(grupos.repairs)
    )
    return resultado, nuevos_anexos, cortes


def retener_los_folios(
    grupos: GroupingResult,
    sellos: Mapping[int, Sello],
    abren: set[int] | frozenset[int],
    anexos: dict[str, list[int]] | None = None,
) -> tuple[GroupingResult, dict[str, list[int]], list[int]]:
    """Lo que cae dentro de los «Folios: N» de un sello es de ese escrito.

    El sello declara cuántas hojas recibió la oficina: «Folios: 19». Todo
    documento que el corte abrió dentro de esas hojas -- la segunda página del
    recurso, el contrato, el certificado, la copia de una respuesta -- es parte
    del escrito, salvo que traiga su propio sello o la etiqueta de LECTA
    (``abren``). Folios cuenta hojas físicas: una factura a dos caras es un
    folio y dos páginas, así que N es un mínimo, nunca un tope donde cortar.

    Devuelve los grupos, los anexos y las hojas que dejaron de abrir documento.
    """
    anexos = {codigo: list(paginas) for codigo, paginas in (anexos or {}).items()}
    salida: list[PageGroup] = []
    hasta = 0  # última página que cubre el sello del documento abierto
    unidas: list[int] = []
    for grupo in grupos.groups:
        primera = grupo.page_numbers[0]
        if salida and primera <= hasta and primera not in abren:
            anterior = salida[-1]
            salida[-1] = PageGroup(
                code=anterior.code,
                page_numbers=anterior.page_numbers + list(grupo.page_numbers),
                title=anterior.title,
                kind=anterior.kind,
                fecha=anterior.fecha,
            )
            # Sus anexos pasan con él; sus hojas no se vuelven anexos: la
            # segunda página de un recurso es el recurso.
            if suyos := anexos.pop(grupo.code.value, []):
                anexos.setdefault(anterior.code.value, []).extend(suyos)
            unidas.append(primera)
            continue
        salida.append(grupo)
        sello = sellos.get(primera)
        hasta = primera + sello.folios - 1 if sello and sello.folios and sello.folios > 1 else 0
    if not unidas:
        return grupos, anexos, []
    return replace(grupos, groups=salida), anexos, unidas


def la_ultima_hoja_sola(
    grupos: GroupingResult,
    con_sello: set[int] | frozenset[int],
    anexos: dict[str, list[int]] | None = None,
    guias: set[int] | frozenset[int] = frozenset(),
) -> tuple[GroupingResult, dict[str, list[int]], int | None]:
    """La última hoja de la caja, si trae sello, en un documento solo.

    Lo dictó el operador: «si encuentras una página que tiene su sello, ya sea
    de LECTA o el otro, y la siguiente no existe -- la última es la del sello --
    y la anterior ya pertenece a un grupo de páginas, agrupa la página con el
    sello sola». Corre al final, después del trámite: es la regla que manda
    sobre las demás para esa hoja, aunque su RE sea el de un trámite anterior.

    La guía de entrega que va justo antes de esa hoja -- la de LECTA, de la
    carta que la sigue -- va con ella: el documento solo es la carta con su
    guía (UPD2321099: guía en la 9, citación en la 10).

    Devuelve los documentos, sus anexos y la hoja que se separó, si alguna.
    """
    anexos = dict(anexos or {})
    paginas = [p for g in grupos.groups for p in g.page_numbers]
    if not paginas:
        return grupos, anexos, None
    ultima = max(paginas)
    if ultima not in con_sello:
        return grupos, anexos, None
    suyo = next(g for g in grupos.groups if ultima in g.page_numbers)
    sola = [ultima]
    while sola[0] - 1 in guias and sola[0] - 1 in suyo.page_numbers:
        sola.insert(0, sola[0] - 1)
    if suyo.page_numbers == sola:
        return grupos, anexos, None
    salida: list[PageGroup] = []
    for grupo in grupos.groups:
        if grupo is not suyo:
            salida.append(grupo)
            continue
        resto = [p for p in grupo.page_numbers if p not in sola]
        salida.append(
            PageGroup(code=grupo.code, page_numbers=resto, title=grupo.title, kind=grupo.kind, fecha=grupo.fecha)
        )
        propios = [p for p in anexos.get(grupo.code.value, []) if p not in sola]
        if propios:
            anexos[grupo.code.value] = propios
        else:
            anexos.pop(grupo.code.value, None)
    # Va al final: es la última hoja. Su código sigue la numeración de la caja.
    puesto = len(salida) + 1
    valor = (
        f"{puesto:0{len(suyo.code.value)}d}"
        if suyo.code.value.isdigit()
        else re.sub(r"^\d+", f"{puesto:02d}", suyo.code.value)
    )
    if valor == suyo.code.value:
        valor = f"{valor}-{ultima}"
    salida.append(PageGroup(code=type(suyo.code)(value=valor, raw=suyo.code.raw), page_numbers=sola))
    return (
        GroupingResult(groups=salida, quarantine=list(grupos.quarantine), repairs=list(grupos.repairs)),
        anexos,
        ultima,
    )


def dividir_por_tramite(
    documentos: GroupingResult,
    propios: Mapping[int, str | None],
    del_tramite: Mapping[int, str],
    abren: set[int] | frozenset[int],
    anexos: dict[str, list[int]] | None = None,
    sin_re_ajeno: Callable[[list[int]], bool] | None = None,
) -> tuple[GroupingResult, dict[str, list[int]]]:
    """Los archivos de una caja entregada por trámite: manda el sello.

    Lo decidió el operador ante UPD2320047, que por RE salía en dos archivos y
    son cuatro documentos: «cuando varias hojas tienen el mismo RE pero aparece
    un sello nuevo o una carta con etiqueta de LECTA, manda el sello». Así:

    1. Se parte de los documentos ya cortados -- continuidad, sello, etiqueta
       de envío, lista de anexos, cédula y factura con la anterior --.
    2. **Un RE nuevo corta**, aunque sea a mitad de un documento: dos
       constancias que el corte unió y son de dos radicados son dos.
    3. **Un documento se une al anterior sólo si trae su propio RE y es el
       mismo**, y no empieza con sello ni etiqueta: la notificación o la
       respuesta de la empresa que citan el radicado del escrito.
    4. **Lo que no trae RE propio queda aparte**: el acta de suspensión.

    ``propios`` es el RE que trae cada hoja -- el de su sello o el que cita su
    texto --; ``del_tramite``, el trámite que el recorrido por RE y fecha le dio
    a cada hoja, que es con el que se nombra el documento que no trae RE
    propio; ``abren``, las hojas que abren un documento sí o sí.
    """
    anexos = anexos or {}
    # 2. Un RE nuevo corta.
    partidos: list[list[int]] = []
    for documento in documentos.groups:
        actual: str | None = None
        for pagina in documento.page_numbers:
            propio = propios.get(pagina)
            if not partidos or pagina == documento.page_numbers[0] or (
                propio and actual and propio != actual
            ):
                partidos.append([])
                actual = None
            partidos[-1].append(pagina)
            actual = actual or propio

    def re_propio(paginas: list[int]) -> str | None:
        return next((propios[p] for p in paginas if propios.get(p)), None)

    # 3 y 4. Se une al anterior sólo lo que trae el mismo RE y no abre nada.
    unidos: list[list[int]] = []
    for paginas in partidos:
        if (
            unidos
            and paginas[0] not in abren
            and (propio := re_propio(paginas))
            and propio == (re_propio(unidos[-1]) or del_tramite.get(unidos[-1][0]))
        ):
            unidos[-1].extend(paginas)
        else:
            unidos.append(list(paginas))

    todos_los_anexos = {p for paginas in anexos.values() for p in paginas}
    salida: list[PageGroup] = []
    nuevos_anexos: dict[str, list[int]] = {}
    for puesto, paginas in enumerate(unidos, start=1):
        # Su propio RE; si no trae, el de su trámite, pero sólo si es un
        # escrito del trámite -- la petición de UPD2321099 p1-8, a la que
        # responde la citación con ese RE --. El formato que no trae ninguno
        # -- el acta, la autorización de habeas data -- no se nombra con el
        # de otro (lo dictó el operador; UPD2326311 p1, UPD2326314 p3), y el
        # trámite sin radicado («SIN-RADICADO…») no nombra a nadie.
        del_suyo = del_tramite.get(paginas[0]) or ""
        prestado = (
            del_suyo
            if del_suyo.startswith(("RE", "P"))
            and not (sin_re_ajeno is not None and sin_re_ajeno(paginas))
            else ""
        )
        clave = re_propio(paginas) or prestado
        valor = f"{puesto:02d} {clave}".strip()
        salida.append(
            PageGroup(
                code=type(documentos.groups[0].code)(value=valor, raw=clave or valor),
                page_numbers=paginas,
                # El tipo lo pone después lo que dice ser su primera hoja.
                kind=None,
            )
        )
        suyos = [p for p in paginas if p in todos_los_anexos]
        if suyos:
            nuevos_anexos[valor] = suyos
    return (
        GroupingResult(
            groups=salida, quarantine=list(documentos.quarantine), repairs=list(documentos.repairs)
        ),
        nuevos_anexos,
    )


def unir_lo_que_no_abre(
    grupos: GroupingResult,
    no_abren: set[int] | frozenset[int],
    anexos: dict[str, list[int]] | None = None,
) -> tuple[GroupingResult, dict[str, list[int]], list[int]]:
    """El documento que no trae nada que lo abra va con el anterior.

    Ante la duda se une (lo decidió el operador): una hoja sin sello, sin
    etiqueta de LECTA, sin un título que diga qué es y sin un radicado propio
    no es evidencia de que empiece otro documento -- la consulta de
    antecedentes detrás de un derecho de petición (UPD2326299 p5), la cédula
    que abría un grupo detrás de su notificación (UPD2326323 p11) --.
    ``no_abren`` son las primeras hojas de esos documentos.
    """
    from .anexos_declarados import _renumerar

    anexos = {codigo: list(paginas) for codigo, paginas in (anexos or {}).items()}
    salida: list[PageGroup] = []
    unidas: list[int] = []
    for grupo in grupos.groups:
        if salida and grupo.page_numbers[0] in no_abren:
            anterior = salida[-1]
            salida[-1] = replace(anterior, page_numbers=anterior.page_numbers + list(grupo.page_numbers))
            if suyos := anexos.pop(grupo.code.value, []):
                anexos.setdefault(anterior.code.value, []).extend(suyos)
            unidas.append(grupo.page_numbers[0])
            continue
        salida.append(grupo)
    if not unidas:
        return grupos, anexos, []
    salida, anexos = _renumerar(salida, anexos)
    return replace(grupos, groups=salida), anexos, unidas


def ajustar_por_cartas(
    grupos: GroupingResult,
    anexos: dict[str, list[int]] | None = None,
    *,
    abren: set[int] | frozenset[int],
    siguen: set[int] | frozenset[int] = frozenset(),
    pruebas: set[int] | frozenset[int] = frozenset(),
) -> tuple[GroupingResult, dict[str, list[int]], list[int], list[int], list[int]]:
    """Cada carta abre su trámite; lo que la continúa o la prueba va con ella.

    Lo pidió el operador ante UPD3102756: «cada trámite va solo, con sus
    respectivos anexos». Tres señales del texto (:mod:`~resolutions.domain.carta`):

    * ``abren``: la primera hoja de una carta -- fecha, «Señores…», «ASUNTO:»
      --. Abre documento aunque no traiga sello y la continuidad la hubiera
      pegado al trámite anterior.
    * ``siguen``: la hoja que empieza a mitad de la carta anterior -- «Peticiones.»,
      la frase en minúscula -- va con ella, aunque traiga el sello al pie.
    * ``pruebas``: la copia de una carta o de un sello ya radicados en la caja, y
      la constancia que la carta anterior cita, van como anexo del documento que
      las trae.

    Devuelve los documentos, sus anexos, las hojas en que se abrió uno, las
    que dejaron de abrirlo y todas las hojas que entraron como prueba: la copia
    entera, no sólo su primera hoja, para que ninguna dé su RE al documento que
    la trae (UPD3102756 pág. 32, la copia del sello de la petición del 14-nov).
    """
    anexos = {codigo: list(paginas) for codigo, paginas in (anexos or {}).items()}
    # Primero se parte en cada carta que abre.
    tramos: list[tuple[PageGroup, list[int]]] = []
    abiertas: list[int] = []
    for grupo in grupos.groups:
        actual: list[int] = []
        for pagina in grupo.page_numbers:
            if actual and pagina in abren:
                tramos.append((grupo, actual))
                abiertas.append(pagina)
                actual = []
            actual.append(pagina)
        tramos.append((grupo, actual))
    # Y lo que sigue la carta o la prueba se une al documento anterior.
    piezas: list[tuple[PageGroup, list[int], list[int]]] = []
    unidas: list[int] = []
    de_prueba: list[int] = []
    for grupo, paginas in tramos:
        suyos = [p for p in paginas if p in set(anexos.get(grupo.code.value, []))]
        primera = paginas[0]
        if piezas and primera not in abren and (primera in siguen or primera in pruebas):
            anterior, de_antes, sus_anexos = piezas[-1]
            # La prueba es anexo del documento que la trae; la hoja que sigue
            # la carta es la carta.
            piezas[-1] = (anterior, de_antes + paginas, sus_anexos + (paginas if primera in pruebas else suyos))
            unidas.append(primera)
            if primera in pruebas:
                de_prueba.extend(paginas)
            continue
        piezas.append((grupo, list(paginas), suyos))
    if not abiertas and not unidas:
        return grupos, anexos, [], [], []
    # Se numeran otra vez por su puesto, como al separar las actas.
    numerados = all(g.code.value.isdigit() for g in grupos.groups)
    ancho = max(2, len(grupos.groups[0].code.value)) if grupos.groups else 2
    salida: list[PageGroup] = []
    nuevos: dict[str, list[int]] = {}
    for puesto, (grupo, paginas, suyos) in enumerate(piezas, start=1):
        entero = paginas == list(grupo.page_numbers)
        pieza = grupo if entero else replace(grupo, page_numbers=paginas, kind=None, fecha=None)
        if numerados:
            valor = f"{puesto:0{ancho}d}"
            pieza = replace(pieza, code=type(grupo.code)(value=valor, raw=valor))
        elif not entero and paginas[0] != grupo.page_numbers[0]:
            pieza = replace(
                pieza,
                code=type(grupo.code)(value=f"{grupo.code.value}-{paginas[0]}", raw=f"{grupo.code.raw}-{paginas[0]}"),
            )
        salida.append(pieza)
        if suyos:
            nuevos[pieza.code.value] = sorted(set(suyos))
    return replace(grupos, groups=salida), nuevos, abiertas, unidas, de_prueba


def separar_las_actas(
    grupos: GroupingResult,
    numeros: Mapping[int, str | None],
    anexos: dict[str, list[int]] | None = None,
) -> tuple[GroupingResult, dict[str, list[int]], list[int]]:
    """Cada acta de suspensión, en su documento.

    ``numeros`` es el número de acta de cada hoja que lo trae. Una hoja con un
    número distinto del acta que venía abierta abre otra; las hojas sin número
    -- el reverso -- siguen con la suya. Devuelve los grupos, los anexos y las
    hojas en que se abrió un acta.
    """
    anexos = anexos or {}
    piezas: list[tuple[PageGroup, list[int]]] = []
    abiertas: list[int] = []
    for grupo in grupos.groups:
        suyos = set(anexos.get(grupo.code.value, []))
        tramos: list[list[int]] = []
        actual: str | None = None
        for pagina in grupo.page_numbers:
            numero = numeros.get(pagina)
            if not tramos or (numero and actual and numero != actual):
                if tramos:
                    abiertas.append(pagina)
                tramos.append([])
            if numero:
                actual = numero
            tramos[-1].append(pagina)
        for tramo in tramos:
            pieza = grupo if len(tramos) == 1 else replace(grupo, page_numbers=tramo)
            piezas.append((pieza, [p for p in tramo if p in suyos]))
    if not abiertas:
        return grupos, dict(anexos), []
    # Se numeran otra vez por su puesto: 01, 02, 03…
    ancho = max(2, len(grupos.groups[0].code.value)) if grupos.groups else 2
    salida: list[PageGroup] = []
    nuevos: dict[str, list[int]] = {}
    for puesto, (pieza, suyos) in enumerate(piezas, start=1):
        valor = f"{puesto:0{ancho}d}"
        salida.append(replace(pieza, code=type(pieza.code)(value=valor, raw=valor)))
        if suyos:
            nuevos[valor] = suyos
    return replace(grupos, groups=salida), nuevos, abiertas


def separar_los_formularios(
    grupos: GroupingResult,
    formularios: Mapping[int, tuple[str, str | None]],
    anexos: dict[str, list[int]] | None = None,
    *,
    intocables: set[int] | frozenset[int] = frozenset(),
    solos: frozenset[str] = frozenset(),
    anexo_evidente: Callable[[int], bool] | None = None,
) -> tuple[GroupingResult, dict[str, list[int]], list[int]]:
    """Cada formulario de la oficina, en su documento.

    Lo dictó el operador el 2026-10-26 sobre las cajas de Magangué: la
    constancia de reclamación va sola salvo un anexo evidente, la notificación
    personal también, y la carta de respuesta que la sigue es otro documento.
    La continuidad las pegaba: cuatro constancias seguidas salían en un
    archivo, y la notificación con su respuesta, la foto del medidor y la
    cédula en otro.

    ``formularios`` dice, de cada hoja que empieza uno, qué es y su radicado:
    ``("CONSTANCIA DE RECLAMACION", "RE2310202205541")``. Una hoja así abre
    documento, salvo que siga al mismo formulario con el mismo radicado -- las
    dos hojas de una misma constancia -- o sea otra pieza del acuerdo de pago,
    que después se junta entero. Lo que no es formulario -- la cédula, la
    factura, la foto, la hoja que continúa la carta -- sigue con el que viene
    abierto: es su anexo.

    ``intocables`` son las hojas que no abren aunque lo parezcan: las que caen
    dentro de los folios de un sello o se aportaron como prueba de un escrito,
    que son de ese escrito.

    Y detrás de los formularios que van ``solos`` -- la constancia, la
    notificación personal -- sólo sigue lo que ``anexo_evidente`` reconoce:
    la cédula, la factura, la foto. Una hoja con texto propio que no es nada
    de eso es otro documento (1000224: la carta de la hoja 2 «es totalmente
    diferente a la primera», 2026-10-26).
    """
    from ..domain.asunto_del_documento import ACUERDO_DE_PAGO

    anexos = anexos or {}
    piezas: list[tuple[PageGroup, list[int]]] = []
    abiertas: list[int] = []
    for grupo in grupos.groups:
        suyos = set(anexos.get(grupo.code.value, []))
        tramos: list[list[int]] = []
        actual: tuple[str, str | None] | None = None
        for pagina in grupo.page_numbers:
            clave = None if pagina in intocables else formularios.get(pagina)
            continua = clave is not None and clave == actual and (clave[1] is not None or clave[0] == ACUERDO_DE_PAGO)
            otro_documento = (
                clave is None
                and actual is not None
                and actual[0] in solos
                and pagina not in intocables
                and anexo_evidente is not None
                and not anexo_evidente(pagina)
            )
            if not tramos or (clave is not None and not continua) or otro_documento:
                if tramos:
                    abiertas.append(pagina)
                tramos.append([])
            if clave is not None:
                actual = clave
            elif otro_documento:
                actual = None
            tramos[-1].append(pagina)
        for tramo in tramos:
            pieza = grupo if len(tramos) == 1 else replace(grupo, page_numbers=tramo)
            piezas.append((pieza, [p for p in tramo if p in suyos]))
    if not abiertas:
        return grupos, dict(anexos), []
    ancho = max(2, len(grupos.groups[0].code.value)) if grupos.groups else 2
    salida: list[PageGroup] = []
    nuevos: dict[str, list[int]] = {}
    for puesto, (pieza, suyos) in enumerate(piezas, start=1):
        valor = f"{puesto:0{ancho}d}"
        salida.append(replace(pieza, code=type(pieza.code)(value=valor, raw=valor)))
        if suyos:
            nuevos[valor] = suyos
    return replace(grupos, groups=salida), nuevos, abiertas
