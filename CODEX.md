# Codex on this workstation

The shell functions in `.bash_aliases` retain `codex` for the personal account and `codex-academic` for the academic account. Both preserve the shared Python environment and file-based credential selection. Configuration and memory remain shared through the existing links; authentication and session stores stay in their separate `CODEX_HOME` directories.

Since 2026-09-20, each account uses OpenAI's managed standalone installation. The personal command is `~/.local/bin/codex`; the academic command is `~/.codex-academic/bin/codex`. Their packages live below their respective account homes in `packages/standalone/`. The native daemon currently requires that layout; a pacman installation at `/usr/bin/codex` alone does not satisfy it.

Version 0.155.1 was installed with `--release 0.155.1`, which omits the installer's latest-channel selection marker. The existing pacman package was retained during verification. It is not the executable selected by these shell functions.

Use the [official installer](https://developers.openai.com/codex/cli#getting-started) for subsequent installation updates. Download and inspect the script, then invoke it once for each account with the appropriate `CODEX_HOME` and `CODEX_INSTALL_DIR`. For personal use those directories are `~/.codex` and `~/.local/bin`; for academic use they are `~/.codex-academic` and `~/.codex-academic/bin`. Choose the same intended version for both. Keep personal `~/.local/bin` as the default command directory in shell startup; the academic wrapper selects its binary explicitly. The installer may otherwise replace the default command or PATH block on the second invocation.

Ordinary local interactive commands still use `-p auto`. Management commands and queue submission omit that runtime profile. Explicit `resume --remote ...` also omits the injected profile: Codex restores the session's saved model and permissions, and rejects new permission overrides on that path. This exception does not change the existing profile files.

The learning workspace owns the small `coordinator` launcher. It uses native `app-server daemon start`, `resume --remote unix://`, and `queue --remote unix://`, with private role/session bindings in `~/.config/codex-coordinators/config.json`. No replacement daemon manager is installed. The current terminal sessions must be exited normally before their saved UUIDs can acquire writable ownership through the daemon.
