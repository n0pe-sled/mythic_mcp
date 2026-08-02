"""Non-mutating smoke test against a configured Mythic instance."""

import argparse
import asyncio

import main
from lib.mythic_api import MythicAPI


async def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--api-token")
    parser.add_argument("--ssl", action=argparse.BooleanOptionalAction, default=None)
    client = MythicAPI(**main._settings(parser.parse_args()))
    operator = await client.connect()
    operations = await client.get_operations()
    callbacks = await client.get_callbacks()
    payloads = await client.get_payloads()
    services = await client.get_services()
    print(
        {
            "connected": True,
            "operator": operator["username"],
            "operations": len(operations),
            "active_callbacks": len(callbacks),
            "payloads": len(payloads),
            "payload_types": len(services["payloadtype"]),
            "c2_profiles": len(services["c2profile"]),
        }
    )


if __name__ == "__main__":
    asyncio.run(run())
