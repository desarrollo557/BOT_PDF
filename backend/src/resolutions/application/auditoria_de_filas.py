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

**Las fechas extremas** (2026-11-10, el revisor de fechas): toda fila que las
traiga -- acta, persona, fila del FUID u otra -- las contrasta con su papel con
la regla de **su** habilidad (``perfil.regla_de_fechas``). La corrección con
prueba es error; lo dudoso va a la IA **en la misma pregunta** que los demás
datos de la fila, con los campos ``fecha_inicial`` y ``fecha_final``: una
pregunta por fila, no dos. Cómo quedaron se cuenta en el resumen de la muestra
(``extra["fechas"]``).

**Tras la revisión adversarial del revisor de fechas** (2026-11-10), lo que no
es error de la entrega no infla el margen ni paga la IA:

- **La ventana de años del libro** (``ventana_de_la_auditoria``), la misma en
  las dos muestras: la fecha fuera de ella es duda, sin preguntar. ACOSTA
  BELLO -- 1994-2001 en «HISTORIAS ACADEMICAS 1986» -- se veía al procesar y no
  al cerrar.
- **El texto que no se deja leer** (``texto_legible``): lo que no trae queda
  sin dato, no en duda, y no se le pregunta a la IA. Las historias escritas a
  mano de Enfermería salían 88 de 88 «en duda».
- **La fecha que la fila tomó de otra parte** (el libro, la serie): sin dato
  salvo fuera de la ventana; la deja así el contraste.

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
    CAMPOS_DE_FECHA,
    Pregunta,
    RevisionDeLaFila,
    cifras,
    hojas_de_la_apertura,
    nombre_en_el_texto,
    numero_en_el_texto,
    plano,
    revisar_la_fila,
    texto_legible,
)
from ..domain.fechas_extremas import ANIO, anios_del_texto, difiere_como_el_ocr
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


def regla_de_fechas_de(habilidad: str | None) -> str:
    """La regla de fechas de una habilidad, la de su perfil: la misma en las dos muestras y al procesar (2026-11-10).

    Un perfil que no la diga se audita con la de los extremos -- la genérica,
    sin lector fuerte --: confirma o pregunta, y nunca da por error lo que no sabe leer.
    """
    from ..domain.fechas_extremas import EXTREMOS
    from .perfiles_de_revision import perfil_de

    return getattr(perfil_de(habilidad), "regla_de_fechas", None) or EXTREMOS


#: Cuánto se ensancha, por cada lado, la ventana de años de una historia en la
#: auditoría. Al procesar va con dos años; aquí con seis por arriba (el de
#: Medicina) y cuatro más por abajo, porque una duda falsa infla el margen.
#: Medido sobre 1 266 filas de Enfermería (2026-11-10), por el nombre de su
#: PDF: con la de procesar caían fuera 121; con ésta, 3 -- ACOSTA BELLO, 1994-2001
#: en «HISTORIAS ACADEMICAS 1986», entre ellas --.
MARGEN_DE_LA_HISTORIA = 6
MAS_ATRAS_DE_LA_HISTORIA = 4
#: Un año de más por cada lado en la de las nóminas y los certificados, como la
#: que pasan las nóminas al procesar.
MARGEN_DEL_LIBRO = 1


