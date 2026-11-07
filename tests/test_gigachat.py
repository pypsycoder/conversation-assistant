"""Cloud transport safety and provider-specific payload checks, no live requests."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.gigachat import GigaChatClient, NoRedirect, SafeAPIError, read_dotenv
from backend.extraction import SYSTEM, SCHEMA


class GigaChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = Path(self.temp.name) / ".env"
        self.env.write_text('GIGACHAT_KEY_L1="fake-authorization-key"\n', encoding="utf-8")

    def test_literal_env_does_not_expand_or_execute(self):
        self.env.write_text("export KEY='$(do-not-execute)'\nOTHER=value # comment\n", encoding="utf-8")
        self.assertEqual(read_dotenv(self.env), {"KEY": "$(do-not-execute)", "OTHER": "value"})

    def test_duplicate_env_variable_rejected_without_echoing_value(self):
        self.env.write_text("KEY=hidden-one\nKEY=hidden-two", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            read_dotenv(self.env)
        self.assertNotIn("hidden", str(caught.exception))

    def test_official_endpoint_only(self):
        self.env.write_text('GIGACHAT_KEY_L1=fake-key\nGIGACHAT_BASE_URL=https://example.com/v1', encoding="utf-8")
        with self.assertRaises(ValueError):
            GigaChatClient(self.env)

    def test_redirect_never_forwards_authorization(self):
        with self.assertRaises(SafeAPIError):
            NoRedirect().redirect_request(None, None, 307, "redirect", {}, "https://example.com")

    def test_redaction_covers_basic_key_and_access_token(self):
        client = GigaChatClient(self.env)
        client._token = "fake-access-token"
        text = client.redact("Basic fake-authorization-key; Bearer fake-access-token")
        self.assertNotIn("fake-", text)
        self.assertIn("[REDACTED]", text)

    def test_models_metadata_contains_no_credentials(self):
        client = GigaChatClient(self.env)
        with patch.object(client, "_request", return_value={"data": [{"id": "GigaChat-3-Ultra"}]}):
            metadata = client.models()
        self.assertEqual(metadata["selected_model"], "GigaChat-3-Ultra")
        self.assertNotIn("fake-authorization-key", json.dumps(metadata))
        self.assertTrue(metadata["tls_verification"])

    def test_extract_preserves_messages_schema_and_omits_auth_artifacts(self):
        client = GigaChatClient(self.env)
        client.model = "GigaChat-3-Ultra"
        client._token = "fake-access-token"
        client._expires_at = time.time() + 1000
        raw = {"choices": [{"finish_reason": "stop", "message": {"content": '{"facts":[]}'}}], "usage": {"total_tokens": 1}}
        with patch.object(client, "_request", return_value=raw):
            result = client.extract([])
        payload = result["request"]
        self.assertEqual(payload["messages"][0]["content"], SYSTEM)
        self.assertEqual(payload["response_format"]["schema"], SCHEMA)
        self.assertEqual(payload["temperature"], 0.001)
        self.assertNotIn("seed", payload)
        self.assertEqual(result["validation_errors"], [])
        self.assertNotIn("fake-", json.dumps(result))

    def test_refusal_or_truncation_is_not_an_empty_success(self):
        client = GigaChatClient(self.env)
        client.model = "GigaChat-3-Ultra"
        for reason in ["length", "blacklist"]:
            raw = {"choices": [{"finish_reason": reason, "message": {"content": ""}}]}
            with self.subTest(reason=reason), patch.object(client, "_request", return_value=raw):
                result = client.extract([])
                self.assertIsNone(result["parsed"])
                self.assertTrue(result["validation_errors"])


if __name__ == "__main__":
    unittest.main()
