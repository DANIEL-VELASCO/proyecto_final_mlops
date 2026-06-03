# 🎬 Guion del video de sustentación — Versión final (palabra por palabra)

> **10 minutos máximo, YouTube en modo "No listado"**.
> Distribución: 30s intro + 3 min P1 + 3 min P2 + 3 min P3 + 30s cierre.
> Cada uno comparte su pantalla en su parte (OBS o Zoom local recording).

---

## ✅ ANTES de empezar a grabar

Que **uno solo** del equipo ejecute esto y confirme que da OK:

```powershell
# 1. Pods Running (deben ser 11)
kubectl -n mlops get pods

# 2. FastAPI con modelo cargado
curl.exe -s http://localhost:30800/health
# Esperado: {"status":"ok","model_loaded":true,"model_version":"1","model_alias":"production"}

# 3. Datos en tablas
kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c "SELECT 'raw_batches' AS t, COUNT(*) FROM raw_data.raw_batches UNION ALL SELECT 'training_audit', COUNT(*) FROM raw_data.training_audit UNION ALL SELECT 'inference_events', COUNT(*) FROM raw_data.inference_events;"

# 4. Argo CD port-forward (DEJA ESTA TERMINAL CORRIENDO durante todo el video)
kubectl -n argocd port-forward svc/argocd-server 8443:443
```

### 🔐 Credenciales (todos las deben tener a la mano)

| Servicio | URL | Login |
|---|---|---|
| Airflow | http://localhost:30808 | `admin` / `admin` |
| MLflow | http://localhost:30500 | sin auth |
| FastAPI Swagger | http://localhost:30800/docs | sin auth |
| Streamlit | http://localhost:30501 | sin auth |
| Grafana | http://localhost:30300 | `admin` / `admin123` |
| Locust | http://localhost:30089 | sin auth |
| MinIO Console | http://localhost:30901 | `minio_admin` / `minio_secret123` |
| Prometheus | http://localhost:30909 | sin auth |
| Argo CD | https://localhost:8443 | `admin` / (ver `argocd-initial-admin-secret`) |

### ⚠️ NO HACER durante el video

1. ❌ **NO darle "Trigger DAG"** en Airflow UI → satura RAM, Docker se cuelga, video arruinado
2. ❌ **NO abrir más de 5 pestañas** del navegador a la vez
3. ❌ **NO recargar Argo CD** repetidas veces, es pesado
4. ❌ **NO ejecutar `docker compose up`** — choca con K8s

---

# 🎤 0:00 – 0:30 — INTRODUCCIÓN (cualquiera, idealmente Daniel)

### Qué muestra en pantalla:
- README.md del repo abierto en VS Code O navegador con el repo de GitHub

### Qué dice (palabra por palabra, ~80 palabras):

> "Hola, somos el equipo del proyecto final de MLOps 2026-1: **David Garzón, Juan Pérez y Daniel Velasco**. Construimos un sistema de Machine Learning Operations end-to-end para predecir el precio de propiedades inmobiliarias.
>
> El sistema integra recolección incremental de datos con Airflow, registro de experimentos en MLflow, inferencia con FastAPI, despliegue en Kubernetes con Argo CD, y observabilidad con Prometheus y Grafana.
>
> Vamos a mostrarles el sistema funcionando en 3 partes: datos y DAG, ML y servicio de inferencia, e infraestructura."

---

# 🟢 0:30 – 3:30 — P1 (David Garzón) — Datos y DAG

## Ventanas que P1 debe tener abiertas antes de empezar:
1. **VS Code** en la carpeta del repo
2. **PowerShell** (no la del port-forward de Argo CD)
3. **Navegador** en http://localhost:30808 (Airflow), ya logueado (admin/admin)

---

## ⏱ 0:30 – 1:00 (30 seg) — Visión general

### Qué hace en pantalla:
- VS Code visible
- Expande `airflow/dags/` → se ven 3 archivos: `api_client.py`, `main_pipeline.py`, `preprocessing.py`
- Click rápido en `scripts/init_db.sql` para mostrar los primeros CREATE TABLE

### Qué dice (palabra por palabra, ~70 palabras):

