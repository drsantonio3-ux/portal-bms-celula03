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

# --- INJEÇÃO DE CSS (Design WMS / Logística) ---
st.markdown("""
    <style>
    .stApp { background-color: #f0f4f8; }
    
    h1, h2, h3, h4, h5, h6 {
        color: #1b3834 !important;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        font-weight: 600;
    }
    
    .stButton>button {
        background-color: #209b7c !important;
        color: white !important;
        border-radius: 4px;
        border: none;
        font-weight: bold;
        padding: 0.5rem 1rem;
        transition: 0.2s ease-in-out;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .stButton>button:hover {
        background-color: #1b3834 !important;
        color: #e59235 !important;
    }
    
    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"] {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 8px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        border: 1px solid #eaedf0;
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
            <h1 style='color: #1b3834; font-size: 42px; line-height: 0.8; margin: 0; font-family: Arial, sans-serif; letter-spacing: -2px;'>DRS</h1>
            <h2 style='color: #1b3834; font-size: 22px; margin: 0; font-family: Arial, sans-serif; font-weight: bold;'>Suportemed</h2>
        </div>
    """, unsafe_allow_html=True)
    
    # Você pode trocar o link do "src" abaixo pelo link da imagem real da logo pequena da DRS
    st.markdown(f"""
        <div style="display: flex; align-items: center; margin-bottom: 10px;">
            <img src="https://via.placeholder.com/16/209b7c/209b7c?text=+" style="width: 16px; height: 16px; border-radius: 3px; margin-right: 8px;" alt="Logo DRS">
            <h3 style="margin: 0; font-size: 16px; color: #1b3834;">Painel de Operações</h3>
        </div>
        <div style="font-size: 13px; color: #4a5568; margin-bottom: 20px; line-height: 1.8; background-color: #f8f9fa; padding: 10px; border-radius: 5px; border-left: 3px solid #e59235;">
            <b>LOGGERS DISPONÍVEIS:</b><br>
            Tag Alert Ambiente: <b style="color: #209b7c; font-size: 14px;">{ta_amb_disp}</b><br>
            Tag Alert Refrigerado: <b style="color: #209b7c; font-size: 14px;">{ta_ref_disp}</b><br>
            TempTale Ambiente: <b style="color: #209b7c; font-size: 14px;">{tt_disp}</b>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("---")
    st.markdown("<p style='font-size: 12px; color: #666; font-weight: bold; margin-bottom: 5px;'>Navegação de Sistemas</p>", unsafe_allow_html=True)
    
    # Botões que funcionam como Links de navegação
    if st.button("📦 Automação de Packing List", use_container_width=True):
        st.session_state.pagina_atual = "automacao"
        st.rerun()
    if st.button("📧 Gerador de E-mail (GR)", use_container_width=True):
        st.session_state.pagina_atual = "email"
        st.rerun()

# ==========================================
# ROTEADOR DE PÁGINAS (EXIBE APENAS A PÁGINA SELECIONADA)
# ==========================================

if st.session_state.pagina_atual == "automacao":
    
    # --- CABEÇALHO DO SISTEMA ---
    st.markdown("""
        <div style="background-color: #1b3834; padding: 15px 25px; border-radius: 8px; border-left: 8px solid #209b7c; display: flex; align-items: center; margin-bottom: 20px;">
            <div>
                <h2 style="color: #ffffff !important; margin: 0; font-size: 24px;">Automação de Packing List (SLA e Estoque)</h2>
            </div>
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
        c1.metric("Destino", cidade_destino)
        c2.metric("Protocolo / Estudo", estudo_encontrado)
        c3.metric("TE Correspondente", te_resultado)

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
                        # Reduz os estoques visualmente na hora
                        for nome, palete, id_est, serie in ids_utilizados:
                            if "TempTale" in nome: st.session_state.consumo_local["tt"] += 1
                            elif "Tag Alert Ambiente" in nome: st.session_state.consumo_local["ta_amb"] += 1
                            elif "Tag Alert Refrigerado" in nome: st.session_state.consumo_local["ta_ref"] += 1
                        
                        st.success(f"✅ Baixa registrada! Reduzindo quantidades...")
                        time.sleep(1) # Pausa rápida para a mensagem ser lida antes da tela atualizar
                        st.rerun() # Atualiza a tela para os números laterais caírem
        
        st.markdown("### 📋 Dados para Restrição e Particularidades")
        val_depositante, val_palete, val_id, val_te = "056998982001260", " | ".join([p[1] for p in ids_utilizados]) or "N/A", " | ".join([p[2] for p in ids_utilizados]) or "N/A", te_resultado
        
        def btn_copia(rotulo, valor, uid):
            html = f"""<div style="display:flex; justify-content:space-between; padding:8px 15px; background:#f4f7f6; border:1px solid #d2dedb; border-radius:4px; margin-bottom:5px;">
            <span style="color:#1b3834; font-weight:bold; width: 130px;">{rotulo}:</span> <span style="font-family:monospace; color:#209b7c;">{valor}</span>
            <button onclick="navigator.clipboard.writeText('{valor}'); this.innerText='Copiado!'; setTimeout(()=>this.innerText='Copiar', 2000)" style="background:#209b7c; color:white; border:none; border-radius:3px; cursor:pointer; font-size:12px; padding:2px 10px;">Copiar</button></div>"""
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
        
        components.html(f"""<button onclick="navigator.clipboard.writeText(`{texto_final}`); this.innerText='📋 Texto Copiado!';" style="background:#e59235; color:white; font-weight:bold; padding:10px; border:none; border-radius:5px; width:100%; cursor:pointer;">📋 Copiar Particularidades</button>""", height=45)

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
        <div style="background-color: #1b3834; padding: 15px 25px; border-radius: 8px; border-left: 8px solid #209b7c; display: flex; align-items: center; margin-bottom: 20px;">
            <div>
                <h2 style="color: #ffffff !important; margin: 0; font-size: 24px;">📧 Gerador de E-mail (Goods Receipt)</h2>
            </div>
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
        if 'tabela_itens' not in st.session_state:
            st.session_state.tabela_itens = pd.DataFrame([{"DESCRIPTION": "", "BATCH": "", "EXP_DATE": "", "QUANTITY": ""}])
        
        df_itens = st.data_editor(st.session_state.tabela_itens, num_rows="dynamic", use_container_width=True, hide_index=True)
    
    with col_preview:
        st.markdown("#### 3. Destinatários (To / CC)")
        lista_emails = "BMSOPSBLA@BMS.COM; Radu.Ciobanescu@bms.com; laura.sourwine@bms.com; cso.distribution@bms.com; MG-BRZ-IMPORT-CTA@bms.com; daniela.mizushima@bms.com; Giovana.Doretto2@bms.com"
        st.code(lista_emails, language="text")
        
        components.html(f"""<button onclick="navigator.clipboard.writeText('{lista_emails}'); this.innerText='Copiado!';" style="background:#209b7c; color:white; border:none; border-radius:4px; padding:5px 15px; cursor:pointer; font-weight:bold; margin-bottom:15px;">Copiar Destinatários</button>""", height=40)
        
        st.markdown("#### 4. Preview do E-mail")
        assunto_base = f"BMS /GR/{gr_num if gr_num else '[GR]'}/DEL# {del_num if del_num else '[DEL]'}"
        st.text_input("Assunto do E-mail:", value=assunto_base)
        components.html(f"""<button onclick="navigator.clipboard.writeText('{assunto_base}'); this.innerText='Copiado!';" style="background:#209b7c; color:white; border:none; border-radius:4px; padding:5px 15px; cursor:pointer; font-weight:bold; margin-bottom:15px;">Copiar Assunto</button>""", height=40)

        corpo_email = f"Dear all,\n\nI would like to inform you that we have received at DRS the following items to {prot_num if prot_num else '[Protocol Number]'}.\n\n"
        corpo_email += f"BRAZILIAN INVOICE: {br_inv if br_inv else '[Invoice]'}\n"
        corpo_email += f"CESV: {cesv if cesv else '[CESV]'}\n"
        corpo_email += f"Order Number: {ord_num if ord_num else '[Order Number]'}\n"
        corpo_email += f"DEL#: {del_num if del_num else '[DEL#]'}\n\n"
        
        corpo_email += "DESCRIPTION | BATCH NUMBER | EXP. DATE | QUANTITY\n"
        corpo_email += "-"*60 + "\n"
        for idx, row in df_itens.iterrows():
            d = row.get("DESCRIPTION", "")
            b = row.get("BATCH", "")
            e = row.get("EXP_DATE", "")
            q = row.get("QUANTITY", "")
            if any([d, b, e, q]): 
                corpo_email += f"{d} | {b} | {e} | {q}\n"

        st.text_area("Corpo do E-mail (Body):", value=corpo_email, height=250)
        
        corpo_js = corpo_email.replace('\n', '\\n').replace("'", "\\'")
        components.html(f"""<button onclick="navigator.clipboard.writeText('{corpo_js}'); this.innerText='Corpo Copiado!';" style="background:#e59235; color:white; border:none; border-radius:4px; padding:8px 20px; cursor:pointer; font-weight:bold; width:100%;">Copiar Corpo do E-mail</button>""", height=50)
