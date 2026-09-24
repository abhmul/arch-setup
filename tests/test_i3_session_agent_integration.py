"""Opt-in Kitty/PTY/session-hook test; never starts a real AI agent.

I3_SESSION_TEST_AGENTS=1 enables a private Xvfb/i3 display, an isolated shell rc,
and a compiled native fixture named codex. HOME is unchanged; user shell files
are never sourced.
"""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import uuid

import psutil
import pytest

from test_i3_session_desktop import eventually, isolated_i3
from i3_session import agent_launch, agent_process, apps, desktop
from i3_session.agent_sessions import Registry


FAKE_CODEX_SOURCE = r'''
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static void emit_hook(const char *payload) {
    pid_t child = fork();
    if (child < 0) exit(80);
    if (child == 0) {
        int input = open(payload, O_RDONLY);
        int output = open(getenv("I3_TEST_HOOK_OUTPUT"), O_WRONLY | O_CREAT | O_APPEND, 0600);
        if (input < 0 || output < 0) _exit(81);
        dup2(input, STDIN_FILENO);
        dup2(output, STDOUT_FILENO);
        execl(getenv("I3_TEST_PYTHON"), getenv("I3_TEST_PYTHON"),
              getenv("I3_TEST_CLI"), "--state-dir", getenv("I3_TEST_STATE"),
              "agent-hook", "--tool", "codex", (char *)NULL);
        _exit(82);
    }
    int status = 0;
    if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status)) exit(83);
}

int main(int argc, char **argv) {
    if (argc != 3 || strcmp(argv[1], "resume") || strcmp(argv[2], getenv("I3_TEST_SESSION_ID"))) return 84;
    int transcript = open(getenv("I3_TEST_TRANSCRIPT"), O_WRONLY | O_APPEND);
    if (transcript < 0) return 85;
    emit_hook(getenv("I3_TEST_START_PAYLOAD"));
    FILE *ready = fopen(getenv("I3_TEST_READY"), "w");
    if (!ready) return 86;
    fprintf(ready, "%ld\n", (long)getpid());
    fclose(ready);
    while (access(getenv("I3_TEST_EXIT"), F_OK) != 0) usleep(10000);
    emit_hook(getenv("I3_TEST_END_PAYLOAD"));
    close(transcript);
    FILE *ended = fopen(getenv("I3_TEST_ENDED"), "w");
    if (!ended) return 87;
    fputs(argv[2], ended);
    fclose(ended);
    return 0;
}
'''


@pytest.mark.skipif(os.environ.get("I3_SESSION_TEST_AGENTS") != "1",
                    reason="Opt in to isolated real-Kitty agent test with I3_SESSION_TEST_AGENTS=1")
