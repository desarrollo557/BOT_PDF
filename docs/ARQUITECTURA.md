# Arquitectura

El sistema toma un PDF con varios documentos adentro y devuelve un archivo por
documento, más el inventario de lo que hizo. Tres piezas: un backend de Python,
un front de SvelteKit y una base MySQL opcional. Corren en la misma máquina que
el operador usa.

```
web/  SvelteKit ──HTTP+SSE──▶ backend/  FastAPI ──▶ db/  MySQL
                                  │
                                  └──▶ inventory.jsonl  (respaldo sin base)
```

## Cuatro maneras de decidir dónde empieza un documento

Ésta es la decisión central del sistema y la que separa sus cuatro caminos. Lo
que cambia entre ellos es **cómo se agrupan las páginas**; a partir de ahí todos
hacen lo mismo.

| Ruta | Qué agrupa las páginas | Cuándo entra |
|---|---|---|
| **Resoluciones** | Un número impreso que manda hasta que aparece otro | El papel dice ser una resolución |
| **Diplomas** | Un folio por cara del libro | El papel dice ser un registro de diplomas |
| **Matrículas** | Una persona por carátula | El papel dice ser un legajo académico |
| **Correspondencia** | La continuidad: si la hoja siguiente sigue a la anterior | El operador lo pide, o el papel no dice ser nada de lo anterior |

`api/worker.py` elige entre ellas leyendo lo que está impreso en una muestra de
doce páginas (`domain/doctype.py`), nunca el nombre del archivo. Y hay un desvío
que evita el peor resultado posible: si las páginas no dicen ser nada conocido y
se pidió «Dividir en documentos», se separa por continuidad en vez de buscar un
número que no existe. Sin él, una caja de correspondencia de 125 páginas salía
como un solo documento de la 37 a la 125.

## La ruta de correspondencia, hoja por hoja

Es la que corre sobre el corpus real y la más elaborada. Una caja de escaneos no
es un documento: son docenas, barajados, y el radicado que llevan todas sus
hojas identifica el expediente, no el papel. Así que se decide **costura por
costura**.

`domain/fingerprint.py` reduce cada hoja a los pocos hechos que discuten sus
bordes: su propia paginación («3 de 5»), el consecutivo, el rótulo que se da a
sí misma, las marcas de apertura, los ordinales con que numera sus párrafos, los
identificadores del asunto, el folio manuscrito, el tamaño del papel, si es
densa y si se pudo leer. Comprimir la página a eso no es sólo más barato de
enviar a un modelo: en un expediente de 125 páginas fueron 4.616 tokens frente a
37.200, y una petición en vez de 124.

`domain/segmentation.py` juzga cada costura con esas huellas, en un orden de
prioridad que está medido sobre expedientes reales:

1. la paginación que la hoja declara — «1 de 5» abre, «2 de 4» nunca abre;
2. el consecutivo del documento;
3. los ordinales de sus párrafos, leídos por posición y no por su máximo;
4. los identificadores compartidos, descartando los que lleva media caja;
5. los anexos, y la cédula comprobada contra la hoja anterior;
6. el rótulo propio, y **sólo cuando cambia**: dos hojas que se titulan igual
   son el mismo documento;
7. la cabecera de apertura, el tamaño de la hoja, la cadena del folio, la
   oración cortada;
8. y al final, dos reglas que se apoyan en ausencias.

**No hay ninguna regla sobre el código de expediente.** Lo comparten las 125
páginas de una caja, y leerlo como continuidad la suelda entera. Lo mismo vale
para el NIC y para la cédula del titular: identifican al sujeto, no al papel.

Lo que ninguna regla resuelve **une** las páginas y declara la costura para
revisión. Nunca corta: partir una unidad documental no deja rastro de que
existió, y unir de más deja una hoja señalada por nombre en la cola de revisión.
Las costuras que quedan sin decidir son las únicas que se le pagan a un modelo,
todas en una sola petición.

## Lo que las cuatro rutas comparten

Decididos los grupos, `application/entrega.py` hace el resto, y lo hace en un
solo sitio a propósito: tenerlo repetido en las cuatro rutas es lo que provocó
una tanda entera de fallos en que un arreglo entraba por una y no por las otras.

1. **Describir** cada unidad: qué clase de papel es y de cuándo.
2. **Comprobar** que cada página cae en exactamente una unidad, antes de
   escribir un solo archivo.
3. **Escribir** un PDF por unidad, nombrando lo que no se pueda escribir.
4. **Inventariar** lo que quedó en el disco: una fila por archivo que existe.

### Qué clase de papel es

`application/clasificacion.py` lo decide con `domain/catalogo.py`, que es el
listado cerrado de tipos del archivo del cliente. Corre **después** del corte,
nunca antes: preguntarle a una caja de cien hojas de qué tipo es no tiene
respuesta, y sobre un documento que ya tiene bordes casi siempre está contestada
en la propia hoja.

Cuatro fuentes, de la más directa a la más débil, en este orden:

