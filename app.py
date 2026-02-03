import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from pyairtable import Api
from datetime import datetime
from zoneinfo import ZoneInfo

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor V8.2 (Métricas Pro)", layout="wide") 
MONEDA_BASE = "EUR" 

# --- ESTADO ---
if "pending_data" not in st.session_state:
    st.session_state.pending_data = None
if "adding_mode" not in st.session_state:
    st.session_state.adding_mode = False
if "reset_seed" not in st.session_state:
    st.session_state.reset_seed = 0

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
            else: st.error("Incorrecto")
        except: st.error("Revisa Secrets")
    return False

@st.cache_data(ttl=300) 
def get_exchange_rate_now(from_curr, to_curr="EUR"):
    if from_curr == to_curr: return 1.0
    try:
        pair = f"{to_curr}=X" if from_curr == "USD" else f"{from_curr}{to_curr}=X"
        return yf.Ticker(pair).history(period="1d")['Close'].iloc[-1]
    except: return 1.0

def get_logo_url(ticker):
    return f"https://financialmodelingprep.com/image-stock/{ticker}.png"

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
        precio = stock.fast_info.last_price
        nombre = stock.info.get('longName') or stock.info.get('shortName') or ticker
        if precio: return nombre, precio
    except: 
        try:
            hist = stock.history(period="1d")
            if not hist.empty:
                return ticker, hist['Close'].iloc[-1]
        except: pass
    return None, None

def guardar_en_airtable(record):
    try:
        api = Api(st.secrets["airtable"]["api_token"])
        table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
        table.create(record)
        st.success(f"✅ Guardado: {record['Ticker']}")
        st.session_state.pending_data = None
        st.session_state.adding_mode = False 
        st.rerun()
    except Exception as e: st.error(f"Error guardando: {e}")

# --- APP ---
if not check_password(): st.stop()

try:
    api = Api(st.secrets["airtable"]["api_token"])
    table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
except Exception as e:
    st.error(f"Error conectando a Airtable: {e}")
    st.stop()

st.title("💼 Control de Rentabilidad (P&L)")

# --- CARGA DATOS ---
try: data = table.all()
except: data = []

