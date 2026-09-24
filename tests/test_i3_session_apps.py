"""Launch recipes must preserve folders/profiles without replaying live jobs."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".scripts"))
from i3_session import apps


def window(window_class, title="", **properties):
    return {"window": 123, "window_properties": {"class": window_class, "title": title, **properties}}


class ApplicationCaptureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="i3-session-test-", dir=Path(__file__).parent)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_browser_retains_profile_and_drops_unsafe_or_unrelated_flags(self):
        args = ["/usr/lib/chromium/chromium", "--user-data-dir", "/home/a/profile with spaces", "--remote-debugging-port=9222", "--profile-directory=Profile 2", "https://private.example/path", "--load-extension=/some/path"]
        with patch.object(apps, "_window_pid", return_value=20), patch.object(apps, "_process_args", return_value=args):
            result = apps.capture_window(window("Chromium"), {})
        self.assertEqual(result["command"], ["chromium", "--user-data-dir", "/home/a/profile with spaces", "--profile-directory=Profile 2", "--remote-debugging-port=9222", "--new-window", "about:blank"])
        self.assertEqual(result["cold_command"], ["chromium", "--user-data-dir", "/home/a/profile with spaces", "--profile-directory=Profile 2", "--remote-debugging-port=9222"])
        self.assertTrue(result["reuse_new_windows"])

    def test_firefox_named_profile_and_no_page_urls(self):
        with patch.object(apps, "_window_pid", return_value=20), patch.object(apps, "_process_args", return_value=["firefox", "-P", "Work profile", "--private-window", "https://private.example"]):
            result = apps.capture_window(window("firefox"), {})
        self.assertEqual(result["command"], ["firefox", "-P", "Work profile", "--new-window", "about:blank"])
        self.assertEqual(result["cold_command"], ["firefox", "-P", "Work profile"])
        self.assertTrue(result["reuse_new_windows"])

    def test_chromium_flattened_process_title_uses_wm_class_profile_without_word_splitting(self):
        path = "/home/a/profile with (parentheses) and spaces"
        args = [f"/usr/lib/chromium/chromium --user-data-dir={path} --remote-debugging-port=9222 about:blank"]
        with patch.object(apps, "_window_pid", return_value=20), patch.object(apps, "_process_args", return_value=args):
            result = apps.capture_window(window("Chromium", instance=f"chromium ({path})"), {})
        self.assertEqual(result["command"], ["chromium", f"--user-data-dir={path}", "--remote-debugging-port=9222", "--new-window", "about:blank"])
        self.assertEqual(result["cold_command"], ["chromium", f"--user-data-dir={path}", "--remote-debugging-port=9222"])
        self.assertEqual(result["warnings"], [])

    def test_chromium_debug_flags_survive_structured_and_flattened_argv(self):
        profile = "/home/a/profile with spaces"
        for flattened in (False, True):
            for separate in (False, True):
                with self.subTest(flattened=flattened, separate=separate):
                    debug = (["--remote-debugging-port", "19321", "--remote-debugging-address", "127.0.0.1"]
                             if separate else ["--remote-debugging-port=19321", "--remote-debugging-address=127.0.0.1"])
                    args = ["chromium", f"--user-data-dir={profile}", *debug, "--remote-allow-origins=*", "--load-extension=/unsafe", "https://private.example"]
                    if flattened:
                        args = [" ".join(args)]
                    with patch.object(apps, "_window_pid", return_value=20), patch.object(apps, "_process_args", return_value=args):
                        result = apps.capture_window(window("Chromium", instance=f"chromium ({profile})"), {})
                    cold = ["chromium", f"--user-data-dir={profile}", "--remote-debugging-port=19321", "--remote-debugging-address=127.0.0.1"]
                    self.assertEqual(result["cold_command"], cold)
                    self.assertEqual(result["command"], cold + ["--new-window", "about:blank"])
                    self.assertEqual(result["warnings"], [])

    def test_chromium_does_not_introduce_absent_debug_flags(self):
        for args in ([], ["chromium"], ["chromium", "--no-first-run"], ["chromium --no-first-run about:blank"]):
            with self.subTest(args=args):
                self.assertEqual(apps._chromium_debug_args(args), ([], []))

    def test_chromium_invalid_missing_or_conflicting_ports_are_omitted(self):
        cases = [
            ["--remote-debugging-port"], ["--remote-debugging-port="],
            ["--remote-debugging-port=0"], ["--remote-debugging-port=65536"],
            ["--remote-debugging-port=-1"], ["--remote-debugging-port=12;touch"],
            ["--remote-debugging-port=1.5"], ["--remote-debugging-port=123x"],
            ["--remote-debugging-port=9222", "--remote-debugging-port=9223"],
            ["--remote-debugging-address=127.0.0.1"],
            ["--remote-debugging-port", "--remote-debugging-address=127.0.0.1"],
        ]
        for flags in cases:
            for flattened in (False, True):
                args = ["chromium", *flags]
                if flattened:
                    args = [" ".join(args)]
                with self.subTest(args=args):
                    debug, warnings = apps._chromium_debug_args(args)
                    self.assertEqual(debug, [])
                    self.assertTrue(warnings)

    def test_chromium_debug_address_is_validated_as_loopback(self):
        for address in ("127.0.0.1", "127.2.3.4", "::1", "localhost"):
            with self.subTest(address=address):
                debug, warnings = apps._chromium_debug_args(["chromium", "--remote-debugging-port=43123", f"--remote-debugging-address={address}"])
                self.assertEqual(debug, ["--remote-debugging-port=43123", f"--remote-debugging-address={address}"])
                self.assertEqual(warnings, [])
        for flags in (["--remote-debugging-address=0.0.0.0"], ["--remote-debugging-address=example.com"],
                      ["--remote-debugging-address=127.0.0.1;touch"], ["--remote-debugging-address="],
                      ["--remote-debugging-address=127.0.0.1", "--remote-debugging-address=::1"]):
            for flattened in (False, True):
                args = ["chromium", "--remote-debugging-port=43123", *flags]
                with self.subTest(flags=flags, flattened=flattened):
                    debug, warnings = apps._chromium_debug_args([" ".join(args)] if flattened else args)
                    self.assertEqual(debug, [])
                    self.assertTrue(warnings)

    def test_chromium_identical_repeated_debug_flags_are_unambiguous(self):
        args = ["chromium", "--remote-debugging-port=9222", "--remote-debugging-port=9222",
                "--remote-debugging-address=127.0.0.1", "--remote-debugging-address=127.0.0.1"]
        expected = (["--remote-debugging-port=9222", "--remote-debugging-address=127.0.0.1"], [])
        self.assertEqual(apps._chromium_debug_args(args), expected)
        self.assertEqual(apps._chromium_debug_args([" ".join(args)]), expected)

    def test_chromium_does_not_treat_flags_inside_profile_path_as_debug_options(self):
        profile = "/home/a/profile --remote-debugging-port=45111"
        args = [f"chromium --user-data-dir={profile} --remote-debugging-port=19321 --remote-debugging-address=127.0.0.1 about:blank"]
        with patch.object(apps, "_window_pid", return_value=20), patch.object(apps, "_process_args", return_value=args):
            result = apps.capture_window(window("Chromium", instance=f"chromium ({profile})"), {})
        self.assertIn(f"--user-data-dir={profile}", result["cold_command"])
        self.assertIn("--remote-debugging-port=19321", result["cold_command"])
        self.assertNotIn("--remote-debugging-port=45111", result["cold_command"])
        self.assertEqual(result["warnings"], [])

    def test_invalid_chromium_profile_cannot_enable_cold_launch_or_reuse(self):
        with patch.object(apps, "_window_pid", return_value=None):
            result = apps.capture_window(window("Chromium", instance="chromium (relative-profile)"), {})
        self.assertIsNone(result["command"])
        self.assertNotIn("cold_command", result)
        self.assertNotIn("reuse_new_windows", result)

    def test_custom_browser_rule_does_not_implicitly_allow_native_window_reuse(self):
        for app in ("firefox", "Chromium"):
            with self.subTest(app=app):
                result = apps.capture_window(window(app), {"applications": [{"class": app, "command": ["custom-browser"]}]})
                self.assertEqual(result["command"], ["custom-browser"])
                self.assertNotIn("cold_command", result)
                self.assertNotIn("reuse_new_windows", result)

    def test_unknown_application_does_not_replay_its_process(self):
        with patch.object(apps, "_window_pid") as process:
            result = apps.capture_window(window("unknown-app"), {})
        process.assert_not_called()
        self.assertIsNone(result["command"])
        self.assertTrue(result["warnings"])

    def test_explicit_rule_preserves_literal_argv(self):
        command = ["program", "$(touch should-not-exist)", "a; b", "two words"]
        result = apps.capture_window(window("Known"), {"applications": [{"class": "Known", "command": command, "cwd": str(self.root)}]})
        self.assertEqual(result["command"], command)
        self.assertEqual(result["cwd"], str(self.root))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_custom_rule_rejects_shell_string_and_relative_cwd(self):
        for rule in [{"class": "Known", "command": "program --arg"}, {"class": "Known", "command": ["program"], "cwd": "relative"}]:
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                apps.capture_window(window("Known"), {"applications": [rule]})

    def test_code_marker_recovers_directory_with_spaces_brackets_and_shell_characters(self):
        folder = self.root / "project [old] ; literal"
        folder.mkdir()
        title = f"README - Code [i3-session:{folder}] [i3-session-remote:]"
        result = apps.capture_window(window("Code", title), {})
        self.assertEqual(result["command"], ["code", "--new-window", str(folder)])
        self.assertEqual(result["cwd"], str(folder))
        self.assertEqual(result["warnings"], [])

    def test_code_missing_or_remote_marker_never_guesses(self):
        for title in ["project - Code", f"project [i3-session:{self.root}]", f"project [i3-session:{self.root}] [i3-session-remote:SSH:server]"]:
            with self.subTest(title=title):
                result = apps.capture_window(window("Code", title), {})
                self.assertEqual(result["command"], ["code", "--new-window"])
                self.assertTrue(result["warnings"])

    def test_code_workspace_file_is_supported_but_untitled_workspace_is_not(self):
        for name, expected in [("saved.code-workspace", True), ("workspace.json", False)]:
            target = self.root / name
            target.write_text("{}")
            title = f"Code [i3-session:{target}] [i3-session-remote:]"
            result = apps.capture_window(window("Code", title), {})
            self.assertEqual(str(target) in result["command"], expected)

    @patch("i3_session.agent_launch.capture_agent", return_value=(None, []))
    def test_kitty_uses_matching_shell_directory_and_does_not_relaunch_job(self, _agent_capture):
        child_dirs = {10: str(self.root), 11: str(self.root / "project"), 12: str(self.root / "other")}
        with patch.object(apps, "_window_pid", return_value=10), patch.object(apps, "_process_args", side_effect=lambda pid: {10: ["kitty", "dangerous-job"], 11: ["bash"], 12: ["bash"]}[pid]), patch.object(apps, "_process_cwd", side_effect=child_dirs.get), patch.object(Path, "read_text", return_value="11 12"), patch.object(Path, "read_bytes", side_effect=lambda: b"WINDOWID=123\0"):
            result = apps.capture_window(window("kitty"), {})
        # Distinct tab directories are ambiguous, so the process cwd is used.
        self.assertEqual(result["command"], ["kitty", "--directory", str(self.root)])
        self.assertTrue(result["warnings"])
        with patch.object(apps, "_window_pid", return_value=10), patch.object(apps, "_process_args", side_effect=lambda pid: ["kitty"] if pid == 10 else ["bash"]), patch.object(apps, "_process_cwd", side_effect=child_dirs.get), patch.object(Path, "read_text", return_value="11"), patch.object(Path, "read_bytes", return_value=b"WINDOWID=123\0"):
            result = apps.capture_window(window("kitty"), {})
        self.assertEqual(result["command"], ["kitty", "--directory", child_dirs[11]])
        self.assertEqual(result["warnings"], [])

    def test_obsidian_vault_uri_is_exact_and_duplicate_names_are_not_guessed(self):
        metadata = self.root / "obsidian.json"
        metadata.write_text(json.dumps({"vaults": {"vault&one": {"path": "/one/my-vault"}}}))
        config = {"obsidian_config": str(metadata)}
        result = apps.capture_window(window("md.obsidian.Obsidian", "note - my-vault - Obsidian 1.13.7"), config)
        self.assertEqual(result["command"], ["obsidian", "obsidian://open?vault=vault%26one"])
        metadata.write_text(json.dumps({"vaults": {"one": {"path": "/one/my-vault"}, "two": {"path": "/two/my-vault"}}}))
        self.assertIsNone(apps.capture_window(window("md.obsidian.Obsidian", "note - my-vault - Obsidian 1.13.7"), config)["command"])


if __name__ == "__main__":
    unittest.main()
