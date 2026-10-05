"""Bounded code search using ripgrep; no shell interpolation."""
import shutil
import subprocess
import tempfile
from fei import config
from fei.tools._paths import resolve
from fei.tools.base import Tool

def _search_code(pattern: str, path: str = ".", glob: str = "", regex: bool = False) -> str:
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("pattern must be a nonempty string")
    if not isinstance(glob, str) or not isinstance(regex, bool):
        raise ValueError("glob must be a string and regex must be boolean")
    executable = shutil.which("rg")
    if executable is None:
        raise RuntimeError("ripgrep (rg) is required; install it or use run_bash for searching")
    target = resolve(path)
    if not target.exists():
        raise FileNotFoundError(str(target))
    args = [executable, "--line-number", "--with-filename", "--color=never", "--no-heading", "--max-count=100"]
    if not regex:
        args.append("--fixed-strings")
    if glob:
        args.append("--glob=" + glob)
    args.extend(["--", pattern, str(target)])
    # Spool to disk so large searches do not accumulate all output in memory.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.run(args, cwd=config.WORKDIR, stdout=output, stderr=errors, timeout=30)
        errors.seek(0)
        error = errors.read().decode("utf-8", errors="replace").strip()
        if process.returncode not in (0, 1):
            raise RuntimeError(f"Search failed (exit {process.returncode}): {error}")
        if process.returncode == 1:
            return "No matches found (respects ignore rules and skips hidden/binary files)."
        output.seek(0)
        text = output.read().decode("utf-8", errors="replace")
    return text + "\n[At most 100 matches per file; respects ignore rules.]"

tool = Tool(
    name="search_code",
    description="Search code with file paths and line numbers. Literal matching by default; regex=true enables regex. Respects ignore rules; skips hidden/binary files. Use path and glob to narrow results, then read_file for context.",
    parameters={"type": "object", "properties": {
        "pattern": {"type": "string"}, "path": {"type": "string", "description": "File or directory; defaults to working directory"},
        "glob": {"type": "string", "description": "Optional file filter, e.g. *.py"}, "regex": {"type": "boolean"},
    }, "required": ["pattern"], "additionalProperties": False},
    handler=_search_code,
)
