"""
DAG principal — Proyecto Final MLOps 2026-1
Persona 1 (Data Engineer): tareas 1–10 implementadas.
Tareas 11–18: invocan imagen Docker de Persona 2 via subprocess.
"""
import hashlib
import json
import logging
import os
import subprocess
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import create_engine, text

from airflow import DAG
from airflow.exceptions import AirflowSkipException
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.utils.trigger_rule import TriggerRule

log = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────
DATABASE_URI   = os.getenv("DATABASE_URI",
                    "postgresql+psycopg2://mlops:mlops@postgres:5432/mlops")
GROUP_ID       = int(os.getenv("DATA_API_GROUP_ID",          "1"))
MIN_RECORDS    = int(os.getenv("MIN_RECORDS_TO_TRAIN",        "100"))
VOLUME_PCT     = float(os.getenv("VOLUME_INCREASE_PCT",       "0.10"))
DRIFT_PVALUE   = float(os.getenv("DRIFT_PVALUE_THRESHOLD",    "0.05"))
NEW_CAT_FREQ   = float(os.getenv("NEW_CATEGORY_FREQ_THRESHOLD","0.05"))

MLFLOW_URI     = os.getenv("MLFLOW_TRACKING_URI",  "http://mlflow:5000")
MLFLOW_S3      = os.getenv("MLFLOW_S3_ENDPOINT_URL","http://minio:9000")
AWS_KEY        = os.getenv("AWS_ACCESS_KEY_ID",    "minioadmin")
AWS_SECRET     = os.getenv("AWS_SECRET_ACCESS_KEY","minioadmin")
TRAINING_IMAGE = os.getenv("TRAINING_IMAGE",       "danielvelasco01/mlops-training:latest")


def _engine():
    return create_engine(DATABASE_URI, pool_pre_ping=True)


def _decode_payload(raw):
    """psycopg2 deserializa JSONB en list/dict; el JSON viejo (text) llega como str.

    Esta funcion absorbe ambos casos para que el resto del DAG no tenga que pensar
    en el tipo de columna.
    """
    if isinstance(raw, (str, bytes, bytearray)):
        return json.loads(raw)
    return raw


def _next_batch_number(engine) -> int:
    with engine.connect() as conn:
        last = conn.execute(
            text("SELECT COALESCE(MAX(batch_number), -1) FROM raw_data.raw_batches WHERE group_id = :g"),
            {"g": GROUP_ID},
        ).scalar()
    return last + 1


def _load_known_categories(engine) -> dict[str, set]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT feature, value FROM raw_data.category_catalog")
        ).fetchall()
    catalog: dict[str, set] = {}
    for r in rows:
        catalog.setdefault(r.feature, set()).add(r.value)
    return catalog


def _upsert_categories(engine, new_cats: dict) -> None:
    if not new_cats:
        return
    with engine.begin() as conn:
        for feat, entries in new_cats.items():
            for e in entries:
                conn.execute(
                    text("""
                        INSERT INTO raw_data.category_catalog (feature, value)
                        VALUES (:f, :v)
                        ON CONFLICT (feature, value) DO UPDATE SET last_seen = NOW()
                    """),
                    {"f": feat, "v": e["value"]},
                )


