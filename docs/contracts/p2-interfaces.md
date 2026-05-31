# Contratos de P2 (ML Engineer) hacia P1 y P3

Documento de referencia para evitar bloqueos. Cualquier cambio en estos
contratos debe avisarse en el chat del equipo y reflejarse aquí.

---

## 1. Hacia P1 (Data Engineer) — invocación de tareas 11-17 del DAG

P2 entrega 3 binarios CLI (también disponibles como subcomandos del entrypoint
de la imagen `mlops-training`). El DAG de Airflow los invoca con `PythonOperator`
(si P1 instala el paquete en el venv de Airflow) o con `KubernetesPodOperator`
(recomendado — usa la imagen Docker publicada).

### 1.1 `train` — tareas 11, 12 y 13 (train + evaluate train + register)

```bash
docker run --rm \
  -e MLFLOW_TRACKING_URI=http://mlflow:5000 \
  -e DATABASE_URI=postgresql+psycopg2://mlops:***@postgres:5432/mlops \
  -e MLFLOW_S3_ENDPOINT_URL=http://minio:9000 \
  -e AWS_ACCESS_KEY_ID=*** -e AWS_SECRET_ACCESS_KEY=*** \
  danielvelasco01/mlops-training:sha-XXXX \
  train \
    --batch-id 2026-05-31-01 \
    --batch-id-filter 2026-05-31-01 \
    --commit-sha $GITHUB_SHA \
    --training-reason "drift detectado en house_size" \
    --clean-table clean_data.properties
```

**Stdout (última línea)** — JSON parseable:
```json
{"run_id":"<uuid>","model_name":"house-price-model","model_version":"3",
 "model_uri":"models:/house-price-model/3",
 "metrics":{"train":{"mae":...,"rmse":...,"mape":...,"r2":...},
            "val":{...},"test":{...}},
 "rows_used":12500,"batch_id":"2026-05-31-01"}
```

**Exit codes:** `0` éxito, `≥1` error (datos insuficientes, conexión MLflow caída, etc.).

### 1.2 `evaluate` — parte de la tarea 14 (compare_with_production)

```bash
docker run ... mlops-training:sha-XXXX \
  evaluate \
    --candidate-version 3 \
    --batch-id-filter 2026-05-31-01 \
    --clean-table clean_data.properties
```

**Stdout:** JSON con métricas del candidato y del productivo evaluados en el
mismo holdout. Si no hay productivo: `"no_production_model": true`.

### 1.3 `promote` — tareas 15, 16 y 17 (decide + promote/reject)

```bash
# leyendo evaluation de archivo:
docker run ... mlops-training:sha-XXXX \
  promote \
    --evaluation-json /tmp/eval.json \
    --candidate-version 3 \
    --mae-improvement-pct 3.0 \
    --rmse-tolerance-pct 1.0
```

**Stdout:** JSON con la decisión:
```json
{"promoted":true,"reason":"MAE candidato 0.12 mejora a productivo 0.18 (-33.3%, umbral -3%); RMSE candidato 0.21 dentro de tolerancia (+0.5%, umbral +1%)",
 "model_name":"house-price-model","candidate_version":"3",
 "alias_applied":"production","previous_production_version":"2",
 "candidate_metrics":{...},"production_metrics":{...}}
```

### 1.4 Encadenamiento sugerido en el DAG

| Tarea Airflow                  | Comando P2  | Pasa al siguiente            |
| ------------------------------ | ----------- | ---------------------------- |
| `train_candidate_model`        | `train`     | `model_version` (XCom)       |
| `evaluate_candidate_model`     | (parte 1.1, ya hecho en train) | métricas ya en MLflow |
| `register_candidate_in_mlflow` | (parte 1.1) | model_uri (XCom)             |
| `compare_with_production`      | `evaluate`  | evaluation_json (XCom)       |
| `decide_promotion` (Branch)    | (lógica DAG: lee `promoted` del resultado de `promote`) | rama promote_model o reject_model |
| `promote_model`                | `promote`   | decisión persistida en MLflow |
| `reject_model`                 | `promote` (mismo binario, simplemente no asigna alias) | razón persistida como tag |
| `notify_or_log_result`         | (P1) usa los JSON anteriores para escribir `raw_data.training_audit` | — |

---

## 2. Hacia P1 — esquema sugerido para `raw_data.inference_events`

P2 inserta una fila por cada llamada a `/predict`. **Esta tabla la creará P1**
con su DDL definitivo. Mientras tanto, P2 ejecuta este `CREATE TABLE IF NOT EXISTS`
al arrancar FastAPI (idempotente, no destruye si ya existe).

```sql
CREATE TABLE IF NOT EXISTS raw_data.inference_events (
    request_id      UUID PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model_name      TEXT NOT NULL,
    model_version   TEXT NOT NULL,
    model_alias     TEXT NOT NULL,
    input_payload   JSONB NOT NULL,
    prediction      DOUBLE PRECISION,
    status          TEXT NOT NULL,    -- 'ok' | 'error'
    error_message   TEXT,
    latency_ms      INTEGER
);
```

