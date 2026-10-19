# syntax=docker/dockerfile:1

FROM node:20-bookworm AS frontend-builder
WORKDIR /workspace/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

# Instala la app backend como paquete Python
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/src /app/backend/src
RUN pip install --upgrade pip && pip install /app/backend

# Carga el frontend ya compilado
COPY --from=frontend-builder /workspace/web/build /app/web/build

ENV RESOLUTIONS_DATA_DIR=/data \
    RESOLUTIONS_UPLOAD_DIR=/data/uploads \
    RESOLUTIONS_OUTPUT_DIR=/data/outputs \
    RESOLUTIONS_LEDGER_PATH=/data/inventory.jsonl \
    RESOLUTIONS_USERS_PATH=/data/usuarios.jsonl

EXPOSE 8000
VOLUME ["/data"]

CMD ["sh", "-c", "python -m uvicorn resolutions.api.main:app --host 0.0.0.0 --port 8000"]
