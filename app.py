import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection

# 1. Configuración de página para móvil
st.set_page_config(page_title="Mi Cartera Cloud", layout="centered") 

# 2. Conexión a la Base de Datos (Google Sheets)
conn = st.connection("gsheets", type=GSheetsConnection)

st.title("📱 Mi Cartera en la Nube")

# 3. Formulario de COMPRA (Para guardar datos)
with st.expander("➕ Registrar Nueva Compra"):
    with st.form("buy_form"):
        ticker = st.text_input("Ticker (ej. AAPL)").upper()
        cantidad = st.number_input("Cantidad", min_value=1.0, step=1.0)
        precio = st.number_input("Precio de compra ($)", min_value=0.1)
        fecha = st.date_input("Fecha")
        
        submitted = st.form_submit_button("Guardar en Nube")
        
        if submitted:
            # Aquí iría la lógica para escribir en Google Sheets
            # data_nueva = pd.DataFrame(...)
            # conn.update(data=data_nueva)
            st.success(f"Guardado: {cantidad} de {ticker} a ${precio}")

# 4. Lectura de Datos (Tu Cartera Actual)
try:
    # Leemos tu hoja de cálculo en vivo
    df_cartera = conn.read(worksheet="Hoja 1")
    
    if not df_cartera.empty:
        st.subheader("💰 Mi Portafolio")
        
        # Calcular valor actual en vivo
        total_valor = 0
        for index, row in df_cartera.iterrows():
            ticker_data = yf.Ticker(row['Ticker']).history(period="1d")
            precio_actual = ticker_data['Close'].iloc[-1]
            valor_posicion = precio_actual * row['Cantidad']
            total_valor += valor_posicion
            
            # Tarjeta visual para móvil
            st.info(f"**{row['Ticker']}**: {row['Cantidad']} acciones | Valor: ${valor_posicion:.2f}")

        st.metric(label="Valor Total Cartera", value=f"${total_valor:,.2f}")

except Exception as e:
    st.warning("Conecta tu Google Sheet para ver los datos.")