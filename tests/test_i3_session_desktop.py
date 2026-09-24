"""Backend checks, including real i3 on an isolated Xvfb display."""

import copy
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".scripts"))
from i3_session import desktop


def eventually(function, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = function()
        if value:
            return value
        time.sleep(0.03)
    raise AssertionError("Timed out waiting for isolated i3")


WINDOW_PROGRAM = r'''
import sys
from Xlib import X, Xatom, display
d = display.Display()
s = d.screen()
w = s.root.create_window(0, 0, 320, 220, 0, s.root_depth,
                         X.InputOutput, X.CopyFromParent,
                         background_pixel=s.white_pixel,
                         event_mask=X.StructureNotifyMask)
w.set_wm_name(sys.argv[1])
w.set_wm_class("i3-session-fixture", "I3SessionFixture")
w.change_property(d.intern_atom("_NET_WM_WINDOW_TYPE"), Xatom.ATOM, 32,
                  [d.intern_atom("_NET_WM_WINDOW_TYPE_NORMAL")])
w.map()
d.flush()
while True:
    d.next_event()
'''


@pytest.fixture
def isolated_i3(tmp_path, monkeypatch):
    if not all(shutil.which(command) for command in ("Xvfb", "i3", "i3-msg")):
        pytest.skip("Xvfb/i3 are required for the isolated integration test")
    if not importlib.util.find_spec("Xlib") or not importlib.util.find_spec("i3_resurrect"):
        pytest.skip("i3-session runtime dependencies are required")
    read_fd, write_fd = os.pipe()
    log = (tmp_path / "x11.log").open("w")
    xvfb = subprocess.Popen(
        ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "1024x768x24", "-nolisten", "tcp"],
        pass_fds=(write_fd,), stdout=log, stderr=log,
    )
    os.close(write_fd)
    with os.fdopen(read_fd) as stream:
        display_number = stream.readline().strip()
    assert display_number.isdecimal()
    monkeypatch.setenv("DISPLAY", ":" + display_number)
    socket_path = tmp_path / "i3.sock"
    monkeypatch.setenv("I3SOCK", str(socket_path))
    config = tmp_path / "i3.config"
    config.write_text(f'font pango:monospace 8\nfocus_follows_mouse no\nipc-socket {socket_path}\n')
    i3 = subprocess.Popen(["i3", "-a", "-c", str(config), "--shmlog-size", "0"], stdout=log, stderr=log)
    processes = []
    try:
        eventually(socket_path.exists)
        client = desktop.I3()
        program = tmp_path / "window.py"
        program.write_text(WINDOW_PROGRAM)

        def launch(command, **kwargs):
            process = subprocess.Popen(command, **kwargs)
            processes.append(process)
            return process

        def open_window(title="old title"):
            before = {node["window"] for node in desktop._windows(client.query("get_tree"))}
            launch([sys.executable, str(program), title], stdout=log, stderr=log)
            return eventually(lambda: next((node for node in desktop._windows(client.query("get_tree"))
                                             if node["window"] not in before), None))

        def capture_window(node, config):
            return {"command": [sys.executable, str(program), 'fresh title; $(literal) "quoted"'],
                    "cwd": str(tmp_path), "app": "fixture", "warnings": []}

        yield client, open_window, capture_window, launch, tmp_path
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in [*processes, i3, xvfb]:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        log.close()


def _close_fixture_windows(client):
    client.command('[class="^I3SessionFixture$"] kill')
    eventually(lambda: not any(node.get("window_properties", {}).get("class") == "I3SessionFixture"
                               for node in desktop._windows(client.query("get_tree"))))


def _config(path, **updates):
    return {"_state_dir": str(path), "restore_timeout_seconds": 3,
            "restore_settle_seconds": 0.08, "restore_poll_seconds": 0.02, **updates}


def test_i3_quote_escapes_syntax_and_rejects_controls():
    assert desktop.quote('a "quote"; \\ path') == '"a \\"quote\\"; \\\\ path"'
    with pytest.raises(desktop.DesktopError):
        desktop.quote("a\nworkspace 2")


