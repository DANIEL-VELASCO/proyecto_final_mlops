-- Bootstrap mínimo para el smoke test de P2.
-- En la entrega real, P1 crea estas tablas con su DDL definitivo. Aquí usamos
-- IF NOT EXISTS para no destruir nada y para que el smoke pueda correr de cero.

\connect mlops;

CREATE SCHEMA IF NOT EXISTS raw_data;
CREATE SCHEMA IF NOT EXISTS clean_data;

CREATE TABLE IF NOT EXISTS clean_data.properties (
    id              BIGSERIAL PRIMARY KEY,
    batch_id        TEXT NOT NULL,
    brokered_by     TEXT,
    status          TEXT,
    price           DOUBLE PRECISION,
    bed             INTEGER,
    bath            INTEGER,
    acre_lot        DOUBLE PRECISION,
    street          TEXT,
    city            TEXT,
    state           TEXT,
    zip_code        INTEGER,
    house_size      INTEGER,
    prev_sold_date  DATE
);
CREATE INDEX IF NOT EXISTS ix_clean_properties_batch ON clean_data.properties(batch_id);

-- La tabla raw_data.inference_events se crea sola al levantar FastAPI
-- (ver fastapi/inference_log.py — CREATE TABLE IF NOT EXISTS).
