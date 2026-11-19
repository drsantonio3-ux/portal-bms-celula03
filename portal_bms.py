import streamlit as st
from pypdf import PdfReader
import pandas as pd
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import re
import urllib.request
import json
import time
import os


def extrair_texto_pdf(leitor, separador=""):
    """Extrai o texto de todas as páginas; ignora páginas sem texto extraível."""
    return separador.join([(pagina.extract_text() or "") for pagina in leitor.pages])


def detectar_faixas_tagalert(texto_upper):
    """Procura faixas 'TEMP 2-8 C' etc. associadas a TAGALERT. Limite superior
    até 8°C = Refrigerado; acima disso = Ambiente."""
    tem_ref = False
    tem_amb = False
    for m in re.finditer(r"TEMP\s*-?\d+(?:[.,]\d+)?\s*-\s*(\d+(?:[.,]\d+)?)\s*C", texto_upper):
        janela = texto_upper[m.end(): m.end() + 200]
        if "TAGALERT" not in janela and "TAG ALERT" not in janela:
            continue
        limite_superior = float(m.group(1).replace(",", "."))
        if limite_superior <= 8:
            tem_ref = True
        else:
            tem_amb = True
    return tem_ref, tem_amb


def detectar_faixas_newse(texto_upper):
    """Igual à anterior, mas para a NEWSE ('2 A 8ºC', '15 A 25ºC'). Sem \\b depois
    do 'C' porque a Quantidade às vezes vem colada na temperatura (ex: '2 A 8ºC12')."""
    tem_ref = False
    tem_amb = False
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*A\s*(\d+(?:[.,]\d+)?)\s*[°º]?C", texto_upper):
        limite_superior = float(m.group(2).replace(",", "."))
        if limite_superior <= 8:
            tem_ref = True
        else:
            tem_amb = True
    return tem_ref, tem_amb


# --- Reconhecimento de medicações citotóxicas (agrupamento de loggers) ---
# Lookahead negativo em PACLITAXEL para não confundir com PACLITAXEL NAB.
CITOTOXICOS_REGEX = re.compile(r"BORTEZOMIB|SPRYCEL|DASATINIB|PACLITAXEL(?!\s*NAB)|TAXOL|CYCLOPHOSPHAMIDE|CICLOFOSFAMIDA")
CITOTOXICO_TEXTO_REGEX = re.compile(r"CYTOTOXIC|CITOT[ÓO]XIC")

# Linha "Quantidade EA Data" que aparece uma vez por item (ex: "8 EA 30-JUN-2027").
ITEM_ANCHOR_REGEX = re.compile(r"\d+\s*EA\s+\d{1,2}-[A-Z]{3}-\d{4}")


def normalizar_faixa_temperatura(bloco_upper):
    """Extrai e normaliza a faixa/limite de temperatura de UM item."""
    m = re.search(r"TEMP\s+NOT\s+EXCEED\s+(\d+(?:[.,]\d+)?)\s*C", bloco_upper)
    if m:
        return f"NE{m.group(1).replace(',', '.')}"
    m = re.search(r"TEMP\s*(-?\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)\s*C", bloco_upper)
    if m:
        minv = m.group(1).replace(',', '.')
        maxv = m.group(2).replace(',', '.')
        return f"{minv}-{maxv}"
    return "FAIXA_NAO_IDENTIFICADA"


def faixa_e_refrigerada(faixa_normalizada):
    """True = refrigerado (limite superior <= 8°C), False = ambiente,
    None = indeterminado (tratado como ambiente)."""
    try:
        if faixa_normalizada.startswith("NE"):
            return float(faixa_normalizada[2:]) <= 8
        if "-" in faixa_normalizada:
            return float(faixa_normalizada.split("-", 1)[1]) <= 8
    except ValueError:
        pass
    return None


def item_e_citotoxico(bloco_upper):
    return bool(CITOTOXICO_TEXTO_REGEX.search(bloco_upper)) or bool(CITOTOXICOS_REGEX.search(bloco_upper))


def analisar_itens_packing(texto_upper):
    """Divide a Packing List em blocos por item e extrai, para cada um, o
    dispositivo (TempTale ou Tag Alert), se é citotóxico e a faixa de temperatura."""
    posicoes = list(ITEM_ANCHOR_REGEX.finditer(texto_upper))
    itens = []
    for i, m in enumerate(posicoes):
        fim_bloco = posicoes[i + 1].start() if i + 1 < len(posicoes) else len(texto_upper)
        bloco = texto_upper[m.end():fim_bloco]

        dispositivo = None
        if "TEMPTALE" in bloco or "TT4" in bloco:
            dispositivo = "TEMPTALE"
        elif "TAGALERT" in bloco or "TAG ALERT" in bloco:
            dispositivo = "TAGALERT"
        if dispositivo is None:
            continue

        itens.append({
            "dispositivo": dispositivo,
            "citotoxico": item_e_citotoxico(bloco),
            "faixa": normalizar_faixa_temperatura(bloco),
        })
    return itens


def agrupar_loggers_necessarios(itens):
    """Decide quantos loggers de cada tipo são necessários: itens do mesmo
    dispositivo, mesma faixa e mesmo status de citotóxico dividem 1 logger;
    citotóxicos nunca dividem caixa com não citotóxicos.
    Retorna (qtd_temptale, qtd_tagalert_amb, qtd_tagalert_ref, tem_citotoxico)."""
    grupos_temptale = set()
    grupos_tagalert = set()
    tem_citotoxico = False

    for item in itens:
        if item["citotoxico"]:
            tem_citotoxico = True
        if item["dispositivo"] == "TEMPTALE":
            grupos_temptale.add((item["citotoxico"], item["faixa"]))
        else:
            refrigerado = faixa_e_refrigerada(item["faixa"])
            categoria = "REF" if refrigerado else "AMB"
            grupos_tagalert.add((item["citotoxico"], categoria))

    qtd_tagalert_amb = sum(1 for _, cat in grupos_tagalert if cat == "AMB")
    qtd_tagalert_ref = sum(1 for _, cat in grupos_tagalert if cat == "REF")
    return len(grupos_temptale), qtd_tagalert_amb, qtd_tagalert_ref, tem_citotoxico


# --- Fichas de segurança obrigatórias (só existem para estas 4 medicações) ---
FICHAS_SEGURANCA = [
    (re.compile(r"BORTEZOMIB"), "fichas_seguranca/ficha_bortezomib.pdf", "Bortezomib (Velcade)"),
    (re.compile(r"SPRYCEL|DASATINIB"), "fichas_seguranca/ficha_sprycel_dasatinib.pdf", "Sprycel / Dasatinib"),
    (re.compile(r"PACLITAXEL|TAXOL"), "fichas_seguranca/ficha_taxol_paclitaxel.pdf", "Taxol / Paclitaxel"),
    (re.compile(r"CYCLOPHOSPHAMIDE|CICLOFOSFAMIDA"), "fichas_seguranca/ficha_ciclofosfamida.pdf", "Cyclophosphamide / Ciclofosfamida"),
]

