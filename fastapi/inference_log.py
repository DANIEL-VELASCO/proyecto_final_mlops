"""Registro de inferencias en RAW_DATA (RF8).

P1 define el DDL final de la tabla. Mientras tanto, P2 escribe en una tabla con
el nombre configurable por env var INFERENCE_EVENTS_TABLE (default:
raw_data.inference_events) usando un esquema mínimo que cubre el RF8:

    request_id      UUID PRIMARY KEY
    occurred_at     TIMESTAMPTZ NOT NULL
    model_name      TEXT NOT NULL
    model_version   TEXT NOT NULL
    model_alias     TEXT NOT NULL
    input_payload   JSONB NOT NULL
    prediction      DOUBLE PRECISION
    status          TEXT NOT NULL  -- 'ok' | 'error'
    error_message   TEXT
    latency_ms      INTEGER

La tabla se crea con IF NOT EXISTS al startup (no es destructivo).
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("p2.fastapi.inference_log")

INFERENCE_EVENTS_TABLE = os.getenv("INFERENCE_EVENTS_TABLE", "raw_data.inference_events")

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {INFERENCE_EVENTS_TABLE} (
    request_id      UUID PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model_name      TEXT NOT NULL,
    model_version   TEXT NOT NULL,
    model_alias     TEXT NOT NULL,
    input_payload   JSONB NOT NULL,
    prediction      DOUBLE PRECISION,
    status          TEXT NOT NULL,
    error_message   TEXT,
    latency_ms      INTEGER
);
"""

INSERT_SQL = f"""
INSERT INTO {INFERENCE_EVENTS_TABLE}
    (request_id, occurred_at, model_name, model_version, model_alias,
     input_payload, prediction, status, error_message, latency_ms)
VALUES
    (:request_id, :occurred_at, :model_name, :model_version, :model_alias,
     CAST(:input_payload AS JSONB), :prediction, :status, :error_message, :latency_ms);
"""


class InferenceLogger:
    def __init__(self, database_uri: str) -> None:
        self.engine: Engine = create_engine(database_uri, pool_pre_ping=True, pool_size=5)

    def ensure_table(self) -> None:
        """Crea la tabla si P1 aún no la entregó (idempotente).

        Si P1 ya creó la tabla con su DDL definitivo, este IF NOT EXISTS es no-op.
        Si P1 cambia el nombre de columnas, hay que avisar a P2 para ajustar.
        """
        try:
            with self.engine.begin() as conn:
                conn.execute(text(CREATE_TABLE_SQL))
            logger.info("Tabla %s lista", INFERENCE_EVENTS_TABLE)
        except Exception as exc:
            logger.warning(
                "No se pudo crear/verificar tabla %s: %s — se asume que P1 ya la creó",
                INFERENCE_EVENTS_TABLE,
                exc,
            )

    def log_inference(
        self,
        request_id: str,
        model_name: str,
        model_version: str,
        model_alias: str,
        input_payload: dict,
        prediction: Optional[float],
        status: str,
        error_message: Optional[str],
        latency_ms: int,
    ) -> None:
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(INSERT_SQL),
                    {
                        "request_id": request_id,
                        "occurred_at": datetime.now(timezone.utc),
                        "model_name": model_name,
                        "model_version": model_version,
                        "model_alias": model_alias,
                        "input_payload": json.dumps(input_payload, default=str),
                        "prediction": prediction,
                        "status": status,
                        "error_message": error_message,
                        "latency_ms": latency_ms,
                    },
                )
        except Exception as exc:
            logger.error("Error registrando inferencia %s: %s", request_id, exc)


def new_request_id() -> str:
    return str(uuid.uuid4())
