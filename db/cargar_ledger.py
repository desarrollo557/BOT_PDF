"""Carga el registro JSONL existente en robotpdf.

El separador viene guardando cada resolución en `data/inventory.jsonl`. Este
script lo vuelca en el modelo relacional sin perder nada de lo que ya hay, y es
idempotente: volver a correrlo no duplica filas.

Las credenciales llegan por entorno, nunca por argumento ni escritas aquí. Un
argumento aparece en la lista de procesos de cualquiera que esté en la máquina.

    set MYSQL_PWD=...
    python db/cargar_ledger.py backend/data/inventory.jsonl
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    import pymysql
except ImportError:  # pragma: no cover - dependencia opcional
    print("Falta pymysql:  pip install pymysql", file=sys.stderr)
    raise SystemExit(2)


def connect():
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PWD", ""),
        database=os.environ.get("MYSQL_DB", "robotpdf"),
        charset="utf8mb4",
        autocommit=False,
    )


def when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None


def read(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # Una línea partida por un corte en seco cuesta una fila, nunca
                # la carga entera.
                print("  aviso: línea ilegible, se omite", file=sys.stderr)
    return rows


def load(path: Path) -> None:
    rows = read(path)
    if not rows:
        print("El registro está vacío; no hay nada que cargar.")
        return

    # El JSONL guarda una fila por resolución. El modelo guarda documentos, así
    # que primero se reagrupan por el trabajo que las produjo.
    by_job: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_job[row.get("job_id") or ""].append(row)

    connection = connect()
    inserted = {"operador": 0, "corrida": 0, "documento": 0, "resolucion": 0}
    skipped = 0

    try:
        with connection.cursor() as cursor:
            for job_id, items in by_job.items():
                first = items[0]

                cursor.execute(
                    "SELECT id FROM documento WHERE uuid = %s", (job_id[:32],)
                )
                if cursor.fetchone():
                    skipped += 1
                    continue

                operador_id = None
                nombre_operador = (first.get("operator") or "").strip()
                if nombre_operador:
                    cursor.execute(
                        "INSERT INTO operador (nombre) VALUES (%s) "
                        "ON DUPLICATE KEY UPDATE visto_ultimo = CURRENT_TIMESTAMP(3)",
                        (nombre_operador[:60],),
                    )
                    cursor.execute(
                        "SELECT id FROM operador WHERE nombre = %s", (nombre_operador[:60],)
                    )
                    operador_id = cursor.fetchone()[0]

                momento = when(first.get("recorded_at")) or datetime.now()
                paginas = int(first.get("source_pages") or 0)
                revision = int(first.get("review") or 0)

                # El registro histórico no distingue lotes de carpetas, así que
                # cada documento entra como su propia corrida individual. Decirlo
                # así es más honesto que inventar una agrupación que no existió.
                cursor.execute(
                    """
                    INSERT INTO corrida
                      (uuid, tipo, nombre, operador_id, estado, iniciada_en,
                       terminada_en, documentos, resoluciones, paginas, bytes_origen)
                    VALUES (%s, 'individual', %s, %s, 'terminada', %s, %s, 1, %s, %s, %s)
                    """,
                    (
                        uuid.uuid4().hex,
                        f"Carga histórica · {first.get('source_document') or ''}"[:160],
                        operador_id,
                        momento,
                        momento,
                        len(items),
                        paginas,
                        int(first.get("source_bytes") or 0),
                    ),
                )
                corrida_id = cursor.lastrowid
                inserted["corrida"] += 1

                cursor.execute(
                    """
                    INSERT INTO documento
                      (uuid, corrida_id, operador_id, nombre, bytes, estado,
                       iniciado_en, terminado_en, paginas, resoluciones, en_revision)
                    VALUES (%s, %s, %s, %s, %s, 'terminado', %s, %s, %s, %s, %s)
                    """,
                    (
                        (job_id or uuid.uuid4().hex)[:32],
                        corrida_id,
                        operador_id,
                        (first.get("source_document") or "sin nombre")[:255],
                        int(first.get("source_bytes") or 0),
                        momento,
                        momento,
                        paginas,
                        len(items),
                        revision,
                    ),
                )
                documento_id = cursor.lastrowid
                inserted["documento"] += 1

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
                            (item.get("title") or None),
                            (item.get("file_name") or "")[:255],
                            int(item.get("page_count") or 0),
                            int(item.get("first_page") or 0),
                            int(item.get("last_page") or 0),
                            (item.get("pages") or None),
                            when(item.get("recorded_at")) or momento,
                        ),
                    )
                    inserted["resolucion"] += cursor.rowcount

            cursor.execute("SELECT COUNT(*) FROM operador")
            inserted["operador"] = cursor.fetchone()[0]

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print("Cargado:")
    for table, count in inserted.items():
        print(f"  {table:<12} {count}")
    if skipped:
        print(f"  omitidos     {skipped} documentos que ya estaban")


if __name__ == "__main__":
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/data/inventory.jsonl")
    if not source.is_file():
        print(f"No existe: {source}", file=sys.stderr)
        raise SystemExit(1)
    load(source)
