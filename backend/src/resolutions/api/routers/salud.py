"""Si el servicio está vivo y qué sabe hacer."""

from __future__ import annotations

from fastapi import APIRouter

from ...adapters.tesseract_ocr import tesseract_disponible
from ...application.lectura import available_readers
from ...application.oracle import available_oracles
from ...application.tipo_pedido import tipos_declarables
from .. import native_picker
from ..contexto import Ctx

router = APIRouter()


#: Bumped whenever this file gains an endpoint the front end depends on.
#:
#: A Python process holds the code it imported at start-up, so a service left
#: running across an update answers 404 to every new route and 405 to every new
#: method -- which reads as a broken request rather than as a stale service.
#: The screen compares this against what it was built for and says so plainly.
API_REVISION = 25

#: What this revision can do, so the screen can name what is missing rather than
#: only that something is.
API_FEATURES = (
    "inventory",
    "inventory-xlsx",
    "inventory-backend",
    "documents",
    "folder-runs",
    "cache-sweep",
    "browse",
    "native-picker",
    "job-delete",
    "output-edit",
    "document-edit",
    "document-bulk-delete",
    "document-detail",
    "inventory-task",
    "job-fuid",
    "job-control",
    # Levantar el FUID de un documento ya procesado, y pedir una carpeta con la
    # misma acción que una subida.
    "job-fuid-make",
    "folder-task",
    # Quitar de la pantalla una carpeta ya terminada, o todas de una vez.
    "folder-run-clear",
    # Separar una caja revuelta existía en la API desde antes y ninguna pantalla
    # podía descubrirlo: la revisión subía sin decir qué traía de nuevo, que es
    # exactamente lo que esta lista existe para evitar.
    "segment-task",
    # Y elegir a qué modelo se le pregunta por los bordes, en vez de heredar el
    # que la cascada encuentre primero.
    "oracle-choice",
    # Que haya perfiles y que el perfil decida qué se deja hacer. La pantalla
    # lo necesita para saber si hay dónde entrar: contra un servicio sin esto,
    # la pantalla de entrada pediría algo que nadie va a leer.
    "perfiles",
    # El FUID como tabla, para mirarlo sin descargar el Excel. Es lo que hace
    # utilizable el perfil que no descarga: sin esto, restringir la descarga
    # sería quitarle el inventario a quien tiene que revisarlo.
    "fuid-tabla",
    # Y abandonar el FUID que se está levantando, que hasta ahora no se podía:
    # su carga útil viajaba sin canal de control.
    "fuid-cancel",
    # Entregar una caja de correspondencia con un archivo por mes en vez de
    # uno por documento. Un servicio sin esto ignoraría el parámetro en
    # silencio y la caja saldría como siempre, que es peor que un aviso.
    "agrupar-por-mes",
    # Y con un archivo por trámite: la solicitud, cada reclamación con su
    # respuesta y su notificación, reconocidas por el radicado y la fecha.
    "agrupar-por-tramite",
    # Entrar como «siar», sin contraseña. Contra un servicio anterior la
    # pantalla de entrada manda un usuario que el servicio no sabe leer, y el
    # aviso tiene que poder decir qué falta en vez de un error de campos.
    "usuario-siar",
    # Inventariar actas de consejo: una fila por PDF con el acta, su fecha, el
    # folio inicial y el final, cuántos folios son y el resumen.
    "acta-consejo",
    # Y bajar el Excel de las actas de una carpeta entera, con una fila por PDF.
    "folder-inventario",
    # Cada documento recuerda de qué carpeta o lote salió, y el Excel general
    # de una carpeta se baja desde el Archivo aunque la corrida ya no esté.
    "origenes",
    # Dividir un libro de actas de consejo: una carpeta por sesión y un PDF por
    # pieza -- portada, citación, asistencia, acta y cada anexo --.
    "acta-piezas",
    # Los folios de un libro de actas encadenados acta con acta, y la lista de
    # los PDF y el Excel de cada trabajo para bajarlos desde su tarjeta.
    "folios-encadenados",
    "archivos-del-trabajo",
    # El patrón de cada tipo: sugerir qué es un PDF o una carpeta antes de
    # procesarla, y desviar a su habilidad lo que no es lo declarado.
    "reconocer",
    # Elegir cuántos archivos a la vez, al subir y al lanzar una carpeta.
    "paralelo",
    # El rendimiento del equipo y del bot, en vivo (GET /api/rendimiento).
    "rendimiento",
)

@router.get("/api/health")
async def health(ctx: Ctx) -> dict[str, object]:
    return {
        "status": "ok",
        "api_revision": API_REVISION,
        "features": list(API_FEATURES),
        "document_workers": ctx.settings.document_workers,
        "page_workers": ctx.settings.page_workers,
        # Cuántos documentos de carpeta van a la vez y cuántos corren ahora.
        "folder_documents": ctx.settings.folder_documents,
        "documentos_en_curso": ctx.planificador.en_curso if ctx.planificador else 0,
        "ia_a_la_vez": ctx.settings.ia_a_la_vez,
        "vision": "claude" if ctx.settings.anthropic_api_key else "disabled",
        # De cada modelo, si hay llave para pedirlo. Con esto la pantalla
        # deshabilita lo que no se puede pedir y dice por qué, en vez de
        # ofrecerlo y cosechar un 422 cuando el operador ya eligió.
        "oracles": available_oracles(ctx.settings.as_worker_payload()),
        # Con qué se puede leer el papel en este servicio. Lo mismo que arriba
        # pero para el paso anterior: sin lectura no hay nada que juzgar.
        "readers": available_readers(ctx.settings.as_worker_payload()),
        # Y si está el motor local, que es el que lee gratis. Sin él nada falla
        # a la vista: se paga en el remoto o sale vacío (2026-10-27).
        "tesseract": tesseract_disponible(),
        # Qué clases de documento se pueden declarar al cargar. Sale de aquí y
        # no escrito a mano en el front para que añadir una sea una línea en un
        # solo archivo.
        "document_types": tipos_declarables(),
        "native_picker": native_picker.available(),
        "inventory_backend": ctx.inventory_backend,
        "queued": ctx.registry.pending,
        "queue_limit": ctx.settings.queue_limit,
    }
