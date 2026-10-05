"""Ordered synchronous lifecycle hooks with isolated event snapshots."""
from copy import deepcopy
from dataclasses import dataclass
import warnings

EVENTS = frozenset({"task_start", "task_end", "before_model", "after_model", "before_tool", "after_tool", "before_compact", "after_compact", "message", "checkpoint", "notice", "after_summary"})
GUARDS = frozenset({"before_model", "before_tool", "before_compact"})

class HookRejected(RuntimeError):
    def __init__(self, message, event=None):
        super().__init__(message)
        self.event = event

@dataclass(frozen=True)
class HookEvent:
    name: str
    data: dict

class HookRegistry:
    def __init__(self, on_error=None):
        self._handlers = {name: [] for name in EVENTS}
        self.on_error = on_error
        self.errors = []

    def register(self, name, handler, *, critical=False):
        if name not in EVENTS:
            raise ValueError(f"Unknown hook: {name}")
        if not callable(handler):
            raise TypeError("Hook handler must be callable")
        entry = (handler, critical)
        self._handlers[name].append(entry)
        def remove():
            if entry in self._handlers[name]:
                self._handlers[name].remove(entry)
        return remove

    def copy(self):
        copied = HookRegistry(self.on_error)
        copied._handlers = {name: list(entries) for name, entries in self._handlers.items()}
        copied.errors = self.errors
        return copied

    def emit(self, name, /, **data):
        if name not in EVENTS:
            raise ValueError(f"Unknown hook: {name}")
        for handler, critical in tuple(self._handlers[name]):
            try:
                # Each handler gets its own snapshot; mutation cannot alter execution or other hooks.
                outcome = handler(HookEvent(name, deepcopy(data)))
                if name in GUARDS and (outcome is False or isinstance(outcome, str)):
                    raise HookRejected(outcome if isinstance(outcome, str) else f"{name} rejected", event=name)
            except HookRejected:
                raise
            except Exception as exc:
                if critical or name in GUARDS:
                    raise HookRejected(f"Hook {name} failed: {type(exc).__name__}: {exc}", event=name) from exc
                error = {"event": name, "handler": getattr(handler, "__name__", type(handler).__name__), "error": f"{type(exc).__name__}: {exc}"}
                self.errors.append(error)
                if self.on_error:
                    try:
                        self.on_error(error)
                    except Exception:
                        warnings.warn(str(error), RuntimeWarning)
                else:
                    warnings.warn(str(error), RuntimeWarning)
