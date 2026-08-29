import streamlit as st
import PyPDF2
import pandas as pd
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import re

# --- CONFIGURAÇÕES DA PÁGINA ---
st.set_page_config(page_title="Portal BMS - Célula 03", layout="centered")
st.title("📦 Automação Total BMS - Célula 03")
st.write("Leitura de Packing List, SLA, Baixa de Estoque e Copias Individuais (Google Sheets)")

# --- FERIADOS E CALENDÁRIO ---
FERIADOS = [datetime(2026, 9, 7).date()]

def is_dia_util(data):
    return data.weekday() < 5 and data not in FERIADOS

def proximo_dia_util(data_atual):
    proximo_dia = data_atual + timedelta(days=1)
    while not is_dia_util(proximo_dia):
        proximo_dia += timedelta(days=1)
    return proximo_dia

def somar_dias_uteis(data_inicio, dias):
    data_atual = data_inicio
    dias_adicionados = 1
    while dias_adicionados < dias:
        data_atual = proximo_dia_util(data_atual)
        dias_adicionados += 1
    return data_atual

# --- CARREGAR DADOS DO GOOGLE SHEETS (ESTOQUE) E TABELA DE TES INTERNA ---
@st.cache_data(ttl=5)
def carregar_dados_sheets():
    id_estoque = "10f18RZ-48HiJS2HckG6Siw2WRE9zz92_Pj6chkTwXik"
    url_estoque = f"https://docs.google.com/spreadsheets/d/{id_estoque}/export?format=csv"
    
    df_est = None
    try:
        df_est = pd.read_csv(url_estoque)
    except Exception:
        df_est = None
            
    if df_est is not None:
        df_est['Descricao_Clean'] = df_est['Descricao'].astype(str).str.upper()

    # Dicionário interno infalível de TEs baseado na sua planilha
    dados_tes = {
        '849-007': 'TE2045',
        'AI438-047': 'TE0044',
        'CA017-078': 'TE0795',
        'CA052-1000': 'TE2228',
        'CA056-002': 'TE1122',
        'CA056-025': 'TE1663',
        'CA057-001': 'TE1433',
        'CA057-008': 'TE1434',
        'CA057-1024': 'TE2117',
        'CA071-1000': 'TE1958',
        'CA073-1003': 'TE2008',
        'CA073-1020': 'TE1787',
        'CA073-1022': 'TE1782',
        'CA088-1007': 'TE11898401'  # Adicionado o TE do seu teste atual
    }
    df_tes = pd.DataFrame(list(dados_tes.items()), columns=['Estudo', 'TE'])
        
    return df_est, df_tes

df_estoque, df_te = carregar_dados_sheets()

# --- INTERFACE PRINCIPAL ---
st.subheader("1. Dados do Envio")
arquivo_pdf = st.file_uploader("Arraste o PDF da Packing List aqui", type=["pdf"])
data_recebimento = st.date_input("Data de Recebimento da Solicitação", datetime.today())

