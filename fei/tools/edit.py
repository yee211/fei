"""Exact replacement without rewriting unrelated file content."""
from fei.changes import apply_change
from fei.tools._paths import resolve
from fei.tools.base import Tool

MAX_EDIT_BYTES = 5 * 1024 * 1024

def _edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
    if not isinstance(old_text, str) or not old_text:
        raise ValueError("old_text must be a nonempty string")
    if not isinstance(new_text, str) or not isinstance(replace_all, bool):
        raise ValueError("new_text must be a string and replace_all must be boolean")
    p = resolve(path).resolve(strict=True)
    if not p.is_file():
        raise ValueError("edit_file requires an existing file")
    if p.stat().st_size > MAX_EDIT_BYTES:
        raise ValueError("File exceeds the 5 MiB editing limit")
    raw = p.read_bytes()
    if b"\x00" in raw:
        raise ValueError("Binary files cannot be edited")
    text = raw.decode("utf-8")
    # Accept model-generated LF snippets for consistently CRLF files.
    if "\r\n" in text and "\n" not in text.replace("\r\n", ""):
        old_text = old_text.replace("\r\n", "\n").replace("\n", "\r\n")
        new_text = new_text.replace("\r\n", "\n").replace("\n", "\r\n")
    count = text.count(old_text)
    if count == 0:
        raise ValueError("old_text was not found; read the file again before editing")
    if count > 1 and not replace_all:
        raise ValueError(f"old_text matches {count} times; provide more surrounding context or explicitly set replace_all=true")
    updated = text.replace(old_text, new_text, -1 if replace_all else 1).encode("utf-8")
    if updated == raw:
        return "No changes: replacement equals existing text"
    change_id = apply_change(p, updated, expected=raw)
    return f"Edited {p}: replaced {count if replace_all else 1} occurrence(s); change_id={change_id}"

tool = Tool(
    name="edit_file",
    description="Replace exact text in an existing UTF-8 file. Read first. Repeated matches fail unless replace_all=true; include context to select one occurrence. Preserves BOM and line endings. Use write_file for new files.",
    parameters={"type": "object", "properties": {
        "path": {"type": "string"},
        "old_text": {"type": "string", "description": "Exact existing text, without displayed line numbers"},
        "new_text": {"type": "string", "description": "Replacement text; empty string deletes the match"},
        "replace_all": {"type": "boolean", "description": "Explicitly replace all matches; defaults to false"},
    }, "required": ["path", "old_text", "new_text"], "additionalProperties": False},
    handler=_edit_file,
)
