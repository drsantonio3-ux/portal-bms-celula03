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

## O que foi corrigido nesta atualização

- Biblioteca de leitura de PDF trocada de `PyPDF2` (descontinuada) para `pypdf` (o sucessor mantido oficialmente).
- Extração de texto do PDF agora não quebra o app se alguma página vier sem texto (ex: PDF escaneado como imagem).
- A página **"Gerador de E-mail (GR)"**, que existia no menu mas não tinha conteúdo (tela em branco), agora mostra um aviso de "em construção" em vez de dar tela vazia.
- A senha de acesso não tem mais um valor padrão fraco escondido no código — precisa ser configurada nos Secrets (ver passo 4 acima).
- Se o nome de alguma coluna na planilha de Estoque mudar, o app não trava mais por completo para todo mundo — só desativa a parte de estoque com um aviso.
- IDs das planilhas e URL do webhook agora podem ser sobrescritos via Secrets (ver seção de segurança acima).

## Limitações conhecidas (não corrigidas nesta rodada, por serem mudanças maiores)

- **Uso simultâneo**: se duas pessoas derem baixa em itens de estoque quase ao mesmo tempo, existe uma janela pequena em que ambas podem "ver" o mesmo item como disponível antes da planilha atualizar. Para o volume de uma célula operacional isso tende a ser raro, mas é bom saber.
- **Sem identificação de quem fez a baixa**: como todo mundo usa a mesma senha, não dá para saber pelo próprio app qual pessoa da equipe executou cada baixa.
- **Lista de feriados**: hoje só tem 07/09/2026 cadastrado (`FERIADOS` no início da página de Automação). Precisa ser atualizada manualmente todo ano.
