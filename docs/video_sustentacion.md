# Guion — Video de sustentación (10 min máx — YouTube)

> **Versión 2 — adaptada al estado real del sistema al 2026-06-02.**
> Estrategia: mostrar la "foto" del sistema funcional, sin disparar runs de
> DAG en vivo durante la grabación (el training pesa ~2 GB y satura la VM
> de WSL2 con todo el clúster arriba). El DAG se muestra como **estructura**
> en el tab Graph; el resultado del entrenamiento ya está en MLflow y en
> las tablas.

Distribución: **3 min P1 + 3 min P2 + 3 min P3 + 30s intro + 30s cierre conjunto**.

Cada uno comparte pantalla en su parte. OBS o Zoom Local Recording. Pueden grabar por separado y editar, o todos juntos en una llamada.

---

## Estado del sistema al momento de grabar (verificado)

- ✅ 11 pods Running en Kubernetes (`mlops` namespace)
- ✅ Argo CD `Synced + Healthy` en `argocd` namespace
- ✅ Modelo `house-price-model v1` con alias `production` en MLflow
- ✅ FastAPI sirviendo predicciones (verificado: NY 3bd/2ba → ~$234k, LA 4bd/3ba → ~$254k)
- ✅ 1 fila en `raw_data.training_audit` (batch_1_0000 — primera línea base, promovida)
- ✅ 2 lotes en `raw_data.raw_batches` (73K + 94K registros bajados de la API real)
- ✅ **662 inferencias** acumuladas en `raw_data.inference_events`
- ✅ Grafana dashboard con los 5 paneles activos
- ✅ Imágenes publicadas en DockerHub: `max181818/mlops-fastapi:latest`, `max181818/mlops-training:latest`
- ✅ GitHub Actions: 3 workflows verdes (`build-fastapi`, `build-streamlit`, `build-training`)

---

## URLs y credenciales (NodePorts directos — no necesitan port-forward)

| Servicio | URL | Login |
|---|---|---|
| Airflow | http://localhost:30808 | `admin` / `admin` |
| MLflow | http://localhost:30500 | — |
| FastAPI Swagger | http://localhost:30800/docs | — |
| Streamlit | http://localhost:30501 | — |
| Grafana | http://localhost:30300 | `admin` / `admin123` |
| Locust | http://localhost:30089 | — |
| MinIO Console | http://localhost:30901 | `minio_admin` / `minio_secret123` |
| Prometheus | http://localhost:30909 | — |
| **Argo CD** (port-forward necesario) | https://localhost:8443 | `admin` / `18-MTOevx64mCKU3` |

> Para Argo CD: `kubectl -n argocd port-forward svc/argocd-server 8443:443` antes de grabar.

---

## 0:00 – 0:30 — Introducción (todos)

> "Hola, somos el equipo del proyecto final de MLOps 2026-1: **David Garzón (P1), Juan Pérez (P2), Daniel Velasco (P3)**. Construimos un sistema MLOps de producción para estimar el precio de propiedades inmobiliarias.
>
> El sistema integra **recolección incremental de datos** con Airflow, **registro de experimentos** en MLflow, **inferencia** en FastAPI, **despliegue declarativo** en Kubernetes con Argo CD, y **observabilidad** con Prometheus, Grafana y Locust.
>
> Repartimos el video en 3 partes: datos + DAG, ML + servicio de inferencia, e infraestructura."

**Mostrar en pantalla**: README.md del repo + diagrama de arquitectura del PDF.

---

## 0:30 – 3:30 — Persona 1 (David Garzón) — Datos y DAG

### 0:30 – 1:00 — Visión general

> "Yo me encargo del pipeline de datos: consumir la API externa, validar los lotes, decidir cuándo entrenar y dejar todo trazable."

**Mostrar**: estructura de `airflow/dags/` en el repo (api_client.py, main_pipeline.py, preprocessing.py) + `scripts/init_db.sql`.

### 1:00 – 1:45 — Separación RAW / CLEAN (RF1 + RF2)

> "Cada lote bajado de la API se persiste íntegro como JSONB en `raw_data.raw_batches`. El preprocesamiento limpia y normaliza, y los datos listos para entrenar van a `clean_data.properties`. La trazabilidad es por `batch_id` — puedo reconstruir exactamente qué datos generaron qué modelo."

**Mostrar en una terminal abierta**, copy-paste estos comandos uno por uno:

```bash
kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c "\dn"
# Debe mostrar: clean_data, raw_data, public

kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c \
  "SELECT batch_id, n_records, status, fetch_timestamp FROM raw_data.raw_batches;"
# Debe mostrar 2 lotes: batch_1_0000 (73K) y batch_1_0001 (94K)
```

