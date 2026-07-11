import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class _ComfyHandler(BaseHTTPRequestHandler):
    response = {}
    received = None

    def do_GET(self):
        body = json.dumps(type(self).response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        type(self).received = json.loads(self.rfile.read(length))
        body = json.dumps({"prompt_id": "test-prompt"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def powershell_command():
    return shutil.which("pwsh") or shutil.which("powershell")


class PowerShellConfigTest(unittest.TestCase):
    def test_config_script_honors_config_path_and_environment_overrides(self):
        script = (ROOT / "scripts" / "comic_pipeline_config.ps1").read_text(encoding="utf-8")

        self.assertIn("COMIC_PIPELINE_CONFIG_PATH", script)
        self.assertIn("Get-ComicEnvValue", script)
        self.assertIn("$envValue", script)
        self.assertIn("COMIC_PIPELINE_IMAGE_QUALITY", script)

    @unittest.skipUnless(powershell_command(), "PowerShell is not installed")
    def test_wait_script_exits_on_comfy_error(self):
        prompt_id = "failed-prompt"
        _ComfyHandler.response = {
            prompt_id: {
                "status": {
                    "status_str": "error",
                    "completed": False,
                    "messages": [["execution_error", {"exception_message": "missing key"}]],
                }
            }
        }
        server = ThreadingHTTPServer(("127.0.0.1", 0), _ComfyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [powershell_command(), "-NoProfile", "-File", str(ROOT / "scripts" / "wait_comfy_prompt.ps1"),
                 "-PromptId", prompt_id, "-ComfyUrl", f"http://127.0.0.1:{server.server_port}",
                 "-PollSeconds", "0", "-MaxPolls", "1"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "missing key")

    @unittest.skipUnless(powershell_command(), "PowerShell is not installed")
    def test_submit_script_mirrors_key_into_comfy_root(self):
        _ComfyHandler.response = {}
        _ComfyHandler.received = None
        server = ThreadingHTTPServer(("127.0.0.1", 0), _ComfyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                comfy_root = root / "comfy"
                comfy_root.mkdir()
                key_path = root / "image.env"
                key_path.write_text("OPENAI_API_KEY=test-secret\nOPENAI_BASE_URL=https://example.test\n", encoding="utf-8")
                config_path = root / ".env"
                config_path.write_text(
                    f"COMIC_PIPELINE_WORKSPACE={ROOT}\n"
                    f"COMIC_PIPELINE_COMFY_ROOT={comfy_root}\n"
                    f"COMIC_PIPELINE_COMFY_URL=http://127.0.0.1:{server.server_port}\n"
                    f"COMIC_PIPELINE_IMAGE_ENV_PATH={key_path}\n",
                    encoding="utf-8",
                )
                workflow_path = root / "workflow.json"
                workflow_path.write_text(json.dumps({
                    "prompt": {
                        "1": {
                            "class_type": "OpenAICompatibleImageGenerate",
                            "inputs": {"prompt": "test", "model": "test", "size": "1024x1024", "api_key": "remove-me"},
                        }
                    }
                }), encoding="utf-8")
                env = os.environ.copy()
                env["COMIC_PIPELINE_CONFIG_PATH"] = str(config_path)
                env["COMIC_PIPELINE_WORKSPACE"] = str(ROOT)
                env["COMIC_PIPELINE_COMFY_ROOT"] = str(comfy_root)
                env["COMIC_PIPELINE_COMFY_URL"] = f"http://127.0.0.1:{server.server_port}"
                env["COMIC_PIPELINE_IMAGE_ENV_PATH"] = str(key_path)
                result = subprocess.run(
                    [powershell_command(), "-NoProfile", "-File", str(ROOT / "scripts" / "submit_image_workflow.ps1"),
                     "-WorkflowPath", str(workflow_path)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=env,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                mirrored = comfy_root / ".comic-pipeline" / "image.env"
                self.assertEqual(mirrored.read_text(encoding="utf-8-sig"), key_path.read_text(encoding="utf-8"))
                inputs = _ComfyHandler.received["prompt"]["1"]["inputs"]
                self.assertEqual(inputs["api_key_env_path"], ".comic-pipeline/image.env")
                self.assertNotIn("api_key", inputs)
        finally:
            server.shutdown()
            server.server_close()

    @unittest.skipUnless(powershell_command(), "PowerShell is not installed")
    def test_single_panel_page_plan_fills_the_canvas(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            episode_path = root / "episode.json"
            result_path = root / "result.json"
            episode_path.write_text(json.dumps({
                "project": "测试",
                "source": "测试",
                "episode_id": "TEST_EP01",
                "page_defaults": {"width": 1600, "height": 2400, "gutter": 36, "reading_order": "left-to-right"},
                "asset_aliases": {},
                "style_bible": "",
                "character_cards": [],
                "global_prompt_block": "",
                "negative_prompt": "",
                "pages": [{
                    "page_id": "TEST_EP01_P001",
                    "title": "第一页",
                    "panels": [{"title": "主视觉", "prompt": "完整画面提示词", "reference_alias": "主角", "dialogue": []}],
                }],
            }, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [powershell_command(), "-NoProfile", "-File", str(ROOT / "scripts" / "create_comic_page_plans.ps1"),
                 "-EpisodePlanPath", str(episode_path), "-OutputDir", str(root), "-ResultPath", str(result_path),
                 "-OverwriteExisting"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads((root / "test_ep01_p001_plan.json").read_text(encoding="utf-8-sig"))

        self.assertEqual(plan["layout_style"], "single_splash")
        self.assertEqual(plan["panels"][0]["reference_alias"], "主角")
        self.assertEqual(plan["panels"][0]["layout"], {
            "x": 0, "y": 0, "w": 1600, "h": 2400,
            "role": "full_page_splash", "shot_type": "full_page",
            "shape": "rect", "border": 0, "render_order": 1,
        })


if __name__ == "__main__":
    unittest.main()
