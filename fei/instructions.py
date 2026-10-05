"""Load scoped project rules; never automatically read above WORKDIR."""
from pathlib import Path
from fei import config

MARKER = "[fei project instructions]"
class ProjectInstructions:
    def __init__(self):
        self.root = config.WORKDIR.resolve()
        self.directories = {self.root}
        self.cache = {}

    def add_path(self, path):
        target = Path(path).resolve()
        if not target.is_relative_to(self.root): return False
        folder = target if target.is_dir() else target.parent
        added = False
        while folder.is_relative_to(self.root):
            if folder not in self.directories:
                self.directories.add(folder); added = True
            if folder == self.root: break
            folder = folder.parent
        return added

    def refresh(self, messages):
        pieces = []
        for folder in sorted(self.directories, key=lambda p: (len(p.parts), str(p))):
            path = folder / "AGENTS.md"
            # A symlink cannot implicitly load rules from outside the authorized project.
            if not path.is_file() or not path.resolve().is_relative_to(self.root):
                self.cache.pop(path, None); continue
            if path.stat().st_size > 65536:
                raise ValueError(f"Project instruction file exceeds 64 KiB: {path}")
            signature = (path.stat().st_mtime_ns, path.stat().st_size)
            previous = self.cache.get(path)
            if previous is None or previous[0] != signature:
                self.cache[path] = (signature, path.read_text(encoding="utf-8-sig"))
            pieces.append(f"Source: {path}\nScope: {folder} and descendants; more specific directory rules apply within their scope.\n{self.cache[path][1]}")
        content = MARKER + "\nLatest project conventions replace earlier snapshots; subordinate to the user's explicit requirements.\n" + "\n\n".join(pieces)
        if len(content.encode("utf-8")) > 131072:
            raise ValueError("Combined project instructions exceed 128 KiB")
        previous = next((m for m in reversed(messages) if m.get("role") == "system" and str(m.get("content", "")).startswith(MARKER)), None)
        changed = (previous or {}).get("content") != content if pieces or previous is not None else False
        if changed:
            from fei.state_messages import append_snapshot
            message = {"role":"system","content":content}
            if previous is None and not any(m.get('role') in {'assistant','tool'} for m in messages):
                position = next((i for i,m in enumerate(messages) if m.get('role') != 'system'),len(messages))
                messages.insert(position,message)
            else:
                append_snapshot(messages,message,lambda m:m.get('role')=='system' and str(m.get('content','')).startswith(MARKER))
        return changed
