"""工具注册表：一个工具一个文件，加新工具 = 新建文件 + 这里 register 一行。"""
from fei.tools import bash, read, write, edit, search, compact, changes, finish, discovery, verify, plan
from fei.tools.base import Tool

REGISTRY: dict = {}


def register(tool: Tool) -> None:
    if tool.name in REGISTRY:
        raise ValueError(f"工具重名: {tool.name}")
    if tool.source is None:
        tool.parameters.setdefault("additionalProperties", False)
        for key, definition in tool.parameters.get("properties", {}).items():
            if key in {"path", "command", "old_text", "pattern"}:
                definition.setdefault("minLength", 1)
    REGISTRY[tool.name] = tool


register(bash.tool)
register(read.tool)
register(write.tool)
register(edit.tool)
register(search.tool)
register(compact.tool)
register(changes.show_tool)
register(changes.revert_tool)
register(finish.tool)
register(discovery.list_tool)
register(discovery.find_tool)
register(verify.tool)
register(plan.tool)


def schemas() -> list:
    return [t.schema() for t in REGISTRY.values()]
