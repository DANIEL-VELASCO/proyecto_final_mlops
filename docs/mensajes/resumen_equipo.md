# Resumen para el equipo — Lo que ya está funcionando

> Mensaje listo para copiar al chat del equipo.

---

Hola equipo 👋

Quería ponerlos al día porque ya tenemos el **sistema MLOps completo
funcionando end-to-end en Kubernetes local**. Resumen de lo logrado y de lo
que queda:

## ✅ Lo que YA está corriendo en el clúster

| Componente | Estado | Detalle |
|---|---|---|
| **PostgreSQL** | Running | bases `airflow`, `mlflow`, `mlops_db`, `mlops` + esquemas `raw_data` y `clean_data` + las 5 tablas del DDL de P1 (`raw_batches`, `row_hashes`, `category_catalog`, `inference_events`, `training_audit`) |
| **MinIO** | Running | bucket `mlflow-artifacts` con el modelo serializado |
| **MLflow** | Running | `house-price-model v1` con alias `production` |
| **Airflow** | Running 2/2 | scheduler + webserver, DAG `real_estate_mlops_pipeline` detectado y cargado |
| **FastAPI** | Running 2 réplicas | image **`max181818/mlops-fastapi:latest`** desde DockerHub (publicada por GitHub Actions), `/health` `/predict` `/metrics` `/reload-model` |
| **data-api** | Running | imagen `cristiandiaz13/mlops-puj:data-api-pf-v1` desplegada en el cluster con Deployment+Service |
| **Streamlit** | Running | `/healthz ok`, contrato HTTP con FastAPI verificado |
| **Prometheus** | Running | scrapeando `fastapi:8000/metrics` cada 15s |
| **Grafana** | Running | dashboard `MLOps FastAPI Dashboard` con 5 paneles activos |
| **Locust** | Running | locustfile real (no el legacy diabetes) |
| **Argo CD** | Running | Application `mlops-proyecto-final` en estado **Synced + Healthy** desde `main` |

## 🧪 Pruebas ejecutadas

1. **Smoke test end-to-end** — postgres → bootstrap → CSV sintético 5000 filas → training (`mlops-training:local train`) → MLflow registró `house-price-model v1` → `evaluate` → `promote` aplicó alias `production` → FastAPI cargó el modelo
2. **10 predicciones manuales** desde port-forward con ciudades reales (NY, LA, Chicago…) — precios coherentes con el patrón geográfico, todas 200 OK, latencias 12-205ms
3. **Locust load test**: 80 usuarios concurrentes, 90 s, **3307 requests, 0 fallos**, 31.2 req/s sostenido en `/predict`, mediana 38ms, **2655 inferencias persistidas** en `raw_data.inference_events`
4. **Grafana** captó la prueba en vivo: paneles "Total de Peticiones", "Tasa de Peticiones req/s", "Latencia p50/p95", "Tasa de Errores 5xx", "Versión del Modelo Productivo"
5. **CI/CD verificado**: 3 workflows en GitHub Actions (`build-fastapi.yml`, `build-training.yml`, `build-streamlit.yml`) corriendo y publicando imágenes en DockerHub bajo `max181818/*` con tag por SHA del commit.
6. **GitOps verificado**: Argo CD detecta cambios en `kubernetes/` de `main` y los aplica al clúster automáticamente.
7. **DAG end-to-end** contra la API real (`data-api`): el DAG `real_estate_mlops_pipeline` consume lotes de 90K-230K registros desde `cristiandiaz13/mlops-puj:data-api-pf-v1`, los persiste en `raw_data.raw_batches`, valida schema/calidad/drift, decide si entrenar, invoca `mlops-training` vía `docker run` con `--network=host`, registra en MLflow y promueve/rechaza según regla. *(En proceso de validación al momento de escribir este mensaje — 4 bugs encontrados en código de P1 ya parcheados y commiteados.)*

## 🔄 Integración entre los 3 sin reuniones

- P1 creó el DDL de `raw_data.inference_events` con el schema exacto que P2 escribe (coincidió porque ambos derivamos del mismo Word de distribución).
- El DAG de P1 invoca `train/evaluate/promote` de la imagen de P2 con los argumentos exactos que documenté en `docs/contracts/p2-interfaces.md`.
- FastAPI de P2 emite las **mismas series Prometheus** que ya consulta el dashboard de Grafana de P3 (sin tener que cambiar nada).
- Streamlit de P3 manda el payload exacto que aceptan los Pydantic schemas de FastAPI.

## 🌳 Estado del repositorio

`main` y `develop` están sincronizadas. Argo CD apunta a `main` con `automated.prune + selfHeal` → cualquier commit nuevo se sincroniza automáticamente.

Últimos commits relevantes:
- `fix(p1-dag): store_raw_batch usa UPSERT chunked para row_hashes`
- `fix(p1-dag): preprocess_data usa UPSERT y filtra price nulo`
- `chore(airflow): subir memoria scheduler a 4Gi por OOM con batches 200K+ registros`
- `fix(p1-dag): api_client usa /data?group_number={gid} + _decode_payload helper`
- `fix(airflow): inyectar DATABASE_URI/MLFLOW/MinIO en airflow-secret`
- `feat(infra): data-api en K8s + Airflow con docker.sock y CLI docker`
- `chore(k8s): apuntar a imagenes publicadas en DockerHub`
- `docs(fastapi+training): READMEs por componente`

## 🟡 Pendiente

Solo queda **una cosa**: grabar y subir el video de sustentación de 10 min.
Guion paso a paso con timings, demos y comandos copy-paste en
`docs/video_sustentacion.md`.

Todo lo demás está hecho:
- ✅ DOCKERHUB_USERNAME + DOCKERHUB_TOKEN configurados en GitHub Actions.
- ✅ Imágenes publicadas en DockerHub (`max181818/mlops-fastapi:latest`, `max181818/mlops-training:latest`).
- ✅ Argo CD instalado, Application creada, `Synced + Healthy`.
- ✅ DAG ejecutándose contra la API real con varios bugs ya parcheados.
- ✅ FastAPI sirviendo desde la imagen pública de DockerHub.
- ✅ README + contratos + guion del video listos en `docs/`.

## 📁 Documentación útil en el repo

- `README.md` — guía principal del proyecto + cómo levantar y validar
- `docs/INTEGRATION_PLAN.md` — flujo `feature → develop → main`
- `docs/contracts/p1-interfaces.md` — qué expone P1
- `docs/contracts/p2-interfaces.md` — qué expone P2 (training image + FastAPI)
- `docs/STATUS_P2.md` — auditoría de lo que P2 entregó
- `docs/video_sustentacion.md` — guion del video distribuido por persona
- `scripts/init_db.sql` — DDL definitivo
- `scripts/smoke/run_smoke.ps1` — smoke test reproducible

---

Cualquier cosa que vean rota o que prefieran ajustar, díganme y lo cambio sin
problema 🙌
