import copy
import json
import os
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".scripts"))
from i3_session.agent_sessions import Registry, validate_binding
from i3_session import agent_launch
from i3_session.state import Store


@pytest.fixture
def context():
    return dict(boot_id="boot", kitty_pid=10, kitty_start="100", window_id="123",
                shell_pid=11, shell_start="110", kitty_window_id="1")


@pytest.fixture
def binding(tmp_path):
    identifier = str(uuid.uuid4())
    root = tmp_path / "agent-home"
    transcript = root / "projects" / "project" / (identifier + ".jsonl")
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"message":"already saved"}\n')
    return dict(tool="claude", launcher="claude", config_home=str(root), session_id=identifier,
                cwd=str(tmp_path), transcript_path=str(transcript))


def test_quit_remains_bookmarked_beyond_desktop_delay(tmp_path, context, binding):
    registry = Registry(tmp_path)
    registered = registry.remember(context, binding)
    registry.ended(context, binding["session_id"])
    assert registry.lookup(context) == (registered, [])
    store = Store(tmp_path / "desktop", {"restore_delay_seconds": 300, "history_seconds": 600})
    for when in [0, 600, 1200]:
        bookmark, warnings = registry.lookup(context)
        store.observe({"workspaces": [{"name": "1", "windows": [{"command": ["kitty"], "agent_session": bookmark}]}]},
                      "login-a", timestamp=when, elapsed=when)
    saved, _ = store.select("login-b")
    assert saved["workspaces"][0]["windows"][0]["agent_session"] == registered


def test_same_directory_terminals_remain_distinct(tmp_path, context, binding):
    registry = Registry(tmp_path)
    first = registry.remember(context, binding)
    other_context = dict(context, shell_pid=20, window_id="124")
    other = dict(binding, session_id=str(uuid.uuid4()))
    other["transcript_path"] = str(Path(binding["transcript_path"]).with_name(other["session_id"] + ".jsonl"))
    second = registry.remember(other_context, other)
    assert registry.lookup(context)[0] == first
    assert registry.lookup(other_context)[0] == second
    assert first["session_id"] != second["session_id"]


def test_new_unconfirmed_launch_never_uses_previous_bookmark(tmp_path, context, binding):
    registry = Registry(tmp_path)
    registry.remember(context, binding)
    registry.begin(context, "claude", binding["config_home"], 200, "250")
    assert registry.lookup(context)[0] is None
    assert registry.lookup(context)[1]
    assert registry.remember(context, binding, owner_pid=199, owner_start="249") is None
    assert registry.lookup(context)[0] is None


def test_late_end_cannot_change_new_session(tmp_path, context, binding):
    registry = Registry(tmp_path)
    first = registry.remember(context, binding)
    second_binding = dict(binding, session_id=str(uuid.uuid4()))
    second_binding["transcript_path"] = str(Path(binding["transcript_path"]).with_name(second_binding["session_id"] + ".jsonl"))
    second = registry.remember(context, second_binding)
    registry.ended(context, first["session_id"], switched=True)
    assert registry.lookup(context) == (second, [])
    assert first["session_id"] == binding["session_id"]


def test_forget_revokes_existing_snapshots_and_late_hooks(tmp_path, context, binding):
    registry = Registry(tmp_path)
    old = copy.deepcopy(registry.remember(context, binding))
    assert registry.forget(context)
    assert registry.revoked(old)
    assert registry.remember(context, binding) is None
    registry.ended(context, binding["session_id"])
    assert registry.lookup(context) == (None, [])
    registry.begin(context, "claude", binding["config_home"], 200, "250")
    new = registry.remember(context, binding, owner_pid=200, owner_start="250")
    assert not registry.revoked(new)
    assert new["binding_id"] != old["binding_id"]


def test_forget_also_revokes_older_invocations_in_delayed_snapshots(tmp_path, context, binding):
    registry = Registry(tmp_path)
    old = registry.remember(context, binding)
    registry.begin(context, "claude", binding["config_home"], 200, "250")
    new = registry.remember(context, binding, owner_pid=200, owner_start="250")
    assert new["binding_id"] != old["binding_id"]
    assert registry.forget(context)
    assert registry.revoked(old) and registry.revoked(new)


def test_late_end_from_old_invocation_cannot_hide_resumed_same_session(tmp_path, context, binding):
    registry = Registry(tmp_path)
    registry.begin(context, "claude", binding["config_home"], 200, "250")
    saved = registry.remember(context, binding, owner_pid=200, owner_start="250")
    registry.ended(context, binding["session_id"], switched=True, owner_pid=199, owner_start="249")
    assert registry.lookup(context) == (saved, [])


def test_unsupported_launch_suppresses_old_bookmark_even_after_exit(tmp_path, context, binding, monkeypatch):
    from i3_session import agent_process
    registry = Registry(tmp_path)
    registry.remember(context, binding)
    monkeypatch.setattr(agent_process, "terminal_context", lambda _pid: context)
    monkeypatch.setattr(agent_process, "process_start", lambda _pid: "250")
    calls = []
    monkeypatch.setattr(os, "execvpe", lambda *args: calls.append(args))
    agent_launch.launch(tmp_path, "codex", ["codex", "resume", "--remote", "unix://server"])
    assert calls[0][1] == ["codex", "resume", "--remote", "unix://server"]
    assert calls[0][2]["I3_SESSION_STATE_DIR"] == str(tmp_path)
    monkeypatch.setattr(agent_process, "discover_window", lambda *_: {"context": context, "warnings": [], "binding": None})
    saved, warnings = agent_launch.capture_agent(tmp_path, context["kitty_pid"], context["window_id"])
    assert saved is None and "Remote Codex" in warnings[0]


