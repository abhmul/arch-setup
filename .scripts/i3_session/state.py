"""Atomic checkpoints and session rotation. Call mutations under operation.lock."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

SCHEMA = 1


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".incoming-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


@contextmanager
def lock(path, blocking=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
        else:
            try:
                yield True
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def usable(snapshot):
    return any(window.get("command") for ws in snapshot.get("workspaces", []) for window in ws["windows"])


class Store:
    def __init__(self, directory, config):
        self.directory = Path(directory)
        self.config = config
        self.index_path = self.directory / "state.json"

    def index(self):
        data = read_json(self.index_path, {"schema": SCHEMA, "active": None, "previous": None, "manual": None})
        if data.get("schema") != SCHEMA:
            raise ValueError("Unsupported session state schema; existing state was preserved")
        return data

    def snapshot(self, snapshot_id):
        # Snapshot identifiers are UUID hex strings, never paths supplied by a caller.
        if not isinstance(snapshot_id, str) or len(snapshot_id) != 32 or any(c not in "0123456789abcdef" for c in snapshot_id):
            raise ValueError("Invalid snapshot identifier")
        snapshot = read_json(self.directory / "snapshots" / f"{snapshot_id}.json")
        if not snapshot or snapshot.get("schema") != SCHEMA or snapshot.get("id") != snapshot_id:
            raise ValueError(f"Snapshot {snapshot_id} is missing or invalid")
        return snapshot

    def rotate(self, index, session_id):
        active = index["active"]
        if active and active["session_id"] == session_id:
            return
        if active:
            checkpoint = active.get("checkpoint")
            if checkpoint:
                index["previous"] = {"id": checkpoint, "reason": "delayed checkpoint"}
            elif not index.get("previous"):
                first = next((item for item in active["history"] if item["usable"]), None)
                if first:
                    index["previous"] = {"id": first["id"], "reason": "short-session fallback (younger than configured delay)"}
        index["active"] = {"session_id": session_id, "history": [], "checkpoint": None,
                           "last_observed_at": None, "last_observed_elapsed": None}

    def observe(self, payload, session_id, timestamp=None, elapsed=None):
        timestamp = time.time() if timestamp is None else timestamp
        elapsed = time.monotonic() if elapsed is None else elapsed
        index = self.index()
        self.rotate(index, session_id)
        snapshot_id = uuid.uuid4().hex
        snapshot = dict(payload, schema=SCHEMA, id=snapshot_id, session_id=session_id,
                        captured_at=timestamp, captured_elapsed=elapsed)
        atomic_json(self.directory / "snapshots" / f"{snapshot_id}.json", snapshot)
        active = index["active"]
        active["last_observed_at"] = timestamp
        active["last_observed_elapsed"] = elapsed
        active["history"].append({"id": snapshot_id, "timestamp": timestamp, "elapsed": elapsed, "usable": usable(snapshot)})
        cutoff = elapsed - self.config["restore_delay_seconds"]
        eligible = [item for item in active["history"] if item["usable"] and item["elapsed"] <= cutoff]
        active["checkpoint"] = eligible[-1]["id"] if eligible else None
        horizon = max(self.config["history_seconds"], self.config["restore_delay_seconds"])
        pins = self.pins(index)
        active["history"] = [item for item in active["history"] if item["elapsed"] >= elapsed - horizon or item["id"] in pins]
        atomic_json(self.index_path, index)
        self.prune(index)
        return snapshot

    @staticmethod
    def pins(index):
        pins = {item["id"] for key in ("previous", "manual") if (item := index.get(key))}
        if (index.get("active") or {}).get("checkpoint"):
            pins.add(index["active"]["checkpoint"])
        receipt = index.get("restore_receipt")
        if receipt:
            pins.add(receipt["id"])
        return pins

    def prune(self, index):
        retained = self.pins(index) | {item["id"] for item in (index.get("active") or {}).get("history", [])}
        for path in (self.directory / "snapshots").glob("*.json"):
            if path.stem not in retained:
                path.unlink()

    def save_manual(self, payload, session_id):
        snapshot_id = uuid.uuid4().hex
        snapshot = dict(payload, schema=SCHEMA, id=snapshot_id, session_id=session_id,
                        captured_at=time.time(), captured_elapsed=time.monotonic())
        if not usable(snapshot):
            raise ValueError("No supported application windows to save")
        atomic_json(self.directory / "snapshots" / f"{snapshot_id}.json", snapshot)
        index = self.index()
        index["manual"] = {"id": snapshot_id, "reason": "explicit save"}
        atomic_json(self.index_path, index)
        self.prune(index)
        return snapshot

    def select(self, session_id, source="previous", snapshot_id=None):
        if snapshot_id:
            return self.snapshot(snapshot_id), "explicit snapshot"
        index = self.index()
        # Infer rotation read-only as restore may run before the recorder starts.
        self.rotate(index, session_id)
        if source == "current":
            chosen = index["active"].get("checkpoint")
            pointer = {"id": chosen, "reason": "current delayed checkpoint"} if chosen else None
        else:
            pointer = index.get(source)
        if not pointer:
            raise ValueError(f"No {source} checkpoint available yet")
        return self.snapshot(pointer["id"]), pointer["reason"]

    def receipt(self, snapshot_id, status, report=None, destination_session=None):
        index = self.index()
        index["restore_receipt"] = {"id": snapshot_id, "status": status, "at": time.time(),
                                    "report": report, "destination_session": destination_session}
        atomic_json(self.index_path, index)
