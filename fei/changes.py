"""Persistent byte snapshots for tool-managed changes; no Git checkout/reset."""
import base64
import difflib
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from fei import config

MAX_BYTES = 5 * 1024 * 1024

def directory():
    return config.WORKDIR / ".fei-changes"

def record_path(change_id):
    if not isinstance(change_id, str) or len(change_id) != 32 or any(c not in "0123456789abcdef" for c in change_id):
        raise ValueError("Invalid change ID")
    return directory() / f"{change_id}.json"

def save(record):
    directory().mkdir(parents=True, exist_ok=True)
    p = record_path(record["id"])
    temporary = p.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    temporary.replace(p)

def get_change(change_id):
    return json.loads(record_path(change_id).read_text(encoding="utf-8"))

def atomic_write(path, data, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".fei-change-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(data)
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def apply_change(path, updated, expected=None):
    path = Path(path).resolve()
    before = path.read_bytes() if path.exists() else None
    if expected is not None and before != expected:
        raise RuntimeError("File changed since reading; read it again")
    if len(updated) > MAX_BYTES or (before is not None and len(before) > MAX_BYTES):
        raise ValueError("Tracked writes are limited to 5 MiB")
    if before == updated:
        return None
    mode = stat.S_IMODE(path.stat().st_mode) if before is not None else None
    change_id = uuid4().hex
    record = {"id": change_id, "path": str(path), "created_at": datetime.now(timezone.utc).isoformat(), "status": "pending", "mode": mode,
              "before": base64.b64encode(before).decode() if before is not None else None,
              "after": base64.b64encode(updated).decode()}
    save(record)  # Keep original bytes before touching the target.
    current = path.read_bytes() if path.exists() else None
    if current != before:
        record["status"] = "failed"
        save(record)
        raise RuntimeError("File changed during editing")
    atomic_write(path, updated, mode)
    record["status"] = "applied"
    save(record)
    return change_id

def show_changes(change_id=""):
    if not change_id:
        records = [json.loads(p.read_text(encoding="utf-8")) for p in directory().glob("*.json")]
        records.sort(key=lambda item: item["created_at"])
        return "\n".join(f"{r['id']} {r['status']} {r['path']}" for r in records) or "No tracked changes"
    record = get_change(change_id)
    before = base64.b64decode(record["before"]) if record["before"] is not None else b""
    after = base64.b64decode(record["after"])
    diff = "".join(difflib.unified_diff([line + "\n" for line in before.decode("utf-8", errors="replace").splitlines()], [line + "\n" for line in after.decode("utf-8", errors="replace").splitlines()], fromfile=record["path"] + " (before)", tofile=record["path"] + " (after)"))
    return f"Change {change_id} [{record['status']}]\n{diff}\nFinal newline: before={before.endswith(bytes([10]))}, after={after.endswith(bytes([10]))}"  # Byte snapshots are authoritative for rollback.

def revert_change(change_id):
    record = get_change(change_id)
    if record["status"] != "applied":
        raise ValueError("Only an applied change can be reverted")
    path = Path(record["path"])
    after = base64.b64decode(record["after"])
    if not path.is_file() or path.read_bytes() != after:
        raise RuntimeError("File was modified after this change; refusing to overwrite newer content")
    if record["before"] is None:
        path.unlink()
    else:
        atomic_write(path, base64.b64decode(record["before"]), record["mode"])
    record["status"] = "reverted"
    record["reverted_at"] = datetime.now(timezone.utc).isoformat()
    save(record)
    return f"Reverted {change_id}: {path}"
