#!/usr/bin/env bash
# Lo mismo que corre CI, en la máquina, en el mismo orden.
set -uo pipefail

# Absoluta desde el principio: los pasos entran y salen de backend/ y web/, y
# una ruta relativa deja de apuntar al intérprete en cuanto se cambia de
# carpeta -- que es exactamente como este script se rompió la primera vez.
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ"

PY="$RAIZ/backend/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$RAIZ/backend/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || command -v python)"

fallos=0
paso() {
  echo
  echo "── $1 ──"
  shift
  if "$@"; then echo "   ok"; else echo "   FALLÓ"; fallos=$((fallos + 1)); fi
}

backend() { (cd "$RAIZ/backend" && "$PY" "$@"); }
web() { (cd "$RAIZ/web" && npm run "$@" --silent); }

paso "Capas" "$PY" "$RAIZ/scripts/check_layers.py"
paso "Lint del backend" backend -m ruff check .
paso "Pruebas del backend" backend -m pytest -q
paso "Tipos del front" web check
paso "Pruebas del front" web test
paso "Build del front" web build

echo
if [ "$fallos" -eq 0 ]; then
  echo "Todo verde. El PR va a pasar."
else
  echo "$fallos verificación(es) en rojo. CI va a fallar igual."
fi
exit "$fallos"
