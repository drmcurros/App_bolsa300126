import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from pyairtable import Api
from datetime import datetime
from zoneinfo import ZoneInfo

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor V7.5 (Métricas Clásicas)", layout="wide") 
MONEDA_BASE = "EUR" 

# --- ESTADO ---
if "pending_data" not in st.session_state:
    st.session_state.pending_data = None
if "adding_mode" not in st.session_state:
    st.session_state.adding_mode = False
if "reset_seed" not in st.session_state:
    st.session_state.reset_seed = 0

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

@st.cache_data(ttl=300) 
def get_exchange_rate_now(from_curr, to_curr="EUR"):
    if from_curr == to_curr: return 1.0
    try:
        pair = f"{to_curr}=X" if from_curr == "USD" else f"{from_curr}{to_curr}=X"
        return yf.Ticker(pair).history(period="1d")['Close'].iloc[-1]
    except: return 1.0

# --- LÓGICA DE LOGOS (V7.4) ---
def get_logo_url(ticker):
    clean_ticker = ticker.replace(".MC", "") 
    return f"https://financialmodelingprep.com/image-stock/{ticker}.png"

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
        precio = stock.fast_info.last_price
        nombre = stock.info.get('longName') or stock.info.get('shortName') or ticker
        if precio: return nombre, precio
    except: 
        try:
            hist = stock.history(period="1d")
            if not hist.empty:
                return ticker, hist['Close'].iloc[-1]
        except: pass
    return None, None

def guardar_en_airtable(record):
    try:
        api = Api(st.secrets["airtable"]["api_token"])
        table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
        table.create(record)
        st.success(f"✅ Guardado: {record['Ticker']}")
        st.session_state.pending_data = None
        st.session_state.adding_mode = False 
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
    st.header("Configuración")
    mis_zonas = ["Atlantic/Canary", "Europe/Madrid", "UTC"]
    mi_zona = st.selectbox("🌍 Tu Zona Horaria:", mis_zonas, index=0)
    st.divider()
    
    st.header("Filtros")
    lista_años = ["Todos los años"]
    if not df.empty and 'Año' in df.columns:
        años_disponibles = sorted(df['Año'].dropna().unique().astype(int), reverse=True)
        lista_años += list(años_disponibles)
    año_seleccionado = st.selectbox("📅 Año Fiscal:", lista_años)
    st.divider()

    if not st.session_state.adding_mode and st.session_state.pending_data is None:
        if st.button("➕ Registrar Nueva Operación", use_container_width=True, type="primary"):
            st.session_state.adding_mode = True
            st.session_state.reset_seed = int(datetime.now().timestamp())
            st.rerun()

    if st.session_state.adding_mode or st.session_state.pending_data is not None:
        st.markdown("### 📝 Datos de la Operación")
        if st.button("❌ Cerrar Formulario", use_container_width=True):
            st.session_state.adding_mode = False
            st.session_state.pending_data = None
            st.rerun()

        if st.session_state.pending_data is None:
            with st.form("trade_form"):
                tipo = st.selectbox("Tipo", ["Compra", "Venta", "Dividendo"])
                ticker = st.text_input("Ticker (ej. TSLA)").upper().strip()
                desc_manual = st.text_input("Descripción (Opcional)")
                moneda = st.selectbox("Moneda", ["EUR", "USD"])
                
                c1, c2 = st.columns(2)
                dinero_total = c1.number_input("Importe Total", min_value=0.0, step=10.0)
                precio_manual = c2.number_input("Precio/Acción", min_value=0.0, format="%.2f")
