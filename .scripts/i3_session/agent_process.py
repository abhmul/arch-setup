"""Read-only native agent/session discovery for one unambiguous kitty pane.

Public interfaces:
* process_info(pid), process_start(pid), namespace(pid, tool): process metadata.
* window_terminal(kitty_pid, window_id): (terminal context or None, warnings).
* terminal_context(pid): foreground process context, including pre-exec helpers.
* session_for_process(pid, tool, config_home): exact native session or None.
* discover_window(kitty_pid, window_id): {context, binding, warnings}.
* hook_owner(tool, session_id=None, pid=None): verified native ancestor or None.

A context identifies boot, kitty process, shell process, OS window, and kitty
pane lifetimes. No content is typed into terminals, no files are written, and no
"latest" session is inferred. Managed daemons without foreground TTY ownership,
nested agents, ambiguous panes, and ambiguous native root sessions are refused.
Hook ownership may precede native SessionStart metadata: binding=None requires
the caller to validate the hook payload before registering its claimed session.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any
import uuid


PROC = Path("/proc")
MAX_METADATA_BYTES = 1024 * 1024
MAX_ANCESTORS = 64
MAX_DESCENDANTS = 4096
SHELLS = {"bash", "zsh", "fish", "sh", "dash", "ksh", "nu"}
ENVIRONMENT_KEYS = {"HOME", "WINDOWID", "KITTY_WINDOW_ID", "CODEX_HOME", "CLAUDE_CONFIG_DIR"}


def _limited_bytes(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_METADATA_BYTES + 1)
    if len(data) > MAX_METADATA_BYTES:
        raise ValueError("Native metadata exceeds the read limit")
    return data


def process_info(pid: int) -> dict[str, Any] | None:
    """Read only current-user process metadata; never return arbitrary env vars."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    path = PROC / str(pid)
    try:
        if path.stat().st_uid != os.getuid():
            return None
        fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] in {"Z", "X"}:
            return None
        argv = [os.fsdecode(value) for value in _limited_bytes(path / "cmdline").split(b"\0") if value]
        environment = {}
        for entry in _limited_bytes(path / "environ").split(b"\0"):
            key, separator, value = entry.partition(b"=")
            name = os.fsdecode(key)
            if separator and name in ENVIRONMENT_KEYS:
                environment[name] = os.fsdecode(value)
        result = {"pid": pid, "start": fields[19], "ppid": int(fields[1]),
                  "pgrp": int(fields[2]), "sid": int(fields[3]), "tty": int(fields[4]),
                  "tpgid": int(fields[5]), "argv": argv, "environment": environment,
                  "cwd": os.readlink(path / "cwd")}
        if (path / "stat").read_text().rsplit(")", 1)[1].split()[19] != result["start"]:
            return None
        return result
    except (OSError, ValueError, IndexError):
        return None


def process_start(pid: int) -> str | None:
    info = process_info(pid)
    return info["start"] if info else None


def _children(pid: int) -> list[int]:
    try:
        return [int(value) for value in (PROC / str(pid) / "task" / str(pid) / "children").read_text().split()]
    except (OSError, ValueError):
        return []


def _native_tool(info: dict[str, Any]) -> str | None:
    name = Path(info["argv"][0]).name if info["argv"] else ""
    return name if name in {"codex", "claude"} else None


def _interactive_agent(info: dict[str, Any], tool: str) -> bool:
    # Keep native discovery and pre-exec shell registration on one policy.
    from .agent_launch import interactive
    return bool(_native_tool(info) == tool and info["tty"] and interactive(tool, info["argv"][1:]))


