# Mensaje para P3 — Cómo levantar todo y dejarlo listo para grabar

> Copiar y mandar tal cual al chat del equipo.

---

Hola Daniel, te paso el paso a paso para que dejes el clúster corriendo antes
de grabar. El sistema ya está **validado end-to-end** en mi máquina contra la
API real del profe, todos los bugs que aparecieron están parchados y
commiteados en `main`. Lo único que necesitas hacer es seguir esto en orden,
no hay que tocar código.

## 0. Requisitos en tu máquina

- Docker Desktop con **Kubernetes habilitado** (Settings → Kubernetes → ☑️ Enable Kubernetes)
- Memoria asignada a Docker: **mínimo 6 GB**, idealmente 8 GB (Settings → Resources → Memory)
- CPUs: 8+ ideal
- `kubectl` y `git`
- Anaconda o Python 3.11 (para generar el CSV sintético si quieres demostrar el smoke)

## 1. Clonar el repo (5 min)

```bash
git clone https://github.com/DANIEL-VELASCO/proyecto_final_mlops.git
cd proyecto_final_mlops
```

## 2. Build de las imágenes locales (10 min)

Tres imágenes que el clúster usa con `imagePullPolicy: Never` mientras el CI
no tenga GitHub Actions configurado en tu fork. Las dos primeras (`mlops-fastapi`
y `mlops-training`) **ya están publicadas en `max181818/...:latest`** así que
puedes pullear desde DockerHub, pero `mlops-airflow:local` sí toca construir.

```bash
# REQUERIDO (no está en DockerHub):
docker build -t mlops-airflow:local ./airflow

# Opcional (ya están en DockerHub como max181818/mlops-{fastapi,training}:latest):
docker build -t mlops-fastapi:local ./fastapi
docker build -t mlops-training:local ./training
```

## 3. Aplicar manifiestos al clúster (5 min)

```bash
kubectl apply -f kubernetes/namespace.yaml
kubectl apply -f kubernetes/secrets.yaml
kubectl apply -f kubernetes/databases/
kubectl -n mlops wait pod/postgres-0 --for=condition=ready --timeout=180s

# Bases + tablas:
kubectl -n mlops exec -i postgres-0 -- psql -U mlops -d postgres < scripts/init_db.sql
# También crear el rol alias mlops_user (la metadata del cluster legacy lo usa):
kubectl -n mlops exec -i postgres-0 -- psql -U mlops -d postgres -c "CREATE USER mlops_user WITH PASSWORD 'mlops_pass' SUPERUSER;"

# Resto de servicios:
kubectl apply -f kubernetes/minio/
kubectl apply -f kubernetes/mlflow/
kubectl apply -f kubernetes/data-api/
kubectl apply -f kubernetes/fastapi/
kubectl apply -f kubernetes/streamlit/
kubectl apply -f kubernetes/prometheus/
kubectl apply -f kubernetes/grafana/
kubectl apply -f kubernetes/airflow/

# Esperar a que todo esté Running:
kubectl -n mlops get pods -w   # Ctrl+C cuando veas todo Running 1/1 o 2/2
```

> **Si algun pod queda en CrashLoopBackOff**, los logs lo dicen:
> `kubectl -n mlops logs <pod>`. Los problemas más comunes que ya parché:
> - Postgres OOM → ya tiene 4 Gi
> - MinIO bucket no existe → lo crea P2 al primer entreno (o créalo manual con `mc`)
> - airflow-secret sin `DATABASE_URI` → ya está en `kubernetes/secrets.yaml`

## 4. Crear el bucket de MinIO (1 vez)

```bash
kubectl -n mlops port-forward svc/minio-service 19010:9000 &
# en otra terminal:
python -c "import boto3; boto3.client('s3', endpoint_url='http://localhost:19010', aws_access_key_id='minio_admin', aws_secret_access_key='minio_secret123').create_bucket(Bucket='mlflow-artifacts')"
# o desde la consola web http://localhost:19011 (minio_admin / minio_secret123)
```

## 5. Instalar Argo CD (5 min)

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.11.4/manifests/install.yaml
kubectl -n argocd rollout status deployment argocd-server --timeout=240s
kubectl apply -f kubernetes/argocd/application.yaml

# Password admin:
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
# UI: kubectl -n argocd port-forward svc/argocd-server 8443:443
# usuario: admin, pass: el output del comando anterior
```

## 6. Despausar el DAG y dispararlo (1 click en UI o 1 comando)

```bash
# Resetear el state de la data-api a batch 0 (importante si ya jugaste con ella):
kubectl -n mlops port-forward svc/data-api 18800:80 &
curl "http://localhost:18800/restart_data_generation?group_number=1"
# Verás {"ok":true}

