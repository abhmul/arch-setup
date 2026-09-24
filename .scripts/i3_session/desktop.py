"""Capture i3 desktops and restore them without matching old window titles.

i3-resurrect supplies layout serialization. Restoration deliberately uses direct
i3 IPC and argv launches: its upstream restore routine unmaps existing windows.
"""

from __future__ import annotations

import copy
from functools import lru_cache
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import types
import uuid


class DesktopError(RuntimeError):
    """A capture or restore operation could not safely proceed."""


@lru_cache(maxsize=1)
def _serializer():
    """Load the pinned upstream serializer without its CLI import side effects.

    i3-resurrect 1.4.2's package initializer imports its CLI and creates a config
    under ~/.config at import time. Load the installed layout/treeutils modules
    in a private namespace instead, supplying an in-memory default config. This
    also avoids its unrelated, Python-3.12-incompatible programs/distutils path.
    No upstream source is copied or modified.
    """
    namespace = "_i3_session_resurrect"
    spec = importlib.util.find_spec("i3_resurrect")
    if spec is None or not spec.submodule_search_locations:
        raise DesktopError("i3-resurrect is missing; run ~/.scripts/install-i3-session.")
    package = types.ModuleType(namespace)
    package.__path__ = list(spec.submodule_search_locations)
    package.__package__ = namespace
    config = types.ModuleType(namespace + ".config")
    config.get = lambda _key, default: default
    package.config = config
    sys.modules[namespace] = package
    sys.modules[namespace + ".config"] = config
    return importlib.import_module(namespace + ".layout").build_layout


def _build_layout(tree, swallow):
    return _serializer()(tree, swallow)


class I3:
    """Small raw-JSON IPC client; inherits DISPLAY/I3SOCK from the caller."""

    def query(self, message_type):
        result = subprocess.run(
            ["i3-msg", "-t", message_type], check=True, capture_output=True,
            text=True, timeout=10,
        )
        return json.loads(result.stdout)

    def command(self, command):
        result = subprocess.run(
            ["i3-msg", "-t", "command", "--", command], check=True,
            capture_output=True, text=True, timeout=10,
        )
        replies = json.loads(result.stdout)
        failures = [reply.get("error", "i3 rejected command") for reply in replies
                    if not reply.get("success")]
        if failures:
            raise DesktopError("; ".join(failures))
        return replies


def quote(value):
    """Quote one i3 string argument, never a shell expression."""
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        raise DesktopError("i3 names must be strings without control characters")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def walk(node):
    yield node
    for key in ("nodes", "floating_nodes"):
        for child in node.get(key, []):
            yield from walk(child)


def _windows(tree):
    return [node for node in walk(tree) if node.get("window")]


def _workspaces(tree):
    return {node["name"]: node for node in walk(tree)
            if node.get("type") == "workspace"}


def _normal_window(node):
    props = node.get("window_properties") or {}
    window_type = node.get("window_type", props.get("window_type", "normal"))
    return bool(node.get("window") and not node.get("swallows") and not props.get("transient_for")
                and props.get("class") and window_type in (None, "normal"))


def _filter_tree(node, config, capture_window, windows, warnings):
    """Omit desktop furniture, placeholders and transient dialog windows."""
    if node.get("window"):
        if not _normal_window(node):
            return None
        props = node.get("window_properties") or {}
        if props.get("class") in config.get("exclude_classes", []):
            return None
        try:
            info = capture_window(node, config)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            info = {"command": None, "cwd": None,
                    "app": props.get("class", "unknown"), "warnings": [str(exc)]}
        info = dict(info)
        info.update({
            "source_id": str(node["window"]),
            "source_con_id": node.get("id"),
            "match": {key: props[key] for key in ("class", "instance") if props.get(key)},
            "focused": bool(node.get("focused")),
        })
        windows.append(info)
        warnings.extend(info.get("warnings", []))
        return copy.deepcopy(node)
    filtered = copy.deepcopy(node)
    for key in ("nodes", "floating_nodes"):
        filtered[key] = [child for original in node.get(key, [])
                         if (child := _filter_tree(original, config, capture_window,
                                                   windows, warnings)) is not None]
    if node.get("type") != "workspace" and not any(
            filtered.get(key) for key in ("nodes", "floating_nodes")):
        return None
    return filtered


def _annotate(source, layout):
    # i3-resurrect preserves child order but omits identifiers from the layout.
    # Keep our association separately; it is removed before append_layout.
    if source.get("window"):
        layout["session_source_id"] = str(source["window"])
    for key in ("nodes", "floating_nodes"):
        for source_child, layout_child in zip(source.get(key, []), layout.get(key, [])):
            _annotate(source_child, layout_child)


