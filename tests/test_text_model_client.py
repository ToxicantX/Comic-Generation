import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CLIENT_PATH = ROOT / "scripts" / "text_model_client.py"


def load_client_module():
    spec = importlib.util.spec_from_file_location("text_model_client_test", CLIENT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeStreamResponse:
    def __init__(self, chunks):
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def __iter__(self):
        return iter(self.chunks)


class TextModelClientTest(unittest.TestCase):
    def test_chat_json_sends_application_user_agent(self):
        client = load_client_module()
        chunks = [b'data: {"choices":[{"delta":{"content":"{\\"ok\\":true}"}}]}\n\n', b"data: [DONE]\n\n"]
        captured = {}

        def fake_urlopen(request, timeout):
            captured["user_agent"] = request.get_header("User-agent")
            return FakeStreamResponse(chunks)

        with patch.object(client, "text_model_config", return_value={
            "model": "test-model",
            "base_url": "https://example.test/v1",
            "api_key": "key",
            "env_path": "",
            "timeout": 180,
            "stream": True,
        }):
            with patch.object(client.urllib.request, "urlopen", side_effect=fake_urlopen):
                client.chat_json([{"role": "user", "content": "test"}], stream=True)

        self.assertEqual(captured["user_agent"], "ComicPipeline/1.0")

    def test_chat_json_streaming_combines_delta_content(self):
        client = load_client_module()
        events = [
            {"choices": [{"delta": {"content": "{\"ok\":"}}]},
            {"choices": [{"delta": {"content": "true}"}}]},
        ]
        chunks = [f"data: {json.dumps(event)}\n\n".encode("utf-8") for event in events]
        chunks.append(b"data: [DONE]\n\n")

        with patch.object(client, "text_model_config", return_value={
            "model": "test-model",
            "base_url": "https://example.test/v1",
            "api_key": "key",
            "env_path": "",
            "timeout": 180,
            "stream": True,
        }):
            with patch.object(client.urllib.request, "urlopen", return_value=FakeStreamResponse(chunks)):
                result = client.chat_json([{"role": "user", "content": "test"}], stream=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["_model"], "test-model")


if __name__ == "__main__":
    unittest.main()
