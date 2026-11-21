# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tool-calling harness for any OpenAI-compatible model endpoint.

Connects to `MODEL_BASE_URL` using `MODEL_API_KEY` and `MODEL_NAME`. The model
works in the task container through four built-in tools (`bash`, `read_file`,
`write_file`, `edit_file`) plus the task's own MCP tools, and finishes when it
provides a complete answer without calling a tool. That answer becomes the final
message. Calls go to the Chat Completions API, or to the Responses API for
OpenAI's GPT-6 models (`RESPONSES_MODELS`).

Optional environment variables: `MAX_OUTPUT_TOKENS` (default `32000`),
`COMPACT_AT_TOKENS` (default `150000`), and `REASONING_EFFORT` (default `max`
for Claude, GLM, GPT-6 and DeepSeek-V4, `high` for other models).
"""

from __future__ import annotations

import json
import os
import re
import types
from typing import Any


MODEL = os.environ.get("MODEL_NAME", "")
# The model's highest reasoning level: max for Claude, GLM, GPT-6 and
# DeepSeek-V4, high for the others (Gemini refuses max). REASONING_EFFORT
# overrides it.
MAX_EFFORT_MODELS = ("claude", "glm", "gpt-6", "deepseek-v4")
EFFORT = os.environ.get("REASONING_EFFORT") or (
    "max" if any(m in MODEL.lower() for m in MAX_EFFORT_MODELS) else "high"
)
# OpenAI's GPT-6 models only support function tools combined with
# reasoning_effort on the Responses API. Other models also switch to
# /v1/responses if /v1/chat/completions returns a 400 directing them there.
RESPONSES_MODELS = ("gpt-6",)
RESPONSES_ONLY = re.compile(
    r"/v1/responses|not supported.{0,80} in /v1/chat/completions"
)
# Claude reuses a cached prompt prefix only where a request marks one
# (marked()); other models cache on their own.
CACHE_MARK = "claude" in MODEL.lower()
COMPACT_AT_TOKENS = int(os.environ.get("COMPACT_AT_TOKENS", "150000"))
TOOL_RESULT_CHARS = 30_000
# MCP tools are offered as functions up to this many characters of JSON in all
DIRECT_MCP_CHARS = 40_000
# functions one request may offer (OpenAI's limit), the built-in four included
MAX_TOOLS = 128
KEEP_RECENT_RESULTS = 12
FINISH_MARGIN_SEC = 180
RETRY_WAITS = (5, 15, 30, 60, 120)
# How endpoints word an error saying the conversation no longer fits (xAI's:
# "maximum prompt length is N but the request contains M tokens"). OpenAI's
# error for too many tools ("'tools': array too long") does not match.
CONTEXT_FULL = re.compile(
    r"context.?(length|window|size|limit)|maximum context|too many"
    r" tokens|prompt is too long|maximum prompt length"
    r"|(input|prompt|request|messages?)\b[^.]{0,40}(too long|exceed)"
    r"|exceed[^.]{0,40}(token|context)",
    re.I,
)
# The context window and the prompt's share of it, as vLLM, OpenAI, Anthropic,
# Gemini and xAI word them in such an error.
WINDOW_RE = re.compile(
    r"maximum context length (?:is |of )?(\d+)"
    r"|context (?:window|length|size)(?: limit)?(?: is| of)? (\d+)"
    r"|tokens? > (\d+) maximum|maximum number of tokens allowed \((\d+)\)"
    r"|maximum prompt length is (\d+)",
    re.I,
)
PROMPT_RE = re.compile(
    r"(\d+) input tokens|(\d+) in the messages|prompt is too long: (\d+)"
    r"|input token count \((\d+)\)|request contains (\d+) tokens",
    re.I,
)
MIN_OUTPUT = 1024  # the fewest output tokens to ask for
# characters an unread tool result keeps, however full the context
UNREAD_KEEP = 600
# tokens left free in the window, since tokenizers count a little differently
CONTEXT_MARGIN = 1024
# How endpoints word an error refusing a parameter or value outright, unlike one
# that names a smaller maximum.
UNSUPPORTED = re.compile(
    r"unsupported|unrecogni[sz]ed|unknown|not supported|does not support|not"
    r" (allowed|permitted)"
    r"|extra (inputs|fields)|unexpected",
    re.I,
)
# The standard fields of a streamed tool call, of its function, and of a reply's
# delta. Any other field an endpoint sends goes back with the message: Gemini
# refuses a tool call without its thought signature, which comes in the call's
# extra_content.
CALL_FIELDS = {"index", "id", "type", "function"}
FUNCTION_FIELDS = {"name", "arguments"}
DELTA_FIELDS = {
    "role",
    "content",
    "tool_calls",
    "function_call",
    "refusal",
    "audio",
    "annotations",
    "reasoning_content",
    "reasoning",
}

SYSTEM = """You are an expert engineer working on a task in a Linux container. Your tools act inside it: bash (it \
starts in {workdir}), read_file, write_file and edit_file. The container has no internet access.{mcp}

