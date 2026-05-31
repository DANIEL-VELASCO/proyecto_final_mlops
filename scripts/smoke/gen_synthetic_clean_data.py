"""Genera un CSV sintético compatible con clean_data.properties para smoke test.

Uso:
    python scripts/smoke/gen_synthetic_clean_data.py --out scripts/smoke/clean_properties.csv --rows 8000

El generador produce un dataset con relación price ≈ f(house_size, bed, bath, city)
+ ruido, suficiente para que RandomForest aprenda algo señalado y los gráficos
en MLflow tengan sentido. No reemplaza a la API real (data-api-pf-v1); solo es
para validar el pipeline antes de la integración.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

CITIES = [
    ("New York", "NY"),
    ("Los Angeles", "CA"),
    ("Chicago", "IL"),
    ("Houston", "TX"),
    ("Phoenix", "AZ"),
    ("Philadelphia", "PA"),
    ("San Antonio", "TX"),
    ("San Diego", "CA"),
    ("Dallas", "TX"),
    ("San Jose", "CA"),
]
STATUSES = ["for_sale", "for_build"]
# Multiplicador de precio por ciudad (NY/SF/LA caros, etc.)
CITY_PRICE_MULT = {
    "New York": 2.5,
    "Los Angeles": 2.3,
    "San Diego": 2.1,
    "San Jose": 2.4,
    "Chicago": 1.4,
    "Houston": 1.1,
    "Phoenix": 1.2,
    "Philadelphia": 1.3,
    "San Antonio": 1.0,
    "Dallas": 1.2,
}


def generate(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    cities_idx = rng.integers(0, len(CITIES), size=n)
    cities = [CITIES[i][0] for i in cities_idx]
    states = [CITIES[i][1] for i in cities_idx]

    house_size = rng.integers(400, 6000, size=n).astype(float)
    bed = np.clip(rng.normal(3, 1.3, size=n).round(), 1, 8).astype(int)
    bath = np.clip(rng.normal(2, 0.9, size=n).round(), 1, 6).astype(int)
    acre_lot = np.round(rng.lognormal(mean=-1.0, sigma=0.8, size=n), 2)

    brokered_by = [f"agency_{i}" for i in rng.integers(1, 250, size=n)]
    street = [f"street_{i}" for i in rng.integers(1, 9000, size=n)]
    status = rng.choice(STATUSES, size=n, p=[0.85, 0.15])
    zip_code = rng.integers(10000, 99999, size=n)

    # 30% no tienen prev_sold_date (NaT)
    has_prev = rng.random(size=n) > 0.3
    base = pd.Timestamp("2010-01-01")
    delta_days = rng.integers(0, 365 * 14, size=n)
    prev_sold_date = pd.Series(
        [base + pd.Timedelta(days=int(d)) if has else pd.NaT for d, has in zip(delta_days, has_prev)]
    )

    base_price = (
        80_000
        + house_size * 100
        + bed * 12_000
        + bath * 18_000
        + acre_lot * 25_000
    )
    city_mult = np.array([CITY_PRICE_MULT[c] for c in cities])
    noise = rng.normal(0, 0.12, size=n)
    price = np.round(base_price * city_mult * (1 + noise), 2)
    price = np.clip(price, 30_000, 5_000_000)

    df = pd.DataFrame(
        {
            "batch_id": "smoke-1",  # P1 lo poblará desde el DAG; aquí asumimos un lote único
            "brokered_by": brokered_by,
            "status": status,
            "price": price,
            "bed": bed,
            "bath": bath,
            "acre_lot": acre_lot,
            "street": street,
            "city": cities,
            "state": states,
            "zip_code": zip_code,
            "house_size": house_size.astype(int),
            "prev_sold_date": prev_sold_date,
        }
    )
    return df


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="scripts/smoke/clean_properties.csv")
    p.add_argument("--rows", type=int, default=8000)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    df = generate(args.rows, args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"Wrote {len(df)} rows -> {out}")
    print(df.head(3).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