def _run_training_cmd(cmd_args: list[str]) -> dict:
    """Ejecuta un subcomando de la imagen de entrenamiento de P2 y parsea la salida JSON."""
    env = {
        **os.environ,
        "MLFLOW_TRACKING_URI":  MLFLOW_URI,
        "DATABASE_URI":         DATABASE_URI,
        "MLFLOW_S3_ENDPOINT_URL": MLFLOW_S3,
        "AWS_ACCESS_KEY_ID":    AWS_KEY,
        "AWS_SECRET_ACCESS_KEY": AWS_SECRET,
    }
    docker_cmd = [
        "docker", "run", "--rm", "--network", "host",
        "-e", f"MLFLOW_TRACKING_URI={MLFLOW_URI}",
        "-e", f"DATABASE_URI={DATABASE_URI}",
        "-e", f"MLFLOW_S3_ENDPOINT_URL={MLFLOW_S3}",
        "-e", f"AWS_ACCESS_KEY_ID={AWS_KEY}",
        "-e", f"AWS_SECRET_ACCESS_KEY={AWS_SECRET}",
        TRAINING_IMAGE,
    ] + cmd_args

    log.info("Ejecutando: %s", " ".join(docker_cmd))
    result = subprocess.run(docker_cmd, capture_output=True, text=True)

    if result.returncode != 0:
        log.error("Stderr: %s", result.stderr)
        raise RuntimeError(
            f"Comando de training falló (exit {result.returncode}): {result.stderr[-500:]}"
        )

    # La última línea del stdout debe ser JSON parseable
    last_line = result.stdout.strip().split("\n")[-1]
    try:
        return json.loads(last_line)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"No se pudo parsear la salida JSON del training. "
            f"Última línea: {last_line!r}. Error: {e}"
        )


# ── Tareas 1-10 (Persona 1) ───────────────────────────────────

def fetch_batch_from_api(**context):
    from api_client import fetch_batch, check_health

    engine = _engine()
    next_batch = _next_batch_number(engine)
    log.info("Solicitando lote %d al grupo %d", next_batch, GROUP_ID)

    if not check_health():
        raise RuntimeError(
            "API de datos no disponible. Verifica DATA_API_HOST y DATA_API_PORT."
        )

    data = fetch_batch(batch_number=next_batch, group_id=GROUP_ID)
    if data is None:
        raise AirflowSkipException("Sin datos nuevos: la API no retornó más lotes.")

    log.info("Lote %s: %d registros", data["batch_id"], data["n_records"])
    context["ti"].xcom_push(key="batch_data", value=data)


def store_raw_batch(**context):
    ti   = context["ti"]
    data = ti.xcom_pull(task_ids="fetch_batch_from_api", key="batch_data")
    if not data:
        raise ValueError("Sin datos desde fetch_batch_from_api")

    records      = data["records"]
    batch_id     = data["batch_id"]
    batch_number = data["batch_number"]

    schema_hash = hashlib.md5(
        json.dumps(sorted(records[0].keys()) if records else [], sort_keys=True).encode()
    ).hexdigest()

    row_hashes = [
        hashlib.md5(json.dumps(r, sort_keys=True, default=str).encode()).hexdigest()
        for r in records
    ]

    engine = _engine()
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT id FROM raw_data.raw_batches WHERE batch_id = :bid"),
            {"bid": batch_id},
        ).fetchone()

        if not existing:
            conn.execute(
                text("""
                    INSERT INTO raw_data.raw_batches
                        (batch_id, group_id, batch_number, n_records, schema_hash, raw_payload)
                    VALUES (:bid, :gid, :bn, :nr, :sh, :rp)
                """),
                {
                    "bid": batch_id, "gid": GROUP_ID, "bn": batch_number,
                    "nr": len(records), "sh": schema_hash,
                    "rp": json.dumps(records),
                },
            )
        else:
            log.warning("Lote %s ya existe — omitiendo inserción", batch_id)

        # Insertar hashes nuevos para deduplicacion (UPSERT bulk para no abortar
        # la txn al primer duplicado).
        hash_payload = [{"bid": batch_id, "rh": rh} for rh in row_hashes]
        chunk_size = 1000
        new_count = 0
        for i in range(0, len(hash_payload), chunk_size):
            chunk = hash_payload[i:i + chunk_size]
            result = conn.execute(
                text("INSERT INTO raw_data.row_hashes (batch_id, row_hash) VALUES (:bid, :rh) ON CONFLICT (row_hash) DO NOTHING"),
                chunk,
            )
            if result.rowcount and result.rowcount > 0:
                new_count += result.rowcount
            else:
                new_count += len(chunk)

    log.info("Almacenados %d/%d registros nuevos únicos", new_count, len(records))
    ti.xcom_push(key="batch_id",    value=batch_id)
    ti.xcom_push(key="n_records",   value=len(records))
    ti.xcom_push(key="new_records", value=new_count)
    ti.xcom_push(key="row_hashes",  value=row_hashes)


