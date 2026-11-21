"""Fresh-context plan, execute, independently verify, fix, and finalize phases."""

import asyncio
import json
import math
import posixpath
import shlex
import sys
import time

from .config import Config
from .host_tools import HostTools
from .llm import AgentLoop
from .mcp import MCPCatalog
from .tools import ContainerTools, HOST_TOOLS, TOOLS, ToolDispatcher, install_engtools

SCRATCH = "/tmp/ple_work"
READ_ONLY = {"bash", "read_file", "extract_text", "inspect_office"}
READ_RULES = """You have read-only access by policy: never create, edit, delete or
overwrite deliverables or inputs. Do not use MCP operations that mutate state.
Bash is for inspection and independent recomputation only. Put all recomputation
scratch under /tmp/ple_work; do not write elsewhere, install packages or use the network.
Tool selection is not an OS sandbox: comply with these restrictions."""

PLAN_PROMPT = """ROLE: RECON_PLAN
Inspect the working directory and relevant input files before planning.
""" + READ_RULES + """
Answer ONLY a JSON object with this schema:
{"discipline":"...", "task_summary":"...",
 "deliverables":[{"path":"...", "format":"...", "contents_required":"..."}],
 "requirements":[{"id":"R1", "text":"...", "how_to_verify":"..."}],
 "given_data":[], "codes_standards":[], "approach_steps":[],
 "assumptions_needed":[], "risks":[]}
Atomize EVERY explicit ask, number, format, unit, naming rule and statement required
in the final answer into a separate requirement. Preserve exact paths and quantities.
Distinguish supplied facts from assumptions; identify missing data and code editions."""

DISCIPLINES = {
    "structural": "Structural: identify load paths and governing load combinations; cite code sections "
                  "and edition used, state material/support assumptions, carry units through calcs, "
                  "check strength and serviceability, sanity-check magnitudes against typical ranges.",
    "civil": "Civil/geotechnical: cite governing code sections and edition used, distinguish effective "
             "and total stress, state drainage/soil/hydrology assumptions, carry units, show calcs "
             "and check magnitudes against typical settlement, bearing or flow ranges.",
    "electrical": "Electrical: cite code sections and edition used; state phase, voltage, PF, demand "
                  "and derating assumptions. Carry units, show calcs, check current/voltage-drop/"
                  "fault magnitudes against typical ranges; use supplied tables, not invented NEC data.",
    "mechanical": "Mechanical: cite governing code sections and edition used; state fluid properties "
                  "and boundary conditions, carry units and show mass/energy/pressure calcs. "
                  "Sanity-check loads, velocities and equipment sizes against typical ranges.",
}

EXECUTE_PROMPT = """ROLE: EXECUTE
You are the responsible engineering expert. Complete the original instruction.
Write real deliverables early, then improve them. No placeholders or TODOs.
Keep scratch and calculation logs under /tmp/ple_work, not in deliverable directories.
Record calculation descriptions, formulas, inputs, results and units with engtools
report.CalcLog where available. Include calculations in requested deliverables as needed.
State assumptions explicitly, cite actual code sections used, never invent a citation.
Host-side document tools run in the serve container even when task libraries are absent.
Before finishing, reopen and check deliverables and every checklist item."""

VERIFY_PROMPT = """ROLE: VERIFY
You are a fresh-context independent reviewer, not the executor.
""" + READ_RULES + """
Open EVERY planned deliverable and every deliverable named in the original instruction
or executor summary. Use extract_text/inspect_office for document content and integrity.
Independently recompute the 3–5 most consequential numbers (or all if fewer),
record evidence with units, and check EACH requirement, file name, format and assumption.
Do NOT modify deliverables. Do not accept the executor's claims without evidence.
Answer ONLY JSON:
{"verdict":"pass"|"fix", "issues":[{"severity":"critical"|"major"|"minor",
 "requirement_id":"R1", "problem":"...", "evidence":"...", "suggested_fix":"..."}]}
Use fix for missing deliverables, unverified consequential results or unmet requirements."""