How to work:
- Read the whole task, then look at the files you were given before choosing an approach.
- Work in small, verified steps. Compute numbers with code rather than by hand, and check units.
- When the task says how the result is checked (a time limit, a format, a test), check it that way yourself.
- Write each deliverable exactly where, under the name and in the format the task asks for. Write it early, then \
improve it.
- Produce office and binary formats (docx, xlsx, pdf, ...) with code, such as python3 and the libraries in the \
container, so they are real files of that format.
- Before you finish, open every deliverable again and check that it is complete and readable.
- You have about {minutes} minutes in total; the time left is shown after the results of your tools.

When the work is done, answer without calling a tool: a short summary of what you delivered (the path of each file) \
and the key results. That answer is graded together with your files."""

MCP_DIRECT = """

The task also offers its own tools (the functions named <server>__<tool>)."""

MCP_CATALOG = """

The task also offers its own tools, listed below by server. Call mcp_find to see a tool's parameters, then mcp_call \
to run it.
{catalog}"""

SUMMARY_PROMPT = """The conversation is getting long, so the earlier turns will be removed. Write notes that let you \
continue without them: what the task requires, what you found in the files, every file you created or changed (with \
its path and state), the numbers and decisions so far, and what remains to do. Be specific."""


def tool(
    name: str, description: str, required: list[str], **properties: Any
) -> dict[str, Any]:
  """Builds an OpenAI function-tool definition dictionary.

  Args:
    name: Tool function name.
    description: Human-readable tool description.
    required: List of required parameter names.
    **properties: Parameter JSON Schema definitions keyed by parameter name.

  Returns:
    An OpenAI function-tool specification dictionary.
  """
  return {
      "type": "function",
      "function": {
          "name": name,
          "description": description,
          "parameters": {
              "type": "object",
              "properties": properties,
              "required": required,
          },
      },
  }


TOOLS = [
    tool(
        "bash",
        "Run a bash command in the task container and return its exit code and"
        " output. Each call starts a new shell in the working directory: only"
        " files persist between calls.",
        ["command"],
        command={"type": "string"},
        timeout_sec={
            "type": "integer",
            "description": (
                "Stop the command after this many seconds (default 120)."
            ),
        },
    ),
    tool(
        "read_file",
        "Read a text file from the task container.",
        ["path"],
        path={"type": "string"},
    ),
    tool(
        "write_file",
        "Create or overwrite a file in the task container; parent directories"
        " are created.",
        ["path", "content"],
        path={"type": "string"},
        content={"type": "string"},
        append={
            "type": "boolean",
            "description": (
                "Add to the end of the file instead (write a large file in"
                " parts)."
            ),
        },
    ),
    tool(
        "edit_file",
        "Replace exact text in a file. old_text must occur exactly once unless"
        " replace_all is true.",
        ["path", "old_text", "new_text"],
        path={"type": "string"},
        old_text={"type": "string"},
        new_text={"type": "string"},
        replace_all={"type": "boolean"},
    ),
]
MCP_TOOLS = [
    tool(
        "mcp_find",
        "Show the description and parameters of the task's own tools that match"
        " a query.",
        ["query"],
        query={
            "type": "string",
            "description": "A tool name, or words describing what you need.",
        },
    ),
    tool(
        "mcp_call",
        "Run one of the task's own tools.",
        ["tool", "arguments"],
        tool={"type": "string", "description": "The tool's name as listed."},
        arguments={"type": "object"},
    ),
]


def clip(text: str, limit: int = TOOL_RESULT_CHARS) -> str:
  """Truncates `text` in the middle if it exceeds `limit` characters.

  Args:
    text: String to clip.
    limit: Maximum character length before truncation.

  Returns:
    The original string if within `limit`, or a middle-truncated string.
  """
  if len(text) <= limit:
    return text
  head = limit * 2 // 3
  return (
      f"{text[:head]}\n[... {len(text) - limit} characters cut"
      f" ...]\n{text[-(limit - head):]}"
  )


def parse_arguments(call: dict[str, Any]) -> dict[str, Any] | str:
  """Parses a tool call's arguments into a dict or returns an error string.

  Rewrites `call["arguments"]` as canonical JSON (`"{}"` when invalid) because
  endpoints reject conversations containing malformed tool-call arguments.

  Args:
    call: Tool-call dictionary with an `arguments` JSON string field.

  Returns:
    The parsed arguments dictionary, or an error string for the model.
  """

  def reject(constant):
    raise ValueError(f"{constant} is not valid JSON")

  try:
    args = json.loads(call["arguments"] or "{}", parse_constant=reject)
    if not isinstance(args, dict):
      raise ValueError("the arguments must be a JSON object")
    call["arguments"] = (
        json.dumps(args, ensure_ascii=False)
        .encode("utf-8", "replace")
        .decode("utf-8")
    )
    return args
  except ValueError as exc:
    call["arguments"] = "{}"
    return (
        f"error: the arguments are not a valid JSON object ({exc}); send the"
        " call again"
    )


def unique_name(name: str, taken: Any) -> str:
  """Truncates `name` to 64 chars and appends `_2`, `_3`, ... if in `taken`.

  Args:
    name: Desired function name.
    taken: Collection or mapping of already-used function names.

  Returns:
    A unique function name of at most 64 characters.
  """
  candidate, n = name[:64], 1
  while candidate in taken:
    n += 1
    candidate = f"{name[:63 - len(str(n))]}_{n}"
  return candidate


def visible(text: str) -> str:
  """Strips `<think>...</think>` reasoning blocks from `text`.

  Args:
    text: Assistant response content string.

  Returns:
    The trimmed response text with inline `<think>` blocks removed.
  """
  return re.sub(r"<think>.*?(</think>|$)", "", text or "", flags=re.S).strip()


def extra_fields(part: Any, known: set[str]) -> dict[str, Any]:
  """Extracts non-null extra fields from a streamed SDK object `part`.

  The OpenAI SDK stores undeclared provider fields in `part.model_extra`.

  Args:
    part: Streamed Pydantic model object (delta, tool call, or function).
    known: Set of standard field names to exclude.

  Returns:
    Dictionary of extra fields not in `known` whose values are not `None`.
  """
  fields = getattr(part, "model_extra", None) or {}
  return {k: v for k, v in fields.items() if k not in known and v is not None}


def merged(old: Any, new: Any, key: str = "") -> Any:
  """Merges a single delta's extra field value `new` into `old`.

  Merges dictionaries key-by-key, concatenates lists, and replaces scalars.
  Delegates `thinking_blocks` lists to `thinking_blocks()`.

  Args:
    old: Accumulated field value so far.
    new: Incoming delta field value.
    key: Field name being merged.

  Returns:
    The merged field value.
  """
  if key == "thinking_blocks" and isinstance(new, list):
    return thinking_blocks(old if isinstance(old, list) else [], new)
  if isinstance(old, dict) and isinstance(new, dict):
    return {**old, **{k: merged(old.get(k), v, k) for k, v in new.items()}}
  if isinstance(old, list) and isinstance(new, list):
    return old + new
  return new


def thinking_blocks(
    blocks: list[dict[str, Any]], new: list[Any]
) -> list[dict[str, Any]]:
  """Accumulates streamed Claude `thinking_blocks` deltas.

  Joins consecutive deltas into the current block until a `signature` closes it;
  redacted blocks (containing `data`) arrive whole and are kept separate.

  Args:
    blocks: Existing list of accumulated thinking blocks.
    new: New list of thinking block deltas from the stream chunk.

  Returns:
    Updated list of thinking block dictionaries.
  """
  out = [dict(b) for b in blocks]
  for b in new:
    if not isinstance(b, dict):
      continue
    last = out[-1] if out else None
    if (
        last is None
        or last.get("signature")
        or last.get("data")
        or b.get("data")
        or last.get("type") != b.get("type")
    ):
      out.append(dict(b))
      continue
    last["thinking"] = (last.get("thinking") or "") + (b.get("thinking") or "")
    if b.get("signature"):
      last["signature"] = b["signature"]
  return out


def signed(block: Any) -> bool:
  """Returns whether `block` has a `signature` or redacted `data` field.

  Args:
    block: Candidate thinking block dictionary.

  Returns:
    `True` if Claude will accept `block` in a subsequent turn, else `False`.
  """
  return isinstance(block, dict) and bool(
      block.get("signature") or block.get("data")
  )


def drop_thinking(
    message: dict[str, Any], unless: Any = lambda block: False
) -> dict[str, Any]:
  """Filters `thinking_blocks` in `message`, keeping blocks matching `unless`.

  Args:
    message: Assistant message dictionary to modify in place.
    unless: Predicate `unless(block)` returning `True` for blocks to keep.

  Returns:
    The modified `message` dictionary.
  """
  if isinstance(message.get("thinking_blocks"), list):
    message["thinking_blocks"] = [
        b for b in message["thinking_blocks"] if unless(b)
    ]
  fields = message.get("provider_specific_fields")
  if isinstance(fields, dict) and isinstance(
      fields.get("thinking_blocks"), list
  ):
    message["provider_specific_fields"] = {
        **fields,
        "thinking_blocks": [b for b in fields["thinking_blocks"] if unless(b)],
    }
  return message


def marked(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Returns the messages a Chat Completions call sends.

  For Claude, this is a copy whose system prompt and newest message carry
  `cache_control` (2 of Claude's 4 cache breakpoints), so every turn reads the
  conversation so far from the cache instead of paying for all of it again.
  The stored conversation stays as it is.

  Args:
    messages: The conversation so far.

  Returns:
    `messages` itself for other models, or the marked copy for Claude.
  """
  if not CACHE_MARK or not messages:
    return messages
  out = list(messages)
  for i in {0, len(out) - 1}:
    m, content = out[i], out[i].get("content")
    if isinstance(content, str) and content:
      out[i] = {
          **m,
          "content": [{
              "type": "text",
              "text": content,
              "cache_control": {"type": "ephemeral"},
          }],
      }
    else:
      out[i] = {**m, "cache_control": {"type": "ephemeral"}}
  return out


