"""Load shipped defaults and optional user overrides."""

import json
import math
import os
from pathlib import Path

DEFAULTS = Path(__file__).resolve().parents[2] / ".config/i3-session/config.json"


def state_directory():
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "i3-session"


def load(path=None, delay=None, interval=None):
    config = json.loads(DEFAULTS.read_text())
    user = Path(path).expanduser() if path else Path(
        os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    ) / "i3-session/config.json"
    if path or user.exists():
        overrides = json.loads(user.read_text())
        if not isinstance(overrides, dict):
            raise ValueError("Configuration must be a JSON object")
        config.update(overrides)
    if delay is not None:
        config["restore_delay_seconds"] = duration(delay)
    if interval is not None:
        config["capture_interval_seconds"] = duration(interval)
    for key in (
        "restore_delay_seconds", "capture_interval_seconds", "history_seconds",
        "restore_timeout_seconds", "restore_poll_seconds", "restore_settle_seconds", "browser_settle_seconds",
        "startup_timeout_seconds", "connection_failure_limit", "log_max_bytes", "log_backups",
    ):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError(f"{key} must be a finite number")
        if value < 0 or (value == 0 and key not in {"restore_delay_seconds", "restore_settle_seconds", "browser_settle_seconds"}):
            raise ValueError(f"{key} must be positive (delay/settle may be zero)")
    for key in ("connection_failure_limit", "log_max_bytes", "log_backups"):
        if not isinstance(config[key], int):
            raise ValueError(f"{key} must be an integer")
    for key in ("exclude_classes", "exclude_workspaces"):
        if not isinstance(config[key], list) or not all(isinstance(v, str) for v in config[key]):
            raise ValueError(f"{key} must be a list of strings")
    for key in ("workspace_map", "output_map"):
        if not isinstance(config[key], dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in config[key].items()
        ):
            raise ValueError(f"{key} must map names to names")
    if not isinstance(config["applications"], list):
        raise ValueError("applications must be a list")
    for rule in config["applications"]:
        if not isinstance(rule, dict) or not isinstance(rule.get("class"), str) or not rule["class"]:
            raise ValueError("Each application rule needs a nonempty class name")
        command = rule.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(v, str) and v and "\0" not in v for v in command):
            raise ValueError("Each application rule needs a nonempty command argv array")
        if "cwd" in rule and (not isinstance(rule["cwd"], str) or not Path(rule["cwd"]).expanduser().is_absolute()):
            raise ValueError("Application cwd must be an absolute path")
    if "browser_executables" in config and (not isinstance(config["browser_executables"], dict) or not all(
        isinstance(k, str) and isinstance(v, str) and v for k, v in config["browser_executables"].items()
    )):
        raise ValueError("browser_executables must map browser names to executable names")
    for key in ("code_title_prefix", "code_title_suffix", "code_executable", "obsidian_executable", "obsidian_config"):
        if key in config and (not isinstance(config[key], str) or not config[key] or "\0" in config[key]):
            raise ValueError(f"{key} must be a nonempty string")
    return config


def duration(value):
    text = str(value).strip().lower()
    scale = {"s": 1, "m": 60, "h": 3600}
    multiplier = scale.get(text[-1:], 1)
    number = text[:-1] if text[-1:] in scale else text
    result = float(number) * multiplier
    if not math.isfinite(result) or result < 0:
        raise ValueError("Duration must be finite and nonnegative")
    return result
