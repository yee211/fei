import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from fei import config, context, loop, skills, session
from fei.approval import ApprovalService
from fei.task_state import TaskState, current_task
from fei.tools import schemas, active_tool_names
from fei.tools.environment import get_environment

class SubagentSkillsTests(unittest.TestCase):
    def call(self, name, args, ident):
        return {"id":ident, "function":{"name":name, "arguments":json.dumps(args)}}

    def test_child_cannot_write_shell_or_recurse_even_full(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, "WORKDIR", Path(folder)):
            (Path(folder)/"a.py").write_text("def example(): pass")
            messages = [{"role":"user", "content":"private parent history"}]
            child_calls = [self.call("write_file", {"path":"bad.py", "content":"bad"}, "write"), self.call("run_bash", {"command":"echo bad"}, "shell"), self.call("explore_code", {"question":"recursive"}, "recursive"), self.call("read_file", {"path":"a.py"}, "read")]
            responses = iter([("", [self.call("explore_code", {"question":"inspect a.py"}, "explore")], None), ("", child_calls, None), ("a.py:1 defines example; no execution performed", [], None), ("parent answer", [], None)])
            snapshots = []
            def chat(client, incoming, on_text=None):
                import copy
                snapshots.append(copy.deepcopy(incoming))
                return next(responses)
            record = {}
            with patch.object(loop, "_chat", side_effect=chat):
                self.assertEqual(loop.run_task(None, messages, permission_policy=ApprovalService(mode="full"), task_record=record), "parent answer")
            self.assertFalse((Path(folder)/"bad.py").exists())
            self.assertEqual([c["name"] for c in record["tool_calls"]], ["explore_code"])
            child = record["subagents"][0]
            self.assertEqual([c["status"] for c in child["tool_calls"]], ["error", "error", "error", "ok"])
            self.assertNotIn("private parent history", json.dumps(snapshots[1]))
            self.assertIsNone(current_task.get())
            self.assertIsNone(active_tool_names.get())

    def test_schema_isolation_uses_real_model_adapter(self):
        seen = []
        def create(**kwargs):
            seen.append({t["function"]["name"] for t in kwargs["tools"]})
            message = types.SimpleNamespace(content="explored", tool_calls=[], reasoning_content=None)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)], usage=None)
        client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
        from fei.subagent import explore, READ_TOOLS
        from fei.hooks import HookRegistry
        parent = TaskState()
        explore(client, "find code", parent, None, ApprovalService(mode="full"), None, HookRegistry())
        self.assertEqual(seen, [set(READ_TOOLS)])
        self.assertIn("write_file", {t["function"]["name"] for t in schemas()})

    def test_child_turn_limit_and_guard_inheritance(self):
        from fei.subagent import explore
        from fei.hooks import HookRegistry
        hooks = HookRegistry()
        hooks.register("before_tool", lambda event: "read forbidden" if event.data["name"] == "read_file" else None)
        parent = TaskState()
        call = self.call("read_file", {"path":"README.md"}, "read")
        with patch.object(config, "REPEAT_LIMIT", 10), patch.object(config, "CONSECUTIVE_ERROR_LIMIT", 10), patch.object(loop, "_chat", return_value=("", [call], None)) as chat:
            result = json.loads(explore(None, "inspect", parent, None, ApprovalService(mode="full"), None, hooks.guards_copy()))
        self.assertEqual(chat.call_count, 8)
        self.assertEqual(result["status"], "limit_reached")
        self.assertTrue(all(c["status"] == "error" for c in parent.subagents[0]["tool_calls"]))
        parent.subagents *= 4
        with self.assertRaises(ValueError):
            explore(None, "inspect", parent, None, None, None, hooks)

    def test_child_outside_read_requires_permission_without_ui(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, "WORKDIR", Path(folder)/"project"):
            outside = Path(folder)/"secret.txt"
            outside.write_text("PRIVATE")
            calls = [self.call("read_file", {"path":str(outside)}, "read")]
            record = {}
            with patch.object(loop, "_chat", side_effect=[("",calls,None),("denied",[],None)]):
                loop.run_task(None, [{"role":"user","content":"inspect"}], permission_policy=ApprovalService(), tool_names={"read_file"}, task_record=record)
            self.assertEqual(record["tool_calls"][0]["status"], "error")
            self.assertNotIn("PRIVATE", record["tool_calls"][0]["result"])

    def test_skills_traversal_budget_and_session_restore(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, "WORKDIR", Path(folder)), patch.object(session, "SESSIONS_DIR", Path(folder)/"sessions"):
            path = Path(folder)/".fei/skills/test/SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text("Preserve API; run existing tests", encoding="utf-8")
            self.assertEqual(json.loads(skills.list_skills())[0]["name"], "test")
            for name in ["../test", "a/b", "", "a"*65]:
                with self.assertRaises(ValueError): skills.skill_path(name)
            state = TaskState()
            token = current_task.set(state)
            try:
                skills.load_skill("test")
                messages = [{"role":"user", "content":"goal"}]
                skills.sync_skills(messages, state.skills)
                saved = session.Session()
                saved.save_state(messages)
                self.assertEqual(skills.restore_skills(session.Session.load_state(saved.path)), state.skills)
                path.write_text("x"*17000)
                with self.assertRaises(ValueError): skills.load_skill("test")
                self.assertIn("Preserve API", state.skills["test"]["instructions"])
            finally:
                current_task.reset(token)

    def test_loaded_skill_survives_compression_unchanged(self):
        loaded = {"test":{"source":"test", "instructions":"Do not change public API"}}
        messages = [{"role":"user", "content":"original goal"}]
        for i in range(5): messages.append({"role":"assistant", "content":"x"*2000})
        skills.sync_skills(messages, loaded)
        response = types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="memo"))])
        client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=Mock(return_value=response))))
        self.assertEqual(skills.restore_skills(context.compact_running(client, messages)), loaded)

    def test_environment_returns_locations_without_commands(self):
        result = json.loads(get_environment())
        self.assertEqual(result["workdir"], str(config.WORKDIR))
        self.assertTrue(Path(result["desktop"]).is_absolute())
        self.assertIn("desktop_exists", result)

if __name__ == "__main__": unittest.main()
