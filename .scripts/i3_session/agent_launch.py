"""Native agent entry points; saved conversations are never copied or replayed."""

import json
import os
from pathlib import Path
import sys

from .agent_sessions import LAUNCHERS, Registry, context_key, validate_binding


CODEX_COMMANDS = {"agents", "exec", "e", "review", "login", "logout", "doctor", "app-server",
                  "remote-control", "completion", "update", "queue", "archive", "delete", "unarchive",
                  "migrate-rollouts", "mcp", "mcp-server", "exec-server", "plugin", "sandbox", "debug",
                  "apply", "a", "cloud", "features", "help"}
CLAUDE_COMMANDS = {"agents", "attach", "auth", "auto-mode", "doctor", "gateway", "import", "install",
                   "logs", "mcp", "plugin", "plugins", "project", "respawn", "rm", "setup-token",
                   "stop", "kill", "ultrareview", "update", "upgrade", "daemon"}
VALUE_FLAGS = {
    "codex": {"-c", "--config", "-m", "--model", "-p", "--profile", "-s", "--sandbox", "-a",
              "--ask-for-approval", "-C", "--cd", "--add-dir", "-i", "--image", "--enable", "--disable",
              "--local-provider", "--remote-auth-token-env"},
    "claude": {"--add-dir", "--agent", "--agents", "--allowedTools", "--allowed-tools", "--append-system-prompt",
               "--autocompact", "--betas", "--debug-file", "--disallowedTools", "--disallowed-tools", "--effort",
               "--fallback-model", "--mcp-config", "--model", "--name", "-n", "--permission-mode",
               "--plugin-dir", "--session-id", "--setting-sources", "--settings", "--system-prompt",
               "--system-prompt-snapshot", "--tools"},
}


def unsupported_terminal_mode(tool, args):
    """Flag interactive modes whose session cannot be proven for this terminal."""
    index = 0
    first_positional = True
    while index < len(args):
        arg = args[index]
        flag = arg.split("=", 1)[0]
        if flag in {"--help", "-h", "--version", "-V", "-v", "--json", "--print"}:
            return None
        if flag in VALUE_FLAGS[tool] and "=" not in arg:
            index += 2
            continue
        if arg == "--":
            break
        if tool == "claude" and flag in {"-r", "--resume"} and "=" not in arg:
            index += 2 if index + 1 < len(args) and not args[index + 1].startswith("-") else 1
            continue
        if tool == "codex" and flag == "--remote":
            return "Remote Codex attachment cannot be mapped to one local session; terminal will reopen as a shell."
        if not arg.startswith("-"):
            if first_positional and arg in ({"agents"} if tool == "codex" else {"agents", "attach"}):
                if any(value in {"--help", "-h", "--json"} for value in args[index + 1:]):
                    return None
                return "Agent dashboard/attachment has no unique terminal session; terminal will reopen as a shell."
            first_positional = False
        index += 1
    return None


def interactive(tool, args):
    """Management, detached and print modes must never become terminal bookmarks."""
    index = 0
    first_positional = True
    while index < len(args):
        arg = args[index]
        flag = arg.split("=", 1)[0]
        if flag in {"--help", "-h", "--version", "-V", "-v"}:
            return False
        if tool == "claude" and flag in {"-p", "--print", "--bg", "--background", "--cloud", "--teleport"}:
            return False
        if tool == "claude" and arg.startswith("-p") and not arg.startswith("--"):
            return False
        if tool == "codex" and flag == "--remote":
            return False  # No proven client-to-terminal identity for remote/shared-server attachments.
        if flag in VALUE_FLAGS[tool] and "=" not in arg:
            index += 2
            continue
        if arg == "--":
            return True
        if tool == "claude" and flag in {"-r", "--resume"} and "=" not in arg:
            index += 2 if index + 1 < len(args) and not args[index + 1].startswith("-") else 1
            continue
        if not arg.startswith("-"):
            if first_positional and arg in (CODEX_COMMANDS if tool == "codex" else CLAUDE_COMMANDS):
                return False
            first_positional = False
        index += 1
    return True


def launch(directory, launcher, command):
    from . import agent_process
    if command and command[0] == "--":
        command = command[1:]
    if launcher not in LAUNCHERS or not command:
        raise ValueError("agent-launch requires a known launcher and executable argv")
    tool = LAUNCHERS[launcher]
    unsupported = unsupported_terminal_mode(tool, command[1:])
    if interactive(tool, command[1:]) or unsupported:
        try:
            context = agent_process.terminal_context(os.getpid())
            if context:
                config_home = os.environ.get("CODEX_HOME" if tool == "codex" else "CLAUDE_CONFIG_DIR")
                config_home = Path(config_home or Path.home() / (".codex" if tool == "codex" else ".claude")).expanduser().resolve()
                Registry(directory).begin(context, launcher, config_home, os.getpid(),
                                          agent_process.process_start(os.getpid()), warning=unsupported)
        except (OSError, ValueError) as exc:
            print(f"i3-session: agent tracking unavailable: {exc}", file=sys.stderr)
    environment = dict(os.environ, I3_SESSION_STATE_DIR=str(directory))
    os.execvpe(command[0], command, environment)


