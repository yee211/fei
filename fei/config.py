"""最底层模块：只读环境变量与路径，不被其他 fei 模块反向依赖。"""
import os
import shutil
from pathlib import Path


def _load_dotenv() -> None:
    """极简 .env 解析，避免引入 python-dotenv 依赖。"""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()

API_KEY = os.environ.get("FEI_API_KEY", "")
BASE_URL = os.environ.get("FEI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
MODEL = os.environ.get("FEI_MODEL", "glm-4.6")
WORKDIR = Path(os.environ.get("FEI_WORKDIR", ".")).resolve()
MAX_TURNS = int(os.environ.get("FEI_MAX_TURNS", "30"))
MAX_TOOL_OUTPUT = 8000
# prompt tokens 超过该值就在任务边界压缩历史（Step 4）
COMPACT_TOKENS = int(os.environ.get("FEI_COMPACT_TOKENS", "48000"))
# 是否流式输出（1 开 / 0 关，Step 5）
STREAM = os.environ.get("FEI_STREAM", "1") != "0"
# 1 = 控制台显示完整工具过程（默认只显示最终回答与错误）
VERBOSE = os.environ.get("FEI_VERBOSE", "") == "1"


def _git_install_dirs():
    """从注册表读 Git for Windows 的安装目录（不依赖 PATH）。"""
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    installs = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for access in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\GitForWindows", 0, access) as key:
                    value, _ = winreg.QueryValueEx(key, "InstallPath")
                    installs.append(Path(value))
            except OSError:
                continue
    return installs


def _portable_git_roots():
    """Git 不在 PATH 也不在注册表（便携解压版）时，扫常见安装位置。"""
    if os.name != "nt":
        return []
    drives = [f"{c}:\\" for c in "CDEFGH" if Path(f"{c}:\\").exists()]
    subdirs = (
        "Program Files/Git", "Program Files (x86)/Git",
        "Git", "utils/Git", "tools/Git", "soft/Git", "apps/Git",
    )
    return [
        Path(drive) / sub
        for drive in drives
        for sub in subdirs
        if (Path(drive) / sub).is_dir()
    ]


def _find_bash():
    """探测可用的 bash。

    Windows 的坑：C:\\Windows\\System32\\bash.exe 是 WSL 启动器，PATH 上
    往往排在 Git Bash 前面，没装发行版时执行只报 WSL ERROR。所以顺序是：
    FEI_BASH 显式指定 > 注册表 GitForWindows > git.exe 推导 > 便携版常见
    位置扫描 > PATH 扫描 > PATH 上的 bash（排除 system32）。
    返回 None 则退回系统默认 shell。
    """
    override = os.environ.get("FEI_BASH")
    if override and os.path.isfile(override):
        return override

    roots = list(_git_install_dirs())
    git = shutil.which("git")
    if git:
        roots.append(Path(git).resolve().parent.parent)  # <Git>/cmd/git.exe → <Git>
    roots += _portable_git_roots()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry.strip():
            p = Path(entry)
            roots += [p, p.parent]  # PATH 里的 <Git>/cmd → 顺便试 <Git>

    for root in roots:
        for rel in ("bin/bash.exe", "usr/bin/bash.exe"):
            candidate = root / rel
            if candidate.is_file():
                return str(candidate)

    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    return None


BASH_PATH = _find_bash()

# Model requests only; tool executions are never automatically retried.
REQUEST_TIMEOUT = float(os.environ.get("FEI_REQUEST_TIMEOUT", "60"))
REQUEST_RETRIES = int(os.environ.get("FEI_REQUEST_RETRIES", "2"))
if REQUEST_TIMEOUT <= 0 or not 0 <= REQUEST_RETRIES <= 5:
    raise ValueError("FEI_REQUEST_TIMEOUT must be positive; FEI_REQUEST_RETRIES must be 0..5")


MAX_MODEL_REQUESTS = int(os.environ.get("FEI_MAX_MODEL_REQUESTS", "60"))
MAX_TASK_TOKENS = int(os.environ.get("FEI_MAX_TASK_TOKENS", "200000"))
MAX_RESPONSE_TOKENS = int(os.environ.get("FEI_MAX_RESPONSE_TOKENS", "4096"))
REPEAT_LIMIT = int(os.environ.get("FEI_REPEAT_LIMIT", "3"))
CONSECUTIVE_ERROR_LIMIT = int(os.environ.get("FEI_CONSECUTIVE_ERROR_LIMIT", "6"))
if min(MAX_MODEL_REQUESTS, MAX_TASK_TOKENS, MAX_RESPONSE_TOKENS) < 1 or min(REPEAT_LIMIT, CONSECUTIVE_ERROR_LIMIT) < 2:
    raise ValueError("Runtime budgets must be positive; loop thresholds must be >=2")

MAX_TASK_TOOL_CALLS = int(os.environ.get("FEI_MAX_TASK_TOOL_CALLS", "120"))
if MAX_TASK_TOOL_CALLS < 1:
    raise ValueError("FEI_MAX_TASK_TOOL_CALLS must be positive")
