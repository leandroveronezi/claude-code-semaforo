# Semáforo de Status

Painel flutuante que mostra, para cada editor/agente monitorado, um mini
semáforo (🔴🟡🟢) com um mascote animado por cima. Todas as sessões ativas
aparecem lado a lado em um único painel — não é uma janela por sessão.

- 🟢 **Verde** — ocioso / aguardando comando
- 🟡 **Amarelo** (pulsando) — processando / escrevendo código
- 🔴 **Vermelho** — erro / intervenção humana necessária. Toca um alerta
  sonoro e dispara uma notificação de desktop ao entrar nesse estado (só na
  transição, não fica repetindo) — e fica em silêncio se você já estiver com
  o olho na janela daquela sessão.

Cada sessão tem seu próprio mascote animado (estilo MS Agent — Clippy,
Merlin, Rocky, Rover, Links, F1, Genius, Bonzi, Genie ou Peedy), que reflete
o status atual e mostra um balão de fala com um preview da última resposta
do Claude quando a sessão termina ou entra em erro. Os assets do mascote
vêm do projeto [clippyjs/clippy.js](https://github.com/clippyjs/clippy.js);
uso pensado para local/pessoal, sem redistribuição (os sprites são
propriedade original da Microsoft, redistribuídos pela comunidade por
nostalgia, sem licença clara).

## Configurações

Pelo menu da bandeja → **Configurações...** dá pra ajustar:

- Personagem do mascote e o tamanho dele em tela
- Som do mascote, ligado/desligado
- Mostrar o mascote ou só as luzes
- Beep de alerta e notificação de desktop, cada um com seu próprio interruptor
- Tempo de revezamento entre sessões e de exibição das mensagens

As preferências ficam salvas em `~/.config/semaforo-status/config.yaml`.

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

- **Arrastar**: clique e segure em qualquer ponto do painel.
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
qualquer projeto) e refletem os eventos do Claude Code assim:

| Evento do Claude Code | Status refletido |
|---|---|
| Início de sessão | 🟢 idle |
| Comando enviado / ferramenta em uso | 🟡 working |
| Aguardando aprovação, permissão ou input | 🔴 error |
| Resposta concluída, aguardando você | 🟢 idle |
| Sessão encerrada | remove a coluna |

Nos momentos relevantes, o hook também tenta ler a última resposta em texto
do Claude e mandar pro balão de fala do mascote — melhor esforço, nunca
trava o hook se não conseguir.

Isso cobre apenas sessões do **Claude Code**. Outros agentes/IDEs não têm
essa integração pronta — veja a seção [Reportando o status de uma sessão
real](#reportando-o-status-de-uma-sessão-real) para plugar o seu.

### Instalando/reinstalando os hooks

Como `~/.claude/settings.json` fica fora deste projeto, ele **não** viaja
junto se você copiar a pasta pra outra máquina ou reclonar o repositório.
Para (re)instalar os hooks acima (idempotente — seguro rodar de novo a
qualquer momento):

```bash
python3 hooks/install.py
```

Isso mescla os hooks do Semáforo dentro do `settings.json` existente, sem
apagar outras configurações/hooks que já estejam lá. Se preferir editar
manualmente, use `/hooks` no Claude Code (ou reinicie a sessão) para
recarregar a configuração depois.

O `main.py` já confere isso sozinho a cada início — se os hooks estiverem
desatualizados (por exemplo, depois de mover/renomear a pasta do projeto),
ele reinstala automaticamente e avisa por notificação do desktop. Rodar
`hooks/install.py` manualmente só é necessário na primeira vez em uma
máquina nova, ou pra forçar a atualização sem esperar o app abrir.

### Sessões travadas ou abandonadas

Se uma sessão morre sem avisar (terminal fechado à força, processo morto,
etc.), o painel verifica periodicamente a idade da última atualização de
cada sessão:

- **Parada há mais de 10 minutos** em `working`/`error` → volta para `idle`
  automaticamente (provável sessão travada, não um alerta real).
- **Parada há mais de 4 horas**, qualquer status → a coluna é removida.

Sessões em `idle` não são afetadas — ficar ocioso por muito tempo é normal.

## Testar com dados simulados

Sem precisar plugar um agente de verdade, rode em outro terminal:

```bash
python3 simulate.py
```

Isso cria 3 sessões fictícias e alterna o status delas aleatoriamente a
cada poucos segundos — você verá 3 colunas aparecerem lado a lado no painel.

## Reportando o status de uma sessão real

Cada sessão monitorada é um arquivo `sessions/<id>.json`. O painel reage a
mudanças nessa pasta quase instantaneamente: criar o arquivo adiciona uma
coluna, atualizar o conteúdo muda a cor, apagar o arquivo remove a coluna.

Use o helper de linha de comando para escrever esse arquivo:

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

Para monitorar vários editores (ou abas) ao mesmo tempo, basta usar um
`session_id` diferente para cada um — cada `session_id` vira uma coluna
independente no mesmo painel.

Por padrão os arquivos ficam em `semaforo_status/sessions/`. Para usar outro
diretório (ex.: compartilhado entre várias instâncias), defina a variável de
ambiente `SEMAFORO_STATUS_DIR` antes de rodar tanto `main.py` quanto
`status_writer.py`.
