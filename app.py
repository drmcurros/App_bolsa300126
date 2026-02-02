import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection

# 1. Configuración
st.set_page_config(page_title="Mi Cartera Cloud", layout="centered") 
st.title("📱 Mi Cartera en la Nube")

# 2. Conexión a Google Sheets (con protección de errores)
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Error conectando con Google Sheets. Revisa tus 'Secrets'.")
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
                # Leemos datos actuales para añadir la nueva fila
                # IMPORTANTE: ttl=0 hace que no use caché y lea datos frescos
                df_actual = conn.read(worksheet="Cartera", ttl=0)
                
                # Creamos la nueva fila
                nueva_fila = pd.DataFrame([{
                    "Ticker": ticker,
                    "Cantidad": cantidad,
                    "Precio": precio,
                    "Fecha": fecha
                }])
                
                # Juntamos y actualizamos
                df_updated = pd.concat([df_actual, nueva_fila], ignore_index=True)
                conn.update(worksheet="Cartera", data=df_updated)
                
                st.success(f"¡Comprada! {cantidad} de {ticker}")
                st.rerun() # Recarga la página para ver cambios
            except Exception as e:
                st.error(f"Error al guardar: {e}")

# 4. Mostrar Cartera
try:
    # Leemos la hoja llamada "Cartera"
    # usecols asegura que solo leemos las columnas que importan
    df_cartera = conn.read(worksheet="Cartera", usecols=[0,1,2,3], ttl=0)
    
    # Limpiamos filas vacías por si acaso
    df_cartera = df_cartera.dropna(how="all")

    if not df_cartera.empty:
        st.divider()
        st.subheader("💰 Mi Portafolio en Vivo")
        
        total_valor = 0
        
        # Iteramos por cada acción
        for index, row in df_cartera.iterrows():
            if pd.isna(row['Ticker']): continue # Saltar filas vacías
            
            simbolo = row['Ticker']
            cant = row['Cantidad']
            
            # Buscamos precio actual (con manejo de error si no existe)
            try:
                stock = yf.Ticker(simbolo)
                hist = stock.history(period="1d")
                
                if not hist.empty:
                    precio_actual = hist['Close'].iloc[-1]
                    valor_posicion = precio_actual * cant
                    total_valor += valor_posicion
                    
                    # Mostramos tarjeta
                    st.info(f"**{simbolo}**: {cant} acc. a ${precio_actual:.2f} | Total: ${valor_posicion:.2f}")
                else:
                    st.warning(f"No se encontraron datos para {simbolo}")
                    
            except Exception:
                st.warning(f"Error buscando {simbolo}")

        st.metric(label="Valor Total Estimado", value=f"${total_valor:,.2f}")
        
        # Mostramos la tabla bruta abajo del todo
        with st.expander("Ver tabla de datos bruta"):
            st.dataframe(df_cartera)
    else:
        st.info("Tu hoja de cálculo está vacía. ¡Añade tu primera compra arriba!")

except Exception as e:
    st.warning("No se pudo leer la hoja 'Cartera'. Asegúrate de que el nombre de la hoja en Google Sheets sea exactamente 'Cartera' y tenga las columnas Ticker, Cantidad, Precio, Fecha.")
    st.write(f"Detalle del error: {e}")

        st.metric(label="Valor Total Cartera", value=f"${total_valor:,.2f}")

except Exception as e:

    st.warning("Conecta tu Google Sheet para ver los datos.")
