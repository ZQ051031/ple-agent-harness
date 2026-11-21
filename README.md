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
