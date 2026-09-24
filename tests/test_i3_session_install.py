"""Non-destructive checks for title integration and original-settings custody."""

import json
from pathlib import Path
import stat
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".scripts"))

from i3_session.install import DEFAULT_TITLE, TITLE_MARKERS, _parse_jsonc, configure_vscode
from i3_session import install


def settings(tmp_path, original):
    path = tmp_path / "Code" / "settings.json"
    path.parent.mkdir()
    path.write_bytes(original)
    return path, tmp_path / "backups"


def test_custom_title_preserves_every_other_byte_and_original_escapes(tmp_path):
    original = (b'{\r\n  // keep this comment\r\n  "other": [1, 2,],\r\n'
                b'  "window.title": "Custom \\u2603 // ${rootName}", // title\r\n}\r\n')
    path, backups = settings(tmp_path, original)
    path.chmod(0o640)
    result = configure_vscode(path, backups)
    added = (" " + " ".join(TITLE_MARKERS)).encode()
    assert path.read_bytes() == original.replace(b'${rootName}"', b'${rootName}' + added + b'"')
    assert Path(result["backup_path"]).read_bytes() == original
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert stat.S_IMODE(Path(result["backup_path"]).stat().st_mode) == 0o600
    assert stat.S_IMODE(backups.stat().st_mode) == 0o700


def test_idempotent_and_first_backup_is_never_overwritten(tmp_path):
    original = b'{"window.title": "first"}\n'
    path, backups = settings(tmp_path, original)
    first = configure_vscode(path, backups)
    updated = path.read_bytes()
    assert configure_vscode(path, backups)["changed"] is False
    assert path.read_bytes() == updated
    path.write_text('{"window.title": "second"}\n')
    assert configure_vscode(path, backups)["changed"] is True
    assert Path(first["backup_path"]).read_bytes() == original
    assert len(list(backups.iterdir())) == 1


@pytest.mark.parametrize("original", [
    b'{}\n', b'{ /* untouched */ }', b'{\n // untouched\n}\n',
    b'{"other": {"window.title": "nested"}}',
    b'{\n  "other": [1,2,], // untouched\n}\n',
    b'{\n  "other": false // untouched\n}\n',
    b'{"other": 1,}', b'\xef\xbb\xbf{\r\n\t"other": 1\r\n}\r\n',
])
def test_absent_title_with_comments_nested_values_and_trailing_commas(tmp_path, original):
    path, backups = settings(tmp_path, original)
    result = configure_vscode(path, backups)
    text = path.read_bytes().decode("utf-8-sig")
    _, _, titles = _parse_jsonc(text)
    assert titles[0][1].value == DEFAULT_TITLE + " " + " ".join(TITLE_MARKERS)
    assert Path(result["backup_path"]).read_bytes() == original
    assert path.read_bytes().startswith(b'\xef\xbb\xbf') == original.startswith(b'\xef\xbb\xbf')


@pytest.mark.parametrize("original", [
    b'', b'[]', b'{,}', b'{"x": [,]}', b'{"x": [1,,]}',
    b'{"x": true false}', b'{"x": NaN}', b'{"x": Infinity}',
    b'{"window.title": null}', b'{"window.title": 42}',
    b'{"window.title": "a", "window.title": "b"}',
    b'{"window.title": "a", "window\\u002etitle": "b"}',
    b'{"x": 1 /* never closed}', b'{"x": "bad\\q"}',
])
def test_invalid_or_ambiguous_settings_fail_without_changes(tmp_path, original):
    path, backups = settings(tmp_path, original)
    with pytest.raises(ValueError):
        configure_vscode(path, backups)
    assert path.read_bytes() == original
    assert not backups.exists()


def test_existing_one_marker_adds_only_missing_marker(tmp_path):
    path, backups = settings(tmp_path, json.dumps({"window.title": "name " + TITLE_MARKERS[0]}).encode())
    configure_vscode(path, backups)
    result = json.loads(path.read_text())["window.title"]
    assert result == "name " + " ".join(TITLE_MARKERS)


def test_new_settings_file_and_symlink_target(tmp_path):
    path = tmp_path / "new" / "settings.json"
    backups = tmp_path / "backups"
    result = configure_vscode(path, backups)
    assert result["backup_path"] is None
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    link = tmp_path / "settings-link.json"
    link.symlink_to(path)
    original = b'{"window.title": "via symlink"}'
    path.write_bytes(original)
    result = configure_vscode(link, backups)
    assert link.is_symlink()
    assert Path(result["backup_path"]).read_bytes() == original
    assert "via symlink" in path.read_text()


def test_backup_failure_leaves_settings_untouched(tmp_path, monkeypatch):
    original = b'{"window.title": "original"}\n'
    path, backups = settings(tmp_path, original)

    def fail_link(*_):
        raise OSError("backup publication failed")

    monkeypatch.setattr(install.os, "link", fail_link)
    with pytest.raises(OSError, match="backup publication"):
        configure_vscode(path, backups)
    assert path.read_bytes() == original
    assert not list(backups.iterdir())


def test_concurrent_settings_change_is_not_overwritten(tmp_path, monkeypatch):
    original = b'{"window.title": "original"}\n'
    concurrent = b'{"window.title": "edited elsewhere"}\n'
    path, backups = settings(tmp_path, original)
    real_sync = install._sync_directory

    def change_after_backup(directory):
        real_sync(directory)
        if directory == backups:
            path.write_bytes(concurrent)

    monkeypatch.setattr(install, "_sync_directory", change_after_backup)
    with pytest.raises(ValueError, match="changed during configuration"):
        configure_vscode(path, backups)
    assert path.read_bytes() == concurrent
    assert next(backups.glob("*.bak")).read_bytes() == original
    assert not list(path.parent.glob(".i3-session-settings-*"))
