from fei import config
from fei.tools._paths import resolve
from fei.tools.base import Tool


def _read_file(path: str, offset: int = 1, limit: int = 2000) -> str:
    p = resolve(path)
    # 目录/不存在用普通结果告诉模型怎么改，别抛异常让它瞎猜
    if p.is_dir():
        return f"{p} 是目录。read_file 只能读文件，列目录请用 run_bash 执行 ls。"
    if not p.exists():
        return f"文件不存在: {p}（相对路径基于工作目录）"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(offset - 1, 0)
    chunk = lines[start : start + limit]
    body = "\n".join(
        f"{n}\t{line}" for n, line in enumerate(chunk, start=start + 1)
    )
    return body or "(empty file)"


tool = Tool(
    name="read_file",
    description="读取文本文件（不能读目录），带行号。大文件可用 offset/limit 分段读。",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对工作目录或绝对路径）"},
            "offset": {"type": "integer", "minimum": 1, "description": "起始行（从 1 数），默认 1"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "description": "读取行数，默认 2000"},
        },
        "required": ["path"],
    },
    handler=_read_file,
)
