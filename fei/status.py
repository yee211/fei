"""Read-only UI projection of current context and latest task record."""
import json
from fei.task_state import TaskState

LABELS = {"pending":"待办", "in_progress":"进行中", "completed":"完成", "running":"执行中", "returned":"已返回", "completed_verified":"已完成（验证通过）", "completed_unverified":"已完成（未确认验证）", "completed_incomplete":"未完成", "incomplete":"未完成", "failed":"失败", "interrupted":"已中断", "limit_reached":"达到轮数上限", "budget_exceeded":"达到模型预算上限", "loop_detected":"检测到无效循环"}

def render_status(messages, record, mode):
    lines = ["权限：" + mode]
    if record:
        goal = " ".join(str(record.get('goal','')).split())
        lines.append("最近任务：" + (goal[:140] + '…' if len(goal)>140 else goal))
        budget = record.get("budget")
        if budget:
            lines.append("工具调用：" + str(budget.get("tool_calls",0)) + " / " + str(budget.get("tool_limit","?")))
            lines.append("模型消耗：" + str(budget["requests"]) + " 次请求，" + str(budget["tokens"]) + " tokens" + ("（含估算）" if budget.get("contains_estimates") else ""))
        if budget:
            rate = budget.get("cache_hit_rate")
            if rate is None:
                lines.append("缓存命中：暂无服务端统计。")
            else:
                lines.append("缓存命中：" + format(rate,".1%") + "；命中 " + str(budget["cache_hit_tokens"]) + " / 未命中 " + str(budget["cache_miss_tokens"]) + " tokens（" + str(budget.get("cache_reported_requests",0)) + " 次有统计的请求）")
        status = record.get('status','unknown')
        lines.append("状态：" + LABELS.get(status,status))
    else:
        lines.append("暂无当前会话任务记录。")
    snapshot = next((m for m in reversed(messages) if TaskState.is_plan_message(m)), None)
    if snapshot:
        try:
            plan = json.loads(snapshot['content'][len(TaskState.PLAN_PREFIX):])
            lines.append("计划" + ("（已关闭）" if plan.get('closed') else "") + "：")
            for step in plan['steps']:
                lines.append("- " + LABELS.get(step['status'],step['status']) + "：" + step['title'])
        except (ValueError, KeyError, TypeError):
            lines.append("计划快照无效，未显示。")
    if record:
        for child in record.get('subagents',[]):
            if child.get('kind') == 'worker':
                lines.append('子任务审阅：' + child.get('review', {}).get('status', 'pending'))
            status = child.get('status','unknown')
            lines.append("子任务 [" + child.get('kind','explore') + "]：" + LABELS.get(status,status) + "；" + str(child.get('goal',''))[:100])
        paths=[]
        calls=list(record.get('tool_calls',[]))
        for child in record.get('subagents',[]):
            calls.extend(child.get('tool_calls',[]))
        for call in calls:
            if call['name'] in {'write_file','edit_file'} and call.get('status')=='ok' and not str(call.get('result','')).startswith('No changes'):
                path=call.get('arguments',{}).get('path','')
                if path and path not in paths:paths.append(path)
        lines.append("记录的修改文件：" + ("、".join(paths[:20]) if paths else "无"))
        checks=[c for c in record.get('tool_calls',[]) if c['name']=='verify_project' or (c['name']=='run_bash' and c.get('arguments',{}).get('purpose')=='verification')]
        if checks:
            latest=checks[-1]
            lines.append("主任务最近验证：" + ("执行成功" if latest.get('status')=='ok' else "执行失败") + "；ID=" + latest['id'])
            lines.append("完成提交：" + str(record.get('verification','未确认')) + "（命令成功不等于整体任务已验收）")
        else:
            lines.append("主任务验证：无实际验证记录。")
    return "\n".join(lines)