> "Hola, yo soy **David Garzón**. Me encargo del pipeline de datos: consumir la API externa, validar los lotes y decidir cuándo entrenar.
>
> Mi código vive en `airflow/dags/`: el `api_client.py` consume la API, el `main_pipeline.py` define el DAG completo con sus 17 tareas, y el `preprocessing.py` tiene las transformaciones.
>
> El DDL de las bases está en `scripts/init_db.sql` y crea los esquemas RAW DATA y CLEAN DATA."

---

## ⏱ 1:00 – 1:45 (45 seg) — Separación RAW/CLEAN

### Qué hace en pantalla:
- Cambia a **PowerShell**
- Pega comando #1 (los esquemas):

```powershell
kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c "\dn"
```

- Espera 2 segundos a que muestre la salida
- Pega comando #2 (los lotes):

```powershell
kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c "SELECT batch_id, n_records, status, fetch_timestamp FROM raw_data.raw_batches ORDER BY fetch_timestamp;"
```

### Qué dice (palabra por palabra, ~75 palabras):

> "Acá veo los esquemas separados que cumplen el RF2 del PDF: `raw_data` con los lotes crudos y `clean_data` con los datos procesados. La trazabilidad es obligatoria.
>
> Acá veo los 2 lotes que ya bajé de la API real del profesor. El primero con 73 mil registros, el segundo con 94 mil. Cada uno se persiste como JSONB con su batch_id único. Puedo reconstruir exactamente qué datos generaron qué modelo."

---

## ⏱ 1:45 – 2:30 (45 seg) — DAG y bifurcaciones

