# Locust — Pruebas de carga

Prueba de carga sobre el endpoint `/predict` de FastAPI.

## Ejecutar con Docker

```bash
docker run --rm -p 8089:8089 \
  -v $(pwd)/locustfile.py:/locust/locustfile.py \
  locustio/locust:2.28.0 \
  -f /locust/locustfile.py \
  --host http://<FASTAPI_URL>
```

## Ejecutar en modo headless (sin UI)

```bash
docker run --rm \
  -v $(pwd)/locustfile.py:/locust/locustfile.py \
  locustio/locust:2.28.0 \
  -f /locust/locustfile.py \
  --host http://<FASTAPI_URL> \
  --users 50 \
  --spawn-rate 5 \
  --run-time 2m \
  --headless \
  --csv=results
```

## Ejecutar desde Kubernetes (port-forward)

```bash
# 1. Hacer port-forward de FastAPI
kubectl port-forward svc/fastapi 8000:8000 -n mlops

# 2. Abrir la UI de Locust en http://localhost:8089
# 3. Host: http://localhost:8000
# 4. Usuarios: 50, Spawn rate: 5
```

## Parámetros recomendados para la prueba

| Parámetro | Valor |
|-----------|-------|
| Usuarios simultáneos | 50 |
| Spawn rate | 5 usuarios/s |
| Duración | 2 minutos |
| Host | URL de FastAPI |

## Tareas definidas

| Task | Peso | Descripción |
|------|------|-------------|
| `predict` | 80% | POST /predict con datos de propiedad aleatorios |
| `health_check` | 20% | GET /health |

## Evidencia esperada en Grafana

Durante la prueba de carga se debe observar en el dashboard de Grafana:
- Aumento en la tasa de peticiones
- Variación en la latencia p50 y p95
- Posibles errores si el sistema llega a su límite de recursos