def _shell(info: dict[str, Any]) -> bool:
    args = info["argv"]
    if not args or Path(args[0]).name.lstrip("-") not in SHELLS:
        return False
    # Restored terminals keep this fixed interactive shell as kitty's direct
    # child, then exec a normal prompt in the same PID after native resume exits.
    # Do not generalize this exception to arbitrary shell command strings.
    bootstrap = args[1:]
    options = set()
    while bootstrap:
        option = bootstrap[0]
        if option == "--noprofile" and option not in options:
            options.add(option)
            bootstrap = bootstrap[1:]
        elif option == "--rcfile" and option not in options and len(bootstrap) > 1 and Path(bootstrap[1]).is_absolute():
            options.add(option)
            bootstrap = bootstrap[2:]
        else:
            break
    if len(bootstrap) == 5 and Path(args[0]).name == "bash" and bootstrap[0] == "-ic":
        from .agent_launch import RESUME_SCRIPT
        if (bootstrap[1] == RESUME_SCRIPT and bootstrap[2] == "i3-session-resume"
                and bootstrap[3] in {"codex", "codex-academic", "claude"} and _session_id(bootstrap[4])):
            return True
    # A shell running a command string is not the interactive terminal owner.
    index = 1
    while index < len(args):
        arg = args[index]
        if arg in {"--rcfile", "--init-file", "-o", "+o"}:
            index += 2
            continue
        if (arg == "--command" or (arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:])
                or not arg.startswith(("-", "+"))):
            return False
        index += 1
    return True


def namespace(pid: int, tool: str) -> dict[str, str] | None:
    info = process_info(pid)
    if not info or tool not in {"codex", "claude"}:
        return None
    environment = info["environment"]
    home = Path(environment.get("HOME", str(Path.home())))
    key = "CODEX_HOME" if tool == "codex" else "CLAUDE_CONFIG_DIR"
    config_home = Path(environment.get(key, str(home / (".codex" if tool == "codex" else ".claude"))))
    if not config_home.is_absolute():
        return None
    config_home = config_home.resolve()
    launcher = "codex-academic" if tool == "codex" and config_home == (home / ".codex-academic").resolve() else tool
    return {"launcher": launcher, "config_home": str(config_home)}


def window_terminal(kitty_pid: int, window_id: int | str) -> tuple[dict[str, Any] | None, list[str]]:
    """Resolve a single direct interactive shell; count panes even at one cwd."""
    window_id = str(window_id)
    kitty = process_info(kitty_pid)
    if (not window_id.isdecimal() or int(window_id) <= 0 or not kitty or not kitty["argv"]
            or Path(kitty["argv"][0]).name != "kitty"):
        return None, ["Terminal process/window identity could not be verified."]
    panes = []
    for child_pid in _children(kitty_pid):
        child = process_info(child_pid)
        if not child or child["ppid"] != kitty_pid or not child["tty"]:
            continue
        claimed_window = child["environment"].get("WINDOWID")
        if claimed_window is None:
            return None, ["A kitty pane has no WINDOWID; exact terminal association is unavailable."]
        if claimed_window == window_id:
            panes.append(child)
    if len(panes) != 1:
        return None, ["Exact agent restore requires one kitty pane; tabs/splits are ambiguous."]
    shell = panes[0]
    pane = shell["environment"].get("KITTY_WINDOW_ID", "")
    if not _shell(shell) or not pane.isdecimal() or int(pane) <= 0:
        return None, ["The kitty window does not have one identifiable interactive shell."]
    try:
        boot_id = str(uuid.UUID((PROC / "sys/kernel/random/boot_id").read_text().strip()))
    except (OSError, ValueError):
        return None, ["Current boot identity is unavailable."]
    if process_start(kitty_pid) != kitty["start"] or process_start(shell["pid"]) != shell["start"]:
        return None, ["Terminal lifetime changed during discovery."]
    context = {"boot_id": boot_id, "kitty_pid": kitty_pid, "kitty_start": kitty["start"],
               "window_id": window_id, "shell_pid": shell["pid"], "shell_start": shell["start"],
               "kitty_window_id": pane}
    return context, []


