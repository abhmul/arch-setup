"""Command line and recorder lifecycle; app launches live in desktop.py."""

import argparse
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from i3_session import config as configuration
from i3_session.state import Store, atomic_json, lock, read_json


def session_identity():
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    session = os.environ.get("XDG_SESSION_ID")
    display = os.environ.get("DISPLAY")
    if not session or not display:
        raise ValueError("Run this command inside your graphical login (DISPLAY and XDG_SESSION_ID are required)")
    return f"{boot}:{session}:{display}"


def process_start(pid):
    try:
        return Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def is_running(directory):
    with lock(directory / "recorder.lock", blocking=False) as acquired:
        return not acquired


def notify(message):
    try:
        subprocess.run(["notify-send", "i3 session", message], check=False, timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass


def summary(snapshot):
    return {
        "id": snapshot["id"],
        "captured_at": datetime.fromtimestamp(snapshot["captured_at"]).astimezone().isoformat(timespec="seconds"),
        "workspaces": [{"name": ws["name"], "windows": len(ws["windows"]),
                        "restorable": sum(bool(w.get("command")) for w in ws["windows"])}
                       for ws in snapshot["workspaces"]],
        "warnings": snapshot.get("warnings", []),
    }


def record(directory, config):
    from i3_session import desktop
    with lock(directory / "recorder.lock", blocking=False) as acquired:
        if not acquired:
            return 0
        session_id = session_identity()
        store = Store(directory, config)
        logger = logging.getLogger("i3-session")
        logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(directory / "recorder.log", maxBytes=config["log_max_bytes"], backupCount=config["log_backups"])
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
        daemon = {"pid": os.getpid(), "process_start": process_start(os.getpid()),
                  "session_id": session_id, "started_at": time.time(), "status": "starting",
                  "delay_seconds": config["restore_delay_seconds"], "interval_seconds": config["capture_interval_seconds"]}
        atomic_json(directory / "daemon.json", daemon)
        failures = 0
        logger.info("Recorder started")
        try:
            while not stop.is_set():
                with lock(directory / "operation.lock", blocking=False) as free:
                    if free:
                        try:
                            payload = desktop.capture_all(config)
                            store.observe(payload, session_id)
                            failures = 0
                            daemon.update(status="recording", last_capture_at=time.time(), error=None)
                        except Exception as exc:
                            failures += 1
                            daemon.update(status="error", error=str(exc))
                            logger.exception("Capture failed")
                        atomic_json(directory / "daemon.json", daemon)
                if failures >= config["connection_failure_limit"]:
                    logger.error("Stopping after repeated capture failures; checkpoints preserved")
                    break
                stop.wait(config["capture_interval_seconds"])
        finally:
            daemon["status"] = "stopped"
            atomic_json(directory / "daemon.json", daemon)
            logger.info("Recorder stopped")
            handler.close()
            logger.removeHandler(handler)
        return 1 if failures else 0


def start(directory, config, args):
    identity = session_identity()
    if is_running(directory):
        existing = read_json(directory / "daemon.json", {})
        if existing.get("session_id") == identity:
            print("Recorder already running")
            return 0
        # A detached recorder may outlive logout. Only signal our verified PID,
        # then give the new login its own identity and i3 environment.
        stop_recorder(directory, config)
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--state-dir", str(directory)]
    for option, value in (("--config", args.config), ("--delay", args.delay), ("--interval", args.interval)):
        if value is not None:
            command.extend([option, str(value)])
    command.append("record")
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + config["startup_timeout_seconds"]
    while time.monotonic() < deadline:
        daemon = read_json(directory / "daemon.json", {})
        if daemon.get("pid") == process.pid and daemon.get("status") == "recording" and is_running(directory):
            print(f"Recorder started (PID {process.pid}); delay {config['restore_delay_seconds']:g}s")
            return 0
        if process.poll() is not None:
            raise ValueError(f"Recorder failed to start; inspect {directory / 'recorder.log'}")
        time.sleep(min(0.1, config["startup_timeout_seconds"]))
    raise ValueError(f"Recorder has not completed its first capture; inspect {directory / 'recorder.log'}")


def stop_recorder(directory, config):
    if not is_running(directory):
        print("Recorder is not running")
        return 0
    daemon = read_json(directory / "daemon.json", {})
    pid = daemon.get("pid")
    if not pid or process_start(pid) != daemon.get("process_start"):
        raise ValueError("Recorder identity could not be verified; no signal sent")
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + config["startup_timeout_seconds"]
    while time.monotonic() < deadline:
        if not is_running(directory):
            print("Recorder stopped; checkpoints retained")
            return 0
        time.sleep(0.1)
    raise ValueError("Stop requested; recorder is still completing its current capture")


def restore(directory, config, args):
    from i3_session import desktop
    with lock(directory / "operation.lock", blocking=False) as acquired:
        if not acquired:
            raise ValueError("Another capture or restore is in progress; try again shortly")
        store = Store(directory, config)
        destination_session = session_identity()
        snapshot, reason = store.select(destination_session, args.source, args.snapshot)
        if args.dry_run:
            result = summary(snapshot)
            result["selection"] = reason
            result["launches"] = [{"workspace": config["workspace_map"].get(ws["name"], ws["name"]),
                                  "command": window.get("command"), "cold_command": window.get("cold_command"),
                                  "reuse_new_windows": bool(window.get("reuse_new_windows")), "cwd": window.get("cwd"),
                                  "agent_session": window.get("agent_session")}
                                 for ws in snapshot["workspaces"] for window in ws["windows"]]
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        receipt = store.index().get("restore_receipt")
        if receipt and receipt["id"] == snapshot["id"] and receipt.get("destination_session") == destination_session:
            if receipt["status"] == "complete":
                print("This checkpoint was already restored; no windows launched")
                return 0
            if not args.retry:
                raise ValueError("An earlier restore was interrupted or partial. Review status and occupied workspaces, then use --retry if appropriate")
        store.receipt(snapshot["id"], "in_progress", destination_session=destination_session)
        try:
            report = desktop.restore(snapshot, dict(config, _state_dir=str(directory)))
        except Exception as exc:
            store.receipt(snapshot["id"], "failed", {"errors": [str(exc)]}, destination_session)
            raise
        success = not report.get("errors")
        store.receipt(snapshot["id"], "complete" if success else "partial", report, destination_session)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if args.notify:
            notify("Desktop restored" if success else "Restore incomplete; run i3-session status for details")
        return 0 if success else 1


def parser():
    root = argparse.ArgumentParser(description="Record delayed i3 desktop checkpoints and restore the previous login")
    root.add_argument("--config", help="JSON configuration override")
    root.add_argument("--state-dir", type=Path, default=configuration.state_directory())
    root.add_argument("--delay", help="Checkpoint delay, e.g. 5m or 300s")
    root.add_argument("--interval", help="Capture interval, e.g. 15s")
    commands = root.add_subparsers(dest="command", required=True)
    for name, help_text in (("start", "Start recording in the background"), ("record", "Record in the foreground"),
                            ("stop", "Stop recording without discarding checkpoints"), ("status", "Show recorder and checkpoints"),
                            ("list", "List retained snapshots"), ("save", "Pin the current desktop as a manual checkpoint"),
                            ("capture", "Capture once into automatic history")):
        commands.add_parser(name, help=help_text)
    restore_parser = commands.add_parser("restore", help="Restore the previous login's delayed checkpoint")
    restore_parser.add_argument("--source", choices=("previous", "current", "manual"), default="previous")
    restore_parser.add_argument("--snapshot", help="Restore an explicit retained snapshot ID")
    restore_parser.add_argument("--dry-run", action="store_true", help="Print launches without changing the desktop")
    restore_parser.add_argument("--retry", action="store_true", help="Retry a partial attempt after reviewing/clearing target workspaces")
    restore_parser.add_argument("--notify", action="store_true", help="Send a desktop notification on success or failure")
    agent_launch = commands.add_parser("agent-launch", help="Run a native agent with terminal tracking")
    agent_launch.add_argument("--launcher", choices=("codex", "codex-academic", "claude"), required=True)
    agent_launch.add_argument("argv", nargs=argparse.REMAINDER)
    agent_hook = commands.add_parser("agent-hook", help="Receive a native agent lifecycle event")
    agent_hook.add_argument("--tool", choices=("codex", "claude"), required=True)
    agent_resume = commands.add_parser("agent-resume", help="Reopen an exact saved agent conversation")
    agent_resume.add_argument("--binding", required=True)
    commands.add_parser("agents", help="Show persistent terminal-to-agent associations")
    commands.add_parser("forget-agent", help="Forget this terminal's agent association without deleting its conversation")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command not in {"agent-launch", "agent-resume"}:
        os.umask(0o077)
    try:
        directory = args.state_dir.expanduser().resolve()
        if args.command.startswith("agent-") or args.command in {"agents", "forget-agent"}:
            from i3_session import agent_launch, agent_process
            from i3_session.agent_sessions import Registry
            if args.command == "agent-launch":
                return agent_launch.launch(directory, args.launcher, args.argv)
            if args.command == "agent-hook":
                try:
                    agent_launch.hook(directory, args.tool, json.load(sys.stdin))
                except (OSError, ValueError, KeyError, TypeError):
                    # Tracking must not inject context or block native agent work.
                    pass
                return 0
            if args.command == "agent-resume":
                return agent_launch.resume(directory, json.loads(args.binding))
            if args.command == "agents":
                print(json.dumps(Registry(directory).read(), indent=2))
                return 0
            context = agent_process.terminal_context(os.getpid())
            if not context:
                raise ValueError("Run forget-agent from a single-pane kitty terminal's shell")
            forgotten = Registry(directory).forget(context)
            print("Agent bookmark forgotten; conversation retained" if forgotten else "This terminal has no agent bookmark")
            return 0
        config = dict(configuration.load(args.config, args.delay, args.interval), _state_dir=str(directory))
        if args.command == "record":
            return record(directory, config)
        if args.command == "start":
            return start(directory, config, args)
        if args.command == "stop":
            return stop_recorder(directory, config)
        store = Store(directory, config)
        if args.command == "status":
            print(json.dumps({"running": is_running(directory), "daemon": read_json(directory / "daemon.json"),
                              "state_directory": str(directory), "state": store.index()}, indent=2, ensure_ascii=False))
        elif args.command == "list":
            for path in sorted((directory / "snapshots").glob("*.json"), key=lambda p: p.stat().st_mtime):
                print(json.dumps(summary(store.snapshot(path.stem)), ensure_ascii=False))
        elif args.command in ("save", "capture"):
            from i3_session import desktop
            with lock(directory / "operation.lock"):
                payload = desktop.capture_all(config)
                snapshot = store.save_manual(payload, session_identity()) if args.command == "save" else store.observe(payload, session_identity())
            print(json.dumps(summary(snapshot), indent=2, ensure_ascii=False))
        elif args.command == "restore":
            return restore(directory, config, args)
        return 0
    except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"i3-session: {exc}", file=sys.stderr)
        if getattr(args, "notify", False):
            notify(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
