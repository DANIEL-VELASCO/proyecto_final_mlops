# feat(p2): MLflow training pipeline + FastAPI inference + contracts

URL para abrir el PR (rama base `develop`):
https://github.com/DANIEL-VELASCO/proyecto_final_mlops/pull/new/feature/p2-mlflow-fastapi

---

## Resumen

Implementa los componentes de **P2 (ML Engineer)** definidos en la sección 4 del
documento de distribución: pipeline de entrenamiento invocable por el DAG,
servicio FastAPI con carga de modelo desde MLflow por alias, y los contratos
necesarios para que P1 y P3 integren sin sorpresas.

## Qué incluye (por commit)

1. **`feat(training)`** — `training/`
   - `preprocess.py` — ColumnTransformer con `OneHotEncoder(handle_unknown="ignore")`
     y conversión `prev_sold_date → days_since_prev_sold`. Sobrevive a nuevas
     categorías sin romper (RF3/RF4 del PDF).
   - `train.py` — RandomForestRegressor, registra params, métricas
     (MAE/RMSE/MAPE/R² para train/val/test), artefactos (residuals,
     feature_importance, preprocessing_report) y el modelo en MLflow Model
     Registry, con tags `batch_id` y `training_reason` (RF5).
   - `evaluate.py` — Carga candidato + productivo por alias y los evalúa en el
     **mismo holdout** para comparación justa (RF6).
   - `promote.py` — Regla explícita: promover si MAE candidato ≤ MAE productivo
     × (1 − 3 %) y RMSE candidato ≤ RMSE productivo × (1 + 1 %); ambos umbrales
     configurables por flag. Actualiza alias `production` o tagea el rechazo (RF6).
   - `Dockerfile` + `entrypoint.sh` — imagen única con subcomandos
     `train` / `evaluate` / `promote` para que P1 invoque desde el DAG con
     `KubernetesPodOperator` (tareas 11–17).

2. **`feat(fastapi)`** — `fastapi/`
   - `schemas.py` — Pydantic alineado al payload que ya envían **Streamlit
     y Locust** (verificado contra `streamlit/app.py` y `locust/locustfile.py`
     de `develop`).
   - `model_loader.py` — Carga thread-safe desde `models:/house-price-model@production`,
     poller en background cada 30 s, **fallback al modelo previamente cargado**
     si una recarga falla (RF7).
   - `inference_log.py` — Persiste cada `/predict` en `raw_data.inference_events`
     con `request_id`, `payload (JSONB)`, `prediction`, `model_version/alias`,
     `latency_ms`, `status`. `CREATE TABLE IF NOT EXISTS` idempotente para no
     bloquearnos por el DDL de P1 (RF8).
   - `main.py` — `/health`, `/predict`, `/metrics`, `/reload-model` (protegido
     por `X-Reload-Token`). Expone las **mismas series Prometheus** que ya
     consulta el dashboard de Grafana de P3 (`http_requests_total`,
     `http_request_duration_seconds_bucket`, `model_version_info`).
   - `Dockerfile` + `requirements.txt` — uvicorn con healthcheck.

3. **`docs(p2)`** — `docs/contracts/p2-interfaces.md`
   - Cómo invocar `train` / `evaluate` / `promote` desde el DAG (args, stdout JSON, exit codes).
   - DDL propuesto para `raw_data.inference_events` (P1 puede ajustarlo).
   - Métricas exactas que se exponen (las que ya consume el Grafana de P3).
   - Variables de entorno que P2 necesita en el Secret de FastAPI.
   - Checklist final de coordinación con P1 y P3.

4. **`chore(compose)`** — `docker-compose.yml`
   - FastAPI ahora recibe `DATABASE_URI`, `MLFLOW_S3_ENDPOINT_URL`,
     `AWS_*`, `MLFLOW_MODEL_NAME`, `MLFLOW_PRODUCTION_ALIAS`, `RELOAD_TOKEN`,
     `INFERENCE_EVENTS_TABLE` para que la misma imagen corra en compose y K8s.
   - Nuevo servicio `training` con `profiles: [training]` para invocar
     `docker compose --profile training run --rm training train ...` localmente.

## Requerimientos funcionales cubiertos

| RF  | Cubre | Dónde |
| --- | ----- | ----- |
| RF3 (validación) | parcial | `preprocess.clean_dataframe` + `OneHotEncoder(handle_unknown=ignore)`; el resto lo cubre P1 en validate_schema / validate_data_quality |
| RF4 (decisión) | parcial | P2 deja el primer caso "no hay productivo → entrenar"; el resto de decide_training lo cubre P1 |
| RF5 (entrenamiento + MLflow) | sí | `train.py` registra params, métricas, artefactos, modelo, batch_id, commit_sha, training_reason |
| RF6 (comparación + promoción) | sí | `evaluate.py` + `promote.py` con regla explícita parametrizable |
| RF7 (recarga sin redespliegue) | sí | `model_loader` con poller + `/reload-model` + fallback |
| RF8 (registro de inferencias) | sí | `inference_log` escribe en `raw_data.inference_events` |
| RF10 (observabilidad) | sí | `/metrics` emite las series exactas que Grafana ya consulta |

## Checklist para integración

Bloqueantes que dependen de P1:
- [ ] P1 confirmar `clean_data.properties` (nombre y columnas) — hoy hay
      asumido `CLEAN_TABLE=clean_data.properties`, configurable por env var.
- [ ] P1 confirmar o reemplazar el DDL propuesto de `raw_data.inference_events`
      (sección 2 de `docs/contracts/p2-interfaces.md`).
- [ ] P1 confirmar `raw_data.training_audit` (lo lee Streamlit, no FastAPI).

Bloqueantes que dependen de P3:
- [ ] P3 agregar `MLFLOW_MODEL_NAME`, `MLFLOW_PRODUCTION_ALIAS`,
      `MLFLOW_S3_ENDPOINT_URL`, `AWS_*`, `RELOAD_TOKEN` al `fastapi-secret`
      de Kubernetes (hoy faltan).
- [ ] P3 cambiar el tag de imagen del `Deployment fastapi` de `:latest`
      a `:sha-${commit}` para reproducibilidad (esto lo exige el rubric).
- [ ] P3 publicar la imagen de `training/` al primer push (el workflow ya está
      en `develop`, debería dispararse al mergear este PR).

## Smoke test pendiente (lo haré antes de pedir review)

- [ ] `docker compose up -d postgres minio mlflow`
- [ ] Cargar CSV sintético a `clean_data.properties`
- [ ] `docker compose --profile training run --rm training train --batch-id smoke-1 --training-reason "smoke test"`
- [ ] Verificar run en MLflow UI (`http://localhost:15000`)
- [ ] `docker compose up -d fastapi` → `curl POST /predict` → fila en `raw_data.inference_events`

## Notas

- Branding/git: cumple convenciones del doc (sección 8: `feature/p2-*` → PR a
  `develop`, mensajes `feat(scope): ...` minúsculas).
- El workflow `build-fastapi.yml` y `build-training.yml` ya filtran por
  `paths: ['fastapi/**']` y `['training/**']`, así que el merge a `develop`
  dispara ambas builds automáticamente.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
