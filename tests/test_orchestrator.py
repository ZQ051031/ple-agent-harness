import asyncio
import json
import time
from types import SimpleNamespace as NS

import pytest

from ple_harness.config import Config
from ple_harness.orchestrator import (
    Orchestrator, READ_ONLY, largest_json_object, solve,
)
from test_core import FakeSession, text_delta

INSTRUCTION = "Write result.txt containing 10 kN. State the assumption in the final answer."
PLAN = {
    "discipline": "structural", "task_summary": "Report the load",
    "deliverables": [{"path": "result.txt", "format": "txt", "contents_required": "10 kN"}],
    "requirements": [{"id": "R1", "text": "10 kN in result.txt", "how_to_verify": "Read file"}],
    "given_data": ["10 kN"], "codes_standards": [], "approach_steps": ["Write file"],
    "assumptions_needed": ["Given load"], "risks": [],
}


class TaskSession(FakeSession):
    instruction = INSTRUCTION

    def __init__(self, directory, seconds=3600):
        super().__init__(directory)
        self.deadline = time.monotonic() + seconds
        self.limits = {"agent_timeout_sec": seconds}
        self.scratch = directory / "scratch"

    def time_left(self):
        return self.deadline - time.monotonic()

    def translate(self, path):
        return str(path).replace("/tmp/ple_work", str(self.scratch))

    async def exec(self, command, timeout_sec=120):
        return await super().exec(self.translate(command), timeout_sec)

    async def read_file(self, path):
        return await super().read_file(self.translate(path))

    async def write_file(self, path, data, append=False):
        return await super().write_file(self.translate(path), data, append)


def write_call(value="10 kN"):
    return NS(content=None, tool_calls=[NS(
        index=0, id="write1", type="function",
        function=NS(name="write_file",
                    arguments=json.dumps({"path": "result.txt", "content": value})))])


class ScriptedClient:
    """Real AgentLoops consume role-routed streamed Chat Completions chunks."""

    def __init__(self, fix=False, plan=None, fail=None, severity="major"):
        self.chat = NS(completions=NS(create=self.create))
        self.fix = fix
        self.plan = json.dumps(PLAN) if plan is None else plan
        self.fail = fail
        self.severity = severity
        self.calls = {}
        self.requests = []

    async def create(self, **kwargs):
        messages = kwargs["messages"]
        content = messages[0]["content"]
        system = content if isinstance(content, str) else content[0]["text"]
        if "ROLE: FIX" in system:
            role = "fix"
        elif "ROLE: EXECUTE" in system:
            role = "execute"
        elif "ROLE: RECON_PLAN" in system:
            role = "plan"
        elif "ROLE: VERIFY" in system:
            role = "verify"
        else:
            role = "finalize"
        count = self.calls.get(role, 0)
        self.calls[role] = count + 1
        self.requests.append((role, kwargs))
        if role == self.fail:
            raise RuntimeError(f"scripted {role} failure")
        if role == "plan":
            delta, finish = text_delta(self.plan), "stop"
        elif role in ("execute", "fix"):
            if count == 0:
                delta, finish = write_call("5 kN" if self.fix and role == "execute" else "10 kN"), "tool_calls"
            else:
                delta, finish = text_delta("Delivered result.txt: 10 kN; assumed given load."), "stop"
        elif role == "verify":
            # Review must have a fresh context and no writable built-in tools.
            assert len(messages) == 2
            assert {t["function"]["name"] for t in kwargs["tools"]} == READ_ONLY
            if self.fix and count == 0:
                review = {"verdict": "fix", "issues": [{
                    "severity": self.severity, "requirement_id": "R1", "problem": "Wrong load",
                    "evidence": "File contains 5 kN, not 10 kN", "suggested_fix": "Use 10 kN"}]}
            else:
                review = {"verdict": "pass", "issues": []}
            delta, finish = text_delta(json.dumps(review)), "stop"
        else:
            assert INSTRUCTION in messages[1]["content"]
            delta, finish = text_delta("Final: result.txt; 10 kN; assumption: given load."), "stop"

        async def chunks():
            yield NS(usage=NS(prompt_tokens=12, completion_tokens=3,
                             prompt_tokens_details=NS(cached_tokens=2)),
                     choices=[NS(delta=delta, finish_reason=finish)])
        return chunks()


