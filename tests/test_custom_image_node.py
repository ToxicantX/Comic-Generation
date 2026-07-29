import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_image_node():
    module_path = ROOT / "custom_nodes" / "openai_compatible_image_node.py"
    spec = importlib.util.spec_from_file_location("comic_test_image_node", module_path)
    module = importlib.util.module_from_spec(spec)
    stubs = {name: types.ModuleType(name) for name in ("numpy", "requests", "torch")}
    stubs["requests"].Session = type("Session", (), {})
    stubs["requests"].Response = type("Response", (), {})
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


class CustomImageNodePathTest(unittest.TestCase):
    def test_edit_fallback_does_not_drop_references_on_auth_rate_limit_or_server_errors(self):
        module = load_image_node()

        def response(status, message):
            return type("Response", (), {
                "status_code": status,
                "text": message,
                "json": lambda self: {"error": {"message": message}},
            })()

        self.assertTrue(module._should_fallback_from_edits(response(404, "not found")))
        self.assertTrue(module._should_fallback_from_edits(response(400, "image edits endpoint is unsupported")))
        for status in (401, 403, 429, 500, 503):
            self.assertFalse(module._should_fallback_from_edits(response(status, "request failed")))

    def test_json_request_retries_rate_limit_once(self):
        module = load_image_node()
        limited = type("Response", (), {"status_code": 429, "headers": {}})()
        passed = type("Response", (), {"status_code": 200, "headers": {}})()
        session = type("Session", (), {
            "responses": [limited, passed],
            "post": lambda self, *args, **kwargs: self.responses.pop(0),
        })()
        attempts = []

        with patch.object(module.time, "sleep") as sleep:
            response = module._post_json_with_rate_limit_retry(
                session,
                "https://example.test/v1/images/generations",
                {},
                {"model": "test"},
                attempts,
                "json_generation",
            )

        self.assertIs(response, passed)
        sleep.assert_called_once_with(65)
        self.assertEqual([name for name, _ in attempts], ["json_generation", "json_generation_rate_limit_retry"])

    def test_relative_env_and_container_reference_paths_resolve_from_comfy_root(self):
        module = load_image_node()
        self.assertEqual(module.OpenAICompatibleImageGenerate.INPUT_TYPES()["optional"]["quality"][1]["default"], "auto")
        response = type("Response", (), {"status_code": 502})()
        self.assertFalse(module._should_fallback_from_edits(response))
        with tempfile.TemporaryDirectory() as temp_dir:
            comfy_root = Path(temp_dir)
            custom_nodes = comfy_root / "custom_nodes"
            custom_nodes.mkdir()
            module.__file__ = str(custom_nodes / "openai_compatible_image_node.py")
            env_path = comfy_root / ".comic-pipeline" / "image.env"
            env_path.parent.mkdir()
            env_path.write_text(
                "OPENAI_API_KEY=test-secret\nOPENAI_BASE_URL=https://example.test\n",
                encoding="utf-8",
            )
            image_path = comfy_root / "output" / "ComicPipeline" / "reference.png"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"png")

            config = module._resolve_openai_compatible_config("", "", ".comic-pipeline/image.env")
            references = module._reference_paths("/comfyui/output/ComicPipeline/reference.png")

        self.assertEqual(config["api_key"], "test-secret")
        self.assertEqual(config["base_url"], "https://example.test")
        self.assertEqual(references, [image_path])


if __name__ == "__main__":
    unittest.main()
