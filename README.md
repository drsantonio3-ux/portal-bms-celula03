# Portal BMS — DRS Group

Painel interno (Streamlit) para automação de Packing List, baixa de estoque e conferência de documentos da célula BMS.

## Como colocar o app no ar (passo a passo)

1. Acesse **https://share.streamlit.io** e faça login com a mesma conta do GitHub usada neste repositório.
2. Clique em **"New app"** (ou "Create app").
3. Escolha:
   - Repository: `drsantonio3-ux/portal-bms-celula03`
   - Branch: `main`
   - Main file path: `portal_bms.py`
4. **Antes de clicar em Deploy**, clique em **"Advanced settings"** e cole no campo de Secrets (formato TOML):

   ```toml
   SENHA_ACESSO = "escolha-uma-senha-forte-aqui"
   ```

   Sem isso o app mostra uma mensagem pedindo para configurar a senha e não libera o acesso — é proposital, para ninguém usar uma senha padrão fraca.
5. Clique em **Deploy**. Em 1–2 minutos o app estará no ar com uma URL do tipo `https://algumacoisa.streamlit.app`.
6. Envie essa URL + a senha escolhida para a equipe (por WhatsApp, e-mail etc — fora do GitHub).

### Se precisar mudar a senha depois

No painel do app em share.streamlit.io: menu (⋮) do app → **Settings** → **Secrets** → edite o valor de `SENHA_ACESSO` → **Save**. O app reinicia sozinho.

### Atualizando o app no futuro

Qualquer alteração enviada (commit) para a branch `main` deste repositório é publicada automaticamente pelo Streamlit Community Cloud em poucos minutos — não precisa reimplantar manualmente. Para editar algo simples (um texto, uma cor), dá pra fazer direto pelo site do GitHub: abra o arquivo, clique no ícone de lápis (editar), altere e clique em "Commit changes".

## Importante — segurança (recomendado, não obrigatório)

O código-fonte deste app é público no GitHub, e por causa disso a URL do webhook do Google Apps Script (usado para dar baixa no estoque) e os IDs das duas planilhas do Google Sheets ficam visíveis para qualquer pessoa que abrir o repositório. Isso já era assim antes desta atualização.

Para reduzir esse risco, sem custo nenhum:

1. No Google Apps Script do webhook, vá em **Implantar → Gerenciar implantações → editar (ícone de lápis) → Nova versão → Implantar**. Isso gera uma **nova URL**.
2. Adicione a nova URL nos Secrets do app no Streamlit Cloud:

   ```toml
   SENHA_ACESSO = "sua-senha"
   WEBHOOK_BAIXA_ESTOQUE = "https://script.google.com/macros/s/NOVA_URL_AQUI/exec"
   ```

Isso é opcional — o app funciona normalmente sem esse passo, usando a URL antiga —, mas é uma boa prática já que a URL antiga ficou exposta. O mesmo vale, se quiser, para os IDs das planilhas (`ID_PLANILHA_ESTOQUE` e `ID_PLANILHA_LOGGERS`), embora o risco ali seja menor (acesso só de leitura).

## O que foi corrigido na primeira atualização

- Biblioteca de leitura de PDF trocada de `PyPDF2` (descontinuada) para `pypdf` (o sucessor mantido oficialmente).
- Extração de texto do PDF agora não quebra o app se alguma página vier sem texto (ex: PDF escaneado como imagem).
- A página **"Gerador de E-mail (GR)"**, que existia no menu mas não tinha conteúdo (tela em branco), agora mostra um aviso de "em construção" em vez de dar tela vazia.
- A senha de acesso não tem mais um valor padrão fraco escondido no código — precisa ser configurada nos Secrets (ver passo 4 acima).
- Se o nome de alguma coluna na planilha de Estoque mudar, o app não trava mais por completo para todo mundo — só desativa a parte de estoque com um aviso.
- IDs das planilhas e URL do webhook agora podem ser sobrescritos via Secrets (ver seção de segurança acima).

## O que mudou na segunda atualização (visual + regras de negócio)

- **Layout redesenhado**: fonte nova (Inter), paleta de cores da DRS Group reforçada, cartões com sombra e cantos arredondados, banners com gradiente, área de upload destacada, e a **página ativa no menu lateral agora fica destacada em verde escuro** (as outras ficam neutras) para deixar claro onde você está.
- **TempTale extra para citotóxicos**: quando a Packing List contém Bortezomib, Sprycel/Dasatinib, Paclitaxel/Taxol ou Cyclophosphamide/Ciclofosfamida, o sistema agora aloca automaticamente **um TempTale a mais** (além dos loggers normais), já que essas medicações precisam seguir em caixa separada.
- **Baixa de estoque mais segura**:
  - O item só é retirado da visão do estoque **depois** que a planilha central confirma a atualização (antes, ele já sumia mesmo se a baixa falhasse).
  - A mensagem de sucesso agora mostra claramente **qual DEL# foi usado para quais itens**.
  - Se você já deu baixa em um Packing List e ele continuar na tela (por exemplo, depois de um F5), o app **reconhece que aquele arquivo já foi processado** e mostra o DEL# já registrado em vez de tentar alocar itens novos de novo.
