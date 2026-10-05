"""Known filesystem locations without shell probing or directory creation."""
import json
import os
from pathlib import Path
from fei import config
from fei.tools.base import Tool

def get_environment():
    home = Path.home()
    desktop = home / "Desktop"
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                value, _ = winreg.QueryValueEx(key, "Desktop")
                desktop = Path(os.path.expandvars(value)).expanduser()
        except OSError:
            pass
    return json.dumps({"platform":os.name, "workdir":str(config.WORKDIR), "home":str(home), "desktop":str(desktop.resolve()), "desktop_exists":desktop.is_dir(), "shell":config.BASH_PATH or "system default", "file_path_hint":"Windows file tools accept C:/... or /c/...; relative paths use workdir."}, ensure_ascii=False)

tool = Tool("get_environment", "Return workdir, home, actual Windows Desktop (including redirected/OneDrive Desktop), shell and path conventions without shell probing. Use for user-mentioned desktop/home paths; if a requested directory is absent, report or clarify instead of silently substituting the workdir.", {"type":"object", "properties":{}, "additionalProperties":False}, get_environment)
