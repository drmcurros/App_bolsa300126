import streamlit as st
import pandas as pd
import yfinance as yf
from pyairtable import Api

# ------------------------------------------------------
# 1. CONFIGURACIÓN Y LOGIN
# ------------------------------------------------------
st.set_page_config(page_title="Mi Cartera Airtable", layout="centered") 

def check_password():
    if st.session_state.get('password_correct', False):
        return True

    st.header("🔒 Acceso Restringido")
    col1, col2 = st.columns(2)
    with col1: user_input = st.text_input("Usuario")
    with col2: pass_input = st.text_input("Contraseña", type="password")

    if st.button("Entrar"):
        try:
            # Verificamos credenciales
            if (user_input == st.secrets["credenciales"]["usuario"] and 
                pass_input == st.secrets["credenciales"]["password"]):
                st.session_state['password_correct'] = True
                st.rerun()
            else:
                st.error("Datos incorrectos")
        except Exception:
            st.error("⚠️ Configura los [secrets] en Streamlit primero.")
            
    return False

if not check_password():
    st.stop()

# ======================================================
# CONEXIÓN CON AIRTABLE
# ======================================================
try:
    # Conectamos usando las claves de Secrets
    api = Api(st.secrets["airtable"]["api_token"])
    table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
except Exception as e:
    st.error("Error conectando con Airtable. Revisa tus Secrets.")
    st.stop()

st.title("📱 Mi Cartera (Airtable)")

# Botón salir
with st.sidebar:
    st.write(f"Usuario: {st.secrets['credenciales']['usuario']}")
    if st.button("Cerrar Sesión"):
        st.session_state['password_correct'] = False
        st.rerun()

# ------------------------------------------------------
# 2. REGISTRAR OPERACIONES
# ------------------------------------------------------
with st.expander("➕ Registrar Nueva Compra", expanded=False):
    with st.form("buy_form"):
        ticker = st.text_input("Ticker (ej. AAPL)").upper()
        cantidad = st.number_input("Cantidad", min_value=1.0, step=1.0)
        precio = st.number_input("Precio de compra ($)", min_value=0.1)
        fecha = st.date_input("Fecha") # Airtable prefiere formato YYYY-MM-DD
        
        submitted = st.form_submit_button("Guardar")
        
        if submitted and ticker:
            try:
                # Enviamos los datos a Airtable
                table.create({
                    "Ticker": ticker,
                    "Cantidad": int(cantidad),
                    "Precio": float(precio),
                    "Fecha": str(fecha)
                })
                st.success(f"¡Guardado en la nube! {ticker}")
                st.rerun()
            except Exception as e:
                st.error(f"Error escribiendo en Airtable: {e}")

# ------------------------------------------------------
# 3. VISUALIZAR CARTERA
# ------------------------------------------------------
try:
    # Descargamos todos los datos de Airtable
    data = table.all()
    
    # Convertimos el formato extraño de Airtable a un DataFrame limpio
    if data:
        df_raw = [x['fields'] for x in data] # Extraemos solo los campos
        df_cartera = pd.DataFrame(df_raw)
        
        # Aseguramos que existan las columnas aunque estén vacías
        required_cols = ["Ticker", "Cantidad", "Precio"]
        for col in required_cols:
            if col not in df_cartera.columns:
                df_cartera[col] = 0

        st.divider()
        st.subheader("💰 Mi Portafolio en Vivo")
        
        total_valor = 0
        
        for index, row in df_cartera.iterrows():
            simbolo = row.get('Ticker') # .get evita errores si la celda está vacía
            cant = row.get('Cantidad', 0)
            
            if not simbolo: continue
            
            try:
                stock = yf.Ticker(simbolo)
                hist = stock.history(period="1d")
                if not hist.empty:
                    precio_actual = hist['Close'].iloc[-1]
                    valor_posicion = precio_actual * cant
                    total_valor += valor_posicion
                    
                    st.info(f"**{simbolo}**: {cant} acc. a ${precio_actual:.2f} | Total: ${valor_posicion:.2f}")
            except Exception:
                pass
        
        st.metric(label="Valor Total Cartera", value=f"${total_valor:,.2f}")
        
        with st.expander("Ver tabla bruta"):
            st.dataframe(df_cartera)
            
    else:
        st.info("Tu base de datos en Airtable está vacía.")

except Exception as e:
    st.warning("Error leyendo datos.")
    st.write(e)