def capture_all(config, *, ipc=None, capture_window=None, build_layout=None):
    if capture_window is None:
        from .apps import capture_window
    if build_layout is None:
        build_layout = _build_layout
    ipc = ipc or I3()
    tree = ipc.query("get_tree")
    live_workspaces = ipc.query("get_workspaces")
    outputs = {workspace["name"]: workspace.get("output") for workspace in live_workspaces}
    focused = next((workspace["name"] for workspace in live_workspaces
                    if workspace.get("focused")), None)
    result = {"workspaces": [], "focused_workspace": focused, "warnings": []}
    for name, node in _workspaces(tree).items():
        if name.startswith("__"):
            if _windows(node):
                result["warnings"].append("Scratchpad windows are not restored.")
            continue
        if name in config.get("exclude_workspaces", []):
            continue
        windows, warnings = [], []
        filtered = _filter_tree(node, config, capture_window, windows, warnings)
        if not windows:
            continue
        layout = build_layout(filtered, ["class", "instance"])
        _annotate(filtered, layout)
        result["workspaces"].append({
            "name": name, "output": outputs.get(name), "layout": layout, "windows": windows,
        })
        result["warnings"].extend(warnings)
    return result


capture = capture_all


def _prepared_layout(layout, windows, token):
    """Use owned placeholders that cannot accidentally swallow any client."""
    source_id = layout.get("session_source_id")
    if source_id is not None and source_id not in windows:
        return None
    result = copy.deepcopy(layout)
    result.pop("session_source_id", None)
    # Captured user marks could collide with marks in the current session.
    result.pop("marks", None)
    result.pop("swallows", None)
    result["fullscreen_mode"] = 0  # Reapply after all windows are positioned.
    if source_id is not None:
        mark = f"i3_session_{token}_{source_id}"
        result["marks"] = [mark]
        result["name"] = "i3-session restore placeholder"
        result["swallows"] = [{"class": "(?!)"}]
        windows[source_id]["_mark"] = mark
        windows[source_id]["_fullscreen_mode"] = layout.get("fullscreen_mode", 0)
        windows[source_id]["_border"] = layout.get("border", "normal")
        windows[source_id]["_border_width"] = layout.get("current_border_width", 2)
        windows[source_id]["_sticky"] = bool(layout.get("sticky"))
    for key in ("nodes", "floating_nodes"):
        children = [_prepared_layout(child, windows, token) for child in layout.get(key, [])]
        children = [child for child in children if child is not None]
        if children:
            result[key] = children
        else:
            # i3's append_layout parser can loop when nested leaves contain
            # empty child arrays. Upstream intentionally omits these arrays.
            result.pop(key, None)
    if source_id is None and layout.get("type") != "workspace" and not any(
            result.get(key) for key in ("nodes", "floating_nodes")):
        return None
    return result


def _matches(node, match):
    if not _normal_window(node):
        return False
    props = node.get("window_properties") or {}
    return bool(match.get("class")) and all(props.get(key) == value for key, value in match.items())


def _wait_new_windows(ipc, before, match, config, *, allow_multiple=False):
    timeout = config.get("restore_timeout_seconds", 30)
    poll = config.get("restore_poll_seconds", 0.1)
    settle = (config.get("browser_settle_seconds", 1)
              if allow_multiple else config.get("restore_settle_seconds", 0.3))
    deadline = time.monotonic() + timeout
    candidate_ids, candidate_since = (), None
    while time.monotonic() < deadline:
        candidates = [node for node in _windows(ipc.query("get_tree"))
                      if node["window"] not in before and _matches(node, match)]
        if len(candidates) > 1 and not allow_multiple:
            raise DesktopError("Several new windows matched one launch; left them untouched.")
        if candidates:
            candidates.sort(key=lambda node: node["window"])
            current_ids = tuple(node["window"] for node in candidates)
            if current_ids != candidate_ids:
                candidate_ids, candidate_since = current_ids, time.monotonic()
            if time.monotonic() - candidate_since >= settle:
                return candidates
        else:
            candidate_ids, candidate_since = (), None
        time.sleep(poll)
    raise DesktopError(f"No new matching window appeared within {timeout:g} seconds.")


def _browser_group(window):
    if not window.get("reuse_new_windows") or not window.get("cold_command"):
        return None
    # Different Firefox profiles can share class/instance. Never pool across
    # different saved launch recipes, even when their X11 properties coincide.
    return (tuple(sorted(window["match"].items())), tuple(window["command"]), window.get("cwd"))


def _cleanup_placeholders(ipc, token, errors):
    prefix = f"i3_session_{token}_"
    # Never issue a broad kill, nor kill a launched window after a swap.
    try:
        for node in walk(ipc.query("get_tree")):
            if (node.get("swallows") == [{"class": "(?!)"}]
                    and any(mark.startswith(prefix) for mark in node.get("marks", []))):
                ipc.command(f'[con_id={int(node["id"])}] kill')
    except (DesktopError, OSError, subprocess.SubprocessError) as exc:
        errors.append(f"Could not remove an owned placeholder: {exc}")