def test_kitty_resume_bootstrap_tracks_exact_session_and_keeps_it_after_exit(isolated_i3):
    compiler, kitty = shutil.which("cc"), shutil.which("kitty")
    if not compiler or not kitty:
        pytest.skip("A C compiler and Kitty are required")
    client, _, _, _, path = isolated_i3
    assert os.environ["DISPLAY"] != ":0"
    assert os.environ["I3SOCK"] == str(path / "i3.sock")
    project = path / "project"
    project.mkdir()
    config_home = path / "fixture-codex-config"
    transcript_dir = config_home / "sessions"
    transcript_dir.mkdir(parents=True)
    session_id = str(uuid.uuid4())
    transcript = transcript_dir / f"rollout-{session_id}.jsonl"
    transcript.write_text(json.dumps({"type": "session_meta", "payload": {
        "id": session_id, "source": "cli", "cwd": str(project),
    }}) + "\n")
    state = path / "bookmarks"
    binding = {"tool": "codex", "launcher": "codex", "config_home": str(config_home),
               "session_id": session_id, "cwd": str(project), "transcript_path": str(transcript)}
    commands = path / "bin"
    commands.mkdir()
    fake_source = path / "fake-codex.c"
    fake_source.write_text(FAKE_CODEX_SOURCE)
    fake_codex = commands / "codex"
    subprocess.run([compiler, "-O0", "-Wall", "-Wextra", "-o", str(fake_codex), str(fake_source)], check=True)
    cli = Path(__file__).resolve().parents[1] / ".scripts/i3_session/cli.py"
    rcfile = path / "fixture.bashrc"
    launch_prefix = shlex.join([sys.executable, str(cli), "--state-dir", str(state),
                               "agent-launch", "--launcher", "codex", "--", str(fake_codex)])
    # Only this controlled function runs: no actual account wrapper, login,
    # shell startup, network request, or paid model session is involved.
    rcfile.write_text(f'codex() {{ {launch_prefix} "$@"; }}\nPS1="fixture$ "\n')
    fake_bash = commands / "bash"
    fake_bash.write_text('#!/bin/sh\nexec /bin/bash --noprofile --rcfile "$I3_TEST_RCFILE" "$@"\n')
    fake_bash.chmod(0o700)
    payload = {"session_id": session_id, "cwd": str(project), "transcript_path": str(transcript)}
    start_payload, end_payload = path / "start.json", path / "end.json"
    start_payload.write_text(json.dumps(dict(payload, hook_event_name="SessionStart", source="resume")))
    end_payload.write_text(json.dumps(dict(payload, hook_event_name="SessionEnd", reason="other")))
    ready, exit_file, ended = path / "ready", path / "please-exit", path / "ended"
    hook_output = path / "hook-stdout"
    environment = dict(os.environ)
    environment.update({
        "CODEX_HOME": str(config_home), "PATH": str(commands) + os.pathsep + environment["PATH"],
        "I3_TEST_RCFILE": str(rcfile), "I3_TEST_SESSION_ID": session_id, "I3_TEST_TRANSCRIPT": str(transcript),
        "I3_TEST_PYTHON": sys.executable, "I3_TEST_CLI": str(cli), "I3_TEST_STATE": str(state),
        "I3_TEST_START_PAYLOAD": str(start_payload), "I3_TEST_END_PAYLOAD": str(end_payload),
        "I3_TEST_READY": str(ready), "I3_TEST_EXIT": str(exit_file), "I3_TEST_ENDED": str(ended),
        "I3_TEST_HOOK_OUTPUT": str(hook_output), "LIBGL_ALWAYS_SOFTWARE": "1",
    })
    for variable, leaf in (("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"), ("XDG_DATA_HOME", "data")):
        directory = path / leaf
        directory.mkdir()
        environment[variable] = str(directory)
    log = (path / "kitty.log").open("w")
    resume = agent_launch.resume_command(binding)
    resume[0] = str(fake_bash)
    process = subprocess.Popen([kitty, "--config", "NONE", "--directory", str(project),
                                "-o", "shell_integration=disabled", "-o", "confirm_os_window_close=0",
                                *resume], env=environment, stdout=log, stderr=log, start_new_session=True)
    tracked = {}

    def remember_processes():
        try:
            root = psutil.Process(process.pid)
            for child in [root, *root.children(recursive=True)]:
                tracked[(child.pid, child.create_time())] = child
        except psutil.Error:
            pass

    try:
        eventually(ready.exists, timeout=15)
        remember_processes()
        native_pid = int(ready.read_text())
        node = eventually(lambda: next((node for node in desktop._windows(client.query("get_tree"))
                                        if node.get("window_properties", {}).get("class", "").casefold() == "kitty"), None))
        context, warnings = agent_process.window_terminal(process.pid, node["window"])
        assert context is not None and warnings == []
        shell = agent_process.process_info(context["shell_pid"])
        assert shell["ppid"] == process.pid
        assert "-ic" in shell["argv"]
        assert agent_process.session_for_process(native_pid, "codex", config_home)["session_id"] == session_id
        # Check the hook result before capture could populate its own fallback.
        registered, warnings = Registry(state).lookup(context)
        assert registered is not None and registered["session_id"] == session_id
        assert warnings == []
        live = apps.capture_window(node, {"_state_dir": str(state)})
        assert live["agent_session"]["session_id"] == session_id
        assert "agent-resume" in live["command"]
        original_binding_id = live["agent_session"]["binding_id"]
        exit_file.touch()
        eventually(ended.exists, timeout=10)
        eventually(lambda: agent_process.process_info(native_pid) is None, timeout=5)
        assert ended.read_text() == session_id
        assert process.poll() is None  # The original Kitty shell remains usable.
        new_context, warnings = agent_process.window_terminal(process.pid, node["window"])
        assert new_context == context and warnings == []
        closed = apps.capture_window(node, {"_state_dir": str(state)})
        assert closed["agent_session"]["session_id"] == session_id
        assert closed["agent_session"]["binding_id"] == original_binding_id
        assert closed["command"] == live["command"]
        assert hook_output.read_bytes() == b""
    finally:
        remember_processes()
        for child in reversed(list(tracked.values())):
            try:
                child.terminate()
            except psutil.Error:
                pass
        _, alive = psutil.wait_procs(list(tracked.values()), timeout=3)
        for child in alive:
            try:
                child.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(alive, timeout=3)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        log.close()