def validate_schema(**context):
    from preprocessing import validate_schema as _vs

    ti       = context["ti"]
    batch_id = ti.xcom_pull(task_ids="store_raw_batch", key="batch_id")
    engine   = _engine()

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT raw_payload FROM raw_data.raw_batches WHERE batch_id = :bid"),
            {"bid": batch_id},
        ).fetchone()

    df     = pd.DataFrame(_decode_payload(row.raw_payload))
    result = _vs(df)
    log.info("Esquema — válido: %s | faltantes: %s", result["valid"], result["missing"])

    new_status = "schema_validated" if result["valid"] else "schema_error"
    err_msg    = None if result["valid"] else f"Columnas faltantes: {result['missing']}"

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE raw_data.raw_batches SET status=:s, error_message=:e WHERE batch_id=:bid"),
            {"s": new_status, "e": err_msg, "bid": batch_id},
        )

    if not result["valid"]:
        raise ValueError(f"Esquema inválido para {batch_id}: columnas faltantes {result['missing']}")


def validate_data_quality(**context):
    from preprocessing import validate_quality

    ti       = context["ti"]
    batch_id = ti.xcom_pull(task_ids="store_raw_batch", key="batch_id")
    engine   = _engine()

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT raw_payload FROM raw_data.raw_batches WHERE batch_id=:bid"),
            {"bid": batch_id},
        ).fetchone()

    df     = pd.DataFrame(_decode_payload(row.raw_payload))
    result = validate_quality(df)
    log.info("Calidad — válido: %s | nulos: %.1f%% | duplicados: %.1f%%",
             result["valid"], result["null_pct_max"]*100, result["duplicate_pct"]*100)

    new_status = "quality_validated" if result["valid"] else "quality_error"
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE raw_data.raw_batches SET status=:s WHERE batch_id=:bid"),
            {"s": new_status, "bid": batch_id},
        )

    if not result["valid"]:
        raise ValueError(
            f"Calidad fallida para {batch_id}: "
            f"nulos_max={result['null_pct_max']:.1%}, "
            f"precios_invalidos={result['invalid_price_count']}"
        )

    context["ti"].xcom_push(key="quality_result", value=result)


def detect_new_categories(**context):
    from preprocessing import detect_new_categories as _dnc

    ti       = context["ti"]
    batch_id = ti.xcom_pull(task_ids="store_raw_batch", key="batch_id")
    engine   = _engine()

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT raw_payload FROM raw_data.raw_batches WHERE batch_id=:bid"),
            {"bid": batch_id},
        ).fetchone()

    df     = pd.DataFrame(_decode_payload(row.raw_payload))
    known  = _load_known_categories(engine)
    findings = _dnc(df, known)

    significant = {
        f: cats for f, cats in findings.items()
        if any(c["frequency"] >= NEW_CAT_FREQ for c in cats)
    }

    log.info("Nuevas categorías: %s | Significativas: %s",
             list(findings.keys()), list(significant.keys()))

    ti.xcom_push(key="new_categories",             value=findings)
    ti.xcom_push(key="significant_new_categories", value=significant)


def detect_data_drift(**context):
    from preprocessing import detect_drift

    ti       = context["ti"]
    batch_id = ti.xcom_pull(task_ids="store_raw_batch", key="batch_id")
    engine   = _engine()

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT raw_payload FROM raw_data.raw_batches WHERE batch_id=:bid"),
            {"bid": batch_id},
        ).fetchone()

    df_new = pd.DataFrame(_decode_payload(row.raw_payload))
    df_ref = pd.read_sql(
        "SELECT bed, bath, acre_lot, house_size, price FROM clean_data.properties "
        "WHERE batch_id != %(bid)s LIMIT 50000",
        engine, params={"bid": batch_id},
    )

    if len(df_ref) < 30:
        log.info("Histórico insuficiente para drift (%d registros)", len(df_ref))
        ti.xcom_push(key="drift_results",   value={})
        ti.xcom_push(key="drift_detected",  value=False)
        ti.xcom_push(key="drift_variables", value=[])
        return

    drift_results  = detect_drift(df_new, df_ref)
    drifted_vars   = [f for f, r in drift_results.items() if r["drift"]]
    drift_detected = len(drifted_vars) > 0

    log.info("Drift: %s — variables: %s", drift_detected, drifted_vars)
    ti.xcom_push(key="drift_results",   value=drift_results)
    ti.xcom_push(key="drift_detected",  value=drift_detected)
    ti.xcom_push(key="drift_variables", value=drifted_vars)


