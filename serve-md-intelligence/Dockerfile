# Single-image private deployment: builds the SPA, then serves it + the API from uvicorn.
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY backend ./backend
COPY pipelines ./pipelines
COPY config ./config
COPY data/fixtures ./data/fixtures
RUN pip install --no-cache-dir . && mkdir -p data/raw data/warehouse data/geo
COPY --from=web /app/frontend/dist ./frontend/dist
ENV SERVEMD_WAREHOUSE_PATH=/app/data/warehouse/servemd.duckdb
EXPOSE 8000
# Builds the sample warehouse if none exists so the container is usable immediately; mount /app/data for real data.
CMD ["sh", "-c", "test -f $SERVEMD_WAREHOUSE_PATH || python -m pipelines.build --sample; uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"]
