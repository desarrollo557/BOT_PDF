# Separador documental

Toma un PDF con muchos documentos adentro y devuelve un archivo por cada uno,
más el inventario oficial de lo que hizo. Usa OCR y un modelo de visión **sólo
donde se acaba la evidencia barata**.

Software de **SIAR**, en uso sobre el archivo de la Universidad de Cartagena.

## Qué reconoce

El tipo no se deduce del nombre del archivo: se lee de lo que está impreso en
las páginas. `domain/doctype.py` muestrea doce páginas repartidas, busca frases
marcadoras tolerando el ruido del OCR, y exige dos condiciones a la vez para
pronunciarse — un puntaje mínimo y una ventaja de 1,6× sobre el segundo
candidato. Si no las cumple, contesta **Sin identificar** antes que adivinar.

| Tipo | Qué es | Unidad que produce |
|---|---|---|
| `resolucion` | Resoluciones administrativas | una resolución |
| `diploma` | Libros de registro de diplomas | un folio |
| `matricula` | Registros de matrícula | un expediente |
| `desconocido` | No alcanzó la evidencia | — |

Cada veredicto conserva la evidencia que lo sostiene: qué marcador, en qué
página, a qué distancia. Un tipo que nadie puede rastrear hasta una página no
sirve para decidir cómo se parte un documento.

## Qué hace con ellos

Cuatro acciones, que se eligen al subir (`application/task.py`):

| Acción | Qué produce |
|---|---|
| **Dividir en documentos** | un PDF por unidad, agrupando por el número impreso |
| **Separar por documento** | un PDF por unidad, decidiendo por continuidad |
| **Solo inventariar** | el FUID; el original queda entero |
| **Dividir e inventariar** | ambas cosas |

«Separar por documento» es la que corresponde a una caja de correspondencia, y
la que el sistema elige solo cuando las páginas no dicen ser nada que sepa
partir por número. Las dos primeras se distinguen en lo que buscan: una, un
código que manda hasta que aparece otro; la otra, si la hoja siguiente continúa
la anterior.

## El modelo de costo

400.000 páginas al día no se pueden leer con un modelo. La tubería es una
cascada, y cada peldaño ve sólo lo que el anterior no pudo contestar:

| Peldaño | Qué hace | Cuesta |
|---|---|---|
| L0 | capa de texto embebida y ancla difusa | ~0 |
| L1 | OCR de la banda del encabezado (~28% de los píxeles) | CPU |
| L2 | OCR de la página completa | CPU |
| L3 | contexto de secuencia — una página cuyos vecinos coinciden no necesita a nadie | ~0 |
| L4 | modelo de visión sobre recortes, en lotes de doce | tokens |

Una página sin ancla pero con capa de texto leída correctamente es una página de
continuación: el motor de agrupación la hereda gratis y nunca llega a un modelo.
Sólo escalan las páginas genuinamente ambiguas — códigos que compiten, o una
lectura de OCR que volvió casi vacía.

Cada corrida reporta qué fracción de páginas llegó a L4, así que la cuenta se
mide en vez de suponerse. En un lote digital de 180 páginas esa cifra es **0%**.

Hay una trampa que la cascada detecta aparte: una capa de texto que existe pero
está mal decodificada, de una fuente con el cmap roto. `domain/legibility.py` la
reconoce porque aparecen mayúsculas en mitad de palabra; las páginas rotas dan
26–30 por mil y las sanas no pasan de 6,5.

## Lotes y progreso en vivo

Se pueden soltar cincuenta PDF o más. Suben de a tres —cincuenta transferencias
en paralelo sólo se estorban entre sí— y se procesan con un proceso del sistema
operativo por documento.

Cada worker emite un evento por página a través de una cola compartida. La API
los pliega en estado por documento y empuja cuadros agrupados cuatro veces por
segundo: un documento de 400 páginas produce 400 eventos y nunca 400 cuadros en
el navegador. La pantalla dibuja una cinta viva, una celda por página, pintada
según el peldaño que la contestó.

Las fallas se aíslan en tres niveles, para que nada se propague:

- una **página** que no se puede leer se marca y va a revisión; las otras 399 del
  documento se procesan igual
- un **documento** que falla no detiene su lote
- la **telemetría** que se rompe nunca interrumpe el trabajo que describía

