import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import altair as alt
import numpy as np 
from pyairtable import Api
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fpdf import FPDF
import time

# --- INTENTO DE IMPORTAR TRADUCTOR ---
try:
    from deep_translator import GoogleTranslator
    HAS_TRANSLATOR = True
except ImportError:
    HAS_TRANSLATOR = False

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor V32.41 (Tooltips & Historical Fix)", layout="wide") 
MONEDA_BASE = "EUR" 

# --- ESTADO ---
if "pending_data" not in st.session_state: st.session_state.pending_data = None
if "adding_mode" not in st.session_state: st.session_state.adding_mode = False
if "reset_seed" not in st.session_state: st.session_state.reset_seed = 0
if "ticker_detalle" not in st.session_state: st.session_state.ticker_detalle = None
if "current_user" not in st.session_state: st.session_state.current_user = None
if "user_role" not in st.session_state: st.session_state.user_role = "user"

if "cfg_zona" not in st.session_state: st.session_state.cfg_zona = "Europe/Madrid"
if "cfg_movil" not in st.session_state: st.session_state.cfg_movil = False

# --- CONEXIÓN AIRTABLE ---
try:
    api = Api(st.secrets["airtable"]["api_token"])
    table_ops = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["table_name"])
    table_users = api.table(st.secrets["airtable"]["base_id"], st.secrets["airtable"]["user_table_name"])
except Exception as e:
    st.error(f"Error crítico de configuración Airtable: {e}")
    st.stop()

# --- FUNCIONES DE AUTENTICACIÓN ---
def get_all_users():
    try:
        records = table_users.all()
        return {r['fields']['Username']: r['fields'] for r in records if 'Username' in r['fields']}
    except: return {}

def register_new_user(username, password, name):
    try:
        existing = get_all_users()
        if username in existing: return False, "El usuario ya existe."
        table_users.create({"Username": username, "Password": password, "Nombre": name, "Rol": "user"})
        return True, "Usuario creado correctamente."
    except Exception as e: return False, f"Error creando usuario: {e}"

def login_system():
    if st.session_state.current_user: return True
    try: query_params = st.query_params
    except: query_params = st.experimental_get_query_params()
    invite_code_url = query_params.get("invite", "")
    if isinstance(invite_code_url, list): invite_code_url = invite_code_url[0]

    st.header("🔐 Acceso al Portal")
    tab1, tab2 = st.tabs(["Iniciar Sesión", "Registrarse"])
    
    with tab1:
        with st.form("login_form"):
            user_in = st.text_input("Usuario")
            pass_in = st.text_input("Contraseña", type="password")
            if st.form_submit_button("Entrar", type="primary"):
                users_db = get_all_users()
                if user_in in users_db and users_db[user_in].get('Password') == pass_in:
                    st.session_state.current_user = user_in
                    st.session_state.user_role = users_db[user_in].get('Rol', 'user')
                    st.rerun()
                else: st.error("Incorrecto")
    with tab2:
        with st.form("register_form"):
            new_user = st.text_input("Nuevo Usuario")
            new_pass = st.text_input("Nueva Contraseña", type="password")
            new_name = st.text_input("Tu Nombre")
            code_in = st.text_input("Código de Invitación", value=invite_code_url)
            if st.form_submit_button("Crear Cuenta"):
                if code_in == st.secrets["general"]["invite_code"]:
                    if new_user and new_pass:
                        ok, msg = register_new_user(new_user, new_pass, new_name)
                        if ok: 
                            st.success(msg)
                            time.sleep(1)
                            st.rerun()
                        else: st.error(msg)
                    else: st.warning("Rellena todo")
                else: st.error("Código inválido")
    return False

# --- FUNCIONES DATOS Y FORMATO ---
def traducir_texto(texto):
    if not texto or texto == "Sin descripción.": return texto
    if not HAS_TRANSLATOR: return texto
    try: return GoogleTranslator(source='auto', target='es').translate(texto[:4999])
    except: return texto