def preprocess_data(**context):
    from preprocessing import clean_batch, compute_row_hash

    ti       = context["ti"]
    batch_id = ti.xcom_pull(task_ids="store_raw_batch", key="batch_id")
    engine   = _engine()

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT raw_payload FROM raw_data.raw_batches WHERE batch_id=:bid"),
            {"bid": batch_id},
        ).fetchone()

    records  = _decode_payload(row.raw_payload)
    df_raw   = pd.DataFrame(records)
    df_clean = clean_batch(df_raw)

    # Filtrar filas sin target (no entrenan ni evaluan)
    df_clean = df_clean.dropna(subset=["price"])
    df_clean = df_clean[df_clean["price"].astype(float) > 0]

    inserted = 0
    # Cada INSERT en su propia transaccion via UPSERT (ON CONFLICT DO NOTHING).
    # Sin esto, una sola fila duplicada o invalida aborta toda la transaccion y
    # las filas siguientes no se insertan ("current transaction is aborted").
    insert_sql = text("""
        INSERT INTO clean_data.properties
            (batch_id, row_hash,
             brokered_by, status, price, bed, bath,
             acre_lot, street, city, state, zip_code,
             house_size, prev_sold_date)
        VALUES
            (:batch_id, :row_hash,
             :brokered_by, :status, :price, :bed, :bath,
             :acre_lot, :street, :city, :state, :zip_code,
             :house_size, :prev_sold_date)
        ON CONFLICT (row_hash) DO NOTHING
    """)
    rows_payload = []
    for _, rec in df_clean.iterrows():
        rec_dict  = rec.to_dict()
        row_hash  = compute_row_hash({k: str(v) for k, v in rec_dict.items()})
        rows_payload.append({
            "batch_id":      batch_id,
            "row_hash":      row_hash,
            "brokered_by":   rec_dict.get("brokered_by"),
            "status":        rec_dict.get("status"),
            "price":         rec_dict.get("price"),
            "bed":           rec_dict.get("bed"),
            "bath":          rec_dict.get("bath"),
            "acre_lot":      rec_dict.get("acre_lot"),
            "street":        rec_dict.get("street"),
            "city":          rec_dict.get("city"),
            "state":         rec_dict.get("state"),
            "zip_code":      rec_dict.get("zip_code"),
            "house_size":    rec_dict.get("house_size"),
            "prev_sold_date": rec_dict.get("prev_sold_date"),
        })

    # Insert por chunks para no llenar memoria con 90K dicts a la vez.
    chunk_size = 1000
    with engine.begin() as conn:
        for i in range(0, len(rows_payload), chunk_size):
            chunk = rows_payload[i:i + chunk_size]
            result = conn.execute(insert_sql, chunk)
            inserted += result.rowcount if result.rowcount and result.rowcount > 0 else len(chunk)

        conn.execute(
            text("UPDATE raw_data.raw_batches SET status='preprocessed' WHERE batch_id=:bid"),
            {"bid": batch_id},
        )

    # Actualizar catálogo de categorías con lo nuevo
    known    = _load_known_categories(engine)
    from preprocessing import detect_new_categories as _dnc
    new_cats = _dnc(df_clean, known)
    _upsert_categories(engine, new_cats)

    log.info("Insertados %d registros en clean_data.properties", inserted)
    ti.xcom_push(key="clean_count", value=inserted)


