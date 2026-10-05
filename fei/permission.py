"""安全闸门：危险命令硬拦截（本项目当前唯一的安全机制）。

纯函数、可单测；由 bash.py 的 guard 挂到 run_bash 上。
命中即拒绝、不交互确认，拒绝原因会作为工具结果喂回模型。
"""
import os
import re

# 命中即拒绝（宁可误杀，可 FEI_ALLOW_DANGEROUS=1 关闭）
DANGEROUS_RES = (
    re.compile(r"rm\s+(-\w+\s+)+/\s*$"),  # rm -rf /（根目录本身）
    re.compile(r"rm\s+(-\w+\s+)+/\*"),    # rm -rf /*
    re.compile(r"rm\s+(-\w+\s+)+~\s*$"),  # rm -rf ~
)
DANGEROUS_SUBSTR = (
    "mkfs", "dd if=", ":(){", "> /dev/sd",
    "shutdown", "reboot", "diskpart",
    "format c:", "rd /s /q c:", "del /f /s /q c:",
)


def dangerous_command(command: str) -> str | None:
    """命中返回原因，否则 None。"""
    if os.environ.get("FEI_ALLOW_DANGEROUS") == "1":
        return None
    low = command.lower()
    for pattern in DANGEROUS_RES:
        if pattern.search(low):
            return f"命中危险命令模式: {pattern.pattern}"
    for sub in DANGEROUS_SUBSTR:
        if sub in low:
            return f"命中危险命令关键词: {sub}"
    return None


def permission_request(tool, args) -> str | None:
    """Return a full reviewable description when execution requires approval."""
    import json
    from fei import config
    from fei.tools._paths import resolve
    name = tool.name
    if tool.source is not None:
        return f"MCP 工具来源：{tool.source}\n参数：{json.dumps(args, ensure_ascii=False)}"
    if name == "delegate_task":
        from fei.delegation import plan, description
        from fei.task_state import current_task
        value = plan(**args)
        state = current_task.get()
        if state is not None:
            state.delegation_plan = value
        return description(value)
    if name == "verify_project":
        from fei.project_verify import load_plan, plan_description
        from fei.task_state import current_task
        plan=load_plan(args.get("checks"))
        task=current_task.get()
        if task is not None:task.verification_plan=plan
        return plan_description(plan)
    if name == "review_worker":
        if args.get("decision") == "accept":
            return None
        from fei.delegation import worker_record
        value = worker_record(args["subtask_id"])
        return "撤销子任务的已记录改动：" + json.dumps(value["handoff"]["changes"], ensure_ascii=False)
    if name == "revert_change":
        from fei.changes import get_change
        record = get_change(args.get("change_id", ""))
        return f"回退修改：{record['id']}\n文件：{record['path']}\n操作：{'恢复原内容' if record['before'] is not None else '删除本工具创建的文件'}"
    if name == "run_bash":
        return f"工作目录：{config.WORKDIR}\n命令：{args.get('command', '')}"
    if name in {"write_file", "edit_file"}:
        path = resolve(args.get("path", "")).resolve()
        if name == "edit_file":
            return (f"文件：{path}\n批量替换：{args.get('replace_all', False)}"
                    f"\n原文：\n{args.get('old_text', '')}\n替换为：\n{args.get('new_text', '')}")
        return f"文件：{path}\n操作：{'覆盖' if path.exists() else '新建'}\n内容：\n{args.get('content', '')}"
    if name in {"read_file", "search_code", "list_directory", "find_files"}:
        path = resolve(args.get("path", ".")).resolve()
        if not path.is_relative_to(config.WORKDIR.resolve()):
            return f"访问工作目录外路径：{path}\n参数：{json.dumps(args, ensure_ascii=False)}"
    if tool.needs_permission or name not in {"read_file", "search_code", "compact_context", "show_changes", "finish_task", "update_plan", "explore_code", "list_skills", "load_skill", "get_environment", "run_check", "list_directory", "find_files"}:
        return json.dumps(args, ensure_ascii=False)
    return None


