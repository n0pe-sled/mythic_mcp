import argparse
import base64
import os
import unittest
from unittest.mock import patch

import main


class SettingsTests(unittest.TestCase):
    def args(self, **overrides):
        values = {
            "host": None,
            "port": None,
            "username": None,
            "password": None,
            "api_token": None,
            "ssl": None,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_accepts_token_without_password(self):
        with patch.dict(
            os.environ,
            {"MYTHIC_API_TOKEN": "token", "MYTHIC_HOST": "localhost"},
            clear=True,
        ):
            settings = main._settings(self.args())
        self.assertEqual(settings["api_token"], "token")
        self.assertEqual(settings["server_ip"], "localhost")
        self.assertTrue(settings["ssl"])

    def test_requires_complete_credentials(self):
        with patch.dict(os.environ, {"MYTHIC_USERNAME": "operator"}, clear=True):
            with self.assertRaises(SystemExit):
                main._settings(self.args())

    def test_maps_declared_ui_features_to_result_channels(self):
        channels = main._expected_result_channels(
            {"supported_ui_features": ["process_browser:list"]}
        )
        self.assertEqual(channels, ["process_browser", "task_response"])

    def test_decodes_text_and_structured_task_responses(self):
        output = [{"response_text": base64.b64encode(b'[{"pid": 7}]').decode()}]

        responses = main._task_responses(output)

        self.assertEqual(responses[0]["response_text"], '[{"pid": 7}]')
        self.assertEqual(responses[0]["response_json"], [{"pid": 7}])
        self.assertNotIn("response_base64", responses[0])

    def test_can_retain_raw_task_response(self):
        raw = base64.b64encode(b"hello").decode()
        responses = main._task_responses([{"response_text": raw}], include_raw=True)
        self.assertEqual(responses[0]["response_base64"], raw)
        self.assertEqual(responses[0]["response_text"], "hello")


if __name__ == "__main__":
    unittest.main()
