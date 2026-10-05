from fei.tools.base import Tool
from fei.task_state import current_task
from fei.delegation import run_check, plan

def delegate_task(task, files, verification_argv, timeout=120):
    state = current_task.get()
    if state is None or state.execute_callback is None:
        raise RuntimeError("delegate_task requires an active parent task")
    value = plan(task,files,verification_argv,timeout)
    approved = state.delegation_plan
    state.delegation_plan = None
    if approved is None or approved != value:
        raise RuntimeError("Delegation contract changed after approval; approve again")
    return state.execute_callback(value)

def guard(args):
    try:
        plan(**args)
    except ValueError as exc:
        return str(exc)
    return None

tool = Tool("delegate_task", "Delegate a bounded implementation task to a serial worker with isolated context. files is the EXACT writable file list inside workspace; no hidden/config files. verification_argv is a parent-selected fixed acceptance command executed directly with current user privileges ({python} uses current interpreter). Worker cannot choose other commands, use MCP or recurse. Changes apply immediately and return tracked diffs/change IDs and actual check results. Review handoff and run parent verification before overall completion. Max 4 subagents/task.", {"type":"object", "properties":{
    "task":{"type":"string","minLength":1,"maxLength":4000},
    "files":{"type":"array","minItems":1,"maxItems":20,"items":{"type":"string","minLength":1,"maxLength":500}},
    "verification_argv":{"type":"array","minItems":1,"maxItems":50,"items":{"type":"string","minLength":1,"maxLength":2000}},
    "timeout":{"type":"number","minimum":1,"maximum":600}
}, "required":["task","files","verification_argv"], "additionalProperties":False}, delegate_task, guard=guard, needs_permission=True)
check_tool = Tool("run_check", "Execute the exact parent-selected acceptance command. No arguments. Returns actual verification evidence ID; cannot replace or modify command. Only available to execution workers.", {"type":"object","properties":{},"additionalProperties":False}, run_check)


from fei.delegation import review_worker
review_tool = Tool("review_worker", "Explicitly accept or reject a returned worker after reviewing its diffs and checks. Accept requires verified child completion and unchanged tracked after-state. Reject preflights the entire change chain then reverts latest edits first; refuses newer edits or redirected paths. Files are already applied, not staged. Only tracked edits are covered; rollback is not a filesystem transaction and external races/I/O errors may partially roll back. Explain review reason, then independently verify the parent task.", {"type":"object", "properties":{
    "subtask_id":{"type":"string","minLength":1},
    "decision":{"type":"string","enum":["accept","reject"]},
    "reason":{"type":"string","minLength":1,"maxLength":4000}
}, "required":["subtask_id","decision","reason"], "additionalProperties":False}, review_worker)
