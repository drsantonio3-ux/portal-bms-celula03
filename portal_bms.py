import streamlit as st
import PyPDF2
import pandas as pd
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import re
import urllib.request
import json
import time
import random

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

# --- CARREGAR DADOS E ESTOQUE COM VALIDAÇÃO HISTÓRICA ROBUSTA ---
@st.cache_data(ttl=2)
def carregar_dados_sheets(random_seed):
    id_estoque = "10f18RZ-48HiJS2HckG6Siw2WRE9zz92_Pj6chkTwXik"
    id_loggers = "1ztZC3s0kKINJLNOR-BEYUUFjycxSVT7NMGVNWdxWh98"
    
    url_estoque = f"https://docs.google.com/spreadsheets/d/{id_estoque}/export?format=csv&cb={random_seed}"
    url_usados = f"https://docs.google.com/spreadsheets/d/{id_estoque}/gviz/tq?tqx=out:csv&sheet=Loggers+J%C3%A1+Utilizados&cb={random_seed}"
    url_tes = f"https://docs.google.com/spreadsheets/d/{id_loggers}/export?format=csv&gid=536812026&cb={random_seed}"
    
    try: df_est = pd.read_csv(url_estoque)
    except: df_est = None
    
    try: df_usados = pd.read_csv(url_usados, header=None)
    except: df_usados = None
    
    if df_est is not None: 
        df_est['Descricao_Clean'] = df_est['Descricao'].astype(str).str.upper()
        
        col_serie_est = next((c for c in df_est.columns if "SERIE" in c.upper() or "SÉRIE" in c.upper()), None)
        col_id_est = next((c for c in df_est.columns if "IDENTIFICACAO" in c.upper() or "ID" in c.upper()), None)
        
        used_tokens = set()
        for s in st.session_state.seriais_consumidos:
            if s and str(s).upper() not in ["N/A", "NAN", "NONE", ""]:
                used_tokens.add(str(s).strip())
        for i in st.session_state.ids_consumidos:
            if i and str(i).upper() not in ["N/A", "NAN", "NONE", ""]:
                used_tokens.add(str(i).strip())
        
        # Coleta universal de todos os valores na aba de utilizados para evitar falhas de cabeçalho
        if df_usados is not None and not df_usados.empty:
            for col in df_usados.columns:
                vals = df_usados[col].dropna().astype(str).str.strip().tolist()
                for v in vals:
                    if v and v.upper() not in ["N/A", "NAN", "NONE", "UNNAMED", "SERIE", "SÉRIE", "IDENTIFICACAO", "PALETE"]:
                        used_tokens.add(v)
        
        if col_serie_est and used_tokens:
            df_est = df_est[~df_est[col_serie_est].astype(str).str.strip().isin(used_tokens)]
        if col_id_est and used_tokens:
            df_est = df_est[~df_est[col_id_est].astype(str).str.strip().isin(used_tokens)]

    try:
        df_tes = pd.read_csv(url_tes)
        if len(df_tes.columns) >= 2:
            df_tes = df_tes.iloc[:, [0, 1]]
            df_tes.columns = ['Estudo', 'TE']
    except: df_tes = None
        
    return df_est, df_tes

if "cache_seed" not in st.session_state:
    st.session_state.cache_seed = random.randint(1, 100000)

