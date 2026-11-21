# PLE Agent Harness: engineering deliverables under a deadline

*Kaggle writeup draft. Dev-set results: pending — requires HF token + model
access. Replace score placeholders only after a reproducible official run.*

## Problem and motivation

Physical-Engineering’s Last Exam evaluates an agent’s ability to complete realistic
engineering work, not merely answer isolated technical questions. Its structural,
civil, electrical and mechanical tasks ask for artifacts such as calculation
packages, design reviews and technical memos. Successful work must connect source
data, assumptions, numerical reasoning and the requested output format. A correct
number buried in chat is insufficient if the deliverable is missing or unreadable.

Our entry approaches that problem as a small engineering workflow. It separates
understanding the brief, producing the work and reviewing the result, while
preserving a simple deployment contract: one WebSocket server and one declared
model. The current competition configuration selects
`google-cloud/claude-opus-5-5`. The implementation is Apache-2.0, derived in part
from Google Research’s custom-openai sample with attribution retained in NOTICE.

## Plan, execute, independently verify, fix

The planning phase creates a structured JSON plan from the original instruction
and available inputs. It enumerates deliverables and atomizes explicit requirements:
paths, units, quantities, naming conventions and statements needed in the answer.
This provides a checklist that later contexts can inspect rather than relying on
an executor’s memory. If JSON parsing fails, the raw plan remains available and
execution continues; planning is assistance, not a brittle prerequisite.

Execution receives the original instruction verbatim alongside the plan. Short
discipline-specific guidance emphasizes units, explicit assumptions, traceable
calculations and appropriate code citations without fabricated references. The
executor is told to write real deliverables early, keep scratch work separate,
and avoid placeholders. This makes partial progress useful even if time expires.

Verification starts with a fresh conversation rather than extending the executor’s
self-justifying history. The reviewer is asked to reopen every deliverable,
independently recompute consequential quantities and assess each requirement.
Its structured verdict distinguishes critical, major and minor issues. Critical
or major findings can trigger a new executor context followed by another review,
with a default maximum of two fix rounds. This is independent context, not an
independent model: shared blind spots remain an important limitation.

## Budgeting and failure containment

Every loop receives a phase deadline bounded by the task deadline. Without a
supplied limit, budgeting uses one hour. Defaults allocate at most 12% of remaining
work time to planning, around 55% to initial execution, and at most 15% to each
review. Fix rounds consume a configurable share of what remains. A final reserve
of the larger of 90 seconds or 3% of total time protects the closing stage, subject
to the actual time available.

Work phases whose budgets fall below two minutes are skipped or use tiny-budget
fallback behavior. Finalization performs deterministic nonempty-file checks and
office inspection before requesting a concise final answer. This cannot prove
engineering correctness, but catches straightforward missing-output failures.
Exceptions, timeouts and trace-writing failures are caught best-effort; the last
executor summary is retained as a fallback rather than replacing it with planner
or reviewer JSON. Phase durations and available token counters are recorded.

## Robustness inherited from the reference

We refactored rather than replaced the reference model loop. It retains streaming,
retry/backoff, Claude cache marks, thinking-block preservation, Responses-API
fallback, token-limit fallback, truncated-output continuation, context compaction
and deadline-aware finish summaries. The refactor makes these mechanisms reusable
by each phase. This reduces the risk of implementing a sophisticated workflow on
top of a fragile transport layer, although not every recovery branch has been
exercised against a real provider.

MCP connection and catalog management are task-scoped and reused across phases.
Container tools and host tools share an extensible dispatcher. Read-only phases
omit built-in write tools and instruct the model not to mutate through shell or
MCP. These are policy restrictions, not an OS filesystem sandbox; arbitrary shell
commands can still write if the model disobeys.

## Documents and a portable engineering library

Task-container contents are unknown and networking is unavailable. Installing a
document library during a task is therefore not a dependable strategy. Our serve
container instead includes python-docx, openpyxl and pypdf. Host-side tools read
task bytes through the evaluator, extract text, create DOCX/XLSX files, inspect
office structures and upload outputs using bounded append chunks. This separates
document capabilities from assumptions about the task image.

The engineering package takes the opposite portability approach: pure Python
standard library, compatible with Python 3.8+, uploaded into the task workspace.
It includes unit conversions, idealized structural/electrical/mechanical/civil
calculations, economic factors and Markdown calculation logs. Formula docstrings
state sources and conventions; conductor tables are supplied by callers rather
than silently inventing authoritative ampacities. These helpers are not complete
design-code implementations, and their outputs need engineering judgment.

Spreadsheet formulas are preserved but not evaluated by openpyxl. Cached formula
values may be absent, and office integrity inspection does not establish visual
quality. Those limitations should remain explicit rather than being hidden behind
a tool’s successful return status.

## Fair play and reproducibility

Production solving uses the declared single sponsored model and general-purpose
tools; it contains no official-task identifiers, hard-coded benchmark answers or
grader inspection logic. It does not use web search or external APIs. Model calls
go through the kit’s egress proxy, while local MCP access uses the evaluator.
The harness must never read its own exported artifacts as prior answers. Official
artifacts must come from the official evaluator running this harness/model pair.

Our separate synthetic mock deliberately contains fixture-specific scripted
responses. It is a transport/tool integration test, is not invoked by production
`solve()`, and must never be confused with an eligible benchmark result. No PLE
task content, tokens or real credentials are included. The dev-evaluation wrapper
inherits credentials from environment only and delegates export to `eval/run.py`;
the kit handles its private transient runtime credential transport.

## Evaluation to date

The recorded offline run used real Docker, Harbor 0.20.0, the kit’s ServeAgent and
protocol relay, a no-network Python task container and a local OpenAI-compatible
mock. The original synthetic task computes balanced three-phase current for
100 kW at 480 V line-line and PF 0.9, producing DOCX and JSON. All four phases
completed; content checks confirmed 133.646 A. One trial earned reward 1.0 with
zero exceptions. The recorded unit suite passed 43 tests in 1.99 seconds; Ruff
reported all checks passed. These measure plumbing, not model intelligence.

Official dev mean: **[pending]**. Per-discipline scores: **[pending]**. Real-model
runtime, token usage and cost: **[pending]**. Hidden-test score: **[not available]**.
No accuracy gain from independent review or engineering tools is claimed yet.

## Limitations and future work

Next steps are official dev evaluation, task-level error analysis and controlled
ablations of planning, review and helper use. We should measure deadline allocation,
tool failures and whether fixes improve or regress outputs before tuning defaults.
Visual document checks and stronger review isolation deserve attention. Any future
optimization must preserve fair-play rules and avoid task-specific answer storage.
Ultimately this harness is an engineering assistant, not a substitute for licensed
professional review or independent safety validation.
