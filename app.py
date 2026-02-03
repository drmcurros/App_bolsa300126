import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from pyairtable import Api
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor Rentabilidad", layout="wide") 
MONEDA_BASE = "EUR" 

# --- ESTADO ---
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
            else: st.error("Incorrecto")
        except: st.error("Revisa Secrets")
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
            return nombre, hist['Close'].iloc[-1]
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
    except Exception as e: st.error(f"Error: {e}")

# --- APP ---
if not check_password(): st.stop()

try:
    api = Api(st.secrets["airtable"]["api_token"])
    table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
except: st.stop()

st.title("💼 Control de Rentabilidad (P&L)")

# --- CARGA DATOS ---
try: data = table.all()
except: data = []

df = pd.DataFrame()
if data:
    df = pd.DataFrame([x['fields'] for x in data])
    if 'Fecha' in df.columns:
        df['Fecha_dt'] = pd.to_datetime(df['Fecha'], errors='coerce')
        df['Año'] = df['Fecha_dt'].dt.year 
        df['Fecha_str'] = df['Fecha_dt'].dt.strftime('%Y/%m/%d %H:%M').fillna("")
    else: df['Año'] = datetime.now().year

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("Nueva Operación")
    
    # Filtro Año
    lista_años = ["Todos los años"]
    if not df.empty and 'Año' in df.columns:
        años_disponibles = sorted(df['Año'].dropna().unique().astype(int), reverse=True)
        lista_años += list(años_disponibles)
    año_seleccionado = st.selectbox("📅 Año Fiscal:", lista_años)
    st.divider()

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
            st.write("📆 **Fecha:**")
            cd, ct = st.columns(2)
            f_in = cd.date_input("Día", value=datetime.now())
            h_in = ct.time_input("Hora", value=datetime.now())
            
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
        st.warning(f"⚠️ ¿Confirmar '{st.session_state.pending_data['Ticker']}'?")
        if st.button("✅ Sí"): guardar_en_airtable(st.session_state.pending_data)
        if st.button("❌ Cancelar"): 
            st.session_state.pending_data = None
            st.rerun()

