# CLAUDE.md

Guia de orientação para trabalhar com código neste repositório.

## O Projeto

**Semáforo de Status** — painel flutuante PyQt6 (Linux) que mostra um mini semáforo (🔴🟡🟢) por sessão monitorada, mais um mascote animado único que reflete o estado agregado de todas as sessões. Integração pronta com Claude Code via hooks, então cada sessão do Claude vira uma coluna automaticamente.

**Convenção:** toda documentação e comentários visíveis ao usuário estão em pt-BR; siga essa convenção também nos comentários de código.

## Comandos

```bash
pip install -r requirements.txt        # PyQt6==6.6.1 / PyQt6-Qt6==6.6.3 pinned se wheels falharem
python3 main.py                        # rodar app (ícone de bandeja aparece imediatamente)
python3 simulate.py                    # 3 sessões fictícias alternando status, para teste
python3 status_writer.py <id> <idle|working|error> --label "..." --message "..."   # reportar sessão manualmente
python3 autostart.py {install|remove|status}   # entrada freedesktop.org autostart
python3 hooks/install.py               # (re)instalar hooks do Claude Code em ~/.claude/settings.json (idempotente)
```

Não há test suite, linter ou build step configurado neste projeto.

`SEMAFORO_STATUS_DIR` — variável de ambiente que override o diretório de sessões (padrão `sessions/` ao lado de `status_store.py`). Necessária se rodar múltiplas instâncias compartilhando estado.

## Arquitetura

**Sessões são arquivos, não conexões.** A superfície de integração inteira é `sessions/<session_id>.json`, escrito atomicamente via `status_store.write_status()` (temp-file + `os.replace`). `SessionManager` (`session_manager.py`) monitora esse diretório com `QFileSystemWatcher` (+ poll de 2s como fallback, pois atomic renames às vezes dropa a watch) e deriva tudo do que lê: status, label, message, activity, pid_chain, updated_at. Qualquer processo, em qualquer linguagem, pode dirigir o painel apenas escrevendo esse shape JSON; `status_writer.py` é a wrapper CLI de conveniência.

**Integração Claude Code é um hook script, não um plugin.** `hooks/status_hook.py` é invocado pelo Claude Code (configurado em `~/.claude/settings.json` ao nível de usuário, instalado/mesclado por `hooks/install.py`) em eventos do ciclo de vida (SessionStart, UserPromptSubmit, PreToolUse/PostToolUse, Notification, PermissionRequest, Stop, SessionEnd, etc. — veja `MANAGED_HOOKS` em `hooks/install.py`). Mapeia cada evento a um status (idle/working/error/remove), extrai melhor-esforço uma preview para o balão do mascote (da transcript em `Stop`, ou do payload de permissão/notificação pendente), e chama `write_status`/`remove_status`. Como `~/.claude/settings.json` fica fora deste repo, `main.py` confere `is_up_to_date()` a cada início e reinstala silenciosamente se os caminhos do hook ficarem velhos (ex.: pasta do projeto movida/renomeada) — é por isso que comandos de hook terminam em `|| true` e nunca bloqueiam o Claude Code mesmo se este app quebrar.

**Um painel, um mascote — não uma janela por sessão.** `SemaphorePanel` (`semaphore_panel.py`) é um widget flutuante único que layout uma `LightColumn` (`light_column.py`) por sessão lado a lado. `MascotOverlay` (`mascot_overlay.py`) é uma janela *separada* always-on-top que segura um `MascotWidget` (`mascot.py`) + `SpeechBubble` (`speech_bubble.py`) compartilhados; reflete o estado *agregado* de todas as sessões (prioridade error > working > idle, igual ao ícone da bandeja) e reveza entre múltiplas sessões do mesmo tier em timer, pausando ao passar o mouse. Transições idle são notificações enfileiradas one-shot (sessão terminando não fica loopando forever) que se intercalam em uma rotação error/working em andamento em vez de ficarem travadas atrás — veja `_combined_entries` / `IDLE_DONE_MARKER` em `mascot_overlay.py` para a mecânica exata antes de tocar lógica de rotação.

**Engine de animação do mascote é um port fiel de clippy.js.** O frame engine de `mascot.py` (`_step`, `_get_next_frame_index`, branching, `exitBranch`, `useExitBranching`) é um port direto de `clippy.js/src/animator.js`, não uma simplificação — preserva branching de animação probabilístico e frames compostos multi-imagem. `assets/mascot/<Name>/agent.json` é regenerado de `clippy.js/agents/<Name>/agent.js` via `scripts/import_mascot_agents.py` (curates `status_animations` por-character já que clippy.js não tem noção de idle/working/error); sons `.wav` são extraídos on-demand via `scripts/import_mascot_sounds.py` (precisa de `ffmpeg`). Não edite `agent.json` manualmente — corrija o importer e rerun. Assets do mascote são sprites originais Microsoft redistribuídos pela comunidade clippy.js sem licença clara — trate como uso pessoal/local apenas, não para redistribuição.

**Detecção de foreground é X11-only e falha aberto para "alert".** `foreground.py`'s `active_window_pid()` shell-outa para `xprop`; em Wayland ou sem `xprop` retorna `None`, e todo caller deve tratar como "unknown" (i.e. ainda alert) em vez de assumir foreground. Usado para suprimir beep/notificação de erro quando o usuário já está olhando para a sessão em questão — matched via `ancestor_pids()` (caminha `/proc/<pid>/stat`) registrado em `pid_chain` de cada sessão.

