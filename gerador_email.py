# -*- coding: utf-8 -*-
"""Gerador de E-mail (GR): monta o HTML da página a partir dos dados lidos da Packing List."""


def _escapar(valor):
    return (valor or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _item_box(descricao="", lote="", validade="", quantidade="", removivel=True):
    botao_remover = '<button type="button" class="remove-btn" onclick="this.parentElement.remove();">X</button>' if removivel else ""
    return f"""
        <div class="item-box">
          {botao_remover}
          <div class="form-group full-width" style="margin-bottom: 10px;">
            <label>DESCRIPTION (Descrição Completa do Material): <span class="required">*</span></label>
            <input type="text" class="item-desc" placeholder="Ex: DEXAMETH TAB 4MG (1BLCRDX20) CA088 OLMUL" value="{_escapar(descricao)}" required>
          </div>
          <div class="form-grid">
            <div class="form-group">
              <label>BATCH NUMBER (Lote): <span class="required">*</span></label>
              <input type="text" class="item-batch" placeholder="Ex: ADA3486" value="{_escapar(lote)}" required>
            </div>
            <div class="form-group">
              <label>EXP. DATE (Validade DD/MM/AAAA): <span class="required">*</span></label>
              <input type="text" class="item-exp" placeholder="Ex: 30/06/2030" value="{_escapar(validade)}" required>
            </div>
          </div>
          <div class="form-group full-width" style="margin-top: 10px;">
            <label>QUANTITY (Quantidade): <span class="required">*</span></label>
            <input type="text" class="item-qty" placeholder="Ex: 80" value="{_escapar(quantidade)}" required>
          </div>
        </div>"""


GERADOR_EMAIL_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Gerador de E-mail de Recebimento / Liberação (Goods Receipt)</title>
  <style>
    * {
      box-sizing: border-box;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    body {
      background-color: #f3f4f6;
      margin: 0;
      padding: 20px;
      color: #1f2937;
    }
    .main-title {
      text-align: center;
      color: #141414;
      margin-bottom: 25px;
      font-size: 24px;
      font-weight: 800;
    }
    .main-title span { color: #f28c1b; }
    .app-container {
      max-width: 1200px;
      margin: 0 auto;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
    }
    @media (max-width: 900px) {
      .app-container { grid-template-columns: 1fr; }
    }
    .card {
      background: #ffffff;
      border-radius: 10px;
      padding: 20px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.06);
      border: 1px solid #e2e4e8;
      margin-bottom: 20px;
    }
    .card-title {
      color: #141414;
      font-size: 16px;
      font-weight: 700;
      margin-top: 0;
      margin-bottom: 18px;
      border-left: 4px solid #f28c1b;
      padding-left: 10px;
    }
    .form-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 15px;
    }
    .form-group { display: flex; flex-direction: column; }
    .form-group.full-width { grid-column: span 2; }
    label {
      font-size: 13px;
      color: #4b5563;
      margin-bottom: 5px;
      font-weight: 500;
    }
    label .required { color: #d97706; font-weight: bold; }
    input[type="text"], textarea {
      padding: 10px 12px;
      border: 1px solid #d1d5db;
      border-radius: 6px;
      font-size: 14px;
      outline: none;
      transition: border-color 0.2s;
    }
    input[type="text"]:focus, textarea:focus { border-color: #f28c1b; }
    input[readonly] {
      background-color: #e5e7eb;
      cursor: not-allowed;
      color: #374151;
      font-weight: 600;
    }
    .item-box {
      border: 1px dashed #9ca3af;
      border-radius: 6px;
      padding: 15px;
      margin-bottom: 15px;
      background-color: #fafafa;
      position: relative;
    }
    .remove-btn {
      position: absolute;
      top: 8px;
      right: 8px;
      background: #374151;
      color: white;
      border: none;
      border-radius: 4px;
      padding: 2px 8px;
      font-size: 12px;
      cursor: pointer;
    }
    .remove-btn:hover { background: #111827; }
    .btn-secondary {
      background-color: #4b5563;
      color: white;
      border: none;
      padding: 8px 14px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
      margin-bottom: 15px;
    }
    .btn-secondary:hover { background-color: #374151; }
    .btn-primary {
      background-color: #f28c1b;
      color: #111111;
      border: none;
      padding: 12px;
      border-radius: 6px;
      font-weight: bold;
      font-size: 15px;
      width: 100%;
      cursor: pointer;
      transition: background 0.2s;
    }
    .btn-primary:hover { background-color: #141414; color: #f28c1b; }
    .btn-copy {
      background-color: #141414;
      color: #f28c1b;
      border: none;
      padding: 8px 14px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
      margin-top: 8px;
      margin-bottom: 15px;
    }
    .btn-copy:hover { background-color: #2b2b2b; }
    .readonly-box {
      background-color: #e5e7eb;
      border: 1px solid #d1d5db;
      padding: 10px 12px;
      border-radius: 6px;
      font-size: 14px;
      font-weight: 600;
      color: #111827;
      word-break: break-all;
      min-height: 40px;
    }
    .email-preview-container {
      border: 1px solid #d1d5db;
      border-radius: 6px;
      padding: 15px;
      background: #ffffff;
      min-height: 250px;
      max-height: 450px;
      overflow-y: auto;
      font-family: Arial, sans-serif;
      font-size: 13px;
      color: #000;
      line-height: 1.4;
    }
    .preview-table { border-collapse: collapse; width: 100%; margin: 12px 0; }
    .preview-table th, .preview-table td {
      border: 1px solid #000;
      padding: 6px 8px;
      font-family: Arial, sans-serif;
      font-size: 12px;
    }
    .preview-table th {
      font-weight: bold;
      font-style: italic;
      text-align: center;
      text-transform: uppercase;
      background-color: #ffffff;
    }
    .preview-table td { text-align: center; }
    .toast {
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: #141414;
      color: #f28c1b;
      padding: 10px 20px;
      border-radius: 6px;
      box-shadow: 0 4px 10px rgba(0,0,0,0.25);
      display: none;
      z-index: 1000;
      font-weight: 600;
    }
  </style>
</head>
<body>
  <div class="main-title">Gerador de E-mail de Recebimento / Liberação <span>(Goods Receipt)</span></div>
  <div class="app-container">
    <!-- Coluna da Esquerda: Formulários -->
    <div>
      <form id="emailForm" onsubmit="event.preventDefault(); generateEmail();">
        <div class="card">
          <div class="card-title">1. Informações do Recebimento (Packing List / Documentação)</div>
          <div class="form-grid">
            <div class="form-group">
              <label for="grNumber">Número GR: <span class="required">*</span></label>
              <input type="text" id="grNumber" value="TO8616" readonly title="Número GR fixo">
            </div>
            <div class="form-group">
              <label for="delNumber">Delivery Number (DEL#): <span class="required">*</span></label>
              <input type="text" id="delNumber" placeholder="Ex: 8020016643" value="__DEL_VALUE_GR__" required>
            </div>
            <div class="form-group">
              <label for="protocolNumber">Protocol Number: <span class="required">*</span></label>
              <input type="text" id="protocolNumber" placeholder="Ex: CA088-1007" value="__PROTOCOLO_VALUE_GR__" required>
            </div>
            <div class="form-group">
              <label for="orderNumber">Order Number: <span class="required">*</span></label>
              <input type="text" id="orderNumber" placeholder="Ex: 45801492" value="__ORDER_VALUE_GR__" required>
            </div>
            <div class="form-group">
              <label for="invoiceNumber">Brazilian Invoice: <span class="required">*</span></label>
              <input type="text" id="invoiceNumber" placeholder="Ex: 40533-1" required>
            </div>
            <div class="form-group">
              <label for="cesvNumber">CESV: <span class="required">*</span></label>
              <input type="text" id="cesvNumber" placeholder="Ex: 2601002022" required>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-title">2. Itens do Recebimento (Material / Lotes)</div>
          <div id="itemsContainer">
            <!--ITENS_PLACEHOLDER_GR-->
          </div>
          <button type="button" class="btn-secondary" onclick="addItem()">+ Adicionar Mais um Item</button>
          <button type="submit" class="btn-primary">Gerar Texto do E-mail</button>
        </div>
      </form>
    </div>
    <!-- Coluna da Direita: Destinatários e Preview -->
    <div>
      <div class="card">
        <div class="card-title">3. Destinatários do E-mail (Para / CC)</div>
        <div class="form-group">
          <label>E-mails para Copiar:</label>
          <textarea id="recipients" rows="4">BMSOPSBLA@BMS.COM; Radu.Ciobanescu@bms.com; laura.sourwine@bms.com; cso.distribution@bms.com; MG-BRZ-IMPORT-CTA@bms.com; daniela.mizushima@bms.com</textarea>
        </div>
        <button type="button" class="btn-copy" onclick="copyRecipients()">Copiar Destinatários</button>
      </div>
      <div class="card">
        <div class="card-title">4. Preview do E-mail Gerado</div>

        <div class="form-group" style="margin-bottom: 5px;">
          <label>Assunto do E-mail (Subject Line):</label>
          <div class="readonly-box" id="subjectBox">BMS/GR/TO8616/DEL#</div>
        </div>
        <button type="button" class="btn-copy" onclick="copySubject()">Copiar Assunto</button>
        <div class="form-group" style="margin-bottom: 5px; margin-top: 10px;">
          <label>Corpo do E-mail (Body):</label>
          <div class="email-preview-container" id="emailBodyContainer" contenteditable="true">
            <p style="color: #6b7280;">Preencha os campos ao lado e clique em "Gerar Texto do E-mail"...</p>
          </div>
        </div>
        <button type="button" class="btn-copy" onclick="copyBody()">Copiar Corpo do E-mail</button>
      </div>
    </div>
  </div>
  <div class="toast" id="toastNotification">Copiado com sucesso!</div>
  <script>
    function addItem() {
      const container = document.getElementById('itemsContainer');
      const itemBox = document.createElement('div');
      itemBox.className = 'item-box';
      itemBox.innerHTML = `
        <button type="button" class="remove-btn" onclick="this.parentElement.remove();">X</button>
        <div class="form-group full-width" style="margin-bottom: 10px;">
          <label>DESCRIPTION (Descrição Completa do Material): <span class="required">*</span></label>
          <input type="text" class="item-desc" placeholder="Ex: DEXAMETH TAB 4MG (1BLCRDX20) CA088 OLMUL" required>
        </div>
        <div class="form-grid">
          <div class="form-group">
            <label>BATCH NUMBER (Lote): <span class="required">*</span></label>
            <input type="text" class="item-batch" placeholder="Ex: ADA3486" required>
          </div>
          <div class="form-group">
            <label>EXP. DATE (Validade DD/MM/AAAA): <span class="required">*</span></label>
            <input type="text" class="item-exp" placeholder="Ex: 30/06/2030" required>
          </div>
        </div>
        <div class="form-group full-width" style="margin-top: 10px;">
          <label>QUANTITY (Quantidade): <span class="required">*</span></label>
          <input type="text" class="item-qty" placeholder="Ex: 80" required>
        </div>
      `;
      container.appendChild(itemBox);
    }
    function generateEmail() {
      const gr = document.getElementById('grNumber').value.trim();
      const del = document.getElementById('delNumber').value.trim();
      const protocol = document.getElementById('protocolNumber').value.trim();
      const order = document.getElementById('orderNumber').value.trim();
      const invoice = document.getElementById('invoiceNumber').value.trim();
      const cesv = document.getElementById('cesvNumber').value.trim();
      const subject = `BMS/GR/${gr}/DEL#${del}`;
      document.getElementById('subjectBox').innerText = subject;
      const itemBoxes = document.querySelectorAll('#itemsContainer .item-box');
      let tableRows = '';
      itemBoxes.forEach(box => {
        const desc = box.querySelector('.item-desc').value.trim();
        const batch = box.querySelector('.item-batch').value.trim();
        const exp = box.querySelector('.item-exp').value.trim();
        const qty = box.querySelector('.item-qty').value.trim();
        tableRows += `
          <tr>
            <td style="text-align: center;">${desc}</td>
            <td style="text-align: center;">${batch}</td>
            <td style="text-align: center;">${exp}</td>
            <td style="text-align: center;">${qty}</td>
          </tr>
        `;
      });
      const tableHtml = `
        <table class="preview-table">
          <thead>
            <tr>
              <th>DESCRIPTION</th>
              <th>BATCH NUMBER</th>
              <th>EXP. DATE</th>
              <th>QUANTITY</th>
            </tr>
          </thead>
          <tbody>
            ${tableRows}
          </tbody>
        </table>
      `;
      const bodyHtml = `
        <div>Dear all,</div>
        <br>
        <div>I would like to inform you that we have received at DRS the following items to ${protocol}.</div>
        <br>
        <div><strong>BRAZILIAN INVOICE</strong> ${invoice}</div>
        <div><strong>CESV</strong> ${cesv}</div>
        <div><strong>Order Number:</strong> ${order}</div>
        <div><strong>DEL#${del}</strong></div>
        ${tableHtml}
        <div>All the goods receipt has been double inspected.</div>
        <br>
        <ul style="margin-top: 0; margin-bottom: 0; padding-left: 20px;">
          <li>Find attached the signed Packing List.</li>
          <li>Find attached the Temperature Graphics received.</li>
        </ul>
      `;
      document.getElementById('emailBodyContainer').innerHTML = bodyHtml;
    }
    function showToast(msg) {
      const toast = document.getElementById('toastNotification');
      toast.innerText = msg;
      toast.style.display = 'block';
      setTimeout(() => { toast.style.display = 'none'; }, 2000);
    }
    function copyRecipients() {
      const text = document.getElementById('recipients').value;
      navigator.clipboard.writeText(text);
      showToast('Destinatários copiados!');
    }
    function copySubject() {
      const text = document.getElementById('subjectBox').innerText;
      navigator.clipboard.writeText(text);
      showToast('Assunto copiado!');
    }
    function copyBody() {
      const container = document.getElementById('emailBodyContainer');
      const range = document.createRange();
      range.selectNodeContents(container);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      try {
        document.execCommand('copy');
        showToast('Corpo do e-mail copiado com formatação e tabela!');
      } catch (err) {
        showToast('Erro ao copiar!');
      }
      selection.removeAllRanges();
    }
  </script>
</body>
</html>
"""


def montar_html_gerador(dados_gr):
    """dados_gr: dict lido da Packing List (delivery, protocolo, order, itens) ou None."""
    dados_gr = dados_gr or {}
    itens = dados_gr.get("itens") or []
    if itens:
        itens_html = "".join(
            _item_box(
                descricao=item.get("descricao", ""),
                lote=item.get("lote", ""),
                validade=item.get("validade", ""),
                quantidade=item.get("quantidade", ""),
                removivel=(i > 0),
            )
            for i, item in enumerate(itens)
        )
    else:
        itens_html = _item_box(removivel=False)

    return (
        GERADOR_EMAIL_HTML
        .replace("__DEL_VALUE_GR__", _escapar(dados_gr.get("delivery", "")))
        .replace("__PROTOCOLO_VALUE_GR__", _escapar(dados_gr.get("protocolo", "")))
        .replace("__ORDER_VALUE_GR__", _escapar(dados_gr.get("order", "")))
        .replace("<!--ITENS_PLACEHOLDER_GR-->", itens_html)
    )
