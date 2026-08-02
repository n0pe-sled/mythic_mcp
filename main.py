"""MCP server exposing agent-agnostic Mythic Scripting primitives."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from lib.mythic_api import MythicAPI
from lib.payload_docs import PayloadDocumentationStore

mcp = FastMCP("mythic")
api: MythicAPI | None = None
documentation = PayloadDocumentationStore()


def _expected_result_channels(command: dict[str, Any] | None) -> list[str]:
    channels = {"task_response"}
    for feature in (command or {}).get("supported_ui_features") or []:
        area = feature.split(":", 1)[0]
        channels.add(
            {
                "callback_table": "callback_state",
                "file_browser": "file_browser",
                "process_browser": "process_browser",
                "task_response": "interactive_task_response",
            }.get(area, area)
        )
    return sorted(channels)


def _task_responses(
    responses: list[dict[str, Any]], include_raw: bool = False
) -> list[dict[str, Any]]:
    """Decode Mythic's base64 response field into agent-readable text/JSON."""
    decoded_responses = []
    for response in responses:
        decoded = dict(response)
        raw = decoded.pop("response_text", None)
        if isinstance(raw, str):
            try:
                response_text = base64.b64decode(raw).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                response_text = None
            decoded["response_text"] = response_text
            if response_text is not None:
                try:
                    decoded["response_json"] = json.loads(response_text)
                except json.JSONDecodeError:
                    pass
            if include_raw or response_text is None:
                decoded["response_base64"] = raw
        decoded_responses.append(decoded)
    return decoded_responses


def _api() -> MythicAPI:
    if api is None:
        raise RuntimeError("The Mythic connection has not been initialized")
    return api


@mcp.tool()
async def get_server_info() -> dict[str, Any]:
    """Check the Mythic connection and return the authenticated operator."""
    return await _api().get_current_user()


@mcp.tool()
async def list_operations() -> list[dict[str, Any]]:
    """List operations visible to the authenticated Mythic operator."""
    return await _api().get_operations()


@mcp.tool()
async def set_current_operation(operation_id: int) -> dict[str, Any]:
    """Select the operation used by subsequent callbacks, payloads, and tasking."""
    return await _api().set_current_operation(operation_id)


@mcp.tool()
async def list_callbacks(active_only: bool = True) -> list[dict[str, Any]]:
    """List callbacks, optionally including callbacks marked inactive."""
    return await _api().get_callbacks(active_only=active_only)


@mcp.tool()
async def list_callback_commands(
    callback_id: int, include_parameters: bool = False
) -> dict[str, Any]:
    """Discover the commands currently loaded in a callback.

    callback_id is Mythic's callback display ID. The result follows dynamic
    command additions/removals reported by the agent.
    """
    return await _api().get_callback_commands(
        callback_id, include_parameters=include_parameters
    )


@mcp.tool()
async def get_command_parameters(
    callback_id: int, command_name: str
) -> dict[str, Any]:
    """Return structured Mythic metadata and parameter groups for a loaded command."""
    return await _api().get_command_parameters(callback_id, command_name)


@mcp.tool()
async def issue_task(
    callback_id: int,
    command_name: str,
    parameters: str | dict[str, Any],
    file_ids: list[str] | None = None,
    wait_for_complete: bool = False,
    timeout: int | None = None,
) -> dict[str, Any]:
    """Issue any command supported by a callback.

    Discover command_name and its parameters first. The default is asynchronous;
    use wait_for_task and get_task_output for long-running commands.
    """
    return await _api().issue_task(
        callback_id=callback_id,
        command_name=command_name,
        parameters=parameters,
        file_ids=file_ids,
        wait_for_complete=wait_for_complete,
        timeout=timeout,
    )


@mcp.tool()
async def list_tasks(callback_id: int | None = None) -> list[dict[str, Any]]:
    """List task history globally or for one callback display ID."""
    return await _api().get_tasks(callback_id)


@mcp.tool()
async def wait_for_task(task_id: int, timeout: int | None = None) -> dict[str, Any]:
    """Wait for a task display ID to complete or until timeout seconds elapse."""
    return await _api().wait_for_task(task_id, timeout=timeout)


@mcp.tool()
async def get_task_output(
    task_id: int, include_raw: bool = False
) -> list[dict[str, Any]]:
    """Get decoded text/JSON responses for a task display ID.

    Set include_raw to retain Mythic's original response_base64 field.
    """
    return _task_responses(await _api().get_task_output(task_id), include_raw)


@mcp.tool()
async def register_file(filename: str, content_base64: str) -> dict[str, str]:
    """Register base64-encoded bytes with Mythic for later task parameters."""
    return await _api().register_file(filename, content_base64)


@mcp.tool()
async def download_file(file_id: str) -> dict[str, str]:
    """Download a Mythic file by UUID, returned as base64-encoded bytes."""
    return await _api().download_file(file_id)


