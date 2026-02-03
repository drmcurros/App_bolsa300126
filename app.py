import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from pyairtable import Api
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor con Ayuda", layout="wide") 
MONEDA_BASE = "EUR" 

# --- ESTADO ---
if "pending_data" not in st.session_state:
    st.session_state.pending_data = None

# --- FUNCIONES ---
def check_password():
    if st.session_state.get('password_correct', False): return True
    st.header("🔒 Login")
    c1, c2 = st.columns(2)
    user = c1.text_input("Usuario")
    pw = c2.text_input("Contraseña", type="password")
    if st.button("Entrar"):
        try:
            if user == st.secrets["credenciales"]["usuario"] and pw == st.secrets["credenciales"]["password"]:
                st.session_state['password_correct'] = True
                st.rerun()
            else: st.error("Incorrecto")
        except: st.error("Revisa Secrets")
    return False

def get_exchange_rate(from_curr, to_curr="EUR"):
    if from_curr == to_curr: return 1.0
    try:
        pair = f"{to_curr}=X" if from_curr == "USD" else f"{from_curr}{to_curr}=X"
        return yf.Ticker(pair).history(period="1d")['Close'].iloc[-1]
    except: return 1.0

def get_stock_data_fmp(ticker):
    try:
        api_key = st.secrets["fmp"]["api_key"]
        url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey={api_key}"
        response = requests.get(url, timeout=3)
        data = response.json()
        if data and len(data) > 0:
            return data[0].get('companyName'), data[0].get('price')
        return None, None
    except: return None, None

def get_stock_data_yahoo(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")
        if not hist.empty:
            nombre = stock.info.get('longName') or stock.info.get('shortName') or ticker
            return nombre, hist['Close'].iloc[-1]
        return None, None
    except: return None, None

def guardar_en_airtable(record):
    try:
        api = Api(st.secrets["airtable"]["api_token"])
        table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
        table.create(record)
        st.success(f"✅ Guardado: {record['Ticker']}")
        st.session_state.pending_data = None
        st.rerun()
    except Exception as e: st.error(f"Error: {e}")

# --- APP ---
if not check_password(): st.stop()

try:
    api = Api(st.secrets["airtable"]["api_token"])
    table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
except: st.stop()

st.title("💼 Control de Rentabilidad (P&L)")

# --- CARGA DATOS ---
try: data = table.all()
except: data = []

df = pd.DataFrame()
if data:
    df = pd.DataFrame([x['fields'] for x in data])
    if 'Fecha' in df.columns:
        df['Fecha_dt'] = pd.to_datetime(df['Fecha'], errors='coerce')
        df['Año'] = df['Fecha_dt'].dt.year 
        df['Fecha_str'] = df['Fecha_dt'].dt.strftime('%Y/%m/%d %H:%M').fillna("")
    else: df['Año'] = datetime.now().year

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("Nueva Operación")
    
    lista_años = ["Todos los años"]
    if not df.empty and 'Año' in df.columns:
        años_disponibles = sorted(df['Año'].dropna().unique().astype(int), reverse=True)
        lista_años += list(años_disponibles)
    año_seleccionado = st.selectbox("📅 Año Fiscal:", lista_años)
    st.divider()

    if st.session_state.pending_data is None:
        with st.form("trade_form"):
            tipo = st.selectbox("Tipo", ["Compra", "Venta", "Dividendo"])
            ticker = st.text_input("Ticker (ej. TSLA)").upper().strip()
            desc_manual = st.text_input("Descripción (Opcional)")
            moneda = st.selectbox("Moneda", ["EUR", "USD"])
            
            c1, c2 = st.columns(2)
            dinero_total = c1.number_input("Importe Total", min_value=0.0, step=10.0)
            precio_manual = c2.number_input("Precio/Acción", min_value=0.0, format="%.2f")
            comision = st.number_input("Comisión", min_value=0.0, format="%.2f")
            
            st.markdown("---")
            st.write("📆 **Fecha:**")
            cd, ct = st.columns(2)
            f_in = cd.date_input("Día", value=datetime.now())
            h_in = ct.time_input("Hora", value=datetime.now())
            
            if st.form_submit_button("🔍 Validar y Guardar"):
                if ticker and dinero_total > 0:
                    nom, pre = None, 0.0
                    with st.spinner("Consultando precio..."):
                        nom, pre = get_stock_data_fmp(ticker)
                        if not nom: nom, pre = get_stock_data_yahoo(ticker)
                    
                    if desc_manual: nom = desc_manual
                    if not nom: nom = ticker
                    if precio_manual > 0: pre = precio_manual
                    if not pre: pre = 0.0

                    dt_final = datetime.combine(f_in, h_in)
                    datos = {
                        "Tipo": tipo, "Ticker": ticker, "Descripcion": nom, 
                        "Moneda": moneda, "Cantidad": float(dinero_total),
                        "Precio": float(pre), "Comision": float(comision),
                        "Fecha": dt_final.strftime("%Y/%m/%d %H:%M")
                    }
                    if pre > 0: guardar_en_airtable(datos)
                    else:
                        st.session_state.pending_data = datos
                        st.rerun()
    else:
        st.warning(f"⚠️ ¿Confirmar '{st.session_state.pending_data['Ticker']}'?")
        if st.button("✅ Sí"): guardar_en_airtable(st.session_state.pending_data)
        if st.button("❌ Cancelar"): 
            st.session_state.pending_data = None
            st.rerun()

# --- CÁLCULO DE RENTABILIDAD ---
if not df.empty:
    df_filtrado = df.copy()
    if año_seleccionado != "Todos los años":
        df_filtrado = df[df['Año'] == int(año_seleccionado)]
        st.info(f"Visualizando datos de: {año_seleccionado}")
    else:
        st.info("Visualizando acumulado histórico.")

    for col in ["Cantidad", "Precio", "Comision"]:
        df_filtrado[col] = pd.to_numeric(df_filtrado.get(col, 0.0), errors='coerce').fillna(0.0)
    
    cartera = {}
    total_div
