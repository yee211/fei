from fei.tools.base import Tool
from fei.changes import show_changes, revert_change, get_change

def _revert_guard(args):
    try:
        get_change(args.get("change_id", ""))
    except (OSError, ValueError, TypeError) as exc:
        return f"Invalid tracked change: {exc}"
    return None

show_tool = Tool("show_changes", "List tracked edit/write changes, or show recorded before/after diff for a change_id. Shell changes are not tracked.", {"type": "object", "properties": {"change_id": {"type": "string"}}, "additionalProperties": False}, show_changes)
revert_tool = Tool("revert_change", "Revert one tracked change by ID. Refuses if file differs from recorded after-state. Revert latest changes first. New files are removed only when unchanged. Requires user confirmation.", {"type": "object", "properties": {"change_id": {"type": "string"}}, "required": ["change_id"], "additionalProperties": False}, revert_change, guard=_revert_guard)
