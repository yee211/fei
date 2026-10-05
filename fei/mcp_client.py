"""Optional stdio MCP bridge; one async task owns each connection's lifetime."""
import asyncio
from concurrent.futures import Future
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import re
import sys
import threading

from fei.tools import REGISTRY, register
from fei.tools.base import Tool


def argument_validator(schema):
    from jsonschema.validators import validator_for
    from referencing import Registry
    cls = validator_for(schema)
    cls.check_schema(schema)
    validator = cls(schema, registry=Registry())  # Never retrieve remote references.
    def check(args):
        try:
            validator.validate(args)
        except Exception as exc:
            raise ValueError(f"MCP arguments invalid: {exc}") from exc
    return check


def tool_name(server, name):
    raw = f"mcp__{server}__{name}"
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", raw)
    if clean != raw or len(clean) > 64:
        clean = clean[:51] + "_" + hashlib.sha256(raw.encode()).hexdigest()[:12]
    return clean


def render_result(result):
    parts = []
    for block in result.content:
        if block.type == "text":
            parts.append(block.text)
        else:
            parts.append(f"[MCP {block.type} content omitted; this client supports text and structured results]")
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False))
    output = "\n".join(parts) or "[MCP returned no content]"
    if result.isError:
        raise RuntimeError(output)
    return output


class StdioConnection:
    def __init__(self, command, args, cwd, timeout=30):
        self.timeout = timeout
        self.ready = Future()
        self.loop = None
        self.queue = None
        self.task = None
        self.thread = threading.Thread(target=self._thread_main, name="fei-mcp", daemon=True)
        self.command, self.args, self.cwd = command, args, cwd
        self.thread.start()
        try:
            self.tools = self.ready.result(timeout + 5)
        except BaseException:
            self.close()
            raise

    def _thread_main(self):
        try:
            asyncio.run(self._serve())
        except BaseException as exc:
            if not self.ready.done():
                self.ready.set_exception(exc)

    async def _serve(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue()
        self.task = asyncio.current_task()
        params = StdioServerParameters(command=self.command, args=self.args, cwd=self.cwd)
        active = None
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=self.timeout)) as session:
                    async def discover():
                        await session.initialize()
                        tools, cursor, seen = [], None, set()
                        while True:
                            page = await session.list_tools(cursor=cursor)
                            tools.extend(page.tools)
                            cursor = page.nextCursor
                            if not cursor:
                                return tools
                            if cursor in seen or len(tools) > 1000:
                                raise ValueError("MCP tool pagination exceeds limit")
                            seen.add(cursor)
                    tools = await asyncio.wait_for(discover(), self.timeout)
                    self.ready.set_result(tools)
                    while True:
                        request = await self.queue.get()
                        if request is None:
                            break
                        name, args, active = request
                        try:
                            result = await session.call_tool(name, args, read_timeout_seconds=timedelta(seconds=self.timeout))
                            active.set_result(render_result(result))
                        except Exception as exc:
                            active.set_exception(exc)
                        finally:
                            active = None
        finally:
            if active is not None and not active.done():
                active.set_exception(RuntimeError("MCP connection closed"))
            while not self.queue.empty():
                request = self.queue.get_nowait()
                if request is not None and not request[2].done():
                    request[2].set_exception(RuntimeError("MCP connection closed"))

    def call(self, name, args):
        if not self.thread.is_alive() or self.loop is None:
            raise RuntimeError("MCP connection is closed")
        future = Future()
        self.loop.call_soon_threadsafe(self.queue.put_nowait, (name, deepcopy(args), future))
        try:
            return future.result(self.timeout + 5)
        except BaseException:
            # No retry: a remote operation may already have happened.
            self.close()
            raise

    def close(self):
        if self.loop is not None and self.thread.is_alive():
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass
            self.thread.join(10)
        if self.thread.is_alive():
            raise RuntimeError("MCP worker did not stop")


def remote_handler(connection, remote_name):
    def call(**kwargs):
        return connection.call(remote_name, kwargs)
    return call


class MCPManager:
    def __init__(self):
        self.connections = []
        self.names = []

    def connect(self, server, command, args, cwd, timeout=30):
        connection = StdioConnection(command, args, str(cwd), timeout)
        pending = []
        try:
            for remote in connection.tools:
                name = tool_name(server, remote.name)
                if name in REGISTRY or any(t.name == name for t in pending):
                    raise ValueError(f"Duplicate MCP tool: {name}")
                schema = deepcopy(remote.inputSchema)
                if schema.get("type") != "object":
                    raise ValueError("MCP tool input schema must be an object")
                pending.append(Tool(name, f"MCP {server}/{remote.name}: {remote.description or ''}", schema,
                    remote_handler(connection, remote.name),
                    needs_permission=True, argument_validator=argument_validator(schema),
                    source=f"{server}/{remote.name}"))
            for tool in pending:
                register(tool)
                self.names.append(tool.name)
            self.connections.append(connection)
        except BaseException:
            connection.close()
            raise

    def load(self, path, confirm):
        path = Path(path)
        if not path.exists():
            return
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError("Invalid MCP config file")
        config = json.loads(path.read_text(encoding="utf-8"))
        if type(config.get("version")) is not int or config["version"] != 1:
            raise ValueError("MCP config requires version=1")
        servers = config.get("servers")
        if not isinstance(servers, dict) or len(servers) > 20:
            raise ValueError("MCP servers must be an object with at most 20 entries")
        plans = []
        for name, spec in servers.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name) or not isinstance(spec, dict):
                raise ValueError("Invalid MCP server definition")
            if set(spec) - {"transport", "command", "args", "timeout"} or spec.get("transport", "stdio") != "stdio":
                raise ValueError("Only stdio MCP transport is supported")
            command, args, timeout = spec.get("command"), spec.get("args", []), spec.get("timeout", 30)
            if not isinstance(command, str) or not command.strip() or not isinstance(args, list) or not all(isinstance(a,str) for a in args):
                raise ValueError("MCP command/args invalid")
            if type(timeout) not in (int, float) or not 1 <= timeout <= 120:
                raise ValueError("MCP timeout must be 1..120 seconds")
            command = sys.executable if command == "{python}" else command
            plans.append((name, command, args, timeout))
        try:
            for name, command, args, timeout in plans:
                description = f"Start MCP server {name}\nCWD: {path.parent.resolve()}\nargv: {json.dumps([command,*args],ensure_ascii=False)}\nServer runs with your user permissions."
                if confirm(name, description):
                    self.connect(name, command, args, path.parent.resolve(), timeout)
        except BaseException:
            self.close()
            raise

    def close(self):
        errors = []
        for connection in reversed(self.connections):
            try:
                connection.close()
            except Exception as exc:
                errors.append(exc)
        self.connections.clear()
        for name in self.names:
            REGISTRY.pop(name, None)
        self.names.clear()
        if errors:
            raise RuntimeError(f"MCP shutdown failed: {errors}")
