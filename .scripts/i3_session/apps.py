"""Conservative launch recipes for desktop windows; never replay process argv.

For reliable local VS Code folders, append these literal variables to window.title:
    [i3-session:${rootPath}] [i3-session-remote:${remoteName}]
The directory cannot reliably be recovered from Code's shared main process or
remembered windowsState. No VS Code configuration is changed by this module.
"""

from __future__ import annotations

import json
import ipaddress
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import quote


XPROP_TIMEOUT_SECONDS = 2
SHELL_NAMES = {"bash", "zsh", "fish", "sh", "dash", "ksh", "nu"}
CHROMIUM_CLASSES = {
    "chromium": "chromium",
    "google-chrome": "google-chrome",
    "brave-browser": "brave",
    "vivaldi-stable": "vivaldi",
}
CODE_CLASSES = {"code": "code", "code - insiders": "code-insiders", "vscodium": "codium"}


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))


def _window_pid(node: dict[str, Any]) -> int | None:
    pid = node.get("pid")
    if isinstance(pid, int) and pid > 0:
        return pid
    window = node.get("window")
    if not isinstance(window, int) or window <= 0:
        return None
    try:
        result = subprocess.run(
            ["xprop", "-id", str(window), "_NET_WM_PID"],
            capture_output=True, text=True, timeout=XPROP_TIMEOUT_SECONDS, check=False,
        )
        match = re.search(r"_NET_WM_PID\(CARDINAL\)\s*=\s*(\d+)", result.stdout)
        return int(match.group(1)) if result.returncode == 0 and match else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _process_args(pid: int | None) -> list[str]:
    if not pid:
        return []
    try:
        return [os.fsdecode(part) for part in (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0") if part]
    except OSError:
        return []


def _process_cwd(pid: int | None) -> str | None:
    if not pid:
        return None
    try:
        path = os.readlink(Path("/proc") / str(pid) / "cwd")
        return path if Path(path).is_dir() else None
    except OSError:
        return None


def _profile_args(args: list[str], flags: set[str]) -> list[str]:
    """Copy only named profile selectors, preserving each argument's boundaries."""
    selected: list[str] = []
    index = 1
    while index < len(args):
        argument = args[index]
        flag, separator, value = argument.partition("=")
        if flag in flags:
            if separator and value:
                selected.append(argument)
            elif not separator and index + 1 < len(args) and not args[index + 1].startswith("-"):
                selected.extend((argument, args[index + 1]))
                index += 1
        index += 1
    return selected


def _chromium_debug_args(args: list[str], profile_path: str | None = None) -> tuple[list[str], list[str]]:
    """Preserve only an unambiguous debugging port and optional loopback bind.

    Chromium may flatten argv without quoting. Recover these two scalar flags
    narrowly, never shell-split that process title or replay other switches.
    """
    values: dict[str, list[str | None]] = {"port": [], "address": []}
    if len(args) == 1:
        title = args[0]
        if profile_path:
            # A literal profile path can itself contain text resembling flags.
            # Mask the known WM_CLASS path before looking for scalar switches.
            title = re.sub(r"(?<!\S)--user-data-dir(?:=|\s+)" + re.escape(profile_path) + r"(?=\s|$)",
                           "--user-data-dir=<recorded-profile>", title)
        pattern = r"(?<!\S)--remote-debugging-(port|address)(?:=([^\s]*)|(?:\s+([^\s]+))?(?=\s|$))"
        for match in re.finditer(pattern, title):
            values[match.group(1)].append(match.group(2) if match.group(2) is not None else match.group(3))
    else:
        for index, argument in enumerate(args[1:], 1):
            flag, separator, value = argument.partition("=")
            for name in values:
                if flag == "--remote-debugging-" + name:
                    values[name].append(value if separator else (args[index + 1] if index + 1 < len(args) else None))
    if not any(values.values()):
        return [], []
    ports = values["port"]
    addresses = values["address"]
    if (not ports or any(not value or not re.fullmatch(r"[0-9]{1,5}", value) or not 1 <= int(value) <= 65535
                         for value in ports) or len({int(value) for value in ports if value and value.isascii() and value.isdigit()}) != 1):
        return [], ["Chromium debugging port is missing, invalid, or conflicting; debugging flags were omitted."]
    if addresses:
        if len(set(addresses)) != 1 or not addresses[0]:
            return [], ["Chromium debugging address is missing or conflicting; debugging flags were omitted."]
        address = addresses[0]
        try:
            loopback = address == "localhost" or ("%" not in address and ipaddress.ip_address(address).is_loopback)
        except ValueError:
            loopback = False
        if not loopback:
            return [], ["Chromium debugging address is not a loopback address; debugging flags were omitted."]
    result = ["--remote-debugging-port=" + str(int(ports[0]))]
    if addresses:
        result.append("--remote-debugging-address=" + addresses[0])
    return result, []


def _kitty_cwd(node: dict[str, Any], pid: int | None) -> tuple[str, list[str]]:
    fallback = _process_cwd(pid) or str(Path.home())
    if not pid:
        return fallback, ["kitty process unavailable; using the home directory."]
    try:
        children = (Path("/proc") / str(pid) / "task" / str(pid) / "children").read_text().split()
    except OSError:
        children = []
    matching: set[str] = set()
    unidentified: set[str] = set()
    for child in children:
        child_pid = int(child)
        args = _process_args(child_pid)
        if not args or Path(args[0]).name.lstrip("-") not in SHELL_NAMES:
            continue
        cwd = _process_cwd(child_pid)
        if not cwd:
            continue
        try:
            environ = (Path("/proc") / child / "environ").read_bytes().split(b"\0")
            window_id = next((item.split(b"=", 1)[1].decode() for item in environ if item.startswith(b"WINDOWID=")), None)
        except (OSError, UnicodeError):
            window_id = None
        if window_id == str(node.get("window")):
            matching.add(cwd)
        elif window_id is None:
            unidentified.add(cwd)
    if len(matching) == 1:
        return matching.pop(), []
    if not matching and len(unidentified) == 1:
        return unidentified.pop(), ["kitty shell has no WINDOWID; its directory is a best-effort match."]
    return fallback, ["kitty tabs/splits have no unique directory; using the terminal process directory."]


def _code_target(title: str, config: dict[str, Any]) -> tuple[str | None, list[str]]:
    prefix = config.get("code_title_prefix", "[i3-session:")
    suffix = config.get("code_title_suffix", "]")
    remote = re.search(r"\[i3-session-remote:(.*?)\]", title)
    if not remote:
        return None, ["VS Code folder is unknown; add both i3-session and i3-session-remote markers to window.title."]
    if remote and remote.group(1).strip():
        return None, ["Remote VS Code workspace is unsupported; reopening an empty local window."]
    if prefix not in title or suffix not in title.split(prefix, 1)[1]:
        return None, ["VS Code folder is unknown; add i3-session markers to window.title to record it."]
    # Greedy matching supports paths containing ']' and uses the closing marker
    # before the separate remote marker, when present.
    local_title = title[:remote.start()] if remote else title
    match = re.search(re.escape(prefix) + r"(.*)" + re.escape(suffix), local_title)
    value = match.group(1) if match else ""
    if not value:
        return None, []
    path = Path(value).expanduser()
    if not path.is_absolute():
        return None, ["VS Code title does not identify an absolute local folder; reopening an empty window."]
    if path.is_dir():
        return str(path), []
    if path.is_file() and path.suffix == ".code-workspace":
        return str(path), []
    return None, ["VS Code folder is missing or is an untitled workspace; reopening an empty window."]


def _obsidian_target(title: str, config: dict[str, Any]) -> tuple[str | None, str | None]:
    """Resolve an unambiguous vault name, without opening any note content."""
    path = Path(config.get("obsidian_config", _config_home() / "obsidian" / "obsidian.json")).expanduser()
    try:
        vaults = json.loads(path.read_text()).get("vaults", {})
    except (OSError, ValueError, AttributeError):
        return None, None
    matches = []
    for vault_id, entry in vaults.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            continue
        vault_path = Path(entry["path"])
        if re.search(r"(?:^| - )" + re.escape(vault_path.name) + r" - Obsidian(?: |$)", title):
            matches.append((vault_id, str(vault_path)))
    return matches[0] if len(matches) == 1 else (None, None)


def capture_window(node: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Return a safe argv launch recipe, cwd, app name, and capture warnings.

    ``applications`` entries override builtins and match an exact WM_CLASS.
    Commands are literal argv arrays, not shell strings; no interpolation occurs.
    Unknown apps are retained in the snapshot with command=None for visibility.
    Builtin browsers may also supply a cold_command and reuse_new_windows: the
    backend can place windows from native session startup into saved slots.
    """
    properties = node.get("window_properties") or {}
    window_class = properties.get("class") or ""
    app = window_class.casefold()
    title = properties.get("title") or node.get("name") or ""
    result: dict[str, Any] = {"command": None, "cwd": str(Path.home()), "app": window_class, "warnings": []}

    for rule in config.get("applications", []):
        if rule.get("class") == window_class:
            command = rule.get("command")
            if not isinstance(command, list) or not command or not all(isinstance(arg, str) and arg and "\0" not in arg for arg in command):
                raise ValueError(f"Application rule for {window_class!r} needs a nonempty command argv array")
            cwd = Path(rule.get("cwd", str(Path.home()))).expanduser()
            if not cwd.is_absolute():
                raise ValueError(f"Application rule for {window_class!r} needs an absolute cwd")
            result.update(command=list(command), cwd=str(cwd))
            return result

    needs_process = app in {"firefox", "firefox-esr", "kitty"} or app in CHROMIUM_CLASSES
    pid = _window_pid(node) if needs_process else None
    args = _process_args(pid) if needs_process else []
    executables = config.get("browser_executables", {})
    if app in {"firefox", "firefox-esr"}:
        executable = executables.get(app, app)
        profiles = _profile_args(args, {"--profile", "-profile", "-P"})
        result["command"] = [executable, *profiles, "--new-window", "about:blank"]
        result.update(cold_command=[executable, *profiles], reuse_new_windows=True)
    elif app in CHROMIUM_CLASSES:
        executable = executables.get(app, CHROMIUM_CLASSES[app])
        profiles = _profile_args(args, {"--user-data-dir", "--profile-directory"})
        # Chromium can overwrite /proc/cmdline with a single, unquoted process
        # title. Splitting that string would corrupt profile paths with spaces.
        # Its WM_CLASS instance explicitly encodes kUserDataDir instead:
        # chromium/src/chrome/browser/shell_integration_linux.cc,
        # internal::GetProgramClassName.
        instance_profile = re.fullmatch(r"[^()]+ \((.*)\)", properties.get("instance", ""))
        if instance_profile and not any(arg.startswith("--user-data-dir") for arg in profiles):
            profile_path = Path(instance_profile.group(1))
            if profile_path.is_absolute():
                profiles.append("--user-data-dir=" + str(profile_path))
        debug, debug_warnings = _chromium_debug_args(args, instance_profile.group(1) if instance_profile else None)
        result["warnings"].extend(debug_warnings)
        result["command"] = [executable, *profiles, *debug, "--new-window", "about:blank"]
        if " (" in properties.get("instance", "") and not any(arg.startswith("--user-data-dir") for arg in profiles):
            result["command"] = None
            result["warnings"].append("Chromium user-data directory could not be read; add an explicit application rule.")
        if len(args) == 1 and "--profile-directory" in args[0]:
            result["warnings"].append("Chromium rewrote its command line; the exact profile-directory cannot be recovered.")
        if result["command"] is not None:
            result.update(cold_command=[executable, *profiles, *debug], reuse_new_windows=True)
    elif app == "kitty":
        cwd, warnings = _kitty_cwd(node, pid)
        result.update(command=["kitty", "--directory", cwd], cwd=cwd, warnings=warnings)
    elif app in CODE_CLASSES:
        target, warnings = _code_target(title, config)
        command = [config.get("code_executable", CODE_CLASSES[app]), "--new-window"]
        if target:
            command.append(target)
            result["cwd"] = target if Path(target).is_dir() else str(Path(target).parent)
        result.update(command=command, warnings=warnings)
    elif app in {"obsidian", "md.obsidian.obsidian"}:
        vault_id, cwd = _obsidian_target(title, config)
        if vault_id:
            result.update(command=[config.get("obsidian_executable", "obsidian"), "obsidian://open?vault=" + quote(vault_id, safe="")], cwd=cwd)
        else:
            result["warnings"].append("Obsidian vault is ambiguous; add an explicit application rule to restore it.")
    else:
        result["warnings"].append(f"Unsupported application class {window_class!r}; add an application rule to restore it.")
    return result
