# Flujo de ramas

Tres ramas permanentes. Ninguna se toca directo: todo entra por pull request y
todo pasa por CI.

```
feat/… fix/… ──PR──▶ develop ──PR──▶ main ──PR──▶ produccion
                        ▲                              │
                        └──────── hotfix/… ────────────┘
```

| Rama | Qué es | Quién la mueve |
|---|---|---|
| `develop` | El día a día. Acá se integra todo lo que se está construyendo. Puede romperse un rato; para eso está. | Cualquier PR de trabajo |
| `main` | Lo que ya se probó y se considera correcto. Es el candidato a producción y el que se prueba contra documentos reales. | PR desde `develop` |
| `produccion` | Exactamente lo que corre en la máquina de la universidad. Cada merge acá es un despliegue. | PR desde `main`, y `hotfix/*` cuando arde |

## Nombres de rama

El prefijo dice qué tipo de cambio trae, y la validación del PR lo exige:

```
feat/picker-de-carpetas
fix/pagina-sin-numero-hereda
refactor/cola-de-progreso
docs/modelo-de-datos
test/formato-oficial
chore/dependencias
perf/ocr-banda-superior
hotfix/inventario-no-carga
```

## Ciclo normal

```bash
git switch develop && git pull
git switch -c feat/lo-que-sea
# ... trabajo, commits ...
git push -u origin feat/lo-que-sea
gh pr create --base develop --fill
```

El título del PR se usa como mensaje del merge, así que va en formato
Conventional Commits: `feat(folders): el picker lista rutas reales del disco`.

## Subir a producción

1. PR de `develop` a `main`. CI en verde y revisión.
2. Probar `main` contra documentos reales, con el servicio levantado.
3. PR de `main` a `produccion`, titulado `release: …`.
4. Etiquetar el merge: `git tag -a v0.3.0 -m "…" && git push origin v0.3.0`.

## Hotfix

Sale de `produccion`, entra a `produccion`, y **vuelve hacia atrás** el mismo
día: se mergea también a `main` y a `develop`. Un arreglo que sólo vive en
producción reaparece en el siguiente despliegue.

```bash
git switch produccion && git pull
git switch -c hotfix/inventario-no-carga
# ... arreglo mínimo, nada más ...
gh pr create --base produccion --fill
# una vez mergeado:
gh pr create --base main --head hotfix/inventario-no-carga --fill
```

## Qué protege cada rama

Configurado en GitHub (Settings → Rules), y explicado en
[`CONTRIBUTING.md`](../CONTRIBUTING.md):

| | `develop` | `main` | `produccion` |
|---|---|---|---|
| Push directo | no | no | no |
| PR obligatorio | sí | sí | sí |
| Revisiones | 0 | 1 | 1 |
| CI en verde | sí | sí | sí |
| Historial lineal | sí | sí | sí |
| Borrado de la rama | — | no | no |