def test_state_environment_routes_shell_wrappers_and_native_hooks(tmp_path, monkeypatch):
    from i3_session.cli import parser
    monkeypatch.setenv("I3_SESSION_STATE_DIR", str(tmp_path))
    assert parser().parse_args(["agent-hook", "--tool", "claude"]).state_dir == tmp_path


@pytest.mark.parametrize("key,value", [("boot_id", "another-boot"), ("shell_start", "999"), ("kitty_start", "999")])
def test_reused_ids_never_reuse_bookmark(tmp_path, context, binding, key, value):
    registry = Registry(tmp_path)
    registry.remember(context, binding)
    assert registry.lookup(dict(context, **{key: value})) == (None, [])


def test_registry_is_private_and_contains_no_transcripts(tmp_path, context, binding):
    registry = Registry(tmp_path)
    registry.remember(context, binding)
    assert registry.path.stat().st_mode & 0o777 == 0o600
    assert "already saved" not in registry.path.read_text()


def test_broken_registry_keeps_ordinary_terminal_restorable(tmp_path, monkeypatch):
    from i3_session import apps
    registry = Registry(tmp_path)
    registry.path.write_text("11")
    monkeypatch.setattr(apps, "_window_pid", lambda _node: 10)
    monkeypatch.setattr(apps, "_kitty_cwd", lambda *_: (str(tmp_path), []))
    result = apps.capture_window({"window": 123, "window_properties": {"class": "kitty", "instance": "kitty"}},
                                 {"_state_dir": str(tmp_path)})
    assert result["command"] == ["kitty", "--directory", str(tmp_path)]
    assert "agent_session" not in result
    assert "Agent tracking unavailable" in result["warnings"][0]


@pytest.mark.parametrize("tool,args,expected", [
    ("codex", ["-p", "exec", "-c", 'key="review"', "resume", str(uuid.uuid4())], True),
    ("codex", ["-p", "auto", "exec", "prompt"], False),
    ("codex", ["resume", "--remote", "unix://"], False),
    ("codex", ["--remote=unix://", "resume"], False),
    ("codex", ["--help"], False),
    ("claude", ["--model", "agents", "--resume", str(uuid.uuid4())], True),
    ("claude", ["--print", "prompt"], False),
    ("claude", ["--model", "opus", "agents", "--json"], False),
    ("claude", ["--resume", str(uuid.uuid4()), "--bg"], False),
])
def test_only_interactive_invocations_are_bookmarked(tool, args, expected):
    assert agent_launch.interactive(tool, args) is expected


def test_resume_targets_exact_id_with_no_prompt_and_latest_native_file(tmp_path, context, binding, monkeypatch):
    registered = Registry(tmp_path).remember(context, binding)
    original = copy.deepcopy(registered)
    with Path(binding["transcript_path"]).open("a") as stream:
        stream.write('{"message":"later final turn"}\n')
    calls = []
    monkeypatch.chdir(tmp_path)
    agent_launch.resume(tmp_path, registered, run=lambda command, **kw: calls.append((command, kw)) or 0, shell=lambda: None)
    command, options = calls[0]
    assert command[-2:] == ["claude", binding["session_id"]]
    assert "--resume" in command[2]
    assert "--continue" not in command[2] and "--last" not in command[2]
    assert options["env"]["CLAUDE_CONFIG_DIR"] == binding["config_home"]
    assert options["env"]["I3_SESSION_STATE_DIR"] == str(tmp_path)
    assert registered == original
    assert "later final turn" in Path(binding["transcript_path"]).read_text()


@pytest.mark.parametrize("failure", ["missing", "revoked", "wrong-account"])
def test_resume_failure_leaves_shell_without_starting_different_session(tmp_path, context, binding, failure, capsys):
    registry = Registry(tmp_path)
    registered = registry.remember(context, binding)
    if failure == "missing":
        Path(binding["transcript_path"]).unlink()
    elif failure == "revoked":
        registry.forget(context)
    else:
        registered.update(tool="codex", launcher="codex-academic")
    shells = []
    agent_launch.resume(tmp_path, registered, run=lambda *_args, **_kw: pytest.fail("native process started"), shell=lambda: shells.append(True))
    assert shells == [True]
    assert "left this shell open" in capsys.readouterr().err


@pytest.mark.parametrize("launcher", ["codex", "codex-academic"])
def test_account_launcher_is_preserved_in_resume_argv(tmp_path, binding, launcher):
    binding.update(tool="codex", launcher=launcher)
    binding["transcript_path"] = str(Path(binding["config_home"]) / "sessions" / (binding["session_id"] + ".jsonl"))
    assert agent_launch.resume_command(binding)[-2:] == [launcher, binding["session_id"]]
