import streamlit as st
import pandas as pd
import yfinance as yf
from pyairtable import Api

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Mi Patrimonio Pro", layout="wide") 
MONEDA_BASE = "EUR"  # La moneda en la que quieres ver tu total

# --- FUNCIONES AUXILIARES ---
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
        except: st.error("Revisa tus Secrets")
    return False

def get_exchange_rate(from_currency, to_currency):
    """Devuelve el tipo de cambio actual (ej. de USD a EUR)."""
    if from_currency == to_currency: return 1.0
    try:
        pair = f"{to_currency}=X" if from_currency == "USD" else f"{from_currency}{to_currency}=X"
        ticker = yf.Ticker(pair)
        hist = ticker.history(period="1d")
        if not hist.empty:
            return hist['Close'].iloc[-1]
        return 1.0
    except:
        return 1.0 

# --- INICIO ---
if not check_password(): st.stop()

# Conexión Airtable
try:
    api = Api(st.secrets["airtable"]["api_token"])
    table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
except: 
    st.error("Error conectando a Airtable. Revisa el ID de la base y el Token.")
    st.stop()

st.title(f"🌍 Mi Patrimonio ({MONEDA_BASE})")

# --- BARRA LATERAL: NUEVA OPERACIÓN ---
with st.sidebar:
    st.header("Registrar Operación")
    with st.form("new_trade"):
        tipo = st.selectbox("Tipo", ["Compra", "Venta", "Dividendo"])
        ticker = st.text_input("Ticker (ej. AAPL)").upper()
        moneda = st.selectbox("Moneda del Activo", ["EUR", "USD"])
        
        c1, c2 = st.columns(2)
        cantidad = c1.number_input("Cantidad", min_value=0.0, step=1.0)
        precio = c2.number_input("Precio/Acción", min_value=0.0)
        
        c3, c4 = st.columns(2)
        comision = c3.number_input("Comisión Total", min_value=0.0)
        fecha = c4.date_input("Fecha")
        
        if st.form_submit_button("Guardar"):
            if ticker:
                try:
                    table.create({
                        "Tipo": tipo, "Ticker": ticker, "Moneda": moneda,
                        "Cantidad": float(cantidad), "Precio": float(precio),
                        "Comision": float(comision), "Fecha": str(fecha)
                    })
                    st.success("Guardado ✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error guardando: {e}")

# --- CÁLCULOS (EL CEREBRO) ---
try:
    data = table.all()
except:
    data = []

if data:
    df = pd.DataFrame([x['fields'] for x in data])
    
    # --- CORRECCIÓN DEL ERROR AQUÍ ---
    # Verificamos si las columnas existen. Si no, las creamos con ceros.
    cols_numericas = ["Cantidad", "Precio", "Comision"]
    for col in cols_numericas:
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = df[col].fillna(0.0)

    # Variables para totales
    cartera = {} 
    total_dividendos = 0
    total_comisiones = 0
    
    # Procesar histórico
    for i, row in df.iterrows():
        t = row.get('Ticker')
        tipo = row.get('Tipo')
        cant = row.get('Cantidad', 0)
        comi = row.get('Comision', 0)
        moneda_origen = row.get('Moneda', 'EUR')
        
        # Obtenemos cambio
        fx = get_exchange_rate(moneda_origen, MONEDA_BASE)
        
        total_comisiones += (comi * fx)
        
        if tipo == "Compra":
            cartera[t] = cartera.get(t, {'cant': 0, 'moneda': moneda_origen})
            cartera[t]['cant'] += cant
            cartera[t]['moneda'] = moneda_origen 
            
        elif tipo == "Venta":
            if t in cartera:
                cartera[t]['cant'] -= cant
                # Evitar negativos por error de datos
                if cartera[t]['cant'] < 0: cartera[t]['cant'] = 0
                
        elif tipo == "Dividendo":
            total_dividendos += (row.get('Precio', 0) * fx)

    # --- VISUALIZACIÓN ---
    
    st.subheader("📊 Resumen Global")
    col1, col2, col3 = st.columns(3)
    
    valor_cartera_eur = 0
    lista_activos = []

    with st.spinner("Actualizando precios de mercado..."):
        for tick, info in cartera.items():
            cantidad_viva = info['cant']
            
            if cantidad_viva > 0.01: 
                moneda_activo = info['moneda']
                
                try:
                    stock = yf.Ticker(tick)
                    # Intentamos obtener precio, si falla usamos 0
                    hist = stock.history(period="1d")
                    if not hist.empty:
                        precio_actual = hist['Close'].iloc[-1]
                    else:
                        precio_actual = 0
                    
                    fx_rate = get_exchange_rate(moneda_activo, MONEDA_BASE)
                    valor_posicion_eur = cantidad_viva * precio_actual * fx_rate
                    
                    valor_cartera_eur += valor_posicion_eur
                    
                    lista_activos.append({
                        "Ticker": tick,
                        "Acciones": cantidad_viva,
                        "Precio": f"{precio_actual:.2f} {moneda_activo}",
                        "Valor (EUR)": round(valor_posicion_eur, 2)
                    })
                except:
                    pass

    col1.metric("Valor Cartera", f"{valor_cartera_eur:,.2f} €")
    col2.metric("Dividendos Cobrados", f"{total_dividendos:,.2f} €")
    col3.metric("Comisiones Pagadas", f"{total_comisiones:,.2f} €", delta_color="inverse")
    
    st.divider()
    if lista_activos:
        st.subheader("🔍 Desglose de Activos")
        st.dataframe(pd.DataFrame(lista_activos), use_container_width=True)
    
    with st.expander("Ver Histórico de Operaciones"):
        st.dataframe(df)

else:
    st.info("Añade tu primera operación en la barra lateral.")
