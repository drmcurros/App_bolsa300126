import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from pyairtable import Api
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor con Confirmación", layout="wide") 
MONEDA_BASE = "EUR" 

# --- INICIALIZAR ESTADO (MEMORIA TEMPORAL) ---
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
            else: st.error("Datos incorrectos")
        except: st.error("Faltan configurar los Secrets")
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
            precio = hist['Close'].iloc[-1]
            return nombre, precio
        return None, None
    except: return None, None

def guardar_en_airtable(record):
    """Función auxiliar para guardar y limpiar estado"""
    try:
        # Recuperamos conexión aquí para asegurar que está activa
        api = Api(st.secrets["airtable"]["api_token"])
        table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
        table.create(record)
        st.success(f"✅ Operación Guardada: {record['Ticker']}")
        st.session_state.pending_data = None # Limpiamos memoria
        st.rerun()
    except Exception as e:
        st.error(f"Error Airtable: {e}")

# --- APP PRINCIPAL ---
if not check_password(): st.stop()

# Conexión Airtable (Solo para lectura inicial)
try:
    api = Api(st.secrets["airtable"]["api_token"])
    table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
except: st.stop()

st.title("💼 Mi Cartera")

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("Registrar Movimiento")
    
    # Si NO hay nada pendiente de confirmar, mostramos el formulario normal
    if st.session_state.pending_data is None:
        with st.form("trade_form"):
            tipo = st.selectbox("Tipo", ["Compra", "Venta", "Dividendo"])
            ticker = st.text_input("Ticker (ej. AAPL)").upper().strip()
            desc_manual = st.text_input("Descripción (Opcional)", help="Fuerza un nombre si quieres.")
            moneda = st.selectbox("Moneda", ["EUR", "USD"])
            
            col_dinero, col_precio = st.columns(2)
            dinero_total = col_dinero.number_input("Importe Total", min_value=0.0, step=10.0)
            precio_manual = col_precio.number_input("Precio (Opcional)", min_value=0.0, format="%.2f")
            comision = st.number_input("Comisión", min_value=0.0, format="%.2f")
            
            submitted = st.form_submit_button("🔍 Verificar y Guardar")

            if submitted:
                if ticker and dinero_total > 0:
                    # 1. VERIFICACIÓN DOBLE
                    nombre_final = None
                    precio_final = 0.0
                    
                    with st.spinner("Verificando..."):
                        # Intento A: FMP
                        nombre_final, precio_final = get_stock_data_fmp(ticker)
                        # Intento B: Yahoo
                        if not nombre_final:
                            nombre_final, precio_final = get_stock_data_yahoo(ticker)
                    
                    # PREPARAR DATOS
                    if desc_manual: nombre_final = desc_manual
                    if not nombre_final: nombre_final = ticker # Si no existe, usamos el ticker
                    
                    if precio_manual > 0: precio_final = precio_manual
                    if not precio_final: precio_final = 0.0

                    fecha_bonita = datetime.now().strftime("%Y/%m/%d %H:%M")
                    
                    datos_registro = {
                        "Tipo": tipo, "Ticker": ticker, "Descripcion": nombre_final, 
                        "Moneda": moneda, "Cantidad": float(dinero_total),
                        "Precio": float(precio_final), "Comision": float(comision),
                        "Fecha": fecha_bonita
                    }

                    # --- EL JUEZ ---
                    # Si encontramos datos válidos (nombre o precio > 0), guardamos directo
                    if precio_final > 0:
                        guardar_en_airtable(datos_registro)
                    else:
                        # Si NO encontramos nada fiable, activamos MODO CONFIRMACIÓN
                        st.session_state.pending_data = datos_registro
                        st.rerun() # Recargamos para mostrar los botones de confirmar

    # Si HAY datos pendientes de confirmar, mostramos la alerta y botones
    else:
        st.warning(f"⚠️ **¡ALERTA!** No he encontrado el ticker **'{st.session_state.pending_data['Ticker']}'** en ninguna base de datos oficial (o su precio es 0).")
        st.write("¿Estás seguro de que está bien escrito?")
        
        col_si, col_no = st.columns(2)
        
        if col_si.button("✅ SÍ, Guardar de todas formas"):
            # Guardamos lo que había en memoria, aunque esté 'mal'
            guardar_en_airtable(st.session_state.pending_data)
            
        if col_no.button("❌ NO, Cancelar"):
            st.session_state.pending_data = None # Borramos memoria
            st.rerun()

