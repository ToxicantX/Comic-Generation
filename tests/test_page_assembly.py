import importlib.util
import unittest
from pathlib import Path

from PIL import ImageFont


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "scripts" / "build_comic_page_from_panels.py"
    spec = importlib.util.spec_from_file_location("comic_test_page_assembly", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PageAssemblyTest(unittest.TestCase):
    def test_caption_cleanup_preserves_noun_ending_in_dao(self):
        module = load_module()
        caption = "晨光越过海面时，他知道自己此后要守住这条雾中航道。"

        self.assertEqual(module.cleanup_caption_text(caption), caption.rstrip("。"))

    def test_default_font_can_be_measured_without_reopening_memory_resource(self):
        module = load_module()
        font = ImageFont.load_default()

        height = module.measure_text_box_height("测试对白排版", font, 320)

        self.assertGreater(height, 0)


if __name__ == "__main__":
    unittest.main()
