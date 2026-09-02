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
import unicodedata


def extrair_texto_pdf(leitor, separador=""):
    """Extrai o texto de todas as páginas de um PDF.
    Ignora páginas sem texto extraível (ex: PDFs escaneados/imagem),
    o que evita que o app quebre com um upload inesperado."""
    return separador.join([(pagina.extract_text() or "") for pagina in leitor.pages])


def remover_acentos(texto):
    """Remove acentos (ex: 'FUNDAÇÃO' -> 'FUNDACAO') para comparar textos
    vindos de sistemas diferentes que nem sempre extraem acentuação da
    mesma forma."""
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def detectar_faixas_tagalert(texto_upper):
    """Procura no Packing List cada faixa de temperatura (ex: "TEMP 2-8 C",
    "TEMP 2-25 C", "TEMP 15-25 C") e verifica se ela está associada a um item
    com TAGALERT por perto. Classifica pelo limite superior da faixa:
    até 8°C = Refrigerado, acima disso = Ambiente.

    Isso é mais robusto do que checar por um texto fixo tipo "15-25" ou
    "2-30C", porque cada Packing List pode escrever a faixa de um jeito
    diferente (2-25, 20-25, 15-30, com ou sem espaço antes do "C" etc)."""
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
    """Igual à detectar_faixas_tagalert, mas para o texto da NEWSE (solicitação),
    que escreve a faixa de temperatura em português — "2 A 8ºC", "15 A 25ºC" —
    em vez do formato "TEMP 2-8 C" do Packing List em inglês. Não depende de
    nenhuma palavra tipo "TAGALERT" por perto, porque a NEWSE não indica o
    dispositivo — só a faixa de temperatura de cada item."""
    tem_ref = False
    tem_amb = False
    # Sem \b depois do "C": na NEWSE, a Quantidade às vezes vem colada direto
    # depois da temperatura sem espaço (ex: "2 A 8ºC12"), e exigir um limite
    # de palavra ali fazia a expressão nunca casar nesse formato.
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*A\s*(\d+(?:[.,]\d+)?)\s*[°º]?C", texto_upper):
        limite_superior = float(m.group(2).replace(",", "."))
        if limite_superior <= 8:
            tem_ref = True
        else:
            tem_amb = True
    return tem_ref, tem_amb


# --- Reconhecimento de medicações citotóxicas (para agrupamento de loggers) ---
# Usada para decidir, ITEM A ITEM, se ele precisa de caixa/logger separado.
# Tem lookahead negativo em PACLITAXEL para não confundir com PACLITAXEL NAB
# / PACLITAXELNAB (nab-paclitaxel/Abraxane): em Packing Lists reais, quando
# o item de nab-paclitaxel não vem com a palavra "Cytotoxic" no próprio
# campo de Storage, ele não teve que dividir caixa/logger com os demais
# itens citotóxicos (validado com documento real — teria feito o sistema
# voltar a contar errado a quantidade de TempTale). Isso é independente de
# precisar ou não da ficha de segurança — ver FICHAS_SEGURANCA mais abaixo,
# que trata PACLITAXEL NAB como precisando da mesma ficha do Paclitaxel.
CITOTOXICOS_REGEX = re.compile(r"BORTEZOMIB|SPRYCEL|DASATINIB|PACLITAXEL(?!\s*NAB)|TAXOL|CYCLOPHOSPHAMIDE|CICLOFOSFAMIDA")
# Além da lista de nomes conhecidos acima, muitas Packing Lists já trazem a
# palavra "Cytotoxic" (ou "Citotóxico") escrita no próprio campo de Storage
# do item — inclusive para medicações que não estão na nossa lista de nomes
# (ex: Cisplatin, Pemetrexed, Carboplatin). Esse sinal do próprio documento
# é o mais confiável para decidir "esse item específico precisa de caixa
# separada", então ele é combinado com a lista de nomes.
CITOTOXICO_TEXTO_REGEX = re.compile(r"CYTOTOXIC|CITOT[ÓO]XIC")

# Linha "Material  Batch   Quantidade EA  Data" que aparece uma vez para
# cada item de uma Packing List (ex: "8 EA 30-JUN-2027"). É o ponto mais
# estável do layout para dividir o texto em blocos, um por item.
ITEM_ANCHOR_REGEX = re.compile(r"\d+\s*EA\s+\d{1,2}-[A-Z]{3}-\d{4}")


