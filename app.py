import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from pyairtable import Api
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor Histórico", layout="wide") 
MONEDA_BASE = "EUR" 

# --- INICIALIZAR ESTADO ---
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
    """
    Necesitamos el cambio de divisa SOLO para convertir los dólares 
    que metes/sacas a Euros y sumarlos bien.
    """
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
    try:
        api = Api(st.secrets["airtable"]["api_token"])
        table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
        table.create(record)
        st.success(f"✅ Guardado: {record['Ticker']}")
        st.session_state.pending_data = None
        st.rerun()
    except Exception as e:
        st.error(f"Error Airtable: {e}")

# --- APP ---
if not check_password(): st.stop()

try:
    api = Api(st.secrets["airtable"]["api_token"])
    table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
except: st.stop()

st.title("💼 Mi Cartera (Saldo Invertido)")

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("Registrar Movimiento")
    
    if st.session_state.pending_data is None:
        with st.form("trade_form"):
            tipo = st.selectbox("Tipo", ["Compra", "Venta", "Dividendo"])
            ticker = st.text_input("Ticker (ej. AAPL)").upper().strip()
            desc_manual = st.text_input("Descripción (Opcional)")
            moneda = st.selectbox("Moneda", ["EUR", "USD"])
            
            col_dinero, col_precio = st.columns(2)
            dinero_total = col_dinero.number_input("Importe Total", min_value=0.0, step=10.0)
            precio_manual = col_precio.number_input("Precio (Opcional)", min_value=0.0, format="%.2f")
            comision = st.number_input("Comisión", min_value=0.0, format="%.2f")
            
            submitted = st.form_submit_button("🔍 Verificar y Guardar")

            if submitted:
                if ticker and dinero_total > 0:
                    nombre_final = None
                    precio_final = 0.0
                    
                    with st.spinner("Verificando existencia..."):
                        nombre_final, precio_final = get_stock_data_fmp(ticker)
                        if not nombre_final:
                            nombre_final, precio_final = get_stock_data_yahoo(ticker)
                    
                    if desc_manual: nombre_final = desc_manual
                    if not nombre_final: nombre_final = ticker
                    
                    if precio_manual > 0: precio_final = precio_manual
                    if not precio_final: precio_final = 0.0

                    fecha_bonita = datetime.now().strftime("%Y/%m/%d %H:%M")
                    
                    datos = {
                        "Tipo": tipo, "Ticker": ticker, "Descripcion": nombre_final, 
                        "Moneda": moneda, "Cantidad": float(dinero_total),
                        "Precio": float(precio_final), "Comision": float(comision),
                        "Fecha": fecha_bonita
                    }

                    if precio_final > 0:
                        guardar_en_airtable(datos)
                    else:
                        st.session_state.pending_data = datos
                        st.rerun()
    else:
        st.warning(f"⚠️ No encuentro '{st.session_state.pending_data['Ticker']}'. ¿Confirmar?")
        c1, c2 = st.columns(2)
        if c1.button("✅ Sí, Guardar"): guardar_en_airtable(st.session_state.pending_data)
        if c2.button("❌ Cancelar"): 
            st.session_state.pending_data = None
            st.rerun()

# --- CÁLCULOS HISTÓRICOS PUROS ---
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
    
    # Pre-calculamos tipos de cambio actuales para homogeneizar saldos
    # (Necesario para sumar USD y EUR en una sola cartera)
    fx_cache = {}

    def get_fx_cached(moneda):
        if moneda == MONEDA_BASE: return 1.0
        if moneda not in fx_cache:
            fx_cache[moneda] = get_exchange_rate(moneda, MONEDA_BASE)
        return fx_cache[moneda]

    for i, row in df.iterrows():
        tipo = row.get('Tipo')
        tick = str(row.get('Ticker', 'UNKNOWN')).strip()
        desc = str(row.get('Descripcion', tick)).strip() or tick
        
        dinero_bruto = float(row.get('Cantidad', 0)) # Dinero de la operación
        precio = float(row.get('Precio', 1)) 
        if precio <= 0: precio = 1
        
        moneda = row.get('Moneda', 'EUR')
        comi = float(row.get('Comision', 0))
        
        # Obtenemos cambio para convertir todo a EUR base
        fx = get_fx_cached(moneda)
        dinero_eur = dinero_bruto * fx
        
        # Calculamos acciones SOLO para saber si la posición sigue abierta
        num_acciones = dinero_bruto / precio
        
        total_comis_eur += (comi * fx)
        
        if tipo == "Compra":
            if tick not in cartera: 
                cartera[tick] = {'acciones': 0, 'saldo_neto_eur': 0.0, 'desc': desc}
            
            cartera[tick]['acciones'] += num_acciones
            # SUMAMOS dinero invertido
            cartera[tick]['saldo_neto_eur'] += dinero_eur
            
            if len(desc) > len(cartera[tick]['desc']): cartera[tick]['desc'] = desc
            
        elif tipo == "Venta":
            if tick in cartera:
                cartera[tick]['acciones'] -= num_acciones
                if cartera[tick]['acciones'] < 0: cartera[tick]['acciones'] = 0
                
                # RESTAMOS dinero recuperado (Lógica: Inversión - Retorno)
                cartera[tick]['saldo_neto_eur'] -= dinero_eur
                
        elif tipo == "Dividendo":
            total_divis_eur += dinero_eur

    # --- VISUALIZACIÓN ---
    
    saldo_total_cartera = 0
    tabla_final = []
    
    # Filtramos para mostrar: Tickers donde aún tengamos acciones > 0
    for t, info in cartera.items():
        if info['acciones'] > 0.001:
            saldo_vivo = info['saldo_neto_eur']
            saldo_total_cartera += saldo_vivo
            
            tabla_final.append({
                "Empresa": info['desc'],
                "Ticker": t,
                "Acciones (Est.)": f"{info['acciones']:.4f}",
                "Saldo Invertido (€)": saldo_vivo
            })

    # BLOQUE DE MÉTRICAS (Totalmente basado en histórico)
    c1, c2, c3 = st.columns(3)
    c1.metric("Dinero en Cartera", f"{saldo_total_cartera:,.2f} €", help="Total invertido - Total retirado")
    c2.metric("Dividendos Totales", f"{total_divis_eur:,.2f} €")
    c3.metric("Comisiones Pagadas", f"{total_comis_eur:,.2f} €")
    
    st.divider()
    
    if tabla_final:
        st.subheader("📊 ACCIONES EN CARTERA actual")
        df_tabla = pd.DataFrame(tabla_final)
        
        # Formato simple, sin colores de mercado ni precios online
        st.dataframe(
            df_tabla.style.format({"Saldo Invertido (€)": "{:.2f} €"}), 
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No tienes acciones en cartera (Saldo de acciones = 0).")
    
    with st.expander("Historial Completo"):
        cols = [c for c in ['Fecha','Tipo','Descripcion','Ticker','Cantidad','Precio','Moneda'] if c in df.columns]
        st.dataframe(df[cols].sort_values(by="Fecha", ascending=False), use_container_width=True)

else:
    st.info("Sin datos.")
