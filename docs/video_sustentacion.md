# Guion — Video de sustentación (10 min máx — YouTube)

Distribución sugerida: **3 min P1 + 3 min P2 + 3 min P3 + 1 min cierre conjunto**.

Para grabar: cada uno comparte pantalla en su parte. Recomendado OBS o Zoom. Pueden grabar por separado y editar.

---

## 0:00 – 0:30 — Introducción (cualquiera, idealmente Daniel)

> "Hola, somos el equipo del proyecto final de MLOps 2026-1, **Persona 1 David Garzón, Persona 2 Juan Pérez, Persona 3 Daniel Velasco**. Construimos un sistema MLOps completo para estimar precios de propiedades inmobiliarias.
>
> El sistema integra recolección de datos vía Airflow, registro en MLflow, inferencia en FastAPI, despliegue en Kubernetes con GitOps mediante Argo CD, y observabilidad con Prometheus y Grafana.
>
> Vamos a mostrarles los 3 frentes: datos y orquestación, ML y servicio de inferencia, y la infraestructura y CI/CD."

**Mostrar en pantalla**: README.md del repo + diagrama de arquitectura.

---

## 0:30 – 3:30 — Persona 1 (David Garzón) — Datos y DAG

### 0:30 – 1:00 — Visión general

> "Yo soy responsable del pipeline de datos. Mi módulo consume la API externa, valida los lotes y decide cuándo entrenar.
>
> Las primeras 9 tareas del DAG corresponden a recolección, validación y decisión. Mi código está en `airflow/dags/` y el DDL de las bases está en `scripts/init_db.sql`."

**Mostrar**: estructura de `airflow/dags/` + diagrama del DAG.

### 1:00 – 1:45 — Cómo decido si entrenar (RF3 + RF4)

> "Cada lote pasa por 4 validaciones antes de decidir:
>
> 1. **Schema check** — comparo las columnas y tipos recibidos contra el esperado.
> 2. **Calidad** — nulos, duplicados, rangos inválidos.
> 3. **Drift detection** — uso Kolmogorov-Smirnov contra el histórico para detectar si la distribución cambió.
> 4. **Nuevas categorías** — comparo contra mi `category_catalog` y veo si alguna nueva tiene frecuencia ≥5 %.
>
> Solo entreno si: es la primera ejecución, hay drift, hay categorías nuevas significativas, o el volumen creció ≥10 %."

**Mostrar**: función `decide_training` en `main_pipeline.py` + tabla `raw_data.training_audit`.

### 1:45 – 2:30 — Ejecutar el DAG en Airflow UI

> "Aquí está Airflow corriendo en Kubernetes. Activo el DAG `real_estate_mlops_pipeline` y disparo manualmente la primera ejecución. Vean cómo cada tarea cambia de estado, la decisión de entrenamiento se imprime en los logs, y al final se actualiza la tabla `raw_data.training_audit`."

**Mostrar**: Airflow UI con grafo del DAG ejecutándose + logs de `decide_training` + query a `training_audit`.

### 2:30 – 3:30 — Separación RAW / CLEAN + auditoría (RF2)

> "Cada lote crudo se persiste en `raw_data.raw_batches` con su payload JSONB original. El preprocesamiento se hace en `preprocessing.py` y los datos limpios van a `clean_data.properties`. Hay trazabilidad completa: puedo reconstruir qué datos generaron qué modelo.
>
> El historial visible para los demás integrantes vive en `raw_data.training_audit`, que tiene `batch_id`, `decision`, `razon`, `mae_candidato`, `mae_productivo`, y si fue promovido o rechazado."

**Mostrar**: query `SELECT * FROM raw_data.training_audit ORDER BY execution_date DESC LIMIT 5;`.

---

## 3:30 – 6:30 — Persona 2 (Juan) — Entrenamiento, MLflow y FastAPI

### 3:30 – 4:00 — Visión general

> "Yo soy responsable de la parte de Machine Learning: el pipeline de entrenamiento, el registro en MLflow y el servicio de inferencia con FastAPI.
>
> El DAG de P1 me invoca como una imagen Docker con 3 subcomandos: `train`, `evaluate` y `promote`. Y FastAPI consume el modelo productivo desde MLflow."

**Mostrar**: estructura de `training/` y `fastapi/`.

### 4:00 – 4:45 — MLflow + comparación + promoción (RF5 + RF6)

> "Entreno un `RandomForestRegressor` con un `ColumnTransformer` que tiene `OneHotEncoder(handle_unknown="ignore")` — esto es clave: si llega una ciudad nueva, el pipeline no se rompe.
>
> Registro en MLflow: parámetros, métricas (MAE, RMSE, MAPE, R² para train/val/test), artefactos (gráfico de residuos, feature importance) y el modelo como sklearn Pipeline.
>
> La promoción tiene una regla explícita: promuevo solo si el MAE baja al menos 3 % **y** el RMSE no empeora más de 1 %. Si cumple, asigno el alias `production` en MLflow Model Registry. Si no, queda registrado pero no se promueve."

**Mostrar**: MLflow UI con el experimento + comparación de modelos + alias `production` apuntando a la versión actual.

### 4:45 – 5:45 — FastAPI con recarga sin redespliegue (RF7 + RF8)

> "FastAPI carga el modelo desde MLflow por alias. El alias actual se consulta cada 30 segundos en un poller en background. Si cambia, recarga el modelo en memoria con un lock thread-safe; si la nueva carga falla, mantengo el modelo previo como fallback.
>
> También expone `/reload-model` protegido por un token para forzar recarga manual.
>
> Cada inferencia se persiste en `raw_data.inference_events` con `request_id` UUID, payload completo en JSONB, predicción, versión del modelo y latencia."

