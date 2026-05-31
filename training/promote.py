"""Decide promoción y actualiza el alias productivo (tareas 14-17 del DAG).

Regla por defecto (RF6 — modificable por flags):
  - Si NO existe modelo productivo, promueve siempre el candidato.
  - Si existe, promueve sólo si:
      MAE candidato <= MAE productivo * (1 - mae_improvement_pct/100)
    AND
      RMSE candidato <= RMSE productivo * (1 + rmse_tolerance_pct/100)

Defaults: --mae-improvement-pct 3.0  --rmse-tolerance-pct 1.0

Recibe por --evaluation-json el output de evaluate.py (puede leerlo de archivo
o de stdin: '-'). Emite por stdout un JSON con la decisión y la razón.

Variables de entorno:
    MLFLOW_TRACKING_URI
    MLFLOW_MODEL_NAME (default: house-price-model)
    MLFLOW_PRODUCTION_ALIAS (default: production)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

import mlflow

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("p2.training.promote")

DEFAULT_MODEL_NAME = os.getenv("MLFLOW_MODEL_NAME", "house-price-model")
PRODUCTION_ALIAS = os.getenv("MLFLOW_PRODUCTION_ALIAS", "production")


def decide_promotion(
    evaluation: dict,
    mae_improvement_pct: float,
    rmse_tolerance_pct: float,
) -> tuple[bool, str]:
    """Retorna (promote, reason)."""
    if evaluation.get("no_production_model"):
        return True, "no existe modelo productivo — promover candidato por defecto"

    cand = evaluation["candidate_metrics"]
    prod = evaluation["production_metrics"]

    mae_threshold = prod["mae"] * (1 - mae_improvement_pct / 100.0)
    rmse_threshold = prod["rmse"] * (1 + rmse_tolerance_pct / 100.0)

    mae_ok = cand["mae"] <= mae_threshold
    rmse_ok = cand["rmse"] <= rmse_threshold

    mae_delta_pct = (cand["mae"] - prod["mae"]) / prod["mae"] * 100.0
    rmse_delta_pct = (cand["rmse"] - prod["rmse"]) / prod["rmse"] * 100.0

    if mae_ok and rmse_ok:
        reason = (
            f"MAE candidato {cand['mae']:.4f} mejora a productivo {prod['mae']:.4f} "
            f"({mae_delta_pct:+.2f}%, umbral -{mae_improvement_pct}%); "
            f"RMSE candidato {cand['rmse']:.4f} dentro de tolerancia "
            f"({rmse_delta_pct:+.2f}%, umbral +{rmse_tolerance_pct}%)"
        )
        return True, reason

    if not mae_ok:
        reason = (
            f"MAE candidato {cand['mae']:.4f} NO mejora suficientemente al productivo "
            f"{prod['mae']:.4f} ({mae_delta_pct:+.2f}%, requerido -{mae_improvement_pct}%)"
        )
    else:
        reason = (
            f"RMSE candidato {cand['rmse']:.4f} se deteriora frente al productivo "
            f"{prod['rmse']:.4f} ({rmse_delta_pct:+.2f}%, máximo permitido +{rmse_tolerance_pct}%)"
        )
    return False, reason


def assign_alias(model_name: str, version: str, alias: str) -> None:
    client = mlflow.tracking.MlflowClient()
    client.set_registered_model_alias(name=model_name, alias=alias, version=version)
    logger.info("Alias '%s' asignado a %s v%s", alias, model_name, version)


def tag_rejected(model_name: str, version: str, reason: str) -> None:
    client = mlflow.tracking.MlflowClient()
    client.set_model_version_tag(model_name, version, "promotion_decision", "rejected")
    client.set_model_version_tag(model_name, version, "rejection_reason", reason[:480])


def tag_promoted(model_name: str, version: str, reason: str) -> None:
    client = mlflow.tracking.MlflowClient()
    client.set_model_version_tag(model_name, version, "promotion_decision", "promoted")
    client.set_model_version_tag(model_name, version, "promotion_reason", reason[:480])


def load_evaluation(path: str) -> dict:
    if path == "-":
        return json.loads(sys.stdin.read())
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decide y aplica promoción")
    parser.add_argument("--evaluation-json", required=True, help="ruta a JSON de evaluate.py, o '-' para stdin")
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--production-alias", default=PRODUCTION_ALIAS)
    parser.add_argument("--mae-improvement-pct", type=float, default=3.0)
    parser.add_argument("--rmse-tolerance-pct", type=float, default=1.0)
    args = parser.parse_args(argv)

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    evaluation = load_evaluation(args.evaluation_json)
    promote, reason = decide_promotion(
        evaluation, args.mae_improvement_pct, args.rmse_tolerance_pct
    )

    if promote:
        assign_alias(args.model_name, args.candidate_version, args.production_alias)
        tag_promoted(args.model_name, args.candidate_version, reason)
    else:
        tag_rejected(args.model_name, args.candidate_version, reason)

    result = {
        "promoted": promote,
        "reason": reason,
        "model_name": args.model_name,
        "candidate_version": args.candidate_version,
        "alias_applied": args.production_alias if promote else None,
        "previous_production_version": evaluation.get("production_version"),
        "candidate_metrics": evaluation.get("candidate_metrics"),
        "production_metrics": evaluation.get("production_metrics"),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
