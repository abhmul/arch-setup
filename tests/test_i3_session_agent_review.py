"""Regression checks for observations racing native hooks and transparent launch."""

import json
import os
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".scripts"))

from i3_session import agent_launch, agent_process, cli
from i3_session.agent_sessions import Registry


@pytest.fixture
def context():
    return {"boot_id": "test-boot", "kitty_pid": 10, "kitty_start": "100",
            "window_id": "123", "shell_pid": 11, "shell_start": "110",
            "kitty_window_id": "1"}


@pytest.fixture
def bindings(tmp_path):
    home = tmp_path / "claude-home"
    project = home / "projects" / "project"
    project.mkdir(parents=True)
    result = []
    for _ in range(2):
        identifier = str(uuid.uuid4())
        transcript = project / f"{identifier}.jsonl"
        transcript.write_text('{"message":"saved natively"}\n')
        result.append({"tool": "claude", "launcher": "claude", "config_home": str(home),
                       "session_id": identifier, "cwd": str(tmp_path), "transcript_path": str(transcript)})
    return result


def test_stale_capture_warning_cannot_hide_hook_confirmation_after_tui_quits(tmp_path, context, bindings, monkeypatch):
    registry = Registry(tmp_path)
    registry.begin(context, "claude", bindings[0]["config_home"], 200, "250")
    confirmed = []

    def discover_then_hook(*_):
        # Discovery observed startup before native metadata existed. The native
        # hook publishes the exact ID before that observation reaches storage.
        confirmed.append(registry.remember(context, bindings[0], owner_pid=200, owner_start="250"))
        return {"context": context, "binding": None, "warnings": ["Stale startup observation"]}

    monkeypatch.setattr(agent_process, "discover_window", discover_then_hook)
    agent_launch.capture_agent(tmp_path, 10, "123")
    assert registry.lookup(context) == (confirmed[0], [])

    # The TUI has now quit. No later process observation can repair a warning
    # that accidentally overwrote the successful hook, so this must still work.
    monkeypatch.setattr(agent_process, "discover_window", lambda *_: {"context": context, "binding": None, "warnings": []})
    assert agent_launch.capture_agent(tmp_path, 10, "123") == (confirmed[0], [])


def test_stale_capture_binding_cannot_undo_hook_session_switch_in_same_process(tmp_path, context, bindings, monkeypatch):
    registry = Registry(tmp_path)
    registry.begin(context, "claude", bindings[0]["config_home"], 200, "250")
    registry.remember(context, bindings[0], owner_pid=200, owner_start="250")
    switched = []

    def discover_then_switch(*_):
        # PID/start remains identical across an in-TUI session switch. Owner
        # checks alone cannot distinguish this obsolete observation from B.
        switched.append(registry.remember(context, bindings[1], owner_pid=200, owner_start="250"))
        return {"context": context, "pid": 200, "warnings": [],
                "binding": dict(bindings[0], agent_pid=200, agent_start="250")}

    monkeypatch.setattr(agent_process, "discover_window", discover_then_switch)
    agent_launch.capture_agent(tmp_path, 10, "123")
    assert registry.lookup(context) == (switched[0], [])
    monkeypatch.setattr(agent_process, "discover_window", lambda *_: {"context": context, "binding": None, "warnings": []})
    assert agent_launch.capture_agent(tmp_path, 10, "123") == (switched[0], [])


@pytest.mark.parametrize("stale_pid,stale_start", [(199, "249"), (200, "249")])
def test_mismatched_owner_is_rejected_even_after_recorded_owner_exits(tmp_path, context, bindings, monkeypatch, stale_pid, stale_start):
    registry = Registry(tmp_path)
    registry.begin(context, "claude", bindings[0]["config_home"], 200, "250")
    latest = registry.remember(context, bindings[0], owner_pid=200, owner_start="250")
    monkeypatch.setattr(agent_process, "process_start", lambda *_: None)

    # A delayed event must not become acceptable merely because the newer
    # invocation ended, including when a PID was reused with a new start time.
    assert registry.remember(context, bindings[1], owner_pid=stale_pid, owner_start=stale_start) is None
    assert registry.lookup(context) == (latest, [])


class ExecIntercept(BaseException):
    """Intercept exec without reaching any real agent or interactive shell."""


@pytest.mark.parametrize("operation", ["agent-launch", "agent-resume"])
def test_cli_preserves_caller_umask_at_native_exec(tmp_path, context, bindings, monkeypatch, operation):
    observed = []

    def intercept_exec(executable, argv, environment):
        current_mask = os.umask(0)
        os.umask(current_mask)
        observed.append((current_mask, executable, argv, environment))
        raise ExecIntercept

    monkeypatch.setattr(agent_launch.os, "execvpe", intercept_exec)
    monkeypatch.setattr(agent_process, "terminal_context", lambda *_: context)
    monkeypatch.setattr(agent_process, "process_start", lambda *_: "250")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", bindings[0]["config_home"])
    monkeypatch.chdir(tmp_path)
    arguments = ["--state-dir", str(tmp_path / "state"), operation]
    if operation == "agent-launch":
        arguments.extend(["--launcher", "claude", "--", "/nonexistent/test/claude"])
    else:
        arguments.extend(["--binding", json.dumps(bindings[0])])

    original_mask = os.umask(0o027)
    try:
        with pytest.raises(ExecIntercept):
            cli.main(arguments)
        assert observed[0][0] == 0o027
        if operation == "agent-launch":
            # Native launch transparency does not weaken registry privacy.
            assert (tmp_path / "state" / "agents.json").stat().st_mode & 0o777 == 0o600
    finally:
        os.umask(original_mask)


def test_valid_codex_transcript_cannot_resume_through_wrong_account_launcher(tmp_path, bindings, capsys):
    binding = dict(bindings[0], tool="codex", launcher="codex-academic")
    transcript = Path(binding["config_home"]) / "sessions" / f'{binding["session_id"]}.jsonl'
    transcript.parent.mkdir()
    transcript.write_text(json.dumps({"type": "session_meta", "payload": {
        "id": binding["session_id"], "source": "cli", "cwd": binding["cwd"],
    }}) + "\n")
    binding["transcript_path"] = str(transcript)
    shells = []

    def unexpected_resume(*_args, **_kwargs):
        pytest.fail("A valid session in a different account namespace was launched")

    agent_launch.resume(tmp_path, binding, run=unexpected_resume, shell=lambda: shells.append(True))
    assert shells == [True]
    assert "Saved Codex account does not match the configured launcher" in capsys.readouterr().err
