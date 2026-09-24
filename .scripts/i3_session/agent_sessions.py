"""Private terminal bookmarks. Native agents continue to own their transcripts."""

import hashlib
import json
from pathlib import Path
import time
import uuid

from .state import atomic_json, lock, read_json


LAUNCHERS = {"codex": "codex", "codex-academic": "codex", "claude": "claude"}
CONTEXT_KEYS = ("boot_id", "kitty_pid", "kitty_start", "window_id", "shell_pid", "shell_start", "kitty_window_id")
UNCONDITIONAL = object()


def identity(binding):
    return tuple(binding.get(key) for key in ("tool", "launcher", "config_home", "session_id"))


def validate_binding(value):
    if not isinstance(value, dict) or LAUNCHERS.get(value.get("launcher")) != value.get("tool"):
        raise ValueError("Unknown agent launcher")
    try:
        value = {key: value[key] for key in ("tool", "launcher", "config_home", "session_id", "cwd", "transcript_path")}
        value["session_id"] = str(uuid.UUID(value["session_id"]))
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Incomplete agent session identity") from exc
    for key in ("config_home", "cwd", "transcript_path"):
        if not isinstance(value[key], str) or "\0" in value[key] or not Path(value[key]).is_absolute():
            raise ValueError(f"Agent {key} must be an absolute path")
    root = Path(value["config_home"]).resolve()
    transcript = Path(value["transcript_path"]).resolve()
    base = root / ("sessions" if value["tool"] == "codex" else "projects")
    if not transcript.is_relative_to(base.resolve()) or value["session_id"] not in transcript.name or transcript.suffix != ".jsonl":
        raise ValueError("Agent transcript does not match its session and account")
    return value


def context_key(context):
    return hashlib.sha256(json.dumps({key: context[key] for key in CONTEXT_KEYS}, sort_keys=True).encode()).hexdigest()


class Registry:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "agents.json"
        self.lock_path = self.directory / "agents.lock"

    def read(self):
        data = read_json(self.path, {"schema": 1, "terminals": {}, "revoked": []})
        if not isinstance(data, dict) or data.get("schema") != 1:
            raise ValueError("Unsupported agent bookmark schema")
        if not isinstance(data.get("terminals"), dict) or not isinstance(data.get("revoked"), list):
            raise ValueError("Malformed agent bookmark registry")
        return data

    def begin(self, context, launcher, config_home, pid, start, *, warning=None):
        if launcher not in LAUNCHERS:
            raise ValueError("Unknown agent launcher")
        with lock(self.lock_path):
            data = self.read()
            token = uuid.uuid4().hex
            key = context_key(context)
            previous = data["terminals"].get(key, {})
            ids = list(previous.get("binding_ids", []))
            if previous.get("binding"):
                ids.append(previous["binding"]["binding_id"])
            data["terminals"][key] = {
                "context": context, "binding": None, "updated_at": time.time(),
                "binding_ids": list(dict.fromkeys(ids)),
                "invocation": {"token": token, "pid": pid, "start": str(start),
                               "launcher": launcher, "config_home": str(config_home)},
                "warning": warning or "Agent started; its exact session has not been confirmed yet.",
            }
            atomic_json(self.path, data)
        return token

    def remember(self, context, binding, *, owner_pid=None, owner_start=None, expected_entry=UNCONDITIONAL):
        binding = validate_binding(binding)
        with lock(self.lock_path):
            data = self.read()
            key = context_key(context)
            if expected_entry is not UNCONDITIONAL and data["terminals"].get(key) != expected_entry:
                return None  # Native hooks changed the association during discovery.
            entry = data["terminals"].setdefault(key, {"context": context})
            invocation = entry.get("invocation")
            if invocation and owner_pid is not None and (
                invocation["pid"] != owner_pid or invocation["start"] != str(owner_start)
                or invocation["launcher"] != binding["launcher"]
                or Path(invocation["config_home"]).resolve() != Path(binding["config_home"]).resolve()
            ):
                return None  # Late event from an earlier invocation.
            if entry.get("forgotten") == list(identity(binding)):
                return None
            old = entry.get("binding")
            binding["binding_id"] = old["binding_id"] if old and identity(old) == identity(binding) else uuid.uuid4().hex
            entry["binding_ids"] = list(dict.fromkeys([*entry.get("binding_ids", []), binding["binding_id"]]))
            entry.update(binding=binding, warning=None, updated_at=time.time(), status="confirmed")
            entry.pop("forgotten", None)
            atomic_json(self.path, data)
            return binding

    def ended(self, context, session_id, *, switched=False, owner_pid=None, owner_start=None):
        with lock(self.lock_path):
            data = self.read()
            entry = data["terminals"].get(context_key(context))
            invocation = (entry or {}).get("invocation")
            if invocation and owner_pid is not None and (
                invocation["pid"] != owner_pid or invocation["start"] != str(owner_start)
            ):
                return
            if entry and (entry.get("binding") or {}).get("session_id") == session_id:
                entry["status"] = "awaiting session switch" if switched else "closed"
                entry["warning"] = "Agent switched sessions; waiting for the new identity." if switched else None
                atomic_json(self.path, data)

    def lookup(self, context):
        entry = self.read()["terminals"].get(context_key(context), {})
        if entry.get("warning"):
            return None, [entry["warning"]]
        return entry.get("binding"), []

    def unconfirmed(self, context, warning, *, expected_entry=UNCONDITIONAL):
        with lock(self.lock_path):
            data = self.read()
            entry = data["terminals"].get(context_key(context))
            if expected_entry is not UNCONDITIONAL and entry != expected_entry:
                return
            if entry:
                entry["warning"] = warning
                atomic_json(self.path, data)

    def forget(self, context):
        with lock(self.lock_path):
            data = self.read()
            entry = data["terminals"].get(context_key(context))
            binding = (entry or {}).get("binding")
            ids = list((entry or {}).get("binding_ids", []))
            if binding:
                ids.append(binding["binding_id"])
            if not ids:
                return False
            data["revoked"] = list(dict.fromkeys([*data["revoked"], *ids]))
            entry.update(binding=None, binding_ids=[], forgotten=list(identity(binding)) if binding else None,
                         warning=None, status="forgotten")
            atomic_json(self.path, data)
            return True

    def revoked(self, binding):
        return binding.get("binding_id") in self.read()["revoked"]
