from fei.tools.base import Tool
from fei.task_state import current_task

def explore_code(question):
    state = current_task.get()
    if state is None or state.explore_callback is None:
        raise RuntimeError("explore_code requires an active task")
    return state.explore_callback(question)

tool = Tool("explore_code", "Delegate a focused code exploration question to a read-only subagent with independent context. Only file reading/search/directory tools; no shell, writes, MCP or recursion. Include the goal and constraints explicitly; parent conversation is not inherited. Returns findings, paths/line numbers and uncertainties, not verification evidence. Max 4 calls per task, 8 model turns each.", {"type":"object", "properties":{"question":{"type":"string", "minLength":1, "maxLength":4000}}, "required":["question"], "additionalProperties":False}, explore_code)
