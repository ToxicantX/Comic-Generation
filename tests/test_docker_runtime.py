import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DockerRuntimeTest(unittest.TestCase):
    def test_console_image_installs_powershell_alias(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("packages.microsoft.com", dockerfile)
        self.assertIn("apt-get install", dockerfile)
        self.assertIn("powershell", dockerfile)
        self.assertIn("fonts-noto-cjk", dockerfile)
        self.assertIn("/usr/local/bin/powershell", dockerfile)

    def test_docker_start_script_autostarts_host_generation_backend(self):
        script = (ROOT / "start_docker.ps1").read_text(encoding="utf-8")

        self.assertIn("SkipGenerationBackend", script)
        self.assertIn("Start-GenerationBackend", script)
        self.assertIn("Start-Process", script)
        self.assertIn("Generation backend ready", script)


if __name__ == "__main__":
    unittest.main()