def terminal_context(pid: int) -> dict[str, Any] | None:
    """Allow a foreground pre-exec helper, but never an agent's child command."""
    target = process_info(pid)
    if not target or not target["tty"] or target["pgrp"] <= 0 or target["pgrp"] != target["tpgid"]:
        return None
    current = target
    seen = set()
    for _ in range(MAX_ANCESTORS):
        if current["pid"] in seen:
            return None
        seen.add(current["pid"])
        parent = process_info(current["ppid"])
        if not parent:
            return None
        if _shell(current) and parent["argv"] and Path(parent["argv"][0]).name == "kitty":
            context, _ = window_terminal(parent["pid"], current["environment"].get("WINDOWID", ""))
            if (context and target["tty"] == current["tty"] and target["sid"] == current["sid"]
                    and target["pgrp"] == current["tpgid"] and process_start(pid) == target["start"]):
                return context
            return None
        if current["pid"] != pid and _native_tool(current):
            return None
        current = parent
    return None


def _session_id(value: Any) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        return None
    return str(uuid.UUID(value))


def _valid_cwd(value: Any) -> bool:
    return isinstance(value, str) and Path(value).is_absolute() and Path(value).is_dir()


def _claude_session(info: dict[str, Any], home: Path) -> tuple[dict[str, str] | None, str]:
    try:
        metadata = json.loads(_limited_bytes(home / "sessions" / f'{info["pid"]}.json'))
    except (OSError, ValueError):
        return None, "unavailable"
    if (not isinstance(metadata, dict) or metadata.get("pid") != info["pid"]
            or str(metadata.get("procStart")) != info["start"] or metadata.get("kind") != "interactive"
            or metadata.get("entrypoint") != "cli"):
        return None, "invalid"
    session_id = _session_id(metadata.get("sessionId"))
    cwd = metadata.get("cwd")
    if not session_id or not _valid_cwd(cwd):
        return None, "invalid"
    projects = (home / "projects").resolve()
    paths = {path.resolve() for path in projects.glob(f"*/{session_id}.jsonl")
             if path.is_file() and path.resolve().is_relative_to(projects)}
    if len(paths) > 1:
        return None, "ambiguous"
    if not paths:
        return None, "pending:" + session_id
    return {"session_id": session_id, "cwd": cwd, "transcript_path": str(paths.pop())}, "verified"


def _codex_session(info: dict[str, Any], home: Path) -> tuple[dict[str, str] | None, str]:
    candidates = {}
    try:
        descriptors = list((PROC / str(info["pid"]) / "fd").iterdir())
    except OSError:
        return None, "unavailable"
    for descriptor in descriptors:
        try:
            path = Path(os.readlink(descriptor)).resolve()
            if path.suffix != ".jsonl" or not any(path.is_relative_to((home / folder).resolve()) for folder in ("sessions", "archived_sessions")):
                continue
            fdinfo = (PROC / str(info["pid"]) / "fdinfo" / descriptor.name).read_text()
            flags = next(line.split(":", 1)[1].strip() for line in fdinfo.splitlines() if line.startswith("flags:"))
            if int(flags, 8) & os.O_ACCMODE == os.O_RDONLY:
                continue
            if path.stat().st_ino != descriptor.stat().st_ino:
                continue
            with path.open("rb") as stream:
                header = stream.readline(MAX_METADATA_BYTES + 1)
            if len(header) > MAX_METADATA_BYTES:
                continue
            value = json.loads(header)
            payload = value.get("payload", {})
            if value.get("type") != "session_meta" or payload.get("source") != "cli" or payload.get("parent_thread_id"):
                continue
            session_id = _session_id(payload.get("id"))
            cwd = payload.get("cwd")
            if session_id and _valid_cwd(cwd):
                candidates[(session_id, str(path))] = {"session_id": session_id, "cwd": cwd, "transcript_path": str(path)}
        except (OSError, ValueError, AttributeError, StopIteration):
            continue
    if len(candidates) == 1:
        return next(iter(candidates.values())), "verified"
    return None, "ambiguous" if candidates else "unavailable"


