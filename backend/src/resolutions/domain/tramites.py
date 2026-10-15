"""El trámite al que pertenece cada página de una caja de correspondencia.

Un expediente de un suscriptor junta varios trámites: la solicitud del servicio
con todos sus requisitos, una reclamación con su respuesta y su notificación,
otra reclamación un mes después. El operador pidió entregarlos así, un archivo
por trámite, y dictó cómo reconocerlos: por su número de radicado, y con la
fecha como filtro para lo que no lo trae.

* **El radicado es el ancla.** La reclamación lleva «N° PQR: RE4310202207352»
  en su constancia y «ASUNTO: Reclamación No. RE4310202207352» en su
  respuesta; la solicitud de servicio, «EXPEDIENTE No. P43102019110005» en su
  portada. Una página con un radicado nuevo abre un trámite; una con uno ya
  visto -- la segunda copia de la portada del expediente -- es de ése.
* **La fecha filtra lo demás.** La cédula, la factura, el certificado de
  tradición no traen radicado: van con el trámite abierto, salvo que su fecha
  encaje en el trámite que viene y no en el abierto.

Aquí está lo que no depende de cómo se leyó el papel; la agrupación vive en
``application.agrupacion``.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from datetime import date, timedelta

#: «RE4310202207352»: la PQR de la reclamación, con lo que el OCR le hace -- un
#: espacio entre la R y la E, o entre la E y las cifras --.
_PQR = re.compile(r"(?<![A-Z0-9])R\s?E\s?(\d{13})(?!\d)")
#: «P43102019110005»: el expediente de una solicitud de servicio.
_EXPEDIENTE = re.compile(r"(?<![A-Z0-9])P\s?(\d{14})(?!\d)")
#: «NIC: 4415228», «CODIGO (NIC): 4415228», «Cuenta Interna No. 1012171».
_NIC = re.compile(r"\bNIC\b\W{0,6}(\d{6,9})\b")
#: Patrones adicionales para Cuenta Interna
_CUENTA_INTERNA = re.compile(r"\bCuenta\s+Interna\s+No\.?\s*(\d{6,9})\b", re.IGNORECASE)
#: Secciones que indican continuidad (sin punto final)
_SECCIONES_ABIERTAS = re.compile(
    r"\b(?:PETICIONES|HECHOS|FUNDAMENTOS|SOLICITO|CONSIDERANDO|ANTECEDENTES):\s*$",
    re.IGNORECASE | re.MULTILINE
)

#: Lo que abre un trámite cuando su radicado no se pudo leer: la constancia de
#: la reclamación, la carta del usuario, la portada del expediente.
_ABRE = re.compile(
    r"RECIBI\s+CONSTANCIA\s+DEL\s+CONTENIDO|DERECHO\s+DE\s+PETICION|EXPEDIENTE\s+NO"
    r"|CONSTANCIA\s+DE\s+CONTRATACION|NOTIFICACION\s+DEL\s+RECLAMO"
)
#: Lo que dice que el trámite es una reclamación.
_RECLAMO = re.compile(r"\bRECLAM(?:O|ACION)\b")

#: Cuánto antes de la fecha del trámite puede estar fechado un papel suyo: la
#: factura que se reclama es de los meses anteriores.
DIAS_ANTES = 120
#: Y cuánto después: la notificación, el certificado que se pidió para él.
DIAS_DESPUES = 45


def _plano(texto: str) -> str:
    import unicodedata

    sin_tildes = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.upper())


def radicados_de(texto: str) -> list[str]:
    """Los radicados de una página, en orden y sin repetir: «RE4310202207352», «P4310…»."""
    plano = _plano(texto)
    hallados = [(m.start(), f"RE{m.group(1)}") for m in _PQR.finditer(plano)]
    hallados += [(m.start(), f"P{m.group(1)}") for m in _EXPEDIENTE.finditer(plano)]
    vistos: list[str] = []
    for _, radicado in sorted(hallados):
        if radicado not in vistos:
            vistos.append(radicado)
    return vistos


def radicado_de(texto: str) -> str | None:
    """El radicado que ancla la página: el de la PQR si lo trae, si no el del expediente."""
    radicados = radicados_de(texto)
    pqr = [r for r in radicados if r.startswith("RE")]
    return (pqr or radicados or [None])[0]


# -- el radicado del sello, como lo deja la OCR -----------------------------------

#: El sello de radicación que la empresa pega en el escrito -- «AL CONTESTAR
#: CITE ESTE NUMERO RE3110202139039» -- llega de la OCR hecho trizas:
#: «NUMF.nORK3110202139039», «NU\IF,nORF.3110202140544», «NUMF.RORF.J
#: 11020214J4?9» (UPD2320043). La palabra NUMERO, la «RE» y hasta dos letras de
#: basura, y después doce a catorce caracteres que deberían ser trece cifras.
_SELLO_CRUDO = re.compile(
    r"(?:N\W?[UV]\W?[MVWI\\]{1,2}\W?[EF]\W?[RN]\W?[O0]\W?R|NUMERO)"
    r"\W{0,3}[RK]?\W?[A-Z\]]{0,2}\W?"
    # Las cifras, con la I y la J que la OCR pone por un 1 sólo si van entre
    # cifras: la «I» de un «I-olios» que viene detrás no es parte del número.
    r"((?:\d|[IJ?](?=\s?\d))(?:\s?(?:\d|[IJ?](?=\d))){11,13})(?!\d)"
)
#: Hasta dónde se busca el sello: va arriba, en la primera cara del escrito.
CABEZA_DEL_SELLO = 1000


def _anio_valido(cifras: str) -> bool:
    """Las cifras 5 y 6 son el siglo del año: «3110 2021 39039»."""
    return cifras[4:6] == "20"


def reparar_radicado(crudo: str, oficinas: Counter[str]) -> str | None:
    """Un radicado mal leído, rehecho sólo de la forma que no deja dudas.

    Las trece cifras son oficina (4), año (4) y consecutivo (5). Se acepta lo
    que la OCR dejó si cuadra; con una cifra de más dentro de una racha
    repetida -- «424449» por «42449» -- se quita; con una de menos, se pone
    delante la oficina de la caja. Lo demás no se adivina.
    """
    cifras = re.sub(r"\s", "", crudo).replace("I", "1").replace("J", "1").replace("?", "")
    if not cifras.isdigit():
        return None
    if len(cifras) == 13:
        return f"RE{cifras}" if _anio_valido(cifras) else None
    if len(cifras) == 14:
        candidatos = {
            cifras[:i] + cifras[i + 1 :] for i in range(8, 14) if cifras[i] == cifras[i - 1]
        }
        candidatos = {c for c in candidatos if _anio_valido(c)}
        return f"RE{candidatos.pop()}" if len(candidatos) == 1 else None
    if len(cifras) == 12 and oficinas:
        oficina = oficinas.most_common(1)[0][0]
        for falta in range(4):
            if oficina[falta + 1 :] and cifras.startswith(oficina[falta + 1 :]):
                completo = oficina[: falta + 1] + cifras
                if len(completo) == 13 and _anio_valido(completo):
                    return f"RE{completo}"
    return None


#: El sello se reconoce aunque su número no se pueda rehacer: «AL CONTESTAR
#: CITE ESTE NUMERO» -- «AT CONTHSTAn C ÍTP», «Af CONTESTAR CtTF» -- o la
#: palabra NUMERO rota y pegada a cifras: «NUMF.RORF.J 11020214J4?9».
_SELLO_VISIBLE = re.compile(
    r"CONT[EHI]\W?STA[RN]\W{0,3}C"
    r"|N\W?[UV]\W?[MVWI\\]{1,2}\W?[EF]\W?[RN]\W?[O0]\W?R\W{0,3}[A-Z]{0,3}\W?\d"
)


#: La fecha del sello, detrás de su rótulo como lo deja la OCR: «Fecha:»,
#: «l oclia:», «l'cciu':», «|■cclla:».
_FECHA_DEL_SELLO = re.compile(
    r"(?:FE|[|L']\W?[EOC])?C\W?[HLI]{1,2}\W?[AU]\W{0,3}\s*"
    r"(\d{1,2})\s*[/-]\s*(\d{1,2})\s*[/-]\s*(\d[\d ]{1,4})"
)


def fecha_del_sello(texto: str, radicado: str | None) -> date | None:
    """La fecha de radicación escrita en el sello, completada con su radicado.

    El año del sello llega cortado -- «17/09/202» --, y el radicado lo trae
    entero en sus cifras 5 a 8: RE3110**2021**40544. Sólo se completa si lo
    leído es el principio de ese año; el día y el mes tienen que ser cifras.
    """
    anio_del_radicado = radicado[6:10] if radicado and radicado.startswith("RE") else None
    for hallada in _FECHA_DEL_SELLO.finditer(_plano(texto)[:CABEZA_DEL_SELLO]):
        dia, mes, anio = int(hallada.group(1)), int(hallada.group(2)), hallada.group(3).replace(" ", "")
        if len(anio) != 4:
            if not (anio_del_radicado and anio_del_radicado.startswith(anio)):
                continue
            anio = anio_del_radicado
        try:
            return date(int(anio), mes, dia)
        except ValueError:
            continue
    return None


def lleva_sello_de_radicacion(texto: str) -> bool:
    """Si la hoja trae arriba el sello con que la empresa radica un escrito."""
    return _SELLO_VISIBLE.search(_plano(texto)[:CABEZA_DEL_SELLO]) is not None


def radicado_del_sello(texto: str, oficinas: Counter[str] | None = None) -> str | None:
    """El radicado de un sello que la OCR rompió, rehecho; ``None`` si no se puede.

    ``oficinas`` son las cuatro primeras cifras de los radicados bien leídos de
    la caja: todos los de un expediente comparten oficina, y es lo que permite
    completar el que perdió una cifra.
    """
    for crudo in _SELLO_CRUDO.findall(_plano(texto)[:CABEZA_DEL_SELLO]):
        reparado = reparar_radicado(crudo, oficinas or Counter())
        if reparado:
            return reparado
    return None


def nic_de(texto: str) -> str | None:
    """Extrae el NIC de una página, incluyendo variantes como 'Cuenta Interna No.'"""
    # Buscar NIC estándar
    hallado = _NIC.search(_plano(texto))
    if hallado:
        return hallado.group(1)
    
    # Buscar Cuenta Interna No.
    hallado = _CUENTA_INTERNA.search(texto)
    if hallado:
        return hallado.group(1)
    
    return None


def pagina_con_seccion_abierta(texto: str) -> bool:
    """Si la página termina con una sección sin cerrar (ej: PETICIONES:)."""
    return bool(_SECCIONES_ABIERTAS.search(_plano(texto)))


def abre_un_tramite(texto: str) -> bool:
    """Si la página es de las que abren un trámite, aunque no se le lea el radicado."""
    return bool(_ABRE.search(_plano(texto)))


def es_reclamo(textos: Iterable[str]) -> bool:
    return any(_RECLAMO.search(_plano(texto)) for texto in textos)


def en_ventana(fecha: date, del_tramite: date) -> bool:
    """Si un papel fechado ``fecha`` puede ser del trámite fechado ``del_tramite``."""
    return (
        del_tramite - timedelta(days=DIAS_ANTES)
        <= fecha
        <= del_tramite + timedelta(days=DIAS_DESPUES)
    )


def nic_mas_comun(nics: Iterable[str | None]) -> str | None:
    cuenta = Counter(n for n in nics if n)
    return cuenta.most_common(1)[0][0] if cuenta else None


def despues_de_la_ventana(fecha: date, del_tramite: date) -> bool:
    """Si un papel está fechado después de lo que un trámite puede durar.

    Antes no se mira: una factura vieja, un certificado de tradición, se anexan
    a un trámite de años después sin dejar de ser suyos.
    """
    return fecha > del_tramite + timedelta(days=DIAS_DESPUES)


def radicados_parecidos(uno: str, otro: str) -> bool:
    """Si dos radicados distintos se diferencian en una sola cifra.

    Es la huella de un mal leído: «RE4310202207352» y «RE4310202207362» en la
    misma caja son, casi siempre, el mismo trámite con un 5 que la OCR vio 6.
    """
    return (
        uno != otro
        and len(uno) == len(otro)
        and uno[:2] == otro[:2]
        and sum(a != b for a, b in zip(uno, otro, strict=True)) == 1
    )


# -- de quién es una cédula -----------------------------------------------------

#: Lo que trae impreso toda cédula colombiana, por los dos lados. Con dos de
#: estos rótulos la hoja es la fotocopia de una cédula. Se buscan con la letra
#: que la OCR se come en la tarjeta gris -- «¡DENTIFICACION FERSONAL», «CEDULA
#: DE GIUDADANIA» --, y no la fecha de nacimiento, que también la pide un
#: formulario de contratación.
_ROTULOS_DE_CEDULA = (
    r"DENTIFICACION\s+[PF]ERSONAL",
    # «CEDULS, CE CIUDADANIA» (UPD2326386 p9).
    r"C[EI]DUL\w\W{0,3}\s*[DC][EF]\s+[CG][IL]?UDADAN",
    # El número de la tarjeta con su rótulo debajo: «5.163.897 NUMERO». La
    # prosa dice «cédula de ciudadanía No. 5.163.897», sin «NUMERO» detrás.
    r"UDADAN\w*\W{0,3}\s*\d[\d.]{6,12}\s+NUMERO\b",
    r"\bE\s?STATURA\b",
    r"REGISTRADOR\s+NACIONAL",
    r"INDICE\s+DERECHO",
)
#: Las palabras de esos rótulos, que no dicen de quién es la cédula.
_PALABRAS_DE_ROTULO = frozenset(
    [
        "REPUBLICA",
        "COLOMBIA",
        "IDENTIFICACION",
        "PERSONAL",
        "CEDULA",
        "CIUDADANIA",
        "NUMERO",
        "APELLIDOS",
        "NOMBRES",
        "FIRMA",
        "FECHA",
        "NACIMIENTO",
        "LUGAR",
        "ESTATURA",
        "SEXO",
        "EXPEDICION",
        "REGISTRADOR",
        "NACIONAL",
        "INDICE",
        "DERECHO",
    ]
)
#: Un número de identidad como se escribe -- «64.581.460», «92516337» -- y
#: como va en el código de barras del reverso: «-F-0064581460-».
_NUMERO = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3}){2,3}|\d{7,10})(?![\d])")
_CODIGO_DE_BARRAS = re.compile(r"-[MF]\W?0*(\d{7,10})\W")


def es_cedula(texto: str) -> bool:
    """Si la página es la fotocopia de una cédula."""
    plano = _plano(texto)
    return sum(bool(re.search(rotulo, plano)) for rotulo in _ROTULOS_DE_CEDULA) >= 2


def numeros_de(texto: str) -> set[str]:
    """Los números que pueden ser de una cédula, sin puntos ni ceros delante."""
    plano = _plano(texto)
    hallados = {re.sub(r"\D", "", n).lstrip("0") for n in _NUMERO.findall(plano)}
    hallados |= {n.lstrip("0") for n in _CODIGO_DE_BARRAS.findall(plano)}
    return {n for n in hallados if 7 <= len(n) <= 10}


def parejas_de_palabras(texto: str) -> set[str]:
    """Las palabras de tres letras o más que van seguidas: «PAYARES SERPA».

    Un apellido suelto se repite en cualquier expediente; dos seguidos ya dicen
    de quién se habla. Los rótulos de la cédula no cuentan.
    """
    palabras = re.findall(r"[A-Z]+", _plano(texto))
    return {
        f"{una} {otra}"
        for una, otra in zip(palabras, palabras[1:], strict=False)
        if len(una) >= 3
        and len(otra) >= 3
        and una not in _PALABRAS_DE_ROTULO
        and otra not in _PALABRAS_DE_ROTULO
    }


def _casi_iguales(uno: str, otro: str) -> bool:
    """El mismo número, o con una cifra mal leída: «64.581.467» por «64581460»."""
    return (
        len(uno) == len(otro) and sum(a != b for a, b in zip(uno, otro, strict=True)) <= 1
    )


def donde_aparece_la_persona(
    cedula: str, tramites: dict[str, str]
) -> dict[str, list[str]]:
    """En qué trámites se nombra a la persona de una cédula, y con qué.

    ``tramites`` es el texto de cada trámite sin sus cédulas: la del
    reclamante se busca en lo que él firmó y en lo que la empresa le contestó,
    no en otra fotocopia. Cuenta su número -- con una cifra de holgura, que la
    cédula fotocopiada se lee mal -- y dos palabras seguidas de su nombre.

    Lo que aparece en todos los trámites no distingue a ninguno -- el titular
    del servicio está en todas las facturas -- y no cuenta: así una cédula sólo
    se reclama para el trámite donde de verdad la nombran.
    """
    numeros = numeros_de(cedula)
    parejas = parejas_de_palabras(cedula)
    rasgos: dict[str, set[str]] = {}
    for clave, texto in tramites.items():
        suyos = numeros_de(texto)
        rasgos[clave] = {
            f"n.º {numero}"
            for numero in numeros
            if any(_casi_iguales(numero, s) for s in suyos)
        } | {f"«{pareja}»" for pareja in parejas & parejas_de_palabras(texto)}
    if len(rasgos) > 1:
        comunes = set.intersection(*rasgos.values())
        rasgos = {clave: suyos - comunes for clave, suyos in rasgos.items()}
    return {clave: sorted(suyos) for clave, suyos in rasgos.items() if suyos}


# -- el remitente de una hoja -------------------------------------------------
#
# Lo usa la continuidad (``segmentation``): dos hojas seguidas con el mismo NIC
# y el mismo remitente son del mismo escrito (UPD2320043, páginas 6 y 7). Vive
# aquí, en el dominio, porque es texto puro; antes estaba en la capa de
# aplicación y el dominio la importaba al revés de lo que permiten las capas.


def normalizar_remitente(nombre: str | None) -> str | None:
    """El nombre listo para comparar: sin acentos, sin signos, en mayúsculas."""
    if not nombre:
        return None
    nombre = unicodedata.normalize("NFKD", nombre)
    nombre = re.sub(r"[^\w\s]", "", nombre)
    return re.sub(r"\s+", " ", nombre).strip().upper()


def extraer_remitente(texto: str) -> str | None:
    """El nombre de quien firma o a quien va la hoja, o ``None``.

    Tras «Señores:», «Señor:» o «Destinatario:», el primer renglón que parece un
    nombre; si no, la firma de las diez últimas líneas.
    """
    lines = texto.split("\n")
    for i, line in enumerate(lines):
        if any(keyword in line for keyword in ["Señores:", "Señor:", "Destinatario:"]):
            for j in range(i + 1, min(i + 9, len(lines))):
                linea = lines[j].strip()
                if (
                    len(linea) > 10
                    and linea[0].isupper()
                    and not any(
                        w in linea.upper()
                        for w in ["OFICINA", "CIUDAD", "FECHA", "ASUNTO", "REF:", "REFERENCIA", "NIC", "ATENTAMENTE"]
                    )
                ):
                    return re.split(r"[;,\n]", linea)[0].strip()
    for line in reversed(lines[-10:]):
        line = line.strip()
        if (
            len(line) > 10
            and line[0].isupper()
            and not any(w in line.upper() for w in ["ATENTAMENTE", "CORDIALMENTE", "NOTIFICACIONES", "FIRMA"])
        ):
            return re.split(r"[;,\n]", line)[0].strip()
    return None
