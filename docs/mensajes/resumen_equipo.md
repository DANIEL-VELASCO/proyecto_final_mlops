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
| **FastAPI** | Running 2 réplicas | image `mlops-fastapi:local`, `/health` `/predict` `/metrics` `/reload-model` |
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

## 🔄 Integración entre los 3 sin reuniones

- P1 creó el DDL de `raw_data.inference_events` con el schema exacto que P2 escribe (coincidió porque ambos derivamos del mismo Word de distribución).
- El DAG de P1 invoca `train/evaluate/promote` de la imagen de P2 con los argumentos exactos que documenté en `docs/contracts/p2-interfaces.md`.
- FastAPI de P2 emite las **mismas series Prometheus** que ya consulta el dashboard de Grafana de P3 (sin tener que cambiar nada).
- Streamlit de P3 manda el payload exacto que aceptan los Pydantic schemas de FastAPI.

## 🌳 Estado del repositorio

```
main = develop = ff758f1  (sin desfase, ambos al día)

Hitos en el historial:
  ff758f1  Merge PR: feat(p2): integration fixes + bring P1 into integration line
  f4728fe  Merge PR: feat(p1): DAG completo, pipeline de datos y DDL de base de datos
  c776652  docs(integration): plan to merge feature branches via develop -> main
  ad215aa  fix(p2): use mlflow.sklearn instead of pyfunc to bypass schema enforcement
  eb9e96e  feat(p1): DAG completo, pipeline de datos y DDL de base de datos
  9ceb79b  Merge pull request #1 from DANIEL-VELASCO/feature/p2-mlflow-fastapi
```

Argo CD apunta a `main` con `automated.prune + selfHeal` → cualquier commit nuevo se sincroniza solo.

## 🟡 Pendiente (no bloquea ya, pero conviene cerrar)

| # | Pendiente | Quién | Notas |
|---|---|---|---|
| 1 | **DOCKERHUB_USERNAME + DOCKERHUB_TOKEN** en GitHub Actions Secrets | dueño del repo (Daniel) | Settings → Secrets and variables → Actions. Mientras tanto, K8s usa imágenes locales con `imagePullPolicy: Never`. |
| 2 | Ejecutar el DAG por primera vez contra la API REAL (`cristiandiaz13/mlops-puj:data-api-pf-v1`) | P1 | El DAG ya está cargado en Airflow; falta activarlo (despausarlo) y ver que consume datos reales. |
| 3 | **Video sustentación 10 min** en YouTube | Todos | Guion completo en `docs/video_sustentacion.md` |
| 4 | README del repo refinado | yo (ya entregado) | Ver `README.md` |

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
