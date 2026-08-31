# Arquitectura

El sistema toma un PDF con muchas resoluciones adentro y devuelve un archivo por
resolución, más el inventario de lo que hizo. Tres piezas: un backend de Python,
un front de SvelteKit y una base MySQL. Corren en la misma máquina que el
operador usa.

```
web/  SvelteKit ──HTTP+SSE──▶ backend/  FastAPI ──▶ db/  MySQL
                                  │
                                  └──▶ inventory.jsonl  (respaldo sin base)
```

## El backend, por capas

`backend/src/resolutions` está partido en cuatro, y las dependencias sólo van
hacia adentro. `scripts/check_layers.py` lo verifica en cada PR.

```
        api  ──▶  adapters  ──▶  application  ──▶  domain
        (HTTP)    (mundo real)   (casos de uso)    (reglas)
```

### `domain/` — las reglas, sin infraestructura

Cero dependencias de terceros. Es lo que decide qué es una resolución y qué
páginas le pertenecen:

| Módulo | Qué resuelve |
|---|---|
| `anchor.py` | Encuentra la palabra ancla tolerando el ruido del OCR, con distancia de Damerau-Levenshtein |
| `resolution_code.py` | Qué es un número de resolución válido y qué no (el `de 2023` nunca es el número) |
| `extraction.py` | Saca los candidatos de una página |
| `scoring.py` | Elige entre candidatos por la estructura del encabezado, no por si está en mayúsculas |
| `grouping.py` | Agrupa páginas por código: una página sin número pertenece a la última que sí lo tenía |
| `title.py`, `naming.py` | El asunto y el nombre del archivo de salida |

Se prueba sin instalar PyMuPDF, ni Tesseract, ni FastAPI. Esa es la razón de la
regla: son las reglas del negocio de la universidad y no pueden quedar atadas a
una librería.

### `application/` — los casos de uso

`process_document.py` orquesta un documento de punta a punta. `pipeline.py` es
la cascada de clasificación. `ports.py` declara, como `Protocol`, lo que el caso
de uso necesita del mundo: una fuente de páginas, un motor de OCR, un oráculo de
visión, un ensamblador, un inventario. No sabe quién los implementa.

### `adapters/` — las implementaciones

Uno por puerto, cada uno reemplazable: `pymupdf_source` y `pymupdf_assembler`
para leer y escribir PDF, `tesseract_ocr`, `claude_vision`, `queue_progress`
para la telemetría, y tres inventarios — `mysql_inventory` (la base),
`ledger` (JSONL, el respaldo cuando no hay MySQL) y `excel_inventory`.

### `api/` — el borde HTTP

`main.py` expone los endpoints; `jobs.py` mantiene el registro de trabajos;
`worker.py` es el proceso que procesa un documento; `janitor.py` recupera disco
cuando la cola está vacía; `folders.py` lista rutas reales del disco para el
picker; `settings.py` concentra la configuración, toda por variable de entorno.

## La cascada de costo

400.000 páginas al día no se pueden leer con un modelo. Cada peldaño ve sólo lo
que el anterior no pudo contestar:

| | Qué hace | Cuesta |
|---|---|---|
| L0 | Capa de texto embebida y ancla difusa | ~0 |
| L1 | OCR de la banda del encabezado (~28% de los píxeles) | CPU |
| L2 | OCR de la página completa | CPU |
| L3 | Contexto de secuencia: si los vecinos coinciden, no hace falta nadie | ~0 |
| L4 | Modelo de visión sobre recortes, en lotes de doce | tokens |

Cada corrida reporta qué fracción de páginas llegó a L4. La cifra se mide, no se
estima.

## Concurrencia

Un proceso del sistema operativo por documento —partir un PDF de 400 páginas es
trabajo de CPU y los procesos son la única forma de saltarse el GIL— y ocho
hilos por proceso para las páginas, porque el código nativo del OCR suelta el
GIL. Las subidas van de a tres: cincuenta transferencias en paralelo sólo se
estorban entre sí.

Cada página emite un evento por una cola compartida. La API los pliega y empuja
cuadros agrupados cuatro veces por segundo: un documento de 400 páginas produce
400 eventos y nunca 400 cuadros en el navegador.

## Aislamiento de fallas

Tres niveles, para que nada se propague:

- una **página** ilegible se marca y va a revisión; las otras 399 se procesan
- un **documento** que falla no detiene su lote
- la **telemetría** que se rompe nunca interrumpe el trabajo que describía

## El front

SvelteKit con estado en runas (`*.svelte.ts`). Tres pantallas, un verbo cada
una: **Procesar** hace el trabajo, **Archivo** encuentra lo que salió,
**Revisión** arregla lo que quedó dudoso. Consume la API por HTTP y recibe el
progreso por `/api/events` (SSE). La consola tipo CMD va vertical, a la derecha,
visible: es donde el operador ve la corrida por dentro.

## La base

`db/schema.sql`: siete tablas, cuatro vistas, once claves foráneas.

```
operador ──< corrida ──< documento ──< resolucion ──< entrega
                              │             ▲
                              ├──< revision ┘
                              └──< correccion
```

No hay una fila por página —serían 104 millones al año para contestar lo que
contestan cinco contadores por documento— y sí hay una fila por resolución
producida, que es la unidad que alguien va a buscar dentro de tres años.
`db/README.md` tiene el detalle y los cálculos de volumen.

## Qué valida CI

`.github/workflows/ci.yml`, en cada PR:

1. **Arquitectura** — las capas siguen en su sitio
2. **Backend** — `ruff check` y toda la suite de `pytest`, con Tesseract instalado
3. **Front** — `svelte-check`, `vitest` y el build de producción
4. **Base** — `db/schema.sql` se aplica sobre una MySQL 8.4 vacía

`.github/workflows/pr-guard.yml` valida el flujo de ramas, el título y la
descripción del PR. El detalle está en [`RAMAS.md`](RAMAS.md) y en
[`../CONTRIBUTING.md`](../CONTRIBUTING.md).
