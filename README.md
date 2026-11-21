# PLE Agent Harness

Apache-2.0 competition harness derived from Google Research's PLE custom-openai
sample; see NOTICE for attribution. Run the WebSocket server with
`python serve.py` in the evaluator's environment.

## Development

```sh
uv run --with-requirements requirements.txt --with pytest pytest -q
uv run ruff check .
```

## Reusing the core

`AgentLoop(session, system_prompt, initial_messages, tools, dispatch,
deadline=None, role="agent", client=None)` accepts a user string or a list of
Chat Completions messages. `await loop.run()` returns `(final_text, history)`.
`deadline` is an absolute `time.monotonic()` timestamp; the earlier of it and
the session deadline governs streaming, retry waits, compaction and wrapping up.
An injected client must implement the OpenAI asynchronous streaming interface.
The caller owns and closes the client, including a default-created client.

`ToolDispatcher.register(spec, async_handler)` registers a function schema and
its keyword-argument handler. Register `ContainerTools(session, time_left)`
with `register_container`; the optional clock lets shell execution respect
the loop's step deadline. Unknown tools and malformed arguments become text
errors for the model.

Create one `MCPCatalog(session, reserved_names)` per task, call `connect()`
once (repeated calls are idempotent), then `register(dispatcher)`. Its returned
prompt describes direct tools or catalog search. The catalog and its connections
can be shared by multiple sequential loops without reconnecting.

The solve function runs the multi-phase orchestrator described below. Document
libraries are installed in the serve container only, not the task container.

## Engineering tools

The default solve registers serve-side `extract_text`, `write_docx`,
`write_xlsx`, and `inspect_office`. Inputs are stat-checked against the
10,000,000-byte protocol read limit; larger files require container-side
processing. Writes use 5,000,000-byte append chunks. Extraction clips text,
limits spreadsheets to 1000 rows/sheet, and rejects ZIPs whose declared
expanded size exceeds 100 MB. PDF `pages` are 1-based page numbers.

Spreadsheet formulas are written but not calculated by openpyxl. Extraction
reports both formula text and cached values where available; a newly generated
formula normally has no cached value until a spreadsheet engine recalculates it.
Inspection reports existing spreadsheet error cells; it does not evaluate formulas.

`install_engtools(session)` uploads all eight stdlib-only package files at
task start. The model receives instructions to use
`PYTHONPATH=/tmp/ple_work python3 script.py` and import `engtools`.
Module/function docstrings document formula sources, units and assumptions.
The helpers implement preliminary idealized calculations, not complete code
compliance checks. ASCE ELF requires a code-limited period and mapped S1 to
apply the high-seismic minimum. Conductor ampacity tables are caller-supplied.
The transformer short-circuit function includes the necessary 1000 conversion
from kVA to VA, so its output is amperes.

To run engineering checks without any site packages:

```sh
/usr/bin/python3 -I -S tests/test_engtools.py
```

## Multi-phase orchestration

`ple_harness.orchestrator.solve(session, config=None, client=None)` runs:

1. Read-only recon/planning, saving parsed JSON (or a raw-plan wrapper) to
   `/tmp/ple_work/plan.json`.
2. Execution using the original instruction, plan and atomized checklist.
3. Fresh-context independent verification, reopening deliverables and recomputing
   consequential numbers.
4. Up to two fix/review rounds for critical or major issues.
5. Deterministic nonempty-file checks and office inspections, then a short
   read-only loop producing the final answer.

MCP connections and the installed engineering package are reused across phases,
but model conversations are not. Executor summaries are retained as fallbacks;
planner/reviewer JSON never replaces the task's final message. Exceptions and
timeouts are logged to stderr, and phase timing/token outcomes and final checks
are saved best-effort in `/tmp/ple_work/trace.json`. Missing or malformed reviews
are not treated as passes.

Read-only phases omit the built-in write/edit/document-creation tools and instruct
the model not to modify inputs or deliverables, including through MCP. Reviewer
bash calls start in `/tmp/ple_work` and are restricted by prompt to inspection
and independent recomputation there. **This is a model/tool policy, not an OS
filesystem sandbox:** arbitrary bash and task-specific MCP tools can still write.

### Configuration

The frozen `Config` dataclass accepts these environment overrides. Fractions are
decimal shares of the **then-remaining work time after subtracting the final
reserve**, not shares of the original task budget:

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `PLE_DEFAULT_TOTAL_SECONDS` | 3600 | Total if no task deadline or positive limit is supplied |
| `PLE_RECON_SHARE` | 0.12 | Recon share; cannot exceed 0.12 |
| `PLE_EXECUTE_SHARE` | 0.55 | Initial execution share |
| `PLE_VERIFY_SHARE` | 0.15 | Each independent review share; cannot exceed 0.15 |
| `PLE_FIX_SHARE` | 0.65 | Each fix round's share |
| `PLE_MIN_PHASE_SECONDS` | 120 | Skip ordinary phases with smaller budgets |
| `PLE_FINAL_RESERVE_SECONDS` | 90 | Minimum reserved finalization time |
| `PLE_FINAL_RESERVE_SHARE` | 0.03 | Reserved fraction of initial total; use the larger reserve |
| `PLE_FINALIZE_SECONDS` | 90 | Maximum final-answer loop duration |
| `PLE_FINAL_CHECK_SECONDS` | 30 | Maximum deterministic-check time, also capped at 40% of time left |
| `PLE_SETUP_SECONDS` | 60 | Per-operation engtools/MCP setup timeout |
| `PLE_MAX_FIX_ROUNDS` | 2 | Maximum fix loops, each followed by a review if budget permits |

The total deadline is the earliest of the session deadline, current time plus
session time left, and current time plus the declared task limit. With none,
the configurable one-hour default is used. Each AgentLoop also gets its own
absolute monotonic step deadline, and an outer timeout bounds the entire phase,
including tools. Very short tasks skip ordinary phases and use their available
time for a final answer. Finalization is exempt from the 120-second threshold.
Invalid environment configuration is logged and defaults are used.
