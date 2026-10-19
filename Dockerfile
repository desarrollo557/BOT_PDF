# syntax=docker/dockerfile:1
#
# BOT_PDF en un contenedor: el front compilado y el servicio en una sola imagen.
# Se usa con docker-compose.yml y scripts/instalar-escritorio.ps1, que además
# monta los discos del equipo para que las rutas locales funcionen igual que
# sin Docker. Ver la sección «Con Docker» del README.

# -- 1. El front: SvelteKit estático --------------------------------------------
# La misma versión de Node que la CI.
FROM node:22-bookworm AS frontend-builder
WORKDIR /workspace/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# -- 2. El servicio --------------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Bogota

# Tesseract con español: el OCR local, el de «Solo OCR». Sin él, todo papel
# escaneado sin capa de texto se leía vacío. tzdata, para que las fechas de los
# inventarios y el registro salgan en hora de Colombia y no en UTC.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# El servicio como paquete Python, con sus plantillas (pyproject: package-data).
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/src /app/backend/src
RUN pip install --upgrade pip && pip install /app/backend

# El front ya compilado; lo sirve el propio servicio en el puerto 8000.
COPY --from=frontend-builder /workspace/web/build /app/web/build

# Todo lo que se produce va a /data, un volumen que sobrevive a reconstruir la
# imagen: salidas, libro mayor, usuarios y registro diario.
ENV RESOLUTIONS_DATA_DIR=/data \
    RESOLUTIONS_UPLOAD_DIR=/data/uploads \
    RESOLUTIONS_OUTPUT_DIR=/data/outputs \
    RESOLUTIONS_LEDGER=/data/inventory.jsonl \
    RESOLUTIONS_USERS=/data/usuarios.jsonl \
    BOTPDF_WEB_ROOT=/app/web/build

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1

CMD ["python", "-m", "uvicorn", "resolutions.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
