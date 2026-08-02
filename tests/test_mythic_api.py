import base64
import unittest
from unittest.mock import AsyncMock, patch

from lib.mythic_api import MythicAPI


class MythicAPITests(unittest.IsolatedAsyncioTestCase):
    def client(self, **overrides):
        values = {"server_ip": "mythic.test", "api_token": "token"}
        values.update(overrides)
        return MythicAPI(**values)

    async def test_connects_with_api_token(self):
        client = self.client()
        connection = object()
        with patch("lib.mythic_api.mythic.login", AsyncMock(return_value=connection)) as login:
            with patch(
                "lib.mythic_api.mythic.get_me",
                AsyncMock(return_value={"meHook": {"status": "success"}}),
            ):
                result = await client.connect()

        self.assertEqual(result["username"], None)
        self.assertEqual(result["meHook"]["status"], "success")
        login.assert_awaited_once_with(
            username=None,
            password=None,
            apitoken="token",
            server_ip="mythic.test",
            server_port=7443,
            ssl=True,
            timeout=30,
        )

    async def test_discovers_commands_from_callback_payload_type(self):
        client = self.client()
        client.mythic_instance = object()
        callback = {
            "display_id": 4,
            "payload": {"payloadtype": {"name": "example-agent"}},
        }
        response = {
            "callback": [
                {
                    "loadedcommands": [
                        {
                            "version": 2,
                            "command": {
                                "cmd": "do_thing",
                                "attributes": {},
                                "commandparameters": [{"name": "value"}],
                            },
                        }
                    ]
                }
            ]
        }
        with patch.object(client, "get_callback", AsyncMock(return_value=callback)):
            with patch(
                "lib.mythic_api.mythic.execute_custom_query",
                AsyncMock(return_value=response),
            ) as commands:
                result = await client.get_callback_commands(4, include_parameters=True)

        self.assertEqual(result["payload_type"], "example-agent")
        self.assertEqual(result["commands"][0]["cmd"], "do_thing")
        self.assertTrue(result["commands"][0]["loaded"])
        self.assertEqual(result["commands"][0]["parameters"][0]["name"], "value")
        self.assertEqual(commands.await_args.kwargs["variables"], {"callback_id": 4})

    async def test_issues_arbitrary_agent_command(self):
        client = self.client()
        client.mythic_instance = object()
        with patch(
            "lib.mythic_api.mythic.issue_task",
            AsyncMock(return_value={"status": "success", "display_id": 12}),
        ) as issue:
            result = await client.issue_task(
                callback_id=4,
                command_name="agent_defined_command",
                parameters={"value": 3},
            )

        self.assertEqual(result["display_id"], 12)
        issue.assert_awaited_once_with(
            client.mythic_instance,
            callback_display_id=4,
            command_name="agent_defined_command",
            parameters={"value": 3},
            file_ids=None,
            wait_for_complete=False,
            timeout=None,
        )

    async def test_file_round_trip_uses_base64_at_mcp_boundary(self):
        client = self.client()
        client.mythic_instance = object()
        with patch(
            "lib.mythic_api.mythic.register_file", AsyncMock(return_value="file-id")
        ) as register:
            result = await client.register_file(
                "sample.bin", base64.b64encode(b"payload").decode()
            )
        self.assertEqual(result, {"file_id": "file-id", "filename": "sample.bin"})
        register.assert_awaited_once_with(
            client.mythic_instance, filename="sample.bin", contents=b"payload"
        )

    async def test_rejects_unknown_c2_action(self):
        client = self.client()
        client.mythic_instance = object()
        with self.assertRaisesRegex(ValueError, "action must"):
            await client.control_c2_profile("http", "restart")

    async def test_discovers_services_through_mythic_scripting(self):
        client = self.client()
        client.mythic_instance = object()
        response = {"payloadtype": [], "c2profile": [{"name": "http"}]}
        with patch(
            "lib.mythic_api.mythic.execute_custom_query",
            AsyncMock(return_value=response),
        ) as query:
            result = await client.get_services()
        self.assertEqual(result, response)
        self.assertIn("MCPServiceDiscovery", query.await_args.kwargs["query"])


if __name__ == "__main__":
    unittest.main()
