"""Project-configured verification with an approved immutable execution plan."""
import hashlib
import json
import sys
from pathlib import Path
from fei import config
from fei.validation import validate
from fei.task_state import current_task
from fei.commands import run_command

class VerificationOutput(str):
    def __new__(cls,text,checks):
        value=super().__new__(cls,text);value.checks=checks
        value.success=bool(checks) and all(check['status']=='passed' for check in checks)
        return value

CHECK_SCHEMA={"type":"object","properties":{"argv":{"type":"array","items":{"type":"string","minLength":1},"minItems":1,"maxItems":100},"category":{"type":"string","enum":["test","lint","build"]},"timeout":{"type":"number","minimum":1,"maximum":600}},"required":["argv","category"],"additionalProperties":False}

def load_plan(checks=None):
    path=config.WORKDIR/'.fei.json'
    if not path.is_file():raise ValueError('No .fei.json verification configuration. Create explicit checks with category/argv/timeout; commands are never guessed.')
    if path.is_symlink():raise ValueError('.fei.json must not be a symlink')
    if path.stat().st_size>65536:raise ValueError('.fei.json exceeds 64 KiB')
    raw=path.read_bytes();data=json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data,dict) or set(data)-{'version','checks'} or (type(data.get('version')) is not int or data.get('version')!=1):raise ValueError('.fei.json requires version=1 and checks')
    definitions=data.get('checks')
    if not isinstance(definitions,dict) or not definitions or len(definitions)>20:raise ValueError('Configure 1..20 named checks')
    for name,definition in definitions.items():
        if not name or len(name)>100:raise ValueError('Check name must be 1..100 characters')
        validate(definition,CHECK_SCHEMA,f'checks.{name}')
    names=list(definitions) if not checks else checks
    if len(set(names))!=len(names):raise ValueError('Duplicate selected checks')
    if any(name not in definitions for name in names):raise ValueError('Unknown selected check; available: '+', '.join(definitions))
    selected=[]
    for name in names:
        definition=definitions[name]
        argv=[sys.executable if arg=='{python}' else arg for arg in definition['argv']]
        selected.append({'name':name,'category':definition['category'],'argv':argv,'timeout':definition.get('timeout',120)})
    return {'path':str(path.resolve()),'digest':hashlib.sha256(raw).hexdigest(),'checks':selected,'selected':names,'cwd':str(config.WORKDIR.resolve())}

def plan_description(plan):
    return '项目验证配置：'+plan['path']+'\n工作目录：'+plan['cwd']+'\n'+ '\n'.join(f"{check['name']} [{check['category']}] timeout={check['timeout']}s argv={json.dumps(check['argv'],ensure_ascii=False)}" for check in plan['checks'])

def verify_project(checks=None):
    task=current_task.get()
    if task is None or task.verification_plan is None:raise RuntimeError('verify_project requires an approved execution plan from the tool loop')
    plan=task.verification_plan;task.verification_plan=None
    if plan['selected']!=(checks or plan['selected']) or str(config.WORKDIR.resolve())!=plan['cwd']:raise RuntimeError('Approved plan does not match requested checks')
    raw=Path(plan['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=plan['digest']:raise RuntimeError('Verification configuration changed after approval; confirm again')
    from fei.permission import dangerous_command
    for check in plan['checks']:
        reason=dangerous_command(' '.join(check['argv']))
        if reason:raise RuntimeError('Configured command blocked: '+reason)
    results=[]
    for check in plan['checks']:
        try:
            process=run_command(check['argv'],cwd=plan['cwd'],timeout=check['timeout'],progress=task.progress)
            result={**check,'exit_code':process.returncode,'status':'passed' if process.returncode==0 else 'failed','output':process.stdout+process.stderr}
        except Exception as exc:
            result={**check,'exit_code':None,'status':'error','output':f'{type(exc).__name__}: {exc}'}
        results.append(result)
    return VerificationOutput(json.dumps({'configuration':plan['path'],'configuration_digest':plan['digest'],'checks':results},ensure_ascii=False,indent=2),results)

def guard(args):
    from fei.permission import dangerous_command
    try:
        plan=load_plan(args.get('checks'))
        for check in plan['checks']:
            reason=dangerous_command(' '.join(check['argv']))
            if reason:return reason
    except (OSError,ValueError,TypeError) as exc:return str(exc)
    return None
