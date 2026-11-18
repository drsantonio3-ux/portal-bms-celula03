# -*- coding: utf-8 -*-
"""Checklist de Particularidades (novo padrão DRS) para o Portal BMS."""

import hashlib
import json
import os
import re
import unicodedata

import streamlit as st
import streamlit.components.v1 as components

ARQUIVO_FIXAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "particularidades_fixas.json")

PALAVRAS_ORDEM_COMPLEMENTAR = ("CAMARGO", "ICESP", "PRUDENTE", "INSTITUTO DO CANCER")

OBS_CS_PACKING = [
    "A SC e Minuta deverá ser emitida no CNPJ do Centro de destino.",
]

ANEXOS_PACKING = ["Minutas", "Formulário de Remessa", "Packing list"]
ANEXO_FICHA = "Ficha de segurança de produtos perigosos"

OBS_WHS_CITOTOXICO = [
    "Identificar o volume com a etiqueta UN3481 – para envio de equipamentos.",
    "Etiquetar os volumes com etiqueta excepted quantities.",
]

# CYTOTOXIC: escolha obrigatória na hora do atendimento (nunca fixa)
OBS_WHS_CREDO_IGARAI = (
    "As medicações devem ser acondicionadas em embalagem CREDO, a QUAL deverá ser "
    "ALOCADA DENTRO DE UMA CAIXA HOMOLOGADA IGARAI 4GV2 + VERMICULITA."
)
OBS_WHS_CREDO_SIMPLES = (
    "As medicações seguirão com o envio em CREDO sem necessidade de IGARAI e VERMICULITA."
)

VERSAO_CHECKLIST = "v4 · embalagem CYTOTOXIC obrigatória"

OPCAO_VALIDADE_NAO = "NÃO"
OPCAO_VALIDADE_SIM = "SIM – OBRIGATÓRIO AUTORIZAÇÃO DO CLIENTE ANEXA"

# Medicações CYTOTOXIC (as que têm ficha de segurança)
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