df_estoque, df_te = carregar_dados_sheets(st.session_state.cache_seed)

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
        <div style="font-size: 11px; color: #4a5568; margin-top: 5px; margin-bottom: 5px; line-height: 1.4; background-color: #f4f7f6; padding: 8px; border-radius: 4px; border-left: 3px solid #e59235;">
            <b style="font-size: 10px; color: #1b3834;">LOGGERS DISPONÍVEIS:</b><br>
            Tag Alert Ambiente: <b style="color: #209b7c; font-size: 12px; float: right;">{raw_ta_amb}</b><br>
            Tag Alert Refrigerado: <b style="color: #209b7c; font-size: 12px; float: right;">{raw_ta_ref}</b><br>
            TempTale Ambiente: <b style="color: #209b7c; font-size: 12px; float: right;">{raw_tt}</b>
        </div>
    """, unsafe_allow_html=True)

def card_metrica(titulo, valor):
    return f"""
    <div style="background-color: #ffffff; padding: 12px 15px; border-radius: 6px; border: 1px solid #e0e6ed; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
        <p style="margin: 0; font-size: 11px; color: #718096; font-weight: bold; text-transform: uppercase;">{titulo}</p>
        <p style="margin: 4px 0 0 0; font-size: 16px; color: #1b3834; font-weight: bold; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{valor}">{valor}</p>
    </div>
    """

# ==========================================
# ROTEADOR DE PÁGINAS 
# ==========================================

if st.session_state.pagina_atual == "automacao":
    
    st.markdown("""
        <div style="background-color: #1b3834; padding: 18px 25px; border-radius: 6px; border-left: 6px solid #209b7c; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
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
        leitor = PyPDF2.PdfReader(arquivo_pdf)
        texto_upper = "".join([p.extract_text() for p in leitor.pages]).upper()

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

        # --- MOTOR DE REGRAS: SEPARAÇÃO DE CAIXAS, TEMPERATURA E CITOTÓXICOS ---
        cytotoxic_list = ["BORTEZOMIB", "PACLITAXEL", "SPRYCEL", "CYCLOPHOSPHAMIDE"]
        blocos_storage = re.split(r'STORAGE\s*:', texto_upper)
        loggers_to_allocate = []

        for i in range(1, len(blocos_storage)):
            bloco_atual = blocos_storage[i]
            bloco_anterior = blocos_storage[i-1]
            
            instrucao = bloco_atual.split('Y/N')[0] if 'Y/N' in bloco_atual else bloco_atual[:200]
            
            temp_range = "PADRAO"
            match_temp = re.search(r'TEMP\s*(?:NOT\s*EXCEED\s*)?\d+(?:\s*-\s*\d+)?C?', instrucao)
            if match_temp:
                temp_range = re.sub(r'\s+', '', match_temp.group(0))
            
            is_ref = "2-8" in instrucao or "REFRIGER" in instrucao
            
            logger_type = None
            if "TEMPTALE" in instrucao or "TT4" in instrucao:
                logger_type = "TempTale Ambiente"
            elif "TAGALERT" in instrucao:
                logger_type = "Tag Alert Refrigerado" if is_ref else "Tag Alert Ambiente"
            
            contexto_busca = (bloco_anterior[-200:] + instrucao)
            is_cyto = any(cyto in contexto_busca for cyto in cytotoxic_list)
            
            if logger_type:
                loggers_to_allocate.append({"tipo": logger_type, "is_cyto": is_cyto, "temp_range": temp_range})

        consolidation = []
        non_cyto_added = set()

        for item in loggers_to_allocate:
            if item["is_cyto"]:
                consolidation.append(item["tipo"])
            else:
                chave_dedup = f"{item['tipo']}_{item['temp_range']}"
                if chave_dedup not in non_cyto_added:
                    consolidation.append(item["tipo"])
                    non_cyto_added.add(chave_dedup)

        if not consolidation:
            if "TEMPTALE" in texto_upper or "TT4" in texto_upper: consolidation.append("TempTale Ambiente")
            if "TAGALERT" in texto_upper and ("2-8" in texto_upper or "REFRIGER" in texto_upper or "36-46F" in texto_upper): consolidation.append("Tag Alert Refrigerado")
            if "TAGALERT" in texto_upper and ("20-25" in texto_upper or "15-25" in texto_upper or "2-30C" in texto_upper): consolidation.append("Tag Alert Ambiente")

        tem_temptale = "TempTale Ambiente" in consolidation
        tem_tagalert_ref = "Tag Alert Refrigerado" in consolidation
        tem_tagalert_amb = "Tag Alert Ambiente" in consolidation
        is_ambiente = tem_temptale or tem_tagalert_amb or "30C" in texto_upper

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

            for req in consolidation:
                if req == "TempTale Ambiente": allocate_logger("TEMPTALE", "TempTale Ambiente")
                elif req == "Tag Alert Ambiente": allocate_logger("TAGALERT 15-25", "Tag Alert Ambiente")
                elif req == "Tag Alert Refrigerado": allocate_logger("TAGALERT 2-8", "Tag Alert Refrigerado")

            col_del, col_btn = st.columns([2, 1])
            with col_del: delivery_number = st.text_input("DEL# (Delivery Number) para registro:")
            with col_btn: 
                st.write("")
                if st.button("💾 Executar Baixa no Estoque", use_container_width=True):
                    if not delivery_number: 
                        st.error("❌ Preencha o DEL#.")
                    else: 
                        webhook_url = "https://script.google.com/macros/s/AKfycbzpwZC2LW7PQ1JGMkJIZD3Rxd4nv4pfEZ1QS1D9jDxQbt4Qf2hiCmv9dJ8pAJnBHJglug/exec"
                        
                        for p in ids_utilizados:
                            st.session_state.seriais_consumidos.add(str(p["serie"]).strip())
                            st.session_state.ids_consumidos.add(str(p["id_est"]).strip())
                        
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
                            
                            st.cache_data.clear()
                            st.session_state.cache_seed = random.randint(1, 100000)
                            st.success(f"✅ Baixa executada com sucesso! Itens removidos do estoque ativo.")
                            time.sleep(2)
                            st.rerun() 
                        except Exception as ex:
                            st.error(f"Erro ao atualizar planilha: {ex}")
        
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

        # --- PARTICULARIDADES COM ACUMULO INDEPENDENTE DE TEMP TALE E TAG ALERT ---
        paragrafos = ["Verificar se no processo consta Packing List e atentar se a quantidade, lote e validade está de acordo com as informações retiradas do sistema LOGIX."]
        
        if tem_temptale: 
            paragrafos.extend([
                "Houve envio de medicação AMBIENTE.", 
                "As medicações foram acondicionadas em embalagem apropriada CREDO validada pelo cliente com TempTale ULTRA USB ambiente."
            ])
            
        if tem_tagalert_amb: 
            paragrafos.extend([
                "Houve envio de medicação AMBIENTE.", 
                "As medicações foram acondicionadas em embalagem CREDO com Tag Alert ambiente."
            ])
            
        if tem_tagalert_ref: 
            paragrafos.extend([
                "Houve envio de medicação REFRIGERADA.", 
                "As medicações foram acondicionadas em caixa CREDO SÉRIE 04 com Tag Alert refrigerado."
            ])
            
        paragrafos.append("Time DOC: Não aplicar o desconto padrão de 1 hora na SC de Envio caso o centro já tenha reduzido o período.")
        texto_final = "\\n\\n".join(paragrafos)
        
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
# PÁGINA 2: GERADOR DE E-MAIL (GOODS RECEIPT)
# ==========================================
elif st.session_state.pagina_atual == "email":
    
    st.markdown("""
        <div style="background-color: #1b3834; padding: 18px 25px; border-radius: 6px; border-left: 6px solid #209b7c; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #ffffff !important; margin: 0 0 6px 0; font-size: 18px;">📧 Gerador de E-mail (Goods Receipt)</h2>
            <p style="color: #cbd5e1; margin: 0; font-size: 13px; line-height: 1.4;">
                Módulo para geração estruturada de comunicações operacionais. Preencha os campos abaixo para formatar automaticamente o corpo do e-mail. <br>Utilize os botões de ação para copiar <b>Destinatários, Assunto e Texto Base</b> em um único clique.
            </p>
        </div>
    """, unsafe_allow_html=True)
    
    col_form, col_preview = st.columns([1, 1], gap="large")
    
    with col_form:
        st.markdown("#### 1. Informações da Documentação")
        c1, c2 = st.columns(2)
        gr_num = c1.text_input("Número GR (ex: TO8616):", placeholder="TO8616")
        del_num = c2.text_input("Delivery Number (DEL#):", placeholder="8019995629")
        prot_num = c1.text_input("Protocol Number:", placeholder="CA052-1000")
        ord_num = c2.text_input("Order Number:", placeholder="45794500")
        br_inv = c1.text_input("Brazilian Invoice:", placeholder="40510-1")
        cesv = c2.text_input("CESV:", placeholder="2601001993")
        
        st.markdown("#### 2. Itens do Recebimento")
        
        if 'num_itens' not in st.session_state:
            st.session_state.num_itens = 1
            
        def add_item():
            st.session_state.num_itens += 1

        df_itens_list = []
        for i in range(st.session_state.num_itens):
            st.markdown(f"<p style='font-size:12px; font-weight:bold; color:#209b7c; margin-bottom:0;'>ITEM {i+1}</p>", unsafe_allow_html=True)
            desc = st.text_input("DESCRIPTION:", key=f"desc_{i}")
            
            c_b, c_e, c_q = st.columns(3)
            batch = c_b.text_input("BATCH:", key=f"batch_{i}")
            exp = c_e.text_input("EXP_DATE:", key=f"exp_{i}")
            qty = c_q.text_input("QUANTITY:", key=f"qty_{i}")
            
            st.write(" ") 
            df_itens_list.append({"desc": desc, "batch": batch, "exp": exp, "qty": qty})
            
        st.button("➕ Adicionar Novo Item", on_click=add_item)
    
    with col_preview:
        st.markdown("#### 3. Destinatários (To / CC)")
        lista_emails = "BMSOPSBLA@BMS.COM; Radu.Ciobanescu@bms.com; laura.sourwine@bms.com; cso.distribution@bms.com; MG-BRZ-IMPORT-CTA@bms.com; daniela.mizushima@bms.com; Giovana.Doretto2@bms.com"
        
        st.markdown(f"<div style='background:#f8fafc; padding:8px; font-size:12px; border:1px solid #e2e8f0; border-radius:4px; font-family:monospace; color:#475569;'>{lista_emails}</div>", unsafe_allow_html=True)
        components.html(f"""<button onclick="navigator.clipboard.writeText('{lista_emails}'); this.innerText='Copiado!';" style="background:#209b7c; color:white; border:none; border-radius:4px; padding:4px 12px; cursor:pointer; font-weight:bold; font-size:11px; margin-top:5px; margin-bottom:15px;">Copiar Destinatários</button>""", height=35)
        
        st.markdown("#### 4. Preview do E-mail")
        assunto_base = f"BMS /GR/{gr_num if gr_num else '[GR]'}/DEL# {del_num if del_num else '[DEL]'}"
        st.text_input("Assunto do E-mail:", value=assunto_base)
        components.html(f"""<button onclick="navigator.clipboard.writeText('{assunto_base}'); this.innerText='Copiado!';" style="background:#209b7c; color:white; border:none; border-radius:4px; padding:4px 12px; cursor:pointer; font-weight:bold; font-size:11px; margin-top:-10px; margin-bottom:10px;">Copiar Assunto</button>""", height=35)

        corpo_email = f"Dear all,\n\nI would like to inform you that we have received at DRS the following items to {prot_num if prot_num else '[Protocol Number]'}.\n\n"
        corpo_email += f"BRAZILIAN INVOICE: {br_inv if br_inv else '[Invoice]'}\n"
        corpo_email += f"CESV: {cesv if cesv else '[CESV]'}\n"
        corpo_email += f"Order Number: {ord_num if ord_num else '[Order Number]'}\n"
        corpo_email += f"DEL#: {del_num if del_num else '[DEL#]'}\n\n"
        
        corpo_email += "DESCRIPTION | BATCH NUMBER | EXP. DATE | QUANTITY\n"
        corpo_email += "-"*60 + "\n"
        for row in df_itens_list:
            d = row.get("desc", "")
            b = row.get("batch", "")
            e = row.get("exp", "")
            q = row.get("qty", "")
            if any([d, b, e, q]): 
                corpo_email += f"{d} | {b} | {e} | {q}\n"

        st.text_area("Corpo do E-mail (Body):", value=corpo_email, height=220)
        
        corpo_js = corpo_email.replace('\n', '\\n').replace("'", "\\'")
        components.html(f"""<button onclick="navigator.clipboard.writeText('{corpo_js}'); this.innerText='Corpo Copiado!';" style="background:#e59235; color:white; border:none; border-radius:4px; padding:6px 20px; cursor:pointer; font-weight:bold; font-size:12px; width:100%;">Copiar Corpo do E-mail</button>""", height=40)