# --- CÁLCULOS (Visor) ---
try: data = table.all()
except: data = []

if data:
    df = pd.DataFrame([x['fields'] for x in data])
    
    if 'Fecha' in df.columns:
        df['Fecha_dt'] = pd.to_datetime(df['Fecha'], errors='coerce')
        df['Fecha'] = df['Fecha_dt'].dt.strftime('%Y/%m/%d %H:%M')
        df['Fecha'] = df['Fecha'].fillna("")

    for col in ["Cantidad", "Precio", "Comision"]:
        df[col] = df.get(col, 0.0)
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    
    cartera = {}
    total_divis_eur = 0
    total_comis_eur = 0
    
    for i, row in df.iterrows():
        tipo = row.get('Tipo')
        tick = str(row.get('Ticker', 'UNKNOWN')).strip()
        raw_desc = row.get('Descripcion')
        if pd.isna(raw_desc) or not raw_desc: desc = tick
        else: desc = str(raw_desc).strip() or tick

        dinero = float(row.get('Cantidad', 0))
        precio = float(row.get('Precio', 1))
        if precio == 0: precio = 1 
        comi = float(row.get('Comision', 0))
        moneda = row.get('Moneda', 'EUR')
        
        num_acciones = dinero / precio
        fx = get_exchange_rate(moneda, MONEDA_BASE)
        total_comis_eur += (comi * fx)
        
        if tipo == "Compra":
            if tick not in cartera: cartera[tick] = {'acciones': 0, 'desc': desc, 'moneda': moneda}
            cartera[tick]['acciones'] += num_acciones
            if len(str(desc)) > len(str(cartera[tick]['desc'])): cartera[tick]['desc'] = str(desc)
        elif tipo == "Venta":
            if tick in cartera:
                cartera[tick]['acciones'] -= num_acciones
                if cartera[tick]['acciones'] < 0: cartera[tick]['acciones'] = 0
        elif tipo == "Dividendo":
            total_divis_eur += (dinero * fx)

    # --- DASHBOARD ---
    val_total = 0
    tabla = []
    
    with st.spinner("Valorando..."):
        for t, info in cartera.items():
            acc = info['acciones']
            if acc > 0.001:
                # Valoración Híbrida
                _, p_now = get_stock_data_fmp(t)
                if not p_now:
                    try: p_now = yf.Ticker(t).history(period="1d")['Close'].iloc[-1]
                    except: pass
                
                if p_now:
                    mon = info['moneda']
                    fx = get_exchange_rate(mon, MONEDA_BASE)
                    val = acc * p_now * fx
                    val_total += val
                    tabla.append({
                        "Empresa": info['desc'], "Ticker": t,
                        "Acciones": f"{acc:.4f}", "Precio": f"{p_now:.2f} {mon}",
                        "Valor (€)": val
                    })
                # Si no hay precio online, podemos mostrar el valor de coste o avisar
                # De momento solo mostramos si hay precio para no romper la tabla

    c1, c2, c3 = st.columns(3)
    c1.metric("Cartera", f"{val_total:,.2f} €")
    c2.metric("Dividendos", f"{total_divis_eur:,.2f} €")
    c3.metric("Comisiones", f"{total_comis_eur:,.2f} €")
    
    st.divider()
    if tabla:
        st.subheader("📊 Posiciones")
        st.dataframe(pd.DataFrame(tabla).style.format({"Valor (€)": "{:.2f} €"}), use_container_width=True)
    
    with st.expander("Historial"):
        if not df.empty:
            cols = [c for c in ['Fecha','Tipo','Descripcion','Ticker','Cantidad','Precio'] if c in df.columns]
            st.dataframe(df[cols].sort_values(by="Fecha", ascending=False), use_container_width=True)

else:
    st.info("Sin datos.")
