import streamlit as st
import pandas as pd
import yfinance as yf
from pyairtable import Api
from datetime import datetime, time

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor de Inversiones Auto", layout="wide") 
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

st.title("💼 Mi Cartera (Inteligente)")

# --- BARRA LATERAL: NUEVA OPERACIÓN ---
with st.sidebar:
    st.header("Registrar Movimiento")
    with st.form("trade_form"):
        tipo = st.selectbox("Tipo", ["Compra", "Venta", "Dividendo"])
        ticker = st.text_input("Ticker (ej. AAPL)").upper()
        
        # NOTA: Hemos quitado el campo manual de "Descripción"
        # Se buscará solo en internet
        
        moneda = st.selectbox("Moneda", ["EUR", "USD"])
        
        col_dinero, col_precio = st.columns(2)
        dinero_total = col_dinero.number_input("Importe Total (Dinero)", min_value=0.0, step=10.0, help="Dinero invertido o retirado")
        precio_accion = col_precio.number_input("Precio Cotización", min_value=0.0, format="%.2f", help="Precio de la acción en ese momento")
        
        comision = st.number_input("Comisión", min_value=0.0, format="%.2f")
        
        c_date, c_time = st.columns(2)
        fecha_op = c_date.date_input("Fecha")
        hora_op = c_time.time_input("Hora", value=time(9, 30))
        
        if st.form_submit_button("Guardar Operación"):
            if ticker and dinero_total > 0:
                fecha_completa = datetime.combine(fecha_op, hora_op).isoformat()
                
                # --- AUTO-COMPLETADO DE NOMBRE ---
                nombre_empresa = ticker # Por defecto usamos el ticker si falla internet
                try:
                    with st.spinner(f"Buscando nombre de {ticker} en internet..."):
                        info_stock = yf.Ticker(ticker).info
                        # Intentamos coger el nombre largo, si no el corto
                        nombre_empresa = info_stock.get('longName') or info_stock.get('shortName') or ticker
                except Exception as e:
                    st.warning(f"No se pudo encontrar el nombre oficial. Se usará {ticker}.")
                
                record = {
                    "Tipo": tipo,
                    "Ticker": ticker,
                    "Descripcion": nombre_empresa, # Aquí va el nombre automático
                    "Moneda": moneda,
                    "Cantidad": float(dinero_total),
                    "Precio": float(precio_accion),
                    "Comision": float(comision),
                    "Fecha": fecha_completa
                }
                
                try:
                    table.create(record)
                    st.success(f"Guardado: {tipo} de {nombre_empresa} ({ticker})")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error Airtable: {e}")

# --- CÁLCULOS ---
try: data = table.all()
except: data = []

if data:
    df = pd.DataFrame([x['fields'] for x in data])
    
    # Rellenar columnas
    for col in ["Cantidad", "Precio", "Comision"]:
        if col not in df.columns: df[col] = 0.0
        else: df[col] = df[col].fillna(0.0)
    
    cartera = {}
    total_divis_eur = 0
    total_comis_eur = 0
    
    for i, row in df.iterrows():
        tipo = row.get('Tipo')
        tick = row.get('Ticker')
        # Usamos la descripción guardada en Airtable
        desc = row.get('Descripcion', tick) 
        
        dinero_operacion = row.get('Cantidad', 0)
        precio_momento = row.get('Precio', 1)
        comi = row.get('Comision', 0)
        moneda = row.get('Moneda', 'EUR')
        
        num_acciones = (dinero_operacion / precio_momento) if precio_momento > 0 else 0
        
        fx = get_exchange_rate(moneda, MONEDA_BASE)
        total_comis_eur += (comi * fx)
        
        if tipo == "Compra":
            if tick not in cartera:
                cartera[tick] = {'acciones': 0, 'desc': desc, 'moneda': moneda}
            cartera[tick]['acciones'] += num_acciones
            # Actualizamos descripción por si ha mejorado
            if len(desc) > len(cartera[tick]['desc']): 
                cartera[tick]['desc'] = desc
            
        elif tipo == "Venta":
            if tick in cartera:
                cartera[tick]['acciones'] -= num_acciones
                if cartera[tick]['acciones'] < 0: cartera[tick]['acciones'] = 0
                
        elif tipo == "Dividendo":
            total_divis_eur += (dinero_operacion * fx)

    # --- DASHBOARD ---
    valor_total_cartera = 0
    tabla_final = []
    
    with st.spinner("Actualizando valoraciones..."):
        for tick, data_stock in cartera.items():
            acc = data_stock['acciones']
            if acc > 0.001:
                try:
                    curr_price = yf.Ticker(tick).history(period="1d")['Close'].iloc[-1]
                    moneda_act = data_stock['moneda']
                    fx_now = get_exchange_rate(moneda_act, MONEDA_BASE)
                    val_eur = acc * curr_price * fx_now
                    valor_total_cartera += val_eur
                    
                    tabla_final.append({
                        "Empresa": data_stock['desc'],
                        "Ticker": tick,
                        "Acciones": f"{acc:.4f}",
                        "Precio Mercado": f"{curr_price:.2f} {moneda_act}",
                        "Valor Total (€)": val_eur
                    })
                except: pass

    c1, c2, c3 = st.columns(3)
    c1.metric("Valor Cartera", f"{valor_total_cartera:,.2f} €")
    c2.metric("Dividendos", f"{total_divis_eur:,.2f} €")
    c3.metric("Comisiones", f"{total_comis_eur:,.2f} €")
    
    st.divider()
    if tabla_final:
        df_show = pd.DataFrame(tabla_final)
        st.subheader("📊 Posiciones Abiertas")
        st.dataframe(
            df_show.style.format({"Valor Total (€)": "{:.2f} €"}), 
            use_container_width=True, 
            hide_index=True
        )
    
    with st.expander("📜 Historial Detallado"):
        # Mostramos también la columna Descripcion en el historial
        cols_orden = ['Fecha', 'Tipo', 'Descripcion', 'Ticker', 'Cantidad', 'Precio', 'Moneda']
        # Filtramos solo las columnas que existen
        cols_existentes = [c for c in cols_orden if c in df.columns]
        st.dataframe(df[cols_existentes].sort_values(by="Fecha", ascending=False), use_container_width=True)

else:
    st.info("No hay datos. Añade una operación.")