## Las tres pantallas

Un verbo cada una: **hacer** el trabajo, **encontrar** el trabajo, **arreglar**
el trabajo.

**Procesar** recibe documentos y muestra sólo lo que está pasando ahora. Las
subidas vienen en tres modos —individual hasta cinco, lote sin tope, o una
carpeta local— porque «estoy partiendo estos cinco», «estoy corriendo un trabajo»
y «vigila esta carpeta» piden pantallas y ritmos distintos. Lo terminado se va de
esta pantalla; el contador de la pestaña Archivo es lo que lo dice.

**Archivo** es todo lo que salió, en cualquiera de los dos granos. Una tarjeta por
documento procesado, esté todavía en el registro o sólo en el libro mayor. Las
tarjetas llevan las cifras que importan (unidades, páginas, peso, quién, cuándo).
Se filtra por texto, período, estado y operador; se ordena por fecha, volumen o
nombre; cada encabezado de día lleva sus propios totales, porque un encabezado
que sólo da la fecha obliga al lector a sumar las tarjetas de abajo. El grano
«por resolución» lista las unidades una por una, con edición en línea del número
y del título. Lee su historia del libro mayor y no del registro, que es lo que la
hace sobrevivir a limpiar la pantalla y a reiniciar el servicio.

**Revisión** es la cola de lo que la máquina no quiso adivinar, reunida de todos
los documentos y agrupada por motivo. Las demás pantallas contestan «qué hizo»;
ésta contesta «qué me necesita», que es la única pregunta con plazo. Enterrada de
a un documento por vez era invisible.

`/inventario` y `/procesados` ya no son pantallas: redirigen a `/archivo`.
Documentos y resoluciones eran dos destinos que mostraban el mismo trabajo en dos
granos, y quien buscaba «la 00086» tenía que adivinar cuál lo tenía. Son la misma
pregunta, así que el grano es un control y no un destino.

La consola va **anclada a la derecha, de arriba abajo, y abierta**. El contenido
nunca queda debajo: la consola publica el ancho que ocupa y el resto del layout
lo respeta como margen. Cerrada se reduce a un riel de 34 px con la palabra
«consola» en vertical, nunca desaparece del todo, y recuerda su ancho entre
sesiones. No tiene endpoint propio: cada línea sale de comparar un cuadro de
progreso contra el anterior.

Cuando una unidad de trabajo se cierra levanta un informe en vez de simplemente
desaparecer: documentos, páginas, unidades, peso neto, reloj de pared, cómo se
contestó cada página, y todo lo que produjo. Que la vista viva desaparezca no es
una respuesta; el operador la vio correr y se le debe lo que hizo.

El informe se levanta sólo por trabajo que **esta pestaña** vio pasar de en vuelo
a terminado. El servicio guarda las corridas terminadas y las repite al conectar,
así que sin esa regla recargar la página sacaba el informe de una corrida que
había terminado una hora antes. Una corrida de carpeta reporta con sus propios
totales, porque sus documentos se van del registro mucho antes de que alguien
reabra el informe: sumar los trabajos daría cero, y un informe que afirma algo
falso es peor que no tener informe.

## Sesiones

La entrada pide un nombre y nada más. No hay contraseña, la pantalla lo dice con
todas sus letras, y las pruebas lo fijan: leer, borrar y subir funcionan sin
nombre. Si alguien alguna vez ata la cabecera a un permiso, esas pruebas fallan y
la decisión hay que tomarla a propósito.

Lo que el nombre compra es real de todos modos. Cada trabajo lleva el operador
que lo corrió hasta el libro mayor, así que el archivo contesta «quién procesó
esto» mucho después de limpiar la pantalla. El nombre viaja percent-encoded,
porque los valores de cabecera HTTP son ASCII y la mitad de los nombres de un
edificio hispanohablante llevan tilde: mandar uno crudo revienta en el navegador
antes de que salga la petición.

```
anónimo --abrir()--> activa --inactiva(1h)--> inactiva --reanudar()--> activa
                        `--cerrar()--> anónimo <--cerrar()--'
