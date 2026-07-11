import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "scripts" / "build_comic_consistency_qa.py"
    spec = importlib.util.spec_from_file_location("build_comic_consistency_qa", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConsistencyQaTest(unittest.TestCase):
    def test_no_text_instruction_accepts_current_bilingual_prompts(self):
        module = load_module()

        self.assertTrue(module.has_no_text_instruction("do not render text inside the image"))
        self.assertTrue(module.has_no_text_instruction("电影感构图，无画面内文字，无水印"))

    def test_output_prefix_matches_host_and_container_paths(self):
        module = load_module()
        prefix = "ComicPipeline/panels/TEST_EP01_P001_PANEL01_v001"

        self.assertTrue(module.output_matches_prefix(
            "/comfyui/output/ComicPipeline/panels/TEST_EP01_P001_PANEL01_v001_00001_.png",
            prefix,
        ))
        self.assertTrue(module.output_matches_prefix(
            r"G:\ComfyUI\output\ComicPipeline\panels\TEST_EP01_P001_PANEL01_v001_00001_.png",
            prefix,
        ))
        self.assertFalse(module.output_matches_prefix(
            "/comfyui/output/ComicPipeline/panels/OTHER_00001_.png",
            prefix,
        ))


if __name__ == "__main__":
    unittest.main()
