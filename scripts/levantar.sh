#!/usr/bin/env bash
# Levanta el servicio entero con un solo comando: el backend y el front.
#
# El gemelo de levantar.ps1, para Git Bash, Linux y macOS. Misma idea: buscar
# puertos libres antes de arrancar, porque la máquina corre otros servicios de
# Node y el 5173 -- el puerto por omisión de Vite -- suele estar tomado.
#
#   ./scripts/levantar.sh                 puertos automáticos
#   WEB_PORT=5200 ./scripts/levantar.sh   uno concreto
#   FIJO=1 ./scripts/levantar.sh          falla si el pedido está ocupado
set -uo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ"

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
FIJO="${FIJO:-}"

PY="$RAIZ/backend/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$RAIZ/backend/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || command -v python)"

if [ ! -d "$RAIZ/web/node_modules" ]; then
  echo "Falta web/node_modules. Corra primero:  cd web && npm install"
  exit 1
fi

libre() {
  # Un intento de conexión que no llega a ninguna parte es un puerto libre.
  ! (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

puerto() {
  local pedido="$1" para="$2" candidato
  if libre "$pedido"; then echo "$pedido"; return; fi
  if [ -n "$FIJO" ]; then
    echo "El puerto $pedido está ocupado y se pidió FIJO." >&2
    exit 1
  fi
  for candidato in $(seq $((pedido + 1)) $((pedido + 40))); do
    if libre "$candidato"; then
      echo "   $pedido ocupado: $para se va al $candidato" >&2
      echo "$candidato"
      return
    fi
  done
  echo "No hay ningún puerto libre para $para a partir del $pedido." >&2
  exit 1
}

echo
echo "── puertos ──"
API_PORT="$(puerto "$API_PORT" "el backend")"
WEB_PORT="$(puerto "$WEB_PORT" "el front")"

echo
echo "── backend ──"
(cd "$RAIZ/backend" && "$PY" -m uvicorn resolutions.api.main:app --port "$API_PORT") &
BACK=$!

# Matar el backend pase lo que pase: uno que sobreviva al front es el que ocupa
# el 8000 la próxima vez y nadie se acuerda de por qué.
limpiar() {
  echo
  if kill -0 "$BACK" 2>/dev/null; then
    kill "$BACK" 2>/dev/null
    echo "backend detenido."
  fi
}
trap limpiar EXIT INT TERM

# Esperar a que conteste, para que el front no abra con errores de proxy que
# dejan de ser ciertos treinta segundos después.
listo=""
for _ in $(seq 1 60); do
  if ! kill -0 "$BACK" 2>/dev/null; then
    echo "El backend se cayó al arrancar." >&2
    exit 1
  fi
  if curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1; then
    listo="si"
    break
  fi
  sleep 0.5
done
[ -n "$listo" ] || { echo "El backend no contestó en el $API_PORT." >&2; exit 1; }
echo "   escuchando en http://127.0.0.1:$API_PORT"

echo
echo "── front ──"
echo "   abra http://localhost:$WEB_PORT"
echo "   Ctrl+C para parar los dos"
echo

# API_URL es lo que lee el proxy del servidor de desarrollo. Sin ella apunta al
# 8000 fijo, que es lo correcto de costumbre y lo equivocado en cuanto el
# backend tuvo que irse a otro puerto.
#
# Se llama a Vite directo y no por `npm run dev -- ...`: es lo mismo que hace
# el guion de PowerShell, donde pasar por npm perdía los argumentos y Vite
# acababa tomando el número de puerto por directorio raíz. Un solo camino en
# los dos guiones es un fallo que sólo hay que entender una vez.
cd "$RAIZ/web"
API_URL="http://127.0.0.1:$API_PORT" ./node_modules/.bin/vite dev --port "$WEB_PORT" --strictPort