def _sem_acentos(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def centro_exige_ordem_complementar(texto_upper):
    texto = _sem_acentos(texto_upper)
    bloco = texto.split("SHIP TO")[-1] if "SHIP TO" in texto else texto
    return any(p in bloco for p in PALAVRAS_ORDEM_COMPLEMENTAR)


def montar_texto_embalagem(qtd_temptale, qtd_tag_amb, qtd_tag_ref):
    def fmt(qtd, rotulo):
        return rotulo if qtd == 1 else f"{qtd}x {rotulo}"

    credos, loggers = [], []
    credo_ambiente = qtd_tag_amb + qtd_temptale
    if credo_ambiente:
        credos.append(fmt(credo_ambiente, "CREDO AMBIENTE"))
    if qtd_tag_ref:
        credos.append(fmt(qtd_tag_ref, "CREDO REFRIGERADO"))
    if qtd_tag_amb:
        loggers.append(fmt(qtd_tag_amb, "TAG ALERT AMBIENTE"))
    if qtd_tag_ref:
        loggers.append(fmt(qtd_tag_ref, "TAG ALERT REFRIGERADO"))
    if qtd_temptale:
        loggers.append(fmt(qtd_temptale, "TEMPTALE AMBIENTE"))
    if not credos:
        return ""
    return " E ".join(credos) + " + " + " E ".join(loggers)


def carregar_linhas_fixas():
    if "linhas_fixas" in st.session_state:
        return st.session_state["linhas_fixas"]
    dados = {secao: [] for secao in ("obs_cs", "anexos")}
    try:
        with open(ARQUIVO_FIXAS, "r", encoding="utf-8") as f:
            lido = json.load(f)
        for secao in dados:
            dados[secao] = [str(x).strip() for x in lido.get(secao, []) if str(x).strip()]
    except Exception:
        pass
    st.session_state["linhas_fixas"] = dados
    return dados


def salvar_linhas_fixas():
    try:
        with open(ARQUIVO_FIXAS, "w", encoding="utf-8") as f:
            json.dump(st.session_state["linhas_fixas"], f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _hash(texto):
    return hashlib.md5(texto.encode("utf-8")).hexdigest()[:8]


def _unicos(linhas):
    vistos, saida = set(), []
    for linha in linhas:
        if linha not in vistos:
            vistos.add(linha)
            saida.append(linha)
    return saida


def _bloco_linhas_extras(secao, arquivo_id, rotulo_campo):
    fixas = carregar_linhas_fixas()[secao]
    chave_extras = f"part_extras_{secao}_{arquivo_id}"
    chave_cont = f"part_cont_{secao}_{arquivo_id}"
    st.session_state.setdefault(chave_extras, [])
    st.session_state.setdefault(chave_cont, 0)

    selecionadas = []

    for texto in list(fixas):
        c1, c2 = st.columns([12, 1])
        with c1:
            if st.checkbox(f"📌 {texto}", value=True, key=f"part_fixa_{secao}_{_hash(texto)}_{arquivo_id}"):
                selecionadas.append(texto)
        with c2:
            if st.button("🗑️", key=f"part_fixa_del_{secao}_{_hash(texto)}_{arquivo_id}",
                         help="Remover das linhas fixas"):
                fixas.remove(texto)
                salvar_linhas_fixas()
                st.rerun()

    for texto in st.session_state[chave_extras]:
        if st.checkbox(texto, value=True, key=f"part_extra_{secao}_{_hash(texto)}_{arquivo_id}"):
            selecionadas.append(texto)

    cont = st.session_state[chave_cont]
    novo = st.text_input(
        rotulo_campo,
        key=f"part_novo_{secao}_{cont}_{arquivo_id}",
        placeholder="Digite uma informação adicional (opcional)",
    )
    fixar = st.checkbox(
        "📌 Deixar esta linha como fixa (aparece em todas as próximas Packing Lists)",
        key=f"part_fixar_{secao}_{cont}_{arquivo_id}",
    )
    if st.button("➕ Adicionar linha", key=f"part_add_{secao}_{arquivo_id}"):
        texto_novo = (novo or "").strip()
        if texto_novo:
            if fixar:
                if texto_novo not in fixas:
                    fixas.append(texto_novo)
                    if not salvar_linhas_fixas():
                        st.warning("Não consegui gravar a linha fixa em arquivo — ela vale só nesta sessão.")
            elif texto_novo not in st.session_state[chave_extras]:
                st.session_state[chave_extras].append(texto_novo)
            st.session_state[chave_cont] = cont + 1
            st.rerun()

    return selecionadas


@_fragment
def _checklist(texto_upper, arquivo_id, qtd_temptale, qtd_tag_amb, qtd_tag_ref, tem_citotoxico_amplo):

    def k(nome):
        return f"part_{nome}_{arquivo_id}"

    st.caption(f"Checklist {VERSAO_CHECKLIST}")

    citotoxicas = [rotulo for regex, rotulo in CITOTOXICAS if regex.search(texto_upper)]
    eh_cito = bool(citotoxicas)

    if eh_cito:
        st.info("🧪 Medicação CYTOTOXIC identificada: " + ", ".join(citotoxicas))
    elif tem_citotoxico_amplo:
        st.caption(
            "ℹ️ A Packing List traz item marcado como Cytotoxic que não está na lista das "
            "medicações com ficha de segurança — não marquei como CYTOTOXIC. Ajuste abaixo se precisar."
        )

    # ---------------- CS ----------------
    st.markdown("#### CS")
    st.markdown("**ORDENS COMPLEMENTARES**")
    exige_oc = centro_exige_ordem_complementar(texto_upper)
    if exige_oc:
        st.caption("Centro AC Camargo / ICESP / Antônio Prudente → SIM (independente do TE).")
    escolha_oc = st.radio(
        "Ordens complementares", ["SIM", "NÃO", "N/A"],
        index=0 if exige_oc else 1, horizontal=True,
        key=k("oc"), label_visibility="collapsed",
    )
    tn_oc = ""
    if escolha_oc == "SIM":
        tn_oc = st.text_input("TN:", key=k("oc_tn"), placeholder="Preencha o número do TN").strip()
        if not tn_oc:
            st.warning("⚠️ TN em branco.")

    st.markdown("**OBSERVAÇÕES CS**")
    st.caption("Incluída automaticamente (via Packing List):")
    for linha in OBS_CS_PACKING:
        st.markdown(f"- {linha}")
    obs_cs_extras = _bloco_linhas_extras("obs_cs", arquivo_id, "Nova observação CS:")

    # ---------------- OPERAÇÃO WHS ----------------
    st.markdown("#### OPERAÇÃO WHS")
    st.markdown("**EMBALAGENS**")
    sugerido = montar_texto_embalagem(qtd_temptale, qtd_tag_amb, qtd_tag_ref)
    if not sugerido:
        st.warning("⚠️ Não identifiquei TAG ALERT / TEMPTALE nesta Packing List — preencha o texto manualmente.")
    st.caption("Packing List → sempre ( X ) OUTRO. Texto calculado pela quantidade de TAG ALERT / TEMPTALE (pode editar):")
    texto_embalagem = st.text_input("OUTRO:", value=sugerido, key=k("emb")).strip()

    st.markdown("**ETIQUETAGEM**")
    st.caption("( X ) N/A — fixo para Packing List")

    st.markdown("**ENVIO DE EQUIPAMENTOS**")
    st.caption("( X ) N/A — fixo para Packing List")

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
    for rotulo in ANEXOS_PACKING:
        if st.checkbox(rotulo, value=True, key=k(f"anx_{_hash(rotulo)}")):
            anexos.append(rotulo)
    if st.checkbox(ANEXO_FICHA, value=eh_cito, key=k("anx_ficha")):
        anexos.append(ANEXO_FICHA)
    anexos_extras = _bloco_linhas_extras("anexos", arquivo_id, "Novo anexo obrigatório:")

    st.markdown("**OBSERVAÇÕES WHS**")
    st.caption("Se nada for marcado nem escrito, esta etapa não aparece nas particularidades.")
    obs_whs = []
    for texto in OBS_WHS_CITOTOXICO:
        if st.checkbox(texto, value=eh_cito, key=k(f"whs_{_hash(texto)}")):
            obs_whs.append(texto)
    escolha_credo = None
    if eh_cito:
        st.markdown("**Embalagem do CYTOTOXIC — escolha obrigatória:**")
        escolha_credo = st.radio(
            "Embalagem CYTOTOXIC", [OBS_WHS_CREDO_IGARAI, OBS_WHS_CREDO_SIMPLES],
            index=None, key=k("credo"), label_visibility="collapsed",
        )
        if escolha_credo is None:
            st.error("⛔ Escolha uma das 2 opções acima para liberar as particularidades.")
        else:
            obs_whs.append(escolha_credo)
    extra_whs = st.text_area(
        "Nova observação WHS (opcional — uma por linha):",
        key=k("whs_extra"), height=80,
        placeholder="Digite uma informação adicional, se precisar",
    )
    obs_whs += [l.strip() for l in (extra_whs or "").splitlines() if l.strip()]

    st.markdown("**FISCAL**")
    st.caption("Se nada for escrito, esta etapa não aparece nas particularidades.")
    extra_fiscal = st.text_area(
        "Observação FISCAL (opcional — uma por linha):",
        key=k("fiscal_extra"), height=80,
        placeholder="Digite uma informação fiscal, se precisar",
    )
    obs_fiscal = _unicos([l.strip() for l in (extra_fiscal or "").splitlines() if l.strip()])

    # CYTOTOXIC sem a escolha da embalagem: não gera nem libera a cópia
    if eh_cito and escolha_credo is None:
        st.warning("🔒 Particularidades bloqueadas: selecione a embalagem do CYTOTOXIC em OBSERVAÇÕES WHS.")
        return

    # ---------------- Documento final ----------------
    linhas = ["CS:", "", "- ORDENS COMPLEMENTARES:"]
    if escolha_oc == "SIM":
        linhas.append(f"( X ) SIM - TN: {tn_oc}".rstrip())
    else:
        linhas.append(f"( X ) {escolha_oc}")

    linhas += ["", "OBSERVAÇÕES CS:"]
    linhas += _unicos(OBS_CS_PACKING + obs_cs_extras)

    linhas += ["", "OPERAÇÃO WHS:", "", "- EMBALAGENS:"]
    linhas.append(f"( X ) OUTRO: {texto_embalagem}".rstrip())

    linhas += ["", "- ETIQUETAGEM:", "( X ) N/A"]
    linhas += ["", "- ENVIO DE EQUIPAMENTOS:", "( X ) N/A"]

    linhas += ["", "- ENVIO DE PRODUTOS PERIGOSOS:"]
    if perigoso == "SIM":
        linhas.append("( X ) SIM - ( X ) FICHA DE SEGURANÇA" if ficha_perigoso else "( X ) SIM")
    else:
        linhas.append("( X ) N/A")

    linhas += ["", "- ESTÁ AUTORIZADO O ENVIO DE PRODUTOS COM VALIDADE INFERIOR A 3 MESES?",
               f"( X ) {validade}"]

    linhas += ["", "- ANEXOS OBRIGATÓRIOS NO ENVIO:"]
    linhas += [f"( X ) {a}" for a in _unicos(anexos + anexos_extras)]

    obs_whs = _unicos(obs_whs)
    if obs_whs:
        linhas += ["", "OBSERVAÇÕES WHS:"]
        linhas += obs_whs

    if obs_fiscal:
        linhas += ["", "- FISCAL:"]
        linhas += obs_fiscal

    texto_final = "\n".join(linhas)

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


def renderizar_checklist_particularidades(texto_upper, arquivo_id, qtd_temptale,
                                          qtd_tagalert_amb, qtd_tagalert_ref, tem_citotoxico):
    _checklist(texto_upper, arquivo_id, qtd_temptale, qtd_tagalert_amb,
               qtd_tagalert_ref, tem_citotoxico)
