import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fei.mcp_client import MCPManager, argument_validator, render_result, tool_name, remote_handler
from fei.tools import REGISTRY
from fei.permission import permission_request

class MCPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import mcp, jsonschema
        except ImportError:
            raise unittest.SkipTest("Install fei[mcp] for optional MCP tests")

    def test_schema_combinations_and_refs(self):
        schema = {"type":"object", "$defs":{"value":{"anyOf":[{"type":"string"},{"type":"null"}]}},
                  "properties":{"value":{"$ref":"#/$defs/value"}},"required":["value"]}
        check = argument_validator(schema)
        check({"value":None}); check({"value":"x","extra":1})
        with self.assertRaises(ValueError): check({"value":1})
        with self.assertRaises(ValueError): check({})
        self.assertNotIn("additionalProperties",schema)

    def test_no_remote_schema_fetch(self):
        check = argument_validator({"type":"object","properties":{"x":{"$ref":"https://example.com/schema"}}})
        with self.assertRaises(ValueError): check({"x":1})

    def test_namespace(self):
        self.assertNotEqual(tool_name("a","x.y"),tool_name("a","x_y"))
        self.assertLessEqual(len(tool_name("a","x"*100)),64)
        self.assertNotEqual(tool_name("a","x"),tool_name("b","x"))

    def test_results_and_errors(self):
        result=SimpleNamespace(content=[SimpleNamespace(type="text",text="hello"),SimpleNamespace(type="image")],structuredContent={"n":1},isError=False)
        self.assertIn("hello",render_result(result)); self.assertIn('"n": 1',render_result(result))
        result.isError=True
        with self.assertRaises(RuntimeError):render_result(result)

    def test_remote_name_cannot_be_overridden(self):
        c=Mock(); remote_handler(c,"actual")(_remote="other")
        c.call.assert_called_once_with("actual",{"_remote":"other"})

    def test_config_decline_and_unsupported(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"config.json"
            p.write_text(json.dumps({"version":1,"servers":{"test":{"command":"never-execute"}}}))
            m=MCPManager();m.load(p,lambda *args:False);self.assertEqual(m.names,[])
            p.write_text(json.dumps({"version":1,"servers":{"test":{"command":"x","transport":"http"}}}))
            with self.assertRaises(ValueError):m.load(p,lambda *args:True)

    def test_timeout_closes_connection(self):
        from fei.mcp_client import StdioConnection
        with tempfile.TemporaryDirectory() as d:
            script=Path(d)/"slow.py"
            script.write_text("from mcp.server.fastmcp import FastMCP\nimport asyncio\nm=FastMCP('slow')\n@m.tool()\nasync def slow()->str:\n await asyncio.sleep(30)\n return 'late'\nm.run(transport='stdio')\n")
            connection=StdioConnection(sys.executable,[str(script)],d,timeout=1)
            with self.assertRaises(Exception):connection.call("slow",{})
            self.assertFalse(connection.thread.is_alive())
            connection.close()

    def test_live_stdio_lifecycle(self):
        m=MCPManager(); original=set(REGISTRY)
        try:
            m.connect("readonly",sys.executable,["examples/readonly_mcp.py"],Path.cwd(),timeout=10)
            self.assertEqual(len(m.names),2)
            tool=REGISTRY[tool_name("readonly","root_files")]
            tool.argument_validator({"suffix":None})
            self.assertIn("readonly/root_files",permission_request(tool,{}))
            self.assertIn("pyproject.toml",tool.handler(suffix=".toml"))
            result=REGISTRY[tool_name("readonly","project_info")].handler()
            self.assertIn('"pid"',result)
            connection=m.connections[0]
            from fei import loop
            from fei.hooks import HookRegistry
            calls=[{"id":"mcp-test","function":{"name":tool.name,"arguments":'{"suffix":".toml"}'}}]
            events=[]; hooks=HookRegistry()
            hooks.register("after_tool",lambda event:events.append(event.data))
            messages=[]
            with patch.object(loop,"_chat",side_effect=[("",calls,None),("done",[],None)]):
                loop.run_task(None,messages,hooks=hooks,confirm=lambda *args:True)
            self.assertIn("pyproject.toml",next(msg["content"] for msg in messages if msg.get("role")=="tool"))
            self.assertEqual(len(events),1)
            with patch.object(loop,"_chat",side_effect=[("",calls,None),("done",[],None)]), patch.object(connection,"call") as invoke:
                loop.run_task(None,[],confirm=lambda *args:False)
                invoke.assert_not_called()
            hooks.register("before_tool",lambda event:"MCP blocked by hook")
            with patch.object(loop,"_chat",side_effect=[("",calls,None),("done",[],None)]), patch.object(connection,"call") as invoke:
                loop.run_task(None,[],hooks=hooks,confirm=lambda *args:True)
                invoke.assert_not_called()
        finally:m.close()
        self.assertFalse(connection.thread.is_alive())
        self.assertEqual(set(REGISTRY),original)
        m.close()

if __name__ == "__main__":unittest.main()