# --- Módulos do portal (arquivos na mesma pasta deste) ---
from checklist_particularidades import renderizar_checklist_particularidades
from checklist_brasil import renderizar_checklist_brasil, CATEGORIA_MEDICACAO, CATEGORIA_SUPRIMENTO
from leitura_packing import extrair_dados_packing_para_email, OCR_DISPONIVEL
from gerador_email import montar_html_gerador
from tabela_programacao import html_tabela_programacao


# --- CONFIGURAÇÕES DA PÁGINA ---
st.set_page_config(page_title="DRS Group | BMS Operations", layout="wide", page_icon="🏢")

# --- TEMA: PRETO, CINZA E LARANJA ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    :root {
        --drs-preto: #141414;
        --drs-grafite: #232323;
        --drs-cinza: #6b7280;
        --drs-cinza-claro: #9ca3af;
        --drs-laranja: #f28c1b;
        --drs-laranja-escuro: #d97706;
        --drs-fundo: #f3f4f6;
        --drs-borda: #e2e4e8;
    }

    html, body, [class*="css"], .stApp {
        font-family: 'Inter', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif !important;
    }

    .stApp {
        background: radial-gradient(circle at top left, #ffffff 0%, var(--drs-fundo) 55%);
    }

    header[data-testid="stHeader"] { background: rgba(0,0,0,0); }

    h1, h2, h3, h4, h5, h6 {
        color: var(--drs-preto) !important;
        font-weight: 700;
        margin-bottom: 0.3rem;
    }
    h2 { font-size: 19px !important; letter-spacing: -0.2px; }
    h3 { font-size: 13px !important; text-transform: uppercase; letter-spacing: 0.6px; color: var(--drs-cinza) !important; font-weight: 700 !important; }
    h4 { font-size: 12px !important; }

    /* Botões */
    .stButton>button {
        background-color: var(--drs-laranja) !important;
        color: #111111 !important;
        border-radius: 7px;
        border: 1px solid var(--drs-laranja) !important;
        font-size: 13px !important;
        font-weight: 700;
        padding: 0.45rem 1rem;
        transition: 0.15s ease-in-out;
        box-shadow: 0 1px 4px rgba(0,0,0,0.18);
    }
    .stButton>button:hover {
        background-color: var(--drs-preto) !important;
        border-color: var(--drs-preto) !important;
        color: var(--drs-laranja) !important;
    }
    .stButton>button:disabled {
        background-color: #e5e7eb !important;
        border-color: #e5e7eb !important;
        color: #9ca3af !important;
        box-shadow: none !important;
    }

    /* Barra lateral (preta) */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f0f10 0%, #1c1c1e 100%);
        border-right: 1px solid #2a2a2a;
        padding-top: 1rem;
    }
    [data-testid="stSidebar"] .stButton>button {
        background: transparent !important;
        color: #d1d5db !important;
        border: 1px solid transparent !important;
        box-shadow: none !important;
        text-align: left !important;
        justify-content: flex-start !important;
        font-weight: 600 !important;
        width: 100%;
    }
    [data-testid="stSidebar"] .stButton>button:hover {
        background: #262626 !important;
        color: var(--drs-laranja) !important;
    }
    [data-testid="stSidebar"] .stButton>button[kind="primary"],
    [data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
        background: var(--drs-laranja) !important;
        color: #111111 !important;
        border: 1px solid var(--drs-laranja) !important;
        box-shadow: 0 2px 8px rgba(242,140,27,0.35) !important;
    }
    [data-testid="stSidebar"] .stButton>button[kind="primary"]:hover,
    [data-testid="stSidebar"] button[data-testid="stBaseButton-primary"]:hover {
        background: var(--drs-laranja-escuro) !important;
        color: #111111 !important;
    }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: #9ca3af !important; }

    /* Cartões / blocos aninhados */
    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"] {
        background-color: #ffffff;
        padding: 12px;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        border: 1px solid var(--drs-borda);
    }
    [data-testid="stSidebar"] div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"] {
        background-color: transparent;
        padding: 0;
        border: none;
        box-shadow: none;
    }

    [data-testid="stFileUploaderDropzone"] {
        border-radius: 10px !important;
        border: 1.5px dashed #9ca3af !important;
        background-color: #fafafa !important;
    }

    /* Faixa de título de cada página */
    .drs-banner {
        background: linear-gradient(135deg, #141414 0%, #2b2b2b 100%);
        padding: 20px 26px;
        border-radius: 12px;
        border-left: 6px solid var(--drs-laranja);
        margin-bottom: 20px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.18);
    }
    .drs-banner h2 { color: #ffffff !important; margin: 0 0 6px 0; font-size: 18px !important; }
    .drs-banner p { color: #d1d5db; margin: 0; font-size: 13px; line-height: 1.4; }
    .drs-banner b { color: var(--drs-laranja); }

    /* Aviso fixo de pendência */
    .drs-alerta-pendente {
        position: sticky;
        top: 0.5rem;
        z-index: 999;
        background: linear-gradient(90deg, #fff4e6, #ffe9cc);
        border: 1px solid var(--drs-laranja);
        color: #7a4a10;
        padding: 10px 16px;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 600;
        margin-bottom: 16px;
        box-shadow: 0 2px 8px rgba(242,140,27,0.18);
    }
    </style>
""", unsafe_allow_html=True)


def banner(titulo, descricao):
    st.markdown(f"""
        <div class="drs-banner">
            <h2>{titulo}</h2>
            <p>{descricao}</p>
        </div>
    """, unsafe_allow_html=True)


# --- SISTEMA DE AUTENTICAÇÃO ---
SENHA_ACESSO = st.secrets.get("SENHA_ACESSO")

if not SENHA_ACESSO:
    st.error(
        "⚠️ O acesso ainda não foi configurado. Peça ao administrador para "
        "definir o secret **SENHA_ACESSO** nas configurações do app no "
        "Streamlit Community Cloud (menu do app → Settings → Secrets)."
    )
    st.stop()


def tela_login(mostrar_erro):
    """Tela de login: fundo preto + cartão central com logo e campo de senha."""
    st.markdown("""
        <style>
        .stApp { background: linear-gradient(160deg, #0b0b0c 0%, #1c1c1e 55%, #141414 100%) !important; }
        [data-testid="stSidebar"] { display: none !important; }
        header[data-testid="stHeader"] { background: rgba(0,0,0,0) !important; }

        .drs-login-topo {
            height: 6px; margin: -12px -12px 22px -12px;
            background: linear-gradient(90deg, #f28c1b, #d97706);
            border-radius: 10px 10px 0 0;
        }
        .drs-login-badge {
            width: 56px; height: 56px; margin: 0 auto 16px auto;
            border-radius: 14px;
            background: linear-gradient(135deg, #f28c1b 0%, #d97706 100%);
            display: flex; align-items: center; justify-content: center;
            font-family: 'Inter', sans-serif; font-weight: 800; font-size: 18px; color: #111111;
            letter-spacing: 0.5px;
            box-shadow: 0 8px 20px rgba(0,0,0,0.35);
        }
        .drs-login-title {
            text-align: center; font-family: 'Inter', sans-serif; font-weight: 800 !important;
            font-size: 22px !important; color: #141414 !important;
            letter-spacing: 0.4px; margin: 0 !important;
        }
        .drs-login-subtitle {
            text-align: center; font-family: 'Inter', sans-serif; font-weight: 700; font-size: 12px;
            color: #f28c1b; text-transform: uppercase; letter-spacing: 1.2px;
            margin: 6px 0 18px 0;
        }
        .drs-login-desc {
            text-align: center; font-size: 13px; color: #6b7280; line-height: 1.5; margin-bottom: 6px;
        }
        .drs-login-footer {
            font-size: 11px; color: #9ca3af; text-align: center; margin-top: 16px;
        }
        </style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.3, 1])
    with col2:
        with st.container():
            st.markdown("""
                <div class="drs-login-topo"></div>
                <div style="padding: 22px 18px 6px 18px;">
                    <div class="drs-login-badge">DRS</div>
                    <p class="drs-login-title">DRS GROUP</p>
                    <p class="drs-login-subtitle">🧬 Célula 03 · BMS Operations</p>
                    <p class="drs-login-desc">Painel interno de automação de Packing List, controle de<br>
                    estoque e geração de e-mails.<br>Acesso restrito à equipe autorizada.</p>
                </div>
            """, unsafe_allow_html=True)
            st.text_input(
                "Senha de Acesso", type="password", on_change=senha_inserida_callback,
                key="password_input", label_visibility="collapsed", placeholder="🔒 Senha de acesso",
            )
            if mostrar_erro:
                st.error("❌ Credencial inválida. Acesso negado.")
            st.markdown("<div class='drs-login-footer'>Acesso restrito · Uso interno DRS Group</div>", unsafe_allow_html=True)


def senha_inserida_callback():
    if st.session_state["password_input"] == SENHA_ACESSO:
        st.session_state["password_correta"] = True
        del st.session_state["password_input"]
    else:
        st.session_state["password_correta"] = False


def verificar_senha():
    if "password_correta" not in st.session_state:
        tela_login(mostrar_erro=False)
        return False
    elif not st.session_state["password_correta"]:
        tela_login(mostrar_erro=True)
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
if "baixas_registradas" not in st.session_state:
    st.session_state.baixas_registradas = {}  # arquivo_id -> {delivery_number, itens, data_uso}
if "alocacao_pendente" not in st.session_state:
    st.session_state.alocacao_pendente = False
if "packing_uploader_key" not in st.session_state:
    st.session_state.packing_uploader_key = 0
if "solicitacoes_brasil_registradas" not in st.session_state:
    st.session_state.solicitacoes_brasil_registradas = {}  # arquivo_id -> {itens, data_uso}
if "brasil_uploader_key" not in st.session_state:
    st.session_state.brasil_uploader_key = 0

# --- CARREGAR DADOS E ESTOQUE ---
@st.cache_data(ttl=1)
def carregar_dados_sheets():
    id_estoque = st.secrets.get("ID_PLANILHA_ESTOQUE", "10f18RZ-48HiJS2HckG6Siw2WRE9zz92_Pj6chkTwXik")
    gid_estoque = st.secrets.get("GID_PLANILHA_ESTOQUE", "667151981")
    id_loggers = st.secrets.get("ID_PLANILHA_LOGGERS", "1ztZC3s0kKINJLNOR-BEYUUFjycxSVT7NMGVNWdxWh98")

    cb = int(time.time())
    # gid fixo (aba "ESTOQUE") para não depender da ordem das abas.
    url_estoque = f"https://docs.google.com/spreadsheets/d/{id_estoque}/export?format=csv&gid={gid_estoque}&cb={cb}"
    url_tes = f"https://docs.google.com/spreadsheets/d/{id_loggers}/export?format=csv&gid=536812026&cb={cb}"

    try: df_est = pd.read_csv(url_estoque)
    except: df_est = None

    if df_est is not None:
        try:
            df_est['Descricao_Clean'] = df_est['Descricao'].astype(str).str.upper()

            col_serie_est = next((c for c in df_est.columns if "SERIE" in c.upper() or "SÉRIE" in c.upper()), None)
            col_id_est = next((c for c in df_est.columns if "IDENTIFICACAO" in c.upper() or "ID" in c.upper()), None)

            if col_serie_est and st.session_state.seriais_consumidos:
                df_est = df_est[~df_est[col_serie_est].astype(str).str.strip().isin(st.session_state.seriais_consumidos)]
            if col_id_est and st.session_state.ids_consumidos:
                df_est = df_est[~df_est[col_id_est].astype(str).str.strip().isin(st.session_state.ids_consumidos)]
        except Exception:
            # Nome de coluna mudou na planilha: só desativa o estoque, sem derrubar o app.
            df_est = None

    try:
        df_tes = pd.read_csv(url_tes)
        if len(df_tes.columns) >= 2:
            df_tes = df_tes.iloc[:, [0, 1]]
            df_tes.columns = ['Estudo', 'TE']
    except: df_tes = None

    return df_est, df_tes

df_estoque, df_te = carregar_dados_sheets()

# --- NAVEGAÇÃO ---
if "pagina_atual" not in st.session_state or st.session_state.pagina_atual not in ("automacao", "bms_brasil", "email", "tabela_programacao"):
    st.session_state.pagina_atual = "automacao"

# --- BARRA LATERAL ---
with st.sidebar:
    st.markdown("""
        <div style='text-align: left; padding: 4px 0 10px 0; border-bottom: 1px solid #2f2f2f; margin-bottom: 14px;'>
            <h1 style='color: #ffffff !important; font-size: 32px; line-height: 0.9; margin: 0; font-family: "Inter", Arial, sans-serif; font-weight: 800; letter-spacing: -1px;'>DRS <span style="color:#f28c1b;">GROUP</span></h1>
            <p style="margin: 4px 0 0 0; font-size: 10px; color: #9ca3af; font-weight: 700; letter-spacing: 1.5px;">BMS OPERATIONS</p>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("""
        <div style="display: flex; align-items: center; margin-bottom: 2px;">
            <div style="width: 8px; height: 8px; border-radius: 50%; background-color: #f28c1b; margin-right: 6px; box-shadow: 0 0 6px #f28c1b;"></div>
            <h3 style="margin: 0; font-size: 11px; color: #e5e7eb !important;">Painel de Operações</h3>
        </div>
        <p style="font-size: 10px; color: #f28c1b; margin-top: 0px; margin-left: 14px; font-weight: bold; margin-bottom: 14px;">Sistema Apto para Uso</p>
    """, unsafe_allow_html=True)

    st.markdown("<p style='font-size: 10px; color: #9ca3af; font-weight: 700; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.6px;'>Navegação</p>", unsafe_allow_html=True)

    bloqueado = st.session_state.alocacao_pendente
    paginas_menu = [
        ("automacao", "📦  Automação de Packing List"),
        ("bms_brasil", "🇧🇷  BMS Brasil - Solicitações"),
        ("email", "📧  Gerador de E-mail (GR)"),
        ("tabela_programacao", "🗓️  Tabela de Coleta e Entrega"),
    ]
    for chave, rotulo in paginas_menu:
        ativa = st.session_state.pagina_atual == chave
        if st.button(
            rotulo,
            use_container_width=True,
            type="primary" if ativa else "secondary",
            disabled=(bloqueado and not ativa),
            key=f"nav_{chave}",
        ):
            st.session_state.pagina_atual = chave
            st.rerun()

    if bloqueado:
        st.caption("🔒 Finalize a baixa em andamento (preencha o DEL# e confirme) para liberar a navegação.")

    st.write("")

    raw_tt = len(df_estoque[df_estoque['Descricao_Clean'].str.contains("TEMPTALE", na=False)]) if df_estoque is not None else 0
    raw_ta_amb = len(df_estoque[df_estoque['Descricao_Clean'].str.contains("TAGALERT 15-25", na=False)]) if df_estoque is not None else 0
    raw_ta_ref = len(df_estoque[df_estoque['Descricao_Clean'].str.contains("TAGALERT 2-8", na=False)]) if df_estoque is not None else 0

    st.markdown(f"""
        <div style="font-size: 11px; color: #d1d5db; margin-top: 5px; margin-bottom: 5px; line-height: 1.6; background-color: #1f1f21; padding: 12px 14px; border-radius: 10px; border: 1px solid #2f2f2f; border-left: 4px solid #f28c1b;">
            <b style="font-size: 10px; color: #ffffff; letter-spacing: 0.4px;">LOGGERS DISPONÍVEIS</b><br>
            <div style="display:flex; justify-content:space-between; margin-top:6px;"><span>Tag Alert Ambiente</span><b style="color: #f28c1b;">{raw_ta_amb}</b></div>
            <div style="display:flex; justify-content:space-between;"><span>Tag Alert Refrigerado</span><b style="color: #f28c1b;">{raw_ta_ref}</b></div>
            <div style="display:flex; justify-content:space-between;"><span>TempTale Ambiente</span><b style="color: #f28c1b;">{raw_tt}</b></div>
        </div>
    """, unsafe_allow_html=True)


def card_metrica(titulo, valor):
    return f"""
    <div style="background-color: #ffffff; padding: 14px 16px; border-radius: 10px; border: 1px solid #e2e4e8; border-top: 3px solid #f28c1b; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
        <p style="margin: 0; font-size: 10px; color: #9ca3af; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">{titulo}</p>
        <p style="margin: 5px 0 0 0; font-size: 17px; color: #141414; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{valor}">{valor}</p>
    </div>
    """


def linha_copia(rotulo, valor, altura=45):
    """Linha 'ROTULO: valor [Copiar]' (mesmo visual na Automação e na BMS Brasil)."""
    html = f"""<div style="display:flex; justify-content:space-between; align-items: center; padding:6px 12px; background:#f9fafb; border:1px solid #e5e7eb; border-radius:4px; margin-bottom:5px;">
    <div><span style="color:#4b5563; font-weight:bold; font-size:11px;">{rotulo}:</span> <span style="font-family:monospace; color:#d97706; font-size:13px; font-weight:bold; margin-left:5px;">{valor}</span></div>
    <button onclick="navigator.clipboard.writeText('{valor}'); this.innerText='Copiado!'; setTimeout(()=>this.innerText='Copiar', 2000)" style="background:#f28c1b; color:#111111; border:none; border-radius:3px; cursor:pointer; font-size:11px; padding:4px 10px; font-weight:bold;">Copiar</button></div>"""
    components.html(html, height=altura)


# ==========================================
# PÁGINA: AUTOMAÇÃO DE PACKING LIST
# ==========================================

if st.session_state.pagina_atual == "automacao":

    banner(
        "📦 Automação de Packing List (SLA e Estoque)",
        "Faça o upload do <b>Packing List (PDF)</b> para extração imediata de dados. O sistema realiza a sugestão automática de "
        "<b>ativos logísticos</b>, cálculo exato do <b>SLA de entrega</b> (considerando dias úteis) e a "
        "<b>baixa de estoque ao vivo na planilha</b>.",
    )

    FERIADOS = [datetime(2026, 9, 7).date()]
    def is_dia_util(data): return data.weekday() < 5 and data not in FERIADOS
    def proximo_dia_util(data_atual):
        proximo_dia = data_atual + timedelta(days=1)
        while not is_dia_util(proximo_dia): proximo_dia += timedelta(days=1)
        return proximo_dia
    def somar_dias_uteis(data_inicio, dias):
        data_atual = data_inicio
        dias_adicionados = 1
        while dias_adicionados < dias:
            data_atual = proximo_dia_util(data_atual)
            dias_adicionados += 1
        return data_atual

    col_pdf, col_data = st.columns([3, 1])
    with col_pdf:
        arquivo_pdf = st.file_uploader(
            "📥 Arraste o PDF da Packing List aqui",
            type=["pdf"],
            key=f"packing_{st.session_state.packing_uploader_key}",
        )
    with col_data: data_recebimento = st.date_input("Data de Recebimento", datetime.today())

    if arquivo_pdf is None:
        # Sem PDF: nada foi retirado do estoque, então a navegação não precisa ficar travada.
        st.session_state.alocacao_pendente = False

    if arquivo_pdf is not None:
        leitor = PdfReader(arquivo_pdf)
        texto_upper = extrair_texto_pdf(leitor).upper()

        estudo_encontrado = "NÃO IDENTIFICADO"
        match_protocolo = re.search(r"PROTOCOL\s*NUMBER\s*[:\s]*([A-Z0-9\-\/]+)", texto_upper)
        if match_protocolo: estudo_encontrado = match_protocolo.group(1).split('/')[0].strip()
        else:
            for palavra in texto_upper.split():
                if palavra.startswith("CA") and "-" in palavra:
                    estudo_encontrado = palavra.split('/')[0].strip(); break

        te_resultado = "NÃO ENCONTRADO"
        if df_te is not None:
            for idx, row in df_te.iterrows():
                if estudo_encontrado in str(row['Estudo']).upper():
                    te_resultado = str(row['TE']).strip(); break

        # --- Análise por item (quantos loggers de cada tipo são realmente necessários) ---
        itens_detectados = analisar_itens_packing(texto_upper)

        if itens_detectados:
            qtd_temptale, qtd_tagalert_amb, qtd_tagalert_ref, tem_citotoxico = agrupar_loggers_necessarios(itens_detectados)
        else:
            # Formato não reconhecido: usa o modelo antigo como rede de segurança.
            tem_temptale_doc = "TEMPTALE" in texto_upper or "TT4" in texto_upper
            tem_tagalert_ref_doc, tem_tagalert_amb_doc = detectar_faixas_tagalert(texto_upper)
            if "TAGALERT" in texto_upper and not tem_tagalert_ref_doc and not tem_tagalert_amb_doc:
                tem_tagalert_amb_doc = True
            tem_citotoxico = bool(CITOTOXICOS_REGEX.search(texto_upper)) or bool(CITOTOXICO_TEXTO_REGEX.search(texto_upper))
            qtd_temptale = (1 if tem_temptale_doc else 0) + (1 if tem_citotoxico and tem_temptale_doc else 0)
            qtd_tagalert_amb = 1 if tem_tagalert_amb_doc else 0
            qtd_tagalert_ref = 1 if tem_tagalert_ref_doc else 0

        tem_temptale = qtd_temptale > 0
        tem_tagalert_amb = qtd_tagalert_amb > 0
        tem_tagalert_ref = qtd_tagalert_ref > 0

        cidade_destino = "NÃO IDENTIFICADA"
        linhas = texto_upper.split('\n')
        for i, linha in enumerate(linhas):
            if any(term in linha for term in ["SHIP TO", "SÃO PAULO", "SAO PAULO"]):
                for j in range(max(0, i-2), min(len(linhas), i+6)):
                    if any(c in linhas[j] for c in ["NATAL", "RIO DE JANEIRO", "CURITIBA", "BELO HORIZONTE", "PORTO ALEGRE", "SALVADOR", "BRASILIA", "SÃO PAULO", "SAO PAULO", "CAMPINAS", "RIBEIRAO PRETO", "JAU", "SAO JOSE"]):
                        cidade_destino = "SÃO PAULO (CAPITAL)" if "PAULO" in linhas[j] else linhas[j].strip(); break

        is_capital = "SÃO PAULO (CAPITAL)" in cidade_destino and not any(exc in cidade_destino for exc in ["JAÚ", "RIO PRETO", "RIBEIRÃO", "CAMPOS"])

        st.success("✅ Documento processado com sucesso.")

        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(card_metrica("Destino", cidade_destino), unsafe_allow_html=True)
        with c2: st.markdown(card_metrica("Protocolo / Estudo", estudo_encontrado), unsafe_allow_html=True)
        with c3: st.markdown(card_metrica("TE Correspondente", te_resultado), unsafe_allow_html=True)
        st.write("")

        st.markdown("### 📦 Separação e Baixa de Estoque")

        # Identidade estável deste upload (evita duplicar a baixa se a página
        # recarregar com o mesmo PDF ainda anexado).
        arquivo_id = getattr(arquivo_pdf, "file_id", None) or f"{arquivo_pdf.name}_{arquivo_pdf.size}"
        registro_existente = st.session_state.baixas_registradas.get(arquivo_id)

        if registro_existente:
            st.session_state.alocacao_pendente = False
            ids_utilizados = registro_existente["itens"]
            st.success(
                f"✅ Baixa já registrada para este Packing List — **DEL# {registro_existente['delivery_number']}** "
                f"em {registro_existente['data_uso']}."
            )
            for p in ids_utilizados:
                st.markdown(f"- **{p['label']}** ➔ Palete: {p['palete']} | ID: {p['id_est']} | Série: {p['serie']}")
            st.caption("Para dar baixa em um novo envio, envie um novo arquivo PDF acima.")
        else:
            ids_utilizados = []

            if df_estoque is not None and not df_estoque.empty:
                df_estoque_temp = df_estoque.copy()
                def allocate_logger(nome_busca, label):
                    filtro = df_estoque_temp[
                        df_estoque_temp['Descricao_Clean'].str.contains(nome_busca, na=False)
                    ]
                    if not filtro.empty:
                        item = filtro.iloc[0]
                        df_estoque_temp.drop(item.name, inplace=True)

                        serie = next((str(item[c]) for c in item.index if "SERIE" in c.upper() or "SÉRIE" in c.upper()), str(item.iloc[7]) if len(item)>7 else "N/A")
                        ids_utilizados.append({
                            "label": label,
                            "palete": str(item.get('Palete', 'N/A')).strip(),
                            "id_est": str(item.get('Identificacao Estoque', item.get('Identificacao Estoque', 'N/A'))).strip(),
                            "serie": serie
                        })
                        st.info(f"**{label}** alocado ➔ Palete: {item.get('Palete', 'N/A')} | ID: {item.get('Identificacao Estoque', 'N/A')} | Série: {serie}")
                    else:
                        st.warning(f"⚠️ **{label}**: Sem saldo disponível no estoque!")

                # Aloca exatamente a quantidade de cada logger que os itens realmente precisam.
                for i in range(qtd_temptale):
                    rotulo = "TempTale Ambiente" if qtd_temptale == 1 else f"TempTale Ambiente ({i + 1}/{qtd_temptale})"
                    allocate_logger("TEMPTALE", rotulo)
                for i in range(qtd_tagalert_amb):
                    rotulo = "Tag Alert Ambiente" if qtd_tagalert_amb == 1 else f"Tag Alert Ambiente ({i + 1}/{qtd_tagalert_amb})"
                    allocate_logger("TAGALERT 15-25", rotulo)
                for i in range(qtd_tagalert_ref):
                    rotulo = "Tag Alert Refrigerado" if qtd_tagalert_ref == 1 else f"Tag Alert Refrigerado ({i + 1}/{qtd_tagalert_ref})"
                    allocate_logger("TAGALERT 2-8", rotulo)

                if tem_citotoxico:
                    st.markdown(
                        "<div style='font-size:12px; color:#92400e; background:#fff7ed; border:1px solid #fdba74; "
                        "border-radius:6px; padding:6px 10px; margin:6px 0;'>🧪 Medicação citotóxica identificada "
                        "— por regra, essa carga segue em caixa separada (já refletido na quantidade de loggers acima).</div>",
                        unsafe_allow_html=True
                    )

                # --- Fichas de segurança obrigatórias (citotóxicos) ---
                fichas_encontradas = [
                    (path, rotulo) for regex, path, rotulo in FICHAS_SEGURANCA if regex.search(texto_upper)
                ]
                if fichas_encontradas:
                    st.markdown(
                        "<div style='font-size:12px; color:#92400e; background:#fff7ed; border:1px solid #fdba74; "
                        "border-radius:6px; padding:6px 10px; margin:6px 0;'>📎 <b>Ficha de segurança obrigatória "
                        "no check-list</b> para a(s) medicação(ões) identificada(s) abaixo:</div>",
                        unsafe_allow_html=True
                    )
                    cols_ficha = st.columns(len(fichas_encontradas))
                    for col_ficha, (caminho_ficha, rotulo_ficha) in zip(cols_ficha, fichas_encontradas):
                        with col_ficha:
                            if os.path.exists(caminho_ficha):
                                with open(caminho_ficha, "rb") as f_ficha:
                                    st.download_button(
                                        f"📄 Ficha — {rotulo_ficha}",
                                        data=f_ficha.read(),
                                        file_name=os.path.basename(caminho_ficha),
                                        mime="application/pdf",
                                        use_container_width=True,
                                        key=f"ficha_{os.path.basename(caminho_ficha)}",
                                    )
                            else:
                                st.warning(f"⚠️ Ficha de {rotulo_ficha} não encontrada no sistema.")

                # Itens alocados e baixa não confirmada: trava a navegação.
                st.session_state.alocacao_pendente = bool(ids_utilizados)

                if ids_utilizados:
                    st.markdown(
                        "<div class='drs-alerta-pendente'>⚠️ Alocação pendente de confirmação — preencha o DEL# "
                        "e clique em <b>Executar Baixa no Estoque</b> antes de sair desta página, "
                        "ou os itens acima podem ser usados por outra pessoa.</div>",
                        unsafe_allow_html=True
                    )
                    components.html(
                        "<script>window.parent.onbeforeunload = function(e){ e.preventDefault(); e.returnValue = ''; return ''; };</script>",
                        height=0
                    )
                else:
                    components.html("<script>window.parent.onbeforeunload = null;</script>", height=0)

                col_del, col_btn = st.columns([2, 1])
                with col_del: delivery_number = st.text_input("DEL# (Delivery Number) para registro:")
                with col_btn:
                    st.write("")
                    if st.button("💾 Executar Baixa no Estoque", use_container_width=True):
                        if not delivery_number:
                            st.error("❌ Preencha o DEL#.")
                        else:
                            webhook_url = st.secrets.get(
                                "WEBHOOK_BAIXA_ESTOQUE",
                                "https://script.google.com/macros/s/AKfycbzpwZC2LW7PQ1JGMkJIZD3Rxd4nv4pfEZ1QS1D9jDxQbt4Qf2hiCmv9dJ8pAJnBHJglug/exec"
                            )

                            payload = {
                                "data_uso": datetime.today().strftime('%d/%m/%Y'),
                                "delivery_number": delivery_number,
                                "estudo": estudo_encontrado,
                                "te": te_resultado,
                                "cidade_destino": cidade_destino,
                                "itens": [
                                    {
                                        "tipo": p["label"],
                                        "palete": p["palete"],
                                        "id_est": p["id_est"],
                                        "serie": p["serie"]
                                    } for p in ids_utilizados
                                ]
                            }

                            try:
                                req = urllib.request.Request(
                                    webhook_url,
                                    data=json.dumps(payload).encode('utf-8'),
                                    headers={'Content-Type': 'application/json'}
                                )
                                resposta_bruta = urllib.request.urlopen(req, timeout=25).read().decode("utf-8")
                                try:
                                    resposta = json.loads(resposta_bruta)
                                except ValueError:
                                    resposta = {}

                                # O Apps Script responde HTTP 200 mesmo com erro interno,
                                # por isso é preciso checar o campo "result".
                                if resposta.get("result") != "success":
                                    raise RuntimeError(
                                        resposta.get("message", f"Resposta inesperada do servidor: {resposta_bruta[:300]}")
                                    )

                                for p in ids_utilizados:
                                    st.session_state.seriais_consumidos.add(str(p["serie"]).strip())
                                    st.session_state.ids_consumidos.add(str(p["id_est"]).strip())

                                st.session_state.baixas_registradas[arquivo_id] = {
                                    "delivery_number": delivery_number,
                                    "itens": ids_utilizados,
                                    "data_uso": datetime.today().strftime('%d/%m/%Y %H:%M'),
                                }
                                st.session_state.alocacao_pendente = False

                                # Troca a "key" do uploader para limpar o PDF anexado.
                                st.session_state.packing_uploader_key += 1

                                st.cache_data.clear()
                                itens_txt = ", ".join([p["label"] for p in ids_utilizados])
                                st.success(f"✅ Baixa executada com sucesso! DEL# **{delivery_number}** usado para: {itens_txt}.")
                                time.sleep(2)
                                st.rerun()
                            except Exception as ex:
                                st.error(f"Erro ao atualizar planilha: {ex}")
            else:
                st.warning("⚠️ Estoque indisponível no momento — não é possível alocar loggers automaticamente.")

        st.markdown("### 📋 Dados para Restrição e Particularidades")
        val_depositante = "056998982001260"
        val_palete = " | ".join([p["palete"] for p in ids_utilizados]) or "N/A"
        val_id = " | ".join([p["id_est"] for p in ids_utilizados]) or "N/A"
        val_te = te_resultado

        c_esq, c_dir = st.columns(2)
        with c_esq:
            linha_copia("DEPOSITANTE", val_depositante)
            linha_copia("PALETE", val_palete)
        with c_dir:
            linha_copia("ID ITEM", val_id)
            linha_copia("TE DO ESTUDO", val_te)

        # --- CHECKLIST DE PARTICULARIDADES (NOVO PADRÃO) ---
        st.markdown("### ✅ Checklist de Particularidades (novo padrão)")
        renderizar_checklist_particularidades(
            texto_upper, arquivo_id,
            qtd_temptale, qtd_tagalert_amb, qtd_tagalert_ref, tem_citotoxico,
        )

        st.markdown("### ⏱️ SLA e Prazos Operacionais")
        prazo_maximo = somar_dias_uteis(data_recebimento, 7)
        data_limite_doc = somar_dias_uteis(data_recebimento, 2)

        if tem_tagalert_ref and not is_capital:
            data_entrega = somar_dias_uteis(data_limite_doc, 2)
            st.warning(f"🚨 **ALERTA REFRIGERADO (FLY):** Validade 96h ativada. Entrega sugerida: {data_entrega.strftime('%d/%m/%Y')}")
        else:
            st.info(f"✅ **FLUXO PADRÃO.** Prazo DOC: {data_limite_doc.strftime('%d/%m/%Y')} | Limite Final: {prazo_maximo.strftime('%d/%m/%Y')}")

# ==========================================
# PÁGINA: BMS BRASIL - SOLICITAÇÕES
# ==========================================
elif st.session_state.pagina_atual == "bms_brasil":

    banner(
        "🇧🇷 BMS Brasil — Solicitações",
        "Anexe a <b>NEWSE (PDF)</b> e escolha a categoria. Para <b>Medicação</b>, o portal retira automaticamente o "
        "<b>Tag Alert</b> (Ambiente ou Refrigerado, conforme a temperatura da solicitação) e registra a retirada. "
        "<b>Equipamento / Suprimento</b> não usa Tag Alert. Nos dois casos o checklist de particularidades é gerado.",
    )

    arquivo_newse_brasil = st.file_uploader(
        "📥 Arraste o PDF da NEWSE (Solicitação Brasil) aqui",
        type=["pdf"],
        key=f"brasil_{st.session_state.brasil_uploader_key}",
    )

    if arquivo_newse_brasil is None:
        # Sem arquivo anexado nada foi retirado do estoque: libera a navegação.
        st.session_state.alocacao_pendente = False

    if arquivo_newse_brasil is not None:
        leitor_brasil = PdfReader(arquivo_newse_brasil)
        texto_brasil_upper = extrair_texto_pdf(leitor_brasil).upper()

        # --- Protocolo do estudo ---
        estudo_brasil = "NÃO IDENTIFICADO"
        match_protocolo_brasil = re.search(r"\bCA\d+-\d+\b", texto_brasil_upper)
        if match_protocolo_brasil:
            estudo_brasil = match_protocolo_brasil.group(0)

        # --- TE do estudo: tenta achar impresso na NEWSE; senão usa a planilha ---
        te_brasil = "NÃO ENCONTRADO"
        match_te_brasil = re.search(r"\bTE\s*(\d{3,5})\b", texto_brasil_upper)
        if match_te_brasil:
            te_brasil = f"TE{match_te_brasil.group(1)}"
        elif df_te is not None:
            for idx, row in df_te.iterrows():
                if estudo_brasil != "NÃO IDENTIFICADO" and estudo_brasil in str(row['Estudo']).upper():
                    te_brasil = str(row['TE']).strip(); break

        # --- Centro / instituição de destino (apenas para exibição) ---
        centro_brasil = "NÃO IDENTIFICADO"
        match_centro_brasil = re.search(
            r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\s*-\s*([A-ZÀ-Ú\s]+?)\s*\d{2}\.\d{3}\.\d{3}",
            texto_brasil_upper
        )
        if match_centro_brasil:
            centro_brasil = match_centro_brasil.group(1).strip()

        # --- Faixa de temperatura (decide Tag Alert Ambiente x Refrigerado) ---
        tem_ref_brasil, tem_amb_brasil = detectar_faixas_newse(texto_brasil_upper)

        # --- DEPOSITANTE (CNPJ): lido da NEWSE, com 0 na frente como na Automação ---
        m_dep_brasil = re.search(r"DEPOSITANTE\s*:?\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", texto_brasil_upper)
        val_depositante_brasil = ("0" + re.sub(r"\D", "", m_dep_brasil.group(1))) if m_dep_brasil else "056998982001260"

        st.success("✅ NEWSE processada com sucesso.")
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(card_metrica("Centro / Instituição", centro_brasil), unsafe_allow_html=True)
        with c2: st.markdown(card_metrica("Protocolo / Estudo", estudo_brasil), unsafe_allow_html=True)
        with c3: st.markdown(card_metrica("TE Correspondente", te_brasil), unsafe_allow_html=True)
        st.write("")
        linha_copia("DEPOSITANTE", val_depositante_brasil, altura=50)

        # Identidade estável deste upload (evita duplicar a retirada no rerun).
        arquivo_id_brasil = getattr(arquivo_newse_brasil, "file_id", None) or f"{arquivo_newse_brasil.name}_{arquivo_newse_brasil.size}"

        # --- Categoria (decide se há retirada de Tag Alert) ---
        st.markdown("### 🗂️ Categoria da solicitação")
        categoria_brasil = st.radio(
            "Categoria da solicitação", [CATEGORIA_MEDICACAO, CATEGORIA_SUPRIMENTO],
            index=None, horizontal=True,
            key=f"brasil_categoria_{arquivo_id_brasil}", label_visibility="collapsed",
        )

        if categoria_brasil is None:
            st.session_state.alocacao_pendente = False
            st.info("Escolha a categoria (Medicação ou Equipamento / Suprimento) para continuar.")

        elif categoria_brasil == CATEGORIA_SUPRIMENTO:
            # Equipamento / Suprimento não usa Tag Alert: nada é retirado do estoque.
            st.session_state.alocacao_pendente = False
            components.html("<script>window.parent.onbeforeunload = null;</script>", height=0)
            st.info("📦 Equipamento / Suprimento não utiliza Tag Alert — nenhuma retirada de estoque será feita.")

        else:
            st.markdown("### 🏷️ Retirada de Tag Alert")

            if not tem_ref_brasil and not tem_amb_brasil:
                st.warning("⚠️ Não foi possível identificar a faixa de temperatura (Ambiente/Refrigerado) nesta NEWSE. Verifique o documento manualmente.")

            registro_existente_brasil = st.session_state.solicitacoes_brasil_registradas.get(arquivo_id_brasil)

            if registro_existente_brasil:
                st.session_state.alocacao_pendente = False
                itens_brasil = registro_existente_brasil["itens"]
                st.success(f"✅ Retirada já registrada para esta NEWSE em {registro_existente_brasil['data_uso']}.")
                for p in itens_brasil:
                    st.markdown(f"- **{p['label']}** ➔ Palete: {p['palete']} | ID: {p['id_est']} | Série: {p['serie']}")
                st.caption("Para registrar uma nova solicitação, envie um novo arquivo PDF acima.")
            else:
                itens_brasil = []

                if df_estoque is not None and not df_estoque.empty:
                    df_estoque_temp_brasil = df_estoque.copy()

                    def allocate_logger_brasil(nome_busca, label):
                        filtro = df_estoque_temp_brasil[
                            df_estoque_temp_brasil['Descricao_Clean'].str.contains(nome_busca, na=False)
                        ]
                        if not filtro.empty:
                            item = filtro.iloc[0]
                            df_estoque_temp_brasil.drop(item.name, inplace=True)
                            serie = next((str(item[c]) for c in item.index if "SERIE" in c.upper() or "SÉRIE" in c.upper()), str(item.iloc[7]) if len(item) > 7 else "N/A")
                            itens_brasil.append({
                                "label": label,
                                "palete": str(item.get('Palete', 'N/A')).strip(),
                                "id_est": str(item.get('Identificacao Estoque', 'N/A')).strip(),
                                "serie": serie
                            })
                            st.info(f"**{label}** alocado ➔ Palete: {item.get('Palete', 'N/A')} | ID: {item.get('Identificacao Estoque', 'N/A')} | Série: {serie}")
                        else:
                            st.warning(f"⚠️ **{label}**: Sem saldo disponível no estoque!")

                    # Só Tag Alert — solicitações Brasil não usam TempTale.
                    # Um Tag Alert por faixa de temperatura detectada.
                    if tem_amb_brasil:
                        allocate_logger_brasil("TAGALERT 15-25", "Tag Alert Ambiente")
                    if tem_ref_brasil:
                        allocate_logger_brasil("TAGALERT 2-8", "Tag Alert Refrigerado")

                    st.session_state.alocacao_pendente = bool(itens_brasil)

                    if itens_brasil:
                        st.markdown(
                            "<div class='drs-alerta-pendente'>⚠️ Retirada pendente de confirmação — clique em "
                            "<b>Gravar Solicitação Brasil</b> antes de sair desta página, "
                            "ou os itens acima podem ser usados por outra pessoa.</div>",
                            unsafe_allow_html=True
                        )
                        components.html(
                            "<script>window.parent.onbeforeunload = function(e){ e.preventDefault(); e.returnValue = ''; return ''; };</script>",
                            height=0
                        )
                    else:
                        components.html("<script>window.parent.onbeforeunload = null;</script>", height=0)

                    col_id_brasil, col_btn_brasil = st.columns([2, 1])
                    with col_id_brasil:
                        # Campo travado de propósito: solicitações Brasil não têm DEL#.
                        st.text_input("Identificador para registro:", value="Solicitação Brasil", disabled=True)
                    with col_btn_brasil:
                        st.write("")
                        if st.button("💾 Gravar Solicitação Brasil", use_container_width=True, disabled=not itens_brasil):
                            webhook_url = st.secrets.get(
                                "WEBHOOK_BAIXA_ESTOQUE",
                                "https://script.google.com/macros/s/AKfycbzpwZC2LW7PQ1JGMkJIZD3Rxd4nv4pfEZ1QS1D9jDxQbt4Qf2hiCmv9dJ8pAJnBHJglug/exec"
                            )

                            payload = {
                                "data_uso": datetime.today().strftime('%d/%m/%Y'),
                                "delivery_number": "Solicitação Brasil",
                                "estudo": estudo_brasil,
                                "te": te_brasil,
                                "cidade_destino": centro_brasil,
                                "itens": [
                                    {
                                        "tipo": p["label"],
                                        "palete": p["palete"],
                                        "id_est": p["id_est"],
                                        "serie": p["serie"]
                                    } for p in itens_brasil
                                ]
                            }

                            try:
                                req = urllib.request.Request(
                                    webhook_url,
                                    data=json.dumps(payload).encode('utf-8'),
                                    headers={'Content-Type': 'application/json'}
                                )
                                resposta_bruta = urllib.request.urlopen(req, timeout=25).read().decode("utf-8")
                                try:
                                    resposta = json.loads(resposta_bruta)
                                except ValueError:
                                    resposta = {}

                                if resposta.get("result") != "success":
                                    raise RuntimeError(
                                        resposta.get("message", f"Resposta inesperada do servidor: {resposta_bruta[:300]}")
                                    )

                                for p in itens_brasil:
                                    st.session_state.seriais_consumidos.add(str(p["serie"]).strip())
                                    st.session_state.ids_consumidos.add(str(p["id_est"]).strip())

                                st.session_state.solicitacoes_brasil_registradas[arquivo_id_brasil] = {
                                    "itens": itens_brasil,
                                    "data_uso": datetime.today().strftime('%d/%m/%Y %H:%M'),
                                }
                                st.session_state.alocacao_pendente = False
                                st.session_state.brasil_uploader_key += 1

                                st.cache_data.clear()
                                itens_txt_brasil = ", ".join([p["label"] for p in itens_brasil])
                                st.success(f"✅ Retirada registrada com sucesso para: {itens_txt_brasil}.")
                                time.sleep(2)
                                st.rerun()
                            except Exception as ex:
                                st.error(f"Erro ao atualizar planilha: {ex}")
                else:
                    st.warning("⚠️ Estoque indisponível no momento — não é possível alocar Tag Alert automaticamente.")

        # --- CHECKLIST DE PARTICULARIDADES (depois de escolher a categoria) ---
        if categoria_brasil is not None:
            st.markdown("### ✅ Checklist de Particularidades — BMS Brasil")
            renderizar_checklist_brasil(
                texto_brasil_upper, arquivo_id_brasil, tem_ref_brasil, tem_amb_brasil, categoria_brasil,
            )

# ==========================================
# PÁGINA: GERADOR DE E-MAIL (GR)
# ==========================================
elif st.session_state.pagina_atual == "email":

    banner(
        "📧 Gerador de E-mail (GR)",
        "Preencha os dados do recebimento para montar o e-mail de Goods Receipt (GR) e copie o assunto, "
        "os destinatários e o corpo já formatados.",
    )

    if "email_uploader_key" not in st.session_state:
        st.session_state.email_uploader_key = 0
    if "email_dados_extraidos" not in st.session_state:
        st.session_state.email_dados_extraidos = None

    col_email_up, col_email_limpar = st.columns([3, 1])
    with col_email_up:
        pdf_gr = st.file_uploader(
            "📎 Envie a Packing List (PDF) para preencher automaticamente Delivery, Protocol, Order e os itens abaixo",
            type=["pdf"],
            key=f"email_pdf_{st.session_state.email_uploader_key}",
        )
    with col_email_limpar:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button("🗑️ Limpar PDF", key="email_limpar_btn", use_container_width=True):
            st.session_state.email_uploader_key += 1
            st.session_state.email_dados_extraidos = None
            st.rerun()

    if pdf_gr is not None and st.session_state.email_dados_extraidos is None:
        with st.spinner("🔎 Lendo a Packing List (pode levar alguns segundos se for um PDF escaneado)..."):
            st.session_state.email_dados_extraidos = extrair_dados_packing_para_email(pdf_gr)

    dados_gr = st.session_state.email_dados_extraidos
    if dados_gr:
        qtd_itens = len(dados_gr["itens"])
        if dados_gr["delivery"] or dados_gr["protocolo"] or dados_gr["order"] or qtd_itens:
            st.success(
                f"✅ PDF lido — Delivery **{dados_gr['delivery'] or '—'}**, Protocol **{dados_gr['protocolo'] or '—'}**, "
                f"Order **{dados_gr['order'] or '—'}**, {qtd_itens} item(ns) encontrado(s). "
                f"**Confira os campos abaixo antes de gerar o e-mail** — a leitura de PDF escaneado ocasionalmente erra um dígito. "
                f"Brazilian Invoice e CESV continuam manuais."
            )
        else:
            st.warning("⚠️ Não consegui identificar os campos automaticamente neste PDF — preencha manualmente abaixo.")
    else:
        st.caption("Nenhum PDF lido ainda — os campos abaixo podem ser preenchidos manualmente, como hoje.")

    components.html(montar_html_gerador(dados_gr), height=1450, scrolling=True)

# ==========================================
# PÁGINA: TABELA DE PROGRAMAÇÃO DE COLETA E ENTREGA (BMS / IQVIA)
# ==========================================
elif st.session_state.pagina_atual == "tabela_programacao":

    banner(
        "🗓️ Tabela de Coleta e Entrega",
        "Preencha a programação de <b>BMS</b> ou <b>IQVIA</b> direto na tabela, clique em <b>Copiar tabela</b> e "
        "cole no e-mail (Ctrl+V): o visual vai igual ao que está na tela. O que você digita fica salvo neste navegador.",
    )

    components.html(html_tabela_programacao(), height=1150, scrolling=True)
