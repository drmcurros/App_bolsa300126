import streamlit as st
import pandas as pd
import yfinance as yf
from pyairtable import Api
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor Cartera", layout="wide") 
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
        hist = yf.Ticker(pair).history(period="1d")
        return hist['Close'].iloc[-1] if not hist.empty else 1.0
    except: return 1.0

# --- APP ---
if not check_password(): st.stop()

# Conexión Airtable
try:
    api = Api(st.secrets["airtable"]["api_token"])
    table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
except: st.stop()

st.title("💼 Mi Cartera")

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("Registrar Movimiento")
    with st.form("trade_form"):
        tipo = st.selectbox("Tipo", ["Compra", "Venta", "Dividendo"])
        ticker = st.text_input("Ticker (ej. AAPL)").upper()
        
        desc_manual = st.text_input("Descripción (Opcional)", help="Si lo dejas vacío, se buscará en internet.")
        
        moneda = st.selectbox("Moneda", ["EUR", "USD"])
        
        col_dinero, col_precio = st.columns(2)
        dinero_total = col_dinero.number_input("Importe Total (Dinero)", min_value=0.0, step=10.0)
        precio_accion = col_precio.number_input("Precio Cotización", min_value=0.0, format="%.2f")
        comision = st.number_input("Comisión", min_value=0.0, format="%.2f")
        
        if st.form_submit_button("Guardar Operación"):
            if ticker and dinero_total > 0:
                # --- CAMBIO AQUÍ: FORMATO LEGIBLE ---
                # %Y = Año, %m = Mes, %d = Día, %H:%M = Hora:Minutos
                fecha_bonita = datetime.now().strftime("%Y/%m/%d %H:%M")
                # ------------------------------------
                
                nombre_final = ticker 
                if desc_manual:
                    nombre_final = desc_manual
                else:
                    try:
                        with st.spinner(f"Buscando nombre de {ticker}..."):
                            info = yf.Ticker(ticker).info
                            encontrado = info.get('longName') or info.get('shortName')
                            if encontrado: nombre_final = encontrado
                    except: pass
                
                record = {
                    "Tipo": tipo, "Ticker": ticker, "Descripcion": nombre_final, 
                    "Moneda": moneda, "Cantidad": float(dinero_total),
                    "Precio": float(precio_accion), "Comision": float(comision),
                    "Fecha": fecha_bonita
                }
                try:
                    table.create(record)
                    st.success(f"Guardado: {ticker} el {fecha_bonita}")
                    st.rerun()
                except Exception as e: st.error(f"Error: {e}")

# --- CÁLCULOS ---
try: data = table.all()
except: data = []

if data:
    df = pd.DataFrame([x['fields'] for x in data])
    
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
            if tick not in cartera:
                cartera[tick] = {'acciones': 0, 'desc': desc, 'moneda': moneda}
            
            cartera[tick]['acciones'] += num_acciones
            
            if len(str(desc)) > len(str(cartera[tick]['desc'])): 
                cartera[tick]['desc'] = str(desc)
            
        elif tipo == "Venta":
            if tick in cartera:
                cartera[tick]['acciones'] -= num_acciones
                if cartera[tick]['acciones'] < 0: cartera[tick]['acciones'] = 0
                
        elif tipo == "Dividendo":
            total_divis_eur += (dinero * fx)

    # --- DASHBOARD ---
    val_total = 0
    tabla = []
    
    with st.spinner("Calculando..."):
        for t, info in cartera.items():
            acc = info['acciones']
            if acc > 0.001:
                try:
                    p_now = yf.Ticker(t).history(period="1d")['Close'].iloc[-1]
                    mon = info['moneda']
                    fx = get_exchange_rate(mon, MONEDA_BASE)
                    val = acc * p_now * fx
                    val_total += val
                    tabla.append({
                        "Empresa": info['desc'], "Ticker": t,
                        "Acciones": f"{acc:.4f}", "Precio": f"{p_now:.2f} {mon}",
                        "Valor (€)": val
                    })
                except: pass

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
            st.dataframe(
                df[cols].sort_values(by="Fecha", ascending=False), 
                use_container_width=True
            )

else:
    st.info("Sin datos.")
