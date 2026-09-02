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

                    if p_pi != "NÃO CONSTA" and p_pi in texto_sol_upper:
                        s_pi = p_pi
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
                    seriais_newse = re.findall(r"(\d{5,7})\s*(?:AREA|CAMARA)", texto_sol_upper)
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
                    # Confirmação cruzada: quando o nome da instituição não bate por
                    # grafia diferente entre os dois sistemas, mas o CEP de destino
                    # dos dois documentos é idêntico, isso já confirma que é o mesmo
                    # endereço/centro de destino — não faz sentido bloquear a
                    # remessa só porque o nome foi escrito de um jeito diferente.
                    centro_confirmado_por_cep = (
                        s_addr != "NÃO CONSTA" and s_addr == p_addr
                        and s_centre != p_centre
                    )
                    centro_ok = (s_centre != "NÃO CONSTA" and s_centre == p_centre) or centro_confirmado_por_cep

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
                                "Razão social avaliada." if (s_centre != "NÃO CONSTA" and s_centre == p_centre)
                                else "Nome do centro escrito de forma diferente nos dois sistemas, mas confirmado pelo CEP de destino (idêntico nos dois documentos)." if centro_confirmado_por_cep
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
                            "Status": "✅ Conforme" if p_pi != "NÃO CONSTA" and s_pi == p_pi else "❌ Divergência",
                            "Observação": "Nome do investigador comparado." if s_pi == p_pi else "Investigador do Packing List não foi encontrado no texto da NEWSE."
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