df = pd.DataFrame()
if data:
    df = pd.DataFrame([x['fields'] for x in data])
    df.columns = df.columns.str.strip() # Limpieza de espacios

    if 'Fecha' in df.columns:
        df['Fecha_dt'] = pd.to_datetime(df['Fecha'], errors='coerce')
        df['Año'] = df['Fecha_dt'].dt.year 
        df['Fecha_str'] = df['Fecha_dt'].dt.strftime('%Y/%m/%d %H:%M').fillna("")
    else: 
        df['Año'] = datetime.now().year
        df['Fecha_dt'] = datetime.now()

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("Configuración")
    mis_zonas = ["Atlantic/Canary", "Europe/Madrid", "UTC"]
    mi_zona = st.selectbox("🌍 Tu Zona Horaria:", mis_zonas, index=0)
    st.divider()
    
    st.header("Filtros")
    lista_años = ["Todos los años"]
    if not df.empty and 'Año' in df.columns:
        años_disponibles = sorted(df['Año'].dropna().unique().astype(int), reverse=True)
        lista_años += list(años_disponibles)
    año_seleccionado = st.selectbox("📅 Año Fiscal:", lista_años)
    st.divider()

    if not st.session_state.adding_mode and st.session_state.pending_data is None:
        if st.button("➕ Registrar Nueva Operación", use_container_width=True, type="primary"):
            st.session_state.adding_mode = True
            st.session_state.reset_seed = int(datetime.now().timestamp())
            st.rerun()

    if st.session_state.adding_mode or st.session_state.pending_data is not None:
        st.markdown("### 📝 Datos de la Operación")
        if st.button("❌ Cerrar Formulario", use_container_width=True):
            st.session_state.adding_mode = False
            st.session_state.pending_data = None
            st.rerun()

        if st.session_state.pending_data is None:
            with st.form("trade_form"):
                tipo = st.selectbox("Tipo", ["Compra", "Venta", "Dividendo"])
                ticker = st.text_input("Ticker (ej. TSLA)").upper().strip()
                desc_manual = st.text_input("Descripción (Opcional)")
                moneda = st.selectbox("Moneda", ["EUR", "USD"])
                
                c1, c2 = st.columns(2)
                dinero_total = c1.number_input("Importe Total", min_value=0.0, step=10.0)
                precio_manual = c2.number_input("Precio/Acción", min_value=0.0, format="%.2f")
                comision = st.number_input("Comisión", min_value=0.0, format="%.2f")
                
                st.markdown("---")
                st.write(f"📆 **Fecha ({mi_zona}):**")
                ahora_local = datetime.now(ZoneInfo(mi_zona))
                
                cd, ct = st.columns(2)
                f_in = cd.date_input("Día", value=ahora_local, key=f"d_{st.session_state.reset_seed}")
                h_in = ct.time_input("Hora", value=ahora_local, key=f"t_{st.session_state.reset_seed}")
                
                if st.form_submit_button("🔍 Validar y Guardar"):
                    if ticker and dinero_total > 0:
                        nom, pre = None, 0.0
                        with st.spinner("Consultando precio..."):
                            nom, pre = get_stock_data_fmp(ticker)
                            if not nom: nom, pre = get_stock_data_yahoo(ticker)
                        
                        if desc_manual: nom = desc_manual
                        if not nom: nom = ticker
                        if precio_manual > 0: pre = precio_manual
                        if not pre: pre = 0.0

                        dt_final = datetime.combine(f_in, h_in)
                        datos = {
                            "Tipo": tipo, "Ticker": ticker, "Descripcion": nom, 
                            "Moneda": moneda, "Cantidad": float(dinero_total),
                            "Precio": float(pre), "Comision": float(comision),
                            "Fecha": dt_final.strftime("%Y/%m/%d %H:%M")
                        }
                        
                        if pre > 0: guardar_en_airtable(datos)
                        else:
                            st.session_state.pending_data = datos
                            st.rerun()
        else:
            st.warning(f"⚠️ **ALERTA:** No encuentro precio para **'{st.session_state.pending_data['Ticker']}'**.")
            c_si, c_no = st.columns(2)
            if c_si.button("✅ Guardar"): guardar_en_airtable(st.session_state.pending_data)
            if c_no.button("❌ Revisar"): 
                st.session_state.pending_data = None
                st.rerun()

