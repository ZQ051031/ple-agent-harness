# Recorded results

**Our own dev-set score is unmeasured because the Hugging Face dataset is gated.**
The checks below were measured on 2026-11-21. Neither synthetic outputs nor kit
smoke checks are official dev artifacts; never copy them into root `artifacts/`.

## Current measurements

| Check | Measured result |
| --- | --- |
| Unit suite | 62 passed in 1.83 s |
| Ruff | `All checks passed!` |
| Offline Docker/Harbor E2E | 1 trial, 0 exceptions, reward 1.0; console runtime 25 s |
| Official kit with local Qwen3-8B Q4_K_M on CPU | Smoke 19 s; MCP 35 s; cancel passed |
| Organizers' template baseline, Pi + Claude Opus 5.5 | Mean dev reward 0.491 over 29 tasks; not our score |

The offline E2E used Harbor 0.20.0, the official kit relay and ServeAgent, a
no-network task container and our deterministic mock. Its DOCX and JSON passed
content checks; all four orchestration phases completed. It tests integration,
not engineering reasoning. Mock token counts are unknown, not measured zeros.
DOCX visual rendering remains unverified.

## Official kit: real local model

The successful full `kit check --cancel-test` used Qwen3-8B Q4_K_M through the
existing CPU llama.cpp server at `http://localhost:8091/v1`. Only a disposable
copy declared `openai-compatible/qwen3-8b`; the repository retained its sponsored
Claude declaration. The local CPU profile sets `REASONING_EFFORT=none`.

| Stage | Result | Measurement or limitation |
| --- | --- | --- |
| submission.yaml | PASS | Local Qwen declaration |
| files | WARN | Disposable copy is not a Git repository |
| build | PASS | 121 MiB bundle; 27 s |
| model | PASS | 12.4 s through egress proxy |
| listen | PASS | WebSocket accepted after 2 s |
| smoke | PASS | 19 s; 11 requests; 3705 input / 70 output tokens |
| MCP | PASS | 35 s; 15 requests; 5615 input / 135 output tokens |
| cancel | PASS | Done within 10 s after cancellation |
| artifacts | WARN | Genuine dev artifacts absent |

The kit marks the self-hosted model local-only, not ready to submit. The root
`harness.py` required by the entry layout is now present and supplies `solve()`
to `serve.py`. No task fingerprints or official-task-specific answers were added.

### Reasoning-effort ablation

| Local configuration | Smoke | MCP | Cancel |
| --- | --- | --- | --- |
| `high` (initial default) | PASS, 287 s | File not written within model-phase budget | PASS |
| `none` (CPU profile) | PASS, 19 s | PASS, 35 s | PASS |

In the first run, MCP discovery succeeded, but model streams were cut off at
their deadlines before producing the deliverable. Changing only the local
reasoning setting resolved that failure. These single runs are a local
configuration ablation, not evidence of a general accuracy improvement or a
planning/review benefit. Final runs skip planning/review phases whose allocated
budgets fall below the configured two-minute threshold.

## Organizers' template reference, not our result

The committed `artifacts/manifest.json` in `~/repos/submission-template` identifies
`google-cloud/claude-opus-5-5`; its root solver runs Pi. Computing the arithmetic
mean of all 29 entries in `tasks[*].reward` gives:

```text
sum = 14.246023
count = 29
mean = 0.4912421724137931 (0.491 rounded)
```

The manifest was created `2026-10-20T03:33:56Z` and records harness commit
`6ab05b9f5f256b4ce148c20498b255712fdfbf26`. This is the organizers' template
baseline, not an evaluation we ran and not a score attributable to our harness.
No reference task contents or deliverables are copied here.

## Provenance and reproduction

[`local_qwen_check.json`](local_qwen_check.json) records environment fingerprints,
stage measurements, the reasoning ablation and aggregate baseline provenance,
without secrets or task content. Local evidence paths (not repository dependencies):

- `~/ple-offline-runs/qwen-unit.log` and `qwen-ruff.log`.
- `~/ple-offline-runs/e2e.log` and
  `verification-1795303900/jobs/synthetic/result.json`.
- `~/ple-offline-runs/qwen-check.log` and `qwen-check/check.json` (reasoning high).
- `~/ple-offline-runs/qwen-no-thinking.log` and
  `qwen-no-thinking/kit/check.json` (reasoning none).

Use `scripts/run_offline_e2e.sh` or `scripts/run_local_model.sh check` with a new
output directory; see the top-level README. Genuine dev artifacts must come from
`eval/run.py` with gated dataset access. Future dev records should identify the
harness/model/judge, dataset revision, coverage and exported artifact manifest.

[`offline_e2e.json`](offline_e2e.json) remains an older, separately identified
synthetic snapshot (43 tests, 24-second console runtime); it was not rewritten
to imply that those historical measurements came from the current run.
