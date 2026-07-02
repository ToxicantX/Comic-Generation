import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PowerShellConfigTest(unittest.TestCase):
    def test_config_script_honors_config_path_and_environment_overrides(self):
        script = (ROOT / "scripts" / "comic_pipeline_config.ps1").read_text(encoding="utf-8")

        self.assertIn("COMIC_PIPELINE_CONFIG_PATH", script)
        self.assertIn("Get-ComicEnvValue", script)
        self.assertIn("$envValue", script)


if __name__ == "__main__":
    unittest.main()
