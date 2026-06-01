# Estado de P2 (ML Engineer) — 2026-05-31

## TL;DR

✅ **Mi código está mergeado en `main`** (PR #1, commit `b4185bf`).
⚠️ **Quedan 5 bloqueos para que el sistema funcione end-to-end**, todos
del lado de P1 y P3 (yo no puedo destrabarlos por contrato).
🔴 **El clúster K8s local está corriendo con código viejo** (imagen
`max181818/mlops-api:latest` que no es mía). Hay que rebuildar y rotar.

---

## ✅ Listo (P2 — lo que ya entregué)

| Componente                                          | Archivo                                       | Cubre   |
| --------------------------------------------------- | --------------------------------------------- | ------- |
| Preprocesamiento con OneHotEncoder(handle_unknown)  | `training/preprocess.py`                      | RF3/RF4 |
| Entrenamiento + registro en MLflow                  | `training/train.py`                           | RF5     |
| Evaluación candidato vs productivo (mismo holdout)  | `training/evaluate.py`                        | RF6     |
| Promoción con regla MAE −3 % / RMSE +1 %            | `training/promote.py`                         | RF6     |
| Imagen Docker con subcomandos train/evaluate/promote| `training/Dockerfile` + `training/entrypoint.sh` | —    |
| FastAPI con /health /predict /metrics /reload-model | `fastapi/main.py`                             | RF7/RF8/RF10 |
| Recarga sin redespliegue + fallback                 | `fastapi/model_loader.py`                     | RF7     |
| Registro de inferencias en `raw_data.inference_events` | `fastapi/inference_log.py`                 | RF8     |
| Métricas Prometheus alineadas al dashboard de P3    | `fastapi/main.py` (gauge `model_version_info`)| RF10    |
| Contratos documentados hacia P1 y P3                | `docs/contracts/p2-interfaces.md`             | —       |
| Smoke test end-to-end (docker-compose)              | `scripts/smoke/run_smoke.ps1`                 | —       |

---

## 🔴 Bloqueos / Inconsistencias detectadas

### B1. PR mergeado a `main` directamente, `develop` quedó desincronizado
- `main` ya tiene mis 6 commits.
- `develop` sigue en `8a61a98` (no tiene nada de P2).
- El doc de distribución (sección 8.3) dice **`feature/* → develop → main`**.
- **Acción**: hacer un PR `main → develop` o un cherry-pick de los commits.
  Si no, cuando P1 ramifique de `develop` no va a ver mis archivos.

### B2. El clúster K8s usa imagen `max181818/mlops-api:latest` (no es la mía)
- Mi workflow `build-fastapi.yml` publica `${DOCKERHUB_USERNAME}/mlops-fastapi:sha-XXXX`.
- El Deployment en `kubernetes/fastapi/deployment.yaml` apunta a `danielvelasco01/mlops-fastapi:latest`.
- Pero los pods corriendo HOY usan `max181818/mlops-api:latest` (un Deployment legacy de 18 días).
- **Acción P3**: borrar el Deployment viejo y aplicar el manifiesto del repo
  con la nueva imagen (`max181818/mlops-fastapi:sha-b4185bf` cuando termine el
  build de GH Actions).

### B3. Postgres en K8s tiene rol `mlops` faltante
- `kubectl exec postgres-0 -- psql -U mlops` → `role "mlops" does not exist`.
- Las bases `airflow`, `mlflow`, `mlops` y los esquemas `raw_data` / `clean_data`
  **no se crearon** porque el ConfigMap `postgres-init` se ejecuta una sola vez
  al PRIMER boot, y el StatefulSet ya tiene volumen viejo que saltó esa fase.
- **Acción P1+P3**: borrar el PVC de postgres y reiniciar (perderás los datos
  actuales, pero como no hay datos productivos aún, no importa).

### B4. Nombres de servicio inconsistentes en Secrets
- Los Services en K8s se llaman `mlflow-service`, `postgres-service`, `minio-service`, `fastapi-service`.
- Pero `kubernetes/secrets.yaml` apunta a `http://mlflow:5000`, `postgres:5432`, `http://minio:9000`.
- **Acción P3**: cambiar los Secrets para usar `mlflow-service`, `postgres-service`, `minio-service`.

### B5. Tablas que debe crear P1 (sin ellas mi código falla)
- `clean_data.properties` (la lee mi `training/train.py`)
- `raw_data.training_audit` (la lee Streamlit, no yo, pero el DAG la escribe)
- `raw_data.inference_events` — **yo la creo con `CREATE TABLE IF NOT EXISTS`
  si no existe**, pero P1 debería poner su DDL oficial en `kubernetes/databases/configmap.yaml`.

---

## 🟡 Cosas que faltan por hacer (a nivel proyecto, no solo P2)

| #   | Pendiente                                       | Responsable     |
| --- | ----------------------------------------------- | --------------- |
| 1   | Sincronizar `develop` con `main`                | P3 o cualquiera |
| 2   | Borrar PVC de postgres y rebootstrap            | P3              |
| 3   | Arreglar Secrets de K8s (`-service` suffix)     | P3              |
| 4   | Cambiar Deployment fastapi a mi imagen          | P3              |
| 5   | Implementar DAG de Airflow (tareas 1-9 + DAG completo) | **P1**   |
| 6   | Crear DDL de `clean_data.properties` y `raw_data.training_audit` | **P1** |
| 7   | Smoke test end-to-end vivo (cuando 1-6 listos)  | yo (P2)         |
| 8   | Configurar Argo CD Application para sync GitOps | P3              |
| 9   | Locust escenario con duración + ramp-up         | P3 (ya casi listo) |
| 10  | Video de sustentación 10 min (YouTube)          | **Todos**       |

---

## 🟢 Cuando estos bloqueos se destraben, así corre todo

1. P1 reinicia postgres → bases + esquemas + tablas creadas.
2. P3 cambia el Deployment fastapi → mi imagen pulled de DockerHub.
3. P3 reinicia Streamlit/Grafana/Prometheus → siguen viendo lo mismo (mismo contrato).
4. P1 dispara el DAG manualmente o lo programa cada N minutos.
5. Cada ejecución del DAG: consume API → valida → decide → entrena (vía mi imagen training) → registra en MLflow → compara → promueve si cumple regla.
6. FastAPI detecta el nuevo modelo en ≤30 s (poller) y lo recarga sin redespliegue.
7. Streamlit muestra historial leyendo `raw_data.training_audit`.
8. Grafana muestra latencia/req-rate/versión del modelo.
9. Locust dispara carga → Grafana evidencia el efecto.

---

## 📈 Cumplimiento del rubric (sección 9 del PDF)

| Criterio                  | Estado P2  | Notas                                                                                 |
| ------------------------- | ---------- | ------------------------------------------------------------------------------------- |
| Orquestación              | n/a        | P1                                                                                    |
| Datos (RAW / CLEAN)       | n/a (P1)   | Yo escribo eventos de inferencia en `raw_data`; P1 hace la separación                 |
| Decisión de entrenamiento | parcial    | El primer caso ("no hay productivo → entrenar") lo cubro yo; el resto lo decide P1    |
| MLflow                    | ✅ listo   | params, métricas, artefactos, modelo registrado, tags `batch_id`/`training_reason`    |
| Promoción de modelos      | ✅ listo   | Regla MAE −3 % / RMSE +1 %, configurable por flag                                     |
| Inferencia                | ✅ listo   | FastAPI carga desde MLflow por alias, recarga sin redespliegue, fallback              |
| Streamlit                 | n/a        | P3 (yo le entrego el contrato HTTP)                                                   |
| CI/CD                     | n/a        | P3 (yo entrego Dockerfile válido para sus workflows)                                  |
| GitOps                    | n/a        | P3                                                                                    |
| Kubernetes                | parcial    | Mis manifiestos los redactó P3; falta sincronizar imagen y Secrets                    |
| Observabilidad            | ✅ listo   | `/metrics` expone exactamente las series que el dashboard de Grafana ya consulta      |
| Documentación             | ✅ listo   | `docs/contracts/p2-interfaces.md` + este `STATUS_P2.md` + READMEs en `scripts/smoke/` |

---

Generado automáticamente por P2.
