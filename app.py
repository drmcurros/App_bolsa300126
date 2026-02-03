import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from pyairtable import Api
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor V9.0 (Detalle Gráfico)", layout="wide") 
MONEDA_BASE = "EUR" 

# --- ESTADO (SESSION STATE) ---
if "pending_data" not in st.session_state:
    st.session_state.pending_data = None
if "adding_mode" not in st.session_state:
    st.session_state.adding_mode = False
if "reset_seed" not in st.session_state:
    st.session_state.reset_seed = 0
# NUEVO: Estado para saber qué acción estamos viendo en detalle
if "ticker_detalle" not in st.session_state:
    st.session_state.ticker_detalle = None

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
            return data[0].get('companyName'), data[0].get('price'), data[0].get('description')
        return None, None, None
    except: return None, None, None

def get_stock_data_yahoo(ticker):
    try:
        stock = yf.Ticker(ticker)
        precio = stock.fast_info.last_price
        nombre = stock.info.get('longName') or stock.info.get('shortName') or ticker
        desc = stock.info.get('longBusinessSummary') or "Sin descripción."
        if precio: return nombre, precio, desc
    except: 
        try:
            hist = stock.history(period="1d")
            if not hist.empty:
                return ticker, hist['Close'].iloc[-1], "Sin descripción."
        except: pass
    return None, None, None

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

# --- CARGA Y PROCESAMIENTO INICIAL DE DATOS ---
# (Calculamos todo primero para tener los datos listos para cualquier vista)
try: data = table.all()
except: data = []

df = pd.DataFrame()
cartera_global = {} # Diccionario global para acceder desde el detalle

if data:
    df = pd.DataFrame([x['fields'] for x in data])
    df.columns = df.columns.str.strip() 

    if 'Fecha' in df.columns:
        df['Fecha_dt'] = pd.to_datetime(df['Fecha'], errors='coerce')
        df['Año'] = df['Fecha_dt'].dt.year 
        df['Fecha_str'] = df['Fecha_dt'].dt.strftime('%Y/%m/%d %H:%M').fillna("")
    else: 
        df['Año'] = datetime.now().year
        df['Fecha_dt'] = datetime.now()

    # --- PROCESAMIENTO DE CARTERA ---
    cols_numericas = ["Cantidad", "Precio", "Comision"]
    for col in cols_numericas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    
    # Variables globales para el dashboard principal
    total_dividendos = 0.0 
    total_comisiones = 0.0
    pnl_global_cerrado = 0.0 
    total_compras_historicas_eur = 0.0
    coste_ventas_total = 0.0

    # Iteramos sobre TODO el histórico (sin filtrar por año para la cartera actual)
    # Nota: Para el dashboard principal usaremos filtros, pero para la cartera viva necesitamos todo.
    for i, row in df.sort_values(by="Fecha_dt").iterrows():
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
        
        # Acumulados globales
        total_comisiones += (comi * fx)

        if tick not in cartera_global:
            cartera_global[tick] = {
                'acciones': 0.0, 'coste_total_eur': 0.0, 'desc': desc, 
                'pnl_cerrado': 0.0, 'pmc': 0.0, 'moneda_origen': mon,
                'movimientos': [] # Guardamos índices para el detalle
            }
        
        # Guardamos referencia del movimiento
        cartera_global[tick]['movimientos'].append(row)

        if tipo == "Compra":
            cartera_global[tick]['acciones'] += acciones_op
            cartera_global[tick]['coste_total_eur'] += dinero_eur
            total_compras_historicas_eur += dinero_eur 
            if cartera_global[tick]['acciones'] > 0:
                cartera_global[tick]['pmc'] = cartera_global[tick]['coste_total_eur'] / cartera_global[tick]['acciones']
            if len(desc) > len(cartera_global[tick]['desc']): cartera_global[tick]['desc'] = desc

        elif tipo == "Venta":
            coste_proporcional = acciones_op * cartera_global[tick]['pmc']
            coste_ventas_total += coste_proporcional 
            beneficio_operacion = dinero_eur - coste_proporcional
            
            cartera_global[tick]['pnl_cerrado'] += beneficio_operacion
            pnl_global_cerrado += beneficio_operacion
            
            cartera_global[tick]['acciones'] -= acciones_op
            cartera_global[tick]['coste_total_eur'] -= coste_proporcional 
            if cartera_global[tick]['acciones'] < 0: cartera_global[tick]['acciones'] = 0

        elif tipo == "Dividendo":
            total_dividendos += dinero_eur


