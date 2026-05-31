import os
import streamlit as st
import requests
import pandas as pd
from sqlalchemy import create_engine, text

FASTAPI_URL = os.getenv("FASTAPI_URL", "http://localhost:8000")
DATABASE_URI = os.getenv("DATABASE_URI", "postgresql+psycopg2://mlops:mlops_pass@localhost:5432/mlops")

st.set_page_config(
    page_title="MLOps — Estimación de Precios Inmobiliarios",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("MLOps — Estimación de Precios Inmobiliarios")

tab1, tab2 = st.tabs(["Inferencia", "Historial de Entrenamiento"])


# ── Sección 1: Inferencia ──────────────────────────────────────────────────────

with tab1:
    st.subheader("Ingresa los datos de la propiedad")

    col1, col2, col3 = st.columns(3)

    with col1:
        brokered_by = st.text_input("Agencia / Corredor", value="agency_1")
        status = st.selectbox("Estado de la vivienda", ["for_sale", "for_build"])
        bed = st.number_input("Habitaciones", min_value=1, max_value=20, value=3)
        bath = st.number_input("Baños", min_value=1, max_value=20, value=2)

    with col2:
        acre_lot = st.number_input("Tamaño del terreno (acres)", min_value=0.01, max_value=500.0, value=0.5, step=0.01)
        house_size = st.number_input("Área habitable (sq ft)", min_value=100, max_value=50000, value=1500)
        zip_code = st.number_input("Código postal", min_value=1000, max_value=99999, value=10001)

    with col3:
        street = st.text_input("Dirección (codificada)", value="street_1")
        city = st.text_input("Ciudad", value="New York")
        state = st.text_input("Estado / Región", value="NY")
        prev_sold_date = st.date_input("Fecha de venta anterior (opcional)", value=None)

    st.divider()

    if st.button("Predecir precio", type="primary", use_container_width=True):
        payload = {
            "brokered_by": brokered_by,
            "status": status,
            "bed": int(bed),
            "bath": int(bath),
            "acre_lot": float(acre_lot),
            "street": street,
            "city": city,
            "state": state,
            "zip_code": int(zip_code),
            "house_size": int(house_size),
            "prev_sold_date": str(prev_sold_date) if prev_sold_date else None,
        }

        with st.spinner("Consultando modelo..."):
            try:
                response = requests.post(f"{FASTAPI_URL}/predict", json=payload, timeout=10)
                response.raise_for_status()
                result = response.json()

                st.success("Predicción obtenida correctamente")

                res_col1, res_col2 = st.columns(2)
                with res_col1:
                    st.metric(
                        label="Precio estimado",
                        value=f"${result.get('price', 0):,.2f}",
                    )
                with res_col2:
                    st.metric(
                        label="Versión del modelo",
                        value=result.get("model_version", "N/A"),
                        help=f"Alias: {result.get('model_alias', 'N/A')}",
                    )

            except requests.exceptions.ConnectionError:
                st.error(f"No se puede conectar a FastAPI en {FASTAPI_URL}. Verifica que el servicio esté activo.")
            except requests.exceptions.Timeout:
                st.error("Tiempo de espera agotado. El servicio tardó demasiado en responder.")
            except requests.exceptions.HTTPError as e:
                st.error(f"Error en la API: {e.response.status_code} — {e.response.text}")
            except Exception as e:
                st.error(f"Error inesperado: {e}")


# ── Sección 2: Historial de Entrenamiento ─────────────────────────────────────

with tab2:
    st.subheader("Historial de lotes y decisiones de entrenamiento")

    @st.cache_data(ttl=30)
    def load_history():
        engine = create_engine(DATABASE_URI)
        query = text("""
            SELECT
                batch_id,
                fecha,
                n_registros,
                decision,
                razon,
                mae_candidato,
                mae_productivo,
                promovido
            FROM raw_data.training_audit
            ORDER BY fecha DESC
        """)
        with engine.connect() as conn:
            return pd.read_sql(query, conn)

    try:
        df = load_history()

        if df.empty:
            st.info("Aún no hay lotes procesados. El historial aparecerá aquí una vez que el DAG ejecute el primer lote.")
        else:
            # Métricas resumen
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total de lotes", len(df))
            m2.metric("Lotes entrenados", df["decision"].eq("entrenó").sum())
            m3.metric("Modelos promovidos", df["promovido"].eq(True).sum())
            entrenamientos = df[df["decision"] == "entrenó"]
            if not entrenamientos.empty and entrenamientos["mae_candidato"].notna().any():
                mejor_mae = entrenamientos["mae_candidato"].min()
                m4.metric("Mejor MAE candidato", f"{mejor_mae:,.4f}")
            else:
                m4.metric("Mejor MAE candidato", "N/A")

            st.divider()

            # Tabla detallada con colores
            def highlight_row(row):
                if row["decision"] == "no entrenó":
                    return ["background-color: #f0f0f0"] * len(row)
                elif row["promovido"] is True:
                    return ["background-color: #d4edda"] * len(row)
                else:
                    return ["background-color: #fff3cd"] * len(row)

            df_display = df.copy()
            df_display["promovido"] = df_display["promovido"].map(
                {True: "✅ Sí", False: "❌ No", None: "—"}
            )
            df_display["mae_candidato"] = df_display["mae_candidato"].apply(
                lambda x: f"{x:,.4f}" if pd.notna(x) else "—"
            )
            df_display["mae_productivo"] = df_display["mae_productivo"].apply(
                lambda x: f"{x:,.4f}" if pd.notna(x) else "—"
            )
            df_display.columns = [
                "Batch ID", "Fecha", "Registros", "Decisión",
                "Razón", "MAE Candidato", "MAE Productivo", "Promovido",
            ]

            st.dataframe(
                df_display.style.apply(highlight_row, axis=1),
                use_container_width=True,
                hide_index=True,
            )

            # Detalle expandible por lote
            st.subheader("Detalle por lote")
            selected = st.selectbox("Selecciona un lote", df["batch_id"].tolist())
            row = df[df["batch_id"] == selected].iloc[0]

            with st.expander(f"Lote {selected} — detalles completos", expanded=True):
                d1, d2 = st.columns(2)
                with d1:
                    st.write(f"**Fecha:** {row['fecha']}")
                    st.write(f"**Registros:** {row['n_registros']}")
                    st.write(f"**Decisión:** {row['decision']}")
                    st.write(f"**Razón:** {row['razon']}")
                with d2:
                    st.write(f"**MAE Candidato:** {row['mae_candidato'] if pd.notna(row['mae_candidato']) else '—'}")
                    st.write(f"**MAE Productivo:** {row['mae_productivo'] if pd.notna(row['mae_productivo']) else '—'}")
                    st.write(f"**Promovido:** {'✅ Sí' if row['promovido'] else '❌ No' if row['promovido'] is False else '—'}")

    except Exception as e:
        st.warning(
            "No se pudo conectar a la base de datos o la tabla de auditoría aún no existe. "
            "El historial aparecerá automáticamente una vez que P1 cree la tabla `raw_data.training_audit`."
        )
        with st.expander("Detalle del error"):
            st.code(str(e))
