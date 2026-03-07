import contextlib
import json
import logging
import os
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "mcp_config.json"


class MCPClientManager:
    def __init__(self):
        self._exit_stack = contextlib.AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self._tools: list[dict] = []

    async def start(self):
        await self._exit_stack.__aenter__()
        if not CONFIG_PATH.exists():
            log.info("mcp_config.json not found — no MCP servers configured")
            return
        config = json.loads(CONFIG_PATH.read_text())
        for name, cfg in config.get("mcpServers", {}).items():
            try:
                await self._connect(name, cfg)
            except Exception as e:
                log.error("MCP server %s failed to connect: %s", name, e)

    async def _connect(self, name: str, cfg: dict):
        params = StdioServerParameters(
            command=cfg["command"],
            args=cfg.get("args", []),
            env={**os.environ, **cfg.get("env", {})},
        )
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        session: ClientSession = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()

        resp = await session.list_tools()
        for tool in resp.tools:
            self._tools.append({
                "name": f"{name}__{tool.name}",
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            })
        self._sessions[name] = session
        log.info("MCP server %s connected (%d tools)", name, len(resp.tools))

    def get_tools(self) -> list[dict]:
        return self._tools

    async def call_tool(self, namespaced_name: str, tool_input: dict) -> str:
        server_name, tool_name = namespaced_name.split("__", 1)
        session = self._sessions.get(server_name)
        if not session:
            raise ValueError(f"No connected MCP server: {server_name}")
        result = await session.call_tool(tool_name, tool_input)
        return "\n".join(
            c.text if hasattr(c, "text") else str(c) for c in result.content
        )

    async def stop(self):
        await self._exit_stack.aclose()