```

Inactiva no es un candado; un clic la reanuda, porque no hay nada que destrabar.
Existe para que una consola que quedó abierta toda la noche deje de atribuirle el
trabajo de la mañana siguiente a quien se fue. Cerrar la sesión puede limpiar la
pantalla, pero nunca los archivos, y nunca sin preguntar.

## El formato del encabezado

Los encabezados reales se escriben de tres maneras, y el corpus sólo varía en
mayúsculas, tildes y el año final:

```
RESOLUCION NO. 00086
Resolución No. 00072 de 2023
RESOLUCIÓN No. 00083 de 2023
```

El ancla, un token de numeración y un número con ceros a la izquierda son el
invariante, así que esa estructura se puntúa como señal propia
(`OFFICIAL_FORM_WEIGHT`). Sin ella un encabezado en Title Case se apoya sólo en
sus mayúsculas y queda una centésima sobre el piso de confianza — a una lectura
rival de un viaje evitable al modelo de visión. La señal se le niega a las citas,
que se escriben igual: la forma dice «esto es un número de resolución», nunca
«esta página lo es».

## Las reglas de agrupación

Cuatro caminos, uno por clase de papel, y lo que cambia entre ellos es
únicamente **cómo se agrupan las páginas**. A partir de ahí los cuatro pasan por
el mismo sitio (`application/entrega.py`): describir cada unidad, comprobar que
ninguna hoja se perdió, escribir los PDF e inventariar lo que quedó en el disco.

`docs/ARQUITECTURA.md` explica los cuatro con detalle. En resumen:

| Ruta | Qué agrupa las páginas |
|---|---|
| Resoluciones | Un número impreso que manda hasta que aparece otro |
| Diplomas | Un folio por cara del libro |
| Matrículas | Una persona por carátula |
| Correspondencia | La continuidad, costura por costura (`domain/segmentation.py`) |

Y en las cuatro, el tipo documental y la fecha de cada unidad se leen **después**
del corte, con el catálogo del archivo (`domain/catalogo.py`) y por este orden:
el asunto que el papel declara, su encabezado, una mención del cuerpo y, para
una hoja suelta que no dice nada, el tipo de lo que venía antes.

Para resoluciones (`domain/grouping.py`):

1. Una página con código abre o continúa el grupo de esa resolución.
2. Una página sin código hereda el código de la **página anterior**.
3. Se agrupa **por código, no por contigüidad**: un código que reaparece después
   vuelve a su grupo original. Las páginas conservan su orden.
4. Las páginas anteriores al primer código quedan **en cuarentena**, nunca se
   adivinan.
5. Una mala lectura de una sola página flanqueada por dos lecturas idénticas
   (distancia de edición ≤ 2) se absorbe como ruido de OCR, y la corrección queda
   registrada.
6. No se escribe nada si no está cada página de origen contada exactamente una vez.

Para libros de diplomas (`application/diploma_split.py`) la regla es otra: una
unidad por folio, la cara sin identificador se anexa a la anterior, y un folio
repetido con la misma cédula es el mismo registro.

## Los nombres de salida

```
RESOLUCION_00086.pdf
```

El asunto **no va en el nombre**: vive en su columna del inventario. El nombre
largo anterior se cambió a petición del operador.

Las unidades que no son resoluciones no llevan ese prefijo. La unidad de un libro
de folios es un folio, y llamar `RESOLUCION_728` a un registro de diploma sería
escribir en el disco algo que no es verdad.

## El inventario

Hay que distinguir dos cosas que se llaman parecido:

**El FUID** es la planilla oficial FO-GD-008 de la Universidad. No se genera
desde cero: se abre la plantilla real que viaja con el programa
(`assets/fuid-fo-gd-008.xlsx` y `assets/fuid-diplomas.xlsx`), se rellena
respetando su estilo, se limpia lo que quede debajo del último registro para que
una plantilla ya usada no deje dos inventarios pegados, y se reubica el bloque de
firmas buscándolo por su texto. Se pide con `POST /api/jobs/{id}/fuid` y se baja
con `GET /api/jobs/{id}/fuid.xlsx`, desde el botón que la pantalla ofrece por
documento. Cada tipo de documento tiene su traductor a filas FUID, y ninguno
inventa una fecha que no leyó: donde no hay dato va `N/A`.

**El libro mayor** contesta la otra pregunta. Un `inventory.json` por documento
dice «qué salió de este archivo», pero después de unos cientos la pregunta pasa a
ser «de qué documento salió la 00086», así que cada PDF generado se agrega también
a un registro durable. Anotar un trabajo terminado es siempre un append, nunca una
reescritura.

Una fila por archivo escrito, y sólo por archivo escrito. Las cuatro rutas que
producen PDF —resoluciones, diplomas, matrículas y separación por continuidad—
arman su inventario con la misma función y con el mismo dato: el mapa de código
a nombre real que devuelve el escritor. Es lo que impide las dos formas de
mentir que tenía un inventario armado a ojo:

- **una unidad que no se pudo escribir** ya no aparece con el nombre que le
  habría tocado. El archivo no existe, la fila no se inventa, y sus páginas van
  a la cola de revisión una por una;
- **ninguna fila hereda el archivo de la siguiente.** Emparejar la lista de
  grupos con la de archivos por posición funciona hasta que uno falla; a partir
  de ahí cada fila afirma que un PDF contiene las páginas de otro, y el
  inventario no tiene forma de notarlo porque le siguen cuadrando los totales.

Cada fila lleva además lo que se supo de la unidad: su **tipo documental**,
tomado del catálogo del archivo y vacío cuando nadie lo reconoció, y **qué
páginas suyas son anexos**, que es la única respuesta a «¿de qué acta son estas
fotografías?».

El libro mayor sobrevive al registro de trabajos a propósito: limpiar la pantalla
olvida los trabajos, y el libro mayor es la constancia de que el trabajo ocurrió.
`GET /api/inventory` lo busca, `GET /api/inventory.csv` lo exporta con BOM para
que Excel abra bien las tildes, y las descargas se sirven por id de trabajo para
que los archivos de un documento limpiado sigan alcanzables.

Detrás puede haber MySQL o un archivo JSONL, y la pantalla no distingue cuál.
Manda la presencia de contraseña: sin `RESOLUTIONS_DB_PASSWORD` no se intenta
conectar y se escribe en `data/inventory.jsonl`. Si hay configuración pero la base
no responde, el servicio **degrada al archivo y lo dice** en `/api/health` en vez
de no arrancar. Un servicio que arranca contra la base equivocada hace más daño
que uno que no arranca contra ninguna.

## Daño y escala

Los escáneres, las pasarelas de correo y los archivos de hace una década producen
PDF cuya tabla de objetos no sobrevive a una lectura estricta — `code=4: source
object number out of range` es MuPDF diciéndolo. Un documento que llega al
ensamblado ya fue leído, agrupado y cuadrado, así que el escritor degrada en tres
pasos en vez de perderlo entero:

1. **Reparar.** Cuando MuPDF tuvo que reconstruir la tabla de referencias cruzadas
   lo hizo en memoria, y los números de objeto que cita el árbol de páginas no son
   los que tiene la reconstrucción. Escribirla y reabrirla renumera todo de forma
   consistente — una pasada extra, y sólo para archivos dañados.
2. **Reintento por página.** Una copia en bloque que falla se reintenta página por
   página. Más reescritura de objetos, pero toda página que no esté rota se
   entrega igual.
3. **Pérdida con nombre.** Una página que no se puede copiar a ninguna
   granularidad va a revisión por número. El archivo existe con menos adentro, y
   nadie tiene que descubrirlo comparando conteos de páginas.

Los mensajes de MuPDF no se muestran crudos: `application/diagnostico.py` traduce
unas treinta y cinco variantes al español del operador y separa lo recuperado de
lo perdido.

Las subidas se escriben a disco por trozos y nunca se sostienen en memoria, así
que el tope de 4 GB acota disco y no RAM, y el límite de cola acota lo que se
acepta sin empezar, no lo que se puede procesar.

## Barrido de caché ocioso

Tres cosas se acumulan durante una corrida y no valen nada al terminar: una
subida cuyo trabajo ya no está, un directorio de salida que nadie referencia, y
la cinta de páginas de un documento cuyo informe ya dice todo lo que decía la
cinta. Un janitor las recupera — y nada más. Los PDF generados y el libro mayor no
se tocan nunca.

Dos guardas dejan el caso ocioso gratis. Se salta si la cola no está vacía, porque
recuperar disco debajo de un worker corriendo es como desaparece un directorio de
salida a medio escribir; y se salta otra vez si el registro no cambió desde la
pasada anterior. Un sistema en reposo cuesta una comparación de enteros por tick
y ni una llamada al sistema de archivos.

## Estructura

```
backend/
  src/resolutions/
    domain/       reglas puras, cero dependencias   (anchor, extraction, scoring,
                  grouping, doctype, legibility, validation, naming)
    application/  casos de uso y puertos            (pipeline, process_document,
                  inventory_document, fuid, task, control)
    adapters/     uno por proveedor                 (PyMuPDF, Tesseract, Claude,
                  MySQL, openpyxl, archivos)
    api/          FastAPI, pool de workers, SSE
  tests/          1023 pruebas; el dominio corre en menos de un segundo
