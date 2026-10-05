"""接口层：REPL。核心逻辑都在 loop.py，这里只负责输入输出和权限确认。"""
from fei import llm
from datetime import datetime, timezone
from uuid import uuid4
from fei.config import STREAM, VERBOSE
from fei.loop import run_task
from fei.hooks import HookRegistry
from fei.session import Session
from fei.approval import ApprovalService

SYSTEM = (
    "你是 fei，一个运行在用户终端里的轻量编程助手。"
    "先用工具获取事实，再回答；回答用中文，简洁。"
    "Windows 文件工具支持 C:/Users/... 和 /c/Users/...。路径错误先检查准确目标，只清理本任务创建的具体文件；不得扩大到删除父目录。"
    "多步骤任务用 update_plan 维护计划，完成步骤后及时更新。恢复时参考现有计划，目标改变时重写或清空计划。计划状态不是执行或验证证据。"
    "先用 list_directory 了解结构、find_files 定位文件，再用 search_code 搜索内容。项目有 .fei.json 时优先用 verify_project 执行配置检查。"
    "定位代码优先用 search_code，修改前用 read_file 查看上下文。"
    "编辑与写入返回 change_id；完成后可用 show_changes 检查 diff，出错可请求 revert_change 回退。"
    "局部修改优先用 edit_file，write_file 用于新建文件或明确要求的整文件重写。"
    "修改后运行相关测试（run_bash purpose=verification），并用 finish_task 提交实际调用 ID、完成事项和未完成事项。"
    "先完成清理，再执行最终验证；最终验证后直接 finish_task，避免再执行普通命令导致验证失效。Java 编译用 -encoding UTF-8 -d 指定构建目录，避免源码目录留下 class 文件。"
    "finish_task 的 remaining 只填写未完成的用户要求；环境说明、编码注意事项放在 summary，verified 时 remaining 必须为空。"
    "最终回答说明完成事项、实际验证及结果、尚未完成或未验证的事项；不要把未执行的验证说成通过。"
    "被拒绝的操作不能绕过权限改用其他工具执行。"
    "旧上下文干扰判断或即将进入新阶段时，可调用 compact_context 主动请求压缩，随后查看实际结果。"
    "任务备忘是历史记录；大工具结果的完整输出存于提示的文件路径，可用 read_file 分页读取。"
)

HELP = """\
命令：
  /help   显示帮助
  /clear  清空对话，创建新会话
  /resume <路径>  从 .jsonl 或 .state.json 恢复会话（路径可带引号）
  /permission [read|auto|full]  查看或切换权限模式；切换清除已有授权
  /exit   退出
"""


def format_completion(completion):
    lines = [completion["summary"]]
    if completion.get("remaining"):
        lines.extend(["", "尚未完成：", *["- " + item for item in completion["remaining"]]])
    status = completion.get("status")
    lines.extend(["", {"verified": "验证：检查通过。", "unverified": "验证：未确认通过。", "incomplete": "状态：尚未完成。"}.get(status, "状态：未知。")])
    return "\n".join(lines)


