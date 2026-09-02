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

## Limitações conhecidas (não corrigidas nesta rodada, por serem mudanças maiores)

- **Uso simultâneo**: se duas pessoas derem baixa em itens de estoque quase ao mesmo tempo, existe uma janela pequena em que ambas podem "ver" o mesmo item como disponível antes da planilha atualizar. Isso ficou um pouco mais seguro nesta atualização (o item só some depois da confirmação), mas a janela de concorrência em si ainda existe.
- **Sem identificação de quem fez a baixa**: como todo mundo usa a mesma senha, não dá para saber pelo próprio app qual pessoa da equipe executou cada baixa.
- **Lista de feriados**: hoje só tem 07/09/2026 cadastrado (`FERIADOS` no início da página de Automação). Precisa ser atualizada manualmente todo ano.
- **Aviso ao fechar/atualizar a aba do navegador** é "melhor esforço": a maioria dos navegadores modernos respeita esse aviso, mas alguns podem ignorá-lo silenciosamente. A trava dos botões do menu lateral é a garantia principal.
