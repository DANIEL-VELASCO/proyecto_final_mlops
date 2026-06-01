"""Entrena un modelo candidato y lo registra en MLflow.

Invocación esperada desde Airflow (tareas train_candidate_model + register_candidate_in_mlflow):

    python -m training.train \\
        --batch-id 2026-05-31-01 \\
        --commit-sha $GITHUB_SHA \\
        --training-reason "drift detectado en house_size" \\
        --clean-table clean_data.properties

Salida (stdout): un JSON con la metadata del run para que el DAG la encadene a la
tarea de comparación. Ejemplo:

    {"run_id": "...", "model_uri": "models:/house-price-model/3",
     "model_name": "house-price-model", "model_version": "3",
     "metrics": {"mae": ..., "rmse": ..., "mape": ..., "r2": ...}}

Variables de entorno necesarias:
    MLFLOW_TRACKING_URI       — URL del MLflow server
    DATABASE_URI              — URI SQLAlchemy a la BD mlops (lee clean_data.*)
    MLFLOW_S3_ENDPOINT_URL    — MinIO endpoint
    AWS_ACCESS_KEY_ID         — credencial MinIO
    AWS_SECRET_ACCESS_KEY     — credencial MinIO
    MLFLOW_EXPERIMENT_NAME    — nombre del experimento (default: house-price)
    MLFLOW_MODEL_NAME         — nombre en Model Registry (default: house-price-model)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from mlflow.models import infer_signature
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import (
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sqlalchemy import create_engine, text

try:
    from .preprocess import (
        ALL_FEATURES,
        TARGET_COLUMN,
        build_preprocessor,
        clean_dataframe,
        split_features_target,
    )
except ImportError:  # ejecución directa (no como módulo)
    from preprocess import (  # type: ignore
        ALL_FEATURES,
        TARGET_COLUMN,
        build_preprocessor,
        clean_dataframe,
        split_features_target,
    )

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("p2.training.train")

DEFAULT_EXPERIMENT = os.getenv("MLFLOW_EXPERIMENT_NAME", "house-price")
DEFAULT_MODEL_NAME = os.getenv("MLFLOW_MODEL_NAME", "house-price-model")


def load_clean_data(clean_table: str, batch_filter: str | None) -> pd.DataFrame:
    """Carga datos limpios desde la BD.

    clean_table: e.g. "clean_data.properties" (esquema.tabla, definido por P1).
    batch_filter: si se pasa, filtra por batch_id (recolección incremental — RF1).
    """
    db_uri = os.environ["DATABASE_URI"]
    engine = create_engine(db_uri)
    if batch_filter:
        query = text(f"SELECT * FROM {clean_table} WHERE batch_id <= :b")
        with engine.connect() as conn:
            df = pd.read_sql(query, conn, params={"b": batch_filter})
    else:
        query = text(f"SELECT * FROM {clean_table}")
        with engine.connect() as conn:
            df = pd.read_sql(query, conn)
    logger.info("Cargados %d registros desde %s", len(df), clean_table)
    return df


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    mae = float(mean_absolute_error(y_true, y_pred))
    mape = float(mean_absolute_percentage_error(y_true, y_pred))
    r2 = float(r2_score(y_true, y_pred))
    return {"mae": mae, "rmse": rmse, "mape": mape, "r2": r2}


def _log_residuals_plot(y_true: np.ndarray, y_pred: np.ndarray, out_dir: Path) -> Path:
    residuals = y_true - y_pred
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].scatter(y_pred, residuals, alpha=0.4, s=8)
    axes[0].axhline(0, color="red", linestyle="--")
    axes[0].set_xlabel("Predicción")
    axes[0].set_ylabel("Residuo")
    axes[0].set_title("Residuos vs. predicción")
    axes[1].hist(residuals, bins=50)
    axes[1].set_xlabel("Residuo")
    axes[1].set_ylabel("Frecuencia")
    axes[1].set_title("Distribución de residuos")
    fig.tight_layout()
    path = out_dir / "residuals.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _log_feature_importance_plot(
    pipeline: Pipeline, out_dir: Path, top_n: int = 20
) -> Path | None:
    try:
        regressor: RandomForestRegressor = pipeline.named_steps["regressor"]
        preproc = pipeline.named_steps["preprocessor"]
        names = preproc.get_feature_names_out()
        importances = regressor.feature_importances_
        order = np.argsort(importances)[::-1][:top_n]
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.barh(range(len(order)), importances[order][::-1])
        ax.set_yticks(range(len(order)))
        ax.set_yticklabels(names[order][::-1])
        ax.set_xlabel("Importancia")
        ax.set_title(f"Top {top_n} feature importances")
        fig.tight_layout()
        path = out_dir / "feature_importance.png"
        fig.savefig(path, dpi=120)
        plt.close(fig)
        return path
    except Exception as exc:  # pragma: no cover
        logger.warning("No se pudo generar feature_importance: %s", exc)
        return None


def train(args: argparse.Namespace) -> dict:
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    mlflow.set_experiment(DEFAULT_EXPERIMENT)

    df = load_clean_data(args.clean_table, args.batch_id_filter)
    df, report = clean_dataframe(df)
    if len(df) < args.min_rows:
        raise SystemExit(
            f"Datos insuficientes para entrenar: {len(df)} < {args.min_rows} requeridos"
        )

    X, y = split_features_target(df)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=args.test_size, random_state=args.random_state
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_train, y_train, test_size=args.val_size, random_state=args.random_state
    )

    preprocessor = build_preprocessor()
    regressor = RandomForestRegressor(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        min_samples_leaf=args.min_samples_leaf,
        n_jobs=args.n_jobs,
        random_state=args.random_state,
    )
    pipeline = Pipeline(
        steps=[("preprocessor", preprocessor), ("regressor", regressor)]
    )

    run_name = f"candidate-{args.batch_id}"
    with mlflow.start_run(run_name=run_name) as run:
        mlflow.set_tag("batch_id", args.batch_id)
        mlflow.set_tag("commit_sha", args.commit_sha or "unknown")
        mlflow.set_tag("training_reason", args.training_reason)
        mlflow.set_tag("model_family", "RandomForestRegressor")

        mlflow.log_params(
            {
                "n_estimators": args.n_estimators,
                "max_depth": args.max_depth,
                "min_samples_leaf": args.min_samples_leaf,
                "test_size": args.test_size,
                "val_size": args.val_size,
                "random_state": args.random_state,
                "n_rows_input": report.n_rows_in,
                "n_rows_used": report.n_rows_out,
                "n_train": len(X_train),
                "n_val": len(X_val),
                "n_test": len(X_test),
            }
        )

        pipeline.fit(X_train, y_train)

        y_train_pred = pipeline.predict(X_train)
        y_val_pred = pipeline.predict(X_val)
        y_test_pred = pipeline.predict(X_test)

        train_metrics = compute_metrics(y_train.values, y_train_pred)
        val_metrics = compute_metrics(y_val.values, y_val_pred)
        test_metrics = compute_metrics(y_test.values, y_test_pred)

        for split, metrics in {
            "train": train_metrics,
            "val": val_metrics,
            "test": test_metrics,
        }.items():
            mlflow.log_metrics({f"{split}_{k}": v for k, v in metrics.items()})

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            residuals_path = _log_residuals_plot(y_test.values, y_test_pred, out_dir)
            mlflow.log_artifact(str(residuals_path), artifact_path="diagnostics")
            fi_path = _log_feature_importance_plot(pipeline, out_dir)
            if fi_path is not None:
                mlflow.log_artifact(str(fi_path), artifact_path="diagnostics")

            report_path = out_dir / "preprocessing_report.json"
            report_path.write_text(
                json.dumps(report.__dict__, indent=2, ensure_ascii=False)
            )
            mlflow.log_artifact(str(report_path), artifact_path="diagnostics")

        signature = infer_signature(X_train, y_train_pred)
        mlflow.sklearn.log_model(
            sk_model=pipeline,
            artifact_path="model",
            registered_model_name=args.model_name,
            signature=signature,
            input_example=X_train.head(3),
        )

        client = mlflow.tracking.MlflowClient()
        latest = max(
            client.search_model_versions(f"name='{args.model_name}'"),
            key=lambda v: int(v.version),
        )
        client.set_model_version_tag(args.model_name, latest.version, "batch_id", args.batch_id)
        client.set_model_version_tag(
            args.model_name, latest.version, "training_reason", args.training_reason
        )

        result = {
            "run_id": run.info.run_id,
            "model_name": args.model_name,
            "model_version": latest.version,
            "model_uri": f"models:/{args.model_name}/{latest.version}",
            "metrics": {
                "train": train_metrics,
                "val": val_metrics,
                "test": test_metrics,
            },
            "rows_used": report.n_rows_out,
            "batch_id": args.batch_id,
        }
        logger.info("Run terminado: %s", result["run_id"])
        return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Entrena modelo candidato")
    parser.add_argument("--batch-id", required=True, help="ID del lote actual")
    parser.add_argument(
        "--batch-id-filter",
        default=None,
        help="Si se pasa, entrena con todos los lotes <= este ID (acumulado)",
    )
    parser.add_argument("--commit-sha", default=os.getenv("GITHUB_SHA"))
    parser.add_argument(
        "--training-reason",
        required=True,
        help="Razón por la que decide_training escogió entrenar (copia de la tabla de auditoría)",
    )
    parser.add_argument(
        "--clean-table",
        default=os.getenv("CLEAN_TABLE", "clean_data.properties"),
        help="Tabla esquema.tabla con datos procesados (definida por P1)",
    )
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--n-estimators", type=int, default=200)
    parser.add_argument("--max-depth", type=int, default=None)
    parser.add_argument("--min-samples-leaf", type=int, default=2)
    parser.add_argument("--n-jobs", type=int, default=-1)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--test-size", type=float, default=0.15)
    parser.add_argument("--val-size", type=float, default=0.15)
    parser.add_argument("--min-rows", type=int, default=50)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = train(args)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