### 1:45 – 2:30 — DAG y bifurcaciones (RF3 + RF4)

> "El DAG `real_estate_mlops_pipeline` tiene 17 tareas con 2 bifurcaciones explícitas:
>
> - **decide_training** → entrenar o saltar entrenamiento. Las reglas: si es la primera ejecución, si hay drift detectado por Kolmogorov-Smirnov, si aparecieron nuevas categorías con frecuencia ≥5%, o si el volumen creció ≥10%.
>
> - **decide_promotion** → promover o rechazar. Solo promuevo si el MAE baja al menos 3% **y** el RMSE no empeora más de 1%."

**Mostrar**: Airflow UI → DAGs → `real_estate_mlops_pipeline` → tab **Graph** (la estructura del grafo, sin ejecutar). Apuntar a los 2 nodos de decisión con el cursor.

### 2:30 – 3:30 — Auditoría y resultado del entrenamiento

> "Cada decisión queda en `raw_data.training_audit` para que Streamlit muestre el historial. En este momento tenemos una fila: el primer lote entrenó y se promovió porque no existía modelo productivo previo — es la línea base."

**Mostrar**, en la terminal:

```bash
kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c \
  "SELECT batch_id, decision, LEFT(reason,60), promoted, model_version, status FROM raw_data.training_audit;"
# Debe mostrar batch_1_0000 | train | "Primera ejecucion..." | t | 1 | completed
```

---

## 3:30 – 6:30 — Persona 2 (Juan Pérez) — Entrenamiento, MLflow y FastAPI

### 3:30 – 4:00 — Visión general

> "Yo me encargo del Machine Learning: el pipeline de entrenamiento como imagen Docker reutilizable, el registro en MLflow, y el servicio de inferencia con FastAPI que carga el modelo productivo sin redespliegue."

**Mostrar**: estructura de `training/` (Dockerfile, entrypoint.sh, train.py, evaluate.py, promote.py) y `fastapi/` (main.py, model_loader.py, inference_log.py).

### 4:00 – 4:45 — MLflow + promoción (RF5 + RF6)

> "Entreno un `RandomForestRegressor` con `ColumnTransformer` que usa `OneHotEncoder(handle_unknown='ignore')`. Esto es clave: si llega una ciudad nueva, el pipeline **no se rompe** — exactamente lo que pide el RF3 del PDF.
>
> Registro en MLflow: parámetros, métricas MAE/RMSE/MAPE/R² para train/val/test, artefactos como gráfico de residuos, y el modelo como sklearn Pipeline. La promoción es por **alias** — `production` apunta a la versión actual del modelo, así no quemo rutas locales en FastAPI."

