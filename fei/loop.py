"""核心 agent 循环。

本文件不做任何输入输出：交互由接口层通过 confirm / notify / on_text
回调注入，所以将来加 FastAPI / Web 界面时核心一行不用改。
"""
import json
from time import perf_counter
from fei.hooks import HookRegistry, HookRejected
from fei.recording import attach_task_record
from fei.validation import validate
from fei.instructions import ProjectInstructions
from fei.task_state import TaskState, current_task
from fei.tools._paths import resolve

from fei.config import MAX_TOOL_OUTPUT, MAX_TURNS, MODEL
from fei.tools import REGISTRY, schemas
from fei.permission import permission_request
from fei import config
from fei.context import estimate_tokens, compact_running
from fei.output import prepare_output


def _chat(client, messages, on_text=None):
    """调一次模型，统一返回 (content, tool_calls, usage)。

    on_text 不为 None 时走流式：文本增量回调给接口层，
    tool_calls 从 delta 增量拼装成和非流式一致的结构。
    """
    if on_text is None:
        resp = client.chat.completions.create(
            model=MODEL, messages=messages, tools=schemas(),
        )
        msg = resp.choices[0].message
        tool_calls = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name,
                          "arguments": tc.function.arguments or "{}"}}
            for tc in msg.tool_calls or []
        ]
        return msg.content or "", tool_calls, resp.usage, getattr(msg, "reasoning_content", None)

    reasoning_parts: list = []
    parts: list = []
    acc: dict = {}  # index -> 工具调用累积器
    usage = None
    stream = client.chat.completions.create(
        model=MODEL, messages=messages, tools=schemas(),
        stream=True, stream_options={"include_usage": True},
    )
    for chunk in stream:
        if getattr(chunk, "usage", None):
            usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta is None:
            continue
        if getattr(delta, "reasoning_content", None):
            reasoning_parts.append(delta.reasoning_content)
        if delta.content:
            parts.append(delta.content)
            on_text(delta.content)
        for tc in delta.tool_calls or []:
            item = acc.setdefault(tc.index, {
                "id": "", "type": "function",
                "function": {"name": "", "arguments": ""},
            })
            if tc.id:
                item["id"] = tc.id
            if tc.function and tc.function.name:
                item["function"]["name"] += tc.function.name
            if tc.function and tc.function.arguments:
                item["function"]["arguments"] += tc.function.arguments
    return "".join(parts), [acc[i] for i in sorted(acc)], usage, "".join(reasoning_parts) or None


def _execute(tool, args):
    """返回 (结果文本, 错误原因)；成功时错误为 None。"""
    try:
        return tool.handler(**args), None
    except Exception as exc:  # 错误也喂回模型，让它自己纠错
        text = f"{type(exc).__name__}: {exc}"
        return text, text


def run_task(client, messages, confirm=None, notify=None, on_text=None,
             stats=None, task_record=None, output_writer=None,
             on_message=None, checkpoint=None, hooks=None, permission_policy=None, on_completion=None) -> str:
    """Run with lifecycle hooks; legacy observer callbacks remain compatible."""
    active = hooks.copy() if hooks is not None else HookRegistry()
    if notify:
        active.register("notice", lambda event: notify(event.data["kind"], event.data["text"]))
    if on_message:
        active.register("message", lambda event: on_message(event.data["message"]), critical=True)
    if checkpoint:
        active.register("checkpoint", lambda event: checkpoint(event.data["messages"]), critical=True)
    if task_record is not None:
        attach_task_record(active, task_record)
    state = TaskState()
    state.restore_plan(messages)
    state.progress = lambda text: active.emit("notice", kind="progress", text=text)
    active.register("after_tool", state.observe, critical=True)
    token = current_task.set(state)
    status, result = "failed", ""
    primary_error = None
    try:
        goal = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        active.emit("task_start", goal=goal)
        result, status = _run_task(client, messages, active, confirm, on_text,
                                   stats if stats is not None else {}, output_writer, permission_policy, on_completion)
        return result
    except BaseException as exc:
        primary_error = exc
        status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        result = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        state.sync_plan(messages)
        current_task.reset(token)
        try:
            active.emit("task_end", status=status, result=result, completion=state.completion)
        except Exception as hook_error:
            if primary_error is None:
                raise
            if hasattr(primary_error, "add_note"):
                primary_error.add_note(f"task_end hook also failed: {hook_error}")


