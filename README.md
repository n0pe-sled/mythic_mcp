# Mythic MCP

An agent-agnostic MCP server for Mythic. It uses the official asynchronous [Mythic Scripting](https://github.com/MythicMeta/Mythic_Scripting) package and exposes Mythic primitives instead of assuming command names from a specific payload type.

## Design

- Discover callbacks and their payload types at runtime.
- Discover the command set and parameter guidance supplied by each agent.
- Submit any supported command with string or structured parameters.
- Keep long-running task submission separate from completion and output collection.
- Support Mythic file and payload transfer with base64 at the MCP boundary.
- Overlay exact-ref payload documentation without executing repository code.
- Read authentication from environment variables so credentials are not exposed in process arguments.

## Requirements

- Python 3.10 or later
- [uv](https://docs.astral.sh/uv/)
- A Mythic operator username/password or API token

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MYTHIC_HOST` | `127.0.0.1` | Mythic web/API hostname |
| `MYTHIC_PORT` | `7443` | Mythic web/API port |
| `MYTHIC_SSL` | `true` | Set to `false` for a non-TLS endpoint |
| `MYTHIC_API_TOKEN` | | Preferred authentication method |
| `MYTHIC_USERNAME` | | Used with `MYTHIC_PASSWORD` when no token is set |
| `MYTHIC_PASSWORD` | | Used with `MYTHIC_USERNAME` when no token is set |

CLI flags with the same names are available for temporary testing. Environment variables are preferred for secrets.

Example MCP client configuration:

```json
{
  "mcpServers": {
    "mythic": {
      "command": "uv",
      "args": [
        "--directory",
        "/full/path/to/mythic-mcp",
        "run",
        "main.py"
      ],
      "env": {
        "MYTHIC_HOST": "127.0.0.1",
        "MYTHIC_PORT": "7443",
        "MYTHIC_API_TOKEN": "replace-with-an-operator-api-token"
      }
    }
  }
}
```

## MCP tools

- `get_server_info`, `list_operations`, `set_current_operation`
- `list_callbacks`
- `list_callback_commands`, `get_command_parameters`
- `index_payload_docs`, `search_payload_docs`
- `describe_payload_type`, `describe_c2_profile`, `describe_command`
- `issue_task`, `list_tasks`, `wait_for_task`, `get_task_output`
- `register_file`, `download_file`
- `list_services`, `list_payloads`, `create_payload`, `download_payload`
- `control_c2_profile`

`get_task_output` decodes Mythic response bytes into `response_text` and, when
the response is JSON, `response_json`. Set `include_raw=true` only when the
original `response_base64` is needed.

Use the callback display ID and task display ID shown in the Mythic UI. `issue_task` is asynchronous by default. Discover a callback's commands and parameters before submitting agent-specific tasking.

## Payload documentation

Index the repository and exact deployed ref once, then use descriptions/searches alongside live Mythic state:

```text
index_payload_docs(
  payload_type="poseidon",
  repository_url="https://github.com/MythicAgents/poseidon",
  ref="<deployed-tag-or-commit>"
)
describe_payload_type(payload_type="poseidon")
describe_command(payload_type="poseidon", command_name="ps", callback_id=7)
```

The index reads Git objects without a checkout, limits input to documentation files, and caches source-linked chunks under `~/.cache/mythic-mcp/docs`. `agent_capabilities.json` is parsed as structured data. Markdown is split by heading so command usage, arguments, output notes, development guidance, and OPSEC notes can be retrieved without injecting an entire repository into the model context.

## Development

```sh
uv sync
uv run python -m unittest discover -s tests -v
```

With configuration variables set, non-mutating live checks are available as `uv run python -m tests.live_smoke` and `uv run python -m tests.live_mcp_smoke`. Invoke one MCP tool for live integration testing with `uv run python -m tests.live_tool_call TOOL [JSON_ARGUMENTS]`.

No agent or C2 profile is required for connection, operation, callback, task-history, or payload-history queries. Tasking and payload builds naturally require compatible services installed in Mythic.