def fmt_dinamico(valor, sufijo="", decimales=3):
    if valor is None: return ""
    s = f"{valor:,.{decimales}f}" 
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    if "," in s: s = s.rstrip('0').rstrip(',')
    if s == "": s = "0"
    return f"{s} {sufijo}"

def fmt_num_es(valor):
    if valor is None: return "0,00"
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- FUNCION CRITICA: BUSQUEDA PRECIO HISTORICO ---
def get_historical_stock_price(ticker, dt_obj):
    """Obtiene el precio de cierre para el día solicitado (o el anterior disponible)."""
    try:
        stock = yf.Ticker(ticker)
        # Búsqueda en un rango de 4 días para evitar fines de semana
        start_date = dt_obj.date()
        end_date = start_date + timedelta(days=4)
        data = stock.history(start=start_date, end=end_date)
        if not data.empty:
            return float(data['Close'].iloc[0])
    except: pass
    return 0.0

def get_historical_eur_rate(date_obj, from_currency):
    if from_currency == "EUR": return 1.0
    ticker = f"{MONEDA_BASE}=X" if from_currency == "USD" else f"{from_currency}{MONEDA_BASE}=X"
    start_date = date_obj - timedelta(days=3)
    end_date = date_obj + timedelta(days=1)
    try:
        data = yf.download(ticker, start=start_date, end=end_date, progress=False)
        if not data.empty:
            rate = data['Close'].iloc[-1]
            if isinstance(rate, (pd.Series, pd.DataFrame)): rate = float(rate.iloc[0])
            return float(rate)
    except: pass
    return 1.0

@st.cache_data(ttl=300, show_spinner=False) 
def get_exchange_rate_now(from_curr, to_curr="EUR"):
    if from_curr == to_curr: return 1.0
    try:
        pair = f"{to_curr}=X" if from_curr == "USD" else f"{from_curr}{to_curr}=X"
        hist = yf.Ticker(pair).history(period="1d")
        if not hist.empty:
            return hist['Close'].iloc[-1]
    except: pass
    return 1.0 

@st.cache_data(show_spinner=False)
def get_ticker_isin(ticker):
    try:
        t = yf.Ticker(ticker)
        isin = t.isin
        if isin and isin != '-' and len(isin) > 5: return isin
    except: pass
    try:
        api_key = st.secrets["fmp"]["api_key"]
        url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey={api_key}"
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0:
                isin = data[0].get('isin')
                if isin and len(isin) > 5: return isin
    except: pass
    return ""

def get_logo_url(ticker):
    return f"https://financialmodelingprep.com/image-stock/{ticker}.png"

def get_stock_data_fmp(ticker):
    try:
        api_key = st.secrets["fmp"]["api_key"]
        url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey={api_key}"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                return data[0].get('companyName'), data[0].get('price'), traducir_texto(data[0].get('description'))
    except: pass
    return None, None, None

def get_stock_data_yahoo(ticker):
    try:
        stock = yf.Ticker(ticker)
        precio = None
        try: precio = stock.fast_info.last_price
        except: pass
        if precio is None:
            try:
                hist = stock.history(period="1d")
                if not hist.empty: precio = hist['Close'].iloc[-1]
            except: pass
        try:
            info = stock.info
            nombre = info.get('longName') or info.get('shortName') or ticker
            desc = traducir_texto(info.get('longBusinessSummary') or "Sin descripción.")
        except:
            nombre = ticker
            desc = "Sin descripción."
        if precio: return nombre, precio, desc
    except: pass
    return None, None, None

