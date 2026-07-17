# Semáforo de Status

Painel flutuante que mostra, para cada editor/agente monitorado, um mini
semáforo (🔴🟡🟢) com um mascote animado por cima. Todas as sessões ativas
aparecem lado a lado em um único painel — não é uma janela por sessão.

- 🟢 Verde = ocioso / aguardando comando
- 🟡 Amarelo (pulsando) = processando / escrevendo código
- 🔴 Vermelho = erro / intervenção humana necessária (toca `assets/alert.wav`
  via `paplay`/`pw-play` e dispara uma notificação de desktop ao entrar
  nesse estado — só na transição, não fica repetindo)

> **Beep/notificação só quando a sessão não está em primeiro plano.** Se a
> janela do terminal daquela sessão já é a janela ativa (X11), o alerta é
> silenciado — não faz sentido tocar som/notificar algo que você já está
> olhando. Isso é detectado gravando, junto do status, a cadeia de PIDs
> ancestrais do processo que reportou o evento (`foreground.py:ancestor_pids`)
> e comparando com o dono da janela em foco no momento do alerta
> (`foreground.py:active_window_pid`, via `xprop`). Funciona só em X11 —
> em Wayland, sem `xprop`, ou quando a sessão roda via SSH/remoto (sem
> relação PID↔janela local), a detecção retorna "não sei" e o comportamento
> cai para o alerta de sempre (nunca o contrário: incerteza nunca silencia).
> Com tmux/screen ou várias abas no mesmo terminal, a granularidade é por
> *janela*, não por aba — todas as sessões daquela janela contam como "em
> primeiro plano" juntas.