**Si P1 quiere otro nombre/columnas, basta con cambiar `INFERENCE_EVENTS_TABLE`
en el Secret de FastAPI y avisar.** P2 no asume nada más sobre `raw_data`.

---

## 3. Hacia P3 (DevOps) — contrato HTTP

### 3.1 Payload `/predict` (consumido por Streamlit y Locust)

```json
{
  "brokered_by": "agency_1",
  "status": "for_sale",
  "bed": 3,
  "bath": 2,
  "acre_lot": 0.5,
  "street": "street_1",
  "city": "New York",
  "state": "NY",
  "zip_code": 10001,
  "house_size": 1500,
  "prev_sold_date": null
}
```

### 3.2 Respuesta `/predict`

```json
{
  "price": 425000.0,
  "model_version": "3",
  "model_alias": "production",
  "inference_id": "8c8e...-...-...",
  "timestamp": "2026-05-31T18:42:11.234Z"
}
```

### 3.3 Métricas Prometheus expuestas

Las que ya consulta el dashboard de Grafana de P3 (`grafana-dashboard-mlops`):

| Métrica                                  | Origen                            |
| ---------------------------------------- | --------------------------------- |
| `http_requests_total{status,...}`        | `prometheus_fastapi_instrumentator` |
| `http_request_duration_seconds_bucket`   | `prometheus_fastapi_instrumentator` |
| `model_version_info{version,alias,...}`  | Gauge custom de P2                |
| `model_load_total{result}`               | Counter custom de P2              |
| `inference_log_failures_total`           | Counter custom de P2              |

### 3.4 `/reload-model` — endpoint admin

`POST /reload-model` con header `X-Reload-Token: <token del Secret>` y body
`{"force": false}`. Si el token no coincide → `401`.

---

## 4. Variables de entorno que P2 espera en FastAPI

Ya configuradas por P3 en `kubernetes/secrets.yaml`:

| Variable                      | Valor actual                                                         |
| ----------------------------- | -------------------------------------------------------------------- |
| `MLFLOW_TRACKING_URI`         | `http://mlflow:5000`                                                 |
| `DATABASE_URI`                | `postgresql+psycopg2://mlops:***@postgres:5432/mlops`                |

**Falta agregar** (P2 lo pedirá a P3 vía PR al secret):

| Variable                      | Default si ausente                                                   |
| ----------------------------- | -------------------------------------------------------------------- |
| `MLFLOW_MODEL_NAME`           | `house-price-model`                                                  |
| `MLFLOW_PRODUCTION_ALIAS`     | `production`                                                         |
| `MODEL_POLL_INTERVAL_SEC`     | `30`                                                                 |
| `RELOAD_TOKEN`                | `""` (si vacío, `/reload-model` siempre rechaza)                     |
| `INFERENCE_EVENTS_TABLE`      | `raw_data.inference_events`                                          |

---

## 5. Variables de entorno que P2 espera en la imagen de training

Las que P1 debe inyectar al ejecutar el contenedor desde el DAG:

| Variable                      | Obligatorio | Notas                                                |
| ----------------------------- | ----------- | ---------------------------------------------------- |
| `MLFLOW_TRACKING_URI`         | sí          | http://mlflow:5000                                   |
| `DATABASE_URI`                | sí          | mismo que FastAPI                                    |
| `MLFLOW_S3_ENDPOINT_URL`      | sí          | http://minio:9000                                    |
| `AWS_ACCESS_KEY_ID`           | sí          | desde Secret minio                                   |
| `AWS_SECRET_ACCESS_KEY`       | sí          | desde Secret minio                                   |
| `MLFLOW_EXPERIMENT_NAME`      | opcional    | default `house-price`                                |
| `MLFLOW_MODEL_NAME`           | opcional    | default `house-price-model`                          |
| `CLEAN_TABLE`                 | opcional    | default `clean_data.properties` (P1 puede cambiarlo) |

---

## 6. Checklist de coordinación

- [ ] P1: confirmar nombre de tabla y columnas de `clean_data.*`
- [ ] P1: confirmar nombre de tabla de auditoría (`raw_data.training_audit`)
- [ ] P1: validar o ajustar el DDL de `raw_data.inference_events` propuesto en §2
- [ ] P3: añadir variables faltantes al `fastapi-secret` (§4)
- [ ] P3: añadir `RELOAD_TOKEN` al Secret de FastAPI (puede ser cualquier UUID generado)
- [ ] P3: confirmar que la imagen Docker publicada para FastAPI usa
       `${DOCKERHUB_USERNAME}/mlops-fastapi:sha-...` y actualizar el Deployment en consecuencia
       (hoy apunta a `:latest`, que no garantiza reproducibilidad)
