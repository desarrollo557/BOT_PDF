"""Una fila del inventario auditada: lo que dice el papel, los patrones de su habilidad y lo dudoso decidido por la IA.

La regla de cada clase de fila está en ``domain/auditoria_de_filas.py``. Aquí se
junta con dos cosas más (2026-11-09):

- **Los patrones de su habilidad**: lo que su perfil espera de los datos de un
  documento (``perfil.datos.revisar`` -- las fechas extremas de una historia,
  la cédula de una nómina --), lo mismo que se revisa al procesar. El operador:
  «que la auditoría tome como margen de error cada patrón de cada habilidad».
- **La IA**, sólo si la corrida se hizo con ella: se le manda el texto de las
  páginas de la fila y los datos que la auditoría no encontró, y contesta por
  cada uno «esta», «no_esta» o «no_se» con la cita del papel. Una cita que el
  texto no trae no vale; un «esta» cuya cita no contiene el dato tampoco; y un
  «no_esta» que se aparta como lo aparta el OCR -- un dígito -- queda en duda.

Una fila que no se pudo leer -- sus páginas no dan texto, o no están en el PDF
-- o que no trae nada que comprobar **no se audita**: no cuenta para el margen.
Certificar lo que no se leyó era el mismo engaño que el «< 0 %» que el operador
prohibió (la revisión, 2026-11-09).
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Mapping, Sequence

from ..domain.acta_consejo import fechas_del_texto
from ..domain.auditoria import NO_AUDITADO, PdfAuditado, veredicto
from ..domain.auditoria_de_filas import (
    Pregunta,
    RevisionDeLaFila,
    cifras,
    hojas_de_la_apertura,
    nombre_en_el_texto,
    numero_en_el_texto,
    plano,
    revisar_la_fila,
)
from .control import Cancelled
from .ports import JuezDeDatos

#: Cuánto texto de una fila se le manda a la IA: un acta larga son unos treinta
#: mil caracteres; más es pagar tokens por páginas de anexos.
TEXTO_PARA_LA_IA = 30_000
#: Lo mínimo que tiene que tener una cita para tomarla: dos palabras.
CITA_MINIMA = 4
#: Desde qué parecido un nombre citado es el mismo leído con otra letra:
#: «Shirley» y «Shyriey» (0,83) sí; «Ordóñez» y «Ordosgoitia» (0,72) no.
PARECIDO_DEL_OCR = 0.8


def nombres_de_persona() -> tuple[frozenset[str], frozenset[str]]:
    """Los nombres de pila y los apellidos hispanos frecuentes, para saber qué frase del resumen es una persona."""
    from .acta_consejo import _nombres_del_archivo

    return _nombres_del_archivo()


def cita_del_papel(cita: str, texto: str) -> bool:
    """Si la cita está, sin tildes ni signos, en el texto: lo que la IA dice que el papel dice."""
    buscada = plano(cita)
    return len(buscada) >= CITA_MINIMA and buscada in plano(texto)


def auditar_una_fila(
    nombre: str,
    fila: Mapping[str, object],
    textos: Sequence[str],
    *,
    habilidad: str = "",
    juez: JuezDeDatos | None = None,
    sin_texto: int = 0,
    paginas_pedidas: tuple[int, int] | None = None,
) -> PdfAuditado:
    """La fila contra sus páginas, con los patrones de su habilidad y la IA para lo dudoso.

    ``sin_texto`` son las páginas de la fila que no dieron texto ni con la capa
    ni con Tesseract; ``paginas_pedidas``, las que dice la fila, para decir si
    no están en el PDF.
    """
    if not textos:
        donde = f"sus páginas {paginas_pedidas[0]}-{paginas_pedidas[1]}" if paginas_pedidas else "sus páginas"
        return PdfAuditado(nombre, NO_AUDITADO, (f"{donde} no están en el PDF",), habilidad=habilidad)
    if sin_texto >= len(textos):
        return PdfAuditado(
            nombre,
            NO_AUDITADO,
            ("sus páginas no dieron texto que leer, ni con la capa ni con Tesseract",),
            paginas=len(textos),
            habilidad=habilidad,
        )
    de_pila, apellidos = nombres_de_persona()
    revision = revisar_la_fila(fila, textos, de_pila=de_pila, apellidos=apellidos)
    errores = list(revision.errores)
    dudas = list(revision.dudas)
    errores_del_perfil, dudas_del_perfil = _patrones_de_la_habilidad(habilidad, fila)
    if not (errores or revision.preguntas or revision.confirmados or errores_del_perfil or dudas_del_perfil):
        return PdfAuditado(
            nombre,
            NO_AUDITADO,
            ("la fila no trae datos que comprobar en el papel",),
            paginas=len(textos),
            habilidad=habilidad,
        )
    preguntadas = 0
    if revision.preguntas and juez is not None:
        errores, dudas, preguntadas = _con_la_ia(revision, textos, juez, apertura=hojas_de_la_apertura(textos))
    errores.extend(errores_del_perfil)
    dudas.extend(dudas_del_perfil)
    if sin_texto and (dudas or errores):
        dudas.append(f"{sin_texto} página(s) de la fila sin texto que leer")
    if paginas_pedidas and (pedidas := paginas_pedidas[1] - paginas_pedidas[0] + 1) > len(textos):
        # Las páginas 225-240 en un libro de 231: se audita lo que hay, y se dice.
        dudas.append(f"{pedidas - len(textos)} de sus {pedidas} páginas no están en el PDF")
    return PdfAuditado(
        pdf=nombre,
        estado=veredicto(errores, dudas),
        hallazgos=tuple(errores + dudas),
        paginas=len(textos),
        preguntadas_a_la_ia=preguntadas,
        habilidad=habilidad,
        extra={"confirmados": list(revision.confirmados), "sin_dato": list(revision.sin_dato)},
    )


def _patrones_de_la_habilidad(habilidad: str, fila: Mapping[str, object]) -> tuple[list[str], list[str]]:
    """Lo que el perfil de la habilidad espera de los datos de la fila: sus errores y sus dudas."""
    from ..domain.datos_esperados import ERROR as GRAVE
    from .perfiles_de_revision import perfil_de

    esperados = perfil_de(habilidad).datos
    if esperados is None:
        return [], []
    try:
        datos = esperados.de_la_fila(fila)
    except Exception:  # noqa: BLE001 - una fila con otra forma no tumba la auditoría
        return [], []
    if datos is None:
        return [], []
    hallazgos = esperados.revisar(datos)
    return (
        [h.texto for h in hallazgos if h.gravedad == GRAVE],
        [h.texto for h in hallazgos if h.gravedad != GRAVE],
    )


def _con_la_ia(
    revision: RevisionDeLaFila, textos: Sequence[str], juez: JuezDeDatos, *, apertura: str = ""
) -> tuple[list[str], list[str], int]:
    """Lo dudoso preguntado a la IA: lo que cita del papel lo decide; lo demás sigue en duda.

    Devuelve los errores, las dudas y cuántos datos contestó la IA: una IA
    caída o sin llave no «revisó» nada (la revisión, 2026-11-09).
    """
    texto = "\n".join(textos)
    errores = list(revision.errores)
    dudas: list[str] = []
    try:
        respuesta = juez.verificar(
            texto[:TEXTO_PARA_LA_IA],
            [{"campo": p.campo, "valor": p.valor} for p in revision.preguntas],
        )
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 - una respuesta rara no se lleva lo que la regla ya probó
        # Antes la fila entera quedaba «no auditada» y sus errores de la regla
        # se perdían (la segunda revisión, 2026-11-09).
        respuesta = None
    if not respuesta:
        return errores, [f"{p.duda} (la IA no respondió)" for p in revision.preguntas], 0
    contestadas = 0
    for pregunta in revision.preguntas:
        dicho = respuesta.get(pregunta.campo)
        if dicho is None or not cita_del_papel(dicho.cita, texto):
            dudas.append(pregunta.duda)
            continue
        # Sólo cuenta lo que la IA contestó citando el papel.
        contestadas += 1
        cita = dicho.cita.strip()[:120]
        if dicho.decision == "esta" and cita_con_el_dato(pregunta, cita, apertura=apertura):
            continue
        if dicho.decision == "no_esta" and contradice(pregunta, cita):
            errores.append(f"{pregunta.duda}: la IA lo confirma, el papel dice «{cita}»")
        elif dicho.decision == "no_esta":
            # «16 DE ENERO DE 2000» frente a 16/01/2009: un dígito, o una letra
            # en un nombre, es lo que el OCR viejo del escaneo cambia. La fila
            # salió de una lectura mejor; no se le cree al texto contra ella,
            # pero se dice.
            dudas.append(f"{pregunta.duda}: el texto dice «{cita}», que puede ser el OCR: revíselo en el papel")
        else:
            dudas.append(pregunta.duda)
    return errores, dudas, contestadas


def cita_con_el_dato(pregunta: Pregunta, cita: str, *, apertura: str = "") -> bool:
    """Si la cita de un «esta» trae de verdad el dato, y donde el dato va.

    - **Sesión**: la de la cita, sin la otra: «LISTA DE ASISTENCIA» no confirma
      nada, y «ORDINARIA» está dentro de «EXTRAORDINARIA».
    - **Fecha**: la fecha leída como fecha, y en la hoja que abre la sesión: la
      citación anexa «FECHA: LUNES 20 DE JUNIO» no confirma el acta del 21.
    - **Número del acta**: tras su rótulo; «07:30 HORAS» no confirma el 007.
    - **Cédula, código, consecutivo**: todas sus cifras juntas.
    - **Nombre**: sus palabras juntas en la cita.

    Lo midió la segunda revisión (2026-11-09) con una IA que cita cualquier
    trozo con el valor: el 44 % de los números cambiados en uno pasaba.
    """
    campo = pregunta.campo
    if campo == "sesion":
        return _sesion_de_la_cita(cita) == plano(pregunta.valor)
    if campo == "fecha":
        en_la_apertura = not apertura or cita_del_papel(cita, apertura)
        return _fecha(pregunta.valor) in fechas_del_texto(cita) and en_la_apertura
    if campo.startswith("nombre"):
        return nombre_en_el_texto(pregunta.valor, cita)
    numero = cifras(pregunta.valor)
    if not numero:
        return False
    if campo == "numero":
        sin_ceros = numero.lstrip("0") or "0"
        # «ACTA No. 022» o «sesión número veintidós (022)».
        return re.search(rf"\b(?:ACTA|SESION)\b\D{{0,24}}\b0*{sin_ceros}\b", plano(cita)) is not None
    return numero_en_el_texto(numero, cita)


def _sesion_de_la_cita(cita: str) -> str | None:
    """«EXTRAORDINARIA» u «ORDINARIA» si la cita dice una y sólo una."""
    llana = plano(cita)
    extra = "EXTRAORDINARI" in llana
    ordinaria = re.search(r"(?<!EXTRA)ORDINARI", llana) is not None
    if extra and not ordinaria:
        return "EXTRAORDINARIA"
    if ordinaria and not extra:
        return "ORDINARIA"
    return None


def contradice(pregunta: Pregunta, cita: str) -> bool:
    """Si lo que el papel dice choca con el dato, y no sólo como lo aparta el OCR.

    - **Fecha**: la de la cita, leída como fecha, con otro mes, o con el día y el
      año a la vez distintos, o con más de un dígito cambiado. «16 DE ENERO DE
      2000 09 30 HORAS» frente a 16/01/2009 no contradice: un dígito, y la hora
      no es la fecha. Una cita sin fecha legible no contradice nada.
    - **Número** (acta, cédula, código): otro de distinto largo, o del mismo con
      dos dígitos o más cambiados.
    - **Nombre**: otro con parecido menor de 0,8: «EDUARDO ORDOGOITIA» frente a
      «Eduardo Ordóñez Ordoñez».
    """
    campo = pregunta.campo
    if campo == "fecha":
        dato = _fecha(pregunta.valor)
        citadas = fechas_del_texto(cita)
        if dato is None or not citadas or dato in citadas:
            return False
        return all(_fecha_que_choca(dato, otra) for otra in citadas)
    if campo.startswith("nombre"):
        # Una cita con basura del OCR -- «MALRICIO RLBZ» por Mauricio Rivas,
        # palabras sin vocales o con signos -- no prueba otra persona: duda.
        return not _parecido_en(pregunta.valor, cita) and not _con_basura_del_ocr(cita)
    if campo == "sesion":
        # Sólo si la cita dice la otra, y sólo la otra.
        otra = _sesion_de_la_cita(cita)
        return otra is not None and otra != plano(pregunta.valor)
    numero = cifras(pregunta.valor).lstrip("0") or "0"
    citados = [n.lstrip("0") or "0" for n in re.findall(r"\d+", cita or "")]
    if not citados or numero in citados:
        return False
    return all(len(n) != len(numero) or sum(a != b for a, b in zip(n, numero, strict=True)) >= 2 for n in citados)


def _con_basura_del_ocr(cita: str) -> bool:
    """Si la cita trae lo que deja el OCR en letra mala: signos dentro de palabras, palabras sin vocales."""
    if re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ][\^~|\\{}<>@#$%&*=_][A-Za-zÁÉÍÓÚÑáéíóúñ]", cita or ""):
        return True
    palabras = re.findall(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü]{3,}", cita or "")
    return any(not re.search(r"[AEIOUYaeiouyÁÉÍÓÚáéíóú]", palabra) for palabra in palabras)


def _fecha_que_choca(dato, otra) -> bool:
    if otra.month != dato.month:
        return True
    cambios = sum(
        a != b
        for a, b in zip(f"{dato.day:02d}{dato.year:04d}", f"{otra.day:02d}{otra.year:04d}", strict=True)
    )
    return cambios >= 2


def _fecha(valor: str):
    from datetime import date

    hallada = re.fullmatch(r"\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\s*", valor or "")
    if not hallada:
        return None
    try:
        return date(int(hallada.group(3)), int(hallada.group(2)), int(hallada.group(1)))
    except ValueError:
        return None


def _parecido_en(valor: str, cita: str) -> bool:
    """Si el nombre está en la cita con una o dos letras cambiadas."""
    v, c = plano(valor), plano(cita)
    if not v or not c:
        return False
    palabras = c.split()
    largo = len(v.split())
    trozos = [" ".join(palabras[i : i + largo]) for i in range(max(1, len(palabras) - largo + 1))]
    return any(difflib.SequenceMatcher(None, v, t).ratio() >= PARECIDO_DEL_OCR for t in trozos)


def parece_del_ocr(valor: str, cita: str, campo: str | None = None) -> bool:
    """Lo contrario de ``contradice``: la cita se aparta del dato sólo como lo aparta el OCR.

    Sin ``campo``: una fecha si el dato lo es, un número si trae cifras, un nombre si no.
    """
    if campo is None:
        campo = "fecha" if _fecha(valor) else ("numero" if cifras(valor) else "nombre")
    return not contradice(Pregunta(campo, valor, ""), cita)
