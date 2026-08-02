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
            payload_type = os.getenv("MYTHIC_DOC_PAYLOAD_TYPE")
            docs = None
            command_docs = None
            if payload_type:
                docs = await session.call_tool(
                    "describe_payload_type", {"payload_type": payload_type}
                )
                if os.getenv("MYTHIC_DOC_COMMAND"):
                    command_docs = await session.call_tool(
                        "describe_command",
                        {
                            "payload_type": payload_type,
                            "command_name": os.environ["MYTHIC_DOC_COMMAND"],
                        },
                    )
            print(
                {
                    "connected": not status.isError,
                    "tools": len(tools.tools),
                    "documentation_query": None if docs is None else not docs.isError,
                    "command_query": None
                    if command_docs is None
                    else not command_docs.isError,
                }
            )


if __name__ == "__main__":
    asyncio.run(run())
