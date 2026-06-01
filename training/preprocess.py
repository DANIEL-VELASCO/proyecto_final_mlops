"""Preprocesamiento de datos para el modelo de precios de propiedades.

Características clave:
- OneHotEncoder con handle_unknown="ignore" para soportar categorías nuevas sin romper (RF3/RF4).
- Imputación numérica con mediana y categórica con la moda.
- prev_sold_date se convierte a "días desde la venta anterior" (numérica).
- El pipeline se serializa junto al modelo en MLflow para garantizar reproducibilidad.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

logger = logging.getLogger(__name__)

TARGET_COLUMN = "price"

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


@dataclass
class PreprocessingReport:
    """Resumen del preprocesamiento, útil para registrar en MLflow."""

    n_rows_in: int
    n_rows_out: int
    n_missing_target: int
    n_invalid_target: int
    columns_in: list[str]
    n_unique_categories: dict[str, int]


def _coerce_prev_sold_date(df: pd.DataFrame) -> pd.DataFrame:
    """Convierte prev_sold_date a 'días desde la venta anterior'.

    Si prev_sold_date es NaT/None, deja NaN (luego lo imputará el pipeline).
    Esta transformación permite que una fecha sea consumible por modelos tabulares.
    """
    today = pd.Timestamp(datetime.utcnow().date())
    if "prev_sold_date" in df.columns:
        prev = pd.to_datetime(df["prev_sold_date"], errors="coerce")
        df = df.copy()
        df["days_since_prev_sold"] = (today - prev).dt.days.astype("float64")
    else:
        df = df.copy()
        df["days_since_prev_sold"] = np.nan
    return df


def clean_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, PreprocessingReport]:
    """Limpia el DataFrame para entrenamiento.

    Reglas:
    - Elimina filas con target nulo (no se puede entrenar sin etiqueta).
    - Elimina filas con price <= 0 (target inválido).
    - Asegura tipos numéricos donde corresponda.
    - Garantiza que todas las columnas esperadas existan (rellena con NaN si faltan).
    """
    n_in = len(df)
    df = df.copy()

    if TARGET_COLUMN in df.columns:
        df[TARGET_COLUMN] = pd.to_numeric(df[TARGET_COLUMN], errors="coerce")
        n_missing_target = int(df[TARGET_COLUMN].isna().sum())
        df = df.dropna(subset=[TARGET_COLUMN])
        n_invalid_target = int((df[TARGET_COLUMN] <= 0).sum())
        df = df[df[TARGET_COLUMN] > 0]
    else:
        n_missing_target = 0
        n_invalid_target = 0

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

    report = PreprocessingReport(
        n_rows_in=n_in,
        n_rows_out=len(df),
        n_missing_target=n_missing_target,
        n_invalid_target=n_invalid_target,
        columns_in=list(df.columns),
        n_unique_categories={c: int(df[c].nunique()) for c in CATEGORICAL_FEATURES},
    )
    return df, report


def build_preprocessor() -> ColumnTransformer:
    """Construye el ColumnTransformer.

    handle_unknown="ignore" en OneHotEncoder es CRÍTICO: permite que en inferencia
    aparezcan categorías nuevas (ciudades, agencias) sin que el pipeline falle.
    """
    numeric_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )

    categorical_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            (
                "onehot",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False, min_frequency=10),
            ),
        ]
    )

    return ColumnTransformer(
        transformers=[
            ("num", numeric_pipeline, NUMERIC_FEATURES),
            ("cat", categorical_pipeline, CATEGORICAL_FEATURES),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )


def split_features_target(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Devuelve X (DataFrame con las columnas esperadas) y y (Series)."""
    X = df[ALL_FEATURES].copy()
    y = df[TARGET_COLUMN].astype("float64")
    return X, y


def prepare_inference_frame(payload: dict) -> pd.DataFrame:
    """Convierte un payload de inferencia (dict) en el DataFrame que espera el pipeline.

    Reutiliza la misma lógica de limpieza para garantizar coherencia entre
    entrenamiento e inferencia.
    """
    df = pd.DataFrame([payload])
    df, _ = clean_dataframe(df)
    if df.empty:
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