# ==========================================
#        CONTROLADOR DE VISTAS
# ==========================================

# 1. SI HAY UN TICKER SELECCIONADO -> VISTA DE DETALLE
if st.session_state.ticker_detalle:
    t = st.session_state.ticker_detalle
    info = cartera_global.get(t, {})
    
    # Botón Volver
    if st.button("⬅️ Volver a la Cartera Principal", type="secondary"):
        st.session_state.ticker_detalle = None
        st.rerun()
    
    st.divider()

    # --- ENCABEZADO DETALLE ---
    c_logo, c_tit = st.columns([1, 5])
    with c_logo:
        st.image(get_logo_url(t), width=80)
    with c_tit:
        st.title(f"{info.get('desc', t)} ({t})")
        st.caption("Ficha detallada del activo")

    # --- DATOS EN TIEMPO REAL ---
    with st.spinner(f"Descargando datos de mercado y gráfico para {t}..."):
        # Precio actual
        nombre, precio_now, descripcion_larga = get_stock_data_fmp(t)
        if not precio_now: 
            nombre, precio_now, descripcion_larga = get_stock_data_yahoo(t)
        
        # Gráfico histórico (1 año)
        historia = pd.DataFrame()
        try:
            ticker_obj = yf.Ticker(t)
            historia = ticker_obj.history(period="1y")
        except: pass

    # --- MÉTRICAS SUPERIORES ---
    m1, m2, m3, m4 = st.columns(4)
    
    acciones_activas = info.get('acciones', 0)
    pmc_actual = info.get('pmc', 0)
    
    # Calculo valor actual posición
    valor_mercado_eur = 0.0
    rentabilidad_latente = 0.0
    if precio_now and acciones_activas > 0:
        fx = get_exchange_rate_now(info.get('moneda_origen', 'USD')) if info.get('moneda_origen') != 'EUR' else 1.0
        valor_mercado_eur = acciones_activas * precio_now * fx
        if pmc_actual > 0:
            rentabilidad_latente = (valor_mercado_eur - info.get('coste_total_eur', 0)) / info.get('coste_total_eur', 0)

    mon_sim = info.get('moneda_origen', '')

    m1.metric("Precio Actual", f"{precio_now:,.2f} {mon_sim}" if precio_now else "N/A")
    m2.metric("Tus Acciones", f"{acciones_activas:,.4f}")
    m3.metric("Valor en Cartera", f"{valor_mercado_eur:,.2f} €", 
              delta=f"{rentabilidad_latente:+.2f}%" if acciones_activas > 0 else "0%",
              help="Valor actual si vendieras hoy")
    m4.metric("Bº Realizado (Histórico)", f"{info.get('pnl_cerrado',0):,.2f} €", 
              delta="Ya cobrado", help="Dinero ganado en ventas anteriores")

    # --- GRÁFICO ---
    st.subheader("📈 Evolución (1 Año)")
    if not historia.empty:
        st.line_chart(historia['Close'], color="#00FF00", height=300)
    else:
        st.warning("No se pudo cargar el gráfico histórico.")

    # --- DESCRIPCIÓN ---
    with st.expander("📖 Sobre la empresa"):
        st.write(descripcion_larga if descripcion_larga else "No hay descripción disponible.")

    # --- TUS MOVIMIENTOS ---
    st.subheader(f"📝 Tus Movimientos en {t}")
    movs = info.get('movimientos', [])
    if movs:
        df_movs = pd.DataFrame(movs)
        cols_mostrar = ['Fecha_str', 'Tipo', 'Cantidad', 'Precio', 'Moneda', 'Comision']
        # Renombrar para que se vea bien
        df_movs = df_movs[cols_mostrar].rename(columns={
            'Fecha_str': 'Fecha', 
            'Cantidad': 'Importe Total',
            'Precio': 'Precio Ejecución'
        })
        st.dataframe(
            df_movs.sort_values(by="Fecha", ascending=False), 
            use_container_width=True, 
            hide_index=True
        )
    else:
        st.info("No hay movimientos registrados.")