# Disparar el DAG:
POD=$(kubectl -n mlops get pods -l app=airflow -o jsonpath="{.items[0].metadata.name}")
kubectl -n mlops exec $POD -c airflow-scheduler -- airflow dags unpause real_estate_mlops_pipeline
kubectl -n mlops exec $POD -c airflow-scheduler -- airflow dags trigger real_estate_mlops_pipeline -r "demo-$(date +%H%M%S)"
```

Tarda ~12-15 min en completar (los 73 K registros se descargan + procesan +
training de 50 árboles a profundidad 15 + log a MinIO). Durante el video puedes
mostrar el grafo del DAG en Airflow UI mientras corre.

## 7. Validación rápida (cuando termine el DAG)

```bash
# 1) Modelo v2 promovido en MLflow:
kubectl -n mlops port-forward svc/mlflow-service 5000:5000 &
# Abrir http://localhost:5000 → Models → house-price-model → alias 'production' debe estar en v2

# 2) Fila en training_audit:
kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c \
  "SELECT batch_id, decision, mae_candidate, mae_production, promoted FROM raw_data.training_audit ORDER BY execution_date DESC LIMIT 3;"

# 3) FastAPI sirviendo v2:
kubectl -n mlops port-forward svc/fastapi 8000:8000 &
curl http://localhost:8000/health
# debe decir model_version: 2, alias: production
```

## 8. Port-forwards listos para grabar (cada uno en una terminal)

```bash
kubectl -n mlops port-forward svc/fastapi 8000:8000          # FastAPI /docs
kubectl -n mlops port-forward svc/mlflow-service 5000:5000   # MLflow UI
kubectl -n mlops port-forward svc/grafana-service 3000:3000  # Grafana
kubectl -n mlops port-forward svc/streamlit-service 8501:8501# Streamlit
kubectl -n mlops port-forward svc/airflow 8080:8080          # Airflow
kubectl -n mlops port-forward svc/locust-service 8089:8089   # Locust
kubectl -n argocd port-forward svc/argocd-server 8443:443    # Argo CD
```

### Credenciales para el video

| Servicio | URL | Login |
|---|---|---|
| FastAPI Swagger | http://localhost:8000/docs | — |
| MLflow UI | http://localhost:5000 | — |
| Grafana | http://localhost:3000 | admin / admin123 |
| Streamlit | http://localhost:8501 | — |
| Airflow | http://localhost:8080 | admin / admin (password = mlops2026 si pide) |
| Locust | http://localhost:8089 | — |
| Argo CD | https://localhost:8443 | admin / (paso 5) |
| MinIO console | http://localhost:19011 | minio_admin / minio_secret123 |

## 9. Para que el dashboard de Grafana tenga datos al grabar

Lanza Locust antes de empezar a grabar:
- UI → http://localhost:8089
- Number of users: 80
- Spawn rate: 10
- Host: http://fastapi-service:8000
- Run time: 10 m
- Click "Start swarming"

En ~30 s ya verás latencia, RPS y la versión del modelo en Grafana.

## 10. Queries SQL para mostrar en el video

```sql
-- "Batches que P1 procesó"
SELECT batch_id, n_records, status, fetch_timestamp
FROM raw_data.raw_batches ORDER BY fetch_timestamp DESC;

-- "Auditoría del DAG"
SELECT batch_id, decision, LEFT(reason, 60), mae_candidate::INT, mae_production::INT, model_version, promoted
FROM raw_data.training_audit ORDER BY execution_date DESC;

-- "Inferencias del load test"
SELECT model_version, COUNT(*), AVG(latency_ms)::INT
FROM raw_data.inference_events GROUP BY model_version;
```

## Si algo se rompe

- Logs de un pod: `kubectl -n mlops logs <pod>`
- Reaplicar manifiestos: `kubectl apply -f kubernetes/<componente>/`
- Reset total del DAG: borrar runs viejos:
  ```sql
  DELETE FROM task_instance WHERE dag_id='real_estate_mlops_pipeline';
  DELETE FROM dag_run WHERE dag_id='real_estate_mlops_pipeline';
  ```
- Reset data-api a batch 0: `curl "http://data-api:80/restart_data_generation?group_number=1"`

## Cosas que YA NO tienes que hacer (ya está hecho)

- ✅ Schemas (`raw_data`, `clean_data`) y tablas — están en `scripts/init_db.sql`
- ✅ Configmaps de Airflow, Prometheus, Grafana — todos versionados
- ✅ Secrets de PostgreSQL/MinIO/MLflow/FastAPI/Airflow — en `kubernetes/secrets.yaml`
- ✅ Imágenes Docker — `max181818/mlops-fastapi:latest` y `max181818/mlops-training:latest` en DockerHub
- ✅ Dashboard de Grafana — ConfigMap en `kubernetes/grafana/`
- ✅ Argo CD Application — `kubernetes/argocd/application.yaml`
- ✅ DAG con todos los bug fixes — `airflow/dags/main_pipeline.py` (no toques)

## Cualquier cosa que se rompa, avísame y lo arreglo. Suerte con la grabación 🚀

— P2
