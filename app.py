import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection

# ------------------------------------------------------
# 1. CONFIGURACIÓN DE PÁGINA
# ------------------------------------------------------
st.set_page_config(page_title="Mi Cartera Cloud", layout="centered") 

# ------------------------------------------------------
# 2. SISTEMA DE LOGIN (EL PORTERO)
# ------------------------------------------------------
def check_password():
    """Retorna True si el usuario/contraseña son correctos."""

    # Si ya se validó antes, no preguntar de nuevo
    if st.session_state.get('password_correct', False):
        return True

    # Mostrar formulario de login
    st.header("🔒 Acceso Restringido")
    
    col1, col2 = st.columns(2)
    with col1:
        user_input = st.text_input("Usuario")
    with col2:
        pass_input = st.text_input("Contraseña", type="password")

    if st.button("Entrar"):
        # Verificamos contra los "Secrets" que configuraste
        usuario_real = st.secrets["credenciales"]["usuario"]
        pass_real = st.secrets["credenciales"]["password"]

        if user_input == usuario_real and pass_input == pass_real:
            st.session_state['password_correct'] = True
            st.rerun()  # Recargar página para mostrar la app
        else:
            st.error("Usuario o contraseña incorrectos")
    
    return False

# Si el login no es correcto, detenemos el código aquí.
if not check_password():
    st.stop()

# ======================================================
# A PARTIR DE AQUÍ SOLO SE EJECUTA SI ESTÁS LOGUEADO
# ======================================================

st.title("📱 Mi Cartera en la Nube")

# 3. CONEXIÓN A GOOGLE SHEETS
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Error de conexión. Revisa tus 'Secrets'.")
    st.stop()

# 4. BOTÓN DE "CERRAR SESIÓN" (Opcional, para salir)
with st.sidebar:
    st.write(f"Hola, {st.secrets['credenciales']['usuario']}")
    if st.button("Cerrar Sesión"):
        st.session_state['password_correct'] = False
        st.rerun()

# 5. FORMULARIO DE COMPRA
with st.expander("➕ Registrar Nueva Compra", expanded=False):
    with st.form("buy_form"):
        ticker = st.text_input("Ticker (ej. AAPL)").upper()
        cantidad = st.number_input("Cantidad", min_value=1.0, step=1.0)
        precio = st.number_input("Precio de compra ($)", min_value=0.1)
        fecha = st.date_input("Fecha")
        
        submitted = st.form_submit_button("Guardar en Nube")
        
        if submitted and ticker:
            try:
                df_actual = conn.read(worksheet="Cartera", ttl=0)
                nueva_fila = pd.DataFrame([{
                    "Ticker": ticker,
                    "Cantidad": cantidad,
                    "Precio": precio,
                    "Fecha": fecha
                }])
                df_updated = pd.concat([df_actual, nueva_fila], ignore_index=True)
                conn.update(worksheet="Cartera", data=df_updated)
                st.success(f"¡Guardado! {cantidad} de {ticker}")
                st.rerun()
            except Exception as e:
                st.error(f"Error al guardar: {e}")

# 6. MOSTRAR CARTERA
try:
    df_cartera = conn.read(worksheet="Cartera", usecols=[0,1,2,3], ttl=0)
    df_cartera = df_cartera.dropna(how="all")

    if not df_cartera.empty:
        st.divider()
        st.subheader("💰 Mi Portafolio en Vivo")
        
        total_valor = 0
        
        for index, row in df_cartera.iterrows():
            if pd.isna(row['Ticker']): continue
            
            simbolo = row['Ticker']
            cant = row['Cantidad']
            
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
        st.info("Tu hoja está vacía. Añade una compra arriba.")

except Exception as e:
    st.warning("No se pudo leer la hoja 'Cartera'.")