Cada sessão tem seu próprio mascote animado (estilo MS Agent — Clippy,
Merlin, Rocky, Rover, Links, F1, Genius, Bonzi, Genie ou Peedy) que reflete
o status atual (parado no idle, "processando" no working, "alerta" no
error), com som por quadro de animação quando o personagem tem. Quando a
sessão volta a ficar verde (ou entra em erro), o mascote mostra um balão de
fala com um preview (~150 caracteres) da última resposta em texto do Claude
— some quando o status muda de novo. Os assets do mascote
(`assets/mascot/<Personagem>/`) vêm do projeto
[clippyjs/clippy.js](https://github.com/clippyjs/clippy.js); o repositório
não declara uma licença clara (os sprites são propriedade original da
Microsoft, redistribuídos pela comunidade por nostalgia) — uso pensado
para local/pessoal, sem redistribuição.

Dá pra escolher o personagem, desligar o som do mascote, desligar o
mascote (voltando só às luzes) ou desligar o beep de alerta pelo menu da
bandeja → **Configurações...**. As preferências ficam salvas em
`~/.config/semaforo-status/config.yaml`.

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

Um ícone surge na bandeja do sistema assim que o programa abre. O painel só
aparece sozinho quando existe pelo menos uma sessão reportando status; sem
nenhuma sessão ativa ele fica escondido (dá pra abrir manualmente pelo ícone
da bandeja). Ele lembra a última posição em que você o arrastou.

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
| `Notification` | `permission_prompt\|idle_prompt\|agent_needs_input` | 🔴 error |
| `PermissionRequest` | `AskUserQuestion\|Bash\|ExitPlanMode` | 🔴 error |
| `PostToolUse` (a ferramenta terminou) | qualquer ferramenta | 🟡 working |
| `PostToolUseFailure` (a ferramenta falhou de verdade) | — | 🔴 error |
| `Stop` (terminou a resposta, esperando você) | — | 🟢 idle |
| `SessionEnd` | — | remove a coluna |

Nos eventos `Stop`, `Notification` e `PermissionRequest`, o hook também tenta
ler a última resposta em texto do Claude (via `transcript_path`, que o
próprio Claude Code manda no payload) e mandar pro balão de fala do mascote.
Isso é melhor esforço: o formato do transcript é interno/não documentado, e
se mudar em uma versão futura do Claude Code o hook simplesmente não acha
nada e o balão não aparece — nunca trava o hook.

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

O `main.py` já confere isso sozinho a cada início (se os hooks estiverem
desatualizados — por exemplo, depois de mover/renomear a pasta do projeto —
ele reinstala automaticamente e avisa por notificação do desktop). Rodar
`hooks/install.py` manualmente só é necessário na primeira vez em uma
máquina nova, ou se quiser forçar a atualização sem esperar o app abrir.

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
>
> `ExitPlanMode` (o pedido de aprovação do plano, no modo de planejamento)
> também entra no matcher — sem isso, o painel não acusava vermelho enquanto
> esperava você aprovar um plano, já que o nome dessa ferramenta não batia
> com `AskUserQuestion|Bash`.

> **Por que o matcher do `Notification` inclui `idle_prompt` e
> `agent_needs_input` além de `permission_prompt`.** O evento `Notification`
> tem um tipo interno (não exposto no payload JSON, só usado pelo próprio
> Claude Code pra decidir se o matcher bate) com valores como
> `permission_prompt`, `idle_prompt`, `auth_success`, `elicitation_dialog`,
> `agent_needs_input` e `agent_completed`. Só mapear `permission_prompt`
> deixa passar casos reais de "precisa de mim" que não são um pedido de
> permissão — por exemplo, uma ferramenta já pré-aprovada (como `WebSearch`
> na allowlist do projeto) pode disparar uma notificação de atenção sem
> nunca passar por `PermissionRequest`/`permission_prompt`. `idle_prompt` e
> `agent_needs_input` cobrem esses casos; `auth_success`/`agent_completed`
> ficam de fora porque não pedem ação (o segundo já é coberto pelo `Stop`
> → verde).

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
python3 status_writer.py <session_id> <idle|working|error> --label "Nome do editor" --message "Texto opcional do balão"
```

Exemplos:

```bash
# quando o agente começa a processar
python3 status_writer.py vscode-1 working --label "VSCode — projeto A"

# quando termina e volta a aguardar, com um preview no balão do mascote
python3 status_writer.py vscode-1 idle --label "VSCode — projeto A" --message "Terminei, pode conferir"

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
| `main.py` | ponto de entrada; também confere/corrige os hooks a cada início (veja abaixo) |
| `semaphore_panel.py` | janela única, arrastável, sem bordas, que organiza as colunas (balão + mascote + luzes) lado a lado |
| `mascot.py` | widget do personagem animado (sprites do clippy.js), agnóstico de qual personagem, sincronizado com o status |
| `speech_bubble.py` | balão de fala com preview da última resposta |
| `light_column.py` | desenha o mini semáforo (rótulo + 3 luzes) de uma sessão |
| `audio.py` | reprodução de som compartilhada (beep de alerta + sons do mascote) |
| `config.py` | preferências do usuário (personagem, toggles), lidas/salvas em YAML |
| `settings_dialog.py` | janela de configurações, aberta pelo menu da bandeja |
| `session_manager.py` | faz polling da pasta `sessions/`, sincroniza o painel e o ícone da bandeja |
| `status_store.py` | leitura/escrita atômica dos arquivos de status |
| `status_writer.py` | CLI para reportar status (usado por hooks/scripts externos) |
| `hooks/status_hook.py` | hook do Claude Code (chamado automaticamente via `~/.claude/settings.json`) |
| `hooks/install.py` | instala/atualiza os hooks em `~/.claude/settings.json` (chamado automaticamente pelo `main.py`, ou manualmente) |
| `autostart.py` | liga/desliga o painel abrindo sozinho no login |
| `simulate.py` | gera 3 sessões fictícias (com mensagens de exemplo) para demonstração |
| `generate_alert_sound.py` | gera `assets/alert.wav` (som do alerta vermelho) |
| `assets/mascot/<Personagem>/` | sprites + dados de animação + sons de cada personagem (origem: clippy.js) |
