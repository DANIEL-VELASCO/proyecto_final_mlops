# Proyecto Final MLOps 2026-1

**Nivel 4: Automatización, decisión de reentrenamiento y despliegue GitOps**
Pontificia Universidad Javeriana — Mayo 2026

Sistema MLOps completo para estimación de precios de propiedades inmobiliarias.

---

## Arquitectura

```
        GitHub  ──►  GitHub Actions  ──►  DockerHub
            │                                │
            └───────────────► Argo CD ◄──────┘
                                │
                                ▼
                         ┌──────────────┐
                         │  Kubernetes  │
                         └──────────────┘
                                │
            ┌───────────────────┼─────────────────────┐
            │                   │                     │
       ┌────▼────┐         ┌────▼────┐           ┌────▼────┐
       │ Airflow │         │ MLflow  │           │ FastAPI │
       │         │◄───────►│         │◄─────────►│         │
       └────┬────┘         └────┬────┘           └────┬────┘
            │                   │                     │
            │              ┌────▼────┐           ┌────▼─────┐
            │              │  MinIO  │           │Streamlit │
            │              │        │           │          │
            │              └─────────┘           └──────────┘
            ▼                                          │
       ┌─────────┐                                     │
       │PostgreSQL│ ◄──────── Locust ──────────────────┤
       │  RAW +   │                                    │
       │  CLEAN   │            Prometheus  ◄────────── ┤
       └─────────┘                  │                  │
                                    ▼                  │
                                Grafana ───────────────┘
```

## Equipo

| Persona | Rol | Componentes |
|---|---|---|
| **Persona 1** — David Garzón | Data Engineer | `airflow/` (DAG `real_estate_mlops_pipeline`, `api_client.py`, `preprocessing.py`), `scripts/init_db.sql`, esquemas RAW_DATA y CLEAN_DATA |
| **Persona 2** — yo | ML Engineer | `training/` (pipeline `train/evaluate/promote`), `fastapi/` (`/health` `/predict` `/metrics` `/reload-model`), MLflow + MinIO |
| **Persona 3** — Daniel Velasco | DevOps / MLOps | `kubernetes/` (todos los manifests), `streamlit/`, `locust/`, `grafana/`, `.github/workflows/`, Argo CD |

## Estado actual

 Sistema validado **end-to-end** en clúster Kubernetes local. Modelo `house-price-model v1` con alias `production` sirviendo predicciones; 2655 inferencias registradas durante load test de 90 segundos (0 fallos).

## Estructura del repositorio

```
.
├── .github/workflows/      # CI/CD — build + push de imágenes a DockerHub
├── airflow/                # DAGs (Persona 1)
│   ├── dags/
│   │   ├── main_pipeline.py
│   │   ├── api_client.py
│   │   └── preprocessing.py
│   ├── Dockerfile
│   └── requirements.txt
├── training/               # Pipeline de entrenamiento (Persona 2)
│   ├── preprocess.py
│   ├── train.py
│   ├── evaluate.py
│   ├── promote.py
│   ├── Dockerfile
│   └── entrypoint.sh       # subcomandos: train | evaluate | promote
├── fastapi/                # API de inferencia (Persona 2)
│   ├── main.py
│   ├── schemas.py
│   ├── model_loader.py     # thread-safe + poller + fallback
│   ├── inference_log.py    # escribe en raw_data.inference_events
│   └── preprocess.py
├── streamlit/              # UI (Persona 3)
├── locust/                 # Pruebas de carga (Persona 3)
├── kubernetes/             # Manifests (Persona 3)
│   ├── argocd/             # Application GitOps
│   ├── airflow/, databases/, fastapi/, mlflow/, minio/,
│   ├── streamlit/, grafana/, prometheus/
│   ├── namespace.yaml
│   └── secrets.yaml
├── scripts/
│   ├── init_db.sql         # DDL definitivo (P1)
│   └── smoke/              # smoke test reproducible (P2)
├── docs/
│   ├── INTEGRATION_PLAN.md
│   ├── STATUS_P2.md
│   ├── contracts/          # contratos entre personas
│   ├── mensajes/           # mensajes a/del equipo
│   └── video_sustentacion.md
├── docker-compose.yml      # entorno local opcional
└── README.md
```