def ventana_de_la_auditoria(
    habilidad: str | None, nombre: str, textos: Sequence[str] = ()
) -> tuple[int, int] | None:
    """Los años del libro en que pueden caer las fechas de sus documentos, para las dos muestras (2026-11-10).

    La de las habilidades que la usan al procesar, de lo que la auditoría tiene
    a mano y nunca del documento que se audita -- con los años de la propia
    historia la ventana los contendría siempre --:

    - **historias**: los años del nombre de su PDF («HISTORIAS ACADEMICAS
      1986»); sin ellos, y sólo si se pasan los ``textos`` de todo el original
      (la muestra de PDF), los de sus hojas, como al procesar;
    - **nóminas y certificados**: los del nombre del libro, con un año de más;
    - las demás, ninguna: el contraste ya mira los años de «2007-2009» en el
      nombre del archivo de la fila.
    """
    from pathlib import PurePath

    from ..domain.historia_academica import ventana_de_anios
    from ..domain.nomina import ventana_del_libro
    from .perfiles_de_revision import perfil_de

    clave = perfil_de(habilidad).clave
    stem = PurePath(str(nombre or "").replace("\\", "/")).stem
    if clave == "historias":
        ventana = ventana_de_anios([], nombre=stem, margen=MARGEN_DE_LA_HISTORIA)
        if ventana is None and textos:
            ventana = ventana_de_anios(list(textos), margen=MARGEN_DE_LA_HISTORIA)
        return (ventana[0] - MAS_ATRAS_DE_LA_HISTORIA, ventana[1]) if ventana else None
    if clave in ("nominas", "certificados"):
        ventana = ventana_del_libro(stem)
        return (ventana[0] - MARGEN_DEL_LIBRO, ventana[1] + MARGEN_DEL_LIBRO) if ventana else None
    return None


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
    ventana: tuple[int, int] | None = None,
) -> PdfAuditado:
    """La fila contra sus páginas, con los patrones de su habilidad y la IA para lo dudoso.

    ``sin_texto`` son las páginas de la fila que no dieron texto ni con la capa
    ni con Tesseract; ``paginas_pedidas``, las que dice la fila, para decir si
    no están en el PDF. ``ventana``, los años de su libro
    (``ventana_de_la_auditoria``).
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
    legible = texto_legible(textos)
    # Las fechas, con la regla de su habilidad: la de la constancia (2026-11-10).
    revision = revisar_la_fila(
        fila,
        textos,
        de_pila=de_pila,
        apellidos=apellidos,
        regla_de_fechas=regla_de_fechas_de(habilidad),
        ventana=ventana,
        legible=legible,
    )
    errores = list(revision.errores)
    dudas = list(revision.dudas)
    errores_del_perfil, dudas_del_perfil = _patrones_de_la_habilidad(habilidad, fila)
    if not (errores or revision.preguntas or revision.confirmados or errores_del_perfil or dudas_del_perfil):
        # Un texto que no se deja leer no confirma ni desmiente nada: la fila
        # no se audita y no cuenta para el margen (2026-11-10).
        motivo = (
            "sus páginas no se dejan leer (letra a mano o capa con basura): nada que comprobar en el papel"
            if not legible
            else "la fila no trae datos que comprobar en el papel"
        )
        return PdfAuditado(nombre, NO_AUDITADO, (motivo,), paginas=len(textos), habilidad=habilidad)
    preguntadas = 0
    # A la IA, sólo lo que una cita puede decidir: la fecha fuera de los años
    # del libro va derecho a duda (``para_la_ia``), y un texto que no se deja
    # leer no se le manda.
    if juez is not None and legible and any(p.para_la_ia for p in revision.preguntas):
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
        extra={
            "confirmados": list(revision.confirmados),
            "sin_dato": list(revision.sin_dato),
            # Como en la muestra de PDF: cuántos documentos en cada estado.
            "fechas": {estado_de_las_fechas(revision.confirmados, errores, dudas): 1},
        },
    )


#: Cómo quedaron las fechas de un documento auditado (2026-11-10): lo que el
#: resumen de cada muestra cuenta, la de filas y la de PDF.
FECHAS_CONFIRMADAS = "confirmadas"
FECHAS_CON_ERROR = "con error"
FECHAS_EN_DUDA = "en duda"
FECHAS_SIN_DATO = "sin fechas"
_DE_FECHA = ("la fecha", "fecha")


def estado_de_las_fechas(confirmados: Sequence[str], errores: Sequence[str], dudas: Sequence[str]) -> str:
    """Cómo salieron las fechas de un documento, después de la IA: con error, en duda, confirmadas o sin fechas."""
    if any(e.startswith(_DE_FECHA) for e in errores):
        return FECHAS_CON_ERROR
    if any(d.startswith(_DE_FECHA) for d in dudas):
        return FECHAS_EN_DUDA
    if any(c.startswith(_DE_FECHA) for c in confirmados):
        return FECHAS_CONFIRMADAS
    return FECHAS_SIN_DATO


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
    # Lo que no se le pregunta -- fuera de los años del libro -- queda en duda tal cual.
    dudas: list[str] = [p.duda for p in revision.preguntas if not p.para_la_ia]
    preguntas = [p for p in revision.preguntas if p.para_la_ia]
    try:
        respuesta = juez.verificar(
            texto[:TEXTO_PARA_LA_IA],
            [{"campo": p.campo, "valor": p.valor} for p in preguntas],
        )
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 - una respuesta rara no se lleva lo que la regla ya probó
        # Antes la fila entera quedaba «no auditada» y sus errores de la regla
        # se perdían (la segunda revisión, 2026-11-09).
        respuesta = None
    if not respuesta:
        return errores, dudas + [f"{p.duda} (la IA no respondió)" for p in preguntas], 0
    contestadas = 0
    for pregunta in preguntas:
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
    - **Fecha inicial o final** (2026-11-10): la de la fila, leída en la cita
      como fecha; o su año, si la fila sólo da el año.
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
    if campo in CAMPOS_DE_FECHA:
        if (anio := _anio(pregunta.valor)) is not None:
            return anio in anios_del_texto(cita)
        return _fecha(pregunta.valor) in fechas_del_texto(cita)
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
    - **Fecha inicial o final** (2026-11-10): como la de la sesión, o un año que
      se aparta en dos dígitos o más; y si el lector de la regla de su
      habilidad dijo una fecha, la cita tiene que traer ésa: la próxima reunión
      o la fecha de la plantilla no contradicen nada.
    """
    campo = pregunta.campo
    if campo in CAMPOS_DE_FECHA:
        return _fecha_que_contradice(pregunta, cita)
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


def _anio(valor: str) -> int | None:
    """El año de una fecha que la fila sólo da por su año: «1986»."""
    texto = (valor or "").strip()
    return int(texto) if re.fullmatch(r"\d{4}", texto) else None


def _fecha_que_contradice(pregunta: Pregunta, cita: str) -> bool:
    """Si la cita de la IA contradice la fecha inicial o final de la fila, y no sólo como el OCR."""
    from datetime import date

    if (anio := _anio(pregunta.valor)) is not None:
        citados = anios_del_texto(cita)
        if not citados or anio in citados:
            return False
        choca = all(not difiere_como_el_ocr(date(anio, 1, 1), date(otro, 1, 1), ANIO) for otro in citados)
        return choca and (pregunta.dice_el_papel is None or pregunta.dice_el_papel.year in citados)
    dato = _fecha(pregunta.valor)
    citadas = fechas_del_texto(cita)
    if dato is None or not citadas or dato in citadas:
        return False
    choca = all(_fecha_que_choca(dato, otra) for otra in citadas)
    return choca and (pregunta.dice_el_papel is None or pregunta.dice_el_papel in citadas)


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
