import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import altair as alt
import numpy as np 
from pyairtable import Api
from datetime import datetime
from zoneinfo import ZoneInfo
from fpdf import FPDF 

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor V25.1 (Fix Volumen)", layout="wide") 
MONEDA_BASE = "EUR" 

# --- ESTADO ---
if "pending_data" not in st.session_state:
    st.session_state.pending_data = None
if "adding_mode" not in st.session_state:
    st.session_state.adding_mode = False
if "reset_seed" not in st.session_state:
    st.session_state.reset_seed = 0
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
        info = stock.info
        nombre = info.get('longName') or info.get('shortName') or ticker
        desc = info.get('longBusinessSummary') or "Descripción no disponible en Yahoo."
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
        st.success(f"✅ Guardado: {record['Descripcion']} ({record['Ticker']})")
        st.session_state.pending_data = None
        st.session_state.adding_mode = False 
        st.rerun()
    except Exception as e: st.error(f"Error guardando: {e}")

def generar_pdf_historial(dataframe, titulo):
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 12)
            self.cell(0, 10, titulo, 0, 1, 'C')
            self.ln(5)
        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 10, f'Pagina {self.page_no()}', 0, 0, 'C')

    pdf = PDF(orientation='L') 
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    
    cols_map = {
        'Fecha_str': ('Fecha', 35),
        'Tipo': ('Tipo', 25),
        'Ticker': ('Ticker', 20),
        'Descripcion': ('Empresa', 60),
        'Cantidad': ('Importe', 30),
        'Precio': ('Precio', 25),
        'Moneda': ('Div', 15),
        'Comision': ('Com.', 20)
    }
    
    pdf.set_fill_color(200, 220, 255)
    pdf.set_font("Arial", 'B', 10)
    
    cols_validas = []
    for k, (nombre_pdf, ancho) in cols_map.items():
        if k in dataframe.columns:
            cols_validas.append((k, nombre_pdf, ancho))
            pdf.cell(ancho, 10, nombre_pdf, 1, 0, 'C', 1)
    pdf.ln()

    pdf.set_font("Arial", size=9)
    for _, row in dataframe.iterrows():
        for col_key, _, ancho in cols_validas:
            valor = str(row[col_key])
            valor = valor.replace("€", "EUR").encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(ancho, 10, valor, 1, 0, 'C')
        pdf.ln()
        
    return pdf.output(dest='S').encode('latin-1')

# --- APP INICIO ---
if not check_password(): st.stop()

try:
    api = Api(st.secrets["airtable"]["api_token"])
    table = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
except Exception as e:
    st.error(f"Error conectando a Airtable: {e}")
    st.stop()

# 1. CARGA DATOS
try: data = table.all()
except: data = []

df = pd.DataFrame()
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

    cols_numericas = ["Cantidad", "Precio", "Comision"]
    for col in cols_numericas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

# 2. BARRA LATERAL
with st.sidebar:
    st.header("Configuración")
    mis_zonas = ["Atlantic/Canary", "Europe/Madrid", "UTC"]
    mi_zona = st.selectbox("🌍 Tu Zona Horaria:", mis_zonas, index=1)
    st.divider()
    
    st.header("Filtros")
    lista_años = ["Todos los años"]
    if not df.empty and 'Año' in df.columns:
        años_disponibles = sorted(df['Año'].dropna().unique().astype(int), reverse=True)
        lista_años += list(años_disponibles)
    año_seleccionado = st.selectbox("📅 Año Fiscal:", lista_años)
    
    st.write("")
    ver_solo_activas = st.checkbox("👁️ Ocultar posiciones cerradas (0 acciones)", value=False)
    
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
                st.info("💡 Consejo: Si dejas la 'Descripción' vacía, buscaré el nombre automáticamente.")
                tipo = st.selectbox("Tipo", ["Compra", "Venta", "Dividendo"])
                ticker = st.text_input("Ticker (ej. TSLA)").upper().strip()
                desc_manual = st.text_input("Descripción (Opcional - Auto si vacío)")
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
                        
                        nom_api = None
                        pre_api = 0.0

                        with st.spinner(f"Buscando datos de {ticker}..."):
                            nom_api, pre_api, _ = get_stock_data_fmp(ticker)
                            if not nom_api: 
                                nom_api, pre_api, _ = get_stock_data_yahoo(ticker)
                        
                        nombre_final = ""
                        if desc_manual:
                            nombre_final = desc_manual
                        elif nom_api:
                            nombre_final = nom_api
                        else:
                            nombre_final = ticker
                        
                        precio_final = 0.0
                        if precio_manual > 0: precio_final = precio_manual
                        elif pre_api: precio_final = pre_api

                        dt_final = datetime.combine(f_in, h_in)
                        datos = {
                            "Tipo": tipo, "Ticker": ticker, "Descripcion": nombre_final, 
                            "Moneda": moneda, "Cantidad": float(dinero_total),
                            "Precio": float(precio_final), "Comision": float(comision),
                            "Fecha": dt_final.strftime("%Y/%m/%d %H:%M")
                        }
                        
                        if precio_final > 0: guardar_en_airtable(datos)
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

