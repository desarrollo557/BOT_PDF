#!/usr/bin/env bash
# Lo mismo que corre CI, en la máquina, en el mismo orden.
set -uo pipefail
cd "$(dirname "$0")/.."

fallos=0
paso() {
  echo
  echo "── $1 ──"
  shift
  if "$@"; then echo "   ok"; else echo "   FALLÓ"; fallos=$((fallos + 1)); fi
}

PY=python
[ -x backend/.venv/bin/python ] && PY=backend/.venv/bin/python
[ -x backend/.venv/Scripts/python.exe ] && PY=backend/.venv/Scripts/python.exe

paso "Capas" "$PY" scripts/check_layers.py
paso "Lint del backend" bash -c "cd backend && '$PY' -m ruff check ."
paso "Pruebas del backend" bash -c "cd backend && '$PY' -m pytest -q"
paso "Tipos del front" bash -c "cd web && npm run check --silent"
paso "Pruebas del front" bash -c "cd web && npm run test --silent"
paso "Build del front" bash -c "cd web && npm run build --silent"

echo
if [ "$fallos" -eq 0 ]; then
  echo "Todo verde. El PR va a pasar."
else
  echo "$fallos verificación(es) en rojo. CI va a fallar igual."
fi
exit "$fallos"
