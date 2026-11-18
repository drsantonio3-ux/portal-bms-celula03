# -*- coding: utf-8 -*-
"""Leitura da Packing List da BMS para o Gerador de E-mail (GR).

Estratégia:
1. Tenta primeiro o texto que já existe dentro do PDF (rápido e exato).
2. Se faltar dado, faz OCR de todas as páginas com pré-processamento
   (remove as linhas verticais/horizontais do scanner, que "cortam" as
   palavras) e várias leituras diferentes; o valor que mais se repete vence
   (votação). Isso corrige erros típicos do OCR, como ":" lido como "1" ou
   "7" colado no número.
"""

import difflib
import io
import re
from collections import Counter

try:
    import numpy as np
    from PIL import Image, ImageOps
    import pytesseract
    from pdf2image import convert_from_bytes
    OCR_DISPONIVEL = True
except Exception:  # pragma: no cover
    OCR_DISPONIVEL = False

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


DPI_OCR = 300

MESES_EN = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}

# Letras que o OCR costuma trocar por número nas 2 primeiras posições do protocolo
_DIGITO_PARA_LETRA = {"1": "I", "0": "O", "5": "S", "8": "B"}

ITEM_REGEX = re.compile(
    r"(?P<antes>[^\n]*?)\b(?P<qtd>\d{1,5})\s*EA\s*"
    r"(?P<data>\d{1,2}\s*[-–]\s*[A-Za-z]{3}\s*[-–]\s*\d{4})",
    re.IGNORECASE,
)

_LINHAS_IGNORADAS = ("SERIAL", "STORAGE", "TEMPTALE", "TAGALERT", "FAGALERT", "TAG ALERT",
                     "CYTO", "TT ", "TT*", "SHIPMENT", "TO BE COMPLETED")


# --------------------------------------------------------------------------
# Normalizações
# --------------------------------------------------------------------------

def _normalizar_data(data_str):
    """'31 - aug - 2027' -> '31/08/2027' (corrige mês levemente errado)."""
    m = re.match(r"(\d{1,2})\s*[-–]\s*([A-Za-z]{3})\s*[-–]\s*(\d{4})", data_str.strip())
    if not m:
        return data_str.strip()
    dia, mes_txt, ano = m.groups()
    mes_txt = mes_txt.upper()
    if mes_txt not in MESES_EN:
        parecido = difflib.get_close_matches(mes_txt, list(MESES_EN), n=1, cutoff=0.5)
        if not parecido:
            return data_str.strip()
        mes_txt = parecido[0]
    return f"{int(dia):02d}/{MESES_EN[mes_txt]}/{ano}"


def _limpar_descricao(texto):
    """Tira espaços DENTRO de parênteses (ex.: '(1 BTLX28)' -> '(1BTLX28)') e
    corrige o 1 inicial lido como letra/símbolo."""
    texto = re.sub(r"\s+", " ", texto).strip()

    def ajustar(m):
        miolo = m.group(1).replace(" ", "")
        miolo = re.sub(r"^[iIl|/\]j!]+(?=[A-Z0-9])", "1", miolo)
        return f"({miolo})"

    return re.sub(r"\(\s*([^)]*?)\s*\)", ajustar, texto)


def _normalizar_order(janela):
    runs = re.findall(r"\d{7,11}", janela)
    for run in runs:
        if re.fullmatch(r"4\d{7}|5\d{9}", run):
            return run
        # ':' lido como dígito colado na frente do número
        if len(run) in (9, 11) and re.fullmatch(r"4\d{7}|5\d{9}", run[1:]):
            return run[1:]
    return runs[0] if runs else ""


def _normalizar_protocolo(janela):
    m = re.search(r"([A-Z0-9]{2})\s*(\d{3})\s*[-–]\s*(\d{3,4})", janela.upper())
    if not m:
        return ""
    prefixo, num, sufixo = m.groups()
    prefixo = "".join(_DIGITO_PARA_LETRA.get(c, c) if c.isdigit() else c for c in prefixo)
    return f"{prefixo}{num}-{sufixo}"


# --------------------------------------------------------------------------
# Interpretação de UM texto (nativo ou de uma leitura OCR)
# --------------------------------------------------------------------------

