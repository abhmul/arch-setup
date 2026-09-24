# Desktop checkpoints

`i3-session` records the i3 desktop and restores the previous graphical login's delayed checkpoint. Its default delay is five minutes, allowing you to close applications one by one before shutdown. Restore selects one historical desktop; it does not reopen the union of everything seen recently.

## Installation and everyday use

On an existing workstation, run:

```sh
~/arch-setup/.scripts/install-i3-session --configure-vscode
~/.local/bin/i3-session start
i3-msg reload
```

The installer requires `uv`, `i3-msg`, and `xprop`. It creates a dedicated Python environment under `${XDG_DATA_HOME:-~/.local/share}/i3-session/venv`, installs pinned dependencies, and adds configuration and command symlinks without replacing unrelated existing paths. It does not run the workstation bootstrap. Python 3.10 or newer is required; when available, installation uses the shared agent Python interpreter as its base. Runtime dependencies remain separate from the agent environment.

The i3 configuration starts the recorder at graphical login. **Super+Ctrl+Shift+R** restores the previous login's checkpoint and reports the result by desktop notification. To use a terminal instead:

```sh
i3-session status
i3-session restore --dry-run
i3-session restore
```

`~/.local/bin` must be in the shell's `PATH` for the short command. The existing login profile sets this; `~/.local/bin/i3-session` also works directly. Commands require the graphical login's `DISPLAY` and `XDG_SESSION_ID`.

Restore targets must be empty. Launch the command from a workspace outside the saved set, or use the keybinding before opening applications. Existing windows are not closed or moved. If a target is occupied, restoration refuses to proceed. Failed launches leave already restored applications open, remove only the tool's unused placeholders, and preserve the saved snapshot. Inspect `status` before retrying; clear the target workspaces yourself, then use `restore --retry`. Repeating a successful restore in the same login does nothing.

## Configuration

The tracked defaults live in `.config/i3-session/config.json`, linked to `~/.config/i3-session`. All operational settings are named parameters:

| Setting | Default | Meaning |
|---|---:|---|
| `restore_delay_seconds` | 300 | How far before the previous session's final observation to select a checkpoint |
| `capture_interval_seconds` | 15 | Time between completed captures |
| `history_seconds` | 1800 | Retained current-session history; at least the configured delay is retained |
| `restore_timeout_seconds` | 30 | Maximum wait for each new application window |
| `restore_poll_seconds` | 0.1 | Window discovery interval during restore |
| `restore_settle_seconds` | 0.3 | How long a unique matching window must remain identifiable |
| `browser_settle_seconds` | 1 | How long the set of newly opened browser windows must remain stable |
| `startup_timeout_seconds` | 5 | Wait for the recorder's first capture or graceful stop |
| `connection_failure_limit` | 3 | Consecutive capture failures before recording stops |
| `log_max_bytes`, `log_backups` | 1048576, 2 | Bounded recorder logs |

Use a separate JSON override for machine-local paths or application rules, and pass it through `--config /absolute/path/config.json`. The shipped defaults are merged with the override. A custom recorder invocation must also be reflected in the i3 autostart line if it should survive login. Override the delay or interval for a run with:

```sh
i3-session stop
i3-session --delay 10m --interval 20s start
```

Global options precede the subcommand. Duration suffixes `s`, `m`, and `h` are supported. `--state-dir /path` overrides the persistent state directory for every operation. The `status` output reports the running recorder's actual delay and interval, which may differ from newly edited settings until it is restarted.

`exclude_workspaces` and `exclude_classes` contain exact names. `workspace_map` and `output_map` map saved names to destination names. If a saved monitor is absent, restoration uses an available output and reports a warning. Scratchpad and transient dialog windows are excluded.

## Applications

- Firefox and Chromium-family browsers retain identifiable profile selectors. Chromium also retains an explicit valid remote debugging port and loopback debugging address, including those used by `chatgpt-send browser-start`; these are captured from the running browser, with no fixed profile paths or ports. Malformed, conflicting, or non-loopback debugging settings produce a warning and are omitted. A cold launch lets the browser perform its normal startup; any windows it reopens are used for the saved slots before additional blank windows are requested. The wrapper does not capture or reproduce tabs or navigation history. Windows are placed using their new window IDs, independent of their titles. If native startup opens more matching windows than there are saved slots, restoration stops and leaves those new windows open for review.
- Kitty reopens a shell in the captured working directory. A matching shell's `WINDOWID` distinguishes separate OS windows. Internal tabs/splits, shell variables, scrollback, and running foreground jobs are not recreated. Codex and Claude conversations are not automatically resumed: their terminals reopen as shells, without replaying commands. Ambiguous directories generate a warning and use the terminal process's directory.
- VS Code reopens local folders or saved `.code-workspace` files. The optional installer setting appends ` [i3-session:${rootPath}] [i3-session-remote:${remoteName}]` to the existing `window.title` template. It preserves other settings, comments, and any custom title prefix, and backs up the original settings under the state directory's `install/` subdirectory before editing. These markers appear in window titles; workspace-level title overrides can hide them. Remote, untitled, missing, or unidentified folders reopen as empty windows with a warning. Editor tabs and unsaved state are left to VS Code.
- Obsidian uses an unambiguous registered vault name to reopen that vault. Note content is not read.
- Other applications require an explicit launch rule. Unknown applications remain visible in snapshot warnings and are skipped during restore.

