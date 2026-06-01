-- ============================================================
-- Proyecto Final MLOps 2026-1 — DDL definitivo de Persona 1
-- Esquemas: raw_data, clean_data
-- ============================================================

\connect mlops;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── SCHEMA raw_data ─────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS raw_data;

-- Lotes crudos recibidos desde la API de datos
CREATE TABLE IF NOT EXISTS raw_data.raw_batches (
    id              BIGSERIAL PRIMARY KEY,
    batch_id        TEXT NOT NULL UNIQUE,
    group_id        INTEGER NOT NULL DEFAULT 1,
    batch_number    INTEGER NOT NULL,
    fetch_timestamp TIMESTAMPTZ DEFAULT NOW(),
    n_records       INTEGER NOT NULL DEFAULT 0,
    schema_hash     TEXT,
    raw_payload     JSONB NOT NULL,
    status          TEXT NOT NULL DEFAULT 'stored'
                        CHECK (status IN (
                            'stored', 'schema_validated', 'quality_validated',
                            'preprocessed', 'schema_error', 'quality_error', 'error'
                        )),
    error_message   TEXT,
    UNIQUE (group_id, batch_number)
);

CREATE INDEX IF NOT EXISTS idx_raw_batches_status       ON raw_data.raw_batches(status);
CREATE INDEX IF NOT EXISTS idx_raw_batches_batch_number ON raw_data.raw_batches(batch_number);

-- Hashes MD5 por fila para deduplicación entre lotes
CREATE TABLE IF NOT EXISTS raw_data.row_hashes (
    id         BIGSERIAL PRIMARY KEY,
    batch_id   TEXT NOT NULL REFERENCES raw_data.raw_batches(batch_id) ON DELETE CASCADE,
    row_hash   TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_row_hashes_hash ON raw_data.row_hashes(row_hash);

-- Catálogo de categorías conocidas (usado para detección de nuevas categorías)
CREATE TABLE IF NOT EXISTS raw_data.category_catalog (
    id         BIGSERIAL PRIMARY KEY,
    feature    TEXT NOT NULL,
    value      TEXT NOT NULL,
    first_seen TIMESTAMPTZ DEFAULT NOW(),
    last_seen  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (feature, value)
);

CREATE INDEX IF NOT EXISTS idx_catalog_feature ON raw_data.category_catalog(feature);

-- Registro de inferencias (esquema acordado con P2 — FastAPI lo escribe)
-- Ver docs/contracts/p2-interfaces.md §2
CREATE TABLE IF NOT EXISTS raw_data.inference_events (
    request_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model_name    TEXT NOT NULL,
    model_version TEXT NOT NULL,
    model_alias   TEXT NOT NULL,
    input_payload JSONB NOT NULL,
    prediction    DOUBLE PRECISION,
    status        TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    error_message TEXT,
    latency_ms    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_inference_events_ts ON raw_data.inference_events(occurred_at);

-- Auditoría del pipeline de entrenamiento (leída por Streamlit de P3)
-- Contrato de columnas acordado con P3: NO cambiar nombres sin avisar
CREATE TABLE IF NOT EXISTS raw_data.training_audit (
    id               BIGSERIAL PRIMARY KEY,
    batch_id         TEXT NOT NULL REFERENCES raw_data.raw_batches(batch_id),
    execution_date   TIMESTAMPTZ DEFAULT NOW(),
    n_records        INTEGER NOT NULL,
    decision         TEXT NOT NULL CHECK (decision IN ('train', 'skip')),
    reason           TEXT NOT NULL,
    -- Métricas de validación del lote
    null_pct_max     DOUBLE PRECISION,
    duplicate_pct    DOUBLE PRECISION,
    drift_detected   BOOLEAN DEFAULT FALSE,
    drift_variables  TEXT,
    new_categories   TEXT,
    volume_pct       DOUBLE PRECISION,
    -- Resultado de entrenamiento y promoción (P2 no actualiza: el DAG escribe todo al final)
    mlflow_run_id    TEXT,
    model_version    TEXT,
    mae_candidate    DOUBLE PRECISION,
    mae_production   DOUBLE PRECISION,
    rmse_candidate   DOUBLE PRECISION,
    rmse_production  DOUBLE PRECISION,
    promoted         BOOLEAN,
    promotion_reason TEXT,
    status           TEXT DEFAULT 'pending'
                         CHECK (status IN ('pending', 'training', 'completed', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_training_audit_batch_id ON raw_data.training_audit(batch_id);
CREATE INDEX IF NOT EXISTS idx_training_audit_decision ON raw_data.training_audit(decision);
CREATE INDEX IF NOT EXISTS idx_training_audit_date     ON raw_data.training_audit(execution_date);

-- ── SCHEMA clean_data ────────────────────────────────────────
-- Nota: P2 usa clean_data.properties en su imagen de training.
-- Las columnas deben mantenerse; avisar a P2 si se cambia algún nombre.

CREATE SCHEMA IF NOT EXISTS clean_data;

CREATE TABLE IF NOT EXISTS clean_data.properties (
    id             BIGSERIAL PRIMARY KEY,
    batch_id       TEXT NOT NULL REFERENCES raw_data.raw_batches(batch_id),
    row_hash       TEXT NOT NULL UNIQUE,
    processed_ts   TIMESTAMPTZ DEFAULT NOW(),
    brokered_by    TEXT,
    status         TEXT,
    price          DOUBLE PRECISION NOT NULL,
    bed            INTEGER,
    bath           INTEGER,
    acre_lot       DOUBLE PRECISION,
    street         TEXT,
    city           TEXT,
    state          TEXT,
    zip_code       INTEGER,
    house_size     INTEGER,
    prev_sold_date DATE
);

CREATE INDEX IF NOT EXISTS idx_clean_properties_batch ON clean_data.properties(batch_id);
CREATE INDEX IF NOT EXISTS idx_clean_properties_hash  ON clean_data.properties(row_hash);
CREATE INDEX IF NOT EXISTS idx_clean_properties_price ON clean_data.properties(price);
