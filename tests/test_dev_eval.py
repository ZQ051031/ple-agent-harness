"""Check shell argument/export wiring without a dataset, model or Docker."""
import json
import os
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_dev_eval.sh"


@pytest.fixture
def evaluation_env(tmp_path):
    uv = tmp_path / "uv"
    uv.write_text(
        "#!/usr/bin/python3\nimport json, os, sys\n"
        "with open(os.environ['CALL_LOG'], 'a') as log:\n"
        "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
    )
    uv.chmod(0o755)
    return {
        "PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path),
        "PLE_ROOT": str(tmp_path), "CALL_LOG": str(tmp_path / "calls.jsonl"),
        "HF_TOKEN": "test-only-placeholder", "MODEL_PROXY_URL": "http://localhost:4000",
        "MODEL_PROXY_KEY": "test-only-placeholder",
    }


def invoke(env, *args):
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)


@pytest.mark.parametrize("subset", ["", "data-center-site-model,engineers-estimate-check"])
def test_eval_exports_and_checks(evaluation_env, tmp_path, subset):
    env = dict(evaluation_env, DEV_TASKS=subset)
    result = invoke(env, str(tmp_path / "run with spaces"))
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in Path(env["CALL_LOG"]).read_text().splitlines()]
    assert calls[0][:4] == ["run", "python", "eval/run.py", str(SCRIPT.parents[1])]
    assert calls[0][4:8] == ["--trials", "1", "--out", str(tmp_path / "run with spaces")]
    assert calls[0][8:] == (["--tasks", subset] if subset else [])
    assert "--no-export" not in calls[0]
    assert calls[1] == ["run", "python", "-m", "kit", "artifacts", str(SCRIPT.parents[1])]
    assert "test-only-placeholder" not in result.stdout + result.stderr


@pytest.mark.parametrize("change", [
    {"HF_TOKEN": ""}, {"MODEL_PROXY_KEY": ""}, {"DEV_TRIALS": "0"},
    {"JUDGE_API_KEY": "test-only-placeholder"}, {"JUDGE_BASE_URL": "http://localhost:4000"},
])
def test_invalid_environment_stops_before_eval(evaluation_env, tmp_path, change):
    result = invoke(dict(evaluation_env, **change), str(tmp_path / "run"))
    assert result.returncode != 0
    assert not Path(evaluation_env["CALL_LOG"]).exists()
    assert "test-only-placeholder" not in result.stdout + result.stderr


def test_usage_requires_output_directory(evaluation_env):
    assert invoke(evaluation_env).returncode == 2
    assert not os.path.exists(evaluation_env["CALL_LOG"])
