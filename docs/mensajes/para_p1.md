# Mensaje para P1 (Data Engineer)

Copia y pega esto en el chat del equipo.

---

Hola @P1 👋

Acabo de mergear mi PR (`feature/p2-mlflow-fastapi` → `main`, PR #1) con
todo lo de **P2** listo: pipeline de entrenamiento (`training/`), FastAPI
de inferencia (`fastapi/`), MLflow funcionando, y la imagen Docker con
subcomandos `train`/`evaluate`/`promote` que vas a invocar desde el DAG.

**Para que no te bloqueés, te dejé el contrato exacto aquí:**
`docs/contracts/p2-interfaces.md`

Resumen rápido de lo que necesitas hacer / saber:

### 🔵 1. Cómo invocar mis módulos desde el DAG (tareas 11–17)

La imagen `mlops-training:sha-XXXX` (la publica GH Actions al mergear)
acepta 3 subcomandos. Recomiendo usar `KubernetesPodOperator`:

```python
# tareas 11 + 12 + 13 (train + evaluate + register) en una sola tarea:
train_task = KubernetesPodOperator(
    task_id="train_candidate_model",
    image=f"max181818/mlops-training:sha-{commit_sha}",
    cmds=["entrypoint.sh"],
    arguments=[
        "train",
        "--batch-id", "{{ ds }}",
        "--batch-id-filter", "{{ ds }}",
        "--training-reason", "{{ task_instance.xcom_pull(task_ids='decide_training', key='reason') }}",
        "--clean-table", "clean_data.properties",
    ],
    env_from=[k8s.V1EnvFromSource(secret_ref=k8s.V1SecretEnvSource(name="fastapi-secret")),
              k8s.V1EnvFromSource(secret_ref=k8s.V1SecretEnvSource(name="mlflow-secret"))],
    do_xcom_push=True,  # la última línea del stdout es JSON
)
# Pásale `train.xcom_pull()["model_version"]` a la siguiente tarea evaluate.
```

Argumentos exactos, variables de entorno y formato JSON de salida están
documentados en la sección 1.1 / 1.2 / 1.3 del archivo de contratos.

### 🔵 2. Tablas que YO necesito que tú crees (o confirmes el DDL)

| Tabla                              | Quién la lee/escribe          | Estado                                    |
| ---------------------------------- | ----------------------------- | ----------------------------------------- |
| `clean_data.properties`            | La leo yo en `train.py`       | Necesito el DDL definitivo                |
| `raw_data.training_audit`          | La escribes tú, la lee Streamlit | Necesito el DDL para Streamlit         |
| `raw_data.inference_events`        | La escribo yo en FastAPI      | Propongo este DDL (puedes ajustarlo):     |

```sql
CREATE TABLE IF NOT EXISTS raw_data.inference_events (
    request_id      UUID PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model_name      TEXT NOT NULL,
    model_version   TEXT NOT NULL,
    model_alias     TEXT NOT NULL,
    input_payload   JSONB NOT NULL,
    prediction      DOUBLE PRECISION,
    status          TEXT NOT NULL,
    error_message   TEXT,
    latency_ms      INTEGER
);
```

Mi código ya hace `CREATE TABLE IF NOT EXISTS` con ese schema al
arrancar FastAPI, así que **si te queda igual, no haces nada extra**.
Si cambias columnas o nombre de tabla, avísame para ajustar.

### 🔵 3. Columnas mínimas que necesito en `clean_data.properties`

Lo que mi `train.py` espera (orden no importa, nombres sí):

```
batch_id (TEXT), price (DOUBLE PRECISION), bed (INT), bath (INT),
acre_lot (DOUBLE), brokered_by (TEXT), status (TEXT), street (TEXT),
city (TEXT), state (TEXT), zip_code (INT), house_size (INT),
prev_sold_date (DATE NULL)
```

Hay un ejemplo de DDL en `scripts/smoke/bootstrap_db.sql` (es solo para
el smoke test mío; tú pones el oficial).

### 🔵 4. Para el DAG, mi regla de decisión `decide_promotion` es

```
promote if MAE_candidato <= MAE_productivo * 0.97   # baja ≥3 %
       AND RMSE_candidato <= RMSE_productivo * 1.01 # no empeora >1 %
```

Configurable con `--mae-improvement-pct` y `--rmse-tolerance-pct` por
si los acordamos diferentes con el profesor.

### 🔵 5. Para la tarea `notify_or_log_result` (tarea 18)

Tienes que escribir una fila en `raw_data.training_audit` con las
columnas exactas que ya espera Streamlit (P3 ya escribió el query):

```
batch_id, fecha, n_registros, decision ('entrenó'|'no entrenó'),
razon, mae_candidato, mae_productivo, promovido (boolean)
```

Esos valores los tienes en los JSON que devuelven mis `train` /
`evaluate` / `promote` (todos imprimen JSON parseable en la última línea
de stdout).

¿Algo de esto te bloquea? Cualquier cambio en columnas o nombres de
tabla, avísame para sincronizar el código de P2 antes de que rompamos
la integración.

— P2
