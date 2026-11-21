import asyncio
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from ple_harness import common
from ple_harness.llm import AgentLoop
from ple_harness.mcp import MCPCatalog
from ple_harness.tools import ContainerTools, ToolDispatcher


class FakeSession:
    def __init__(self, directory):
        self.workdir = str(directory)
        self.limits = {}
        self.final_message = ""
        self.mcp_servers = []
        self.logs = []
        self.usages = []

    def time_left(self):
        return 600

    async def exec(self, command, timeout_sec=120):
        result = subprocess.run(command, shell=True, cwd=self.workdir,
                                capture_output=True, text=True, timeout=timeout_sec)
        return {"exit_code": result.returncode, "output": result.stdout + result.stderr}

    async def read_file(self, path):
        return Path(path).read_bytes()

    async def write_file(self, path, data, append=False):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("ab" if append else "wb") as stream:
            stream.write(data.encode() if isinstance(data, str) else data)
        return target.stat().st_size

    async def log(self, text):
        self.logs.append(text)

    async def usage(self, *args):
        self.usages.append(args)


class FakeClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []
        self.chat = NS(completions=NS(create=self.create))

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        reply = next(self.replies)

        async def chunks():
            for delta, finish in reply:
                yield NS(usage=None, choices=[NS(delta=delta, finish_reason=finish)])
        return chunks()


def text_delta(text):
    return NS(content=text, tool_calls=None)


def test_loop_with_streamed_tool(tmp_path):
    async def scenario():
        session = FakeSession(tmp_path)
        dispatcher = ToolDispatcher(session)
        dispatcher.register_container(ContainerTools(session))
        call = NS(index=0, id="call_1", type="function",
                  function=NS(name="write_file", arguments=json.dumps(
                      {"path": "answer.txt", "content": "hello"})))
        client = FakeClient([
            [(NS(content=None, tool_calls=[call]), "tool_calls")],
            [(text_delta("Delivered answer.txt"), "stop")],
        ])
        loop = AgentLoop(session, "system", "write a file", dispatcher.specs,
                         dispatcher, deadline=time.monotonic() + 60, client=client)
        answer, history = await loop.run()
        assert answer == "Delivered answer.txt"
        assert (tmp_path / "answer.txt").read_text() == "hello"
        assert any(m["role"] == "tool" for m in history)
        assert all(r["stream"] for r in client.requests)
    asyncio.run(scenario())


@pytest.mark.parametrize("arguments,valid", [
    ('{"x": 1}', True), ("", True), ("{}", True),
    ('{"x": NaN}', False), ("[]", False), ("null", False), ("{", False),
])
def test_arguments(arguments, valid):
    result = common.parse_arguments({"name": "tool", "arguments": arguments})
    assert isinstance(result, dict) is valid


def test_clip():
    assert common.clip("") == ""
    assert common.clip("abc") == "abc"
    assert len(common.clip("x" * 1000, 100)) < 200


def test_marking(monkeypatch):
    messages = [{"role": "system", "content": "rules"},
                {"role": "user", "content": "task"}]
    monkeypatch.setattr(common, "CACHE_MARK", True)
    marked = common.marked(messages)
    assert marked[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert marked[-1]["content"][0]["text"] == "task"
    assert messages[0]["content"] == "rules"
    assert common.marked([]) == []
    monkeypatch.setattr(common, "CACHE_MARK", False)
    assert common.marked(messages) is messages


def test_tools_and_catalog(tmp_path):
    async def scenario():
        session = FakeSession(tmp_path)
        dispatcher = ToolDispatcher(session)
        container = ContainerTools(session)
        dispatcher.register_container(container)
        assert "no tool" in await dispatcher("missing", {})
        assert "error:" in await dispatcher("write_file", {})
        await dispatcher("write_file", {"path": "empty", "content": ""})
        assert await dispatcher("read_file", {"path": "empty"}) == "(empty file)"
        assert "not found" in await dispatcher("edit_file", {
            "path": "empty", "old_text": "absent", "new_text": "new"})
        assert "exit code 0" in await dispatcher("bash", {"command": "printf hi"})
        with pytest.raises(ValueError):
            dispatcher.register(dispatcher.specs[0], container.bash)
        catalog = MCPCatalog(session)
        assert await catalog.connect() == ""
        assert await catalog.connect() == ""
        assert "no tool" in await catalog.dispatch("unknown", {})
    asyncio.run(scenario())


def test_step_deadline_finish(tmp_path):
    async def scenario():
        session = FakeSession(tmp_path)
        client = FakeClient([[(text_delta("summary"), "stop")]])
        loop = AgentLoop(session, "rules", [], [], None,
                         deadline=time.monotonic() + 0.05, client=client)
        loop.finish_margin = 1
        answer = await loop.finish("Step ending.")
        assert answer == "summary"
        assert client.requests[0]["tool_choice"] == "none"
        assert loop.time_left() < 0.1
    asyncio.run(scenario())
