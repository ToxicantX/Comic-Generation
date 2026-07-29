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

    def test_default_compose_has_no_comfyui_mount_or_port_dependency(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertNotIn("G:/ComfyUI", compose)
        self.assertNotIn("host.docker.internal:8188", compose)
        self.assertIn("./output:/app/output", compose)
        self.assertIn("COMIC_PIPELINE_OUTPUT_ROOT: /app/output/ComicPipeline", compose)

    def test_optional_compose_override_mounts_host_comfyui(self):
        override = (ROOT / "docker-compose.comfyui.yml").read_text(encoding="utf-8")

        self.assertIn("COMIC_PIPELINE_HOST_COMFY_ROOT", override)
        self.assertIn("COMIC_PIPELINE_HOST_COMFY_ROOT:-G:/ComfyUI", override)
        self.assertIn(":/comfyui", override)
        self.assertIn("COMIC_PIPELINE_COMFY_OUTPUT_ROOT: /comfyui/output", override)
        self.assertIn("COMIC_PIPELINE_OUTPUT_ROOT: /comfyui/output/ComicPipeline", override)
        self.assertNotIn("/output:/app/output", override)

    def test_docker_start_script_only_autostarts_comfyui_when_selected(self):
        script = (ROOT / "start_docker.ps1").read_text(encoding="utf-8")

        self.assertIn('ValidateSet("direct_api", "comfyui")', script)
        self.assertIn('$ImageBackend = "direct_api"', script)
        self.assertIn("SkipGenerationBackend", script)
        self.assertIn("Start-GenerationBackend", script)
        self.assertIn("Start-Process", script)
        self.assertIn("Generation backend ready", script)
        self.assertIn('$ImageBackend -eq "comfyui"', script)
        self.assertIn('$containerOutputRoot = if ($ImageBackend -eq "comfyui")', script)

    def test_local_console_start_is_backend_aware(self):
        script = (ROOT / "start_console.ps1").read_text(encoding="utf-8")

        self.assertIn("COMIC_PIPELINE_IMAGE_BACKEND", script)
        self.assertIn('if ($imageBackend -ne "comfyui")', script)


if __name__ == "__main__":
    unittest.main()