# ==========================================
#        VISTA PRINCIPAL (DASHBOARD)
# ==========================================
else:
    # --- BARRA LATERAL (Solo visible en dashboard principal) ---
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
                            with st.spinner("Consultando..."):
                                nom, pre, _ = get_stock_data_fmp(ticker)
                                if not nom: nom, pre, _ = get_stock_data_yahoo(ticker)
                            
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

    # --- PANTALLA PRINCIPAL ---
    st.title("💼 Control de Rentabilidad (P&L)")

    # Filtro de visualización para la tabla (los acumulados de arriba no cambian para mantener coherencia de rentabilidad total, 
    # pero puedes ajustar esto si prefieres que las métricas también filtren por año)
    
    # MÉTRICAS GENERALES
    beneficio_neto_total = pnl_global_cerrado + total_dividendos - total_comisiones
    roi_total_pct = 0.0
    if total_compras_historicas_eur > 0:
        roi_total_pct = (beneficio_neto_total / total_compras_historicas_eur) * 100
    
    roi_trading_pct = 0.0
    if coste_ventas_total > 0:
        roi_trading_pct = (pnl_global_cerrado / coste_ventas_total) * 100

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("💰 BENEFICIO TOTAL NETO", f"{beneficio_neto_total:,.2f} €", delta=f"{roi_total_pct:+.2f} % (ROI)")
    m2.metric("Bº/P Trading (Cerrado)", f"{pnl_global_cerrado:,.2f} €", delta=f"{roi_trading_pct:+.2f} %")
    m3.metric("Dividendos Totales", f"{total_dividendos:,.2f} €", delta=None)
    m4.metric("Comisiones Totales", f"-{total_comisiones:,.2f} €", delta="Costes", delta_color="inverse")
    
    st.divider()

    # PREPARAR TABLA FINAL
    # Aquí es donde ocurre la magia de la selección
    tabla_final = []
    fx_usd_now = get_exchange_rate_now("USD", "EUR")

    with st.spinner("Actualizando panel de acciones..."):
        for t, info in cartera_global.items():
            if info['acciones'] > 0.001 or abs(info['pnl_cerrado']) > 0.01:
                saldo_vivo = info['coste_total_eur']
                
                rentabilidad_pct = 0.0
                precio_mercado_str = "0.00"
                logo_url = get_logo_url(t)
                
                if info['acciones'] > 0.001:
                    _, p_now, _ = get_stock_data_fmp(t)
                    if not p_now: _, p_now, _ = get_stock_data_yahoo(t)
                    
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

    if tabla_final:
        df_show = pd.DataFrame(tabla_final)
        st.subheader(f"📊 Cartera Detallada")
        st.info("👆 **Haz clic en una fila** para ver el gráfico y el detalle de la acción.")

        # --- TABLA INTERACTIVA (SELECTION MODE) ---
        # Configuramos para que se pueda seleccionar una fila (single-row)
        event = st.dataframe(
            df_show.style.map(lambda v: 'color: green' if v > 0 else 'color: red', subset=['Bº/P (Cerrado)', '% Latente'])
                         .format({'% Latente': "{:.2%}"}),
            
            column_config={
                "Logo": st.column_config.ImageColumn("Logo", width="small"),
                "Empresa": st.column_config.TextColumn("Empresa"),
                "Ticker": st.column_config.TextColumn("Ticker"),
                "Acciones": st.column_config.NumberColumn("Acciones", format="%.4f"),
                "PMC": st.column_config.NumberColumn("PMC", format="%.2f €"),
                "Saldo Invertido": st.column_config.NumberColumn("Invertido", format="%.2f €"),
                "Bº/P (Cerrado)": st.column_config.NumberColumn("Trading", format="%.2f €"),
                "% Latente": st.column_config.NumberColumn("% Latente", format="%.2f %%")
            },
            use_container_width=True,
            hide_index=True,
            on_select="rerun", # Importante: Recargar al hacer clic
            selection_mode="single-row"
        )
        
        # --- DETECTAR CLIC ---
        if len(event.selection.rows) > 0:
            # Obtenemos el índice de la fila seleccionada
            idx_seleccionado = event.selection.rows[0]
            # Obtenemos el ticker de esa fila
            ticker_seleccionado = df_show.iloc[idx_seleccionado]["Ticker"]
            
            # Guardamos en sesión y recargamos
            st.session_state.ticker_detalle = ticker_seleccionado
            st.rerun()

    else:
        st.info("Añade operaciones para ver tu cartera.")