web/              SvelteKit 5 + Tailwind 4; 101 pruebas sobre los stores
db/               esquema MySQL: 7 tablas, 4 vistas, 11 claves foráneas
docs/             arquitectura y flujo de ramas
scripts/          verificación local y andamios de medición
```

La interfaz, sus mensajes y los motivos de revisión están en español. Los
identificadores y comentarios del código siguen en inglés, igual que las
librerías sobre las que se apoyan.

El dominio no importa nada más que la biblioteca estándar. Eso es lo que mantiene
las reglas comprobables en microsegundos y portables si el volumen alguna vez
exige otro runtime. `scripts/check_layers.py` lo verifica en cada PR: prohíbe once
paquetes de terceros dentro de `domain/` y `application/`, y obliga a que las
dependencias apunten hacia adentro.

## Cómo se corre

### Requisitos

- **Python 3.12+**
- **Node 20+**
- **Tesseract OCR** con el paquete de español — el único binario externo.
  Windows: `winget install UB-Mannheim.TesseractOCR`, y que `tesseract` quede en
  el `PATH`. Sin él los PDF digitales funcionan igual; los escaneados van a
  revisión.
- **MySQL 8+** — opcional. Sin base el servicio arranca igual y escribe el libro
  mayor en `data/inventory.jsonl`; ver *Base de datos* más abajo.

### Los dos, con un comando

```powershell
.\scripts\levantar.ps1     # Windows
```
```bash
./scripts/levantar.sh       # Linux, macOS, Git Bash
```

Levanta el backend y el front, y **elige puertos que estén libres** antes de
arrancar. Hace falta porque la máquina del operador corre otros servicios de
Node y el 5173 -- el puerto por omisión de Vite -- suele estar tomado: sin esta
comprobación Vite se muda solo al siguiente y la dirección que uno tenía
anotada deja de ser la buena sin que nadie lo diga. Cuando el backend acaba en
otro puerto, el proxy del front lo sigue por `API_URL`.

Espera a que la API conteste antes de abrir el front, para que la pantalla no
arranque con errores de red que dejan de ser ciertos treinta segundos después.
Ctrl+C para los dos: el backend se detiene con todo su árbol de procesos,
porque uno que sobreviva al front es el que ocupa el 8000 la próxima vez.

```powershell
.\scripts\levantar.ps1 -WebPort 5200    # un puerto concreto
.\scripts\levantar.ps1 -Fijo            # fallar en vez de buscar otro
```

### Puesta en marcha desde cero

```bash
git clone https://github.com/desarrollo557/BOT_PDF.git
cd BOT_PDF
```

**1. Backend.** El entorno virtual no es opcional. `pip install -e` instala el
paquete en modo editable, y hacerlo contra el Python del sistema ensucia una
instalación que no es de este proyecto.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate         # Linux, macOS, Git Bash
.\.venv\Scripts\Activate.ps1      # Windows PowerShell
pip install -e ".[dev]"
```

