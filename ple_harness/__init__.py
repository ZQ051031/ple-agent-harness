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

"""Single-loop harness."""
import time
from .common import SYSTEM
from .llm import AgentLoop
from .mcp import MCPCatalog
from .tools import ContainerTools, ToolDispatcher

async def solve(session):
    dispatcher = ToolDispatcher(session)
    container = ContainerTools(session)
    dispatcher.register_container(container)
    catalog = MCPCatalog(session, dispatcher.handlers)
    mcp = await catalog.connect()
    catalog.register(dispatcher)
    left = session.time_left()
    loop = AgentLoop(
        session, SYSTEM.format(workdir=session.workdir, mcp=mcp,
                               minutes=int(left / 60) if left else "unlimited"),
        session.instruction, dispatcher.specs, dispatcher,
        deadline=None if left is None else time.monotonic() + left,
    )
    container.time_left = loop.time_left
    container.finish_margin = min(180, max(left, 0) / 4) if left is not None else 180
    try:
        answer, _ = await loop.run()
        return answer
    finally:
        await loop.client.close()
