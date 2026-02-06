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
import time

# --- INTENTO DE IMPORTAR TRADUCTOR ---
try:
    from deep_translator import GoogleTranslator
    HAS_TRANSLATOR = True
except ImportError:
    HAS_TRANSLATOR = False

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Gestor V32.26c (UI Update)", layout="wide") 
MONEDA_BASE = "EUR" 

# --- ESTADO ---
if "pending_data" not in st.session_state: st.session_state.pending_data = None
if "adding_mode" not in st.session_state: st.session_state.adding_mode = False
if "reset_seed" not in st.session_state: st.session_state.reset_seed = 0
if "ticker_detalle" not in st.session_state: st.session_state.ticker_detalle = None
if "current_user" not in st.session_state: st.session_state.current_user = None
if "user_role" not in st.session_state: st.session_state.user_role = "user"

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

# --- FORMATEADOR EUROPEO (3 DECIMALES) ---
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
        record["Usuario"] = st.session_state.current_user
        table_ops.create(record)
        st.success(f"✅ Operación Guardada: {record['Ticker']}")
        st.session_state.pending_data = None
        st.session_state.adding_mode = False 
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

def generar_informe_fiscal_completo(datos_fiscales, año):
    class PDF_Fiscal(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 14)
            self.cell(0, 10, f"Informe Fiscal - Ejercicio {año}", 0, 1, 'C')
            self.set_font('Arial', 'I', 10)
            self.cell(0, 5, f"Generado el {datetime.now().strftime('%d/%m/%Y')}", 0, 1, 'C')
            self.ln(10)
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

    pdf.set_font("Arial", 'B', 9)
    cols = [("Ticker", 18), ("ISIN", 32), ("F. Venta", 23), ("F. Compra", 23), ("Cant.", 18), ("V. Transm.", 30), ("V. Adquis.", 30), ("Rendimiento", 30)]
    for txt, w in cols: pdf.cell(w, 8, txt, 1, 0, 'C')
    pdf.ln()
    
    pdf.set_font("Arial", '', 9)
    total_ganancias = 0.0
    ops_acciones = [d for d in datos_fiscales if d['Tipo'] == "Ganancia/Pérdida"]
    
    for op in ops_acciones:
        rend = op['Rendimiento']
        total_ganancias += rend
        pdf.cell(18, 8, str(op['Ticker']), 1, 0, 'C')
        pdf.cell(32, 8, str(op.get('ISIN', '')), 1, 0, 'C') 
        pdf.cell(23, 8, str(op['Fecha Venta']), 1, 0, 'C')
        pdf.cell(23, 8, str(op['Fecha Compra']), 1, 0, 'C')
        pdf.cell(18, 8, fmt_dinamico(op['Cantidad']), 1, 0, 'C')
        pdf.cell(30, 8, f"{fmt_num_es(op['V. Transmisión'])}", 1, 0, 'R')
        pdf.cell(30, 8, f"{fmt_num_es(op['V. Adquisición'])}", 1, 0, 'R')
        pdf.set_text_color(0, 150, 0) if rend >= 0 else pdf.set_text_color(200, 0, 0)
        pdf.cell(30, 8, f"{fmt_num_es(rend)}", 1, 0, 'R')
        pdf.set_text_color(0, 0, 0)
        pdf.ln()

    # Total 1
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(165, 10, "TOTAL GANANCIA/PÉRDIDA PATRIMONIAL:", 0, 0, 'R')
    pdf.set_text_color(0, 150, 0) if total_ganancias >= 0 else pdf.set_text_color(200, 0, 0)
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
    pdf.cell(150, 10, "TOTAL RENDIMIENTOS (NETO):", 0, 0, 'R')
    pdf.cell(40, 10, f"{fmt_num_es(total_divs_neto)} EUR", 0, 1, 'R')
    
    return pdf.output(dest='S').encode('latin-1')

# --- APP INICIO ---
if not login_system(): st.stop()

c_user, c_logout = st.columns([6, 1])
c_user.write(f"👤 **{st.session_state.current_user}** ({st.session_state.user_role.upper()})")
if c_logout.button("Salir"):
    st.session_state.current_user = None
    st.session_state.password_correct = False
    st.rerun()

