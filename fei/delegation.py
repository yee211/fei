"""Serial worker: exact file capabilities and parent-selected verification argv."""
import json
import sys
from uuid import uuid4
from fei import config
from fei.tools._paths import resolve
from fei.permission import dangerous_command
from fei.commands import run_command
from fei.project_verify import VerificationOutput

WORKER_TOOLS = frozenset({"get_environment", "read_file", "search_code", "list_directory", "find_files", "write_file", "edit_file", "update_plan", "run_check", "finish_task"})

def plan(task, files, verification_argv, timeout=120):
    paths = [resolve(name).resolve() for name in files]
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate allowed files")
    for path in paths:
        if not path.is_relative_to(config.WORKDIR.resolve()):
            raise ValueError("Worker writes must remain inside workspace")
        relative = path.relative_to(config.WORKDIR.resolve())
        if path == config.WORKDIR.resolve() or path.is_dir() or any(part.startswith('.') for part in relative.parts):
            raise ValueError("Only explicit non-hidden files may be delegated")
    argv = [sys.executable if item == "{python}" else item for item in verification_argv]
    reason = dangerous_command(' '.join(argv))
    if reason:
        raise ValueError("Verification command blocked: " + reason)
    return {"task":task, "files":[str(path) for path in paths], "argv":argv, "timeout":timeout, "cwd":str(config.WORKDIR.resolve())}

def description(value):
    return "执行型子任务：" + value["task"] + "\n允许写入文件：" + json.dumps(value["files"],ensure_ascii=False) + "\n固定验收 argv：" + json.dumps(value["argv"],ensure_ascii=False) + "\n工作目录：" + value["cwd"] + "\n验收命令拥有当前用户权限；修改直接落盘，有回退记录。"

def run_check():
    from fei.task_state import current_task
    state = current_task.get()
    value = state.delegated_check if state else None
    if value is None:
        raise RuntimeError("run_check only available inside a delegated worker")
    reason = dangerous_command(' '.join(value['argv']))
    if reason:
        raise RuntimeError(reason)
    process = run_command(value['argv'], cwd=value['cwd'], timeout=value['timeout'], progress=state.progress)
    check = {"argv":value['argv'], "exit_code":process.returncode, "status":"passed" if process.returncode == 0 else "failed", "output":process.stdout+process.stderr}
    return VerificationOutput(json.dumps(check,ensure_ascii=False), [check])

def execute(client, value, parent, confirm, permissions, writer, hooks):
    from fei.loop import run_task
    from fei.changes import show_changes
    if len(parent.subagents) >= 4:
        raise ValueError("At most four subagents per task")
    record = {"id":uuid4().hex, "kind":"worker", "goal":value['task'], "contract":value}
    parent.subagents.append(record)
    messages = [{"role":"system", "content":
        "你是执行型子 Agent。只完成明确子任务，只能修改授权文件。不能运行任意命令、调用 MCP 或继续委派。"
        "先读再改；完成所有修改后用 run_check 执行固定验收，更新计划，再 finish_task 引用实际验收 ID。"
        "验证失败应修复并重试或报告 incomplete；不要篡改验收条件。最终简洁说明修改、验证和未完成事项。"},
        {"role":"user", "content":description(value)}]
    allowed = set(value['files'])
    def scope(event):
        if event.data['name'] in {'write_file','edit_file'}:
            path = resolve(event.data['arguments']['path']).resolve()
            if str(path) not in allowed:
                return "Worker write outside assigned files: " + str(path)
    hooks.register('before_tool', scope, critical=True)
    try:
        run_task(client, messages, confirm=confirm, permission_policy=permissions, hooks=hooks,
                 task_record=record, output_writer=writer, tool_names=WORKER_TOOLS, max_turns=16,
                 delegated_check=value)
    except Exception as exc:
        record['failure'] = f"{type(exc).__name__}: {exc}"
    finally:
        if writer:
            record['transcript_path'] = writer(json.dumps(messages,ensure_ascii=False,indent=2))
    changes = []
    for call in record.get('tool_calls',[]):
        if call['name'] in {'write_file','edit_file'} and call['status'] == 'ok':
            import re
            match = re.search(r'change_id=([a-f0-9]{32})',call['result'])
            if match:
                changes.append({"change_id":match.group(1), "path":call['arguments']['path'], "diff":show_changes(match.group(1))})
    payload = {"subtask_id":record['id'], "status":record.get('status','failed'),
               "completion":record.get('completion'), "failure":record.get('failure'), "changes":changes,
               "verification":[call for call in record.get('tool_calls',[]) if call['name']=='run_check'],
               "notice":"Changes are already applied. Parent must review diffs, call review_worker to accept or reject, and independently verify the overall task; child call IDs are not parent verification evidence."}
    record['review'] = {'status':'pending'}
    payload['review_status'] = 'pending'
    record['handoff'] = payload
    return json.dumps(payload,ensure_ascii=False)


def worker_record(subtask_id):
    from fei.task_state import current_task
    state = current_task.get()
    if state is None or state.delegated_check is not None:
        raise RuntimeError("Worker review requires an active parent task")
    record = next((item for item in state.subagents if item['id'] == subtask_id and item.get('kind') == 'worker'), None)
    if record is None or 'handoff' not in record:
        raise ValueError("Unknown or unfinished worker")
    return record


def review_worker(subtask_id, decision, reason):
    from fei.changes import validate_batch, revert_batch
    record = worker_record(subtask_id)
    if record.get('review', {}).get('status') != 'pending':
        raise ValueError("Worker already reviewed")
    if not reason.strip():
        raise ValueError("Review reason is required")
    if decision not in {'accept', 'reject'}:
        raise ValueError("Invalid review decision")
    ids = [item['change_id'] for item in record['handoff']['changes']]
    validate_batch(ids)
    if decision == 'accept':
        if record.get('status') != 'completed_verified' or record.get('failure'):
            raise ValueError("Cannot accept a worker without successful completion and verification")
    else:
        try:
            revert_batch(ids)
        except Exception as exc:
            record['review']['rollback_error'] = str(exc)
            raise
    record['review'] = {'status':'accepted' if decision == 'accept' else 'rejected', 'reason':reason}
    record['handoff']['review_status'] = record['review']['status']
    return json.dumps({'subtask_id':subtask_id, **record['review'], 'change_ids':ids,
        'notice':'Parent verification is still required. Rollback covers tracked tool edits only; check-command side effects are not tracked.'},ensure_ascii=False)
