import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import altair as alt
from pyairtable import Api
from datetime import datetime
from zoneinfo import ZoneInfo
from fpdf import FPDF 

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor V14.2 (Colores Fila)", layout="wide") 
MONEDA_BASE = "EUR" 

# --- ESTADO ---
if "pending_data" not in st.session_state:
    st.session_state.pending_data = None
if "adding_mode" not in st.session_state:
    st.session_state.adding_mode = False
if "reset_seed" not in st.session_state:
    st.session_state.reset_seed = 0
if "ticker_detalle" not in st.session_state:
    st.session_state.ticker_detalle = None

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

def get_logo_url(ticker):
    return f"https://financialmodelingprep.com/image-stock/{ticker}.png"

def get_stock_data_fmp(ticker):
    try:
        api_key = st.secrets["fmp"]["api_key"]
        url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey={api_key}"
        response = requests.get(url, timeout=3)
        data = response.json()
        if data and len(data) > 0:
            return data[0].get('companyName'), data[0].get('price'), data[0].get('description')
        return None, None, None
    except: return None, None, None

def get_stock_data_yahoo(ticker):
    try:
        stock = yf.Ticker(ticker)
        precio = stock.fast_info.last_price
        nombre = stock.info.get('longName') or stock.info.get('shortName') or ticker
        desc = stock.info.get('longBusinessSummary') or "Sin descripción."
        if precio: return nombre, precio, desc
    except: 
        try:
            hist = stock.history(period="1d")
            if not hist.empty:
                return ticker, hist['Close'].iloc[-1], "Sin descripción."
        except: pass
    return None, None, None

def guardar_en_airtable(record):
    try:
        api = Api(st.secrets["airtable"]["api_token"])
        table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
        table.create(record)
        st.success(f"✅ Guardado: {record['Ticker']}")
        st.session_state.pending_data = None
        st.session_state.adding_mode = False 
        st.rerun()
    except Exception as e: st.error(f"Error guardando: {e}")

def generar_pdf_historial(dataframe, titulo):
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 12)
            self.cell(0, 10, titulo, 0, 1, 'C')
            self.ln(5)
        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 10, f'Pagina {self.page_no()}', 0, 0, 'C')

    pdf = PDF(orientation='L') 
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    
    cols_map = {
        'Fecha_str': ('Fecha', 35),
        'Tipo': ('Tipo', 25),
        'Ticker': ('Ticker', 20),
        'Descripcion': ('Empresa', 60),
        'Cantidad': ('Importe', 30),
        'Precio': ('Precio', 25),
        'Moneda': ('Div', 15),
        'Comision': ('Com.', 20)
    }
    
    pdf.set_fill_color(200, 220, 255)
    pdf.set_font("Arial", 'B', 10)
    
    cols_validas = []
    for k, (nombre_pdf, ancho) in cols_map.items():
        if k in dataframe.columns:
            cols_validas.append((k, nombre_pdf, ancho))
            pdf.cell(ancho, 10, nombre_pdf, 1, 0, 'C', 1)
    pdf.ln()

    pdf.set_font("Arial", size=9)
    for _, row in dataframe.iterrows():
        for col_key, _, ancho in cols_validas:
            valor = str(row[col_key])
            valor = valor.replace("€", "EUR").encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(ancho, 10, valor, 1, 0, 'C')
        pdf.ln()
        
    return pdf.output(dest='S').encode('latin-1')

# --- APP INICIO ---
if not check_password(): st.stop()

try:
    api = Api(st.secrets["airtable"]["api_token"])
    table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
except Exception as e:
    st.error(f"Error conectando a Airtable: {e}")
    st.stop()

# 1. CARGA DATOS
try: data = table.all()
except: data = []

df = pd.DataFrame()
if data:
    df = pd.DataFrame([x['fields'] for x in data])
    df.columns = df.columns.str.strip() 

    if 'Fecha' in df.columns:
        df['Fecha_dt'] = pd.to_datetime(df['Fecha'], errors='coerce')
        df['Año'] = df['Fecha_dt'].dt.year 
        df['Fecha_str'] = df['Fecha_dt'].dt.strftime('%Y/%m/%d %H:%M').fillna("")
    else: 
        df['Año'] = datetime.now().year
        df['Fecha_dt'] = datetime.now()

    cols_numericas = ["Cantidad", "Precio", "Comision"]
    for col in cols_numericas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

# 2. BARRA LATERAL
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
    
    st.write("")
    ver_solo_activas = st.checkbox("👁️ Ocultar posiciones cerradas (0 acciones)", value=False)
    
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
                comision = st.number_input("Comisión", min_value=0.0, format="%.2f")
                
                st.markdown("---")
                st.write(f"📆 **Fecha ({mi_zona}):**")
                ahora_local = datetime.now(ZoneInfo(mi_zona))
                
                cd, ct = st.columns(2)
                f_in = cd.date_input("Día", value=ahora_local, key=f"d_{st.session_state.reset_seed}")
                h_in = ct.time_input("Hora", value=ahora_local, key=f"t_{st.session_state.reset_seed}")
                
                if st.form_submit_button("🔍 Validar y Guardar"):
                    if ticker and dinero_total > 0:
                        nom, pre = None, 0.0
                        with st.spinner("Consultando precio..."):
                            nom, pre = get_stock_data_fmp(ticker)
                            if not nom: nom, pre