# --- CÁLCULOS ---
if not df.empty:
    df_filtrado = df.copy()
    if año_seleccionado != "Todos los años":
        df_filtrado = df[df['Año'] == int(año_seleccionado)]
        st.info(f"Visualizando datos de: {año_seleccionado}")
    else:
        st.info("Visualizando acumulado histórico.")

    cols_numericas = ["Cantidad", "Precio", "Comision"]
    for col in cols_numericas:
        if col in df_filtrado.columns:
            df_filtrado[col] = pd.to_numeric(df_filtrado[col], errors='coerce').fillna(0.0)
    
    cartera = {}
    total_dividendos = 0.0 
    total_comisiones = 0.0
    pnl_global_cerrado = 0.0 
    
    # NUEVO: Acumulador de inversión histórica para calcular ROI %
    total_compras_historicas_eur = 0.0

    for i, row in df_filtrado.sort_values(by="Fecha_dt").iterrows():
        tipo = row.get('Tipo', 'Desconocido')
        tick = str(row.get('Ticker', 'UNKNOWN')).strip()
        desc = str(row.get('Descripcion', tick)).strip() or tick
        dinero = float(row.get('Cantidad', 0))
        precio = float(row.get('Precio', 1))
        if precio <= 0: precio = 1
        mon = row.get('Moneda', 'EUR')
        comi = float(row.get('Comision', 0))
        
        fx = get_exchange_rate_now(mon, MONEDA_BASE)
        
        dinero_eur = dinero * fx
        acciones_op = dinero / precio 
        total_comisiones += (comi * fx)

        if tick not in cartera:
            cartera[tick] = {
                'acciones': 0.0, 'coste_total_eur': 0.0, 'desc': desc, 
                'pnl_cerrado': 0.0, 'pmc': 0.0, 'moneda_origen': mon
            }

        if tipo == "Compra":
            cartera[tick]['acciones'] += acciones_op
            cartera[tick]['coste_total_eur'] += dinero_eur
            
            # Sumamos al histórico de compras para calcular ROI luego
            total_compras_historicas_eur += dinero_eur 

            if cartera[tick]['acciones'] > 0:
                cartera[tick]['pmc'] = cartera[tick]['coste_total_eur'] / cartera[tick]['acciones']
            if len(desc) > len(cartera[tick]['desc']): cartera[tick]['desc'] = desc

        elif tipo == "Venta":
            coste_proporcional = acciones_op * cartera[tick]['pmc']
            beneficio_operacion = dinero_eur - coste_proporcional
            cartera[tick]['pnl_cerrado'] += beneficio_operacion
            pnl_global_cerrado += beneficio_operacion
            cartera[tick]['acciones'] -= acciones_op
            cartera[tick]['coste_total_eur'] -= coste_proporcional 
            if cartera[tick]['acciones'] < 0: cartera[tick]['acciones'] = 0

        elif tipo == "Dividendo":
            total_dividendos += dinero_eur

    # --- TABLA Y VALORACIÓN ONLINE ---
    tabla_final = []
    saldo_invertido_total = 0 
    fx_usd_now = get_exchange_rate_now("USD", "EUR")

    with st.spinner("Calculando estado de cartera..."):
        for t, info in cartera.items():
            if info['acciones'] > 0.001 or abs(info['pnl_cerrado']) > 0.01:
                saldo_vivo = info['coste_total_eur']
                saldo_invertido_total += saldo_vivo
                
                rentabilidad_pct = 0.0
                precio_mercado_str = "0.00"
                logo_url = get_logo_url(t)
                
                if info['acciones'] > 0.001:
                    _, p_now = get_stock_data_fmp(t)
                    if not p_now: _, p_now = get_stock_data_yahoo(t)
                    
                    if p_now:
                        moneda_act = info['moneda_origen']
                        fx_act = 1.0
                        if moneda_act == "USD": fx_act = fx_usd_now
                        
                        precio_actual_eur = p_now * fx_act
                        precio_mercado_str = f"{p_now:.2f} {moneda_act}"
                        
                        if info['pmc'] > 0:
                            rentabilidad_pct = ((precio_actual_eur - info['pmc']) / info['pmc'])

                tabla_final.append({
                    "Logo": logo_url,
                    "Empresa": info['desc'],
                    "Ticker": t,
                    "Acciones": info['acciones'],
                    "PMC": info['pmc'],
                    "Precio Mercado": precio_mercado_str,
                    "Saldo Invertido": saldo_vivo,
                    "Bº/P (Cerrado)": info['pnl_cerrado'],
                    "% Latente": rentabilidad_pct
                })

    # === CÁLCULOS FINALES DE RENTABILIDAD ===
    beneficio_neto_total = pnl_global_cerrado + total_dividendos - total_comisiones
    
    # Calcular ROI Total % (Beneficio Neto / Total Dinero Invertido Históricamente)
    roi_total_pct = 0.0
    if total_compras_historicas_eur > 0:
        roi_total_pct = (beneficio_neto_total / total_compras_historicas_eur) * 100

    # MÉTRICAS CON COLOR Y PORCENTAJE
    m1, m2, m3, m4 = st.columns(4)
    
    # 1. BENEFICIO NETO (Con Color y %)
    m1.metric(
        "💰 BENEFICIO TOTAL NETO", 
        f"{beneficio_neto_total:,.2f} €", 
        delta=f"{roi_total_pct:+.2f} % (ROI)", # Esto pone el % y el color verde/rojo automáticamente
        help="Beneficio limpio (Trading + Div - Comisiones) respecto al total invertido."
    )
    
    # 2. TRADING (Con Color)
    m2.metric(
        "Bº/P Trading (Cerrado)", 
        f"{pnl_global_cerrado:,.2f} €", 
        delta=f"{pnl_global_cerrado:,.2f} €", # Repetimos el valor en delta para forzar el color verde/rojo
        help="Ganancia o pérdida directa por compra-venta de acciones."
    )
    
    # 3. DIVIDENDOS (Siempre positivo o neutro)
    m3.metric("Dividendos Totales", f"{total_dividendos:,.2f} €", delta=None)
    
    # 4. COMISIONES (Rojo inverso para indicar coste)
    m4.metric("Comisiones Totales", f"-{total_comisiones:
