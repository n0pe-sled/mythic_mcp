"""Agent-agnostic adapter for the official Mythic Scripting package."""

from __future__ import annotations

import base64
from typing import Any

from mythic import mythic


class MythicAPI:
    """Expose Mythic primitives without assuming an agent or command set."""

    def __init__(
        self,
        *,
        server_ip: str,
        server_port: int = 7443,
        username: str | None = None,
        password: str | None = None,
        api_token: str | None = None,
        ssl: bool = True,
        timeout: int = 30,
    ) -> None:
        if not api_token and not (username and password):
            raise ValueError("Set MYTHIC_API_TOKEN or both MYTHIC_USERNAME and MYTHIC_PASSWORD")
        self.server_ip = server_ip
        self.server_port = server_port
        self.username = username
        self.password = password
        self.api_token = api_token
        self.ssl = ssl
        self.timeout = timeout
        self.mythic_instance = None

    async def connect(self) -> dict[str, Any]:
        self.mythic_instance = await mythic.login(
            username=self.username,
            password=self.password,
            apitoken=self.api_token,
            server_ip=self.server_ip,
            server_port=self.server_port,
            ssl=self.ssl,
            timeout=self.timeout,
        )
        return await self.get_current_user()

    def _connection(self):
        if self.mythic_instance is None:
            raise RuntimeError("The Mythic connection has not been initialized")
        return self.mythic_instance

    async def get_current_user(self) -> dict[str, Any]:
        details = await mythic.get_me(self._connection())
        return {
            "username": self.username,
            "server": f"{'https' if self.ssl else 'http'}://{self.server_ip}:{self.server_port}",
            **details,
        }

    async def get_operations(self) -> list[dict[str, Any]]:
        return await mythic.get_operations(self._connection())

    async def set_current_operation(self, operation_id: int) -> dict[str, Any]:
        if self.username is None:
            raise ValueError(
                "MYTHIC_USERNAME is required with an API token to change operations"
            )
        response = await mythic.get_operator(self._connection(), self.username)
        operators = response.get("operator", [])
        if len(operators) != 1:
            raise ValueError(f"Unable to resolve operator {self.username}")
        return await mythic.update_current_operation_for_user(
            self._connection(),
            operator_id=operators[0]["id"],
            operation_id=operation_id,
        )

    async def get_callbacks(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        query = mythic.get_all_active_callbacks if active_only else mythic.get_all_callbacks
        return await query(self._connection())

    async def get_callback(self, callback_id: int) -> dict[str, Any]:
        callbacks = await self.get_callbacks(active_only=False)
        for callback in callbacks:
            if callback.get("display_id") == callback_id:
                return callback
        raise ValueError(f"Callback {callback_id} does not exist")

    async def get_callback_commands(
        self, callback_id: int, *, include_parameters: bool = False
    ) -> dict[str, Any]:
        callback = await self.get_callback(callback_id)
        payload_type = callback["payload"]["payloadtype"]["name"]
        commands = await mythic.get_all_commands_for_payloadtype(
            self._connection(), payload_type_name=payload_type
        )
        result: dict[str, Any] = {
            "callback_id": callback_id,
            "payload_type": payload_type,
            "commands": commands,
        }
        if include_parameters:
            result["parameter_options"] = {
                command["cmd"]: await mythic.get_command_parameter_options(
                    self._connection(),
                    command_name=command["cmd"],
                    payload_type_name=payload_type,
                )
                for command in commands
            }
        return result

    async def get_command_parameters(
        self, callback_id: int, command_name: str
    ) -> dict[str, Any]:
        callback = await self.get_callback(callback_id)
        payload_type = callback["payload"]["payloadtype"]["name"]
        options = await mythic.get_command_parameter_options(
            self._connection(),
            command_name=command_name,
            payload_type_name=payload_type,
        )
        return {
            "callback_id": callback_id,
            "payload_type": payload_type,
            "command": command_name,
            "parameter_options": options,
        }

    async def issue_task(
        self,
        *,
        callback_id: int,
        command_name: str,
        parameters: str | dict[str, Any],
        file_ids: list[str] | None = None,
        wait_for_complete: bool = False,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        return await mythic.issue_task(
            self._connection(),
            callback_display_id=callback_id,
            command_name=command_name,
            parameters=parameters,
            file_ids=file_ids,
            wait_for_complete=wait_for_complete,
            timeout=timeout,
        )

    async def get_tasks(self, callback_id: int | None = None) -> list[dict[str, Any]]:
        return await mythic.get_all_tasks(
            self._connection(), callback_display_id=callback_id
        )

    async def wait_for_task(
        self, task_id: int, *, timeout: int | None = None
    ) -> dict[str, Any]:
        return await mythic.waitfor_task_complete(
            self._connection(), task_display_id=task_id, timeout=timeout
        )

    async def get_task_output(self, task_id: int) -> list[dict[str, Any]]:
        return await mythic.get_all_task_output_by_id(
            self._connection(), task_display_id=task_id
        )

    async def register_file(self, filename: str, content_base64: str) -> dict[str, str]:
        contents = base64.b64decode(content_base64, validate=True)
        file_id = await mythic.register_file(
            self._connection(), filename=filename, contents=contents
        )
        return {"file_id": file_id, "filename": filename}

    async def download_file(self, file_id: str) -> dict[str, str]:
        contents = await mythic.download_file(self._connection(), file_uuid=file_id)
        return {"file_id": file_id, "content_base64": base64.b64encode(contents).decode()}

    async def get_payloads(self) -> list[dict[str, Any]]:
        return await mythic.get_all_payloads(self._connection())

    async def get_services(self) -> dict[str, Any]:
        """Discover installed payload types and C2 profiles.

        Mythic Scripting does not currently expose these two collections through a
        dedicated helper, so use its supported custom-query primitive with a small,
        version-stable field set.
        """
        return await mythic.execute_custom_query(
            self._connection(),
            query="""
            query MCPServiceDiscovery {
                payloadtype {
                    id
                    name
                    container_running
                    supported_os
                }
                c2profile {
                    id
                    name
                    running
                    container_running
                    is_p2p
                }
            }
            """,
        )

    async def create_payload(
        self,
        *,
        payload_type: str,
        filename: str,
        operating_system: str,
        c2_profiles: list[dict[str, Any]],
        commands: list[str] | None = None,
        build_parameters: list[dict[str, Any]] | None = None,
        description: str = "",
        wait_for_complete: bool = False,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        return await mythic.create_payload(
            self._connection(),
            payload_type_name=payload_type,
            filename=filename,
            operating_system=operating_system,
            c2_profiles=c2_profiles,
            commands=commands,
            build_parameters=build_parameters,
            description=description,
            return_on_complete=wait_for_complete,
            timeout=timeout,
        )

    async def download_payload(self, payload_id: str) -> dict[str, str]:
        contents = await mythic.download_payload(
            self._connection(), payload_uuid=payload_id
        )
        return {
            "payload_id": payload_id,
            "content_base64": base64.b64encode(contents).decode(),
        }

    async def control_c2_profile(self, profile_name: str, action: str) -> dict[str, Any]:
        if action not in {"start", "stop"}:
            raise ValueError("action must be 'start' or 'stop'")
        result = await mythic.start_stop_c2_profile(
            self._connection(), c2_profile_name=profile_name, action=action
        )
        return {"profile": profile_name, "action": action, **result}