ver_todo = False
if st.session_state.user_role == 'admin':
    ver_todo = st.toggle("👁️ Modo Admin", value=False)

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

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("Configuración")
    mi_zona = st.selectbox("🌍 Zona Horaria:", ["Atlantic/Canary", "Europe/Madrid", "UTC"], index=1)
    st.divider()
    st.header("Filtros")
    lista_años = ["Todos los años"]
    if not df.empty and 'Año' in df.columns:
        años_disponibles = sorted(df['Año'].dropna().unique().astype(int), reverse=True)
        lista_años += list(años_disponibles)
    año_seleccionado = st.selectbox("📅 Año Fiscal:", lista_años)
    ver_solo_activas = st.checkbox("👁️ Ocultar posiciones cerradas", value=False)
    st.divider()

    if not st.session_state.adding_mode and st.session_state.pending_data is None:
        if st.button("➕ Registrar Nueva Operación", use_container_width=True, type="primary"):
            st.session_state.adding_mode = True
            st.session_state.reset_seed = int(datetime.now().timestamp())
            st.rerun()

    if st.session_state.adding_mode or st.session_state.pending_data is not None:
        st.markdown("### 📝 Datos de la Operación")
        if st.button("❌ Cerrar", use_container_width=True):
            st.session_state.adding_mode = False
            st.session_state.pending_data = None
            st.rerun()

        if st.session_state.pending_data is None:
            with st.form("trade_form"):
                st.info("💡 Consejo: Para vender todo, usa el 'Valor Actual' de la tabla.")
                tipo = st.selectbox("Tipo", ["Compra", "Venta", "Dividendo"])
                ticker = st.text_input("Ticker (ej. TSLA)").upper().strip()
                desc_manual = st.text_input("Descripción (Opcional)")
                moneda = st.selectbox("Moneda", ["EUR", "USD"])
                c1, c2 = st.columns(2)
                dinero_total = c1.number_input("Importe Total (Dinero)", min_value=0.00, step=10.0)
                precio_manual = c2.number_input("Precio/Acción", min_value=0.0, format="%.2f")
                comision = st.number_input("Comisión", min_value=0.0, format="%.2f")
                st.markdown("---")
                dt_final = datetime.combine(st.date_input("Día", datetime.now(ZoneInfo(mi_zona))), st.time_input("Hora", datetime.now(ZoneInfo(mi_zona))))
                if st.form_submit_button("🔍 Validar y Guardar"):
                    if ticker and dinero_total > 0:
                        nom, pre, _ = get_stock_data_fmp(ticker)
                        if not nom: nom, pre, _ = get_stock_data_yahoo(ticker)
                        nombre_final = desc_manual if desc_manual else (nom if nom else ticker)
                        precio_final = precio_manual if precio_manual > 0 else (pre if pre else 0.0)
                        datos = {"Tipo": tipo, "Ticker": ticker, "Descripcion": nombre_final, "Moneda": moneda, "Cantidad": float(dinero_total), "Precio": float(precio_final), "Comision": float(comision), "Fecha": dt_final.strftime("%Y/%m/%d %H:%M")}
                        if precio_final > 0: guardar_en_airtable(datos)
                        else: st.session_state.pending_data = datos; st.rerun()
        else:
            st.warning(f"⚠️ **ALERTA:** No encuentro precio para **'{st.session_state.pending_data['Ticker']}'**.")
            c_si, c_no = st.columns(2)
            if c_si.button("✅ Guardar"): guardar_en_airtable(st.session_state.pending_data)
            if c_no.button("❌ Revisar"): st.session_state.pending_data = None; st.rerun()

# 3. MOTOR DE CÁLCULO (LÓGICA FIFO + ISIN DUAL + REDONDEO SEGURO)
cartera = {}
total_div, total_comi, pnl_cerrado, compras_eur, ventas_coste = 0.0, 0.0, 0.0, 0.0, 0.0
roi_log = []
reporte_fiscal_log = []