def run_task(tmp_path, client, seconds=3600, config=None):
    session = TaskSession(tmp_path, seconds)
    answer = asyncio.run(solve(session, config=config, client=client))
    trace = json.loads((session.scratch / "trace.json").read_text())
    return session, answer, trace


def test_happy_path(tmp_path, capsys):
    client = ScriptedClient()
    session, answer, trace = run_task(tmp_path, client)
    assert (tmp_path / "result.txt").read_text() == "10 kN"
    assert answer == session.final_message == "Final: result.txt; 10 kN; assumption: given load."
    assert [p["role"] for p in trace["phases"]] == ["recon-plan", "execute", "verify-0", "finalize"]
    assert all(p["status"] == "ok" for p in trace["phases"])
    assert trace["deliverable_checks"][0]["nonempty"]
    assert trace["phases"][0]["tokens"]["input_tokens"] == 12
    assert trace["phases"][0]["tokens"]["cache_read_tokens"] == 2
    assert json.loads((session.scratch / "plan.json").read_text()) == PLAN
    assert "[verify-0] status=ok" in capsys.readouterr().err
    for role, request in client.requests:
        if role in ("execute", "verify", "finalize"):
            assert INSTRUCTION in request["messages"][1]["content"]


def test_fix_round(tmp_path):
    client = ScriptedClient(fix=True)
    _, _, trace = run_task(tmp_path, client)
    assert (tmp_path / "result.txt").read_text() == "10 kN"
    assert [p["role"] for p in trace["phases"]] == [
        "recon-plan", "execute", "verify-0", "fix-1", "verify-1", "finalize"]
    fix_request = next(r for role, r in client.requests if role == "fix")
    assert "Wrong load" in fix_request["messages"][1]["content"]
    assert trace["last_review"]["verdict"] == "pass"


def test_malformed_plan(tmp_path):
    session, answer, _ = run_task(tmp_path, ScriptedClient(plan="not JSON, inspect files first"))
    assert "Final:" in answer
    assert (tmp_path / "result.txt").exists()
    assert json.loads((session.scratch / "plan.json").read_text())["raw_plan"] == "not JSON, inspect files first"


def test_tiny_budget(tmp_path):
    client = ScriptedClient()
    session, answer, trace = run_task(tmp_path, client, seconds=30)
    statuses = {p["role"]: p["status"] for p in trace["phases"]}
    assert statuses["recon-plan"] == statuses["verify-0"] == "skipped"
    assert statuses["finalize"] == "ok"
    assert answer == session.final_message
    assert list(client.calls) == ["finalize"]


@pytest.mark.parametrize("failed", ["plan", "execute", "verify", "finalize"])
def test_phase_failure_survives(tmp_path, failed, capsys):
    session, answer, trace = run_task(tmp_path, ScriptedClient(fail=failed))
    assert answer and answer == session.final_message
    assert any(p["status"] == "error" for p in trace["phases"])
    assert f"scripted {failed} failure" in capsys.readouterr().err
    if failed == "finalize":
        assert answer == "Delivered result.txt: 10 kN; assumed given load."


def test_largest_json_and_config():
    assert largest_json_object('noise {} ```json\n{"x":{"y":1}}\n```') == {"x": {"y": 1}}
    with pytest.raises(ValueError):
        largest_json_object("not json")
    assert Config.from_env({"PLE_MAX_FIX_ROUNDS": "1", "PLE_EXECUTE_SHARE": ".6"}).execute_share == .6
    for env in ({"PLE_RECON_SHARE": ".13"}, {"PLE_VERIFY_SHARE": ".2"},
                {"PLE_EXECUTE_SHARE": "nan"}, {"PLE_MAX_FIX_ROUNDS": "-1"}):
        with pytest.raises(ValueError):
            Config.from_env(env)