FINAL_PROMPT = """ROLE: FINALIZE
Produce the final answer to the original instruction using existing deliverables only.
""" + READ_RULES + """
Briefly give deliverable paths, key numeric results WITH units, main assumptions,
and anything the task explicitly requires stated in the answer. Use deterministic
checks and prior summaries as evidence; never claim a missing/empty/broken file is
complete. Disclose unresolved major issues and checks that could not be completed.
Do not describe internal orchestration. Return the final answer, not JSON."""


def largest_json_object(text):
    """Decode the largest valid object, ignoring surrounding prose/code fences."""
    decoder = json.JSONDecoder()
    best, size = None, -1
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(text[index:])
        except ValueError:
            continue
        if isinstance(value, dict) and end > size:
            best, size = value, end
    if best is None:
        raise ValueError("No valid JSON object")
    return best


class PhaseSession:
    """Isolate streaming fallback text and count usage without losing task limits."""

    def __init__(self, session, deadline, fallback=""):
        self._session = session
        self.deadline = deadline
        self.final_message = fallback
        self.tokens = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}

    def __getattr__(self, name):
        return getattr(self._session, name)

    def time_left(self):
        left = self._session.time_left()
        step = max(0, self.deadline - time.monotonic())
        return step if left is None else min(step, left)

    async def usage(self, model, input_tokens, output_tokens, cache_read_tokens=0):
        for key, value in zip(self.tokens, (input_tokens, output_tokens, cache_read_tokens)):
            self.tokens[key] += value
        await self._session.usage(model, input_tokens, output_tokens, cache_read_tokens)


