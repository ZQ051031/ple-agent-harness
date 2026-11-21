"""Deterministic local-only OpenAI server for the synthetic electrical task."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PLAN = {
    "discipline": "electrical", "task_summary": "Three-phase current calculation",
    "deliverables": [
        {"path": "/output/result.docx", "format": "docx", "contents_required": "calculation"},
        {"path": "/output/answer.json", "format": "json", "contents_required": "current_a"},
    ],
    "requirements": [{"id": "R1", "text": "100 kW, 480 V line-line, PF 0.9; current in A",
                      "how_to_verify": "100000/(sqrt(3)*480*0.9)"}],
    "given_data": ["100 kW", "480 V", "PF 0.9"], "codes_standards": [],
    "approach_steps": ["Compute, write, inspect"],
    "assumptions_needed": ["balanced three-phase real input power"], "risks": [],
}
FINAL = ("Created /output/result.docx and /output/answer.json. "
         "Current = 133.646 A. Assumed balanced three-phase, 480 V line-line, "
         "100 kW real input power and PF 0.9; no code sizing determination.")


def reply(messages):
    """Return an assistant message without shared conversation state."""
    system = str(messages[0].get("content", "")) if messages else ""
    count = sum(m.get("role") == "tool" for m in messages)
    name, args = None, None
    if "ROLE: RECON_PLAN" in system:
        return {"role": "assistant", "content": json.dumps(PLAN)}
    if "ROLE: EXECUTE" in system:
        calls = [
            ("bash", {"command": "mkdir -p /output && PYTHONPATH=/tmp/ple_work python3 -c "
                      "'from engtools.electrical import current; "
                      "print(current(480, kw=100, pf=0.9, phases=3))'"}),
            ("write_file", {"path": "/output/answer.json", "content": json.dumps({
                "current_a": 100000 / (3 ** 0.5 * 480 * 0.9), "power_kw": 100,
                "voltage_ll_v": 480, "power_factor": 0.9})}),
            ("write_docx", {"path": "/output/result.docx", "markdown":
                "# Three-phase current\n\nI = P / (sqrt(3) V PF)\n\n"
                "I = 100000 W / (sqrt(3) x 480 V x 0.9) = 133.646 A.\n\n"
                "Assumptions: balanced three-phase, line-line voltage, real input power. "
                "This is a circuit calculation, not code-based conductor sizing."}),
            ("inspect_office", {"path": "/output/result.docx"}),
        ]
        if count < len(calls):
            name, args = calls[count]
        else:
            return {"role": "assistant", "content": FINAL}
    elif "ROLE: VERIFY" in system:
        if count == 0:
            name, args = "extract_text", {"path": "/output/result.docx"}
        elif count == 1:
            name, args = "bash", {"command": "cat /output/answer.json && python3 -c "
                                  "'print(100000/(3**0.5*480*0.9))'"}
        else:
            return {"role": "assistant", "content": '{"verdict":"pass","issues":[]}'}
    elif "ROLE: FINALIZE" in system:
        return {"role": "assistant", "content": FINAL}
    else:
        return {"role": "assistant", "content": "OK"}
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": f"call_{count}", "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }]}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            if not isinstance(request, dict):
                raise ValueError("Expected object")
            message = reply(request.get("messages", []))
        except (ValueError, TypeError):
            self.send_error(400, "Invalid JSON request")
            return
        finish = "tool_calls" if message.get("tool_calls") else "stop"
        base = {"id": "chatcmpl-offline", "object": "chat.completion", "created": 0,
                "model": "fake"}
        if request.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            delta = dict(message)
            if "tool_calls" in delta:
                delta["tool_calls"] = [dict(c, index=i) for i, c in enumerate(delta["tool_calls"])]
            for part, reason in ((delta, None), ({}, finish)):
                chunk = dict(base, object="chat.completion.chunk", choices=[{
                    "index": 0, "delta": part, "finish_reason": reason}])
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            body = json.dumps(dict(base, choices=[{
                "index": 0, "message": message, "finish_reason": finish}])).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
