"""Add session-tracking hooks without replacing existing agent configuration.

Codex trust uses its own hooks/list hashes and scoped config/batchWrite edits;
this module never derives hashes or bypasses hook trust. It starts no threads.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import stat
import subprocess
import tempfile
import time


HOOK_TIMEOUT_SECONDS = 3
PROTOCOL_TIMEOUT_SECONDS = 20
MAX_PROTOCOL_BYTES = 2 * 1024 * 1024
DEFAULT_EVENTS = ("SessionStart", "UserPromptSubmit", "SessionEnd")
EVENT_NAMES = {"sessionStart": "session_start", "userPromptSubmit": "user_prompt_submit",
               "sessionEnd": "session_end"}


class InstallError(RuntimeError):
    pass


def hook_command(tool):
    if tool not in ("codex", "claude"):
        raise InstallError(f"Unsupported agent: {tool}")
    return f'"$HOME/.local/bin/i3-session" agent-hook --tool {tool}'


def merge_hooks(document, tool, events=DEFAULT_EVENTS):
    if not isinstance(document, dict):
        raise InstallError("Agent settings must contain a JSON object")
    result = copy.deepcopy(document)
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise InstallError("Agent hooks must be a JSON object")
    command = hook_command(tool)
    added = []
    for event in dict.fromkeys(events):
        if event not in DEFAULT_EVENTS:
            raise InstallError(f"Unsupported hook event: {event}")
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise InstallError(f"Existing {event} hooks must be a list")
        found = False
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise InstallError(f"Existing {event} hook group is malformed")
            found |= any(isinstance(item, dict) and item.get("type") == "command"
                         and item.get("command") == command for item in group["hooks"])
        if not found:
            groups.append({"hooks": [{"type": "command", "command": command,
                                       "timeout": HOOK_TIMEOUT_SECONDS}]})
            added.append(event)
    return result, added


def _absolute(path):
    # Preserve the lexical account namespace; only file writes resolve symlinks.
    return Path(path).expanduser().absolute()


def _backup(path, backup_dir, original):
    if original is None:
        return None
    directory = _absolute(backup_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    digest = hashlib.sha256(str(path).encode()).hexdigest()
    target = directory / f"{path.name}.{digest}.original"
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if target.is_symlink() or not target.is_file():
            raise InstallError(f"Backup path is not a regular file: {target}")
        target.chmod(0o600)
        return str(target)
    with os.fdopen(fd, "wb") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    return str(target)


def _atomic_write(path, content, original, mode):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.i3-session-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
        current = path.read_bytes() if path.exists() else None
        if current != original:
            raise InstallError(f"Settings changed during installation: {path}")
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


class AppServer:
    """Bounded stdio client for a dedicated, threadless native app-server."""

    def __init__(self, binary, config_home):
        environment = os.environ.copy()
        # Select the requested real Codex account/config namespace for this child.
        environment["CODEX_HOME"] = str(_absolute(config_home))
        self.process = subprocess.Popen([str(binary), "app-server", "--stdio"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=environment)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = b""
        self.sequence = 0

    def __enter__(self):
        try:
            response = self.request("initialize", {
                "clientInfo": {"name": "i3-session-hook-installer", "version": "1"},
                "capabilities": {"experimentalApi": True},
            })
            if not isinstance(response, dict):
                raise InstallError("Invalid Codex initialization response")
            self._send({"method": "initialized", "params": {}})
            return self
        except BaseException:
            self.close()
            raise

    def _send(self, message):
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        self.process.stdin.flush()

    def request(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + PROTOCOL_TIMEOUT_SECONDS
        while True:
            if b"\n" not in self.buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.selector.select(remaining):
                    raise InstallError(f"Codex app-server timed out during {method}")
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise InstallError(f"Codex app-server closed during {method}")
                self.buffer += chunk
                if len(self.buffer) > MAX_PROTOCOL_BYTES:
                    raise InstallError("Codex app-server response exceeded the size limit")
                continue
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                response = json.loads(line)
            except (ValueError, UnicodeError) as exc:
                raise InstallError("Codex app-server returned malformed JSON") from exc
            if not isinstance(response, dict):
                raise InstallError("Codex app-server returned a non-object message")
            if "method" in response and "id" in response:
                raise InstallError("Unexpected Codex server request; no approvals were granted")
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise InstallError(f"Codex {method} failed: {response['error']}")
            if "result" not in response:
                raise InstallError(f"Codex {method} response has no result")
            return response["result"]

    def close(self):
        self.selector.close()
        self.process.stdin.close()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.process.stdout.close()

    def __exit__(self, *_):
        self.close()


def _owned_metadata(response, expected_source, command):
    if not isinstance(response, dict) or not isinstance(response.get("data"), list):
        raise InstallError("Invalid hooks/list response")
    owned = {}
    for entry in response["data"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
            raise InstallError("Invalid hooks/list entry")
        if entry.get("errors"):
            raise InstallError("Codex reported hook configuration errors; no trust changed")
        for hook in entry["hooks"]:
            if not isinstance(hook, dict):
                raise InstallError("Invalid hook metadata")
            if hook.get("sourcePath") != expected_source or hook.get("command") != command:
                continue
            event = EVENT_NAMES.get(hook.get("eventName"))
            key = hook.get("key")
            valid = (
                event is not None and hook.get("handlerType") == "command"
                and hook.get("source") == "user" and hook.get("isManaged") is False
                and hook.get("enabled") is True and hook.get("async", False) is False
                and hook.get("matcher") in (None, "", "*")
                and hook.get("timeoutSec") == HOOK_TIMEOUT_SECONDS
                and hook.get("trustStatus") in ("untrusted", "modified", "trusted")
                and isinstance(key, str)
                and re.fullmatch(re.escape(expected_source + ":" + event + ":") + r"\d+:\d+", key)
                and isinstance(hook.get("currentHash"), str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", hook["currentHash"])
            )
            if not valid:
                raise InstallError("Installed hook metadata differs from the expected stable definition")
            if key in owned and owned[key] != hook:
                raise InstallError("Conflicting Codex metadata for the same hook key")
            owned[key] = hook
    if not owned:
        raise InstallError(f"Codex did not discover the installed hooks at {expected_source}")
    return owned


def trust_codex_hooks(binary, config_home, expected_source, hook_command, *, client_factory=AppServer):
    """Trust only these installed definitions using hashes supplied by Codex."""
    home = _absolute(config_home)
    source = str(_absolute(expected_source))
    config_path = (home / "config.toml").resolve()
    with client_factory(binary, home) as client:
        config = client.request("config/read", {"includeLayers": True})
        if not isinstance(config, dict) or not isinstance(config.get("layers"), list):
            raise InstallError("Invalid config/read response")
        versions = [layer.get("version") for layer in config["layers"]
                    if isinstance(layer, dict) and isinstance(layer.get("name"), dict)
                    and layer["name"].get("type") == "user"
                    and layer["name"].get("file")
                    and Path(layer["name"]["file"]).resolve() == config_path]
        if len(versions) != 1 or not isinstance(versions[0], str):
            raise InstallError("Could not identify the Codex user config version")
        query = {"cwds": [str(Path.home())]}
        owned = _owned_metadata(client.request("hooks/list", query), source, hook_command)
        pending = {key: hook for key, hook in owned.items() if hook["trustStatus"] != "trusted"}
        if pending:
            edits = [{"keyPath": "hooks.state." + json.dumps(key) + ".trusted_hash",
                      "value": hook["currentHash"], "mergeStrategy": "upsert"}
                     for key, hook in pending.items()]
            result = client.request("config/batchWrite", {
                "edits": edits, "filePath": str(config_path), "expectedVersion": versions[0],
                "reloadUserConfig": True,
            })
            if (not isinstance(result, dict) or result.get("status") != "ok"
                    or not isinstance(result.get("filePath"), str)
                    or Path(result["filePath"]).resolve() != config_path
                    or not isinstance(result.get("version"), str)):
                raise InstallError("Codex did not confirm the scoped trust write")
            verified = _owned_metadata(client.request("hooks/list", query), source, hook_command)
            for key, hook in owned.items():
                if (key not in verified or verified[key]["currentHash"] != hook["currentHash"]
                        or verified[key]["trustStatus"] != "trusted"):
                    raise InstallError("Codex hook trust could not be verified after writing")
        return {"source": source, "trusted": list(owned), "newly_trusted": list(pending)}


def configure_agent_hooks(*, codex_hooks=(), claude_settings=(), backup_dir,
                          include_user_prompt=True, include_session_end=True,
                          trust_installed_hooks=False, codex_binary="codex",
                          trust_function=trust_codex_hooks):
    events = ["SessionStart"]
    if include_user_prompt:
        events.append("UserPromptSubmit")
    if include_session_end:
        events.append("SessionEnd")
    plans, codex_sources = {}, []
    for tool, paths in (("codex", codex_hooks), ("claude", claude_settings)):
        for raw in paths:
            source = _absolute(raw)
            target = source.resolve()
            if tool == "codex" and source not in codex_sources:
                codex_sources.append(source)
            if target not in plans:
                original = target.read_bytes() if target.exists() else None
                try:
                    document = json.loads(original) if original is not None else {}
                except (ValueError, UnicodeError) as exc:
                    raise InstallError(f"Invalid JSON settings: {source}") from exc
                plans[target] = {"original": original, "document": document, "sources": [], "added": [],
                                 "mode": stat.S_IMODE(target.stat().st_mode) if original is not None else 0o600}
            plan = plans[target]
            if str(source) not in plan["sources"]:
                plan["sources"].append(str(source))
            plan["document"], added = merge_hooks(plan["document"], tool, events)
            plan["added"].extend({"tool": tool, "event": event} for event in added)
    report = {"files": [], "trust": [], "trust_pending": []}
    for target, plan in plans.items():
        backup = None
        if plan["added"]:
            backup = _backup(target, backup_dir, plan["original"])
            content = (json.dumps(plan["document"], indent=2, ensure_ascii=False) + "\n").encode()
            _atomic_write(target, content, plan["original"], plan["mode"])
        report["files"].append({"path": str(target), "sources": plan["sources"],
                                "added": plan["added"], "backup": backup,
                                "changed": bool(plan["added"])})
    if trust_installed_hooks:
        binary = shutil.which(str(codex_binary))
        if not binary:
            raise InstallError(f"Codex executable is unavailable: {codex_binary}")
        for source in codex_sources:
            config_path = (source.parent / "config.toml").resolve()
            original = config_path.read_bytes() if config_path.exists() else None
            _backup(config_path, backup_dir, original)
            report["trust"].append(trust_function(binary, source.parent, source, hook_command("codex")))
    else:
        report["trust_pending"] = list(map(str, codex_sources))
    return report


install_hooks = configure_agent_hooks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-hooks", action="append", default=[])
    parser.add_argument("--claude-settings", action="append", default=[])
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--no-user-prompt", action="store_true")
    parser.add_argument("--no-session-end", action="store_true")
    parser.add_argument("--trust-installed-hooks", action="store_true")
    parser.add_argument("--codex-binary", default="codex")
    args = parser.parse_args(argv)
    if not args.codex_hooks and not args.claude_settings:
        parser.error("provide at least one --codex-hooks or --claude-settings path")
    try:
        report = configure_agent_hooks(codex_hooks=args.codex_hooks, claude_settings=args.claude_settings,
                                       backup_dir=args.backup_dir, include_user_prompt=not args.no_user_prompt,
                                       include_session_end=not args.no_session_end,
                                       trust_installed_hooks=args.trust_installed_hooks,
                                       codex_binary=args.codex_binary)
    except (InstallError, OSError) as exc:
        parser.exit(1, f"Agent hook installation failed: {exc}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
