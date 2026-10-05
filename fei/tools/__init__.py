"""工具注册表：一个工具一个文件，加新工具 = 新建文件 + 这里 register 一行。"""
from fei.tools import bash, read, write, edit, search, compact, changes, finish, discovery, verify, plan, explore, skills, environment, delegate
from fei.tools.base import Tool
from contextvars import ContextVar

active_tool_names = ContextVar("fei_active_tool_names", default=None)

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
register(explore.tool)
register(skills.list_tool)
register(skills.load_tool)
register(environment.tool)
register(delegate.tool)
register(delegate.check_tool)
register(delegate.review_tool)


def schemas() -> list:
    allowed = active_tool_names.get()
    return [t.schema() for t in sorted(REGISTRY.values(), key=lambda tool: tool.name) if (allowed is None and t.name != "run_check") or (allowed is not None and t.name in allowed)]
