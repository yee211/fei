from fei.tools._paths import resolve
from fei.tools.base import Tool
from fei.changes import apply_change


def _write_file(path: str, content: str) -> str:
    p = resolve(path)
    change_id = apply_change(p, content.encode("utf-8"))
    return f"已写入 {p}（{len(content)} 字符）；change_id={change_id}" if change_id else "No changes"


tool = Tool(
    name="write_file",
    description="把完整内容写入文件（覆盖），父目录不存在时自动创建。",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目标文件路径"},
            "content": {"type": "string", "description": "完整文件内容"},
        },
        "required": ["path", "content"],
    },
    handler=_write_file,
)
