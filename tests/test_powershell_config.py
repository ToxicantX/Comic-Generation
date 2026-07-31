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
        self.assertIn("COMIC_PIPELINE_IMAGE_BACKEND", script)
        self.assertIn("COMIC_PIPELINE_COMFY_CHECKPOINT", script)
        self.assertIn("COMIC_PIPELINE_COMFY_CONTROLNET_NAME", script)

    def test_configure_defaults_to_direct_api_and_local_output(self):
        script = (ROOT / "configure.ps1").read_text(encoding="utf-8")

        self.assertIn('ValidateSet("direct_api", "comfyui")', script)
        self.assertIn('$ImageBackend = "direct_api"', script)
        self.assertIn("COMIC_PIPELINE_IMAGE_BACKEND=$ImageBackend", script)
        self.assertIn('Join-Path $root "output"', script)
        self.assertIn("COMIC_PIPELINE_OUTPUT_ROOT=$(Join-Path $imageOutputRoot 'ComicPipeline')", script)
        self.assertIn("COMIC_PIPELINE_COMFY_CHECKPOINT=$ComfyCheckpoint", script)

    @unittest.skipUnless(powershell_command(), "PowerShell is not installed")
    def test_local_panel_workflow_uses_shared_template_and_controlnet_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            comfy_root = root / "comfy"
            reference = root / "reference.png"
            reference.write_bytes(b"fake image")
            plan_path = root / "plan.json"
            workflow_dir = root / "workflows"
            result_path = root / "result.json"
            config_path = root / "config.env"
            plan_path.write_text(json.dumps({
                "project": "测试",
                "episode_id": "TEST_EP01",
                "page_id": "TEST_EP01_P001",
                "global_prompt_block": "中国神话幻想漫画，无画面内文字",
                "negative_prompt": "text, watermark",
                "panels": [{
                    "panel_id": "TEST_EP01_P001_PANEL01",
                    "order": 1,
                    "prompt": "主角站在山巅",
                    "reference_image": str(reference),
                    "reference_alias": "主角",
                    "filename_prefix": "ComicPipeline/panels/test_panel",
                }],
            }, ensure_ascii=False), encoding="utf-8")
            config_path.write_text(
                "\n".join([
                    f"COMIC_PIPELINE_WORKSPACE={ROOT}",
                    "COMIC_PIPELINE_IMAGE_BACKEND=comfyui",
                    f"COMIC_PIPELINE_COMFY_ROOT={comfy_root}",
                    f"COMIC_PIPELINE_COMFY_OUTPUT_ROOT={root / 'output'}",
                    "COMIC_PIPELINE_COMFY_CHECKPOINT=checkpoint.safetensors",
                    "COMIC_PIPELINE_COMFY_LORA_NAME=style.safetensors",
                    "COMIC_PIPELINE_COMFY_LORA_STRENGTH_MODEL=0.8",
                    "COMIC_PIPELINE_COMFY_LORA_STRENGTH_CLIP=0.6",
                    "COMIC_PIPELINE_COMFY_CONTROLNET_NAME=lineart.pth",
                    "COMIC_PIPELINE_COMFY_CONTROLNET_STRENGTH=0.7",
                    "COMIC_PIPELINE_COMFY_CONTROLNET_START=0.1",
                    "COMIC_PIPELINE_COMFY_CONTROLNET_END=0.9",
                    "COMIC_PIPELINE_COMFY_STEPS=24",
                    "COMIC_PIPELINE_COMFY_CFG=6.5",
                    "COMIC_PIPELINE_COMFY_SAMPLER=dpmpp_2m",
                    "COMIC_PIPELINE_COMFY_SCHEDULER=karras",
                    "COMIC_PIPELINE_PYTHON_PATH=python",
                ]) + "\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update({
                "COMIC_PIPELINE_CONFIG_PATH": str(config_path),
                "COMIC_PIPELINE_WORKSPACE": str(ROOT),
            })
            result = subprocess.run(
                [powershell_command(), "-NoProfile", "-File", str(ROOT / "scripts" / "create_comic_panel_workflows.ps1"),
                 "-PlanPath", str(plan_path), "-WorkflowDir", str(workflow_dir), "-ResultPath", str(result_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            workflow_path = workflow_dir / "test_ep01_p001_panel01_image_v001.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8-sig"))
            graph = workflow["prompt"]
            self.assertEqual(graph["1"]["class_type"], "CheckpointLoaderSimple")
            self.assertEqual(graph["2"]["class_type"], "LoraLoader")
            self.assertEqual(graph["7"]["class_type"], "ControlNetLoader")
            self.assertEqual(graph["9"]["inputs"]["steps"], 24)
            self.assertEqual(graph["9"]["inputs"]["cfg"], 6.5)
            copied = comfy_root / "input" / "comic_pipeline" / "test_ep01_p001_panel01_reference.png"
            self.assertTrue(copied.is_file())
            manifest = json.loads(result_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(manifest["created"][0]["image_backend"], "comfyui")

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