# --- CÁLCULO DE RENTABILIDAD (PMC) ---
if not df.empty:
    # 1. Filtramos por año para visualización
    df_filtrado = df.copy()
    if año_seleccionado != "Todos los años":
        df_filtrado = df[df['Año'] == int(año_seleccionado)]
        st.info(f"Visualizando datos de: {año_seleccionado}")
    else:
        st.info("Visualizando acumulado histórico.")

    # Convertir números
    for col in ["Cantidad", "Precio", "Comision"]:
        df_filtrado[col] = pd.to_numeric(df_filtrado.get(col, 0.0), errors='coerce').fillna(0.0)
    
    cartera = {}
    total_divis = 0
    total_comis = 0
    pnl_global_cerrado = 0 # Ganancia/Pérdida realizada global

    # Cache divisas
    fx_cache = {}
    def get_fx(mon):
        if mon == MONEDA_BASE: return 1.0
        if mon not in fx_cache: fx_cache[mon] = get_exchange_rate(mon, MONEDA_BASE)
        return fx_cache[mon]

    # --- MOTOR DE CÁLCULO ---
    # Iteramos para calcular Precio Medio Ponderado (FIFO/Average)
    for i, row in df_filtrado.sort_values(by="Fecha_dt").iterrows():
        tipo = row.get('Tipo')
        tick = str(row.get('Ticker', '')).strip()
        desc = str(row.get('Descripcion', tick)).strip() or tick
        dinero = float(row.get('Cantidad', 0))
        precio = float(row.get('Precio', 1))
        if precio <= 0: precio = 1
        mon = row.get('Moneda', 'EUR')
        comi = float(row.get('Comision', 0))
        
        fx = get_fx(mon)
        dinero_eur = dinero * fx
        acciones_op = dinero / precio # Cuántas acciones movimos
        total_comis += (comi * fx)

        # Inicializar Ticker
        if tick not in cartera:
            cartera[tick] = {
                'acciones': 0.0, 
                'coste_total_eur': 0.0, # Dinero gastado en las acciones que quedan
                'desc': desc,
                'pnl_cerrado': 0.0, # Beneficio ya realizado al vender
                'pmc': 0.0 # Precio Medio de Compra
            }

        if tipo == "Compra":
            cartera[tick]['acciones'] += acciones_op
            cartera[tick]['coste_total_eur'] += dinero_eur
            # Recalculamos Precio Medio de Compra (PMC)
            if cartera[tick]['acciones'] > 0:
                cartera[tick]['pmc'] = cartera[tick]['coste_total_eur'] / cartera[tick]['acciones']
            
            if len(desc) > len(cartera[tick]['desc']): cartera[tick]['desc'] = desc

        elif tipo == "Venta":
            # Lógica de P&L:
            # 1. ¿Cuánto me costaron estas acciones originalmente? (Basado en PMC)
            coste_proporcional = acciones_op * cartera[tick]['pmc']
            
            # 2. ¿Cuánto he ganado? (Venta - Coste)
            beneficio_operacion = dinero_eur - coste_proporcional
            
            # 3. Actualizamos acumulados
            cartera[tick]['pnl_cerrado'] += beneficio_operacion
            pnl_global_cerrado += beneficio_operacion
            
            # 4. Reducimos inventario
            cartera[tick]['acciones'] -= acciones_op
            cartera[tick]['coste_total_eur'] -= coste_proporcional # Quitamos el coste de lo vendido
            
            if cartera[tick]['acciones'] < 0: cartera[tick]['acciones'] = 0

        elif tipo == "Dividendo":
            total_divis += dinero_eur

    # --- TABLA FINAL ---
    tabla_final = []
    saldo_invertido_total = 0 # Dinero que sigue en bolsa

    for t, info in cartera.items():
        # Mostramos si hay acciones vivas O si ha habido ganancia/pérdida este año
        if info['acciones'] > 0.001 or abs(info['pnl_cerrado']) > 0.01:
            saldo_vivo = info['coste_total_eur'] # Esto es lo que "queda" invertido
            saldo_invertido_total += saldo_vivo
            
            # Formateo visual del PMC
            precio_medio = info['pmc'] / get_fx(df_filtrado[df_filtrado['Ticker']==t]['Moneda'].iloc[-1]) # Aprox revertir a divisa orig visualmente
            
            tabla_final.append({
                "Empresa": info['desc'],
                "Ticker": t,
                "Acciones": f"{info['acciones']:.4f}",
                "PMC (Est.)": f"{info['pmc']:.2f} €", # Precio medio en Euros
                "Saldo Invertido (€)": saldo_vivo,
                "Bº/P (Cerrado)": info['pnl_cerrado'] # Columna CLAVE
            })

    # --- VISUALIZACIÓN ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Dinero en Juego", f"{saldo_invertido_total:,.2f} €", help="Coste de acciones que aún tienes")
    c2.metric("Bº/Pérdida Realizado", f"{pnl_global_cerrado:,.2f} €", 
              delta="Ganancia Neta" if pnl_global_cerrado > 0 else "Pérdida Neta",
              help="Dinero ganado o perdido de las ventas cerradas")
    c3.metric("Dividendos", f"{total_divis:,.2f} €")
    c4.metric("Comisiones", f"{total_comis:,.2f} €")
    
    st.divider()
    
    if tabla_final:
        df_show = pd.DataFrame(tabla_final)
        st.subheader(f"📊 Rentabilidad {año_seleccionado}")
        
        # Colorear la columna de Beneficio
        st.dataframe(
            df_show.style.format({
                "Saldo Invertido (€)": "{:.2f} €",
                "Bº/P (Cerrado)": "{:+.2f} €"
            }).map(lambda v: 'color: green;' if v > 0 else 'color: red;' if v < 0 else '', subset=['Bº/P (Cerrado)']),
            use_container_width=True, hide_index=True
        )
    
    with st.expander("📝 Ver Histórico"):
        cols = [c for c in ['Fecha_str','Tipo','Ticker','Cantidad','Precio','Moneda'] if c in df_filtrado.columns]
        st.dataframe(df_filtrado[cols].sort_values(by="Fecha_str", ascending=False), use_container_width=True)

else:
    st.info("Sin datos.")