def decide_training(**context) -> str:
    ti         = context["ti"]
    batch_id   = ti.xcom_pull(task_ids="store_raw_batch",       key="batch_id")
    n_records  = ti.xcom_pull(task_ids="store_raw_batch",       key="n_records") or 0
    new_recs   = ti.xcom_pull(task_ids="store_raw_batch",       key="new_records") or 0
    drift      = ti.xcom_pull(task_ids="detect_data_drift",     key="drift_detected") or False
    drift_vars = ti.xcom_pull(task_ids="detect_data_drift",     key="drift_variables") or []
    sig_cats   = ti.xcom_pull(task_ids="detect_new_categories", key="significant_new_categories") or {}

    engine = _engine()
    with engine.connect() as conn:
        total_clean = conn.execute(
            text("SELECT COUNT(*) FROM clean_data.properties WHERE batch_id != :bid"),
            {"bid": batch_id},
        ).scalar() or 0

        first_run = conn.execute(
            text("SELECT COUNT(*) FROM raw_data.training_audit "
                 "WHERE decision='train' AND promoted=TRUE"),
        ).scalar() == 0

    volume_pct = new_recs / max(total_clean, 1)
    decision   = "skip_training"
    reason     = None

    if n_records < MIN_RECORDS:
        reason = f"Lote demasiado pequeño: {n_records} registros (mínimo: {MIN_RECORDS})"
    elif first_run:
        reason   = "Primera ejecución — no existe modelo productivo. Entrenamiento obligatorio."
        decision = "train_candidate_model"
    elif drift:
        reason   = f"Drift estadístico detectado en: {drift_vars}"
        decision = "train_candidate_model"
    elif sig_cats:
        cats_str = ", ".join(f"{k}: {len(v)} nuevas" for k, v in sig_cats.items())
        reason   = f"Nuevas categorías significativas: {cats_str}"
        decision = "train_candidate_model"
    elif volume_pct >= VOLUME_PCT:
        reason   = f"Volumen creció {volume_pct:.1%} (umbral: {VOLUME_PCT:.1%})"
        decision = "train_candidate_model"
    else:
        reason = (
            f"Sin criterio de reentrenamiento: "
            f"drift={drift}, nuevas_cats={bool(sig_cats)}, "
            f"vol={volume_pct:.1%}, n={n_records}"
        )

    log.info("Decisión: %s — %s", decision, reason)
    ti.xcom_push(key="train_decision", value=decision)
    ti.xcom_push(key="train_reason",   value=reason)
    ti.xcom_push(key="volume_pct",     value=float(volume_pct))
    return decision