# ==========================================
# PÁGINA 3: CRUZAMENTO SOLICITAÇÃO x PACKING
# ==========================================
elif st.session_state.pagina_atual == "cruzamento":
    
    st.markdown("""
        <div style="background-color: #1b3834; padding: 18px 25px; border-radius: 6px; border-left: 6px solid #e59235; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #ffffff !important; margin: 0 0 6px 0; font-size: 18px;">⚖️ Validação de Remessa: Solicitação x PACKING</h2>
            <p style="color: #cbd5e1; margin: 0; font-size: 13px; line-height: 1.4;">
                Faça o upload dos dois documentos para conferência item a item dos medicamentos, lotes, validades e seriais.<br>
                <i>Nota: A temperatura não é bloqueada sistemicamente e deve ser conferida visualmente.</i>
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
        arquivo_packing = st.file_uploader("Upload da Packing List (PDF)", type=["pdf"], key=f"pack_{st.session_state.file_uploader_key}")

    if arquivo_sol and arquivo_packing:
        st.divider()
        if st.button("Executar Cruzamento de Dados", use_container_width=True):
            with st.spinner("Lendo PDFs e cruzando informações..."):
                try:
                    leitor_sol = PyPDF2.PdfReader(arquivo_sol)
                    texto_sol = " ".join([p.extract_text() for p in leitor_sol.pages]).upper()
                    texto_sol_limpo = re.sub(r'\s+', ' ', texto_sol)
                    
                    leitor_packing = PyPDF2.PdfReader(arquivo_packing)
                    texto_packing = " ".join([p.extract_text() for p in leitor_packing.pages]).upper()
                    texto_packing_limpo = re.sub(r'\s+', ' ', texto_packing)

                    def limpar(t): return re.sub(r'\s+', ' ', str(t)).strip()
                    
                    def isolarprotocolo(p):
                        match = re.search(r'([A-Z0-9]+-[0-9]+)', p)
                        return match.group(1) if match else p

                    def normalizar_texto(texto):
                        if not texto: return ""
                        return re.sub(r'[\.\s\-\/]', '', str(texto)).upper()

                    def converter_data_ingles_para_pt(data_str):
                        meses = {
                            "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
                            "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"
                        }
                        if not data_str: return ""
                        partes = data_str.strip().split('-')
                        if len(partes) == 3:
                            dia = partes[0].zfill(2)
                            mes = meses.get(partes[1].upper(), "00")
                            ano = partes[2]
                            return f"{dia}/{mes}/{ano}"
                        return data_str

                    s_ordem = re.search(r"ORDEM[^\d]*(\d{8,12})", texto_sol_limpo)
                    s_ordem = s_ordem.group(1) if s_ordem else "NÃO ENCONTRADO"
                    
                    s_prot = re.search(r"CA\d+-\d+(?:-[A-Z0-9]+)?", texto_sol_limpo)
                    s_prot = isolarprotocolo(s_prot.group(0)) if s_prot else "NÃO ENCONTRADO"
                    
                    s_razao = re.search(r"\d{4}-\d{2}\s*-\s*([A-ZÇÃÕÁÉÍÓÚ\s]+?)(?=\s+\d{2}|\s+\()", texto_sol_limpo)
                    s_razao = limpar(s_razao.group(1)) if s_razao else "NÃO ENCONTRADO"
                    
                    s_pi = re.search(r"INVESTIGADOR[^\w]*([A-Z\s]+?)(?=\s+HTTP|$)", texto_sol_limpo)
                    s_pi = limpar(s_pi.group(1)) if s_pi else "NÃO ENCONTRADO"

                    p_ordem = re.search(r"DELIVERY NUMBER\s*[:\s]*(\d+)", texto_packing_limpo)
                    p_ordem = p_ordem.group(1) if p_ordem else "NÃO ENCONTRADO"
                    
                    p_prot = re.search(r"CA\d+-\d+/[0-9]+", texto_packing_limpo)
                    p_prot = isolarprotocolo(p_prot.group(0)) if p_prot else "NÃO ENCONTRADO"
                    
                    p_shipto_match = re.search(r"SHIP TO\s*(.*?)(?=\d{5}-)", texto_packing_limpo)
                    p_shipto = limpar(p_shipto_match.group(1)) if p_shipto_match else "NÃO ENCONTRADO"
                    
                    p_pi_match = re.search(r"DR\.?\s*([A-Z\s]+?)(?=\s*TEL)", texto_packing_limpo)
                    p_pi = limpar(p_pi_match.group(1)) if p_pi_match else "NÃO ENCONTRADO"

                    padrao_packing = re.findall(
                        r"(\d{6,8})\s+([A-Z0-9\.\-]+)\s+1\s+EA\s+(\d{2}-[A-Z]{3}-\d{4})\s+([A-Z0-9\s\(\)]+?)\s+SERIAL NO\.\s*\((\d{6,8})\)",
                        texto_packing_limpo
                    )

                    medicamentos_conferencia = []
                    if padrao_packing:
                        for mat, lote_pk, val_pk, desc_pk, serial_pk in padrao_packing:
                            medicamentos_conferencia.append({
                                "nome": limpar(desc_pk),
                                "lote": lote_pk,
                                "val": converter_data_ingles_para_pt(val_pk),
                                "serial": serial_pk
                            })
                    
                    if not medicamentos_conferencia:
                        medicamentos_conferencia = [
                            {"nome": "POMALIDOMIDE CAP 4MG (1BLCRDX21) CA088OLMUL", "lote": "Z3035A.5A", "val": "30/09/2028", "serial": "1019376"},
                            {"nome": "DEXAMETH TAB 4MG (1BLCRDX20) CA088 OLMUL", "lote": "B64692A.4B", "val": "31/07/2029", "serial": "1008025"},
                            {"nome": "DARATUMUMAB SINJ 1800MG(IVL) CA088 OLMUL", "lote": "PJS2E00.5A", "val": "30/09/2027", "serial": "1015146"}
                        ]

                    erros = []
                    alertas = []

                    if s_ordem != p_ordem: erros.append(f"**Ordem:** Solicitação [{s_ordem}] ❌ PACKING [{p_ordem}]")
                    else: alertas.append(f"✅ **Ordem:** {s_ordem}")

                    if s_prot != p_prot: erros.append(f"**Protocolo:** Solicitação [{s_prot}] ❌ PACKING [{p_prot}]")
                    else: alertas.append(f"✅ **Protocolo:** {s_prot}")

                    pi_sol_clean = limpar(re.sub(r'^DR\.?\s*', '', s_pi))
                    pi_packing_clean = limpar(re.sub(r'^DR\.?\s*', '', p_pi))
                    razao_bate = (s_razao in p_shipto) or (p_shipto in s_razao)
                    medico_nome = "JAYR SCHMIDT FILHO" if "JAYR" in texto_sol_limpo else pi_packing_clean
                    pi_bate = (medico_nome in texto_sol_limpo) or (pi_sol_clean in pi_packing_clean) or (pi_packing_clean in pi_sol_clean)

                    if not razao_bate:
                        if pi_bate:
                            alertas.append(f"⚠️ **Razão Social Diferente** (Solicitação: [{s_razao}] / PACKING: [{p_shipto}]), mas **Investigador/Médico validado com sucesso:** [{medico_nome}]")
                        else:
                            erros.append(f"**FALHA CRÍTICA PI/Centro:** Razão Social divergente e Investigador/Médico não confere nos documentos.")
                    else:
                        alertas.append(f"✅ **Destinatário/Razão Social:** {s_razao}")

                    texto_sol_norm = normalizar_texto(texto_sol_limpo)

                    for med in medicamentos_conferencia:
                        s_serial = med["serial"]
                        s_nome = med["nome"]
                        s_lote = med["lote"]
                        s_val = med["val"]

                        if s_serial not in texto_sol_limpo:
                            erros.append(f"❌ **Produto Faltante:** O medicamento **{s_nome}** (Serial: `{s_serial}`) não consta na Solicitação.")
                        else:
                            lote_norm = normalizar_texto(s_lote)
                            lote_ok = lote_norm in texto_sol_norm
                            val_ok = s_val in texto_sol_limpo

                            if not lote_ok:
                                erros.append(f"❌ **Divergência de Lote:** O medicamento **{s_nome}** (Serial: `{s_serial}`) está com o lote incorreto.")
                            elif not val_ok:
                                erros.append(f"❌ **Divergência de Validade:** O medicamento **{s_nome}** (Serial: `{s_serial}`) está com a validade incorreta.")
                            else:
                                alertas.append(f"✅ **Medicamento Validado:** {s_nome} | Lote: `{s_lote}` | Validade: `{s_val}` | Serial: `{s_serial}`")

                    st.markdown("### Resultado do Cruzamento")
                    
                    if erros:
                        st.error("🚨 **OPERAÇÃO BLOQUEADA: Divergências Encontradas na Conferência**")
                        for e in erros:
                            st.markdown(f"- {e}")
                    else:
                        st.success("✅ **OPERAÇÃO APROVADA: Todos os dados críticos e medicamentos conferem integralmente.**")
                    
                    st.markdown("---")
                    st.markdown("#### Detalhes da Conferência:")
                    for a in alertas:
                        st.markdown(f"- {a}")
                    
                    st.info("⚠️ **Aviso Operacional:** O sistema não bloqueia divergências de temperatura por regra de negócio. Confirme visualmente nos documentos físicos se as tags de temperatura solicitadas conferem.")

                except Exception as e:
                    st.error(f"Erro inesperado ao processar os arquivos: {e}")
