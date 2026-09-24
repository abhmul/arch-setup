"""Native root identity must not be inferred from cwd, latest files, or PID alone."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".scripts"))
from i3_session import agent_process as agents


ROOT_ID = "019c6e27-e55b-73d1-87d8-4e01f1f75043"
OTHER_ID = "019c7714-3b77-74d1-9866-e1f484aae2ab"
BOOT_ID = "6a405086-74c6-49e8-a8a4-2bde6c6d409f"


class AgentProcessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="i3-agent-process-", dir=Path(__file__).parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.proc = self.root / "proc"
        (self.proc / "sys/kernel/random").mkdir(parents=True)
        (self.proc / "sys/kernel/random/boot_id").write_text(BOOT_ID)
        self.home = self.root / "home"
        self.home.mkdir()
        self.cwd = self.root / "project"
        self.cwd.mkdir()
        self.patch = patch.object(agents, "PROC", self.proc)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.process(10, 1, ["kitty"], tty=0, sid=10, pgrp=10, tpgid=-1)
        self.process(20, 10, ["bash"], pgrp=20)
        self.process(30, 20, ["codex"], env={"CODEX_HOME": str(self.home / ".codex")})

    def process(self, pid, ppid, args, *, start=None, tty=34816, sid=20, pgrp=30, tpgid=30, env=None):
        directory = self.proc / str(pid)
        directory.mkdir(exist_ok=True)
        fields = ["0"] * 20
        fields[:6] = ["S", str(ppid), str(pgrp), str(sid), str(tty), str(tpgid)]
        fields[19] = str(start if start is not None else pid * 100)
        (directory / "stat").write_text(f"{pid} (process name) " + " ".join(fields))
        (directory / "cmdline").write_bytes(b"\0".join(os.fsencode(arg) for arg in args) + b"\0")
        environment = {"HOME": str(self.home), "WINDOWID": "900", "KITTY_WINDOW_ID": "1", "SECRET_TOKEN": "not-for-return"}
        environment.update(env or {})
        (directory / "environ").write_bytes(b"\0".join(os.fsencode(key + "=" + value) for key, value in environment.items() if value is not None))
        if not (directory / "cwd").is_symlink():
            (directory / "cwd").symlink_to(self.cwd)
        own_children = directory / "task" / str(pid) / "children"
        own_children.parent.mkdir(parents=True, exist_ok=True)
        if not own_children.exists():
            own_children.write_text("")
        parent_children = self.proc / str(ppid) / "task" / str(ppid) / "children"
        if parent_children.exists():
            children = set(parent_children.read_text().split()) | {str(pid)}
            parent_children.write_text(" ".join(sorted(children)))
        return directory

    def codex_transcript(self, session_id=ROOT_ID, *, fd=5, source="cli", parent=None, writable=True, home=None):
        home = home or self.home / ".codex"
        path = home / "sessions/2026/09/24" / f"rollout-{session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": session_id, "source": source, "cwd": str(self.cwd), "parent_thread_id": parent,
        }}) + "\n" + "PRIVATE CONTENT MUST NOT BE READ\n")
        fdroot = self.proc / "30/fd"
        fdroot.mkdir(exist_ok=True)
        (fdroot / str(fd)).symlink_to(path)
        fdinfo = self.proc / "30/fdinfo"
        fdinfo.mkdir(exist_ok=True)
        (fdinfo / str(fd)).write_text("flags:\t" + ("02102002" if writable else "0100000") + "\n")
        return path

    def claude_metadata(self, *, session_id=ROOT_ID, proc_start="3000", transcript=True, **updates):
        self.process(30, 20, ["claude"])
        home = self.home / ".claude"
        (home / "sessions").mkdir(parents=True, exist_ok=True)
        data = {"pid": 30, "procStart": proc_start, "kind": "interactive", "entrypoint": "cli",
                "sessionId": session_id, "cwd": str(self.cwd), **updates}
        (home / "sessions/30.json").write_text(json.dumps(data))
        path = home / "projects/project" / f"{session_id}.jsonl"
        if transcript:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("PRIVATE CONTENT MUST NOT BE READ\n")
        return home, path

    def test_foreground_helper_and_native_share_exact_terminal_lifetime(self):
        context = agents.terminal_context(30)
        self.assertEqual(context, {"boot_id": BOOT_ID, "kitty_pid": 10, "kitty_start": "1000",
                                   "window_id": "900", "shell_pid": 20, "shell_start": "2000", "kitty_window_id": "1"})
        self.process(30, 20, ["python", "agent-launch"])
        self.assertEqual(agents.terminal_context(30), context)
        self.assertNotIn("SECRET_TOKEN", agents.process_info(30)["environment"])

    def test_shell_reuse_changes_context_even_with_same_pid_and_directory(self):
        original = agents.terminal_context(30)
        self.process(20, 10, ["bash"], pgrp=20, start=9999)
        self.assertNotEqual(agents.terminal_context(30), original)

    def test_background_different_tty_and_nested_agent_helpers_are_rejected(self):
        for updates in ({"pgrp": 31}, {"tty": 34817}, {"sid": 21}):
            with self.subTest(updates=updates):
                self.process(30, 20, ["codex"], **updates)
                self.assertIsNone(agents.terminal_context(30))
        self.process(30, 20, ["claude"])
        self.process(40, 30, ["python", "agent-launch"])
        self.assertIsNone(agents.terminal_context(40))
        self.process(40, 30, ["codex"])
        self.assertIsNone(agents.terminal_context(40))

    def test_two_panes_same_cwd_are_ambiguous(self):
        self.process(21, 10, ["bash"], sid=21, pgrp=21, tty=34817, env={"KITTY_WINDOW_ID": "2"})
        context, warnings = agents.window_terminal(10, 900)
        self.assertIsNone(context)
        self.assertTrue(warnings)
        self.assertIsNone(agents.terminal_context(30))

    def test_other_os_window_pane_does_not_make_this_window_ambiguous(self):
        self.process(21, 10, ["bash"], sid=21, pgrp=21, tty=34817, env={"WINDOWID": "901", "KITTY_WINDOW_ID": "2"})
        self.assertIsNotNone(agents.window_terminal(10, 900)[0])

    def test_unknown_window_or_noninteractive_shell_is_rejected(self):
        self.process(20, 10, ["bash"], pgrp=20, env={"WINDOWID": None})
        self.assertIsNone(agents.window_terminal(10, 900)[0])
        for args in (["bash", "-lc", "command"], ["bash", "script.sh"]):
            self.process(20, 10, args, pgrp=20)
            self.assertIsNone(agents.window_terminal(10, 900)[0])

    def test_only_exact_native_resume_bootstrap_may_use_interactive_command_string(self):
        from i3_session.agent_launch import RESUME_SCRIPT
        command = ["bash", "-ic", RESUME_SCRIPT, "i3-session-resume", "codex", ROOT_ID]
        self.process(20, 10, command, pgrp=20)
        context = agents.terminal_context(30)
        self.assertIsNotNone(context)
        self.process(20, 10, ["bash", "-i"], pgrp=20)
        self.assertEqual(agents.window_terminal(10, 900)[0], context)
        self.process(20, 10, ["bash", "--noprofile", "--rcfile", str(self.root / "fixture.bashrc"), *command[1:]], pgrp=20)
        self.assertEqual(agents.window_terminal(10, 900)[0], context)
        for bad_args in (["bash", "-ic", RESUME_SCRIPT + "\necho changed", *command[3:]],
                         [*command[:4], "unknown", ROOT_ID], [*command[:5], "not-a-uuid"],
                         ["bash", "--unknown", *command[1:]], ["bash", "--rcfile", "relative-file", *command[1:]]):
            with self.subTest(command=bad_args):
                self.process(20, 10, bad_args, pgrp=20)
                self.assertIsNone(agents.window_terminal(10, 900)[0])

    def test_codex_exact_writable_root_excludes_subagents_and_readonly_roots(self):
        path = self.codex_transcript()
        self.codex_transcript(OTHER_ID, fd=6, source={"subagent": {"thread_spawn": {"parent_thread_id": ROOT_ID}}}, parent=ROOT_ID)
        self.codex_transcript("019c7714-3b77-74d1-9866-e1f484aae2ac", fd=7, writable=False)
        result = agents.session_for_process(30, "codex", self.home / ".codex")
        self.assertEqual(result, {"session_id": ROOT_ID, "cwd": str(self.cwd), "transcript_path": str(path)})
        discovered = agents.discover_window(10, 900)
        self.assertEqual(discovered["binding"]["session_id"], ROOT_ID)
        self.assertEqual(discovered["binding"]["agent_pid"], 30)
        self.assertEqual(discovered["warnings"], [])

    def test_two_codex_root_writers_refuse_guessing(self):
        self.codex_transcript()
        self.codex_transcript(OTHER_ID, fd=6)
        self.assertIsNone(agents.session_for_process(30, "codex", self.home / ".codex"))
        self.process(40, 30, ["python", "hook"])
        self.assertIsNone(agents.hook_owner("codex", ROOT_ID, pid=40))

    def test_exec_source_and_stale_latest_file_never_become_native_root(self):
        self.codex_transcript(source="exec")
        self.assertIsNone(agents.session_for_process(30, "codex", self.home / ".codex"))
        self.assertIsNone(agents.discover_window(10, 900)["binding"])

    def test_codex_academic_namespace_is_retained(self):
        home = self.home / ".codex-academic"
        self.process(30, 20, ["/other/bin/codex"], env={"CODEX_HOME": str(home)})
        self.codex_transcript(home=home)
        result = agents.discover_window(10, 900)["binding"]
        self.assertEqual(result["launcher"], "codex-academic")
        self.assertEqual(result["config_home"], str(home))
        self.assertIsNone(agents.session_for_process(30, "codex", self.home / ".codex"))

    def test_claude_native_pid_metadata_not_transcript_contents_identifies_session(self):
        home, path = self.claude_metadata()
        self.assertEqual(agents.session_for_process(30, "claude", home),
                         {"session_id": ROOT_ID, "cwd": str(self.cwd), "transcript_path": str(path)})

    def test_claude_stale_pid_noninteractive_kind_and_duplicate_transcripts_are_rejected(self):
        for updates in ({"proc_start": "111"}, {"kind": "background"}, {"entrypoint": "sdk"}, {"pid": 99}):
            with self.subTest(updates=updates):
                home, _ = self.claude_metadata(**updates)
                self.assertIsNone(agents.session_for_process(30, "claude", home))
        home, _ = self.claude_metadata()
        duplicate = home / "projects/other" / f"{ROOT_ID}.jsonl"
        duplicate.parent.mkdir()
        duplicate.write_text("")
        self.assertIsNone(agents.session_for_process(30, "claude", home))

    def test_hook_owner_checks_actual_ancestor_session_and_refuses_subagent_uuid(self):
        self.codex_transcript()
        self.process(40, 30, ["python", "hook"], tty=0, pgrp=40, tpgid=-1)
        result = agents.hook_owner("codex", ROOT_ID, pid=40)
        self.assertEqual(result["pid"], 30)
        self.assertEqual(result["binding"]["session_id"], ROOT_ID)
        self.assertIsNone(agents.hook_owner("codex", OTHER_ID, pid=40))
        self.assertIsNone(agents.hook_owner("claude", ROOT_ID, pid=40))

    def test_hook_start_without_persisted_metadata_has_owner_but_no_binding(self):
        self.process(40, 30, ["python", "hook"])
        result = agents.hook_owner("codex", ROOT_ID, pid=40)
        self.assertEqual(result["pid"], 30)
        self.assertIsNone(result["binding"])

    def test_claude_pending_transcript_still_rejects_known_different_session_id(self):
        self.claude_metadata(transcript=False)
        self.process(40, 30, ["python", "hook"])
        self.assertIsNotNone(agents.hook_owner("claude", ROOT_ID, pid=40))
        self.assertIsNone(agents.hook_owner("claude", OTHER_ID, pid=40))

    def test_daemon_inherited_terminal_environment_is_not_foreground_ownership(self):
        self.process(30, 1, ["codex", "app-server"], tty=0, sid=30, pgrp=30, tpgid=-1)
        self.process(40, 30, ["python", "hook"])
        self.assertIsNone(agents.hook_owner("codex", ROOT_ID, pid=40))
        self.assertIsNone(agents.terminal_context(30))

    def test_native_noninteractive_modes_are_not_bootstrapped(self):
        self.codex_transcript()
        self.process(30, 20, ["codex", "-p", "auto", "exec", "prompt"])
        self.assertIsNone(agents.discover_window(10, 900)["binding"])
        self.claude_metadata()
        self.process(30, 20, ["claude", "--print", "prompt"])
        self.assertIsNone(agents.discover_window(10, 900)["binding"])

    def test_legacy_shell_local_session_followed_by_unsupported_tui_cannot_reuse_binding(self):
        self.codex_transcript()
        self.claude_metadata()
        modes = [
            ("codex", ["--remote", "unix:///private/socket"]),
            ("codex", ["resume", ROOT_ID, "--remote=unix:///private/socket"]),
            ("codex", ["-p", "auto", "agents"]),
            ("claude", ["attach", ROOT_ID]),
            ("claude", ["--model", "sonnet", "agents"]),
        ]
        for tool, args in modes:
            with self.subTest(tool=tool, args=args):
                self.process(30, 20, [tool])
                original = agents.discover_window(10, 900)
                self.assertEqual(original["binding"]["session_id"], ROOT_ID)
                self.process(30, 20, [tool, *args])
                unsupported = agents.discover_window(10, 900)
                self.assertEqual(unsupported["context"], original["context"])
                self.assertEqual(unsupported["pid"], 30)
                self.assertIsNone(unsupported["binding"])
                self.assertTrue(unsupported["warnings"])

    def test_background_and_nested_unsupported_agents_cannot_invalidate_foreground_session(self):
        self.codex_transcript()
        self.process(40, 20, ["codex", "--remote=unix:///private/socket"], pgrp=40)
        self.process(50, 30, ["claude", "attach", OTHER_ID])
        result = agents.discover_window(10, 900)
        self.assertEqual(result["binding"]["session_id"], ROOT_ID)
        self.assertEqual(result["warnings"], [])


if __name__ == "__main__":
    unittest.main()
