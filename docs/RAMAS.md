# Flujo de ramas

Tres ramas permanentes. Ninguna se toca directo: todo entra por pull request y
todo pasa por CI. El estándar de ramas es el que pidió el operador el
2026-11-26.

```
feature/… bugfix/… chore/… docs/… ──PR──▶ develop ──▶ release/… ──PR──▶ main ──▶ produccion
                                            ▲                                        │
                                            └───────────── hotfix/… ─────────────────┘
```

| Rama | Qué es | Quién la mueve |
|---|---|---|
| `develop` | Integración y desarrollo continuo. Acá se integra todo lo que se está construyendo. Puede romperse un rato; para eso está. | Las ramas de trabajo |
| `release/*` | La preparación de una versión nueva, sacada de `develop`, p. ej. `release/2026-11-26`. Sólo arreglos de último momento. | Se saca de `develop` |
| `main` | Estable y lista para producción: lo que ya se probó y se considera correcto. | PR desde `release/*` (o `develop`) y `hotfix/*` |
| `produccion` | Exactamente lo que corre en los equipos (`actualizar-docker`). Va al mismo commit que `main`; cada movimiento acá es un despliegue. | Desde `main`, y `hotfix/*` cuando arde |

## Nombres de rama

El prefijo dice qué tipo de cambio trae, y la validación del PR lo exige:

| Prefijo | Para qué | Ejemplo |
|---|---|---|
| `feature/` | Funcionalidades nuevas | `feature/monitoreo-de-equipos` |
| `bugfix/` | Errores detectados | `bugfix/nombre-documental` |
| `hotfix/` | Correcciones urgentes en producción | `hotfix/inventario-no-carga` |
| `release/` | Preparación de una versión nueva | `release/2026-11-26` |
| `chore/` | Mantenimiento: dependencias, configuración | `chore/dependencias` |
| `docs/` | Cambios en la documentación del proyecto | `docs/modelo-de-datos` |

Los prefijos de antes (`feat/`, `fix/`, `refactor/`, `test/`, `perf/`) se
siguen aceptando para las ramas que ya existían; el trabajo nuevo usa los de la
tabla.

## Ciclo normal

```bash
git switch develop && git pull
git switch -c feature/lo-que-sea      # o bugfix/…, chore/…, docs/…
# ... trabajo, commits ...
git push -u origin feature/lo-que-sea
gh pr create --base develop --fill
```

Los commits y el título del PR van en formato Conventional Commits, que es lo
que valida el PR: `feat(folders): el picker lista rutas reales del disco`,
`fix(nombres): …`, `chore(ci): …`, `docs: …`.

## Subir a producción

1. Sacar `release/<fecha>` de `develop`. CI en verde sobre esa rama.
2. Probar la versión contra documentos reales, con el servicio levantado.
3. `main` avanza a la release (PR desde `release/*`, o fast-forward como abajo).
4. `produccion` va al mismo commit que `main`.
5. Etiquetar: `git tag -a v<fecha> -m "…" && git push origin v<fecha>`.

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

## Dejar las tres ramas en el mismo commit

Las ramas exigen historial lineal, así que no hay merge commits: un PR
mergeado con *squash* deja en el destino un commit nuevo, y las otras dos
ramas quedan con el mismo código pero «N commits ahead». Para que las tres
apunten al **mismo** commit, un administrador las avanza por fast-forward,
sin `--force`, una vez que ese commit pasó la CI:

```powershell
git fetch origin
$sha = git rev-parse <commit-probado>
# Las tres tienen que ser ancestros del commit: si no, no es un fast-forward.
foreach ($r in 'develop','main','produccion') { git merge-base --is-ancestor "origin/$r" $sha; if ($?) { "$r ok" } }
git push origin "${sha}:refs/heads/develop" "${sha}:refs/heads/main" "${sha}:refs/heads/produccion"
```

GitHub marca solos como mergeados los PR cuyo contenido queda en la rama.
Mover `produccion` es desplegar.

### La CI se lanza a mano

En este repositorio los workflows no se disparan con los push ni con los PR
(el último disparo automático fue el 2026-09-07), así que las comprobaciones
obligatorias de un PR se quedan en «Waiting for status to be reported». La CI
se lanza sobre la rama y se espera en verde:

```powershell
gh workflow run CI --ref <rama>
gh run list --branch <rama> --limit 1
gh run watch <id> --exit-status
```

«Rama, título y descripción» (`pr-guard.yml`) sólo corre con eventos de PR, y
por lo mismo tampoco llega nunca.

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