def normalizar_faixa_temperatura(bloco_upper):
    """Extrai e normaliza a faixa/limite de temperatura de UM item (bloco de
    texto entre o início desse item e o início do próximo), para poder
    comparar se dois itens compartilham a mesma faixa (e por isso podem
    dividir a mesma caixa/logger)."""
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
    None = não foi possível determinar (tratado como ambiente por segurança
    operacional, já que é a faixa mais comum)."""
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
    """Divide o texto do Packing List em blocos por item (usando a linha
    Material/Batch/Quantidade/Data como âncora) e extrai, para cada item,
    qual dispositivo ele precisa (TempTale ou Tag Alert), se é uma
    medicação citotóxica e a faixa de temperatura normalizada.

    Isso substitui a lógica antiga, que só enxergava "o documento inteiro
    tem a palavra X" e por isso nunca conseguia contar corretamente quantos
    loggers eram realmente necessários quando havia vários itens com faixas
    de temperatura diferentes, ou vários itens citotóxicos que precisam
    cada um da sua própria caixa separada."""
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
            continue  # item sem exigência de logger (ex: linha de confirmação)

        itens.append({
            "dispositivo": dispositivo,
            "citotoxico": item_e_citotoxico(bloco),
            "faixa": normalizar_faixa_temperatura(bloco),
        })
    return itens


def agrupar_loggers_necessarios(itens):
    """A partir da lista de itens (ver analisar_itens_packing), decide quantos
    loggers de cada tipo são realmente necessários:

    - Itens do MESMO dispositivo, com a MESMA faixa de temperatura e o MESMO
      status de citotóxico podem compartilhar uma caixa e, portanto, 1 logger.
    - Itens citotóxicos NUNCA dividem caixa/logger com itens não citotóxicos
      (regra de caixa separada), mesmo que a faixa de temperatura seja igual.

    Retorna (qtd_temptale, qtd_tagalert_ambiente, qtd_tagalert_refrigerado,
    tem_algum_citotoxico)."""
    grupos_temptale = set()
    grupos_tagalert = set()  # chave: (citotoxico, "AMB"/"REF")
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


# --- Fichas de segurança obrigatórias para medicações citotóxicas ---
# Cada entrada: (regex de reconhecimento, caminho do PDF, rótulo amigável).
# Só existe ficha própria para essas 4 medicações — outras que o documento
# marque como "Cytotoxic" (ex: Cisplatin, Carboplatin) entram na regra de
# caixa separada/logger, mas não têm ficha própria cadastrada aqui.
FICHAS_SEGURANCA = [
    (re.compile(r"BORTEZOMIB"), "fichas_seguranca/ficha_bortezomib.pdf", "Bortezomib (Velcade)"),
    (re.compile(r"SPRYCEL|DASATINIB"), "fichas_seguranca/ficha_sprycel_dasatinib.pdf", "Sprycel / Dasatinib"),
    (re.compile(r"PACLITAXEL|TAXOL"), "fichas_seguranca/ficha_taxol_paclitaxel.pdf", "Taxol / Paclitaxel"),
    (re.compile(r"CYCLOPHOSPHAMIDE|CICLOFOSFAMIDA"), "fichas_seguranca/ficha_ciclofosfamida.pdf", "Cyclophosphamide / Ciclofosfamida"),
]


# --- CONFIGURAÇÕES DA PÁGINA (SaaS Logístico - Wide) ---
st.set_page_config(page_title="DRS Group | BMS Operations", layout="wide", page_icon="🏢")

# --- INJEÇÃO DE CSS (Identidade Visual DRS Group) ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    :root {
        --drs-verde-escuro: #12302c;
        --drs-verde: #1b3834;
        --drs-teal: #209b7c;
        --drs-laranja: #e59235;
        --drs-fundo: #eef3f2;
        --drs-borda: #dde6e3;
        --drs-texto-2: #64748b;
    }

    html, body, [class*="css"], .stApp {
        font-family: 'Inter', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif !important;
    }

    .stApp {
        background: radial-gradient(circle at top left, #f6faf9 0%, var(--drs-fundo) 55%);
    }

    header[data-testid="stHeader"] { background: rgba(0,0,0,0); }

    h1, h2, h3, h4, h5, h6 {
        color: var(--drs-verde) !important;
        font-weight: 700;
        margin-bottom: 0.3rem;
    }
    h2 { font-size: 19px !important; letter-spacing: -0.2px; }
    h3 { font-size: 13px !important; text-transform: uppercase; letter-spacing: 0.6px; color: var(--drs-texto-2) !important; font-weight: 700 !important; }
    h4 { font-size: 12px !important; }

    /* Botões padrão (fora da sidebar) */
    .stButton>button {
        background-color: var(--drs-teal) !important;
        color: white !important;
        border-radius: 7px;
        border: 1px solid var(--drs-teal) !important;
        font-size: 13px !important;
        font-weight: 600;
        padding: 0.45rem 1rem;
        transition: 0.15s ease-in-out;
        box-shadow: 0 1px 4px rgba(18,48,44,0.18);
    }
    .stButton>button:hover {
        background-color: var(--drs-verde-escuro) !important;
        border-color: var(--drs-verde-escuro) !important;
        color: var(--drs-laranja) !important;
    }
    .stButton>button:disabled {
        background-color: #e8ecec !important;
        border-color: #e0e6ed !important;
        color: #a3adae !important;
        box-shadow: none !important;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #ffffff 0%, #f6faf9 100%);
        border-right: 1px solid var(--drs-borda);
        padding-top: 1rem;
    }
    [data-testid="stSidebar"] .stButton>button {
        background: transparent !important;
        color: var(--drs-verde) !important;
        border: 1px solid transparent !important;
        box-shadow: none !important;
        text-align: left !important;
        justify-content: flex-start !important;
        font-weight: 600 !important;
        width: 100%;
    }
    [data-testid="stSidebar"] .stButton>button:hover {
        background: #e7f5f0 !important;
        color: var(--drs-teal) !important;
    }
    [data-testid="stSidebar"] .stButton>button[kind="primary"],
    [data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
        background: var(--drs-verde) !important;
        color: #ffffff !important;
        border: 1px solid var(--drs-verde) !important;
        box-shadow: 0 2px 6px rgba(27,56,52,0.28) !important;
    }
    [data-testid="stSidebar"] .stButton>button[kind="primary"]:hover,
    [data-testid="stSidebar"] button[data-testid="stBaseButton-primary"]:hover {
        color: var(--drs-laranja) !important;
    }

    /* Cartões / blocos aninhados */
    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"] {
        background-color: #ffffff;
        padding: 12px;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(18,48,44,0.06);
        border: 1px solid var(--drs-borda);
    }

    [data-testid="stFileUploaderDropzone"] {
        border-radius: 10px !important;
        border: 1.5px dashed #b7c9c4 !important;
        background-color: #fafcfb !important;
    }

    .dataframe { font-size: 12px !important; }

    /* Aviso fixo de pendência (não deixa passar despercebido) */
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
        box-shadow: 0 2px 8px rgba(229,146,53,0.18);
    }
    </style>
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
    """Renderiza a tela de login (fundo em degradê DRS + cartão central com
    logo, título e o campo de senha). Tudo fica DENTRO de um único
    st.container(), para o cartão realmente envolver o campo de senha no
    HTML final (dividir isso em vários st.markdown soltos não funciona no
    Streamlit — cada st.markdown é um fragmento de HTML independente, uma
    tag aberta ali não continua "aberta" no próximo elemento)."""
    st.markdown("""
        <style>
        /* Fundo cheio em degradê verde DRS, só nesta tela (login) */
        .stApp { background: linear-gradient(160deg, #10281f 0%, #1b3834 45%, #12302c 100%) !important; }
        [data-testid="stSidebar"] { display: none !important; }
        header[data-testid="stHeader"] { background: rgba(0,0,0,0) !important; }

        .drs-login-topo {
            height: 6px; margin: -12px -12px 22px -12px;
            background: linear-gradient(90deg, var(--drs-teal), var(--drs-laranja));
            border-radius: 10px 10px 0 0;
        }
        .drs-login-badge {
            width: 56px; height: 56px; margin: 0 auto 16px auto;
            border-radius: 14px;
            background: linear-gradient(135deg, var(--drs-verde) 0%, var(--drs-verde-escuro) 100%);
            display: flex; align-items: center; justify-content: center;
            font-family: 'Inter', sans-serif; font-weight: 800; font-size: 18px; color: #ffffff;
            letter-spacing: 0.5px;
            box-shadow: 0 8px 20px rgba(18,48,44,0.35);
        }
        .drs-login-title {
            text-align: center; font-family: 'Inter', sans-serif; font-weight: 800 !important;
            font-size: 22px !important; color: var(--drs-verde) !important;
            letter-spacing: 0.4px; margin: 0 !important;
        }
        .drs-login-subtitle {
            text-align: center; font-family: 'Inter', sans-serif; font-weight: 700; font-size: 12px;
            color: var(--drs-laranja); text-transform: uppercase; letter-spacing: 1.2px;
            margin: 6px 0 18px 0;
        }
        .drs-login-desc {
            text-align: center; font-size: 13px; color: var(--drs-texto-2); line-height: 1.5; margin-bottom: 6px;
        }
        .drs-login-footer {
            font-size: 11px; color: #a9b3b1; text-align: center; margin-top: 16px;
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
                    estoque e conferência documental.<br>Acesso restrito à equipe autorizada.</p>
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
    # gid fixo (aba "ESTOQUE" confirmada com o usuário) em vez de depender de
    # qual aba está posicionada primeiro na planilha — evita que a leitura
    # "pule" para outra aba se alguém reordenar ou criar uma aba nova antes dela.
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
            # Nome de coluna mudou na planilha (ex: "Descricao" -> "Descrição"):
            # evita derrubar o app inteiro para todo mundo, só desativa o estoque.
            df_est = None

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
        <div style='text-align: left; padding: 4px 0 10px 0; border-bottom: 1px solid #dde6e3; margin-bottom: 14px;'>
            <h1 style='color: #1b3834; font-size: 32px; line-height: 0.9; margin: 0; font-family: "Inter", Arial, sans-serif; font-weight: 800; letter-spacing: -1px;'>DRS <span style="color:#209b7c;">GROUP</span></h1>
            <p style="margin: 4px 0 0 0; font-size: 10px; color: #94a3ab; font-weight: 700; letter-spacing: 1.5px;">BMS OPERATIONS</p>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("""
        <div style="display: flex; align-items: center; margin-bottom: 2px;">
            <div style="width: 8px; height: 8px; border-radius: 50%; background-color: #28a745; margin-right: 6px; box-shadow: 0 0 4px #28a745;"></div>
            <h3 style="margin: 0; font-size: 11px; color: #1b3834;">Painel de Operações</h3>
        </div>
        <p style="font-size: 10px; color: #28a745; margin-top: 0px; margin-left: 14px; font-weight: bold; margin-bottom: 14px;">Sistema Apto para Uso</p>
    """, unsafe_allow_html=True)

    st.markdown("<p style='font-size: 10px; color: #94a3ab; font-weight: 700; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.6px;'>Navegação</p>", unsafe_allow_html=True)

    bloqueado = st.session_state.alocacao_pendente
    paginas_menu = [
        ("automacao", "📦  Automação de Packing List"),
        ("cruzamento", "⚖️  Cruzamento NEWSE x PACKING"),
        ("conferencia_agendamento", "🧾  Conferência de Agendamento"),
        ("bms_brasil", "🇧🇷  BMS Brasil - Solicitações"),
        ("email", "📧  Gerador de E-mail (GR)"),
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
        <div style="font-size: 11px; color: #4a5568; margin-top: 5px; margin-bottom: 5px; line-height: 1.6; background-color: #ffffff; padding: 12px 14px; border-radius: 10px; border: 1px solid #dde6e3; border-left: 4px solid #e59235; box-shadow: 0 2px 8px rgba(18,48,44,0.05);">
            <b style="font-size: 10px; color: #1b3834; letter-spacing: 0.4px;">LOGGERS DISPONÍVEIS</b><br>
            <div style="display:flex; justify-content:space-between; margin-top:6px;"><span>Tag Alert Ambiente</span><b style="color: #209b7c;">{raw_ta_amb}</b></div>
            <div style="display:flex; justify-content:space-between;"><span>Tag Alert Refrigerado</span><b style="color: #209b7c;">{raw_ta_ref}</b></div>
            <div style="display:flex; justify-content:space-between;"><span>TempTale Ambiente</span><b style="color: #209b7c;">{raw_tt}</b></div>
        </div>
    """, unsafe_allow_html=True)

def card_metrica(titulo, valor):
    return f"""
    <div style="background-color: #ffffff; padding: 14px 16px; border-radius: 10px; border: 1px solid #dde6e3; border-top: 3px solid #209b7c; box-shadow: 0 2px 8px rgba(18,48,44,0.05);">
        <p style="margin: 0; font-size: 10px; color: #94a3ab; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">{titulo}</p>
        <p style="margin: 5px 0 0 0; font-size: 17px; color: #1b3834; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{valor}">{valor}</p>
    </div>
    """

# ==========================================
# ROTEADOR DE PÁGINAS 
# ==========================================

if st.session_state.pagina_atual == "automacao":
    
    st.markdown("""
        <div style="background: linear-gradient(135deg, #1b3834 0%, #10281f 100%); padding: 20px 26px; border-radius: 12px; border-left: 6px solid #209b7c; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #ffffff !important; margin: 0 0 6px 0; font-size: 18px;">📦 Automação de Packing List (SLA e Estoque)</h2>
            <p style="color: #cbd5e1; margin: 0; font-size: 13px; line-height: 1.4;">
                Faça o upload do <b>Packing List (PDF)</b> para extração imediata de dados. O sistema realiza a sugestão automática de <b>ativos logísticos</b>,<br> cálculo exato do <b>SLA de entrega</b> (considerando dias úteis) e a <b>baixa de estoque ao vivo na planilha</b>.
            </p>
        </div>
    """, unsafe_allow_html=True)

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
        # Sem PDF anexado nesta tela: nada foi de fato retirado do estoque
        # (isso só acontece depois que "Executar Baixa" confirma sucesso), então
        # não há motivo para manter a navegação travada. Isso permite cancelar
        # uma alocação pendente simplesmente removendo o arquivo (clicando no
        # "x" do upload), em vez de ficar preso até preencher um DEL#.
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
        # Divide a Packing List em blocos, um por item, e agrupa por (dispositivo,
        # citotóxico, faixa de temperatura) — ver analisar_itens_packing/
        # agrupar_loggers_necessarios no topo do arquivo. Isso substitui a lógica
        # antiga que só olhava "o documento tem essa palavra em algum lugar" e por
        # isso não conseguia contar corretamente quantos loggers eram necessários
        # quando havia mais de um item com faixas de temperatura diferentes.
        itens_detectados = analisar_itens_packing(texto_upper)

        if itens_detectados:
            qtd_temptale, qtd_tagalert_amb, qtd_tagalert_ref, tem_citotoxico = agrupar_loggers_necessarios(itens_detectados)
        else:
            # Formato de documento não reconhecido pelo separador de itens —
            # usa o modelo antigo (menos preciso, mas já validado) como rede
            # de segurança em vez de não alocar nenhum logger.
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

        # Identidade estável deste upload — usada para lembrar se a baixa
        # já foi registrada para ESTE arquivo específico (evita duplicar
        # a alocação/baixa se a página recarregar com o mesmo PDF ainda anexado).
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

                # Aloca exatamente a quantidade de cada logger que os itens desta
                # Packing List realmente precisam (ver análise por item acima) —
                # itens citotóxicos com faixa/dispositivo diferentes dos demais já
                # entram como grupos separados, então não é somado nenhum "extra"
                # à parte: o próprio agrupamento já reflete a regra de caixa
                # separada para citotóxicos.
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

                # Enquanto houver itens alocados e a baixa ainda não foi confirmada,
                # trava a navegação para outras páginas (ver barra lateral).
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

                                # O Apps Script sempre responde com HTTP 200, mesmo quando ele
                                # mesmo capturou um erro internamente (planilha/aba não encontrada,
                                # item não localizado etc). Por isso não basta a chamada não ter
                                # "explodido" — é preciso checar o campo "result" que o script devolve
                                # para não mostrar "sucesso" quando na verdade nada foi gravado.
                                if resposta.get("result") != "success":
                                    raise RuntimeError(
                                        resposta.get("message", f"Resposta inesperada do servidor: {resposta_bruta[:300]}")
                                    )

                                # Só marca os itens como consumidos (some da visão de todo mundo)
                                # e só trava o arquivo como "já processado" DEPOIS de confirmar
                                # que a planilha central foi atualizada com sucesso.
                                for p in ids_utilizados:
                                    st.session_state.seriais_consumidos.add(str(p["serie"]).strip())
                                    st.session_state.ids_consumidos.add(str(p["id_est"]).strip())

                                st.session_state.baixas_registradas[arquivo_id] = {
                                    "delivery_number": delivery_number,
                                    "itens": ids_utilizados,
                                    "data_uso": datetime.today().strftime('%d/%m/%Y %H:%M'),
                                }
                                st.session_state.alocacao_pendente = False

                                # Troca a "key" do uploader para a próxima renderização —
                                # isso faz o Streamlit tratá-lo como um campo novo/vazio,
                                # limpando o PDF anexado automaticamente (sem precisar de F5).
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
        
        def btn_copia(rotulo, valor, uid):
            html = f"""<div style="display:flex; justify-content:space-between; align-items: center; padding:6px 12px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:4px; margin-bottom:5px;">
            <div><span style="color:#475569; font-weight:bold; font-size:11px;">{rotulo}:</span> <span style="font-family:monospace; color:#209b7c; font-size:13px; font-weight:bold; margin-left:5px;">{valor}</span></div>
            <button onclick="navigator.clipboard.writeText('{valor}'); this.innerText='Copiado!'; setTimeout(()=>this.innerText='Copiar', 2000)" style="background:#209b7c; color:white; border:none; border-radius:3px; cursor:pointer; font-size:11px; padding:4px 10px; font-weight:bold;">Copiar</button></div>"""
            components.html(html, height=45)
            
        c_esq, c_dir = st.columns(2)
        with c_esq: btn_copia("DEPOSITANTE", val_depositante, "d"); btn_copia("PALETE", val_palete, "p")
        with c_dir: btn_copia("ID ITEM", val_id, "i"); btn_copia("TE DO ESTUDO", val_te, "t")

        # --- CONSTRUÇÃO DAS PARTICULARIDADES COM REGRAS DE CITOTÓXICOS ---
        paragrafos = [
            "Verificar se no processo consta Packing List e atentar se a quantidade, lote e validade está de acordo com as informações retiradas do sistema LOGIX."
        ]
        
        if tem_temptale: 
            paragrafos.extend([
                "Houve envio de medicação AMBIENTE.", 
                "As medicações foram acondicionadas em embalagem apropriada CREDO validada pelo cliente com TempTale ULTRA USB ambiente conforme solicitado pelo cliente."
            ])
        if tem_tagalert_amb: 
            paragrafos.extend([
                "Houve envio de medicação AMBIENTE.", 
                "As medicações foram acondicionadas em embalagem CREDO com Tag Alert ambiente conforme solicitado pelo cliente."
            ])
        if tem_tagalert_ref: 
            paragrafos.extend([
                "Houve envio de medicação REFRIGERADA.", 
                "As medicações foram acondicionadas em embalagem apropriada caixa CREDO SÉRIE 04 com Tag Alert refrigerado conforme solicitado pelo cliente."
            ])
            
        paragrafos.append("Time DOC: Não aplicar o desconto padrão de 1 hora na SC de Envio caso o centro já tenha reduzido o período no agendamento.")
        
        # Detecção e adição das regras específicas de Citotóxicos
        if "BORTEZOMIB" in texto_upper:
            paragrafos.extend([
                "As caixas foram devidamente identificadas com a Etiqueta “Excepted Quantity Nº 6.1” quando houver o envio de “BORTEZOMIB”",
                "Para envios da medicação BORTEZOMIB, será anexado ficha de segurança do produto.",
                "Para envios da medicação BORTEZOMIB, deverá ser encaminhado em caixa separada quando houver envio de mais medicações.",
                "As medicações foram acondicionadas em embalagem apropriada CREDO validada pelo cliente com TempTale ULTRA USB ambiente conforme solicitado pelo cliente.",
                "A etiqueta do Logger USB deve ir colada na Packing List de envio.",
                "Produtos com temperaturas diferentes seguirão em caixas separadas quando houver a necessidade de TT4."
            ])

        if "SPRYCEL" in texto_upper or "DASATINIB" in texto_upper:
            paragrafos.extend([
                "As medicações foram acondicionadas em embalagem apropriada CREDO 28L validada pelo cliente com Tag Alert ambiente conforme solicitado pelo cliente.",
                "No caso de medicações comerciais, as medicações estão devidamente etiquetadas com a etiqueta de venda proibida.",
                "Para envios da medicação DASATINIB ou SPRYCEL, será anexado ficha de segurança do produto.",
                "Para envios da medicação DASATINIB ou SPRYCEL, deverá ser encaminhado em caixa separada quando houver envio de mais medicações.",
                "As caixas foram devidamente identificadas com a Etiqueta “Excepted Quantity Nº 6.1” quando houver o envio de “DASATINIB OU SPRYCEL."
            ])

        if re.search(r"PACLITAXEL|TAXOL", texto_upper):
            paragrafos.extend([
                "As medicações foram acondicionadas em embalagem apropriada CREDO 28L validada pelo cliente com Tag Alert ambiente conforme solicitado pelo cliente.",
                "O formulário de requisição dos produtos comerciais, deverá ser enviado para a Instituição de destino.",
                "No caso de medicações comerciais, as medicações estão devidamente etiquetadas com a etiqueta de venda proibida.",
                "As caixas foram devidamente identificadas com a Etiqueta “Excepted Quantity Nº 3” quando houver o envio de “TAXOL OU PACLITAXEL”",
                "Para envios da medicação PACLITAXEL ou TAXOL, será anexado ficha de segurança do produto.",
                "Para envios da medicação PACLITAXEL ou TAXOL, deverá ser encaminhado em caixa separada quando houver envio de mais medicações."
            ])

        if "CYCLOPHOSPHAMIDE" in texto_upper or "CICLOFOSFAMIDA" in texto_upper:
            paragrafos.extend([
                "As medicações foram acondicionadas em embalagem apropriada CREDO 28L com Tag Alert ambiente conforme solicitado pelo cliente.",
                "As caixas foram devidamente identificadas com a Etiqueta “Excepted Quantity Nº 6.1” quando houver o envio de “CICLOFOSFAMIDA”",
                "Para envios da medicação CICLOFOSFAMIDA, será anexado ficha de segurança do produto.",
                "Para envios da medicação CICLOFOSFAMIDA, deverá ser encaminhado em caixa separada quando houver envio de mais medicações.",
                "As medicações foram acondicionadas em embalagem apropriada CREDO 28L validada pelo cliente com TempTale ULTRA USB ambiente conforme solicitado pelo cliente.",
                "A etiqueta do Logger USB deve ir colada na Packing List de envio.",
                "Produtos com temperaturas diferentes seguirão em caixas separadas quando houver a necessidade de TT4."
            ])

        texto_final = "\n\n".join(paragrafos)
        components.html(f"""<button onclick="navigator.clipboard.writeText(`{texto_final}`); this.innerText='📋 Texto Copiado!';" style="background:#e59235; color:white; font-size:13px; font-weight:bold; padding:8px; border:none; border-radius:4px; width:100%; cursor:pointer;">📋 Copiar Particularidades</button>""", height=40)

        st.markdown("### ⏱️ SLA e Prazos Operacionais")
        prazo_maximo = somar_dias_uteis(data_recebimento, 7)
        data_limite_doc = somar_dias_uteis(data_recebimento, 2)
        
        if tem_tagalert_ref and not is_capital:
            data_entrega = somar_dias_uteis(data_limite_doc, 2)
            st.warning(f"🚨 **ALERTA REFRIGERADO (FLY):** Validade 96h ativada. Entrega sugerida: {data_entrega.strftime('%d/%m/%Y')}")
        else:
            st.info(f"✅ **FLUXO PADRÃO.** Prazo DOC: {data_limite_doc.strftime('%d/%m/%Y')} | Limite Final: {prazo_maximo.strftime('%d/%m/%Y')}")

# ==========================================
# PÁGINA 3: CRUZAMENTO SOLICITAÇÃO x PACKING (ASSISTENTE DE CONFERÊNCIA)
# ==========================================
elif st.session_state.pagina_atual == "cruzamento":
    
    st.markdown("""
        <div style="background: linear-gradient(135deg, #1b3834 0%, #10281f 100%); padding: 20px 26px; border-radius: 12px; border-left: 6px solid #e59235; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #ffffff !important; margin: 0 0 6px 0; font-size: 18px;">⚖️ Assistente de Conferência - Validação de Remessa</h2>
            <p style="color: #cbd5e1; margin: 0; font-size: 13px; line-height: 1.4;">
                Aja como a 'Assistente de Conferência'. Analise o texto do Shipment e da Solicitação fornecidos.<br>
                Compare estritamente os campos e bloqueie remessas com divergências.
            </p>
        </div>
    """, unsafe_allow_html=True)
    
    if "file_uploader_key" not in st.session_state:
        st.session_state.file_uploader_key = 0

    col_btn_limpar, col_vazio = st.columns([1, 4])
    with col_btn_limpar:
        if st.button("🗑️ Limpar Arquivos", use_container_width=True):
            st.session_state.file_uploader_key += 1
            st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        arquivo_sol = st.file_uploader("Upload da Solicitação (PDF)", type=["pdf"], key=f"sol_{st.session_state.file_uploader_key}")
    with col2:
        arquivo_packing = st.file_uploader("Upload da Packing List / Shipment (PDF)", type=["pdf"], key=f"pack_{st.session_state.file_uploader_key}")

    if arquivo_sol and arquivo_packing:
        st.divider()
        if st.button("Executar Conferência Estritamente", use_container_width=True):
            with st.spinner("Processando documentos e auditando campos..."):
                try:
                    leitor_sol = PdfReader(arquivo_sol)
                    texto_sol = extrair_texto_pdf(leitor_sol, " ")
                    # Acentos removidos: a NEWSE e o Packing List nem sempre extraem
                    # acentuação da mesma forma (ex: "FUNDAÇÃO" vs "FUNDACAO"), então
                    # comparar sem acento evita divergência falsa só por causa disso.
                    texto_sol_upper = remover_acentos(texto_sol.upper())
                    texto_sol_limpo = re.sub(r'\s+', ' ', texto_sol)

                    leitor_packing = PdfReader(arquivo_packing)
                    texto_packing = extrair_texto_pdf(leitor_packing, " ")
                    texto_packing_upper = remover_acentos(texto_packing.upper())
                    texto_packing_limpo = re.sub(r'\s+', ' ', texto_packing)

                    def limpar(t): return re.sub(r'\s+', ' ', str(t)).strip()

                    # --- Grupos de instituições conhecidas (para o campo Centre/Depto) ---
                    # Cada grupo tem palavras-chave que podem aparecer com nomes
                    # diferentes na NEWSE e no Packing List (sistemas diferentes,
                    # grafias diferentes) mas se referem à mesma instituição.
                    # Lista pequena de propósito — o campo NÃO depende só dela:
                    # quando nenhum grupo bate mas o CEP dos dois documentos é
                    # idêntico, isso já é usado como confirmação (ver mais abaixo),
                    # em vez de bloquear a remessa só por causa da grafia do nome.
                    GRUPOS_CENTRO = [
                        ("A. C. CAMARGO / FUNDAÇÃO ANTÔNIO PRUDENTE", ["CAMARGO", "PRUDENTE"]),
                        ("FUNDACAO PIO XII", ["PIO XII"]),
                        ("HOSPITAL SAO LUCAS DA PUCRS", ["SAO LUCAS"]),
                        ("ICESP", ["ICESP", "INSTITUTO DO CANCER"]),
                        ("HOSPITAL MOINHOS DE VENTO", ["MOINHOS DE VENTO"]),
                    ]

                    def identificar_centro(texto):
                        for nome_grupo, palavras in GRUPOS_CENTRO:
                            if any(p in texto for p in palavras):
                                return nome_grupo
                        return "NÃO CONSTA"

                    # --- EXTRAÇÃO DOCUMENTO FONTE (SOLICITAÇÃO / NEWSE) ---
                    s_prot_match = re.search(r"(CA\d+-\d+)", texto_sol_upper)
                    s_prot = s_prot_match.group(1) if s_prot_match else "NÃO CONSTA"

                    # Na NEWSE, o campo "Número da ordem" é onde o número do Delivery
                    # (não do Order) da BMS acaba sendo registrado — por isso o termo
                    # em português "ORDEM" entra na busca, junto dos termos em inglês.
                    s_ship_match = re.search(r"(?:NUMERO DA ORDEM|ORDEM|ORDER|SHIPMENT)[^\d]*(\d{8,12})", texto_sol_upper)
                    s_ship = s_ship_match.group(1) if s_ship_match else (re.search(r"\b(8\d{9})\b", texto_sol_limpo).group(1) if re.search(r"\b(8\d{9})\b", texto_sol_limpo) else "NÃO CONSTA")

                    s_centre = identificar_centro(texto_sol_upper)

                    s_cep_match = re.search(r"CEP[^\d]*(\d{5}-?\d{3})", texto_sol_upper)
                    s_addr = s_cep_match.group(1).replace("-", "") if s_cep_match else (re.search(r"\b(\d{8})\b", texto_sol_upper).group(1) if re.search(r"\b(\d{8})\b", texto_sol_upper) else "NÃO CONSTA")

                    # --- EXTRAÇÃO DOCUMENTO VALIDADO (PACKING LIST) ---
                    p_prot_match = re.search(r"PROTOCOL NUMBER\s*[:\s]*([A-Z0-9\-\/]+)", texto_packing_upper)
                    if p_prot_match:
                        p_prot_raw = p_prot_match.group(1).split('/')[0].strip()
                        p_prot_match2 = re.search(r"(CA\d+-\d+)", p_prot_raw)
                        p_prot = p_prot_match2.group(1) if p_prot_match2 else p_prot_raw
                    else:
                        p_prot = "NÃO CONSTA"

                    p_ship_match = re.search(r"(?:DELIVERY NUMBER|SHIPMENT)\s*[:\s]*(\d{8,12})", texto_packing_upper)
                    p_ship = p_ship_match.group(1) if p_ship_match else "NÃO CONSTA"

                    p_shipto_bloco = texto_packing_upper.split("SHIP TO")[-1] if "SHIP TO" in texto_packing_upper else texto_packing_upper
                    p_centre = identificar_centro(p_shipto_bloco)

                    p_cep_match = re.search(r"(\d{5}-?\d{3})", p_shipto_bloco)
                    p_addr = p_cep_match.group(1).replace("-", "") if p_cep_match else "NÃO CONSTA"

                    # --- Investigator Name ---
                    # O Packing List tem um formato limpo e consistente ("Dr(a).
                    # Fulano de Tal" seguido de "Tel:"), muito mais confiável do que
                    # tentar reconhecer o nome dentro do layout da NEWSE (que varia
                    # e às vezes reordena os campos). Por isso o nome é extraído do
                    # Packing List e depois procurado dentro do texto da NEWSE — em
                    # vez de uma lista fixa de nomes conhecidos, que travava qualquer
                    # investigador novo com uma falsa divergência.
                    p_pi_match = re.search(r"DR\.?A?\.?\s+([A-Z][A-Z\s]+?)\s*TEL\s*:", texto_packing_upper)
                    p_pi = limpar(p_pi_match.group(1)) if p_pi_match else "NÃO CONSTA"

                    # Comparação tolerante a pequenas diferenças de grafia/digitação
                    # entre os sistemas (ex: nome do meio duplicado ou digitado com
                    # uma letra diferente no Packing List). Em vez de exigir o nome
                    # inteiro como substring exata, confirma-se pelo PRIMEIRO e
                    # ÚLTIMO nome (mais estável entre os dois documentos) — reduz
                    # falsos "divergência" por causa de erro de digitação em nomes
                    # do meio, mantendo baixo risco de confirmar a pessoa errada.
                    pi_investigador_conferido = False
                    pi_exato = False
                    if p_pi != "NÃO CONSTA":
                        palavras_pi = [w for w in p_pi.split() if len(w) >= 3]
                        if p_pi in texto_sol_upper:
                            pi_investigador_conferido = True
                            pi_exato = True
                        elif len(palavras_pi) >= 2 and palavras_pi[0] in texto_sol_upper and palavras_pi[-1] in texto_sol_upper:
                            pi_investigador_conferido = True

                    if pi_investigador_conferido:
                        s_pi = p_pi if pi_exato else f"{p_pi} (confirmado por nome/sobrenome — grafia difere no meio)"
                    elif p_pi != "NÃO CONSTA":
                        s_pi = "NÃO ENCONTRADO NA NEWSE"
                    else:
                        s_pi = "NÃO CONSTA"

                    p_qty_matches = re.findall(r"(\d+)\s*EA", texto_packing_upper)
                    p_qty = str(sum([int(q) for q in p_qty_matches])) if p_qty_matches else "NÃO CONSTA"

                    # Coleta de Seriais da Packing List (Documento Validado)
                    seriais_packing = []
                    serial_matches = re.findall(r"SERIAL\s*NO\.?\s*\(([^)]+)\)", texto_packing_upper)
                    if serial_matches:
                        for bloco in serial_matches:
                            if "-" in bloco:
                                p_arr = bloco.split("-")
                                if len(p_arr) == 2 and p_arr[0].strip().isdigit() and p_arr[1].strip().isdigit():
                                    seriais_packing.extend([str(s) for s in range(int(p_arr[0]), int(p_arr[1]) + 1)])
                            elif "," in bloco:
                                seriais_packing.extend([s.strip() for s in bloco.split(",")])
                            else:
                                seriais_packing.append(bloco.strip())
                    else:
                        seriais_packing = re.findall(r"\b\d{5,8}\b", texto_packing_upper)
                    seriais_packing = list(dict.fromkeys(seriais_packing))

                    # Coleta de Seriais da NEWSE — extraídos da própria tabela de
                    # produtos da NEWSE (número que aparece logo antes de "AREA
                    # CLIMATIZADA" ou "CAMARA FRIA" em cada linha), em vez de apenas
                    # verificar se os números do Packing List aparecem em algum lugar
                    # do texto da NEWSE. O método antigo podia dar falso positivo
                    # (um serial coincidir com pedaço de CEP/CNPJ/telefone) e não
                    # detectava serial que a NEWSE tivesse a mais.
                    # O \b (limite de palavra) antes do grupo é necessário porque a
                    # série de um logger (ex: Tag Alert) às vezes vem no formato
                    # alfanumérico "15450K53039" — sem o \b, a regex pescava só o
                    # pedaço final em dígitos ("53039") como se fosse um serial de
                    # produto de verdade, inflando a quantidade e criando uma
                    # divergência falsa nessa linha.
                    seriais_newse = re.findall(r"\b(\d{5,7})\s*(?:AREA|CAMARA)", texto_sol_upper)
                    if not seriais_newse:
                        # Layout de NEWSE não reconhecido — usa o método antigo como
                        # rede de segurança em vez de não comparar nada.
                        seriais_newse = [s for s in seriais_packing if s in texto_sol_upper]
                    seriais_newse = list(dict.fromkeys(seriais_newse))

                    seriais_faltantes_na_newse = [s for s in seriais_packing if s not in seriais_newse]
                    seriais_a_mais_na_newse = [s for s in seriais_newse if s not in seriais_packing]
                    seriais_status_ok = not seriais_faltantes_na_newse and not seriais_a_mais_na_newse and len(seriais_packing) > 0

                    s_qty = str(len(seriais_newse)) if seriais_newse else "NÃO CONSTA"

                    # --- COMPARAÇÃO ESTRITA ---
                    # Confirmação cruzada: quando o nome da instituição não é
                    # reconhecido em nenhum dos dois documentos (ou está escrito de
                    # forma diferente entre os dois sistemas), mas o CEP de destino
                    # dos dois documentos é idêntico, isso já confirma que é o mesmo
                    # endereço/centro de destino — não faz sentido bloquear a
                    # remessa só porque o nome não bateu ou não foi reconhecido.
                    centro_confirmado_por_alias = (s_centre != "NÃO CONSTA" and s_centre == p_centre)
                    centro_confirmado_por_cep = (
                        not centro_confirmado_por_alias
                        and s_addr != "NÃO CONSTA" and s_addr == p_addr
                    )
                    centro_ok = centro_confirmado_por_alias or centro_confirmado_por_cep

                    dados_validacao = [
                        {
                            "Campo Validado": "Dados de Protocolo",
                            "Documento Fonte": s_prot,
                            "Documento Validado": p_prot,
                            "Status": "✅ Conforme" if s_prot != "NÃO CONSTA" and p_prot != "NÃO CONSTA" and (s_prot.replace("-","") in p_prot.replace("-","") or p_prot.replace("-","") in s_prot.replace("-","")) else "❌ Divergência",
                            "Observação": "Protocolos idênticos." if s_prot == p_prot else "Protocolos divergentes entre os documentos."
                        },
                        {
                            "Campo Validado": "Shipment Number",
                            "Documento Fonte": s_ship,
                            "Documento Validado": p_ship,
                            "Status": "✅ Conforme" if s_ship != "NÃO CONSTA" and s_ship == p_ship else "❌ Divergência",
                            "Observação": "Números de shipment idênticos." if s_ship == p_ship else "Divergência no shipment."
                        },
                        {
                            "Campo Validado": "Centre and Department Name",
                            "Documento Fonte": s_centre,
                            "Documento Validado": p_centre,
                            "Status": "✅ Conforme" if centro_ok else "❌ Divergência",
                            "Observação": (
                                "Razão social avaliada." if centro_confirmado_por_alias
                                else "Nome do centro não reconhecido ou escrito de forma diferente nos dois sistemas, mas confirmado pelo CEP de destino (idêntico nos dois documentos)." if centro_confirmado_por_cep
                                else "Divergência na razão social / centro."
                            )
                        },
                        {
                            "Campo Validado": "Depot site Address",
                            "Documento Fonte": s_addr,
                            "Documento Validado": p_addr,
                            "Status": "✅ Conforme" if s_addr != "NÃO CONSTA" and s_addr == p_addr else "❌ Divergência",
                            "Observação": "Endereço / CEP verificado." if s_addr == p_addr else "Divergência no endereço / CEP."
                        },
                        {
                            "Campo Validado": "Investigator Name",
                            "Documento Fonte": s_pi,
                            "Documento Validado": p_pi,
                            "Status": "✅ Conforme" if pi_investigador_conferido else "❌ Divergência",
                            "Observação": (
                                "Nome do investigador idêntico nos dois documentos." if pi_exato
                                else "Nome e sobrenome do investigador conferem, mas a grafia do nome do meio difere entre os documentos (provável erro de digitação)." if pi_investigador_conferido
                                else "Investigador do Packing List não foi encontrado no texto da NEWSE."
                            )
                        },
                        {
                            "Campo Validado": "Total quantity in shipment",
                            "Documento Fonte": s_qty,
                            "Documento Validado": p_qty,
                            "Status": "✅ Conforme" if s_qty != "NÃO CONSTA" and s_qty == p_qty else "❌ Divergência",
                            "Observação": "Quantidade total avaliada." if s_qty == p_qty else "Divergência na quantidade total."
                        },
                        {
                            "Campo Validado": "Validação de Seriais dos Produtos",
                            "Documento Fonte": f"Seriais: {', '.join(seriais_newse)}",
                            "Documento Validado": f"Seriais: {', '.join(seriais_packing)}",
                            "Status": "✅ Conforme" if seriais_status_ok else "❌ Divergência",
                            "Observação": (
                                "Números de série conferem integralmente." if seriais_status_ok
                                else "Faltando na NEWSE: " + (", ".join(seriais_faltantes_na_newse) or "-") + " | A mais na NEWSE: " + (", ".join(seriais_a_mais_na_newse) or "-")
                            )
                        }
                    ]

                    df = pd.DataFrame(dados_validacao)

                    def estilizar_status(val):
                        if "Divergência" in val or "Ausente" in val:
                            return f'<span style="color:red">{val}</span>'
                        return val

                    df_exibicao = df.copy()
                    df_exibicao["Status"] = df_exibicao["Status"].apply(estilizar_status)

                    st.markdown("### Tabela de Validação de Remessa")
                    html_tabela = df_exibicao.to_html(escape=False, index=False, classes="dataframe")
                    st.markdown(f"<div style='overflow-x:auto;'>{html_tabela}</div>", unsafe_allow_html=True)

                    tem_divergencia = any("Divergência" in row["Status"] for row in dados_validacao)
                    
                    st.markdown("---")
                    st.markdown("### Resumo Executivo")
                    if tem_divergencia:
                        st.error("🔴 **Classificação Final:** Reprovado por Divergência (Há inconsistências críticas entre os documentos ou seriais ausentes).")
                    else:
                        st.success("🟢 **Classificação Final:** Aprovado (Todos os campos e seriais conferem integralmente sem divergências).")

                except Exception as e:
                    st.error(f"Erro na execução da conferência: {e}")

# ==========================================
# PÁGINA: CONFERÊNCIA DE AGENDAMENTO (Packing List x NEWSE x Agendamento x Minuta)
# ==========================================
# Portado do painel "Validador DRS Group - Logística" (artifact separado do
# usuário) para dentro do Portal BMS, como uma aba própria — e reescrito para
# fazer conferência DE VERDADE campo a campo (a versão original só mostrava
# "Verificado no Portal" fixo, sem checar nada de fato). Mantém os mesmos 3
# estágios do painel original, mas agora cada campo é extraído dos dois
# documentos e comparado de verdade, com o valor de cada lado sempre visível
# na tela — nunca só "Verificar PDF".
elif st.session_state.pagina_atual == "conferencia_agendamento":

    st.markdown("""
        <div style="background: linear-gradient(135deg, #1b3834 0%, #10281f 100%); padding: 20px 26px; border-radius: 12px; border-left: 6px solid #6d28d9; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #ffffff !important; margin: 0 0 6px 0; font-size: 18px;">🧾 Conferência de Agendamento — Packing List, NEWSE, Agendamento e Minuta</h2>
            <p style="color: #cbd5e1; margin: 0; font-size: 13px; line-height: 1.4;">
                Auditoria estruturada campo a campo, em 3 etapas: <b>Packing List x NEWSE</b>, <b>NEWSE x Agendamento</b>
                e <b>Auditoria Final com a Minuta de Envio (SC)</b>. Todo campo comparado mostra o valor extraído dos dois
                documentos lado a lado — nada fica marcado como correto sem ter sido checado de fato.
            </p>
        </div>
    """, unsafe_allow_html=True)

    def extrair_texto_pdf_conferencia(arquivo):
        """Mesma extração usada no resto do portal (pypdf), mas mantendo uma
        quebra de linha entre páginas — os regex desta página dependem de
        '\\n' para não vazar de uma linha para a próxima."""
        leitor_conf = PdfReader(arquivo)
        return extrair_texto_pdf(leitor_conf, separador="\n")

    def normalizar_alfanum(t):
        """Maiúsculo e só letras/dígitos — remove espaço, hífen, barra, ponto
        etc. Usado para achar um Lote dentro do texto da NEWSE mesmo quando a
        extração do PDF grudou/quebrou a formatação original (comum em
        tabelas de PDF)."""
        return re.sub(r"[^A-Z0-9]", "", str(t).upper())

    def so_digitos(t):
        return re.sub(r"\D", "", str(t))

    def extrair_lista_contatos(texto_bruto):
        """Recebe um bloco de texto bruto (pode ter quebras de linha no meio
        dos nomes) e devolve uma lista de nomes limpos, separados por '/'."""
        texto_limpo = re.sub(r"\s+", " ", str(texto_bruto)).strip()
        nomes = []
        for parte in texto_limpo.split("/"):
            parte = parte.strip()
            m = re.match(r"^([A-Za-zÀ-ÿ\s\.]+)", parte)
            nome = m.group(1).strip() if m else parte
            if nome:
                nomes.append(nome)
        return nomes

    def comparar_listas_nomes(lista_a, texto_b_bruto):
        """Confere se cada nome da lista_a aparece no texto_b_bruto. Compara
        com TODOS os espaços removidos dos dois lados (além de acento/caixa)
        porque alguns PDFs (ex: a Minuta) têm um artefato de fonte que insere
        um espaço extra no meio de palavras ("V itoria", "CONT ATO") — sem
        isso, esses nomes apareceriam como falsa divergência."""
        texto_b_normalizado = re.sub(r"\s+", "", remover_acentos(str(texto_b_bruto).upper()))
        encontrados, faltando = [], []
        for nome in lista_a:
            nome_normalizado = re.sub(r"\s+", "", remover_acentos(nome.upper()))
            if nome_normalizado and nome_normalizado in texto_b_normalizado:
                encontrados.append(nome)
            else:
                faltando.append(nome)
        return encontrados, faltando

    MESES_CONF = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
                  "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}

    def data_para_iso(data_str):
        """Converte '31-AUG-2028' (formato do Packing List) -> '2028-08-31'
        (formato usado na NEWSE). Devolve None se não reconhecer o formato."""
        m = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", str(data_str).strip())
        if not m:
            return None
        dia, mes_txt, ano = m.groups()
        mes = MESES_CONF.get(mes_txt.upper())
        if not mes:
            return None
        return f"{ano}-{mes:02d}-{int(dia):02d}"

    def extrair_itens_packing(texto):
        """Extrai cada item de produto da Packing List: Material, Batch
        (Lote), Quantity, Use Date (Validade) e a lista de números de série —
        a partir do bloco 'Shipping Information' (Material Batch Quantity Use
        Date / Serial No. (...))."""
        itens = []
        padrao_item = re.compile(
            r"(\d{5,8})\s+([A-Z0-9\.\-]+)\s+(\d+)\s*EA\s+(\d{1,2}-[A-Z]{3}-\d{4})",
            re.IGNORECASE,
        )
        matches = list(padrao_item.finditer(texto))
        for i, m in enumerate(matches):
            material, lote, qtd, validade = m.groups()
            bloco = texto[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(texto)]
            nome_match = re.match(r"\s*([^\n]+)", bloco)
            nome = nome_match.group(1).strip() if nome_match else "NÃO IDENTIFICADO"
            serial_match = re.search(r"Serial\s*No\.?\s*\(([^)]+)\)", bloco, re.IGNORECASE)
            seriais = [s.strip() for s in serial_match.group(1).split(",")] if serial_match else []
            itens.append({
                "material": material,
                "lote": lote,
                "quantidade": int(qtd),
                "validade": validade.upper(),
                "validade_iso": data_para_iso(validade),
                "nome": nome,
                "seriais": seriais,
            })
        return itens

    def extrair_seriais_produtos_newse(texto_newse_bruto):
        """Lê a tabela 'Produto(s)' da NEWSE e devolve um dicionário
        serial -> [validades associadas a ele]. A extração de PDF grudona
        Nome+Lote+Validade+Série numa sequência contínua de caracteres sem
        separador confiável entre eles (ex: 'ADE45722028-08-31145783AREA') —
        por isso, em vez de tentar separar essas colunas, a técnica aqui
        procura, em toda a tabela normalizada (só letras/dígitos), o padrão
        <data no formato AAAAMMDD><dígitos do serial>, sempre imediatamente
        seguido de 'AREA' ou 'CAMARA' (a área de armazenamento que a NEWSE
        sempre imprime logo depois da série de cada produto). Isso funciona
        mesmo com o Lote grudado na frente da data, porque só uma posição de
        início permite que a data (8 dígitos) e a série (o resto) encaixem
        exatamente até 'AREA'/'CAMARA' — testado com um documento NEWSE real."""
        bloco = texto_newse_bruto.split("Produto(s)")[-1]
        if "Observações" in bloco:
            bloco = bloco.split("Observações")[0]
        bloco_normalizado = normalizar_alfanum(bloco)
        padrao = re.compile(r"(20\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(\d{4,8})(?=AREA|CAMARA)")
        mapa_serial_para_validades = {}
        for m in padrao.finditer(bloco_normalizado):
            data_compacta, serial = m.groups()
            data_iso = f"{data_compacta[:4]}-{data_compacta[4:6]}-{data_compacta[6:]}"
            mapa_serial_para_validades.setdefault(serial, []).append(data_iso)
        return mapa_serial_para_validades, bloco_normalizado

    def linha_conferencia(campo, valor_a, valor_b, ok, obs_ok, obs_divergente):
        """Renderiza uma linha da tabela de conferência (campo, valor de cada
        lado e status) e devolve se ela está OK — sempre mostrando os dois
        valores extraídos, nunca um texto fixo tipo 'Verificado no Portal'."""
        c1, c2, c3, c4 = st.columns([2.3, 2.2, 2.2, 1.6])
        c1.write(f"**{campo}**")
        c2.text(valor_a if valor_a else "—")
        c3.text(valor_b if valor_b else "—")
        c4.markdown("✅ Conforme" if ok else "❌ Divergência")
        st.caption(obs_ok if ok else obs_divergente)
        st.markdown("---")
        return ok

    tab_conf1, tab_conf2, tab_conf3 = st.tabs([
        "Etapa 1: Packing List x NEWSE",
        "Etapa 2: NEWSE x Agendamento",
        "Etapa 3: Auditoria Final (Minuta)",
    ])

    # ---------------------------------------------------------
    # ETAPA 1: PACKING LIST X NEWSE
    # ---------------------------------------------------------
    with tab_conf1:
        st.markdown("#### Etapa 1: Validação de Raiz (Packing List x NEWSE)")
        st.caption("Confronto estruturado campo a campo entre a Packing List e a NEWSE.")

        col1, col2 = st.columns(2)
        with col1:
            pedido_file = st.file_uploader("Arraste a Packing List (PDF)", type=["pdf"], key="conf_p_etapa1")
        with col2:
            newse_file_1 = st.file_uploader("Arraste a NEWSE (PDF)", type=["pdf"], key="conf_n_etapa1")

        if st.button("Validar Etapa 1", key="conf_btn1"):
            if pedido_file and newse_file_1:
                t_pedido = extrair_texto_pdf_conferencia(pedido_file)
                t_newse = extrair_texto_pdf_conferencia(newse_file_1)

                checks_1 = []

                # --- Delivery Number (Packing List) x Número da Ordem (NEWSE) ---
                m_del_p = re.search(r"Delivery\s*number\s*:?\s*(\d+)", t_pedido, re.IGNORECASE)
                del_p = m_del_p.group(1).strip() if m_del_p else "NÃO LOCALIZADO"
                m_del_n = re.search(r"N[uú]mero da ordem\s*:?\s*(\d+)", t_newse, re.IGNORECASE)
                del_n = m_del_n.group(1).strip() if m_del_n else "NÃO LOCALIZADO"
                ok_delivery = del_p != "NÃO LOCALIZADO" and del_p == del_n

                # --- Protocolo / Estudo ---
                m_prot_p = re.search(r"Protocol number\s*:?\s*([A-Z0-9\-\/]+)", t_pedido, re.IGNORECASE)
                prot_p_raw = m_prot_p.group(1) if m_prot_p else ""
                m_prot_p2 = re.search(r"(CA\d+-\d+)", prot_p_raw.upper())
                prot_p = m_prot_p2.group(1) if m_prot_p2 else (prot_p_raw or "NÃO LOCALIZADO")
                m_prot_n = re.search(r"(CA\d+-\d+)", t_newse.upper())
                prot_n = m_prot_n.group(1) if m_prot_n else "NÃO LOCALIZADO"
                ok_protocolo = prot_p != "NÃO LOCALIZADO" and prot_p == prot_n

                # --- CEP de destino ---
                bloco_shipto_packing = t_pedido.split("Ship To")[-1] if "Ship To" in t_pedido else t_pedido
                m_cep_p = re.search(r"(\d{5}-?\d{3})", bloco_shipto_packing)
                cep_p = m_cep_p.group(1).replace("-", "") if m_cep_p else "NÃO LOCALIZADO"
                m_cep_n = re.search(r"CEP[^\d]*(\d{5}-?\d{3})", t_newse, re.IGNORECASE)
                cep_n = m_cep_n.group(1).replace("-", "") if m_cep_n else "NÃO LOCALIZADO"
                ok_cep = cep_p != "NÃO LOCALIZADO" and cep_p == cep_n

                # --- Investigador: fonte é a NEWSE (campo bem identificado lá),
                # e depois confere se o nome aparece no texto da Packing List ---
                m_inv_n = re.search(
                    r"Investigador\(es\) Principal\(is\) / M[eé]dico\(s\)\s*\n?Nome\s*\n?([^\n]+)",
                    t_newse, re.IGNORECASE,
                )
                inv_n = m_inv_n.group(1).strip() if m_inv_n else "NÃO LOCALIZADO"
                palavras_inv = [w for w in remover_acentos(inv_n.upper()).split() if len(w) >= 3]
                packing_upper_noacc = remover_acentos(t_pedido.upper())
                ok_investigador = bool(palavras_inv) and all(
                    w in packing_upper_noacc for w in [palavras_inv[0], palavras_inv[-1]]
                )

                st.markdown("### 📋 Tabela de Conferência Analítica - Etapa 1")
                checks_1.append(linha_conferencia(
                    "Delivery Number x Número da Ordem", del_p, del_n, ok_delivery,
                    "Números idênticos.",
                    "Delivery Number da Packing List não bate com o Número da Ordem da NEWSE (ou não foi encontrado).",
                ))
                checks_1.append(linha_conferencia(
                    "Protocolo / Estudo", prot_p, prot_n, ok_protocolo,
                    "Protocolo idêntico nos dois documentos.",
                    "Protocolo divergente ou não encontrado em um dos documentos.",
                ))
                checks_1.append(linha_conferencia(
                    "CEP de Destino", cep_p, cep_n, ok_cep,
                    "CEP de destino idêntico nos dois documentos.",
                    "CEP de destino divergente ou não encontrado em um dos documentos.",
                ))
                checks_1.append(linha_conferencia(
                    "Investigador (NEWSE) x Packing List", inv_n,
                    "Encontrado no texto da Packing List" if ok_investigador else "NÃO encontrado no texto da Packing List",
                    ok_investigador,
                    "Nome do investigador da NEWSE localizado no texto da Packing List.",
                    "Nome do investigador da NEWSE não foi localizado no texto da Packing List.",
                ))

                # --- Confronto Detalhado: Dispositivos / Produtos ---
                st.markdown("### 📦 Confronto Detalhado: Dispositivos / Produtos (PACKING x NEWSE)")
                st.caption(
                    "Material/Batch/Quantity/Use Date/Serial No. (Packing List) x "
                    "Nome/Lote/Quantidade/Validade/Peça ou Série (NEWSE). O mais importante: "
                    "se um número aparece no campo Peça OU no campo Série da NEWSE, já conta como correto."
                )

                itens_packing = extrair_itens_packing(t_pedido)
                mapa_serial_newse, bloco_produtos_newse_norm = extrair_seriais_produtos_newse(t_newse)

                if not itens_packing:
                    st.warning("⚠️ Não foi possível identificar os itens de produto na Packing List (formato não reconhecido — verifique manualmente pelos blocos de texto abaixo).")
                    checks_1.append(False)

                seriais_packing_todos = []
                for item in itens_packing:
                    seriais_packing_todos.extend(item["seriais"])
                    lote_norm = normalizar_alfanum(item["lote"])
                    lote_ok = lote_norm in bloco_produtos_newse_norm

                    linhas_serial = []
                    for s in item["seriais"]:
                        datas_encontradas = mapa_serial_newse.get(s, [])
                        encontrado = bool(datas_encontradas)
                        validade_bate = encontrado and item["validade_iso"] in datas_encontradas
                        linhas_serial.append((s, encontrado, validade_bate))

                    qtd_ok = item["quantidade"] == len(item["seriais"])
                    seriais_ok = bool(item["seriais"]) and all(v for _, _, v in linhas_serial)
                    item_ok = lote_ok and qtd_ok and seriais_ok
                    checks_1.append(item_ok)

                    st.markdown(f"**{item['nome']}**  (Material {item['material']})")
                    col_pk, col_nw = st.columns(2)
                    with col_pk:
                        st.markdown("📄 *Packing List*")
                        st.text(f"Lote (Batch): {item['lote']}")
                        st.text(f"Quantidade: {item['quantidade']}")
                        st.text(f"Validade (Use Date): {item['validade']}")
                        st.text(f"Peça/Série (Serial No.): {', '.join(item['seriais']) or 'N/A'}")
                    with col_nw:
                        st.markdown("📄 *NEWSE*")
                        st.text(f"Lote encontrado: {'Sim' if lote_ok else 'NÃO ENCONTRADO'}")
                        st.text(f"Quantidade de séries localizadas: {sum(1 for _, e, _ in linhas_serial if e)} de {item['quantidade']}")
                        for s, encontrado, validade_bate in linhas_serial:
                            if encontrado and validade_bate:
                                st.text(f"✅ Peça/Série {s} — encontrada, validade confere")
                            elif encontrado and not validade_bate:
                                st.text(f"⚠️ Peça/Série {s} — encontrada, mas com validade diferente")
                            else:
                                st.text(f"❌ Peça/Série {s} — NÃO encontrada na NEWSE")
                    st.markdown("✅ **Item conforme**" if item_ok else "❌ **Item com divergência**")
                    st.markdown("---")

                a_mais_na_newse = [s for s in mapa_serial_newse.keys() if s not in seriais_packing_todos]
                if a_mais_na_newse:
                    st.warning(f"⚠️ Seriais a mais na NEWSE, sem produto correspondente na Packing List: {', '.join(a_mais_na_newse)}")
                    checks_1.append(False)
                elif itens_packing:
                    st.success("✅ Nenhum serial a mais na NEWSE — todos os produtos da NEWSE têm correspondência na Packing List.")

                # Blocos de texto bruto, para conferência visual manual adicional
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    with st.expander("Ver texto bruto extraído da Packing List"):
                        st.text(t_pedido)
                with col_d2:
                    with st.expander("Ver texto bruto extraído da NEWSE"):
                        st.text(t_newse)

                st.markdown("---")
                aprovado_1 = all(checks_1)
                if aprovado_1:
                    st.success("🎉 **Resultado Final da Etapa 1:** APROVADO! Todos os dados essenciais e itens conferem perfeitamente.")
                else:
                    st.error("🚨 **Resultado Final da Etapa 1:** REPROVADO! Divergências encontradas entre os documentos (veja acima quais campos/itens).")
            else:
                st.warning("Por favor, faça o upload de ambos os arquivos.")

    # ---------------------------------------------------------
    # ETAPA 2: NEWSE X AGENDAMENTO
    # ---------------------------------------------------------
    with tab_conf2:
        st.markdown("#### Etapa 2: Validação de Comunicação (NEWSE x Agendamento)")
        st.caption("Confronto estruturado entre a NEWSE e o e-mail de Agendamento (ignorando data e horário de entrega).")

        col1, col2 = st.columns(2)
        with col1:
            newse_file_2 = st.file_uploader("Arraste a NEWSE (PDF)", type=["pdf"], key="conf_n_etapa2")
        with col2:
            agenda_file = st.file_uploader("Arraste o E-mail de Agendamento (PDF)", type=["pdf"], key="conf_a_etapa2")

        if st.button("Validar Etapa 2", key="conf_btn2"):
            if newse_file_2 and agenda_file:
                t_newse2 = extrair_texto_pdf_conferencia(newse_file_2)
                t_agenda = extrair_texto_pdf_conferencia(agenda_file)

                checks_2 = []

                m_prot_n2 = re.search(r"(CA\d+-\d+)", t_newse2.upper())
                prot_n2 = m_prot_n2.group(1) if m_prot_n2 else "NÃO LOCALIZADO"
                m_prot_a = re.search(r"(CA\d+-\d+)", t_agenda.upper())
                prot_a = m_prot_a.group(1) if m_prot_a else "NÃO LOCALIZADO"
                ok_prot2 = prot_n2 != "NÃO LOCALIZADO" and prot_n2 == prot_a

                bloco_dest_n = t_newse2.split("Dados do Destinatário")[-1] if "Dados do Destinatário" in t_newse2 else t_newse2
                m_cnpj_n = re.search(r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", bloco_dest_n)
                cnpj_n = so_digitos(m_cnpj_n.group(1)) if m_cnpj_n else "NÃO LOCALIZADO"
                m_cnpj_a = re.search(r"CPF\s*/\s*CNPJ\s*:?\s*([\d\.\/\-]+)", t_agenda, re.IGNORECASE)
                cnpj_a = so_digitos(m_cnpj_a.group(1)) if m_cnpj_a else "NÃO LOCALIZADO"
                ok_cnpj2 = cnpj_n != "NÃO LOCALIZADO" and cnpj_n == cnpj_a

                m_cep_n2 = re.search(r"CEP[^\d]*(\d{5}-?\d{3})", t_newse2, re.IGNORECASE)
                cep_n2 = so_digitos(m_cep_n2.group(1)) if m_cep_n2 else "NÃO LOCALIZADO"
                m_cep_a = re.search(r"CEP\s*:?\s*\n?\s*(\d{5}-?\d{3})", t_agenda, re.IGNORECASE)
                cep_a = so_digitos(m_cep_a.group(1)) if m_cep_a else "NÃO LOCALIZADO"
                ok_cep2 = cep_n2 != "NÃO LOCALIZADO" and cep_n2 == cep_a

                m_contatos_n = re.search(
                    r"Pessoa\(s\) Autorizada\(s\)\s*\nNome[^\n]*\n(.+?)Investigador",
                    t_newse2, re.IGNORECASE | re.DOTALL,
                )
                contatos_n = extrair_lista_contatos(m_contatos_n.group(1)) if m_contatos_n else []
                m_contatos_a = re.search(r"Contatos autorizados\s*:?(.+?)Data da entrega", t_agenda, re.IGNORECASE | re.DOTALL)
                contatos_a_texto = m_contatos_a.group(1) if m_contatos_a else ""
                encontrados_c2, faltando_c2 = comparar_listas_nomes(contatos_n, contatos_a_texto)
                ok_contatos2 = bool(contatos_n) and not faltando_c2

                st.markdown("### 📋 Tabela de Conferência Analítica - Etapa 2")
                checks_2.append(linha_conferencia(
                    "Protocolo / Estudo", prot_n2, prot_a, ok_prot2,
                    "Protocolo idêntico nos dois documentos.",
                    "Protocolo divergente ou não encontrado em um dos documentos.",
                ))
                checks_2.append(linha_conferencia(
                    "CNPJ do Centro / Destinatário", cnpj_n, cnpj_a, ok_cnpj2,
                    "CNPJ idêntico nos dois documentos.",
                    "CNPJ divergente ou não encontrado em um dos documentos.",
                ))
                checks_2.append(linha_conferencia(
                    "CEP do Centro", cep_n2, cep_a, ok_cep2,
                    "CEP idêntico nos dois documentos.",
                    "CEP divergente ou não encontrado em um dos documentos.",
                ))
                checks_2.append(linha_conferencia(
                    "Contatos Autorizados de Entrega",
                    ", ".join(contatos_n) or "NÃO LOCALIZADO",
                    f"{len(encontrados_c2)}/{len(contatos_n)} confirmados" if contatos_n else "NÃO LOCALIZADO",
                    ok_contatos2,
                    "Todos os contatos autorizados da NEWSE aparecem no e-mail de Agendamento.",
                    "Faltando no Agendamento: " + (", ".join(faltando_c2) or "-"),
                ))
                c1, c2, c3, c4 = st.columns([2.3, 2.2, 2.2, 1.6])
                c1.write("**Janela de Entrega (Data/Horário)**")
                c2.text("Ignorado por regra")
                c3.text("Ignorado por regra")
                c4.markdown("➖ Não avaliado")
                st.caption("Por regra desta etapa, data e horário de entrega não são conferidos aqui (podem mudar por reagendamento sem indicar problema no envio).")
                st.markdown("---")

                aprovado_2 = all(checks_2)
                if aprovado_2:
                    st.success("🎉 **Resultado Final da Etapa 2:** APROVADO! O agendamento confere com a NEWSE.")
                else:
                    st.error("🚨 **Resultado Final da Etapa 2:** REPROVADO! Divergências encontradas entre os documentos (veja acima quais campos).")
            else:
                st.warning("Por favor, faça o upload de ambos os arquivos.")

    # ---------------------------------------------------------
    # ETAPA 3: AUDITORIA FINAL (MINUTA)
    # ---------------------------------------------------------
    with tab_conf3:
        st.markdown("#### Etapa 3: Auditoria Final (Todas as Documentações + Minuta)")
        st.caption("Auditoria cruzada final com a Minuta de Envio (SC) e regras fixas de transporte DRS.")

        col1, col2, col3 = st.columns(3)
        with col1:
            f_newse_3 = st.file_uploader("NEWSE", type=["pdf"], key="conf_n_etapa3")
        with col2:
            f_agenda_3 = st.file_uploader("Agendamento", type=["pdf"], key="conf_a_etapa3")
        with col3:
            f_minuta_3 = st.file_uploader("Minuta de Envio (SC)", type=["pdf"], key="conf_m_etapa3")

        if st.button("Executar Auditoria Final", key="conf_btn3"):
            if f_newse_3 and f_agenda_3 and f_minuta_3:
                t_newse3 = extrair_texto_pdf_conferencia(f_newse_3)
                t_minuta = extrair_texto_pdf_conferencia(f_minuta_3)

                checks_3 = []

                cnpjs_drs_validos = ["00804488000100", "00804488000290"]
                m_remetente = re.search(r"Remetente\s*-\s*([\d\.\/\-\s]+)", t_minuta)
                remetente_digits = so_digitos(m_remetente.group(1)) if m_remetente else ""
                ok_remetente = remetente_digits in cnpjs_drs_validos

                m_prot_n3 = re.search(r"(CA\d+-\d+)", t_newse3.upper())
                prot_n3 = m_prot_n3.group(1) if m_prot_n3 else "NÃO LOCALIZADO"
                m_prot_m = re.search(r"(CA\d+-\d+)", t_minuta.upper())
                prot_m = m_prot_m.group(1) if m_prot_m else "NÃO LOCALIZADO"
                ok_prot3 = prot_n3 != "NÃO LOCALIZADO" and prot_n3 == prot_m

                m_track_n = re.search(r"Tracking Number\s*:?\s*\n?\s*([\d\-]+)", t_newse3, re.IGNORECASE)
                track_n = m_track_n.group(1) if m_track_n else "NÃO LOCALIZADO"
                m_track_m = re.search(r"TRACKING NUMBER\s+([\d\-]+)", t_minuta, re.IGNORECASE)
                track_m = m_track_m.group(1) if m_track_m else "NÃO LOCALIZADO"
                ok_track = track_n != "NÃO LOCALIZADO" and track_n == track_m

                bloco_dest_n3 = t_newse3.split("Dados do Destinatário")[-1] if "Dados do Destinatário" in t_newse3 else t_newse3
                m_cnpj_n3 = re.search(r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", bloco_dest_n3)
                cnpj_n3 = so_digitos(m_cnpj_n3.group(1)) if m_cnpj_n3 else "NÃO LOCALIZADO"
                m_dest_minuta = re.search(r"Destinat[aá]rio\s*-\s*([\d\s]+)", t_minuta)
                dest_cnpj_minuta = so_digitos(m_dest_minuta.group(1)) if m_dest_minuta else "NÃO LOCALIZADO"
                ok_dest_cnpj = dest_cnpj_minuta != "NÃO LOCALIZADO" and dest_cnpj_minuta == cnpj_n3

                m_inv_n3 = re.search(
                    r"Investigador\(es\) Principal\(is\) / M[eé]dico\(s\)\s*\n?Nome\s*\n?([^\n]+)",
                    t_newse3, re.IGNORECASE,
                )
                inv_n3 = m_inv_n3.group(1).strip() if m_inv_n3 else "NÃO LOCALIZADO"
                m_pi_minuta = re.search(r"P\.I\.\s*([^\n]+)", t_minuta)
                pi_minuta = m_pi_minuta.group(1).strip() if m_pi_minuta else "NÃO LOCALIZADO"
                palavras_inv3 = [w for w in remover_acentos(inv_n3.upper()).split() if len(w) >= 3]
                ok_pi3 = bool(palavras_inv3) and all(
                    w in remover_acentos(pi_minuta.upper()) for w in [palavras_inv3[0], palavras_inv3[-1]]
                )

                m_contatos_n3 = re.search(
                    r"Pessoa\(s\) Autorizada\(s\)\s*\nNome[^\n]*\n(.+?)Investigador",
                    t_newse3, re.IGNORECASE | re.DOTALL,
                )
                contatos_n3 = extrair_lista_contatos(m_contatos_n3.group(1)) if m_contatos_n3 else []
                # "CONTATO" e "COLETA" às vezes saem com um espaço extra no meio
                # ("CONT ATO", "COLET A") por um artefato de fonte da Minuta.
                m_contatos_m = re.search(
                    r"CONT\s*ATO AUTORIZADO ENTREGA\s*(.+?)CONT\s*ATO AUTORIZADO COLET\s*A",
                    t_minuta, re.IGNORECASE | re.DOTALL,
                )
                contatos_m_texto = m_contatos_m.group(1) if m_contatos_m else ""
                encontrados_c3, faltando_c3 = comparar_listas_nomes(contatos_n3, contatos_m_texto)
                ok_contatos3 = bool(contatos_n3) and not faltando_c3

                m_transp = re.search(r"DRS\s*(COURIER|ADMINISTRA[CÇ][AÃ]O DE ESTOQUES)", t_minuta, re.IGNORECASE)
                ok_transp = bool(m_transp)

                st.markdown("### 📋 Tabela de Conferência Analítica - Etapa 3")
                checks_3.append(linha_conferencia(
                    "Protocolo / Estudo", prot_n3, prot_m, ok_prot3,
                    "Protocolo idêntico nos dois documentos.",
                    "Protocolo divergente ou não encontrado em um dos documentos.",
                ))
                checks_3.append(linha_conferencia(
                    "Remetente DRS (CNPJ Fixo Oficial)", "00804488000100 ou 00804488000290", remetente_digits, ok_remetente,
                    "CNPJ do remetente é um dos CNPJs oficiais da DRS.",
                    "CNPJ do remetente na Minuta não é nenhum dos CNPJs oficiais da DRS.",
                ))
                checks_3.append(linha_conferencia(
                    "Tracking Number", track_n, track_m, ok_track,
                    "Tracking Number idêntico nos dois documentos.",
                    "Tracking Number divergente ou não encontrado em um dos documentos.",
                ))
                checks_3.append(linha_conferencia(
                    "CNPJ do Destinatário", cnpj_n3, dest_cnpj_minuta, ok_dest_cnpj,
                    "CNPJ do destinatário idêntico nos dois documentos.",
                    "CNPJ do destinatário divergente ou não encontrado em um dos documentos.",
                ))
                checks_3.append(linha_conferencia(
                    "P.I. / Investigador", inv_n3, pi_minuta, ok_pi3,
                    "Nome do investigador da NEWSE localizado no campo P.I. da Minuta.",
                    "Nome do investigador da NEWSE não foi localizado no campo P.I. da Minuta.",
                ))
                checks_3.append(linha_conferencia(
                    "Contatos Autorizados",
                    ", ".join(contatos_n3) or "NÃO LOCALIZADO",
                    f"{len(encontrados_c3)}/{len(contatos_n3)} confirmados" if contatos_n3 else "NÃO LOCALIZADO",
                    ok_contatos3,
                    "Todos os contatos autorizados da NEWSE aparecem na Minuta.",
                    "Faltando na Minuta: " + (", ".join(faltando_c3) or "-"),
                ))
                checks_3.append(linha_conferencia(
                    "Transportadora", "DRS COURIER LTDA (regra fixa)",
                    m_transp.group(0) if m_transp else "NÃO ENCONTRADA", ok_transp,
                    "Transportadora oficial DRS identificada na Minuta.",
                    "Transportadora oficial DRS não foi encontrada na Minuta.",
                ))

                aprovado_3 = all(checks_3)
                if aprovado_3:
                    st.success("🎉 **Resultado Final da Etapa 3:** TUDO CERTO com a minuta de envio! Processo liberado para o time de Expedição.")
                else:
                    st.error("🚨 **Resultado Final da Etapa 3:** REPROVADO! Divergências encontradas entre os documentos (veja acima quais campos).")
            else:
                st.warning("Por favor, faça o upload de todos os três documentos exigidos.")

# ==========================================
# PÁGINA: BMS BRASIL - SOLICITAÇÕES (retirada de TAG sem Packing List)
# ==========================================
elif st.session_state.pagina_atual == "bms_brasil":

    st.markdown("""
        <div style="background: linear-gradient(135deg, #1b3834 0%, #10281f 100%); padding: 20px 26px; border-radius: 12px; border-left: 6px solid #209b7c; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #ffffff !important; margin: 0 0 6px 0; font-size: 18px;">🇧🇷 BMS Brasil — Solicitações</h2>
            <p style="color: #cbd5e1; margin: 0; font-size: 13px; line-height: 1.4;">
                Para solicitações da <b>BMS Brasil</b>, a NEWSE não vem acompanhada de Packing List com TAG/TEMP já definido.
                Anexe a <b>NEWSE (PDF)</b> aqui para retirar automaticamente o <b>Tag Alert</b> (Ambiente ou Refrigerado, conforme a
                faixa de temperatura da solicitação) e registrar a retirada para rastreabilidade — sem TempTale, e sem precisar
                editar a planilha manualmente.
            </p>
        </div>
    """, unsafe_allow_html=True)

    arquivo_newse_brasil = st.file_uploader(
        "📥 Arraste o PDF da NEWSE (Solicitação Brasil) aqui",
        type=["pdf"],
        key=f"brasil_{st.session_state.brasil_uploader_key}",
    )

    if arquivo_newse_brasil is None:
        # Mesma lógica da página de Automação: sem arquivo anexado, nada foi
        # de fato retirado do estoque ainda, então a navegação não precisa
        # ficar travada — permite cancelar só removendo o arquivo.
        st.session_state.alocacao_pendente = False

    if arquivo_newse_brasil is not None:
        leitor_brasil = PdfReader(arquivo_newse_brasil)
        texto_brasil_upper = extrair_texto_pdf(leitor_brasil).upper()

        # --- Protocolo do estudo ---
        estudo_brasil = "NÃO IDENTIFICADO"
        match_protocolo_brasil = re.search(r"\bCA\d+-\d+\b", texto_brasil_upper)
        if match_protocolo_brasil:
            estudo_brasil = match_protocolo_brasil.group(0)

        # --- TE do estudo: primeiro tenta achar impresso na própria NEWSE;
        # se não achar, cai no mesmo fallback por planilha usado na Automação ---
        te_brasil = "NÃO ENCONTRADO"
        match_te_brasil = re.search(r"\bTE\s*(\d{3,5})\b", texto_brasil_upper)
        if match_te_brasil:
            te_brasil = f"TE{match_te_brasil.group(1)}"
        elif df_te is not None:
            for idx, row in df_te.iterrows():
                if estudo_brasil != "NÃO IDENTIFICADO" and estudo_brasil in str(row['Estudo']).upper():
                    te_brasil = str(row['TE']).strip(); break

        # --- Centro / instituição de destino (apenas para exibição/contexto) ---
        centro_brasil = "NÃO IDENTIFICADO"
        match_centro_brasil = re.search(
            r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\s*-\s*([A-ZÀ-Ú\s]+?)\s*\d{2}\.\d{3}\.\d{3}",
            texto_brasil_upper
        )
        if match_centro_brasil:
            centro_brasil = match_centro_brasil.group(1).strip()

        # --- Faixa de temperatura (decide Tag Alert Ambiente x Refrigerado) ---
        tem_ref_brasil, tem_amb_brasil = detectar_faixas_newse(texto_brasil_upper)

        st.success("✅ NEWSE processada com sucesso.")
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(card_metrica("Centro / Instituição", centro_brasil), unsafe_allow_html=True)
        with c2: st.markdown(card_metrica("Protocolo / Estudo", estudo_brasil), unsafe_allow_html=True)
        with c3: st.markdown(card_metrica("TE Correspondente", te_brasil), unsafe_allow_html=True)
        st.write("")

        st.markdown("### 🏷️ Retirada de Tag Alert")

        if not tem_ref_brasil and not tem_amb_brasil:
            st.warning("⚠️ Não foi possível identificar a faixa de temperatura (Ambiente/Refrigerado) nesta NEWSE. Verifique o documento manualmente.")

        # Identidade estável deste upload — evita duplicar a retirada se a
        # página recarregar com o mesmo PDF ainda anexado (mesmo padrão da
        # página de Automação).
        arquivo_id_brasil = getattr(arquivo_newse_brasil, "file_id", None) or f"{arquivo_newse_brasil.name}_{arquivo_newse_brasil.size}"
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

                # Só Tag Alert — solicitações Brasil não usam TempTale (pedido
                # explícito do usuário: "para solicitações brasil não mandamos
                # TEMPTALE"). Um Tag Alert por faixa de temperatura detectada.
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
                    # Campo travado de propósito — pedido explícito do usuário:
                    # solicitações Brasil não têm um DEL# de verdade, então o
                    # identificador fica fixo como "Solicitação Brasil" (não
                    # editável) em vez de um campo de texto livre.
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

# ==========================================
# PÁGINA: GERADOR DE E-MAIL (GR)
# ==========================================
elif st.session_state.pagina_atual == "email":

    st.markdown("""
        <div style="background: linear-gradient(135deg, #1b3834 0%, #10281f 100%); padding: 20px 26px; border-radius: 12px; border-left: 6px solid #e59235; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #ffffff !important; margin: 0 0 6px 0; font-size: 18px;">📧 Gerador de E-mail (GR)</h2>
            <p style="color: #cbd5e1; margin: 0; font-size: 13px; line-height: 1.4;">
                Preencha os dados do recebimento para montar o e-mail de Goods Receipt (GR) e copie o assunto, os destinatários e o corpo já formatados.
            </p>
        </div>
    """, unsafe_allow_html=True)

    GERADOR_EMAIL_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Gerador de E-mail de Recebimento / Liberação (Goods Receipt)</title>
  <style>
    * {
      box-sizing: border-box;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    body {
      background-color: #f0f2f5;
      margin: 0;
      padding: 20px;
      color: #333;
    }
    .main-title {
      text-align: center;
      color: #0d6efd;
      margin-bottom: 25px;
      font-size: 24px;
      font-weight: 700;
    }
    .app-container {
      max-width: 1200px;
      margin: 0 auto;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
    }
    @media (max-width: 900px) {
      .app-container {
        grid-template-columns: 1fr;
      }
    }
    .card {
      background: #ffffff;
      border-radius: 8px;
      padding: 20px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.06);
      margin-bottom: 20px;
    }
    .card-title {
      color: #0d6efd;
      font-size: 16px;
      font-weight: 700;
      margin-top: 0;
      margin-bottom: 18px;
    }
    .form-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 15px;
    }
    .form-group {
      display: flex;
      flex-direction: column;
    }
    .form-group.full-width {
      grid-column: span 2;
    }
    label {
      font-size: 13px;
      color: #555;
      margin-bottom: 5px;
      font-weight: 500;
    }
    label .required {
      color: #dc3545;
      font-weight: bold;
    }
    input[type="text"], textarea {
      padding: 10px 12px;
      border: 1px solid #ced4da;
      border-radius: 6px;
      font-size: 14px;
      outline: none;
      transition: border-color 0.2s;
    }
    input[type="text"]:focus, textarea:focus {
      border-color: #0d6efd;
    }
    input[readonly] {
      background-color: #e9ecef;
      cursor: not-allowed;
      color: #495057;
      font-weight: 600;
    }
    .item-box {
      border: 1px dashed #adb5bd;
      border-radius: 6px;
      padding: 15px;
      margin-bottom: 15px;
      background-color: #fafafa;
      position: relative;
    }
    .remove-btn {
      position: absolute;
      top: 8px;
      right: 8px;
      background: #dc3545;
      color: white;
      border: none;
      border-radius: 4px;
      padding: 2px 8px;
      font-size: 12px;
      cursor: pointer;
    }
    .btn-secondary {
      background-color: #6c757d;
      color: white;
      border: none;
      padding: 8px 14px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
      margin-bottom: 15px;
    }
    .btn-secondary:hover {
      background-color: #5c636a;
    }
    .btn-primary {
      background-color: #0d6efd;
      color: white;
      border: none;
      padding: 12px;
      border-radius: 6px;
      font-weight: bold;
      font-size: 15px;
      width: 100%;
      cursor: pointer;
      transition: background 0.2s;
    }
    .btn-primary:hover {
      background-color: #0b5ed7;
    }
    .btn-copy {
      background-color: #198754;
      color: white;
      border: none;
      padding: 8px 14px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
      margin-top: 8px;
      margin-bottom: 15px;
    }
    .btn-copy:hover {
      background-color: #157347;
    }
    .readonly-box {
      background-color: #e9ecef;
      border: 1px solid #ced4da;
      padding: 10px 12px;
      border-radius: 6px;
      font-size: 14px;
      font-weight: 600;
      color: #212529;
      word-break: break-all;
      min-height: 40px;
    }
    .email-preview-container {
      border: 1px solid #ced4da;
      border-radius: 6px;
      padding: 15px;
      background: #ffffff;
      min-height: 250px;
      max-height: 450px;
      overflow-y: auto;
      font-family: Arial, sans-serif;
      font-size: 13px;
      color: #000;
      line-height: 1.4;
    }
    .preview-table {
      border-collapse: collapse;
      width: 100%;
      margin: 12px 0;
    }
    .preview-table th, .preview-table td {
      border: 1px solid #000;
      padding: 6px 8px;
      font-family: Arial, sans-serif;
      font-size: 12px;
    }
    .preview-table th {
      font-weight: bold;
      font-style: italic;
      text-align: center;
      text-transform: uppercase;
      background-color: #ffffff;
    }
    .preview-table td {
      text-align: center;
    }
    .toast {
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: #198754;
      color: white;
      padding: 10px 20px;
      border-radius: 6px;
      box-shadow: 0 4px 10px rgba(0,0,0,0.15);
      display: none;
      z-index: 1000;
      font-weight: 500;
    }
  </style>
</head>
<body>
  <div class="main-title">Gerador de E-mail de Recebimento / Liberação (Goods Receipt)</div>
  <div class="app-container">
    <!-- Coluna da Esquerda: Formulários -->
    <div>
      <form id="emailForm" onsubmit="event.preventDefault(); generateEmail();">
        <div class="card">
          <div class="card-title">1. Informações do Recebimento (Packing List / Documentação)</div>
          <div class="form-grid">
            <div class="form-group">
              <label for="grNumber">Número GR: <span class="required">*</span></label>
              <input type="text" id="grNumber" value="TO8616" readonly title="Número GR fixo">
            </div>
            <div class="form-group">
              <label for="delNumber">Delivery Number (DEL#): <span class="required">*</span></label>
              <input type="text" id="delNumber" placeholder="Ex: 8020016643" required>
            </div>
            <div class="form-group">
              <label for="protocolNumber">Protocol Number: <span class="required">*</span></label>
              <input type="text" id="protocolNumber" placeholder="Ex: CA088-1007" required>
            </div>
            <div class="form-group">
              <label for="orderNumber">Order Number: <span class="required">*</span></label>
              <input type="text" id="orderNumber" placeholder="Ex: 45801492" required>
            </div>
            <div class="form-group">
              <label for="invoiceNumber">Brazilian Invoice: <span class="required">*</span></label>
              <input type="text" id="invoiceNumber" placeholder="Ex: 40533-1" required>
            </div>
            <div class="form-group">
              <label for="cesvNumber">CESV: <span class="required">*</span></label>
              <input type="text" id="cesvNumber" placeholder="Ex: 2601002022" required>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-title">2. Itens do Recebimento (Material / Lotes)</div>
          <div id="itemsContainer">
            <!-- Item 1 -->
            <div class="item-box">
              <div class="form-group full-width" style="margin-bottom: 10px;">
                <label>DESCRIPTION (Descrição Completa do Material): <span class="required">*</span></label>
                <input type="text" class="item-desc" placeholder="Ex: DEXAMETH TAB 4MG (1BLCRDX20) CA088 OLMUL" required>
              </div>
              <div class="form-grid">
                <div class="form-group">
                  <label>BATCH NUMBER (Lote): <span class="required">*</span></label>
                  <input type="text" class="item-batch" placeholder="Ex: ADA3486" required>
                </div>
                <div class="form-group">
                  <label>EXP. DATE (Validade DD/MM/AAAA): <span class="required">*</span></label>
                  <input type="text" class="item-exp" placeholder="Ex: 30/06/2030" required>
                </div>
              </div>
              <div class="form-group full-width" style="margin-top: 10px;">
                <label>QUANTITY (Quantidade): <span class="required">*</span></label>
                <input type="text" class="item-qty" placeholder="Ex: 80" required>
              </div>
            </div>
          </div>
          <button type="button" class="btn-secondary" onclick="addItem()">+ Adicionar Mais um Item</button>
          <button type="submit" class="btn-primary">Gerar Texto do E-mail</button>
        </div>
      </form>
    </div>
    <!-- Coluna da Direita: Destinatários e Preview -->
    <div>
      <div class="card">
        <div class="card-title">3. Destinatários do E-mail (Para / CC)</div>
        <div class="form-group">
          <label>E-mails para Copiar:</label>
          <textarea id="recipients" rows="4">BMSOPSBLA@BMS.COM; Radu.Ciobanescu@bms.com; laura.sourwine@bms.com; cso.distribution@bms.com; MG-BRZ-IMPORT-CTA@bms.com; daniela.mizushima@bms.com; Giovana.Doretto2@bms.com</textarea>
        </div>
        <button type="button" class="btn-copy" onclick="copyRecipients()">Copiar Destinatários</button>
      </div>
      <div class="card">
        <div class="card-title">4. Preview do E-mail Gerado</div>

        <div class="form-group" style="margin-bottom: 5px;">
          <label>Assunto do E-mail (Subject Line):</label>
          <div class="readonly-box" id="subjectBox">BMS/GR/TO8616/DEL#</div>
        </div>
        <button type="button" class="btn-copy" onclick="copySubject()">Copiar Assunto</button>
        <div class="form-group" style="margin-bottom: 5px; margin-top: 10px;">
          <label>Corpo do E-mail (Body):</label>
          <div class="email-preview-container" id="emailBodyContainer" contenteditable="true">
            <p style="color: #6c757d; italic;">Preencha os campos ao lado e clique em "Gerar Texto do E-mail"...</p>
          </div>
        </div>
        <button type="button" class="btn-copy" onclick="copyBody()">Copiar Corpo do E-mail</button>
      </div>
    </div>
  </div>
  <div class="toast" id="toastNotification">Copiado com sucesso!</div>
  <script>
    function addItem() {
      const container = document.getElementById('itemsContainer');
      const itemBox = document.createElement('div');
      itemBox.className = 'item-box';
      itemBox.innerHTML = `
        <button type="button" class="remove-btn" onclick="this.parentElement.remove();">X</button>
        <div class="form-group full-width" style="margin-bottom: 10px;">
          <label>DESCRIPTION (Descrição Completa do Material): <span class="required">*</span></label>
          <input type="text" class="item-desc" placeholder="Ex: DEXAMETH TAB 4MG (1BLCRDX20) CA088 OLMUL" required>
        </div>
        <div class="form-grid">
          <div class="form-group">
            <label>BATCH NUMBER (Lote): <span class="required">*</span></label>
            <input type="text" class="item-batch" placeholder="Ex: ADA3486" required>
          </div>
          <div class="form-group">
            <label>EXP. DATE (Validade DD/MM/AAAA): <span class="required">*</span></label>
            <input type="text" class="item-exp" placeholder="Ex: 30/06/2030" required>
          </div>
        </div>
        <div class="form-group full-width" style="margin-top: 10px;">
          <label>QUANTITY (Quantidade): <span class="required">*</span></label>
          <input type="text" class="item-qty" placeholder="Ex: 80" required>
        </div>
      `;
      container.appendChild(itemBox);
    }
    function generateEmail() {
      const gr = document.getElementById('grNumber').value.trim();
      const del = document.getElementById('delNumber').value.trim();
      const protocol = document.getElementById('protocolNumber').value.trim();
      const order = document.getElementById('orderNumber').value.trim();
      const invoice = document.getElementById('invoiceNumber').value.trim();
      const cesv = document.getElementById('cesvNumber').value.trim();
      const subject = `BMS/GR/${gr}/DEL#${del}`;
      document.getElementById('subjectBox').innerText = subject;
      const itemBoxes = document.querySelectorAll('#itemsContainer .item-box');
      let tableRows = '';
      itemBoxes.forEach(box => {
        const desc = box.querySelector('.item-desc').value.trim();
        const batch = box.querySelector('.item-batch').value.trim();
        const exp = box.querySelector('.item-exp').value.trim();
        const qty = box.querySelector('.item-qty').value.trim();
        tableRows += `
          <tr>
            <td style="text-align: center;">${desc}</td>
            <td style="text-align: center;">${batch}</td>
            <td style="text-align: center;">${exp}</td>
            <td style="text-align: center;">${qty}</td>
          </tr>
        `;
      });
      const tableHtml = `
        <table class="preview-table">
          <thead>
            <tr>
              <th>DESCRIPTION</th>
              <th>BATCH NUMBER</th>
              <th>EXP. DATE</th>
              <th>QUANTITY</th>
            </tr>
          </thead>
          <tbody>
            ${tableRows}
          </tbody>
        </table>
      `;
      const bodyHtml = `
        <div>Dear all,</div>
        <br>
        <div>I would like to inform you that we have received at DRS the following items to ${protocol}.</div>
        <br>
        <div><strong>BRAZILIAN INVOICE</strong> ${invoice}</div>
        <div><strong>CESV</strong> ${cesv}</div>
        <div><strong>Order Number:</strong> ${order}</div>
        <div><strong>DEL#${del}</strong></div>
        ${tableHtml}
        <div>All the goods receipt has been double inspected.</div>
        <br>
        <ul style="margin-top: 0; margin-bottom: 0; padding-left: 20px;">
          <li>Find attached the signed Packing List.</li>
          <li>Find attached the Temperature Graphics received.</li>
        </ul>
      `;
      document.getElementById('emailBodyContainer').innerHTML = bodyHtml;
    }
    function showToast(msg) {
      const toast = document.getElementById('toastNotification');
      toast.innerText = msg;
      toast.style.display = 'block';
      setTimeout(() => {
        toast.style.display = 'none';
      }, 2000);
    }
    function copyRecipients() {
      const text = document.getElementById('recipients').value;
      navigator.clipboard.writeText(text);
      showToast('Destinatários copiados!');
    }
    function copySubject() {
      const text = document.getElementById('subjectBox').innerText;
      navigator.clipboard.writeText(text);
      showToast('Assunto copiado!');
    }
    function copyBody() {
      const container = document.getElementById('emailBodyContainer');

      const range = document.createRange();
      range.selectNodeContents(container);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      try {
        document.execCommand('copy');
        showToast('Corpo do e-mail copiado com formatação e tabela!');
      } catch (err) {
        showToast('Erro ao copiar!');
      }
      selection.removeAllRanges();
    }
  </script>
</body>
</html>
"""

    components.html(GERADOR_EMAIL_HTML, height=1450, scrolling=True)
