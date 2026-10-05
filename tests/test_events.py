"""loop 事件策略的无 API 单测：成功是过程事件，失败必须是 error 事件。
python tests/test_events.py
"""
import json
import types

from fei.loop import run_task


def _resp(content=None, calls=None):
    msg = types.SimpleNamespace(content=content, tool_calls=calls)
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=msg)],
        usage=types.SimpleNamespace(prompt_tokens=10),
    )


def _call(name, args):
    return types.SimpleNamespace(
        id="t1", function=types.SimpleNamespace(name=name, arguments=args)
    )


class _FakeClient:
    """按顺序吐出预制响应的假客户端，不碰网络。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, **kwargs):
        return self._responses.pop(0)


def run(responses):
    events = []
    messages = [{"role": "system", "content": "s"},
                {"role": "user", "content": "u"}]
    run_task(_FakeClient(responses), messages,
             confirm=lambda name, description: True,
             notify=lambda k, t: events.append((k, t)))
    return events


def test_success_never_emits_error():
    events = run([
        _resp(calls=[_call("run_bash", json.dumps({"command": "echo hi"}))]),
        _resp(content="好的"),
    ])
    assert not any(k == "error" for k, _ in events)
    assert any(k == "result" for k, _ in events)  # 过程事件照发，由 cli 决定隐不隐


def test_unknown_tool_emits_error():
    events = run([
        _resp(calls=[_call("no_such_tool", "{}")]),
        _resp(content="好的"),
    ])
    assert any(k == "error" and "no_such_tool" in t for k, t in events)


def test_tool_exception_emits_error():
    # 缺必填参数 → handler 抛 TypeError → 必须以 error 事件上报
    events = run([
        _resp(calls=[_call("write_file", json.dumps({"path": "x.txt"}))]),
        _resp(content="好的"),
    ])
    assert any(k == "error" for k, _ in events)


def test_guard_block_emits_error():
    events = run([
        _resp(calls=[_call("run_bash", json.dumps({"command": "rm -rf /"}))]),
        _resp(content="好的"),
    ])
    assert any(k == "error" and "拦截" in t for k, t in events)


if __name__ == "__main__":
    for fn in (test_success_never_emits_error,
               test_unknown_tool_emits_error,
               test_tool_exception_emits_error,
               test_guard_block_emits_error):
        fn()
    print("loop 事件策略单测全部通过")
