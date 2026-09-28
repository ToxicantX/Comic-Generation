import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "console" / "server.py"
PATH_ENVIRONMENT_KEYS = {
    "COMIC_PIPELINE_RESOURCE_ROOT",
    "COMIC_PIPELINE_DATA_ROOT",
    "COMIC_PIPELINE_CONFIG_PATH",
    "COMIC_PIPELINE_TEXT_ENV_PATH",
    "COMIC_PIPELINE_IMAGE_ENV_PATH",
    "COMIC_PIPELINE_MANIFEST_DIR",
    "COMIC_PIPELINE_PROJECTS_DIR",
    "COMIC_PIPELINE_NOVELS_DIR",
    "COMIC_PIPELINE_BACKUPS_DIR",
    "COMIC_PIPELINE_LOG_DIR",
    "COMIC_PIPELINE_GENERATED_WORKFLOWS_DIR",
    "COMIC_PIPELINE_OUTPUT_ROOT",
    "COMIC_PIPELINE_COMFY_OUTPUT_ROOT",
    "COMIC_PIPELINE_NOVEL_PATH",
}


def import_server_paths(overrides=None, cwd=None):
    environment = os.environ.copy()
    for key in PATH_ENVIRONMENT_KEYS:
        environment.pop(key, None)
    environment.update(overrides or {})
    script = f"""
import importlib.util
import json
import sys
from pathlib import Path

server_path = Path({str(SERVER_PATH)!r})
sys.path.insert(0, str(server_path.parent))
spec = importlib.util.spec_from_file_location("desktop_runtime_path_test", server_path)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
print(json.dumps({{
    "resource_root": str(server.RESOURCE_ROOT),
    "data_root": str(server.DATA_ROOT),
    "scripts": str(server.SCRIPTS_DIR),
    "static": str(server.STATIC_DIR),
    "workflow_templates": str(server.WORKFLOW_TEMPLATES_DIR),
    "config": str(server.CONFIG_PATH),
    "text_env": str(server.TEXT_ENV_PATH),
    "image_env": str(server.IMAGE_ENV_PATH),
    "manifests": str(server.MANIFESTS_DIR),
    "projects": str(server.PROJECT_MANIFESTS_ROOT),
    "novels": str(server.NOVELS_DIR),
    "backups": str(server.BACKUPS_DIR),
    "logs": str(server.LOG_DIR),
    "generated_workflows": str(server.GENERATED_WORKFLOWS_DIR),
    "generated_assets": str(server.GENERATED_ASSET_WORKFLOW_DIR),
    "workflow_probe": str(server.workflow_path_for_panel("DESKTOP_RUNTIME_PATH_TEST") or ""),
    "output": server.DEFAULTS["COMIC_PIPELINE_OUTPUT_ROOT"],
    "comfy_output": server.DEFAULTS["COMIC_PIPELINE_COMFY_OUTPUT_ROOT"],
    "default_novel": server.DEFAULTS["COMIC_PIPELINE_NOVEL_PATH"],
}}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return json.loads(completed.stdout)


class DesktopRuntimePathsTest(unittest.TestCase):
    def test_default_paths_keep_repository_layout(self):
        paths = import_server_paths()

        self.assertEqual(Path(paths["resource_root"]), ROOT)
        self.assertEqual(Path(paths["data_root"]), ROOT)
        self.assertEqual(Path(paths["scripts"]), ROOT / "scripts")
        self.assertEqual(Path(paths["static"]), ROOT / "console" / "static")
        self.assertEqual(Path(paths["workflow_templates"]), ROOT / "workflows" / "comic")
        self.assertEqual(Path(paths["config"]), ROOT / "config" / ".env")
        self.assertEqual(Path(paths["text_env"]), ROOT / "config" / "text.env")
        self.assertEqual(Path(paths["image_env"]), ROOT / "config" / "image.env")
        self.assertEqual(Path(paths["manifests"]), ROOT / "manifests")
        self.assertEqual(Path(paths["projects"]), ROOT / "manifests" / "projects")
        self.assertEqual(Path(paths["novels"]), ROOT / "novels")
        self.assertEqual(Path(paths["backups"]), ROOT / "backups")
        self.assertEqual(Path(paths["logs"]), ROOT / "logs")
        self.assertEqual(Path(paths["generated_workflows"]), ROOT / "workflows" / "comic")
        self.assertEqual(Path(paths["generated_assets"]), ROOT / "workflows" / "comic" / "generated_assets")
        self.assertEqual(paths["workflow_probe"], "")
        self.assertEqual(Path(paths["output"]), ROOT / "output" / "ComicPipeline")
        self.assertEqual(Path(paths["comfy_output"]), ROOT / "output")
        self.assertEqual(Path(paths["default_novel"]), ROOT / "novel.txt")

    def test_environment_overrides_import_with_separate_user_data_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "user-data"
            explicit = {
                "COMIC_PIPELINE_RESOURCE_ROOT": str(ROOT),
                "COMIC_PIPELINE_DATA_ROOT": str(data_root),
                "COMIC_PIPELINE_CONFIG_PATH": str(data_root / "settings" / ".env"),
                "COMIC_PIPELINE_TEXT_ENV_PATH": str(data_root / "settings" / "text.env"),
                "COMIC_PIPELINE_IMAGE_ENV_PATH": str(data_root / "settings" / "image.env"),
                "COMIC_PIPELINE_MANIFEST_DIR": str(data_root / "manifests"),
                "COMIC_PIPELINE_PROJECTS_DIR": str(data_root / "projects"),
                "COMIC_PIPELINE_NOVELS_DIR": str(data_root / "novels"),
                "COMIC_PIPELINE_BACKUPS_DIR": str(data_root / "backups"),
                "COMIC_PIPELINE_LOG_DIR": str(data_root / "logs"),
                "COMIC_PIPELINE_GENERATED_WORKFLOWS_DIR": str(data_root / "generated-workflows"),
                "COMIC_PIPELINE_OUTPUT_ROOT": str(data_root / "output"),
                "COMIC_PIPELINE_COMFY_OUTPUT_ROOT": str(data_root / "comfy-output"),
                "COMIC_PIPELINE_NOVEL_PATH": str(data_root / "novels" / "active.txt"),
            }
            generated_workflows = Path(explicit["COMIC_PIPELINE_GENERATED_WORKFLOWS_DIR"])
            generated_workflows.mkdir(parents=True)
            workflow_probe = generated_workflows / "desktop_runtime_path_test_fallback_v001.json"
            workflow_probe.write_text("{}", encoding="utf-8")
            paths = import_server_paths(explicit, cwd=temp_dir)

        self.assertEqual(Path(paths["resource_root"]), ROOT)
        self.assertEqual(Path(paths["scripts"]), ROOT / "scripts")
        self.assertEqual(Path(paths["static"]), ROOT / "console" / "static")
        self.assertEqual(Path(paths["workflow_templates"]), ROOT / "workflows" / "comic")
        self.assertEqual(Path(paths["data_root"]), data_root)
        self.assertEqual(Path(paths["config"]), data_root / "settings" / ".env")
        self.assertEqual(Path(paths["text_env"]), data_root / "settings" / "text.env")
        self.assertEqual(Path(paths["image_env"]), data_root / "settings" / "image.env")
        self.assertEqual(Path(paths["manifests"]), data_root / "manifests")
        self.assertEqual(Path(paths["projects"]), data_root / "projects")
        self.assertEqual(Path(paths["novels"]), data_root / "novels")
        self.assertEqual(Path(paths["backups"]), data_root / "backups")
        self.assertEqual(Path(paths["logs"]), data_root / "logs")
        self.assertEqual(Path(paths["generated_workflows"]), data_root / "generated-workflows")
        self.assertEqual(Path(paths["generated_assets"]), data_root / "generated-workflows" / "generated_assets")
        self.assertEqual(Path(paths["workflow_probe"]), workflow_probe)
        self.assertEqual(Path(paths["output"]), data_root / "output")
        self.assertEqual(Path(paths["comfy_output"]), data_root / "comfy-output")
        self.assertEqual(Path(paths["default_novel"]), data_root / "novels" / "active.txt")


if __name__ == "__main__":
    unittest.main()
