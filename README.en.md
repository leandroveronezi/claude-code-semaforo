*[Português](README.md) | English*

# Status Semaphore

A floating panel for Linux that monitors editor and AI agent sessions in real time. Each session becomes a column with a mini traffic light (🔴🟡🟢), and a single animated mascot summarizes the overall state of everything running.

Ready-made integration with **Claude Code**: install the hook once and every session turns into a column automatically, no per-project setup needed.

<p align="center">
  <img src="assets/screenshots/painel.png" alt="Traffic-light panel, with a per-session token usage bar" height="260">
  &nbsp;&nbsp;
  <img src="assets/screenshots/mascote-cota.png" alt="Mascot with speech bubble and account quota (5h Session / 7d Week)" height="260">
</p>

## States

| | Status | Meaning |
|---|--------|-------------|
| 🟢 | **Green** | Idle — waiting for a command |
| 🟡 | **Yellow** (pulsing) | Processing / writing code |
| 🔴 | **Red** | Error or human intervention required |

Red plays an alert sound and fires a desktop notification on the transition — but stays silent if you're already looking at that window (detected via X11).

## Installation

Requires Python 3.9+.

```bash
pip install -r requirements.txt
python3 main.py
```

If pip tries to compile PyQt6 and fails (`qmake` error), pin the tested versions:

```bash
pip install --user "PyQt6==6.6.1" "PyQt6-Qt6==6.6.3"
```

> On some distros, install `python3-dev` and `libgl1-mesa-dev` first.

A tray icon appears as soon as the app starts. The panel only floats on screen while there's at least one active session, and its position is remembered across runs — drag the title bar to move it.

To launch automatically at login (freedesktop.org, works on KDE/GNOME/XFCE):

```bash
python3 autostart.py install
```

## Claude Code Integration

```bash
python3 hooks/install.py
```

Merges the Semaphore hooks into `~/.claude/settings.json` without wiping existing settings. From then on, every Claude Code session (in any project) automatically becomes a column, reflecting the session's real lifecycle:

| Claude Code event | Status |
|---|---|
| Session started / response finished | 🟢 idle |
| Prompt sent / tool in use | 🟡 working |
| Waiting for approval or permission | 🔴 error |
| Session ended | column removed |

The mascot's speech bubble shows a preview of the last response when a session finishes or errors out. If the project folder is moved or renamed, `main.py` detects it and reinstalls the hooks on its own at the next start — no need to run `hooks/install.py` manually again.

## The Mascot

A single animated mascot (MS Agent style) represents the aggregate state of all sessions, with priority error > working > idle. Pick the character in **Settings → Mascot**:

<p align="center">
  <img src="assets/screenshots/mascotes.png" alt="Clippy, Merlin, Rocky, Rover, Links, F1, Genius, Bonzi, Genie and Peedy" width="720">
</p>

Clippy, Merlin, Rocky, Rover, Links, F1, Genius, Bonzi, Genie and Peedy. Original assets from the [clippy.js](https://github.com/clippyjs/clippy.js) project (Microsoft sprites redistributed by the community with no clear license — personal/local use only).

## Settings

Open it from the tray icon → **Settings...** (persisted at `~/.config/semaforo-status/config.yaml`).

| Option | Effect |
|-------|--------|
| Character | Which mascot to animate |
| Size | Mascot scale in pixels |
| Sound | Movement and alert sounds |
| Show mascot | Full panel (mascot + lights) or lights only |
| Beep / desktop notification | Alerts when a session enters error |
| Rotation time | Speed of rotation between sessions |
| Message time | How long the speech bubble stays visible |

`working`/`error` sessions with no update for 10+ minutes revert to `idle` (likely a stuck process); any session untouched for 4+ hours is removed. `idle` sessions are never removed just for being old.

## Integrating other editors/agents

The protocol is one JSON file per session at `sessions/<session_id>.json`, watched in real time. Report status via the CLI:

```bash
python3 status_writer.py <id> <idle|working|error> --label "Name" [--message "Bubble text"]
```

```bash
python3 status_writer.py vscode-1 working --label "VSCode — Project A"
python3 status_writer.py vscode-1 idle    --label "VSCode — Project A" --message "✓ Code generated"
python3 status_writer.py vscode-1 error   --label "VSCode — Project A" --message "⚠ Permission denied"
```

Each distinct `session_id` becomes an independent column. To share state across multiple instances of the app, point them all at the same directory:

```bash
export SEMAFORO_STATUS_DIR=/tmp/semaforo-sessions
```

### Testing without a real agent

```bash
python3 simulate.py
```

Creates 3 fake sessions cycling through idle/working/error — handy for seeing the panel and mascot in action before wiring up a real integration.
