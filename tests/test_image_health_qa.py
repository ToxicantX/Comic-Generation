import argparse
import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_comic_image_health_qa.py"
SPEC = importlib.util.spec_from_file_location("build_comic_image_health_qa", SCRIPT_PATH)
health_qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health_qa)


class ImageHealthQaSizeTests(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(blank_stddev=2.0, low_contrast_stddev=8.0)

    def check_size(self, size):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "panel.png"
            image = Image.effect_noise(size, 64).convert("RGB")
            image.save(path)
            return health_qa.check_image_file(
                path=str(path),
                page_id="EP01_P001",
                panel_id="EP01_P001_PANEL01",
                image_kind="panel",
                min_width=512,
                min_height=512,
                min_bytes=1,
                expected_size=(1024, 1536),
                args=self.args,
            )

    def test_one_pixel_size_variance_is_warning(self):
        result = self.check_size((1023, 1537))

        self.assertFalse(any(item["code"] == "panel_image_size_mismatch" for item in result["issues"]))
        self.assertTrue(any(item["code"] == "panel_image_size_variance" for item in result["warnings"]))

    def test_larger_size_variance_is_issue(self):
        result = self.check_size((1022, 1538))

        self.assertTrue(any(item["code"] == "panel_image_size_mismatch" for item in result["issues"]))


if __name__ == "__main__":
    unittest.main()
