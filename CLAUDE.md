# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Semáforo de Status" — a floating PyQt6 desktop panel (Linux) that shows a mini traffic light per monitored editor/agent session (🔴🟡🟢), plus a single shared animated mascot (MS Agent style — Clippy, Merlin, Rover, etc.) that reflects the aggregate mood across all sessions. It ships with ready-made Claude Code hook integration so every Claude Code session anywhere becomes a column automatically. All user-facing docs/comments are in pt-BR; follow that convention in this repo.

## Commands

```bash
pip install -r requirements.txt        # PyQt6==6.6.1 / PyQt6-Qt6==6.6.3 pinned if wheels fail to build
python3 main.py                        # run the app (tray icon appears immediately)
python3 simulate.py                    # 3 fake sessions cycling status, for testing without a real agent
python3 status_writer.py <session_id> <idle|working|error> --label "..." --message "..."   # report a session manually
python3 autostart.py {install|remove|status}   # freedesktop.org autostart entry
python3 hooks/install.py               # (re)install Claude Code hooks into ~/.claude/settings.json (idempotent)
```

There is no test suite, linter, or build step configured in this repo.

`SEMAFORO_STATUS_DIR` env var overrides the sessions directory (default `sessions/` next to `status_store.py`) for both `main.py` and `status_writer.py` — needed if you run multiple instances sharing state.

## Architecture

**Sessions are files, not connections.** The entire integration surface is `sessions/<session_id>.json`, written atomically (`status_store.write_status`, via temp-file + `os.replace`). `SessionManager` (`session_manager.py`) watches that directory with `QFileSystemWatcher` (plus a 2s fallback poll, since atomic renames sometimes drop the underlying watch) and derives everything else from what it reads — status, label, message, activity, pid_chain, updated_at. Any process, in any language, can drive the panel just by writing that JSON shape; `status_writer.py` is the CLI convenience wrapper around it.

**Claude Code integration is a hook script, not a plugin.** `hooks/status_hook.py` is invoked by Claude Code itself (configured in the user-level `~/.claude/settings.json`, installed/merged by `hooks/install.py`) on lifecycle events (SessionStart, UserPromptSubmit, PreToolUse/PostToolUse, Notification, PermissionRequest, Stop, SessionEnd, etc. — see `MANAGED_HOOKS` in `hooks/install.py`). It maps each event to a status (idle/working/error/remove), best-effort extracts a preview message for the mascot's speech bubble (from the transcript on `Stop`, or from the pending permission/notification payload), and calls `write_status`/`remove_status`. Because `~/.claude/settings.json` lives outside this repo, `main.py` checks `is_up_to_date()` on every launch and silently reinstalls if the hook paths are stale (e.g. project folder moved/renamed) — this is why hook commands end in `|| true` and never block Claude Code even if this app is broken or absent.

**One panel, one mascot — not one window per session.** `SemaphorePanel` (`semaphore_panel.py`) is a single floating widget that lays out a `LightColumn` (`light_column.py`) per session side by side. `MascotOverlay` (`mascot_overlay.py`) is a *separate* always-on-top window holding one shared `MascotWidget` (`mascot.py`) + `SpeechBubble` (`speech_bubble.py`); it reflects the *aggregate* mood of all sessions (error > working > idle priority, same as the tray icon) and rotates between multiple same-tier sessions on a timer, pausing on hover. Idle transitions are one-shot queued notifications (a session finishing doesn't loop forever) that get interleaved into an ongoing error/working rotation rather than stalled behind it — see `_combined_entries` / `IDLE_DONE_MARKER` in `mascot_overlay.py` for the exact mechanics before touching rotation logic.

**Mascot animation engine is a faithful port of clippy.js.** `mascot.py`'s frame engine (`_step`, `_get_next_frame_index`, branching, `exitBranch`, `useExitBranching`) is a direct port of `clippy.js/src/animator.js`, not a simplification — it preserves probabilistic animation branching and multi-image composited frames. `assets/mascot/<Name>/agent.json` is regenerated from `clippy.js/agents/<Name>/agent.js` via `scripts/import_mascot_agents.py` (curates `status_animations` per-character since clippy.js has no notion of idle/working/error); `.wav` sounds are extracted on demand via `scripts/import_mascot_sounds.py` (needs `ffmpeg`). Don't hand-edit `agent.json` — fix the importer and rerun it. Mascot assets are original Microsoft sprites redistributed by the clippy.js community with no clear license — treat as personal/local use only, not for redistribution.

**Foreground detection is X11-only and fails open to "alert".** `foreground.py`'s `active_window_pid()` shells out to `xprop`; on Wayland or without `xprop` it returns `None`, and every caller must treat that as "unknown" (i.e. still alert) rather than assuming foreground. This is used to suppress the error beep/notification when the user is already looking at the session in question — matched via `ancestor_pids()` (walks `/proc/<pid>/stat`) recorded in each session's `pid_chain`.

**Stale session handling** lives in `SessionManager._check_stale`: working/error sessions untouched for 10 minutes revert to idle (likely a killed process, not a real alert); any session untouched for 4 hours is removed entirely. Idle sessions are never auto-removed for age alone.

**Config** (`config.py`) is a single dataclass persisted as YAML at `~/.config/semaforo-status/config.yaml`, editable via the tray menu's `SettingsDialog` (`settings_dialog.py`). `Config.load()` silently drops unknown keys, so old config files never crash a newer version of the app.

## Key files

- `status_store.py` — the on-disk session protocol (read/write/remove), shared by the app and any external reporter
- `session_manager.py` — session discovery, tray icon, stale-session sweep, screen-change reanchoring
- `mascot_overlay.py` — mascot window: layout, rotation/queue engine, multi-monitor anchoring
- `mascot.py` — clippy.js-derived animation/frame engine
- `hooks/status_hook.py` + `hooks/install.py` — the entire Claude Code integration
- `foreground.py` — X11 foreground-window detection for alert suppression
