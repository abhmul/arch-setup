"""Opt-in real-browser checks on private Xvfb, D-Bus and throwaway profiles.

Run with I3_SESSION_BROWSER_TESTS=1; ordinary pytest never starts browsers.
"""

import json
import os
import signal
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

import pytest

from test_i3_session_desktop import isolated_i3, eventually
from i3_session import desktop


pytestmark = pytest.mark.skipif(os.environ.get("I3_SESSION_BROWSER_TESTS") != "1",
                                reason="real-browser integration checks require explicit opt-in")


@pytest.fixture
def browser_environment(isolated_i3, monkeypatch):
    client, _, _, _, path = isolated_i3
    log = (path / "browser.log").open("w")
    bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                           stdout=subprocess.PIPE, stderr=log, text=True)
    address = bus.stdout.readline().strip()
    assert address.startswith("unix:")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
    monkeypatch.setenv("NO_AT_BRIDGE", "1")
    monkeypatch.delenv("SESSION_MANAGER", raising=False)
    for variable, leaf in (("XDG_CACHE_HOME", "cache"), ("XDG_CONFIG_HOME", "config"),
                           ("XDG_DATA_HOME", "data")):
        target = path / leaf
        target.mkdir()
        monkeypatch.setenv(variable, str(target))
    processes = []

    def launch(command, **kwargs):
        # Only these test-local flags differ from the saved Chromium recipe.
        # Profile selection, blank-window arguments and identity are unchanged.
        if "chromium" in command[0]:
            command = [command[0], "--no-first-run", "--no-default-browser-check",
                       "--disable-gpu", "--disable-background-networking",
                       "--password-store=basic", *command[1:]]
        kwargs.update(stdout=log, stderr=log, start_new_session=True)
        process = subprocess.Popen(command, **kwargs)
        processes.append(process)
        return process

    try:
        yield client, path, launch, processes
    finally:
        # Each browser has a process group created by this fixture. Never match
        # or signal global browser names, user profiles or the user's X display.
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
        bus.terminate()
        bus.wait(timeout=3)
        bus.stdout.close()
        log.close()


def windows(client):
    return [node for node in desktop._windows(client.query("get_tree")) if desktop._normal_window(node)]


def firefox_profile(path, restore_previous=False):
    profile = path / "firefox-profile"
    profile.mkdir()
    prefs = {
        "browser.shell.checkDefaultBrowser": "false",
        "browser.startup.homepage": '"about:blank"',
        "browser.startup.homepage_override.mstone": '"ignore"',
        "browser.aboutwelcome.enabled": "false",
        "datareporting.policy.dataSubmissionEnabled": "false",
        "browser.tabs.warnOnClose": "false",
        "browser.warnOnQuit": "false",
        "browser.sessionstore.interval": "1000",
        "browser.startup.page": "3" if restore_previous else "1",
    }
    (profile / "user.js").write_text("\n".join(f'user_pref("{key}", {value});' for key, value in prefs.items()))
    return profile


@pytest.mark.parametrize("browser", ["firefox", "chromium"])
def test_real_browser_single_window_cold_restore(browser_environment, browser):
    client, path, launch, processes = browser_environment
    client.command(desktop._workspace_command("7"))
    if browser == "firefox":
        profile = firefox_profile(path)
        command = ["firefox", "--no-remote", "--profile", str(profile), "--new-window", "about:blank"]
    else:
        profile = path / "chromium-profile"
        command = ["chromium", "--user-data-dir=" + str(profile), "--new-window", "about:blank"]
    process = launch(command)
    eventually(lambda: windows(client), timeout=25)
    time.sleep(0.5)
    snapshot = desktop.capture_all({}, ipc=client)
    assert len(snapshot["workspaces"]) == 1
    assert len(snapshot["workspaces"][0]["windows"]) == 1
    saved = snapshot["workspaces"][0]["windows"][0]
    assert any(str(profile) in arg for arg in saved["command"])
    before = windows(client)[0]["rect"]
    for node in windows(client):
        client.command(f'[con_id={node["id"]}] kill')
    eventually(lambda: not windows(client), timeout=15)
    eventually(lambda: process.poll() is not None, timeout=15)
    report = desktop.restore(snapshot, {"_state_dir": str(path), "restore_timeout_seconds": 25,
                                        "restore_poll_seconds": 0.05, "restore_settle_seconds": 1},
                             ipc=client, launch=launch)
    assert report["errors"] == []
    assert len(report["restored"]) == 1
    time.sleep(1)
    assert len(windows(client)) == 1
    assert windows(client)[0]["rect"] == before


