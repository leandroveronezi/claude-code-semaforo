# Semáforo de Status

Painel flutuante que mostra, para cada editor/agente monitorado, um mini
semáforo (🔴🟡🟢). Todas as sessões ativas aparecem lado a lado em um único
painel — não é uma janela por sessão.

- 🟢 Verde = ocioso / aguardando comando
- 🟡 Amarelo (pulsando) = processando / escrevendo código
- 🔴 Vermelho = erro / intervenção humana necessária (toca `assets/alert.wav`
  via `paplay`/`pw-play` e dispara uma notificação de desktop ao entrar
  nesse estado — só na transição, não fica repetindo)

> Usamos `paplay`/`pw-play` (tocam pelo servidor de áudio de verdade) em vez
> do beep nativo do Qt (`QApplication.beep()`), porque esse último usa o
> "system bell" do X11 — que em muitos ambientes, incluindo KDE Plasma, não
> tem áudio de verdade roteado por padrão e fica silencioso mesmo com o bell
> "ativado". Se nenhum dos dois players estiver disponível, cai de volta
> pro beep do Qt. Tocamos a 150% do volume (`ALERT_VOLUME_ARGS` em
> `session_manager.py`) pra garantir que se destaque; ajuste esse valor se
> quiser mais ou menos alto.
>
> O som em si (`assets/alert.wav`) é um arpejo curto de 3 notas com timbre
> de sino, sintetizado por `generate_alert_sound.py` (só stdlib, sem
> dependências) em vez de usar um som pronto do tema do sistema. Para
> ajustar as notas/duração/decaimento, edite as constantes no topo do script
> e rode `python3 generate_alert_sound.py` de novo — o `.wav` gerado é
> commitável, não precisa regenerar em cada máquina.

## Instalação

Requer Python 3.9+.

```bash
cd semaforo_status
pip install -r requirements.txt
```

Se o `pip install` tentar compilar do zero e falhar (erro de `qmake`),
geralmente é porque o pip escolheu uma versão do PyQt6 sem wheel pré-compilada
para o seu sistema. Force as versões já testadas:

```bash
pip install --user "PyQt6==6.6.1" "PyQt6-Qt6==6.6.3"
```

## Como rodar

```bash
python3 main.py
```

O painel aparece no canto da tela (ou na última posição em que você o
arrastou) e um ícone surge na bandeja do sistema. Enquanto não houver nenhuma
sessão reportando status, ele mostra "Sem sessões monitoradas".

- **Arrastar**: clique e segure em qualquer ponto do painel (fora dos
  círculos não é necessário, os cliques atravessam para o fundo).
- **Ocultar/Mostrar**: clique com o botão direito no painel, clique no ícone
  da bandeja, ou use o menu da bandeja (botão direito no ícone).
- **Sair**: menu da bandeja → "Sair".

## Abrir automaticamente no login

Usa o mecanismo padrão do freedesktop.org (arquivo `.desktop` em
`~/.config/autostart/`), funciona em qualquer desktop Linux (KDE, GNOME,
XFCE...) sem precisar de systemd:

```bash
python3 autostart.py install   # liga: abre sozinho a partir do próximo login
python3 autostart.py remove    # desliga
python3 autostart.py status    # mostra o estado atual
```

## Monitorando o Claude Code automaticamente

Já vem pronta a integração automática com o Claude Code via hooks: cada
janela/sessão do Claude Code (em qualquer projeto, qualquer editor) vira uma
coluna no painel sozinha, sem precisar rodar nada manualmente.

Os hooks ficam em `~/.claude/settings.json` (nível usuário, valem para
qualquer projeto) e chamam `hooks/status_hook.py`:

| Evento do Claude Code | Matcher | Status refletido |
|---|---|---|
| `SessionStart` | — | 🟢 idle |
| `UserPromptSubmit` | — | 🟡 working |
| `PreToolUse` | qualquer ferramenta | 🟡 working |
| `Notification` | `permission_prompt` | 🔴 error |
| `PermissionRequest` | `AskUserQuestion\|Bash` | 🔴 error |
| `PostToolUse` (a ferramenta terminou) | qualquer ferramenta | 🟡 working |
| `PostToolUseFailure` (a ferramenta falhou de verdade) | — | 🔴 error |
| `Stop` (terminou a resposta, esperando você) | — | 🟢 idle |
| `SessionEnd` | — | remove a coluna |

### Instalando/reinstalando os hooks

Como `~/.claude/settings.json` fica fora deste projeto, ele **não** viaja
junto se você copiar a pasta pra outra máquina ou reclonar o repositório.
Para (re)instalar os hooks acima (idempotente — seguro rodar de novo a
qualquer momento, inclusive para atualizar depois de mudanças no projeto):

```bash
python3 hooks/install.py
```

Isso mescla os hooks do Semáforo dentro do `settings.json` existente
(identificados pelo caminho de `status_hook.py`), sem apagar outras
configurações/hooks que já estejam lá. Se preferir editar manualmente, use
`/hooks` no Claude Code (ou reinicie a sessão) para recarregar a
configuração depois.