def guardar_en_airtable(record):
    try:
        # 1. Envía el dato a la nube (Airtable)
        record["Usuario"] = st.session_state.current_user
        table_ops.create(record)
        
        # 2. Muestra mensaje de éxito
        st.toast(f"✅ Operación Guardada: {record['Ticker']}", icon="💾")
        time.sleep(1) 
        
        # 3. Limpia el formulario
        st.session_state.pending_data = None
        st.session_state.adding_mode = False 
        
        # 4. ¡LA CLAVE! Reinicia la app completa
        st.rerun()
    except Exception as e: st.error(f"Error guardando: {e}")

# --- GENERADORES PDF ---
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
    cols_map = {'Fecha_str': ('Fecha', 35), 'Ticker': ('Ticker', 15), 'Descripcion': ('Empresa', 50), 'Cantidad': ('Cant.', 25), 'Precio': ('Precio', 25), 'Moneda': ('Div', 15), 'Comision': ('Com.', 20), 'Usuario': ('Usuario', 30)}
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
            val = row[col_key]
            if isinstance(val, (int, float)) and col_key not in ['Cantidad']: 
                valor = fmt_num_es(val)
            else:
                valor = str(val).replace("€", "EUR").encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(ancho, 10, valor, 1, 0, 'C')
        pdf.ln()
    return pdf.output(dest='S').encode('latin-1')

def generar_informe_fiscal_completo(datos_fiscales, año, nombre_titular, dni_titular):
    class PDF_Fiscal(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 14)
            self.cell(0, 10, f"Informe Fiscal - Ejercicio {año}", 0, 1, 'C')
            self.set_font('Arial', '', 10)
            self.cell(0, 5, f"Titular: {nombre_titular} | NIF/DNI: {dni_titular}", 0, 1, 'C')
            self.set_font('Arial', 'I', 8)
            self.cell(0, 5, f"Generado el {datetime.now().strftime('%d/%m/%Y')}", 0, 1, 'C')
            self.ln(5)
        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 10, f'Pág {self.page_no()}', 0, 0, 'C')

    pdf = PDF_Fiscal(orientation='L')
    pdf.add_page()
    
    # 1. GANANCIAS
    pdf.set_font("Arial", 'B', 12)
    pdf.set_fill_color(200, 200, 200)
    pdf.cell(0, 10, "1. Ganancias y Pérdidas Patrimoniales (Acciones)", 1, 1, 'L', 1)
    pdf.ln(2)

    pdf.set_font("Arial", 'B', 8)
    cols = [("Ticker", 15), ("Empresa", 35), ("ISIN", 25), ("F. Venta", 20), ("F. Compra", 20), ("Cant.", 15), ("V. Transm.", 25), ("V. Adquis.", 25), ("Rendimiento", 25)]
    for txt, w in cols: pdf.cell(w, 8, txt, 1, 0, 'C')
    pdf.ln()
    
    pdf.set_font("Arial", '', 8)
    total_ganancias = 0.0
    ops_acciones = [d for d in datos_fiscales if d['Tipo'] == "Ganancia/Pérdida"]
    
    for op in ops_acciones:
        rend = op['Rendimiento']
        total_ganancias += rend
        empresa_txt = str(op.get('Empresa', ''))[:18]

        pdf.cell(15, 8, str(op['Ticker']), 1, 0, 'C')
        pdf.cell(35, 8, empresa_txt, 1, 0, 'L')
        pdf.cell(25, 8, str(op.get('ISIN', '')), 1, 0, 'C') 
        pdf.cell(20, 8, str(op['Fecha Venta']), 1, 0, 'C')
        pdf.cell(20, 8, str(op['Fecha Compra']), 1, 0, 'C')
        pdf.cell(15, 8, fmt_dinamico(op['Cantidad']), 1, 0, 'C')
        pdf.cell(25, 8, f"{fmt_num_es(op['V. Transmisión'])}", 1, 0, 'R')
        pdf.cell(25, 8, f"{fmt_num_es(op['V. Adquisición'])}", 1, 0, 'R')
        
        if rend >= 0: pdf.set_text_color(0, 150, 0)
        else: pdf.set_text_color(200, 0, 0)
        
        pdf.cell(25, 8, f"{fmt_num_es(rend)}", 1, 0, 'R')
        pdf.set_text_color(0, 0, 0)
        pdf.ln()

    # Total 1
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(170, 10, "TOTAL GANANCIA/PÉRDIDA PATRIMONIAL:", 0, 0, 'R')
    if total_ganancias >= 0: pdf.set_text_color(0, 150, 0)
    else: pdf.set_text_color(200, 0, 0)
    pdf.cell(35, 10, f"{fmt_num_es(total_ganancias)} EUR", 0, 1, 'R')
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)

    # 2. DIVIDENDOS
    pdf.set_font("Arial", 'B', 12)
    pdf.set_fill_color(200, 200, 200)
    pdf.cell(0, 10, "2. Rendimientos del Capital Mobiliario (Dividendos)", 1, 1, 'L', 1)
    pdf.ln(2)

    pdf.set_font("Arial", 'B', 9)
    cols_div = [("Ticker", 30), ("Fecha Cobro", 40), ("Importe Bruto", 40), ("Gastos Ded.", 40), ("Importe Neto", 40)]
    for txt, w in cols_div: pdf.cell(w, 8, txt, 1, 0, 'C')
    pdf.ln()

    pdf.set_font("Arial", '', 9)
    total_divs_neto = 0.0
    ops_divs = [d for d in datos_fiscales if d['Tipo'] == "Dividendo"]

    for op in ops_divs:
        total_divs_neto += op['Neto']
        pdf.cell(30, 8, str(op['Ticker']), 1, 0, 'C')
        pdf.cell(40, 8, str(op['Fecha']), 1, 0, 'C')
        pdf.cell(40, 8, f"{fmt_num_es(op['Bruto'])}", 1, 0, 'R')
        pdf.cell(40, 8, f"{fmt_num_es(op['Gastos'])}", 1, 0, 'R')
        pdf.cell(40, 8, f"{fmt_num_es(op['Neto'])}", 1, 0, 'R')
        pdf.ln()

    # Total 2
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(160, 10, "TOTAL RENDIMIENTOS (NETO):", 0, 0, 'R')
    pdf.cell(30, 10, f"{fmt_num_es(total_divs_neto)} EUR", 0, 1, 'R')
    
    return pdf.output(dest='S').encode('latin-1')

