"""Evalúa candidato vs. productivo (tarea evaluate_candidate_model + compare_with_production del DAG).

Carga ambos modelos desde MLflow, los evalúa en el MISMO holdout (para que la
comparación sea justa) y emite un JSON con métricas por separado. La decisión de
promoción se toma en promote.py.

Invocación:

    python -m training.evaluate \\
        --candidate-version 3 \\
        --clean-table clean_data.properties \\
        --batch-id 2026-05-31-01

Salida (stdout): JSON con candidate_metrics, production_metrics y delta porcentuales.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

import mlflow
import mlflow.pyfunc
import pandas as pd
from sklearn.model_selection import train_test_split
from sqlalchemy import create_engine, text

try:
    from .preprocess import clean_dataframe, split_features_target
    from .train import compute_metrics
except ImportError:
    from preprocess import clean_dataframe, split_features_target  # type: ignore
    from train import compute_metrics  # type: ignore

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("p2.training.evaluate")

DEFAULT_MODEL_NAME = os.getenv("MLFLOW_MODEL_NAME", "house-price-model")
PRODUCTION_ALIAS = os.getenv("MLFLOW_PRODUCTION_ALIAS", "production")


def load_holdout(clean_table: str, batch_id_filter: str | None, test_size: float, random_state: int):
    """Reproduce el split de train.py para obtener el holdout (X_test, y_test)."""
    db_uri = os.environ["DATABASE_URI"]
    engine = create_engine(db_uri)
    if batch_id_filter:
        query = text(f"SELECT * FROM {clean_table} WHERE batch_id <= :b")
        with engine.connect() as conn:
            df = pd.read_sql(query, conn, params={"b": batch_id_filter})
    else:
        query = text(f"SELECT * FROM {clean_table}")
        with engine.connect() as conn:
            df = pd.read_sql(query, conn)
    df, _ = clean_dataframe(df)
    X, y = split_features_target(df)
    _, X_test, _, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state
    )
    return X_test, y_test


def load_model_by_version(model_name: str, version: str):
    uri = f"models:/{model_name}/{version}"
    logger.info("Cargando candidato: %s", uri)
    return mlflow.pyfunc.load_model(uri)


def load_production_model(model_name: str, alias: str):
    """Carga el modelo productivo por alias (estilo MLflow 2.x).

    Si no existe ningún modelo con ese alias todavía, devuelve None (primer ciclo del sistema).
    """
    client = mlflow.tracking.MlflowClient()
    try:
        mv = client.get_model_version_by_alias(model_name, alias)
    except Exception as exc:  # primera vez: aún no hay alias productivo
        logger.warning("Sin modelo productivo (alias '%s'): %s", alias, exc)
        return None, None
    uri = f"models:/{model_name}@{alias}"
    logger.info("Cargando productivo: %s (version=%s)", uri, mv.version)
    return mlflow.pyfunc.load_model(uri), mv.version


def evaluate(args: argparse.Namespace) -> dict:
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])

    X_test, y_test = load_holdout(
        args.clean_table, args.batch_id_filter, args.test_size, args.random_state
    )
    logger.info("Holdout: %d filas", len(X_test))

    candidate = load_model_by_version(args.model_name, args.candidate_version)
    candidate_pred = candidate.predict(X_test)
    candidate_metrics = compute_metrics(y_test.values, candidate_pred)

    production, production_version = load_production_model(args.model_name, args.production_alias)
    if production is None:
        return {
            "candidate_version": args.candidate_version,
            "candidate_metrics": candidate_metrics,
            "production_version": None,
            "production_metrics": None,
            "delta_pct": None,
            "no_production_model": True,
            "n_holdout": len(X_test),
        }

    production_pred = production.predict(X_test)
    production_metrics = compute_metrics(y_test.values, production_pred)

    def pct_change(new: float, old: float) -> float:
        if old == 0:
            return 0.0
        return (new - old) / old * 100.0

    delta_pct = {
        k: pct_change(candidate_metrics[k], production_metrics[k])
        for k in candidate_metrics
    }

    return {
        "candidate_version": args.candidate_version,
        "candidate_metrics": candidate_metrics,
        "production_version": production_version,
        "production_metrics": production_metrics,
        "delta_pct": delta_pct,
        "no_production_model": False,
        "n_holdout": len(X_test),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evalúa candidato vs. productivo")
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--production-alias", default=PRODUCTION_ALIAS)
    parser.add_argument(
        "--clean-table", default=os.getenv("CLEAN_TABLE", "clean_data.properties")
    )
    parser.add_argument("--batch-id-filter", default=None)
    parser.add_argument("--test-size", type=float, default=0.15)
    parser.add_argument("--random-state", type=int, default=42)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = evaluate(args)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
