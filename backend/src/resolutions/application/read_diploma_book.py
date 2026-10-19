"""Read a whole book of diploma registrations, one record per page.

The same cascade the resolution splitter uses, for a different question. The
embedded text layer answers most pages for nothing; a page that leaves a field
unread is re-rendered and passed to OCR, and only what was actually missing is
taken from that second reading. On the three printed books measured, the text
layer alone left 57 of 1 084 pages incomplete and OCR closed all but a handful.
"""

from __future__ import annotations

import inspect
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from ..domain.diploma import (
    CriterioDeCorte,
    DiplomaRecord,
    FormaDeLaCara,
    asientos_en_progresion,
    con_lo_que_dice_el_libro,
    continuaciones,
    extract_diploma,
    extract_diploma_warnings,
    forma_de_la_cara,
    lines_from_text,
    merge,
    plantilla_antigua,
    sin_avisos_de_costura,
    vueltas_por_la_tinta,
)
from ..domain.folio_manuscrito import (
    AVISO_FUERA_DE_RITMO,
    BANDA_DEL_FOLIO,
    MarcaDeFolio,
    TrazoEnEsquina,
    folio_de_la_esquina,
    folios_comprobados,
    marca_de_folio,
    marcas_en_ritmo,
)
from ..domain.page import Provenance
from .control import NullRunControl, RunControl, alguno_listo, completados, hilos
from .diagnostico import explicar
from .ports import Band, OcrEngine
from .progress import NullProgressReporter, ProgressEvent, ProgressReporter, Stage

logger = logging.getLogger(__name__)

#: Escalations are rendered larger than the classification cascade uses. These
#: are small printed captions and eight-digit identity numbers, not a heading in
#: 24 point, and at 200 dpi Tesseract loses the digits that matter.
ESCALATION_DPI = 300

#: Cuántas páginas se leen a la vez. Leer es esperar: casi tres segundos por
#: página contra el proveedor de OCR, y durante esos tres segundos este proceso
#: no hace nada. Medido sobre el libro 7 -- 398 páginas -- en serie son veinte
#: minutos de reloj y de CPU casi ninguno.
#:
#: Hilos y no procesos porque el trabajo es de espera y no de cálculo: una
#: petición HTTP y un binario externo sueltan los dos el GIL mientras tanto. El
#: rasterizado se queda fuera del pool, en el hilo que manda, porque MuPDF no
#: promete ser seguro entre hilos sobre el mismo documento: lo que viaja al pool
#: son bytes de imagen ya hechos.
LECTORES = 8

#: Cada cuántas páginas se informa durante una pasada que no lee nada. Ni por
#: página -- serían cuatrocientos avisos para cuatro segundos de trabajo -- ni
#: al final, que es lo que dejaba la pantalla en blanco.
_CADA_CUANTAS_SE_AVISA = 25

#: Cuántos caracteres del principio de la página entera se guardan para sacar
#: de ahí el folio de la esquina. La esquina es lo primero que el OCR devuelve
#: -- "2/V # LA REPUBLICA DE COLOMBIA..." en la página 3 del libro 7 -- así que
#: con la cabecera basta, y quedarse con toda la página haría que una fecha del
#: cuerpo ("12/05") pasara por folio.
_CABECERA_CHARS = 120

#: Cuántas páginas se releen con el motor local antes de decidir si sirve de
#: algo seguir. En un libro de fichas mecanografiadas Tesseract cierra los
#: huecos que la capa de texto dejó; en un libro de 1982 con todo manuscrito
#: vuelve a leer lo que el escáner ya leyó y no recupera un solo campo en las
#: 398 páginas. Se prueba con las primeras y se sigue sólo si recuperó algo:
#: medido, son 110 segundos por libro que se dejan de gastar en no leer nada.
_MUESTRA_LOCAL = 16

#: Cuánto tiempo sin rechazos del proveedor hace falta para volver a ampliar la
#: ventana de lecturas en vuelo después de haberla estrechado por un 429.
_TREGUA_TRAS_RECHAZO = 60.0

#: A cuánto se rasteriza la esquina del folio. Es una anotación a mano de tres
#: o cuatro caracteres en una banda estrecha, así que se pide más resolución que
#: para la página entera y aun así la imagen pesa una fracción: son cuatro
#: centímetros de papel, no una hoja.
FOLIO_DPI = 300

#: Cuántas páginas viajan juntas en una petición al motor de pago.
#:
#: El proveedor acepta un documento entero y devuelve una entrada por página, de
#: modo que las pendientes se encuadernan en un PDF de usar y tirar y se mandan
#: de una vez. Donde iban cuatrocientas peticiones ahora van unas veinte.
#:
#: Doce y no cincuenta porque la tanda es también la unidad de pérdida: si una
#: petición se cae del todo, lo que se queda sin texto es la tanda entera. Doce
#: páginas a 300 dpi son unos ocho megas de PDF, que el proveedor acepta de
#: sobra, y son también el grano con que la pantalla ve avanzar el trabajo: con
#: tandas de cincuenta la cinta daría cuatro saltos en todo el libro.
TAMANO_DE_TANDA = 12

#: Lo que un libro de registro escribe cuando un diploma se anuló. Aparece en la
#: misma esquina y en la vuelta de la hoja -- en la página 224 del libro 7, sin
#: ir más lejos --, así que quien lee esa esquina se lo encuentra gratis y sería
#: absurdo tirarlo: que un registro esté anulado es lo primero que alguien
#: necesita saber de él.
_ANULADA = ("ANULADA", "ANULADO")


def _dice_anulada(texto: str) -> bool:
    limpio = (texto or "").upper()
    return any(palabra in limpio for palabra in _ANULADA)


@dataclass(slots=True)
class BookReadingStats:
    """Where the readings came from, counted rather than assumed."""

    pages: int = 0
    from_text_layer: int = 0
    escalated: int = 0
    recovered_by_ocr: int = 0
    incomplete: list[int] = field(default_factory=list)
    failures: dict[int, str] = field(default_factory=dict)
    #: Caras que no se leyeron porque pertenecen a la hoja anterior. No es un
    #: fallo ni un hueco: es el ahorro, y va al informe para que se vea. Una
    #: vuelta no nombra ningún archivo ni abre ninguna fila del inventario, así
    #: que leerla sería pagar por un dato que nadie va a mirar.
    no_leidas: list[int] = field(default_factory=list)
    #: Cuántas cédulas recuperó el rastreo local que la lectura normal había
    #: dejado escapar. Son páginas que iban camino del motor de pago y no
    #: llegaron: el ahorro se mide aquí.
    recuperadas_sin_pagar: int = 0
    #: Caras que abren documento y se quedaron **sin cédula y sin nombre**.
    #:
    #: Es la cuenta que hace comprobable la promesa de que ningún documento
    #: salga sin identidad. No siempre se puede cumplir -- hay papel que no
    #: se deja leer, y libros de los años setenta que no traen cédula en
    #: absoluto -- pero sí se puede decir cuántos y cuáles, que es la
    #: diferencia entre una entrega revisable y una que hay que creerse.
    sin_identidad: list[int] = field(default_factory=list)
    #: Cuántas páginas acabó respondiendo cada peldaño. No es lo mismo que
    #: ``escalated``, que cuenta los intentos: una escalada que falla deja en
    #: pie la lectura de la capa de texto, y aquí se cuenta esa.
    provenance: dict[str, int] = field(default_factory=dict)
    #: Lo que la repesca recuperó después de la lectura entera: cédulas y
    #: nombres leídos en franjas ampliadas, y caras releídas sueltas. Es la
    #: cuenta de lo que la tanda se había dejado.
    repescadas: dict[str, int] = field(default_factory=dict)
    #: Lo que el motor de pago contestó de cada cara, tal cual. No viaja en el
    #: informe -- son cientos de páginas de texto -- pero se deja junto a la
    #: entrega, para que quien revise una hoja pueda ver qué leyó la IA de
    #: ella sin volver a pagarla.
    lecturas: dict[int, str] = field(default_factory=dict, repr=False)

    def as_dict(self) -> dict[str, object]:
        return {
            "pages": self.pages,
            "from_text_layer": self.from_text_layer,
            "escalated": self.escalated,
            "recovered_by_ocr": self.recovered_by_ocr,
            "provenance": dict(self.provenance),
            "incomplete": list(self.incomplete),
            "no_leidas": list(self.no_leidas),
            "recuperadas_sin_pagar": self.recuperadas_sin_pagar,
            "sin_identidad": list(self.sin_identidad),
            "repescadas": dict(self.repescadas),
            "failures": {str(page): error for page, error in sorted(self.failures.items())},
        }


class _CintaEnOrden:
    """Pinta la cinta de páginas según se resuelven, y en el orden del libro.

    Existe porque leer por tandas rompió la fluidez de la pantalla. Antes, con
    una petición por página, cada lectura que volvía pintaba su casilla; al
    agrupar las páginas en tandas, el anuncio se hacía al final y la cinta
    pasaba todo el trabajo en blanco para llenarse de golpe. El trabajo iba
    igual de bien, pero desde fuera era indistinguible de estar colgado.

    Pinta **en orden y sólo hasta donde todo esté resuelto**. Las lecturas
    vuelven desordenadas -- son varias en vuelo --, y una casilla pintada antes
    que la de su izquierda no informa de por dónde va el trabajo: parece un
    salteado. Así que se guarda y se pinta cuando le llega el turno.
    """

    def __init__(self, lector, records, stats) -> None:
        self._lector = lector
        self._records = records
        self._stats = stats
        self._siguiente = 0

    def avanzar(self, resueltos: dict, procedencias: dict, pendientes: set[int]) -> None:
        """Pinta lo que se pueda pintar sin saltarse ninguna casilla."""
        while self._siguiente < len(self._records):
            record = self._records[self._siguiente]
            pagina = record.page_number
            # Una cara que nadie iba a leer está decidida desde el principio; una
            # que sí, hasta que no vuelva su lectura no se sabe de dónde salió.
            if pagina in pendientes and pagina not in procedencias:
                return
            final = resueltos.get(pagina, record)
            self._lector._anunciar_pagina(
                final,
                procedencias.get(pagina, Provenance.TEXT_LAYER),
                len(self._records),
                self._stats,
            )
            self._siguiente += 1

    def cerrar(self, resueltos: dict, procedencias: dict) -> None:
        """Y al terminar, lo que quede, se haya resuelto o no."""
        self.avanzar(resueltos, procedencias, set())


