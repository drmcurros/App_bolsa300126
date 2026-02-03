import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from pyairtable import Api
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor por Años", layout="wide") 
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

st.title("💼 Mi Cartera (Histórica)")

# --- CARGA DE DATOS INICIAL ---
try: data = table.all()
except: data = []

df = pd.DataFrame()
if data:
    df = pd.DataFrame([x['fields'] for x in data])
    # Procesar fechas al principio para poder filtrar
    if 'Fecha' in df.columns:
        df['Fecha_dt'] = pd.to_datetime(df['Fecha'], errors='coerce')
        df['Año'] = df['Fecha_dt'].dt.year # Extraemos el año
        df['Fecha_str'] = df['Fecha_dt'].dt.strftime('%Y/%m/%d %H:%M').fillna("")
    else:
        df['Año'] = datetime.now().year

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("Registrar Movimiento")
    
    # === SELECCIÓN DE AÑO (NUEVO) ===
    st.divider()
    lista_años = ["Todos los años"]
    if not df.empty and 'Año' in df.columns:
        años_disponibles = sorted(df['Año'].dropna().unique().astype(int), reverse=True)
        lista_años += list(años_disponibles)
    
    año_seleccionado = st.selectbox("📅 Filtrar Vista por Año:", lista_años)
    st.divider()
    # ================================

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
                    with st.spinner("Verificando..."):
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
                    if precio_final > 0: guardar_en_airtable(datos)
                    else:
                        st.session_state.pending_data = datos
                        st.rerun()
    else:
        st.warning(f"⚠️ ¿Confirmar '{st.session_state.pending_data['Ticker']}'?")
        c1, c2 = st.columns(2)
        if c1.button("✅ Sí"): guardar_en_airtable(st.session_state.pending_data)
        if c2.button("❌ Cancelar"): 
            st.session_state.pending_data = None
            st.rerun()

# --- FILTRADO Y CÁLCULOS ---

if not df.empty:
    
    # 1. APLICAMOS EL FILTRO DE AÑO
    df_filtrado = df.copy()
    if año_seleccionado != "Todos los años":
        df_filtrado = df[df['Año'] == int(año_seleccionado)]
        st.info(f"Mostrando movimientos y resultados del año: {año_seleccionado}")
    else:
        st.info("Mostrando acumulado histórico total.")

    # Limpieza de números
    for col in ["Cantidad", "Precio", "Comision"]:
        df_filtrado[col] = pd.to_numeric(df_filtrado.get(col, 0.0), errors='coerce').fillna(0.0)
    
    cartera = {}
    total_divis_eur = 0
    total_comis_eur = 0
    
    # Caché de divisas
    fx_cache = {}
    def get_fx_cached(moneda):
        if moneda == MONEDA_BASE: return 1.0
        if moneda not in fx_cache:
            fx_cache[moneda] = get_exchange_rate(moneda, MONEDA_BASE)
        return fx_cache[moneda]

    # Iteramos solo sobre los datos filtrados
    for i, row in df_filtrado.iterrows():
        tipo = row.get('Tipo')
        tick = str(row.get('Ticker', 'UNKNOWN')).strip()
        desc = str(row.get('Descripcion', tick)).strip() or tick
        
        dinero_bruto = float(row.get('Cantidad', 0)) 
        precio = float(row.get('Precio', 1)) 
        if precio <= 0: precio = 1
        
        moneda = row.get('Moneda', 'EUR')
        comi = float(row.get('Comision', 0))
        
        fx = get_fx_cached(moneda)
        dinero_eur = dinero_bruto * fx
        num_acciones = dinero_bruto / precio
        
        total_comis_eur += (comi * fx)
        
        if tipo == "Compra":
            if tick not in cartera: 
                cartera[tick] = {'acciones': 0, 'saldo_neto_eur': 0.0, 'desc': desc}
            cartera[tick]['acciones'] += num_acciones
            cartera[tick]['saldo_neto_eur'] += dinero_eur
            if len(desc) > len(cartera[tick]['desc']): cartera[tick]['desc'] = desc
            
        elif tipo == "Venta":
            if tick in cartera:
                cartera[tick]['acciones'] -= num_acciones
                # Si es parcial, ajustamos
                if cartera[tick]['acciones'] < 0: cartera[tick]['acciones'] = 0
                cartera[tick]['saldo_neto_eur'] -= dinero_eur
                
        elif tipo == "Dividendo":
            total_divis_eur += dinero_eur

    # --- VISUALIZACIÓN ---
    
    saldo_total_cartera = 0
    tabla_final = []
    
    for t, info in cartera.items():
        # En la vista anual, mostramos la empresa si ha habido movimiento de dinero
        # aunque el saldo de acciones sea 0 (ej. compré y vendí todo este año)
        if abs(info['saldo_neto_eur']) > 0.01 or info['acciones'] > 0.001:
            saldo_vivo = info['saldo_neto_eur']
            saldo_total_cartera += saldo_vivo
            
            tabla_final.append({
                "Empresa": info['desc'],
                "Ticker": t,
                # En vista anual: Acciones compradas (netas) este año
                # En vista total: Acciones vivas actuales
                "Acciones (Movimiento)": f"{info['acciones']:.4f}", 
                "Saldo Invertido (€)": saldo_vivo
            })

    # BLOQUE DE MÉTRICAS
    c1, c2, c3 = st.columns(3)
    
    label_saldo = "Saldo Neto (Flujo)" if año_seleccionado != "Todos los años" else "Dinero en Cartera"
    help_text = "Dinero invertido menos retirado en este periodo."
    
    c1.metric(label_saldo, f"{saldo_total_cartera:,.2f} €", help=help_text)
    c2.metric("Dividendos", f"{total_divis_eur:,.2f} €")
    c3.metric("Comisiones", f"{total_comis_eur:,.2f} €")
    
    st.divider()
    
    if tabla_final:
        st.subheader(f"📊 Detalle del periodo: {año_seleccionado}")
        st.dataframe(
            pd.DataFrame(tabla_final).style.format({"Saldo Invertido (€)": "{:.2f} €"}), 
            use_container_width=True, hide_index=True
        )
    else:
        st.info(f"No hubo movimientos en {año_seleccionado}.")
    
    with st.expander("Historial Filtrado"):
        cols = [c for c in ['Fecha_str','Tipo','Descripcion','Ticker','Cantidad','Precio','Moneda'] if c in df_filtrado.columns]
        # Renombramos Fecha_str a Fecha para que se vea bonito
        df_show = df_filtrado[cols].rename(columns={'Fecha_str': 'Fecha'})
        st.dataframe(df_show.sort_values(by="Fecha", ascending=False), use_container_width=True)

else:
    st.info("Conecta Airtable y añade tu primera operación.")