**2. Front.**

```bash
cd ../web
npm install
```

**3. Levantar las dos mitades**, cada una en su terminal:

```bash
cd backend && uvicorn resolutions.api.main:app --port 8000
```
```bash
cd web && npm run dev
```

**4. Abrir `http://localhost:5173`.**

El servidor de desarrollo hace proxy de `/api` a `http://127.0.0.1:8000`, así que
todo es del mismo origen y CORS nunca entra en juego. Por eso el backend no
necesita exponerse.

### Comprobar que quedó bien

```bash
cd backend && pytest              # 1023 pruebas
cd web && npm test                # 101 pruebas sobre los stores
```

Y contra el servicio levantado, `GET http://localhost:8000/api/health` dice
contra qué está guardando el inventario sin exponer la contraseña. Es la forma de
saber si tomó la base o cayó al archivo JSONL.

### Base de datos

MySQL 8+ / InnoDB / `utf8mb4_0900_ai_ci`. Siete tablas, cuatro vistas, once
claves foráneas. El modelo y las decisiones que lo sostienen están en
[`db/README.md`](db/README.md).

Es opcional: manda la presencia de `RESOLUTIONS_DB_PASSWORD`. Sin ella no se
intenta conectar y el libro mayor va a `data/inventory.jsonl`.

