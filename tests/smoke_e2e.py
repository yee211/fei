"""真实 API 冒烟测试（需要 .env 里有有效 key）：python tests/smoke_e2e.py"""
import json

from fei import llm
from fei.context import compact
from fei.loop import run_task


def main() -> None:
    client = llm.make_client()

    print("--- 测试 1：流式输出 + 工具调用循环 ---")
    messages = [
        {"role": "system", "content": "你是 fei，终端编程助手，回答用中文，简洁。"},
        {"role": "user", "content": "用 run_bash 数一下 fei 包目录下有多少个 .py 文件，然后回答数字。"},
    ]
    stats: dict = {}
    reply = run_task(
        client, messages,
        confirm=lambda name, description: input(f"{name}: {description}\nAllow? [y/N] ").strip().lower() == "y",
        notify=lambda k, t: print(f"\n  · [{k}] {t}", flush=True),
        on_text=lambda d: print(d, end="", flush=True),
        stats=stats,
    )
    print("\n[最终回复]", reply)
    print("[prompt_tokens]", stats.get("prompt_tokens"))

    print("--- 测试 2：上下文压缩 ---")
    history = [{"role": "system", "content": "你是 fei。"}]
    for i in range(1, 4):
        args = json.dumps({"path": f"n{i}.txt", "content": str(i)})
        history += [
            {"role": "user", "content": f"任务{i}：把数字 {i} 写进 n{i}.txt"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": f"c{i}", "type": "function",
                 "function": {"name": "write_file", "arguments": args}}]},
            {"role": "tool", "tool_call_id": f"c{i}", "content": "已写入"},
            {"role": "assistant", "content": f"任务{i}完成。"},
        ]
    compacted = compact(client, history)
    print("压缩前消息数:", len(history), "→ 压缩后:", len(compacted))
    print("摘要预览:", compacted[1]["content"][:100].replace("\n", " "))
    compacted.append({"role": "user", "content": "直接回答：1+1 等于几？不要用工具。"})
    print("压缩后继续对话:", run_task(client, compacted))
    print("--- 全部通过 ---")


if __name__ == "__main__":
    main()
