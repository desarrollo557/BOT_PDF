# robotpdf — modelo de datos

MySQL 8+ / InnoDB / `utf8mb4_0900_ai_ci`.

```
operador ──< corrida ──< documento ──< resolucion ──< entrega
                              │             ▲
                              ├──< revision ┘
                              └──< correccion
```

Siete tablas, cuatro vistas, once claves foráneas. `db/schema.sql` lo crea todo
desde cero; `db/cargar_ledger.py` vuelca el registro JSONL existente.

## La escala manda

400.000 páginas al día. Con ~20 páginas por documento y ~1 resolución cada 4
páginas, al año sobre 260 días hábiles:

| tabla | filas/año | con índices |
|---|---:|---:|
| `documento` | 5,2 M | ~1,2 GB |
| `resolucion` | 26,0 M | ~7,0 GB |
| `revision` | 5,2 M | ~0,8 GB |

Dos decisiones sostienen eso.

**No hay una fila por página.** Serían 104 M de filas al año para responder
preguntas que contestan cinco contadores (`pag_capa_texto`, `pag_ocr_banda`,
`pag_ocr_total`, `pag_vision`, `pag_ilegible`). Lo que sí se guarda es la
excepción: la página que fue a revisión, la que se corrigió. `pagina_leida`
queda comentada al final del esquema, particionada por mes, para cuando haga
falta análisis por página — con purga por partición, que es instantánea, en vez
de un `DELETE` de ocho millones de filas que no lo es.

**La clave primaria es un `BIGINT` autoincremental, no el UUID.** InnoDB agrupa
físicamente las filas por la clave primaria: con un UUID aleatorio cada
inserción cae en una página distinta del disco, y esa clave se copia dentro de
cada índice secundario. El UUID vive igual, como columna única, porque es el
identificador que ya usa la API.

## Lo que se denormaliza, y por qué

`documento` lleva sus propios contadores (`resoluciones`, `paginas`,
`en_revision`, `bytes`) y `corrida` lleva los suyos. No es descuido: la tarjeta
del archivo muestra los cuatro, y calcularlos sería cuatro agregaciones por
tarjeta sobre las tablas grandes. Además el informe de una corrida se lee mucho
después, cuando sus documentos pueden haber sido purgados — y un informe que cae
a cero afirma algo falso, que es peor que no tener informe.

El escritor es único, así que mantener esos contadores no tiene carrera.

## Índices: verificados contra el plan real

Cada consulta de la aplicación usa índice. Ninguna escanea la tabla:

| consulta | índice |
|---|---|
| buscar una resolución por número | `ix_resolucion_codigo` |
| archivo de un día | `ix_documento_fecha` |
| sólo lo que necesita revisión | `ix_documento_revision` |
| documentos de un operador | `ix_documento_operador` |
| resoluciones de un documento | `ix_resolucion_documento` |
| de qué documento salió 00086 | `ix_resolucion_codigo` + `PRIMARY` |

`documento.fecha` y `resolucion.fecha` son **columnas generadas STORED e
indexadas**. El archivo agrupa por día; sin ellas cada consulta aplicaría
`DATE()` sobre cada fila y perdería el índice.

### El límite que hay que conocer

`LIKE '%texto%'` **no puede usar un índice**, nunca. Sobre 26 M de resoluciones
es un escaneo completo. Por eso `titulo` y `nombre` llevan `FULLTEXT`:

```sql
-- escanea 26 M de filas
SELECT * FROM resolucion WHERE titulo LIKE '%nombramiento%';

-- usa el índice de texto
SELECT * FROM resolucion
WHERE MATCH(titulo) AGAINST('nombramiento' IN BOOLEAN MODE);
```

El servicio hoy busca con `LIKE`. Funciona con miles de filas y deja de hacerlo
con millones; cuando se migre, es lo primero que hay que cambiar.

## Collation

`utf8mb4_0900_ai_ci` — acento-insensible **a propósito**: buscar `maria`
encuentra `María Martínez`. Verificado.

Los códigos van en `ascii`: son dígitos y, con OCR dañado, letras latinas. No
necesitan `utf8mb4` y ocupan la cuarta parte por carácter en los índices.

## Ejecutar

```bash
mysql -u root -p < db/schema.sql          # crea la base desde cero
set MYSQL_PWD=...                          # nunca por argumento: se ve en la
python db/cargar_ledger.py \               # lista de procesos
       backend/data/inventory.jsonl
```

`cargar_ledger.py` es idempotente: volver a correrlo no duplica nada.

## Pendiente

- **El servicio todavía no usa esta base.** Sigue con el registro en memoria y
  el JSONL. La base está creada, cargada y verificada; conectarla es el
  siguiente paso.
- **`pdf_resolution_bot`** quedó intacta. Si es de un intento anterior, se puede
  borrar.
- La contraseña de `root` viajó por un chat. Conviene rotarla y crear el usuario
  `robotpdf_app` que está al final del esquema: el servicio no necesita permisos
  para borrar tablas, y así un fallo del programa no puede perder el esquema.

## Cómo se conecta el servicio

El servicio escribe en MySQL en el momento en que produce cada resolución. No
hay carga posterior ni copia que mantener en paralelo: la base es el sistema de
registro. Si no encuentra configuración, guarda en el archivo JSONL y lo dice en
`/api/health`, que es lo correcto en una máquina de pruebas sin base.

**Ninguna credencial vive en el repositorio.** La conexión se arma con lo que
haya en el entorno del proceso:

| Variable | Para qué | Por defecto |
|---|---|---|
| `RESOLUTIONS_DB_PASSWORD` | La contraseña. **Sin ella no se intenta conectar.** | — |
| `RESOLUTIONS_DB_USER` | El usuario | `robotpdf_app` |
| `RESOLUTIONS_DB_HOST` | El servidor | `127.0.0.1` |
| `RESOLUTIONS_DB_PORT` | El puerto | `3306` |
| `RESOLUTIONS_DB_NAME` | La base | `robotpdf` |

Que la ausencia de contraseña sea lo que decide es deliberado: un servicio que
arranca contra la base equivocada hace más daño que uno que no arranca contra
ninguna.

Para levantarlo contra la base, en PowerShell:

```powershell
$env:RESOLUTIONS_DB_USER = "robotpdf_app"
$env:RESOLUTIONS_DB_PASSWORD = "<la contraseña>"
python -m uvicorn resolutions.api.main:app --port 8001
```

Y para comprobar contra qué está guardando, sin exponer la contraseña:

```
GET /api/health  ->  "inventory_backend": "mysql://robotpdf_app@127.0.0.1:3306/robotpdf"
```

Conviene usar `robotpdf_app` -- con permisos sólo de datos -- y no `root`. El
usuario está preparado al final de `schema.sql`, comentado, junto con sus
concesiones.
