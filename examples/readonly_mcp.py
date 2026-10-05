"""Read-only stdio example; protocol output must stay on stdout."""
from pathlib import Path
import os
from mcp.server.fastmcp import FastMCP
server = FastMCP("fei-readonly")

@server.tool()
def project_info() -> dict:
    """Return current project name and server PID for lifecycle checks."""
    return {"project": Path.cwd().name, "pid": os.getpid()}

@server.tool()
def root_files(suffix: str | None = None) -> list[str]:
    """List at most 100 non-hidden root filenames, optionally filtered by suffix."""
    return sorted(p.name for p in Path.cwd().iterdir()
                  if not p.name.startswith(".") and p.is_file() and not p.is_symlink()
                  and (suffix is None or p.name.endswith(suffix)))[:100]

if __name__ == "__main__":
    server.run(transport="stdio")
