# Mensaje para P3 (DevOps / MLOps)

Copia y pega esto en el chat del equipo.

---

Hola @P3 👋

Mi PR ya está mergeado en `main` (PR #1, commit `b4185bf`). Listo todo
de **P2**: pipeline de training, FastAPI con `/health /predict /metrics
/reload-model` y métricas Prometheus alineadas EXACTAMENTE a tu
dashboard de Grafana (`http_requests_total`, `http_request_duration_seconds_bucket`,
`model_version_info`).

Revisé el estado de tu clúster K8s local y encontré 4 cosas que toca
ajustar para que el sistema corra. La 1 y la 2 son las urgentes:

### 🟠 1. La imagen en el `Deployment fastapi` no es la mía

El manifiesto dice:
```yaml
image: danielvelasco01/mlops-fastapi:latest
```

Pero los pods que están corriendo tienen:
```
max181818/mlops-api:latest    # repo viejo, no es el mío
```

GH Actions publica mi imagen como `${DOCKERHUB_USERNAME}/mlops-fastapi:sha-XXXX`.
Si `DOCKERHUB_USERNAME=max181818`, entonces la imagen quedará en
`max181818/mlops-fastapi:sha-b4185bf` (no `mlops-api`). Hay que:

```bash
# 1) Verificar que el workflow build-fastapi.yml terminó OK en main:
#    https://github.com/DANIEL-VELASCO/proyecto_final_mlops/actions

# 2) Cambiar el image: del Deployment a la nueva imagen:
kubectl -n mlops set image deployment/fastapi-deployment \
    fastapi=max181818/mlops-fastapi:sha-b4185bf
# (o editar kubernetes/fastapi/deployment.yaml y dejarlo apuntando a
#  max181818/mlops-fastapi:sha-b4185bf — yo ya lo dejé así en
#  feature/p2-status-and-fixes)
```

### 🟠 2. Postgres en K8s NO inicializó el rol `mlops`

```bash
$ kubectl exec -n mlops postgres-0 -- psql -U mlops -d mlops
psql: error: FATAL:  role "mlops" does not exist
```

El ConfigMap `postgres-init` corre `CREATE DATABASE airflow; CREATE
DATABASE mlflow; CREATE DATABASE mlops; ...` pero solo en el primer
boot. Como el StatefulSet tiene un PVC viejo de `postgres:` por defecto,
no se ejecutó. Hay que borrar el PVC y bootstrappear de cero:

```bash
kubectl -n mlops delete statefulset postgres --cascade=foreground
kubectl -n mlops delete pvc postgres-pvc
kubectl -n mlops apply -f kubernetes/databases/
# espera hasta que postgres-0 esté Running y healthy:
kubectl -n mlops wait pod/postgres-0 --for=condition=ready --timeout=120s
# verifica:
kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c "\dn"
# debería listar raw_data y clean_data
```

Esto **borra los datos actuales** del postgres del clúster, pero como
no tenemos datos productivos aún, no perdemos nada.

### 🟠 3. Los Secrets apuntan a hostnames que no existen en DNS

Los Services en K8s se llaman:
- `mlflow-service` (no `mlflow`)
- `postgres-service` (no `postgres`)
- `minio-service` (no `minio`)

Pero `kubernetes/secrets.yaml` apunta así:
```yaml
MLFLOW_TRACKING_URI: http://mlflow:5000              # ❌ debería ser mlflow-service
BACKEND_STORE_URI: postgresql+psycopg2://...@postgres:5432/mlflow  # ❌
DATABASE_URI: postgresql+psycopg2://...@postgres:5432/mlops        # ❌
MLFLOW_S3_ENDPOINT_URL: http://minio:9000            # ❌
```

Hay dos opciones:
- **A) (recomendada)**: añade alias-services sin el sufijo `-service`
  para mantener compatibilidad. Ejemplo:

  ```yaml
  # kubernetes/databases/service-alias.yaml
  apiVersion: v1
  kind: Service
  metadata: { name: postgres, namespace: mlops }
  spec:
    selector: { app: postgres }
    ports: [{ port: 5432, targetPort: 5432 }]
  ```

- **B)**: actualiza los Secrets para usar `*-service`. Ya lo dejé
  preparado en `feature/p2-status-and-fixes` por si quieres mergearlo
  directo.

### 🟠 4. Falta sincronizar `develop` con `main`

El PR mío se mergeó a `main` directamente. `develop` quedó atrás.
Cuando P1 ramifique de `develop`, no va a ver mis archivos (training/,
fastapi/, scripts/smoke/). Sugiero:

```bash
git checkout develop
git pull
git merge main
git push origin develop
```

### 🔵 Variables de entorno que mi FastAPI necesita

Estas faltan en `fastapi-secret` (mi código usa defaults si no están,
pero conviene tenerlas explícitas):

```yaml
MLFLOW_MODEL_NAME: house-price-model
MLFLOW_PRODUCTION_ALIAS: production
MODEL_POLL_INTERVAL_SEC: "30"
RELOAD_TOKEN: "<UUID generado>"  # si vacío, /reload-model rechaza siempre
INFERENCE_EVENTS_TABLE: raw_data.inference_events
MLFLOW_S3_ENDPOINT_URL: http://minio-service:9000
AWS_ACCESS_KEY_ID: minioadmin
AWS_SECRET_ACCESS_KEY: minioadmin123
```

(Las últimas 3 son críticas: FastAPI necesita poder bajar el modelo
desde MinIO al cargar desde MLflow.)

### 🔵 Contrato HTTP — Streamlit y Locust ya funcionan con mi API

- `POST /predict` recibe el payload que tu `streamlit/app.py` ya envía
  (verifiqué línea por línea contra `schemas.py`).
- Responde `{ price, model_version, model_alias, inference_id, timestamp }`.
- `/metrics` expone EXACTAMENTE las series que tu Grafana ya consulta
  (no necesitas cambiar el dashboard).
- `/reload-model` requiere header `X-Reload-Token: <token del Secret>`.

Cuando arregles los 4 puntos de arriba (especialmente 1 y 2), el sistema
debería responder. Yo voy a hacer port-forward y validar end-to-end
cuando me confirmes que ya está.

— P2