if not df.empty:
    colas_fifo = {}
    isin_cache_local = {}

    for i, row in df.sort_values(by="Fecha_dt").iterrows():
        tipo, tick = row.get('Tipo'), str(row.get('Ticker')).strip()
        dinero, precio = float(row.get('Cantidad', 0)), float(row.get('Precio', 1))
        mon, comi = row.get('Moneda', 'EUR'), float(row.get('Comision', 0))
        
        fx = get_exchange_rate_now(mon, MONEDA_BASE)
        dinero_eur = dinero * fx
        if precio <= 0: precio = 1
        
        acciones_op = round(dinero / precio, 8) 
        
        en_rango_visual = (año_seleccionado == "Todos los años") or (row.get('Año') == int(año_seleccionado))
        es_año_fiscal = (row.get('Año') == int(año_seleccionado)) if año_seleccionado != "Todos los años" else True

        delta_p, delta_i = 0.0, 0.0
        
        if en_rango_visual: total_comi += (comi * fx)
        delta_p -= (comi * fx)

        if tick not in cartera:
            colas_fifo[tick] = [] 
            cartera[tick] = {'acciones': 0.0, 'coste_total_eur': 0.0, 'desc': row.get('Descripcion', tick), 'pnl_cerrado': 0.0, 'pmc': 0.0, 'moneda_origen': mon, 'movimientos': [], 'lotes': colas_fifo[tick]}
        
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
            valor_transmision_neto_total = dinero_eur * fx - (comi * fx) 
            precio_venta_neto_unitario = valor_transmision_neto_total / acciones_op if acciones_op > 0 else 0

            # --- CAPTURA ISIN (DUAL) ---
            isin_actual = ""
            if es_año_fiscal:
                if tick not in isin_cache_local:
                    isin_cache_local[tick] = get_ticker_isin(tick)
                isin_actual = isin_cache_local[tick]

            while acciones_a_vender > 0.00000001 and colas_fifo[tick]:
                lote = colas_fifo[tick][0]
                cantidad_consumida = 0
                if lote['acciones_restantes'] <= acciones_a_vender:
                    cantidad_consumida = lote['acciones_restantes']
                    coste_total_venta_fifo += cantidad_consumida * lote['coste_por_accion_eur']
                    acciones_a_vender -= cantidad_consumida
                    colas_fifo[tick].pop(0)
                else:
                    cantidad_consumida = acciones_a_vender
                    coste_total_venta_fifo += cantidad_consumida * lote['coste_por_accion_eur']
                    lote['acciones_restantes'] -= cantidad_consumida
                    acciones_a_vender = 0
                
                if es_año_fiscal:
                    v_adquisicion = cantidad_consumida * lote['coste_por_accion_eur']
                    v_transmision = cantidad_consumida * precio_venta_neto_unitario
                    rendimiento = v_transmision - v_adquisicion
                    reporte_fiscal_log.append({"Tipo": "Ganancia/Pérdida", "Ticker": tick, "ISIN": isin_actual, "Fecha Venta": row.get('Fecha_str', '').split(' ')[0], "Fecha Compra": lote['fecha_str'], "Cantidad": cantidad_consumida, "V. Transmisión": v_transmision, "V. Adquisición": v_adquisicion, "Rendimiento": rendimiento})

            beneficio = (dinero_eur - (comi * fx)) - coste_total_venta_fifo
            delta_p += beneficio
            
            if en_rango_visual: 
                ventas_coste += coste_total_venta_fifo
                pnl_cerrado += beneficio
                cartera[tick]['pnl_cerrado'] += beneficio
            
            cartera[tick]['acciones'] -= acciones_op
            cartera[tick]['coste_total_eur'] -= coste_total_venta_fifo
            
            if cartera[tick]['acciones'] < 0.000001: 
                cartera[tick]['acciones'] = 0.0
                cartera[tick]['coste_total_eur'] = 0.0
                cartera[tick]['pmc'] = 0.0
            else:
                cartera[tick]['pmc'] = cartera[tick]['coste_total_eur'] / cartera[tick]['acciones']

        elif tipo == "Dividendo":
            delta_p += dinero_eur
            div_neto = (dinero_eur) - (comi * fx)
            if en_rango_visual: total_div += dinero_eur
            
            if es_año_fiscal:
                reporte_fiscal_log.append({
                    "Tipo": "Dividendo",
                    "Ticker": tick,
                    "Fecha": row.get('Fecha_str', '').split(' ')[0],
                    "Bruto": dinero_eur,
                    "Gastos": comi * fx,
                    "Neto": div_neto
                })
        
        roi_log.append({'Fecha': row.get('Fecha_dt'), 'Year': row.get('Año'), 'Delta_Profit': delta_p, 'Delta_Invest': delta_i})