# 3. MOTOR DE CÁLCULO
cartera_global = {}
total_dividendos = 0.0 
total_comisiones = 0.0
pnl_global_cerrado = 0.0 
total_compras_historicas_eur = 0.0
coste_ventas_total = 0.0

roi_history_log = []

if not df.empty:
    for i, row in df.sort_values(by="Fecha_dt").iterrows():
        tipo = row.get('Tipo', 'Desconocido')
        tick = str(row.get('Ticker', 'UNKNOWN')).strip()
        desc = str(row.get('Descripcion', tick)).strip() or tick
        dinero = float(row.get('Cantidad', 0))
        precio = float(row.get('Precio', 1))
        if precio <= 0: precio = 1
        mon = row.get('Moneda', 'EUR')
        comi = float(row.get('Comision', 0))
        fecha_op = row.get('Fecha_dt')
        year_op = row.get('Año')
        
        en_rango = (año_seleccionado == "Todos los años") or (year_op == int(año_seleccionado))

        fx = get_exchange_rate_now(mon, MONEDA_BASE)
        dinero_eur = dinero * fx
        acciones_op = dinero / precio 
        
        delta_profit = 0.0
        delta_invest = 0.0
        
        if tipo == "Compra":
            delta_invest = dinero_eur
        elif tipo == "Venta":
            pass 
        elif tipo == "Dividendo":
            delta_profit += dinero_eur
        
        delta_profit -= (comi * fx)

        if en_rango:
            total_comisiones += (comi * fx)

        if tick not in cartera_global:
            cartera_global[tick] = {
                'acciones': 0.0, 'coste_total_eur': 0.0, 'desc': desc, 
                'pnl_cerrado': 0.0, 'pmc': 0.0, 'moneda_origen': mon,
                'movimientos': []
            }
        
        row['Fecha_Raw'] = fecha_op
        cartera_global[tick]['movimientos'].append(row)

        if tipo == "Compra":
            cartera_global[tick]['acciones'] += acciones_op
            cartera_global[tick]['coste_total_eur'] += dinero_eur
            if en_rango:
                total_compras_historicas_eur += dinero_eur 
            if cartera_global[tick]['acciones'] > 0:
                cartera_global[tick]['pmc'] = cartera_global[tick]['coste_total_eur'] / cartera_global[tick]['acciones']
            if len(desc) > len(cartera_global[tick]['desc']): cartera_global[tick]['desc'] = desc

        elif tipo == "Venta":
            coste_proporcional = acciones_op * cartera_global[tick]['pmc']
            beneficio_operacion = dinero_eur - coste_proporcional
            
            delta_profit += beneficio_operacion

            if en_rango:
                coste_ventas_total += coste_proporcional 
                pnl_global_cerrado += beneficio_operacion
                cartera_global[tick]['pnl_cerrado'] += beneficio_operacion
            
            cartera_global[tick]['acciones'] -= acciones_op
            cartera_global[tick]['coste_total_eur'] -= coste_proporcional 
            if cartera_global[tick]['acciones'] < 0: cartera_global[tick]['acciones'] = 0

        elif tipo == "Dividendo":
            if en_rango:
                total_dividendos += dinero_eur
        
        roi_history_log.append({
            'Fecha': fecha_op, 
            'Year': year_op,
            'Delta_Profit': delta_profit,
            'Delta_Invest': delta_invest
        })

