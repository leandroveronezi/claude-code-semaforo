# Semáforo de Status

Painel flutuante que monitora **uma ou múltiplas sessões** de editores/agentes em tempo real. Cada sessão aparece como uma coluna independente com seu mini semáforo (🔴🟡🟢), e um mascote animado único (estilo MS Agent — Clippy, Merlin, Rocky, Rover, etc.) que reflete o **estado agregado** de todas as sessões.

## Estados de Status

- 🟢 **Verde** — ocioso / aguardando comando
- 🟡 **Amarelo** (pulsando) — processando / escrevendo código  
- 🔴 **Vermelho** — erro / intervenção humana necessária
  - Toca um alerta sonoro e dispara notificação de desktop (apenas na transição)
  - Fica em silêncio se você já estiver vendo aquela sessão (detecção de janela ativa via X11)

## O Mascote

Um mascote animado único que representa o **estado geral** do painel. Escolha entre:
Clippy, Merlin, Rocky, Rover, Links, F1, Genius, Bonzi, Genie ou Peedy. 

Mostra um balão de fala com preview da última resposta quando uma sessão termina ou entra em erro. Assets originais do projeto [clippy.js](https://github.com/clippyjs/clippy.js) (sprites Microsoft, uso pessoal/local apenas, sem redistribuição).

## Configurações

Acesse pelo ícone da bandeja do sistema → **Configurações...**

| Opção | Efeito |
|-------|--------|
| **Personagem** | Escolha qual mascote animar (Clippy, Merlin, etc.) |
| **Tamanho** | Ajuste a escala do mascote em pixels |
| **Som** | Ativar/desativar sons de movimento e alerta |
| **Mostrar mascote** | Alternar entre painel completo (mascote + luzes) ou apenas as luzes |
| **Beep de alerta** | Ativar/desativar som quando uma sessão entra em erro |
| **Notificação de desktop** | Ativar/desativar pop-up de notificação |
| **Tempo de revezamento** | Velocidade de rotação entre múltiplas sessões (ms) |
| **Tempo de mensagem** | Quanto tempo a fala do mascote fica visível (ms) |

Preferências salvas em `~/.config/semaforo-status/config.yaml`.

## Instalação

**Requisitos:** Python 3.9+ e dependências de compilação do PyQt6 (em sistemas sem wheels pré-compiladas).

```bash
pip install -r requirements.txt
```

Se o pip tentar compilar e falhar com erro `qmake`, force as versões testadas:

```bash
pip install --user "PyQt6==6.6.1" "PyQt6-Qt6==6.6.3"
```

> **Dica:** Em algumas distribuições Linux, você pode precisar instalar `python3-dev` e `libgl1-mesa-dev` antes.

## Executando

```bash
python3 main.py
```

### Comportamento

- Um ícone de bandeja aparece imediatamente
- O painel flutua apenas quando há **pelo menos uma sessão ativa** (sem sessões, fica oculto)
- A posição do painel é lembrada entre execuções

### Controles

| Ação | Como fazer |
|------|-----------|
| **Mover painel** | Arrastar a barra de título (clique e segure) |
| **Mostrar/ocultar** | Clique no ícone da bandeja ou botão direito no painel |
| **Abrir menu** | Botão direito no ícone da bandeja |
| **Sair** | Menu da bandeja → "Sair" |

## Abrir Automaticamente no Login

Usa o mecanismo padrão do freedesktop.org (compatível com KDE, GNOME, XFCE, etc. — sem systemd):

```bash
python3 autostart.py install   # ativar — abre sozinho no próximo login
python3 autostart.py remove    # desativar
python3 autostart.py status    # verificar estado atual
```

Cria um arquivo `.desktop` em `~/.config/autostart/` que funciona em qualquer desktop Linux.

## Integração com Claude Code (Automática)

Já vem pronta a integração com Claude Code via hooks. Cada sessão do Claude Code (em qualquer projeto) **vira uma coluna automaticamente**, sem configuração manual.

### Como funciona

Os hooks são registrados em `~/.claude/settings.json` (nível usuário) e refletem os eventos do Claude Code:

| Evento | Status |
|--------|--------|
| Sessão iniciada | 🟢 idle |
| Comando enviado / ferramenta em uso | 🟡 working |
| Aguardando aprovação ou permissão | 🔴 error |
| Resposta completa | 🟢 idle |
| Sessão encerrada | remove coluna |

O hook também extrai um preview da última resposta do Claude para o balão de fala do mascote (melhor esforço — nunca trava se não conseguir).

**Nota:** Isso cobre apenas Claude Code. Para integrar outros editores/agentes, veja [Reportando Status Manual](#reportando-status-manual).

### Instalação dos Hooks

Na **primeira execução** em uma máquina nova, instale os hooks:

```bash
python3 hooks/install.py
```

Isso mescla os hooks do Semáforo em `~/.claude/settings.json` **sem apagar** outras configurações/hooks já existentes.

#### Comportamento automático

- `main.py` verifica os hooks a cada início
- Se detectar que o projeto foi movido/renomeado, reinstala automaticamente
- Notifica por desktop quando faz isso
- Você **não precisa** rodar `hooks/install.py` manualmente novamente

#### Recarregar hooks manualmente

Se editar `settings.json` diretamente, use `/hooks` no Claude Code (ou reinicie a sessão).

### Limpeza Automática de Sessões Travadas

O painel verifica periodicamente a idade da última atualização:

| Tempo sem atualização | Ação |
|---|---|
| 10+ minutos em `working` ou `error` | Revert para `idle` (provável travamento) |
| 4+ horas, qualquer status | Remove a coluna |

**Sessões em `idle` nunca são removidas por idade** — é normal ficar ocioso.

## Testar com Dados Simulados

Sem precisar de um agente real, abra outro terminal e execute:

```bash
python3 simulate.py
```

Cria 3 sessões fictícias que alternam entre os estados (idle/working/error) a cada poucos segundos — útil para testar a animação do mascote e o comportamento do painel antes de integrar com o Claude Code.

## Reportando Status Manual

Para integrar editores/agentes **personalizados**, reporte o status via CLI. O protocolo é simples: cada sessão é um arquivo JSON em `sessions/<session_id>.json` que o painel monitora em tempo real.

### Usando o comando `status_writer.py`

```bash
python3 status_writer.py <id> <idle|working|error> --label "Nome" [--message "Texto do balão"]
```

### Exemplos

```bash
# Quando uma tarefa inicia
python3 status_writer.py vscode-1 working --label "VSCode — Projeto A"

# Quando termina (com preview no balão)
python3 status_writer.py vscode-1 idle --label "VSCode — Projeto A" --message "✓ Código gerado"

# Quando há erro
python3 status_writer.py vscode-1 error --label "VSCode — Projeto A" --message "⚠ Permissão recusada"
```

### Múltiplas sessões

Use um `session_id` diferente para cada editor/aba — cada um vira uma coluna independente:

```bash
python3 status_writer.py neovim-1 working --label "Neovim — config"
python3 status_writer.py vscode-1 idle --label "VSCode — main"
# Painel mostra 2 colunas lado a lado
```

### Diretório customizado

Para usar outro local (ex.: compartilhado entre múltiplas instâncias do app):

```bash
export SEMAFORO_STATUS_DIR=/tmp/semaforo-sessions
python3 main.py &
python3 status_writer.py my-session working --label "Custom Editor"
```
