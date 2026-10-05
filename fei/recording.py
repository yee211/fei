"""Task evidence subscriber; independent of the agent loop."""
from datetime import datetime, timezone

def attach_task_record(hooks, record):
    def start(event):
        record.update(status="running", tool_calls=[], final_answer="")
        record.setdefault("started_at", datetime.now(timezone.utc).isoformat())
        record.setdefault("goal", event.data["goal"])
        record.setdefault("verification", "not_independently_verified")
        record.pop("context_compactions", None)
    def tool(event):
        data = event.data
        record["tool_calls"].append({"id": data["id"], "name": data["name"], "arguments": data["arguments"], "status": "error" if data["error"] else "ok", "result": data["result"], "output_path": data["output_path"], "exit_code": data.get("exit_code"), "checks": data.get("checks")})
    def compact(event):
        record.setdefault("context_compactions", []).append({"turn": event.data["turn"], "memory": event.data["memory"]})
    def end(event):
        if event.data.get("completion") is not None:
            record["completion"] = event.data["completion"]
            record["verification"] = event.data["completion"]["status"]
        record.update(status=event.data["status"], final_answer=event.data["result"], finished_at=datetime.now(timezone.utc).isoformat())
    hooks.register("task_start", start, critical=True)
    hooks.register("after_tool", tool, critical=True)
    hooks.register("after_compact", compact, critical=True)
    hooks.register("task_end", end, critical=True)