def _session_status(pid: int, tool: str, config_home: str | Path) -> tuple[dict[str, str] | None, str]:
    info = process_info(pid)
    space = namespace(pid, tool)
    if not info or not space or not _interactive_agent(info, tool) or Path(config_home).resolve() != Path(space["config_home"]):
        return None, "invalid"
    home = Path(space["config_home"])
    result, status = _claude_session(info, home) if tool == "claude" else _codex_session(info, home)
    if process_start(pid) != info["start"]:
        return None, "invalid"
    return result, status


def session_for_process(pid: int, tool: str, config_home: str | Path) -> dict[str, str] | None:
    """Return a unique exact native root session; no transcript search by time."""
    return _session_status(pid, tool, config_home)[0]


def _binding(info: dict[str, Any], tool: str, space: dict[str, str], session: dict[str, str]) -> dict[str, Any]:
    return {"tool": tool, **space, **session, "agent_pid": info["pid"], "agent_start": info["start"]}


def discover_window(kitty_pid: int, window_id: int | str) -> dict[str, Any]:
    from .agent_launch import unsupported_terminal_mode
    context, warnings = window_terminal(kitty_pid, window_id)
    result = {"context": context, "pid": None, "binding": None, "warnings": warnings}
    if context is None:
        return result
    pending = _children(context["shell_pid"])
    seen = set()
    candidates = []
    unsupported = []
    while pending and len(seen) < MAX_DESCENDANTS:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        info = process_info(pid)
        if not info:
            continue
        tool = _native_tool(info)
        if tool:
            if terminal_context(pid) == context:
                warning = unsupported_terminal_mode(tool, info["argv"][1:])
                if warning:
                    unsupported.append((info, warning))
                elif _interactive_agent(info, tool):
                    candidates.append((info, tool))
            # An agent's descendants are never independent terminal owners.
            continue
        pending.extend(_children(pid))
    if unsupported:
        # Legacy shells may not have run agent-launch's invalidation wrapper.
        # An unsupported foreground TUI must not inherit an older local session.
        result["warnings"].extend(warning for _, warning in unsupported)
        if len(unsupported) == 1 and not candidates:
            result["pid"] = unsupported[0][0]["pid"]
        return result
    if pending or len(candidates) > 1:
        result["warnings"].append("Several foreground agent candidates or an oversized process tree prevent exact association.")
        return result
    if candidates:
        info, tool = candidates[0]
        result["pid"] = info["pid"]
        space = namespace(info["pid"], tool)
        session = session_for_process(info["pid"], tool, space["config_home"]) if space else None
        if session:
            result["binding"] = _binding(info, tool, space, session)
        else:
            result["warnings"].append(f"Exact {tool} session metadata is unavailable or ambiguous; no session was guessed.")
    return result


def hook_owner(tool: str, session_id: str | None = None, pid: int | None = None) -> dict[str, Any] | None:
    """Find a foreground native hook ancestor; missing metadata stays unbound."""
    if tool not in {"codex", "claude"} or (session_id is not None and not _session_id(session_id)):
        return None
    expected = _session_id(session_id) if session_id is not None else None
    current = process_info(os.getpid() if pid is None else pid)
    seen = set()
    for _ in range(MAX_ANCESTORS):
        if not current or current["pid"] in seen:
            return None
        seen.add(current["pid"])
        native = _native_tool(current)
        if native:
            if native != tool or not _interactive_agent(current, tool):
                return None
            context = terminal_context(current["pid"])
            space = namespace(current["pid"], tool)
            if not context or not space:
                return None
            session, status = _session_status(current["pid"], tool, space["config_home"])
            if status in {"ambiguous", "invalid"} or (session and expected and session["session_id"] != expected):
                return None
            if expected and status.startswith("pending:") and status.removeprefix("pending:") != expected:
                return None
            return {"pid": current["pid"], "context": context, "tool": tool, **space,
                    "binding": _binding(current, tool, space, session) if session else None}
        current = process_info(current["ppid"])
    return None
