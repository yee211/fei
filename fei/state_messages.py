"""Append dynamic snapshots at complete message boundaries; merge only on compression."""

def append_snapshot(messages, message, matches):
    previous = next((m for m in reversed(messages) if matches(m)), None)
    if previous == message:
        return
    # If interruption left a partial tool batch, keep the snapshot before that
    # newly generated batch so CLI cleanup does not discard durable task state.
    index = len(messages)
    for i,m in enumerate(messages):
        calls = m.get('tool_calls',[])
        if calls:
            pending={call['id'] for call in calls}
            for result in messages[i+1:]:
                if result.get('role') != 'tool':break
                pending.discard(result.get('tool_call_id'))
            if pending:
                index=i
                break
    messages.insert(index,message)

def compact_system_messages(messages):
    from fei.task_state import TaskState
    from fei.skills import MARKER
    from fei.instructions import MARKER as PROJECT_MARKER
    project = None
    plan = None
    skills = None
    fixed=[]
    for message in messages:
        if message.get('role') != 'system':continue
        if TaskState.is_plan_message(message):plan=message
        elif str(message.get('content','')).startswith(MARKER):skills=message
        elif str(message.get("content","")).startswith(PROJECT_MARKER):project=message
        else:fixed.append(message)
    return fixed+[m for m in (project,plan,skills) if m is not None]
