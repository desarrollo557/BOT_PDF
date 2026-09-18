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
    #: A dónde acabará la copia en una corrida sobre carpeta local.
    delivered_to: str | None
    operator: str | None
    #: Dónde se anota lo que este trabajo le pide a los proveedores de pago.
    #: Uno por trabajo y compartido por todos los adaptadores que el taller
    #: construya, para que el informe pueda decir cuánto costó el documento y
    #: no cuánto costó cada llamada por separado.
    consumo: Consumo = field(default_factory=Consumo)

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
            delivered_to=payload.get("destination"),
            operator=payload.get("operator"),
            # El despachador lo crea antes de elegir ruta y lo deja en el
            # payload, para poder adjuntarlo al informe cuando la ruta vuelva.
            consumo=(
                payload["consumo"]
                if isinstance(payload.get("consumo"), Consumo)
                else Consumo(precio_por_pagina=settings.get("precio_ocr_por_pagina"))
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
        from ...application.lectura import LecturaChoice

        local = HeaderAndPageOcr(language=self.settings["ocr_language"])
        if LecturaChoice.parse(self.lectura_choice) is not LecturaChoice.MISTRAL:
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
            local=local, remoto=MistralOcr(api_key=llave, consumo=self.consumo)
        )

    def vision(self):
        """El modelo de visión para el último peldaño de la cascada, o nadie."""
        from ...adapters.claude_vision import (
            ClaudeVisionConfig,
            ClaudeVisionOracle,
            NullVisionOracle,
        )

        api_key = self.settings.get("anthropic_api_key")
        if not api_key:
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
        return _boundary_oracle(self.settings, self.oracle_choice, consumo=self.consumo)

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