def _interactive_main() -> None:
    client = llm.make_client()
    session = Session()
    messages = [{"role": "system", "content": SYSTEM}]
    stats: dict = {}
    pending = [False]  # 流式模式下 notify 之后内容还没换行

    def ask_permission(name, description, remember):
        print(f"\n需要确认工具 {name}：\n{description}", flush=True)
        choices = "[y=一次 / s=本会话 / N=拒绝]" if remember else "[y=一次 / N=拒绝]"
        answer = input("允许？" + choices + " ").strip().lower()
        return "session" if answer == "s" and remember else "once" if answer == "y" else "denied"

    permissions = ApprovalService(ask_permission, record=lambda event: session.append_permission(event))

    def on_text(delta: str) -> None:
        if pending[0]:
            print()
            pending[0] = False
        print(delta, end="", flush=True)

    def notify(kind: str, text: str) -> None:
        if kind not in {"error", "progress"} and not VERBOSE:
            return  # 安静模式：只显示错误；完整过程在会话 JSONL 里
        pending[0] = True
        print(f"  · [{kind}] {text}", flush=True)

    print(f"fei 就绪，会话记录：{session.path}")
    print("权限：auto；工作区文件自动执行，范围外按需确认。/permission 切换模式。")
    print("输入任务开始，/help 查看命令。\n")

    while True:
        try:
            user = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            continue
        if user == "/exit":
            break
        if user == "/permission" or user.startswith("/permission "):
            mode = user[len("/permission"):].strip()
            if not mode:
                print("当前权限：" + permissions.policy.mode + "；可选 read / auto / full")
            else:
                try:
                    permissions.set_mode(mode)
                    print("权限已切换：" + mode + ("；工具免确认，以当前用户权限执行，危险守卫保留。" if mode == "full" else "；已有授权已清除。"))
                except ValueError as exc:
                    print(exc)
            continue
        if user == "/clear":
            messages = [{"role": "system", "content": SYSTEM}]
            stats.clear()
            session = Session()
            permissions.reset()
            session.save_state(messages)
            print(f"已清空对话，新会话：{session.path}")
            continue
        if user == "/help":
            print(HELP)
            continue

        if user == "/resume" or user.startswith("/resume "):
            path = user[len("/resume"):].strip().strip('"').strip("'")
            if not path:
                print("用法：/resume <会话文件路径>")
                continue
            try:
                restored = Session.load_state(path)
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                print(f"恢复失败：{exc}")
                continue
            session = Session()
            permissions.reset()
            messages = restored
            stats.clear()
            for message in messages:
                session.append(message)
            session.save_state(messages)
            print(f"已恢复 {len(messages)} 条消息，新会话：{session.path}")
            continue

        task_record = {
            "id": uuid4().hex, "goal": user,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "verification": "not_independently_verified",
            "tool_calls": [], "status": "running", "final_answer": "",
        }
        messages.append({"role": "user", "content": user})
        session.append(messages[-1])
        hooks = HookRegistry(on_error=lambda error: notify("error", f"Hook {error['event']}: {error['error']}"))
        hooks.register("notice", lambda event: notify(event.data["kind"], event.data["text"]))
        hooks.register("message", lambda event: session.append(event.data["message"]), critical=True)
        hooks.register("checkpoint", lambda event: session.save_state(event.data["messages"]), critical=True)
        try:
            result = run_task(client, messages,
                              permission_policy=permissions, hooks=hooks, task_record=task_record,
                              on_text=on_text if STREAM else None,
                              on_completion=lambda completion: on_text("\n" + format_completion(completion)) if STREAM else None,
                              stats=stats, output_writer=session.store_output)
        except (Exception, KeyboardInterrupt) as exc:
            # 保留完整工具调用/结果配对，丢弃本轮尚未完成的调用。
            end = len(messages)
            for index in range(len(messages)):
                calls = messages[index].get("tool_calls", [])
                if calls:
                    expected = {call["id"] for call in calls}
                    actual = {m.get("tool_call_id") for m in messages[index + 1:]
                              if m.get("role") == "tool"}
                    if not expected.issubset(actual):
                        end = index
                        break
            del messages[end:]
            result = "任务已中断。" if isinstance(exc, KeyboardInterrupt) else f"任务失败：{type(exc).__name__}: {exc}"
            task_record.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", final_answer=result)
            messages.append({"role": "assistant", "content": result})
            session.append(messages[-1])
            if STREAM:
                print(f"\n{result}")
        finally:
            task_record["finished_at"] = datetime.now(timezone.utc).isoformat()
            session.append_task(task_record)
            session.save_state(messages)
        if not STREAM and task_record.get("completion"):
            result = format_completion(task_record["completion"])
        print("\n" if STREAM else f"\n{result}\n")




def main() -> None:
    from fei import config
    from fei.mcp_client import MCPManager
    manager = MCPManager()
    def confirm_server(name, description):
        print(f"\n{description}", flush=True)
        try:
            return input("允许启动此 MCP 服务？[y/N] ").strip().lower() == "y"
        except EOFError:
            return False
    try:
        manager.load(config.WORKDIR / ".fei-mcp.json", confirm_server)
        if manager.names:
            print(f"已接入 {len(manager.names)} 个 MCP 工具")
        _interactive_main()
    finally:
        manager.close()


if __name__ == "__main__":
    main()
