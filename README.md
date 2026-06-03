# Sistema MLOps — Estimación de Precios Inmobiliarios

**Nivel 4: Automatización completa, decisión de reentrenamiento y despliegue GitOps**  
Pontificia Universidad Javeriana — 2026-1

---

## Tabla de contenidos

1. [Descripción general](#1-descripción-general)
2. [Arquitectura del sistema](#2-arquitectura-del-sistema)
3. [Stack tecnológico](#3-stack-tecnológico)
4. [Estructura del repositorio](#4-estructura-del-repositorio)
5. [Base de datos — Esquemas y tablas](#5-base-de-datos--esquemas-y-tablas)
6. [Pipeline de orquestación — Airflow DAG](#6-pipeline-de-orquestación--airflow-dag)
7. [Pipeline de ML — Training, Evaluación y Promoción](#7-pipeline-de-ml--training-evaluación-y-promoción)
8. [API de inferencia — FastAPI](#8-api-de-inferencia--fastapi)
9. [Interfaz de usuario — Streamlit](#9-interfaz-de-usuario--streamlit)
10. [Observabilidad — Prometheus y Grafana](#10-observabilidad--prometheus-y-grafana)
11. [Pruebas de carga — Locust](#11-pruebas-de-carga--locust)
12. [CI/CD — GitHub Actions y DockerHub](#12-cicd--github-actions-y-dockerhub)
13. [GitOps — Argo CD](#13-gitops--argo-cd)
14. [Despliegue en Kubernetes](#14-despliegue-en-kubernetes)
15. [Entorno local con Docker Compose](#15-entorno-local-con-docker-compose)
16. [Puertos y credenciales de acceso](#16-puertos-y-credenciales-de-acceso)
17. [Flujo end-to-end completo](#17-flujo-end-to-end-completo)
18. [Decisiones técnicas relevantes](#18-decisiones-técnicas-relevantes)

---

## 1. Descripción general

Este proyecto implementa un sistema **MLOps de Nivel 4** que automatiza el ciclo de vida completo de un modelo de Machine Learning para estimar precios de propiedades inmobiliarias. El sistema opera de forma continua e incremental: recolecta datos desde una API externa por lotes, los valida, detecta drift y nuevas categorías, decide si entrenar un nuevo modelo con criterios técnicos objetivos, y promueve automáticamente al modelo candidato si supera al modelo en producción.

**Problema:** Regresión supervisada — estimar el precio de una propiedad a partir de sus características (habitaciones, baños, tamaño, ubicación, etc.).

**Dataset:** Registros de propiedades inmobiliarias en Estados Unidos. Variables: `brokered_by`, `status`, `price` (target), `bed`, `bath`, `acre_lot`, `street`, `city`, `state`, `zip_code`, `house_size`, `prev_sold_date`.

**Fuente de datos:** API externa por lotes (imagen Docker `cristiandiaz13/mlops-puj:data-api-pf-v1`). La API es stateful y entrega un batch diferente en cada llamada para el mismo `group_id`. No permite descargar todo el dataset de una vez — el diseño incremental es obligatorio.

---

## 2. Arquitectura del sistema

```
  ┌─────────────────────────────────────────────────────────────────────┐
  │                         GitHub Repository                           │
  │   feature/* ──► develop ──► main                                    │
  └──────────┬──────────────────────────────┬──────────────────────────┘
             │ push                          │ push
             ▼                               ▼
    ┌─────────────────┐             ┌──────────────────┐
    │  GitHub Actions │             │    Argo CD        │
    │  CI/CD Pipelines│             │  (GitOps sync)    │
    └────────┬────────┘             └────────┬─────────┘
             │ docker push                    │ kubectl apply
             ▼                               ▼
    ┌─────────────────────────────────────────────────────┐
    │                   DockerHub                          │
    │  mlops-airflow | mlops-fastapi | mlops-training      │
    │  mlops-streamlit                                     │
    └─────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                        Kubernetes (namespace: mlops)                 │
  │                                                                     │
  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
  │  │   Airflow    │    │    MLflow    │    │       FastAPI         │  │
  │  │  (scheduler  │◄──►│  (tracking + │◄──►│  /predict /health    │  │
  │  │  + webserver │    │   registry)  │    │  /metrics /reload    │  │
  │  │  + triggerer)│    └──────┬───────┘    └──────────┬───────────┘  │
  │  └──────┬───────┘           │                       │              │
  │         │                   ▼                       │              │
  │         │           ┌──────────────┐                ▼              │
  │         │           │    MinIO     │         ┌──────────────┐      │
  │         │           │  (S3 —       │         │  Streamlit   │      │
  │         │           │  artefactos) │         │  (UI predict │      │
  │         │           └──────────────┘         │  + historial)│      │
  │         ▼                                    └──────────────┘      │
  │  ┌──────────────┐                                                   │
  │  │  PostgreSQL  │   ┌──────────────┐    ┌──────────────────────┐  │
  │  │  raw_data    │   │  Prometheus  │    │       Grafana         │  │
  │  │  clean_data  │◄──│  (scraping)  │───►│  (dashboards MLOps)  │  │
  │  │  mlflow DB   │   └──────────────┘    └──────────────────────┘  │
  │  │  airflow DB  │                                                   │
  │  └──────────────┘   ┌──────────────┐                               │
  │                     │    Locust    │                               │
  │                     │ (load tests) │                               │
  │                     └──────────────┘                               │
  └─────────────────────────────────────────────────────────────────────┘
             ▲
             │ GET /data?group_number=1
  ┌──────────┴──────────┐
  │  Data API externa   │
  │  (pf-v1, stateful)  │
  └─────────────────────┘
```

**Flujo principal:**
1. El DAG de Airflow llama a la Data API y obtiene un batch de registros
2. Valida, limpia y persiste los datos en PostgreSQL
3. Aplica criterios técnicos para decidir si entrenar
4. Si corresponde, lanza el pipeline de ML dentro de un contenedor Docker
5. El modelo candidato se compara con el productivo; si gana, se promueve en MLflow Registry
6. FastAPI detecta el nuevo modelo (polling cada 30s) y lo carga sin reiniciarse
7. Streamlit expone inferencia en tiempo real e historial de entrenamientos
8. Prometheus recopila métricas y Grafana las visualiza

---

## 3. Stack tecnológico

| Capa | Tecnología | Versión / Imagen |
|------|-----------|-----------------|
| Orquestación | Apache Airflow | `apache/airflow:2.8.1` (custom) |
| ML tracking | MLflow | `ghcr.io/mlflow/mlflow:latest` |
| Model training | scikit-learn | 1.4.x |
| Artifact store | MinIO | `minio/minio:latest` |
| Base de datos | PostgreSQL | 15 |
| Inferencia | FastAPI + Uvicorn | 0.111.0 + 0.30.1 |
| UI | Streamlit | 1.35.0 |
| Observabilidad | Prometheus + Grafana | `prom/prometheus` + `grafana/grafana` |
| Pruebas de carga | Locust | custom |
| Contenedores | Docker + Docker Compose | 24+ |
| Orquestación K8s | Kubernetes | 1.29+ |
| GitOps | Argo CD | 2.11.4 |
| CI/CD | GitHub Actions | — |
| Registro de imágenes | DockerHub | — |

---

## 4. Estructura del repositorio

```
.
├── .github/
│   └── workflows/
│       ├── build-airflow.yml       # CI: build + push mlops-airflow
│       ├── build-fastapi.yml       # CI: build + push mlops-fastapi
│       ├── build-streamlit.yml     # CI: build + push mlops-streamlit
│       └── build-training.yml      # CI: build + push mlops-training
│
├── airflow/
│   ├── dags/
│   │   ├── main_pipeline.py        # DAG principal (18 tareas)
│   │   ├── api_client.py           # Cliente con reintentos para la Data API
│   │   └── preprocessing.py        # Validación, drift, nuevas categorías
│   ├── Dockerfile
│   └── requirements.txt
│
├── training/
│   ├── train.py                    # Entrena Random Forest, registra en MLflow
│   ├── evaluate.py                 # Compara candidato vs. productivo (holdout)
│   ├── promote.py                  # Asigna alias "production" en MLflow Registry
│   ├── preprocess.py               # ColumnTransformer, features, limpieza
│   ├── entrypoint.sh               # Multicomando: train | evaluate | promote
│   ├── Dockerfile
│   └── requirements.txt
│
├── fastapi/
│   ├── main.py                     # Endpoints: /health /predict /metrics /reload-model
│   ├── model_loader.py             # Carga thread-safe + poller + fallback
│   ├── inference_log.py            # Persiste inferencias en raw_data.inference_events
│   ├── schemas.py                  # Pydantic: PropertyRequest, PredictionResponse
│   ├── preprocess.py               # Preprocesamiento del payload de inferencia
│   ├── Dockerfile
│   └── requirements.txt
│
├── streamlit/
│   ├── app.py                      # Tab Inferencia + Tab Historial de entrenamientos
│   ├── Dockerfile
│   └── requirements.txt
│
├── locust/
│   ├── locustfile.py               # 8 tareas /predict + 2 tareas /health
│   ├── Dockerfile
│   └── README.md
│
├── kubernetes/
│   ├── namespace.yaml              # namespace: mlops
│   ├── secrets.yaml                # Credenciales de todos los servicios
│   ├── airflow/                    # Deployment, Service, PVC, ConfigMap
│   ├── databases/                  # PostgreSQL StatefulSet, init ConfigMap
│   ├── fastapi/                    # Deployment (2 réplicas), Service, NodePort
│   ├── mlflow/                     # Deployment, Service, NodePorts
│   ├── minio/                      # StatefulSet, PVC, Services S3+UI
│   ├── streamlit/                  # Deployment, Service
│   ├── prometheus/                 # Deployment, ConfigMap scrape, PVC
│   ├── grafana/                    # Deployment, Dashboard ConfigMap, Datasource
│   ├── locust/                     # Deployment, Service
│   ├── data-api/                   # Deployment de la API externa de datos
│   └── argocd/
│       └── application.yaml        # Application GitOps (auto-sync + self-heal)
│
├── scripts/
│   ├── init_db.sql                 # DDL completo: raw_data + clean_data
│   └── smoke/
│       ├── run_smoke.ps1           # Smoke test automatizado (PowerShell)
│       ├── bootstrap_db.sql        # Datos sintéticos para pruebas
│       ├── gen_synthetic_clean_data.py
│       └── README.md
│
├── docs/
│   ├── contracts/
│   │   ├── p1-interfaces.md        # Contrato de interfaces entre componentes
│   │   └── p2-interfaces.md
│   ├── INTEGRATION_PLAN.md
│   └── video_sustentacion.md
│
├── grafana_dashboard.json          # Dashboard predefinido para importar
├── docker-compose.yml              # Stack completo para desarrollo local
└── README.md
```

---

## 5. Base de datos — Esquemas y tablas

El sistema utiliza **PostgreSQL 15** con cuatro bases de datos y un DDL completo definido en `scripts/init_db.sql`.

### Bases de datos

| Base de datos | Propósito |
|--------------|-----------|
| `mlops` | Datos del negocio (raw_data + clean_data) |
| `mlflow` | Metadatos de experimentos y modelos |
| `airflow` | Estado del scheduler y DAG runs |

### Esquema `raw_data`

**`raw_batches`** — Registro de cada lote obtenido de la API

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `batch_id` | VARCHAR PK | Identificador único del lote (ej: `batch_1_0002`) |
| `group_id` | INTEGER | Grupo de la API (siempre 1 en este proyecto) |
| `batch_number` | INTEGER | Número secuencial del lote |
| `n_records` | INTEGER | Registros recibidos |
| `raw_payload` | JSONB | Payload completo sin modificar |
| `status` | VARCHAR | `received` / `processed` / `error` |
| `error_message` | TEXT | Detalle si hubo error |
| `created_at` | TIMESTAMPTZ | Timestamp de inserción |

**`row_hashes`** — Deduplicación entre lotes

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `row_hash` | VARCHAR UNIQUE | Hash MD5 de cada fila |
| `batch_id` | VARCHAR FK | Lote en que apareció por primera vez |
| `created_at` | TIMESTAMPTZ | — |

**`category_catalog`** — Catálogo de valores conocidos para features categóricas

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `feature` | VARCHAR | Nombre del campo (city, state, status, etc.) |
| `value` | VARCHAR | Valor observado |
| `first_seen` | TIMESTAMPTZ | Primera vez que apareció |
| `last_seen` | TIMESTAMPTZ | Última vez que apareció |

**`training_audit`** — Auditoría completa de cada ejecución del pipeline

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `batch_id` | VARCHAR FK | Lote que disparó esta ejecución |
| `execution_date` | TIMESTAMPTZ | Cuándo se corrió |
| `n_records` | INTEGER | Registros procesados |
| `decision` | VARCHAR | `train` o `skip` |
| `reason` | TEXT | Razón de la decisión |
| `null_pct_max` | FLOAT | Máximo % de nulos por columna |
| `duplicate_pct` | FLOAT | % de duplicados detectados |
| `drift_detected` | BOOLEAN | ¿Se detectó drift? |
| `drift_variables` | JSON | Variables con drift (KS-test p < 0.05) |
| `new_categories` | JSON | Categorías nuevas detectadas |
| `volume_pct` | FLOAT | Crecimiento de volumen vs. lote anterior |
| `mlflow_run_id` | VARCHAR | Run ID del experimento en MLflow |
| `model_version` | VARCHAR | Versión del modelo candidato |
| `mae_candidate` | FLOAT | MAE del candidato en holdout |
| `mae_production` | FLOAT | MAE del productivo en holdout |
| `rmse_candidate` | FLOAT | RMSE del candidato |
| `rmse_production` | FLOAT | RMSE del productivo |
| `promoted` | BOOLEAN | ¿El candidato fue promovido? |
| `promotion_reason` | TEXT | Razón de la decisión de promoción |
| `status` | VARCHAR | `success` / `error` |

**`inference_events`** — Registro de cada llamada a `/predict`

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `request_id` | UUID PK | Identificador único de la inferencia |
| `occurred_at` | TIMESTAMPTZ | Timestamp de la petición |
| `model_name` | VARCHAR | Nombre del modelo en MLflow |
| `model_version` | VARCHAR | Versión usada para inferir |
| `model_alias` | VARCHAR | Alias usado (siempre `production`) |
| `input_payload` | JSONB | Features enviados por el cliente |
| `prediction` | FLOAT | Precio estimado |
| `status` | VARCHAR | `ok` / `error` |
| `error_message` | TEXT | Detalle si falló |
| `latency_ms` | FLOAT | Tiempo de respuesta en milisegundos |

### Esquema `clean_data`

**`properties`** — Datos listos para entrenamiento

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `id` | SERIAL PK | — |
| `batch_id` | VARCHAR FK | Lote de origen |
| `row_hash` | VARCHAR UNIQUE | Hash para evitar duplicados |
| `processed_ts` | TIMESTAMPTZ | Cuándo se limpió |
| `brokered_by` | VARCHAR | Inmobiliaria/bróker |
| `status` | VARCHAR | Estado de la propiedad |
| `price` | FLOAT | Precio (target) |
| `bed` | FLOAT | Habitaciones |
| `bath` | FLOAT | Baños |
| `acre_lot` | FLOAT | Tamaño del lote en acres |
| `street` | VARCHAR | Calle |
| `city` | VARCHAR | Ciudad |
| `state` | VARCHAR | Estado |
| `zip_code` | FLOAT | Código postal |
| `house_size` | FLOAT | Tamaño de la casa (sq ft) |
| `prev_sold_date` | DATE | Fecha de venta anterior |

---

## 6. Pipeline de orquestación — Airflow DAG

### Configuración del DAG

| Parámetro | Valor |
|----------|-------|
| **DAG ID** | `real_estate_mlops_pipeline` |
| **Schedule** | `@daily` |
| **Max active runs** | 1 (secuencial — previene condiciones de carrera) |
| **Retries** | 1 por tarea, delay de 5 minutos |
| **Archivo** | `airflow/dags/main_pipeline.py` |

### Flujo de tareas

```
start
  │
  ▼
fetch_batch_from_api
  │
  ▼
store_raw_batch
  │
  ▼
validate_schema ──────── FALLA → marca lote como error, fin
  │
  ▼
validate_data_quality ─── FALLA → marca lote como error, fin
  │
  ├──────────────┐
  ▼              ▼
detect_new_    detect_data_drift
categories        │
  │              │
  └──────┬───────┘
         ▼
    preprocess_data
         │
         ▼
    decide_training
    (BranchPythonOperator)
         │
    ┌────┴───────┐
    ▼            ▼
skip_training  train_candidate_model
    │              │
    │              ▼
    │       evaluate_candidate_model
    │              │
    │              ▼
    │         decide_promotion
    │         (BranchPythonOperator)
    │              │
    │         ┌────┴────────┐
    │         ▼             ▼
    │    promote_model   reject_model
    │         │             │
    └────┬────┘             │
         ▼                  │
  notify_or_log_result ◄────┘
         │
         ▼
        end
```

### Descripción de cada tarea

**`fetch_batch_from_api`**  
Llama a `GET http://data-api/data?group_number=1`. La API es stateful y devuelve el siguiente batch en cada llamada (~21 MB de payload). El cliente `api_client.py` implementa reintentos con backoff exponencial (hasta 3 intentos, timeout configurable). Almacena el resultado en XCom para la siguiente tarea.

**`store_raw_batch`**  
Parsea el JSON recibido, calcula el número de lote correlativo y persiste en `raw_data.raw_batches` como JSONB. Calcula el hash MD5 de cada fila individual y registra en `raw_data.row_hashes` para detectar duplicados entre lotes futuros. Retorna el `batch_id` en XCom.

**`validate_schema`**  
Verifica que el DataFrame contenga exactamente las 12 columnas esperadas: `brokered_by`, `status`, `price`, `bed`, `bath`, `acre_lot`, `street`, `city`, `state`, `zip_code`, `house_size`, `prev_sold_date`. Si falta alguna o hay columnas extra inesperadas, marca el lote como `error` y termina el pipeline para ese run.

**`validate_data_quality`**  
Dos validaciones:
- Nulos: ninguna columna puede superar el 50% de valores nulos
- Precios válidos: `price` debe ser numérico y positivo

Si falla, marca el lote como error y termina.

**`detect_new_categories`**  
Compara los valores únicos de las features categóricas (`brokered_by`, `status`, `street`, `city`, `state`) contra el catálogo almacenado en `raw_data.category_catalog`. Identifica categorías nuevas y calcula su frecuencia relativa dentro del batch. Actualiza el catálogo con los nuevos valores. El resultado (lista de categorías nuevas con frecuencia ≥ 5%) se guarda en XCom.

**`detect_data_drift`**  
Aplica el test de Kolmogorov-Smirnov sobre las features numéricas (`bed`, `bath`, `acre_lot`, `house_size`, `price`) comparando la distribución del lote actual vs. el lote anterior. Considera que hay drift si el p-value < 0.05. Lista las variables con drift en XCom.

**`preprocess_data`**  
Limpieza del lote:
- Elimina filas con `price` nulo o ≤ 0
- Convierte columnas numéricas al tipo correcto
- Elimina duplicados usando los hashes calculados previamente
- Inserta las filas limpias en `clean_data.properties`
- Actualiza el estado del lote en `raw_data.raw_batches` a `processed`

**`decide_training`** *(BranchPythonOperator)*  
Evalúa los siguientes criterios para decidir si entrenar:

| Criterio | Condición |
|---------|-----------|
| Primera ejecución | No existe ningún registro con `promoted=true` en `training_audit` |
| Drift detectado | Alguna variable superó el umbral KS (p < 0.05) |
| Nuevas categorías significativas | Alguna categoría nueva con frecuencia ≥ 5% |
| Crecimiento de volumen | El lote actual tiene ≥ 10% más registros que el promedio anterior |

Si ninguna condición se cumple **o** el lote tiene menos de 100 registros → `skip_training`.  
Si al menos una se cumple → `train_candidate_model`.

**`skip_training`**  
Registra en `raw_data.training_audit` con `decision='skip'` y la razón textual. No realiza ninguna acción de ML.

**`train_candidate_model`**  
Lanza el pipeline de entrenamiento vía Docker:
```
docker run --rm --network host \
  -e MLFLOW_TRACKING_URI=http://localhost:15000 \
  -e DATABASE_URI=postgresql+psycopg2://... \
  -e MLFLOW_S3_ENDPOINT_URL=http://localhost:19000 \
  danielvelasco01/mlops-training:latest \
  train \
  --batch-id <batch_id> \
  --training-reason "<razón>" \
  --n-estimators 3 \
  --max-depth 3 \
  --min-samples-leaf 50
```
Captura el JSON de salida (run_id, model_version, metrics) y lo guarda en XCom.

**`evaluate_candidate_model`**  
Lanza el contenedor de evaluación:
```
docker run ... mlops-training evaluate --candidate-version <version>
```
Carga el modelo candidato y el modelo productivo actual desde MLflow, los evalúa sobre el mismo holdout (15% de `clean_data.properties`), y retorna un JSON con las métricas comparadas de ambos más el flag `no_production_model`.

**`decide_promotion`** *(BranchPythonOperator)*  
Lee el JSON de evaluación y aplica la regla de negocio:
- **Primer modelo** (`no_production_model=true`): siempre promover
- **Modelo existente**: promover solo si:
  - MAE candidato ≤ MAE productivo × (1 − 3%)
  - RMSE candidato ≤ RMSE productivo × (1 + 1%)

Si pasa → `promote_model`. Si falla → `reject_model`.

**`promote_model`**  
Lanza `mlops-training promote`, que asigna el alias `production` al modelo candidato en MLflow Model Registry. Registra en `training_audit` con `promoted=true` y todas las métricas. FastAPI detectará el nuevo alias en el siguiente ciclo de polling (≤ 30 segundos).

**`reject_model`**  
Registra en `training_audit` con `promoted=false` y la razón del rechazo. El modelo productivo anterior sigue activo.

**`notify_or_log_result`**  
Registra el resultado final del pipeline (éxito/fallo, razón, métricas) para trazabilidad completa.

---

## 7. Pipeline de ML — Training, Evaluación y Promoción

El pipeline de ML está encapsulado en la imagen Docker `danielvelasco01/mlops-training:latest`, construida desde `training/`. El entrypoint es `entrypoint.sh`, que acepta tres subcomandos: `train`, `evaluate`, `promote`.

### Preprocesamiento (`training/preprocess.py`)

**Features numéricas:** `bed`, `bath`, `acre_lot`, `zip_code`, `house_size`, `days_since_prev_sold`  
**Features categóricas:** `brokered_by`, `status`, `street`, `city`, `state`

Transformaciones aplicadas (ColumnTransformer):
- **Numéricos:** `SimpleImputer(strategy='median')` → `StandardScaler()`
- **Categóricos:** `SimpleImputer(strategy='most_frequent')` → `OneHotEncoder(handle_unknown='ignore', min_frequency=10)`

La opción `handle_unknown='ignore'` es clave: permite que el modelo reciba en inferencia categorías que no vio durante el entrenamiento (ej: una ciudad nueva) sin lanzar error — simplemente las trata como ceros en el vector one-hot.

`min_frequency=10` evita la explosión de dimensionalidad por valores raros (ciudades con pocas apariciones se agrupan implícitamente).

La columna `prev_sold_date` se transforma a `days_since_prev_sold` (días desde la venta anterior hasta la fecha de ejecución). Los nulos se imputan con la mediana.

### Entrenamiento (`training/train.py`)

1. Carga datos de `clean_data.properties` filtrando por `batch_id`
2. Aplica `clean_dataframe()`: elimina filas con price ≤ 0, castea tipos, genera `days_since_prev_sold`
3. Split 85% train / 15% holdout (random_state=42, estratificado por rangos de precio)
4. Construye el pipeline: `ColumnTransformer` + `RandomForestRegressor`
5. Parámetros configurables: `n_estimators`, `max_depth`, `min_samples_leaf`
6. Calcula métricas sobre el holdout: **MAE, RMSE, MAPE, R²**
7. Registra en MLflow:
   - Parámetros del modelo
   - Métricas de evaluación
   - Artefacto del modelo (almacenado en MinIO vía S3)
   - Tags: `batch_id`, `training_reason`, `commit_sha`
8. Registra el modelo en MLflow Model Registry bajo el nombre `house-price-model`
9. Imprime en stdout un JSON: `{ "run_id": "...", "model_version": "...", "metrics": {...} }`

### Evaluación (`training/evaluate.py`)

1. Carga el modelo candidato (por versión) y el modelo productivo (por alias `production`) desde MLflow
2. Usa el **mismo holdout** (15% de clean_data, misma semilla) para ambos
3. Calcula MAE, RMSE, MAPE, R² para cada uno
4. Computa `delta_pct` por métrica: `(candidato - productivo) / productivo × 100`
5. Imprime JSON con ambas métricas y el flag `no_production_model`

### Promoción (`training/promote.py`)

1. Lee el JSON de evaluación (desde archivo `--evaluation-json` o stdin)
2. Aplica las reglas de promoción configurables (`--mae-improvement-pct`, `--rmse-tolerance-pct`)
3. Si pasa:
   - `mlflow_client.set_registered_model_alias(model_name, "production", version)`
   - Agrega tag `promotion_decision=promoted`
4. Si no pasa:
   - Agrega tag `promotion_decision=rejected` con razón
5. Imprime JSON: `{ "promoted": true/false, "reason": "...", "metrics": {...} }`

### Experimento y registro en MLflow

| Parámetro | Valor |
|----------|-------|
| Experiment name | `house-price` |
| Model name | `house-price-model` |
| Alias de producción | `production` |
| Artifact store | MinIO (`s3://mlflow-artifacts/`) |
| Backend store | PostgreSQL (`mlflow` database) |

---

## 8. API de inferencia — FastAPI

### Endpoints

**`GET /health`**
```json
{
  "status": "ok",
  "model_loaded": true,
  "model_name": "house-price-model",
  "model_version": "3",
  "model_alias": "production"
}
```

**`POST /predict`**

Request:
```json
{
  "brokered_by": "Coldwell Banker",
  "status": "for_sale",
  "bed": 3,
  "bath": 2,
  "acre_lot": 0.12,
  "street": "Main St",
  "city": "Austin",
  "state": "Texas",
  "zip_code": 78701,
  "house_size": 1850,
  "prev_sold_date": "2019-05-15"
}
```

Response:
```json
{
  "prediction": 425000.0,
  "model_name": "house-price-model",
  "model_version": "3",
  "model_alias": "production",
  "inference_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-06-03T15:30:00Z"
}
```

**`POST /reload-model`** *(requiere header `X-Reload-Token`)*  
Fuerza una recarga inmediata del modelo desde MLflow, sin esperar el ciclo de polling.

**`GET /metrics`**  
Endpoint de Prometheus. Expone métricas en formato text/plain para ser scrapeado.

### Carga thread-safe del modelo (`fastapi/model_loader.py`)

La carga y el swap del modelo en producción están protegidos con `threading.RLock()`. El flujo de recarga es:

1. **Background poller** (hilo daemon, intervalo 30s): consulta MLflow para saber a qué versión apunta el alias `production`
2. Si la versión cambió respecto a la cargada actualmente, carga el nuevo modelo en memoria
3. Una vez cargado exitosamente, hace el swap atómico bajo el lock
4. **Fallback:** si la nueva carga falla (MLflow caído, modelo corrupto), conserva el modelo anterior activo — la API nunca queda sin modelo

### Registro de inferencias (`fastapi/inference_log.py`)

Cada llamada exitosa (y cada error) a `/predict` se persiste de forma asíncrona en `raw_data.inference_events`, incluyendo el payload completo (JSONB), la predicción, la latencia en ms y la versión del modelo usada.

### Métricas Prometheus

| Métrica | Tipo | Descripción |
|---------|------|-------------|
| `http_requests_total` | Counter | Conteo por handler, method, status |
| `http_request_duration_seconds` | Histogram | Latencia por percentil |
| `model_version_info` | Gauge | Versión y alias del modelo activo |
| `model_load_total` | Counter | Cargas exitosas/fallidas |
| `inference_log_failures_total` | Counter | Fallos al persistir inferencias |

---

## 9. Interfaz de usuario — Streamlit

Accesible en `http://localhost:8501` (local) o a través del NodePort de Kubernetes.

### Tab 1: Inferencia en tiempo real

Formulario con los 11 campos de entrada de una propiedad. Al enviar, hace `POST /predict` a FastAPI y muestra:
- Precio estimado (destacado visualmente)
- Versión y alias del modelo usado
- Timestamp de la predicción

### Tab 2: Historial de entrenamientos

Lee `raw_data.training_audit` con cache de 30 segundos (`st.cache_data(ttl=30)`).

Muestra:
- **Resumen agregado:** total de lotes procesados, lotes que entrenaron, lotes promovidos, mejor MAE histórico
- **Tabla de runs** con colores por estado:
  - Gris: `skip` (no se entrenó)
  - Amarillo: entrenado pero no promovido
  - Verde: entrenado y promovido a producción
- **Detalle expandible** por lote: métricas de candidato vs. productivo, variables con drift, categorías nuevas, razón de la decisión

---

## 10. Observabilidad — Prometheus y Grafana

### Prometheus

Scrape configurado en `kubernetes/prometheus/configmap.yaml`:
```yaml
scrape_configs:
  - job_name: 'fastapi'
    static_configs:
      - targets: ['fastapi:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

### Grafana

Dashboard predefinido disponible en `grafana_dashboard.json`. Paneles incluidos:
- **Request rate** por endpoint (req/s)
- **Latencia p50 / p95 / p99** de `/predict`
- **Versión activa del modelo** (gauge)
- **Inferencias por minuto** (rate)
- **Errores de inferencia** (log failures)
- **Model load events** (cuándo se cargó un nuevo modelo)

Credenciales por defecto: `admin / admin`

---

## 11. Pruebas de carga — Locust

El archivo `locust/locustfile.py` define un usuario virtual con dos comportamientos:

| Tarea | Peso | Descripción |
|------|------|-------------|
| `predict` | 8 | POST `/predict` con payload de propiedad aleatorio |
| `health` | 2 | GET `/health` |

Accesible en `http://localhost:8089` (local) o NodePort. Permite configurar número de usuarios concurrentes y tasa de spawn desde la UI web.

Resultado de referencia: **2,655 inferencias en 90 segundos con 0 fallos** sobre 2 réplicas de FastAPI.

---

## 12. CI/CD — GitHub Actions y DockerHub

Cada componente tiene su propio workflow en `.github/workflows/`:

| Workflow | Trigger | Imagen publicada |
|---------|---------|-----------------|
| `build-airflow.yml` | push a `main` o `develop` | `danielvelasco01/mlops-airflow:latest` + `:sha-<commit>` |
| `build-fastapi.yml` | push a `main` o `develop` | `danielvelasco01/mlops-fastapi:latest` + `:sha-<commit>` |
| `build-training.yml` | push a `main` o `develop` | `danielvelasco01/mlops-training:latest` + `:sha-<commit>` |
| `build-streamlit.yml` | push a `main` o `develop` | `danielvelasco01/mlops-streamlit:latest` + `:sha-<commit>` |

El tag `:sha-<commit>` permite hacer rollback a cualquier versión anterior simplemente actualizando el tag en los manifests de Kubernetes.

---

## 13. GitOps — Argo CD

`kubernetes/argocd/application.yaml` define una Application de Argo CD que:
- Sincroniza automáticamente el directorio `kubernetes/` del repositorio GitHub con el clúster
- Activa **auto-sync**, **prune** (elimina recursos huérfanos) y **self-heal** (revierte cambios manuales en el clúster)

```yaml
syncPolicy:
  automated:
    prune: true
    selfHeal: true
```

**Flujo GitOps:**
1. Desarrollador actualiza un manifest en `kubernetes/` y hace push a `main`
2. Argo CD detecta el cambio (polling cada 3 min o webhook)
3. Aplica los manifests actualizados al clúster automáticamente
4. Si alguien edita un recurso directamente con `kubectl`, Argo CD lo revierte

---

## 14. Despliegue en Kubernetes

### Prerequisitos

- Docker Desktop con Kubernetes habilitado (o clúster equivalente)
- `kubectl` configurado y apuntando al clúster correcto
- `git`

### Paso 1 — Clonar el repositorio

```bash
git clone https://github.com/DANIEL-VELASCO/proyecto_final_mlops.git
cd proyecto_final_mlops
```

### Paso 2 — Namespace y secrets

```bash
kubectl apply -f kubernetes/namespace.yaml
kubectl apply -f kubernetes/secrets.yaml
```

### Paso 3 — Base de datos

```bash
kubectl apply -f kubernetes/databases/

# Esperar a que PostgreSQL esté listo
kubectl -n mlops wait pod/postgres-0 --for=condition=ready --timeout=120s

# Aplicar el DDL completo
kubectl -n mlops exec -i postgres-0 -- psql -U mlops -d mlops < scripts/init_db.sql

# Crear las bases de datos para MLflow y Airflow
kubectl -n mlops exec -i postgres-0 -- psql -U mlops -c "CREATE DATABASE mlflow; CREATE DATABASE airflow;"
```

### Paso 4 — MinIO

```bash
kubectl apply -f kubernetes/minio/

# Esperar a que MinIO esté listo
kubectl -n mlops wait pod/minio-0 --for=condition=ready --timeout=120s

# Crear el bucket para artefactos de MLflow
kubectl -n mlops port-forward svc/minio-service 19010:9000 &
python -c "
import boto3
s3 = boto3.client('s3',
    endpoint_url='http://localhost:19010',
    aws_access_key_id='minioadmin',
    aws_secret_access_key='minioadmin'
)
s3.create_bucket(Bucket='mlflow-artifacts')
print('Bucket creado.')
"
```

### Paso 5 — MLflow

```bash
kubectl apply -f kubernetes/mlflow/
kubectl -n mlops rollout status deployment/mlflow --timeout=120s
```

### Paso 6 — Data API externa

```bash
kubectl apply -f kubernetes/data-api/
```

### Paso 7 — Airflow

```bash
kubectl apply -f kubernetes/airflow/
kubectl -n mlops rollout status deployment/airflow --timeout=300s
```

### Paso 8 — FastAPI

```bash
kubectl apply -f kubernetes/fastapi/
kubectl -n mlops rollout status deployment/fastapi --timeout=120s
```

### Paso 9 — Streamlit, Prometheus, Grafana, Locust

```bash
kubectl apply -f kubernetes/streamlit/
kubectl apply -f kubernetes/prometheus/
kubectl apply -f kubernetes/grafana/
kubectl apply -f kubernetes/locust/
```

### Paso 10 — Argo CD (opcional)

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.11.4/manifests/install.yaml
kubectl -n argocd rollout status deployment/argocd-server --timeout=300s
kubectl apply -f kubernetes/argocd/application.yaml
```

### Paso 11 — Verificar el sistema

```bash
# Verificar pods
kubectl -n mlops get pods

# Port-forwards para acceso local
kubectl -n mlops port-forward svc/airflow 18080:8080 &
kubectl -n mlops port-forward svc/mlflow-service 15000:5000 &
kubectl -n mlops port-forward svc/fastapi 8000:8000 &
kubectl -n mlops port-forward svc/streamlit-service 8501:8501 &
kubectl -n mlops port-forward svc/grafana-service 13000:3000 &
kubectl -n mlops port-forward svc/locust-service 8089:8089 &

# Verificar FastAPI
curl http://localhost:8000/health
```

---

## 15. Entorno local con Docker Compose

Para desarrollo y pruebas sin Kubernetes:

```bash
cd PROYECTO_FINAL_2

# Levantar todos los servicios
docker compose up -d

# Verificar estado
docker compose ps

# Ver logs de un servicio específico
docker compose logs -f airflow
```

### Inicialización de la base de datos (primera vez)

```bash
# Crear DBs adicionales
docker exec mlops-postgres psql -U mlops -c "CREATE DATABASE mlflow; CREATE DATABASE airflow;"

# Aplicar DDL
Get-Content scripts/init_db.sql | docker exec -i mlops-postgres psql -U mlops -d mlops
```

### Fix de conexiones zombie tras reinicio de Docker Desktop

Después de reiniciar Docker Desktop, Airflow puede quedar bloqueado por conexiones zombie en PostgreSQL:

```bash
docker exec mlops-postgres psql -U mlops -d airflow -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity \
   WHERE datname = 'airflow' AND pid <> pg_backend_pid();"

docker compose restart airflow
```

### Reiniciar el contador de la Data API

Antes de disparar el DAG manualmente (si hubo runs fallidos que ya consumieron batches):

```powershell
Invoke-WebRequest -Uri "http://localhost:18001/restart_data_generation?group_number=1"
```

### Disparar el DAG manualmente

```bash
docker exec mlops-airflow airflow dags trigger real_estate_mlops_pipeline
```

### Cancelar runs en cola (si hay acumulación)

```bash
docker exec mlops-postgres psql -U mlops -d airflow -c \
  "UPDATE dag_run SET state = 'failed' \
   WHERE dag_id = 'real_estate_mlops_pipeline' AND state = 'queued';"
```

---

## 16. Puertos y credenciales de acceso

### Docker Compose (entorno local)

| Servicio | URL | Credenciales |
|---------|-----|-------------|
| Airflow | http://localhost:18080 | admin / admin123 |
| MLflow | http://localhost:15000 | sin autenticación |
| FastAPI (Swagger) | http://localhost:8000/docs | sin autenticación |
| Streamlit | http://localhost:8501 | sin autenticación |
| Grafana | http://localhost:13000 | admin / admin |
| Prometheus | http://localhost:19090 | sin autenticación |
| MinIO (UI) | http://localhost:19001 | minioadmin / minioadmin |
| PostgreSQL | localhost:15432 | mlops / mlops |
| Data API | http://localhost:18001 | sin autenticación |

### Kubernetes (NodePorts)

Los manifests en `kubernetes/*/nodeport.yaml` exponen los mismos servicios en los puertos equivalentes del nodo.

---

## 17. Flujo end-to-end completo

Partiendo de un sistema recién desplegado:

```
1. Data API devuelve batch #1 (~21 MB, ~50,000 registros)
   └── stored en raw_data.raw_batches
   └── hashes en raw_data.row_hashes

2. validate_schema → OK (12 columnas presentes)
   validate_data_quality → OK (nulls < 50%, precios válidos)

3. detect_new_categories → registra ~3,000 ciudades en category_catalog
   detect_data_drift → primer lote, sin lote anterior para comparar → no drift

4. preprocess_data → ~48,000 filas limpias en clean_data.properties

5. decide_training → "Primera ejecución, no existe modelo productivo" → TRAIN

6. train_candidate_model:
   docker run mlops-training train --batch-id batch_1_0001 ...
   → carga 48,000 registros de clean_data.properties
   → entrena RandomForest(n_estimators=3, max_depth=3, min_samples_leaf=50)
   → métricas sobre holdout: MAE=45,000, RMSE=75,000, R²=0.61
   → guarda modelo en MinIO, registra run en MLflow (house-price v1)

7. evaluate_candidate_model:
   → no_production_model=true (primer modelo)
   → métricas candidato: MAE=45,000, RMSE=75,000

8. decide_promotion → primer modelo → PROMOTE siempre

9. promote_model:
   → asigna alias "production" a house-price-model v1 en MLflow Registry
   → registra en training_audit: promoted=true, mae_candidate=45000

10. FastAPI (polling cada 30s):
    → detecta que alias "production" ahora apunta a v1
    → carga el modelo en memoria (thread-safe)
    → model_version_info gauge actualizado en Prometheus

11. /health → { "model_loaded": true, "model_version": "1", "model_alias": "production" }

12. POST /predict:
    → recibe payload de propiedad
    → preprocesa con el mismo ColumnTransformer
    → retorna precio estimado
    → persiste en raw_data.inference_events

13. Streamlit:
    → Tab Inferencia: disponible (sin error 503)
    → Tab Historial: muestra 1 lote, promoted=true, MAE=45,000

14. Grafana:
    → panel model_version_info = 1
    → panel request rate = req/s del load test de Locust
    → panel p95 latency de /predict
```

---

## 18. Decisiones técnicas relevantes

**`handle_unknown='ignore'` en OneHotEncoder**  
El dataset incluye miles de ciudades y brokers únicos. Inevitablemente, la inferencia recibirá valores que el modelo nunca vio durante el entrenamiento. En lugar de lanzar un error, el encoder simplemente produce un vector de ceros para esa categoría, permitiendo que el modelo haga la mejor predicción posible con los demás features.

**`min_frequency=10` en OneHotEncoder**  
Sin este parámetro, cada ciudad rara genera su propia columna one-hot, inflando la dimensionalidad a miles de columnas. Con `min_frequency=10`, las ciudades que aparecen menos de 10 veces en el set de entrenamiento se agrupan en una categoría "infrequent", manteniendo el modelo manejable.

**`mlflow.sklearn` en lugar de `mlflow.pyfunc`**  
MLflow `pyfunc` aplica schema enforcement estricto y tiene incompatibilidades con `StringDtype` de pandas (introduce comportamiento diferente entre `str` y `pd.StringDtype`). Usar `mlflow.sklearn` serializa directamente el pipeline scikit-learn y lo carga sin modificar los tipos, evitando errores silenciosos en inferencia.

**Alias `production` en lugar de Stage**  
MLflow 2.x deprecó el sistema de Stages (`Staging`, `Production`, `Archived`). El mecanismo recomendado son los aliases, que permiten múltiples aliases por modelo y no tienen semántica fija. Usar `production` como alias garantiza compatibilidad con versiones futuras de MLflow.

**`threading.RLock` con snapshot inmutable**  
El modelo cargado en FastAPI es referenciado por múltiples hilos (workers de Uvicorn) simultáneamente. El lock garantiza que ningún hilo lea el modelo mientras está siendo reemplazado. El patrón "snapshot inmutable" significa que se carga el nuevo modelo en una variable temporal y solo se hace el swap de la referencia global bajo lock, minimizando el tiempo de contención.

**Fallback al modelo anterior**  
Si durante un swap el nuevo modelo falla al cargar (MLflow caído, artefacto corrupto en MinIO, error de deserialización), el sistema captura la excepción, loguea el error y conserva el modelo anterior activo. La API nunca queda en estado `model_loaded=false` por un fallo transitorio de infraestructura.

**`max_active_runs=1` en el DAG**  
Si el scheduler lanzara dos runs simultáneos del mismo DAG, ambos podrían leer el mismo "lote siguiente" de la Data API (que es stateful) o escribir en la misma tabla con el mismo `batch_id`. El límite de 1 run activo garantiza que el pipeline sea siempre secuencial.

**Regla de promoción configurable**  
Los umbrales de promoción (`--mae-improvement-pct=3`, `--rmse-tolerance-pct=1`) son parámetros de `promote.py`, no constantes hardcodeadas. Esto permite ajustar el criterio de calidad mínima requerida para reemplazar el modelo en producción sin modificar código — solo cambiando el argumento en el DAG.

**Pipeline de training como contenedor Docker separado**  
El entrenamiento no corre dentro del contenedor de Airflow. En cambio, el DAG lanza un `docker run` que ejecuta el training en su propio contenedor con sus propias dependencias (scikit-learn, MLflow client, boto3). Esto garantiza aislamiento de dependencias, facilita el debugging y permite escalar el training independientemente del scheduler.
