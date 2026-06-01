# feat(p2): integration fixes + bring P1's DAG/DDL into the integration line

URL para abrir el PR (base `main`):
https://github.com/DANIEL-VELASCO/proyecto_final_mlops/pull/new/feature/p2-status-and-fixes

---

## Resumen

Cierra la integración entre P1 (DAG + DDL) y P2 (training + FastAPI) sobre el
clúster K8s real, y valida el sistema end-to-end. Mergea
`feature/p1-airflow-dag` y agrega correcciones del lado de P2 detectadas durante
la validación contra el clúster.

## Commits

1. **`fix(p2): use mlflow.sklearn instead of pyfunc to bypass schema enforcement`**
   - `training/evaluate.py` y `fastapi/model_loader.py`: cambian de
     `mlflow.pyfunc.load_model` a `mlflow.sklearn.load_model` para evitar el
     bug de MLflow donde `StringDtype` de pandas no se convierte a `<U0`.
   - `training/entrypoint.sh`: limpia CRLF para que el shebang `/usr/bin/env bash`
     resuelva en el contenedor (lo causaba git autocrlf en Windows).
   - `kubernetes/fastapi/deployment.yaml`: cambia `image:` a `mlops-fastapi:local`
     con `imagePullPolicy: Never` mientras GitHub Actions no publique las imágenes,
     añade annotations `prometheus.io/scrape: "true"` para que el cluster scrape
     automáticamente.
   - `kubernetes/secrets.yaml`: alinea hostnames a `*-service` (mlflow-service,
     postgres-service, minio-service — los Services reales del clúster) y
     credenciales a las del Secret legacy `mlops-secrets` (`minio_admin`,
     `mlops_user`) para no romper apps existentes.
   - `docs/STATUS_P2.md` + `docs/mensajes/para_p1.md` + `docs/mensajes/para_p3.md`:
     reporte completo de bloqueos y mensajes listos para el equipo.

2. **`feat(p1): DAG completo, pipeline de datos y DDL de base de datos`** (merge
   desde `feature/p1-airflow-dag` — autoría: P1).

## Validación end-to-end ejecutada

Ejecutada en el clúster `kind` local (Docker Desktop K8s) tras aplicar todos
los manifiestos:

| Paso                                                            | Resultado |
| --------------------------------------------------------------- | --------- |
| `kubectl apply -f kubernetes/databases/`                        | ✅ creado |
| `psql -f scripts/init_db.sql` (DDL de P1)                       | ✅ tablas raw_batches, row_hashes, category_catalog, inference_events, training_audit creadas |
| Cargar 5000 filas sintéticas en `clean_data.properties`         | ✅        |
| `docker run mlops-training:local train --batch-id smoke-001`    | ✅ model_version=1, MAE_test=85,465, R²_test=0.91 |
| `docker run mlops-training:local evaluate --candidate-version 1`| ✅ `no_production_model: true` |
| `docker run mlops-training:local promote --candidate-version 1` | ✅ alias `production` asignado a v1 |
| `kubectl apply -f kubernetes/fastapi/`                          | ✅ 2 réplicas Running |
| `curl /health`                                                  | ✅ `model_loaded: true, version: 1, alias: production` |
| `curl POST /predict`                                            | ✅ `price=$764,835`, `model_version=1`, latency 205 ms |
| `curl /metrics`                                                 | ✅ `model_version_info{version="1",alias="production"} 1.0` |
| `SELECT FROM raw_data.inference_events`                         | ✅ 1 fila con request_id, prediction, status=ok |

## Coordinación verificada

- P1 invoca mis 3 subcomandos (`train`/`evaluate`/`promote`) usando EXACTAMENTE
  el contrato de `docs/contracts/p2-interfaces.md` §1 (a pesar de que P1 dice
  que solo se guió por el Word de distribución — los contratos coincidieron
  porque ambos derivan del mismo documento maestro).
- El schema de `raw_data.inference_events` que P1 creó coincide al 100 % con el
  que mi `inference_log.py` espera. Mi `CREATE TABLE IF NOT EXISTS` es no-op.
- Streamlit y Locust (P3, ya en `main`) consumen `/predict` con el payload que
  mis schemas Pydantic aceptan sin transformación.
- El dashboard de Grafana (P3, ya en `main`) consulta exactamente las series
  Prometheus que mi `/metrics` emite (verificado contra el JSON del ConfigMap).

## Lo que queda pendiente (no bloquea este PR)

- [ ] **DOCKERHUB_USERNAME y DOCKERHUB_TOKEN** en GitHub Secrets para que los
      workflows publiquen `max181818/mlops-fastapi:sha-XXXX` y
      `max181818/mlops-training:sha-XXXX`. Mientras tanto el clúster usa
      imágenes locales con `imagePullPolicy: Never`.
- [ ] Sincronizar `develop` con `main` (mismo desfase de antes).
- [ ] Cuando P1 ejecute el DAG por primera vez contra la API real
      (`cristiandiaz13/mlops-puj:data-api-pf-v1`), validar que la tarea
      `train_candidate_model` puede correr `docker run` desde dentro del pod
      de Airflow (puede requerir montar `/var/run/docker.sock` o cambiar a
      `KubernetesPodOperator`).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