# --- APP INICIO ---
if not login_system(): st.stop()

# BARRA DE USUARIO
c_user, c_logout = st.columns([6, 1])
c_user.write(f"👤 **{st.session_state.current_user}** ({st.session_state.user_role.upper()})")
if c_logout.button("Salir"):
    st.session_state.current_user = None
    st.session_state.password_correct = False
    st.rerun()

ver_todo = False
if st.session_state.user_role == 'admin':
    ver_todo = st.toggle("👁️ Modo Admin", value=False)

# CARGA DATOS
try: data = table_ops.all()
except: data = []

df = pd.DataFrame()
if data:
    df = pd.DataFrame([x['fields'] for x in data])
    df.columns = df.columns.str.strip() 
    if 'Usuario' in df.columns:
        if not ver_todo: df = df[df['Usuario'] == st.session_state.current_user]
    else:
        if not ver_todo: df = pd.DataFrame()

    if not df.empty:
        if 'Fecha' in df.columns:
            df['Fecha_dt'] = pd.to_datetime(df['Fecha'], errors='coerce')
            df['Año'] = df['Fecha_dt'].dt.year 
            df['Fecha_str'] = df['Fecha_dt'].dt.strftime('%Y/%m/%d %H:%M').fillna("")
        else: 
            df['Año'] = datetime.now().year
            df['Fecha_dt'] = datetime.now()
        for col in ["Cantidad", "Precio", "Comision"]:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        if 'Cambio' not in df.columns: df['Cambio'] = 1.0
        df['Cambio'] = pd.to_numeric(df['Cambio'], errors='coerce').fillna(1.0)