def _workspace_command(name):
    return "workspace --no-auto-back-and-forth " + quote(name)


def _preflight_launch(window, command=None):
    cwd = window.get("cwd")
    if cwd is not None and (not isinstance(cwd, str) or not Path(cwd).is_dir()):
        raise DesktopError(f"Saved working directory does not exist: {cwd}")
    command = window["command"] if command is None else command
    if (not isinstance(command, list) or not command
            or not all(isinstance(arg, str) and "\0" not in arg for arg in command)):
        raise DesktopError("Saved launch commands must be nonempty argv lists.")
    executable = command[0]
    if "/" in executable:
        path = Path(executable)
        if not path.is_absolute():
            path = Path(cwd or Path.cwd()) / path
        available = path.is_file() and os.access(path, os.X_OK)
    else:
        available = shutil.which(executable) is not None
    if not available:
        raise DesktopError(f"Saved application executable is unavailable: {executable}")


def restore(snapshot, config, *, ipc=None, launch=None):
    """Restore into empty workspaces; stop on ambiguous/failed application launch.

    Existing windows are never adopted or closed. Failed restores retain windows
    already opened, report the partial result, and remove owned placeholders.
    """
    ipc = ipc or I3()
    launch = launch or subprocess.Popen
    report = {"restored": [], "skipped": [], "errors": [], "warnings": []}
    token = uuid.uuid4().hex
    current_tree = ipc.query("get_tree")
    existing = _workspaces(current_tree)
    workspace_map = config.get("workspace_map", {})
    output_map = config.get("output_map", {})
    targets = []
    seen_names = set()
    for workspace in snapshot.get("workspaces", []):
        name = workspace_map.get(workspace["name"], workspace["name"])
        quote(name)
        if name.startswith("__") or name in seen_names:
            raise DesktopError(f"Invalid or duplicated target workspace: {name}")
        seen_names.add(name)
        windows = {}
        for original in workspace.get("windows", []):
            window = copy.deepcopy(original)
            command = window.get("command")
            if not command:
                report["skipped"].append({"workspace": name, "source_id": window.get("source_id"),
                                          "reason": "No supported launch command"})
                continue
            if (not isinstance(command, list) or not command
                    or not all(isinstance(arg, str) and "\0" not in arg for arg in command)):
                raise DesktopError("Saved launch commands must be nonempty argv lists.")
            source_id = str(window["source_id"])
            if not source_id.isdecimal() or source_id in windows:
                raise DesktopError("Saved window identifiers must be unique decimal strings.")
            if not window.get("match", {}).get("class"):
                raise DesktopError("Saved window has no class for identifying its new window.")
            _preflight_launch(window)
            if window.get("reuse_new_windows"):
                _preflight_launch(window, window.get("cold_command", []))
            windows[source_id] = window
        if not windows:
            continue
        live = existing.get(name)
        if live and any(live.get(key) for key in ("nodes", "floating_nodes")):
            raise DesktopError(f"Workspace {name!r} is not empty; restore made no changes. "
                               "Use the restore keybinding or run from another workspace.")
        layout = _prepared_layout(workspace["layout"], windows, token)
        if not all("_mark" in window for window in windows.values()):
            raise DesktopError("Snapshot layout does not identify every saved window.")
        output = output_map.get(workspace.get("output"), workspace.get("output"))
        if output:
            quote(output)
        targets.append((name, output, layout, windows))
    if not targets:
        return report
    active_outputs = {output["name"] for output in ipc.query("get_outputs") if output.get("active")}
    original_focus = next((node["name"] for node in ipc.query("get_workspaces")
                           if node.get("focused")), None)
    state_dir = Path(config.get("_state_dir", Path(os.environ.get(
        "XDG_STATE_HOME", Path.home() / ".local/state")) / "i3-session"))
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    placed = []
    processes = []
    pools, remaining = {}, {}
    for _, _, _, windows in targets:
        for window in windows.values():
            group = _browser_group(window)
            if group is not None:
                remaining[group] = remaining.get(group, 0) + 1
    try:
        with tempfile.TemporaryDirectory(prefix="restore-", dir=state_dir) as directory:
            for index, (name, output, layout, windows) in enumerate(targets):
                # Recheck immediately before appending, since users can open windows during restore.
                live = _workspaces(ipc.query("get_tree")).get(name)
                if live and any(live.get(key) for key in ("nodes", "floating_nodes")):
                    raise DesktopError(f"Workspace {name!r} became occupied; stopping restore.")
                ipc.command(_workspace_command(name))
                if output in active_outputs:
                    ipc.command("move workspace to output " + quote(output))
                elif output:
                    report["warnings"].append(f"Output {output!r} unavailable; kept {name!r} on an available output.")
                workspace_node = _workspaces(ipc.query("get_tree"))[name]
                layout_mode = layout.get("layout", "splith")
                if layout_mode not in ("splith", "splitv", "stacked", "stacking", "tabbed", "default"):
                    raise DesktopError("Snapshot has an unsupported workspace layout.")
                if layout_mode == "stacked":
                    layout_mode = "stacking"
                ipc.command(f'[con_id={int(workspace_node["id"])}] layout {layout_mode}')
                path = Path(directory) / f"layout-{index}.json"
                # Use the documented i3-save-tree framing: a stream of objects.
                path.write_text("\n".join(json.dumps(node) for node in
                                          layout.get("nodes", []) + layout.get("floating_nodes", [])))
                path.chmod(0o600)
                ipc.command("append_layout " + quote(str(path)))
                for window in windows.values():
                    current = _windows(ipc.query("get_tree"))
                    group = _browser_group(window)
                    if group is not None and pools.get(group):
                        window_id = pools[group].pop(0)
                        new = next((node for node in current if node["window"] == window_id
                                    and _matches(node, window["match"])), None)
                        if new is None:
                            raise DesktopError("A newly opened browser window disappeared before placement.")
                    else:
                        before = {node["window"] for node in current}
                        command, cwd = window["command"], window.get("cwd")
                        if group is not None and not any(_matches(node, window["match"]) for node in current):
                            # A cold browser can restore several native session
                            # windows. Do not request an additional blank one.
                            command = window["cold_command"]
                        if cwd and not Path(cwd).is_dir():
                            raise DesktopError(f"Saved working directory does not exist: {cwd}")
                        process = launch(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         start_new_session=True)
                        processes.append(process)
                        candidates = _wait_new_windows(ipc, before, window["match"], config,
                                                       allow_multiple=group is not None)
                        if group is not None:
                            if len(candidates) > remaining[group]:
                                raise DesktopError("Browser opened more windows than saved layout slots; left them untouched.")
                            pools[group] = [node["window"] for node in candidates[1:]]
                        new = candidates[0]
                    placeholder = next((node for node in walk(ipc.query("get_tree"))
                                        if window["_mark"] in node.get("marks", [])), None)
                    if not placeholder or placeholder.get("swallows") != [{"class": "(?!)"}]:
                        raise DesktopError("Restore placeholder disappeared; left the new window untouched.")
                    # Border changes resize floating frames. Set the border
                    # before swapping so the saved outer rectangle is final.
                    border = window["_border"]
                    if border in ("normal", "pixel", "none"):
                        width = max(0, int(window["_border_width"]))
                        border_command = "border none" if border == "none" else f"border {border} {width}"
                        ipc.command(f'[con_id={int(new["id"])}] {border_command}')
                    ipc.command(f'[con_id={int(new["id"])}] swap container with con_id {int(placeholder["id"])}')
                    # The placeholder keeps its identity after the swap. Verify before closing.
                    now = next((node for node in walk(ipc.query("get_tree"))
                                if node.get("id") == placeholder["id"]), None)
                    if now and now.get("swallows") == [{"class": "(?!)"}]:
                        ipc.command(f'[con_id={int(now["id"])}] kill')
                    if window["_sticky"]:
                        ipc.command(f'[con_id={int(new["id"])}] sticky enable')
                    report["restored"].append({"workspace": name, "source_id": window["source_id"],
                                               "window_id": new["window"]})
                    placed.append((new["id"], window))
                    if group is not None:
                        remaining[group] -= 1
            for con_id, window in placed:
                if window["_fullscreen_mode"]:
                    mode = " global" if window["_fullscreen_mode"] == 2 else ""
                    ipc.command(f"[con_id={int(con_id)}] fullscreen enable{mode}")
            focused = snapshot.get("focused_workspace")
            if focused:
                ipc.command(_workspace_command(workspace_map.get(focused, focused)))
            for con_id, window in placed:
                if window.get("focused"):
                    ipc.command(f"[con_id={int(con_id)}] focus")
    except (DesktopError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        report["errors"].append(str(exc))
        if original_focus:
            try:
                ipc.command(_workspace_command(original_focus))
            except (DesktopError, OSError, subprocess.SubprocessError) as focus_error:
                report["errors"].append(f"Could not restore focus: {focus_error}")
    finally:
        _cleanup_placeholders(ipc, token, report["errors"])
        # Reap launchers which exited (e.g. browser IPC clients), without waiting for applications.
        for process in processes:
            process.poll()
    return report