@mcp.tool()
async def list_payloads() -> list[dict[str, Any]]:
    """List payloads registered in the current operation."""
    return await _api().get_payloads()


@mcp.tool()
async def list_services() -> dict[str, Any]:
    """List installed payload types and C2 profiles with container state."""
    return await _api().get_services()


@mcp.tool()
async def index_payload_docs(
    payload_type: str,
    repository_url: str,
    ref: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Index an agent's versioned repository documentation.

    repository_url may be a public/private Git URL or a local repository path.
    Supply the deployed tag or commit as ref when known.
    """
    return await documentation.index(payload_type, repository_url, ref, refresh)


@mcp.tool()
async def search_payload_docs(
    payload_type: str, query: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Search indexed documentation for a payload type and return source-linked excerpts."""
    return await documentation.search(payload_type, query, limit)


@mcp.tool()
async def describe_payload_type(payload_type: str) -> dict[str, Any]:
    """Merge live Mythic build/C2 metadata with indexed agent capabilities."""
    runtime = await _api().get_payload_type(payload_type)
    docs = documentation.get(payload_type)
    return {
        "payload_type": payload_type,
        "installed": runtime is not None,
        "runtime": runtime,
        "documentation": docs,
    }


@mcp.tool()
async def describe_c2_profile(profile_name: str) -> dict[str, Any]:
    """Return live configuration parameters for an installed C2 profile."""
    runtime = await _api().get_c2_profile(profile_name)
    return {
        "profile": profile_name,
        "installed": runtime is not None,
        "runtime": runtime,
    }


@mcp.tool()
async def describe_command(
    payload_type: str, command_name: str, callback_id: int | None = None
) -> dict[str, Any]:
    """Merge command schema, callback loaded state, and indexed documentation."""
    runtime = await _api().get_registered_command(payload_type, command_name)
    loaded: bool | None = None
    if callback_id is not None:
        capabilities = await _api().get_callback_commands(
            callback_id, include_parameters=False
        )
        if capabilities["payload_type"] != payload_type:
            raise ValueError(
                f"Callback {callback_id} uses {capabilities['payload_type']}, not {payload_type}"
            )
        loaded = any(
            command["cmd"] == command_name for command in capabilities["commands"]
        )
    try:
        docs = await documentation.command_docs(payload_type, command_name)
    except ValueError:
        docs = []
    return {
        "payload_type": payload_type,
        "command": command_name,
        "registered": runtime is not None,
        "loaded": loaded,
        "expected_result_channels": _expected_result_channels(runtime),
        "runtime": runtime,
        "documentation": docs,
    }


@mcp.tool()
async def create_payload(
    payload_type: str,
    filename: str,
    operating_system: str,
    c2_profiles: list[dict[str, Any]],
    commands: list[str] | None = None,
    build_parameters: list[dict[str, Any]] | None = None,
    description: str = "",
    wait_for_complete: bool = False,
    timeout: int | None = None,
    include_all_commands: bool = False,
) -> dict[str, Any]:
    """Create a payload for any installed payload type and compatible C2 profile."""
    return await _api().create_payload(
        payload_type=payload_type,
        filename=filename,
        operating_system=operating_system,
        c2_profiles=c2_profiles,
        commands=commands,
        build_parameters=build_parameters,
        description=description,
        wait_for_complete=wait_for_complete,
        timeout=timeout,
        include_all_commands=include_all_commands,
    )


@mcp.tool()
async def download_payload(payload_id: str) -> dict[str, str]:
    """Download a built payload by UUID, returned as base64-encoded bytes."""
    return await _api().download_payload(payload_id)


@mcp.tool()
async def control_c2_profile(profile_name: str, action: str) -> dict[str, Any]:
    """Start or stop any installed C2 profile by name."""
    return await _api().control_c2_profile(profile_name, action)


def _settings(args: argparse.Namespace) -> dict[str, Any]:
    api_token = args.api_token or os.getenv("MYTHIC_API_TOKEN")
    username = args.username or os.getenv("MYTHIC_USERNAME")
    password = args.password or os.getenv("MYTHIC_PASSWORD")
    if not api_token and not (username and password):
        raise SystemExit(
            "Set MYTHIC_API_TOKEN or both MYTHIC_USERNAME and MYTHIC_PASSWORD"
        )
    return {
        "server_ip": args.host or os.getenv("MYTHIC_HOST", "127.0.0.1"),
        "server_port": args.port
        if args.port is not None
        else int(os.getenv("MYTHIC_PORT", "7443")),
        "username": username,
        "password": password,
        "api_token": api_token,
        "ssl": args.ssl
        if args.ssl is not None
        else os.getenv("MYTHIC_SSL", "true").lower() not in {"0", "false", "no"},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--api-token")
    parser.add_argument("--ssl", action=argparse.BooleanOptionalAction, default=None)
    return parser


async def main() -> None:
    global api
    api = MythicAPI(**_settings(_parser().parse_args()))
    await api.connect()
    await mcp.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(main())
