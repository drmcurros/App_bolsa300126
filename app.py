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
        if user == st.secrets["credenciales"]["usuario"] and pw == st.secrets["credenciales"]["password"]:
            st.session_state['password_correct'] = True
            st.rerun()
        else: st.error("Incorrecto")
    return False

def get_exchange_rate(from_currency, to_currency):
    """Devuelve el tipo de cambio actual (ej. de USD a EUR)."""
    if from_currency == to_currency: return 1.0
    try:
        # Yahoo usa el formato "EUR=X" para USD->EUR
        pair = f"{to_currency}=X" if from_currency == "USD" else f"{from_currency}{to_currency}=X"
        ticker = yf.Ticker(pair)
        hist = ticker.history(period="1d")
        return hist['Close'].iloc[-1]
    except:
        return 1.0 # Si falla, asumimos 1 a 1 para no romper la app

# --- INICIO ---
if not check_password(): st.stop()

# Conexión Airtable
try:
    api = Api(st.secrets["airtable"]["api_token"])
    table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
except: st.stop()

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
                table.create({
                    "Tipo": tipo, "Ticker": ticker, "Moneda": moneda,
                    "Cantidad": float(cantidad), "Precio": float(precio),
                    "Comision": float(comision), "Fecha": str(fecha)
                })
                st.success("Guardado ✅")
                st.rerun()

# --- CÁLCULOS (EL CEREBRO) ---
data = table.all()
if data:
    df = pd.DataFrame([x['fields'] for x in data])
    
    # Asegurar columnas numéricas
    for col in ["Cantidad", "Precio", "Comision"]:
        df[col] = df.get(col, 0).fillna(0)

    # Variables para totales
    cartera = {} # Diccionario para guardar acciones vivas: {AAPL: 10, TSLA: 5}
    total_dividendos = 0
    total_comisiones = 0
    
    # Procesar histórico (FIFO lógico simplificado)
    for i, row in df.iterrows():
        t = row.get('Ticker')
        tipo = row.get('Tipo')
        cant = row.get('Cantidad', 0)
        comi = row.get('Comision', 0)
        moneda_origen = row.get('Moneda', 'EUR')
        
        # Obtenemos cambio para sumar comisiones/dividendos en EUR
        fx = get_exchange_rate(moneda_origen, MONEDA_BASE)
        
        total_comisiones += (comi * fx)
        
        if tipo == "Compra":
            cartera[t] = cartera.get(t, {'cant': 0, 'moneda': moneda_origen})
            cartera[t]['cant'] += cant
            cartera[t]['moneda'] = moneda_origen # Guardamos moneda del activo
            
        elif tipo == "Venta":
            if t in cartera:
                cartera[t]['cant'] -= cant
                
        elif tipo == "Dividendo":
            # Precio aquí suele ser el total cobrado o por acción? 
            # Asumiremos Precio = Total Cobrado bruto en este form simple
            total_dividendos += (row.get('Precio', 0) * fx)

    # --- VISUALIZACIÓN ---
    
    st.subheader("📊 Resumen Global")
    col1, col2, col3 = st.columns(3)
    
    valor_cartera_eur = 0
    lista_activos = []

    # Calcular valor actual de acciones vivas
    with st.spinner("Actualizando precios de mercado..."):
        for tick, info in cartera.items():
            cantidad_viva = info['cant']
            
            if cantidad_viva > 0.01: # Solo mostramos si tenemos algo
                moneda_activo = info['moneda']
                
                # Buscar precio actual
                try:
                    stock = yf.Ticker(tick)
                    precio_actual = stock.history(period="1d")['Close'].iloc[-1]
                    
                    # Convertir a Euros
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
    st.subheader("🔍 Desglose de Activos")
    st.dataframe(pd.DataFrame(lista_activos), use_container_width=True)
    
    with st.expander("Ver Histórico de Operaciones"):
        st.dataframe(df.sort_values(by="Fecha", ascending=False))

else:
    st.info("Añade tu primera operación en la barra lateral.")
