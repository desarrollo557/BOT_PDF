#!/usr/bin/env bash
# Instala o actualiza BOT_PDF con Docker en un equipo Linux.
# Monta /home, /mnt y /media en la misma ruta dentro del contenedor, así que las
# rutas del equipo valen tal cual en la pantalla. Los datos viven en el volumen
# bot_pdf_botpdf_data y sobreviven a reconstruir la imagen.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker no está instalado o no está en el PATH." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker no responde: arranque el servicio (sudo systemctl start docker) y vuelva a intentarlo." >&2
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "   Se creó .env a partir de .env.example: ponga ahí sus llaves y vuelva a ejecutar."
fi

# Las carpetas del equipo, en la misma ruta dentro del contenedor.
{
  echo "# Generado por scripts/instalar-escritorio.sh para este equipo: no se versiona."
  echo "services:"
  echo "  botpdf:"
  echo "    volumes:"
  for carpeta in /home /mnt /media; do
    [ -d "$carpeta" ] && echo "      - \"$carpeta:$carpeta\""
  done
} > docker-compose.override.yml

echo "==> Construyendo la imagen y arrancando..."
docker compose up -d --build

echo "==> Esperando a que el servicio conteste..."
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:8000/api/health >/dev/null 2>&1; then
    docker compose ps
    echo ""
    echo "BOT_PDF listo en http://localhost:8000"
    echo "Registro en vivo: docker compose logs -f"
    exit 0
  fi
  sleep 3
done
docker compose ps
echo "El servicio no contestó en 3 minutos. Vea: docker compose logs -f" >&2
exit 1