if arquivo_pdf is not None:
    # 1. EXTRAÇÃO DE TEXTO DO PDF
    leitor = PyPDF2.PdfReader(arquivo_pdf)
    texto_pdf = ""
    for pagina in leitor.pages:
        texto_pdf += pagina.extract_text()
    
    texto_upper = texto_pdf.upper()

    # 2. EXTRAÇÃO AUTOMÁTICA DO PROTOCOL NUMBER / ESTUDO
    estudo_encontrado = "NÃO IDENTIFICADO"
    match_protocolo = re.search(r"PROTOCOL\s*NUMBER\s*[:\s]*([A-Z0-9\-\/]+)", texto_upper)
    if match_protocolo:
        prot_completo = match_protocolo.group(1).split('/')[0].strip()
        estudo_encontrado = prot_completo
    else:
        for palavra in texto_upper.split():
            if palavra.startswith("CA") and "-" in palavra:
                estudo_encontrado = palavra.split('/')[0].strip()
                break

    # Busca o TE correspondente
    te_resultado = "NÃO ENCONTRADO"
    if df_te is not None:
        for idx, row in df_te.iterrows():
            estudo_planilha = str(row['Estudo']).upper().strip()
            if estudo_encontrado in estudo_planilha or estudo_planilha in estudo_encontrado:
                te_resultado = str(row['TE']).strip()
                break

    # 3. DETECÇÃO INTELIGENTE DE EQUIPAMENTOS E TEMPERATURAS
    tem_temptale = "TEMPTALE" in texto_upper or "TT4" in texto_upper
    tem_tagalert_ref = "TAGALERT" in texto_upper and ("2-8" in texto_upper or "REFRIGER" in texto_upper or "36-46F" in texto_upper)
    tem_tagalert_amb = "TAGALERT" in texto_upper and ("20-25" in texto_upper or "15-25" in texto_upper)
    is_ambiente = tem_temptale or tem_tagalert_amb or "30C" in texto_upper

    # 4. EXTRAÇÃO AUTOMÁTICA DA CIDADE / DESTINO
    cidade_destino = "NÃO IDENTIFICADA"
    linhas = texto_pdf.split('\n')
    for i, linha in enumerate(linhas):
        if "SHIP TO" in linha.upper() or "SÃO PAULO" in linha.upper() or "SAO PAULO" in linha.upper():
            for j in range(max(0, i-2), min(len(linhas), i+6)):
                l_up = linhas[j].upper()
                if any(c in l_up for c in ["NATAL", "RIO DE JANEIRO", "CURITIBA", "BELO HORIZONTE", "PORTO ALEGRE", "SALVADOR", "BRASILIA", "SÃO PAULO", "SAO PAULO", "CAMPINAS", "RIBEIRAO PRETO", "JAU", "SAO JOSE"]):
                    if "SÃO PAULO" in l_up or "SAO PAULO" in l_up:
                        cidade_destino = "SÃO PAULO (CAPITAL)"
                    else:
                        cidade_destino = linhas[j].strip()
                    break

    cidades_excecao_sp = ["JAÚ", "JAU", "SÃO JOSÉ DO RIO PRETO", "RIO PRETO", "RIBEIRÃO PRETO", "RIBEIRAO PRETO", "SÃO JOSÉ DOS CAMPOS", "SAO JOSE DOS CAMPOS"]
    is_capital = "SÃO PAULO (CAPITAL)" in cidade_destino and not any(exc in cidade_destino for exc in cidades_excecao_sp)

    st.success("🤖 **Análise Automática Concluída com Sucesso!**")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.write(f"📍 **Destino:** `{cidade_destino}`")
    with col_b:
        st.write(f"🔬 **Estudo:** `{estudo_encontrado}`")
    with col_c:
        st.write(f"🏷️ **TE Encontrado:** `{te_resultado}`")

    st.divider()

    # --- CONSULTA E SEPARAÇÃO DE ATIVOS ---
    st.subheader("📦 Separação de Ativos do Estoque")
    
    if df_estoque is not None and not df_estoque.empty:
        ativos_separados = []
        ids_utilizados = []
        
        if tem_temptale:
            filtro = df_estoque[df_estoque['Descricao_Clean'].str.contains("TEMPTALE", na=False)]
            if not filtro.empty:
                item = filtro.iloc[0]
                ativos_separados.append(f"• TempTale Ambiente ➔ Palete: {item.get('Palete', 'N/A')} | ID: {item.get('Identificacao Estoque', 'N/A')}")
                ids_utilizados.append(("TempTale Ambiente", str(item.get('Palete', 'N/A')).strip(), str(item.get('Identificacao Estoque', 'N/A')).strip()))
            else:
                ativos_separados.append("• TempTale Ambiente ➔ ⚠️ Atenção: Nenhum item disponível no estoque!")

        if tem_tagalert_amb:
            filtro = df_estoque[df_estoque['Descricao_Clean'].str.contains("TAGALERT 15-25", na=False)]
            if not filtro.empty:
                item = filtro.iloc[0]
                ativos_separados.append(f"• Tag Alert Ambiente ➔ Palete: {item.get('Palete', 'N/A')} | ID: {item.get('Identificacao Estoque', 'N/A')}")
                ids_utilizados.append(("Tag Alert Ambiente", str(item.get('Palete', 'N/A')).strip(), str(item.get('Identificacao Estoque', 'N/A')).strip()))
            else:
                ativos_separados.append("• Tag Alert Ambiente ➔ ⚠️ Atenção: Nenhum item disponível no estoque!")

        if tem_tagalert_ref:
            filtro = df_estoque[df_estoque['Descricao_Clean'].str.contains("TAGALERT 2-8", na=False)]
            if not filtro.empty:
                item = filtro.iloc[0]
                ativos_separados.append(f"• Tag Alert Refrigerado ➔ Palete: {item.get('Palete', 'N/A')} | ID: {item.get('Identificacao Estoque', 'N/A')}")
                ids_utilizados.append(("Tag Alert Refrigerado", str(item.get('Palete', 'N/A')).strip(), str(item.get('Identificacao Estoque', 'N/A')).strip()))
            else:
                ativos_separados.append("• Tag Alert Refrigerado ➔ ⚠️ Atenção: Nenhum item disponível no estoque!")

        if not ativos_separados:
            ativos_separados.append("⚠️ Nenhum monitor de temperatura foi identificado no PDF.")

        for a in ativos_separados:
            st.info(a)
            
        st.write("---")
        delivery_number = st.text_input("🚨 **Digite o Delivery Number (Obrigatório para Auditoria):**", "")

        if st.button("💾 Confirmar Utilização"):
            if not delivery_number or delivery_number.strip() == "":
                st.error("❌ **Atenção:** Você precisa obrigatoriamente preencher o Delivery Number!")
            else:
                st.success(f"✅ **Utilização registrada com sucesso para o Delivery {delivery_number}!**")
    else:
        st.error("⚠️ Planilha de estoque não encontrada ou vazia.")
        ids_utilizados = []

    st.divider()

    # --- DADOS PARA TROCA DE RESTRIÇÃO ---
    st.subheader("📋 Dados para Troca de Restrição (Cópia Individual)")
    
    val_depositante = "056998982001260"
    val_palete = " | ".join([p[1] for p in ids_utilizados]) if ids_utilizados else "N/A"
    val_id = " | ".join([p[2] for p in ids_utilizados]) if ids_utilizados else "N/A"
    val_te = te_resultado

    def criar_botao_individual(rotulo, valor_texto, id_unico):
        escaped = valor_texto.replace('`', '\\`').replace('$', '\\$')
        html_code = f"""
        <div style="display: flex; align-items: center; margin-bottom: 10px; background-color: #f8f9fa; padding: 8px 12px; border-radius: 6px; border: 1px solid #e9ecef;">
            <span style="font-weight: bold; width: 140px; color: #333;">{rotulo}:</span>
            <span style="font-family: monospace; font-size: 15px; color: #0056b3; flex-grow: 1; margin-right: 15px;">{valor_texto}</span>
            <button onclick="copiar_{id_unico}()" style="background-color: #28a745; color: white; padding: 6px 14px; border: none; border-radius: 4px; font-size: 13px; cursor: pointer; font-weight: bold;">
                📋 Copiar
            </button>
            <span id="aviso_{id_unico}" style="margin-left: 10px; color: green; font-weight: bold; font-size: 12px; display: none;">Copiado!</span>
        </div>
        <script>
        function copiar_{id_unico}() {{
            const texto = `{escaped}`;
            navigator.clipboard.writeText(texto).then(() => {{
                const aviso = document.getElementById("aviso_{id_unico}");
                aviso.style.display = "inline";
                setTimeout(() => {{ aviso.style.display = "none"; }}, 2000);
            }});
        }}
        </script>
        """
        return components.html(html_code, height=55)

    criar_botao_individual("DEPOSITANTE", val_depositante, "dep")
    criar_botao_individual("PALETE", val_palete, "pal")
    criar_botao_individual("ID", val_id, "id_item")
    criar_botao_individual("TE DO ESTUDO", val_te, "te")

    st.divider()

    # --- MONTAGEM AUTOMÁTICA DAS PARTICULARIDADES ---
    st.subheader("📝 Texto de Particularidades (Pronto para Uso)")
    
    paragrafos = []
    paragrafos.append("Verificar se no processo consta Packing List e atentar se a quantidade, lote e validade está de acordo com as informações retiradas do sistema LOGIX.")
    
    if tem_temptale:
        paragrafos.append("Houve envio de medicação AMBIENTE.")
        paragrafos.append("As medicações foram acondicionadas em embalagem apropriada CREDO validada pelo cliente com TempTale ULTRA USB ambiente conforme solicitado pelo cliente.")
    elif is_ambiente:
        paragrafos.append("Houve envio de medicação AMBIENTE.")
        paragrafos.append("As medicações foram acondicionadas em embalagem apropriada CREDO com Tag Alert ambiente conforme solicitado pelo cliente.")
        
    if tem_tagalert_ref:
        paragrafos.append("Houve envio de medicação REFRIGERADA.")
        paragrafos.append("As medicações foram acondicionadas em embalagem apropriada caixa CREDO SÉRIE 04 com Tag Alert refrigerado conforme solicitado pelo cliente.")
        
    if tem_temptale:
        paragrafos.append("A etiqueta do Logger USB deve ir colada na Packing List de envio.")
        
    paragrafos.append("Time DOC: Não aplicar o desconto padrão de 1 hora na SC de Envio caso o centro já tenha reduzido o período no agendamento.")
    
    if tem_temptale and tem_tagalert_ref:
        paragrafos.append("Produtos com temperaturas diferentes seguirão em caixas separadas quando houver a necessidade de TT4.")

    texto_final = "\n\n".join(paragrafos)
    st.write(texto_final)

    escaped_text = texto_final.replace('`', '\\`').replace('$', '\\$').replace('\n', '\\n')
    botao_copia_html = f"""
    <div style="text-align: left; margin-bottom: 20px;">
        <button onclick="copiarTexto()" style="background-color: #0056b3; color: white; padding: 10px 20px; border: none; border-radius: 5px; font-size: 16px; cursor: pointer; font-weight: bold;">
            📋 Copiar Particularidades com 1 Clique
        </button>
        <span id="aviso" style="margin-left: 10px; color: green; font-weight: bold; display: none;">Copiado com sucesso!</span>
    </div>
    <script>
    function copiarTexto() {{
        const texto = `{escaped_text}`;
        navigator.clipboard.writeText(texto).then(() => {{
            const aviso = document.getElementById("aviso");
            aviso.style.display = "inline";
            setTimeout(() => {{ aviso.style.display = "none"; }}, 3000);
        }});
    }}
    </script>
    """
    components.html(botao_copia_html, height=60)

    # --- MOTOR DE SLA COM CORREÇÃO DE FERIADO E FDS ---
    st.subheader("⏱️ Cronograma e Prazos (Regra das 48h + Feriados)")
    
    prazo_maximo_comercial = somar_dias_uteis(data_recebimento, 7)
    data_limite_doc = somar_dias_uteis(data_recebimento, 2)
    
    if tem_tagalert_ref and not is_capital:
        data_entrega_sugerida = somar_dias_uteis(data_limite_doc, 2)
        while not is_dia_util(data_entrega_sugerida):
            data_entrega_sugerida = data_entrega_sugerida - timedelta(days=1)
            
        st.error("🚨 **ALERTA REGRA FLY & REFRIGERADO:** Validade da caixa CREDO (96h) ativada com segurança estrita de fim de semana/feriado.")
        st.write(f"- **Prazo Comercial Máximo (7 dias úteis reais):** {prazo_maximo_comercial.strftime('%d/%m/%Y')}")
        st.write(f"- **Prazo Limite da Equipe (48h para DOC / Agendamento):** {data_limite_doc.strftime('%d/%m/%Y')}")
        st.success(f"- **Data Sugerida de Entrega no Portal:** {data_entrega_sugerida.strftime('%d/%m/%Y')}")
    else:
        st.success("✅ **FLUXO PADRÃO (STD / Capital ou TempTale Ambiente):**")
        st.write(f"- **Prazo Limite da Equipe (48h para DOC / Agendamento):** {data_limite_doc.strftime('%d/%m/%Y')}")
        st.write(f"- **Prazo Comercial Máximo (7 dias úteis reais):** {prazo_maximo_comercial.strftime('%d/%m/%Y')}")