> **`db/schema.sql` empieza con `DROP DATABASE IF EXISTS robotpdf`.** Crea la base
> desde cero y borra la que hubiera. Sobre una instalación con datos, los pierde.
> Correrlo es un acto deliberado, nunca un paso de rutina.

```bash
mysql -u root -p < db/schema.sql
```

El servicio **no debe conectarse como `root`**. El usuario de aplicación está al
final de `schema.sql`, comentado, con los permisos que necesita y ninguno más: no
puede crear ni borrar tablas, así que un fallo del programa no puede perder el
esquema.

```sql
CREATE USER IF NOT EXISTS 'robotpdf_app'@'localhost' IDENTIFIED BY '<contraseña>';
CREATE USER IF NOT EXISTS 'robotpdf_app'@'127.0.0.1' IDENTIFIED BY '<contraseña>';
GRANT SELECT, INSERT, UPDATE, DELETE ON robotpdf.* TO 'robotpdf_app'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON robotpdf.* TO 'robotpdf_app'@'127.0.0.1';
FLUSH PRIVILEGES;
```

> **Las dos cuentas hacen falta.** Para MySQL, `'robotpdf_app'@'localhost'` y
> `'robotpdf_app'@'127.0.0.1'` son **usuarios distintos**: el primero responde al
> socket, el segundo a TCP. El valor por defecto de `RESOLUTIONS_DB_HOST` es
> `127.0.0.1`, así que crear sólo el de `localhost` —que es lo que trae el esquema
> comentado— da `Access denied` con la contraseña correcta. Cambiar la contraseña
> más adelante también hay que hacerlo en las dos, o una deja de entrar.

Con la base creada se le puede volcar el libro mayor que ya exista. Es
idempotente: volver a correrlo no duplica nada.

```bash
python db/cargar_ledger.py backend/data/inventory.jsonl
```

Y para levantar el servicio contra la base:

```powershell
$env:RESOLUTIONS_DB_PASSWORD = "<la contraseña>"
uvicorn resolutions.api.main:app --port 8000
```
```bash
export RESOLUTIONS_DB_PASSWORD='<la contraseña>'
uvicorn resolutions.api.main:app --port 8000
```

Si hay configuración pero la base no responde, el servicio **degrada al archivo y
lo dice** en `/api/health` en vez de no arrancar.

### Antes de abrir un PR

```powershell
.\scripts\verificar.ps1     # Windows
```
```bash
./scripts/verificar.sh      # Linux, macOS, Git Bash
```

Corre lo mismo que corre CI, en el mismo orden: capas, lint del backend, pruebas
del backend, tipos del front, pruebas del front y build. Usa `backend/.venv` si
existe, así que no hace falta activarlo antes.

### Desde otro equipo de la red

El servidor de desarrollo escucha en todas las interfaces, así que basta abrir
`http://IP-DEL-SERVIDOR:5173` desde el otro puesto. Vite imprime la dirección al
arrancar, bajo `Network:`.

El backend **no** hace falta exponerlo: quien habla con él es el proxy del
servidor de desarrollo, que corre en la misma máquina, y por eso puede seguir
escuchando sólo en `127.0.0.1`. Si aun así se quisiera alcanzar la API
directamente desde otro equipo, hay que arrancarla con `--host 0.0.0.0` **y**
añadir ese origen a la lista de CORS en `api/main.py`, que hoy sólo admite
localhost.

Para el caso contrario —el front en un equipo y el backend en otro— el destino
del proxy sale de `API_URL`, así que no hay que tocar la configuración:

```bash
API_URL=http://192.168.1.50:8000 npm run dev
```

## Configuración

Toda por variable de entorno. Ninguna credencial vive en el repositorio.

