import streamlit as st
import PyPDF2
import pandas as pd
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import re
import urllib.request
import json
import time

# --- CONFIGURAÇÕES DA PÁGINA (SaaS Logístico - Wide) ---
st.set_page_config(page_title="DRS Group | BMS Operations", layout="wide", page_icon="🏢")

# --- INJEÇÃO DE CSS (Design WMS / Logística Ajustado) ---
st.markdown("""
    <style>
    .stApp { background-color: #f4f7f9; }
    
    h1, h2, h3, h4, h5, h6 {
        color: #1b3834 !important;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        font-weight: 600;
        margin-bottom: 0.3rem;
    }
    h2 { font-size: 18px !important; }
    h3 { font-size: 14px !important; }
    h4 { font-size: 12px !important; }
    
    .stButton>button {
        background-color: #209b7c !important;
        color: white !important;
        border-radius: 4px;
        border: none;
        font-size: 12px !important;
        font-weight: bold;
        padding: 0.3rem 0.8rem;
        transition: 0.2s ease-in-out;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .stButton>button:hover {
        background-color: #1b3834 !important;
        color: #e59235 !important;
    }
    
    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"] {
        background-color: #ffffff;
        padding: 10px;
        border-radius: 6px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        border: 1px solid #e0e6ed;
    }
    
    [data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #d2dedb;
        padding-top: 1rem;
    }
    
    .dataframe {
        font-size: 12px !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- SISTEMA DE AUTENTICAÇÃO ---
def verificar_senha():
    def senha_inserida():
        if st.session_state["password_input"] == st.secrets.get("SENHA_ACESSO", "bms2026"):
            st.session_state["password_correta"] = True
            del st.session_state["password_input"]
        else:
            st.session_state["password_correta"] = False

    if "password_correta" not in st.session_state:
        st.markdown("<h2 style='color: #1b3834; text-align: center; margin-top: 10vh;'>🔒 DRS Group - Acesso Restrito</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.info("Insira suas credenciais para acessar o painel de operações BMS.")
            st.text_input("Senha de Acesso", type="password", on_change=senha_inserida, key="password_input")
        return False
    elif not st.session_state["password_correta"]:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.text_input("Senha de Acesso", type="password", on_change=senha_inserida, key="password_input")
            st.error("❌ Credencial inválida. Acesso negado.")
        return False
    else:
        return True

if not verificar_senha():
    st.stop()

# --- CONTROLE DE SESSÃO PARA BLOQUEIO IMEDIATO ---
if "seriais_consumidos" not in st.session_state:
    st.session_state.seriais_consumidos = set()
if "ids_consumidos" not in st.session_state:
    st.session_state.ids_consumidos = set()

# --- CARREGAR DADOS E ESTOQUE ---
@st.cache_data(ttl=1)
def carregar_dados_sheets():
    id_estoque = "10f18RZ-48HiJS2HckG6Siw2WRE9zz92_Pj6chkTwXik"
    id_loggers = "1ztZC3s0kKINJLNOR-BEYUUFjycxSVT7NMGVNWdxWh98"
    
    cb = int(time.time())
    url_estoque = f"https://docs.google.com/spreadsheets/d/{id_estoque}/export?format=csv&cb={cb}"
    url_tes = f"https://docs.google.com/spreadsheets/d/{id_loggers}/export?format=csv&gid=536812026&cb={cb}"
    
    try: df_est = pd.read_csv(url_estoque)
    except: df_est = None
    
    if df_est is not None: 
        df_est['Descricao_Clean'] = df_est['Descricao'].astype(str).str.upper()
        
        col_serie_est = next((c for c in df_est.columns if "SERIE" in c.upper() or "SÉRIE" in c.upper()), None)
        col_id_est = next((c for c in df_est.columns if "IDENTIFICACAO" in c.upper() or "ID" in c.upper()), None)
        
        if col_serie_est and st.session_state.seriais_consumidos:
            df_est = df_est[~df_est[col_serie_est].astype(str).str.strip().isin(st.session_state.seriais_consumidos)]
        if col_id_est and st.session_state.ids_consumidos:
            df_est = df_est[~df_est[col_id_est].astype(str).str.strip().isin(st.session_state.ids_consumidos)]

    try:
        df_tes = pd.read_csv(url_tes)
        if len(df_tes.columns) >= 2:
            df_tes = df_tes.iloc[:, [0, 1]]
            df_tes.columns = ['Estudo', 'TE']
    except: df_tes = None
        
    return df_est, df_tes

df_estoque, df_te = carregar_dados_sheets()

# --- LÓGICA DE NAVEGAÇÃO DE PÁGINAS ---
if "pagina_atual" not in st.session_state:
    st.session_state.pagina_atual = "automacao"

# --- BARRA LATERAL (SIDEBAR) ---
with st.sidebar:
    st.markdown("""
        <div style='text-align: left; padding-bottom: 5px;'>
            <h1 style='color: #1b3834; font-size: 36px; line-height: 0.8; margin: 0; font-family: Arial, sans-serif; letter-spacing: -1px;'>DRS</h1>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
        <div style="display: flex; align-items: center; margin-bottom: 2px;">
            <div style="width: 8px; height: 8px; border-radius: 50%; background-color: #28a745; margin-right: 6px; box-shadow: 0 0 4px #28a745;"></div>
            <h3 style="margin: 0; font-size: 12px; color: #1b3834;">Painel de Operações</h3>
        </div>
        <p style="font-size: 10px; color: #28a745; margin-top: 0px; margin-left: 14px; font-weight: bold; margin-bottom: 12px;">Sistema Apto para Uso</p>
    """, unsafe_allow_html=True)
    
    st.markdown("<p style='font-size: 10px; color: #666; font-weight: bold; margin-bottom: 3px; text-transform: uppercase;'>Navegação</p>", unsafe_allow_html=True)
    
    if st.button("📦 Automação de Packing List", use_container_width=True):
        st.session_state.pagina_atual = "automacao"
        st.rerun()
    if st.button("⚖️ Cruzamento NEWSE x PACKING", use_container_width=True):
        st.session_state.pagina_atual = "cruzamento"
        st.rerun()
    if st.button("📧 Gerador de E-mail (GR)", use_container_width=True):
        st.session_state.pagina_atual = "email"
        st.rerun()

    st.write("") 

    raw_tt = len(df_estoque[df_estoque['Descricao_Clean'].str.contains("TEMPTALE", na=False)]) if df_estoque is not None else 0
    raw_ta_amb = len(df_estoque[df_estoque['Descricao_Clean'].str.contains("TAGALERT 15-25", na=False)]) if df_estoque is not None else 0
    raw_ta_ref = len(df_estoque[df_estoque['Descricao_Clean'].str.contains("TAGALERT 2-8", na=False)]) if df_estoque is not None else 0

    st.markdown(f"""
        <div style="font-size: 11px; color: #4a5568; margin-top: 5px; margin-bottom: 5px; line-height: 1.4; background-color: #f4
