import copy
import json
import os
from pathlib import Path
import stat
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".scripts"))
from i3_session import agent_install as installer


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_additive_merge_preserves_settings_hooks_indices_and_idempotence():
    document = {"model": "existing-model", "env": {"EXAMPLE": "keep"}, "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "guard"}]}],
        "SessionStart": [{"matcher": "resume", "hooks": [{"type": "command", "command": "old"}]}],
    }}
    original = copy.deepcopy(document)
    merged, added = installer.merge_hooks(document, "codex")
    assert document == original
    assert added == list(installer.DEFAULT_EVENTS)
    assert merged["model"] == document["model"]
    assert merged["env"] == document["env"]
    assert merged["hooks"]["PreToolUse"] == document["hooks"]["PreToolUse"]
    assert merged["hooks"]["SessionStart"][0] == document["hooks"]["SessionStart"][0]
    assert merged["hooks"]["SessionStart"][1]["hooks"] == [{
        "type": "command", "command": installer.hook_command("codex"), "timeout": 3,
    }]
    assert installer.merge_hooks(merged, "codex") == (merged, [])


def test_preserves_existing_own_definition_without_overwriting():
    document = {"hooks": {"SessionStart": [{"matcher": "resume", "hooks": [{
        "type": "command", "command": installer.hook_command("claude"), "timeout": 7,
    }]}]}}
    result, added = installer.merge_hooks(document, "claude", events=["SessionStart"])
    assert result == document and added == []


def test_symlink_shared_file_written_once_and_first_backup_retained(tmp_path):
    source = tmp_path / "personal/hooks.json"
    alias = tmp_path / "academic/hooks.json"
    document = {"hooks": {"PermissionRequest": [{"hooks": [{"type": "command", "command": "approve"}]}]}}
    write_json(source, document)
    source.chmod(0o600)
    original = source.read_bytes()
    alias.parent.mkdir()
    alias.symlink_to(source)
    backups = tmp_path / "backups"
    result = installer.configure_agent_hooks(codex_hooks=[source, alias, source], backup_dir=backups)
    assert len(result["files"]) == 1
    assert result["files"][0]["sources"] == [str(source), str(alias)]
    assert result["trust_pending"] == [str(source), str(alias)]
    backup = Path(result["files"][0]["backup"])
    assert backup.read_bytes() == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE(backups.stat().st_mode) == 0o700
    assert alias.is_symlink() and alias.resolve() == source
    installed = source.read_bytes()
    again = installer.configure_agent_hooks(codex_hooks=[alias, source], backup_dir=backups)
    assert not again["files"][0]["changed"]
    assert source.read_bytes() == installed
    assert backup.read_bytes() == original
    assert len(list(backups.iterdir())) == 1


def test_invalid_second_file_preflight_preserves_first(tmp_path):
    first, second = tmp_path / "one.json", tmp_path / "two.json"
    write_json(first, {"kept": True})
    second.write_text("broken json")
    original = first.read_bytes()
    with pytest.raises(installer.InstallError, match="Invalid JSON"):
        installer.configure_agent_hooks(claude_settings=[first, second], backup_dir=tmp_path / "backups")
    assert first.read_bytes() == original
    assert not (tmp_path / "backups").exists()


def test_atomic_failure_retains_original_and_removes_temporary(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    write_json(settings, {"kept": True})
    original = settings.read_bytes()

    def fail_replace(*_):
        raise OSError("test rename failure")

    monkeypatch.setattr(installer.os, "replace", fail_replace)
    with pytest.raises(OSError, match="rename failure"):
        installer.configure_agent_hooks(claude_settings=[settings], backup_dir=tmp_path / "backups")
    assert settings.read_bytes() == original
    assert not list(tmp_path.glob(".settings.json.i3-session-*"))


def test_new_settings_private_and_optional_events(tmp_path):
    settings = tmp_path / "new/settings.json"
    result = installer.configure_agent_hooks(claude_settings=[settings], backup_dir=tmp_path / "backups",
                                             include_user_prompt=False, include_session_end=False)
    assert set(json.loads(settings.read_text())["hooks"]) == {"SessionStart"}
    assert stat.S_IMODE(settings.stat().st_mode) == 0o600
    assert result["files"][0]["backup"] is None


def metadata(source, *, command=None, event="sessionStart", index=0):
    return {
        "sourcePath": str(source), "command": command or installer.hook_command("codex"),
        "key": f"{source}:{installer.EVENT_NAMES[event]}:{index}:0", "eventName": event,
        "handlerType": "command", "source": "user", "isManaged": False, "enabled": True,
        "async": False, "matcher": None, "timeoutSec": installer.HOOK_TIMEOUT_SECONDS,
        "trustStatus": "untrusted", "currentHash": "sha256:" + "a" * 64,
    }


class FakeClient:
    def __init__(self, config_file, hooks):
        self.config_file = config_file
        self.hooks = hooks
        self.calls = []
        self.change_after_write = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def request(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))
        if method == "config/read":
            return {"layers": [{"name": {"type": "user", "file": str(self.config_file)}, "version": "v1"}]}
        if method == "hooks/list":
            return {"data": [{"hooks": copy.deepcopy(self.hooks), "errors": [], "warnings": []}]}
        assert method == "config/batchWrite"
        assert params["expectedVersion"] == "v1"
        assert params["filePath"] == str(self.config_file.resolve())
        edited = {edit["keyPath"] for edit in params["edits"]}
        for hook in self.hooks:
            path = "hooks.state." + json.dumps(hook["key"]) + ".trusted_hash"
            if path in edited:
                hook["trustStatus"] = "trusted"
                if self.change_after_write:
                    hook["currentHash"] = "sha256:" + "b" * 64
        return {"status": "ok", "filePath": str(self.config_file.resolve()), "version": "v2"}