class ReadDiplomaBook:
    """One book in, one record per page out."""

    def __init__(
        self,
        ocr: OcrEngine | None = None,
        progress: ProgressReporter | None = None,
        escalation_dpi: int = ESCALATION_DPI,
        control: RunControl | None = None,
        workers: int = LECTORES,
        criterio: CriterioDeCorte = CriterioDeCorte.PAGINA,
        rastreo=None,
        mosaico=None,
        mosaico_de_cedulas=None,
        mosaico_de_fechas=None,
        lectura_de_ahorro: bool = False,
    ) -> None:
        self._ocr = ocr
        self._progress = progress or NullProgressReporter()
        self._dpi = escalation_dpi
        self._control = control or NullRunControl()
        self._workers = max(1, workers)
        #: Con qué se va a cortar el libro, que es lo que decide **qué hay que
        #: leer y hasta dónde**. Leer no es un fin en sí: es lo que hace falta
        #: para poder repartir y nombrar, y eso cambia con el criterio.
        self._criterio = criterio
        #: Quién da la segunda mirada local a una cédula que no salió, antes
        #: de gastar en la IA. ``None`` es no darla: el rastreo cuesta tiempo
        #: de CPU y no tiene sentido cuando nadie va a mirar esa cédula.
        self._rastreo = rastreo
        #: Quien lee los nombres de varias caras en una sola imagen. Cuando
        #: lo hay, una cara cuyo nombre saque el mosaico **no llega a leerse
        #: entera**: es la renuncia que el operador acepto al elegir la
        #: lectura de ahorro, y es de donde sale el factor diez.
        self._mosaico = mosaico
        #: Quien lee la cédula de varias caras en franjas ampliadas. Es la
        #: repesca de lo que la lectura entera dejó sin cédula creíble: a
        #: página entera el motor de pago se come dígitos del número
        #: manuscrito, y en la franja recortada los lee casi todos.
        self._mosaico_de_cedulas = mosaico_de_cedulas
        #: Quien lee la fecha manuscrita de varias caras en el pie del diploma.
        #: Es la repesca de lo que la lectura entera dejó sin fecha: la fecha
        #: va escrita a mano en la fórmula "a los X días del mes de Y de mil
        #: novecientos Z" y Tesseract no la lee; el motor de pago sí.
        self._mosaico_de_fechas = mosaico_de_fechas
        #: Si el operador eligió pagar por la franja y no por la hoja. Entonces
        #: el mosaico de nombres **sustituye** a la lectura entera en vez de
        #: repescar lo que ésta dejó, y nada se lee suelto.
        self._lectura_de_ahorro = lectura_de_ahorro
        #: En qué formato se rasteriza lo que va al motor de pago, cuando la
        #: fuente sabe elegirlo. Se decide al abrir el libro.
        self._formato_de_pago: str | None = None

    def execute(
        self, source, paginas: Sequence[int] | None = None
    ) -> tuple[list[DiplomaRecord], BookReadingStats]:
        """Lee el libro entero o, con ``paginas``, sólo esas caras.

        Leer sólo unas caras es retomar una entrega a medias: las demás ya
        están en el destino y volver a leerlas -- y a pagarlas -- no aporta
        nada. Cada registro conserva su número de página del libro, que es el
        que nombra el archivo cuando no hay cédula ni nombre y el que ordena
        el FUID junto a lo ya entregado.
        """
        numeros = (
            sorted({n for n in paginas if 1 <= n <= source.page_count})
            if paginas
            else list(range(1, source.page_count + 1))
        )
        stats = BookReadingStats(pages=len(numeros))
        #: Que caras traian capa de texto. Se llena durante la primera
        #: pasada, que las lee de todos modos.
        self._con_texto: set[int] = set()
        #: Qué parte del formulario trae cada cara, de su capa de texto.
        self._formas: dict[int, FormaDeLaCara] = {}
        self._formato_de_pago = _formato_para_la_red(source)
        self._report(ProgressEvent(stage=Stage.OPENED, page_count=len(numeros)))

        # Primero lo que no espera a nadie: la esquina y la capa de texto de
        # cada página, que juntas cuestan una centésima de segundo. De aquí sale
        # ya el reparto del libro; lo que falta después es sólo ponerle nombre a
        # cada documento.
        records: list[DiplomaRecord] = []
        for hechas, page_number in enumerate(numeros, start=1):
            self._control.check()
            records.append(self._de_la_capa(source, page_number, stats))
            # Esta pasada dura cuatro segundos en un libro de cuatrocientas
            # páginas, pero callarla dejaba la pantalla diciendo "reconociendo"
            # sin un solo número mientras el trabajo ya estaba midiendo folios.
            if hechas % _CADA_CUANTAS_SE_AVISA == 0 or hechas == len(numeros):
                self._report(
                    ProgressEvent(
                        stage=Stage.IDENTIFYING,
                        page_count=len(numeros),
                        detail="midiendo el folio de cada esquina",
                        done=hechas,
                        total=len(numeros),
                    )
                )

        # Y con el libro entero leído, lo que sólo se sabe al final: su ritmo.
        # Una esquina se mide sola, pero si este libro va de dos en dos -- folio,
        # vuelta, folio, vuelta -- entonces una cara marcada justo detrás de otra
        # marcada no es un folio, sea lo que sea lo que haya escrito ahí.
        records = self._en_ritmo(records)

        # Lo primero que devuelve el OCR de cada página entera, para sacar de ahí
        # el folio de la esquina sin pagar una segunda lectura.
        self._cabeceras: dict[int, str] = {}

        # Y aquí lo que sí espera. Las páginas que la capa de texto no resolvió
        # se rasterizan en este hilo y se leen en el pool: mientras el proveedor
        # contesta por ocho de ellas, éste va preparando las ocho siguientes.
        # Qué caras se puede uno ahorrar, que depende del criterio de corte.
        # Cortando por folio, la vuelta de una hoja no nombra ningún archivo
        # -- el nombre sale de la cara que abre -- ni abre fila del inventario,
        # así que pagar por leerla es pagar por un dato que nadie va a mirar: en
        # un libro foliado hoja a hoja, la mitad. Cortando por cédula no se
        # salta ninguna, porque la señal que manda hay que leerla.
        records = self._escalar(source, records, stats, vueltas_por_la_tinta(records))

        # Y con el reparto ya decidido, el número. Va al final y no durante la
        # lectura de cada página porque comprobarlo exige el libro entero: un
        # folio suelto no se puede contrastar con nada, y la progresión sí.
        records = self._folios_de_las_esquinas(source, records, stats)

        # Y lo que sólo el libro entero confirma: el número de libro de la cara
        # que no lo dejó leer y el título mal leído que se repite bien en otras.
        records = con_lo_que_dice_el_libro(records)
        if self._criterio is CriterioDeCorte.PAGINA:
            records = asientos_en_progresion(records)

        # Cortando cara a cara no se une nada, así que los avisos que hablan
        # de unir esta hoja a la anterior no describen ninguna decisión: son
        # de otro criterio, y mandaban a revisión hojas que salieron bien.
        if self._criterio is CriterioDeCorte.PAGINA:
            records = [sin_avisos_de_costura(record) for record in records]

        # Dónde empieza cada diploma, por lo impreso: la cara que no trae nada
        # que abra un formulario continúa el anterior. Va al final, después de
        # cualquier relectura, para que ninguna mezcla de lecturas lo borre.
        records = self._marcar_continuaciones(records)

        # Y lo último, con el libro entero leído: cuántas unidades se quedaron
        # sin cédula y sin nombre. No cambia nada de lo leído; lo declara.
        self._contar_sin_identidad(records, stats)

        # Sin DONE: leer no es terminar. Quien anuncia el final es quien sabe
        # qué queda por hacer después, que es el trabajo y no el lector.
        return records, stats

    def _marcar_continuaciones(self, records: list[DiplomaRecord]) -> list[DiplomaRecord]:
        """Las caras que continúan el diploma anterior, marcadas y declaradas.

        Lo dictó el operador: el encabezado abre diploma, y la cara sin él es
        un diploma dividido. Se declara en revisión porque juntar dos caras es
        la decisión que, si se equivoca, mete dos graduados en un archivo.
        """
        if self._criterio is not CriterioDeCorte.PAGINA:
            # Los otros criterios deciden la unión por su propia señal.
            return records
        sin_forma = FormaDeLaCara(con_texto=False, abre=False, cuerpo=False, cierra=False)
        formas = [self._formas.get(record.page_number, sin_forma) for record in records]
        siguen = continuaciones(formas)
        if not siguen:
            return records
        return [
            replace(
                record,
                continuacion=True,
                warnings=[
                    *record.warnings,
                    "no trae el encabezado ni ninguna leyenda que abra un diploma: "
                    "se unió al diploma anterior como su continuación; revísela",
                ],
            )
            if indice in siguen
            else record
            for indice, record in enumerate(records)
        ]

    def _en_ritmo(self, records: list[DiplomaRecord]) -> list[DiplomaRecord]:
        """Los mismos registros, con las caras que rompen el compás unidas.

        El aviso se añade a los que ya traía la página en vez de recalcularlos:
        una página que no se dejó leer lleva escrito por qué, y perder eso para
        poner esto otro cambiaría un motivo de revisión por otro en lugar de
        sumarlos.
        """
        marcas = [record.folio_mark or MarcaDeFolio.SIN_MEDIR for record in records]
        ajustadas = marcas_en_ritmo(marcas)
        if ajustadas == marcas:
            return records
        logger.info(
            "el libro va de dos en dos; %d caras marcadas fuera de ritmo se unen "
            "a la anterior",
            sum(
                1
                for vieja, nueva in zip(marcas, ajustadas, strict=True)
                if vieja is not nueva
            ),
        )
        return [
            record
            if nueva is vieja
            else replace(
                record, folio_mark=nueva, warnings=[*record.warnings, AVISO_FUERA_DE_RITMO]
            )
            for record, vieja, nueva in zip(records, marcas, ajustadas, strict=True)
        ]

    def _de_la_capa(
        self, source, page_number: int, stats: BookReadingStats
    ) -> DiplomaRecord:
        """Lo que la página dice de sí misma sin que nadie la lea: gratis.

        La esquina primero, y aunque la lectura fracase: si la hoja abre un
        registro o es la vuelta de la anterior lo dice el folio escrito a mano,
        y eso se sabe sin entender una palabra de lo que hay impreso. Una página
        que no se deja leer sigue sabiendo decir dónde va.
        """
        marca = self._marca_de_folio(source, page_number)
        try:
            renglones = source.lines_of(page_number)
            # Que esta cara traiga o no capa de texto se sabe aqui y gratis, y
            # decide despues si vale la pena rastrearle la cedula: el rastreo se
            # orienta por el rotulo impreso, y una pagina sin texto no tiene
            # ninguno que seguir. Averiguarlo mas tarde obligaria a volver a
            # extraer la pagina, que en un libro escaneado es un segundo por
            # cara -- tres minutos de reloj sobre un libro de cuatrocientas.
            if renglones:
                self._con_texto.add(page_number)
            # Qué parte del formulario trae: decide, con el libro entero
            # leído, si esta cara abre diploma o continúa el anterior.
            self._formas[page_number] = forma_de_la_cara(renglones)
            record = extract_diploma(renglones, page_number)
            # En las plantillas antiguas el asiento va escrito a mano y la capa
            # sólo devuelve ruido: se deja vacío para quien lo sepa leer.
            if plantilla_antigua(renglones):
                record = replace(record, folio=None, registered_folio=None)
        except Exception as error:  # noqa: BLE001 - contained to this page
            logger.warning("no se pudo leer la página %s", page_number, exc_info=True)
            stats.failures[page_number] = explicar(error)
            return DiplomaRecord(
                page_number=page_number,
                folio_mark=marca,
                warnings=[f"la página no pudo procesarse: {error}"],
            )
        # Los avisos se recalculan con la marca ya puesta: una hoja sin nada con
        # qué situarla sólo es una costura dudosa si además nadie pudo medir su
        # esquina, y eso no se sabe hasta aquí.
        return extract_diploma_warnings(replace(record, folio_mark=marca))

    def _escalar(
        self,
        source,
        records: list[DiplomaRecord],
        stats: BookReadingStats,
        vueltas_medidas: set[int],
    ) -> list[DiplomaRecord]:
        """Relee lo que la capa de texto no resolvió, y sólo donde hace falta.

        Tres filtros, en el orden en que ahorran:

        1. **Qué páginas.** Sólo las que abren documento. La vuelta de una hoja
           no nombra archivo ni abre fila del inventario.
        2. **Qué páginas de ésas.** Sólo las que dejaron algo sin leer o se
           contradicen a sí mismas -- el folio del encabezado contra el del pie,
           un nombre con un dígito dentro --, porque en las dos hay algo que
           verificar.
        3. **Con qué motor.** Cuando el trabajo tiene los dos, Tesseract lo
           intenta primero y gratis, y al de pago le llega sólo lo que el de
           casa no consiguió.

        La procedencia que se cuenta es la del peldaño que produjo lo que se
        conserva, no la del último que se intentó: una escalada que falla deja
        en pie la lectura de la capa de texto, y decir "OCR" ahí sería contar el
        intento en vez del resultado.
        """
        for record in records:
            if self._resuelto(record):
                stats.from_text_layer += 1

        pendientes = [
            record for record in records if self._hay_que_leerla(record, vueltas_medidas)
        ]
        vueltas = [
            record
            for record in records
            if not self._resuelto(record)
            and not self._hay_que_leerla(record, vueltas_medidas)
        ]
        if vueltas:
            stats.no_leidas.extend(record.page_number for record in vueltas)
            logger.info(
                "%d caras pertenecen a la hoja anterior y no se leen: no nombran "
                "ningún archivo ni abren ninguna fila",
                len(vueltas),
            )

        if self._ocr is None or not pendientes:
            stats.incomplete.extend(record.page_number for record in pendientes)
            self._anunciar_paginas(records, {}, stats)
            return records

        stats.escalated += len(pendientes)
        if self._sabe_colaborar():
            return self._escalar_en_dos_fases(source, records, pendientes, stats)
        return self._escalar_una_a_una(source, records, pendientes, stats)

    def _resuelto(self, record: DiplomaRecord) -> bool:
        """Si esta cara ya dio lo que hacía falta, y por tanto no hay que pagarla.

        **Depende del criterio, y ahí está el ahorro.**

        Cortando por folio hace falta todo lo que va al FUID -- nombre, título,
        fecha, libro --, de modo que cualquier hueco justifica releer.

        Cortando por cédula, en cambio, lo único que decide dónde termina cada
        documento y cómo se llama es **el número de cédula**. Una cara cuya
        cédula ya se sostiene está resuelta aunque no se haya leído su fecha,
        así que no se le pide nada al motor de pago. Es exactamente lo que
        pidió el operador: que la OCR busque la cédula y sólo si no la capta, o
        sale mal, se pase a la IA.

        Lo que falte de las demás columnas se escribe N/A en el inventario, que
        es lo que manda el instructivo donde el papel no se dejó leer, y no un
        dato inventado.
        """
        if self._criterio is CriterioDeCorte.PAGINA:
            # Con una de las dos basta, porque es lo único que hace falta para
            # nombrar el archivo. La cédula primero, que es única y llega antes;
            # el nombre cuando el libro no la trae.
            return record.identity_creible or record.nombre_creible
        if self._criterio is CriterioDeCorte.CEDULA:
            return record.identity_creible
        if self._criterio is CriterioDeCorte.ENCABEZADO:
            # Lo que este criterio necesita está impreso: el membrete y el
            # nombre. Con eso decide dónde corta y cómo llama al archivo, y no
            # hay nada más que preguntar.
            return record.encabezado or record.nombre_creible
        if self._criterio is CriterioDeCorte.NOMBRE_Y_CEDULA:
            # Las dos señales, porque las dos deciden. Una cara con cédula y sin
            # nombre no puede compararse con la anterior, así que se sigue
            # preguntando por ella -- y sale barato, porque el nombre viene en la
            # misma lectura que la cédula y no en una petición aparte.
            return record.identity_creible and bool(record.name)
        return not record.debe_releerse

    def _hay_que_leerla(self, record: DiplomaRecord, vueltas_medidas: set[int]) -> bool:
        """Si vale la pena gastar una lectura en esta cara.

        Cortando por folio se saltan las vueltas: no nombran ningún archivo -- el
        nombre sale de la cara que abre -- ni abren fila del inventario.

        Cortando por cédula **no se salta ninguna**, y conviene entender por qué
        no es un descuido: ahí lo que decide dónde termina un documento es la
        cédula, y la cédula hay que leerla. Saltarse una cara sería decidir sin
        mirar justo la señal que manda. Cuesta más, y es el precio declarado de
        ese criterio; lo que lo compensa es que de cada cara basta un número.
        """
        if self._resuelto(record):
            return False
        if self._criterio in (
            CriterioDeCorte.CEDULA,
            CriterioDeCorte.NOMBRE_Y_CEDULA,
            CriterioDeCorte.ENCABEZADO,
            CriterioDeCorte.PAGINA,
        ):
            return True
        return record.page_number not in vueltas_medidas

    def _sabe_colaborar(self) -> bool:
        """Si este motor distingue su peldaño gratis del de pago.

        Sólo la cascada lo hace. Un motor suelto -- Tesseract a secas, o un
        doble de una prueba -- es su propio peldaño y se le pide una vez por
        página, que es como funcionaba esto antes de que hubiera dos motores.
        """
        return hasattr(self._ocr, "read_local") and hasattr(self._ocr, "read_many_remote")

    def _escalar_en_dos_fases(
        self,
        source,
        records: list[DiplomaRecord],
        pendientes: list[DiplomaRecord],
        stats: BookReadingStats,
    ) -> list[DiplomaRecord]:
        """Tesseract primero y gratis; al de pago, sólo lo que falte y en tandas.

        El criterio para escalar es **por campo y no por volumen de texto**, y
        es la diferencia que hace útil esta fase. Preguntar "¿salió texto?" no
        sirve en estos libros: de un diploma de 1982 Tesseract saca el
        formulario impreso entero -- "en atención a que el Señor", "le expide el
        presente Diploma" -- sin haber leído ninguno de los cinco datos que
        identifican al graduado, porque ésos están manuscritos. Medido por
        caracteres esa lectura parece buena y no escalaría jamás. Lo que se
        pregunta es si el registro quedó resuelto.

        Y la fase local se abandona en cuanto se ve que no sirve. Tesseract es
        gratis en dinero pero cuesta un cuarto de segundo por página, que en un
        libro de cuatrocientas son cien segundos de reloj; si en la muestra no
        resolvió una sola cara, lo que trajo se descarta -- esos campos habrían
        ido al FUID como si fueran datos -- y el resto va directo al de pago.
        """
        resueltos: dict[int, DiplomaRecord] = {}
        procedencias: dict[int, Provenance] = {}
        # Lo que la pantalla ve avanzar. Se le pasa a las dos fases para que
        # pinten según resuelven, en vez de dejar la cinta en blanco hasta el
        # final: con tandas de doce páginas, callarse hasta el final es doce
        # minutos de pantalla quieta sobre un trabajo que va perfectamente.
        cinta = _CintaEnOrden(self, records, stats)
        esperadas = {record.page_number for record in pendientes}

        # --- Fase gratis -----------------------------------------------------
        restantes = self._pasada_local(
            source, pendientes, resueltos, procedencias, stats, cinta, esperadas
        )

        # --- Rastreo local del campo, todavía gratis ------------------------
        tiene_lector_remoto = getattr(self._ocr, "read_remote", None) is not None
        puede_rastrear_sin_repetir = not (
            self._criterio is CriterioDeCorte.PAGINA and tiene_lector_remoto
        )
        if restantes and self._rastreo is not None and puede_rastrear_sin_repetir:
            restantes = self._rastrear(source, restantes, resueltos, procedencias, stats)
            cinta.avanzar(resueltos, procedencias, esperadas)
        elif restantes and self._criterio is CriterioDeCorte.PAGINA and tiene_lector_remoto:
            logger.info(
                "se omite el rastreo local de cédula: el OCR local ya fue probado "
                "y la lectura remota resolverá nombre y cédula sin reprocesar las caras"
            )

        # --- Los nombres en mosaico, si se eligio la lectura de ahorro ------
        if restantes and self._mosaico is not None and self._lectura_de_ahorro:
            quedan = self._por_mosaico(source, restantes, resueltos, procedencias, stats)
            # Y aqui se acaba el gasto. Elegir la lectura de ahorro es aceptar
            # que de estas caras se lee el nombre y nada mas; dejar que las que
            # el mosaico no consiguio cayeran a la lectura entera convertiria el
            # ahorro en una loteria -- medido sobre el libro de posgrados 3858081,
            # veinticuatro caras costaban diecisiete paginas en vez de tres.
            #
            # Lo que el mosaico no saco se declara en la cola de revision, que
            # es informacion util: dice exactamente que caras volver a pasar con
            # la lectura entera si hacen falta sus datos.
            if quedan:
                logger.info(
                    "el mosaico no consiguio el nombre de %d caras; con la lectura "
                    "de ahorro no se leen enteras y quedan declaradas para revision",
                    len(quedan),
                )
            restantes = []
            cinta.avanzar(resueltos, procedencias, esperadas)

        # --- Fase de pago, en tandas ----------------------------------------
        # Salvo que el criterio no pague: el del encabezado se decide sobre papel
        # impreso, y lo que el motor de casa no vea ahí no lo arregla la IA --
        # lo arregla mirar la hoja. Pedirla sería gastar por costumbre.
        if restantes and not self._criterio.paga_lectura:
            logger.info(
                "%d caras quedaron sin resolver y el criterio elegido no usa el "
                "motor de pago: se declaran para revisión",
                len(restantes),
            )
            restantes = []
        if restantes:
            self._pasada_remota(
                source,
                restantes,
                resueltos,
                procedencias,
                stats,
                len(records),
                cinta,
                esperadas,
            )

        # --- La repesca: lo que la lectura entera dejó sin identidad --------
        if self._criterio.paga_lectura and getattr(self._ocr, "read_remote", None) is not None:
            self._repescar(source, pendientes, resueltos, procedencias, stats, len(records))
            cinta.avanzar(resueltos, procedencias, esperadas)

        for record in pendientes:
            if record.page_number not in resueltos:
                stats.incomplete.append(record.page_number)
                procedencias.setdefault(record.page_number, Provenance.TEXT_LAYER)
            elif not self._resuelto(resueltos[record.page_number]):
                stats.incomplete.append(record.page_number)

        cinta.cerrar(resueltos, procedencias)
        return [resueltos.get(record.page_number, record) for record in records]

    def _repescar(
        self,
        source,
        pendientes: list[DiplomaRecord],
        resueltos: dict[int, DiplomaRecord],
        procedencias: dict[int, Provenance],
        stats: BookReadingStats,
        total: int,
    ) -> None:
        """Lo que la lectura entera dejó sin cédula o sin nombre, en franjas.

        La lectura a página entera y en tanda tiene dos fallos medidos sobre el
        libro 7, y ninguno de los dos se arregla leyendo más veces lo mismo:

        - **Se come dígitos de la cédula manuscrita**: "45425" donde el papel
          dice 45.425.748. Siete cédulas creíbles de doce caras, mandadas como
          se mandaran. En la franja del renglón "C.C. No.", recortada y
          ampliada, **diez de diez**.
        - **Se vuela el renglón manuscrito del nombre** cuando viaja en tanda:
          lo devuelve como una imagen y no como texto. Diez nombres de doce en
          tanda; en la franja bajo "en atención a que el Señor", los doce.

        Así que primero la tanda, que es barata y trae el folio, la fecha y el
        título; y después, sólo para las caras que se quedaron sin cédula o sin
        nombre creíbles, las franjas: diez caras por página facturada. Y como
        último recurso, la cara entera sola, para la que aún no tenga con qué
        nombrarse: es lo más caro por cara y lo mejor que lee, y son pocas.

        Cada pasada actúa sólo sobre el campo que le falta a la cara y nunca
        pisa un valor creíble que ya estuviera: la franja de la cédula no toca
        el nombre, y al revés.
        """
        por_pagina = {record.page_number: record for record in pendientes}

        def actual(pagina: int) -> DiplomaRecord:
            return resueltos.get(pagina, por_pagina[pagina])

        def anotar(pagina: int, **campos) -> None:
            resueltos[pagina] = extract_diploma_warnings(replace(actual(pagina), **campos))
            procedencias.setdefault(pagina, Provenance.OCR_REGION)

        if self._mosaico_de_cedulas is not None:
            # Todas las caras que pasaron por el motor de pago, y no sólo las que
            # quedaron sin cédula: la franja también **corrobora** la que la
            # página entera trajo. Hace falta, y se midió: dos corridas del
            # libro 7 dieron cédulas creíbles **distintas** para cuatro caras
            # -- 2347073 y 23089093 para la misma hoja --, y una cédula creíble
            # y equivocada nombra el archivo sin que nadie lo note. Cuesta una
            # página facturada por cada diez caras.
            caras = list(por_pagina)
            self._report(
                ProgressEvent(
                    stage=Stage.VERIFYING,
                    page_count=total,
                    detail=f"comprobando la cédula de {len(caras)} caras en franjas",
                    done=0,
                    total=len(caras),
                )
            )
            primera = self._franjas_de_cedula(source, caras)
            recuperadas = confirmadas = 0
            segunda_vuelta: list[int] = []
            for pagina in caras:
                registro = actual(pagina)
                leida = primera.get(pagina)
                if leida is None:
                    if registro.identity_creible:
                        # La de la página entera sigue sin comprobar: se le
                        # da a la franja una segunda oportunidad.
                        segunda_vuelta.append(pagina)
                    continue
                if not registro.identity_creible:
                    anotar(pagina, identity_number=leida)
                    recuperadas += 1
                elif registro.identity_number == leida:
                    confirmadas += 1
                else:
                    segunda_vuelta.append(pagina)

            # Donde la página entera y la franja no coinciden manda la
            # mayoría, y para que la haya hace falta una tercera lectura: otra
            # franja, **recortada distinto**, sólo de esas caras. Distinto
            # porque el proveedor es determinista y la misma franja devuelve lo
            # mismo. Medido sobre diez discrepancias del libro 7 mirando el
            # papel: la franja acertaba en ocho y la página entera en dos, así
            # que ninguna de las dos puede mandar sola; y sobre las 74 del
            # libro, la segunda mirada confirmó la franja en 52, dio la razón
            # a la página en 13 y dejó 8 sin mayoría. Lo que dos lecturas
            # confirman se archiva y queda como aviso; lo que tres lecturas no
            # cierran es un error de verdad y va a revisión.
            segunda = (
                self._franjas_de_cedula(source, segunda_vuelta, otra_mirada=True)
                if segunda_vuelta
                else {}
            )
            zanjadas = discrepantes = 0
            for pagina in segunda_vuelta:
                entera = actual(pagina).identity_number
                una, otra = primera.get(pagina), segunda.get(pagina)
                if una is None and otra is None:
                    continue
                if una is None:
                    if otra == entera:
                        confirmadas += 1
                        continue
                    elegida, aviso = otra, (
                        f"hay que comprobar la cédula: la página entera dice {entera} y la "
                        f"franja {otra}, y no hay una tercera lectura que decida; se archivó "
                        f"por la franja"
                    )
                    discrepantes += 1
                elif otra == una:
                    elegida, aviso = una, (
                        f"la cédula leída a página entera ({entera}) no coincide con la de la "
                        f"franja ({una}), que dos lecturas confirmaron; se archivó por la franja"
                    )
                    zanjadas += 1
                elif otra == entera:
                    elegida, aviso = entera, (
                        f"la franja leyó una vez otra cédula ({una}); dos lecturas "
                        f"confirmaron la de la página ({entera})"
                    )
                    zanjadas += 1
                else:
                    elegida, aviso = una, (
                        f"hay que comprobar la cédula: se leyó de tres formas distintas "
                        f"({entera}, {una}, {otra or 'sin lectura'}); se archivó por la "
                        f"primera franja"
                    )
                    discrepantes += 1
                anotar(pagina, identity_number=elegida)
                resueltos[pagina] = replace(
                    resueltos[pagina], warnings=[*resueltos[pagina].warnings, aviso]
                )
            stats.repescadas["cedulas"] = recuperadas
            stats.repescadas["cedulas_confirmadas"] = confirmadas
            stats.repescadas["cedulas_zanjadas"] = zanjadas
            stats.repescadas["cedulas_discrepantes"] = discrepantes
            logger.info(
                "la franja de la cédula recuperó %d, confirmó %d, zanjó %d y dejó %d "
                "por comprobar de %d caras",
                recuperadas,
                confirmadas,
                zanjadas,
                discrepantes,
                len(caras),
            )

        # --- Mosaico de fechas: repesca la fecha manuscrita del pie ----------
        if self._mosaico_de_fechas is not None:
            # Caras que llegaron al motor de pago y no tienen fecha
            caras_sin_fecha = [p for p in por_pagina if not actual(p).graduation_date]
            if caras_sin_fecha:
                self._report(
                    ProgressEvent(
                        stage=Stage.VERIFYING,
                        page_count=total,
                        detail=f"buscando la fecha de {len(caras_sin_fecha)} caras en franjas",
                        done=0,
                        total=len(caras_sin_fecha),
                    )
                )
                fechas = self._mosaico_de_fechas.fechas(source, caras_sin_fecha)
                recuperadas_fecha = 0
                for pagina, fecha in fechas.items():
                    if fecha:
                        anotar(pagina, graduation_date=fecha)
                        recuperadas_fecha += 1
                stats.repescadas["fechas"] = recuperadas_fecha
                logger.info(
                    "el mosaico de fechas recuperó %d de %d caras",
                    recuperadas_fecha,
                    len(caras_sin_fecha),
                )

        if self._mosaico is not None and not self._lectura_de_ahorro:
            sin_nombre = [p for p in por_pagina if not actual(p).nombre_creible]
            if sin_nombre:
                self._report(
                    ProgressEvent(
                        stage=Stage.VERIFYING,
                        page_count=total,
                        detail=f"repescando el nombre de {len(sin_nombre)} caras en franjas",
                        done=0,
                        total=len(sin_nombre),
                    )
                )
                try:
                    nombres = self._mosaico.nombres(source, sin_nombre)
                except Exception:  # noqa: BLE001 - la repesca es un extra, no un requisito
                    logger.warning("falló el mosaico de nombres", exc_info=True)
                    nombres = {}
                for pagina, nombre in nombres.items():
                    anotar(pagina, name=nombre.upper())
                stats.repescadas["nombres"] = len(nombres)
                logger.info(
                    "la repesca en franjas recuperó %d nombres de %d caras",
                    len(nombres),
                    len(sin_nombre),
                )

        if self._lectura_de_ahorro:
            # Con la lectura de ahorro se acabó el gasto aquí: de estas caras se
            # lee la franja y nada más, que es lo que el operador eligió.
            return

        sin_nada = [
            p for p in por_pagina if not actual(p).identity_creible and not actual(p).nombre_creible
        ]
        if not sin_nada:
            return
        textos = self._leer_en_paralelo(
            sin_nada,
            lambda pagina: self._rasterizar_para_el_pago(source, pagina),
            self._leer_entera,
            stats,
            f"releyendo sueltas {len(sin_nada)} caras sin cédula ni nombre",
            total,
        )
        releidas = 0
        for pagina, texto in textos.items():
            if not texto:
                continue
            stats.lecturas[pagina] = texto
            nuevo = extract_diploma(lines_from_text(texto), pagina)
            registro = actual(pagina)
            campos: dict[str, object] = {}
            if not registro.identity_creible and nuevo.identity_creible:
                campos["identity_number"] = nuevo.identity_number
            if not registro.nombre_creible and nuevo.nombre_creible:
                campos["name"] = nuevo.name
            if campos:
                releidas += 1
            # Y lo demás -- título, fecha, folio -- rellena los huecos que haya,
            # sin pisar nada que ya se hubiera leído.
            resueltos[pagina] = merge(replace(registro, **campos), nuevo)
            procedencias[pagina] = Provenance.OCR_FULL_PAGE
        stats.repescadas["sueltas"] = releidas
        logger.info(
            "la relectura suelta dio identidad a %d de %d caras que no tenían ninguna",
            releidas,
            len(sin_nada),
        )

    def _contar_sin_identidad(
        self, records: list[DiplomaRecord], stats: BookReadingStats
    ) -> None:
        """Cuántas unidades quedan sin cédula y sin nombre, dicho en voz alta.

        Un documento sin ninguna de las dos se archiva por su folio o por su
        orden, y así no lo encuentra quien busque a esa persona. Contarlo aquí
        -- una vez, al final, con el libro entero leído -- es lo que permite que
        el informe lo declare y que el operador decida si vuelve a pasarlo con
        ayuda de pago.
        """
        from ..domain.diploma import pertenece_al_anterior

        padre: DiplomaRecord | None = None
        for record in records:
            if pertenece_al_anterior(record, padre, self._criterio):
                continue
            padre = record
            if not record.identity_creible and not record.nombre_creible:
                stats.sin_identidad.append(record.page_number)
        if stats.sin_identidad:
            logger.warning(
                "%d documentos quedan sin cédula y sin nombre y se archivarán por "
                "su folio o su orden; si el papel está escrito a mano, este libro "
                "necesita leerse con OCR + IA",
                len(stats.sin_identidad),
            )

    def _pasada_local(
        self,
        source,
        pendientes: list[DiplomaRecord],
        resueltos: dict[int, DiplomaRecord],
        procedencias: dict[int, Provenance],
        stats: BookReadingStats,
        cinta: _CintaEnOrden,
        esperadas: set[int],
    ) -> list[DiplomaRecord]:
        """Lo que el motor de casa consigue, que no cuesta dinero.

        Devuelve las páginas que siguen sin resolver, que son las únicas que
        llegarán a pagarse.
        """
        self._report(
            ProgressEvent(
                stage=Stage.VERIFYING,
                page_count=len(pendientes),
                detail=f"leyendo {len(pendientes)} caras con el motor de casa",
                done=0,
                total=len(pendientes),
            )
        )

        muestra = pendientes[:_MUESTRA_LOCAL]
        resueltas = self._leer_con_el_local(
            source, muestra, resueltos, procedencias, stats, cinta, esperadas
        )
        # Con un motor de pago detrás, la medida de si Tesseract sirve en este
        # libro es **cuántas cédulas creíbles sacó**, no cuántas caras dio por
        # resueltas. Un nombre es una fila de letras y no se puede comprobar:
        # sobre el libro 7, manuscrito, Tesseract "resolvió" quince caras con
        # nombres como "UUY DL YEC CHAUS URAS LLES", que pasaron por nombre y
        # nunca llegaron a la IA -- y de paso gastó seis minutos leyendo las
        # otras trescientas setenta. Una cédula, en cambio, se sostiene o no.
        con_cedula = sum(
            1
            for record in muestra
            if resueltos.get(record.page_number, record).identity_creible
            and not record.identity_creible
        )
        tiene_lector_remoto = getattr(self._ocr, "read_remote", None) is not None
        if not resueltas or (tiene_lector_remoto and not con_cedula):
            # No recupera nada en este libro: lo que trajo se descarta y el
            # resto no se le pregunta siquiera.
            for record in muestra:
                resueltos.pop(record.page_number, None)
                procedencias.pop(record.page_number, None)
            logger.info(
                "el motor local no sacó ninguna cédula de %d caras de muestra; "
                "se descarta lo que trajo y el resto va directo al motor de pago",
                len(muestra),
            )
            return list(pendientes)

        self._leer_con_el_local(
            source,
            pendientes[_MUESTRA_LOCAL:],
            resueltos,
            procedencias,
            stats,
            cinta,
            esperadas,
        )
        return [
            record
            for record in pendientes
            if record.page_number not in resueltos
            or not self._resuelto(resueltos[record.page_number])
        ]

    def _leer_con_el_local(
        self,
        source,
        pendientes: list[DiplomaRecord],
        resueltos: dict[int, DiplomaRecord],
        procedencias: dict[int, Provenance],
        stats: BookReadingStats,
        cinta: _CintaEnOrden,
        esperadas: set[int],
    ) -> int:
        """Lee ese tramo con Tesseract y anota lo que haya resuelto de verdad."""
        if not pendientes:
            return 0
        textos = self._leer_en_paralelo(
            [record.page_number for record in pendientes],
            lambda pagina: source.render(pagina, None, self._dpi),
            lambda imagen: self._ocr.read_local(imagen).text,
            stats,
            f"leyendo {len(pendientes)} caras con el motor de casa",
            len(pendientes),
        )
        resueltas = 0
        for record in pendientes:
            texto = textos.get(record.page_number)
            if not texto:
                continue
            fundido = merge(record, extract_diploma(lines_from_text(texto), record.page_number))
            if not self._resuelto(fundido):
                # No se conserva: un campo suelto de una lectura que no cierra
                # el registro iría al FUID como si fuera un dato.
                continue
            self._cabeceras[record.page_number] = texto[:_CABECERA_CHARS]
            resueltos[record.page_number] = fundido
            procedencias[record.page_number] = Provenance.OCR_FULL_PAGE
            stats.recovered_by_ocr += 1
            resueltas += 1
        # Lo que el motor de casa cerró ya se puede pintar: esas caras no van a
        # cambiar, y enseñarlas ahora es la diferencia entre una pantalla que
        # avanza y una que espera a la fase de pago para decir nada.
        cinta.avanzar(resueltos, procedencias, esperadas - set(resueltos))
        return resueltas

    def _rastrear(
        self,
        source,
        pendientes: list[DiplomaRecord],
        resueltos: dict[int, DiplomaRecord],
        procedencias: dict[int, Provenance],
        stats: BookReadingStats,
    ) -> list[DiplomaRecord]:
        """Una segunda mirada local a la cédula, antes de pagar por ella.

        Se mete entre las dos fases a propósito: llega después de que la lectura
        normal fallara y antes de que la IA cobre. Lo que recupera es lo que ya
        estaba legible en el papel y se perdió por leerlo mal -- Tesseract
        buscando párrafos donde hay un número --, y eso no hay por qué pagarlo.

        Sólo busca la cédula, porque es el único campo que se puede atacar así:
        se sabe qué forma tiene, dónde vive y con qué rótulo viene. Un nombre no
        se puede atar a un juego de caracteres ni comprobar contra nada.

        Devuelve lo que sigue pendiente, que es lo único que llegará a pagarse.
        """
        self._report(
            ProgressEvent(
                stage=Stage.VERIFYING,
                page_count=len(pendientes),
                detail=f"buscando la cédula de {len(pendientes)} caras sin pagar",
                done=0,
                total=len(pendientes),
            )
        )
        recuperadas = 0
        candidatos = [
            record
            for record in pendientes
            if record.page_number in self._con_texto
            and not resueltos.get(record.page_number, record).identity_creible
        ]
        # MuPDF se usa sólo aquí, en el hilo principal. Las imágenes ya listas
        # sí se pueden pasar a varios Tesseract sin compartir el documento PDF.
        with hilos(min(4, self._workers)) as pool:
            futuros = {}
            for indice, record in enumerate(candidatos, start=1):
                self._control.check()
                imagenes = self._rastreo.imagenes(source, record.page_number)
                if imagenes:
                    futuros[pool.submit(
                        self._rastreo.buscar_imagenes, imagenes, record.page_number
                    )] = record
                if indice == 1 or (indice - 1) % _CADA_CUANTAS_SE_AVISA == 0:
                    self._report(
                        ProgressEvent(
                            stage=Stage.VERIFYING,
                            page_count=len(pendientes),
                            detail=f"preparando cédula: {indice}/{len(candidatos)} caras",
                            done=indice - 1,
                            total=len(candidatos),
                        )
                    )
            for indice, futuro in enumerate(completados(futuros, self._control), start=1):
                record = futuros[futuro]
                cedula = futuro.result()
                if cedula:
                    actual = resueltos.get(record.page_number, record)
                    resueltos[record.page_number] = extract_diploma_warnings(
                        replace(actual, identity_number=cedula)
                    )
                    procedencias.setdefault(record.page_number, Provenance.OCR_REGION)
                    recuperadas += 1
                if indice == len(futuros) or indice % _CADA_CUANTAS_SE_AVISA == 0:
                    self._report(
                        ProgressEvent(
                            stage=Stage.VERIFYING,
                            page_count=len(pendientes),
                            detail=f"buscando cédulas: {indice}/{len(futuros)} caras",
                            done=indice,
                            total=len(futuros),
                        )
                    )
        if recuperadas:
            logger.info(
                "el rastreo local recuperó %d cédulas de %d caras sin pagar una sola",
                recuperadas,
                len(pendientes),
            )
            stats.recuperadas_sin_pagar += recuperadas
        return [
            record
            for record in pendientes
            if not self._resuelto(resueltos.get(record.page_number, record))
        ]

    def _por_mosaico(
        self,
        source,
        pendientes: list[DiplomaRecord],
        resueltos: dict[int, DiplomaRecord],
        procedencias: dict[int, Provenance],
        stats: BookReadingStats,
    ) -> list[DiplomaRecord]:
        """Los nombres de muchas caras pagando por unas pocas paginas.

        Corre justo antes de la lectura entera y le quita trabajo: la cara cuyo
        nombre salga de aqui **ya no se lee completa**. Esa es la renuncia que
        el operador acepto al elegir la lectura de ahorro -- de esas caras se
        lee el nombre y nada mas -- y es de donde sale el factor diez.

        Lo que el mosaico no consiga sigue su camino y se lee como siempre, de
        modo que esto solo puede abaratar: nunca deja una cara peor de lo que
        estaba.
        """
        numeros = [record.page_number for record in pendientes]
        self._report(
            ProgressEvent(
                stage=Stage.VERIFYING,
                page_count=len(numeros),
                detail=f"leyendo el nombre de {len(numeros)} caras en mosaico",
                done=0,
                total=len(numeros),
            )
        )
        try:
            nombres = self._mosaico.nombres(source, numeros)
        except Exception:  # noqa: BLE001 - el mosaico es un atajo, no un requisito
            logger.warning("fallo el mosaico de nombres", exc_info=True)
            return pendientes

        por_pagina = {record.page_number: record for record in pendientes}
        for pagina, nombre in nombres.items():
            actual = resueltos.get(pagina, por_pagina[pagina])
            resueltos[pagina] = extract_diploma_warnings(replace(actual, name=nombre))
            procedencias.setdefault(pagina, Provenance.OCR_REGION)
        if nombres:
            logger.info(
                "el mosaico leyó %d nombres; esas caras ya no se leen enteras",
                len(nombres),
            )
        return [record for record in pendientes if record.page_number not in nombres]

    def _pasada_remota(
        self,
        source,
        pendientes: list[DiplomaRecord],
        resueltos: dict[int, DiplomaRecord],
        procedencias: dict[int, Provenance],
        stats: BookReadingStats,
        total: int,
        cinta: _CintaEnOrden,
        esperadas: set[int],
    ) -> None:
        """Lo que el de casa no consiguió, al motor de pago: en tandas y varias a la vez.

        Las tandas viajan **en paralelo**, con la misma ventana adaptable con
        que se leen las páginas sueltas. Iban una detrás de otra, y eso era el
        cuello de botella entero de la ruta de pago: cada tanda de doce caras
        eran unos veinte segundos de proveedor durante los que este proceso no
        hacía nada, y un libro de cuatrocientas caras eran cuarenta tandas en
        fila -- un cuarto de hora de espera pura. Con ocho en vuelo, el
        proveedor contesta por noventa y seis caras mientras este hilo
        rasteriza las doce siguientes.

        El rasterizado se queda en este hilo, como siempre: MuPDF no promete ser
        seguro entre hilos sobre el mismo documento. Lo que viaja al pool son
        bytes, y viajan ya en JPEG cuando la fuente sabe darlos así: escribir
        el PNG de una cara a 300 ppp cuesta un cuarto de segundo de este hilo,
        que es el único que puede rasterizar, y el proveedor lo recibía en
        JPEG de todos modos.
        """
        por_pagina = {record.page_number: record for record in pendientes}
        numeros = [record.page_number for record in pendientes]
        tandas = [
            numeros[arranque : arranque + TAMANO_DE_TANDA]
            for arranque in range(0, len(numeros), TAMANO_DE_TANDA)
        ]
        hechas = 0

        def rasterizar(indice: int) -> tuple[list[bytes], list[int]]:
            imagenes: list[bytes] = []
            leidas: list[int] = []
            for pagina in tandas[indice]:
                try:
                    imagenes.append(self._rasterizar_para_el_pago(source, pagina))
                    leidas.append(pagina)
                except Exception as error:  # noqa: BLE001 - una página, no el libro
                    logger.warning("no se pudo rasterizar la página %s", pagina, exc_info=True)
                    stats.failures[pagina] = explicar(error)
            return imagenes, leidas

        def leer(preparada: tuple[list[bytes], list[int]]) -> tuple[list[int], list[str]]:
            imagenes, leidas = preparada
            if not imagenes:
                return leidas, []
            try:
                textos = list(self._ocr.read_many_remote(imagenes))
            except Exception as error:  # noqa: BLE001 - la tanda, no el libro
                logger.warning("falló la tanda de %s páginas", len(imagenes), exc_info=True)
                for pagina in leidas:
                    stats.failures[pagina] = explicar(error)
                textos = []
            if textos and any(textos):
                return leidas, textos
            # La tanda volvió vacía entera. No es que doce caras seguidas estén
            # en blanco: es que el proveedor la rechazó -- un rechazo por ritmo
            # que agotó los reintentos, una conexión cortada -- y contestó sin
            # texto. Medido sobre el libro 7: dos tandas así dejaron 24 caras
            # nombradas por su orden sin que nada lo dijera. Se releen una a
            # una, que es el camino que existía antes de las tandas.
            logger.warning(
                "la tanda de %d caras volvió sin texto; se releen una a una",
                len(imagenes),
            )
            sueltas: list[str] = []
            for pagina, imagen in zip(leidas, imagenes, strict=True):
                try:
                    sueltas.append(self._leer_entera(imagen))
                except Exception as error:  # noqa: BLE001 - una página, no la tanda
                    stats.failures[pagina] = explicar(error)
                    sueltas.append("")
            return leidas, sueltas

        def cerrar(indices: list[int], contestadas: dict) -> None:
            """Resuelve las tandas que acaban de volver y pinta hasta donde se pueda."""
            nonlocal hechas
            for indice in indices:
                leidas, textos = contestadas.get(indice) or ([], [])
                for pagina, texto in zip(leidas, textos, strict=False):
                    if not texto:
                        continue
                    self._cabeceras[pagina] = texto[:_CABECERA_CHARS]
                    stats.lecturas[pagina] = texto
                    fundido = merge(
                        por_pagina[pagina], extract_diploma(lines_from_text(texto), pagina)
                    )
                    resueltos[pagina] = fundido
                    procedencias[pagina] = Provenance.OCR_FULL_PAGE
                    if self._resuelto(fundido):
                        stats.recovered_by_ocr += 1
                for pagina in tandas[indice]:
                    # Lo que volvió sin texto queda decidido igual, para que la
                    # cinta no se quede esperando una lectura que ya no llega.
                    procedencias.setdefault(pagina, Provenance.TEXT_LAYER)
                hechas += len(tandas[indice])
            # Y la cinta avanza tanda a tanda, que es lo que hace que el trabajo
            # se vea moverse en vez de parecer parado doce páginas seguidas.
            cinta.avanzar(resueltos, procedencias, esperadas)
            self._report(
                ProgressEvent(
                    stage=Stage.VERIFYING,
                    page_count=total,
                    detail=f"leyendo {len(numeros)} caras con el motor de pago",
                    done=hechas,
                    total=len(numeros),
                )
            )

        self._leer_en_paralelo(
            list(range(len(tandas))),
            rasterizar,
            leer,
            stats,
            f"leyendo {len(numeros)} caras con el motor de pago",
            total,
            al_cerrar_tanda=cerrar,
            # Una ventana de tandas y no de páginas: cuatro tandas son
            # cuarenta y ocho caras en vuelo. Con ocho, la ráfaga inicial de
            # ocho peticiones le arrancaba al proveedor rechazos por ritmo que
            # agotaban los reintentos de dos tandas enteras; con cuatro el
            # libro entero sigue leyéndose en menos de un minuto.
            en_vuelo=max(2, self._workers // 2),
        )

    def _franjas_de_cedula(
        self, source, paginas: list[int], otra_mirada: bool = False
    ) -> dict[int, str]:
        """Las cédulas que la franja lee de esas caras; vacío si el mosaico falla.

        Con ``otra_mirada`` se recorta distinto -- más margen, más resolución --
        para que la lectura no repita la primera. Un mosaico que no sepa mirar
        de otra forma se usa tal cual.
        """
        if not paginas:
            return {}
        mosaico = self._mosaico_de_cedulas
        if otra_mirada:
            mirar = getattr(mosaico, "otra_mirada", None)
            if mirar is not None:
                mosaico = mirar()
        try:
            return mosaico.cedulas(source, paginas)
        except Exception:  # noqa: BLE001 - la repesca es un extra, no un requisito
            logger.warning("falló el mosaico de cédulas", exc_info=True)
            return {}

    def _rasterizar_para_el_pago(self, source, pagina: int) -> bytes:
        """La página como viaja al proveedor, por el camino más corto que haya.

        Primero el escaneo original, si la fuente sabe sacarlo: en un libro
        escaneado cada cara es un JPEG que cubre la hoja, y mandarlo tal cual
        cuesta un milisegundo donde rasterizarlo cuesta ciento setenta -- del
        hilo que manda, que es el único que puede rasterizar y por tanto el
        suelo de toda la ruta de pago. Después, el rasterizado en JPEG, si la
        fuente sabe elegir formato. Y si no, como siempre.
        """
        escaneada = getattr(source, "imagen_escaneada", None)
        if escaneada is not None:
            try:
                original = escaneada(pagina)
            except Exception:  # noqa: BLE001 - se rasteriza, que es lo que había
                logger.debug("no se pudo sacar el escaneo de la página %s", pagina, exc_info=True)
                original = None
            if original:
                return original
        if self._formato_de_pago is None:
            return source.render(pagina, None, self._dpi)
        return source.render(pagina, None, self._dpi, formato=self._formato_de_pago)

    def _escalar_una_a_una(
        self,
        source,
        records: list[DiplomaRecord],
        pendientes: list[DiplomaRecord],
        stats: BookReadingStats,
    ) -> list[DiplomaRecord]:
        """El camino de siempre: una lectura por página, con el motor que haya.

        Lo toma un motor suelto, que es su propio peldaño y no tiene a quién
        escalar.
        """
        resueltos: dict[int, DiplomaRecord] = {}
        procedencias: dict[int, Provenance] = {}
        anunciadas = 0

        resueltas = 0

        def resolver(pagina: int, texto: str | None, record: DiplomaRecord) -> None:
            nonlocal resueltas
            if texto is None:
                stats.incomplete.append(pagina)
                procedencias[pagina] = Provenance.TEXT_LAYER
                return
            self._cabeceras[pagina] = texto[:_CABECERA_CHARS]
            segundo = extract_diploma(lines_from_text(texto), pagina)
            fundido = merge(record, segundo)
            if fundido.debe_releerse:
                stats.incomplete.append(pagina)
            else:
                stats.recovered_by_ocr += 1
                resueltas += 1
            # La escalada renderiza la página entera, no una banda del encabezado.
            procedencias[pagina] = Provenance.OCR_FULL_PAGE
            resueltos[pagina] = fundido

        def cerrar_tanda(tanda: list[int], leidas: dict[int, str]) -> None:
            """Resuelve lo que acaba de llegar y lo cuenta, sin adelantarse.

            En orden y sólo hasta donde esté todo resuelto, que es lo que hace
            que la cinta avance por bloques en vez de a saltos: leyendo a la vez
            las páginas vuelven desordenadas, y una casilla pintada antes que la
            de su izquierda no informa de por dónde va el trabajo.
            """
            nonlocal anunciadas
            for pagina in tanda:
                resolver(pagina, leidas.get(pagina), por_pagina[pagina])
            while anunciadas < len(records):
                siguiente = records[anunciadas]
                if (
                    siguiente.debe_releerse
                    and siguiente.page_number not in procedencias
                ):
                    break
                final = resueltos.get(siguiente.page_number, siguiente)
                self._anunciar_pagina(
                    final,
                    procedencias.get(siguiente.page_number, Provenance.TEXT_LAYER),
                    len(records),
                    stats,
                )
                anunciadas += 1

        por_pagina = {record.page_number: record for record in pendientes}

        def leer(paginas: list[int]) -> None:
            self._leer_en_paralelo(
                paginas,
                lambda pagina: source.render(pagina, None, self._dpi),
                self._leer_entera,
                stats,
                f"leyendo {len(pendientes)} páginas con OCR",
                len(records),
                al_cerrar_tanda=cerrar_tanda,
            )

        numeros = [record.page_number for record in pendientes]
        solo_local = getattr(self._ocr, "read_remote", None) is None
        if not solo_local or len(numeros) <= _MUESTRA_LOCAL:
            leer(numeros)
        else:  # pragma: no cover - sólo con un motor local suelto y libro largo
            # Con el motor local se prueba antes de seguir. La medida es si
            # alguna página quedó **resuelta** -- completa y sin contradicciones
            # -- y no si trajo algo, porque en un libro manuscrito Tesseract
            # siempre trae algo y nunca sirve: medido sobre el libro 7, en las 16
            # primeras páginas "recuperó" el libro 71, el nombre "exigen para
            # optar el título de" y la cédula 6507. Ni una página resuelta.
            #
            # Y si no resolvió ninguna, lo que trajo en la muestra se descarta
            # también: esos campos habrían ido al FUID como si fueran datos.
            muestra = numeros[:_MUESTRA_LOCAL]
            leer(muestra)
            if resueltas:
                leer(numeros[_MUESTRA_LOCAL:])
            else:
                logger.info(
                    "el motor local no resolvió ninguna de %d páginas de muestra; "
                    "se descarta lo que trajo y no se releen las %d restantes",
                    _MUESTRA_LOCAL,
                    len(numeros) - _MUESTRA_LOCAL,
                )
                for pagina in muestra:
                    resueltos.pop(pagina, None)
                    procedencias[pagina] = Provenance.TEXT_LAYER
                self._report(
                    ProgressEvent(
                        stage=Stage.VERIFYING,
                        page_count=len(records),
                        detail="el motor local no recupera nada en este libro; se sigue sin releer",
                        done=len(numeros),
                        total=len(numeros),
                    )
                )
                for pagina in numeros[_MUESTRA_LOCAL:]:
                    stats.incomplete.append(pagina)
                    procedencias[pagina] = Provenance.TEXT_LAYER
                cerrar_tanda([], {})

        return [resueltos.get(record.page_number, record) for record in records]

    def _anunciar_paginas(
        self,
        records: list[DiplomaRecord],
        procedencias: dict[int, Provenance],
        stats: BookReadingStats,
    ) -> None:
        """Todas de una vez, para cuando no hubo nada que escalar."""
        for record in records:
            self._anunciar_pagina(
                record,
                procedencias.get(record.page_number, Provenance.TEXT_LAYER),
                len(records),
                stats,
            )

    def _anunciar_pagina(
        self,
        record: DiplomaRecord,
        procedencia: Provenance,
        total: int,
        stats: BookReadingStats,
    ) -> None:
        """Una casilla de la cinta, con de dónde salió y por qué hay que mirarla.

        Se dice de dónde salió cada lectura porque callarlo pintaba con la misma
        marca la página fallida y la que no declara procedencia: un libro entero
        se anunciaba como ilegible mientras se leía perfectamente. Y se dice por
        qué hay que mirarla, porque marcar una página sin decir qué le pasa
        obliga al operador a abrirla para averiguarlo, que es justo el trabajo
        que este sistema existe para ahorrarle.
        """
        if record.page_number in stats.failures and not record.warnings:
            procedencia = Provenance.NONE
        self._contar(stats, procedencia, 1)
        self._report(
            ProgressEvent(
                stage=Stage.PAGE,
                page_number=record.page_number,
                page_count=total,
                provenance=str(procedencia),
                failed=record.needs_review,
                detail=record.review_reason,
            )
        )

    def _leer_en_paralelo(
        self,
        claves: list,
        preparar,
        leer,
        stats: BookReadingStats,
        detalle: str,
        total: int,
        al_cerrar_tanda=None,
        en_vuelo: int | None = None,
    ) -> dict:
        """Prepara en este hilo y lee en varios, sin que uno espere al otro.

        Cada ``clave`` es una unidad de lectura: una página, o una tanda de
        ellas. ``preparar`` la convierte en lo que viaja -- una imagen, una
        lista de imágenes -- y corre aquí; ``leer`` la contesta y corre en el
        pool. Es una sola máquina para las dos formas de leer porque lo que la
        hace valer es lo mismo en las dos: el hilo que manda prepara **por
        delante** y entrega según termina, con un tope de lecturas en vuelo
        para que la memoria no se dispare.

        Antes iba por tandas cerradas: se rasterizaban ocho, se leían ocho, y
        hasta que no volvía la última no se rasterizaba la siguiente. El render
        cuesta un cuarto de segundo por página y en serie son cien segundos en
        un libro de cuatrocientas; con tandas, esos cien segundos se sumaban a
        la red en vez de esconderse debajo.

        El rasterizado se queda en este hilo porque MuPDF no promete ser seguro
        entre hilos sobre el mismo documento. Lo que viaja al pool son bytes.

        La ventana se estrecha sola cuando el proveedor pide esperar -- un 429
        con ocho lecturas en vuelo suele seguir a otro -- y se vuelve a abrir
        tras un minuto sin rechazos. Es lo que evita perder páginas por ir
        rápido: medido, con doce lectores fijos un rechazo agotaba los
        reintentos y esa página volvía sin texto.

        El orden de llegada no importa: cada lectura vuelve con su clave y el
        llamador las recoloca. Lo que sí importa es que una lectura que falla
        no arrastre a las demás, así que cada una se protege sola y la página
        vuelve sin texto, que es lo que ya contestaba el peldaño anterior.
        """
        leidas: dict = {}
        hechas = 0
        tope = max(1, en_vuelo or self._workers * 2)
        ventana = tope
        ultimo_rechazo = time.monotonic()
        rechazos_vistos = self._rechazos_hasta_ahora()

        def fallo(clave, error: Exception) -> None:
            stats.failures[clave] = explicar(error)

        def recoger(todo: bool = False) -> list:
            """Espera lecturas hasta que quepa una más, o hasta la última si ``todo``.

            Las dos cosas son distintas y hubo que aprenderlo: al terminar el
            libro quedaban dos lecturas en vuelo que cabían de sobra en la
            ventana, nadie las esperaba, y esas dos páginas volvían sin texto y
            se iban a pagar otra vez en la pasada de las esquinas.
            """
            nonlocal hechas, ventana, ultimo_rechazo, rechazos_vistos
            terminadas: list = []
            while vuelo and (todo or len(vuelo) >= ventana):
                listos = alguno_listo(vuelo, self._control)
                for futuro in listos:
                    clave = vuelo.pop(futuro)
                    contestado = futuro.result()
                    if contestado is not None:
                        leidas[clave] = contestado
                    terminadas.append(clave)
            hechas += len(terminadas)

            # La ventana se ajusta a lo que el proveedor aguante.
            rechazos = self._rechazos_hasta_ahora()
            ahora = time.monotonic()
            if rechazos > rechazos_vistos:
                rechazos_vistos = rechazos
                ultimo_rechazo = ahora
                if ventana > 2:
                    ventana = max(2, ventana // 2)
                    logger.info("el proveedor pide esperar; lecturas en vuelo: %d", ventana)
            elif ventana < tope and ahora - ultimo_rechazo > _TREGUA_TRAS_RECHAZO:
                ventana += 1
                ultimo_rechazo = ahora
            return terminadas

        def anunciar(terminadas: list) -> None:
            if not terminadas:
                return
            if al_cerrar_tanda is not None:
                al_cerrar_tanda(sorted(terminadas), leidas)
            else:
                # Sin nada que anunciar por página -- las esquinas del folio son
                # una relectura de páginas ya contadas --, se informa de la
                # pasada entera para que la pantalla no se quede muda.
                self._report(
                    ProgressEvent(
                        stage=Stage.VERIFYING,
                        page_count=total,
                        detail=detalle,
                        done=hechas,
                        total=len(claves),
                    )
                )

        vuelo: dict = {}
        with hilos(self._workers) as pool:
            for clave in claves:
                # Entre una unidad y la siguiente no hay nada a medio leer: es
                # donde parar es seguro y reanudar significa continuar.
                self._control.check()
                anunciar(recoger())
                try:
                    carga = preparar(clave)
                except Exception as error:  # noqa: BLE001
                    logger.warning("no se pudo rasterizar la página %s", clave, exc_info=True)
                    fallo(clave, error)
                    continue
                vuelo[pool.submit(_protegido, leer, carga, clave, fallo)] = clave
            anunciar(recoger(todo=True))
        return leidas

    def _rechazos_hasta_ahora(self) -> int:
        """Cuántas veces el proveedor ha pedido esperar, si el motor lo cuenta."""
        contador = getattr(self._ocr, "consumo", None)
        if contador is None:
            return 0
        try:
            return int(contador.as_dict().get("rechazos") or 0)
        except Exception:  # noqa: BLE001 - contar no puede tumbar la lectura
            return 0

    @staticmethod
    def _contar(stats: BookReadingStats, provenance: Provenance, veces: int) -> None:
        if veces <= 0:
            return
        clave = str(provenance)
        stats.provenance[clave] = stats.provenance.get(clave, 0) + veces

    def _folios_de_las_esquinas(
        self, source, records: list[DiplomaRecord], stats: BookReadingStats
    ) -> list[DiplomaRecord]:
        """Qué folio lleva cada cara, leyendo sólo la esquina donde está escrito.

        Se le pide al mismo OCR que el trabajo tenga puesto, sin saber cuál es.
        Con el motor local no se va a leer casi nada -- lo de esa esquina está
        escrito a mano y Tesseract no lee manuscrito -- y no pasa nada, porque
        lo que no se lee se descarta y el archivo se nombra por su página. Con
        el motor de pago activado se leen dos de cada tres, y de ésas el libro
        confirma las que encajan con su progresión.

        Sólo se miran las caras que abren registro. La vuelta de la hoja no
        lleva folio -- ésa es la regla que reparte el libro -- así que pedir su
        lectura sería pagar por leer papel en blanco.

        Nada de esto puede tumbar el trabajo: una esquina que no se deja leer es
        un archivo con nombre menos bonito, no un libro sin partir.
        """
        if self._ocr is None:
            return records
        if getattr(self._ocr, "read_remote", None) is None:
            # Sin motor de pago no se lee ninguna esquina. Lo que hay escrito
            # ahí es la foliación a mano del archivista, y el motor de casa no
            # lee manuscrito: medido, 208 esquinas y doce segundos para cero
            # folios en el libro de 2011, 249 esquinas y dieciocho segundos
            # para cero folios en el libro 7. Era el tramo más largo de toda
            # la lectura con «Solo OCR», y no producía un solo dato.
            logger.info(
                "sin motor de pago no se leen las esquinas: el folio está escrito "
                "a mano y el motor local no lo lee"
            )
            return records

        aperturas = [
            record
            for record in records
            if record.folio_mark is MarcaDeFolio.PRESENTE
            # Con el folio impreso en el formulario no hace falta el de la
            # esquina: ya se sabe, y ése es el que manda al nombrar. Los libros
            # mecanografiados lo traen en todas las caras, y pagar 208 esquinas
            # por un dato que ya está en la fila era el tercio de su factura.
            and not record.folio
            and not record.registered_folio
        ]
        # Y también las esquinas que el ritmo del libro rebajó. Son tres en un
        # libro de cuatrocientas páginas, así que leerlas no cuesta nada, y son
        # justamente las que tienen algo escrito que no es un folio: en la
        # página 224 del libro 7 lo que hay escrito es "Anulada". Esa palabra es
        # un dato del expediente -- que el diploma se anuló -- y de paso
        # confirma por su valor que la rebaja estuvo bien hecha.
        rebajadas = [
            record for record in records if record.folio_mark is MarcaDeFolio.DUDOSA
        ]
        if not aperturas and not rebajadas:
            return records

        # Primero lo que ya se leyó. La página entera pasó por el OCR hace un
        # momento y la esquina es lo primero que devuelve: "2/V # LA REPUBLICA
        # DE COLOMBIA...". Pedirla otra vez era pagar dos veces la misma tinta:
        # 203 peticiones y un tercio de la factura del libro 7.
        cabeceras = getattr(self, "_cabeceras", {})
        textos: dict[int, str] = {}
        faltan: list[int] = []
        for record in (*aperturas, *rebajadas):
            cabecera = cabeceras.get(record.page_number, "")
            if cabecera and (
                folio_de_la_esquina(cabecera, record.page_number) or _dice_anulada(cabecera)
            ):
                textos[record.page_number] = cabecera
            else:
                faltan.append(record.page_number)

        # Y la esquina sola, sólo para las caras donde la cabecera no lo dijo.
        # Las rebajadas por el ritmo van en la misma pasada: no entran en la
        # comprobación -- una vuelta no ocupa lugar en la progresión --, pero
        # interesa saber si dicen "Anulada", que es un dato del expediente.
        #
        # Con la lectura de ahorro, o cortando cara a cara, solo las caras que
        # **no tienen con que nombrarse**. El folio de la esquina sirve para dos
        # cosas: dar nombre a un archivo que no tiene cedula ni graduando, y
        # anotar "Registrado a folio No. N" en el FUID. Lo primero importa; lo
        # segundo es una nota, y cuesta una pagina facturada por esquina.
        #
        # Medido sobre el libro de posgrados 3858081: veinticuatro caras salian
        # por diecisiete paginas, de las cuales tres eran los mosaicos y catorce
        # estas esquinas. Cobrar catorce paginas por una columna de notas, en el
        # modo que existe para no gastar, no se sostiene. Lo que la cabecera de
        # una lectura ya hecha dijo gratis se conserva igual: el filtro es sólo
        # para lo que habría que pagar.
        if faltan and (self._mosaico is not None or self._criterio is CriterioDeCorte.PAGINA):
            por_pagina = {record.page_number: record for record in records}
            con_nombre = [
                pagina
                for pagina in faltan
                if por_pagina[pagina].identity_creible or por_pagina[pagina].name
            ]
            if con_nombre:
                logger.info(
                    "%d esquinas no se leen porque su documento ya tiene con qué nombrarse",
                    len(con_nombre),
                )
                faltan = [pagina for pagina in faltan if pagina not in set(con_nombre)]
        if faltan:
            textos.update(
                self._leer_en_paralelo(
                    sorted(faltan),
                    lambda pagina: source.render(pagina, Band(*BANDA_DEL_FOLIO), FOLIO_DPI),
                    self._leer_la_esquina,
                    stats,
                    f"leyendo el folio de {len(faltan)} esquinas",
                    len(records),
                )
            )

        anuladas = {
            pagina for pagina, texto in textos.items() if _dice_anulada(texto)
        }
        leidas: list[tuple[int, str | None]] = [
            (
                record.page_number,
                folio_de_la_esquina(textos.get(record.page_number, ""), record.page_number),
            )
            for record in aperturas
        ]

        confirmados = folios_comprobados(leidas)
        if not confirmados and not anuladas:
            return records

        logger.info(
            "se leyeron %d folios en las esquinas y el libro confirmó %d",
            sum(1 for _pagina, folio in leidas if folio),
            len(confirmados),
        )
        return [
            replace(
                record,
                folio_manuscrito=confirmados.get(record.page_number),
                annulled=record.annulled or record.page_number in anuladas,
            )
            if record.page_number in confirmados or record.page_number in anuladas
            else record
            for record in records
        ]

    def _leer_entera(self, image: bytes) -> str:
        """La página completa, con el motor que sepa leer lo que aquí importa.

        Cuando el operador activó el motor de pago se le pide a él directamente,
        sin pasar por Tesseract. No es derroche: en estos libros el formulario
        está impreso y **todo lo que identifica al graduado está escrito a
        mano** -- su nombre, su cédula, el título y la fecha. Tesseract devuelve
        el formulario entero y ninguna de las cuatro, así que la cascada, que
        mide si salió texto, daría esa lectura por buena y no escalaría jamás.
        """
        leer = getattr(self._ocr, "read_remote", None) or self._ocr.read
        return leer(image).text

    def _leer_la_esquina(self, imagen: bytes) -> str:
        """El folio de esa esquina, con el motor que sabe leer manuscrito.

        Igual que la página entera, y por el mismo motivo: lo que hay escrito
        ahí es una anotación a mano, y el motor local devuelve `', "'` después
        de gastar un cuarto de segundo. En un libro de 398 páginas eso son
        cincuenta segundos de reloj para no leer nada.
        """
        leer = getattr(self._ocr, "read_remote", None) or self._ocr.read
        return leer(imagen).text

    def _marca_de_folio(self, source, page_number: int) -> MarcaDeFolio:
        """Si esta cara lleva el folio escrito a mano en la esquina.

        Nunca levanta. Una fuente que no sabe dar píxeles devuelve ``SIN_MEDIR``
        -- nadie miró esa esquina -- y el reparto se decide como se decidía antes
        de existir esta señal, por los identificadores que se hayan leído.

        No es lo mismo que ``DUDOSA``, y la diferencia tiene dos consecuencias.
        Una: ``DUDOSA`` une la hoja a la anterior, de modo que un libro entero
        sin medir se soldaría en un solo documento. Y otra: a una esquina dudosa
        se le pide después su folio al OCR, así que decir "dudosa" donde nadie
        miró era pagar una lectura por cada página de una fuente que no tiene
        píxeles que enseñar.
        """
        medir = getattr(source, "ink_of", None)
        if medir is None:
            return MarcaDeFolio.SIN_MEDIR
        try:
            trazo = medir(page_number, Band(*BANDA_DEL_FOLIO))
        except Exception:  # noqa: BLE001 - medir la esquina no puede tumbar el libro
            logger.debug(
                "no se pudo medir la esquina del folio en la página %s",
                page_number,
                exc_info=True,
            )
            return MarcaDeFolio.DUDOSA
        return marca_de_folio(TrazoEnEsquina(*trazo) if trazo is not None else None)

    def _report(self, event: ProgressEvent) -> None:
        # Con lo gastado hasta ahora, si el motor de lectura lo cuenta: es lo
        # que hace que el contador de la pantalla suba tanda a tanda y no sólo
        # al terminar, cuando ya no queda nada que decidir.
        contador = getattr(self._ocr, "consumo", None)
        if contador is not None and event.consumo is None and not contador.vacio:
            event = replace(event, consumo=contador.as_dict())
        try:
            self._progress.emit(event)
        except Exception:  # noqa: BLE001 - telemetry never breaks the work
            logger.debug("el informe de progreso falló, se continúa", exc_info=True)


def _protegido(leer, carga, clave, fallo):
    """Una lectura que falla es una página sin texto, no un libro sin leer."""
    try:
        return leer(carga)
    except Exception as error:  # noqa: BLE001 - contenido a esta página
        logger.warning("falló el OCR de la página %s", clave, exc_info=True)
        fallo(clave, error)
        return None


def _formato_para_la_red(source) -> str | None:
    """``"jpeg"`` si esta fuente sabe elegir el formato al rasterizar, o nada.

    Se mira la firma en vez de probar y capturar: una fuente de pruebas que no
    acepte el parámetro no tiene por qué levantar un ``TypeError`` que después
    haya que distinguir de uno de verdad.
    """
    try:
        return "jpeg" if "formato" in inspect.signature(source.render).parameters else None
    except (TypeError, ValueError):
        return None
