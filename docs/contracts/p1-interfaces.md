# Contratos de P1 (Data Engineer) hacia P2 y P3

---

## 1. Esquema de base de datos — `raw_data`

### `raw_data.raw_batches`
Un registro por lote recibido desde la API de datos.

| Columna        | Tipo     | Descripción                                       |
| -------------- | -------- | ------------------------------------------------- |
| batch_id       | TEXT     | Identificador único del lote                      |
| group_id       | INTEGER  | Grupo del dataset (default: 1)                    |
| batch_number   | INTEGER  | Número secuencial del lote                        |
| n_records      | INTEGER  | Cantidad de registros en el lote                  |
| raw_payload    | JSONB    | Datos crudos tal como llegan de la API            |
| status         | TEXT     | stored → schema_validated → quality_validated → preprocessed |

### `raw_data.training_audit`
**Leída por P3 (Streamlit).** NO renombrar columnas sin avisar.

| Columna          | Tipo    | Descripción                                        |
| ---------------- | ------- | -------------------------------------------------- |
| batch_id         | TEXT    | FK a raw_batches                                   |
| execution_date   | TIMESTAMPTZ | Fecha de ejecución                             |
| n_records        | INTEGER | Registros del lote                                 |
| decision         | TEXT    | `'train'` o `'skip'`                               |
| reason           | TEXT    | Razón de la decisión                               |
| drift_detected   | BOOLEAN | Si se detectó drift estadístico                    |
| drift_variables  | TEXT    | JSON con variables drifteadas                      |
| new_categories   | TEXT    | JSON con categorías nuevas                         |
| volume_pct       | FLOAT   | % de crecimiento de volumen                        |
| mlflow_run_id    | TEXT    | Run ID de MLflow (P1 escribe desde output de P2)   |
| model_version    | TEXT    | Versión del modelo                                 |
| mae_candidate    | FLOAT   | MAE del candidato                                  |
| mae_production   | FLOAT   | MAE del modelo productivo                          |
| rmse_candidate   | FLOAT   | RMSE del candidato                                 |
| rmse_production  | FLOAT   | RMSE del productivo                                |
| promoted         | BOOLEAN | Si el candidato fue promovido                      |
| promotion_reason | TEXT    | Razón de promoción o rechazo                       |
| status           | TEXT    | pending → completed / failed                       |

### `raw_data.inference_events`
Creada por P1, escrita por P2 (FastAPI). Usar `INFERENCE_EVENTS_TABLE=raw_data.inference_events`.
Ver definición completa en `scripts/init_db.sql`.

---

## 2. Esquema de base de datos — `clean_data`

### `clean_data.properties`
**Leída por P2 (imagen de training).** Usar `--clean-table clean_data.properties`.

Columnas con nombres originales del dataset (P2 hace el encoding ML en su imagen):

| Columna       | Tipo            |
| ------------- | --------------- |
| batch_id      | TEXT            |
| row_hash      | TEXT (UNIQUE)   |
| brokered_by   | TEXT            |
| status        | TEXT            |
| price         | DOUBLE PRECISION |
| bed           | INTEGER         |
| bath          | INTEGER         |
| acre_lot      | DOUBLE PRECISION |
| street        | TEXT            |
| city          | TEXT            |
| state         | TEXT            |
| zip_code      | INTEGER         |
| house_size    | INTEGER         |
| prev_sold_date| DATE            |

---

## 3. Criterios de decisión de entrenamiento (RF4)

El DAG bifurca en `decide_training`. Condiciones para **entrenar**:

1. **Primera ejecución** — no existe ningún registro con `decision='train' AND promoted=TRUE` en `training_audit` → siempre entrenar.
2. **Drift estadístico** — KS-test (p-value < 0.05) en alguna de: `bed, bath, acre_lot, house_size, price`.
3. **Nuevas categorías significativas** — frecuencia ≥ `NEW_CATEGORY_FREQ_THRESHOLD` (default 5%) en `city, state, status, brokered_by, street`.
4. **Crecimiento de volumen** — registros nuevos / total histórico ≥ `VOLUME_INCREASE_PCT` (default 10%).

Condiciones para **no entrenar**:
- Lote < `MIN_RECORDS_TO_TRAIN` (default 100 registros).
- Ninguno de los criterios anteriores se cumple.

---

## 4. Variables de entorno que P1 necesita inyectar

### En Airflow (ver `kubernetes/airflow/airflow-configmap.yaml`):

| Variable                      | Default               | Descripción                          |
| ----------------------------- | --------------------- | ------------------------------------ |
| `DATA_API_HOST`               | `data-api`            | Host del contenedor de la API        |
| `DATA_API_PORT`               | `80`                  | Puerto de la API                     |
| `DATA_API_GROUP_ID`           | `1`                   | Número de grupo del dataset          |
| `DATABASE_URI`                | (en airflow-secret)   | URI de conexión a PostgreSQL         |
| `TRAINING_IMAGE`              | `danielvelasco01/mlops-training:latest` | Imagen P2 |
| `MIN_RECORDS_TO_TRAIN`        | `100`                 | Mínimo de registros para entrenar    |
| `VOLUME_INCREASE_PCT`         | `0.10`                | % mínimo de crecimiento de volumen   |
| `DRIFT_PVALUE_THRESHOLD`      | `0.05`                | Umbral p-value para KS-test          |
| `NEW_CATEGORY_FREQ_THRESHOLD` | `0.05`                | Frecuencia mínima de categoría nueva |

---

## 5. Checklist de coordinación con P2

- [x] Tabla `raw_data.training_audit` — columnas definidas en §1
- [x] Tabla `clean_data.properties` — columnas originales (P2 hace encoding)
- [x] Tabla `raw_data.inference_events` — DDL en `scripts/init_db.sql`
- [ ] P2: confirmar que `--clean-table clean_data.properties` es correcto
- [ ] P2: actualizar `TRAINING_IMAGE` en `airflow-configmap.yaml` con SHA real cuando publique imagen

## 6. Checklist de coordinación con P3

- [x] Tabla `raw_data.training_audit` disponible para consulta Streamlit
- [ ] P3: leer las columnas de `training_audit` en §1 para la consulta SQL de Streamlit
- [ ] P3: agregar `DATA_API_HOST`, `DATABASE_URI` y vars de P1 al secret de Airflow si no están ya
- [ ] P3: el workflow de GitHub Actions para Airflow debe usar `garzonds201/mlops-airflow:sha-{commit}`
