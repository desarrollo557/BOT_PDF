#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker no está instalado o no está en PATH." >&2
  exit 1
fi

echo "==> Construyendo la imagen de BOT_PDF..."
docker compose build

echo "==> Arrancando la aplicación..."
docker compose up -d

echo "==> Estado del contenedor:"
docker compose ps

echo ""
echo "La aplicación queda disponible en http://localhost:8000"
echo "Para ver logs: docker compose logs -f"