def test_budget_default_and_deadline(tmp_path):
    session = FakeSession(tmp_path)
    session.time_left = lambda: None
    start = time.monotonic()
    orchestrator = Orchestrator(session)
    assert start + 3599 < orchestrator.deadline < start + 3601
    assert 107 < orchestrator.reserve < 109
    session.deadline = time.monotonic() + 10
    session.limits = {"agent_timeout_sec": 1000}
    orchestrator = Orchestrator(session)
    assert orchestrator.total <= 10
    assert orchestrator.remaining() == 0


def test_timeout_and_no_cross_phase_fallback(tmp_path):
    class SlowClient:
        chat = None

        def __init__(self):
            self.chat = NS(completions=NS(create=self.create))

        async def create(self, **kwargs):
            await asyncio.sleep(10)

    async def scenario():
        orchestrator = Orchestrator(TaskSession(tmp_path), Config(min_phase_seconds=.01), SlowClient())
        # Model timeout cannot consume the finalization reserve.
        text = await orchestrator.phase("verify-timeout", "ROLE: VERIFY", "review", share=.00001)
        assert text == ""
        assert orchestrator.trace[-1]["seconds_used"] < 1
        assert orchestrator.remaining(final=True) > orchestrator.reserve
    asyncio.run(scenario())


def test_verify_bash_scratch_and_dispatch_filter(tmp_path):
    async def scenario():
        session = TaskSession(tmp_path)
        orchestrator = Orchestrator(session)
        from ple_harness.orchestrator import PhaseSession
        proxy = PhaseSession(session, time.monotonic() + 10)
        dispatcher = orchestrator.dispatcher(proxy, True, scratch_bash=True)
        assert set(dispatcher.handlers) == READ_ONLY
        assert "no tool" in await dispatcher("write_file", {"path": "bad", "content": "bad"})
        result = await dispatcher("bash", {"command": "pwd"})
        assert str(session.scratch) in result
    asyncio.run(scenario())


def test_final_checks_missing_empty_and_office(tmp_path):
    async def scenario():
        session = TaskSession(tmp_path)
        from ple_harness.host_tools import HostTools
        await HostTools(session).write_docx("out.docx", "# Valid")
        (tmp_path / "empty").write_text("")
        orchestrator = Orchestrator(session)
        orchestrator.plan = {"deliverables": [{"path": p} for p in ["missing", "empty", "out.docx"]]}
        checks = await orchestrator.deterministic_checks()
        assert [c["nonempty"] for c in checks] == [False, False, True]
        assert "paragraphs" in checks[-1]["inspection"]
    asyncio.run(scenario())


def test_fix_round_limit(tmp_path):
    client = ScriptedClient(fix=True)
    _, answer, trace = run_task(tmp_path, client, config=Config(max_fix_rounds=0))
    assert "Final:" in answer
    assert "fix" not in client.calls
    assert trace["last_review"]["verdict"] == "fix"


def test_trace_failure_is_nonfatal(tmp_path, capsys):
    class BrokenTraceSession(TaskSession):
        async def write_file(self, path, data, append=False):
            if path.endswith("trace.json"):
                raise RuntimeError("Trace storage unavailable")
            return await super().write_file(path, data, append)

    session = BrokenTraceSession(tmp_path)
    answer = asyncio.run(solve(session, client=ScriptedClient()))
    assert "Final:" in answer
    assert "Trace storage unavailable" in capsys.readouterr().err


def test_minor_issue_does_not_trigger_fix(tmp_path):
    client = ScriptedClient(fix=True, severity="minor")
    _, _, trace = run_task(tmp_path, client)
    assert "fix" not in client.calls
    assert trace["last_review"]["verdict"] == "fix"


def test_package_solve_delegates(monkeypatch, tmp_path):
    import ple_harness

    async def fake_orchestrator(session):
        session.final_message = "delegated"
        return session.final_message

    monkeypatch.setattr(ple_harness.orchestrator, "solve", fake_orchestrator)
    session = TaskSession(tmp_path)
    assert asyncio.run(ple_harness.solve(session)) == "delegated"
