"""Invoke one MCP tool against a configured live Mythic instance."""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run() -> None:
    if len(sys.argv) not in {2, 3}:
        raise SystemExit("usage: python -m tests.live_tool_call TOOL [JSON_ARGUMENTS]")
    arguments = json.loads(sys.argv[2]) if len(sys.argv) == 3 else {}
    params = StdioServerParameters(
        command=sys.executable,
        args=["main.py"],
        env=dict(os.environ),
    )
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            result = await session.call_tool(sys.argv[1], arguments)
            if result.isError:
                raise RuntimeError("\n".join(item.text for item in result.content))
            for item in result.content:
                if item.type == "text":
                    print(item.text)


if __name__ == "__main__":
    asyncio.run(run())