def skip_training(**context):
    ti         = context["ti"]
    batch_id   = ti.xcom_pull(task_ids="store_raw_batch",       key="batch_id")
    n_records  = ti.xcom_pull(task_ids="store_raw_batch",       key="n_records") or 0
    reason     = ti.xcom_pull(task_ids="decide_training",       key="train_reason") or "Sin razón"
    drift      = ti.xcom_pull(task_ids="detect_data_drift",     key="drift_detected") or False
    drift_vars = ti.xcom_pull(task_ids="detect_data_drift",     key="drift_variables") or []
    new_cats   = ti.xcom_pull(task_ids="detect_new_categories", key="new_categories") or {}
    volume_pct = ti.xcom_pull(task_ids="decide_training",       key="volume_pct") or 0.0
    q_result   = ti.xcom_pull(task_ids="validate_data_quality", key="quality_result") or {}

    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO raw_data.training_audit
                    (batch_id, n_records, decision, reason,
                     null_pct_max, duplicate_pct,
                     drift_detected, drift_variables, new_categories,
                     volume_pct, status)
                VALUES
                    (:batch_id, :n_records, 'skip', :reason,
                     :null_pct_max, :dup_pct,
                     :drift, :drift_vars, :new_cats,
                     :vol_pct, 'completed')
            """),
            {
                "batch_id":    batch_id,
                "n_records":   n_records,
                "reason":      reason,
                "null_pct_max": q_result.get("null_pct_max"),
                "dup_pct":     q_result.get("duplicate_pct"),
                "drift":       drift,
                "drift_vars":  json.dumps(drift_vars),
                "new_cats":    json.dumps(new_cats),
                "vol_pct":     volume_pct,
            },
        )
    log.info("Skip registrado en training_audit: %s", reason)


# ── Tareas 11-17 (Persona 2 — invocación vía imagen Docker) ──

def train_candidate_model(**context):
    """
    Tareas 11, 12 y 13 consolidadas: llama a `train` en la imagen de P2.
    Captura run_id, model_version y métricas del JSON de salida.

    Contrato (ver docs/contracts/p2-interfaces.md §1.1):
      Imagen: TRAINING_IMAGE
      Cmd:    train --batch-id <id> --training-reason <reason> --clean-table clean_data.properties
      Stdout: {"run_id":..., "model_name":..., "model_version":..., "metrics":{...}, ...}
    """
    ti         = context["ti"]
    batch_id   = ti.xcom_pull(task_ids="store_raw_batch",  key="batch_id")
    reason     = ti.xcom_pull(task_ids="decide_training",  key="train_reason")
    commit_sha = os.getenv("GIT_COMMIT_SHA", "unknown")

    output = _run_training_cmd([
        "train",
        "--batch-id",         batch_id,
        "--training-reason",  reason,
        "--commit-sha",       commit_sha,
        "--clean-table",      "clean_data.properties",
    ])

    log.info("Training completado — run_id: %s, version: %s",
             output.get("run_id"), output.get("model_version"))

    ti.xcom_push(key="mlflow_run_id",   value=output["run_id"])
    ti.xcom_push(key="model_version",   value=str(output["model_version"]))
    ti.xcom_push(key="model_name",      value=output.get("model_name", "house-price-model"))
    ti.xcom_push(key="training_output", value=output)


def evaluate_candidate_model(**context):
    """
    Tarea 14: llama a `evaluate` en la imagen de P2 para comparar candidato vs productivo.

    Contrato (ver docs/contracts/p2-interfaces.md §1.2):
      Cmd:    evaluate --candidate-version <v> --clean-table clean_data.properties
      Stdout: {"candidate_mae":..., "production_mae":..., "no_production_model":bool, ...}
    """
    ti              = context["ti"]
    batch_id        = ti.xcom_pull(task_ids="store_raw_batch",       key="batch_id")
    model_version   = ti.xcom_pull(task_ids="train_candidate_model", key="model_version")

    output = _run_training_cmd([
        "evaluate",
        "--candidate-version", str(model_version),
        "--batch-id-filter",   batch_id,
        "--clean-table",       "clean_data.properties",
    ])

    log.info("Evaluación completada: %s", output)
    ti.xcom_push(key="evaluation_output", value=output)


def decide_promotion(**context) -> str:
    """
    Tarea 15 (Branch): llama a `promote` en la imagen de P2 y ramifica.

    Contrato (ver docs/contracts/p2-interfaces.md §1.3):
      Cmd:    promote --candidate-version <v> --mae-improvement-pct 3.0 --rmse-tolerance-pct 1.0
      Stdout: {"promoted":bool, "reason":..., "candidate_version":..., ...}
    """
    ti             = context["ti"]
    model_version  = ti.xcom_pull(task_ids="train_candidate_model", key="model_version")
    eval_output    = ti.xcom_pull(task_ids="evaluate_candidate_model", key="evaluation_output")

    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(eval_output, f)
        eval_file = f.name

    output = _run_training_cmd([
        "promote",
        "--evaluation-json",      eval_file,
        "--candidate-version",    str(model_version),
        "--mae-improvement-pct",  "3.0",
        "--rmse-tolerance-pct",   "1.0",
    ])

    log.info("Promoción: %s — %s", output.get("promoted"), output.get("reason"))
    ti.xcom_push(key="promotion_output", value=output)

    return "promote_model" if output.get("promoted") else "reject_model"


def promote_model(**context):
    """Tarea 16: registra la promoción en training_audit."""
    ti          = context["ti"]
    batch_id    = ti.xcom_pull(task_ids="store_raw_batch",  key="batch_id")
    n_records   = ti.xcom_pull(task_ids="store_raw_batch",  key="n_records") or 0
    reason      = ti.xcom_pull(task_ids="decide_training",  key="train_reason")
    promo       = ti.xcom_pull(task_ids="decide_promotion", key="promotion_output") or {}
    train_out   = ti.xcom_pull(task_ids="train_candidate_model", key="training_output") or {}
    q_result    = ti.xcom_pull(task_ids="validate_data_quality", key="quality_result") or {}
    drift       = ti.xcom_pull(task_ids="detect_data_drift",     key="drift_detected") or False
    drift_vars  = ti.xcom_pull(task_ids="detect_data_drift",     key="drift_variables") or []
    new_cats    = ti.xcom_pull(task_ids="detect_new_categories", key="new_categories") or {}
    volume_pct  = ti.xcom_pull(task_ids="decide_training",       key="volume_pct") or 0.0

    candidate_m = promo.get("candidate_metrics", {})
    production_m = promo.get("production_metrics", {})

    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO raw_data.training_audit
                    (batch_id, n_records, decision, reason,
                     null_pct_max, duplicate_pct,
                     drift_detected, drift_variables, new_categories, volume_pct,
                     mlflow_run_id, model_version,
                     mae_candidate, mae_production,
                     rmse_candidate, rmse_production,
                     promoted, promotion_reason, status)
                VALUES
                    (:batch_id, :n_records, 'train', :reason,
                     :null_pct_max, :dup_pct,
                     :drift, :drift_vars, :new_cats, :vol_pct,
                     :run_id, :model_version,
                     :mae_c, :mae_p, :rmse_c, :rmse_p,
                     TRUE, :promo_reason, 'completed')
            """),
            {
                "batch_id":    batch_id, "n_records":   n_records,
                "reason":      reason,
                "null_pct_max": q_result.get("null_pct_max"),
                "dup_pct":     q_result.get("duplicate_pct"),
                "drift":       drift, "drift_vars": json.dumps(drift_vars),
                "new_cats":    json.dumps(new_cats), "vol_pct": volume_pct,
                "run_id":      train_out.get("run_id"),
                "model_version": str(promo.get("candidate_version", "")),
                "mae_c":  candidate_m.get("mae"), "mae_p":  production_m.get("mae"),
                "rmse_c": candidate_m.get("rmse"), "rmse_p": production_m.get("rmse"),
                "promo_reason": promo.get("reason", ""),
            },
        )
    log.info("Modelo promovido — versión %s", promo.get("candidate_version"))


