# Plan de integración final — Proyecto MLOps 2026-1

> Documento de coordinación. Última actualización: 2026-05-31 22:00 UTC-5

## Estado actual del repositorio

| Rama                                | HEAD       | Estado                                                          |
| ----------------------------------- | ---------- | --------------------------------------------------------------- |
| `main`                              | `b4185bf`  | tiene P3 (k8s, streamlit, locust, CI, grafana) + P2 (training + fastapi + smoke) — sin las correcciones de la integración |
| `develop`                           | `b4185bf`  | **acabo de sincronizarla con `main`** — ya están idénticas       |
| `feature/p1-airflow-dag`            | `efd6ae2`  | trabajo de P1 (DAG, DDL, api_client) — pusheada, **sin PR abierto** |
| `feature/p2-status-and-fixes`       | `131eb4a`  | mi rama de cierre: incluye P1 mergeado + fix sklearn + secrets/manifests corregidos + validación end-to-end — **sin PR abierto** |

## Cómo NO se debe hacer (lo que pasó antes)

PR #1 (mío) se mergeó directo a `main`, saltándose `develop`. Eso dejó
`develop` 6 commits atrás de `main` y rompió el flujo del documento de
distribución (§8.3).

**Regla**: **NO mergear a `main` directamente**. Todas las features van a
`develop`. Cuando develop esté completo y validado en K8s, alguien autorizado
(generalmente el dueño del repo) abre el PR `develop → main` y lo mergea.

## Cómo SÍ se debe hacer ahora

```
                                  PR (P1)
feature/p1-airflow-dag ───────────────────────►┐
                                                │
                                                ├───► develop ───────►  main
                                                │       (Daniel)
                                  PR (P2)       │
feature/p2-status-and-fixes ──────────────────►┘
```

### Paso 1 — P1 abre su PR

P1 debe abrir su PR con base `develop`:

URL directa:
https://github.com/DANIEL-VELASCO/proyecto_final_mlops/compare/develop...feature/p1-airflow-dag

Título sugerido:
```
feat(p1): DAG completo, pipeline de datos y DDL de base de datos
```

### Paso 2 — P2 (yo) abre su PR

Mi PR debe ir a `develop` (no a `main` como puse antes):

URL directa:
https://github.com/DANIEL-VELASCO/proyecto_final_mlops/compare/develop...feature/p2-status-and-fixes

Título:
```
feat(p2): integration fixes + bring P1's DAG/DDL into the integration line
```

Cuerpo: usar el contenido de `docs/pr/p2-integration-fixes.md` (en este repo).

**Nota importante**: mi rama YA INCLUYE el merge de `feature/p1-airflow-dag`. Si
P1 abre su PR primero y se mergea a develop, mi PR queda con menos cambios
(automático por git). Si P1 abre su PR después, no pasa nada — mis cambios y
los de él se solapan correctamente.

### Paso 3 — verificar que `develop` sigue funcionando en K8s

Una vez ambos PRs mergeados a `develop`:

```bash
git checkout develop
git pull
# Reaplicar todo al clúster
kubectl -n mlops apply -f kubernetes/databases/
kubectl -n mlops apply -f kubernetes/secrets.yaml
kubectl -n mlops apply -f kubernetes/fastapi/
kubectl -n mlops apply -f kubernetes/mlflow/
# El smoke test que valida end-to-end
docker build -t mlops-fastapi:local ./fastapi
docker build -t mlops-training:local ./training
# El detalle de validación está en docs/pr/p2-integration-fixes.md
```

Validar:
- `kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c "\dt raw_data.*"` → 5 tablas
- `curl http://localhost:18000/health` → `model_loaded: true, version: 1, alias: production`
- `curl POST http://localhost:18000/predict ...` → devuelve precio
- `SELECT FROM raw_data.inference_events` → tiene filas

### Paso 4 — Daniel (o quien corresponda) abre PR final `develop → main`

URL directa:
https://github.com/DANIEL-VELASCO/proyecto_final_mlops/compare/main...develop

Cuando se mergee, **ArgoCD (cuando esté configurado) sincronizará el cluster
automáticamente**.

---

## Pendientes que NO bloquean la integración a develop

Estos pueden quedar para iteraciones posteriores:

1. **`develop` → `main`**: lo hace Daniel cuando todos los PRs lleguen a develop.
2. **GitHub Secrets** `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN`: necesarios para
   que el workflow `build-fastapi.yml` y `build-training.yml` publiquen
   imágenes. Mientras no estén, el clúster usa `imagePullPolicy: Never` y
   construimos local. **Lo configura el dueño del repo** (Settings → Secrets
   and variables → Actions).
3. **Argo CD Application** en `kubernetes/argocd/application.yaml`: ya está el
   YAML pero hay que instalar Argo CD en el clúster y aplicarlo. P3.
4. **Ejecutar el DAG por primera vez** consumiendo `data-api-pf-v1` real
   (Cristian Díaz). P1 debe ajustar `TRAINING_IMAGE` env var del Deployment
   de Airflow para que apunte a `mlops-training:local` o a la imagen
   publicada en DockerHub.
5. **Locust load test**: ejecutar y capturar screenshots de Grafana para el
   video. P3.
6. **Video de sustentación 10 min**: todos.

---

## Resumen ejecutivo (3 líneas para el chat del equipo)

> Sistema validado end-to-end en K8s (FastAPI sirviendo predicciones del
> modelo v1, MLflow con alias `production`, inferencias logged en `raw_data`,
> Grafana viendo métricas). Falta: P1 abre su PR a `develop`, yo (P2) abro
> el mío a `develop`, y cuando ambos estén ahí, Daniel hace el PR
> `develop → main`. Todo el detalle: `docs/INTEGRATION_PLAN.md`.
