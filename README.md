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

The initial solve function intentionally runs just one loop. Document libraries
are installed in the serve container only, not the task container.

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
