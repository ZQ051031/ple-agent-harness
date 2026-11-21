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

"""Task-scoped reusable MCP catalog."""
import json
import re
from typing import Any
import taskbridge
from .common import (DIRECT_MCP_CHARS, MAX_TOOLS, MCP_DIRECT, MCP_CATALOG,
                     MCP_TOOLS, TOOL_RESULT_CHARS, clip, unique_name)

class MCPServer(taskbridge.MCPClient):
  """Client wrapper for a single task MCP server and its discovered tools."""

  def __init__(self, session: taskbridge.Session, spec: dict[str, Any]):
    super().__init__(session, spec["url"], client="custom-harness")
    self.name = spec["name"]
    self.tools: list[dict[str, Any]] = []

  async def start(self) -> None:
    """Initializes the MCP session and fetches the server's tool list."""
    await self.initialize()
    self.tools = await self.list_tools()

  async def call(self, name: str, arguments: dict[str, Any]) -> str:
    """Calls tool `name` on the MCP server and formats the result as text.

    Args:
      name: Unprefixed MCP tool name on this server.
      arguments: Tool input arguments dictionary.

    Returns:
      Formatted text output (prefixed with `error: ` if `isError` is set).
    """
    result = await self.call_tool(name, arguments)
    parts = []
    content = (
        result.get("content") if isinstance(result.get("content"), list) else []
    )
    for item in content:
      kind = item.get("type") if isinstance(item, dict) else None
      if kind == "text":
        parts.append(str(item.get("text", "")))
      elif kind == "resource":
        parts.append(json.dumps(item.get("resource"))[:TOOL_RESULT_CHARS])
      elif kind == "resource_link":  # its uri, name and mimeType
        parts.append(json.dumps(item)[:TOOL_RESULT_CHARS])
      else:
        parts.append(f"[{kind or 'unknown'} content not shown]")
    if not parts and result.get("structuredContent") is not None:
      parts.append(json.dumps(result["structuredContent"]))
    text = "\n".join(parts) or "(no content)"
    return f"error: {text}" if result.get("isError") else text


class MCPCatalog:
  def __init__(self, session, reserved_names=()):
    self.session = session
    self.mcp = {}
    self.tools = []
    self.reserved_names = set(reserved_names)
    self.connected = False
    self.prompt = ""

  async def connect(self):
    if not self.connected:
      self.prompt = await self.connect_mcp()
      self.connected = True
    return self.prompt

  async def connect_mcp(self) -> str:
    """Connects to the task's MCP servers and registers their tools.

    Exposes a small set of MCP tools directly as OpenAI functions; for larger
    tool sets, lists their names in the system prompt and exposes `mcp_find`
    and `mcp_call`.

    Returns:
      The system-prompt section describing the available MCP tools.
    """
    for spec in self.session.mcp_servers:
      server = MCPServer(self.session, spec)
      try:
        await server.start()
      except (taskbridge.TaskError, RuntimeError, ValueError) as exc:
        await self.session.log(f"MCP server {server.name} unavailable: {exc}")
        continue
      for t in server.tools:
        name = re.sub(r"[^A-Za-z0-9_-]", "_", f"{server.name}__{t['name']}")
        self.mcp[unique_name(name, self.reserved_names | self.mcp.keys())] = (server, t)
      await self.session.log(
          f"MCP server {server.name}: {len(server.tools)} tools"
      )
    if not self.mcp:
      return ""
    functions = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": (t.get("description") or t["name"])[:1024],
                "parameters": (
                    {
                        k: v
                        for k, v in (t.get("inputSchema") or {}).items()
                        if k != "$schema"
                    }
                    or {"type": "object", "properties": {}}
                ),
            },
        }
        for name, (_, t) in self.mcp.items()
    ]
    if (
        len(json.dumps(functions)) <= DIRECT_MCP_CHARS
        and len(self.reserved_names) + len(functions) <= MAX_TOOLS
    ):
      self.tools += functions
      return MCP_DIRECT
    self.tools += MCP_TOOLS
    servers: dict[str, list[str]] = {}
    for name, (server, _) in self.mcp.items():
      servers.setdefault(server.name, []).append(name)
    return MCP_CATALOG.format(
        catalog="\n".join(
            f"{s}: {', '.join(names)}" for s, names in servers.items()
        )
    )

  def find_mcp(self, query: str) -> str:
    """Finds MCP tools matching `query` and formats their schemas.

    Returns as many matching tool schemas as fit within `TOOL_RESULT_CHARS`
    (always at least one, without truncating any individual schema).

    Args:
      query: Tool name or search keywords.

    Returns:
      Formatted descriptions and JSON parameter schemas of matching tools.
    """
    words = [w for w in re.split(r"[^a-z0-9]+", query.lower()) if w]

    def score(item):
      name, (_, t) = item
      text = f"{name} {t.get('description') or ''}".lower()
      return (
          (query == name) * 100
          + sum(w in name.lower() for w in words) * 3
          + sum(w in text for w in words)
      )

    best = [
        item
        for item in sorted(self.mcp.items(), key=score, reverse=True)[:8]
        if score(item) > 0
    ]
    if not best:
      return (
          f"no tool matches {query!r}; the names are listed in the system"
          " prompt"
      )
    found = [
        f"{name}: {(t.get('description') or '')[:400]}\nparameters:"
        f" {json.dumps(t.get('inputSchema') or {})}"
        for name, (_, t) in best
    ]
    while len(found) > 1 and len("\n\n".join(found)) > TOOL_RESULT_CHARS:
      found.pop()
    return "\n\n".join(found)


  async def dispatch(self, name, args):
    if name == "mcp_find":
      return self.find_mcp(str(args.get("query", "")))
    if name == "mcp_call":
      name, args = str(args.get("tool", "")), args.get("arguments") or {}
      args = json.loads(args) if isinstance(args, str) else args
    if name not in self.mcp:
      return f"error: no tool named {name!r}; use mcp_find"
    server, spec = self.mcp[name]
    return clip(await server.call(spec["name"], args))

  def register(self, dispatcher):
    for spec in self.tools:
      name = spec["function"]["name"]
      async def handler(_name=name, **args):
        return await self.dispatch(_name, args)
      dispatcher.register(spec, handler)
