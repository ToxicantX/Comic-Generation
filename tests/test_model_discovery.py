import importlib.util
import io
import json
import sys
import unittest
import urllib.error
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class ModelDiscoveryTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "console"))
        spec = importlib.util.spec_from_file_location("comic_model_discovery_test", ROOT / "console" / "server.py")
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(self.server, "runtime_config", return_value={
            "COMIC_PIPELINE_TEXT_ENV_PATH": "/tmp/text.env",
            "COMIC_PIPELINE_IMAGE_ENV_PATH": "/tmp/image.env",
        }))
        self.read_env = self.stack.enter_context(patch.object(self.server, "read_env", side_effect=lambda path: {
            "OPENAI_BASE_URL": f"https://{path.stem}.example/v1",
            "OPENAI_API_KEY": f"saved-{path.stem}-secret",
        }))
        self.save = self.stack.enter_context(patch.object(self.server, "save_config"))
        self.write = self.stack.enter_context(patch.object(self.server, "write_env"))
        self.opener = self.stack.enter_context(patch.object(self.server.urllib.request, "build_opener"))
        self.open = self.opener.return_value.open
        self.open.return_value = io.BytesIO(json.dumps({"data": [
            {"id": "z-model"}, {"id": "a-model"}, {"id": "z-model"},
            {"id": ""}, {"id": 123}, None,
        ]}).encode("utf-8"))

    def test_saved_text_and_image_credentials_are_independent(self):
        for target in ("text", "image"):
            with self.subTest(target=target):
                self.open.return_value = io.BytesIO(b'{"data":[{"id":"model-a"}]}')
                result = self.server.list_models_api({"target": target})
                request = self.open.call_args.args[0]
                self.assertEqual(request.full_url, f"https://{target}.example/v1/models")
                self.assertEqual(request.get_header("Authorization"), f"Bearer saved-{target}-secret")
                self.assertEqual(request.get_method(), "GET")
                self.assertEqual(self.open.call_args.kwargs["timeout"], 20)
                self.assertEqual(self.read_env.call_args.args[0], Path(f"/tmp/{target}.env"))
                self.assertTrue(result["ok"])
                self.assertEqual(result["models"], ["model-a"])
                self.assertNotIn("secret", json.dumps(result))
        self.save.assert_not_called()
        self.write.assert_not_called()

    def test_unsaved_provider_values_are_used_without_persisting(self):
        result = self.server.list_models_api({
            "target": "image", "base_url": "https://new.example/api/v1/images/generations",
            "api_key": "new-image-secret",
        })
        request = self.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://new.example/api/v1/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer new-image-secret")
        self.assertEqual(result["models"], ["a-model", "z-model"])
        self.save.assert_not_called()
        self.write.assert_not_called()

    def test_model_urls_normalize_supported_provider_endpoints(self):
        for suffix in ("", "/v1", "/v1/", "/v1/chat/completions", "/v1/responses",
                       "/v1/images/generations", "/v1/images/edits", "/v1/models"):
            with self.subTest(suffix=suffix):
                self.open.return_value = io.BytesIO(b'{"data":[{"id":"model-a"}]}')
                self.server.list_models_api({"target": "text", "base_url": f"https://api.example{suffix}"})
                self.assertEqual(self.open.call_args.args[0].full_url, "https://api.example/v1/models")

    def test_blank_key_uses_only_the_corresponding_saved_key(self):
        self.server.list_models_api({"target": "text", "api_key": " "})
        self.assertEqual(self.open.call_args.args[0].get_header("Authorization"), "Bearer saved-text-secret")

    def test_missing_configuration_and_invalid_target_do_not_call_provider(self):
        self.read_env.side_effect = None
        self.read_env.return_value = {}
        for payload in ({"target": "text"}, {"target": "image", "base_url": "https://api.example"}):
            with self.subTest(payload=payload):
                result = self.server.list_models_api(payload)
                self.assertFalse(result["ok"])
                self.assertEqual(result["models"], [])
        with self.assertRaises(ValueError):
            self.server.list_models_api({"target": "other"})
        self.open.assert_not_called()

    def test_invalid_urls_and_header_injection_are_rejected(self):
        for url in ("file:///tmp/config", "https://user:secret@api.example", "https://api.example?key=secret",
                    "https://api.example#secret", "api.example", "https://api.example:bad"):
            with self.subTest(url=url):
                self.assertFalse(self.server.list_models_api({"target": "text", "base_url": url})["ok"])
        result = self.server.list_models_api({"target": "image", "api_key": "secret\r\nX-Header: value"})
        self.assertFalse(result["ok"])
        self.open.assert_not_called()

    def test_invalid_or_empty_responses_preserve_manual_fallback(self):
        for body in (b"not-json", b"[]", b'{"data":{}}', b'{"data":[]}', b'{"data":[{"id":123}]}',
                     b"x" * (2 * 1024 * 1024 + 1)):
            with self.subTest(body_length=len(body)):
                self.open.return_value = io.BytesIO(body)
                result = self.server.list_models_api({"target": "text"})
                self.assertFalse(result["ok"])
                self.assertEqual(result["models"], [])
                self.assertIn("手动", result["message"])

    def test_provider_errors_are_sanitized(self):
        for code in (301, 401, 403, 404, 429, 500):
            with self.subTest(code=code):
                self.open.side_effect = urllib.error.HTTPError(
                    "https://secret.example", code, "saved-text-secret", {}, io.BytesIO(b"saved-text-secret"),
                )
                result = self.server.list_models_api({"target": "text"})
                self.assertFalse(result["ok"])
                self.assertIn(str(code), result["message"])
                self.assertNotIn("secret", json.dumps(result))

    def test_timeout_and_network_errors_are_sanitized(self):
        for error in (TimeoutError("secret"), urllib.error.URLError(TimeoutError("secret")),
                      urllib.error.URLError("secret")):
            with self.subTest(error_type=type(error).__name__):
                self.open.side_effect = error
                result = self.server.list_models_api({"target": "image"})
                self.assertFalse(result["ok"])
                self.assertNotIn("secret", json.dumps(result))

    def test_redirects_cannot_forward_the_provider_key(self):
        self.server.list_models_api({"target": "text"})
        redirect_handler = self.opener.call_args.args[0]
        self.assertIsNone(redirect_handler.redirect_request(None, None, 302, "redirect", {}, "https://other.example"))


if __name__ == "__main__":
    unittest.main()
