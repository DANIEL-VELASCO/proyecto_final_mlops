FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# preprocess.py se copia desde training/ (P2 mantiene una sola fuente de verdad
# del preprocesamiento; el Dockerfile asume contexto raíz del repo cuando se
# construye desde docker-compose o GitHub Actions con context=. )
# Build context = ./fastapi por defecto: copiamos archivo equivalente local.
COPY preprocess.py main.py schemas.py model_loader.py inference_log.py ./

EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
