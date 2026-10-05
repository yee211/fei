"""Explicit real-API evaluation; isolated fixture directories, not an OS sandbox."""
import json
import runpy
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from fei import config, llm, loop
from fei.cli import SYSTEM
from fei.hooks import HookRegistry
from fei.tools._paths import resolve

CASES = runpy.run_path(str(Path(__file__).with_name("eval_cases.py")))["CASES"]

def recovery_observed(calls):
    failed = next((i for i,c in enumerate(calls) if c["name"] == "run_bash" and c["arguments"].get("purpose") == "verification" and c["status"] == "error" and str(c["result"]).find("命令退出码") >= 0), None)
    if failed is None: return False
    edited = next((i for i,c in enumerate(calls) if i > failed and c["name"] in {"write_file", "edit_file"} and c["status"] == "ok"), None)
    return edited is not None and any(i > edited and c["name"] == "run_bash" and c["arguments"].get("purpose") == "verification" and c["status"] == "ok" for i,c in enumerate(calls))

def check_tests(folder):
    try:
        process = subprocess.run([sys.executable,"-B","-m","unittest","discover","-s",".","-p","test_solution.py","-v"],cwd=folder,capture_output=True,text=True,timeout=20)
        return process.returncode == 0, process.stdout + process.stderr
    except subprocess.TimeoutExpired:
        return False, "Independent validation timed out"

def main():
    project = Path(__file__).resolve().parents[1]
    output = project / "work" / "evals" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output.mkdir(parents=True)
    report = {"model":config.MODEL,"planned_cases":len(CASES),"cases":[]}
    for fixture in CASES:
        case_name=fixture["name"]
        folder=output/case_name;folder.mkdir()
        allowed={(folder/name).resolve() for name in fixture["files"]}
        for name,source in fixture["files"].items():
            target=folder/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(source,encoding="utf-8")
        test_path=folder/"test_solution.py";test_path.write_text(fixture["tests"],encoding="utf-8")
        instructions=folder/"AGENTS.md"
        instructions.write_text("Do not modify test_solution.py or AGENTS.md. Preserve public signatures. Use the specified test command. Submit finish_task with real verification IDs.\n",encoding="utf-8")
        protected={p:p.read_bytes() for p in (test_path,instructions)}
        for name,source in fixture.get("extra_files",{}).items():
            target=folder/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(source,encoding="utf-8");protected[target]=target.read_bytes()
        if fixture.get("configured_verification"):
            configuration=folder/".fei.json"
            configuration.write_text(json.dumps({"version":1,"checks":{"test":{"category":"test","argv":["{python}","-B","-m","unittest","discover","-s",".","-p","test_solution.py","-v"],"timeout":20}}}),encoding="utf-8")
            protected[configuration]=configuration.read_bytes()
        baseline_passed,_=check_tests(folder)
        command=f'"{sys.executable}" -B -m unittest discover -s . -p test_solution.py -v'
        hooks=HookRegistry();usage={"prompt_tokens":0,"completion_tokens":0}
        def usage_hook(event):
            for key in usage: usage[key]+=(event.data["usage"] or {}).get(key,0)
        hooks.register("after_model",usage_hook)
        hooks.register("after_summary",usage_hook)
        def guard(event):
            name=event.data["name"];args=event.data["arguments"]
            if name in {"write_file","edit_file"} and resolve(args.get("path","")).resolve() not in allowed:
                return "Modify only: " + ", ".join(fixture["files"])
            if name in {"read_file","search_code","list_directory","find_files"} and not resolve(args.get("path",".")).resolve().is_relative_to(folder.resolve()):
                return "Read only inside the evaluation folder"
            if name == "run_bash" and args.get("command") != command:
                return "Only the exact provided test command is allowed: " + command
            if name == "revert_change": return "Rollback disabled in this evaluation"
        hooks.register("before_tool",guard)
        record={};started=time.monotonic();error=None
        print("Starting "+case_name,flush=True)
        with patch.object(config,"WORKDIR",folder),patch.object(config,"REQUEST_TIMEOUT",20),patch.object(config,"REQUEST_RETRIES",0),patch.object(loop,"MAX_TURNS",20),patch.object(config,"COMPACT_TOKENS",24000 if fixture.get("long_context") else 48000):
            try:
                with llm.make_client() as client:
                    goal=fixture["goal"]+" Files: "+", ".join(fixture["files"])+". Do not modify tests or AGENTS.md. Use run_bash(purpose=verification). Exact allowed test command: "+command
                    messages=[{"role":"system","content":SYSTEM},{"role":"user","content":goal}]
                    if fixture.get("long_context"):
                        for index in range(7):
                            call_id = f"synthetic_read_{index}"
                            messages.append({"role":"assistant","content":"Synthetic history fixture", "reasoning_content":"", "tool_calls":[{"id":call_id,"type":"function","function":{"name":"read_file","arguments":json.dumps({"path":"synthetic_history.txt"})}}]})
                            messages.append({"role":"tool","tool_call_id":call_id,"content":f"Synthetic historical note {index}; controlled fixture, not actual executed evidence. " + ("Earlier unrelated exploration of implementation alternatives. " * 70)})
                    loop.run_task(client,messages,hooks=hooks,confirm=lambda *args:True,task_record=record)
            except Exception as exc: error=type(exc).__name__
        code_passed,test_output=check_tests(folder)
        unchanged=all(p.is_file() and p.read_bytes()==original for p,original in protected.items())
        calls=record.get("tool_calls",[])
        recovery=recovery_observed(calls)
        compactions=len(record.get("context_compactions",[]))
        navigation=all(any(call["name"]==tool and call["status"]=="ok" for call in calls) for tool in ("list_directory","find_files"))
        project_verified=any(call["name"]=="verify_project" and call["status"]=="ok" for call in calls)
        accepted=record.get("status")=="completed_verified"
        passed=code_passed and unchanged and accepted and not baseline_passed and (not fixture.get("recovery") or recovery) and (not fixture.get("long_context") or compactions>0) and (not fixture.get("navigation") or navigation) and (not fixture.get("configured_verification") or project_verified)
        result={"name":case_name,"passed":passed,"baseline_failed":not baseline_passed,"code_tests_passed":code_passed,"completion_accepted":accepted,"protected_files_unchanged":unchanged,"recovery_observed":recovery,"navigation_observed":navigation,"project_verification_observed":project_verified,"context_compactions":compactions,"model_error":error,"elapsed_seconds":round(time.monotonic()-started,2),"tool_calls":len(calls),"tool_errors":sum(c["status"]=="error" for c in calls),"usage":usage,"agent_status":record.get("status"),"test_output":test_output}
        report["cases"].append(result)
        report["passed"]=sum(c["passed"] for c in report["cases"])
        report["completed_cases"]=len(report["cases"])
        report["success_rate"]=report["passed"]/report["completed_cases"]
        (folder/"task.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
        (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({k:v for k,v in result.items() if k!="test_output"},ensure_ascii=False),flush=True)
        if error in {"AuthenticationError","PermissionDeniedError","APIConnectionError","APITimeoutError","RateLimitError"}:break
    print("Report: "+str(output/"report.json"),flush=True)

if __name__=="__main__": main()