### Proceso

| Variable | Por defecto | Para qué |
|---|---|---|
| `RESOLUTIONS_DATA_DIR` | `./data` | raíz de subidas y salidas |
| `RESOLUTIONS_UPLOAD_DIR` | `<data>/uploads` | subidas |
| `RESOLUTIONS_OUTPUT_DIR` | `<data>/outputs` | salidas |
| `RESOLUTIONS_DOCUMENT_WORKERS` | núcleos − 1 | PDF en paralelo, un proceso cada uno |
| `RESOLUTIONS_PAGE_WORKERS` | 8 | hilos que reparten páginas al OCR dentro de un worker |
| `RESOLUTIONS_QUEUE_LIMIT` | 10000 | documentos aceptados y no empezados antes de que la API responda 429 |
| `RESOLUTIONS_MAX_UPLOAD_BYTES` | 4 GB | PDF más grande aceptado; acota disco, no memoria |
| `RESOLUTIONS_SWEEP_SECONDS` | 30 | cada cuánto busca sobras el janitor ocioso |

### Lectura

| Variable | Por defecto | Para qué |
|---|---|---|
| `RESOLUTIONS_OCR_LANG` | `spa` | idioma de Tesseract |
| `RESOLUTIONS_TESSERACT_CMD` | del `PATH` | ruta completa a `tesseract.exe` cuando no está en el `PATH` |
| `ANTHROPIC_API_KEY` | — | habilita el peldaño L4; sin ella las escaladas van a revisión |
| `RESOLUTIONS_VISION_MODEL` | `claude-sonnet-5` | modelo de visión |
| `RESOLUTIONS_MOSAIC_SIZE` | 12 | recortes por petición de visión |

### Inventario

| Variable | Por defecto | Para qué |
|---|---|---|
| `RESOLUTIONS_LEDGER` | `<data>/inventory.jsonl` | el libro mayor durable |
| `RESOLUTIONS_FUID_TEMPLATE` | la que viaja con el programa | plantilla FUID alternativa |
| `RESOLUTIONS_FUID_CAJA` | `3269` | caja que se estampa en el FUID |
| `RESOLUTIONS_FUID_OTRO` | `N/A` | columna «otro» del FUID |
| `RESOLUTIONS_FUID_TRD` | `N/A` | código TRD |
| `RESOLUTIONS_FUID_OFICINA` | — | oficina productora |

### Base de datos

| Variable | Por defecto | Para qué |
|---|---|---|
| `RESOLUTIONS_DB_PASSWORD` | — | **sin ella no se intenta conectar**; se usa el JSONL |
| `RESOLUTIONS_DB_USER` | `robotpdf_app` | usuario |
| `RESOLUTIONS_DB_HOST` | `127.0.0.1` | servidor |
| `RESOLUTIONS_DB_PORT` | `3306` | puerto |
| `RESOLUTIONS_DB_NAME` | `robotpdf` | base |

`GET /api/health` dice contra qué está guardando, sin exponer la contraseña.

## Lo que todavía no está

- **No hay plantilla FUID de matrículas.** Se dividen bien -- un archivo por
  expediente, nombrado con el código del estudiante -- pero su inventario cae en
  la plantilla genérica FO-GD-008.
- **Las lecturas verificadas no llegan a la interfaz.**
  `application/verified_readings.py` conserva las correcciones hechas por una
  persona contra la imagen, pero hoy su único consumidor es
  `scripts/inventario_diplomas.py`. Mientras no haya endpoint y control en
  pantalla, esa memoria no es una función del producto.
- **Aprendizaje de ROI.** El puerto `RoiRegistry` está declarado y no lo
  implementa nadie: la banda del encabezado es una fracción fija de la página.
  Aprender coordenadas por diseño necesita documentos reales contra los cuales
  calibrar, y una banda fija que funciona es mejor que una aprendida que nunca se
  midió.
- **Estado durable de los trabajos.** `JobRegistry` vive en memoria; un reinicio
  olvida la cola. El libro mayor no, que es lo que importa.
- **Inferencia del formato del código.** Los códigos capturados se validan por
  forma, no contra un patrón aprendido del corpus. Eso necesita un corpus real.

## Licencia y autoría

© SIAR. Desarrollado para la Universidad de Cartagena.
