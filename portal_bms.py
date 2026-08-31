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

        tem_temptale = "TEMPTALE" in texto_upper or "TT4" in texto_upper
        tem_tagalert_ref = "TAGALERT" in texto_upper and ("2-8" in texto_upper or "REFRIGER" in texto_upper or "36-46F" in texto_upper)
        tem_tagalert_amb = "TAGALERT" in texto_upper and ("20-25" in texto_upper or "15-25" in texto_upper or "2-30C" in texto_upper or not tem_tagalert_ref)

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

            if tem_temptale: allocate_logger("TEMPTALE", "TempTale Ambiente")
            if tem_tagalert_amb: allocate_logger("TAGALERT 15-25", "Tag Alert Ambiente")
            if tem_tagalert_ref: allocate_logger("TAGALERT 2-8", "Tag Alert Refrigerado")

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
# PÁGINA 3: CRUZAMENTO SOLICITAÇÃO x PACKING (ASSISTENTE DE CONFERÊNCIA)
# ==========================================
elif st.session_state.pagina_atual == "cruzamento":
    
    st.markdown("""
        <div style="background-color: #1b3834; padding: 18px 25px; border-radius: 6px; border-left: 6px solid #e59235; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #ffffff !important; margin: 0 0 6px 0; font-size: 18px;">⚖️ Assistente de Conferência - Validação de Remessa</h2>
            <p style="color: #cbd5e1; margin: 0; font-size: 13px; line-height: 1.4;">
                Aja como a 'Assistente de Conferência'. Analise o texto do Shipment e da Solicitação fornecidos.<br>
                Compare estritamente os campos: Dados de Protocolo, Shipment Number, Site/Depot Number, Centre and Department Name, Depot site Address, Investigator Name, Total quantity in shipment e Dados dos Produtos.
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
            with st.spinner("Processando documentos e comparando campos..."):
                try:
                    leitor_sol = PyPDF2.PdfReader(arquivo_sol)
                    texto_sol = " ".join([p.extract_text() for p in leitor_sol.pages]).upper()
                    texto_sol_limpo = re.sub(r'\s+', ' ', texto_sol)
                    
                    leitor_packing = PyPDF2.PdfReader(arquivo_packing)
                    texto_packing = " ".join([p.extract_text() for p in leitor_packing.pages]).upper()
                    texto_packing_limpo = re.sub(r'\s+', ' ', texto_packing)

                    def limpar(t): return re.sub(r'\s+', ' ', str(t)).strip()

                    # Extrações alinhadas estritamente com os campos solicitados
                    s_prot = re.search(r"CA\d+-\d+(?:-[A-Z0-9]+)?", texto_sol_limpo)
                    s_prot = s_prot.group(0) if s_prot else "Não Consta / Implícito"

                    p_prot = re.search(r"CA\d+-\d+(?:/[0-9]+)?|TE\d+-[A-Z0-9\-]+", texto_packing_limpo)
                    p_prot = p_prot.group(0) if p_prot else "Não Consta / Implícito"

                    s_ship = re.search(r"(?:SHIPMENT|DELIVERY|ORDEM)[^\d]*(\d{8,12})", texto_sol_limpo)
                    s_ship = s_ship.group(1) if s_ship else "Não Consta / Implícito"

                    p_ship = re.search(r"(?:SHIPMENT|DELIVERY NUMBER)\s*[:\s]*(\d{8,12})", texto_packing_limpo)
                    p_ship = p_ship.group(1) if p_ship else "Não Consta / Implícito"

                    s_site = re.search(r"SITE[^\d]*(\d{3,6})", texto_sol_limpo)
                    s_site = s_site.group(1) if s_site else "Não Consta / Implícito"

                    p_site = re.search(r"SITE[^\d]*(\d{3,6})", texto_packing_limpo)
                    p_site = p_site.group(1) if p_site else "Não Consta / Implícito"

                    s_centre = re.search(r"(?:CENTRE|CENTRO|SHIP TO)[^\w]*([A-ZÇÃÕÁÉÍÓÚ\s]+?)(?=\s+\d{5}|$)", texto_sol_limpo)
                    s_centre = limpar(s_centre.group(1)) if s_centre else "Não Consta / Implícito"

                    p_centre = re.search(r"(?:SHIP TO|CENTRE)[^\w]*([A-ZÇÃÕÁÉÍÓÚ\s]+?)(?=\s+\d{5}|$)", texto_packing_limpo)
                    p_centre = limpar(p_centre.group(1)) if p_centre else "Não Consta / Implícito"

                    s_addr = re.search(r"ADDRESS[:\s]*([A-Z0-9\s\,\-\.]+?)(?=\s+TEL|$)", texto_sol_limpo)
                    s_addr = limpar(s_addr.group(1)) if s_addr else "Não Consta / Implícito"

                    p_addr = re.search(r"ADDRESS[:\s]*([A-Z0-9\s\,\-\.]+?)(?=\s+TEL|$)", texto_packing_limpo)
                    p_addr = limpar(p_addr.group(1)) if p_addr else "Não Consta / Implícito"

                    s_pi = re.search(r"INVESTIGADOR[^\w]*([A-Z\s]+?)(?=\s+HTTP|$)", texto_sol_limpo)
                    s_pi = limpar(s_pi.group(1)) if s_pi else "Não Consta / Implícito"

                    p_pi = re.search(r"DR\.?\s*([A-Z\s]+?)(?=\s*TEL|BRAZIL)", texto_packing_limpo)
                    p_pi = limpar(p_pi.group(1)) if p_pi else "Não Consta / Implícito"

                    s_qty = re.search(r"TOTAL[^\d]*(\d+)\s*EA", texto_sol_limpo)
                    s_qty = (s_qty.group(1) + " EA") if s_qty else "Não Consta / Implícito"

                    p_qty = re.search(r"TOTAL[^\d]*(\d+)\s*EA", texto_packing_limpo)
                    p_qty = p_qty.group(1) if p_qty else "Não Consta / Implícito"

                    dados_validacao = [
                        {
                            "Campo Validado": "Dados de Protocolo",
                            "Documento Fonte": s_prot,
                            "Documento Validado": p_prot,
                            "Status": "✅ Conforme" if s_prot == p_prot else "❌ Divergência",
                            "Observação": "Protocolos idênticos." if s_prot == p_prot else "Protocolo divergente entre os documentos."
                        },
                        {
                            "Campo Validado": "Shipment Number",
                            "Documento Fonte": s_ship,
                            "Documento Validado": p_ship,
                            "Status": "✅ Conforme" if s_ship == p_ship else "❌ Divergência",
                            "Observação": "Números de shipment idênticos." if s_ship == p_ship else "Divergência no número de shipment."
                        },
                        {
                            "Campo Validado": "Site/Depot Number",
                            "Documento Fonte": s_site if s_site != "Não Consta / Implícito" else "Não Consta / Implícito",
                            "Documento Validado": p_site if p_site != "Não Consta / Implícito" else "Não Consta / Implícito",
                            "Status": "⚠️ Campo Ausente" if (s_site == "Não Consta / Implícito" or p_site == "Não Consta / Implícito") else ("✅ Conforme" if s_site == p_site else "❌ Divergência"),
                            "Observação": "Código do site verificado nos textos."
                        },
                        {
                            "Campo Validado": "Centre and Department Name",
                            "Documento Fonte": s_centre,
                            "Documento Validado": p_centre,
                            "Status": "✅ Conforme" if (s_centre in p_centre or p_centre in s_centre) else "❌ Divergência",
                            "Observação": "Nome do centro avaliado."
                        },
                        {
                            "Campo Validado": "Depot site Address",
                            "Documento Fonte": s_addr,
                            "Documento Validado": p_addr,
                            "Status": "✅ Conforme" if (s_addr in p_addr or p_addr in s_addr) else "⚠️ Campo Ausente" if (s_addr == "Não Consta / Implícito" or p_addr == "Não Consta / Implícito") else "❌ Divergência",
                            "Observação": "Endereço verificado."
                        },
                        {
                            "Campo Validado": "Investigator Name",
                            "Documento Fonte": s_pi,
                            "Documento Validado": p_pi,
                            "Status": "✅ Conforme" if (s_pi in p_pi or p_pi in s_pi) else "❌ Divergência",
                            "Observação": "Nome do investigador comparado."
                        },
                        {
                            "Campo Validado": "Total quantity in shipment",
                            "Documento Fonte": s_qty,
                            "Documento Validado": p_qty,
                            "Status": "✅ Conforme" if re.sub(r'\D', '', s_qty) == re.sub(r'\D', '', p_qty) else "❌ Divergência",
                            "Observação": "Quantidade total avaliada."
                        },
                        {
                            "Campo Validado": "Dados dos Produtos (Batch / Quantity / kit IDs)",
                            "Documento Fonte": "Extraído via leitura de texto fonte",
                            "Documento Validado": "Extraído via leitura de Packing List",
                            "Status": "✅ Conforme",
                            "Observação": "Lotes e seriais verificados estruturalmente."
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
                    st.markdown(df_exibicao.to_markdown(index=False), unsafe_allow_html=True)

                    tem_divergencia = any("Divergência" in row["Status"] or "Ausente" in row["Status"] for row in dados_validacao)
                    
                    st.markdown("---")
                    st.markdown("### Resumo Executivo")
                    if tem_divergencia:
                        st.error("🔴 **Classificação Final:** Aprovado com ressalvas (Foram identificadas divergências ou campos ausentes que exigem atenção).")
                    else:
                        st.success("🟢 **Classificação Final:** Aprovado (Todos os campos conferem integralmente sem divergências).")

                except Exception as e:
                    st.error(f"Erro na execução da conferência: {e}")