# ==============================================================================
# 1. SIDEBAR: FILTROS E IMPUESTOS
# ==============================================================================
with st.sidebar:
    st.header("Filtros")
    lista_años = ["Todos los años"]
    if not df.empty and 'Año' in df.columns:
        años_disponibles = sorted(df['Año'].dropna().unique().astype(int), reverse=True)
        lista_años += list(años_disponibles)
    año_seleccionado = st.selectbox("📅 Año Fiscal:", lista_años)
    ver_solo_activas = st.checkbox("👁️ Ocultar posiciones cerradas", value=False)
    st.divider()

# ==============================================================================
# 2. MOTOR DE CÁLCULO (FIFO + ROI + FISCAL)
# ==============================================================================
cartera = {}
total_div, total_comi, pnl_cerrado, compras_eur, ventas_coste = 0.0, 0.0, 0.0, 0.0, 0.0
roi_log = []
reporte_fiscal_log = []

if not df.empty:
    colas_fifo = {}
    isin_cache_local = {}

    for i, row in df.sort_values(by="Fecha_dt").iterrows():
        tipo, tick = row.get('Tipo'), str(row.get('Ticker', 'UNKNOWN')).strip()
        dinero, precio = float(row.get('Cantidad', 0)), float(row.get('Precio', 1))
        mon, comi = row.get('Moneda', 'EUR'), float(row.get('Comision', 0))
        
        # Como en esta versión ya convertimos a EUR en el guardado, dinero ya es EUR
        dinero_eur = dinero
        if precio <= 0: precio = 0.0001
        
        acciones_op = round(dinero / precio, 8) 
        
        en_rango_visual = (año_seleccionado == "Todos los años") or (row.get('Año') == int(año_seleccionado))
        es_año_fiscal = (row.get('Año') == int(año_seleccionado)) if año_seleccionado != "Todos los años" else True

        delta_p, delta_i = 0.0, 0.0
        
        if en_rango_visual: total_comi += comi
        delta_p -= comi

        if tick not in cartera:
            colas_fifo[tick] = [] 
            desc_ini = row.get('Descripcion', tick)
            cartera[tick] = {'acciones': 0.0, 'coste_total_eur': 0.0, 'desc': desc_ini, 'pnl_cerrado': 0.0, 'pmc': 0.0, 'moneda_origen': mon, 'movimientos': [], 'lotes': colas_fifo[tick]}
        
        row['Fecha_Raw'] = row.get('Fecha_dt')
        cartera[tick]['movimientos'].append(row)

        if tipo == "Compra":
            delta_i = dinero_eur
            cartera[tick]['acciones'] += acciones_op
            cartera[tick]['coste_total_eur'] += dinero_eur
            if en_rango_visual: compras_eur += dinero_eur
            
            colas_fifo[tick].append({'fecha': row.get('Fecha_dt'), 'fecha_str': row.get('Fecha_str', '').split(' ')[0], 'acciones_restantes': acciones_op, 'coste_por_accion_eur': dinero_eur / acciones_op if acciones_op > 0 else 0})
            if cartera[tick]['acciones'] > 0: cartera[tick]['pmc'] = cartera[tick]['coste_total_eur'] / cartera[tick]['acciones']

        elif tipo == "Venta":
            acciones_a_vender = acciones_op
            coste_total_venta_fifo = 0.0
            valor_transmision_neto_total = dinero_eur - comi 
            precio_venta_neto_unitario = valor_transmision_neto_total / acciones_op if acciones_op > 0 else 0

            isin_actual = ""
            if es_año_fiscal:
                if tick not in isin_cache_local: isin_cache_local[tick] = get_ticker_isin(tick)
                isin_actual = isin_cache_local[tick]

            while acciones_a_vender > 0.00000001 and colas_fifo[tick]:
                lote = colas_fifo[tick][0]
                cantidad_consumida = min(lote['acciones_restantes'], acciones_a_vender)
                
                coste_total_venta_fifo += cantidad_consumida * lote['coste_por_accion_eur']
                
                if es_año_fiscal:
                    v_adquisicion = cantidad_consumida * lote['coste_por_accion_eur']
                    v_transmision = cantidad_consumida * precio_venta_neto_unitario
                    reporte_fiscal_log.append({
                        "Tipo": "Ganancia/Pérdida", "Ticker": tick, "Empresa": cartera[tick]['desc'],
                        "ISIN": isin_actual, "Fecha Venta": row.get('Fecha_str', '').split(' ')[0], 
                        "Fecha Compra": lote['fecha_str'], "Cantidad": cantidad_consumida, 
                        "V. Transmisión": v_transmision, "V. Adquisición": v_adquisicion, "Rendimiento": v_transmision - v_adquisicion
                    })

                lote['acciones_restantes'] -= cantidad_consumida
                acciones_a_vender -= cantidad_consumida
                if lote['acciones_restantes'] <= 0: colas_fifo[tick].pop(0)

            beneficio = (dinero_eur - comi) - coste_total_venta_fifo
            delta_p += beneficio
            
            if en_rango_visual: 
                ventas_coste += coste_total_venta_fifo
                pnl_cerrado += beneficio
                cartera[tick]['pnl_cerrado'] += beneficio
            
            cartera[tick]['acciones'] -= acciones_op
            cartera[tick]['coste_total_eur'] -= coste_total_venta_fifo
            cartera[tick]['pmc'] = cartera[tick]['coste_total_eur'] / cartera[tick]['acciones'] if cartera[tick]['acciones'] > 0 else 0

        elif tipo == "Dividendo":
            delta_p += dinero_eur
            div_neto = dinero_eur - comi
            if en_rango_visual: total_div += dinero_eur
            if es_año_fiscal:
                reporte_fiscal_log.append({
                    "Tipo": "Dividendo", "Ticker": tick, "Empresa": cartera[tick]['desc'],
                    "Fecha": row.get('Fecha_str', '').split(' ')[0], "Bruto": dinero_eur,
                    "Gastos": comi, "Neto": div_neto
                })
        
        roi_log.append({'Fecha': row.get('Fecha_dt'), 'Year': row.get('Año'), 'Delta_Profit': delta_p, 'Delta_Invest': delta_i})

