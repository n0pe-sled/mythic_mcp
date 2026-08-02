"""End-to-end stdio MCP smoke test against a configured Mythic instance."""

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["main.py"],
        env=dict(os.environ),
    )
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            tools = await session.list_tools()
            status = await session.call_tool("get_server_info", {})
            print({"connected": not status.isError, "tools": len(tools.tools)})


if __name__ == "__main__":
    asyncio.run(run())