**Limpeza de sessão stale** vive em `SessionManager._check_stale`: sessões working/error intocadas por 10+ minutos revert para idle (provável processo morto, não alerta real); qualquer sessão intocada por 4+ horas é removida inteiramente. Sessões idle nunca são auto-removidas por idade apenas.

**Cota da conta (Session 5h / Weekly 7d) é raspada da tela, não de uma API.** Não existe hook, arquivo local nem API pública para os números que `/usage` mostra no CLI — é dado exclusivo daquela tela interativa (o próprio binário do `claude` busca isso de um endpoint OAuth interno não documentado). `account_usage.py` automatiza a tela em vez de reimplementar esse endpoint: abre um `claude` real num pty (`pty.fork`), digita `/usage` e usa `pyte` pra renderizar e ler o texto igual um humano veria. Dois efeitos colaterais são neutralizados deliberadamente: `SEMAFORO_SKIP_HOOK=1` no ambiente do processo filho (checado logo no início de `hooks/status_hook.py` e `hooks/statusline_hook.py`) pra essa sessão descartável não virar uma coluna fantasma no painel; e um `--session-id` fixo (`FIXED_SESSION_ID`) cujo `.jsonl` é apagado ao final, pra não acumular sessões vazias no `/resume`. `SessionManager` chama `fetch_account_usage()` (bloqueante, ~15s) numa `_AccountUsageThread` a cada 20min (`ACCOUNT_USAGE_POLL_MS`) e mostra o resultado no tooltip da bandeja. `_AccountUsageThread` **sobrescreve `QThread.run()` diretamente** em vez do padrão comum `moveToThread()` + `started`/`quit()` — esse padrão tem uma corrida real do Qt quando o trabalho conectado a `started()` é síncrono/direto: como `finished` é emitido cross-thread, o `quit()` conectado a ele fica enfileirado pra rodar na thread principal, e pode chegar antes do `exec()` da thread em background sequer ter começado — nesse caso `quit()` vira no-op, a thread fica presa num loop de eventos vazio pra sempre (`isRunning()` nunca volta a `False`), e quando o Python por fim coleta o `QThread` órfão, o destructor do Qt aborta o processo com "QThread: Destroyed while thread is still running". Isso não é teórico: reproduzido de forma 100% determinística (~1s depois de toda consulta bem-sucedida) antes da reescrita. Sobrescrever `run()` evita o problema inteiro (quando `run()` retorna, a thread já está oficialmente terminada). `_wait_for_account_usage_thread`, ligado a `aboutToQuit`, só dá `wait()` (sem `quit()`, que não faz sentido pra uma thread sem `exec()`) pra não deixar o app fechar com a thread ainda rodando. Consultas em sequência rápida parecem ser limitadas pelo servidor (o "% used" da sessão às vezes não carrega, o da semana sim) — por isso o parser em `_parse_usage_screen` trata os dois blocos como opcionais independentes em vez de exigir os dois.

O mesmo dado também aparece visualmente: `AccountUsageBadge` (`account_usage_widget.py`) é uma caixa deitada (duas barras, Sessão 5h / Semana 7d, com % e "reseta ...") desenhada com o mesmo padrão de `LightColumn`/`SpeechBubble` (QPainter direto, sem layout). Fica colada logo abaixo do mascote — `MascotOverlay._relayout()` (`mascot_overlay.py`) trata a janela inteira como "ancorada" em `self._anchor` (posição arrastada do mascote) e recalcula mascote+balão+caixa de cota ao redor dela a cada mudança, então arrastar/salvar posição e o mascote reaparecer depois (`set_visible_animated`) já vêm com o layout certo automaticamente — não existe estado de posição separado pra caixa. A caixa nunca colide com o balão de fala porque o balão só aparece acima ou ao lado do mascote (nunca abaixo); perto da borda inferior da tela a caixa é clampada pra não vazar da tela. Controlada por `Config.account_usage_badge_enabled` (aba Mascote das configurações) — desligar só esconde a caixa, não para as consultas de `fetch_account_usage()` (o tooltip da bandeja continua funcionando).

**Config** (`config.py`) é um dataclass único persistido como YAML em `~/.config/semaforo-status/config.yaml`, editável via menu de bandeja `SettingsDialog` (`settings_dialog.py`). `Config.load()` silenciosamente dropa chaves desconhecidas, então arquivos config antigos nunca crasham uma versão mais nova do app.

## Arquivos-Chave

- `status_store.py` — protocolo de sessão em disco (ler/escrever/remover), compartilhado pelo app e qualquer reporter externo
- `session_manager.py` — descoberta de sessão, ícone de bandeja, sweep de sessão stale, reancoragem em mudança de tela
- `mascot_overlay.py` — janela do mascote: layout, engine de rotação/fila, ancoragem multi-monitor
- `mascot.py` — engine de animação/frame derivado de clippy.js
- `hooks/status_hook.py` + `hooks/install.py` — toda a integração Claude Code
- `foreground.py` — detecção de janela foreground X11 para supressão de alerta
- `account_usage.py` — raspagem best-effort da cota de conta (Session 5h / Weekly 7d) via automação de pty do `/usage` do CLI
- `account_usage_widget.py` — caixa deitada com a cota da conta, exibida abaixo do mascote
