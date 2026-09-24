"""Opt-in native Codex config API checks; no model or thread requests.

Run with I3_SESSION_TEST_CODEX_TRUST=1. CODEX_HOME selects disposable native
configuration namespaces; HOME and the user's actual agent settings stay intact.
"""

import json
import os
from pathlib import Path
import shutil
import sys
import tomllib

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".scripts"))
from i3_session import agent_install as installer


pytestmark = pytest.mark.skipif(
    os.environ.get("I3_SESSION_TEST_CODEX_TRUST") != "1",
    reason="set I3_SESSION_TEST_CODEX_TRUST=1 for isolated native trust checks",
)

BINARIES = (Path.home() / ".local/bin/codex", Path.home() / ".codex-academic/bin/codex")


def native_metadata(binary, namespace):
    with installer.AppServer(binary, namespace) as client:
        response = client.request("hooks/list", {"cwds": [str(namespace)]})
    assert all(not entry["errors"] for entry in response["data"])
    return [hook for entry in response["data"] for hook in entry["hooks"]
            if hook["sourcePath"] == str(namespace / "hooks.json")]


@pytest.mark.parametrize("binary", BINARIES, ids=("personal-native", "academic-native"))
def test_native_scoped_trust_shared_config_and_cross_version_reads(tmp_path, binary):
    if not shutil.which(str(binary)):
        pytest.skip(f"native binary unavailable: {binary}")
    personal, academic = tmp_path / "personal", tmp_path / "academic"
    personal.mkdir()
    academic.mkdir()
    config = personal / "config.toml"
    sentinel_hash = "sha256:" + "0" * 64
    config.write_text('model_reasoning_effort = "xhigh"\n[features]\nhooks = true\n'
                      '[hooks.state."unrelated-fixture-key"]\n'
                      f'trusted_hash = "{sentinel_hash}"\n')
    original_config = config.read_bytes()
    original_hooks = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": "/usr/bin/true", "timeout": 3},
    ]}]}}
    hooks = personal / "hooks.json"
    hooks.write_text(json.dumps(original_hooks))
    original_hooks_bytes = hooks.read_bytes()
    (academic / "config.toml").symlink_to(config)
    (academic / "hooks.json").symlink_to(hooks)
    sources = [namespace / "hooks.json" for namespace in (personal, academic)]
    backups = tmp_path / "backups"

    report = installer.configure_agent_hooks(
        codex_hooks=sources, backup_dir=backups,
        trust_installed_hooks=True, codex_binary=binary,
    )

    assert len(report["files"]) == 1
    assert [len(item["newly_trusted"]) for item in report["trust"]] == [3, 3]
    assert (academic / "config.toml").is_symlink()
    assert (academic / "hooks.json").is_symlink()
    saved = tomllib.loads(config.read_text())
    assert saved["model_reasoning_effort"] == "xhigh"
    assert saved["features"]["hooks"] is True
    assert saved["hooks"]["state"]["unrelated-fixture-key"]["trusted_hash"] == sentinel_hash
    assert len(saved["hooks"]["state"]) == 7
    assert json.loads(hooks.read_text())["hooks"]["PreToolUse"] == original_hooks["hooks"]["PreToolUse"]
    backup_bytes = [path.read_bytes() for path in backups.iterdir()]
    assert sorted(backup_bytes) == sorted([original_hooks_bytes, original_config])

    # Definitions approved by either installed version must remain trusted when
    # loaded using the actual binary used by the other account.
    for reader in BINARIES:
        if not shutil.which(str(reader)):
            continue
        for namespace in (personal, academic):
            metadata = native_metadata(reader, namespace)
            owned = [hook for hook in metadata if hook["command"] == installer.hook_command("codex")]
            unrelated = [hook for hook in metadata if hook["command"] == "/usr/bin/true"]
            assert len(owned) == 3
            assert all(hook["trustStatus"] == "trusted" for hook in owned)
            assert len(unrelated) == 1 and unrelated[0]["trustStatus"] == "untrusted"
            for hook in owned:
                assert saved["hooks"]["state"][hook["key"]]["trusted_hash"] == hook["currentHash"]

    installed_config, installed_hooks = config.read_bytes(), hooks.read_bytes()
    again = installer.configure_agent_hooks(
        codex_hooks=sources, backup_dir=backups,
        trust_installed_hooks=True, codex_binary=binary,
    )
    assert not again["files"][0]["changed"]
    assert all(not item["newly_trusted"] for item in again["trust"])
    assert config.read_bytes() == installed_config
    assert hooks.read_bytes() == installed_hooks
