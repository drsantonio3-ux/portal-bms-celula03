# -*- coding: utf-8 -*-
"""Checklist de Particularidades da página BMS Brasil - Solicitações.
 
Ao subir a NEWSE, o usuário escolhe MEDICAÇÃO ou EQUIPAMENTO / SUPRIMENTO e
o portal gera o modelo fixo de cada categoria.
"""
 
import json
import re
 
import streamlit as st
import streamlit.components.v1 as components
 
VERSAO_CHECKLIST_BRASIL = "Brasil v1"
 
CATEGORIA_MEDICACAO = "MEDICAÇÃO"
CATEGORIA_SUPRIMENTO = "EQUIPAMENTO / SUPRIMENTO"
 
OBS_CS = "A SC e Minuta deverá ser emitida no CNPJ do Centro de destino."
EMBALAGEM_SUPRIMENTO = "Papelão P/M/G"
 
ANEXO_MINUTAS = "Minutas"
ANEXO_FORMULARIO = "Formulário de Remessa"
ANEXO_FICHA = "Ficha de segurança de produtos perigosos"
ANEXO_BATERIA = "DECLARAÇÃO DE BATERIA DE LÍTIO"
 
OBS_WHS_UN3481 = "Identificar o volume com a etiqueta UN3481 – para envio de equipamentos."
OBS_WHS_EXCEPTED = "Etiquetar os volumes com etiqueta excepted quantities."
 
OPCAO_VALIDADE_NAO = "NÃO"
OPCAO_VALIDADE_SIM = "SIM – OBRIGATÓRIO AUTORIZAÇÃO DO CLIENTE ANEXA"
 
OPCAO_EQUIP_SIM = "SIM"
OPCAO_EQUIP_NAO = "N/A"
 
# As 4 medicações CYTOTOXIC (mesma regra da Automação)
CITOTOXICAS = [
    (re.compile(r"BORTEZOMIB"), "Bortezomib (Velcade)"),
    (re.compile(r"SPRYCEL|DASATINIB"), "Sprycel / Dasatinib"),
    (re.compile(r"PACLITAXEL|TAXOL"), "Taxol / Paclitaxel"),
    (re.compile(r"CYCLOPHOSPHAMIDE|CICLOFOSFAMIDA"), "Cyclophosphamide / Ciclofosfamida"),
]
 
_fragment = (
    getattr(st, "fragment", None)
    or getattr(st, "experimental_fragment", None)
    or (lambda f: f)
)
 
 
def bloco_produtos_newse(texto_upper):
    """Trecho da NEWSE entre 'Produto(s)' e 'Observações' (onde fica o Nome
    do produto). Se não achar, usa o texto inteiro."""
    bloco = texto_upper.split("PRODUTO(S)")[-1] if "PRODUTO(S)" in texto_upper else texto_upper
    if "OBSERVAÇÕES" in bloco:
        bloco = bloco.split("OBSERVAÇÕES")[0]
    return bloco
 
 
def montar_texto_embalagem_brasil(tem_ref, tem_amb):
    tags, credos = [], []
    if tem_amb:
        tags.append("TAG ALERT AMBIENTE")
        credos.append("CREDO AMBIENTE")
    if tem_ref:
        tags.append("TAG ALERT REFRIGERADO")
        credos.append("CREDO REFRIGERADA")
    if not tags:
        return ""
    return " E ".join(tags) + " + " + " E ".join(credos)
 
 
def _unicos(linhas):
    vistos, saida = set(), []
    for linha in linhas:
        if linha not in vistos:
            vistos.add(linha)
            saida.append(linha)
    return saida
 
 
def _exibir_resultado(linhas):
    texto_final = "\n".join(linhas)
 
    st.markdown("#### 📄 Particularidades geradas")
    st.code(texto_final, language="text")
 
    texto_js = json.dumps(texto_final, ensure_ascii=False).replace("</", "<\\/")
    components.html(
        f"""
<button id="copiar" style="background:#e59235; color:white; font-size:13px; font-weight:bold;
            padding:8px; border:none; border-radius:4px; width:100%; cursor:pointer;">
            📋 Copiar Particularidades
</button>
<script>
          const texto = {texto_js};
          const botao = document.getElementById('copiar');
          botao.addEventListener('click', () => {{
            navigator.clipboard.writeText(texto);
            botao.innerText = '📋 Texto Copiado!';
          }});
</script>
        """,
        height=45,
    )
 
 