def reject_model(**context):
    """Tarea 17: registra el rechazo en training_audit."""
    ti          = context["ti"]
    batch_id    = ti.xcom_pull(task_ids="store_raw_batch",  key="batch_id")
    n_records   = ti.xcom_pull(task_ids="store_raw_batch",  key="n_records") or 0
    reason      = ti.xcom_pull(task_ids="decide_training",  key="train_reason")
    promo       = ti.xcom_pull(task_ids="decide_promotion", key="promotion_output") or {}
    train_out   = ti.xcom_pull(task_ids="train_candidate_model", key="training_output") or {}
    q_result    = ti.xcom_pull(task_ids="validate_data_quality", key="quality_result") or {}
    drift       = ti.xcom_pull(task_ids="detect_data_drift",     key="drift_detected") or False
    drift_vars  = ti.xcom_pull(task_ids="detect_data_drift",     key="drift_variables") or []
    new_cats    = ti.xcom_pull(task_ids="detect_new_categories", key="new_categories") or {}
    volume_pct  = ti.xcom_pull(task_ids="decide_training",       key="volume_pct") or 0.0

    candidate_m  = promo.get("candidate_metrics", {})
    production_m = promo.get("production_metrics", {})

    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO raw_data.training_audit
                    (batch_id, n_records, decision, reason,
                     null_pct_max, duplicate_pct,
                     drift_detected, drift_variables, new_categories, volume_pct,
                     mlflow_run_id, model_version,
                     mae_candidate, mae_production,
                     rmse_candidate, rmse_production,
                     promoted, promotion_reason, status)
                VALUES
                    (:batch_id, :n_records, 'train', :reason,
                     :null_pct_max, :dup_pct,
                     :drift, :drift_vars, :new_cats, :vol_pct,
                     :run_id, :model_version,
                     :mae_c, :mae_p, :rmse_c, :rmse_p,
                     FALSE, :promo_reason, 'completed')
            """),
            {
                "batch_id":    batch_id, "n_records":   n_records,
                "reason":      reason,
                "null_pct_max": q_result.get("null_pct_max"),
                "dup_pct":     q_result.get("duplicate_pct"),
                "drift":       drift, "drift_vars": json.dumps(drift_vars),
                "new_cats":    json.dumps(new_cats), "vol_pct": volume_pct,
                "run_id":      train_out.get("run_id"),
                "model_version": str(promo.get("candidate_version", "")),
                "mae_c":  candidate_m.get("mae"), "mae_p":  production_m.get("mae"),
                "rmse_c": candidate_m.get("rmse"), "rmse_p": production_m.get("rmse"),
                "promo_reason": promo.get("reason", ""),
            },
        )
    log.info("Modelo rechazado — razón: %s", promo.get("reason"))


def notify_or_log_result(**context):
    """Tarea 18: log final del estado del pipeline."""
    ti       = context["ti"]
    batch_id = ti.xcom_pull(task_ids="store_raw_batch",  key="batch_id")
    decision = ti.xcom_pull(task_ids="decide_training",  key="train_decision")
    log.info("Pipeline completado para lote %s. Decisión: %s", batch_id, decision)


# ── DAG ───────────────────────────────────────────────────────
default_args = {
    "owner":            "persona1",
    "depends_on_past":  False,
    "retries":          1,
    "retry_delay":      timedelta(minutes=5),
    "email_on_failure": False,
}

with DAG(
    dag_id="real_estate_mlops_pipeline",
    description="Pipeline MLOps — estimación de precios inmobiliarios",
    default_args=default_args,
    start_date=datetime(2026, 1, 1),
    schedule_interval="@daily",
    catchup=False,
    max_active_runs=1,
    tags=["mlops", "real-estate", "proyecto-final"],
) as dag:

    t01 = EmptyOperator(task_id="start")

    t02 = PythonOperator(task_id="fetch_batch_from_api",  python_callable=fetch_batch_from_api)
    t03 = PythonOperator(task_id="store_raw_batch",       python_callable=store_raw_batch)
    t04 = PythonOperator(task_id="validate_schema",       python_callable=validate_schema)
    t05 = PythonOperator(task_id="validate_data_quality", python_callable=validate_data_quality)
    t06 = PythonOperator(task_id="detect_new_categories", python_callable=detect_new_categories)
    t07 = PythonOperator(task_id="detect_data_drift",     python_callable=detect_data_drift)
    t08 = PythonOperator(task_id="preprocess_data",       python_callable=preprocess_data)

    t09 = BranchPythonOperator(task_id="decide_training", python_callable=decide_training)
    t10 = PythonOperator(task_id="skip_training",         python_callable=skip_training)

    t11 = PythonOperator(task_id="train_candidate_model",    python_callable=train_candidate_model)
    t12 = PythonOperator(task_id="evaluate_candidate_model", python_callable=evaluate_candidate_model)

    t13 = BranchPythonOperator(task_id="decide_promotion",   python_callable=decide_promotion)
    t14 = PythonOperator(task_id="promote_model",            python_callable=promote_model)
    t15 = PythonOperator(task_id="reject_model",             python_callable=reject_model)

    t16 = PythonOperator(
        task_id="notify_or_log_result",
        python_callable=notify_or_log_result,
        trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS,
    )
    t17 = EmptyOperator(
        task_id="end",
        trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS,
    )

    # ── Dependencias ──────────────────────────────────────────
    t01 >> t02 >> t03 >> t04 >> t05 >> t06 >> t07 >> t08 >> t09

    t09 >> t10 >> t16                              # rama skip
    t09 >> t11 >> t12 >> t13                       # rama train
    t13 >> t14 >> t16                              # rama promote
    t13 >> t15 >> t16                              # rama reject

    t16 >> t17
