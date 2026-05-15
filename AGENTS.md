# AGENTS.md

This repository is the source of truth for the user's Arch Linux workstation setup. Most files are symlinked into `$HOME` by `setup.sh`.

## Scope

- Keep changes local to this repository unless the user explicitly asks to update live machine state.
- Do not edit global VSCode keybindings, unrelated dotfiles outside this repository, or generated build/cache output.
- Treat `tmp/` directories as scratch space and do not read from or write to them unless the user explicitly names one.
- Do not commit secrets. If a setting is machine-local or sensitive, put it in an untracked local file and document the expected shape instead.

## Important Files

- `setup.sh`: package installation and symlink bootstrap.
- `.bash_aliases`: shell aliases/functions; sourced by `.bashrc.extra`.
- `.bashrc.extra`: extra shell initialization loaded from the user's `.bashrc`.
- `.bash_profile`: login shell setup and X startup.
- `.config/i3/config`: i3 window-manager config; symlinked to `~/.config/i3`.
- `.config/kitty/kitty.conf`: kitty terminal config; symlinked to `~/.config/kitty`.
- `.scripts/`: helper scripts used by shell aliases and i3 bindings.
- `.snippets/`: HyperSnips/VSCode snippet files.

## Deployment Model

`setup.sh` assumes it is run from the repository root. It sets `SETUP_PATH=$(pwd)` and then symlinks tracked files/directories into `$HOME`, including `.bash_aliases`, `.bashrc.extra`, `.bash_profile`, `.scripts`, `.snippets`, `.config/i3`, and `.config/kitty`.

Prefer editing the tracked source file in this repository over editing the symlink target directly. If changing deployment behavior, update `setup.sh` and verify that the target symlink path still matches the tracked layout.

## Shell And Terminal Conventions

- Put shell aliases and small shell functions in `.bash_aliases`.
- Use shell functions instead of aliases when quoting, `$PWD`, backgrounding, or future flags matter.
- The terminal emulator is kitty. Do not force `TERM=xterm-kitty` for non-kitty terminals; `$TERM` should describe the actual terminal emulator.
- i3 bindings launch from i3's process context, not from the focused shell's current directory. Same-directory terminal spawning belongs either in a shell function run from the current shell or in kitty's own `launch --cwd=current` mapping.

## Testing

Use non-destructive checks by default:

- `bash -n setup.sh`
- `bash -n .bash_aliases`
- `bash -n .bashrc.extra`
- `kitty +runpy 'from kitty.config import load_config; bad=[]; load_config(".config/kitty/kitty.conf", accumulate_bad_lines=bad); [print(b) for b in bad]; raise SystemExit(1 if bad else 0)'`
- `i3 -C -c .config/i3/config` when i3 is installed

Do not run `setup.sh` unless the user explicitly asks; it installs packages, removes existing target paths, and rewrites symlinks.