def _run_task(client, messages, hooks, confirm, on_text, stats, output_writer, permission_policy=None, on_completion=None):
    instructions = ProjectInstructions()
    state = current_task.get()
    finish_reminders = 0
    state.summary_callback = lambda data: hooks.emit("after_summary", phase="compression", **data)
    def append(message):
        messages.append(message)
        hooks.emit("message", message=message)
    def notice(kind, text):
        hooks.emit("notice", kind=kind, text=text)

    def allowed(tool, args):
        request = permission_request(tool, args)
        if permission_policy is not None:
            return permission_policy.authorize(tool, args, request)
        return request is None or (confirm is not None and confirm(tool.name, request))

    def compress(turn, budget, source, reason="", required=False):
        hooks.emit("before_compact", turn=turn, messages=messages, budget=budget,
                   source=source, reason=reason)
        notice("context", "整理任务备忘…")
        updated = compact_running(client, messages)
        if updated is messages:
            if required:
                raise RuntimeError("Context remains above budget; shorten request or raise FEI_COMPACT_TOKENS")
            return "跳过：历史不足，没有可压缩的较早消息块。"
        if required and estimate_tokens(updated, schemas()) > config.COMPACT_TOKENS:
            raise RuntimeError("Context remains above budget; shorten request or raise FEI_COMPACT_TOKENS")
        messages[:] = updated
        stats.clear()
        memory = next(m["content"] for m in messages if str(m.get("content", "")).startswith("[任务备忘"))
        hooks.emit("after_compact", turn=turn, memory=memory, messages=messages,
                   source=source, reason=reason)
        hooks.emit("checkpoint", messages=messages)
        return "成功：已压缩较早记录，保留原始要求、任务备忘和最近完整工具消息块。"

    for turn in range(MAX_TURNS):
        state.sync_plan(messages)
        if instructions.refresh(messages):
            notice("instructions", "项目 AGENTS.md 指令已加载或刷新。")
        estimate = estimate_tokens(messages, schemas())
        delta = max(0, estimate - stats.get("request_estimate", estimate))
        budget = max(estimate, stats.get("prompt_tokens", 0) + delta)
        if budget > config.COMPACT_TOKENS:
            compress(turn, budget, "automatic", required=True)
            estimate = estimate_tokens(messages, schemas())
        stats["request_estimate"] = estimate
        hooks.emit("before_model", turn=turn, messages=messages, estimate=estimate)
        started = perf_counter()
        response = _chat(client, messages, on_text=on_text)
        content, tool_calls, usage = response[:3]
        model_metadata = {"reasoning_content": response[3]} if len(response) > 3 and response[3] is not None else {}
        if usage is not None:
            stats["prompt_tokens"] = usage.prompt_tokens
        hooks.emit("after_model", turn=turn, content=content, tool_calls=tool_calls,
                   elapsed=perf_counter() - started,
                   usage=usage.model_dump() if hasattr(usage, "model_dump") else vars(usage) if usage is not None else None)
        if not tool_calls:
            append({"role": "assistant", "content": content, **model_metadata})
            if state.last_change >= 0 or state.plan:
                if finish_reminders >= 2:
                    result = "任务未提交有效 finish_task；修改已保留，但完成与验证尚未确认。"
                    append({"role": "assistant", "content": result})
                    if on_text: on_text(result)
                    return result, "incomplete"
                finish_reminders += 1
                append({"role": "system", "content": "本任务已修改文件或维护计划，请用 finish_task 提交 completed、remaining、status 和实际 verification_ids。未运行验证必须标记 unverified。验证命令应使用 run_bash(purpose='verification')。"})
                continue
            return content, "returned"
        append({"role": "assistant", "content": content, "tool_calls": tool_calls, **model_metadata})
        pending_compact = []
        new_instructions_in_batch = False
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                args = None
                argument_error = f"工具参数不是有效 JSON: {exc}"
            else:
                argument_error = None if isinstance(args, dict) else "工具参数必须是 JSON 对象"
            notice("tool", f"{name}({json.dumps(args, ensure_ascii=False)[:160]})")
            tool = REGISTRY.get(name)
            if not argument_error and tool is not None:
                try:
                    if tool.argument_validator is not None:
                        tool.argument_validator(args)
                    else:
                        validate(args, tool.parameters)
                    if name == "finish_task" and len(tool_calls) != 1:
                        raise ValueError("finish_task must be the only tool call in its batch")
                except ValueError as exc:
                    argument_error = str(exc)
            error = None
            started = perf_counter()
            if argument_error:
                result = error = argument_error
            elif tool is None:
                result = error = f"未知工具: {name}"
            else:
                try:
                    if name in {"read_file", "search_code", "list_directory", "find_files", "write_file", "edit_file"}:
                        instructions.add_path(resolve(args.get("path", ".")))
                        changed = instructions.refresh(messages)
                        new_instructions_in_batch = new_instructions_in_batch or changed
                        if new_instructions_in_batch and name in {"write_file", "edit_file"}:
                            raise HookRejected("New scoped AGENTS.md instructions loaded; review them before retrying the modification")
                    hooks.emit("before_tool", id=tc["id"], name=name, arguments=args, turn=turn)
                except HookRejected as exc:
                    result = error = str(exc)
                else:
                    # Always inspect original arguments and enforce built-in permissions after hooks.
                    if tool.guard and (reason := tool.guard(args)):
                        result = error = f"已被安全策略拦截：{reason}"
                    elif not allowed(tool, args):
                        result = error = "权限策略或用户拒绝了本次调用；不得绕过限制，请说明原因。"
                    else:
                        result, error = _execute(tool, args)
                        if name == "verify_project" and error is None and not getattr(result, "success", False):
                            error = "One or more configured checks failed or no valid check result was returned"
                        if name == "compact_context" and error is None:
                            pending_compact.append(args.get("reason", ""))
            check_results=getattr(result,"checks",None)
            if name in {"run_bash", "verify_project"}:
                result = (f"[Execution evidence: id={tc['id']}; purpose={args.get('purpose', 'command') if isinstance(args, dict) else 'invalid'}; "
                          f"execution={'failed' if error else 'succeeded'}]\n" + str(result))
            preview, output_path = prepare_output(str(result), writer=output_writer)
            append({"role": "tool", "tool_call_id": tc["id"], "content": preview})
            hooks.emit("after_tool", id=tc["id"], name=name, arguments=args, error=error,
                       result=preview, output_path=output_path, elapsed=perf_counter() - started, turn=turn,
                       exit_code=0 if name in {"run_bash", "verify_project"} and error is None else None,
                       checks=check_results)
            notice("error" if error else "result", f"{name}: {str(result)[:120]}")
        state.sync_plan(messages)
        if state.completion is not None:
            hooks.emit("checkpoint", messages=messages)
            result = state.render()
            append({"role": "assistant", "content": result})
            if on_completion:
                from copy import deepcopy
                on_completion(deepcopy(state.completion))
            elif on_text:
                on_text(result)
            return result, "completed_" + state.completion["status"]
        if pending_compact:
            # All call/result pairs are complete before changing the context.
            reason = "; ".join(pending_compact)
            try:
                outcome = compress(turn, estimate_tokens(messages, schemas()), "tool", reason)
            except HookRejected as exc:
                if exc.event != "before_compact":
                    raise
                outcome = f"拒绝：{exc}。上下文未主动压缩。"
                notice("error", outcome)
            except Exception as exc:
                outcome = f"失败：{type(exc).__name__}: {exc}。原有或最近已保存的上下文继续保留。"
                notice("error", outcome)
            append({"role": "assistant", "content": "[compact_context 实际执行结果] " + outcome})
        hooks.emit("checkpoint", messages=messages)
    result = "(已达到最大工具调用轮数，任务中止)"
    append({"role": "assistant", "content": result})
    notice("error", result)
    if on_text:
        on_text(result)
    return result, "limit_reached"
