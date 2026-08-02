import subprocess
import tempfile
import unittest
from pathlib import Path

from lib.payload_docs import PayloadDocumentationStore


class PayloadDocumentationTests(unittest.IsolatedAsyncioTestCase):
    async def test_indexes_capabilities_and_heading_chunks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(
                ["git", "-C", str(source), "config", "user.name", "test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(source), "config", "user.email", "test@test"],
                check=True,
            )
            (source / "agent_capabilities.json").write_text(
                '{"os":["Linux"],"languages":["go"]}', encoding="utf-8"
            )
            docs = source / "documentation-payload" / "sample"
            docs.mkdir(parents=True)
            (docs / "commands.md").write_text(
                "# Commands\n## Echo\nRuns echo.\n### Output\nReturns standard output.",
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(source), "commit", "-qm", "fixture"],
                check=True,
            )

            store = PayloadDocumentationStore(root / "cache")
            summary = await store.index("sample", str(source))
            results = await store.search("sample", "echo output")

            self.assertEqual(summary["capabilities"]["languages"], ["go"])
            self.assertEqual(summary["documents"], 1)
            self.assertEqual(results[0]["heading"], "Echo")
            self.assertIn("Runs echo", results[0]["text"])
            self.assertRegex(results[0]["source_url"], r"@[0-9a-f]{40}:")

    def test_ignores_unrelated_payload_documentation(self):
        self.assertTrue(
            PayloadDocumentationStore._documentation_path(
                "documentation-payload/sample/usage.md", "sample"
            )
        )
        self.assertFalse(
            PayloadDocumentationStore._documentation_path(
                "documentation-payload/other/usage.md", "sample"
            )
        )


if __name__ == "__main__":
    unittest.main()