### Qué hace en pantalla:
- Cambia al **navegador** en Airflow (http://localhost:30808)
- Click en el DAG `real_estate_mlops_pipeline`
- Click en la pestaña **Graph**
- Apunta con el cursor (sin clickear) a `decide_training`, después a `decide_promotion`

### Qué dice (palabra por palabra, ~90 palabras):

> "Acá está el DAG corriendo en Airflow. Tiene 17 tareas con dos bifurcaciones explícitas que cumplen el RF4 del PDF.
>
> La primera bifurcación es `decide_training`. Las reglas son: si es la primera ejecución, si hay drift detectado por Kolmogorov-Smirnov, si aparecieron nuevas categorías con frecuencia mayor al cinco por ciento, o si el volumen creció más del diez por ciento.
>
> La segunda bifurcación es `decide_promotion`. Solo promuevo si el MAE baja al menos tres por ciento y el RMSE no empeora más de uno por ciento."

> ⚠️ **NO LE DEN CLICK A "TRIGGER DAG"** — esto es lo más importante. Solo muestren el grafo.

---

## ⏱ 2:30 – 3:30 (60 seg) — Auditoría y resultado

### Qué hace en pantalla:
- Cambia a **PowerShell**
- Pega comando #3:

```powershell
kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c "SELECT batch_id, decision, LEFT(reason,55) AS razon, promoted, model_version, status FROM raw_data.training_audit ORDER BY execution_date;"
```

### Qué dice (palabra por palabra, ~90 palabras):

> "Cada decisión queda persistida en la tabla `raw_data.training_audit`. Acá veo el resultado: el lote `batch_1_0000` entrenó porque no había modelo productivo previo, se promovió como línea base, y el modelo registrado es la versión 1.
>
> Esta misma tabla la lee Streamlit para mostrar el historial al usuario final.
>
> Con esto cumplo el RF3 y la sección de Datos del rubric: separación RAW y CLEAN, validación, decisión de entrenamiento con razón justificada, y auditoría completa.
>
> Le paso la palabra a Juan que va a mostrar el modelo en MLflow y la API de inferencia."

---

# 🟣 3:30 – 6:30 — P2 (Juan Pérez) — ML y FastAPI

## Ventanas que P2 debe tener abiertas antes de empezar:
1. **VS Code** en la carpeta del repo (con `training/` y `fastapi/` colapsados)
2. **Navegador** con 2 pestañas: http://localhost:30500 (MLflow) y http://localhost:30800/docs (Swagger)
3. **PowerShell**

---

## ⏱ 3:30 – 4:00 (30 seg) — Visión general

### Qué hace en pantalla:
- **VS Code** visible
- Segundo 0-15: expande `training/` → se ven 6 archivos (`Dockerfile`, `entrypoint.sh`, `train.py`, `evaluate.py`, `promote.py`, `preprocess.py`)
- Segundo 15-25: colapsa `training/`, expande `fastapi/` → se ven 5 archivos (`main.py`, `model_loader.py`, `inference_log.py`, `schemas.py`, `preprocess.py`)
- Segundo 25-30: cambia al navegador con MLflow ya abierto

### Qué dice (palabra por palabra, ~70 palabras):

> "Hola, yo soy **Juan**, encargado de Machine Learning. Tengo dos componentes en el repositorio.
>
> En la carpeta `training` empaco una imagen Docker reutilizable con tres subcomandos: `train`, `evaluate` y `promote` — el DAG la invoca con cada uno por separado.
>
> En la carpeta `fastapi` está el servicio de inferencia, con un cargador de modelo dinámico que consulta MLflow.
>
> Ahora se los muestro corriendo en vivo."

---

## ⏱ 4:00 – 4:45 (45 seg) — MLflow en vivo

### Qué hace en pantalla:
- **Navegador en MLflow** (http://localhost:30500)
- Click en pestaña **Experiments** (arriba)
- Click en el experimento `house-price`
- Click en el run que aparece (uno solo, `candidate-batch_1_0000`)
- Click rápido por las pestañas: **Parameters** → **Metrics** → **Artifacts** (1-2 seg en cada una)
- Click en pestaña **Models** (arriba)
- Click en `house-price-model` → mostrar **Version 1** con etiqueta **`@production`**

### Qué dice (palabra por palabra, ~95 palabras):

> "Acá está MLflow. Entreno un `RandomForestRegressor` con un `ColumnTransformer` que usa `OneHotEncoder` con `handle_unknown='ignore'`. Esto es muy importante porque si llega una ciudad nueva en producción, el pipeline **no se rompe** — exactamente lo que pide el RF3 del PDF.
>
> Registro todo: parámetros, métricas MAE, RMSE, MAPE y R cuadrado para train, val y test, artefactos como el gráfico de residuos, y el modelo serializado.
>
> Acá en Models veo el `house-price-model` versión 1 con el alias `production`. Cuando entrene una versión 2 que mejore las métricas, el alias se mueve automáticamente."

---

## ⏱ 4:45 – 5:45 (60 seg) — FastAPI Swagger en vivo

### Qué hace en pantalla:
- **Navegador en Swagger** (http://localhost:30800/docs)
- Mostrar los endpoints listados
- Click en `GET /health` → **Try it out** → **Execute** → mostrar respuesta
- Click en `POST /predict` → **Try it out** → el textbox tiene JSON precargado (lo deja como está) → **Execute**
- Mostrar la respuesta con `price`, `model_version`, `inference_id`
- Cambia a **PowerShell**, pega:

```powershell
kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c "SELECT request_id, model_version, prediction::INT AS price, latency_ms FROM raw_data.inference_events ORDER BY occurred_at DESC LIMIT 3;"
```

### Qué dice (palabra por palabra, ~120 palabras):

> "FastAPI tiene cuatro endpoints documentados con Swagger.
>
> El endpoint `/health` me dice qué modelo está cargado: versión 1, alias production. Importante: FastAPI **lee esto desde MLflow en vivo**, no es un valor quemado en código. Esto cumple el RF7.
>
> El endpoint `/predict` recibe los datos de una propiedad y devuelve el precio estimado. Acá veo el resultado: precio estimado de aproximadamente 234 mil dólares, versión 1 del modelo, con un `inference_id` único.
>
> Y acá en la base de datos veo que la predicción que acabo de hacer **ya está persistida** en `raw_data.inference_events` con su UUID, versión del modelo y latencia. Esto cumple el RF8 del PDF."

---

## ⏱ 5:45 – 6:30 (45 seg) — Métricas Prometheus

### Qué hace en pantalla:
- **PowerShell**, pega:

```powershell
curl.exe -s http://localhost:30800/metrics | Select-String -Pattern "model_version_info|http_requests_total" | Select-Object -First 10
```

### Qué dice (palabra por palabra, ~95 palabras):

> "Para observabilidad expongo `/metrics` con las series que Prometheus consume.
>
> Las tres más importantes son: `http_requests_total` con etiquetas de handler, método y status para contar peticiones y errores; `http_request_duration_seconds_bucket` para latencias p50, p95, p99; y `model_version_info`, un gauge custom que dice exactamente qué versión del modelo está cargada en cada momento.
>
> Con esto cumplo el RF10 del PDF.
>
> Le paso la palabra a Daniel para que muestre Argo CD, Streamlit, Locust y Grafana."

---

# 🔵 6:30 – 9:30 — P3 (Daniel Velasco) — Infra, GitOps, UI

## Ventanas que P3 debe tener abiertas antes de empezar:
1. **VS Code** en la carpeta `kubernetes/` del repo
2. **PowerShell**
3. **Navegador** con 5 pestañas: GitHub Actions, https://localhost:8443 (Argo CD), http://localhost:30501 (Streamlit), http://localhost:30089 (Locust), http://localhost:30300 (Grafana)

---

## ⏱ 6:30 – 7:00 (30 seg) — Visión general

### Qué hace en pantalla:
- **VS Code** mostrando el árbol de `kubernetes/`
- Después cambia a **PowerShell** y pega:

```powershell
kubectl -n mlops get pods
```

### Qué dice (palabra por palabra, ~70 palabras):

> "Hola, yo soy **Daniel**, encargado de la infraestructura, CI/CD, observabilidad e interfaz de usuario.
>
> Cada componente corre en Kubernetes desde manifiestos versionados en la carpeta `kubernetes/` del repo. Acá tengo los 11 pods del sistema corriendo: Airflow con webserver y scheduler, FastAPI con 2 réplicas, Postgres, MLflow, MinIO, Streamlit, Grafana, Prometheus, Locust y la data-api del profesor."

---

## ⏱ 7:00 – 7:45 (45 seg) — GitHub Actions + Argo CD

### Qué hace en pantalla:
1. **Navegador** → GitHub → tab Actions → mostrar workflows verdes
2. Cambia a la pestaña de **Argo CD** (https://localhost:8443)
3. Logueado, click en Application `mlops-proyecto-final`
4. Mostrar el estado **Synced** y **Healthy** + lista de recursos sincronizados

### Qué dice (palabra por palabra, ~100 palabras):

> "Tengo tres workflows en GitHub Actions que construyen y publican las imágenes en DockerHub al hacer push a main: `build-fastapi`, `build-streamlit` y `build-training`. Etiquetadas por commit SHA para reproducibilidad.
>
> Argo CD vive en su propio namespace. La Application `mlops-proyecto-final` monitorea el repo: cualquier cambio en `kubernetes/` se aplica al clúster automáticamente, con `prune: true` y `selfHeal: true`.
>
> Acá veo el estado **Synced + Healthy** con todos los recursos sincronizados. Esto es GitOps puro — no hay `kubectl apply` manual. Cumple el RF de GitOps del PDF."

---

## ⏱ 7:45 – 8:30 (45 seg) — Streamlit

### Qué hace en pantalla:
- **Navegador** en Streamlit (http://localhost:30501)
- Llenar el formulario con datos de una propiedad (ej: New York, 3 bed, 2 bath, 1800 sqft)
- Click en "Predecir"
- Mostrar el precio + versión del modelo
- Click en la pestaña **Historial** → mostrar la tabla con `batch_1_0000`

### Qué dice (palabra por palabra, ~85 palabras):

> "Streamlit tiene dos secciones obligatorias del RF9.
>
> La primera es **Inferencia**: el usuario llena un formulario, consume FastAPI y ve la predicción más la versión del modelo utilizada. Acá veo el precio estimado de unos 234 mil dólares con la versión 1.
>
> La segunda es **Historial de entrenamiento y despliegue**: muestra cada lote procesado con la decisión, la razón, y si fue promovido o rechazado. Acá veo `batch_1_0000`, decisión `train`, promovido como línea base."

---

## ⏱ 8:30 – 9:30 (60 seg) — Locust + Grafana

### Qué hace en pantalla:
1. **Navegador en Locust** (http://localhost:30089)
2. Configurar: Number of users = **50**, Spawn rate = **5**, Host = `http://fastapi:8000`
3. Click **Start swarming**
4. Mostrar el gráfico de RPS subiendo durante 5-10 segundos
5. Cambia a **Grafana** (http://localhost:30300)
6. Abrir dashboard `MLOps FastAPI Dashboard`
7. Mostrar los paneles en vivo: Total de Peticiones, RPS, Latencia, Tasa de Errores, Versión del Modelo
8. Cambia a **PowerShell** y pega:

```powershell
kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c "SELECT model_version, COUNT(*) AS total, ROUND(AVG(latency_ms)) AS avg_ms FROM raw_data.inference_events GROUP BY model_version;"
```

### Qué dice (palabra por palabra, ~135 palabras):

> "Para demostrar observabilidad bajo carga, lanzo Locust con 50 usuarios concurrentes contra `/predict`.
>
> Acá en el dashboard de Grafana veo los 5 paneles del `MLOps FastAPI Dashboard`: Total de Peticiones acumuladas, Tasa de Peticiones por segundo, Latencia p50 y p95, Tasa de Errores 5xx que se mantiene en cero, y la Versión del Modelo Productivo que indica que está cargada la versión 1.
>
> Y acá en la base de datos confirmo que las inferencias quedaron persistidas en `raw_data.inference_events` — más de 600 inferencias con su versión y latencia.
>
> Con esto cumplo el RF10 del PDF. Esto cierra mi parte."

---

# 🟡 9:30 – 10:00 — CIERRE CONJUNTO

### Qué muestra en pantalla:
- README.md con link al repo: `github.com/DANIEL-VELASCO/proyecto_final_mlops`

### Qué dicen (palabra por palabra, uno tras otro):

> **Daniel**: "Recapitulando: tenemos un sistema MLOps end-to-end desplegado en Kubernetes con GitOps, donde un evento de datos entra por Airflow, pasa por validaciones, decide si entrenar, y si entrena, compara contra el productivo."
>
> **Juan**: "Los modelos quedan versionados en MLflow con trazabilidad completa. FastAPI los carga sin redespliegue. Las inferencias quedan registradas para futuras iteraciones."
>
> **David**: "El despliegue es GitOps con Argo CD, las imágenes vienen de GitHub Actions y se publican en DockerHub. Todo el sistema es reproducible desde el repo."
>
> **Juntos (o uno solo)**: "Gracias por su atención. Repositorio: `github.com/DANIEL-VELASCO/proyecto_final_mlops`."

---

# 🆘 Si algo falla durante la grabación

| Problema | Solución rápida (15 segundos) |
|---|---|
| Pod en `Error` u `OOMKilled` | `kubectl -n mlops delete pod <nombre>` → reaparece en 30s |
| FastAPI devuelve 503 | `kubectl -n mlops delete pod -l app=fastapi` |
| Streamlit "Connection refused" | `kubectl -n mlops delete pod -l app=streamlit` |
| Grafana sin datos | Esperar 15s y refrescar el dashboard |
| Argo CD UI cerrada | Volver a abrir terminal con `kubectl -n argocd port-forward svc/argocd-server 8443:443` |
| Docker daemon colgado | Restart Docker Desktop → esperar 2 min → todos los pods reaparecen |

> **Si algo se rompe en VIVO**: no entren en pánico, salten al siguiente bloque y digan "acá hubo un timeout pero el resultado se puede ver en la base de datos / en MLflow" y muestren eso.

---

# 📋 Checklist FINAL (5 min antes de empezar a grabar)

- [ ] Cerrar Chrome, Discord, Spotify, IDE extra
- [ ] Confirmar `.wslconfig` con `memory=8GB`
- [ ] Correr los 4 chequeos de la sección "ANTES de empezar a grabar"
- [ ] Terminal con `kubectl -n argocd port-forward svc/argocd-server 8443:443` corriendo
- [ ] Cada persona tiene sus ventanas listas (ver secciones P1/P2/P3)
- [ ] Cada persona tiene su .txt con los comandos copy-paste a la mano
- [ ] OBS o Zoom listo, micrófono probado
- [ ] Practicar UNA VEZ completa antes de grabar

**Si los 4 chequeos están verdes → dale Record. Suerte 🎬**
