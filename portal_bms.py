import streamlit as st
from pypdf import PdfReader
import pandas as pd
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import re
import urllib.request
import json
import time


def extrair_texto_pdf(leitor, separador=""):
    """Extrai o texto de todas as páginas de um PDF.
    Ignora páginas sem texto extraível (ex: PDFs escaneados/imagem),
    o que evita que o app quebre com um upload inesperado."""
    return separador.join([(pagina.extract_text() or "") for pagina in leitor.pages])


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


def verificar_senha():
    def senha_inserida():
        if st.session_state["password_input"] == SENHA_ACESSO:
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
if "baixas_registradas" not in st.session_state:
    st.session_state.baixas_registradas = {}  # arquivo_id -> {delivery_number, itens, data_uso}
if "alocacao_pendente" not in st.session_state:
    st.session_state.alocacao_pendente = False

# --- CARREGAR DADOS E ESTOQUE ---
@st.cache_data(ttl=1)
def carregar_dados_sheets():
    id_estoque = st.secrets.get("ID_PLANILHA_ESTOQUE", "10f18RZ-48HiJS2HckG6Siw2WRE9zz92_Pj6chkTwXik")
    id_loggers = st.secrets.get("ID_PLANILHA_LOGGERS", "1ztZC3s0kKINJLNOR-BEYUUFjycxSVT7NMGVNWdxWh98")

    cb = int(time.time())
    url_estoque = f"https://docs.google.com/spreadsheets/d/{id_estoque}/export?format=csv&cb={cb}"
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
    with col_pdf: arquivo_pdf = st.file_uploader("📥 Arraste o PDF da Packing List aqui", type=["pdf"])
    with col_data: data_recebimento = st.date_input("Data de Recebimento", datetime.today())

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

        tem_temptale = "TEMPTALE" in texto_upper or "TT4" in texto_upper
        tem_tagalert_ref = "TAGALERT" in texto_upper and ("2-8" in texto_upper or "REFRIGER" in texto_upper or "36-46F" in texto_upper)
        tem_tagalert_amb = "TAGALERT" in texto_upper and ("20-25" in texto_upper or "15-25" in texto_upper or "2-30C" in texto_upper or not tem_tagalert_ref)

        CITOTOXICOS = ["BORTEZOMIB", "SPRYCEL", "DASATINIB", "PACLITAXEL", "TAXOL", "CYCLOPHOSPHAMIDE", "CICLOFOSFAMIDA"]
        tem_citotoxico = any(c in texto_upper for c in CITOTOXICOS)

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

                if tem_temptale: allocate_logger("TEMPTALE", "TempTale Ambiente")
                if tem_tagalert_amb: allocate_logger("TAGALERT 15-25", "Tag Alert Ambiente")
                if tem_tagalert_ref: allocate_logger("TAGALERT 2-8", "Tag Alert Refrigerado")

                if tem_citotoxico:
                    st.markdown(
                        "<div style='font-size:12px; color:#92400e; background:#fff7ed; border:1px solid #fdba74; "
                        "border-radius:6px; padding:6px 10px; margin:6px 0;'>🧪 Medicação citotóxica identificada "
                        "— por regra, essa carga segue em caixa separada e precisa de um TempTale adicional.</div>",
                        unsafe_allow_html=True
                    )
                    allocate_logger("TEMPTALE", "TempTale Extra (Citotóxico – Caixa Separada)")

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
                                urllib.request.urlopen(req, timeout=25)

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

        if "PACLITAXEL" in texto_upper or "TAXOL" in texto_upper:
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
                    texto_sol_upper = texto_sol.upper()
                    texto_sol_limpo = re.sub(r'\s+', ' ', texto_sol)

                    leitor_packing = PdfReader(arquivo_packing)
                    texto_packing = extrair_texto_pdf(leitor_packing, " ")
                    texto_packing_upper = texto_packing.upper()
                    texto_packing_limpo = re.sub(r'\s+', ' ', texto_packing)

                    def limpar(t): return re.sub(r'\s+', ' ', str(t)).strip()

                    # --- EXTRAÇÃO DOCUMENTO FONTE (SOLICITAÇÃO / NEWSE) ---
                    s_prot_match = re.search(r"(CA\d+-\d+)", texto_sol_upper)
                    s_prot = s_prot_match.group(1) if s_prot_match else "NÃO CONSTA"

                    s_ship_match = re.search(r"(?:ORDEM|ORDER|SHIPMENT)[^\d]*(\d{8,12})", texto_sol_upper)
                    s_ship = s_ship_match.group(1) if s_ship_match else (re.search(r"\b(8\d{9})\b", texto_sol_limpo).group(1) if re.search(r"\b(8\d{9})\b", texto_sol_limpo) else "NÃO CONSTA")

                    s_centre = "NÃO CONSTA"
                    if "PRUDENTE" in texto_sol_upper or "CAMARGO" in texto_sol_upper:
                        s_centre = "A. C. CAMARGO / FUNDAÇÃO PRUDENTE"
                    elif "FUNDACAO PIO XII" in texto_sol_upper or "FUNDAÇÃO PIO XII" in texto_sol_upper:
                        s_centre = "FUNDACAO PIO XII"
                    elif "HOSPITAL SÃO LUCAS" in texto_sol_upper or "HOSPITAL SAO LUCAS" in texto_sol_upper:
                        s_centre = "HOSPITAL SAO LUCAS DA PUCRS"

                    s_cep_match = re.search(r"CEP[^\d]*(\d{5}-?\d{3})", texto_sol_upper)
                    s_addr = s_cep_match.group(1).replace("-", "") if s_cep_match else (re.search(r"\b(\d{8})\b", texto_sol_upper).group(1) if re.search(r"\b(\d{8})\b", texto_sol_upper) else "NÃO CONSTA")

                    s_pi = "NÃO CONSTA"
                    for medico in ["JAYR SCHMIDT", "FLAVIO AUGUSTO", "MARIZA SCHAAN", "ARINILDA"]:
                        if medico in texto_sol_upper:
                            s_pi = medico; break

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

                    p_centre = "NÃO CONSTA"
                    p_shipto_bloco = texto_packing_upper.split("SHIP TO")[-1] if "SHIP TO" in texto_packing_upper else texto_packing_upper
                    if "CAMARGO" in p_shipto_bloco or "PRUDENTE" in p_shipto_bloco:
                        p_centre = "A. C. CAMARGO / FUNDAÇÃO PRUDENTE"
                    elif "FUNDAÇÃO PIO XII" in p_shipto_bloco or "FUNDACAO PIO XII" in p_shipto_bloco:
                        p_centre = "FUNDACAO PIO XII"
                    elif "HOSPITAL SAO LUCAS" in p_shipto_bloco or "HOSPITAL SÃO LUCAS" in p_shipto_bloco:
                        p_centre = "HOSPITAL SAO LUCAS DA PUCRS"

                    p_cep_match = re.search(r"(\d{5}-?\d{3})", p_shipto_bloco)
                    p_addr = p_cep_match.group(1).replace("-", "") if p_cep_match else "NÃO CONSTA"

                    p_pi = "NÃO CONSTA"
                    for medico in ["JAYR SCHMIDT", "FLAVIO AUGUSTO", "MARIZA SCHAAN", "ARINILDA"]:
                        if medico in p_shipto_bloco or medico in texto_packing_upper:
                            p_pi = medico; break

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

                    # Coleta de Seriais da Solicitação confrontando diretamente com os seriais encontrados na packing list
                    seriais_sol = [s for s in seriais_packing if s in texto_sol_upper]
                    s_qty = str(len(seriais_sol)) if len(seriais_sol) > 0 else "NÃO CONSTA"

                    # Validação estrita focada apenas nos números de série
                    seriais_faltantes = [s for s in seriais_packing if s not in texto_sol_upper]
                    seriais_status_ok = len(seriais_faltantes) == 0 and len(seriais_packing) > 0 and len(seriais_packing) == len(seriais_sol)

                    # --- COMPARAÇÃO ESTRITA ---
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
                            "Status": "✅ Conforme" if s_centre != "NÃO CONSTA" and s_centre == p_centre else "❌ Divergência",
                            "Observação": "Razão social avaliada." if s_centre == p_centre else "Divergência na razão social / centro."
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
                            "Status": "✅ Conforme" if s_pi != "NÃO CONSTA" and s_pi == p_pi else "❌ Divergência",
                            "Observação": "Nome do investigador comparado." if s_pi == p_pi else "Divergência no nome do investigador."
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
                            "Documento Fonte": f"Seriais: {', '.join(seriais_sol)}",
                            "Documento Validado": f"Seriais: {', '.join(seriais_packing)}",
                            "Status": "✅ Conforme" if s_qty == p_qty and seriais_status_ok else "❌ Divergência",
                            "Observação": "Números de série conferem integralmente." if (s_qty == p_qty and seriais_status_ok) else "Divergência ou divergência nos números de série entre os documentos."
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
                Módulo em construção.
            </p>
        </div>
    """, unsafe_allow_html=True)

    st.info("🚧 Este módulo ainda não foi implementado. Assim que as regras do e-mail de GR forem definidas, esta página passa a gerar o texto automaticamente, como as demais.")
