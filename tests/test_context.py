"""不调 API 的单元测试：python tests/test_context.py（有 pytest 也可 pytest tests -q）"""
from fei.context import render, split_for_compact
from fei.permission import dangerous_command


def fake_task(user_text: str, call_id: str = "c1") -> list:
    return [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": call_id, "type": "function",
             "function": {"name": "run_bash",
                          "arguments": "{\"command\": \"ls\"}"}}]},
        {"role": "tool", "tool_call_id": call_id, "content": "a.py"},
        {"role": "assistant", "content": "done"},
    ]


def test_split_keeps_tool_pairs_together():
    messages = [{"role": "system", "content": "sys"}]
    messages += fake_task("任务一", "c1")
    messages += fake_task("任务二", "c2")
    parts = split_for_compact(messages)
    assert parts is not None
    system, old, recent = parts
    assert system[0]["content"] == "sys"
    assert recent[0] == {"role": "user", "content": "任务二"}  # 切点在最后一个 user
    assert old[-1]["role"] == "assistant"   # 旧任务是完整的
    assert "tool" in [m["role"] for m in recent]


def test_nothing_to_compact_with_single_task():
    messages = [{"role": "system", "content": "sys"}, *fake_task("唯一任务")]
    assert split_for_compact(messages) is None


def test_render_includes_tool_calls():
    text = render(fake_task("x"))
    assert "run_bash" in text and "[tool]" in text


def test_dangerous_patterns():
    assert dangerous_command("rm -rf /") is not None
    assert dangerous_command("rm -rf /*") is not None
    assert dangerous_command("rm -rf ~") is not None
    assert dangerous_command("rm -rf /tmp/build") is None  # 不误伤子目录
    assert dangerous_command("dd if=/dev/zero of=x") is not None
    assert dangerous_command("echo hi") is None


if __name__ == "__main__":
    for fn in (test_split_keeps_tool_pairs_together,
               test_nothing_to_compact_with_single_task,
               test_render_includes_tool_calls,
               test_dangerous_patterns):
        fn()
    print("context / permission 单元测试全部通过")