def hook(directory, tool, payload):
    """This hook produces no model context and never vetoes native agent work."""
    from . import agent_process
    if not isinstance(payload, dict) or tool not in {"codex", "claude"}:
        return
    event = payload.get("hook_event_name")
    if event not in {"SessionStart", "SessionEnd", "UserPromptSubmit"}:
        return
    if tool == "codex" and event == "SessionStart" and payload.get("source") not in {"startup", "resume", "clear"}:
        return
    owner = agent_process.hook_owner(tool, payload.get("session_id"))
    if not owner:
        return
    registry = Registry(directory)
    if event == "SessionEnd":
        registry.ended(owner["context"], payload.get("session_id"),
                       switched=payload.get("reason") in {"clear", "resume"},
                       owner_pid=owner["pid"], owner_start=agent_process.process_start(owner["pid"]))
        return
    binding = dict(tool=tool, launcher=owner["launcher"], config_home=owner["config_home"],
                   session_id=payload.get("session_id"), cwd=payload.get("cwd"),
                   transcript_path=payload.get("transcript_path"))
    binding = validate_binding(binding)
    # Codex's subagents can share a process and terminal; only CLI-root rollouts
    # are eligible. Read one metadata record, never conversation content.
    if tool == "codex":
        try:
            with Path(binding["transcript_path"]).open() as stream:
                metadata = json.loads(stream.readline()).get("payload", {})
            if metadata.get("source") != "cli" or metadata.get("id") != binding["session_id"]:
                return
        except (OSError, ValueError):
            return  # A later prompt hook or recorder observation can confirm it.
    registry.remember(owner["context"], binding, owner_pid=owner["pid"],
                      owner_start=agent_process.process_start(owner["pid"]))


RESUME_SCRIPT = '''case "$1" in
  codex) codex resume "$2" ;;
  codex-academic) codex-academic resume "$2" ;;
  claude) claude --resume "$2" ;;
  *) exit 2 ;;
esac
agent_exit=$?
if [ "$agent_exit" -ne 0 ]; then
  printf 'i3-session: native resume exited with status %s; this shell remains open.\\n' "$agent_exit" >&2
fi
exec bash -i'''


def resume_command(binding):
    validated = validate_binding(binding)
    return ["bash", "-ic", RESUME_SCRIPT, "i3-session-resume", validated["launcher"], validated["session_id"]]


def resume(directory, binding, *, run=None, shell=None):
    """Leave a usable shell after exit/failure; never fall back to a different ID."""
    try:
        validated = validate_binding(binding)
        if Registry(directory).revoked(binding):
            raise ValueError("This terminal's agent bookmark was forgotten")
        if not Path(validated["cwd"]).is_dir():
            raise ValueError("Saved agent working directory is missing")
        if not Path(validated["transcript_path"]).is_file():
            raise ValueError("Saved agent conversation is missing; no replacement session was started")
        expected = Path.home() / {"codex": ".codex", "codex-academic": ".codex-academic", "claude": ".claude"}[validated["launcher"]]
        if validated["tool"] == "codex" and Path(validated["config_home"]).resolve() != expected.resolve():
            raise ValueError("Saved Codex account does not match the configured launcher")
        os.chdir(validated["cwd"])
        environment = dict(os.environ, I3_SESSION_STATE_DIR=str(directory))
        if validated["tool"] == "claude":
            environment["CLAUDE_CONFIG_DIR"] = validated["config_home"]
        command = resume_command(validated)
        if run is None:
            # Replace Kitty's direct child with its persistent interactive
            # shell before the native agent starts; preserve the pane PID.
            os.execvpe(command[0], command, environment)
        status = run(command, env=environment)
        if status:
            print(f"i3-session: native resume exited with status {status}; left this shell open.", file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"i3-session: {exc}; left this shell open.", file=sys.stderr)
    if shell is not None:
        return shell()
    os.execvp("bash", ["bash", "-i"])


def capture_agent(directory, kitty_pid, window_id):
    from . import agent_process
    registry = Registry(directory)
    before = registry.read()
    discovered = agent_process.discover_window(kitty_pid, window_id)
    context = discovered.get("context")
    warnings = discovered.get("warnings", [])
    if not context:
        return None, warnings
    expected = before["terminals"].get(context_key(context))
    binding = discovered.get("binding")
    if binding:
        owner_pid = discovered.get("pid", binding.get("agent_pid"))
        owner_start = binding.get("agent_start") or agent_process.process_start(owner_pid)
        saved = registry.remember(context, binding, owner_pid=owner_pid, owner_start=owner_start, expected_entry=expected)
        if saved is None:
            return None, warnings
    if warnings:
        registry.unconfirmed(context, warnings[0], expected_entry=expected)
        return None, warnings
    return registry.lookup(context)


def terminal_command(directory, cwd, binding):
    return ["kitty", "--directory", cwd, str(Path(__file__).resolve().parents[1] / "i3-session"),
            "--state-dir", str(directory), "agent-resume", "--binding", json.dumps(binding, separators=(",", ":"))]
