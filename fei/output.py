"""Keep complete tool results on disk and head/tail previews in context."""
from pathlib import Path
from uuid import uuid4
from fei import config


def store_output(text: str) -> str:
    directory = config.WORKDIR / ".fei-results"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid4().hex}.txt"
    path.write_text(text, encoding="utf-8")
    return str(path.resolve())


def prepare_output(text: str, writer=None, limit=None):
    limit = config.MAX_TOOL_OUTPUT if limit is None else limit
    if len(text) <= limit:
        return text, None
    path = (writer or store_output)(text)
    marker = f"\n[Output preview; full result: {path}. Use read_file with offset/limit for details.]\n"
    available = max(0, limit - len(marker))
    head = available // 2
    tail = available - head
    preview = text[:head] + marker + (text[-tail:] if tail else "")
    return preview, path
