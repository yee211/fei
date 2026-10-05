"""Model-maintained plan; execution evidence remains independent."""
from fei.tools.base import Tool
from fei.task_state import current_task

PLAN_SCHEMA = {
    "type": "object", "properties": {"steps": {
        "type": "array", "maxItems": 30, "items": {
            "type": "object", "properties": {
                "id": {"type": "string", "minLength": 1, "maxLength": 80},
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
            }, "required": ["id", "title", "status"], "additionalProperties": False,
        },
    }}, "required": ["steps"], "additionalProperties": False,
}

def update_plan(steps):
    task = current_task.get()
    if task is None:
        raise RuntimeError("update_plan requires an active task")
    return task.update_plan(steps)

tool = Tool("update_plan", "Replace the current task plan. Use stable unique step IDs; at most one in_progress step. Revise as findings change; steps=[] clears an obsolete plan. Plan completion is not verification evidence. Unfinished steps require finish_task status=incomplete and a remaining explanation.", PLAN_SCHEMA, update_plan)
