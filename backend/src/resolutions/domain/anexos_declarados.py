"""Lo que un escrito dice que trae detrás: su lista de «ANEXOS».

La dictó el operador sobre UPD2321099: «si encuentras la palabra anexos, ya
sabes cuántos documentos tendrá un trámite». La escribe el propio cliente al
final de su escrito, y es la única pista del papel que dice de antemano qué
viene pegado detrás:

    ANEXOS
    Contrato de arrendamiento.
    Factura de cobro.
    Cédula de ciudadanía.
    NOTIFICACIONES

Por eso se lee con cuidado, renglón por renglón. La palabra suelta no basta:
«las fotografías anexas», «el anexo general de la Resolución CREG», «en calidad
de Anexo 1» o «SE ME ANEXE ESTADO DE CUENTA» -- que es algo que el cliente pide,
no algo que trae -- son prosa, y leerlas como lista uniría documentos que no
tienen nada que ver. Cuenta como lista sólo:

* un **encabezado** que es la palabra sola en su renglón -- «ANEXOS», «ANEXOS:»,
  «PRUEBAS Y ANEXOS» (la OCR lo deja en «PRUEBA YANEXOS») --, con lo que
  enumera debajo o detrás de los dos puntos, hasta el renglón que abre otra
  sección -- «NOTIFICACIONES», «Atentamente» --; y
* una **frase** que empieza el renglón declarando lo que se adjunta: «Anexo la
  factura del mes… / Y la cédula de ciudadanía».

Cada renglón de la lista se clasifica en una clase de anexo -- contrato,
factura, cédula, certificado de tradición… -- con la que después se busca en
las hojas que siguen. Lo que no se reconoce se guarda con sus palabras, y lo
que remite a otra parte -- «los documentos que relacioné en las pruebas» -- se
anota como una lista sin detalle.

Aquí no se lee papel: entra el texto de una página y sale la lista.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .tramites import es_cedula

#: Las clases de anexo, en el orden en que se prueban. Cada una con lo que la
#: nombra en la lista del escrito y lo que la reconoce en la hoja misma. El
#: orden importa en la lista: un renglón se clasifica por la clase que aparece
#: PRIMERO en él, porque «la factura del mes que está en reclamo por derecho de
#: petición» es una factura, no una petición.
_CLASES: tuple[tuple[str, re.Pattern[str], re.Pattern[str] | None], ...] = (
    (
        "contrato de arrendamiento",
        re.compile(r"CONTRATO\s+DE\s+ARRENDAMIENTO|\bARRENDAMIENTO\b"),
        # Su título, en los primeros renglones: el cuerpo de un escrito también
        # dice «el contrato de arrendamiento goza de toda credibilidad».
        # Al principio de un renglón de la cabecera, no sólo de la hoja: el
        # escaneo deja ruido encima del título (UPD2326310 p6).
        # Y con lo que la OCR le hace al título: «CONTRATO DEARRENDAMIENTO»,
        # «PCONTRATO DE ARRENDAILENTO», «COITOATO DS ARRINDAMRBITOM»
        # (UPD2326409 p6, UPD2326328 p6, UPD2326418 p12): sin reconocerlo, el
        # certificado de delante se tragaba el contrato.
        # Con más ruido delante, sólo si sigue como sigue el título -- «PARA
        # VIVIENDA URBANA», «DE INMUEBLE» --: la prosa «el contrato de
        # arrendamiento goza de credibilidad» no.
        # Las palabras de delante, separadas por espacios y sin vuelta atrás:
        # con «\S+\W+» la basura de la OCR -- signos que son a la vez \S y \W
        # -- hacía retroceder la búsqueda sin fin (UPD2321099 p8 colgaba).
        re.compile(
            r"^\W*+(?:\S++\s++){0,3}\w?C[O0][NI]?[TI][RO]?[AO]T[O0]\s*D[EOS]\s*ARR[EI]\w?NDA"
            r"|^\W*+(?:\S++\s++){0,6}\w?C[O0][NI]?[TI][RO]?[AO]T[O0]\s*D[EOS]\s*ARR[EI]\w?NDA\w*"
            r"\W{0,3}.{0,25}(?:VI\w?[IE]NDA|URBANA|INMUEBLE|LOCAL)",
            re.MULTILINE,
        ),
    ),
    (
        "factura",
        re.compile(
            r"\bFACTURAS?\b|RECIBOS?\s+DE\s+(?:COBRO|ENERGIA|LUZ|SERVICIOS?|LA\s+LUZ)"
            r"|CUENTAS?\s+DE\s+COBRO|ESTADOS?\s+DE\s+CUENTA|\bRECIBOS?\s+PUBLICOS?"
        ),
        re.compile(
            # Lo que sólo imprime la factura. «Facturas vencidas» o «total a
            # pagar» se escriben también en el reclamo que la discute.
            r"OPERADOR\s+DE\s+RED|TITULAR\s+DE\s+PAGO|USE\s+ESTE\s+NUMERO\s+PARA"
            # «OPERADOR OERH)»: el de red con la OCR encima (UPD2326402 p12).
            r"|OPERADOR\s+[DO][EF]\s*R[EH]"
            r"|DATOS\s+DE\s+(?:LA\s+)?FACTURA|ESTADO\s+DE\s+CUENTA\s+DEL\s+SERVICIO"
            r"|PAGUE\s+HASTA|CAPITULO\s+11\s+DEL\s+ANEXO\s+GENERAL"
            # El reverso, el estado de cuenta: «Estado de cuenta / No. Facturas
            # Vencidas / No. Financiaciones pendientes / Fecha Último Pago».
            r"|^\W*(?:\S+\W+){0,2}ESTADO\s+DE\s+CUE|FINANCIACIONES\s+PENDIENTES"
            # Y la que se titula así: «FACTURA DE VENTA», «FACTURA ELECTRÓNICA».
            r"|^\W*(?:\S+\W+){0,2}FACTURA\s+(?:DE\s+VENTA|ELECTRONICA|DE\s+SERVICIOS?|No\b|N\W)"
            r"|NO\.?\s+FACTURAS\s+VENCIDAS|FECHA\s+\S{0,2}LTIMO\s+PA[GQ]O|\bNIU\s*:"
        ),
    ),
    (
        "documento de identidad",
        re.compile(
            r"\bCEDULAS?\b|\bC\.\s?C\.?(?=\s|$)|DOCUMENTOS?\s+DE\s+IDENTI|TARJETAS?\s+DE\s+IDENTIDAD"
            r"|\bIDENTIFICACION\b"
        ),
        re.compile(r"REGISTRADURIA\s+NACIONAL|IDENTIFICACION\s+PERSONAL|INDICE\s+DERECHO"),
    ),
    (
        "certificado de tradición",
        re.compile(r"TRADI+C+ION|LIBERTAD\s+Y\s+TRADI|MATRICULA\s+INMOBILIARIA"),
        re.compile(
            r"CERTIFICADO\s+DE\s+TRADICION|MATRICULA\s+INMOBILIARIA"
            r"|OFICINA\s+DE\s+REGISTRO\s+DE\s+INSTRUMENTOS"
        ),
    ),
    (
        "certificado catastral",
        re.compile(r"NOMENCLATURA|CATASTR|\bIGAC\b|AGUSTIN\s+CODAZZI"),
        re.compile(r"NOMENCLATURA|CATASTR|\bIGAC\b|AGUSTIN\s+CODAZZI"),
    ),
    ("escritura pública", re.compile(r"\bESCRITURAS?\b"), re.compile(r"ESCRITURA\s+PUBLICA")),
    (
        "poder",
        re.compile(r"\bPODER\b"),
        re.compile(r"^\W*PODER\b|(?:CONFIERO|OTORGO)\s+PODER|PODER\s+(?:ESPECIAL|AMPLIO)"),
    ),
    (
        "fotografías",
        # «FOTO» sí, «FOTOCOPIA» no: «Fotocopia de documento de identificación»
        # es una cédula (UPD2326326 p14).
        re.compile(r"\bFOTO(?!\W?COPIA)|REGISTRO\s+FOTOGRAFICO|EVIDENCIAS?\s+FOTOGRAFICA"),
        re.compile(r"REGISTRO\s+FOTOGRAFICO|EVIDENCIAS?\s+FOTOGRAFICAS?|^\W*FOTOGRAFIAS?\b"),
    ),
    (
        "comprobante de pago",
        re.compile(r"COMPROBANTES?|RECIBOS?\s+DE\s+(?:PAGO|CAJA)|CONSIGNACION|SOPORTES?\s+DE\s+PAGO"),
        re.compile(r"COMPROBANTE\s+DE\s+PAGO|RECIBO\s+DE\s+CAJA|CONSIGNACION|TRANSACCION\s+EXITOSA"),
    ),
    (
        "certificado de existencia",
        re.compile(r"CAMARA\s+DE\s+COMERCIO|EXISTENCIA\s+Y\s+REPRESENTACION|\bRUT\b"),
        re.compile(r"CAMARA\s+DE\s+COMERCIO|EXISTENCIA\s+Y\s+REPRESENTACION"),
    ),
    (
        "acta",
        re.compile(r"\bACTAS?\s+DE\b"),
        re.compile(r"^\W*ACTA\s+DE\s+(?:SUSPENSION|VISITA|REVISION|IRREGULARIDAD|INSTALACION)"),
    ),
    # Copias de lo que se tramitó antes: se nombran en la lista pero la hoja no
    # se distingue de un escrito nuevo, así que no tienen reconocedor y quedan
    # «sin verificar» en vez de «faltan».
    (
        "copia de reclamo o respuesta",
        re.compile(
            r"\bRESPUESTA\b|\bRECLAMO\b|DERECHO\s+DE\s+PETICION|\bDECISION\b|\bRESOLUCION\b"
            r"|ACTO\s+ADMINISTRATIVO"
        ),
        None,
    ),
)

#: Las clases cuyo reconocedor busca sólo en la cabecera de la hoja: su nombre
#: también se menciona en el cuerpo de un escrito, y ahí no es el papel.
_EN_LA_CABEZA = {"contrato de arrendamiento", "poder", "acta", "fotografías"}
#: Hasta dónde llega la cabecera de una hoja, en caracteres.
CABEZA = 500

#: Las clases que son anexo aunque nadie las enumere: la fotocopia de una
#: cédula siempre soporta otra cosa. Entre dos anexos declarados no cortan la
#: cadena; se retienen y se anotan como no declaradas.
SIEMPRE_ANEXO = {"documento de identidad"}

#: Una hoja con menos palabras de verdad que éstas es una fotocopia de la que la
#: lectura no sacó un renglón: el reverso de una cédula, una foto. Se cuentan
#: palabras y no trozos: la OCR de una fotocopia devuelve cincuenta trozos de
#: basura -- «^i2jmMn TvpíSI s iS?» -- y ninguno es una palabra.
PALABRAS_DE_UNA_HOJA_MUDA = 25
#: Lo que es una palabra: tres letras o más, con vocal, sin cuatro consonantes
#: seguidas.
_PALABRA = re.compile(r"^[A-Za-zÁÉÍÓÚÑÜáéíóúñü]{3,}$")
_SIN_VOCAL_O_TRABADA = re.compile(r"^[^AEIOUÁÉÍÓÚaeiouáéíóú]+$|[^AEIOUÁÉÍÓÚaeiouáéíóú\W\d]{4,}")
#: La fotocopia de una cédula que la OCR casi no leyó todavía deja ver esto.
_CEDULA_MAL_LEIDA = re.compile(
    r"REPUBLICA\s+DE\s+COLOMBIA|REGISTRADURIA|IDENTIFICACION\s+PERSONAL"
    # El reverso: «FECHA DF NACIMIENTO», «FECHA Y LUGAR DE EXPEDICION»
    # (UPD2326302 p12, sin una sola palabra del anverso legible).
    r"|FECHA\s+D[EF]\s+NACIMIENTO|LUGAR\s+D[EF]\s+EXPEDICION"
)
#: Cómo se llama la clase de una hoja así.
HOJA_MUDA = "hoja sin texto legible"

# -- el encabezado y la frase ------------------------------------------------------

#: «ANEXOS», «ANEXOS:», «DOCUMENTOS ANEXOS», «PRUEBAS Y ANEXOS» (y «PRUEBA
#: YANEXOS», como la deja la OCR), «ANEXO:» -- el singular sólo con dos puntos:
#: «ANEXO A RECLAMO» es el título de una hoja anexa, no una lista --, con su
#: numeración de sección delante si la lleva: «5. ANEXOS», «V. ANEXOS».
_ENCABEZADO = re.compile(
    r"^\W*(?:\d{1,2}\W{1,3}|[IVX]{1,4}\W{1,3})?"
    r"(?:PRUEBAS?\s*Y\s*|DOCUMENTOS\s+)?"
    r"(?:ANEXOS|ADJUNTOS|ANEXO\s*:|ADJUNTO\s*:)"
    r"(?:\s*Y\s+PRUEBAS?)?"
    r"\s*[:.\-]?\s*(?P<resto>.*)$"
)

#: La frase que declara lo que se adjunta, al principio del renglón: «Anexo la
#: factura…», «Adjunto copia de…», «Se anexan los siguientes documentos».
_FRASE = re.compile(
    r"^\W*(?:ME\s+PERMITO\s+)?(?:ANEXO|ADJUNTO|ANEXAMOS|ADJUNTAMOS|ANEXAR|ADJUNTAR"
    r"|SE\s+ANEXAN?|SE\s+ADJUNTAN?)"
    r"\s+(?P<resto>(?:A\s+LA\s+PRESENTE\W*)?(?:LA|EL|LOS|LAS|COPIAS?|FOTOCOPIAS?|UNA?|DOS|TRES"
    r"|CUATRO|LO|\d{1,2}\s+[A-Z]|SIGUIENTES?|DOCUMENTOS?|SOPORTES?)\b.*)$"
)

#: Lo que después de la palabra dice que no es una lista: «anexo general de la
#: Resolución CREG», «anexo técnico».
_NO_ES_LISTA = re.compile(r"^\W*(?:GENERAL|TECNICO|\d+\s*[.:)\-]?\s*$)")

#: El renglón que cierra la lista: abre otra sección o es la despedida.
_CIERRA = re.compile(
    r"^\W*(?:NOTIFICACION|ATENTAMENTE|CORDIALMENTE|CORDIAL|ATT\b|FIRMA|ESPERO|AGRADEZCO"
    r"|AGRADECIENDO|DEL\s+SENOR|LAS?\s+RECIBIR|RECIBIRE|EL\s+SUSCRITO|C\.?\s?C\.?\s*(?:NO|N\W|\d)"
    r"|CC\s+\d|FUNDAMENTOS?|PETICION|PRETENSION|HECHOS|DIRECCION|EMAIL|CORREO|CELULAR"
    r"|TELEFONO|JURAMENTO|COMPETENCIA|DERECHO|CONSIDERACIONES|SOLICITUD|PROCEDENCIA|CUANTIA"
    r"|SIN\s+OTRO\s+PARTICULAR|QUEDO\s+ATENT)"
)

#: El renglón que presenta la lista sin ser parte de ella: «Téngase como tales
#: las que a continuación se relacionan:», «Documentales:».
_PRESENTA = re.compile(
    r"TENGASE|A\s+CONTINUACION|SE\s+RELACIONAN|LOS\s+SIGUIENTES|LAS\s+SIGUIENTES"
    r"|^\W*DOCUMENTA(?:LES|RIAS?)\W*$"
    # «ANEXOS como prueba», «ANEXOS LO SIGUIENTES;» (UPD2326300 p13): la frase
    # que presenta la lista, no un anexo.
    r"|^\W*(?:COMO\s+PRUEBAS?|LO\s+SIGUIENTES?|LOS?\s+SIGUIENTES?)\W*$"
)

#: Cuántas palabras tiene un renglón de prosa. Un anexo se nombra en pocas
#: palabras -- «Copia del certificado de tradición y libertad» --; un renglón
#: largo que no nombra ninguna clase y no lleva viñeta es el escrito que sigue
#: (la cita de una sentencia entre dos «ANEXOS» en UPD2326300 p13), y la
#: lista ya terminó.
PALABRAS_DE_PROSA = 10
_VINETA = re.compile(r"^\W*(?:[-•*·]|\d{1,2}[.)]|[a-z][.)])\s*", re.IGNORECASE)

#: Lo que remite a otra parte del escrito en vez de enumerar.
_SIN_DETALLE = re.compile(
    r"QUE\s+RELACION|RELACIONAD|\bPRUEBAS\b|LO\s+(?:ANUNCIADO|ENUNCIADO|RELACIONADO)"
    r"|LOS\s+DOCUMENTOS\s+(?:QUE|MENCIONADOS|CITADOS)|LO\s+ANTERIOR"
)

#: Cuántos renglones puede tener una lista. Más que esto ya no es una lista,
#: es la lectura que no encontró dónde parar.
RENGLONES_DE_UNA_LISTA = 12

#: Cuántos de una clase dice el renglón: «dos (2) facturas», «3 fotografías».
_NUMEROS = {"UN": 1, "UNA": 1, "DOS": 2, "TRES": 3, "CUATRO": 4, "CINCO": 5, "SEIS": 6}
_CANTIDAD = re.compile(r"\((\d{1,2})\)|^\W*(?:COPIA\s+DE\s+)?(\d{1,2}|UNA?|DOS|TRES|CUATRO|CINCO|SEIS)\s+[A-Z]")


def plano(texto: str) -> str:
    """Mayúsculas y sin tildes, conservando los renglones."""
    sin_tildes = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.upper()


@dataclass(frozen=True, slots=True)
class AnexoDeclarado:
    """Un renglón de la lista, como lo escribió el cliente y como se busca."""

    #: Lo que dice el renglón, limpio de viñetas: «Contrato de arrendamiento».
    texto: str
    #: La clase con que se busca en las hojas, o ``None`` si no se reconoce.
    clase: str | None
    #: Cuántos dice: «dos (2) facturas» son dos.
    cantidad: int = 1
    #: Si en su mismo renglón alguien escribió a mano -- en ventanilla, al
    #: radicar -- que no se aportó: «No aporta documento» (UPD2326315 p2).
    anotado_no_aporta: bool = False


#: Lo que se escribe al lado de un anexo que no llegó, cuando la lectura lo deja
#: legible: «no aporta documento», «no anexa», «no allega».
_NO_APORTA = re.compile(
    r"\bN[O0]\s+(?:LO\s+|LA\s+)?(?:APORTA|ANEXA|ADJUNTA|ALLEGA|PRESENTA|TRAE|ENTREGA)\w*"
)
#: El rastro de la letra a mano en la lectura de la máquina: una minúscula
#: seguida de una mayúscula dentro de una palabra -- «fJO» --, que ninguna
#: palabra impresa tiene.
_LETRA_A_MANO = re.compile(r"[a-záéíóúñ][A-ZÁÉÍÓÚÑ]")


def sin_la_anotacion(texto: str) -> tuple[str, bool]:
    """El renglón sin lo que la mano le agregó al lado, y si decía que no se aportó.

    Lo pidió el operador: «en el anexo dice, relacionado en la misma línea, que
    no aporta… enséñale a razonar al bot para que sepa que ese documento está en
    el anexo mas no aporta». Dos maneras de verlo:

    * La lectura dejó la frase: «Copia de contrato de arrendamiento NO APORTA
      DOCUMENTO».
    * La lectura dejó el rastro de la letra a mano al final del renglón impreso
      -- «Copia de contrato de arrendamiento fJO O-» --. Qué dice no se sabe; que
      alguien anotó algo al lado de ese anexo, sí. Quien decide si eso es un
      «no aporta» es la verificación: sólo si el anexo, además, no aparece.
    """
    hallado = _NO_APORTA.search(plano(texto))
    if hallado is not None:
        return texto[: hallado.start()].rstrip(" -.,;:"), True
    palabras = texto.split()
    ruido: list[str] = []
    while palabras:
        ultima = palabras[-1]
        limpia = ultima.strip("-.,;:()'\"")
        if len(limpia) <= 2 or _LETRA_A_MANO.search(limpia):
            ruido.insert(0, ultima)
            palabras.pop()
            continue
        break
    if palabras and any(_LETRA_A_MANO.search(r) for r in ruido):
        return " ".join(palabras), True
    return texto, False


@dataclass(frozen=True, slots=True)
class ListaDeAnexos:
    """La lista de anexos de una página."""

    #: El renglón donde empieza: «ANEXOS», «Anexo la factura del mes…».
    encabezado: str
    anexos: list[AnexoDeclarado] = field(default_factory=list)
    #: Si remite a otra parte -- «los documentos que relacioné en las
    #: pruebas» -- en vez de enumerar.
    sin_detalle: bool = False

    @property
    def cantidad(self) -> int:
        return sum(anexo.cantidad for anexo in self.anexos)


def clase_del_renglon(renglon: str) -> str | None:
    """La clase de anexo que nombra un renglón: la primera que aparece en él."""
    texto = plano(renglon)
    hallazgos = [
        (hallado.start(), clase)
        for clase, nombre, _ in _CLASES
        if (hallado := nombre.search(texto)) is not None
    ]
    return min(hallazgos)[1] if hallazgos else None


def _limpio(renglon: str) -> str:
    """Sin viñetas, numeración, conjunción ni punto final: «Factura de cobro»."""
    texto = re.sub(r"^\W*(?:\d{1,2}|[a-zA-Z])?[.)\-•*]\s+", "", renglon.strip())
    texto = re.sub(r"^\W*(?:[YyEe]\s+)", "", texto)
    texto = re.sub(r"^[\W_]+|[\W_]+$", "", texto)
    return re.sub(r"\s+", " ", texto)


def _letras(texto: str) -> int:
    return sum(1 for palabra in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{2,}", texto))


def _cantidad(renglon: str) -> int:
    hallada = _CANTIDAD.search(plano(renglon))
    if hallada is None:
        return 1
    valor = hallada.group(1) or hallada.group(2)
    numero = int(valor) if valor.isdigit() else _NUMEROS.get(valor, 1)
    return numero if 1 <= numero <= 20 else 1


def _partes(renglon: str) -> list[str]:
    """Un renglón que nombra varias cosas, partido en cada una.

    «la factura del mes, y la cédula de ciudadanía» son dos; «certificado de
    libertad y tradición» es uno. Se parte por punto y coma, coma y «y», y se
    vuelve a juntar el trozo que no nombra ninguna clase con el anterior: era
    parte de su descripción.
    """
    trozos = re.split(r";|,|\s+[YyEe]\s+(?=(?:la|el|los|las|copias?|fotocopias?|una?)\b)", renglon, flags=re.IGNORECASE)
    partes: list[str] = []
    for trozo in trozos:
        if not trozo.strip():
            continue
        if partes and clase_del_renglon(trozo) is None:
            partes[-1] = f"{partes[-1]}, {trozo.strip()}"
        else:
            partes.append(trozo.strip())
    return partes


def _anexos_de(renglones: list[str]) -> tuple[list[AnexoDeclarado], bool]:
    anexos: list[AnexoDeclarado] = []
    sin_detalle = False
    for renglon in renglones:
        for parte in _partes(renglon):
            texto = _limpio(parte)
            if _letras(texto) < 1:
                continue
            texto, anotado = sin_la_anotacion(texto)
            clase = clase_del_renglon(texto)
            if clase is None and _SIN_DETALLE.search(plano(texto)):
                sin_detalle = True
                continue
            anexos.append(
                AnexoDeclarado(
                    texto=texto, clase=clase, cantidad=_cantidad(texto), anotado_no_aporta=anotado
                )
            )
    return anexos, sin_detalle


def _sigue_la_oracion(renglones: list[str], i: int) -> bool:
    """Si el renglón ``i`` continúa la oración del anterior: empieza en
    minúscula y el anterior acaba en letra o en coma."""
    actual = renglones[i].lstrip()
    anterior = next((r.rstrip() for r in reversed(renglones[:i]) if r.strip()), "")
    return bool(actual[:1].islower() and anterior and (anterior[-1].isalpha() or anterior[-1] == ","))


def leer_lista_de_anexos(texto: str) -> ListaDeAnexos | None:
    """La lista de anexos que declara la página, o ``None`` si no declara.

    Si declara más de una -- un escrito que enumera en «PRUEBAS» y otra vez en
    «ANEXOS» -- se juntan.
    """
    renglones = texto.splitlines()
    planos = [plano(renglon) for renglon in renglones]
    halladas: list[ListaDeAnexos] = []
    #: Las listas que remiten a otra parte con palabras, no por estar vacías.
    remisiones: list[bool] = []
    i = 0
    while i < len(renglones):
        encabezado = _ENCABEZADO.match(planos[i])
        frase = None if encabezado else _FRASE.match(planos[i])
        if encabezado is None and frase is None:
            i += 1
            continue
        hallado = encabezado or frase
        resto_plano = hallado.group("resto")
        if frase is not None and _NO_ES_LISTA.match(resto_plano):
            i += 1
            continue
        if frase is not None and _sigue_la_oracion(renglones, i):
            # «…evidenciamos que al mismo / anexo el Certificado de Tradición,
            # por tanto, nos debe aportar dicho»: el salto de renglón dejó el
            # verbo al principio, pero es la mitad de una oración de la carta
            # de la empresa, no un cliente que declara (UPD2326503 p7).
            i += 1
            continue
        # Lo que sigue al encabezado en su mismo renglón, con la grafía original.
        corte = len(renglones[i]) - len(resto_plano)
        presenta = _PRESENTA.search(resto_plano) and clase_del_renglon(resto_plano) is None
        lista = [renglones[i][corte:]] if resto_plano.strip() and not presenta else []
        j = i + 1
        sigue_otro_encabezado = False
        while j < len(renglones) and len(lista) < RENGLONES_DE_UNA_LISTA:
            actual = planos[j]
            if not actual.strip():
                j += 1
                continue
            if _CIERRA.match(actual) or _ENCABEZADO.match(actual):
                sigue_otro_encabezado = bool(_ENCABEZADO.match(actual))
                break
            if _PRESENTA.search(actual) and clase_del_renglon(actual) is None:
                j += 1
                continue
            if (
                len(actual.split()) >= PALABRAS_DE_PROSA
                and clase_del_renglon(actual) is None
                and not _VINETA.match(renglones[j])
            ):
                break
            if _letras(actual) < 2 and not clase_del_renglon(actual):
                # Basura de la lectura: un sello, una firma.
                break
            # La frase sigue en los renglones que la continúan: «Y la cédula de
            # ciudadanía». Un renglón que no nombra nada ya es otra cosa.
            if (
                frase is not None
                and not re.match(r"^\W*(?:Y|E|-|•|\*|\d{1,2}[.)])\s", actual)
                and clase_del_renglon(actual) is None
            ):
                break
            lista.append(renglones[j])
            j += 1
        anexos, sin_detalle = _anexos_de(lista)
        remisiones.append(sin_detalle)
        if frase is not None and not anexos and not sin_detalle:
            # «Anexo la presente…» sin nada que se reconozca: no era una lista.
            i += 1
            continue
        if encabezado is not None and not anexos and not sin_detalle and sigue_otro_encabezado:
            # «ANEXOS» y en el renglón siguiente «ANEXOS como prueba»: la misma
            # sección escrita dos veces, no una lista que remite a otra parte.
            i = j
            continue
        if anexos or sin_detalle or encabezado is not None:
            halladas.append(
                ListaDeAnexos(
                    encabezado=_limpio(renglones[i]) or renglones[i].strip(),
                    anexos=anexos,
                    sin_detalle=sin_detalle or (encabezado is not None and not anexos),
                )
            )
        i = max(j, i + 1)
    if not halladas:
        return None
    anexos = [anexo for lista in halladas for anexo in lista.anexos]
    con_anexos = [lista for lista in halladas if lista.anexos]
    return ListaDeAnexos(
        # El encabezado de la lista que enumera, si alguna enumera: «ANEXOS LO
        # SIGUIENTES», no el «ANEXOS» vacío que lo precedía.
        encabezado=(con_anexos or halladas)[0].encabezado,
        anexos=anexos,
        # Un encabezado vacío sólo dice «sin detalle» si ninguna lista de la
        # página enumera nada; la remisión explícita («los documentos que
        # relacioné en las pruebas») lo dice siempre.
        sin_detalle=any(lista.sin_detalle for lista in halladas if lista.anexos)
        or (not anexos and any(lista.sin_detalle for lista in halladas))
        or any(explicita for explicita in remisiones),
    )


def clase_de_la_hoja(texto: str) -> str | None:
    """Qué anexo es una hoja, leída por sí misma: la que reconoce, la muda, o ``None``."""
    if es_cedula(texto):
        return "documento de identidad"
    todo = plano(texto)
    cabeza = todo[:CABEZA]
    # Lo que la hoja dice ser en su cabecera manda sobre lo que menciona en el
    # cuerpo: «CONTRATO DE ARRENDAMIENTO DE VIVIENDA URBANA» arriba es un
    # contrato aunque más abajo cite la nomenclatura catastral del inmueble
    # (UPD2326310 p6). Si la cabecera no dice nada, se mira el resto.
    en_la_cabeza = [
        (hallado.start(), clase)
        for clase, _, reconoce in _CLASES
        if reconoce is not None and (hallado := reconoce.search(cabeza))
    ]
    if en_la_cabeza:
        return min(en_la_cabeza)[1]
    for clase, _, reconoce in _CLASES:
        if reconoce is not None and clase not in _EN_LA_CABEZA and reconoce.search(todo):
            return clase
    if palabras_reales(texto) < PALABRAS_DE_UNA_HOJA_MUDA:
        return "documento de identidad" if _CEDULA_MAL_LEIDA.search(todo) else HOJA_MUDA
    return None


def palabras_reales(texto: str) -> int:
    """Cuántas palabras de verdad trae el texto, sin la basura de la OCR."""
    limpios = (trozo.strip(".,;:()«»\"'") for trozo in texto.split())
    return sum(
        1 for palabra in limpios if _PALABRA.match(palabra) and not _SIN_VOCAL_O_TRABADA.search(palabra)
    )


def corresponde(declarada: str | None, hallada: str | None) -> bool:
    """Si la hoja hallada es el anexo que se declaró."""
    if declarada is None or hallada is None:
        return False
    if declarada == hallada:
        return True
    # La hoja muda puede ser la fotocopia de lo que la lectura no alcanzó.
    return hallada == HOJA_MUDA and declarada in {"documento de identidad", "fotografías"}