def _interpretar_texto(texto):
    dados = {"delivery": "", "protocolo": "", "order": "", "itens": []}

    m = re.search(r"Delivery\s*number([^\n]{0,30})", texto, re.IGNORECASE)
    if m:
        d = re.search(r"80\d{8}", m.group(1))
        dados["delivery"] = d.group(0) if d else ""
    if not dados["delivery"]:
        d = re.search(r"\b80\d{8}\b", texto)
        dados["delivery"] = d.group(0) if d else ""

    m = re.search(r"Protocol\s*number([^\n]{0,30})", texto, re.IGNORECASE)
    if m:
        dados["protocolo"] = _normalizar_protocolo(m.group(1))
    if not dados["protocolo"]:
        dados["protocolo"] = _normalizar_protocolo(texto)

    m = re.search(r"Order\s*number([^\n]{0,30})", texto, re.IGNORECASE)
    if m:
        dados["order"] = _normalizar_order(m.group(1))

    prefixo_proto = dados["protocolo"][:5].upper() if dados["protocolo"] else ""
    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        mi = ITEM_REGEX.search(linha)
        if not mi:
            continue
        tokens = [t for t in re.split(r"\s+", mi.group("antes").strip().upper()) if t]
        tokens = [re.sub(r"[^A-Z0-9.\-/]", "", t) for t in tokens]
        tokens = [t for t in tokens if len(t) >= 4 and re.search(r"\d", t)]
        lote = tokens[-1] if tokens else ""

        candidatas = []
        for j in range(i + 1, min(i + 7, len(linhas))):
            cand = linhas[j].strip()
            if not cand or cand.upper().startswith(_LINHAS_IGNORADAS):
                continue
            candidatas.append(cand)
        descricao = ""
        for cand in candidatas:
            up = cand.upper()
            if "OLMU" in up or (prefixo_proto and prefixo_proto in up.replace(" ", "")):
                descricao = cand
                break
        if not descricao:
            for cand in candidatas:
                if len(cand) >= 10 and re.search(r"[A-Za-z]{3}", cand):
                    descricao = cand
                    break

        dados["itens"].append({
            "descricao": _limpar_descricao(descricao).upper() if descricao else "",
            "lote": lote,
            "validade": _normalizar_data(mi.group("data")),
            "quantidade": mi.group("qtd"),
        })
    return dados


# --------------------------------------------------------------------------
# Pré-processamento para OCR (só numpy + PIL)
# --------------------------------------------------------------------------

def _limiar_otsu(a):
    hist, _ = np.histogram(a, bins=256, range=(0, 256))
    total = a.size
    soma = float(np.dot(np.arange(256), hist))
    soma_b = 0.0
    peso_b = 0
    melhor, limiar = 0.0, 128
    for t in range(256):
        peso_b += hist[t]
        if peso_b == 0:
            continue
        peso_f = total - peso_b
        if peso_f == 0:
            break
        soma_b += t * hist[t]
        media_b = soma_b / peso_b
        media_f = (soma - soma_b) / peso_f
        var = peso_b * peso_f * (media_b - media_f) ** 2
        if var > melhor:
            melhor, limiar = var, t
    return limiar


def _preprocessar(img):
    """Binariza e apaga as linhas longas (verticais/horizontais) do scanner,
    preservando as letras que cruzam a linha."""
    a = np.array(ImageOps.grayscale(img))
    escuro = a < _limiar_otsu(a)
    h, w = escuro.shape

    frac_col = escuro.sum(axis=0) / h
    cols = np.where(frac_col > 0.35)[0]
    grupos = []
    for c in cols:
        if grupos and c - grupos[-1][-1] <= 2:
            grupos[-1].append(c)
        else:
            grupos.append([c])
    for g in grupos:
        x0, x1 = g[0], g[-1]
        esq = escuro[:, max(0, x0 - 6)]
        dir_ = escuro[:, min(w - 1, x1 + 6)]
        livre = ~esq & ~dir_  # vizinhança limpa dos dois lados = é só a linha
        for x in range(x0, x1 + 1):
            escuro[livre, x] = False

    frac_lin = escuro.sum(axis=1) / w
    for y in np.where(frac_lin > 0.5)[0]:
        escuro[max(0, y - 2):y + 3, :] = False

    return Image.fromarray(np.where(escuro, 0, 255).astype(np.uint8))


# --------------------------------------------------------------------------
# Votação entre várias leituras
# --------------------------------------------------------------------------

def _mais_comum(valores):
    valores = [v for v in valores if v]
    if not valores:
        return ""
    return Counter(valores).most_common(1)[0][0]


