# Recorded results

**Dev-set results: pending — requires HF token + model access**

[`offline_e2e.json`](offline_e2e.json) records the last Step 4 synthetic run, not
an official benchmark evaluation. It used the implementation committed as
`2dcf1b3`, before this documentation handoff. These records are not a substitute
for `artifacts/` exported by the official evaluator; never import synthetic
outputs as official dev artifacts.

## Provenance

Command: `scripts/run_offline_e2e.sh /home/ubuntu/ple-offline-run-2`

Local evidence retained on the development machine (not public repo dependencies):

* `/home/ubuntu/ple-offline-run-2.log`: kit check, Harbor output, phases and final answer.
* `/home/ubuntu/ple-offline-run-2/jobs/synthetic/result.json`: one completed trial,
  zero exceptions, mean reward 1.0; Harbor console reports 24 s total runtime.
* `jobs/synthetic/synthetic_task__69ETTqx/result.json` beneath that run directory:
  trial timestamps, completed serve status, 22 protocol requests, reward 1.0.
* `jobs/synthetic/synthetic_task__69ETTqx/artifacts/tmp/ple_work/trace.json`:
  exact phase durations, reviewer verdict and nonempty deliverable checks.
* Collected `artifacts/output/`: DOCX and JSON passing the original stdlib checker.

The trial timestamps span about 24.90 s; this differs from the rounded console
runtime. Phase durations exclude setup, tool installation and other overhead, so
they must not be interpreted as whole-episode runtime. Token usage and cost are
unknown: the mock emits no usage, and zero phase counters do not measure tokens.

The recorded code-check snapshot was `43 passed in 1.99s` and Ruff's
`All checks passed!`. Later documentation/wrapper checks are reported separately
in the handoff, not retroactively attributed to this run.

## Interpretation and reproduction

The fixture computes 100 kW / (sqrt(3) × 480 V × 0.9) = 133.646 A, writes a DOCX
and JSON, then checks file contents. The model is deterministic scripted test
code, not an engineering reasoning evaluation. DOCX visual rendering was not checked.
Kit build/model/listen stages passed through the real egress proxy; the runner
skipped unrelated kit smoke/MCP tasks. No HF dataset or paid model was used.

Follow the top-level README to reproduce with a new output directory. Images and
dependencies must first be provisioned; the task container itself has no network.
No raw official task content or secret-bearing runtime configs are published here.
Future real dev runs should record harness commit, model/judge settings, dataset
commit, full-set versus subset coverage, score, costs and exported artifact manifest.