An application rule has an exact `class`, a literal argv array, and optionally an absolute `cwd`:

```json
{
  "applications": [
    {"class": "ExampleEditor", "command": ["example-editor", "--new-window"], "cwd": "/home/your-user/project"}
  ]
}
```

Arguments are passed directly to the application without a shell. Rules do not interpolate titles or run saved foreground commands. They must open a new window matching the captured class and instance; singleton applications or apps that restore several windows at once may need a custom rule. Let restoration finish before opening other windows: several matching new windows cause it to stop, but one unrelated matching window cannot reliably be distinguished from a window opened by the launch command.

## Checkpoints and recovery

Snapshots and logs live under `${XDG_STATE_HOME:-~/.local/state}/i3-session/`, outside Git. Files are private, written atomically, and snapshots are published only after a complete capture. The active login, previous restore point, manual save, and restore receipt are tracked separately. Recording and restoration use locks; recording skips captures during restoration.

The default restore point is the newest usable snapshot at least `restore_delay_seconds` before the previous login's last successful observation. Elapsed time determines the cutoff, so wall-clock corrections do not change the delay. Selection is bounded by the capture cadence and capture duration. Recorder restarts and i3 restarts within the same graphical login retain history. A new login rotates the checkpoint once, identified using boot ID, login session ID, and display. That previous checkpoint remains pinned throughout the new login: waiting five minutes or several hours before restoring does not replace it with the new desktop.

Short or empty logins preserve an existing previous restore point. If there is no previous checkpoint and the first session is shorter than the configured delay, its oldest usable snapshot is exposed as a clearly labeled short-session fallback. Empty or unsupported-only captures do not replace a usable checkpoint. The current session's buffer is pruned while referenced checkpoints remain pinned.

Closing applications over longer than the configured delay can affect the selected checkpoint. Changes made during the delay immediately before shutdown can be omitted. For an exact checkpoint before a longer shutdown routine:

```sh
i3-session save
# At the next login:
i3-session restore --source manual
```

Additional inspection/recovery commands:

```sh
i3-session list
i3-session restore --source current --dry-run
i3-session restore --snapshot SNAPSHOT_ID --dry-run
i3-session stop
```

`save` is an explicit pinned checkpoint and does not change automatic delayed selection. `capture` adds a single observation to automatic history; ordinary use relies on the recorder. Stopping does not delete checkpoints. A repeated complete restore can be performed in a later graphical login; within one login it remains a no-op. If recording stops after errors, inspect `recorder.log`, correct the cause, and run `start`.

## Implementation and verification

`i3-resurrect==1.4.2` supplies layout serialization. The wrapper uses direct i3 IPC for window placement and direct argv launches, so it does not require `xdotool` or use upstream's window-unmapping restore routine. It loads the installed serializer in a private module namespace to avoid upstream's import-time configuration writes and legacy `distutils` dependency. The pinned upstream source is not copied or modified.

Tests exercise delayed selection, login rotation, short sessions, atomic writes, retention, private state, locks, dry-run and repeated/partial restore behavior, application recipes, and VS Code settings edits. When Xvfb is installed, backend tests start a separate i3 server and synthetic windows to verify real layout restoration without touching the user's desktop.

```sh
uv pip install --python ~/.local/share/i3-session/venv/bin/python pytest
~/.local/share/i3-session/venv/bin/python -B -m pytest -q -p no:cacheprovider tests
bash -n .scripts/install-i3-session
bash -n setup.sh
i3 -C -c .config/i3/config
```

Run these checks from the repository root. Full browser and VS Code restoration on a real reboot remains an application-level acceptance check; the test display exercises the window-manager behavior independently.

Optional application tests use the installed browsers/editor with disposable profiles, a private X server, and temporary application data directories. They verify cold launches and folder capture without reopening your working desktop:

```sh
I3_SESSION_TEST_CODE=1 ~/.local/share/i3-session/venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_i3_session_code_integration.py
I3_SESSION_BROWSER_TESTS=1 ~/.local/share/i3-session/venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_i3_session_browser_integration.py
```