# ==========================================
#        VISTA DETALLE (SI HAY SELECCIÓN)
# ==========================================
if st.session_state.ticker_detalle:
    t = st.session_state.ticker_detalle
    info = cartera_global.get(t, {})
    
    if st.button("⬅️ Volver a la Cartera Principal", type="secondary"):
        st.session_state.ticker_detalle = None
        st.rerun()
    
    st.divider()

    c_logo, c_tit = st.columns([1, 5])
    with c_logo: st.image(get_logo_url(t), width=80)
    with c_tit:
        st.title(f"{info.get('desc', t)} ({t})")
        st.caption("Ficha detallada del activo")

    st.write("⚙️ **Configuración del Gráfico**")
    c_time, c_ind = st.columns([1, 3])
    
    opciones_tiempo = {"1 Mes": "1mo", "6 Meses": "6mo", "1 Año": "1y", "5 Años": "5y", "Todo": "max"}
    label_tiempo = c_time.select_slider("Periodo", options=list(opciones_tiempo.keys()), value="1 Año")
    periodo_api = opciones_tiempo[label_tiempo]
    
    indicadores = c_ind.multiselect(
        "Indicadores Técnicos",
        ["Volumen", "Media Móvil (SMA 50)", "Soportes/Resistencias", "Línea de Tendencia"],
        default=[]
    )
    
    tipo_grafico = st.radio("Estilo de Precio", ["Línea", "Velas"], horizontal=True, label_visibility="collapsed")

    with st.spinner(f"Cargando gráfico ({label_tiempo})..."):
        nombre, precio_now, descripcion_larga = get_stock_data_fmp(t)
        if not precio_now: nombre, precio_now, descripcion_larga = get_stock_data_yahoo(t)
        
        historia = pd.DataFrame()
        try:
            ticker_obj = yf.Ticker(t)
            historia = ticker_obj.history(period=periodo_api)
            historia = historia.reset_index()
            historia['Date'] = pd.to_datetime(historia['Date']).dt.date
            # Limpieza para evitar errores en volumen
            historia['Volume'] = pd.to_numeric(historia['Volume'], errors='coerce').fillna(0)
        except: pass

    # --- CÁLCULO DE INDICADORES ---
    if not historia.empty:
        if "Media Móvil (SMA 50)" in indicadores:
            historia['SMA_50'] = historia['Close'].rolling(window=50).mean()
        
        val_max = historia['High'].max()
        val_min = historia['Low'].min()
        
        if "Línea de Tendencia" in indicadores:
            historia['Date_Ord'] = pd.to_datetime(historia['Date']).map(datetime.toordinal)
            x = historia['Date_Ord'].values
            y = historia['Close'].values
            if len(x) > 1:
                m, b = np.polyfit(x, y, 1)
                historia['Trend'] = m * x + b

    m1, m2, m3, m4 = st.columns(4)
    acciones_activas = info.get('acciones', 0)
    pmc_actual = info.get('pmc', 0)
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
              delta=f"{rentabilidad_latente:+.2f}%" if acciones_activas > 0 else "0%")
    m4.metric("Bº Realizado", f"{info.get('pnl_cerrado',0):,.2f} €", 
              delta="En periodo" if año_seleccionado != "Todos los años" else "Total")

    st.subheader(f"📈 Evolución ({tipo_grafico})")
    
    if not historia.empty:
        # 1. ESTADÍSTICAS (MAX/MIN/AVG)
        stat_max = historia['Close'].max()
        stat_min = historia['Close'].min()
        stat_avg = historia['Close'].mean()
        last_date = historia['Date'].max()
        
        df_price_stats = pd.DataFrame([
            {'Val': stat_max, 'Label': f"Max: {stat_max:.2f}", 'Color': 'green'},
            {'Val': stat_min, 'Label': f"Min: {stat_min:.2f}", 'Color': 'red'},
            {'Val': stat_avg, 'Label': f"Med: {stat_avg:.2f}", 'Color': 'blue'}
        ])
        df_price_stats['Date'] = last_date

        hover = alt.selection_point(fields=['Date'], nearest=True, on='mouseover', empty=False)
        base = alt.Chart(historia).encode(x=alt.X('Date:T', title='Fecha'))
        
        # 2. CAPA PRECIO (VELAS O LÍNEA)
        grafico_base = None
        if tipo_grafico == "Línea":
            grafico_base = base.mark_line(color='#29b5e8').encode(
                y=alt.Y('Close', scale=alt.Scale(zero=False), title='Precio')
            )
        else:
            rule = base.mark_rule().encode(
                y=alt.Y('Low', scale=alt.Scale(zero=False), title='Precio'),
                y2='High',
                color=alt.condition("datum.Open < datum.Close", alt.value("#00C805"), alt.value("#FF0000"))
            )
            bar = base.mark_bar(width=8).encode(
                y='Open',
                y2='Close',
                color=alt.condition("datum.Open < datum.Close", alt.value("#00C805"), alt.value("#FF0000"))
            )
            grafico_base = rule + bar

        # 3. INTERACTIVIDAD (CROSSHAIR + TOOLTIP)
        points = base.mark_point().encode(opacity=alt.value(0)).add_params(hover)
        tooltips = [
            alt.Tooltip('Date', title='Fecha', format='%Y-%m-%d'),
            alt.Tooltip('Close', title='Cierre', format='.2f'),
            alt.Tooltip('Volume', title='Volumen', format=',')
        ]
        rule_vertical = base.mark_rule(color='black', strokeDash=[4, 4]).encode(
            opacity=alt.condition(hover, alt.value(1), alt.value(0)),
            tooltip=tooltips
        )

        # 4. CAPAS DE ESTADÍSTICAS
        rules_stats = alt.Chart(df_price_stats).mark_rule(strokeDash=[4, 4], opacity=0.7).encode(
            y='Val', color=alt.Color('Color', scale=None)
        )
        text_stats = alt.Chart(df_price_stats).mark_text(align='left', dx=5, dy=-10).encode(
            x='Date', y='Val', text='Label', color=alt.Color('Color', scale=None)
        )

        # 5. CAPAS DE OPERACIONES (TRIÁNGULOS)
        movs_raw = info.get('movimientos', [])
        capa_compras = alt.Chart(pd.DataFrame()).mark_point()
        capa_ventas = alt.Chart(pd.DataFrame()).mark_point()
        COLOR_COMPRA = "#0044FF"  
        COLOR_VENTA = "#800020"   

        if movs_raw:
            df_movs_chart = pd.DataFrame(movs_raw)
            df_movs_chart['Date'] = pd.to_datetime(df_movs_chart['Fecha_Raw']).dt.date
            min_date = historia['Date'].min()
            df_movs_chart = df_movs_chart[df_movs_chart['Date'] >= min_date]
            
            if not df_movs_chart.empty:
                compras = df_movs_chart[df_movs_chart['Tipo'] == 'Compra']
                if not compras.empty:
                    rule_compra = alt.Chart(compras).mark_rule(color=COLOR_COMPRA, strokeDash=[4, 4], opacity=0.6).encode(x='Date:T')
                    point_compra = alt.Chart(compras).mark_point(shape='triangle-up', size=150, color=COLOR_COMPRA, filled=True, opacity=1).encode(
                        x='Date:T', y='Precio', tooltip=['Date', 'Precio', 'Cantidad']
                    )
                    capa_compras = rule_compra + point_compra

                ventas = df_movs_chart[df_movs_chart['Tipo'] == 'Venta']
                if not ventas.empty:
                    rule_venta = alt.Chart(ventas).mark_rule(color=COLOR_VENTA, strokeDash=[4, 4], opacity=0.6).encode(x='Date:T')
                    point_venta = alt.Chart(ventas).mark_point(shape='triangle-down', size=150, color=COLOR_VENTA, filled=True, opacity=1).encode(
                        x='Date:T', y='Precio', tooltip=['Date', 'Precio', 'Cantidad']
                    )
                    capa_ventas = rule_venta + point_venta

        # --- ENSAMBLAJE FINAL DEL GRÁFICO (FIX V25.1) ---
        
        # Grupo 1: Capas relacionadas con el PRECIO (Eje Y Izquierdo)
        layers_precio = [
            grafico_base, 
            points, 
            rule_vertical, 
            rules_stats, 
            text_stats, 
            capa_compras, 
            capa_ventas
        ]

        # Añadir indicadores de precio si existen
        if "Media Móvil (SMA 50)" in indicadores:
            sma = base.mark_line(color='orange', strokeDash=[2,2]).encode(
                y='SMA_50', tooltip=[alt.Tooltip('SMA_50', title='SMA 50', format='.2f')]
            )
            layers_precio.append(sma)

        if "Línea de Tendencia" in indicadores and 'Trend' in historia.columns:
            trend = base.mark_line(color='purple', strokeWidth=2).encode(
                y='Trend', tooltip=[alt.Tooltip('Trend', title='Tendencia', format='.2f')]
            )
            layers_precio.append(trend)

        if "Soportes/Resistencias" in indicadores:
            res_line = base.mark_rule(color='green', strokeDash=[5,5]).encode(y=alt.datum(val_max))
            sup_line = base.mark_rule(color='red', strokeDash=[5,5]).encode(y=alt.datum(val_min))
            layers_precio.append(res_line)
            layers_precio.append(sup_line)

        # Combinamos todo lo que es PRECIO en un solo gráfico
        chart_precio = alt.layer(*layers_precio)

        # Grupo 2: Capa de VOLUMEN (Eje Y Derecho)
        if "Volumen" in indicadores:
            vol = base.mark_bar(opacity=0.3, color='#CCCCCC').encode(
                y=alt.Y('Volume', axis=alt.Axis(title='Volumen', orient='right', grid=False)),
                # Quitamos tooltip del volumen para no ensuciar la cruz del precio
            )
            # FUSIONAMOS CON ESCALAS INDEPENDIENTES
            chart_final = alt.layer(chart_precio, vol).resolve_scale(y='independent')
        else:
            chart_final = chart_precio

        st.altair_chart(chart_final, use_container_width=True)
        st.caption(f"🔵 **Compra (Azul)** | 🍷 **Venta (Burdeos)**")
        
    else:
        st.warning("No se pudo cargar el historial de precios.")

    with st.expander("📖 Sobre la empresa"):
        st.write(descripcion_larga if descripcion_larga else "No hay descripción disponible.")

    st.subheader(f"📝 Historial de Operaciones")
    if movs_raw:
        df_movs_show = pd.DataFrame(movs_raw)
        df_movs_show = df_movs_show[['Fecha_str', 'Tipo', 'Cantidad', 'Precio', 'Moneda', 'Comision']]
        df_movs_show = df_movs_show.rename(columns={'Fecha_str': 'Fecha', 'Cantidad': 'Importe Total'})
        
        def color_rows_detail(row):
            color = ''
            if row['Tipo'] == 'Compra': color = 'color: green'
            elif row['Tipo'] == 'Venta': color = 'color: #800020'
            elif row['Tipo'] == 'Dividendo': color = 'color: #FF8C00'
            return [color] * len(row)

        st.dataframe(
            df_movs_show.sort_values(by="Fecha", ascending=False).style.apply(color_rows_detail, axis=1), 
            use_container_width=True, 
            hide_index=True
        )

