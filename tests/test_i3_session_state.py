import argparse
import copy
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".scripts"))
from i3_session import cli, config, desktop
from i3_session.state import Store, atomic_json, lock


def payload(name="work", supported=True):
    return {"workspaces": [{"name": name, "windows": [{"command": ["kitty"] if supported else None,
                                                       "cwd": "/", "source_id": "1"}], "layout": {}}],
            "warnings": [], "focused_workspace": name}


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path, {"restore_delay_seconds": 300, "history_seconds": 600})


def observe(store, when, session="login-a", data=None):
    return store.observe(payload() if data is None else data, session, timestamp=when, elapsed=when)


def test_shutdown_closing_sequence_selects_old_configuration(store):
    good = observe(store, 0)
    observe(store, 200, data=payload("reduced"))
    observe(store, 310, data={"workspaces": []})
    result, reason = store.select("login-b")
    assert result["id"] == good["id"]
    assert reason == "delayed checkpoint"
    assert store.index()["active"]["session_id"] == "login-a"  # selection has no writes


def test_next_login_time_does_not_change_previous_cutoff(store):
    good = observe(store, 100)
    observe(store, 390, data=payload("closing"))
    observe(store, 410)
    observe(store, 100000, "login-b")
    assert store.select("login-b")[0]["id"] == good["id"]


def test_same_session_recorder_restart_keeps_active_history(store):
    observe(store, 0)
    checkpoint = observe(store, 15)
    observe(Store(store.directory, store.config), 315)
    assert store.index()["previous"] is None
    assert store.select("login-a", "current")[0]["id"] == checkpoint["id"]


def test_new_session_rotation_happens_once(store):
    good = observe(store, 0)
    observe(store, 301)
    observe(store, 1000, "login-b")
    observe(store, 1015, "login-b")
    assert store.select("login-b")[0]["id"] == good["id"]


@pytest.mark.parametrize("new_payload", [{"workspaces": []}, payload(supported=False), payload("short")])
def test_short_or_empty_login_cannot_erase_previous_checkpoint(store, new_payload):
    good = observe(store, 0)
    observe(store, 301)
    observe(store, 1000, "login-b", new_payload)
    observe(store, 1015, "login-c", {"workspaces": []})
    assert store.select("login-c")[0]["id"] == good["id"]


def test_first_short_session_uses_labeled_oldest_fallback(store):
    first = observe(store, 0)
    observe(store, 100)
    snapshot, reason = store.select("login-b")
    assert snapshot["id"] == first["id"]
    assert "short-session" in reason


def test_nondefault_delay_is_used(tmp_path):
    store = Store(tmp_path, {"restore_delay_seconds": 60, "history_seconds": 600})
    observe(store, 0)
    wanted = observe(store, 240)
    observe(store, 305)
    assert store.select("login-b")[0]["id"] == wanted["id"]


def test_increasing_delay_revalidates_old_checkpoint(store):
    store.config["restore_delay_seconds"] = 0
    observe(store, 0)
    observe(store, 15)
    assert store.index()["active"]["checkpoint"]
    store.config["restore_delay_seconds"] = 300
    observe(store, 30)
    assert store.index()["active"]["checkpoint"] is None
    assert "short-session" in store.select("login-b")[1]


def test_elapsed_clock_controls_delay_when_wall_clock_changes(store):
    first = store.observe(payload(), "a", timestamp=1000, elapsed=0)
    store.observe(payload(), "a", timestamp=500, elapsed=301)
    assert store.select("b")[0]["id"] == first["id"]


def test_pruning_retains_previous_and_manual_and_checkpoint(store):
    previous = observe(store, 0)
    observe(store, 301)
    observe(store, 1000, "login-b")
    manual = store.save_manual(payload(), "login-b")
    for when in range(1015, 5000, 15):
        observe(store, when, "login-b")
    assert store.snapshot(previous["id"])
    assert store.snapshot(manual["id"])
    assert len(list((store.directory / "snapshots").glob("*.json"))) <= 45


def test_interrupted_snapshot_write_does_not_replace_index(store, monkeypatch):
    before = observe(store, 0)
    from i3_session import state
    real_atomic = state.atomic_json
    def fail_index(path, value):
        if Path(path) == store.index_path:
            raise OSError("interrupted before index commit")
        return real_atomic(path, value)
    monkeypatch.setattr(state, "atomic_json", fail_index)
    with pytest.raises(OSError):
        observe(store, 300)
    assert store.index()["active"]["history"][0]["id"] == before["id"]
    assert len(store.index()["active"]["history"]) == 1
    monkeypatch.setattr(state, "atomic_json", real_atomic)
    observe(store, 315)
    assert len(list((store.directory / "snapshots").glob("*.json"))) == 2