# ==========================================
#        VISTA DETALLE
# ==========================================
if st.session_state.ticker_detalle:
    t = st.session_state.ticker_detalle
    info = cartera.get(t, {})
    if st.button("⬅️ Volver", type="secondary"): st.session_state.ticker_detalle = None; st.rerun()
    st.divider()
    c1, c2 = st.columns([1, 5])
    with c1: st.image(get_logo_url(t), width=80)
    with c2: st.title(f"{info.get('desc', t)} ({t})"); st.caption("Ficha detallada")

    # --- CAMBIOS VISUALES V32.26c: ORDEN Y ESTILO ---
    
    # 1. METRICAS GIGANTES ARRIBA (HTML PERSONALIZADO PARA TAMAÑO DE FUENTE)
    acc = info.get('acciones', 0)
    with st.spinner("Cargando..."):
        nom, now, desc = get_stock_data_fmp(t)
        if not now: nom, now, desc = get_stock_data_yahoo(t)
    
    valor_mercado_eur, rent = 0.0, 0.0
    fx_actual = 1.0
    if now and acc > 0:
        fx_actual = get_exchange_rate_now(info.get('moneda_origen', 'USD')) if info.get('moneda_origen') != 'EUR' else 1.0
        valor_mercado_eur = acc * now * fx_actual
        if info.get('coste_total_eur') > 0: rent = (valor_mercado_eur - info.get('coste_total_eur', 0)) / info.get('coste_total_eur')

    # CSS para las métricas grandes
    st.markdown("""
    <style>
    .big-metric { text-align: center; border: 1px solid #e6e6e6; padding: 10px; border-radius: 5px; margin-bottom: 10px; }
    .big-label { font-size: 1.1rem; color: gray; font-weight: 500; margin-bottom: -5px; }
    .big-value { font-size: 1.8rem; font-weight: 700; margin: 0; }
    .big-delta { font-size: 1rem; margin-top: -5px; }
    </style>
    """, unsafe_allow_html=True)

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f'<div class="big-metric"><p class="big-label">Precio</p><p class="big-value">{now:,.2f} {info.get("moneda_origen","")}</p></div>', unsafe_allow_html=True)
    with m2:
        st.markdown(f'<div class="big-metric"><p class="big-label">Acciones</p><p class="big-value">{fmt_dinamico(acc)}</p></div>', unsafe_allow_html=True)
    with m3:
        color = "green" if rent >= 0 else "red"
        st.markdown(f'<div class="big-metric"><p class="big-label">Valor Actual</p><p class="big-value">{fmt_dinamico(valor_mercado_eur, "€")}</p><p class="big-delta" style="color:{color}">{rent*100:+.2f}%</p></div>', unsafe_allow_html=True)
    with m4:
        trad = info.get('pnl_cerrado', 0)
        color = "green" if trad >= 0 else "red"
        st.markdown(f'<div class="big-metric"><p class="big-label">Trading (Cerrado)</p><p class="big-value" style="color:{color}">{fmt_dinamico(trad, "€")}</p></div>', unsafe_allow_html=True)

    st.divider()

    # 2. BARRA DE CONTROL UNIFICADA
    # Columnas: Periodo | Tipo de Gráfico | Indicadores (Checkboxes)
    c_tools = st.columns([2, 1, 3])
    
    with c_tools[0]:
        # AÑADIDA OPCION "1 Sem"
        label_t = st.select_slider("Periodo", options=["1 Sem", "1 Mes", "6 Meses", "1 Año", "5 Años", "Todo"], value="1 Año", label_visibility="collapsed")
        periodo_map = {"1 Sem": "5d", "1 Mes": "1mo", "6 Meses": "6mo", "1 Año": "1y", "5 Años": "5y", "Todo": "max"}
        width_map = {"1 Sem": 20, "1 Mes": 10, "6 Meses": 4, "1 Año": 2, "5 Años": 1, "Todo": 1}

    with c_tools[1]:
        # AÑADIDA OPCION "Barras"
        type_g = st.radio("Estilo", ["Línea", "Velas", "Barras (OHLC)"], horizontal=True, label_visibility="collapsed")

    with c_tools[2]:
        # CHECKBOXES EN FILA
        cols_chk = st.columns(4)
        i_vol = cols_chk[0].checkbox("Vol", value=False)
        i_sma = cols_chk[1].checkbox("SMA", value=False)
        i_sup = cols_chk[2].checkbox("Sop", value=False)
        i_ten = cols_chk[3].checkbox("Tend", value=False)
    
    inds = []
    if i_vol: inds.append("Volumen")
    if i_sma: inds.append("SMA")
    if i_sup: inds.append("Soportes")
    if i_ten: inds.append("Tendencia")
    
    sma_p = 50
    if i_sma: sma_p = c_tools[2].selectbox("Periodo SMA", [5, 10, 20, 50, 100, 200], index=3, label_visibility="collapsed")

    # --- LOGICA GRAFICO ---
    hist = pd.DataFrame()
    try:
        hist = yf.Ticker(t).history(period=periodo_map[label_t]).reset_index()
        hist['Date'] = pd.to_datetime(hist['Date']).dt.date
        hist['Volume'] = pd.to_numeric(hist['Volume'], errors='coerce').fillna(0)
    except: pass

    if not hist.empty:
        if i_sma: hist['SMA'] = hist['Close'].rolling(window=sma_p).mean()
        if i_ten:
            hist['Ord'] = pd.to_datetime(hist['Date']).map(datetime.toordinal)
            x, y = hist['Ord'].values, hist['Close'].values
            if len(x)>1: m, b = np.polyfit(x,y,1); hist['Trend'] = m*x+b
        
        # Stats lines
        stat_max = hist['Close'].max(); stat_min = hist['Close'].min(); stat_avg = hist['Close'].mean()
        last_date = hist['Date'].max()
        df_price_stats = pd.DataFrame([{'Val': stat_max, 'Label': f"Max: {stat_max:.2f}", 'Color': 'green'}, {'Val': stat_min, 'Label': f"Min: {stat_min:.2f}", 'Color': 'red'}, {'Val': stat_avg, 'Label': f"Med: {stat_avg:.2f}", 'Color': 'blue'}])
        df_price_stats['Date'] = last_date

        hover = alt.selection_point(fields=['Date'], nearest=True, on='mouseover', empty=False, clear='mouseout')
        base = alt.Chart(hist).encode(x=alt.X('Date:T', title='Fecha'))
        
        # SELECCION DE ESTILO
        if type_g == "Línea":
            main = base.mark_line(color='#29b5e8').encode(y=alt.Y('Close', scale=alt.Scale(zero=False)))
        elif type_g == "Velas":
            rule = base.mark_rule().encode(y=alt.Y('Low', scale=alt.Scale(zero=False)), y2='High', color=alt.condition("datum.Open<datum.Close", alt.value("#00C805"), alt.value("#FF0000")))
            bar = base.mark_bar(width=width_map[label_t]).encode(y='Open', y2='Close', color=alt.condition("datum.Open<datum.Close", alt.value("#00C805"), alt.value("#FF0000")))
            main = rule + bar
        else: # Barras (OHLC Estilo Simplificado)
            # Regla vertical (Low-High)
            rule = base.mark_rule(color='black').encode(y=alt.Y('Low', scale=alt.Scale(zero=False)), y2='High')
            # Tick Apertura (izquierda) - Simulado con regla corta offset
            # Altair básico no soporta ticks offset facil, usamos tick mark simple para Open y Close
            tick_open = base.mark_tick(thickness=2, size=10, color='black', orient='left').encode(y='Open')
            tick_close = base.mark_tick(thickness=2, size=10, color='black', orient='right').encode(y='Close')
            main = rule + tick_open + tick_close

        tooltips = [alt.Tooltip('Date', title='Fecha'), alt.Tooltip('Close', title='Precio', format=',.2f'), alt.Tooltip('Volume', title='Vol', format=',')]
        points = base.mark_point().encode(y='Close', opacity=alt.value(0), tooltip=tooltips).add_params(hover)
        rule_hover = base.mark_rule(color='gray', strokeDash=[4,4]).encode(opacity=alt.condition(hover, alt.value(1), alt.value(0))).transform_filter(hover)
        
        # Manual stats layers
        stats_layers = []
        for _, r in df_price_stats.iterrows():
            stats_layers.append(alt.Chart(pd.DataFrame({'y':[r['Val']]})).mark_rule(color=r['Color'], strokeDash=[4,4]).encode(y='y'))
            stats_layers.append(alt.Chart(pd.DataFrame({'x':[r['Date']], 'y':[r['Val']], 't':[r['Label']]})).mark_text(color=r['Color'], align='left', dx=5).encode(x='x', y='y', text='t'))

        layers = [main, points, rule_hover] + stats_layers
        
        # Movimientos
        movs_raw = info.get('movimientos', [])
        if movs_raw:
            df_m_chart = pd.DataFrame(movs_raw)
            df_m_chart['Date'] = pd.to_datetime(df_m_chart['Fecha_Raw']).dt.date
            df_m_chart = df_m_chart[df_m_chart['Date'] >= hist['Date'].min()]
            if not df_m_chart.empty:
                compras = df_m_chart[df_m_chart['Tipo'] == 'Compra']
                if not compras.empty: layers.append(alt.Chart(compras).mark_point(shape='circle', size=100, color='blue', filled=True).encode(x='Date:T', y='Precio', tooltip=['Date', 'Precio', 'Cantidad']))
                ventas = df_m_chart[df_m_chart['Tipo'] == 'Venta']
                if not ventas.empty: layers.append(alt.Chart(ventas).mark_point(shape='triangle', size=100, color='red', filled=True).encode(x='Date:T', y='Precio', tooltip=['Date', 'Precio', 'Cantidad']))

        if i_sma: layers.append(base.mark_line(color='orange', strokeDash=[2,2]).encode(y='SMA'))
        if i_ten and 'Trend' in hist: layers.append(base.mark_line(color='purple').encode(y='Trend'))

        chart_final = alt.layer(*layers).properties(height=400, width='container')
        
        if i_vol:
            vol_chart = base.mark_bar(width=width_map[label_t]).encode(y=alt.Y('Volume', axis=alt.Axis(format='~s')), color=alt.condition("datum.Open<datum.Close", alt.value("#00C805"), alt.value("#FF0000"))).properties(height=100).add_params(hover)
            chart_final = alt.vconcat(chart_final, vol_chart).resolve_scale(x='shared')

        st.altair_chart(chart_final, use_container_width=True)

    # 3. TABLA FIFO DEBAJO DEL GRAFICO
    lotes = info.get('lotes', [])
    if lotes and now:
        st.subheader("📦 Desglose de Lotes Activos (FIFO)")
        data_lotes = []
        for l in lotes:
            cant = l['acciones_restantes']
            coste_paquete = cant * l['coste_por_accion_eur']
            valor_paquete = cant * now * fx_actual
            plusvalia = valor_paquete - coste_paquete
            rent_lote = (plusvalia / coste_paquete) * 100 if coste_paquete > 0 else 0
            data_lotes.append({"Fecha Compra": l['fecha_str'], "Acciones": cant, "Precio Orig. (EUR)": l['coste_por_accion_eur'], "Coste Lote": coste_paquete, "Valor Hoy": valor_paquete, "Plusvalía": plusvalia, "% Rent.": rent_lote})
        
        df_lotes = pd.DataFrame(data_lotes)
        if not df_lotes.empty:
            def estilo_lotes(row):
                color = '#d4edda' if row['Plusvalía'] >= 0 else '#f8d7da' 
                return [f'background-color: {color}; color: black']*len(row)
            st.dataframe(df_lotes.style.format({"Acciones": lambda x: fmt_dinamico(x), "Precio Orig. (EUR)": lambda x: fmt_num_es(x) + " €", "Coste Lote": lambda x: fmt_num_es(x) + " €", "Valor Hoy": lambda x: fmt_num_es(x) + " €", "Plusvalía": lambda x: fmt_num_es(x) + " €", "% Rent.": lambda x: fmt_num_es(x) + "%"}).apply(estilo_lotes, axis=1), use_container_width=True, hide_index=True)

    # 4. DESCRIPCION E HISTORIAL AL FINAL
    with st.expander("📖 Descripción"): st.write(desc if desc else "N/A")
    st.subheader("📝 Movimientos Históricos")
    if info['movimientos']:
        df_m = pd.DataFrame(info['movimientos'])[['Fecha_str','Tipo','Cantidad','Precio','Moneda','Comision']]
        st.dataframe(df_m, use_container_width=True, hide_index=True)

