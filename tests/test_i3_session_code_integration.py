"""Optional real VS Code check on a disposable X server and editor profile.

Run with I3_SESSION_TEST_CODE=1 in the i3-session test environment. The user's
display, Code settings, extensions, and application profile are never used.
"""

import json
import os
import shutil
import subprocess

import psutil
import pytest

from test_i3_session_desktop import eventually, isolated_i3
from i3_session import apps, desktop
from i3_session.install import DEFAULT_TITLE, TITLE_MARKERS


@pytest.mark.skipif(os.environ.get("I3_SESSION_TEST_CODE") != "1", reason="Opt in to isolated real-Code test with I3_SESSION_TEST_CODE=1")
def test_real_code_captures_folder_and_restores_on_isolated_display(isolated_i3):
    executable = shutil.which("code")
    if not executable:
        pytest.skip("VS Code is unavailable")
    client, _, _, _, path = isolated_i3
    # The fixture has already replaced DISPLAY and I3SOCK with its private server.
    assert os.environ["I3SOCK"] == str(path / "i3.sock")
    assert os.environ["DISPLAY"] != ":0"
    project = path / "project with spaces"
    project.mkdir()
    profile = path / "code-profile"
    (profile / "User").mkdir(parents=True)
    (profile / "User/settings.json").write_text(json.dumps({
        "window.title": DEFAULT_TITLE + " " + " ".join(TITLE_MARKERS),
        "telemetry.telemetryLevel": "off",
        "workbench.startupEditor": "none",
        "window.restoreWindows": "none",
        "update.mode": "none",
        "extensions.autoCheckUpdates": False,
        "extensions.autoUpdate": False,
    }))
    extensions = path / "extensions"
    extensions.mkdir()
    test_config_root = path / "app-environment"
    test_config_root.mkdir()
    environment = dict(os.environ, XDG_CONFIG_HOME=str(test_config_root / ".config"),
                       XDG_CACHE_HOME=str(test_config_root / ".cache"), XDG_DATA_HOME=str(test_config_root / ".local/share"))
    for key in list(environment):
        if key.startswith("VSCODE_") or key in {"ELECTRON_RUN_AS_NODE", "NODE_OPTIONS"}:
            environment.pop(key)
    base_command = [executable, "--user-data-dir", str(profile), "--extensions-dir", str(extensions),
                    "--disable-extensions", "--disable-gpu", "--disable-workspace-trust", "--wait", "--new-window"]
    tracked = {}
    launchers = []
    log = (path / "code.log").open("w")

    def remember_children():
        for launcher in launchers:
            if launcher.poll() is not None:
                continue
            try:
                root = psutil.Process(launcher.pid)
                for process in [root, *root.children(recursive=True)]:
                    tracked[(process.pid, process.create_time())] = process
            except psutil.Error:
                pass

    def launch(command, **kwargs):
        assert str(profile) in command and str(extensions) in command
        kwargs.update(env=environment, stdout=log, stderr=log, start_new_session=True)
        process = subprocess.Popen(command, **kwargs)
        launchers.append(process)
        remember_children()
        return process

    def code_window_with_folder():
        remember_children()
        for node in desktop._windows(client.query("get_tree")):
            if (node.get("window_properties", {}).get("class", "").casefold() == "code"
                    and apps.capture_window(node, {})["cwd"] == str(project)):
                return node
        return None

    try:
        client.command(desktop._workspace_command("7: Code integration"))
        launch([*base_command, str(project)])
        original = eventually(code_window_with_folder, timeout=45)
        recipe = apps.capture_window(original, {})
        assert recipe["command"] == ["code", "--new-window", str(project)]
        assert recipe["warnings"] == []
        snapshot = desktop.capture_all({}, ipc=client)
        assert len(snapshot["workspaces"]) == 1
        assert len(snapshot["workspaces"][0]["windows"]) == 1
        saved = snapshot["workspaces"][0]["windows"][0]
        saved["command"] = [*base_command, str(project)]
        client.command(f'[con_id={original["id"]}] kill')
        eventually(lambda: not desktop._windows(client.query("get_tree")))
        # Let Code's previous main process exit before relaunching that profile.
        eventually(lambda: all(process.poll() is not None for process in launchers), timeout=10)
        report = desktop.restore(snapshot, {
            "_state_dir": str(path / "state"), "restore_timeout_seconds": 45,
            "restore_poll_seconds": 0.05, "restore_settle_seconds": 0.4,
        }, ipc=client, launch=launch)
        assert report["errors"] == []
        assert len(report["restored"]) == 1
        restored = eventually(code_window_with_folder, timeout=15)
        assert restored["rect"] == original["rect"]
        assert apps.capture_window(restored, {})["command"][-1] == str(project)
        assert not any(node.get("swallows") for node in desktop._windows(client.query("get_tree")))
    finally:
        remember_children()
        # Only touch processes recorded beneath our own --wait CLI launchers;
        # psutil's identity checks protect against PID reuse.
        processes = list(tracked.values())
        for process in reversed(processes):
            try:
                process.terminate()
            except psutil.Error:
                pass
        _, alive = psutil.wait_procs(processes, timeout=3)
        for process in alive:
            try:
                process.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(alive, timeout=3)
        for launcher in launchers:
            try:
                launcher.wait(timeout=3)
            except subprocess.TimeoutExpired:
                launcher.kill()
                launcher.wait(timeout=3)
        log.close()
