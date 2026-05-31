# Proyecto Final MLOps 2026-1

**Nivel 4: Automatización, decisión de reentrenamiento y despliegue GitOps**  
Pontificia Universidad Javeriana — Mayo 2026

## Descripción

Sistema MLOps completo para estimación de precios de propiedades inmobiliarias. Integra recolección incremental de datos, validación, decisión automática de reentrenamiento, registro en MLflow, inferencia via FastAPI, interfaz en Streamlit, despliegue en Kubernetes con GitOps (Argo CD) y observabilidad con Prometheus y Grafana.

## Arquitectura

```
API Externa (datos) → Airflow DAG → RAW_DATA / CLEAN_DATA
                                  → MLflow (experimentos + modelos)
                                  → FastAPI (inferencia)
                                  → Streamlit (UI)
Prometheus + Grafana ← FastAPI /metrics
GitHub Actions → DockerHub → Kubernetes ← Argo CD (GitOps)
```

## Estructura del repositorio

```
.
├── .github/workflows/     # CI/CD — GitHub Actions (P3)
├── airflow/               # DAGs y orquestación (P1)
├── training/              # Pipeline de entrenamiento (P2)
├── fastapi/               # API de inferencia (P2)
├── streamlit/             # Interfaz de usuario (P3)
├── locust/                # Pruebas de carga (P3)
├── kubernetes/            # Manifiestos K8s (P3 — revisión global)
│   ├── airflow/
│   ├── mlflow/
│   ├── minio/
│   ├── fastapi/
│   ├── streamlit/
│   ├── databases/
│   ├── prometheus/
│   ├── grafana/
│   └── argocd/
├── docker-compose.yml     # Entorno de desarrollo local
└── README.md
```

## Equipo

| Persona | Rol |
|---------|-----|
| Persona 1 | Data Engineer — Pipeline de datos, validaciones y DAG Airflow |
| Persona 2 | ML Engineer — Entrenamiento, MLflow y FastAPI |
| Persona 3 | DevOps/MLOps Engineer — CI/CD, Kubernetes, Argo CD, Observabilidad y Streamlit |

## Estrategia de ramas

- `main` — producción estable (solo via PR desde `develop`)
- `develop` — integración (solo via PR desde `feature branches`)
- `feature/p1-*` — Persona 1
- `feature/p2-*` — Persona 2
- `feature/p3-*` — Persona 3
- `hotfix/*` — correcciones urgentes

## Requisitos previos

- Docker y Docker Compose
- Kubernetes (minikube o clúster del curso)
- kubectl y Helm
- Argo CD instalado en el clúster
- Cuenta DockerHub con secretos `DOCKERHUB_USERNAME` y `DOCKERHUB_TOKEN` en GitHub

## Levantar entorno de desarrollo local

```bash
docker compose up -d
```

## Documentación técnica

Ver sección de cada componente en sus respectivos directorios.