## Cómo levantar el sistema (paso a paso)

### Requisitos

- Docker Desktop (con Kubernetes habilitado) o un clúster equivalente
- `kubectl`, `git`
- (Opcional) Python 3.11 si querés correr el smoke test desde el host

### 1. Clonar y construir imágenes

```bash
git clone https://github.com/DANIEL-VELASCO/proyecto_final_mlops.git
cd proyecto_final_mlops

# Mientras GitHub Actions no publique en DockerHub, construimos local:
docker build -t mlops-fastapi:local ./fastapi
docker build -t mlops-training:local ./training
docker build -t mlops-airflow:local ./airflow
```

### 2. Crear namespace y secrets

```bash
kubectl apply -f kubernetes/namespace.yaml
kubectl apply -f kubernetes/secrets.yaml
```

### 3. Bases de datos + esquemas

```bash
kubectl apply -f kubernetes/databases/
# espera a que postgres-0 esté Running:
kubectl -n mlops wait pod/postgres-0 --for=condition=ready --timeout=120s

# Aplica el DDL definitivo de P1:
kubectl -n mlops exec -i postgres-0 -- psql -U mlops -d postgres < scripts/init_db.sql
```

### 4. MinIO + MLflow

```bash
kubectl apply -f kubernetes/minio/
kubectl apply -f kubernetes/mlflow/

# Crear bucket mlflow-artifacts (port-forward + boto3 o mc):
kubectl -n mlops port-forward svc/minio-service 19010:9000 &
python -c "import boto3; s3=boto3.client('s3', endpoint_url='http://localhost:19010', aws_access_key_id='minio_admin', aws_secret_access_key='minio_secret123'); s3.create_bucket(Bucket='mlflow-artifacts')"
```

### 5. FastAPI, Streamlit, Prometheus, Grafana, Locust

```bash
kubectl apply -f kubernetes/fastapi/
kubectl apply -f kubernetes/streamlit/
kubectl apply -f kubernetes/prometheus/
kubectl apply -f kubernetes/grafana/
kubectl apply -f kubernetes/locust/   # si existe; si no, está en otra carpeta
```

### 6. Airflow (con DAG ya incluido en la imagen)

```bash
kubectl apply -f kubernetes/airflow/
```

### 7. Argo CD (GitOps)

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.11.4/manifests/install.yaml
kubectl -n argocd rollout status deployment argocd-server --timeout=240s

