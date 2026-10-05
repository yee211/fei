"""Request context compression at the next complete tool-batch boundary."""
from fei.tools.base import Tool

def _request_compact(reason: str = "") -> str:
    if not isinstance(reason, str):
        raise ValueError("reason must be a string")
    if len(reason) > 1000:
        raise ValueError("reason must not exceed 1000 characters")
    return "压缩请求已接受，将在本轮全部工具结果回填后执行。随后会报告实际结果；此消息不代表压缩已成功。"

tool = Tool(
    name="compact_context",
    description="Actively request compression when old context is distracting or before a new task phase. Runs after ALL tool results in the current batch are available. Preserves original goal and recent complete tool blocks; may skip if too little history. A subsequent status message reports success, skip or failure. Automatic budget compression remains enabled.",
    parameters={"type": "object", "properties": {"reason": {"type": "string", "description": "Optional short reason; up to 1000 characters"}}, "additionalProperties": False},
    handler=_request_compact,
)
