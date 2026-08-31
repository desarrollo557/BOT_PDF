"""El inventario guardado en MySQL, en la base ``robotpdf``.

Hasta aquí el inventario vivía en un archivo JSONL y la base se llenaba después,
con un cargador por lotes. Eso significaba que la aplicación y la base decían
cosas distintas en cualquier momento intermedio, y que las vistas del modelo --
``v_inventario``, ``v_revision_pendiente``, ``v_produccion_diaria`` -- mostraban
un pasado y no lo que estaba pasando. Este almacén escribe cada resolución en el
momento en que se produce, así que la base es el sistema y no una copia.

Ninguna credencial vive aquí ni en ningún archivo del repositorio: la conexión
se arma con lo que haya en el entorno. Sin configuración, el servicio sigue
funcionando contra el archivo, que es lo correcto para una máquina de pruebas.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Any

from .ledger import InventoryReads

logger = logging.getLogger(__name__)

#: Cuánto se espera a la base antes de darla por caída. Corto a propósito: el
#: servicio atiende peticiones y no puede quedarse colgado de un socket.
CONNECT_TIMEOUT = 5


class InventoryUnavailable(RuntimeError):
    """No hay base configurada, o no se pudo hablar con ella."""


def settings_from_env(environ: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Los datos de conexión, tomados del entorno. ``None`` si no hay ninguno.

    ``RESOLUTIONS_DB_PASSWORD`` es la que decide: sin contraseña no se intenta
    conectar, porque un servicio que arranca contra una base equivocada es peor
    que uno que no arranca contra ninguna.
    """
    env = environ if environ is not None else dict(os.environ)
    password = env.get("RESOLUTIONS_DB_PASSWORD") or env.get("MYSQL_PWD")
    if not password:
        return None
    return {
        "host": env.get("RESOLUTIONS_DB_HOST", "127.0.0.1"),
        "port": int(env.get("RESOLUTIONS_DB_PORT", "3306")),
        "user": env.get("RESOLUTIONS_DB_USER", "robotpdf_app"),
        "password": password,
        "database": env.get("RESOLUTIONS_DB_NAME", "robotpdf"),
    }


def _at(value: str | None) -> datetime:
    """Un instante ISO del informe, como lo entiende MySQL."""
    if value:
        try:
            return datetime.fromisoformat(value).replace(tzinfo=None)
        except ValueError:
            pass
    return datetime.now()


def _compact(pages: list[int]) -> str:
    """Las páginas como rangos: ``1-3,8-9`` en vez de una lista larga."""
    if not pages:
        return ""
    ordered = sorted(set(pages))
    tramos: list[str] = []
    inicio = previo = ordered[0]
    for page in ordered[1:]:
        if page == previo + 1:
            previo = page
            continue
        tramos.append(f"{inicio}-{previo}" if inicio != previo else str(inicio))
        inicio = previo = page
    tramos.append(f"{inicio}-{previo}" if inicio != previo else str(inicio))
    return ",".join(tramos)


#: Una resolución y todo lo que la pantalla necesita saber de ella. La consulta
#: devuelve exactamente las mismas claves que el archivo JSONL, para que nada
#: aguas arriba tenga que saber de dónde salieron.
_ROWS_SQL = """
SELECT
    r.creada_en                          AS recorded_at,
    d.nombre                             AS source_document,
    r.codigo                             AS code,
    r.titulo                             AS title,
    r.archivo                            AS file_name,
    r.paginas                            AS page_count,
    r.pagina_desde                       AS first_page,
    r.pagina_hasta                       AS last_page,
    COALESCE(r.rango_paginas, '')        AS pages,
    d.uuid                               AS job_id,
    o.nombre                             AS operator,
    d.paginas                            AS source_pages,
    d.bytes                              AS source_bytes,
    d.en_revision                        AS review
FROM resolucion r
JOIN documento d ON d.id = r.documento_id
LEFT JOIN operador o ON o.id = d.operador_id
ORDER BY r.creada_en DESC, r.id DESC
"""


