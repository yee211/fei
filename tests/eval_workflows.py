"""Offline task-level evaluation: scripted decisions, actual file/test execution."""
import json
import runpy
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))

class Results(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.cases=[]
    def startTest(self,test):
        self.started=time.monotonic()
        super().startTest(test)
    def outcome(self,test,status,details=""):
        self.cases.append({"name":test.id(),"status":status,"elapsed_seconds":round(time.monotonic()-self.started,3),"details":details})
    def addSuccess(self,test):
        super().addSuccess(test);self.outcome(test,"passed")
    def addFailure(self,test,err):
        super().addFailure(test,err);self.outcome(test,"failed",self._exc_info_to_string(err,test))
    def addError(self,test,err):
        super().addError(test,err);self.outcome(test,"error",self._exc_info_to_string(err,test))
    def addSkip(self,test,reason):
        super().addSkip(test,reason);self.outcome(test,"skipped",reason)

def main():
    module=runpy.run_path(str(PROJECT/'tests/test_task_workflows.py'))
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(module['TaskWorkflowTests'])
    result=unittest.TextTestRunner(verbosity=2,resultclass=Results).run(suite)
    folder=PROJECT/'work/evals'/datetime.now().strftime('%Y%m%d-%H%M%S-workflows')
    folder.mkdir(parents=True,exist_ok=True)
    report={"mode":"scripted_model_real_tools", "external_model_called":False,
            "tests_run":result.testsRun,"passed":result.wasSuccessful(),"cases":result.cases}
    path=folder/'report.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Report: '+str(path))
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(main())
