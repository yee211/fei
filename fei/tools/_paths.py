"""工具共享的路径解析：相对路径一律基于工作目录。"""
import os
import re
from pathlib import Path

from fei import config


def resolve(path: str) -> Path:
    if os.name == "nt":
        match = re.match(r"^/([a-zA-Z])(?:/|$)(.*)", path)
        if match:
            path = match.group(1).upper() + ":/" + match.group(2)
        elif path.startswith("/") and not path.startswith("//"):
            raise ValueError("Use a Windows absolute path (C:/...) or Git Bash drive path (/c/...), not a root-relative path")
    p = Path(path).expanduser()
    return p if p.is_absolute() else (config.WORKDIR / p).resolve()
