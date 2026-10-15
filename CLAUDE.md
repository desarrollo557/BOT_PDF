# BOT_PDF — instrucciones del proyecto

Divide un PDF en las unidades documentales que contiene. No agrupa páginas por
código de resolución: el corpus real son expedientes heterogéneos donde todas las
páginas comparten el radicado, así que leerlo como señal de continuidad soldaría
la caja entera en un solo documento.

## El contexto está en Obsidian, no en el repositorio

El porqué de cada regla vive en una bóveda de Obsidian, fuera de este árbol:

```
C:\Users\desarrollo.SIAR\Documents\Obsidian\Eduver-Vault\10-Proyectos\BOT-PDF\
```

275 notas enlazadas entre sí, una por archivo de código, una por endpoint y una
por tabla, más las decisiones, las reglas de negocio con la medida que las
respalda, qué fija cada prueba, la operación y el glosario.

| Carpeta | Qué hay |
| --- | --- |
| `Mapa-Codigo/Dominio,Aplicacion,Adaptadores,API` | una nota por archivo de código |
| `Mapa-Codigo/Endpoints` | una nota por endpoint |
| `Mapa-Codigo/Frontend`, `Base de datos` | componentes y tablas |
| `Decisiones/` | qué se decidió, con qué medida y sobre qué expediente real |
| `Reglas/` | las reglas de corte de cada una de las cuatro rutas |
| `Pruebas/` | qué fija cada suite — qué se rompe al cambiar una regla |
| `Operacion/` · `Glosario/` | cómo se levanta y opera · vocabulario del dominio |

**Antes de tocar un archivo, lee su nota.** Cada nota declara en el frontmatter
el archivo que describe (`archivo: backend/src/...`), así que la correspondencia
es directa: `domain/segmentation.py` → `Mapa-Codigo/Dominio/segmentation (domain).md`.
El código dice qué hace; la nota dice por qué se decidió así y qué se midió para
decidirlo. Cambiar un umbral sin leer la decisión que lo fijó es deshacer trabajo
que ya se pagó.

La bóveda está fuera del directorio del proyecto, así que leerla pide permiso la
primera vez de cada sesión. Es lo esperable.

## La nota se actualiza en el mismo cambio que el código

No después. Una nota desactualizada engaña más que la ausencia de nota.

- Cambias un archivo → actualizas su nota.
- Añades un archivo o un endpoint → creas su nota, con el mismo frontmatter y las
  mismas secciones que sus vecinas, y la enlazas desde el hub de su capa y desde
  lo que la usa. Una nota a la que nadie llega no existe.
- Borras un archivo → borras su nota y los enlaces que apuntaban a ella.
- Cambias una regla de negocio → la nota de `Reglas/` y la de `Decisiones/` que la
  justifica, y la de `Pruebas/` si cambia lo que la prueba fija.

## Cómo se nombra una nota

Obsidian resuelve los `[[enlaces]]` por nombre de archivo en **toda** la bóveda,
que además aloja otro proyecto. De ahí tres reglas que ya costaron una tarde:

- **Sin puntos.** `segmentation (domain)`, no `segmentation.py`: Obsidian lee lo
  que sigue al punto como extensión y el enlace deja de resolver.
- **Sin tildes ni eñes** en el nombre, para no depender de la codificación del
  sistema de archivos. El contenido sí va con acentos, en español.
- **Único en toda la bóveda.** Un nombre genérico que ya exista en el otro
  proyecto hace que el enlace salte de proyecto. Por eso los hubs llevan sufijo:
  `Frontend (BOT-PDF)`, `Base de datos (BOT-PDF)`, `FUID (BOT-PDF)`.

Y un aviso para el operador: si en el grafo aparece un círculo rojo, **no hay que
pulsarlo**. Cada clic crea una nota vacía en `00-Inbox` que compite por el nombre
y empeora el problema. Lo que toca es recargar Obsidian: cuando se escriben
muchas notas desde fuera, su índice no las ve hasta que la aplicación reinicia.

## El verificador

```
python scripts/obsidian_check.py
```

Cruza la bóveda con el código y lista la deriva: notas que describen archivos
borrados, código sin nota, enlaces rotos, notas que nadie enlaza, nombres con
punto, nombres que chocan con el otro proyecto y notas vacías. Pásalo al terminar
un cambio que haya tocado la documentación.

No está en `verificar.sh` ni en CI a propósito: la bóveda no existe en el runner
de GitHub y bloquear un PR por algo que no está en el repositorio no tendría
sentido. Si no encuentra la bóveda, avisa y sale con 0. Se busca en la ruta de
arriba, o en `OBSIDIAN_VAULT` si está definida.

## Antes de tocar código

- `scripts/verificar.ps1` (o `.sh`) corre lo mismo que CI, en el mismo orden.
  Pásalo antes de dar nada por terminado.
- Las flechas apuntan hacia adentro: `domain` ← `application` ← `adapters` ← `api`.
  El dominio no sabe que existe FastAPI, PyMuPDF ni MySQL. Lo comprueba
  `scripts/check_layers.py` y falla el PR.
- El entorno se levanta con `scripts/levantar.ps1`. En esta máquina hay otros
  servicios de Node encendidos: nunca arranques sobre sus puertos.
- Ramas: `develop`, `main` y `produccion` terminan apuntando al mismo commit.
