from types import SimpleNamespace

import pytest

from scripts import local_model


@pytest.fixture
def local_entry(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "submission.yaml").write_text(
        "name: test\nmodel_api: google-cloud/claude-opus-5-5\nserve: python serve.py\n")
    (root / ".env").write_text("SECRET=not-a-real-secret\n")
    (root / "artifacts").mkdir()
    monkeypatch.setattr(local_model, "__file__", str(root / "scripts/local_model.py"))
    for name in ("MODEL_API_KEY", "JUDGE_BASE_URL", "JUDGE_API_KEY", "JUDGE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return root


@pytest.mark.parametrize("mode", ["check", "eval"])
@pytest.mark.parametrize("custom_judge", [False, True])
def test_local_copy(local_entry, tmp_path, monkeypatch, mode, custom_judge):
    out = tmp_path / "run"
    calls = []
    monkeypatch.setattr("sys.argv", ["local_model.py", mode, "--output", str(out),
                                     "--ple-root", str(tmp_path / "ple"), "--rebuild"])
    if custom_judge:
        monkeypatch.setenv("JUDGE_BASE_URL", "http://other-model/v1")
        monkeypatch.setenv("JUDGE_API_KEY", "test-key")
    monkeypatch.setattr(local_model.subprocess, "run",
                        lambda *a, **kw: calls.append((a, kw)) or SimpleNamespace(returncode=0))
    with pytest.raises(SystemExit) as result:
        local_model.main()
    assert result.value.code == 0
    entry = out / "entry"
    assert "openai-compatible/qwen3-8b" in (entry / "submission.yaml").read_text()
    assert 'REASONING_EFFORT: "none"' in (entry / "submission.yaml").read_text()
    assert "google-cloud/" in (local_entry / "submission.yaml").read_text()
    assert not (entry / ".env").exists()
    assert not (entry / "artifacts").exists()
    command = calls[0][0][0]
    env = calls[0][1]["env"]
    assert command[-1] == "--rebuild"
    assert command[command.index("--model-base-url") + 1] == "http://localhost:8091/v1"
    assert env["MODEL_API_KEY"] == "local-placeholder"
    if mode == "check":
        assert "--cancel-test" in command
    else:
        assert command[command.index("--trials") + 1] == "1"
        assert env["JUDGE_BASE_URL"] == (
            "http://other-model/v1" if custom_judge else "http://localhost:8091/v1")


def test_local_copy_rejects_nested_output(local_entry, monkeypatch):
    monkeypatch.setattr("sys.argv", ["local_model.py", "check", "--output",
                                     str(local_entry / "run")])
    with pytest.raises(SystemExit) as result:
        local_model.main()
    assert result.value.code == 2


def test_local_copy_does_not_overwrite(local_entry, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["local_model.py", "check", "--output", str(tmp_path)])
    with pytest.raises(FileExistsError):
        local_model.main()


def test_local_copy_rejects_missing_model(local_entry, tmp_path, monkeypatch):
    (local_entry / "submission.yaml").write_text("")
    monkeypatch.setattr("sys.argv", ["local_model.py", "check", "--output",
                                     str(tmp_path / "run")])
    with pytest.raises(SystemExit) as result:
        local_model.main()
    assert result.value.code == 2


def test_local_copy_preserves_environment(local_entry, tmp_path, monkeypatch):
    config = local_entry / "submission.yaml"
    config.write_text(config.read_text() + 'env:\n  OTHER: "setting"\n  REASONING_EFFORT: "high"\n')
    out = tmp_path / "run"
    monkeypatch.setattr("sys.argv", ["local_model.py", "check", "--output", str(out)])
    monkeypatch.setattr(local_model.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    with pytest.raises(SystemExit):
        local_model.main()
    text = (out / "entry/submission.yaml").read_text()
    assert text.count("REASONING_EFFORT:") == 1
    assert 'OTHER: "setting"' in text
    assert 'REASONING_EFFORT: "none"' in text