# ==============================================================================
# 3. SIDEBAR (BOT): IMPUESTOS + REGISTRO
# ==============================================================================
with st.sidebar:
    if año_seleccionado != "Todos los años" and reporte_fiscal_log:
        st.markdown(f"**⚖️ Impuestos {año_seleccionado}**")
        with st.expander("📝 Datos Titular"):
            nombre_titular = st.text_input("Nombre:")
            dni_titular = st.text_input("DNI:")
        
        pdf_fiscal = generar_informe_fiscal_completo(reporte_fiscal_log, año_seleccionado, nombre_titular, dni_titular)
        st.download_button(f"📄 Informe Fiscal {año_seleccionado}", data=pdf_fiscal, file_name=f"Informe_{año_seleccionado}.pdf", use_container_width=True)
        st.divider()

    if not st.session_state.adding_mode:
        if st.button("➕ Registrar Nueva Operación", use_container_width=True, type="primary"):
            st.session_state.adding_mode = True
            st.rerun()

    if st.session_state.adding_mode:
        st.markdown("### 📝 Datos del Trade")
        if st.button("❌ Cerrar"):
            st.session_state.adding_mode = False
            st.rerun()
            
        with st.form("trade_form"):
            tipo = st.selectbox("Tipo", ["Compra", "Venta", "Dividendo"])
            ticker = st.text_input("Ticker (ej. TSLA)").upper().strip()
            moneda = st.selectbox("Moneda", ["EUR", "USD"])
            c1, c2 = st.columns(2)
            dinero_total = c1.number_input("Importe Total", min_value=0.0)
            precio_manual = c2.number_input("Precio/Acción (0=Auto)", min_value=0.0, format="%.4f")
            comision = st.number_input("Comisión", min_value=0.0)
            
            tz = st.session_state.cfg_zona
            d_op = st.date_input("Día", datetime.now(ZoneInfo(tz)))
            t_op = st.time_input("Hora", datetime.now(ZoneInfo(tz)))
            dt_op_final = datetime.combine(d_op, t_op)

            if st.form_submit_button("🔍 Validar y Guardar"):
                if ticker and dinero_total > 0:
                    p_final = float(precio_manual)
                    
                    # --- MEJORA V32.41: BUSQUEDA HISTORICA OBLIGATORIA ---
                    if p_final <= 0:
                        with st.spinner(f"Consultando mercado para {ticker}..."):
                            p_final = get_historical_stock_price(ticker, dt_op_final)
                    
                    if p_final > 0:
                        nom, _, _ = get_stock_data_fmp(ticker)
                        if not nom: nom, _, _ = get_stock_data_yahoo(ticker)
                        
                        # Conversión a EUR inmediata
                        fx = 1.0
                        if moneda != "EUR":
                            fx = get_historical_eur_rate(dt_op_final, moneda)
                        
                        datos = {
                            "Tipo": tipo, "Ticker": ticker, "Descripcion": nom if nom else ticker,
                            "Moneda": "EUR", "Cantidad": dinero_total * fx, "Precio": p_final * fx,
                            "Comision": comision * fx, "Cambio": fx, "Fecha": dt_op_final.strftime("%Y/%m/%d %H:%M")
                        }
                        guardar_en_airtable(datos)
                    else:
                        st.error(f"❌ No se encontró precio para {ticker}. Introdúcelo manualmente.")

    st.divider()
    st.header("Configuración")
    st.session_state.cfg_zona = st.selectbox("🌍 Zona Horaria:", ["Atlantic/Canary", "Europe/Madrid", "UTC"], index=1)
    st.session_state.cfg_movil = st.toggle("📱 Vista Móvil / Tarjetas", value=st.session_state.cfg_movil)

