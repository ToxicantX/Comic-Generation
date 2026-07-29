import base64
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "image_provider.py"


def load_module():
    spec = importlib.util.spec_from_file_location("image_provider", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200, headers: dict | None = None):
        self.payload = payload
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def png_base64() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 12), "#336699").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class ImageProviderTest(unittest.TestCase):
    def test_backend_defaults_to_direct_api_and_rejects_unknown_value(self):
        module = load_module()

        self.assertEqual(module.normalize_backend(""), "direct_api")
        self.assertEqual(module.normalize_backend("comfyui"), "comfyui")
        with self.assertRaisesRegex(ValueError, "direct_api.*comfyui"):
            module.normalize_backend("automatic")

    def test_edit_fallback_only_allows_unsupported_endpoint_errors(self):
        module = load_module()

        self.assertTrue(module.should_fallback_from_edits(404, "not found"))
        self.assertTrue(module.should_fallback_from_edits(405, "method not allowed"))
        self.assertTrue(module.should_fallback_from_edits(400, "unsupported image edits endpoint"))
        for status in (401, 403, 429, 500, 503):
            self.assertFalse(module.should_fallback_from_edits(status, "request failed"))

    def test_generate_from_workflow_writes_exact_output_path(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow_path = root / "workflow.json"
            output_path = root / "panels" / "panel01.png"
            env_path = root / "image.env"
            env_path.write_text(
                "OPENAI_API_KEY=test-key\nOPENAI_BASE_URL=https://images.example\n",
                encoding="utf-8",
            )
            workflow_path.write_text(json.dumps({
                "prompt": {
                    "1": {
                        "class_type": "OpenAICompatibleImageGenerate",
                        "inputs": {
                            "prompt": "hero at sunrise",
                            "negative_prompt": "text, watermark",
                            "model": "image-model",
                            "size": "1024x1536",
                            "quality": "high",
                        },
                    },
                    "2": {
                        "class_type": "SaveImage",
                        "inputs": {"filename_prefix": "ComicPipeline/panels/panel01"},
                    },
                }
            }), encoding="utf-8")
            requests = []

            def fake_urlopen(request, timeout):
                requests.append((request, timeout))
                return FakeResponse({"data": [{"b64_json": png_base64()}]})

            with patch.object(module.urllib.request, "urlopen", side_effect=fake_urlopen):
                result = module.generate_from_workflow(
                    workflow_path,
                    output_path,
                    env_path=env_path,
                    prompt_suffix="\n\n[生成上下文]\nkeep the same costume",
                )

            self.assertTrue(output_path.is_file())
            with Image.open(output_path) as generated:
                self.assertEqual(generated.size, (8, 12))
                self.assertEqual(generated.format, "PNG")
            self.assertEqual(result["backend"], "direct_api")
            self.assertEqual(result["output_path"], str(output_path))
            self.assertEqual(result["model"], "image-model")
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0][0].get_header("User-agent"), "ComicPipeline/2.0")
            request_body = json.loads(requests[0][0].data.decode("utf-8"))
            self.assertIn("Avoid: text, watermark", request_body["prompt"])
            self.assertIn("keep the same costume", request_body["prompt"])

    def test_base_url_with_v1_does_not_duplicate_api_prefix(self):
        module = load_module()
        config = {"api_key": "test-key", "base_url": "https://images.example/v1"}
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(request.full_url)
            return FakeResponse({"data": [{"b64_json": png_base64()}]})

        with patch.object(module.urllib.request, "urlopen", side_effect=fake_urlopen):
            image_bytes, _ = module.request_image(
                config,
                {"model": "image-model", "prompt": "test", "n": 1},
                [],
                30,
            )

        self.assertTrue(image_bytes.startswith(b"\x89PNG"))
        self.assertEqual(requests, ["https://images.example/v1/images/generations"])

    def test_full_image_endpoint_is_normalized_for_each_operation(self):
        module = load_module()

        self.assertEqual(
            module.image_api_url("https://images.example/v1/images/generations", "images/generations"),
            "https://images.example/v1/images/generations",
        )
        self.assertEqual(
            module.image_api_url("https://images.example/v1/images/generations", "images/edits"),
            "https://images.example/v1/images/edits",
        )

    def test_reference_edit_retries_rate_limit_without_dropping_reference(self):
        module = load_module()
        config = {"api_key": "test-key", "base_url": "https://images.example"}
        responses = [
            (429, {"Retry-After": "0"}, b'{"error":{"message":"rate limited"}}'),
            (200, {}, json.dumps({"data": [{"b64_json": png_base64()}]}).encode("utf-8")),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            reference = Path(temp_dir) / "reference.png"
            Image.new("RGB", (4, 4), "white").save(reference)
            with patch.object(module, "post_multipart", side_effect=responses) as post, patch.object(module.time, "sleep"):
                image_bytes, attempts = module.request_image(
                    config,
                    {"model": "image-model", "prompt": "test", "response_format": "b64_json"},
                    [reference],
                    30,
                )

        self.assertTrue(image_bytes.startswith(b"\x89PNG"))
        self.assertEqual(post.call_count, 2)
        self.assertEqual([item["status"] for item in attempts], [429, 200])

    def test_reference_edit_retries_without_response_format(self):
        module = load_module()
        config = {"api_key": "test-key", "base_url": "https://images.example"}
        payloads = []

        def fake_post(url, headers, payload, references, timeout):
            payloads.append(dict(payload))
            if len(payloads) == 1:
                return 400, {}, b'{"error":{"message":"Unknown parameter: response_format"}}'
            return 200, {}, json.dumps({"data": [{"b64_json": png_base64()}]}).encode("utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            reference = Path(temp_dir) / "reference.png"
            Image.new("RGB", (4, 4), "white").save(reference)
            with patch.object(module, "post_multipart", side_effect=fake_post):
                image_bytes, _ = module.request_image(
                    config,
                    {"model": "image-model", "prompt": "test", "response_format": "b64_json"},
                    [reference],
                    30,
                )

        self.assertTrue(image_bytes.startswith(b"\x89PNG"))
        self.assertEqual(len(payloads), 2)
        self.assertIn("response_format", payloads[0])
        self.assertNotIn("response_format", payloads[1])

    def test_generate_from_workflow_rejects_non_png_output(self):
        module = load_module()
        with self.assertRaisesRegex(ValueError, "PNG"):
            module.generate_from_workflow("missing-workflow.json", "panel.jpg")


if __name__ == "__main__":
    unittest.main()