# ==========================================
#        VISTA DASHBOARD (PRINCIPAL)
# ==========================================
else:
    st.title("💼 Control de Rentabilidad (P&L)")
    
    beneficio_neto_total = pnl_global_cerrado + total_dividendos - total_comisiones
    roi_total_pct = 0.0
    if total_compras_historicas_eur > 0:
        roi_total_pct = (beneficio_neto_total / total_compras_historicas_eur) * 100
    
    roi_trading_pct = 0.0
    if coste_ventas_total > 0:
        roi_trading_pct = (pnl_global_cerrado / coste_ventas_total) * 100

    m1, m2, m3, m4 = st.columns(4)
    tit = f"({año_seleccionado})"
    m1.metric(f"💰 Bº NETO {tit}", f"{beneficio_neto_total:,.2f} €", delta=f"{roi_total_pct:+.2f} % (ROI)")
    m2.metric(f"Trading {tit}", f"{pnl_global_cerrado:,.2f} €", delta=f"{roi_trading_pct:+.2f} %")
    m3.metric(f"Dividendos {tit}", f"{total_dividendos:,.2f} €", delta=None)
    m4.metric(f"Comisiones {tit}", f"-{total_comisiones:,.2f} €", delta="Costes", delta_color="inverse")
    
    # --- GRÁFICO ROI CON STATS ---
    if roi_history_log:
        df_roi = pd.DataFrame(roi_history_log)
        df_roi['Fecha'] = pd.to_datetime(df_roi['Fecha'])
        
        if año_seleccionado != "Todos los años":
            df_roi = df_roi[df_roi['Year'] == int(año_seleccionado)]
        
        if not df_roi.empty:
            df_roi.set_index('Fecha', inplace=True)
            df_roi_w = df_roi.resample('W').sum().fillna(0)
            df_roi_w['Cum_Profit'] = df_roi_w['Delta_Profit'].cumsum()
            df_roi_w['Cum_Invest'] = df_roi_w['Delta_Invest'].cumsum()
            df_roi_w['ROI_Pct'] = df_roi_w.apply(
                lambda x: (x['Cum_Profit'] / x['Cum_Invest'] * 100) if x['Cum_Invest'] > 0 else 0.0, axis=1
            )
            df_roi_w = df_roi_w.reset_index()

            y_min = df_roi_w['ROI_Pct'].min()
            y_max = df_roi_w['ROI_Pct'].max()
            
            stops = []
            if y_min >= 0:
                stops = [alt.GradientStop(color='#00C805', offset=0), alt.GradientStop(color='#00C805', offset=1)]
            elif y_max <= 0:
                stops = [alt.GradientStop(color='#FF0000', offset=0), alt.GradientStop(color='#FF0000', offset=1)]
            else:
                range_total = y_max - y_min
                offset_zero = abs(y_max) / range_total
                stops = [
                    alt.GradientStop(color='#00C805', offset=0),            
                    alt.GradientStop(color='#00C805', offset=offset_zero),  
                    alt.GradientStop(color='#FF0000', offset=offset_zero),  
                    alt.GradientStop(color='#FF0000', offset=1)             
                ]

            hover_roi = alt.selection_point(
                fields=['Fecha'], nearest=True, on='mouseover', empty=False
            )

            base_roi = alt.Chart(df_roi_w).encode(x=alt.X('Fecha:T', title=""))

            area = base_roi.mark_area(
                opacity=0.6,
                line={'color': '#800080', 'strokeWidth': 2},
                color=alt.Gradient(
                    gradient='linear', stops=stops, x1=1, x2=1, y1=0, y2=1
                )
            ).encode(y=alt.Y('ROI_Pct', title="ROI Acumulado (%)"))
            
            selectors = base_roi.mark_point().encode(opacity=alt.value(0)).add_params(hover_roi)

            tooltips_roi = [
                alt.Tooltip('Fecha', title='Fecha', format='%Y-%m-%d'),
                alt.Tooltip('ROI_Pct', title='ROI %', format='.2f'),
                alt.Tooltip('Cum_Profit', title='Bº Neto (€)', format='.2f')
            ]
            rule_hover = base_roi.mark_rule(color='black', strokeDash=[4, 4]).encode(
                opacity=alt.condition(hover_roi, alt.value(1), alt.value(0)),
                tooltip=tooltips_roi
            )
            
            rule_zero = alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(color='black', strokeDash=[2,2], opacity=0.5).encode(y='y')

            # STATS DASHBOARD
            stat_max = df_roi_w['ROI_Pct'].max()
            stat_min = df_roi_w['ROI_Pct'].min()
            stat_avg = df_roi_w['ROI_Pct'].mean()
            last_date = df_roi_w['Fecha'].max()
            
            df_stats = pd.DataFrame([
                {'Val': stat_max, 'Label': f"Max: {stat_max:.2f}%", 'Color': 'green'},
                {'Val': stat_min, 'Label': f"Min: {stat_min:.2f}%", 'Color': 'red'},
                {'Val': stat_avg, 'Label': f"Med: {stat_avg:.2f}%", 'Color': 'blue'}
            ])
            df_stats['Date'] = last_date

            rules_stats = alt.Chart(df_stats).mark_rule(strokeDash=[4, 4], opacity=0.7).encode(
                y='Val', color=alt.Color('Color', scale=None)
            )
            text_stats = alt.Chart(df_stats).mark_text(align='left', dx=5, dy=-10).encode(
                x='Date', y='Val', text='Label', color=alt.Color('Color', scale=None)
            )

            st.altair_chart((area + rule_zero + selectors + rule_hover + rules_stats + text_stats), use_container_width=True)
        else:
            st.info("No hay datos suficientes para generar la curva de ROI.")

    st.divider()

    tabla_final = []
    fx_usd_now = get_exchange_rate_now("USD", "EUR")

    with st.spinner("Actualizando panel de acciones..."):
        for t, info in cartera_global.items():
            es_viva = info['acciones'] > 0.001
            tuvo_actividad = abs(info['pnl_cerrado']) > 0.01
            
            mostrar = False
            if ver_solo_activas: mostrar = es_viva
            else: mostrar = es_viva or tuvo_actividad

            if mostrar:
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
                    "Logo": logo_url, "Empresa": info['desc'], "Ticker": t,
                    "Acciones": info['acciones'], "PMC": info['pmc'],
                    "Precio Mercado": precio_mercado_str, "Saldo Invertido": saldo_vivo,
                    "Bº/P (Cerrado)": info['pnl_cerrado'], "% Latente": rentabilidad_pct
                })

    if tabla_final:
        df_show = pd.DataFrame(tabla_final)
        st.subheader(f"📊 Cartera Detallada")
        st.info("👆 **Haz clic en una fila** para ver el gráfico interactivo.")
        
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
            use_container_width=True, hide_index=True,
            on_select="rerun", selection_mode="single-row"
        )
        
        if len(event.selection.rows) > 0:
            idx = event.selection.rows[0]
            st.session_state.ticker_detalle = df_show.iloc[idx]["Ticker"]
            st.rerun()
    else:
        st.info("No hay datos para el periodo seleccionado.")

    st.divider()
    st.subheader(f"📜 Historial de Órdenes y Dividendos ({año_seleccionado})")
    
    if not df.empty:
        df_historial = df.copy()
        if año_seleccionado != "Todos los años":
            df_historial = df_historial[df_historial['Año'] == int(año_seleccionado)]
        
        if not df_historial.empty:
            cols_ver = ['Fecha_str', 'Tipo', 'Ticker', 'Descripcion', 'Cantidad', 'Precio', 'Moneda', 'Comision']
            cols_ver = [c for c in cols_ver if c in df_historial.columns]
            df_export = df_historial[cols_ver].sort_values(by='Fecha_str', ascending=False)
            
            c_csv, c_pdf = st.columns(2)
            
            csv = df_export.to_csv(index=False).encode('utf-8')
            c_csv.download_button(
                label="📥 Exportar a Excel (CSV)",
                data=csv,
                file_name=f"historial_{año_seleccionado}.csv",
                mime="text/csv",
                use_container_width=True
            )
            
            try:
                pdf_bytes = generar_pdf_historial(df_export, f"Historial {año_seleccionado}")
                c_pdf.download_button(
                    label="📄 Exportar a PDF",
                    data=pdf_bytes,
                    file_name=f"historial_{año_seleccionado}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            except Exception as e:
                c_pdf.warning(f"Error generando PDF: {e}")

            def color_rows(row):
                color = ''
                if row['Tipo'] == 'Compra':
                    color = 'color: green'
                elif row['Tipo'] == 'Venta':
                    color = 'color: #800020'
                elif row['Tipo'] == 'Dividendo':
                    color = 'color: #FF8C00'
                return [color] * len(row)

            st.dataframe(
                df_export.style.apply(color_rows, axis=1),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No hay operaciones registradas en este periodo.")