class Orchestrator:
    def __init__(self, session, config=None, client=None):
        self.session = session
        self.config = config or Config.from_env()
        self.client = client
        now = time.monotonic()
        candidates = []
        for value in (getattr(session, "deadline", None),):
            if isinstance(value, (float, int)) and math.isfinite(value):
                candidates.append(value)
        left = session.time_left()
        if left is not None and math.isfinite(left):
            candidates.append(now + max(0, left))
        limit = session.limits.get("agent_timeout_sec")
        if isinstance(limit, (float, int)) and math.isfinite(limit) and limit > 0:
            candidates.append(now + limit)
        self.deadline = min(candidates) if candidates else now + self.config.default_total_seconds
        self.total = max(0, self.deadline - now)
        self.reserve = min(self.total, max(self.config.final_reserve_seconds,
                                          self.total * self.config.final_reserve_share))
        self.trace = []
        self.summary = session.final_message or "No completed deliverables have been confirmed."
        self.plan = {"raw_plan": "Planning skipped; follow the original instruction directly."}
        self.engtools_doc = "engtools installation was unavailable; use task stdlib or host document tools."
        names = [spec["function"]["name"] for spec in TOOLS + HOST_TOOLS]
        self.catalog = MCPCatalog(session, names)
        self.mcp_prompt = ""

    def remaining(self, final=False):
        left = self.session.time_left()
        deadline = self.deadline if left is None else min(self.deadline, time.monotonic() + left)
        return max(0, deadline - time.monotonic() - (0 if final else self.reserve))

    def log(self, message):
        print(message, file=sys.stderr, flush=True)

    async def bounded(self, awaitable, seconds):
        return await asyncio.wait_for(awaitable, timeout=max(0, seconds))

    async def persist(self, name, value, final=False):
        try:
            await self.bounded(self.session.write_file(
                f"{SCRATCH}/{name}", json.dumps(value, ensure_ascii=False, indent=2)),
                min(10, self.remaining(final)))
        except (Exception, asyncio.CancelledError) as exc:
            self.log(f"[persist {name}] {type(exc).__name__}: {exc}")

    async def setup(self):
        for label, operation in (("engtools", lambda: install_engtools(self.session)),
                                 ("mcp", self.catalog.connect)):
            try:
                if self.remaining() < self.config.min_phase_seconds:
                    continue
                text = await self.bounded(operation(), min(self.config.setup_seconds, self.remaining()))
                if label == "engtools":
                    self.engtools_doc = text
                else:
                    self.mcp_prompt = text
            except (Exception, asyncio.CancelledError) as exc:
                self.log(f"[setup {label}] {type(exc).__name__}: {exc}")

    def dispatcher(self, phase_session, read_only, scratch_bash=False):
        dispatcher = ToolDispatcher(phase_session)
        container = ContainerTools(phase_session)
        container.finish_margin = min(180, max(0, phase_session.time_left()) / 4)
        dispatcher.register_container(container)
        dispatcher.register_host()
        if read_only:
            dispatcher.specs = [s for s in dispatcher.specs if s["function"]["name"] in READ_ONLY]
            dispatcher.handlers = {k: v for k, v in dispatcher.handlers.items() if k in READ_ONLY}
        if scratch_bash:
            async def recompute(command, timeout_sec=120):
                return await container.bash(
                    "mkdir -p /tmp/ple_work && cd /tmp/ple_work && bash -c " + shlex.quote(command),
                    timeout_sec)
            dispatcher.handlers["bash"] = recompute
        if self.catalog.connected:
            self.catalog.register(dispatcher)
        return dispatcher

    async def phase(self, role, system, user, share=1, read_only=False, final=False):
        budget = self.remaining(final) * share
        if final:
            budget = min(budget, self.config.finalize_seconds)
        if budget < (0.01 if final else self.config.min_phase_seconds):
            self.trace.append({"role": role, "status": "skipped", "budget_seconds": budget,
                               "seconds_used": 0, "tokens": None})
            self.log(f"[{role}] skipped: seconds=0.00 budget={budget:.2f}s")
            return ""
        start = time.monotonic()
        deadline = min(self.deadline, start + budget)
        fallback = self.summary if role == "execute" or role.startswith("fix") else ""
        session = PhaseSession(self.session, deadline, fallback)
        record = {"role": role, "status": "error", "budget_seconds": budget}
        loop = None
        text = ""
        try:
            dispatcher = self.dispatcher(session, read_only, role.startswith("verify"))
            loop = AgentLoop(session, system + "\n" + self.mcp_prompt,
                             user, dispatcher.specs, dispatcher, deadline=deadline,
                             role=role, client=self.client)
            text, _ = await self.bounded(loop.run(), budget)
            record.update(status="ok", text=text)
        except (Exception, asyncio.CancelledError) as exc:
            text = session.final_message
            record.update(error=f"{type(exc).__name__}: {exc}", text=text)
            self.log(f"[{role}] {record['error']}")
        finally:
            if loop is not None and self.client is None:
                try:
                    await self.bounded(loop.client.close(), min(2, self.remaining(final)))
                except (Exception, asyncio.CancelledError) as exc:
                    self.log(f"[{role}] client close: {exc}")
            record.update(seconds_used=time.monotonic() - start, tokens=session.tokens)
            self.trace.append(record)
            self.log(f"[{role}] status={record['status']} seconds={record['seconds_used']:.2f} "
                     f"tokens={json.dumps(session.tokens)}")
        return text

    def context(self):
        return ("ORIGINAL INSTRUCTION (verbatim):\n" + self.session.instruction
                + "\n\nPLAN:\n" + json.dumps(self.plan, ensure_ascii=False)
                + "\n\nREQUIREMENTS CHECKLIST:\n"
                + json.dumps(self.plan.get("requirements", []), ensure_ascii=False))

    def executor_prompt(self):
        discipline = str(self.plan.get("discipline", "")).lower()
        guidance = [text for name, text in DISCIPLINES.items() if name in discipline]
        return EXECUTE_PROMPT + "\n" + "\n".join(guidance or DISCIPLINES.values()) + "\n" + self.engtools_doc

    async def verify(self, round_number):
        text = await self.phase(f"verify-{round_number}", VERIFY_PROMPT,
                                self.context() + "\n\nEXECUTOR SUMMARY:\n" + self.summary,
                                share=self.config.verify_share, read_only=True)
        if not text:
            return None
        try:
            review = largest_json_object(text)
            if review.get("verdict") not in ("pass", "fix") or not isinstance(review.get("issues"), list):
                raise ValueError("Invalid review schema")
            return review
        except ValueError as exc:
            self.log(f"[verify-{round_number}] {exc}; retaining raw review in trace")
            return None

    async def deterministic_checks(self):
        checks = []
        deadline = time.monotonic() + min(self.config.final_check_seconds, self.remaining(final=True) * .4)
        deliverables = self.plan.get("deliverables", [])
        if not isinstance(deliverables, list):
            return [{"error": "Plan has no usable deliverable list"}]
        for item in deliverables:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"]:
                checks.append({"error": "Malformed planned deliverable", "item": item})
                continue
            path = item["path"]
            path = path if posixpath.isabs(path) else posixpath.join(self.session.workdir, path)
            check = {"path": path}
            try:
                available = max(0, deadline - time.monotonic())
                if available == 0:
                    check["error"] = "Final-check budget exhausted; file not checked"
                    checks.append(check)
                    continue
                result = await self.bounded(self.session.exec(
                    "test -s " + shlex.quote(path), timeout_sec=10),
                    min(10, available))
                check["nonempty"] = result["exit_code"] == 0
                if check["nonempty"] and posixpath.splitext(path)[1].lower() in (
                        ".docx", ".xlsx", ".xlsm", ".pdf", ".zip", ".pptx"):
                    check["inspection"] = await self.bounded(
                        HostTools(self.session).inspect_office(path),
                        min(15, max(0, deadline - time.monotonic())))
            except (Exception, asyncio.CancelledError) as exc:
                check["error"] = f"{type(exc).__name__}: {exc}"
                self.log(f"[final checks] {path}: {check['error']}")
            checks.append(check)
        return checks

    async def run(self):
        review = None
        checks = []
        try:
            await self.setup()
            text = await self.phase("recon-plan", PLAN_PROMPT,
                                    "ORIGINAL INSTRUCTION (verbatim):\n" + self.session.instruction
                                    + "\n\nWORKDIR: " + self.session.workdir,
                                    share=self.config.recon_share, read_only=True)
            if text:
                try:
                    self.plan = largest_json_object(text)
                except ValueError:
                    self.plan = {"raw_plan": text}
                    self.log("[recon-plan] malformed JSON; using raw text")
            await self.persist("plan.json", self.plan)
            text = await self.phase("execute", self.executor_prompt(), self.context(),
                                    share=self.config.execute_share)
            if text:
                self.summary = text
            self.session.final_message = self.summary
            review = await self.verify(0)
            for round_number in range(1, self.config.max_fix_rounds + 1):
                if not review or review["verdict"] != "fix" or not any(
                        isinstance(i, dict) and i.get("severity") in ("critical", "major")
                        for i in review["issues"]):
                    break
                text = await self.phase(
                    f"fix-{round_number}", self.executor_prompt() + "\nROLE: FIX\n"
                    "Correct the issues and re-verify the changed deliverables before summarizing.",
                    self.context() + "\n\nPREVIOUS SUMMARY:\n" + self.summary
                    + "\n\nREVIEW ISSUES:\n" + json.dumps(review, ensure_ascii=False),
                    share=self.config.fix_share)
                if not text:
                    break
                self.summary = text
                self.session.final_message = self.summary
                review = await self.verify(round_number)
            checks = await self.deterministic_checks()
            text = await self.phase(
                "finalize", FINAL_PROMPT,
                self.context() + "\n\nLAST EXECUTOR SUMMARY:\n" + self.summary
                + "\n\nLAST REVIEW:\n" + json.dumps(review, ensure_ascii=False)
                + "\n\nDETERMINISTIC CHECKS:\n" + json.dumps(checks, ensure_ascii=False),
                read_only=True, final=True)
            self.session.final_message = text or self.summary
        except (Exception, asyncio.CancelledError) as exc:
            self.log(f"[orchestrator] {type(exc).__name__}: {exc}")
            self.session.final_message = self.summary
        finally:
            self.session.final_message = self.session.final_message or self.summary
            await self.persist("trace.json", {
                "total_seconds": self.total, "final_reserve_seconds": self.reserve,
                "phases": self.trace, "last_review": review, "deliverable_checks": checks,
            }, final=True)
        return self.session.final_message


async def solve(session, config=None, client=None):
    """Run orchestration; an injected client is owned by the caller."""
    try:
        orchestrator = Orchestrator(session, config, client)
    except Exception as exc:
        print(f"[config] {type(exc).__name__}: {exc}; using defaults", file=sys.stderr)
        orchestrator = Orchestrator(session, Config(), client)
    return await orchestrator.run()
