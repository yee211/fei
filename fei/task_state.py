"""Per-task execution evidence; survives context compression."""
from contextvars import ContextVar
import json

current_task = ContextVar("fei_current_task", default=None)

class TaskState:
    def __init__(self):
        self.execute_callback = None
        self.delegation_plan = None
        self.delegated_check = None
        self.skills = {}
        self.subagents = []
        self.explore_callback = None
        self.plan_updated = False
        self.plan = []
        self.plan_closed = False
        self.evidence = {}
        self.sequence = 0
        self.last_change = -1
        self.last_effect = -1
        self.completion = None
        self.progress = None
        self.summary_callback = None
        self.verification_plan = None

    PLAN_PREFIX = "[fei task plan v1]\n"

    def update_plan(self, steps):
        from copy import deepcopy
        from fei.tools.plan import PLAN_SCHEMA
        from fei.validation import validate
        validate({"steps": steps}, PLAN_SCHEMA)
        if len({step["id"] for step in steps}) != len(steps):
            raise ValueError("Plan step IDs must be unique")
        if sum(step["status"] == "in_progress" for step in steps) > 1:
            raise ValueError("Only one plan step can be in_progress")
        self.plan_updated = True
        self.plan = deepcopy(steps)
        self.plan_closed = False
        if self.progress:
            self.progress("计划：" + "；".join(step["title"] + " (" + step["status"] + ")" for step in steps))
        return json.dumps({"steps": self.plan}, ensure_ascii=False)

    @classmethod
    def is_plan_message(cls, message):
        return message.get("role") == "system" and str(message.get("content", "")).startswith(cls.PLAN_PREFIX)

    def restore_plan(self, messages):
        saved = next((m for m in reversed(messages) if self.is_plan_message(m)), None)
        if saved is not None:
            value = json.loads(saved["content"][len(self.PLAN_PREFIX):])
            if not value["closed"]:
                self.update_plan(value["steps"])

    def sync_plan(self, messages):
        from fei.state_messages import append_snapshot
        previous = next((m for m in reversed(messages) if self.is_plan_message(m)), None)
        if previous and not self.plan and not self.plan_updated and json.loads(previous["content"][len(self.PLAN_PREFIX):]).get("closed"):
            return
        if self.plan or previous:
            append_snapshot(messages, {"role":"system", "content":self.PLAN_PREFIX + json.dumps(
                {"steps":self.plan,"closed":self.plan_closed},ensure_ascii=False,sort_keys=True)}, self.is_plan_message)

    def observe(self, event):
        data = event.data
        self.sequence += 1
        self.evidence[data["id"]] = {**data, "sequence": self.sequence}
        if data["name"] in {"write_file", "edit_file", "revert_change"} and not data["error"] and not str(data["result"]).startswith("No changes"):
            self.last_change = self.sequence
            self.last_effect = self.sequence
        if data["name"] == "review_worker" and data["arguments"].get("decision") == "reject":
            self.last_change = self.sequence
            self.last_effect = self.sequence
        if data["name"] == "delegate_task":
            self.last_change = self.sequence
            self.last_effect = self.sequence
        if data["name"] == "run_bash" and data["arguments"].get("purpose") != "verification":
            self.last_effect = self.sequence

    def finish(self, summary, completed, remaining, verification_ids, status):
        pending_workers = [item['id'] for item in self.subagents if item.get('kind') == 'worker' and item.get('review', {}).get('status', 'pending') == 'pending']
        if pending_workers and status != 'incomplete':
            raise ValueError("Review returned workers before completing the task: " + ', '.join(pending_workers))
        unfinished = [step["title"] for step in self.plan if step["status"] != "completed"]
        if unfinished and (status != "incomplete" or not remaining):
            raise ValueError("Unfinished plan steps require incomplete status and remaining explanation: " + "; ".join(unfinished))
        if status == "verified":
            if not verification_ids: raise ValueError("Verified completion requires actual verification call IDs")
            if remaining: raise ValueError("remaining must be [] for verified; use incomplete for unfinished requested work. Put environment notes/caveats in summary.")
        for call_id in verification_ids:
            evidence = self.evidence.get(call_id)
            valid=evidence is not None and (evidence["name"] in {"verify_project", "run_check"} or (evidence["name"]=="run_bash" and evidence["arguments"].get("purpose")=="verification"))
            if not valid:
                available=[key for key,item in self.evidence.items() if item["name"] in {"verify_project", "run_check"} or (item["name"]=="run_bash" and item["arguments"].get("purpose")=="verification")]
                raise ValueError(f"{call_id}: must reference an actual verification call in this task. Available IDs: {available}")
            from fei import config
            if status=="verified" and (config.WORKDIR/'.fei.json').is_file() and evidence["name"]!="verify_project" and self.delegated_check is None:
                raise ValueError("This project configures verification; use verify_project evidence")
            if status == "verified" and evidence["error"]:
                raise ValueError(f"{call_id}: verification failed: {evidence['error']}")
            if status == "verified" and evidence["sequence"] <= max(self.last_change, self.last_effect):
                latest = max(self.last_change, self.last_effect)
                cause = next((key + ": " + item["name"] for key, item in self.evidence.items() if item["sequence"] == latest), "unknown")
                raise ValueError(f"{call_id}: verification predates subsequent operation {cause}. Finish cleanup first, then rerun verification and immediately submit finish_task.")
        self.completion = {"summary": summary, "completed": completed, "remaining": remaining, "verification_ids": verification_ids, "status": status}
        self.plan_closed = status != "incomplete"
        return self.render()

    def render(self):
        value = self.completion
        return json.dumps(value, ensure_ascii=False, indent=2)