@_fragment
def _checklist_brasil(texto_upper, arquivo_id, tem_ref, tem_amb):
 
    def k(nome):
        return f"brasil_{nome}_{arquivo_id}"
 
    st.caption(f"Checklist {VERSAO_CHECKLIST_BRASIL}")
 
    st.markdown("**Esta solicitação é de qual categoria?**")
    categoria = st.radio(
        "Categoria da solicitação", [CATEGORIA_MEDICACAO, CATEGORIA_SUPRIMENTO],
        index=None, horizontal=True, key=k("categoria"), label_visibility="collapsed",
    )
    if categoria is None:
        st.info("Escolha a categoria para abrir o checklist de particularidades.")
        return
 
    # ======================= MEDICAÇÃO =======================
    if categoria == CATEGORIA_MEDICACAO:
        produtos = bloco_produtos_newse(texto_upper)
        citotoxicas = [rotulo for regex, rotulo in CITOTOXICAS if regex.search(produtos)]
        eh_cito = bool(citotoxicas)
        if eh_cito:
            st.info("🧪 Medicação CYTOTOXIC identificada: " + ", ".join(citotoxicas))
 
        st.markdown("#### CS")
        st.markdown("**ORDENS COMPLEMENTARES**")
        st.caption("( X ) SIM")
        tn = st.text_input("TN:", key=k("tn"), placeholder="Preencha o número do TN").strip()
        if not tn:
            st.warning("⚠️ TN em branco.")
 
        st.markdown("**OBSERVAÇÕES CS**")
        st.markdown(f"- {OBS_CS}")
 
        st.markdown("#### OPERAÇÃO WHS")
        st.markdown("**EMBALAGENS**")
        sugerido = montar_texto_embalagem_brasil(tem_ref, tem_amb)
        if not sugerido:
            st.warning("⚠️ Não identifiquei a temperatura (ambiente / 2 A 8ºC) na NEWSE — preencha o texto manualmente.")
        st.caption("Pela temperatura da NEWSE (pode editar):")
        embalagem = st.text_input("OUTRO:", value=sugerido, key=k("emb")).strip()
 
        st.markdown("**ETIQUETAGEM**")
        ve = st.text_input("VE:", key=k("ve"), placeholder="Preencha o VE").strip()
        if not ve:
            st.warning("⚠️ VE em branco.")
 
        st.markdown("**ENVIO DE EQUIPAMENTOS**")
        st.caption("( X ) N/A")
 
        st.markdown("**ENVIO DE PRODUTOS PERIGOSOS**")
        perigoso = st.radio(
            "Produtos perigosos", ["SIM", "N/A"],
            index=0 if eh_cito else 1, horizontal=True,
            key=k("per"), label_visibility="collapsed",
        )
        ficha_perigoso = False
        if perigoso == "SIM":
            ficha_perigoso = st.checkbox("FICHA DE SEGURANÇA", value=True, key=k("per_ficha"))
 
        st.markdown("**ESTÁ AUTORIZADO O ENVIO DE PRODUTOS COM VALIDADE INFERIOR A 3 MESES?**")
        st.caption("Padrão: NÃO. Troque para SIM só se o cliente autorizar.")
        validade = st.radio(
            "Validade inferior a 3 meses", [OPCAO_VALIDADE_NAO, OPCAO_VALIDADE_SIM],
            index=0, key=k("val"), label_visibility="collapsed",
        )
 
        st.markdown("**ANEXOS OBRIGATÓRIOS NO ENVIO**")
        anexos = []
        if st.checkbox(ANEXO_MINUTAS, value=True, key=k("anx_min")):
            anexos.append(ANEXO_MINUTAS)
        if st.checkbox(ANEXO_FORMULARIO, value=True, key=k("anx_form")):
            anexos.append(ANEXO_FORMULARIO)
        if eh_cito and st.checkbox(ANEXO_FICHA, value=True, key=k("anx_ficha")):
            anexos.append(ANEXO_FICHA)
 
        obs_whs = []
        if eh_cito:
            st.markdown("**OBSERVAÇÕES WHS**")
            if st.checkbox(OBS_WHS_UN3481, value=True, key=k("whs_un3481")):
                obs_whs.append(OBS_WHS_UN3481)
            if st.checkbox(OBS_WHS_EXCEPTED, value=True, key=k("whs_excepted")):
                obs_whs.append(OBS_WHS_EXCEPTED)
 
        linhas = [
            "CS:", "", "- ORDENS COMPLEMENTARES:", f"( X ) SIM - TN: {tn}".rstrip(),
            "", "OBSERVAÇÕES CS:", OBS_CS,
            "", "OPERAÇÃO WHS:", "", "- EMBALAGENS:", f"( X ) OUTRO: {embalagem}".rstrip(),
            "", "- ETIQUETAGEM:", f"( X ) SIM - VE: {ve}".rstrip(),
            "", "- ENVIO DE EQUIPAMENTOS:", "( X ) N/A",
            "", "- ENVIO DE PRODUTOS PERIGOSOS:",
        ]
        if perigoso == "SIM":
            linhas.append("( X ) SIM - ( X ) FICHA DE SEGURANÇA" if ficha_perigoso else "( X ) SIM")
        else:
            linhas.append("( X ) N/A")
        linhas += ["", "- ESTÁ AUTORIZADO O ENVIO DE PRODUTOS COM VALIDADE INFERIOR A 3 MESES?",
                   f"( X ) {validade}"]
        linhas += ["", "- ANEXOS OBRIGATÓRIOS NO ENVIO:"]
        linhas += [f"( X ) {a}" for a in anexos]
        obs_whs = _unicos(obs_whs)
        if obs_whs:
            linhas += ["", "OBSERVAÇÕES WHS:"]
            linhas += obs_whs
 
        _exibir_resultado(linhas)
        return
 
    # ================= EQUIPAMENTO / SUPRIMENTO =================
    st.markdown("#### CS")
    st.markdown("**ORDENS COMPLEMENTARES**")
    st.caption("( X ) NÃO")
 
    st.markdown("**OBSERVAÇÕES CS**")
    st.markdown(f"- {OBS_CS}")
 
    st.markdown("#### OPERAÇÃO WHS")
    st.markdown("**EMBALAGENS**")
    embalagem = st.text_input("OUTRO:", value=EMBALAGEM_SUPRIMENTO, key=k("emb_sup")).strip()
 
    st.markdown("**ETIQUETAGEM**")
    st.caption("( X ) N/A")
 
    st.markdown("**ENVIO DE EQUIPAMENTOS** — escolha obrigatória")
    equip = st.radio(
        "Envio de equipamentos", [OPCAO_EQUIP_SIM, OPCAO_EQUIP_NAO],
        index=None, horizontal=True, key=k("equip"), label_visibility="collapsed",
    )
    catalogo = None
    if equip == OPCAO_EQUIP_SIM:
        st.caption("Catálogo anexado?")
        catalogo = st.radio(
            "Catálogo anexado", ["SIM", "N/A"],
            index=None, horizontal=True, key=k("catalogo"), label_visibility="collapsed",
        )
 
    st.markdown("**ENVIO DE PRODUTOS PERIGOSOS**")
    st.caption("( X ) N/A")
 
    st.markdown("**ESTÁ AUTORIZADO O ENVIO DE PRODUTOS COM VALIDADE INFERIOR A 3 MESES?**")
    st.caption("Padrão: NÃO. Troque para SIM só se o cliente autorizar.")
    validade = st.radio(
        "Validade inferior a 3 meses", [OPCAO_VALIDADE_NAO, OPCAO_VALIDADE_SIM],
        index=0, key=k("val_sup"), label_visibility="collapsed",
    )
 
    eh_equipamento = (equip == OPCAO_EQUIP_SIM)
 
    st.markdown("**ANEXOS OBRIGATÓRIOS NO ENVIO**")
    anexos = []
    if st.checkbox(ANEXO_MINUTAS, value=True, key=k("anx_min_sup")):
        anexos.append(ANEXO_MINUTAS)
    if st.checkbox(ANEXO_FORMULARIO, value=True, key=k("anx_form_sup")):
        anexos.append(ANEXO_FORMULARIO)
    if eh_equipamento and st.checkbox(ANEXO_BATERIA, value=True, key=k("anx_bateria")):
        anexos.append(ANEXO_BATERIA)
 
    obs_whs = []
    if eh_equipamento:
        st.markdown("**OBSERVAÇÕES WHS**")
        if st.checkbox(OBS_WHS_UN3481, value=True, key=k("whs_un3481")):
            obs_whs.append(OBS_WHS_UN3481)
 
    # Bloqueio: precisa decidir sobre equipamento (e catálogo, se for o caso)
    if equip is None:
        st.error("⛔ Escolha SIM ou N/A em ENVIO DE EQUIPAMENTOS para liberar as particularidades.")
        return
    if eh_equipamento and catalogo is None:
        st.error("⛔ Informe se o catálogo está anexado (SIM ou N/A) para liberar as particularidades.")
        return
 
    linhas = [
        "CS:", "", "- ORDENS COMPLEMENTARES:", "( X ) NÃO",
        "", "OBSERVAÇÕES CS:", OBS_CS,
        "", "OPERAÇÃO WHS:", "", "- EMBALAGENS:", f"( X ) OUTRO: {embalagem}".rstrip(),
        "", "- ETIQUETAGEM:", "( X ) N/A",
        "", "- ENVIO DE EQUIPAMENTOS:",
    ]
    if eh_equipamento:
        linhas.append(f"( X ) SIM - catálogo anexado: ( X ) {catalogo}")
    else:
        linhas.append("( X ) N/A")
    linhas += ["", "- ENVIO DE PRODUTOS PERIGOSOS:", "( X ) N/A"]
    linhas += ["", "- ESTÁ AUTORIZADO O ENVIO DE PRODUTOS COM VALIDADE INFERIOR A 3 MESES?",
               f"( X ) {validade}"]
    linhas += ["", "- ANEXOS OBRIGATÓRIOS NO ENVIO:"]
    linhas += [f"( X ) {a}" for a in anexos]
    obs_whs = _unicos(obs_whs)
    if obs_whs:
        linhas += ["", "OBSERVAÇÕES WHS:"]
        linhas += obs_whs
 
    _exibir_resultado(linhas)
 
 
def renderizar_checklist_brasil(texto_upper, arquivo_id, tem_ref, tem_amb):
    _checklist_brasil(texto_upper, arquivo_id, tem_ref, tem_amb)
