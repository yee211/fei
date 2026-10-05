"""Session approval seam, independent of terminal UI and conversation memory."""
from pathlib import Path
from fei.permission import PermissionPolicy

class ApprovalService:
    def __init__(self, ask=None, record=None, mode="auto"):
        self.policy = PermissionPolicy(mode)
        self.ask = ask
        self.record = record
        self.grants = set()

    def reset(self):
        self.grants.clear()
        self.policy.set_mode("auto")

    def set_mode(self, mode):
        self.policy.set_mode(mode)
        self.grants.clear()
        self.emit("mode", mode=mode)

    def emit(self, event, **data):
        if self.record:
            self.record({"event": "permission." + event, **data})

    def granted(self, scope):
        if scope in self.grants:
            return True
        if scope and scope[0] in {"read", "write"}:
            path = Path(scope[1])
            return any(grant[0] in ({"read", "write"} if scope[0] == "read" else {"write"})
                       and path.is_relative_to(Path(grant[1])) for grant in self.grants if grant[0] in {"read", "write"})
        return False

    def authorize(self, tool, args, description):
        decision = self.policy.decide(tool, args, description)
        if decision.kind == "deny":
            self.emit("decided", tool=tool.name, decision="denied", reason=decision.reason)
            return False
        if decision.kind == "allow" or (decision.remember and self.granted(decision.scope)):
            self.emit("decided", tool=tool.name, decision="allowed", reason=decision.reason, scope=decision.scope)
            return True
        request = (description or "") + "\n授权范围：" + decision.reason
        self.emit("asked", tool=tool.name, arguments=args, scope=decision.scope, reason=decision.reason)
        try:
            answer = self.ask(tool.name, request, decision.remember and decision.scope is not None) if self.ask else "unavailable"
        except (EOFError, KeyboardInterrupt):
            answer = "cancelled"
        except Exception as exc:
            self.emit("decided", tool=tool.name, decision="unavailable", reason=str(exc))
            return False
        allowed = answer in {"once", "session"}
        self.emit("decided", tool=tool.name, decision=answer if allowed else "denied", scope=decision.scope)
        if answer == "session" and decision.remember and decision.scope is not None:
            self.grants.add(decision.scope)
        return allowed
