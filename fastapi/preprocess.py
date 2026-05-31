"""Preprocesamiento mínimo para inferencia — ESPEJO de training/preprocess.py.

El modelo serializado en MLflow contiene el pipeline completo (ColumnTransformer +
RandomForest), así que en inferencia este módulo SOLO necesita:
  - coercer el payload entrante a un DataFrame con las columnas esperadas,
  - convertir prev_sold_date a 'days_since_prev_sold',
  - rellenar NaN y unknown coherentemente con el entrenamiento.

IMPORTANTE: si cambias las constantes en training/preprocess.py (NUMERIC_FEATURES,
CATEGORICAL_FEATURES, etc.) debes reflejar el cambio aquí. El modelo entrenado y
la API DEBEN compartir el mismo orden y nombre de features, de lo contrario
sklearn falla en predict.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

NUMERIC_FEATURES = [
    "bed",
    "bath",
    "acre_lot",
    "zip_code",
    "house_size",
    "days_since_prev_sold",
]

CATEGORICAL_FEATURES = [
    "brokered_by",
    "status",
    "street",
    "city",
    "state",
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def _coerce_prev_sold_date(df: pd.DataFrame) -> pd.DataFrame:
    today = pd.Timestamp(datetime.utcnow().date())
    df = df.copy()
    if "prev_sold_date" in df.columns:
        prev = pd.to_datetime(df["prev_sold_date"], errors="coerce")
        df["days_since_prev_sold"] = (today - prev).dt.days.astype("float64")
    else:
        df["days_since_prev_sold"] = np.nan
    return df


def prepare_inference_frame(payload: dict) -> pd.DataFrame:
    df = pd.DataFrame([payload])
    df = _coerce_prev_sold_date(df)

    for col in NUMERIC_FEATURES:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = np.nan

    for col in CATEGORICAL_FEATURES:
        if col not in df.columns:
            df[col] = "unknown"
        df[col] = df[col].astype("string").fillna("unknown")

    return df[ALL_FEATURES]