**Mostrar**: Swagger en `/docs` + un `POST /predict` desde Swagger devolviendo precio + `SELECT FROM raw_data.inference_events` mostrando la fila recién insertada.

### 5:45 – 6:30 — Métricas Prometheus (RF10)

> "Para observabilidad, expongo `/metrics` con las series que el dashboard de Grafana ya consulta:
> - `http_requests_total{handler, method, status}`
> - `http_request_duration_seconds_bucket{le}`
> - `model_version_info{version, alias, model_name}` — gauge custom que dice qué modelo está cargado
>
> Esto se conecta con el load test de Locust que va a mostrar Daniel."

**Mostrar**: `curl /metrics` con las 3 métricas resaltadas.

---

## 6:30 – 9:30 — Persona 3 (Daniel) — K8s, GitOps, Observabilidad

### 6:30 – 7:00 — Visión general

> "Yo soy responsable de la infraestructura, CI/CD, observabilidad e interfaz de usuario.
>
> Cada componente del sistema corre en Kubernetes desde manifiestos versionados en `kubernetes/`. Argo CD sincroniza el repo con el clúster — un push a `main` se refleja solo."

**Mostrar**: árbol de `kubernetes/` + namespace `mlops` con todos los pods Running.

### 7:00 – 7:45 — GitHub Actions + Argo CD (CI/CD + GitOps)

> "Tres workflows construyen y publican las imágenes en DockerHub al hacer push a `main` o `develop`, etiquetadas por commit SHA para reproducibilidad."
>
> "Argo CD está corriendo en el namespace `argocd`. La Application `mlops-proyecto-final` monitorea el repo: cualquier cambio en `kubernetes/` lo aplica al clúster automáticamente, con `prune: true` y `selfHeal: true`."

**Mostrar**: Argo CD UI con la Application `Synced + Healthy` + lista de recursos administrados (deployments, services, configmaps).

### 7:45 – 8:30 — Streamlit (RF9)

> "La interfaz tiene 2 secciones: **inferencia**, donde el usuario llena un formulario y ve la predicción + versión del modelo, y **historial**, que muestra cada lote procesado con la decisión y razón leyendo de `raw_data.training_audit`."

**Mostrar**: Streamlit con un input → resultado → tabla de historial.

### 8:30 – 9:30 — Prueba de carga con Locust + Grafana

> "Para demostrar el sistema bajo carga, lanzo Locust con 80 usuarios concurrentes contra `/predict` durante 90 segundos."

**Mostrar**: Locust UI con stats en vivo (RPS subiendo, latencias).

> "En Grafana vemos en tiempo real el impacto en los 5 paneles del dashboard `MLOps FastAPI Dashboard`:
> - Total de peticiones acumulado
> - Tasa req/s
> - Latencia p50 y p95
> - Tasa de errores 5xx (que se mantiene en cero)
> - Versión del modelo cargado
>
> Y al final, en la base de datos, podemos confirmar que las miles de inferencias quedaron persistidas en `raw_data.inference_events`."

**Mostrar**: Grafana con los 5 paneles activos durante el load test + query final `SELECT COUNT(*) FROM raw_data.inference_events;`.

---

## 9:30 – 10:00 — Cierre conjunto

> *(Daniel)*: "Recapitulando: tenemos un sistema MLOps end-to-end donde un evento de datos nuevo entra por Airflow, pasa por validaciones, se entrena un modelo si corresponde, se compara contra el productivo, y si mejora se promueve. La API se entera del cambio sin redespliegue."
>
> *(P2)*: "Los modelos quedan versionados en MLflow con trazabilidad completa, las inferencias quedan registradas para futuras iteraciones, y las métricas son observables en Grafana."
>
> *(P1)*: "El despliegue es GitOps, las imágenes vienen del CI, y todo es reproducible desde el repo."
>
> *(juntos)*: "Gracias por su atención. Repositorio: `github.com/DANIEL-VELASCO/proyecto_final_mlops`."

---

## Checklist técnico antes de grabar

- [ ] Pasar el smoke test sin errores (`pwsh ./scripts/smoke/run_smoke.ps1`)
- [ ] Tener postgres, MLflow, MinIO, FastAPI, Streamlit, Grafana, Prometheus, Locust, Airflow y Argo CD todos en `Running`
- [ ] Tener al menos un modelo `house-price-model v1` con alias `production` en MLflow
- [ ] Tener al menos 50 inferencias en `raw_data.inference_events` para que el dashboard de Grafana tenga datos
- [ ] Tener al menos 1 fila en `raw_data.training_audit` para que Streamlit muestre algo
- [ ] Tener Argo CD UI accesible y mostrando `Synced + Healthy`
- [ ] Activar el DAG `real_estate_mlops_pipeline` antes de grabar (para que haya runs visibles)

## Tips para que se vea profesional

- Practicar una vez completa antes de grabar — el video tiene tope de 10 min.
- Compartir solo la ventana relevante en cada parte, no todo el escritorio.
- Tener las URLs de port-forward preparadas y verificadas justo antes.
- Si una demo falla en vivo, tener un screenshot de respaldo para no perder tiempo.
- Voz clara, audio sin ruido de fondo (revisar micrófono).
- El video se sube a YouTube en modo **No listado** para que el profesor pueda verlo con el link.
