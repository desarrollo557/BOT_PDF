"""Lo que toda habilidad arma igual antes de empezar.

Cuatro rutas parten un PDF de cuatro maneras, pero las cuatro necesitan lo
mismo para arrancar: saber de dónde viene el documento y a dónde va, por dónde
avisar del progreso, a quién preguntarle si debe seguir, un OCR, y -- las que
lo usan -- un modelo de visión o un oráculo de bordes. Cada ruta lo construía a
mano, con el bloque «si hay clave de Anthropic, Claude; si no, nada» escrito
tres veces y la elección del reportero de progreso, cuatro.

Los adaptadores se importan dentro de cada método y no arriba: el proceso de la
API no tiene por qué cargar MuPDF, Tesseract ni el SDK de Anthropic para
aceptar una subida.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...application.consumo import Consumo
from ...application.control import RunControl
from ...application.progress import ProgressEvent, ProgressReporter, Stage

logger = logging.getLogger(__name__)

#: En qué orden prueba la cascada cuando el operador no eligió. Es por costo, no
#: por calidad: Claude cachea las instrucciones, que en una caja se pagan una vez
#: por página; la capa gratuita de Gemini aguanta una caja preguntada de una sola
#: vez; Mistral no trae ninguna de las dos cosas, así que va último.
_CASCADE = ("claude", "gemini", "mistral")


@dataclass(frozen=True, slots=True)
class Taller:
    """El puesto de trabajo de una habilidad: de dónde, a dónde y con qué."""

    #: Los ajustes del servicio, tal como viajan al proceso worker.
    settings: dict
    job_id: str
    #: El PDF en el disco, bajo el nombre generado con que se guardó la subida.
    source: Path
    #: El nombre que le puso el operador, que es el que va a los informes.
    name: str
    #: La carpeta del trabajo, donde queda todo lo que se produzca.
    destination: Path
    progress: ProgressReporter
    control: RunControl
    #: Qué modelo pidió el operador para las costuras dudosas, si pidió alguno.
    oracle_choice: str | None
    #: Con qué se transcribe el papel: sólo Tesseract, o Tesseract y el OCR de
    #: Mistral donde el de casa no saque nada. Lo elige el operador al cargar el
    #: archivo, porque es él quien sabe si tiene delante un expediente
    #: mecanografiado -- donde el remoto no aportaría nada y se pagaría igual --
    #: o un libro donde todo lo que identifica al documento está escrito a mano.
    lectura_choice: str | None
    #: Con qué señal del papel se corta un libro de diplomas: por el folio de la
    #: esquina o por el número de cédula. Sólo lo mira esa habilidad; las demás
    #: cortan por lo suyo y este campo les da igual.
    corte_choice: str | None
    #: Qué se entrega como un archivo en una caja de correspondencia, una vez
    #: cortada: cada documento, o todos los de un mismo mes juntos. Sólo lo
    #: mira esa habilidad.
    agrupar_choice: str | None
    #: A dónde acabará la copia en una corrida sobre carpeta local.
    delivered_to: str | None
    operator: str | None
    #: Dónde se anota lo que este trabajo le pide a los proveedores de pago.
    #: Uno por trabajo y compartido por todos los adaptadores que el taller
    #: construya, para que el informe pueda decir cuánto costó el documento y
    #: no cuánto costó cada llamada por separado.
    consumo: Consumo = field(default_factory=Consumo)
    #: El tope común de llamadas a la IA de todo el servicio: un semáforo del
    #: Manager que comparten los procesos del pool. ``None`` fuera del servicio.
    turnos_de_ia: Any = None
    #: Las páginas que hay que leer, cuando no es el documento entero: al
    #: retomar una entrega a medias, las que faltan en el destino. Sólo la
    #: habilidad de libros de diplomas sabe leer así.
    paginas: tuple[int, ...] | None = None

    @classmethod
    def desde(cls, payload: dict) -> Taller:
        settings = payload["settings"]
        source = Path(payload["source"])
        return cls(
            settings=settings,
            job_id=payload["job_id"],
            source=source,
            name=payload.get("filename") or source.name,
            destination=Path(settings["output_dir"]) / payload["job_id"],
            progress=_reportero(payload),
            control=_control(payload),
            oracle_choice=payload.get("oracle"),
            lectura_choice=payload.get("lectura"),
            corte_choice=payload.get("corte"),
            agrupar_choice=payload.get("agrupar"),
            delivered_to=payload.get("destination"),
            operator=payload.get("operator"),
            turnos_de_ia=payload.get("turnos_de_ia"),
            paginas=tuple(int(n) for n in payload["paginas"]) if payload.get("paginas") else None,
            # El despachador lo crea antes de elegir ruta y lo deja en el
            # payload, para poder adjuntarlo al informe cuando la ruta vuelva.
            consumo=(
                payload["consumo"]
                if isinstance(payload.get("consumo"), Consumo)
                else Consumo(
                    precio_por_pagina=settings.get("precio_ocr_por_pagina"),
                    tope_de_paginas=settings.get("tope_paginas_ocr"),
                )
            ),
        )


    def ocr(self):
        """El motor de lectura de este trabajo, que es el mismo para todas.

        Las cuatro habilidades piden su OCR aquí y ninguna sabe cuál le tocó:
        la de resoluciones le pedirá el número del encabezado, la de registros
        el folio de la esquina, la de correspondencia el texto con que decide
        las costuras y la de inventario la portada del archivo. Por eso activar
        el motor de pago las alcanza a las cuatro sin tocar ninguna.

        Sin llave se devuelve el local y no se avisa aquí: pedir un motor que no
        se puede pedir ya se rechazó en la API, antes de recibir el archivo.
        """
        from ...adapters.tesseract_ocr import HeaderAndPageOcr

        local = HeaderAndPageOcr(language=self.settings["ocr_language"])
        if not self._con_ia():
            return local

        llave = self.settings.get("mistral_api_key")
        if not llave:
            logger.warning(
                "se pidió leer con Mistral y no hay llave; se lee sólo con Tesseract"
            )
            return local

        from ...adapters.mistral_ocr import MistralOcr
        from ...adapters.ocr_cascada import OcrEnCascada

        return OcrEnCascada(
            local=local,
            remoto=MistralOcr(api_key=llave, consumo=self.consumo, turnos=self.turnos_de_ia),
            consumo=self.consumo,
        )

    def vision(self):
        """El modelo de visión para el último peldaño de la cascada, o nadie.

        Con «Solo OCR», nadie: es una IA de pago, y esa elección existe para
        no gastar en lo que no se pidió.
        """
        from ...adapters.claude_vision import (
            ClaudeVisionConfig,
            ClaudeVisionOracle,
            NullVisionOracle,
        )

        api_key = self.settings.get("anthropic_api_key")
        if not api_key or not self._con_ia():
            return NullVisionOracle()
        from anthropic import Anthropic

        return ClaudeVisionOracle(
            client=Anthropic(api_key=api_key),
            config=ClaudeVisionConfig(model=self.settings["vision_model"]),
            consumo=self.consumo,
        )

    def pipeline(self, ocr):
        """La cascada de lectura, con el OCR que se le dé y la visión que haya."""
        from ...application.pipeline import ClassificationPipeline, PipelineConfig

        return ClassificationPipeline(
            ocr=ocr,
            vision=self.vision(),
            config=PipelineConfig(
                max_workers=self.settings["page_workers"],
                mosaic_size=self.settings["mosaic_size"],
            ),
            progress=self.progress,
            control=self.control,
        )

    def oraculo_de_bordes(self):
        """Quién juzga las costuras que la estructura no decidió.

        Con «Solo OCR», nadie: las costuras dudosas se unen y van a revisión
        (ante la duda se une). Lo decidió el operador: «cuando sea solo OCR,
        sea solo OCR». Antes el oráculo en «auto» consultaba al modelo que
        tuviera llave aunque se hubiera elegido no gastar.
        """
        if not self._con_ia():
            from ...adapters.boundary_prompt import NullBoundaryOracle

            return NullBoundaryOracle()
        return _boundary_oracle(self.settings, self.oracle_choice, consumo=self.consumo)

    def con_ia(self) -> bool:
        """Si el operador pidió la ayuda de pago para este trabajo."""
        return self._con_ia()

    def _con_ia(self) -> bool:
        """Si este trabajo puede pedirle páginas al motor de pago."""
        from ...application.lectura import LecturaChoice

        return LecturaChoice.parse(self.lectura_choice) in (
            LecturaChoice.MISTRAL,
            LecturaChoice.MISTRAL_NOMBRES,
        )

    def mosaico(self):
        """Quien lee los nombres de muchas caras pagando por unas pocas páginas.

        Con cualquiera de las dos lecturas de pago. En la de ahorro **sustituye**
        a la lectura entera: de esas caras se lee el nombre y nada más, que es la
        renuncia que el operador aceptó. En la completa **repesca** lo que la
        tanda dejó sin nombre: viajando en tanda, el motor de pago devuelve el
        renglón manuscrito como imagen en una de cada seis caras, y en la franja
        ampliada lo lee.
        """
        from ...adapters.mosaico_de_nombres import MosaicoDeNombres

        return self._mosaico(MosaicoDeNombres)

    def mosaico_de_cedulas(self):
        """Quien repesca la cédula en franjas ampliadas, con cualquier lectura de pago.

        A página entera el motor de pago se come dígitos de la cédula
        manuscrita; en la franja del renglón "C.C. No." los lee casi todos, y
        cuesta una página facturada por cada diez caras.
        """
        from ...adapters.mosaico_de_nombres import MosaicoDeCedulas

        return self._mosaico(MosaicoDeCedulas)

    def lectura_de_ahorro(self) -> bool:
        """Si el operador eligió pagar por la franja del nombre y no por la hoja."""
        from ...application.lectura import LecturaChoice

        return LecturaChoice.parse(self.lectura_choice) is LecturaChoice.MISTRAL_NOMBRES

    def _mosaico(self, clase):
        if not self._con_ia():
            return None
        llave = self.settings.get("mistral_api_key")
        if not llave:
            return None

        from ...adapters.mistral_ocr import MistralOcr

        motor = MistralOcr(api_key=llave, consumo=self.consumo, turnos=self.turnos_de_ia)
        return clase(
            leer=lambda imagen: motor.read(imagen).text,
            # La mitad de los lectores de página: un mosaico son diez caras, y
            # cuatro en vuelo son cuarenta franjas en camino.
            lectores=max(1, int(self.settings.get("page_workers") or 8) // 2),
        )

    def mosaico_de_fechas(self):
        """Quien repesca la fecha manuscrita en el pie del diploma, con cualquier lectura de pago.

        La fecha va escrita a mano en la fórmula "a los X días del mes de Y de mil
        novecientos Z". Tesseract no la lee; el motor de pago sí.
        En la franja del pie (12% de la hoja) agrupa 10 caras = 1 página facturada.
        """
        from ...adapters.mosaico_de_fechas import MosaicoDeFechas

        return self._mosaico(MosaicoDeFechas)

    def mistral_summary(self):
        """Adaptador para generar resúmenes de actas con Mistral (chat completions)."""
        from ...adapters.mistral_summary import (
            MistralSummaryAdapter,
            MistralSummaryConfig,
        )

        api_key = self.settings.get("mistral_api_key")
        if not api_key or not self._con_ia():
            return None
        return MistralSummaryAdapter(
            api_key=api_key,
            config=MistralSummaryConfig(),
            consumo=self.consumo,
        )

    def resumidor(self):
        """Quien escribe el resumen de un acta de consejo, si se pidió la IA.

        Lee el texto que ya sacó el OCR de casa, nunca la imagen: se paga por
        los tokens del resumen y no por página. Con «Solo OCR» no hay
        resumidor, porque gastar en lo que el operador no pidió es justo lo que
        esa elección existe para evitar.
        """
        if not self._con_ia():
            return None
        llave = self.settings.get("mistral_api_key")
        if not llave:
            return None

        from ...adapters.mistral_resumen import MistralResumidor

        return MistralResumidor(api_key=llave, consumo=self.consumo, turnos=self.turnos_de_ia)

    def nombrador(self):
        """Quien nombra con la IA un documento que nada supo nombrar, si se pidió la IA.

        Lo pidió el operador el 2026-10-22: «que la IA, de acuerdo al cuerpo del
        PDF, le agregue el nombre; la idea es que no se vaya vacío». Es el chat
        pequeño, con el catálogo del cliente como contexto, y sólo para el
        documento que se iba a llamar por su caja y sus páginas. Con «Solo OCR»
        no hay nombrador.
        """
        if not self._con_ia():
            return None
        llave = self.settings.get("mistral_api_key")
        if not llave:
            return None

        from ...adapters.mistral_resumen import MistralResumenConfig, MistralResumidor
        from ...domain.nombre_oficial import instrucciones_para_nombrar

        return MistralResumidor(
            api_key=llave,
            config=MistralResumenConfig(max_tokens=40, temperatura=0.0),
            consumo=self.consumo,
            turnos=self.turnos_de_ia,
            instrucciones=instrucciones_para_nombrar(),
            encabezado="Texto del documento",
        )

    def lector_del_estudiante(self):
        """Quien saca con la IA el nombre de un estudiante del texto de su ficha, si se pidió la IA.

        Lo pidió el operador el 2026-10-30: «ningún PDF sin nombre; cuando vaya
        sin nombre, que sea la IA quien actúe». Lee el texto que el OCR de pago
        ya sacó de la ficha, no la imagen: se paga por tokens. Con «Solo OCR» no hay.
        """
        if not self._con_ia():
            return None
        llave = self.settings.get("mistral_api_key")
        if not llave:
            return None

        from ...adapters.mistral_resumen import MistralResumenConfig, MistralResumidor
        from ...domain.historia_academica import INSTRUCCIONES_DEL_ESTUDIANTE

        return MistralResumidor(
            api_key=llave,
            config=MistralResumenConfig(max_tokens=40, temperatura=0.0),
            consumo=self.consumo,
            turnos=self.turnos_de_ia,
            instrucciones=INSTRUCCIONES_DEL_ESTUDIANTE,
            encabezado="Texto de la ficha",
        )

    def lector_de_folios(self):
        """Quien lee el folio manuscrito de un acta, si se pidió la IA.

        Lee sólo la esquina de la primera y la última hoja foliada, apiladas en
        una imagen: una página facturada por acta. Con «Solo OCR» no hay lector,
        y el acta sale con las hojas foliadas contadas por la tinta.
        """
        if not self._con_ia():
            return None
        llave = self.settings.get("mistral_api_key")
        if not llave:
            return None

        from ...adapters.esquinas_del_folio import LectorDeFolios
        from ...adapters.mistral_ocr import MistralOcr

        motor = MistralOcr(api_key=llave, consumo=self.consumo, turnos=self.turnos_de_ia)
        return LectorDeFolios(leer=lambda imagen: motor.read(imagen).text)

    def lector_de_pago(self):
        """Quien relee con la IA una hoja entera, si se pidió la IA.

        Lo usan las actas de grado para lo que Tesseract no supo leer del
        graduado: se paga sólo por esas hojas. Con «Solo OCR», o sin llave, no
        hay lector y el acta se queda con lo que leyó el de casa.
        """
        if not self._con_ia():
            return None
        llave = self.settings.get("mistral_api_key")
        if not llave:
            return None

        from ...adapters.mistral_ocr import MistralOcr

        return MistralOcr(api_key=llave, consumo=self.consumo, turnos=self.turnos_de_ia)

    def motivo_sin_resumidor(self) -> str:
        """Por qué este trabajo no tiene resumidor, dicho para la columna de notas."""
        if not self._con_ia():
            return "se leyó con «Solo OCR»"
        return "falta la llave de Mistral en el servicio"

    def rastreo(self):
        """Quién da la segunda mirada local a una cédula que no salió.

        Se construye siempre: es gratis en dinero y casi gratis en tiempo --
        sólo mira las caras que traen capa de texto y el rótulo impreso de la
        cédula --, y lo que recupera son páginas que iban camino del motor de
        pago. En un libro escaneado sin capa de texto no llega a mirar ninguna.
        """
        from ...adapters.rastreo_cedula import RastreoDeCedula

        return RastreoDeCedula(language=self.settings["ocr_language"])

    def criterio(self):
        """El criterio de corte que pidió el operador, o el de siempre.

        Lo desconocido no se adivina: la API lo rechaza antes de aceptar el
        archivo, así que llegar aquí con algo raro sólo pasa si alguien llama al
        worker por su cuenta, y entonces vale más fallar que cortar por un
        criterio que nadie pidió.
        """
        from ...domain.diploma import CriterioDeCorte

        return CriterioDeCorte.parse(self.corte_choice)

    def agrupacion(self):
        """Qué se entrega como un archivo: cada documento o cada mes.

        Como el criterio de corte, lo desconocido falla en vez de adivinarse: la
        API ya lo rechazó antes de aceptar el archivo.
        """
        from ...application.agrupacion import Agrupacion

        return Agrupacion.parse(self.agrupar_choice)

    def ubicacion(self):
        return _ubicacion(self.settings)


def _control(payload: dict) -> RunControl:
    """Lo que este trabajo consulta para saber si debe seguir.

    El diccionario viene de un Manager, así que leerlo cruza a otro proceso.
    Por eso se consulta una vez por página y no dentro del bucle de una: a esa
    cadencia el coste es invisible y la orden llega en un segundo.

    La clave por omisión es la del trabajo, porque lo normal es que procesar un
    documento sea la única cosa que corre bajo su identificador. No siempre: el
    FUID que se levanta a petición vuelve a leer un documento que ya terminó, y
    ese trabajo tiene que poder abandonarse sin que la orden se confunda con la
    del trabajo original -- que ya no existe, y cuya clave el registro reutiliza
    para decir en qué estado quedó. De ahí ``control_key``.
    """
    from ...application.control import FlagRunControl, NullRunControl

    controls = payload.get("controls")
    if controls is None:
        return NullRunControl()
    clave = payload.get("control_key") or payload["job_id"]
    return FlagRunControl(lambda: controls.get(clave))


def _reportero(payload: dict) -> ProgressReporter:
    """El canal por el que un adaptador informa de su avance.

    Devuelve un reportero nulo cuando no hay cola -- en las pruebas y en los
    scripts -- para que escribir PDF o planillas no dependa de que alguien esté
    mirando.
    """
    from ...adapters.queue_progress import QueueProgressReporter
    from ...application.progress import NullProgressReporter

    queue = payload.get("progress_queue")
    if queue is None:
        return NullProgressReporter()
    return QueueProgressReporter(queue, payload["job_id"])


def _anunciar(
    payload: dict,
    stage: Stage,
    page_count: int | None = None,
    *,
    detail: str | None = None,
    done: int | None = None,
    total: int | None = None,
) -> None:
    """Decir en qué va el trabajo, sin que un fallo del aviso lo interrumpa.

    El detalle y el contador no son adorno: una etapa que sólo dice su nombre
    dice lo mismo en el primer archivo que en el número 287, y desde la pantalla
    eso es indistinguible de estar colgado.
    """
    from ...adapters.queue_progress import QueueProgressReporter

    queue = payload.get("progress_queue")
    if queue is None:
        return
    # Y lo que lleva gastado hasta aquí, cuando algo se gastó: la pantalla lo
    # enseña en vivo y no sólo al final, que es cuando ya no hay nada que decidir.
    consumo = payload.get("consumo")
    cuentas = consumo.as_dict() if isinstance(consumo, Consumo) and not consumo.vacio else None
    try:
        QueueProgressReporter(queue, payload["job_id"]).emit(
            ProgressEvent(
                stage=stage, page_count=page_count, detail=detail, done=done, total=total,
                consumo=cuentas,
            )
        )
    except Exception:  # noqa: BLE001 - la telemetría nunca rompe el trabajo
        logger.debug("no se pudo anunciar la etapa %s", stage, exc_info=True)


def _ubicacion(settings: dict):
    """La ubicación física del lote, que el PDF no puede saber."""
    from ...application.fuid import Ubicacion

    return Ubicacion(
        caja=settings.get("fuid_caja") or "N/A",
        otro=settings.get("fuid_otro") or "N/A",
        codigo_trd=settings.get("fuid_codigo_trd") or "N/A",
    )


def _boundary_oracle(settings: dict, choice=None, consumo: Consumo | None = None):
    """Quién juzga las costuras que la estructura no pudo decidir.

    Con una elección explícita se respeta o no se contesta. Nunca se sustituye:
    si alguien pidió Mistral y el sistema contestara con Gemini, el informe
    mentiría sobre quién decidió los cortes, y un corte cuya autoría no se puede
    rastrear no sirve para decidir si el criterio funciona. Pedir un proveedor
    sin su llave devuelve el oráculo nulo -- la API contesta 422 antes de llegar
    acá, así que esto es la última defensa y no el camino previsto.

    Sin elección se recorre `_CASCADE`, que es el comportamiento que había antes
    de que la elección existiera.

    Y sin ninguna llave se devuelve el oráculo nulo en vez de fallar: la caja se
    separa por todo lo que la estructura decide sola y lo demás va a revisión.

    Eso no es un modo degradado aceptable, y conviene decirlo con el número
    medido en vez de con una impresión. Sobre el expediente de 125 páginas contra
    el que se construyó este camino, la estructura resolvió 32 de 124 costuras
    -- el 25%, no "la mayor parte" -- y las 92 restantes quedaron sin decidir. Al
    tratarse una costura dudosa como corte, la caja salió como 109 documentos, de
    los cuales 100 son de una sola página.

    Dicho de otro modo: en una caja de correspondencia sin paginación impresa el
    modelo no es una optimización, es la pieza que hace utilizable el resultado.
    Sin llave el operador recibe algo que tiene que rearmar a mano casi entero, y
    la cola de revisión se lo dice honestamente, pero se lo dice 92 veces.
    """
    from ...adapters.boundary_prompt import NullBoundaryOracle
    from ...application.oracle import OracleChoice

    eleccion = OracleChoice.AUTO if choice is None else OracleChoice(choice)

    if eleccion is not OracleChoice.AUTO:
        if not eleccion.is_available(settings):
            logger.warning(
                "se pidió %s y no hay %s; las costuras dudosas van a revisión",
                eleccion.value,
                eleccion.env_var,
            )
            return NullBoundaryOracle()
        return _oracle_named(eleccion.value, settings, consumo)

    for candidate in _CASCADE:
        if OracleChoice(candidate).is_available(settings):
            return _oracle_named(candidate, settings, consumo)

    return NullBoundaryOracle()


def _oracle_named(name: str, settings: dict, consumo: Consumo | None = None):
    """Construye un proveedor concreto, ya sabiendo que su llave está puesta."""
    if name == "claude":
        from anthropic import Anthropic

        from ...adapters.claude_boundary import ClaudeBoundaryOracle

        return ClaudeBoundaryOracle(
            client=Anthropic(api_key=str(settings.get("anthropic_api_key"))),
            consumo=consumo,
        )

    if name == "gemini":
        from ...adapters.gemini_boundary import GeminiBoundaryOracle

        return GeminiBoundaryOracle(
            api_key=str(settings.get("gemini_api_key")), consumo=consumo
        )

    from ...adapters.mistral_boundary import MistralBoundaryOracle

    return MistralBoundaryOracle(
        api_key=str(settings.get("mistral_api_key")), consumo=consumo
    )
