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

"""Extensible container tool dispatcher."""
import json
import posixpath
import taskbridge
from .common import TOOLS, clip

class ContainerTools:
  def __init__(self, session, time_left=None):
    self.session = session
    self.time_left = time_left or session.time_left
    self.finish_margin = 0

  def path(self, path: str) -> str:
    """Resolves `path` relative to `self.session.workdir` if not absolute.

    Args:
      path: Absolute or workdir-relative file path.

    Returns:
      The resolved container path string.
    """
    return (
        path
        if path.startswith("/")
        else posixpath.join(self.session.workdir, path)
    )

  async def bash(self, command: str, timeout_sec: int = 120) -> str:
    """Executes `command` with bash in the task container.

    Args:
      command: Shell command string to run.
      timeout_sec: Timeout in seconds, cut to end before the time kept for the
        final summary.

    Returns:
      Formatted exit code and command output string.
    """
    cap = int(self.session.limits.get("exec_timeout_sec") or 600)
    left = self.time_left()
    if left is not None:
      cap = min(cap, max(1, int(left - self.finish_margin)))
    result = await self.session.exec(
        command, taskbridge.positive_int(timeout_sec, 120, cap)
    )
    note = " (timed out)" if result.get("timed_out") else ""
    return (
        "exit code"
        f" {result['exit_code']}{note}\n{result['output'] or '(no output)'}"
    )

  async def read_file(self, path: str) -> str:
    """Reads a UTF-8 text file from `path` in the task container.

    Args:
      path: File path inside the task container.

    Returns:
      Decoded file contents, or a notice if the file is binary or empty.
    """
    data = await self.session.read_file(self.path(path))
    if b"\0" in data[:8192]:
      return (
          f"{path} is a binary file ({len(data)} bytes); inspect it with bash"
          " (python3, unzip -l, ...)"
      )
    return data.decode("utf-8", "replace") or "(empty file)"

  async def write_file(
      self, path: str, content: str, append: bool = False
  ) -> str:
    """Writes or appends `content` to `path` in the task container.

    Args:
      path: Destination file path inside the task container.
      content: Text content to write.
      append: Whether to append to the file instead of overwriting.

    Returns:
      Confirmation string with the resulting file size in bytes.
    """
    size = await self.session.write_file(
        self.path(path), content, append=bool(append)
    )
    return f"{path} now holds {size} bytes"

  async def edit_file(
      self, path: str, old_text: str, new_text: str, replace_all: bool = False
  ) -> str:
    """Replaces `old_text` with `new_text` in `path` inside the task container.

    Args:
      path: Target file path inside the task container.
      old_text: Substring to search for.
      new_text: Replacement string.
      replace_all: Whether to replace all occurrences instead of requiring one.

    Returns:
      Confirmation string or an error message if `old_text` is missing or
      ambiguous.
    """
    text = (await self.session.read_file(self.path(path))).decode("utf-8")
    count = text.count(old_text) if old_text else 0
    if count == 0:
      return f"error: old_text was not found in {path}"
    if count > 1 and not replace_all:
      return (
          f"error: old_text occurs {count} times in {path}; add context to make"
          " it unique, or set replace_all"
      )
    await self.session.write_file(
        self.path(path),
        text.replace(old_text, new_text, -1 if replace_all else 1),
    )
    return f"replaced {count if replace_all else 1} occurrence(s) in {path}"


class ToolDispatcher:
  def __init__(self, session):
    self.session = session
    self.handlers = {}
    self.specs = []

  def register(self, spec, handler):
    name = spec["function"]["name"]
    if name in self.handlers:
      raise ValueError(f"duplicate tool: {name}")
    self.handlers[name] = handler
    self.specs.append(spec)

  def register_container(self, container):
    for spec in TOOLS:
      self.register(spec, getattr(container, spec["function"]["name"]))

  async def __call__(self, name, args):
    await self.session.log(f"{name} {json.dumps(args)[:400]}")
    try:
      handler = self.handlers.get(name)
      return clip(await handler(**args)) if handler else f"error: there is no tool named {name}"
    except (taskbridge.TaskError, AttributeError, KeyError, TypeError, ValueError, RuntimeError) as exc:
      return f"error: {type(exc).__name__}: {exc}"
