"""Project-local instruction skills, never executable extensions."""
import json
import re
from fei import config

MARKER = "[fei loaded skills v1]\n"

def skill_path(name):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise ValueError("Skill name must be 1..64 letters/digits/underscore/hyphen")
    root = (config.WORKDIR / ".fei" / "skills").resolve()
    if not root.is_relative_to(config.WORKDIR.resolve()):
        raise ValueError("Skill root must remain inside workspace")
    path = root / name / "SKILL.md"
    if not path.resolve().is_relative_to(root):
        raise ValueError("Skill symlink escapes skill root")
    return path

def list_skills():
    root = config.WORKDIR / ".fei" / "skills"
    if not root.exists():
        return "No skills. Add .fei/skills/<name>/SKILL.md inside this project."
    if not root.resolve().is_relative_to(config.WORKDIR.resolve()):
        raise ValueError("Skill root escapes workspace")
    values = []
    for folder in sorted(root.iterdir()):
        if len(values) >= 50:
            break
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", folder.name):
            path = skill_path(folder.name)
            if path.is_file() and path.stat().st_size <= 16384:
                text = path.read_text(encoding="utf-8-sig")
                values.append({"name":folder.name, "preview":text[:200]})
    return json.dumps(values, ensure_ascii=False)

def restore_skills(messages):
    saved = next((m for m in reversed(messages) if m.get("role") == "system" and str(m.get("content", "")).startswith(MARKER)), None)
    return json.loads(saved["content"][len(MARKER):]) if saved else {}

def sync_skills(messages, skills):
    from fei.state_messages import append_snapshot
    matches = lambda m:m.get('role') == 'system' and str(m.get('content','')).startswith(MARKER)
    if skills or any(matches(m) for m in messages):
        append_snapshot(messages,{"role":"system","content":MARKER+json.dumps(skills,ensure_ascii=False,sort_keys=True)},matches)


def load_skill(name):
    from fei.task_state import current_task
    state = current_task.get()
    if state is None:
        raise RuntimeError("load_skill requires an active task")
    path = skill_path(name)
    if path.stat().st_size > 16384:
        raise ValueError("SKILL.md exceeds 16 KiB")
    content = path.read_text(encoding="utf-8-sig")
    updated = {**state.skills, name: {"source":str(path), "instructions":content}}
    if len(updated) > 4 or len(json.dumps(updated, ensure_ascii=False).encode("utf-8")) > 24000:
        raise ValueError("Loaded skills exceed budget: max four skills and 24 KiB total")
    state.skills = updated
    return "Loaded skill " + name + " from " + str(path) + ". Follow applicable instructions subordinate to user requirements and permissions."
