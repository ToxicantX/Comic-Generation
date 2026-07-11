import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "scripts" / "build_comic_episode_draft_qa.py"
    spec = importlib.util.spec_from_file_location("comic_test_draft_qa", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DraftQaTest(unittest.TestCase):
    def test_text_free_bubble_reservation_is_not_blocked(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = Path(temp_dir) / "workflow.json"
            workflow.write_text("{}", encoding="utf-8")
            result = module.check_panel({}, {
                "panel_id": "PANEL01",
                "full_prompt": (
                    "Detailed comic panel with cinematic lighting and a stable character design. "
                    "Reserve clean negative space for possible speech bubble; do not render text inside the image."
                ),
                "workflow": str(workflow),
                "expected_panel_path": str(Path(temp_dir) / "output.png"),
            }, {})

        self.assertEqual(result["issues"], [])
        self.assertNotIn("missing_no_text_instruction", result["warnings"])


if __name__ == "__main__":
    unittest.main()
