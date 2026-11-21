import importlib.util
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from docx import Document

from scripts.mock_model import Handler, PLAN, reply


def test_script_roles():
    assert json.loads(reply([{"content": "ROLE: RECON_PLAN"}])["content"]) == PLAN
    messages = [{"content": "ROLE: EXECUTE"}]
    for name in ("bash", "write_file", "write_docx", "inspect_office"):
        assert reply(messages)["tool_calls"][0]["function"]["name"] == name
        messages.append({"role": "tool", "content": "ok"})
    assert "133.646 A" in reply(messages)["content"]
    assert reply([])["content"] == "OK"
    assert "133.646 A" in reply([{"content": "ROLE: FINALIZE"}])["content"]
    review = [{"content": "ROLE: VERIFY"}, {"role": "tool"}, {"role": "tool"}]
    assert json.loads(reply(review)["content"])["verdict"] == "pass"


def test_http_stream_and_probe():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
    try:
        def post(body):
            return urlopen(Request(url, data=body, headers={"Content-Type": "application/json"}))
        with post(b'{"messages":[]}') as response:
            assert json.load(response)["choices"][0]["message"]["content"] == "OK"
        request = {"stream": True, "messages": [{"content": "ROLE: EXECUTE"}]}
        with post(json.dumps(request).encode()) as response:
            lines = response.read().decode().splitlines()
        chunks = [json.loads(line[6:]) for line in lines if line.startswith("data: {")]
        assert chunks[0]["choices"][0]["delta"]["tool_calls"][0]["index"] == 0
        assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
        assert lines[-2] == "data: [DONE]"
        with pytest.raises(HTTPError, match="400"):
            post(b"not json")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_synthetic_checker(tmp_path):
    path = Path(__file__).resolve().parents[1] / "examples/synthetic_task/tests/check.py"
    spec = importlib.util.spec_from_file_location("synthetic_check", path)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    with pytest.raises(FileNotFoundError):
        checker.check(tmp_path)
    messages = [{"content": "ROLE: EXECUTE"}, {"role": "tool"}]
    args = json.loads(reply(messages)["tool_calls"][0]["function"]["arguments"])
    (tmp_path / "answer.json").write_text(args["content"])
    document = Document()
    document.add_paragraph("100000 W 480 V 0.9 133.646 A Assumptions balanced line-line")
    document.save(tmp_path / "result.docx")
    checker.check(tmp_path)
    (tmp_path / "answer.json").write_text('{"current_a": 0}')
    with pytest.raises(AssertionError):
        checker.check(tmp_path)
