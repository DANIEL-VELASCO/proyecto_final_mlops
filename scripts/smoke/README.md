# Smoke test de P2 (ML Engineer)

Valida que el pipeline completo de P2 funciona end-to-end **antes** de pedirle
integración a P1 (DAG) y P3 (Grafana, Streamlit, K8s).

## Qué prueba

1. PostgreSQL + MinIO + MLflow arrancan en `docker-compose`.
2. Las dos bases (`raw_data`, `clean_data`) y `clean_data.properties` se crean.
3. Se genera un CSV sintético de 8 000 propiedades (`gen_synthetic_clean_data.py`).
4. El CSV se carga en `clean_data.properties`.
5. `docker compose --profile training run training train ...` entrena un
   `RandomForestRegressor` y lo registra en el Model Registry.
6. `evaluate` corre contra el candidato y reporta `no_production_model: true`.
7. `promote` asigna alias `production` al primer modelo por defecto.
8. FastAPI arranca, `/health` reporta `model_loaded: true`.
9. `POST /predict` devuelve `price + model_version` y deja registro en
   `raw_data.inference_events`.
10. `/metrics` expone `model_version_info`, `http_requests_total`, etc.

## Cómo correrlo

Pre-requisito: Docker Desktop arrancado.

```powershell
# Desde la raíz del repo:
pwsh ./scripts/smoke/run_smoke.ps1
# Opcional: limpiar contenedores y volúmenes al final
pwsh ./scripts/smoke/run_smoke.ps1 -Cleanup
```

URLs útiles tras el smoke:

- MLflow UI — http://localhost:15000
- MinIO console — http://localhost:19001 (`minioadmin` / `minioadmin`)
- FastAPI docs — http://localhost:8000/docs

## Cuando algo falle

| Síntoma                                        | Probable causa                                  |
| ---------------------------------------------- | ----------------------------------------------- |
| `mc mb` falla con "Access Denied"              | El bucket ya existe; el script lo ignora        |
| `train` falla con "datos insuficientes"        | Bajar `--rows` no, subirlo. Default 8 000 OK    |
| FastAPI `/predict` → 503                       | Esperar más; el poller carga el modelo en ≤30 s |
| `inference_events` vacía pero `/predict` OK    | Revisar `DATABASE_URI` y permisos a `raw_data`  |
| `/metrics` no muestra `model_version_info`     | El gauge se setea sólo tras la primera carga    |
