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

**Config** (`config.py`) é um dataclass único persistido como YAML em `~/.config/semaforo-status/config.yaml`, editável via menu de bandeja `SettingsDialog` (`settings_dialog.py`). `Config.load()` silenciosamente dropa chaves desconhecidas, então arquivos config antigos nunca crasham uma versão mais nova do app.

## Arquivos-Chave

- `status_store.py` — protocolo de sessão em disco (ler/escrever/remover), compartilhado pelo app e qualquer reporter externo
- `session_manager.py` — descoberta de sessão, ícone de bandeja, sweep de sessão stale, reancoragem em mudança de tela
- `mascot_overlay.py` — janela do mascote: layout, engine de rotação/fila, ancoragem multi-monitor
- `mascot.py` — engine de animação/frame derivado de clippy.js
- `hooks/status_hook.py` + `hooks/install.py` — toda a integração Claude Code
- `foreground.py` — detecção de janela foreground X11 para supressão de alerta
