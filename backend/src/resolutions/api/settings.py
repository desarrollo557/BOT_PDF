from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path(os.environ.get("RESOLUTIONS_DATA_DIR", "./data")).resolve()


def _float_opcional(name: str) -> float | None:
    """Un número decimal del entorno, o nada. Un valor ilegible es nada, no cero."""
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def _int_opcional(name: str) -> int | None:
    """Un entero del entorno, o nada. Un valor ilegible es nada, no cero.

    Nada y cero son cosas distintas aquí: en un tope de páginas, "nada"
    significa sin tope y cero significa no gastar ni una. Un `RESOLUTIONS_TOPE_
    PAGINAS_OCR=abc` que se interpretara como cero apagaría el motor de pago en
    silencio, que es exactamente la clase de degradación callada que esta casa
    no admite.
    """
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _int(name: str, fallback: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return fallback


def _float(name: str, fallback: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return fallback


@dataclass(frozen=True, slots=True)
class Settings:
    upload_dir: Path = DEFAULT_ROOT / "uploads"
    output_dir: Path = DEFAULT_ROOT / "outputs"

    #: Documents processed concurrently. One OS process each, because a 400-page
    #: PDF is CPU-bound work and processes are the only way past the GIL.
    document_workers: int = max(1, (os.cpu_count() or 4) - 1)

    #: Threads inside a worker, fanning pages out across the OCR engine. Native
    #: code releases the GIL, so this scales without another process boundary.
    #: Es el tope de un documento solo: con varios a la vez el planificador
    #: reparte los hilos de la máquina entre ellos (ver `planificador.py`).
    page_workers: int = 8

    #: Cuántos documentos de carpeta se procesan a la vez, sumando todas las
    #: carpetas en marcha. Uno los ponía en fila y dejaba parados los demás
    #: procesos del pool: una carpeta de 103 PDF tardó 41 minutos con diez de
    #: once procesos sin trabajo. Por defecto, uno por cada cuatro hilos de la
    #: máquina -- tres en una de doce --, que deja hilos de OCR a cada uno.
    folder_documents: int = 0

    #: Cuántos PDF de una carpeta se verifican a la vez contra su constancia
    #: al recorrerla. Cada uno son unas cuantas lecturas del destino, y en el
    #: disco que Docker monta cada lectura tarda un milisegundo esperando, no
    #: trabajando: una tras otra, relanzar mil PDF ya entregados eran 16 s
    #: (2026-10-28). Uno lo deja en fila, como antes.
    verificar_a_la_vez: int = 8

    #: Cuántas llamadas a la IA de pago a la vez, sumando todos los documentos.
    #: Con varios documentos en paralelo cada uno pide las suyas, y el
    #: proveedor contesta 429 si se le pisa: este tope común marca el paso.
    ia_a_la_vez: int = 8

    #: Cuántas veces más se intenta un documento cuyo fallo no dice nada del
    #: papel -- la red que se cayó, el proceso del pool que murió, un tiempo
    #: agotado -- (ver `reintentos.py`). Cero lo apaga.
    reintentos: int = 2
    #: Cuántos segundos se espera antes del segundo intento; el tercero espera
    #: el triple. Da tiempo a que vuelva la red sin dejar la carpeta parada.
    espera_de_reintento: float = 15.0
    #: Cuántos minutos puede pasar un documento sin avanzar una página antes de
    #: darlo por atascado: se le ordena parar y se marca fallido, y la carpeta
    #: sigue. Generoso a propósito: escribir trescientos PDF o esperar a la IA
    #: tampoco produce avisos. Cero lo apaga. Por debajo, cada espera entre
    #: hilos tiene su propio tope de quince minutos (``control.TOPE_SIN_NOVEDAD``).
    minutos_sin_avance: float = 20.0
    #: Cuántos documentos procesa cada proceso del pool antes de cambiarlo por
    #: uno nuevo (``max_tasks_per_child``). Apagado (cero) por omisión: es la
    #: pieza del pool con más historia de cuelgues en CPython, y un pool colgado
    #: deja la carpeta parada sin un error. Se enciende con
    #: RESOLUTIONS_DOCUMENTOS_POR_PROCESO si la memoria crece en corridas de días.
    documentos_por_proceso: int = 0
    #: Cuántos documentos seguidos pueden fallar en una carpeta antes de
    #: pausarla. Diez seguidos casi nunca son diez papeles malos: es la red,
    #: el disco o la cuenta del proveedor, y seguir quemaría la carpeta entera
    #: en minutos. No la detiene: la pausa, sigue de uno en uno y los fallidos
    #: vuelven al final (ver `folders.py`). Cero lo apaga.
    fallos_seguidos: int = 10
    #: Cuántos segundos dura la primera pausa; cada pausa seguida dobla la
    #: anterior, hasta quince minutos.
    pausa_tras_fallos: float = 60.0
    #: Cuántas vueltas más se dan, al final de la carpeta, a los documentos que
    #: fallaron por algo que no dice nada del papel. Cero lo apaga.
    vueltas_de_reintento: int = 1
    #: Cuántos minutos se espera a que vuelva la carpeta de origen -- la unidad
    #: de red que se desconectó -- antes de dar la corrida por fallida.
    minutos_de_espera_del_origen: float = 30.0
    #: Cuántos documentos terminados de una carpeta se guardan enteros en la
    #: pantalla. Los más viejos salen del registro -- su fila sigue en los
    #: inventarios, que la corrida guarda aparte -- para que una carpeta de
    #: veinte mil PDF no se quede con el informe de cada uno en memoria.
    trabajos_en_memoria: int = 300
    #: Si, tras entregar un documento de carpeta, se borran sus PDF de la
    #: carpeta de salidas. La copia buena está en el destino; la de salidas
    #: duplica el disco (un millón de páginas son cientos de GB) pero es la que
    #: usa el Archivo para descargar o corregir un archivo suelto. Apagado por
    #: omisión.
    liberar_salidas: bool = False

    #: Documents in flight before the API pushes back. Not a limit on how much
    #: can be processed -- the pool drains it steadily -- only on how much may be
    #: accepted and not yet started, since each waiting job holds its upload on
    #: disk. Raise it freely; the memory per queued job is a few kilobytes.
    queue_limit: int = 10_000

    ocr_language: str = "spa"
    mosaic_size: int = 12
    anthropic_api_key: str | None = None
    vision_model: str = "claude-sonnet-5"

    #: La otra llave que puede juzgar las costuras de una caja revuelta. Se usa
    #: sólo cuando no hay llave de Anthropic: Claude puede cachear el prompt, que
    #: en una caja se paga una vez por página, y Gemini no. Sin ninguna de las
    #: dos el sistema sigue separando todo lo que la estructura decida sola.
    gemini_api_key: str | None = None

    #: La tercera, y la última en preferencia. No cachea el prompt como Claude ni
    #: trae la capa gratuita de Gemini, así que se usa cuando es la llave que
    #: hay. Sin ninguna de las tres el sistema sigue separando todo lo que la
    #: estructura decida sola.
    mistral_api_key: str | None = None

    #: Cuánto cuesta una página del OCR de pago, para estimar el gasto de un
    #: trabajo. Opcional a propósito: el precio cambia, varía por cuenta y por
    #: moneda, y una cifra inventada aquí sería la única de la pantalla que no
    #: sale de una medida. Sin él se enseñan páginas y tokens, que sí se miden.
    precio_ocr_por_pagina: float | None = None

    #: Cuántas páginas facturadas como máximo puede gastar **un trabajo**.
    #:
    #: ``None`` es sin tope, que es lo que había y sigue siendo lo normal. Se
    #: pone cuando importa más no pasarse de una cifra que leerlo todo: una caja
    #: son cientos de páginas y el motor remoto cobra por cada una, de modo que
    #: sin tope la única señal de que un trabajo se comió el crédito llegaba
    #: cuando el proveedor contestaba "sin presupuesto" en mitad del libro
    #: siguiente.
    #:
    #: Alcanzarlo no cancela nada: el motor de pago deja de pedirse y lo que
    #: falte se lee con el local. En un libro de diplomas eso significa que los
    #: documentos salen igual -- el corte sale de medir tinta y no necesita OCR
    #: -- sólo que nombrados por su folio o su orden en vez de por su cédula.
    tope_paginas_ocr: int | None = None

    #: Uploads are streamed to disk in chunks and never held in memory, so this
    #: bounds disk use rather than RAM. Four gigabytes covers a full archive box
    #: scanned at 300 dpi; set it higher when the scanner disagrees.
    max_upload_bytes: int = 4 * 1024 * 1024 * 1024

    #: How often the idle janitor looks for scratch to reclaim. It does nothing
    #: at all unless the queue is empty and something has changed since the last
    #: pass, so this is a poll of one integer comparison in the common case.
    sweep_seconds: float = 30.0

    #: The durable record of every resolution PDF ever produced. It outlives the
    #: job registry, so clearing the screen never erases the history of the work.
    ledger_path: Path = DEFAULT_ROOT / "inventory.jsonl"

    #: Quién está dado de alta y con qué perfil. Junto al libro mayor y por el
    #: mismo motivo: es el otro dato que tiene que sobrevivir a limpiar la
    #: pantalla, a reiniciar el servicio y a borrar las salidas.
    users_path: Path = DEFAULT_ROOT / "usuarios.jsonl"

    #: La plantilla oficial del FUID. Vacío significa la que viaja con el
    #: programa; se pone una ruta cuando la Universidad publique otra versión
    #: del formato y no se quiera esperar a un despliegue.
    fuid_template: str | None = None

    #: Datos de ubicación física que el PDF no puede saber y que se repiten en
    #: todas las filas de un lote. Lo que no se conoce va como N/A, que es lo
    #: que manda el instructivo del formato.
    #:
    #: La caja la dice la ruta del PDF en una corrida de carpeta («3220\\UPD…»).
    #: RESOLUTIONS_FUID_CAJA la fija para todo, cuando el archivo llega suelto.
    #: Valía «3269» por omisión, y esa caja de diplomas se colaba en todas.
    fuid_caja: str = ""
    fuid_otro: str = "N/A"
    fuid_codigo_trd: str = "N/A"
    fuid_oficina: str | None = None

    def __post_init__(self) -> None:
        # Cero es «lo que aguante la máquina»: uno por cada cuatro hilos, sin
        # pasar de los procesos del pool, que son quienes de verdad los leen.
        if self.folder_documents <= 0:
            por_defecto = max(1, min(self.document_workers, (os.cpu_count() or 4) // 4))
            object.__setattr__(self, "folder_documents", por_defecto)
        else:
            object.__setattr__(
                self, "folder_documents", min(self.folder_documents, self.document_workers)
            )
        object.__setattr__(self, "ia_a_la_vez", max(1, self.ia_a_la_vez))

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            upload_dir=Path(os.environ.get("RESOLUTIONS_UPLOAD_DIR", DEFAULT_ROOT / "uploads")),
            output_dir=Path(os.environ.get("RESOLUTIONS_OUTPUT_DIR", DEFAULT_ROOT / "outputs")),
            document_workers=_int("RESOLUTIONS_DOCUMENT_WORKERS", max(1, (os.cpu_count() or 4) - 1)),
            page_workers=_int("RESOLUTIONS_PAGE_WORKERS", 8),
            folder_documents=_int("RESOLUTIONS_FOLDER_DOCUMENTS", 0),
            verificar_a_la_vez=_int("RESOLUTIONS_VERIFICAR_A_LA_VEZ", 8),
            ia_a_la_vez=_int("RESOLUTIONS_IA_A_LA_VEZ", 8),
            queue_limit=_int("RESOLUTIONS_QUEUE_LIMIT", 10_000),
            reintentos=_int("RESOLUTIONS_REINTENTOS", 2),
            espera_de_reintento=_float("RESOLUTIONS_ESPERA_REINTENTO", 15.0),
            minutos_sin_avance=_float("RESOLUTIONS_MINUTOS_SIN_AVANCE", 20.0),
            documentos_por_proceso=_int("RESOLUTIONS_DOCUMENTOS_POR_PROCESO", 0),
            fallos_seguidos=_int("RESOLUTIONS_FALLOS_SEGUIDOS", 10),
            pausa_tras_fallos=_float("RESOLUTIONS_PAUSA_TRAS_FALLOS", 60.0),
            vueltas_de_reintento=_int("RESOLUTIONS_VUELTAS_DE_REINTENTO", 1),
            minutos_de_espera_del_origen=_float("RESOLUTIONS_ESPERA_DEL_ORIGEN", 30.0),
            trabajos_en_memoria=_int("RESOLUTIONS_TRABAJOS_EN_MEMORIA", 300),
            liberar_salidas=os.environ.get("RESOLUTIONS_LIBERAR_SALIDAS", "").strip().lower()
            in ("1", "si", "sí", "true", "yes"),
            ocr_language=os.environ.get("RESOLUTIONS_OCR_LANG", "spa"),
            mosaic_size=_int("RESOLUTIONS_MOSAIC_SIZE", 12),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            vision_model=os.environ.get("RESOLUTIONS_VISION_MODEL", "claude-sonnet-5"),
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
            mistral_api_key=os.environ.get("MISTRAL_API_KEY") or None,
            precio_ocr_por_pagina=_float_opcional("RESOLUTIONS_PRECIO_OCR_POR_PAGINA"),
            tope_paginas_ocr=_int_opcional("RESOLUTIONS_TOPE_PAGINAS_OCR"),
            max_upload_bytes=_int("RESOLUTIONS_MAX_UPLOAD_BYTES", 4 * 1024 * 1024 * 1024),
            ledger_path=Path(
                os.environ.get("RESOLUTIONS_LEDGER", DEFAULT_ROOT / "inventory.jsonl")
            ),
            users_path=Path(
                os.environ.get("RESOLUTIONS_USERS", DEFAULT_ROOT / "usuarios.jsonl")
            ),
            sweep_seconds=_float("RESOLUTIONS_SWEEP_SECONDS", 30.0),
            fuid_template=os.environ.get("RESOLUTIONS_FUID_TEMPLATE") or None,
            fuid_caja=os.environ.get("RESOLUTIONS_FUID_CAJA", ""),
            fuid_otro=os.environ.get("RESOLUTIONS_FUID_OTRO", "N/A"),
            fuid_codigo_trd=os.environ.get("RESOLUTIONS_FUID_TRD", "N/A"),
            fuid_oficina=os.environ.get("RESOLUTIONS_FUID_OFICINA") or None,
        )

    def ensure_directories(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.users_path.parent.mkdir(parents=True, exist_ok=True)

    def as_worker_payload(self) -> dict[str, object]:
        """Only what a worker process needs, and nothing that cannot be pickled."""
        return {
            "output_dir": str(self.output_dir),
            "page_workers": self.page_workers,
            "ocr_language": self.ocr_language,
            "mosaic_size": self.mosaic_size,
            "anthropic_api_key": self.anthropic_api_key,
            "vision_model": self.vision_model,
            "gemini_api_key": self.gemini_api_key,
            "mistral_api_key": self.mistral_api_key,
            "precio_ocr_por_pagina": self.precio_ocr_por_pagina,
            "tope_paginas_ocr": self.tope_paginas_ocr,
            "fuid_template": self.fuid_template,
            "fuid_caja": self.fuid_caja,
            "fuid_otro": self.fuid_otro,
            "fuid_codigo_trd": self.fuid_codigo_trd,
            "fuid_oficina": self.fuid_oficina,
        }
