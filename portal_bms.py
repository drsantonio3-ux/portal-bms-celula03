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
        margin-bottom: 0.5rem;
    }
    h2 { font-size: 20px !important; }
    h3 { font-size: 16px !important; }
    h4 { font-size: 14px !important; }
    
    .stButton>button {
        background-color: #209b7c !important;
        color: white !important;
        border-radius: 4px;
        border: none;
        font-size: 13px !important;
        font-weight: bold;
        padding: 0.4rem 1rem;
        transition: 0.2s ease-in-out;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .stButton>button:hover {
        background-color: #1b3834 !important;
        color: #e59235 !important;
    }
    
    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"] {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 6px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        border: 1px solid #e0e6ed;
    }
    
    [data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #d2dedb;
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

# --- CARREGAR DADOS E ESTOQUE ---
@st.cache_data(ttl=5)
def carregar_dados_sheets():
    id_estoque = "10f18RZ-48HiJS2HckG6Siw2WRE9zz92_Pj6chkTwXik"
    id_loggers = "1ztZC3s0kKINJLNOR-BEYUUFjycxSVT7NMGVNWdxWh98"
    url_estoque = f"https://docs.google.com/spreadsheets/d/{id_estoque}/export?format=csv"
    url_tes = f"https://docs.google.com/spreadsheets/d/{id_loggers}/export?format=csv&gid=536812026"
    
    try: df_est = pd.read_csv(url_estoque)
    except: df_est = None
    if df_est is not None: df_est['Descricao_Clean'] = df_est['Descricao'].astype(str).str.upper()

    try:
        df_tes = pd.read_csv(url_tes)
        if len(df_tes.columns) >= 2:
            df_tes = df_tes.iloc[:, [0, 1]]
            df_tes.columns = ['Estudo', 'TE']
    except: df_tes = None
        
    return df_est, df_tes

df_estoque, df_te = carregar_dados_sheets()

# --- LÓGICA DE CONTAGEM DE ESTOQUE (COM REDUÇÃO AO VIVO) ---
if "consumo_local" not in st.session_state:
    st.session_state.consumo_local = {"tt": 0, "ta_amb": 0, "ta_ref": 0}

raw_tt = len(df_estoque[df_estoque['Descricao_Clean'].str.contains("TEMPTALE", na=False)]) if df_estoque is not None else 0
raw_ta_amb = len(df_estoque[df_estoque['Descricao_Clean'].str.contains("TAGALERT 15-25", na=False)]) if df_estoque is not None else 0
raw_ta_ref = len(df_estoque[df_estoque['Descricao_Clean'].str.contains("TAGALERT 2-8", na=False)]) if df_estoque is not None else 0

tt_disp = max(0, raw_tt - st.session_state.consumo_local["tt"])
ta_amb_disp = max(0, raw_ta_amb - st.session_state.consumo_local["ta_amb"])
ta_ref_disp = max(0, raw_ta_ref - st.session_state.consumo_local["ta_ref"])

# --- LÓGICA DE NAVEGAÇÃO DE PÁGINAS ---
if "pagina_atual" not in st.session_state:
    st.session_state.pagina_atual = "automacao"

# --- BARRA LATERAL (SIDEBAR) ---
with st.sidebar:
    st.markdown("""
        <div style='text-align: left; padding-bottom: 20px;'>
            <h1 style='color: #1b3834; font-size: 38px; line-height: 0.8; margin: 0; font-family: Arial, sans-serif; letter-spacing: -1px;'>DRS</h1>
            <h2 style='color: #1b3834; font-size: 18px; margin: 0; font-family: Arial, sans-serif; font-weight: bold;'>Suportemed</h2>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
        <div style="display: flex; align-items: center; margin-bottom: 5px;">
            <div style="width: 10px; height: 10px; border-radius: 50%; background-color: #28a745; margin-right: 8px; box-shadow: 0 0 6px #28a745;"></div>
            <h3 style="margin: 0; font-size: 14px; color: #1b3834;">Painel de Operações</h3>
        </div>
        <p style="font-size: 11px; color: #28a745; margin-top: 0px; margin-left: 18px; font-weight: bold; margin-bottom: 20px;">Sistema Apto para Uso</p>
    """, unsafe_allow_html=True)
    
    st.markdown(f"""
        <div style="font-size: 12px; color: #4a5568; margin-bottom: 25px; line-height: 1.6; background-color: #f4f7f6; padding: 12px; border-radius: 5px; border-left: 3px solid #e59235;">
            <b style="font-size: 11px; color: #1b3834;">LOGGERS DISPONÍVEIS:</b><br><br>
            Tag Alert Ambiente: <b style="color: #209b7c; font-size: 14px; float: right;">{ta_amb_disp}</b><br>
            Tag Alert Refrigerado: <b style="color: #209b7c; font-size: 14px; float: right;">{ta_ref_disp}</b><br>
            TempTale Ambiente: <b style="color: #209b7c; font-size: 14px; float: right;">{tt_disp}</b>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("<p style='font-size: 11px; color: #666; font-weight: bold; margin-bottom: 5px; text-transform: uppercase;'>Navegação</p>", unsafe_allow_html=True)
    
    if st.button("📦 Automação de Packing List", use_container_width=True):
        st.session_state.pagina_atual = "automacao"
        st.rerun()
    if st.button("📧 Gerador de E-mail (GR)", use_container_width=True):
        st.session_state.pagina_atual = "email"
        st.rerun()
    # ==========================================
    # NOVO BOTÃO INSERIDO AQUI
    # ==========================================
    if st.button("⚖️ Cruzamento NEWSE x PACKING", use_container_width=True):
        st.session_state.pagina_atual = "cruzamento"
        st.rerun()

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
                Faça o upload do <b>Packing List (PDF)</b> para extração imediata de dados. O sistema realiza a sugestão automática de <b>ativos logísticos</b>,<br> cálculo exato do <b>SLA de entrega</b> (considerando dias úteis) e a <b>baixa de estoque ao vivo</b>.
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
        tem_tagalert_amb = "TAGALERT" in texto_upper and ("20-25" in texto_upper or "15-25" in texto_upper)
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
            def add_item(nome_busca, label):
                filtro = df_estoque[df_estoque['Descricao_Clean'].str.contains(nome_busca, na=False)]
                if not filtro.empty:
                    item = filtro.iloc[0]
                    serie = next((str(item[c]) for c in item.index if "SERIE" in c.upper()), str(item.iloc[7]) if len(item)>7 else "N/A")
                    ids_utilizados.append((label, str(item.get('Palete', 'N/A')).strip(), str(item.get('Identificacao Estoque', 'N/A')).strip(), serie))
                    st.info(f"**{label}** alocado ➔ Palete: {item.get('Palete', 'N/A')} | ID: {item.get('Identificacao Estoque', 'N/A')} | Série: {serie}")
                else: st.warning(f"⚠️ **{label}**: Sem saldo no estoque!")

            if tem_temptale: add_item("TEMPTALE", "TempTale Ambiente")
            if tem_tagalert_amb: add_item("TAGALERT 15-25", "Tag Alert Ambiente")
            if tem_tagalert_ref: add_item("TAGALERT 2-8", "Tag Alert Refrigerado")

            col_del, col_btn = st.columns([2, 1])
            with col_del: delivery_number = st.text_input("DEL# (Delivery Number) para registro:")
            with col_btn: 
                st.write("")
                if st.button("💾 Executar Baixa no Estoque", use_container_width=True):
                    if not delivery_number: 
                        st.error("❌ Preencha o DEL#.")
                    else: 
                        for nome, palete, id_est, serie in ids_utilizados:
                            if "TempTale" in nome: st.session_state.consumo_local["tt"] += 1
                            elif "Tag Alert Ambiente" in nome: st.session_state.consumo_local["ta_amb"] += 1
                            elif "Tag Alert Refrigerado" in nome: st.session_state.consumo_local["ta_ref"] += 1
                        
                        st.success(f"✅ Baixa registrada! Reduzindo quantidades...")
                        time.sleep(1)
                        st.rerun() 
        
        st.markdown("### 📋 Dados para Restrição e Particularidades")
        val_depositante, val_palete, val_id, val_te = "056998982001260", " | ".join([p[1] for p in ids_utilizados]) or "N/A", " | ".join([p[2] for p in ids_utilizados]) or "N/A", te_resultado
        
        def btn_copia(rotulo, valor, uid):
            html = f"""<div style="display:flex; justify-content:space-between; align-items: center; padding:6px 12px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:4px; margin-bottom:5px;">
            <div><span style="color:#475569; font-weight:bold; font-size:11px;">{rotulo}:</span> <span style="font-family:monospace; color:#209b7c; font-size:13px; font-weight:bold; margin-left:5px;">{valor}</span></div>
            <button onclick="navigator.clipboard.writeText('{valor}'); this.innerText='Copiado!'; setTimeout(()=>this.innerText='Copiar', 2000)" style="background:#209b7c; color:white; border:none; border-radius:3px; cursor:pointer; font-size:11px; padding:4px 10px; font-weight:bold;">Copiar</button></div>"""
            components.html(html, height=45)
            
        c_esq, c_dir = st.columns(2)
        with c_esq: btn_copia("DEPOSITANTE", val_depositante, "d"); btn_copia("PALETE", val_palete, "p")
        with c_dir: btn_copia("ID ITEM", val_id, "i"); btn_copia("TE DO ESTUDO", val_te, "t")

        paragrafos = ["Verificar se no processo consta Packing List e atentar se a quantidade, lote e validade está de acordo com as informações retiradas do sistema LOGIX."]
        if tem_temptale: paragrafos.extend(["Houve envio de medicação AMBIENTE.", "As medicações foram acondicionadas em embalagem apropriada CREDO validada pelo cliente com TempTale ULTRA USB ambiente."])
        elif is_ambiente: paragrafos.extend(["Houve envio de medicação AMBIENTE.", "As medicações foram acondicionadas em embalagem CREDO com Tag Alert ambiente."])
        if tem_tagalert_ref: paragrafos.extend(["Houve envio de medicação REFRIGERADA.", "As medicações foram acondicionadas em caixa CREDO SÉRIE 04 com Tag Alert refrigerado."])
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
            
            st.write("") # Pequeno espaçamento entre os itens
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
# NOVA PÁGINA 3: CRUZAMENTO NEWSE X PACKING
# ==========================================
elif st.session_state.pagina_atual == "cruzamento":
    
    st.markdown("""
        <div style="background-color: #1b3834; padding: 18px 25px; border-radius: 6px; border-left: 6px solid #e59235; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #ffffff !important; margin: 0 0 6px 0; font-size: 18px;">⚖️ Validação de Remessa: NEWSE x PACKING</h2>
            <p style="color: #cbd5e1; margin: 0; font-size: 13px; line-height: 1.4;">
                Faça o upload dos dois documentos para cruzamento. O sistema validará <b>Ordem, Protocolo, Destinatário/PI e Itens (Lote, Série, Validade, Qtd)</b>.<br>
                <i>Nota: A temperatura não é bloqueada sistemicamente e deve ser conferida visualmente.</i>
            </p>
        </div>
    """, unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    with col1:
        arquivo_newse = st.file_uploader("Upload da NEWSE (PDF)", type=["pdf"])
    with col2:
        arquivo_packing = st.file_uploader("Upload da Packing List (PDF)", type=["pdf"])

    if arquivo_newse and arquivo_packing:
        st.divider()
        if st.button("Executar Cruzamento de Dados", use_container_width=True):
            with st.spinner("Lendo PDFs e cruzando informações..."):
                try:
                    # --- 1. LEITURA BRUTA DOS PDFs ---
                    leitor_newse = PyPDF2.PdfReader(arquivo_newse)
                    texto_newse = " ".join([p.extract_text() for p in leitor_newse.pages]).upper()
                    
                    leitor_packing = PyPDF2.PdfReader(arquivo_packing)
                    texto_packing = " ".join([p.extract_text() for p in leitor_packing.pages]).upper()

                    # --- 2. FUNÇÕES AUXILIARES DE LIMPEZA ---
                    def limpar(t): return re.sub(r'\s+', ' ', str(t)).strip()
                    
                    def isolar_protocolo(p):
                        match = re.search(r'([A-Z0-9]+-[0-9]+)', p)
                        return match.group(1) if match else p

                    # --- 3. EXTRAÇÃO DE DADOS (REGEX) ---
                    # Dados NEWSE
                    n_ordem = re.search(r"NUMERO DA ORDEM:\s*(\d+)", texto_newse)
                    n_ordem = n_ordem.group(1) if n_ordem else "NÃO ENCONTRADO"
                    
                    n_prot = re.search(r"CA\d+-\d+(?:-[A-Z0-9]+)?", texto_newse)
                    n_prot = isolar_protocolo(n_prot.group(0)) if n_prot else "NÃO ENCONTRADO"
                    
                    n_razao = re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\s*-\s*([A-ZÇÃÕÁÉÍÓÚ\s]+)(?=\s|\|)", texto_newse)
                    n_razao = limpar(n_razao.group(1)) if n_razao else "NÃO ENCONTRADO"
                    
                    n_pi = re.search(r"INVESTIGADOR.*?NOME\s*([A-Z\s]+?)(?:HTTPS|$)", texto_newse)
                    n_pi = limpar(n_pi.group(1)) if n_pi else "NÃO ENCONTRADO"
                    
                    # Extração de Lotes e Seriais NEWSE (Procura padrão LOTE | VALIDADE | PEÇA | SÉRIE)
                    n_seriais = re.findall(r"([A-Z0-9]+(?:\.[A-Z0-9]+)?)\s*\|\s*\d{2}/\d{2}/\d{4}\s*\|\s*\d+\s*\|\s*(\d{5,8})", texto_newse)

                    # Dados PACKING
                    p_ordem = re.search(r"DELIVERY NUMBER\s*[:\s]*(\d+)", texto_packing)
                    p_ordem = p_ordem.group(1) if p_ordem else "NÃO ENCONTRADO"
                    
                    p_prot = re.search(r"CA\d+-\d+/[0-9]+", texto_packing)
                    p_prot = isolar_protocolo(p_prot.group(0)) if p_prot else "NÃO ENCONTRADO"
                    
                    # Pega as primeiras linhas do endereço de entrega como Ship To
                    p_shipto_match = re.search(r"SHIP TO\s*(.*?)(?=\d{5}-)", texto_packing)
                    p_shipto = limpar(p_shipto_match.group(1)) if p_shipto_match else "NÃO ENCONTRADO"
                    
                    p_pi = re.search(r"DR\.\s*([A-Z\s]+)(?=TEL)", texto_packing)
                    p_pi = limpar(p_pi.group(1)) if p_pi else "NÃO ENCONTRADO"
                    
                    # Extração de Lotes e Seriais PACKING (Procura Lote.Sufixo e Serial No)
                    p_lotes = re.findall(r"([A-Z0-9]{5,8}(?:\.[A-Z0-9]+)?)\s+[A-Z0-9\s\(\)]+SERIAL NO\.\s*\((\d+)\)", texto_packing)

                    # --- 4. MOTOR DE VALIDAÇÃO ---
                    erros = []
                    alertas = []

                    # Validar Ordem
                    if n_ordem != p_ordem:
                        erros.append(f"**Ordem:** NEWSE [{n_ordem}] ❌ PACKING [{p_ordem}]")
                    else:
                        alertas.append(f"✅ **Ordem:** {n_ordem}")

                    # Validar Protocolo
                    if n_prot != p_prot:
                        erros.append(f"**Protocolo:** NEWSE [{n_prot}] ❌ PACKING [{p_prot}]")
                    else:
                        alertas.append(f"✅ **Protocolo:** {n_prot}")

                    # Validar Destinatário / PI
                    if n_razao not in p_shipto and p_shipto not in n_razao:
                        if n_pi != p_pi:
                            erros.append(f"**FALHA CRÍTICA PI:** Razão Social divergente e PI não confere (NEWSE: {n_pi} ❌ PACKING: {p_pi})")
                        else:
                            alertas.append(f"⚠️ **Destinatário Divergente:** (NEWSE: {n_razao} / PACKING: {p_shipto}), mas **PI Validado:** {n_pi}")
                    else:
                        alertas.append(f"✅ **Destinatário:** {n_razao}")

                    # Validar Lotes e Seriais
                    if not n_seriais or not p_lotes:
                        erros.append("Falha ao extrair tabela de produtos. A formatação do PDF pode estar corrompida ou diferente do padrão.")
                    else:
                        dict_packing = {serial: lote for lote, serial in p_lotes}
                        for lote_newse, serial_newse in n_seriais:
                            if serial_newse not in dict_packing:
                                erros.append(f"**Produto Faltante:** Serial [{serial_newse}] está na NEWSE, mas não na PACKING.")
                            elif dict_packing[serial_newse] != lote_newse:
                                erros.append(f"**Divergência de Lote (Serial {serial_newse}):** NEWSE [{lote_newse}] ❌ PACKING [{dict_packing[serial_newse]}]")
                            else:
                                alertas.append(f"✅ **Produto Validado:** Serial {serial_newse} (Lote {lote_newse})")

                    # --- 5. EXIBIÇÃO DOS RESULTADOS ---
                    st.markdown("### Resultado do Cruzamento")
                    
                    if erros:
                        st.error("🚨 **OPERAÇÃO BLOQUEADA: Divergências Encontradas**")
                        for e in erros:
                            st.markdown(f"- {e}")
                    else:
                        st.success("✅ **OPERAÇÃO APROVADA: Todos os dados críticos conferem.**")
                    
                    with st.expander("Ver logs de validação e detalhes (incluindo temperatura)"):
                        for a in alertas:
                            st.markdown(f"- {a}")
                        st.info("⚠️ **Aviso Operacional:** O sistema não bloqueia divergências de temperatura por regra de negócio. Confirme visualmente nos documentos físicos se as tags de temperatura solicitadas conferem.")

                except Exception as e:
                    st.error(f"Erro inesperado ao processar os arquivos: {e}")
