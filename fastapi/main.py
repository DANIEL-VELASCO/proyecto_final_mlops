"""FastAPI — servicio de inferencia (P2).

Endpoints:
- GET  /health        — readiness/liveness; reporta si el modelo está cargado
- POST /predict       — predice precio y registra la inferencia en RAW_DATA
- GET  /metrics       — expone métricas Prometheus (exactamente las que consume Grafana)
- POST /reload-model  — fuerza recarga desde MLflow (protegido por header X-Reload-Token)

Métricas custom expuestas (además de las automáticas de prometheus_fastapi_instrumentator):
- model_version_info{version,alias}  — gauge 1 con la versión productiva cargada
- model_load_total{result}           — counter de cargas exitosas/fallidas
- inference_log_failures_total       — counter de fallos al persistir en RAW_DATA

Configuración (env vars):
    MLFLOW_TRACKING_URI           (requerido)
    DATABASE_URI                  (requerido)
    MLFLOW_MODEL_NAME             default: house-price-model
    MLFLOW_PRODUCTION_ALIAS       default: production
    MODEL_POLL_INTERVAL_SEC       default: 30
    RELOAD_TOKEN                  default: "" (si vacío, /reload-model rechaza siempre)
    INFERENCE_EVENTS_TABLE        default: raw_data.inference_events
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge
from prometheus_fastapi_instrumentator import Instrumentator

from inference_log import InferenceLogger, new_request_id
from model_loader import ModelLoader, build_default_loader
from preprocess import prepare_inference_frame
from schemas import (
    HealthResponse,
    PredictionResponse,
    PropertyRequest,
    ReloadRequest,
    ReloadResponse,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("p2.fastapi")

RELOAD_TOKEN = os.getenv("RELOAD_TOKEN", "")

MODEL_VERSION_INFO = Gauge(
    "model_version_info",
    "Versión del modelo productivo cargado (always=1; la info viaja en labels).",
    labelnames=("version", "alias", "model_name"),
)
MODEL_LOAD_TOTAL = Counter(
    "model_load_total",
    "Cantidad de cargas de modelo intentadas, etiquetadas por resultado.",
    labelnames=("result",),
)
INFERENCE_LOG_FAILURES = Counter(
    "inference_log_failures_total",
    "Cantidad de inferencias que no pudieron registrarse en RAW_DATA.",
)


def _update_model_version_gauge(loader: ModelLoader) -> None:
    snap = loader.current()
    MODEL_VERSION_INFO.clear()
    if snap is not None:
        MODEL_VERSION_INFO.labels(
            version=str(snap.version), alias=snap.alias, model_name=loader.model_name
        ).set(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    loader = build_default_loader()
    app.state.loader = loader

    inference_logger = InferenceLogger(os.environ["DATABASE_URI"])
    inference_logger.ensure_table()
    app.state.inference_logger = inference_logger

    try:
        loaded = loader.load()
        if loaded is not None:
            MODEL_LOAD_TOTAL.labels(result="ok").inc()
        else:
            MODEL_LOAD_TOTAL.labels(result="no_alias_yet").inc()
    except Exception as exc:
        logger.error("Carga inicial del modelo falló: %s", exc)
        MODEL_LOAD_TOTAL.labels(result="error").inc()

    _update_model_version_gauge(loader)
    loader.start_background_poller()

    yield

    loader.stop_background_poller()


app = FastAPI(
    title="MLOps — House Price Inference API",
    description="P2 (ML Engineer) — Inferencia con modelo productivo cargado desde MLflow.",
    version="1.0.0",
    lifespan=lifespan,
)


Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/metrics", "/health"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


def get_loader(request: Request) -> ModelLoader:
    return request.app.state.loader


def get_inference_logger(request: Request) -> InferenceLogger:
    return request.app.state.inference_logger


@app.get("/health", response_model=HealthResponse)
async def health(loader: ModelLoader = Depends(get_loader)) -> HealthResponse:
    snap = loader.current()
    return HealthResponse(
        status="ok",
        model_loaded=snap is not None,
        model_version=str(snap.version) if snap else None,
        model_alias=snap.alias if snap else None,
    )


@app.post("/predict", response_model=PredictionResponse)
async def predict(
    payload: PropertyRequest,
    loader: ModelLoader = Depends(get_loader),
    inf_log: InferenceLogger = Depends(get_inference_logger),
) -> PredictionResponse:
    request_id = new_request_id()
    started = time.perf_counter()
    payload_dict = payload.to_model_payload()
    snap = loader.current()

    if snap is None:
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            inf_log.log_inference(
                request_id=request_id,
                model_name=loader.model_name,
                model_version="none",
                model_alias=loader.alias,
                input_payload=payload_dict,
                prediction=None,
                status="error",
                error_message="model_not_loaded",
                latency_ms=latency_ms,
            )
        except Exception:
            INFERENCE_LOG_FAILURES.inc()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Modelo productivo no disponible. Espera a que el primer modelo se promueva.",
        )

    try:
        X = prepare_inference_frame(payload_dict)
        price, used_snap = loader.predict(X)
        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            inf_log.log_inference(
                request_id=request_id,
                model_name=loader.model_name,
                model_version=str(used_snap.version),
                model_alias=used_snap.alias,
                input_payload=payload_dict,
                prediction=price,
                status="ok",
                error_message=None,
                latency_ms=latency_ms,
            )
        except Exception:
            INFERENCE_LOG_FAILURES.inc()

        return PredictionResponse(
            price=price,
            model_version=str(used_snap.version),
            model_alias=used_snap.alias,
            inference_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.exception("Error en /predict")
        try:
            inf_log.log_inference(
                request_id=request_id,
                model_name=loader.model_name,
                model_version=str(snap.version),
                model_alias=snap.alias,
                input_payload=payload_dict,
                prediction=None,
                status="error",
                error_message=str(exc)[:480],
                latency_ms=latency_ms,
            )
        except Exception:
            INFERENCE_LOG_FAILURES.inc()
        raise HTTPException(status_code=500, detail="Error en inferencia")


@app.post("/reload-model", response_model=ReloadResponse)
async def reload_model(
    body: ReloadRequest,
    x_reload_token: str | None = Header(default=None, alias="X-Reload-Token"),
    loader: ModelLoader = Depends(get_loader),
) -> ReloadResponse:
    if not RELOAD_TOKEN or x_reload_token != RELOAD_TOKEN:
        raise HTTPException(status_code=401, detail="Token inválido")

    prev = loader.current()
    prev_version = str(prev.version) if prev else None

    new = loader.load()
    if new is None:
        MODEL_LOAD_TOTAL.labels(result="no_alias_yet").inc()
        return ReloadResponse(
            reloaded=False,
            previous_version=prev_version,
            current_version=None,
            message="No hay alias productivo en MLflow",
        )

    if prev is not None and new.version == prev.version and not body.force:
        return ReloadResponse(
            reloaded=False,
            previous_version=prev_version,
            current_version=str(new.version),
            message="Versión sin cambios (usa force=true para forzar recarga)",
        )

    MODEL_LOAD_TOTAL.labels(result="ok").inc()
    _update_model_version_gauge(loader)
    return ReloadResponse(
        reloaded=True,
        previous_version=prev_version,
        current_version=str(new.version),
        message="Modelo recargado correctamente",
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Error no controlado: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "internal error"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
