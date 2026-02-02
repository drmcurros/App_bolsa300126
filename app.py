import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection

# 1. Configuración básica
st.set_page_config(page_title="Mi Cartera Cloud", layout="centered") 
st.title("📱 Mi Cartera en la Nube")

# 2. Conexión a Google Sheets
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Error de conexión. Revisa tus 'Secrets' en Streamlit.")
    st.stop()

# 3. Formulario de COMPRA
with st.expander("➕ Registrar Nueva Compra", expanded=False):
    with st.form("buy_form"):
        ticker = st.text_input("Ticker (ej. AAPL)").upper()
        cantidad = st.number_input("Cantidad", min_value=1.0, step=1.0)
        precio = st.number_input("Precio de compra ($)", min_value=0.1)
        fecha = st.date_input("Fecha")
        
        submitted = st.form_submit_button("Guardar en Nube")
        
        if submitted and ticker:
            try:
                # Leemos datos sin caché (ttl=0)
                df_actual = conn.read(worksheet="Cartera", ttl=0)
                
                # Creamos la nueva fila
                nueva_fila = pd.DataFrame([{
                    "Ticker": ticker,
                    "Cantidad": cantidad,
                    "Precio": precio,
                    "Fecha": fecha
                }])
                
                # Unimos y guardamos
                df_updated = pd.concat([df_actual, nueva_fila], ignore_index=True)
                conn.update(worksheet="Cartera", data=df_updated)
                
                st.success(f"¡Guardado! {cantidad} de {ticker}")
                st.rerun()
            except Exception as e:
                st.error(f"Error al guardar: {e}")

# 4. Mostrar Cartera
try:
    # Leemos la hoja "Cartera"
    df_cartera = conn.read(worksheet="Cartera", usecols=[0,1,2,3], ttl=0)
    df_cartera = df_cartera.dropna(how="all")

    if not df_cartera.empty:
        st.divider()
        st.subheader("💰 Mi Portafolio en Vivo")
        
        total_valor = 0
        
        # Bucle para calcular valores
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
        
        # --- AQUÍ ESTABA EL ERROR DE ALINEACIÓN ---
        # Ahora está correctamente alineado fuera del bucle 'for'
        st.metric(label="Valor Total Cartera", value=f"${total_valor:,.2f}")
        
        with st.expander("Ver tabla bruta"):
            st.dataframe(df_cartera)

    else:
        st.info("Tu hoja está vacía. Añade una compra arriba.")

except Exception as e:
    st.warning("No se pudo leer la hoja 'Cartera'.")
    st.write(e)
