import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "scripts" / "build_comic_status_report.py"
    spec = importlib.util.spec_from_file_location("comic_test_status_report", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StatusReportTest(unittest.TestCase):
    def test_project_manifest_directory_is_used_for_page_files(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "projects" / "test"
            root.mkdir(parents=True)
            page_id = "TEST_EP01_P001"
            (root / f"{page_id.lower()}_plan.json").write_text(json.dumps({
                "panels": [{"panel_id": "TEST_PANEL01", "order": 1, "title": "测试分镜"}]
            }), encoding="utf-8")
            (root / f"{page_id.lower()}_fallback_workflows.json").write_text(json.dumps({
                "created": [{
                    "panel_id": "TEST_PANEL01",
                    "workflow": str(root / "workflow.json"),
                    "expected_panel_path": str(root / "missing.png"),
                }]
            }), encoding="utf-8")

            status = module.build_page_status({"page_id": page_id, "title": "第一页"}, root)

        self.assertEqual(Path(status["plan_path"]).parent, root)
        self.assertEqual(status["status"], "missing_assembly")
        self.assertEqual(status["panel_count"], 1)
        self.assertEqual(status["missing_panels"], ["TEST_PANEL01"])


if __name__ == "__main__":
    unittest.main()