# ==========================================
# 4. VISTA DETALLE (DE TU BASE V32.40)
# ==========================================
if st.session_state.ticker_detalle:
    t = st.session_state.ticker_detalle
    info = cartera.get(t, {})
    if st.button("⬅️ Volver"): st.session_state.ticker_detalle = None; st.rerun()
    
    st.divider()
    c1, c2 = st.columns([1, 5])
    c1.image(get_logo_url(t), width=80)
    c2.title(f"{info.get('desc')} ({t})")

    with st.spinner("Cargando mercado..."):
        _, p_now, desc_larga = get_stock_data_fmp(t)
        if not p_now: _, p_now, desc_larga = get_stock_data_yahoo(t)

    # MÉTRICAS ESTILO V32.40
    st.markdown("""<style>.metric-value { font-size: 2.5rem; font-weight: bold; }</style>""", unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Precio Actual", fmt_dinamico(p_now, "€"))
    m2.metric("Tus Acciones", fmt_dinamico(info['acciones']))
    
    val_m = info['acciones'] * p_now if p_now else 0
    rent_l = (val_m - info['coste_total_eur'])/info['coste_total_eur'] if info['coste_total_eur']>0 else 0
    m3.metric("Valor Mercado", fmt_dinamico(val_m, "€"), f"{rent_l*100:.2f}%")
    m4.metric("Bº Realizado", fmt_dinamico(info['pnl_cerrado'], "€"))

    st.divider()
    # GRÁFICO ALTAIR INTERACTIVO
    hist = yf.Ticker(t).history(period="1y").reset_index()
    if not hist.empty:
        base_g = alt.Chart(hist).encode(x='Date:T')
        line_g = base_g.mark_line(color='#29b5e8').encode(y=alt.Y('Close', scale=alt.Scale(zero=False)))
        st.altair_chart(line_g.properties(height=300), use_container_width=True)

    # LOTES FIFO
    if info['lotes']:
        st.subheader("📦 Lotes FIFO")
        df_l = pd.DataFrame([{"Fecha": l['fecha_str'], "Acciones": l['acciones_restantes'], "Precio": l['coste_por_accion_eur']} for l in info['lotes'] if l['acciones_restantes']>0])
        st.dataframe(df_l, use_container_width=True, hide_index=True)

# ==========================================
# 5. DASHBOARD PRINCIPAL (DE TU BASE V32.40)
# ==========================================
else:
    tabla_v = []
    val_total_cartera = 0.0
    for t, i in cartera.items():
        if i['acciones'] > 0.001 or abs(i['pnl_cerrado']) > 0.01:
            _, p_now, _ = get_stock_data_fmp(t)
            if not p_now: _, p_now, _ = get_stock_data_yahoo(t)
            v_act = i['acciones'] * p_now if p_now else 0
            val_total_cartera += v_act
            tabla_v.append({"Logo": get_logo_url(t), "Ticker": t, "Empresa": i['desc'], "Acciones": i['acciones'], "Valor": v_act, "PMC": i['pmc'], "Invertido": i['coste_total_eur'], "Latente": (v_act - i['coste_total_eur'])/i['coste_total_eur'] if i['coste_total_eur']>0 else 0, "Trading": i['pnl_cerrado']})

    c_tit, c_val = st.columns([1, 2])
    c_tit.title("💼 Cartera")
    c_val.markdown(f'<div style="text-align: right;"><span style="color: gray;">Valor Actual</span><br><span style="font-size: 3.5rem; font-weight: bold;">{fmt_dinamico(val_total_cartera, "€")}</span></div>', unsafe_allow_html=True)
    
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    neto_t = pnl_cerrado + total_div - total_comi
    roi_t = (neto_t/compras_eur)*100 if compras_eur>0 else 0
    m1.metric("Bº Neto", fmt_dinamico(neto_t, "€"), f"{roi_t:.2f}%")
    m2.metric("Trading", fmt_dinamico(pnl_cerrado, "€"))
    m3.metric("Dividendos", fmt_dinamico(total_div, "€"))
    m4.metric("Comisiones", f"-{fmt_dinamico(total_comi, '€')}")

    # CURVA DE ROI (GRADIENTES V32.40)
    if roi_log:
        df_roi = pd.DataFrame(roi_log)
        df_roi['Fecha'] = pd.to_datetime(df_roi['Fecha'])
        df_roi.set_index('Fecha', inplace=True)
        df_w = df_roi.resample('W').sum().fillna(0)
        df_w['ROI'] = (df_w['Delta_Profit'].cumsum() / df_w['Delta_Invest'].cumsum() * 100).fillna(0)
        
        area_roi = alt.Chart(df_w.reset_index()).mark_area(opacity=0.5, color='purple').encode(x='Fecha:T', y='ROI:Q')
        st.altair_chart(area_roi.properties(height=200), use_container_width=True)

    # TABLA / TARJETAS
    if tabla_v:
        if st.session_state.cfg_movil:
            for r in tabla_v:
                with st.container(border=True):
                    st.write(f"**{r['Ticker']}** | {fmt_dinamico(r['Valor'], '€')}")
                    if st.button("Ver", key=f"v_{r['Ticker']}"): st.session_state.ticker_detalle = r['Ticker']; st.rerun()
        else:
            df_final = pd.DataFrame(tabla_v)
            st.dataframe(df_final, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("📜 Historial Completo")
    st.dataframe(df[['Fecha_str', 'Ticker', 'Tipo', 'Cantidad', 'Precio', 'Moneda']], use_container_width=True, hide_index=True)