**Mostrar**: MLflow UI (http://localhost:30500) → Experiments → `house-price` → run `8c5459b0...` → tab Parameters + Metrics + Artifacts. Luego: Models → `house-price-model` → v1 → alias `production`.

### 4:45 – 5:45 — FastAPI con recarga sin redespliegue (RF7 + RF8)

> "FastAPI carga el modelo desde MLflow por alias. Cada 30 segundos un poller en background consulta si cambió la versión productiva — si cambia, la recarga con un lock thread-safe; si la nueva carga falla, mantiene el modelo previo como fallback.
>
> También expone `/reload-model` protegido por un token X-Reload-Token para forzar recarga manual.
>
> Cada inferencia se persiste en `raw_data.inference_events` con `request_id` UUID, payload JSONB, predicción, versión del modelo y latencia."

**Mostrar**:

1. Swagger en http://localhost:30800/docs
2. Expandir `POST /predict` → Try it out → pegar:
   ```json
   {"brokered_by":"agency_42","status":"for_sale","bed":3,"bath":2,"acre_lot":0.25,"street":"street_100","city":"New York","state":"NY","zip_code":10001,"house_size":1800,"prev_sold_date":null}
   ```
3. Ejecutar → debe devolver `price ≈ 234000`, `model_version: "1"`, `model_alias: "production"`, `inference_id` UUID
4. En la terminal, mostrar que se persistió:
   ```bash
   kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c \
     "SELECT request_id, model_version, prediction::INT, latency_ms FROM raw_data.inference_events ORDER BY occurred_at DESC LIMIT 3;"
   ```

### 5:45 – 6:30 — Métricas Prometheus (RF10)

> "Para observabilidad expongo `/metrics` con las series que el dashboard de Grafana ya consulta:
> - `http_requests_total{handler, method, status}`
> - `http_request_duration_seconds_bucket{le}`
> - `model_version_info{version, alias, model_name}` — gauge custom que dice qué modelo está cargado en cada momento."

**Mostrar**:

```bash
curl -s http://localhost:30800/metrics | grep -E "model_version_info|http_requests_total|http_request_duration_seconds_bucket" | head -20
```

---

## 6:30 – 9:30 — Persona 3 (Daniel Velasco) — K8s, GitOps, UI y Observabilidad

### 6:30 – 7:00 — Visión general

> "Yo me encargo de la infraestructura, CI/CD, observabilidad e interfaz de usuario. Cada componente corre en Kubernetes desde manifiestos versionados en `kubernetes/`, y Argo CD sincroniza el repo con el clúster automáticamente."

**Mostrar**: árbol de `kubernetes/` en el repo + estado del clúster:

```bash
kubectl -n mlops get pods
# Debe mostrar 11 pods Running

kubectl -n mlops get svc | grep nodeport
# Debe mostrar los NodePorts: 30808, 30500, 30800, 30501, 30300, 30089, 30900, 30909
```

### 7:00 – 7:45 — GitHub Actions + Argo CD (CI/CD + GitOps)

> "Tres workflows construyen y publican imágenes en DockerHub al hacer push a `main`: `build-fastapi`, `build-streamlit` y `build-training`. Etiquetadas por commit SHA para reproducibilidad.
>
> Argo CD vive en su propio namespace. La Application `mlops-proyecto-final` monitorea el repo: cualquier cambio en `kubernetes/` se aplica al clúster con `prune: true` y `selfHeal: true`. Esto es GitOps puro — no hay `kubectl apply` manual."

**Mostrar**:

1. GitHub → tab Actions → workflows verdes
2. DockerHub → `max181818/mlops-fastapi` y `max181818/mlops-training` con tags por SHA
3. Argo CD UI en https://localhost:8443 (admin/`18-MTOevx64mCKU3`) → Application `mlops-proyecto-final` → **Synced + Healthy** + lista de recursos sincronizados

### 7:45 – 8:30 — Streamlit (RF9)

> "Streamlit tiene 2 secciones:
> - **Inferencia**: formulario que consume `POST /predict` y muestra precio + versión del modelo
> - **Historial**: tabla leída directamente de `raw_data.training_audit` con cada lote procesado, su decisión y razón
>
> Acá vemos el resultado real del primer entrenamiento."

**Mostrar**: http://localhost:30501 → llenar el formulario con datos de una propiedad → ver predicción + `model_version: 1`. Luego ir a tab Historial → ver la fila de batch_1_0000.

### 8:30 – 9:30 — Locust + Grafana

> "Para demostrar observabilidad bajo carga, lanzo Locust con **50 usuarios concurrentes** durante 60 segundos contra `/predict`. Ya tenemos **662 inferencias** acumuladas de pruebas anteriores."

**Mostrar**:

1. http://localhost:30089 → Number of users: **50**, Spawn rate: **5**, Host: `http://fastapi:8000`, Run time: **60s** → Start swarming
2. Mientras corre, abrir http://localhost:30300 (admin/admin123) → dashboard `MLOps FastAPI Dashboard` → ver los 5 paneles en vivo:
   - Total de Peticiones
   - Tasa de Peticiones req/s
   - Latencia p50/p95
   - Tasa de Errores 5xx
   - Versión del Modelo Productivo
3. En la terminal, demostrar las inferencias persistidas:
   ```bash
   kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c \
     "SELECT model_version, COUNT(*) AS total, ROUND(AVG(latency_ms)) AS avg_ms FROM raw_data.inference_events GROUP BY model_version;"
   # Debe mostrar v1 con cientos de inferencias
   ```

---

## 9:30 – 10:00 — Cierre conjunto

> **P3 (Daniel)**: "Recapitulando: tenemos un sistema MLOps **end-to-end** desplegado en Kubernetes con GitOps, donde un evento de datos entra por Airflow, pasa por validaciones de schema, calidad, drift y nuevas categorías, decide si entrenar, y si entrena, compara contra el productivo."
>
> **P2 (Juan)**: "Los modelos quedan versionados en MLflow con artefactos, métricas y trazabilidad completa al lote que los generó. FastAPI los carga sin redespliegue. Las inferencias quedan registradas para futuras iteraciones del modelo."
>
> **P1 (David)**: "El despliegue es **GitOps con Argo CD**, las imágenes vienen de **GitHub Actions** y se publican en **DockerHub**. Todo el sistema es reproducible desde el repo. Gracias por su atención."

**Pantalla final**: README.md con link al repo: `github.com/DANIEL-VELASCO/proyecto_final_mlops`.

---

## ⚠️ Cosas que NO hacer durante la grabación

1. **NO disparar un nuevo DAG run en vivo.** El training task ejecuta `docker run` con la imagen `mlops-training`, lo cual consume ~2 GB de RAM extra y satura la VM de WSL2 con todo el clúster arriba. Resultado: OOMKilled cascading (mlflow, fastapi, grafana). En el video se ve fatal. Mostrar el grafo en tab Graph (estructura) y los resultados ya persistidos en BD/MLflow.

2. **NO recargar Argo CD repetidas veces.** La UI carga lento bajo carga; abrirla una vez y dejarla.

3. **NO abrir muchas pestañas del navegador**. Cada pestaña de Grafana/Airflow consume RAM. Idealmente tener una sola ventana con varias pestañas, cerrar lo demás.

4. **NO ejecutar `docker compose up`**. El sistema corre en K8s, no en compose. Si lo levantan, chocan puertos.

---

## ✅ Checklist técnico ANTES de empezar a grabar

Ejecutar estos comandos y verificar que cada uno responde OK:

```bash
# 1. Todos los pods Running
kubectl -n mlops get pods
# Esperado: 11 pods con 1/1 o 2/2 Running

# 2. Argo CD Synced + Healthy
kubectl -n argocd get application mlops-proyecto-final
# Esperado: Synced  Healthy

# 3. FastAPI sirviendo modelo v1
curl -s http://localhost:30800/health
# Esperado: {"status":"ok","model_loaded":true,"model_version":"1","model_alias":"production"}

# 4. MLflow tiene v1 con alias production
curl -s "http://localhost:30500/api/2.0/mlflow/registered-models/alias?name=house-price-model&alias=production" | head -c 200
# Esperado: JSON con "version": "1"

# 5. Tablas con datos
kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c \
  "SELECT 'raw_batches' AS t, COUNT(*) FROM raw_data.raw_batches UNION ALL SELECT 'training_audit', COUNT(*) FROM raw_data.training_audit UNION ALL SELECT 'inference_events', COUNT(*) FROM raw_data.inference_events;"
# Esperado: raw_batches >=1, training_audit >=1, inference_events >=100

# 6. Streamlit responde
curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:30501/_stcore/health
# Esperado: 200

# 7. Grafana responde
curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:30300/api/health
# Esperado: 200

# 8. Argo CD port-forward activo (abrir en otra terminal y dejar)
kubectl -n argocd port-forward svc/argocd-server 8443:443
```

Si todos están verdes → grabar.

---

## Tips para que se vea profesional

- **Practicar una vez completa antes de grabar** — el video tiene tope de 10 min.
- **Compartir solo la ventana relevante**, no todo el escritorio.
- **Tener las URLs verificadas** en pestañas separadas justo antes de empezar.
- **Voz clara**, audio sin ruido de fondo (revisar micrófono).
- **Si una demo falla** en vivo (timeout, etc), pasen a la siguiente sección — no insistan en debug.
- **El video se sube a YouTube como "No listado"** para que el profesor pueda verlo con el link.
- **Cerrar Discord, Spotify, browsers extras** — Docker Desktop ya está al filo de la RAM.

---

## Apéndice: Queries SQL listas para mostrar

```sql
-- Lotes ingestados (P1, sección 1:00)
SELECT batch_id, n_records, status, fetch_timestamp
FROM raw_data.raw_batches
ORDER BY fetch_timestamp DESC;

-- Auditoría del DAG (P1, sección 2:30)
SELECT batch_id, decision, LEFT(reason,60), promoted, model_version, status
FROM raw_data.training_audit
ORDER BY execution_date DESC;

-- Inferencias persistidas (P2, sección 4:45)
SELECT request_id, model_version, prediction::INT, latency_ms
FROM raw_data.inference_events
ORDER BY occurred_at DESC LIMIT 5;

-- Total de inferencias por modelo (P3, sección 8:30)
SELECT model_version, COUNT(*) AS total, ROUND(AVG(latency_ms)) AS avg_ms
FROM raw_data.inference_events
GROUP BY model_version;

-- Schemas separados RAW vs CLEAN (P1, sección 1:00)
\dn
\dt raw_data.*
\dt clean_data.*
```

---

## Apéndice: Si algo falla durante la grabación

| Problema | Solución rápida |
|---|---|
| Pod en Error / OOMKilled | `kubectl -n mlops delete pod <nombre>` → reaparece en 30s |
| FastAPI devuelve 503 | `kubectl -n mlops delete pod -l app=fastapi` |
| Streamlit muestra "Connection refused" | `kubectl -n mlops delete pod -l app=streamlit` |
| Grafana sin datos | Esperar 15s a que Prometheus haga scrape; refrescar dashboard |
| MLflow UI no carga | `kubectl -n mlops delete pod -l app=mlflow` |
| Argo CD UI sin sesión | `kubectl -n argocd port-forward svc/argocd-server 8443:443` en otra terminal |
| Docker daemon colgado | Restart Docker Desktop (~2 min); todos los pods reaparecen solos |
