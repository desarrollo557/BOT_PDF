# Cómo se trabaja en este repositorio

El separador parte resoluciones administrativas de una universidad. Un error no
produce una pantalla fea: produce un PDF con la resolución de otra persona
adentro. De ahí sale casi todo lo que sigue.

## Antes de abrir un PR

Lo mismo que corre CI, corre en la máquina:

```powershell
.\scripts\verificar.ps1     # Windows
```
```bash
./scripts/verificar.sh      # Linux, macOS, Git Bash
```

Eso ejecuta cuatro cosas: las capas, el lint, las pruebas del backend y las del
front con el build. Si una falla, el PR va a fallar igual, sólo que veinte
minutos más tarde.

## Las reglas que CI hace cumplir

**Las dependencias apuntan hacia adentro.** `scripts/check_layers.py` lee los
`import` de `backend/src/resolutions` y falla si el dominio conoce a FastAPI, a
PyMuPDF o a MySQL. El dominio se prueba sin instalar nada de eso; el día que un
adaptador se filtre ahí, cambiar de motor de OCR pasa a ser una reescritura.

**El flujo de ramas.** Un PR a `produccion` que no venga de `main` o de
`hotfix/*` no se puede mergear. Ver [`docs/RAMAS.md`](docs/RAMAS.md).

**El título en Conventional Commits.** Es el mensaje que queda en el historial:
`fix(grouping): una página sin número hereda la anterior`.

**Una descripción que se pueda revisar.** Qué cambia, por qué, y qué se probó
de verdad.

## Las reglas que CI no puede hacer cumplir

**Ninguna cifra inventada.** Todo número que la interfaz muestra —resoluciones,
páginas, tiempos, tamaños— sale de la corrida real o de la base. No hay valores
por defecto que reemplacen una medición, ni filas de ejemplo. Un dato que no se
conoce se muestra como desconocido; un inventario con un número que nadie puede
rastrear hasta un documento es peor que uno que admite el hueco.

**Los endpoints se prueban contra el servicio levantado.** Las pruebas pasan
sobre el código; el operador usa el proceso que está corriendo. Antes de decir
que algo funciona, levantar la API y ejercitar la ruta con `curl`, incluyendo
los casos de error. Si el cambio exige reiniciar el backend, decirlo.

**Nada de botones sin backend.** Si una pantalla ofrece una acción, la acción
funciona.

## Pruebas

Las pruebas están escritas como frases: `test_a_page_without_a_code_inherits_
the_previous_one`. Se leen antes que el código y describen la regla, no la
implementación. Un comportamiento del negocio que se corrige lleva su prueba en
el mismo PR — la que falla antes del arreglo y pasa después.

`backend/tests/test_official_format.py` y `test_rf01_official_header_opens.py`
fijan el formato real de los encabezados. No se relajan para hacer pasar un
cambio: si un documento real no encaja, el que está mal es el código.

## Estilo

Python: `ruff check` con la configuración de `backend/pyproject.toml`, líneas de
90. TypeScript y Svelte: `npm run check`, sin errores ni advertencias.

Los comentarios explican por qué, no qué. El código ya dice qué hace.

## Base de datos

`db/schema.sql` crea todo desde cero y CI verifica en cada PR que se aplique
sobre una base vacía. Un cambio de esquema viene con la migración que lleva una
base existente al estado nuevo, descrita en el PR: las tablas de resoluciones
crecen a decenas de millones de filas al año y un `ALTER` improvisado sobre eso
bloquea el turno entero.