# ==========================================
#        DASHBOARD (PORTADA)
# ==========================================
else:
    # --- CÁLCULO PREVIO DE DATOS ---
    tabla = []
    valor_total_cartera = 0.0
    
    with st.spinner("Conectando con el mercado..."):
        for t, i in cartera.items():
            alive = i['acciones'] > 0.001
            act = abs(i['pnl_cerrado']) > 0.01
            if (ver_solo_activas and alive) or (not ver_solo_activas and (alive or act)):
                p_now = 0
                if i['acciones'] > 0.001:
                    _, p_now, _ = get_stock_data_fmp(t)
                    if not p_now: _, p_now, _ = get_stock_data_yahoo(t)
                val = i['acciones'] * p_now if p_now else 0
                
                valor_total_cartera += val
                
                r_lat = (val - i['coste_total_eur'])/i['coste_total_eur'] if i['coste_total_eur']>0 else 0
                tabla.append({"Logo": get_logo_url(t), "Empresa": i['desc'], "Ticker": t, "Acciones": i['acciones'], "Valor": val, "PMC": i['pmc'], "Invertido": i['coste_total_eur'], "Trading": i['pnl_cerrado'], "Latente": r_lat})

    neto = pnl_cerrado + total_div - total_comi
    roi = (neto/compras_eur)*100 if compras_eur>0 else 0

    # --- DISEÑO HEADER PRO V32.26c ---
    c_hdr_1, c_hdr_2 = st.columns([3, 1])
    with c_hdr_1:
        st.title("💼 Cartera") 
    with c_hdr_2:
        st.markdown(f"""
            <div style="text-align: right;">
                <span style="font-size: 1.1rem; color: gray;">Valor Cartera</span><br>
                <span style="font-size: 2.2rem; font-weight: bold;">{fmt_dinamico(valor_total_cartera, '€')}</span>
            </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")

    # --- MÉTRICAS SECUNDARIAS ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Bº Neto", fmt_dinamico(neto, '€'), f"{fmt_num_es(roi)}%")
    m2.metric("Trading", fmt_dinamico(pnl_cerrado, '€'))
    m3.metric("Dividendos", fmt_dinamico(total_div, '€'))
    m4.metric("Comisiones", f"-{fmt_dinamico(total_comi, '€')}")

    # --- GRÁFICO ROI (FIX MANUAL LAYERS) ---
    if roi_log:
        with st.expander("📈 Ver Evolución ROI", expanded=False):
            df_r = pd.DataFrame(roi_log)
            df_r['Fecha'] = pd.to_datetime(df_r['Fecha'])
            if año_seleccionado != "Todos los años": df_r = df_r[df_r['Year'] == int(año_seleccionado)]
            if not df_r.empty:
                df_r.set_index('Fecha', inplace=True)
                df_w = df_r.resample('W').sum().fillna(0)
                df_w['Cum_P'] = df_w['Delta_Profit'].cumsum()
                df_w['Cum_I'] = df_w['Delta_Invest'].cumsum()
                df_w['ROI'] = df_w.apply(lambda x: (x['Cum_P']/x['Cum_I']*100) if x['Cum_I']>0 else 0, axis=1)
                df_w = df_w.reset_index()
                
                ymin, ymax = df_w['ROI'].min(), df_w['ROI'].max()
                stops = [alt.GradientStop(color='#00C805', offset=0), alt.GradientStop(color='#00C805', offset=1)]
                if ymax <= 0: stops = [alt.GradientStop(color='#FF0000', offset=0), alt.GradientStop(color='#FF0000', offset=1)]
                elif ymin < 0 < ymax:
                    off = abs(ymax)/(ymax-ymin)
                    stops = [alt.GradientStop(color='#00C805', offset=0), alt.GradientStop(color='#00C805', offset=off), alt.GradientStop(color='#FF0000', offset=off), alt.GradientStop(color='#FF0000', offset=1)]

                base = alt.Chart(df_w).encode(x='Fecha:T')
                area = base.mark_area(opacity=0.6, line={'color':'purple'}, color=alt.Gradient(gradient='linear', stops=stops, x1=1, x2=1, y1=0, y2=1)).encode(y='ROI')
                rule_zero = alt.Chart(pd.DataFrame({'y':[0]})).mark_rule(color='black', strokeDash=[2,2]).encode(y='y')
                
                # Manual stats layers
                s_max, s_min, s_avg = df_w['ROI'].max(), df_w['ROI'].min(), df_w['ROI'].mean()
                last_d = df_w['Fecha'].max()
                
                rule_max = alt.Chart(pd.DataFrame({'y': [s_max]})).mark_rule(color='green', strokeDash=[4,4]).encode(y='y')
                lbl_max = alt.Chart(pd.DataFrame({'x': [last_d], 'y': [s_max], 't': [f"Max: {s_max:.1f}%"]})).mark_text(align='left', dx=5, color='green').encode(x='x', y='y', text='t')

                rule_min = alt.Chart(pd.DataFrame({'y': [s_min]})).mark_rule(color='red', strokeDash=[4,4]).encode(y='y')
                lbl_min = alt.Chart(pd.DataFrame({'x': [last_d], 'y': [s_min], 't': [f"Min: {s_min:.1f}%"]})).mark_text(align='left', dx=5, color='red').encode(x='x', y='y', text='t')

                rule_avg = alt.Chart(pd.DataFrame({'y': [s_avg]})).mark_rule(color='blue', strokeDash=[4,4]).encode(y='y')
                lbl_avg = alt.Chart(pd.DataFrame({'x': [last_d], 'y': [s_avg], 't': [f"Med: {s_avg:.1f}%"]})).mark_text(align='left', dx=5, color='blue').encode(x='x', y='y', text='t')
                
                hover = alt.selection_point(fields=['Fecha'], nearest=True, on='mouseover', empty=False)
                pts = base.mark_point(opacity=0).add_params(hover)
                crs = base.mark_rule(strokeDash=[4,4]).encode(opacity=alt.condition(hover, alt.value(1), alt.value(0)), tooltip=['Fecha', 'ROI'])
                st.altair_chart((area + rule_zero + rule_max + lbl_max + rule_min + lbl_min + rule_avg + lbl_avg + pts + crs), use_container_width=True)

    st.divider()
    
    # === SELECCIÓN DE VISTA ===
    vista_movil = st.sidebar.toggle("📱 Vista Móvil / Tarjetas", value=False)
    
    # === DESCARGA INFORME FISCAL ===
    if año_seleccionado != "Todos los años" and reporte_fiscal_log:
        st.sidebar.divider()
        st.sidebar.markdown(f"**⚖️ Impuestos {año_seleccionado}**")
        try:
            pdf_fiscal = generar_informe_fiscal_completo(reporte_fiscal_log, año_seleccionado)
            st.sidebar.download_button(
                f"📄 Informe Renta {año_seleccionado}", 
                pdf_fiscal, 
                f"Informe_Fiscal_{año_seleccionado}.pdf", 
                "application/pdf",
                use_container_width=True
            )
        except Exception as e:
            st.sidebar.error(f"Error generando PDF: {e}")
    elif año_seleccionado == "Todos los años":
        st.sidebar.divider()
        st.sidebar.caption("⚠️ Selecciona un año concreto arriba para descargar el Informe Fiscal.")

    if tabla:
        st.subheader("📊 Mi Portfolio")
        
        if vista_movil:
            st.info("💡 Vista optimizada para pantallas pequeñas.")
            for row in tabla:
                with st.container(border=True):
                    c_top_1, c_top_2 = st.columns([1, 4])
                    with c_top_1: st.image(row["Logo"], width=50)
                    with c_top_2: 
                        st.write(f"**{row['Ticker']}**")
                        st.caption(row["Empresa"][:30] + "..." if len(row["Empresa"])>30 else row["Empresa"])
                    st.divider()
                    gm1, gm2 = st.columns(2)
                    gm3, gm4 = st.columns(2)
                    gm1.metric("Valor Actual", fmt_dinamico(row['Valor'], '€'))
                    gm2.metric("Rent. Latente", fmt_dinamico(row['Latente']*100, '%'), delta=f"{fmt_num_es(row['Latente']*100)}%")
                    gm3.metric("Invertido", fmt_dinamico(row['Invertido'], '€'))
                    gm4.metric("Trading", fmt_dinamico(row['Trading'], '€'), delta_color="normal" if row['Trading']>=0 else "inverse")
                    if st.button(f"🔍 Ver Detalle {row['Ticker']}", key=f"mob_btn_{row['Ticker']}", use_container_width=True):
                        st.session_state.ticker_detalle = row['Ticker']
                        st.rerun()

        else:
            st.markdown("---")
            c = st.columns([0.6, 0.8, 1.5, 0.8, 1, 1, 1, 1, 0.8, 0.5])
            titles = ["Logo", "Ticker", "Empresa", "Acciones", "PMC", "Invertido", "Valor", "% Latente", "Trading", "Ver"]
            for i, title in enumerate(titles): 
                c[i].markdown(f"**{title}**")
            st.markdown("---")
            for row in tabla:
                c = st.columns([0.6, 0.8, 1.5, 0.8, 1, 1, 1, 1, 0.8, 0.5])
                with c[0]: st.image(row["Logo"], width=30)
                with c[1]: st.write(f"**{row['Ticker']}**")
                with c[2]: st.caption(row["Empresa"])
                with c[3]: st.write(fmt_dinamico(row['Acciones']))
                with c[4]: st.write(fmt_dinamico(row['PMC'], '€'))
                with c[5]: st.write(fmt_dinamico(row['Invertido'], '€'))
                with c[6]: st.write(f"**{fmt_dinamico(row['Valor'], '€')}**") 
                color_lat = "green" if row['Latente'] >= 0 else "red"
                with c[7]: st.markdown(f":{color_lat}[{fmt_num_es(row['Latente']*100)}%]")
                color_trad = "green" if row['Trading'] >= 0 else "red"
                with c[8]: st.markdown(f":{color_trad}[{fmt_dinamico(row['Trading'], '€')}]")
                with c[9]:
                    if st.button("🔍", key=f"btn_{row['Ticker']}"): 
                        st.session_state.ticker_detalle = row['Ticker']
                        st.rerun()
                st.divider()
    
    st.divider()
    st.subheader("📜 Historial")
    if not df.empty:
        c1, c2, c3 = st.columns([1, 1, 6])
        with c1: st.download_button("Descargar CSV", df.to_csv(index=False).encode('utf-8'), "historial.csv")
        try: 
            with c2: st.download_button("Descargar PDF", generar_pdf_historial(df, f"Historial {año_seleccionado}"), f"historial.pdf")
        except: pass
        
        cols_display = ['Fecha_str', 'Ticker', 'Tipo', 'Cantidad', 'Precio', 'Moneda']
        if not df.empty:
            st.dataframe(df[cols_display], use_container_width=True, hide_index=True)
