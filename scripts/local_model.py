"""Run the official kit against a disposable copy and a local Qwen server."""

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["check", "eval"])
    parser.add_argument("--ple-root", type=Path, default=Path.home() / "repos/ple")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--base-url", default="http://localhost:8091/v1")
    parser.add_argument("--reasoning-effort", choices=["none", "low", "medium", "high"],
                        default="none")
    args, extra = parser.parse_known_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output or Path.home() / "ple-offline-runs" / f"qwen-{time.time_ns()}"
    output = output.resolve()
    if output == root or root in output.parents:
        parser.error("--output must be outside the harness checkout")
    entry = output / "entry"
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(root, entry, ignore=shutil.ignore_patterns(
        ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".env", "artifacts"))
    config = entry / "submission.yaml"
    spec, count = re.subn(r"(?m)^model_api:.*$", "model_api: openai-compatible/qwen3-8b",
                          config.read_text())
    if count != 1:
        parser.error("submission.yaml must have one top-level model_api line")
    spec = re.sub(r"(?m)^model_base_url:.*\n?", "", spec)
    setting = f'  REASONING_EFFORT: "{args.reasoning_effort}"'
    if re.search(r"(?m)^env:", spec):
        spec = re.sub(r"(?m)^  REASONING_EFFORT:.*\n?", "", spec)
        spec, count = re.subn(r"(?m)^env:[ \t]*(?:#.*)?$", "env:\n" + setting, spec)
        if count != 1:
            parser.error("use a block mapping for submission.yaml env")
    else:
        spec = spec.rstrip() + "\nenv:\n" + setting + "\n"
    config.write_text(spec.rstrip() + "\nmodel_base_url: https://example.org/v1\n")
    env = dict(os.environ)
    env.setdefault("MODEL_API_KEY", "local-placeholder")
    if args.mode == "check":
        command = ["uv", "run", "python", "-m", "kit", "check", str(entry),
                   "--cancel-test", "--work", str(output / "kit")]
    else:
        if not env.get("JUDGE_BASE_URL") and not env.get("JUDGE_API_KEY"):
            env.update(JUDGE_BASE_URL=args.base_url,
                       JUDGE_API_KEY=env["MODEL_API_KEY"], JUDGE_MODEL="qwen3-8b")
        command = ["uv", "run", "python", "eval/run.py", str(entry),
                   "--trials", "1", "--out", str(output / "eval")]
    command += ["--model-base-url", args.base_url, *extra]
    print(f"Local entry: {entry}\nCommand: {' '.join(command)}", flush=True)
    print("This local-only model/copy is not a competition submission.", flush=True)
    result = subprocess.run(command, cwd=args.ple_root, env=env, check=False)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