1. **el asunto** que el papel declara, cuando abre su renglón;
2. **el encabezado**, si ocupa un renglón para él solo;
3. **una mención** en el cuerpo;
4. **el contexto** — el tipo del documento anterior — sólo para una unidad corta
   que no dice nada de sí misma.

Lo que no se reconoce sale sin tipo, que es lo honesto: un tercio de una caja
real no lleva rótulo legible, y llamarla «FACTURA» porque la palabra salía en el
cuerpo sería escribir en el disco algo que nadie comprobó.

### De cuándo es

`domain/fechas.py` busca la fecha más reciente del documento **entero** — la
fecha extrema final del FUID. Lo difícil no es reconocer una fecha sino
descartar las que sólo se citan: un recurso nombra la Ley 142 de 1994 y la
Sentencia T-1204 de 2001, y de 214 fechas de un expediente real 49 eran citas
así.

## El backend, por capas

```
        api  ──▶  adapters  ──▶  application  ──▶  domain
        (HTTP)    (mundo real)   (casos de uso)    (reglas)
```

`domain/` no importa nada más que la biblioteca estándar. Eso es lo que mantiene
las reglas comprobables en microsegundos y portables si el volumen exige otro
runtime. `scripts/check_layers.py` lo verifica en cada PR: prohíbe once paquetes
de terceros dentro de `domain/` y `application/`, y obliga a que las
dependencias apunten hacia adentro.

| Capa | Qué vive ahí |
|---|---|
| `domain/` | `fingerprint`, `segmentation`, `catalogo`, `tipo_documental`, `fechas`, `anchor`, `extraction`, `scoring`, `grouping`, `doctype`, `legibility`, `naming`, `validation` |
| `application/` | `entrega`, `clasificacion`, `inventory`, `informe`, `segment_document`, `process_document`, `inventory_document`, `pipeline`, `fuid`, `task`, `control`, `ports` |
| `adapters/` | PyMuPDF, Tesseract, Claude/Gemini/Mistral, MySQL, openpyxl, JSONL |
| `api/` | FastAPI, pool de workers, SSE, corridas de carpeta, janitor |

`application/ports.py` declara como `Protocol` lo que el caso de uso necesita
del mundo —una fuente de páginas, un OCR, un oráculo, un ensamblador, un
inventario— sin saber quién lo implementa.

## La cascada de costo, en la ruta de resoluciones

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

La ruta de correspondencia no usa esta cascada: decide sobre la capa de texto y
la geometría de los renglones, sin OCR ni visión, y por eso una caja de cien
páginas se resuelve en segundos.

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

## El inventario

Tres cosas distintas que conviene no confundir:

- **La planilla del documento** (`__inventario.xlsx`) se escribe sola al
  terminar, junto a los PDF que describe: número, tipo documental, fecha,
  páginas de origen, archivo generado y carpeta de destino.
- **El FUID** es la planilla oficial FO-GD-008 de la Universidad, que se rellena
  sobre la plantilla real y se pide aparte.
- **El libro mayor** es el registro durable de cada archivo producido, con su
  tipo, su fecha y el NIC de su expediente. Sobrevive a limpiar la pantalla, que
  es lo que lo hace la constancia de que el trabajo ocurrió.

Detrás del libro mayor puede haber MySQL o un archivo JSONL, y la pantalla no
distingue cuál. Manda la presencia de contraseña: sin `RESOLUTIONS_DB_PASSWORD`
se escribe en `data/inventory.jsonl`.

## El front

SvelteKit con estado en runas (`*.svelte.ts`). Tres pantallas, un verbo cada
una: **Procesar** hace el trabajo, **Archivo** encuentra lo que salió,
**Revisión** arregla lo que quedó dudoso. Consume la API por HTTP y recibe el
progreso por `/api/events` (SSE).

## La base

`db/schema.sql`: siete tablas, cuatro vistas, once claves foráneas.

```
operador ──< corrida ──< documento ──< resolucion ──< entrega
                              │             ▲
                              ├──< revision ┘
                              └──< correccion
```

No hay una fila por página —serían 104 millones al año para contestar lo que
contestan cinco contadores por documento— y sí hay una fila por unidad
producida, que es la que alguien va a buscar dentro de tres años. Sobre una base
que ya existe, los cambios de esquema van en `db/migraciones/`.

## Qué valida CI

`.github/workflows/ci.yml`, en cada PR:

1. **Arquitectura** — las capas siguen en su sitio
2. **Backend** — `ruff check` y toda la suite de `pytest`, con Tesseract instalado
3. **Front** — `svelte-check`, `vitest` y el build de producción
4. **Base** — `db/schema.sql` se aplica sobre una MySQL 8.4 vacía

`.github/workflows/pr-guard.yml` valida el flujo de ramas, el título y la
descripción del PR. El detalle está en [`RAMAS.md`](RAMAS.md) y en
[`../CONTRIBUTING.md`](../CONTRIBUTING.md).
