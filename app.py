import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from pyairtable import Api
from datetime import datetime
from zoneinfo import ZoneInfo

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="MODO DIAGNÓSTICO", layout="wide") 

st.title("🛠️ MODO DIAGNÓSTICO DE ERRORES")
st.write("Esta pantalla mostrará paso a paso qué está fallando.")

# 1. VERIFICACIÓN DE SECRETS
st.subheader("1. Verificando Credenciales...")
if "airtable" in st.secrets:
    st.success("✅ Secrets de Airtable detectados.")
else:
    st.error("❌ ERROR CRÍTICO: No encuentro la sección [airtable] en los Secrets.")
    st.stop()

# 2. CONEXIÓN API
st.subheader("2. Conectando con Airtable...")
try:
    api = Api(st.secrets["airtable"]["api_token"])
    table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
    st.success("✅ Objeto de conexión creado (Airtable SDK ok).")
except Exception as e:
    st.error(f"❌ ERROR CONECTANDO: {e}")
    st.stop()

# 3. DESCARGA DE DATOS (AQUÍ SUELE FALLAR)
st.subheader("3. Descargando Datos...")
try:
    data = table.all()
    st.success(f"✅ Conexión exitosa. Se han descargado {len(data)} registros (filas).")
except Exception as e:
    st.error(f"❌ ERROR GRAVE DESCARGANDO DATOS: {e}")
    st.info("Posibles causas: Nombre de tabla incorrecto en Secrets, API Key caducada, o Base ID erróneo.")
    st.stop()

# 4. ANÁLISIS DE DATOS
st.subheader("4. Analizando Estructura de Datos...")
if len(data) == 0:
    st.warning("⚠️ La base de datos está VACÍA. Por eso no ves nada. Añade una operación nueva.")
else:
    # Mostramos el primer registro crudo para ver los nombres de columnas reales
    primer_registro = data[0]['fields']
    st.write("🔎 **Muestra del primer registro (Datos Crudos):**")
    st.json(primer_registro)
    
    df = pd.DataFrame([x['fields'] for x in data])
    st.write("📊 **Columnas detectadas:**", df.columns.tolist())

    # 5. PROCESANDO FECHAS
    st.subheader("5. Procesando Fechas...")
    try:
        if 'Fecha' in df.columns:
            df['Fecha_dt'] = pd.to_datetime(df['Fecha'], errors='coerce')
            df['Año'] = df['Fecha_dt'].dt.year 
            df['Fecha_str'] = df['Fecha_dt'].dt.strftime('%Y/%m/%d %H:%M').fillna("")
            st.success("✅ Fechas procesadas correctamente.")
        else:
            st.error("❌ ERROR: No encuentro la columna 'Fecha' en tu Airtable. Revisa el nombre exacto (mayúsculas importan).")
    except Exception as e:
        st.error(f"❌ Error procesando fechas: {e}")

    # 6. INTENTO DE RENDERIZADO BÁSICO
    st.subheader("6. Tabla de Prueba (Si ves esto, los datos están bien)")
    st.dataframe(df)

# --- FIN DEL DIAGNÓSTICO ---
st.divider()
st.info("Si ves un recuadro ROJO arriba, copia ese mensaje y pégalo en el chat.")
