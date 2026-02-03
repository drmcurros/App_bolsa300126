import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from pyairtable import Api
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor API Pro", layout="wide") 
MONEDA_BASE = "EUR" 

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
    """
    Conecta con la API oficial de Financial Modeling Prep.
    Devuelve: (Nombre, Precio) o (None, None) si falla.
    """
    try:
        api_key = st.secrets["fmp"]["api_key"]
        url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey={api_key}"
        response = requests.get(url, timeout=5)
        data = response.json()
        
        if data and len(data) > 0:
            nombre = data[0].get('companyName')
            precio = data[0].get('price')
            return nombre, precio
        return None, None
    except Exception as e:
        return None, None

# --- APP ---
if not check_password(): st.stop()

try:
    api = Api(st.secrets["airtable"]["api_token"])
    table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
except: st.stop()

st.title("💼 Mi Cartera (Motor FMP)")

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("Registrar Movimiento")
    with st.form("trade_form"):
        tipo = st.selectbox("Tipo", ["Compra", "Venta", "Dividendo"])
        ticker = st.text_input("Ticker (ej. AAPL)").upper().strip()
        
        desc_manual = st.text_input("Descripción (Opcional)", help="Escribe aquí si quieres forzar un nombre.")
        moneda = st.selectbox("Moneda", ["EUR", "USD"])
        
        col_dinero, col_precio = st.columns(2)
        dinero_total = col_dinero.number_input("Importe Total", min_value=0.0, step=10.0)
        
        # El precio lo intentaremos autocompletar, pero dejamos que lo edites
        precio_manual = col_precio.number_input("Precio (Opcional si buscas)", min_value=0.0, format="%.2f", help="Si pones 0, intentaré coger el precio real.")
        comision = st.number_input("Comisión", min_value=0.0, format="%.2f")
        
        # Botón de búsqueda previa (para ver si existe sin guardar)
        check_btn = st.form_submit_button("🔍 Verificar y Guardar")

        if check_btn:
            if ticker and dinero_total > 0:
                
                # 1. VERIFICACIÓN ROBUSTA CON API OFICIAL
                nombre_api = None
                precio_api = 0.0
                es_valido = False
                
                with st.spinner(f"Consultando base de datos oficial para {ticker}..."):
                    nombre_api, precio_api = get_stock_data_fmp(ticker)
                    
                    if nombre_api:
                        es_valido = True
                    else:
                        # Plan B: Yahoo (por si FMP falla o se acaban los créditos)
                        try:
                            info = yf.Ticker(ticker).info
                            # Si Yahoo devuelve algo con sentido, lo damos por bueno
                            if 'regularMarketPrice' in info or 'currentPrice' in info:
                                es_valido = True
                                nombre_api = info.get('longName', ticker)
                                precio_api = info.get('currentPrice', 0)
                        except: pass

                # 2. DECISIÓN DEL PORTERO
                if not es_valido and not desc_manual:
                    st.error(f"❌ Error: El ticker '{ticker}' no existe en la base de datos oficial. Verifica que esté bien escrito.")
                    st.stop()
                
                # 3. PREPARAR DATOS
                # Nombre: Manual > API > Ticker
                nombre_final = desc_manual if desc_manual else (nombre_api if nombre_api else ticker)
                
                # Precio: Manual > API > 0
                precio_final = precio_manual if precio_manual > 0 else (precio_api if precio_api else 0)
                
                if precio_final == 0:
                    st.warning("⚠️ No se encontró precio online. Por favor introduce el precio manualmente.")
                    st.stop()

                fecha_bonita = datetime.now().strftime("%Y/%m/%d %H:%M")
                
                record = {
                    "Tipo": tipo, "Ticker": ticker, "Descripcion": nombre_final, 
                    "Moneda": moneda, "Cantidad": float(dinero_total),
                    "Precio": float(precio_final), "Comision": float(comision),
                    "Fecha": fecha_bonita
                }
                
                try:
                    table.create(record)
                    st.success(f"✅ Guardado: {nombre_final} a {precio_final} {moneda}")
                    st.rerun()
                except Exception as e: st.error(f"Error Airtable: {e}")

# --- CÁLCULOS ---
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
        if pd.isna(raw_desc) or raw_desc is None: desc = tick
        else:
            desc = str(raw_desc).strip()
            if desc == "": desc = tick

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
    
    with st.spinner("Valorando cartera (FMP + Yahoo)..."):
        for t, info in cartera.items():
            acc = info['acciones']
            if acc > 0.001:
                # Intentamos obtener precio actual
                # 1. Probamos FMP (más rápido y fiable)
                _, p_now = get_stock_data_fmp(t)
                
                # 2. Si falla FMP, probamos Yahoo
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