def response_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Converts Chat Completions messages into Responses API input items.

  Assistant turns produced by the Responses API are replayed using their saved
  output items (including encrypted reasoning). Each function call takes its id
  and name from the turn's stored tool call, and its arguments as
  `parse_arguments` rewrote them.

  Args:
    messages: Conversation messages in Chat Completions format.

  Returns:
    The `input` list for a Responses API call.
  """
  items = []
  for m in messages:
    if m["role"] == "tool":
      items.append({
          "type": "function_call_output",
          "call_id": m["tool_call_id"],
          "output": m["content"],
      })
    elif m["role"] != "assistant":
      items.append({"role": m["role"], "content": m["content"]})
    elif "output_items" in m:
      calls = iter(m.get("tool_calls") or [])
      for item in m["output_items"]:
        call = None
        if item.get("type") == "function_call":
          call = next(calls, None)
        if call:
          item = {
              **item,
              "call_id": call["id"],
              "name": call["function"]["name"],
              "arguments": call["function"]["arguments"],
          }
        items.append(item)
    else:
      if m.get("content"):
        items.append({"role": "assistant", "content": m["content"]})
      items += [
          {
              "type": "function_call",
              "call_id": c["id"],
              "name": c["function"]["name"],
              "arguments": c["function"]["arguments"],
          }
          for c in m.get("tool_calls") or []
      ]
  return items


def chat_usage(usage: Any) -> Any:
  """Returns Responses API `usage` in the shape `record` and `report` read.

  Args:
    usage: A Responses API usage object, or None.

  Returns:
    An object with `prompt_tokens`, `completion_tokens` and
    `prompt_tokens_details.cached_tokens`, as Chat Completions reports them, or
    None.
  """
  if usage is None:
    return None
  details = getattr(usage, "input_tokens_details", None)
  return types.SimpleNamespace(
      prompt_tokens=usage.input_tokens or 0,
      completion_tokens=usage.output_tokens or 0,
      prompt_tokens_details=types.SimpleNamespace(
          cached_tokens=getattr(details, "cached_tokens", 0) or 0
      ),
  )
