"""Read a whole book of diploma registrations, one record per page.

The same cascade the resolution splitter uses, for a different question. The
embedded text layer answers most pages for nothing; a page that leaves a field
unread is re-rendered and passed to OCR, and only what was actually missing is
taken from that second reading. On the three printed books measured, the text
layer alone left 57 of 1 084 pages incomplete and OCR closed all but a handful.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace

from ..domain.diploma import (
    DiplomaRecord,
    extract_diploma,
    extract_diploma_warnings,
    lines_from_text,
    merge,
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
from .control import NullRunControl, RunControl
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
    #: Cuántas páginas acabó respondiendo cada peldaño. No es lo mismo que
    #: ``escalated``, que cuenta los intentos: una escalada que falla deja en
    #: pie la lectura de la capa de texto, y aquí se cuenta esa.
    provenance: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "pages": self.pages,
            "from_text_layer": self.from_text_layer,
            "escalated": self.escalated,
            "recovered_by_ocr": self.recovered_by_ocr,
            "provenance": dict(self.provenance),
            "incomplete": list(self.incomplete),
            "failures": {str(page): error for page, error in sorted(self.failures.items())},
        }


class ReadDiplomaBook:
    """One book in, one record per page out."""

    def __init__(
        self,
        ocr: OcrEngine | None = None,
        progress: ProgressReporter | None = None,
        escalation_dpi: int = ESCALATION_DPI,
        control: RunControl | None = None,
        workers: int = LECTORES,
    ) -> None:
        self._ocr = ocr
        self._progress = progress or NullProgressReporter()
        self._dpi = escalation_dpi
        self._control = control or NullRunControl()
        self._workers = max(1, workers)

    def execute(self, source) -> tuple[list[DiplomaRecord], BookReadingStats]:
        stats = BookReadingStats(pages=source.page_count)
        self._report(ProgressEvent(stage=Stage.OPENED, page_count=source.page_count))

        # Primero lo que no espera a nadie: la esquina y la capa de texto de
        # cada página, que juntas cuestan una centésima de segundo. De aquí sale
        # ya el reparto del libro; lo que falta después es sólo ponerle nombre a
        # cada documento.
        records: list[DiplomaRecord] = []
        for page_number in range(1, source.page_count + 1):
            self._control.check()
            records.append(self._de_la_capa(source, page_number, stats))
            # Esta pasada dura cuatro segundos en un libro de cuatrocientas
            # páginas, pero callarla dejaba la pantalla diciendo "reconociendo"
            # sin un solo número mientras el trabajo ya estaba midiendo folios.
            if page_number % _CADA_CUANTAS_SE_AVISA == 0 or page_number == source.page_count:
                self._report(
                    ProgressEvent(
                        stage=Stage.IDENTIFYING,
                        page_count=source.page_count,
                        detail="midiendo el folio de cada esquina",
                        done=page_number,
                        total=source.page_count,
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
        records = self._escalar(source, records, stats)

        # Y con el reparto ya decidido, el número. Va al final y no durante la
        # lectura de cada página porque comprobarlo exige el libro entero: un
        # folio suelto no se puede contrastar con nada, y la progresión sí.
        records = self._folios_de_las_esquinas(source, records, stats)

        # Sin DONE: leer no es terminar. Quien anuncia el final es quien sabe
        # qué queda por hacer después, que es el trabajo y no el lector.
        return records, stats

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
            record = extract_diploma(source.lines_of(page_number), page_number)
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
        self, source, records: list[DiplomaRecord], stats: BookReadingStats
    ) -> list[DiplomaRecord]:
        """Relee con OCR las páginas que la capa de texto no resolvió.

        No basta con que estén todos los campos: una página que se contradice a
        sí misma -- el folio del encabezado contra el del pie, un nombre con un
        dígito dentro -- está completa y mal leída. El OCR entra en las dos,
        porque en las dos hay algo que verificar.

        La procedencia que se cuenta es la del peldaño que produjo lo que se
        conserva, no la del último que se intentó: una escalada que falla deja
        en pie la lectura de la capa de texto, y decir "OCR" ahí sería contar el
        intento en vez del resultado.
        """
        for record in records:
            if not record.debe_releerse:
                stats.from_text_layer += 1

        pendientes = [record for record in records if record.debe_releerse]
        if self._ocr is None or not pendientes:
            stats.incomplete.extend(record.page_number for record in pendientes)
            self._anunciar_paginas(records, {}, stats)
            return records

        stats.escalated += len(pendientes)
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
        else:
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
        paginas: list[int],
        rasterizar,
        leer,
        stats: BookReadingStats,
        detalle: str,
        total: int,
        al_cerrar_tanda=None,
    ) -> dict[int, str]:
        """Rasteriza en este hilo y lee en varios, sin que uno espere al otro.

        Antes iba por tandas cerradas: se rasterizaban ocho, se leían ocho, y
        hasta que no volvía la última no se rasterizaba la siguiente. El render
        cuesta un cuarto de segundo por página y en serie son cien segundos en
        un libro de cuatrocientas; con tandas, esos cien segundos se sumaban a
        la red en vez de esconderse debajo. Ahora el hilo que manda rasteriza
        **por delante** y entrega al pool según termina, con un tope de lecturas
        en vuelo para que la memoria no se dispare: una página rasterizada son
        cerca de dos megas.

        El rasterizado se queda en este hilo porque MuPDF no promete ser seguro
        entre hilos sobre el mismo documento. Lo que viaja al pool son bytes.

        La ventana se estrecha sola cuando el proveedor pide esperar -- un 429
        con ocho lecturas en vuelo suele seguir a otro -- y se vuelve a abrir
        tras un minuto sin rechazos. Es lo que evita perder páginas por ir
        rápido: medido, con doce lectores fijos un rechazo agotaba los
        reintentos y esa página volvía sin texto.

        El orden de llegada no importa: cada lectura vuelve con su número de
        página y el llamador las recoloca. Lo que sí importa es que una lectura
        que falla no arrastre a las demás, así que cada una se protege sola y la
        página vuelve sin texto, que es lo que ya contestaba el peldaño anterior.
        """
        leidas: dict[int, str] = {}
        hechas = 0
        ventana = self._workers * 2
        ultimo_rechazo = time.monotonic()
        rechazos_vistos = self._rechazos_hasta_ahora()

        def recoger(todo: bool = False) -> list[int]:
            """Espera lecturas hasta que quepa una más, o hasta la última si ``todo``.

            Las dos cosas son distintas y hubo que aprenderlo: al terminar el
            libro quedaban dos lecturas en vuelo que cabían de sobra en la
            ventana, nadie las esperaba, y esas dos páginas volvían sin texto y
            se iban a pagar otra vez en la pasada de las esquinas.
            """
            nonlocal hechas, ventana, ultimo_rechazo, rechazos_vistos
            terminadas: list[int] = []
            while en_vuelo and (todo or len(en_vuelo) >= ventana):
                listos, _ = wait(list(en_vuelo), return_when=FIRST_COMPLETED)
                for futuro in listos:
                    pagina = en_vuelo.pop(futuro)
                    texto = futuro.result()
                    if texto is not None:
                        leidas[pagina] = texto
                    terminadas.append(pagina)
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
            elif ventana < self._workers * 2 and ahora - ultimo_rechazo > _TREGUA_TRAS_RECHAZO:
                ventana += 1
                ultimo_rechazo = ahora
            return terminadas

        def anunciar(terminadas: list[int]) -> None:
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
                        total=len(paginas),
                    )
                )

        en_vuelo: dict = {}
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            for pagina in paginas:
                # Entre una página y la siguiente no hay nada a medio leer: es
                # donde parar es seguro y reanudar significa continuar.
                self._control.check()
                anunciar(recoger())
                try:
                    imagen = rasterizar(pagina)
                except Exception as error:  # noqa: BLE001
                    logger.warning("no se pudo rasterizar la página %s", pagina, exc_info=True)
                    stats.failures[pagina] = explicar(error)
                    continue
                en_vuelo[pool.submit(_protegido, leer, imagen, pagina, stats)] = pagina
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

        aperturas = [
            record for record in records if record.folio_mark is MarcaDeFolio.PRESENTE
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


def make_progress_hook(on_page: Callable[[int, int], None]) -> ProgressReporter:
    """Adapt a plain callback to the reporter the use case expects."""

    class _Hook:
        def emit(self, event: ProgressEvent) -> None:
            if event.stage is Stage.PAGE and event.page_number:
                on_page(event.page_number, event.page_count or 0)

    return _Hook()


def _protegido(leer, imagen: bytes, pagina: int, stats: BookReadingStats) -> str | None:
    """Una lectura que falla es una página sin texto, no un libro sin leer."""
    try:
        return leer(imagen)
    except Exception as error:  # noqa: BLE001 - contenido a esta página
        logger.warning("falló el OCR de la página %s", pagina, exc_info=True)
        stats.failures[pagina] = explicar(error)
        return None
