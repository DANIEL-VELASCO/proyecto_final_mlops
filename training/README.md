# Training — Pipeline de entrenamiento (Persona 2)

Imagen Docker con 3 subcomandos invocables por el DAG de Airflow.

## Subcomandos

```bash
# Tareas 11, 12, 13 del DAG (train + evaluate train + register)
mlops-training train \
    --batch-id 2026-05-31-01 \
    --batch-id-filter 2026-05-31-01 \
    --commit-sha $GITHUB_SHA \
    --training-reason "drift detectado en house_size" \
    --clean-table clean_data.properties

# Tarea 14 (compare_with_production)
mlops-training evaluate \
    --candidate-version 3 \
    --batch-id-filter 2026-05-31-01

# Tareas 15-17 (decide + promote/reject)
mlops-training promote \
    --evaluation-json /tmp/eval.json \
    --candidate-version 3 \
    --mae-improvement-pct 3.0 \
    --rmse-tolerance-pct 1.0
```

Cada subcomando imprime un JSON parseable como **última línea de stdout** que el DAG captura con XCom.

## Regla de promoción

Por defecto:

```
promote if MAE_candidato <= MAE_productivo * 0.97   # baja >= 3%
       AND RMSE_candidato <= RMSE_productivo * 1.01 # no empeora > 1%
```

Configurable con `--mae-improvement-pct` y `--rmse-tolerance-pct`.

## Modelo

`RandomForestRegressor` con `ColumnTransformer`:
- Numéricas (`bed`, `bath`, `acre_lot`, `zip_code`, `house_size`, `days_since_prev_sold`): mediana + StandardScaler
- Categóricas (`brokered_by`, `status`, `street`, `city`, `state`): moda + `OneHotEncoder(handle_unknown="ignore", min_frequency=10)`

Eso garantiza que ciudades nuevas o agencias desconocidas no rompan el pipeline en inferencia.

## Imagen publicada

DockerHub: `max181818/mlops-training` con tags `latest` y `sha-<commit>`.

Publicada automáticamente por GitHub Actions (`.github/workflows/build-training.yml`) en cada push a `main` o `develop` que toque `training/**`.