def test_private_snapshot_and_atomic_temporary_cleanup(store):
    saved = observe(store, 0)
    assert (store.directory / "snapshots" / f"{saved['id']}.json").stat().st_mode & 0o777 == 0o600
    assert not list(store.directory.rglob(".incoming-*"))


def test_lock_contention_is_nonblocking(tmp_path):
    with lock(tmp_path / "operation.lock") as first:
        with lock(tmp_path / "operation.lock", blocking=False) as second:
            assert first and not second


def test_reject_snapshot_path_traversal(store):
    with pytest.raises(ValueError):
        store.snapshot("../../other")


def restore_args(**kwargs):
    return argparse.Namespace(source="manual", snapshot=None, dry_run=False, retry=False, notify=False, **kwargs)


def test_restore_dry_run_never_invokes_backend(store, monkeypatch, capsys):
    store.save_manual(payload(), "a")
    monkeypatch.setattr(cli, "session_identity", lambda: "a")
    monkeypatch.setattr(desktop, "restore", lambda *_: pytest.fail("dry run launched"))
    args = restore_args()
    args.dry_run = True
    assert cli.restore(store.directory, dict(store.config, workspace_map={}), args) == 0
    assert "launches" in capsys.readouterr().out
    assert not store.index().get("restore_receipt")


def test_completed_restore_idempotent_within_login_but_works_next_login(store, monkeypatch):
    store.save_manual(payload(), "a")
    calls = []
    monkeypatch.setattr(cli, "session_identity", lambda: "a")
    monkeypatch.setattr(desktop, "restore", lambda *args: calls.append(args) or {"errors": [], "restored": []})
    assert cli.restore(store.directory, store.config, restore_args()) == 0
    assert cli.restore(store.directory, store.config, restore_args()) == 0
    assert len(calls) == 1
    monkeypatch.setattr(cli, "session_identity", lambda: "b")
    assert cli.restore(store.directory, store.config, restore_args()) == 0
    assert len(calls) == 2


def test_partial_restore_requires_explicit_retry_and_preserves_source(store, monkeypatch):
    source = store.save_manual(payload(), "a")
    monkeypatch.setattr(cli, "session_identity", lambda: "a")
    monkeypatch.setattr(desktop, "restore", lambda *_: {"errors": ["timeout"], "restored": []})
    assert cli.restore(store.directory, store.config, restore_args()) == 1
    with pytest.raises(ValueError, match="interrupted or partial"):
        cli.restore(store.directory, store.config, restore_args())
    assert store.snapshot(source["id"])


@pytest.mark.parametrize("value", ["-1s", "nan", "inf", "bogus"])
def test_invalid_duration_rejected(value):
    with pytest.raises(ValueError):
        config.duration(value)


def test_configuration_overrides_do_not_change_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"restore_delay_seconds": 420}))
    settings = config.load(path, interval="2s")
    assert settings["restore_delay_seconds"] == 420
    assert settings["capture_interval_seconds"] == 2
    assert config.load(delay="5m")["restore_delay_seconds"] == 300


def test_start_stops_verified_recorder_from_old_login(store, monkeypatch):
    settings = dict(store.config, capture_interval_seconds=15, startup_timeout_seconds=1)
    args = argparse.Namespace(config=None, delay=None, interval=None)
    monkeypatch.setattr(cli, "session_identity", lambda: "new-login")
    monkeypatch.setattr(cli, "is_running", lambda _: True)
    called = []
    old = {"session_id": "old-login", "pid": 12}
    new = {"session_id": "new-login", "pid": 123, "status": "recording"}
    records = iter([old, new])
    monkeypatch.setattr(cli, "read_json", lambda *_: next(records))
    monkeypatch.setattr(cli, "stop_recorder", lambda *_: called.append("stop"))
    class FakeProcess:
        pid = 123
        def poll(self):
            return None
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: called.append("start") or FakeProcess())
    assert cli.start(store.directory, settings, args) == 0
    assert called == ["stop", "start"]


def test_same_login_start_does_not_replace_recorder(store, monkeypatch):
    monkeypatch.setattr(cli, "session_identity", lambda: "a")
    monkeypatch.setattr(cli, "is_running", lambda _: True)
    monkeypatch.setattr(cli, "read_json", lambda *_: {"session_id": "a"})
    monkeypatch.setattr(cli, "stop_recorder", lambda *_: pytest.fail("same-login recorder stopped"))
    assert cli.start(store.directory, store.config, None) == 0


@pytest.mark.parametrize("override", [
    {"applications": [None]}, {"applications": [{"class": "Example", "command": "bad shell"}]},
    {"browser_executables": []}, {"code_title_prefix": False},
])
def test_invalid_application_configuration_rejected_before_capture(tmp_path, override):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(override))
    with pytest.raises(ValueError):
        config.load(path)