def test_chromium_debug_endpoint_survives_cold_restore(browser_environment):
    client, path, launch, processes = browser_environment
    client.command(desktop._workspace_command("7"))
    profile = path / "chromium-debug-profile"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    expected_flags = {
        "--user-data-dir": str(profile),
        "--remote-debugging-port": str(port),
        "--remote-debugging-address": "127.0.0.1",
    }
    command = ["chromium", *(f"{flag}={value}" for flag, value in expected_flags.items()),
               "--new-window", "about:blank"]
    opener = build_opener(ProxyHandler({}))

    def endpoint_version():
        try:
            with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=0.5) as response:
                version = json.load(response)
            return version if version.get("webSocketDebuggerUrl") else None
        except (OSError, URLError, json.JSONDecodeError):
            return None

    def flag_value(argv, flag):
        for index, argument in enumerate(argv):
            if argument.startswith(flag + "="):
                return argument.split("=", 1)[1]
            if argument == flag and index + 1 < len(argv):
                return argv[index + 1]
        return None

    process = launch(command)
    eventually(lambda: len(windows(client)) == 1, timeout=25)
    original_version = eventually(endpoint_version, timeout=15)
    snapshot = desktop.capture_all({}, ipc=client)
    assert len(snapshot["workspaces"]) == 1
    assert len(snapshot["workspaces"][0]["windows"]) == 1
    saved = snapshot["workspaces"][0]["windows"][0]
    assert saved["warnings"] == []
    for recipe in ("command", "cold_command"):
        assert {flag: flag_value(saved[recipe], flag) for flag in expected_flags} == expected_flags
    old_rect = windows(client)[0]["rect"]
    for node in windows(client):
        client.command(f'[con_id={node["id"]}] kill')
    eventually(lambda: not windows(client), timeout=15)
    eventually(lambda: process.poll() is not None, timeout=15)
    eventually(lambda: endpoint_version() is None, timeout=15)

    report = desktop.restore(snapshot, {"_state_dir": str(path), "restore_timeout_seconds": 25,
                                        "restore_poll_seconds": 0.05, "browser_settle_seconds": 1},
                             ipc=client, launch=launch)
    assert report["errors"] == []
    assert len(report["restored"]) == 1
    restored_version = eventually(endpoint_version, timeout=15)
    assert restored_version["Browser"] == original_version["Browser"]
    assert restored_version["webSocketDebuggerUrl"] != original_version["webSocketDebuggerUrl"]
    assert {flag: flag_value(processes[-1].args, flag) for flag in expected_flags} == expected_flags
    assert len(windows(client)) == 1
    assert windows(client)[0]["rect"] == old_rect


@pytest.mark.parametrize("saved_slots", [2, 1])
def test_firefox_prior_session_reuses_new_windows_or_rejects_excess(browser_environment, saved_slots):
    client, path, launch, processes = browser_environment
    client.command(desktop._workspace_command("7"))
    profile = firefox_profile(path, restore_previous=True)
    process = launch(["firefox", "--no-remote", "--profile", str(profile),
                      "--new-window", "about:blank", "--new-window", "about:blank"])
    eventually(lambda: len(windows(client)) == 2, timeout=25)
    time.sleep(2)
    snapshot = desktop.capture_all({}, ipc=client)
    assert len(snapshot["workspaces"][0]["windows"]) == 2
    original_rects = {str(node["window"]): node["rect"] for node in windows(client)}
    if saved_slots == 1:
        snapshot["workspaces"][0]["windows"][1]["command"] = None
    # Abrupt application exit leaves the periodically written two-window
    # session to exercise Firefox's next-start recovery behavior.
    eventually(lambda: (profile / "sessionstore-backups/recovery.jsonlz4").exists(), timeout=15)
    process.terminate()
    eventually(lambda: process.poll() is not None, timeout=15)
    assert not windows(client)
    report = desktop.restore(snapshot, {"_state_dir": str(path), "restore_timeout_seconds": 25,
                                        "restore_poll_seconds": 0.05, "restore_settle_seconds": 1},
                             ipc=client, launch=launch)
    if saved_slots == 2:
        assert report["errors"] == []
        assert len(report["restored"]) == 2
        restored_windows = {node["window"]: node for node in windows(client)}
        for restored in report["restored"]:
            assert restored_windows[restored["window_id"]]["rect"] == original_rects[restored["source_id"]]
    else:
        assert report["restored"] == []
        assert report["errors"] == ["Browser opened more windows than saved layout slots; left them untouched."]
    time.sleep(1)
    count = len(windows(client))
    print(f"Firefox prior-session recovery produced {count} windows for {saved_slots} saved slots.")
    assert count == 2
    assert not any(node.get("swallows") for node in desktop._windows(client.query("get_tree")))
