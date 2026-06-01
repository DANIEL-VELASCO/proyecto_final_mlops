"""
Preprocesamiento de P1: limpieza y validación de datos crudos.
Almacena en clean_data.properties con columnas originales — P2 hace el encoding ML.
"""
import hashlib
import json
import logging
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

EXPECTED_COLUMNS = [
    "brokered_by", "status", "price", "bed", "bath",
    "acre_lot", "street", "city", "state", "zip_code",
    "house_size", "prev_sold_date",
]

NUMERIC_COLS     = ["price", "bed", "bath", "acre_lot", "zip_code", "house_size"]
CATEGORICAL_COLS = ["brokered_by", "status", "street", "city", "state"]
TARGET           = "price"


def compute_row_hash(row: dict) -> str:
    return hashlib.md5(
        json.dumps(row, sort_keys=True, default=str).encode()
    ).hexdigest()


def validate_schema(df: pd.DataFrame) -> dict:
    present  = set(df.columns.str.lower().str.strip())
    expected = set(EXPECTED_COLUMNS)
    missing  = sorted(expected - present)
    extra    = sorted(present - expected)
    return {"valid": len(missing) == 0, "missing": missing, "extra": extra}


def validate_quality(df: pd.DataFrame, null_threshold: float = 0.5) -> dict[str, Any]:
    null_pct  = df.isnull().mean()
    over_null = null_pct[null_pct > null_threshold].index.tolist()

    n_dup = int(df.duplicated().sum())

    price_col = pd.to_numeric(df.get("price", pd.Series(dtype=float)), errors="coerce")
    bad_price = int(((price_col <= 0) | price_col.isna()).sum())

    valid = (
        len(over_null) == 0
        and bad_price == 0
        and n_dup / max(len(df), 1) < 0.5
    )
    return {
        "valid":          valid,
        "null_pct_max":   float(null_pct.max()),
        "cols_high_nulls": over_null,
        "duplicate_count": n_dup,
        "duplicate_pct":  float(n_dup / max(len(df), 1)),
        "invalid_price_count": bad_price,
    }


def detect_new_categories(df: pd.DataFrame, known: dict[str, set]) -> dict:
    """
    Detecta categorías nuevas en city, state, status, brokered_by.
    known = {feature: set_of_known_values}
    """
    findings: dict[str, list] = {}
    for col in CATEGORICAL_COLS:
        if col not in df.columns:
            continue
        vals  = df[col].dropna().astype(str)
        freq  = vals.value_counts(normalize=True)
        new   = [(c, float(p)) for c, p in freq.items() if c not in known.get(col, set())]
        if new:
            findings[col] = [{"value": c, "frequency": p} for c, p in new]
    return findings


def detect_drift(df_new: pd.DataFrame, df_ref: pd.DataFrame) -> dict:
    """KS-test para numéricas contra el histórico de clean_data."""
    from scipy import stats

    results: dict[str, dict] = {}
    for col in ["bed", "bath", "acre_lot", "house_size", "price"]:
        if col not in df_new.columns or col not in df_ref.columns:
            continue
        a = pd.to_numeric(df_new[col], errors="coerce").dropna()
        b = pd.to_numeric(df_ref[col],  errors="coerce").dropna()
        if len(a) < 10 or len(b) < 10:
            continue
        stat, pval = stats.ks_2samp(a, b)
        results[col] = {"statistic": float(stat), "pvalue": float(pval), "drift": pval < 0.05}
    return results


def clean_batch(df: pd.DataFrame) -> pd.DataFrame:
    """
    Limpieza mínima del lote: normaliza tipos, rellena nulos básicos.
    Devuelve DataFrame con columnas originales listo para clean_data.properties.
    No hace encoding — eso lo hace P2 en la imagen de training.
    """
    df = df.copy()
    df.columns = df.columns.str.lower().str.strip()

    # Tipos numéricos
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Eliminar filas sin precio válido
    if TARGET in df.columns:
        df = df[df[TARGET].notna() & (df[TARGET] > 0)]

    # Normalizar fecha
    if "prev_sold_date" in df.columns:
        df["prev_sold_date"] = pd.to_datetime(df["prev_sold_date"], errors="coerce").dt.date

    # Trim en categóricas
    for col in CATEGORICAL_COLS:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().replace("nan", None).replace("", None)

    return df
