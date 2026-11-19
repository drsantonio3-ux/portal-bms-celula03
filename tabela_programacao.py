# -*- coding: utf-8 -*-
"""Tabela "Programação de Coleta e Entrega" (BMS / IQVIA) para copiar e colar no e-mail.

A tabela é editável direto na tela, salva no navegador (localStorage) e o botão
"Copiar tabela" copia o visual pronto para colar no Outlook.
"""

import json

LOGOS = {
 "drs": {
  "src": "data:image/png;base64,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",
  "w": 46,
  "h": 54
 },
 "bms": {
  "src": "data:image/png;base64,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",
  "w": 219,
  "h": 36
 },
 "iqvia": {
  "src": "data:image/png;base64,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",
  "w": 159,
  "h": 35
 }
}

HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; }
  body { margin: 0; padding: 4px 0 24px 0; font-family: 'Inter', 'Segoe UI', Verdana, sans-serif; background: transparent; color: #141414; }
  .barra { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 10px; }
  .grupo { display: flex; gap: 8px; flex-wrap: wrap; }
  button { font-family: inherit; font-size: 13px; font-weight: 700; border-radius: 8px; cursor: pointer; padding: 9px 16px; transition: .15s; }
  .tab, .acao { background: #ffffff; color: #141414; border: 1.5px solid #141414; }
  .tab:hover, .acao:hover { background: #141414; color: #f28c1b; }
  .tab.ativa { background: #f28c1b; border-color: #f28c1b; color: #111111; }
  .principal { background: #f28c1b; color: #111111; border: 1.5px solid #f28c1b; }
  .principal:hover { background: #141414; border-color: #141414; color: #f28c1b; }
  .acao.confirmar { background: #141414; color: #f28c1b; }
  .opcoes { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; margin: 4px 0 12px 0; font-size: 12.5px; color: #4b5563; }
  .opcoes label { display: flex; align-items: center; gap: 6px; cursor: pointer; font-weight: 600; color: #141414; }
  .opcoes input { accent-color: #f28c1b; width: 15px; height: 15px; }
  .dica { line-height: 1.45; }

  #wrap { position: relative; width: 695px; margin: 0 auto; }
  #gutter { position: absolute; left: 703px; top: 0; width: 26px; }
  #gutter button.del { position: absolute; left: 0; width: 22px; height: 22px; padding: 0; line-height: 18px; font-size: 15px;
      border-radius: 50%; border: 1px solid #d1d5db; background: #ffffff; color: #6b7280; opacity: .35; }
  #gutter button.del:hover { opacity: 1; background: #141414; color: #f28c1b; border-color: #141414; }
  td.cel:focus { outline: 2px solid #f28c1b; outline-offset: -2px; background: #fff7ed !important; }
  td.cel { cursor: text; }

  #toast { position: fixed; bottom: 14px; right: 14px; background: #141414; color: #f28c1b; padding: 10px 18px; border-radius: 8px;
      font-size: 13px; font-weight: 700; display: none; box-shadow: 0 4px 12px rgba(0,0,0,.3); z-index: 20; }
</style>
</head>
<body>
<div id="app">
  <div class="barra">
    <div class="grupo">
      <button class="tab" data-cli="iqvia">IQVIA</button>
      <button class="tab" data-cli="bms">BMS</button>
    </div>
    <div class="grupo">
      <button class="acao" id="btn-add">+ Adicionar centro</button>
      <button class="acao" id="btn-rem">− Remover última linha</button>
      <button class="acao" id="btn-limpar">Limpar tabela</button>
      <button class="principal" id="btn-copiar">Copiar tabela</button>
    </div>
  </div>
  <div class="opcoes">
    <label><input type="checkbox" id="chk-vazias"> Ignorar linhas vazias ao copiar</label>
    <span class="dica">Clique nas células para editar (Enter desce para a próxima linha; Tab vai para a próxima célula).
      Dá para colar direto do Excel. Datas como <b>1911</b> ou <b>19/11</b> viram <b>19/11/2026</b> sozinhas.
      Tudo fica salvo neste navegador.</span>
  </div>
  <div id="palco"></div>
</div>
<div id="toast"></div>

<script>
const LOGOS = __LOGOS_JSON__;
const CHAVE = 'drs_tabela_programacao_v1';
const LIMITE_LINHAS = 80;

const CLIENTES = {
  bms:   { rotulo: 'BMS',   logo: 'bms',   linhas: 11, colunas: [
            { t: 'TN', w: 124 }, { t: 'Centro', w: 284 },
            { t: 'Data de coleta', w: 139, data: true }, { t: 'Data de entrega', w: 148, data: true } ] },
  iqvia: { rotulo: 'IQVIA', logo: 'iqvia', linhas: 1, colunas: [
            { t: 'TN', w: 124 }, { t: 'Centro', w: 260 },
            { t: 'Kit envio', w: 170 }, { t: 'Data de entrega', w: 141, data: true } ] }
};

function linhaVazia(cli) { return CLIENTES[cli].colunas.map(() => ''); }
function tabelaVazia(cli) { return Array.from({ length: CLIENTES[cli].linhas }, () => linhaVazia(cli)); }

function carregar() {
  const base = { cliente: 'bms', ignorar: true, dados: { bms: tabelaVazia('bms'), iqvia: tabelaVazia('iqvia') } };
  let salvo = null;
  try { salvo = JSON.parse(localStorage.getItem(CHAVE)); } catch (e) {}
  if (!salvo || typeof salvo !== 'object') return base;
  if (CLIENTES[salvo.cliente]) base.cliente = salvo.cliente;
  if (typeof salvo.ignorar === 'boolean') base.ignorar = salvo.ignorar;
  ['bms', 'iqvia'].forEach(cli => {
    const linhas = salvo.dados && Array.isArray(salvo.dados[cli]) ? salvo.dados[cli] : null;
    if (!linhas || !linhas.length) return;
    const n = CLIENTES[cli].colunas.length;
    base.dados[cli] = linhas.slice(0, LIMITE_LINHAS).map(l => {
      const nova = linhaVazia(cli);
      if (Array.isArray(l)) for (let i = 0; i < n; i++) nova[i] = String(l[i] == null ? '' : l[i]);
      return nova;
    });
  });
  return base;
}
let estado = carregar();
function salvar() { try { localStorage.setItem(CHAVE, JSON.stringify(estado)); } catch (e) {} }

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function dados() { return estado.dados[estado.cliente]; }
function pad(n) { return String(n).padStart(2, '0'); }

function formatarData(txt) {
  const t = (txt || '').trim();
  if (!t) return t;
  const ano = new Date().getFullYear();
  let m;
  const valido = (d, mo) => +d >= 1 && +d <= 31 && +mo >= 1 && +mo <= 12;
  if ((m = t.match(/^(\d{1,2})[\/\.\-](\d{1,2})$/)) && valido(m[1], m[2])) return pad(m[1]) + '/' + pad(m[2]) + '/' + ano;
  if ((m = t.match(/^(\d{1,2})[\/\.\-](\d{1,2})[\/\.\-](\d{2}|\d{4})$/)) && valido(m[1], m[2]))
    return pad(m[1]) + '/' + pad(m[2]) + '/' + (m[3].length === 2 ? '20' + m[3] : m[3]);
  if (/^\d+$/.test(t)) {
    if (t.length === 4 && valido(t.slice(0, 2), t.slice(2, 4))) return t.slice(0, 2) + '/' + t.slice(2, 4) + '/' + ano;
    if (t.length === 6 && valido(t.slice(0, 2), t.slice(2, 4))) return t.slice(0, 2) + '/' + t.slice(2, 4) + '/20' + t.slice(4, 6);
    if (t.length === 8 && valido(t.slice(0, 2), t.slice(2, 4))) return t.slice(0, 2) + '/' + t.slice(2, 4) + '/' + t.slice(4, 8);
  }
  return t;
}

function lerCelula(td) {
  let out = '';
  td.childNodes.forEach(n => {
    if (n.nodeType === 3) out += n.nodeValue;
    else if (n.nodeName === 'BR') out += '\n';
    else out += '\n' + n.textContent;
  });
  return out.replace(/\u00a0/g, ' ').replace(/^\n+|\n+$/g, '').trim();
}

function render(focar) {
  const cli = CLIENTES[estado.cliente];
  const logoCli = LOGOS[cli.logo];
  const n = cli.colunas.length;

  let h = '<div id="wrap">';
  h += '<table id="tabela-email" width="695" cellpadding="0" cellspacing="0" border="0" ' +
       'style="width:695px;border-collapse:collapse;border:1px solid #dbe5e1;background:#ffffff;font-family:Verdana,Geneva,Arial,sans-serif;">';

  // topo: logos
  h += '<tr><td colspan="' + n + '" align="center" style="padding:16px 0;border-bottom:3px solid #1aa88a;background:#ffffff;">' +
       '<table cellpadding="0" cellspacing="0" border="0" align="center" style="margin:0 auto;"><tr>' +
       '<td valign="middle"><img src="' + LOGOS.drs.src + '" width="' + LOGOS.drs.w + '" height="' + LOGOS.drs.h + '" alt="DRS Group" style="display:block;border:0;"></td>' +
       '<td width="46" style="width:46px;">&nbsp;</td>' +
       '<td valign="middle"><img src="' + logoCli.src + '" width="' + logoCli.w + '" height="' + logoCli.h + '" alt="' + cli.rotulo + '" style="display:block;border:0;"></td>' +
       '</tr></table></td></tr>';

  // título
  h += '<tr><td colspan="' + n + '" align="center" style="padding:14px 0 12px 0;background:#ffffff;font-size:18px;font-weight:bold;color:#0b6b57;">' +
       'Programação de Coleta e Entrega</td></tr>';

  // cabeçalho das colunas
  h += '<tr class="cab">';
  cli.colunas.forEach(col => {
    h += '<td width="' + col.w + '" align="center" style="width:' + col.w + 'px;padding:12px 8px;background:#d7ebe5;color:#0b6b57;' +
         'font-size:14px;font-weight:bold;text-align:center;border-bottom:2px solid #0e6b56;">' + esc(col.t) + '</td>';
  });
  h += '</tr>';

  // linhas
  dados().forEach((linha, r) => {
    const bg = r % 2 === 0 ? '#ffffff' : '#f2f7f5';
    h += '<tr class="linha">';
    cli.colunas.forEach((col, c) => {
      h += '<td class="cel" contenteditable="true" data-r="' + r + '" data-c="' + c + '"' + (col.data ? ' data-data="1"' : '') +
           ' width="' + col.w + '" align="center" style="width:' + col.w + 'px;height:35px;padding:6px 8px;border-bottom:1px solid #e3ece8;' +
           'background:' + bg + ';font-size:14px;color:#1f2937;text-align:center;vertical-align:middle;">' +
           esc(linha[c]).replace(/\n/g, '<br>') + '</td>';
    });
    h += '</tr>';
  });

  // rodapé
  h += '<tr><td colspan="' + n + '" align="center" style="padding:9px 0;background:#0e6b56;color:#ffffff;font-size:12px;">DRS Group · Go beyond</td></tr>';
  h += '</table><div id="gutter"></div></div>';

  document.getElementById('palco').innerHTML = h;
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('ativa', b.dataset.cli === estado.cliente));
  document.getElementById('chk-vazias').checked = estado.ignorar;
  posicionarDel();

  if (focar) {
    const alvo = document.querySelector('td.cel[data-r="' + focar[0] + '"][data-c="' + focar[1] + '"]');
    if (alvo) alvo.focus();
  }
}

function posicionarDel() {
  const wrap = document.getElementById('wrap');
  const gutter = document.getElementById('gutter');
  if (!wrap || !gutter) return;
  gutter.innerHTML = '';
  const topoWrap = wrap.getBoundingClientRect().top;
  document.querySelectorAll('#tabela-email tr.linha').forEach((tr, r) => {
    const rect = tr.getBoundingClientRect();
    const b = document.createElement('button');
    b.className = 'del';
    b.textContent = '×';
    b.title = 'Remover esta linha';
    b.style.top = (rect.top - topoWrap + rect.height / 2 - 11) + 'px';
    b.addEventListener('click', () => removerLinha(r));
    gutter.appendChild(b);
  });
}

function avisar(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.display = 'block';
  clearTimeout(avisar._t);
  avisar._t = setTimeout(() => { t.style.display = 'none'; }, 2600);
}

function adicionarLinha() {
  if (dados().length >= LIMITE_LINHAS) { avisar('Limite de linhas atingido.'); return; }
  dados().push(linhaVazia(estado.cliente));
  salvar();
  render([dados().length - 1, 0]);
}

function removerLinha(r) {
  if (dados().length <= 1) { dados()[0] = linhaVazia(estado.cliente); }
  else dados().splice(r, 1);
  salvar();
  render();
}

// ---------- eventos ----------
const palco = document.getElementById('palco');

palco.addEventListener('input', e => {
  const td = e.target.closest('td.cel');
  if (!td) return;
  dados()[+td.dataset.r][+td.dataset.c] = lerCelula(td);
  salvar();
  posicionarDel();
});

palco.addEventListener('focusout', e => {
  const td = e.target.closest ? e.target.closest('td.cel[data-data]') : null;
  if (!td) return;
  const original = lerCelula(td);
  const formatado = formatarData(original);
  if (formatado !== original) {
    td.textContent = formatado;
    dados()[+td.dataset.r][+td.dataset.c] = formatado;
    salvar();
  }
});

palco.addEventListener('keydown', e => {
  const td = e.target.closest('td.cel');
  if (!td || e.key !== 'Enter' || e.shiftKey) return;
  e.preventDefault();
  const r = +td.dataset.r, c = +td.dataset.c;
  if (r + 1 >= dados().length) {
    if (dados().length >= LIMITE_LINHAS) return;
    dados().push(linhaVazia(estado.cliente));
    salvar();
    render([r + 1, c]);
  } else {
    const prox = document.querySelector('td.cel[data-r="' + (r + 1) + '"][data-c="' + c + '"]');
    if (prox) prox.focus();
  }
});

palco.addEventListener('paste', e => {
  const td = e.target.closest('td.cel');
  if (!td) return;
  e.preventDefault();
  const texto = (e.clipboardData || window.clipboardData).getData('text/plain') || '';
  let linhas = texto.replace(/\r/g, '').split('\n');
  if (linhas.length > 1 && linhas[linhas.length - 1] === '') linhas.pop();
  const grade = linhas.map(l => l.split('\t'));
  const ehGrade = grade.length > 1 || grade[0].length > 1;
  if (!ehGrade) { document.execCommand('insertText', false, texto.trim()); return; }

  const cli = CLIENTES[estado.cliente];
  const r0 = +td.dataset.r, c0 = +td.dataset.c;
  grade.forEach((cols, i) => {
    const r = r0 + i;
    if (r >= LIMITE_LINHAS) return;
    while (dados().length <= r) dados().push(linhaVazia(estado.cliente));
    cols.forEach((valor, j) => {
      const c = c0 + j;
      if (c >= cli.colunas.length) return;
      const v = valor.trim();
      dados()[r][c] = cli.colunas[c].data ? formatarData(v) : v;
    });
  });
  salvar();
  render([Math.min(r0 + grade.length - 1, dados().length - 1), c0]);
});

document.querySelectorAll('.tab').forEach(b => b.addEventListener('click', () => {
  estado.cliente = b.dataset.cli;
  salvar();
  render();
}));
document.getElementById('btn-add').addEventListener('click', adicionarLinha);
document.getElementById('btn-rem').addEventListener('click', () => removerLinha(dados().length - 1));
document.getElementById('chk-vazias').addEventListener('change', e => { estado.ignorar = e.target.checked; salvar(); });

// "Limpar tabela" com confirmação em 2 cliques (sem janela pop-up)
(function () {
  const btn = document.getElementById('btn-limpar');
  let aguardando = false, timer = null;
  btn.addEventListener('click', () => {
    if (!aguardando) {
      aguardando = true;
      btn.textContent = 'Clique de novo para confirmar';
      btn.classList.add('confirmar');
      timer = setTimeout(reset, 3500);
      return;
    }
    estado.dados[estado.cliente] = tabelaVazia(estado.cliente);
    salvar();
    render();
    avisar('Tabela ' + CLIENTES[estado.cliente].rotulo + ' limpa.');
    reset();
  });
  function reset() {
    aguardando = false;
    clearTimeout(timer);
    btn.textContent = 'Limpar tabela';
    btn.classList.remove('confirmar');
  }
})();

// ---------- copiar para o e-mail ----------
function montarCopia() {
  const clone = document.getElementById('tabela-email').cloneNode(true);
  clone.querySelectorAll('td.cel').forEach(td => {
    ['contenteditable', 'data-r', 'data-c', 'data-data', 'class'].forEach(a => td.removeAttribute(a));
  });
  let linhas = Array.from(clone.querySelectorAll('tr.linha'));
  if (estado.ignorar) {
    const preenchidas = linhas.filter(tr => Array.from(tr.querySelectorAll('td')).some(td => td.textContent.replace(/\u00a0/g, '').trim() !== ''));
    if (preenchidas.length) linhas.filter(tr => !preenchidas.includes(tr)).forEach(tr => tr.remove());
    linhas = Array.from(clone.querySelectorAll('tr.linha'));
  }
  linhas.forEach((tr, i) => {
    tr.removeAttribute('class');
    tr.querySelectorAll('td').forEach(td => {
      td.style.background = i % 2 === 0 ? '#ffffff' : '#f2f7f5';
      if (td.textContent.trim() === '') td.innerHTML = '&nbsp;';
    });
  });
  clone.querySelectorAll('tr.cab').forEach(tr => tr.removeAttribute('class'));
  clone.removeAttribute('id');
  return clone;
}

function textoSimples(clone) {
  return Array.from(clone.querySelectorAll('tr')).filter(tr => tr.querySelectorAll('td').length > 1)
    .map(tr => Array.from(tr.querySelectorAll('td')).map(td => td.innerText || td.textContent).join('\t')).join('\n');
}

async function copiarTabela() {
  const clone = montarCopia();
  const area = document.createElement('div');
  area.style.cssText = 'position:fixed;left:-10000px;top:0;background:#ffffff;';
  area.appendChild(clone);
  document.body.appendChild(area);

  let ok = false;
  try {
    const sel = window.getSelection();
    const faixa = document.createRange();
    faixa.selectNode(clone);
    sel.removeAllRanges();
    sel.addRange(faixa);
    ok = document.execCommand('copy');
    sel.removeAllRanges();
  } catch (e) { ok = false; }

  if (!ok && navigator.clipboard && window.ClipboardItem) {
    try {
      await navigator.clipboard.write([new ClipboardItem({
        'text/html': new Blob([clone.outerHTML], { type: 'text/html' }),
        'text/plain': new Blob([textoSimples(clone)], { type: 'text/plain' })
      })]);
      ok = true;
    } catch (e) { ok = false; }
  }
  area.remove();
  avisar(ok ? 'Tabela copiada! Cole no e-mail com Ctrl+V.' : 'Não consegui copiar — tente de novo.');
}
document.getElementById('btn-copiar').addEventListener('click', copiarTabela);

render();
</script>
</body>
</html>
'''


def html_tabela_programacao():
    return HTML_TEMPLATE.replace("__LOGOS_JSON__", json.dumps(LOGOS))