class MySQLInventory(InventoryReads):
    """El inventario, con MySQL como sistema de registro.

    Comparte con el almacén de archivo todo lo que se deduce de las filas, así
    que la pantalla no distingue cuál de los dos está detrás -- y las dos
    responden lo mismo a la misma pregunta, que es lo único que importa.
    """

    def __init__(self, settings: dict[str, Any], connector: Any | None = None) -> None:
        if connector is None:
            try:
                import pymysql
            except ImportError as error:  # pragma: no cover - depende del entorno
                raise InventoryUnavailable(
                    "Falta el conector de MySQL (pymysql) en el servicio"
                ) from error
            connector = pymysql
        self._connector = connector
        self._settings = settings
        self._lock = threading.Lock()

    # -- conexión --------------------------------------------------------------

    def _connect(self):
        return self._connector.connect(
            connect_timeout=CONNECT_TIMEOUT,
            charset="utf8mb4",
            autocommit=False,
            **self._settings,
        )

    def check(self) -> None:
        """Falla ruidosamente si la base no está. Se llama al arrancar."""
        try:
            connection = self._connect()
        except Exception as error:  # noqa: BLE001 - cualquier fallo es el mismo fallo
            raise InventoryUnavailable(f"No se pudo conectar a MySQL: {error}") from error
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM resolucion LIMIT 1")
        finally:
            connection.close()

    @property
    def describe(self) -> str:
        """Cómo nombrar esta conexión sin decir la contraseña."""
        s = self._settings
        return f"mysql://{s['user']}@{s['host']}:{s['port']}/{s['database']}"

    # -- escritura -------------------------------------------------------------

    def record(
        self,
        job_id: str,
        report: dict,
        operator: str | None = None,
        source_bytes: int = 0,
    ) -> int:
        """Graba un documento terminado y sus resoluciones. Devuelve cuántas."""
        inventory = report.get("inventory") or {}
        items = inventory.get("items") or []
        if not items:
            return 0

        source = inventory.get("source_document") or report.get("document") or ""
        pages = int(inventory.get("source_pages") or report.get("page_count") or 0)
        review = len(report.get("review_queue") or [])
        stats = report.get("stats") or {}
        provenance = stats.get("by_provenance") or {}
        moment = _at(inventory.get("recorded_at"))

        with self._lock:
            connection = self._connect()
            try:
                with connection.cursor() as cursor:
                    operador_id = self._operator_id(cursor, operator)
                    corrida_id = self._run_id(
                        cursor, source, operador_id, moment, len(items), pages, source_bytes
                    )
                    documento_id = self._document_id(
                        cursor,
                        job_id,
                        corrida_id,
                        operador_id,
                        source,
                        source_bytes,
                        moment,
                        pages,
                        len(items),
                        review,
                        report,
                        provenance,
                    )
                    written = 0
                    for item in items:
                        cursor.execute(
                            """
                            INSERT IGNORE INTO resolucion
                              (documento_id, codigo, titulo, archivo, paginas,
                               pagina_desde, pagina_hasta, rango_paginas, creada_en)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                documento_id,
                                (item.get("code") or "")[:32],
                                item.get("title") or None,
                                (item.get("file_name") or "")[:255],
                                int(item.get("page_count") or 0),
                                int(item.get("first_page") or 0),
                                int(item.get("last_page") or 0),
                                _compact(item.get("page_numbers") or []) or None,
                                moment,
                            ),
                        )
                        written += cursor.rowcount
                connection.commit()
                return written
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def _operator_id(self, cursor, name: str | None) -> int | None:
        if not name:
            return None
        cursor.execute(
            "INSERT INTO operador (nombre) VALUES (%s) "
            "ON DUPLICATE KEY UPDATE visto_ultimo = CURRENT_TIMESTAMP(3)",
            (name[:60],),
        )
        cursor.execute("SELECT id FROM operador WHERE nombre = %s", (name[:60],))
        found = cursor.fetchone()
        return found[0] if found else None

    def _run_id(
        self, cursor, source, operador_id, moment, resolutions, pages, source_bytes
    ) -> int:
        cursor.execute(
            """
            INSERT INTO corrida
              (uuid, tipo, nombre, operador_id, estado, iniciada_en, terminada_en,
               documentos, resoluciones, paginas, bytes_origen)
            VALUES (%s, 'individual', %s, %s, 'terminada', %s, %s, 1, %s, %s, %s)
            """,
            (uuid.uuid4().hex, source[:160], operador_id, moment, moment,
             resolutions, pages, source_bytes),
        )
        return cursor.lastrowid

    def _document_id(
        self, cursor, job_id, corrida_id, operador_id, source, source_bytes,
        moment, pages, resolutions, review, report, provenance,
    ) -> int:
        cursor.execute(
            """
            INSERT INTO documento
              (uuid, corrida_id, operador_id, nombre, bytes, estado,
               iniciado_en, terminado_en, paginas, resoluciones, en_revision,
               en_cuarentena, correcciones, pag_capa_texto, pag_ocr_banda,
               pag_ocr_total, pag_vision)
            VALUES (%s, %s, %s, %s, %s, 'terminado', %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              resoluciones = VALUES(resoluciones),
              en_revision  = VALUES(en_revision),
              terminado_en = VALUES(terminado_en)
            """,
            (
                (job_id or uuid.uuid4().hex)[:32],
                corrida_id,
                operador_id,
                (source or "sin nombre")[:255],
                source_bytes,
                moment,
                moment,
                pages,
                resolutions,
                review,
                len(report.get("quarantine") or []),
                len(report.get("repairs") or []),
                int(provenance.get("text_layer") or 0),
                int(provenance.get("ocr_band") or 0),
                int(provenance.get("ocr_full") or 0),
                int(provenance.get("vision") or 0),
            ),
        )
        if cursor.lastrowid:
            return cursor.lastrowid
        cursor.execute("SELECT id FROM documento WHERE uuid = %s", ((job_id or "")[:32],))
        return cursor.fetchone()[0]

    def update(self, job_id: str, file_name: str, changes: dict) -> dict | None:
        """Corrige una resolución ya grabada. Devuelve la fila como quedó."""
        campos, valores = [], []
        if "code" in changes:
            campos.append("codigo = %s")
            valores.append(str(changes["code"])[:32])
        if "title" in changes:
            campos.append("titulo = %s")
            valores.append(changes["title"] or None)
        if "file_name" in changes:
            campos.append("archivo = %s")
            valores.append(str(changes["file_name"])[:255])
        if not campos:
            return self._one(job_id, file_name)
        # Toda corrección queda marcada: el inventario tiene que poder decir qué
        # leyó la máquina y qué arregló una persona.
        campos.append("corregida = 1")

        with self._lock:
            connection = self._connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"UPDATE resolucion r JOIN documento d ON d.id = r.documento_id "
                        f"SET {', '.join(campos)} WHERE d.uuid = %s AND r.archivo = %s",
                        (*valores, job_id[:32], file_name),
                    )
                    changed = cursor.rowcount
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
        if not changed:
            return None
        return self._one(job_id, changes.get("file_name", file_name))

    def remove(self, job_id: str, file_name: str) -> dict | None:
        """Borra una resolución del inventario. Devuelve la fila que se fue."""
        gone = self._one(job_id, file_name)
        if gone is None:
            return None
        with self._lock:
            connection = self._connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE r FROM resolucion r JOIN documento d ON d.id = r.documento_id "
                        "WHERE d.uuid = %s AND r.archivo = %s",
                        (job_id[:32], file_name),
                    )
                    cursor.execute(
                        "UPDATE documento SET resoluciones = GREATEST(resoluciones - 1, 0) "
                        "WHERE uuid = %s",
                        (job_id[:32],),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
        return gone

    def remove_document(self, job_id: str) -> int:
        """Borra un documento entero del inventario. Devuelve filas eliminadas.

        Se borra la fila de ``documento``; las revisiones y correcciones se van
        con ella por las claves foráneas en cascada del esquema, que es donde esa
        regla tiene que vivir para que nadie la reimplemente distinto desde otro
        lado.
        """
        with self._lock:
            connection = self._connect()
            try:
                with connection.cursor() as cursor:
                    # Las resoluciones se borran a mano aunque la cascada las
                    # arrastraría igual: es la única forma de saber cuántas eran
                    # y poder decírselo a quien lo pidió.
                    cursor.execute(
                        "DELETE r FROM resolucion r JOIN documento d "
                        "ON d.id = r.documento_id WHERE d.uuid = %s",
                        (job_id[:32],),
                    )
                    resoluciones = cursor.rowcount
                    cursor.execute("DELETE FROM documento WHERE uuid = %s", (job_id[:32],))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
        return resoluciones

    def rename_document(self, job_id: str, source_document: str) -> int:
        """Cambia el nombre del documento de origen. Devuelve filas tocadas."""
        with self._lock:
            connection = self._connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE documento SET nombre = %s WHERE uuid = %s",
                        (source_document[:255], job_id[:32]),
                    )
                    cambiados = cursor.rowcount
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
        return cambiados

    # -- lectura ---------------------------------------------------------------

    def rows(self) -> list[dict]:
        """Cada resolución grabada, la más reciente primero."""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(_ROWS_SQL)
                columnas = [column[0] for column in cursor.description]
                return [self._row(dict(zip(columnas, fila, strict=False))) for fila in cursor.fetchall()]
        finally:
            connection.close()

    @staticmethod
    def _row(row: dict) -> dict:
        """La fila de MySQL con la forma exacta que ya usaba la pantalla."""
        recorded = row.get("recorded_at")
        row["recorded_at"] = recorded.isoformat() if hasattr(recorded, "isoformat") else ""
        for entero in ("page_count", "first_page", "last_page", "source_pages",
                       "source_bytes", "review"):
            row[entero] = int(row.get(entero) or 0)
        return row

    def _one(self, job_id: str, file_name: str) -> dict | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    _ROWS_SQL.replace(
                        "ORDER BY", "WHERE d.uuid = %s AND r.archivo = %s ORDER BY"
                    ),
                    (job_id[:32], file_name),
                )
                fila = cursor.fetchone()
                if fila is None:
                    return None
                columnas = [column[0] for column in cursor.description]
                return self._row(dict(zip(columnas, fila, strict=False)))
        finally:
            connection.close()