- **Trava de navegação**: enquanto houver uma alocação de estoque feita mas ainda **não confirmada** (DEL# não preenchido / botão "Executar Baixa" não clicado), os outros botões do menu lateral ficam **desabilitados** e aparece um aviso laranja fixo no topo da página, além de um alerta ao tentar fechar/atualizar a aba do navegador — tudo para evitar que um logger fique "no limbo": alocado mentalmente, mas não registrado no sistema.

## O que mudou na terceira atualização (fichas de segurança, contagem de loggers e Cruzamento)

- **Fichas de segurança automáticas**: quando a Packing List contém Bortezomib, Sprycel/Dasatinib, Taxol/Paclitaxel ou Cyclophosphamide/Ciclofosfamida, o sistema agora mostra um botão de download com a ficha de segurança correspondente, logo abaixo da separação de loggers — igual ao pedido de "clique aqui para salvar o arquivo".
- **PDF some sozinho depois da baixa**: depois de clicar em "Executar Baixa no Estoque" com sucesso, o campo de upload do PDF é limpo automaticamente — não precisa mais dar F5 para poder subir o próximo Packing List.
- **Contagem correta de loggers (TempTale / Tag Alert)**: a lógica antiga só enxergava "o documento tem TempTale em algum lugar" + "tem alguma medicação citotóxica" (e por isso só alocava no máximo 2: 1 normal + 1 "extra"). Agora o sistema lê a Packing List item por item e conta corretamente quantos loggers são realmente necessários: itens com a mesma faixa de temperatura e o mesmo status (citotóxico ou não) podem dividir 1 logger; itens citotóxicos nunca dividem caixa/logger com itens não citotóxicos. Isso foi validado com Packing Lists reais, incluindo casos de 1, 2 e 3 TempTale e casos com apenas 1 Tag Alert.
- **Cruzamento NEWSE x PACKING mais preciso**:
  - O nome do investigador não depende mais de uma lista fixa de 4 médicos — agora é lido diretamente do Packing List e conferido dentro do texto da NEWSE.
  - O nome do centro/instituição não fica mais restrito a 3 hospitais fixos; e quando o nome está escrito de formas diferentes nos dois sistemas mas o CEP de destino é idêntico, isso já é aceito como confirmação (em vez de bloquear a remessa só pela grafia do nome).
  - A quantidade total e os números de série agora são lidos diretamente da própria tabela de produtos da NEWSE (em vez de apenas verificar se os números do Packing List aparecem em algum lugar do texto da NEWSE, o que podia gerar falso positivo/negativo).
  - Todas essas mudanças foram validadas com um par real de documentos (NEWSE + Packing List do mesmo envio) e também testadas com documentos propositalmente diferentes, para confirmar que divergências reais continuam sendo detectadas.

## O que mudou na quarta atualização (BMS Brasil, correções de precisão e tela de login)

- **Nova página "BMS Brasil - Solicitações"**: para solicitações da BMS Brasil, que chegam só como NEWSE (sem Packing List com TAG/TEMP já definido), agora existe uma aba própria no menu lateral. Basta anexar o PDF da NEWSE que o sistema identifica sozinho o Protocolo, o TE do estudo e o Centro/Instituição, retira automaticamente **1 Tag Alert** (Ambiente ou Refrigerado, conforme a faixa de temperatura da própria NEWSE) — nunca TempTale, já que solicitações Brasil não usam esse logger — e grava o uso na planilha (mesmas abas "Auditoria" e "Loggers Já Utilizados") com o identificador fixo **"Solicitação Brasil"**, que não pode ser editado. Isso resolve o problema de precisar dar baixa manual, item por item, direto na planilha.
- **Ficha de segurança do Paclitaxel/Taxol agora aparece também para nab-Paclitaxel** (Abraxane): antes, o sistema tratava nab-Paclitaxel como um caso à parte só para fins de contagem de caixa/logger separado, e isso acabou fazendo a ficha de segurança não aparecer para ele também, por engano. Agora a ficha aparece nos dois casos; a regra de caixa/logger separado para citotóxicos continua funcionando normalmente.
- **Navegação não trava mais "para sempre"**: se você anexar um Packing List, o sistema alocar os loggers, e você decidir cancelar removendo o arquivo (clicando no "x" do upload) em vez de finalizar a baixa, a navegação para as outras páginas agora é liberada de novo automaticamente — antes ficava bloqueada até a página ser recarregada (F5).
- **Tela de login redesenhada** com a identidade visual da DRS Group (cores, cartão central com o selo "DRS" e menção à Célula 03 · BMS Operations), no lugar da tela genérica anterior.
- **Cruzamento NEWSE x PACKING — 3 correções de precisão**, encontradas testando com documentos reais:
  - Corrigido um bug em que um número de série de Tag Alert dentro da NEWSE (ex: "15450K53039") podia ser lido errado, capturando só o final do código como se fosse um número de série de produto.
  - O nome do centro/instituição agora também é confirmado corretamente quando ele não está na lista de nomes conhecidos, mas o CEP de destino bate entre os dois documentos (antes, esse caso podia passar despercebido).
  - O nome do investigador principal agora também é reconhecido quando há uma pequena diferença de digitação entre os dois documentos (ex: um nome do meio duplicado por engano em um dos sistemas), desde que o primeiro e o último nome batam.
- **Webhook de baixa de estoque corrigido**: o script que grava nas abas "Auditoria" e "Loggers Já Utilizados" estava procurando essas duas abas dentro da planilha errada (a de Estoque, em vez da planilha "LOGGER BMS", onde elas realmente ficam) — por isso a baixa "funcionava" (o item saía do estoque), mas o registro de rastreabilidade nunca era gravado, sem mostrar erro nenhum. **Esse arquivo precisa ser atualizado manualmente no Google Apps Script** (ver instruções enviadas junto com esta atualização) — só subir o `portal_bms.py` novo no GitHub não é suficiente para essa correção específica.

## O que mudou na quinta atualização (nova aba: Conferência de Agendamento)

- **Nova aba "Conferência de Agendamento"**: traz para dentro do Portal BMS o painel de auditoria em 3 etapas que já existia separado ("Validador DRS Group - Logística"), com os mesmos 3 estágios.
- **Sexta atualização — conferência de verdade em todos os campos:** a primeira versão desta aba só mostrava textos fixos tipo "Verificado no Portal" nos campos, sem checar nada de fato. Isso foi corrigido: agora **todo campo mostrado extrai e compara o valor real dos dois documentos**, lado a lado, e só aparece ✅ quando eles realmente batem — igual ao que já era feito na aba Cruzamento NEWSE x PACKING.
  - **Etapa 1 — Packing List x NEWSE**: confere Delivery Number x Número da Ordem (antes usava "IWRS Shipment Number", que não existe na Packing List — corrigido para o campo certo), Protocolo/Estudo, CEP de destino e o nome do Investigador da NEWSE (conferido no texto da Packing List). Além disso, a seção "Confronto Detalhado" agora compara **produto a produto** a Packing List (Material/Batch/Quantity/Use Date/Serial No.) com a NEWSE (Nome/Lote/Quantidade/Validade/Peça ou Série) — um número contando tanto no campo Peça quanto no campo Série da NEWSE — e mostra exatamente quais números de série conferem, quais faltam e se sobrou algum serial na NEWSE sem produto correspondente na Packing List.
  - **Etapa 2 — NEWSE x Agendamento**: confere Protocolo/Estudo, CNPJ do centro/destinatário, CEP e a lista de contatos autorizados de entrega (mostrando quantos dos contatos da NEWSE foram encontrados no e-mail de Agendamento, e quais estão faltando). A data/horário de entrega continua sendo ignorada de propósito nesta etapa.
  - **Etapa 3 — Auditoria Final (Minuta)**: confere Protocolo, CNPJ do remetente DRS (contra a lista de CNPJs oficiais), Tracking Number, CNPJ do destinatário, o nome do P.I. (contra o Investigador da NEWSE), a lista de contatos autorizados e a transportadora — todos comparados de verdade contra o texto da Minuta de Envio (SC).
  - Todas essas checagens foram validadas com um conjunto real de 4 documentos do mesmo envio (Packing List, NEWSE, Agendamento e Minuta), incluindo casos de teste propositalmente errados para confirmar que uma divergência real é sempre sinalizada.

## Limitações conhecidas (não corrigidas nesta rodada, por serem mudanças maiores)

- **Uso simultâneo**: se duas pessoas derem baixa em itens de estoque quase ao mesmo tempo, existe uma janela pequena em que ambas podem "ver" o mesmo item como disponível antes da planilha atualizar. Isso ficou um pouco mais seguro nesta atualização (o item só some depois da confirmação), mas a janela de concorrência em si ainda existe.
- **Sem identificação de quem fez a baixa**: como todo mundo usa a mesma senha, não dá para saber pelo próprio app qual pessoa da equipe executou cada baixa.
- **Lista de feriados**: hoje só tem 07/09/2026 cadastrado (`FERIADOS` no início da página de Automação). Precisa ser atualizada manualmente todo ano.
- **Aviso ao fechar/atualizar a aba do navegador** é "melhor esforço": a maioria dos navegadores modernos respeita esse aviso, mas alguns podem ignorá-lo silenciosamente. A trava dos botões do menu lateral é a garantia principal.
