import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DockerRuntimeTest(unittest.TestCase):
    def test_console_image_installs_powershell_alias(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("packages.microsoft.com", dockerfile)
        self.assertIn("apt-get install", dockerfile)
        self.assertIn("powershell", dockerfile)
        self.assertIn("/usr/local/bin/powershell", dockerfile)


if __name__ == "__main__":
    unittest.main()
