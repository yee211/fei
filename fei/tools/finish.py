from fei.tools.base import Tool
from fei.task_state import current_task

def _finish_task(summary, completed, remaining, verification_ids, status):
    task = current_task.get()
    if task is None: raise RuntimeError("finish_task requires an active task")
    return task.finish(summary, completed, remaining, verification_ids, status)

strings = {"type": "array", "items": {"type": "string"}, "maxItems": 100}
tool = Tool("finish_task", "Submit structured completion. Must be the only call in its batch. Code changes require this tool before finishing. status=verified requires successful actual verify_project or run_bash(purpose=verification) call IDs AFTER latest modification; command exit success does not prove complete correctness. Use unverified when no check was run, incomplete for remaining work. remaining contains ONLY unfinished user-requested work; put encoding notes and caveats in summary. verified requires remaining=[]. Complete cleanup BEFORE final verification: every intervening run_bash(purpose=command), including ls or cleanup, invalidates previous verification conservatively. Compile Java with javac -encoding UTF-8 -d <build-directory> and run from that directory to avoid creating class files beside source. Do not fabricate call IDs.", {"type": "object", "properties": {"summary": {"type": "string", "minLength": 1, "maxLength": 4000}, "completed": strings, "remaining": strings, "verification_ids": strings, "status": {"type": "string", "enum": ["verified", "unverified", "incomplete"]}}, "required": ["summary", "completed", "remaining", "verification_ids", "status"], "additionalProperties": False}, _finish_task)