class TaskPermissions:
    """Interactive task grants; not a command sandbox."""
    def __init__(self, ask):
        self.ask = ask
        self.grants = set()

    def __call__(self, name, description):
        from pathlib import Path
        from fei.tools import REGISTRY
        destructive = name == "run_bash" and re.search(
            r"(?i)(?:\b(?:rm|rmdir|unlink|shred|remove-item|del|erase|drop|truncate|format|diskpart)\b|git\s+(?:clean|reset|checkout|restore)\b)", description)
        if name == "run_bash":
            key = ("shell",)
            scope = "本任务后续普通命令也将自动执行（拥有当前用户权限）；删除/回退命令仍逐次确认。"
        elif name in {"write_file", "edit_file"}:
            # Description comes from permission_request, after resolving the path.
            first_line = description.splitlines()[0]
            directory = str(Path(first_line.split("：", 1)[1]).parent.resolve())
            key = ("write", directory)
            scope = "本任务允许在此目录写入/编辑文件：" + directory
        else:
            key = None
            scope = "仅允许本次调用。"
        tool = REGISTRY.get(name)
        if tool is not None and tool.source is not None:
            key = None
            scope = "仅允许本次外部工具调用。"
        if key is not None and not destructive and key in self.grants:
            return True
        if destructive:
            scope = "此命令包含删除或回退操作，仅允许本次调用。"
        allowed = self.ask(name, description + "\n授权范围：" + scope)
        if allowed and key is not None and not destructive:
            self.grants.add(key)
        return allowed


from dataclasses import dataclass

@dataclass(frozen=True)
class PermissionDecision:
    kind: str
    reason: str
    scope: tuple | None = None
    remember: bool = True

class PermissionPolicy:
    MODES = {"read", "auto", "full"}
    READ_TOOLS = {"read_file", "search_code", "list_directory", "find_files", "show_changes", "compact_context", "update_plan", "finish_task", "explore_code", "list_skills", "load_skill", "get_environment"}

    def __init__(self, mode="auto"):
        self.set_mode(mode)

    def set_mode(self, mode):
        if mode not in self.MODES:
            raise ValueError("权限模式必须为 read / auto / full")
        self.mode = mode

    def decide(self, tool, args, description):
        from fei import config
        from fei.tools._paths import resolve
        name = tool.name
        if self.mode == "read" and (tool.source is not None or name not in self.READ_TOOLS or tool.needs_permission):
            return PermissionDecision("deny", "read 模式禁止命令、写入和外部工具")
        if self.mode == "full":
            return PermissionDecision("allow", "用户选择 full 模式")
        if tool.source is not None:
            return PermissionDecision("ask", "外部工具授权（当前用户权限）", ("mcp", tool.source, name))
        if name in {"write_file", "edit_file", "read_file", "search_code", "list_directory", "find_files"}:
            path = resolve(args.get("path", ".")).resolve()
            if path.is_relative_to(config.WORKDIR.resolve()):
                return PermissionDecision("allow", "工作区内操作")
            directory = path if name in {"search_code", "list_directory", "find_files"} or path.is_dir() else path.parent
            kind = "write" if name in {"write_file", "edit_file"} else "read"
            return PermissionDecision("ask", "工作区外目录及其子目录：" + str(directory), (kind, str(directory)))
        if name == "run_bash":
            destructive = re.search(r"(?i)(?:\b(?:rm|rmdir|unlink|shred|remove-item|del|erase|drop|truncate|format|diskpart)\b|git\s+(?:clean|reset|checkout|restore)\b)", args.get("command", ""))
            if destructive:
                return PermissionDecision("ask", "删除或回退命令仅允许一次", None, False)
            return PermissionDecision("ask", "本会话普通 shell 命令（当前用户权限，包含网络访问）", ("shell",))
        if name == "verify_project":
            import hashlib
            return PermissionDecision("ask", "此组准确项目验证命令", ("verify", hashlib.sha256(description.encode()).hexdigest()))
        if description is None:
            return PermissionDecision("allow", "内部或只读操作")
        return PermissionDecision("ask", "仅允许本次调用", None, False)
