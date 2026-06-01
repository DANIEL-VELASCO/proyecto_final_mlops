# FastAPI — Servicio de inferencia (Persona 2)

API de inferencia que carga el modelo productivo desde MLflow.

## Endpoints

| Endpoint | Método | Descripción |
|---|---|---|
| `/health` | GET | Liveness/readiness. Reporta si el modelo está cargado, versión y alias. |
| `/predict` | POST | Predicción de precio. Valida con Pydantic, registra inferencia en `raw_data.inference_events`. |
| `/metrics` | GET | Métricas Prometheus (consumidas por el dashboard de Grafana). |
| `/reload-model` | POST | Fuerza recarga del modelo desde MLflow. Requiere header `X-Reload-Token`. |
| `/docs` | GET | Swagger UI (FastAPI built-in). |

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `MLFLOW_TRACKING_URI` | (requerido) | URL del servidor MLflow |
| `DATABASE_URI` | (requerido) | URI SQLAlchemy a la base `mlops` |
| `MLFLOW_S3_ENDPOINT_URL` | (requerido si modelo en S3) | URL MinIO |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | (requeridos) | Credenciales MinIO |
| `MLFLOW_MODEL_NAME` | `house-price-model` | Nombre del modelo en MLflow Registry |
| `MLFLOW_PRODUCTION_ALIAS` | `production` | Alias del modelo productivo |
| `MODEL_POLL_INTERVAL_SEC` | `30` | Cada cuánto el poller verifica si cambió el alias |
| `RELOAD_TOKEN` | `""` | Token para `/reload-model`. Si vacío, el endpoint rechaza siempre. |
| `INFERENCE_EVENTS_TABLE` | `raw_data.inference_events` | Tabla de registro de inferencias |

## Cómo correr localmente

```bash
docker build -t mlops-fastapi:local .
docker run --rm -p 8000:8000 \
    -e MLFLOW_TRACKING_URI=http://host.docker.internal:5000 \
    -e DATABASE_URI=postgresql+psycopg2://mlops:mlops_pass@host.docker.internal:5432/mlops \
    -e MLFLOW_S3_ENDPOINT_URL=http://host.docker.internal:9000 \
    -e AWS_ACCESS_KEY_ID=minio_admin \
    -e AWS_SECRET_ACCESS_KEY=minio_secret123 \
    mlops-fastapi:local
```

## Test manual

```bash
curl http://localhost:8000/health
# {"status":"ok","model_loaded":true,"model_version":"1","model_alias":"production"}

curl -X POST http://localhost:8000/predict \
    -H "Content-Type: application/json" \
    -d '{"brokered_by":"agency_1","status":"for_sale","bed":3,"bath":2,
         "acre_lot":0.5,"street":"street_1","city":"New York","state":"NY",
         "zip_code":10001,"house_size":1500,"prev_sold_date":null}'
```

## Imagen publicada

DockerHub: `max181818/mlops-fastapi` con tags `latest` y `sha-<commit>`.

Publicada automáticamente por GitHub Actions (`.github/workflows/build-fastapi.yml`) en cada push a `main` o `develop` que toque `fastapi/**`.
