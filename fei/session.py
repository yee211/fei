"""会话持久化：每条消息一行 JSON（JSONL），存到 ~/.fei/sessions/。"""
import json
import time
from uuid import uuid4
from pathlib import Path

SESSIONS_DIR = Path.home() / ".fei" / "sessions"


class Session:
    def __init__(self) -> None:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self.path = SESSIONS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}.jsonl"

    def append(self, message: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    @property
    def state_path(self) -> Path:
        return self.path.with_suffix(".state.json")

    def save_state(self, messages: list) -> None:
        """保存实际运行上下文，与完整原始记录分开。"""
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.state_path)

    @staticmethod
    def load_state(path) -> list:
        p = Path(path)
        state = p.with_suffix(".state.json") if p.suffix == ".jsonl" else p
        if not state.is_file():
            raise ValueError("没有会话状态文件，无法准确恢复；请选择新版保存的会话。")
        messages = json.loads(state.read_text(encoding="utf-8"))
        if not isinstance(messages, list) or not messages:
            raise ValueError("会话状态必须是非空消息列表")
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}:
                raise ValueError("会话状态包含无效消息")
        pending = set()
        for message in messages:
            if message["role"] == "tool":
                call_id = message.get("tool_call_id")
                if call_id not in pending:
                    raise ValueError("会话状态包含未配对的工具结果")
                pending.remove(call_id)
            else:
                if pending:
                    raise ValueError("会话状态包含未完成的工具调用，不能直接恢复")
                calls = message.get("tool_calls", [])
                for call in calls:
                    call_id = call.get("id")
                    if not call_id or call_id in pending:
                        raise ValueError("会话状态包含无效工具调用 ID")
                    pending.add(call_id)
        if pending:
            raise ValueError("会话状态包含未完成的工具调用，不能直接恢复")
        return messages

    @staticmethod
    def load(path) -> list:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]


    def append_task(self, record: dict) -> None:
        """Append evidence independently of compressed conversation memory."""
        path = self.path.with_suffix(".tasks.jsonl")
        with path.open("a", encoding="utf-8") as target:
            target.write(json.dumps(record, ensure_ascii=False) + "\n")


    def store_output(self, text: str) -> str:
        directory = self.path.with_suffix(".outputs")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{uuid4().hex}.txt"
        path.write_text(text, encoding="utf-8")
        return str(path.resolve())


    def append_permission(self, record: dict) -> None:
        """Audit decisions separately; never restore grants from model context."""
        path = self.path.with_suffix(".permissions.jsonl")
        with path.open("a", encoding="utf-8") as target:
            target.write(json.dumps({"time": time.time(), **record}, ensure_ascii=False) + "\n")


    @staticmethod
    def load_latest_task(path):
        source = Path(path)
        tasks = source.with_suffix(".tasks.jsonl") if source.suffix == ".jsonl" else source.with_name(source.name.removesuffix(".state.json") + ".tasks.jsonl")
        if not tasks.is_file():
            return None
        # Seek from end: loading status must not scan an entire long session.
        with tasks.open("rb") as target:
            target.seek(0, 2)
            cursor = target.tell()
            tail = b""
            while cursor > 0 and len(tail) < 8 * 1024 * 1024:
                count = min(8192, cursor)
                cursor -= count
                target.seek(cursor)
                tail = target.read(count) + tail
                lines = tail.rstrip().split(b"\n")
                if len(lines) > 1 or cursor == 0:
                    value = json.loads(lines[-1].decode("utf-8")) if lines and lines[-1] else None
                    return value if isinstance(value, dict) else None
        raise ValueError("Latest task record exceeds 8 MiB")
