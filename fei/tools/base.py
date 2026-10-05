"""工具的统一描述：schema 给模型看，handler 给循环调。"""
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema，描述参数
    handler: Callable[..., str]
    guard: Optional[Callable[[dict], Optional[str]]] = None
    # guard(args) 返回拦截原因字符串表示拒绝，返回 None 表示放行
    needs_permission: bool = False  # True 则执行前要用户确认

    argument_validator: Optional[Callable[[dict], None]] = None
    source: Optional[str] = None

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
