import runpy
import tempfile
import unittest
from pathlib import Path

MODULE = runpy.run_path(str(Path(__file__).with_name("eval_tasks.py")))
CASES = MODULE["CASES"]
REFERENCES = {
    "fix_clamp": {"solution.py": "def clamp(value,low,high):\n    return max(low,min(high,value))\n"},
    "add_parse_bool": {"solution.py": "def parse_bool(text):\n    value=text.strip().lower()\n    if value in ('true','yes','1'): return True\n    if value in ('false','no','0'): return False\n    raise ValueError(value)\n"},
    "cross_file_checkout": {"pricing.py": "def subtotal(items):\n    return sum(i['price']*i['quantity'] for i in items)\n", "checkout.py": "from pricing import subtotal\ndef total(items,discount_percent=0):\n    return subtotal(items)*(1-discount_percent/100)\n"},
    "feature_retry_delay": {"solution.py": "def retry_delay(attempt,base=1,cap=30):\n    if attempt<0 or base<0 or cap<0: raise ValueError()\n    return min(cap,base*2**attempt)\n"},
    "failure_recovery": {"solution.py": "def parse_numbers(text):\n    return [int(p.strip()) for p in text.split(',') if p.strip()]\n"},
    "long_context": {"solution.py": "SENTINEL='keep-me'\ndef normalize_tags(tags):\n    return list(dict.fromkeys(t.strip().lower() for t in tags if t.strip()))\n"},
}

REFERENCES["project_navigation_verify"]={
    "shop/pricing.py":"def subtotal(items):\n    return sum(item['price']*item['quantity'] for item in items)\n",
    "shop/checkout.py":"from .pricing import subtotal\ndef total(items,discount_percent=0):\n    return subtotal(items)*(1-discount_percent/100)\n",
}

class EvaluationSuiteTests(unittest.TestCase):
    def test_all_fixtures_fail_before_and_pass_with_reference(self):
        for fixture in CASES:
            with self.subTest(name=fixture["name"]), tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                for name,source in fixture["files"].items():
                    target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(source,encoding="utf-8")
                (root/"test_solution.py").write_text(fixture["tests"],encoding="utf-8")
                self.assertFalse(MODULE["check_tests"](root)[0])
                for name,source in REFERENCES[fixture["name"]].items(): (root/name).write_text(source,encoding="utf-8")
                self.assertTrue(MODULE["check_tests"](root)[0])
    def test_recovery_requires_execution_failure_edit_and_success(self):
        failed={"name":"run_bash","arguments":{"purpose":"verification"},"status":"error","result":"命令退出码 1"}
        edit={"name":"edit_file","arguments":{},"status":"ok","result":"changed"}
        passed={"name":"run_bash","arguments":{"purpose":"verification"},"status":"ok","result":"passed"}
        self.assertTrue(MODULE["recovery_observed"]([failed,edit,passed]))
        self.assertFalse(MODULE["recovery_observed"]([edit,failed,passed]))
        denied={**failed,"result":"Hook denied command"}
        self.assertFalse(MODULE["recovery_observed"]([denied,edit,passed]))
    def test_required_coverage_exists(self):
        self.assertEqual(len(CASES),7)
        self.assertTrue(any(len(c["files"])>1 for c in CASES))
        self.assertTrue(any(c.get("long_context") for c in CASES))
        self.assertTrue(any(c.get("recovery") for c in CASES))

if __name__=="__main__": unittest.main()