> **Por que `PermissionRequest` inclui `Bash` apesar do custo.**
> Neste ambiente, `PermissionRequest` dispara em praticamente todo comando
> Bash — mesmo os "aprovados automaticamente", sem ninguém realmente
> esperando. Isso por si só deixaria o painel vermelho o tempo todo, já que
> nada revertia o status depois. A correção foi adicionar `PostToolUse`
> (dispara quando a ferramenta termina, com qualquer resultado) → `working`:
> agora cada vermelho se autocorrige assim que aquele comando específico
> conclui, em vez de ficar preso até a *próxima* ferramenta rodar. Na
> prática isso ainda significa um flash vermelho de alguns segundos em
> praticamente todo comando Bash (medimos ~10s neste ambiente) — mais
> frequente do que o "vermelho raro e chamativo" do design original, mas foi
> a preferência explícita ao testar as duas opções. Se achar barulhento
> demais, remova `|Bash` do matcher do `PermissionRequest` pra voltar a só
> `AskUserQuestion` (silencioso, mas não cobre pedidos de permissão de
> outras ferramentas). `Elicitation`/`ElicitationResult` não se aplicam
> aqui — são específicos de servidores MCP pedindo input, não do
> `AskUserQuestion` nativo do Claude Code.

Isso cobre apenas sessões do **Claude Code**. Outros agentes/IDEs (Antigravity
IDE, etc.) não têm essa integração — eles precisariam do próprio mecanismo de
hooks/logs para reportar status da mesma forma (veja a seção abaixo para
reportar manualmente ou via script).

### Sessões travadas ou abandonadas (TTL)

Se uma sessão morre sem disparar `SessionEnd` (terminal fechado à força, processo
morto, etc.), o arquivo de status fica parado no último valor para sempre. Para
evitar uma coluna vermelha "fantasma" (ou qualquer outra travada), o painel
verifica periodicamente (a cada 30s) a idade da última atualização de cada
sessão:

- **Parada há mais de 10 minutos** e em `working`/`error` → volta para `idle`
  automaticamente (provável sessão travada, não uma alerta real).
- **Parada há mais de 4 horas**, qualquer status → a coluna é removida e o
  arquivo é apagado (sessão claramente abandonada).

Sessões em `idle` não são afetadas pelo primeiro caso — ficar ocioso por muito
tempo é normal e não deve gerar nenhuma mudança.

## Testar com dados simulados

Sem precisar plugar um agente de verdade, rode em outro terminal:

```bash
python3 simulate.py
```

Isso cria 3 sessões fictícias (`editor-1`, `editor-2`, `editor-3`) e alterna
o status delas aleatoriamente a cada poucos segundos — você verá 3 colunas
aparecerem lado a lado no painel.

## Reportando o status de uma sessão real

Cada sessão monitorada é um arquivo `sessions/<id>.json`. O painel reage a
mudanças nessa pasta quase instantaneamente (via `QFileSystemWatcher`, com um
polling de 2s só como rede de segurança): criar o arquivo adiciona uma
coluna, atualizar o conteúdo muda a cor, apagar o arquivo remove a coluna.

Use o helper de linha de comando para escrever esse arquivo (ele grava de
forma atômica, então é seguro chamar de hooks/scripts concorrentes):

```bash
python3 status_writer.py <session_id> <idle|working|error> --label "Nome do editor"
```

Exemplos:

```bash
# quando o agente começa a processar
python3 status_writer.py vscode-1 working --label "VSCode — projeto A"

# quando termina e volta a aguardar
python3 status_writer.py vscode-1 idle --label "VSCode — projeto A"

# quando algo dá errado e precisa de intervenção humana
python3 status_writer.py vscode-1 error --label "VSCode — projeto A"
```

Para monitorar 3 editores (ou 3 abas) ao mesmo tempo, basta usar um
`session_id` diferente para cada um — cada `session_id` vira uma coluna
independente no mesmo painel.

Por padrão os arquivos ficam em `semaforo_status/sessions/`. Para usar outro
diretório (ex.: compartilhado entre várias instâncias), defina a variável de
ambiente `SEMAFORO_STATUS_DIR` antes de rodar tanto `main.py` quanto
`status_writer.py`.

## Estrutura do projeto

| Arquivo | Função |
|---|---|
| `main.py` | ponto de entrada |
| `semaphore_panel.py` | janela única, arrastável, sem bordas, que organiza as colunas lado a lado |
| `light_column.py` | desenha o mini semáforo (rótulo + 3 luzes) de uma sessão |
| `session_manager.py` | faz polling da pasta `sessions/`, sincroniza o painel e o ícone da bandeja |
| `status_store.py` | leitura/escrita atômica dos arquivos de status |
| `status_writer.py` | CLI para reportar status (usado por hooks/scripts externos) |
| `hooks/status_hook.py` | hook do Claude Code (chamado automaticamente via `~/.claude/settings.json`) |
| `hooks/install.py` | instala/atualiza os hooks em `~/.claude/settings.json` (rode em cada máquina nova) |
| `autostart.py` | liga/desliga o painel abrindo sozinho no login |
| `simulate.py` | gera 3 sessões fictícias para demonstração |
| `generate_alert_sound.py` | gera `assets/alert.wav` (som do alerta vermelho) |
