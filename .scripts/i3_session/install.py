"""Minimal, backed-up VS Code JSONC title integration for session capture."""

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile


DEFAULT_TITLE = "${dirty}${activeEditorShort}${separator}${rootName}${separator}${profileName}${separator}${appName}"
TITLE_MARKERS = ("[i3-session:${rootPath}]", "[i3-session-remote:${remoteName}]")


@dataclass(frozen=True)
class Token:
    kind: str
    start: int
    end: int
    value: object = None


def _parse_jsonc(text):
    """Validate JSONC while retaining token offsets into the original text."""
    tokens = []
    cleaned = list(text)
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(text):
        char = text[pos]
        if char.isspace():
            pos += 1
            continue
        if text.startswith("//", pos) or text.startswith("/*", pos):
            if text.startswith("//", pos):
                end = text.find("\n", pos)
                end = len(text) if end < 0 else end
            else:
                end = text.find("*/", pos + 2)
                if end < 0:
                    raise ValueError("Unterminated block comment in VS Code settings")
                end += 2
            for index in range(pos, end):
                if cleaned[index] not in "\r\n":
                    cleaned[index] = " "
            pos = end
            continue
        if char == '"':
            value, end = decoder.raw_decode(text, pos)
            tokens.append(Token("string", pos, end, value))
        elif char in "{}[],:":
            end = pos + 1
            tokens.append(Token(char, pos, end))
        else:
            match = re.match(r'[^\s{}\[\],:"/]+', text[pos:])
            if not match:
                raise ValueError(f"Invalid JSONC token at character {pos}")
            end = pos + len(match.group())
            tokens.append(Token("atom", pos, end))
        pos = end

    for index, token in enumerate(tokens):
        if (token.kind == "," and 0 < index < len(tokens) - 1
                and tokens[index + 1].kind in ("}", "]")
                and tokens[index - 1].kind in ("string", "atom", "}", "]")):
            cleaned[token.start] = " "

    def reject_constant(value):
        raise ValueError(f"Invalid JSON constant {value}")

    data = json.loads("".join(cleaned), parse_constant=reject_constant)
    if not isinstance(data, dict):
        raise ValueError("VS Code settings must be a JSON object")
    depth = 0
    properties = []
    for index, token in enumerate(tokens):
        if (depth == 1 and token.kind == "string" and index + 1 < len(tokens)
                and tokens[index + 1].kind == ":"):
            properties.append((token, tokens[index + 2]))
        if token.kind in ("{", "["):
            depth += 1
        elif token.kind in ("}", "]"):
            depth -= 1
    titles = [(key, value) for key, value in properties if key.value == "window.title"]
    if len(titles) > 1:
        raise ValueError("Duplicate top-level window.title in VS Code settings")
    if titles and titles[0][1].kind != "string":
        raise ValueError("VS Code window.title must be a string")
    return tokens, properties, titles


def _add_title(text, tokens, properties, title):
    closing = tokens[-1]
    value = '"window.title": ' + json.dumps(title, ensure_ascii=False)
    newline = "\r\n" if "\r\n" in text else "\n"
    first_key = properties[0][0] if properties else None
    indentation = "    "
    if first_key:
        candidate = text[text.rfind("\n", 0, first_key.start) + 1:first_key.start]
        if candidate and not candidate.strip():
            indentation = candidate
    edits = []
    if properties and tokens[-2].kind != ",":
        edits.append((tokens[-2].end, ","))
    if "\n" in text[tokens[0].end:closing.start]:
        line_start = text.rfind("\n", 0, closing.start) + 1
        if not text[line_start:closing.start].strip():
            edits.append((line_start, indentation + value + newline))
        else:
            edits.append((closing.start, newline + indentation + value + newline))
    else:
        # A newline also prevents a final // comment from swallowing the new key.
        edits.append((closing.start, newline + indentation + value + newline))
    # Apply the new key first when its insertion shares the comma's offset.
    for _, (offset, insertion) in sorted(enumerate(edits), key=lambda item: (item[1][0], item[0]), reverse=True):
        text = text[:offset] + insertion + text[offset:]
    return text


def _sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def configure_vscode(settings_path, backup_dir):
    """Append capture markers, preserving unrelated JSONC and the first backup.

    Returns paths and whether a change was made. Missing files are created;
    malformed existing files are rejected before creating any backup or edit.
    """
    path = Path(settings_path).expanduser().resolve()
    backup_dir = Path(backup_dir).expanduser().resolve()
    exists = path.exists()
    original = path.read_bytes() if exists else b"{}\n"
    bom = b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b""
    text = original[len(bom):].decode("utf-8")
    tokens, properties, titles = _parse_jsonc(text)
    if titles:
        token = titles[0][1]
        suffix = "".join(" " + marker for marker in TITLE_MARKERS if marker not in token.value)
        if not suffix:
            return {"changed": False, "settings_path": str(path), "backup_path": None}
        # Preserve the exact original string escapes, modifying only its suffix.
        replacement = text[token.start:token.end - 1] + json.dumps(suffix, ensure_ascii=False)[1:]
        updated = text[:token.start] + replacement + text[token.end:]
    else:
        updated = _add_title(text, tokens, properties, DEFAULT_TITLE + " " + " ".join(TITLE_MARKERS))
    _parse_jsonc(updated)
    backup = None
    if exists:
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(backup_dir, 0o700)
        digest = hashlib.sha256(os.fsencode(str(path))).hexdigest()[:16]
        backup = backup_dir / f"vscode-settings-{digest}.jsonc.bak"
        fd, pending_backup = tempfile.mkstemp(prefix=".incoming-backup-", dir=backup_dir)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Linking publishes a complete backup and refuses to replace an
                # existing first backup, including after interrupted installers.
                os.link(pending_backup, backup)
            except FileExistsError:
                if backup.is_symlink() or not backup.is_file():
                    raise ValueError(f"Unsafe existing settings backup: {backup}")
            else:
                _sync_directory(backup_dir)
        finally:
            os.unlink(pending_backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if exists else 0o600
    fd, temporary = tempfile.mkstemp(prefix=".i3-session-settings-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(bom + updated.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        # Avoid replacing edits made since the initial read.
        if (exists and path.read_bytes() != original) or (not exists and path.exists()):
            raise ValueError("VS Code settings changed during configuration; retry")
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"changed": True, "settings_path": str(path), "backup_path": str(backup) if backup else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure-vscode", type=Path, required=True, metavar="SETTINGS")
    parser.add_argument("--backup-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = configure_vscode(args.configure_vscode, args.backup_dir)
    except (ValueError, OSError, UnicodeError) as exc:
        parser.exit(1, f"i3-session: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
