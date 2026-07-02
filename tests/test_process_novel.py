import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "process_novel.py"


def load_process_novel_module():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("process_novel_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProcessNovelTest(unittest.TestCase):
    def test_attach_chapter_excerpts_uses_text_between_chapter_headings(self):
        module = load_process_novel_module()
        lines = [
            "搜神记",
            "第一卷",
            "第一章 神农使者",
            "神农使者来到大荒。",
            "少年拓拔野与蚩尤同行。",
            "第二章 谪仙人",
            "姑射仙子立于云端。",
        ]
        chapter_index = module.build_chapter_index(lines, "搜神记")

        module.attach_chapter_excerpts(chapter_index, lines, max_chars=80)

        chapters = [item for item in chapter_index if item.get("type") == "chapter"]
        self.assertIn("拓拔野", chapters[0]["excerpt"])
        self.assertIn("蚩尤", chapters[0]["excerpt"])
        self.assertNotIn("姑射仙子", chapters[0]["excerpt"])
        self.assertIn("姑射仙子", chapters[1]["excerpt"])


if __name__ == "__main__":
    unittest.main()
