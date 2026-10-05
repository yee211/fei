"""Bounded deterministic filesystem discovery, without following symlinks."""
import os
import time
from dataclasses import dataclass
from itertools import islice
from pathlib import PurePosixPath
from fnmatch import fnmatchcase
from fei.tools._paths import resolve

IGNORED = frozenset({"node_modules", "venv", "env", "__pycache__", "dist", "build", "site-packages", "coverage"})
@dataclass
class Scan:
    scanned: int = 0
    truncated: bool = False

def walk(root, depth, scan, include_hidden=False, include_ignored=False):
    pending=[(root,0)];started=time.monotonic()
    while pending:
        directory,level=pending.pop()
        if time.monotonic()-started>5 or scan.scanned>=10000:
            scan.truncated=True;return
        with os.scandir(directory) as iterator:
            entries=list(islice(iterator,10001-scan.scanned))
        if len(entries)>10000-scan.scanned:
            entries=entries[:10000-scan.scanned];scan.truncated=True
        children=[]
        for entry in sorted(entries,key=lambda item:item.name.lower()):
            if time.monotonic()-started>5:
                scan.truncated=True;return
            scan.scanned+=1
            if not include_hidden and entry.name.startswith('.'):continue
            if entry.is_symlink():continue
            is_dir=entry.is_dir(follow_symlinks=False)
            if is_dir and not include_ignored and entry.name in IGNORED:continue
            path=directory/entry.name
            yield path,is_dir,level+1
            if is_dir and level+1<depth:children.append((path,level+1))
        pending.extend(reversed(children))

def root_directory(path):
    root=resolve(path).resolve()
    if not root.is_dir():raise ValueError("path must be an existing directory")
    return root

def matches(relative,pattern):
    from functools import lru_cache
    pattern=pattern.replace("\\","/").removeprefix("./")
    if '/' not in pattern:return fnmatchcase(PurePosixPath(relative).name,pattern)
    parts=tuple(relative.split('/'));rules=tuple(pattern.split('/'))
    @lru_cache(None)
    def check(i,j):
        if j==len(rules):return i==len(parts)
        if rules[j]=='**':return check(i,j+1) or (i<len(parts) and check(i+1,j))
        return i<len(parts) and fnmatchcase(parts[i],rules[j]) and check(i+1,j+1)
    return check(0,0)


def list_directory(path='.',depth=2,limit=200,include_hidden=False,include_ignored=False):
    root=root_directory(path);scan=Scan();lines=[]
    for target,is_dir,level in walk(root,depth,scan,include_hidden,include_ignored):
        if len(lines)>=limit:scan.truncated=True;break
        lines.append(str(target.relative_to(root)).replace('\\','/')+('/' if is_dir else ''))
    return f"Directory: {root}\n"+'\n'.join(lines or ['(empty or all entries excluded)'])+f"\n[Depth limit={depth}; symlinks skipped; {'truncated, narrow path or raise limit' if scan.truncated else 'within scan/output limits'}]"

def find_files(pattern,path='.',depth=20,limit=100,include_hidden=False,include_ignored=False):
    root=root_directory(path);scan=Scan();lines=[]
    for target,is_dir,level in walk(root,depth,scan,include_hidden,include_ignored):
        relative=target.relative_to(root).as_posix()
        if not is_dir and matches(relative,pattern):
            if len(lines)>=limit:scan.truncated=True;break
            lines.append(relative)
    return f"Search root: {root}\n"+'\n'.join(lines or ['No matching files'])+f"\n[Depth limit={depth}; symlinks skipped; {'truncated, narrow pattern/path or raise limit' if scan.truncated else 'within scan/output limits'}]"
