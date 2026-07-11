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
    def test_relative_env_and_container_reference_paths_resolve_from_comfy_root(self):
        module = load_image_node()
        self.assertEqual(module.OpenAICompatibleImageGenerate.INPUT_TYPES()["optional"]["quality"][1]["default"], "auto")
        response = type("Response", (), {"status_code": 502})()
        self.assertTrue(module._should_fallback_from_edits(response))
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