def test_scoped_trust_uses_authoritative_hash_and_preserves_unrelated_trust(tmp_path):
    home = tmp_path / "personal"
    source = home / "hooks.json"
    own = metadata(source)
    unrelated = metadata(source, command="unrelated-command", index=1)
    other_source = metadata(tmp_path / "other/hooks.json")
    client = FakeClient(home / "config.toml", [own, unrelated, other_source])
    result = installer.trust_codex_hooks("codex", home, source, installer.hook_command("codex"),
                                         client_factory=lambda *_: client)
    assert result["newly_trusted"] == [own["key"]]
    edits = next(params["edits"] for method, params in client.calls if method == "config/batchWrite")
    assert edits == [{"keyPath": "hooks.state." + json.dumps(own["key"]) + ".trusted_hash",
                      "value": own["currentHash"], "mergeStrategy": "upsert"}]
    assert unrelated["trustStatus"] == other_source["trustStatus"] == "untrusted"


@pytest.mark.parametrize("changed", [
    {"currentHash": "invented"}, {"key": "some-other-source:session_start:0:0"},
    {"handlerType": "prompt"}, {"enabled": False}, {"isManaged": True},
    {"timeoutSec": 600}, {"async": True}, {"matcher": "startup"},
])
def test_unexpected_own_metadata_refuses_trust_write(tmp_path, changed):
    source = tmp_path / "hooks.json"
    own = metadata(source)
    own.update(changed)
    client = FakeClient(tmp_path / "config.toml", [own])
    with pytest.raises(installer.InstallError, match="differs"):
        installer.trust_codex_hooks("codex", tmp_path, source, installer.hook_command("codex"),
                                    client_factory=lambda *_: client)
    assert all(method != "config/batchWrite" for method, _ in client.calls)


def test_changed_hash_after_write_is_not_reported_verified(tmp_path):
    source = tmp_path / "hooks.json"
    client = FakeClient(tmp_path / "config.toml", [metadata(source)])
    client.change_after_write = True
    with pytest.raises(installer.InstallError, match="could not be verified"):
        installer.trust_codex_hooks("codex", tmp_path, source, installer.hook_command("codex"),
                                    client_factory=lambda *_: client)


def test_already_trusted_hooks_do_not_write_config(tmp_path):
    source = tmp_path / "hooks.json"
    own = metadata(source)
    own["trustStatus"] = "trusted"
    client = FakeClient(tmp_path / "config.toml", [own])
    result = installer.trust_codex_hooks("codex", tmp_path, source, installer.hook_command("codex"),
                                        client_factory=lambda *_: client)
    assert result["newly_trusted"] == []
    assert all(method != "config/batchWrite" for method, _ in client.calls)


def test_configure_preserves_personal_and_academic_trust_namespaces(tmp_path):
    personal, academic = tmp_path / "personal", tmp_path / "academic"
    write_json(personal / "hooks.json", {})
    (personal / "config.toml").write_text("# original trust config\n")
    academic.mkdir()
    (academic / "hooks.json").symlink_to(personal / "hooks.json")
    (academic / "config.toml").symlink_to(personal / "config.toml")
    calls = []

    def trust(binary, home, source, command):
        calls.append((home, source, command))
        return {"source": str(source)}

    backups = tmp_path / "backups"
    installer.configure_agent_hooks(codex_hooks=[personal / "hooks.json", academic / "hooks.json"],
                                     backup_dir=backups, trust_installed_hooks=True,
                                     codex_binary=sys.executable, trust_function=trust)
    assert [call[0] for call in calls] == [personal, academic]
    assert [call[1] for call in calls] == [personal / "hooks.json", academic / "hooks.json"]
    assert (academic / "config.toml").is_symlink()
    assert len(list(backups.iterdir())) == 2


def test_app_server_transport_only_uses_own_stdio_process(tmp_path):
    fake = tmp_path / "fake-codex"
    fake.write_text(f"#!{sys.executable}\n" + '''
import json, os, sys
for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    result = {} if message["method"] == "initialize" else {"home": os.environ["CODEX_HOME"], "echo": message["params"]}
    print(json.dumps({"method": "test/notification", "params": {}}), flush=True)
    print(json.dumps({"id": message["id"], "result": result}), flush=True)
''')
    fake.chmod(0o700)
    config_home = tmp_path / "account"
    with installer.AppServer(fake, config_home) as client:
        result = client.request("test/ping", {"hello": "world"})
    assert result == {"home": str(config_home), "echo": {"hello": "world"}}
    assert client.process.poll() == 0


def test_cli_repeatable_paths_and_no_automatic_trust(tmp_path, capsys):
    first, second = tmp_path / "one.json", tmp_path / "two.json"
    assert installer.main(["--claude-settings", str(first), "--claude-settings", str(second),
                           "--backup-dir", str(tmp_path / "backups")]) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["files"]) == 2
    assert report["trust"] == []