def _votar(leituras):
    """Junta várias interpretações do MESMO documento e fica com o valor que
    mais se repete em cada campo."""
    resultado = {
        "delivery": _mais_comum([l["delivery"] for l in leituras]),
        "protocolo": _mais_comum([l["protocolo"] for l in leituras]),
        "order": _mais_comum([l["order"] for l in leituras]),
        "itens": [],
    }
    com_itens = [l["itens"] for l in leituras if l["itens"]]
    if not com_itens:
        return resultado

    tamanho = Counter(len(x) for x in com_itens).most_common(1)[0][0]
    validas = [x for x in com_itens if len(x) == tamanho]
    for i in range(tamanho):
        descricoes = [x[i]["descricao"] for x in validas]
        chaves = [re.sub(r"\s+", "", d) for d in descricoes]
        chave_vencedora = _mais_comum(chaves)
        descricao = next((d for d, c in zip(descricoes, chaves) if c == chave_vencedora), "")
        resultado["itens"].append({
            "descricao": descricao,
            "lote": _mais_comum([x[i]["lote"] for x in validas]),
            "validade": _mais_comum([x[i]["validade"] for x in validas]),
            "quantidade": _mais_comum([x[i]["quantidade"] for x in validas]),
        })
    return resultado


def _assinatura(d):
    """Resumo comparável de uma leitura (para saber se duas leituras concordam)."""
    return (
        d["delivery"], d["protocolo"], d["order"],
        tuple((re.sub(r"\s+", "", i["descricao"]), i["lote"], i["validade"], i["quantidade"])
              for i in d["itens"]),
    )


def _completo(d):
    return bool(d["delivery"] and d["order"] and d["protocolo"] and d["itens"])


def _juntar_paginas(por_pagina):
    """Combina o resultado de várias páginas (cabeçalho repete; itens somam)."""
    junto = {"delivery": "", "protocolo": "", "order": "", "itens": []}
    vistos = set()
    for d in por_pagina:
        for campo in ("delivery", "protocolo", "order"):
            junto[campo] = junto[campo] or d[campo]
        for it in d["itens"]:
            chave = (it["lote"], it["quantidade"], it["validade"])
            if chave not in vistos:
                vistos.add(chave)
                junto["itens"].append(it)
    return junto


# --------------------------------------------------------------------------
# Função pública (mesmo nome/retorno da versão antiga do portal)
# --------------------------------------------------------------------------

def extrair_dados_packing_para_email(arquivo_pdf, max_paginas=4):
    """Devolve sempre {"delivery","protocolo","order","itens":[{descricao,lote,
    validade (DD/MM/AAAA),quantidade}]}, com campos vazios quando não achar."""
    vazio = {"delivery": "", "protocolo": "", "order": "", "itens": []}

    arquivo_pdf.seek(0)
    pdf_bytes = arquivo_pdf.read()

    # 1) Texto nativo do PDF
    nativo = dict(vazio)
    if PdfReader is not None:
        try:
            leitor = PdfReader(io.BytesIO(pdf_bytes))
            textos = [(p.extract_text() or "") for p in leitor.pages[:max_paginas]]
            nativo = _juntar_paginas([_interpretar_texto(t) for t in textos])
        except Exception:
            nativo = dict(vazio)
    if _completo(nativo):
        return nativo

    if not OCR_DISPONIVEL:
        return nativo

    # 2) OCR com pré-processamento e votação
    por_pagina = []
    for numero in range(1, max_paginas + 1):
        try:
            imagens = convert_from_bytes(pdf_bytes, dpi=DPI_OCR, first_page=numero, last_page=numero)
        except Exception:
            break
        if not imagens:
            break
        img = imagens[0]
        try:
            pre = _preprocessar(img)
        except Exception:
            pre = img

        leituras, textos = [], []
        passes = ((pre, 6), (pre, 4), (pre, 11), (img, 6))
        for n_leitura, (imagem, psm) in enumerate(passes):
            try:
                texto = pytesseract.image_to_string(imagem, lang="eng", config=f"--psm {psm}")
            except Exception:
                continue
            textos.append(texto)
            leituras.append(_interpretar_texto(texto))
            # 1ª leitura sem nada útil (ex.: página de recebimento): não aprofunda
            if n_leitura == 0 and numero > 1 and not (leituras[0]["itens"] or leituras[0]["delivery"]):
                break
            # 2 leituras que concordam em tudo: já é confiável
            if n_leitura == 1 and _assinatura(leituras[0]) == _assinatura(leituras[1]) and _completo(leituras[0]):
                break
        if leituras:
            por_pagina.append(_votar(leituras))

        # Página com "SHIPMENT CONFIRMATION" = acabou a lista de itens
        if any(re.search(r"SHIPMENT\s*CONFIRMATION|HIPMENT\s*CONFIRMATION|completed\s*by\s*sender", t, re.I)
               for t in textos):
            break

    ocr = _juntar_paginas(por_pagina) if por_pagina else dict(vazio)
    # completa o que o OCR não achou com o que veio do texto nativo
    for campo in ("delivery", "protocolo", "order"):
        ocr[campo] = ocr[campo] or nativo[campo]
    if not ocr["itens"]:
        ocr["itens"] = nativo["itens"]
    return ocr
