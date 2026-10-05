import os
import subprocess
from pathlib import Path

from fei import config
from fei.permission import dangerous_command
from fei.tools.base import Tool
from fei.commands import run_command
from fei.task_state import current_task


def _run(command: str, timeout: float = 120, purpose: str = "command") -> str:
    if config.BASH_PATH:
        # Windows 的 shell=True 会把 cmd 风格的 /c 传给 bash，必须显式 bash -c
        argv = [config.BASH_PATH, "-c", command]
        # 用户终端的 PATH 里往往没有 Git 的工具目录，把 usr/bin 等补到最前，
        # 否则 bash 起来了 ls/cat/grep 也找不到
        bash_bin = Path(config.BASH_PATH).parent
        git_root = bash_bin.parent
        prepend = [bash_bin, git_root / "usr" / "bin", git_root / "bin", git_root / "cmd"]
        env = os.environ.copy()
        env["PATH"] = os.pathsep.join(str(p) for p in prepend) + os.pathsep + env.get("PATH", "")
    else:
        argv = command  # 无 bash 时退回系统默认 shell
        env = None
    task = current_task.get()
    proc = run_command(argv, shell=not config.BASH_PATH, cwd=config.WORKDIR,
                       env=env, timeout=timeout, progress=task.progress if task else None)
    output = (proc.stdout + proc.stderr).strip() or "(no output)"
    if proc.returncode != 0:
        raise RuntimeError(f"命令退出码 {proc.returncode}\n{output}")
    return output


def _guard(args: dict):
    return dangerous_command(args.get("command", ""))


tool = Tool(
    name="run_bash",
    description=(
        "在工作目录执行一条 bash 命令，返回合并的 stdout+stderr。"
        "列目录、看文件树等用 ls / find，不要用 read_file 读目录。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "timeout": {"type": "number", "minimum": 1, "maximum": 600, "description": "Timeout in seconds; default 120"},
            "purpose": {"type": "string", "enum": ["command", "verification"], "description": "Use verification for actual tests/checks referenced by finish_task"},
            "command": {"type": "string", "minLength": 1, "description": "要执行的 bash 命令"},
        },
        "required": ["command"],
    },
    handler=_run,
    guard=_guard,
)
