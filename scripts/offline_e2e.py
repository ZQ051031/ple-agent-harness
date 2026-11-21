"""Run the real kit stack and Harbor against an original synthetic task."""

import argparse
import json
import os
import shutil
import subprocess
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from mock_model import Handler


def run(command, **kwargs):
    print("+ " + " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    # Executed with PLE on PYTHONPATH; no copied PLE implementation or tasks.
    from kit import check, protocol, spec
    from kit.__main__ import _build

    entry = out / "local-entry"
    shutil.copytree(root, entry, ignore=shutil.ignore_patterns(
        ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"))
    yaml = entry / "submission.yaml"
    yaml.write_text(yaml.read_text().replace("google-cloud/claude-opus-5-5", "openai-compatible/fake")
                    + "\nmodel_base_url: https://example.org/v1\n")
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://localhost:{args.port}/v1"
    env = dict(os.environ, MODEL_API_KEY="offline-placeholder")
    try:
        run(["uv", "run", "python", "-m", "kit", "check", entry,
             "--no-smoke", "--model-base-url", base], env=env)
        sub, image, _ = _build(SimpleNamespace(dir=str(entry), work=None, rebuild=False))
        rt = check.runtime(sub, env, base_url=base)
        kwargs = {"image": image, "serve": spec.fill(sub.serve, protocol.PORT),
                  "harness": sub.name, "allow": rt.allow, "exceptions": rt.exceptions}
        print(f"Model endpoint: {rt.env['MODEL_BASE_URL']}; egress exceptions: {rt.exceptions}",
              flush=True)
        with check.private_env_file(rt.env) as env_file:
            kwargs["env_file"] = str(env_file)
            command = ["harbor", "run", "--path", root / "examples/synthetic_task",
                       "--agent", "kit.harbor_agent:ServeAgent", "--jobs-dir", out / "jobs",
                       "--job-name", "synthetic", "--n-concurrent", "1"]
            for key, value in kwargs.items():
                command.extend(["--ak", f"{key}={json.dumps(value) if isinstance(value, list) else value}"])
            run(command, env=env)
        trials = list((out / "jobs/synthetic").glob("*/result.json"))
        assert len(trials) == 1, trials
        result = json.loads(trials[0].read_text())
        assert result.get("exception_info") is None, result
        assert result["verifier_result"]["rewards"]["reward"] == 1.0, result
        trial = trials[0].parent
        for log in sorted(trial.rglob("*")):
            if log.is_file() and log.name in {"serve.log", "test-stdout.txt", "relay.log"}:
                print(f"--- {log.relative_to(out)} ---\n{log.read_text(errors='replace')[-12000:]}")
        outputs = list(trial.rglob("answer.json"))
        assert outputs, "Harbor did not collect deliverables"
        run(["python3", root / "examples/synthetic_task/tests/check.py", outputs[0].parent])
        traces = list(trial.rglob("trace.json"))
        assert traces, "Missing phase trace"
        trace = json.loads(traces[0].read_text())
        assert [(p["role"], p["status"]) for p in trace["phases"]] == [
            ("recon-plan", "ok"), ("execute", "ok"), ("verify-0", "ok"), ("finalize", "ok")]
        assert all(c["nonempty"] for c in trace["deliverable_checks"])
        console = (trial / "agent/ple-agent-harness.txt").read_text()
        final = [json.loads(line)["result"] for line in console.splitlines()
                 if line.startswith('{"type": "result"')]
        assert len(final) == 1 and "133.646 A" in final[0], final
        print("FINAL MESSAGE: " + final[0], flush=True)
        print("OFFLINE E2E PASSED: Harbor reward 1.0", flush=True)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