# Aplica la Application que sincroniza el repo:
kubectl apply -f kubernetes/argocd/application.yaml
```

## Cómo validar que todo funciona

### Smoke test automático

```powershell
# Genera datos sintéticos, entrena, promueve, valida /predict, verifica BD:
pwsh ./scripts/smoke/run_smoke.ps1
```

### Manual (con port-forwards)

```bash
kubectl -n mlops port-forward svc/fastapi 8000:8000     # FastAPI
kubectl -n mlops port-forward svc/mlflow-service 5000:5000 # MLflow UI
kubectl -n mlops port-forward svc/grafana-service 3000:3000 # Grafana (admin/admin123)
kubectl -n mlops port-forward svc/airflow 8080:8080     # Airflow UI
kubectl -n mlops port-forward svc/streamlit-service 8501:8501
kubectl -n mlops port-forward svc/locust-service 8089:8089
```

| URL | Qué ver |
|---|---|
| http://localhost:8000/docs | Swagger de FastAPI |
| http://localhost:8000/health | `{ "model_loaded": true, "version": "1", "alias": "production" }` |
| http://localhost:5000 | MLflow UI con experimento `house-price` y modelo registrado |
| http://localhost:3000 | Grafana — dashboard `MLOps FastAPI Dashboard` |
| http://localhost:8080 | Airflow — DAG `real_estate_mlops_pipeline` |
| http://localhost:8501 | Streamlit — sección inferencia + historial |
| http://localhost:8089 | Locust UI — para lanzar load tests |

### Métricas que expone FastAPI (consumidas por Grafana)

- `http_requests_total{handler, method, status}` — automático
- `http_request_duration_seconds_bucket{le}` — automático
- `model_version_info{version, alias, model_name}` — gauge custom
- `model_load_total{result}` — counter custom
- `inference_log_failures_total` — counter custom

## Flujo de datos (RF1-RF10 del PDF)

1. **RF1 – Recolección incremental**: el DAG llama a `data-api-pf-v1` y guarda en `raw_data.raw_batches`
2. **RF2 – Persistencia separada**: `raw_data` para crudos, `clean_data.properties` para procesados
3. **RF3 – Validación**: schema check, calidad, drift (Kolmogorov-Smirnov), nuevas categorías
4. **RF4 – Decisión de entrenamiento**: bifurcación basada en reglas técnicas
5. **RF5 – Entrenamiento + MLflow**: registra params, métricas MAE/RMSE/MAPE/R², artefactos, modelo
6. **RF6 – Comparación + promoción**: regla MAE −3 % / RMSE +1 %, asigna alias `production`
7. **RF7 – Recarga sin redespliegue**: FastAPI poller cada 30 s + `/reload-model` con token
8. **RF8 – Registro de inferencias**: cada `/predict` se persiste en `raw_data.inference_events`
9. **RF9 – Streamlit**: formulario de inferencia + historial leído desde `raw_data.training_audit`
10. **RF10 – Observabilidad**: métricas Prometheus + dashboard Grafana + Locust

## Decisiones técnicas relevantes

- **OneHotEncoder con `handle_unknown="ignore"`** + `min_frequency=10` → maneja ciudades/agencias nuevas sin romper el pipeline ni inflar dimensionalidad
- **`mlflow.sklearn`** (no `pyfunc`) → evita el bug de schema enforcement con `StringDtype` de pandas
- **Recarga del modelo con `threading.RLock` + snapshot inmutable** → garantiza que `/predict` no quede en estado inconsistente durante un swap
- **Fallback al modelo previamente cargado** si la nueva carga falla → resilencia ante un MLflow caído o un modelo corrupto
- **Alias `production` en MLflow Model Registry** (no `Stage`, que está deprecated en MLflow 2.x) → identificación consistente del modelo productivo
- **Regla de promoción configurable** (`--mae-improvement-pct`, `--rmse-tolerance-pct`) → permite ajustar el criterio sin tocar código

## Branching y CI/CD

- `feature/p1-*`, `feature/p2-*`, `feature/p3-*` para trabajo de cada integrante
- PRs hacia `develop`; cuando todo está validado en K8s, `develop → main`
- GitHub Actions publica en DockerHub al hacer push a `main` o `develop`:
  - `<user>/mlops-fastapi:sha-<commit>` + `:latest`
  - `<user>/mlops-training:sha-<commit>` + `:latest`
  - `<user>/mlops-streamlit:sha-<commit>` + `:latest`
- Argo CD detecta cambios en `kubernetes/` y sincroniza automáticamente (`prune: true`, `selfHeal: true`)

## Documentación adicional

- [`docs/INTEGRATION_PLAN.md`](docs/INTEGRATION_PLAN.md) — flujo de PRs
- [`docs/contracts/p1-interfaces.md`](docs/contracts/p1-interfaces.md) — contrato de P1
- [`docs/contracts/p2-interfaces.md`](docs/contracts/p2-interfaces.md) — contrato de P2
- [`docs/STATUS_P2.md`](docs/STATUS_P2.md) — auditoría de P2
- [`docs/video_sustentacion.md`](docs/video_sustentacion.md) — guion del video
- [`scripts/smoke/README.md`](scripts/smoke/README.md) — smoke test