def test_capture_retains_window_ids_without_mutating_input():
    node = {"id": 1, "type": "workspace", "name": "7", "nodes": [
        {"id": 2, "window": 99, "type": "con", "window_properties": {"class": "Firefox", "instance": "Navigator"}},
    ]}
    original = copy.deepcopy(node)

    class Client:
        def query(self, kind):
            return node if kind == "get_tree" else [{"name": "7", "output": "DP-1", "focused": True}]

    def build_layout(tree, criteria):
        assert criteria == ["class", "instance"]
        return {"type": "workspace", "nodes": [{"type": "con", "swallows": [{"class": "^Firefox$"}]}]}

    snapshot = desktop.capture_all({}, ipc=Client(), build_layout=build_layout,
                                   capture_window=lambda *_: {"command": ["firefox", "--new-window", "about:blank"]})
    assert node == original
    assert snapshot["focused_workspace"] == "7"
    assert snapshot["workspaces"][0]["layout"]["nodes"][0]["session_source_id"] == "99"
    assert snapshot["workspaces"][0]["windows"][0]["match"] == {"class": "Firefox", "instance": "Navigator"}


def test_serializer_does_not_import_upstream_cli_or_disk_config():
    if not importlib.util.find_spec("i3_resurrect"):
        pytest.skip("i3-session runtime dependencies are required")
    program = """
import sys
sys.path.insert(0, sys.argv[1])
from i3_session.desktop import _build_layout
assert _build_layout({'type': 'workspace'}, ['class']) == {'type': 'workspace'}
assert 'i3_resurrect.config' not in sys.modules
assert 'i3_resurrect.main' not in sys.modules
assert 'i3_resurrect.programs' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", program, str(Path(__file__).resolve().parents[1] / ".scripts")], check=True)


def test_real_i3_restores_identical_classes_layout_and_literal_arguments(isolated_i3):
    client, open_window, capture_window, launch, path = isolated_i3
    name = '7: docs; "quoted"'
    client.command(desktop._workspace_command(name))
    first = open_window("old browser one")
    open_window("old browser two")
    client.command(f'[con_id={first["id"]}] focus')
    client.command("split v")
    open_window("old browser three")
    before = {str(node["window"]): node["rect"] for node in desktop._windows(client.query("get_tree"))}
    snapshot = desktop.capture_all({}, ipc=client, capture_window=capture_window)
    assert len(snapshot["workspaces"][0]["windows"]) == 3
    _close_fixture_windows(client)
    report = desktop.restore(snapshot, _config(path), ipc=client, launch=launch)
    assert report["errors"] == []
    assert len(report["restored"]) == 3
    after = {node["window"]: node for node in desktop._windows(client.query("get_tree"))}
    for restored in report["restored"]:
        node = after[restored["window_id"]]
        assert node["rect"] == before[restored["source_id"]]
        assert node["name"] == 'fresh title; $(literal) "quoted"'
    assert not any(node.get("swallows") for node in after.values())
    assert name in desktop._workspaces(client.query("get_tree"))
    assert not list(path.glob("restore-*"))


def test_real_i3_refuses_occupied_target_and_maps_workspace(isolated_i3):
    client, open_window, capture_window, launch, path = isolated_i3
    client.command(desktop._workspace_command("7"))
    original = open_window()
    snapshot = desktop.capture_all({}, ipc=client, capture_window=capture_window)
    with pytest.raises(desktop.DesktopError, match="not empty"):
        desktop.restore(snapshot, _config(path), ipc=client, launch=launch)
    assert [node["window"] for node in desktop._windows(client.query("get_tree"))] == [original["window"]]
    report = desktop.restore(snapshot, _config(path, workspace_map={"7": "8"},
                                              output_map={snapshot["workspaces"][0]["output"]: "absent-output"}),
                             ipc=client, launch=launch)
    assert report["errors"] == []
    assert report["warnings"] and "unavailable" in report["warnings"][0]
    workspaces = desktop._workspaces(client.query("get_tree"))
    assert desktop._windows(workspaces["7"])[0]["window"] == original["window"]
    assert len(desktop._windows(workspaces["8"])) == 1


def test_real_i3_failed_launch_only_cleans_owned_placeholders(isolated_i3):
    client, open_window, capture_window, launch, path = isolated_i3
    client.command(desktop._workspace_command("7"))
    original = open_window()
    snapshot = desktop.capture_all({}, ipc=client, capture_window=capture_window)
    def disappeared_executable(*args, **kwargs):
        raise FileNotFoundError("Executable disappeared after successful preflight")

    report = desktop.restore(snapshot, _config(path, workspace_map={"7": "8"}), ipc=client, launch=disappeared_executable)
    assert report["errors"]
    windows = desktop._windows(client.query("get_tree"))
    assert [node["window"] for node in windows] == [original["window"]]
    assert not list(path.glob("restore-*"))


@pytest.mark.parametrize("problem", ["executable", "cwd"])
def test_real_i3_preflight_rejects_missing_paths_before_changing_workspace(isolated_i3, problem):
    client, open_window, capture_window, launch, path = isolated_i3
    client.command(desktop._workspace_command("7"))
    original = open_window()
    snapshot = desktop.capture_all({}, ipc=client, capture_window=capture_window)
    window = snapshot["workspaces"][0]["windows"][0]
    if problem == "executable":
        window["command"] = [str(path / "missing-executable")]
    else:
        window["cwd"] = str(path / "missing-directory")
    with pytest.raises(desktop.DesktopError):
        desktop.restore(snapshot, _config(path, workspace_map={"7": "8"}), ipc=client, launch=launch)
    assert "8" not in desktop._workspaces(client.query("get_tree"))
    assert [node["window"] for node in desktop._windows(client.query("get_tree"))] == [original["window"]]


def test_real_i3_timeout_does_not_adopt_preexisting_same_class_window(isolated_i3):
    client, open_window, capture_window, launch, path = isolated_i3
    client.command(desktop._workspace_command("7"))
    original = open_window()
    snapshot = desktop.capture_all({}, ipc=client, capture_window=capture_window)
    snapshot["workspaces"][0]["windows"][0]["command"] = [sys.executable, "-c", "pass"]
    report = desktop.restore(snapshot, _config(path, workspace_map={"7": "8"}, restore_timeout_seconds=0.15),
                             ipc=client, launch=launch)
    assert report["errors"] and "No new matching window" in report["errors"][0]
    assert [node["window"] for node in desktop._windows(client.query("get_tree"))] == [original["window"]]


def test_real_i3_ambiguous_launch_leaves_new_windows_open(isolated_i3):
    client, open_window, capture_window, launch, path = isolated_i3
    client.command(desktop._workspace_command("7"))
    original = open_window()
    snapshot = desktop.capture_all({}, ipc=client, capture_window=capture_window)

    def launch_two(command, **kwargs):
        first = launch(command, **kwargs)
        launch(command, **kwargs)
        eventually(lambda: len([node for node in desktop._windows(client.query("get_tree"))
                                 if desktop._normal_window(node)]) == 3)
        return first

    report = desktop.restore(snapshot, _config(path, workspace_map={"7": "8"}), ipc=client, launch=launch_two)
    assert report["errors"] and "Several new windows" in report["errors"][0]
    windows = desktop._windows(client.query("get_tree"))
    assert len(windows) == 3
    assert original["window"] in [node["window"] for node in windows]
    assert all(not node.get("swallows") for node in windows)


@pytest.mark.parametrize("layout", ["splitv", "tabbed", "stacking"])
def test_real_i3_workspace_layout_and_focus_roundtrip(isolated_i3, layout):
    client, open_window, capture_window, launch, path = isolated_i3
    client.command(desktop._workspace_command("7"))
    first = open_window()
    open_window()
    client.command(f"layout {layout}")
    client.command(f'[con_id={first["id"]}] focus')
    snapshot = desktop.capture_all({}, ipc=client, capture_window=capture_window)
    _close_fixture_windows(client)
    report = desktop.restore(snapshot, _config(path), ipc=client, launch=launch)
    assert report["errors"] == []
    workspace = desktop._workspaces(client.query("get_tree"))["7"]
    assert workspace["layout"] == snapshot["workspaces"][0]["layout"]["layout"]
    mapping = {entry["source_id"]: entry["window_id"] for entry in report["restored"]}
    focused = next(node for node in desktop._windows(workspace) if node.get("focused"))
    assert focused["window"] == mapping[str(first["window"])]


def test_real_i3_unsupported_window_is_skipped_without_empty_placeholders(isolated_i3):
    client, open_window, capture_window, launch, path = isolated_i3
    client.command(desktop._workspace_command("7"))
    open_window()
    open_window()
    snapshot = desktop.capture_all({}, ipc=client, capture_window=capture_window)
    snapshot["workspaces"][0]["windows"][0]["command"] = None
    _close_fixture_windows(client)
    report = desktop.restore(snapshot, _config(path), ipc=client, launch=launch)
    assert report["errors"] == []
    assert len(report["restored"]) == len(report["skipped"]) == 1
    windows = desktop._windows(client.query("get_tree"))
    assert len(windows) == 1
    assert not windows[0].get("swallows")


@pytest.mark.parametrize("native_count", [1, 2])
def test_real_i3_browser_windows_reused_across_workspaces(isolated_i3, native_count):
    client, open_window, capture_window, launch, path = isolated_i3
    client.command(desktop._workspace_command("7"))
    open_window()
    client.command(desktop._workspace_command("8"))
    open_window()
    snapshot = desktop.capture_all({}, ipc=client, capture_window=capture_window)
    for workspace in snapshot["workspaces"]:
        window = workspace["windows"][0]
        window["reuse_new_windows"] = True
        window["cold_command"] = [*window["command"][:-1], "native-cold"]
    _close_fixture_windows(client)
    calls = []

    def browser_launch(command, **kwargs):
        calls.append(command)
        before = len([node for node in desktop._windows(client.query("get_tree"))
                      if desktop._normal_window(node)])
        count = native_count if command[-1] == "native-cold" else 1
        processes = [launch(command, **kwargs) for _ in range(count)]
        eventually(lambda: len([node for node in desktop._windows(client.query("get_tree"))
                                 if desktop._normal_window(node)]) == before + count)
        return processes[0]

    report = desktop.restore(snapshot, _config(path, browser_settle_seconds=0.05),
                             ipc=client, launch=browser_launch)
    assert report["errors"] == []
    assert len(report["restored"]) == 2
    assert len(calls) == 3 - native_count
    assert calls[0][-1] == "native-cold"
    if native_count == 1:
        assert calls[1][-1] != "native-cold"
    current = desktop._workspaces(client.query("get_tree"))
    assert len(desktop._windows(current["7"])) == len(desktop._windows(current["8"])) == 1


def test_real_i3_floating_and_fullscreen_restore(isolated_i3):
    client, open_window, capture_window, launch, path = isolated_i3
    client.command(desktop._workspace_command("7"))
    floating = open_window()
    client.command(f'[con_id={floating["id"]}] floating enable')
    client.command(f'[con_id={floating["id"]}] border none')
    client.command(f'[con_id={floating["id"]}] resize set 410 px 250 px')
    client.command(f'[con_id={floating["id"]}] move position 90 px 110 px')
    fullscreen = open_window()
    client.command(f'[con_id={fullscreen["id"]}] fullscreen enable')
    snapshot = desktop.capture_all({}, ipc=client, capture_window=capture_window)
    old_floating = next(node for node in desktop._windows(client.query("get_tree")) if node["window"] == floating["window"])
    _close_fixture_windows(client)
    report = desktop.restore(snapshot, _config(path), ipc=client, launch=launch)
    assert report["errors"] == []
    after = {node["window"]: node for node in desktop._windows(client.query("get_tree"))}
    mapping = {entry["source_id"]: entry["window_id"] for entry in report["restored"]}
    restored_floating = after[mapping[str(floating["window"])]]
    assert restored_floating["floating"] in ("user_on", "auto_on")
    assert restored_floating["border"] == "none"
    assert restored_floating["rect"] == old_floating["rect"]
    assert after[mapping[str(fullscreen["window"])]]['fullscreen_mode'] == 1
