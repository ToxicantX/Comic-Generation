import importlib.util
import hashlib
import io
import json
import os
import sys
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "console" / "server.py"


def load_server_module():
    sys.path.insert(0, str(ROOT / "console"))
    spec = importlib.util.spec_from_file_location("comic_console_server_test", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeConfigTest(unittest.TestCase):
    def test_database_url_uses_global_runtime_config(self):
        server = load_server_module()

        with patch.object(server, "runtime_config", return_value={
            "COMIC_PIPELINE_DATABASE_URL": "postgresql://db.example/comics",
        }):
            self.assertEqual(server.database_url(), "postgresql://db.example/comics")

    def test_image_workflow_command_defaults_to_direct_api(self):
        server = load_server_module()
        config = {
            "COMIC_PIPELINE_IMAGE_BACKEND": "direct_api",
            "COMIC_PIPELINE_PYTHON_PATH": "python-direct",
            "COMIC_PIPELINE_IMAGE_ENV_PATH": "/config/image.env",
        }

        with patch.object(server, "effective_config", return_value=config):
            backend, command = server.image_workflow_command(
                {"slug": "test"},
                Path("workflow.json"),
                Path("panel.png"),
                Path("result.json"),
                "PANEL01",
            )

        self.assertEqual(backend, "direct_api")
        self.assertEqual(command[0], "python-direct")
        self.assertIn(str(server.IMAGE_PROVIDER_SCRIPT), command)
        self.assertEqual(command[command.index("--output-path") + 1], "panel.png")
        self.assertNotIn("8188", " ".join(command))

    def test_image_workflow_command_keeps_comfyui_runner(self):
        server = load_server_module()
        config = {"COMIC_PIPELINE_IMAGE_BACKEND": "comfyui"}

        with patch.object(server, "effective_config", return_value=config):
            backend, command = server.image_workflow_command(
                {"slug": "test"},
                Path("workflow.json"),
                Path("panel.png"),
                Path("result.json"),
                "PANEL01",
                poll_seconds=9,
                max_polls=12,
            )

        self.assertEqual(backend, "comfyui")
        self.assertIn(str(server.RUN_IMAGE_WORKFLOW_SCRIPT), command)
        self.assertEqual(command[command.index("-PollSeconds") + 1], "9")
        self.assertEqual(command[command.index("-MaxPolls") + 1], "12")

    def test_runtime_workflow_converts_legacy_direct_graph_to_current_comfyui_template(self):
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "legacy.json"
            source_path.write_text(json.dumps({
                "client_id": "legacy",
                "prompt": {
                    "1": {
                        "class_type": "OpenAICompatibleImageGenerate",
                        "inputs": {
                            "prompt": "approved panel prompt",
                            "negative_prompt": "text, watermark",
                            "size": "1536x1024",
                        },
                    },
                    "2": {
                        "class_type": "SaveImage",
                        "inputs": {"images": ["1", 0], "filename_prefix": "ComicPipeline/panels/TEST_PANEL_v001"},
                    },
                },
            }), encoding="utf-8")
            config = {
                **server.DEFAULTS,
                "COMIC_PIPELINE_IMAGE_BACKEND": "comfyui",
                "COMIC_PIPELINE_COMFY_CHECKPOINT": "comic.safetensors",
                "COMIC_PIPELINE_COMFY_STEPS": "17",
            }
            context = {"settings": [{"type": "character", "name": "主角", "visual_prompt": "red coat"}]}

            with patch.object(server, "effective_config", return_value=config):
                with patch.object(server, "project_manifest_dir", return_value=root / "manifests"):
                    with patch.object(server.os, "urandom", return_value=(123).to_bytes(8, "big")):
                        runtime_path = server.prepare_runtime_workflow(
                            source_path,
                            {"slug": "test"},
                            context,
                            "job-1",
                            "TEST_PANEL",
                        )

            workflow = json.loads(runtime_path.read_text(encoding="utf-8"))
            graph = workflow["prompt"]
            self.assertEqual(graph["1"]["class_type"], "CheckpointLoaderSimple")
            self.assertEqual(graph["1"]["inputs"]["ckpt_name"], "comic.safetensors")
            self.assertEqual(graph["5"]["inputs"], {"width": 1536, "height": 1024, "batch_size": 1})
            self.assertEqual(graph["9"]["inputs"]["steps"], 17)
            self.assertEqual(graph["9"]["inputs"]["seed"], 123)
            self.assertIn("approved panel prompt", graph["3"]["inputs"]["text"])
            self.assertIn("[生成上下文]", graph["3"]["inputs"]["text"])
            self.assertNotIn("OpenAICompatibleImageGenerate", {node["class_type"] for node in graph.values()})

    def test_runtime_workflow_converts_local_graph_back_to_direct_api(self):
        server = load_server_module()
        local = server.build_local_image_workflow(
            prompt="local panel prompt",
            negative_prompt="bad anatomy",
            filename_prefix="ComicPipeline/panels/TEST_PANEL_v001",
            checkpoint="old.safetensors",
            image_size="1024x1536",
            seed=42,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "local.json"
            source_path.write_text(json.dumps(local), encoding="utf-8")
            config = {
                **server.DEFAULTS,
                "COMIC_PIPELINE_IMAGE_BACKEND": "direct_api",
                "COMIC_PIPELINE_IMAGE_MODEL": "gpt-image-test",
                "COMIC_PIPELINE_IMAGE_QUALITY": "high",
            }

            with patch.object(server, "effective_config", return_value=config):
                with patch.object(server, "project_manifest_dir", return_value=root / "manifests"):
                    runtime_path = server.prepare_runtime_workflow(
                        source_path,
                        {"slug": "test"},
                        {},
                        "job-2",
                        "TEST_PANEL",
                    )

            workflow = json.loads(runtime_path.read_text(encoding="utf-8"))
            graph = workflow["prompt"]
            self.assertEqual(graph["1"]["class_type"], "OpenAICompatibleImageGenerate")
            self.assertEqual(graph["1"]["inputs"]["prompt"], "local panel prompt")
            self.assertEqual(graph["1"]["inputs"]["negative_prompt"], "bad anatomy")
            self.assertEqual(graph["1"]["inputs"]["size"], "1024x1536")
            self.assertEqual(graph["1"]["inputs"]["model"], "gpt-image-test")
            self.assertEqual(graph["1"]["inputs"]["quality"], "high")

    def test_direct_image_workflow_command_rejects_empty_output_path(self):
        server = load_server_module()
        config = {"COMIC_PIPELINE_IMAGE_BACKEND": "direct_api"}

        with patch.object(server, "effective_config", return_value=config):
            with self.assertRaisesRegex(ValueError, "output path"):
                server.image_workflow_command(
                    {"slug": "test"},
                    Path("workflow.json"),
                    Path(""),
                    Path("result.json"),
                    "PANEL01",
                )

    def test_direct_api_health_does_not_probe_comfyui(self):
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_env = root / "image.env"
            image_env.write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")
            config = {
                **server.DEFAULTS,
                "COMIC_PIPELINE_IMAGE_BACKEND": "direct_api",
                "COMIC_PIPELINE_IMAGE_ENV_PATH": str(image_env),
                "COMIC_PIPELINE_OUTPUT_ROOT": str(root / "output"),
            }

            with patch.object(server, "config_snapshot", return_value={"config": config}):
                with patch.object(server, "active_project", side_effect=ValueError("no project")):
                    with patch.object(server.db, "status", return_value={"schema_ready": True}):
                        with patch.object(server.urllib.request, "urlopen") as urlopen:
                            health = server.comfy_health()

        self.assertTrue(health["ok"])
        self.assertEqual(health["image_backend"], "direct_api")
        self.assertEqual(health["checks"], {})
        self.assertTrue(health["paths"]["output_root"]["exists"])
        urlopen.assert_not_called()

    def test_direct_api_status_does_not_publish_comfyui_preview_urls(self):
        server = load_server_module()
        config = {
            **server.DEFAULTS,
            "COMIC_PIPELINE_IMAGE_BACKEND": "direct_api",
            "COMIC_PIPELINE_COMFY_URL": "http://127.0.0.1:8188",
        }

        with patch.object(server, "config_snapshot", return_value={"config": config}):
            preview = server.preview_paths(3)

        self.assertEqual(preview["backend"], "direct_api")
        self.assertEqual(preview["latest_file"], "")
        self.assertEqual(preview["episode_file"], "")
        self.assertEqual(preview["latest_url"], "")
        self.assertEqual(preview["episode_url"], "")

    def test_direct_api_media_does_not_publish_comfyui_view_url(self):
        server = load_server_module()

        with patch.object(server, "runtime_config", return_value={
            "COMIC_PIPELINE_IMAGE_BACKEND": "direct_api",
            "COMIC_PIPELINE_COMFY_URL": "http://127.0.0.1:8188",
        }):
            url = server.comfy_view_url(ROOT / "output" / "panel.png")

        self.assertEqual(url, "")

    def test_connection_failure_diagnostic_is_backend_neutral(self):
        server = load_server_module()

        issue = server.classify_generation_issue("connection refused")

        self.assertEqual(issue["type"], "backend_unreachable")
        self.assertIn("当前后端", issue["message"])
        self.assertNotIn("检查 ComfyUI 是否运行", issue["message"])

    def test_direct_api_agent_findings_hide_optional_comfyui_paths(self):
        server = load_server_module()
        health = {
            "image_backend": "direct_api",
            "paths": {
                "root": {"path": "/app", "exists": True},
                "output_root": {"path": "/app/output", "exists": True},
                "comfy_root": {"path": "/comfyui", "exists": False},
                "comfy_output_root": {"path": "/comfyui/output", "exists": False},
            },
            "image_api_key_configured": True,
        }

        findings = server.agent_health_findings(health)
        labels = {item["label"] for item in findings}

        self.assertNotIn("ComfyUI 根目录", labels)
        self.assertNotIn("ComfyUI 输出目录", labels)
        self.assertIn("输出目录", labels)

    def test_health_summary_keeps_image_backend_independent_from_database(self):
        server = load_server_module()
        health = {
            "ok": False,
            "image_backend": "direct_api",
            "generation_ready": True,
            "checks": {},
            "database": {"schema_ready": False, "error": "database unavailable"},
            "text_api_key_configured": True,
            "image_api_key_configured": True,
        }
        settings = {
            "image_backend": "direct_api",
            "models": {
                "novel_model": "text-model",
                "image_model": "image-model",
                "sources": {},
            },
            "paths": {"output_root": str(ROOT), "sources": {}},
        }

        with patch.object(server, "comfy_health", return_value=health):
            with patch.object(server, "settings_summary", return_value=settings):
                with patch.object(server, "example_consistency_checks", return_value=[]):
                    result = server.health_check_summary()

        checks = {item["name"]: item for item in result["checks"]}
        self.assertFalse(checks["postgres"]["ok"])
        self.assertTrue(checks["image_backend"]["ok"])
        self.assertIn("直连 API", checks["image_backend"]["message"])

    def test_comfyui_health_does_not_require_cloud_image_credentials(self):
        server = load_server_module()
        health = {
            "ok": True,
            "image_backend": "comfyui",
            "generation_ready": True,
            "checks": {"root": {"ok": True}},
            "database": {"schema_ready": True},
            "text_api_key_configured": True,
            "image_api_key_configured": False,
        }
        settings = {
            "image_backend": "comfyui",
            "models": {
                "novel_model": "text-model",
                "image_model": "",
                "sources": {},
            },
            "paths": {"output_root": str(ROOT), "sources": {}},
        }

        with patch.object(server, "comfy_health", return_value=health):
            with patch.object(server, "settings_summary", return_value=settings):
                with patch.object(server, "example_consistency_checks", return_value=[]):
                    result = server.health_check_summary()

        checks = {item["name"]: item for item in result["checks"]}
        self.assertTrue(checks["image_api_key"]["ok"])
        self.assertTrue(checks["image_model"]["ok"])
        self.assertTrue(result["ok"])

    def test_comfyui_health_requires_shared_output_mount(self):
        server = load_server_module()

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = {
                **server.DEFAULTS,
                "COMIC_PIPELINE_IMAGE_BACKEND": "comfyui",
                "COMIC_PIPELINE_COMFY_ROOT": str(root / "missing-comfyui"),
                "COMIC_PIPELINE_COMFY_OUTPUT_ROOT": str(root / "missing-output"),
            }
            with patch.object(server, "config_snapshot", return_value={"config": config}):
                with patch.object(server, "active_project", side_effect=ValueError("no project")):
                    with patch.object(server.db, "status", return_value={"schema_ready": True}):
                        with patch.object(server.urllib.request, "urlopen", return_value=Response()):
                            health = server.comfy_health()

        self.assertTrue(all(item["ok"] for item in health["checks"].values()))
        self.assertFalse(health["paths"]["comfy_root"]["exists"])
        self.assertFalse(health["paths"]["comfy_output_root"]["exists"])
        self.assertFalse(health["generation_ready"])
        self.assertFalse(health["ok"])

    def test_local_model_catalog_checks_nodes_and_selected_models(self):
        server = load_server_module()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                nodes = {
                    name: {"input": {"required": {field: [[value]]}}}
                    for name, field, value in [
                        ("CheckpointLoaderSimple", "ckpt_name", "comic.safetensors"),
                        ("LoraLoader", "lora_name", "style.safetensors"),
                        ("ControlNetLoader", "control_net_name", "lineart.pth"),
                    ]
                }
                nodes.update({name: {} for name in [
                    "CLIPTextEncode", "EmptyLatentImage", "KSampler", "VAEDecode", "SaveImage",
                    "LoadImage", "ControlNetApplyAdvanced",
                ]})
                return json.dumps(nodes).encode("utf-8")

        config = {
            "COMIC_PIPELINE_COMFY_CHECKPOINT": "comic.safetensors",
            "COMIC_PIPELINE_COMFY_LORA_NAME": "style.safetensors",
            "COMIC_PIPELINE_COMFY_CONTROLNET_NAME": "lineart.pth",
        }
        with patch.object(server.urllib.request, "urlopen", return_value=Response()):
            catalog = server.local_model_catalog("http://127.0.0.1:8188", config)

        self.assertTrue(catalog["ok"])
        self.assertEqual(catalog["missing_nodes"], [])
        self.assertEqual(catalog["missing_models"], [])

    def test_save_config_rejects_unknown_image_backend_before_writing(self):
        server = load_server_module()

        with patch.object(server, "config_snapshot", return_value={"config": dict(server.DEFAULTS)}):
            with patch.object(server, "write_env") as write_env:
                with self.assertRaisesRegex(ValueError, "direct_api.*comfyui"):
                    server.save_config({
                        "config": {"COMIC_PIPELINE_IMAGE_BACKEND": "automatic"},
                    })

        write_env.assert_not_called()

    def test_episode_skeleton_uses_planned_panel_count(self):
        server = load_server_module()
        project = {"slug": "test", "title": "测试项目"}

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "episode02.json"
            with patch.object(server, "project_episode_record", return_value={
                "chapter_number": 2,
                "title": "第二章",
                "planned_pages": 1,
                "planned_panels": 1,
            }):
                with patch.object(server, "project_chapter_record", return_value={}):
                    server.create_episode_skeleton_plan(project, 2, target, pages=1)

            plan = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(len(plan["pages"]), 1)
        self.assertEqual(len(plan["pages"][0]["panels"]), 1)

    def test_read_env_returns_empty_config_when_file_is_missing(self):
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "config" / ".env"
            self.assertEqual(server.read_env(missing), {})

    def test_runtime_config_overrides_file_values_with_environment(self):
        server = load_server_module()

        with patch.object(server, "read_env", return_value={
            "COMIC_PIPELINE_DATABASE_URL": "postgresql://file-host/db",
            "COMIC_PIPELINE_COMFY_URL": "http://file-host:8188",
        }):
            with patch.dict(os.environ, {
                "COMIC_PIPELINE_DATABASE_URL": "postgresql://env-host/db",
            }, clear=False):
                config = server.runtime_config()

        self.assertEqual(config["COMIC_PIPELINE_DATABASE_URL"], "postgresql://env-host/db")
        self.assertEqual(config["COMIC_PIPELINE_COMFY_URL"], "http://file-host:8188")

    def test_save_config_writes_text_and_image_credentials_separately(self):
        server = load_server_module()
        writes = {}

        def fake_read_env(path):
            path = Path(path)
            if path.name == ".env":
                return {
                    "COMIC_PIPELINE_IMAGE_ENV_PATH": "/tmp/image.env",
                    "COMIC_PIPELINE_TEXT_ENV_PATH": "/tmp/text.env",
                }
            if path.name == "image.env":
                return {"OPENAI_API_KEY": "old-image", "OPENAI_BASE_URL": "https://image.old"}
            if path.name == "text.env":
                return {"OPENAI_API_KEY": "old-text", "OPENAI_BASE_URL": "https://text.old"}
            return {}

        def fake_write_env(path, values, keys):
            writes[Path(path).name] = {key: values.get(key, "") for key in keys}

        with patch.object(server, "CONFIG_PATH", Path("/tmp/.env")):
            with patch.object(server, "read_env", side_effect=fake_read_env):
                with patch.object(server, "write_env", side_effect=fake_write_env):
                    with patch.object(Path, "is_file", return_value=True):
                        with patch.object(Path, "read_bytes", return_value=b""):
                            with patch.object(server.db, "status", return_value={"schema_ready": True}):
                                with patch.object(server, "active_project_slug", return_value="ssj"):
                                    with patch.object(server, "read_projects", return_value=[]):
                                        server.save_config({
                                            "config": {
                                                "COMIC_PIPELINE_TEXT_ENV_PATH": "/tmp/text.env",
                                                "COMIC_PIPELINE_IMAGE_ENV_PATH": "/tmp/image.env",
                                            },
                                            "text": {
                                                "OPENAI_BASE_URL": "https://text.new",
                                                "OPENAI_API_KEY": "new-text",
                                            },
                                            "image": {
                                                "OPENAI_BASE_URL": "https://image.new",
                                                "OPENAI_API_KEY": "new-image",
                                            },
                                        })

        self.assertEqual(writes["text.env"]["OPENAI_API_KEY"], "new-text")
        self.assertEqual(writes["text.env"]["OPENAI_BASE_URL"], "https://text.new")
        self.assertEqual(writes["image.env"]["OPENAI_API_KEY"], "new-image")
        self.assertEqual(writes["image.env"]["OPENAI_BASE_URL"], "https://image.new")

    def test_image_model_test_is_dry_run_by_default(self):
        server = load_server_module()
        health = {
            "ok": True,
            "checks": {
                "object_info": {"ok": True},
            },
            "image_api_key_configured": True,
        }
        settings = {
            "models": {"image_model": "gpt-image-2"},
            "endpoints": {"image_base_url": "https://image.example"},
        }
        config = {"text_env_path": "/tmp/text.env", "image_env_path": "/tmp/image.env"}

        with patch.object(server, "comfy_health", return_value=health):
            with patch.object(server, "settings_summary", return_value=settings):
                with patch.object(server, "config_snapshot", return_value=config):
                    result = server.test_model_api({"target": "image"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["target"], "image")
        self.assertTrue(result["dry_run"])
        self.assertIn("不生成图片", result["message"])

    def test_direct_image_model_test_does_not_require_comfyui_checks(self):
        server = load_server_module()
        health = {
            "ok": True,
            "image_backend": "direct_api",
            "generation_ready": True,
            "checks": {},
            "image_api_key_configured": True,
        }
        settings = {
            "image_backend": "direct_api",
            "models": {"image_model": "gpt-image-2"},
            "endpoints": {"image_base_url": "https://image.example/v1"},
        }
        config = {"text_env_path": "/tmp/text.env", "image_env_path": "/tmp/image.env"}

        with patch.object(server, "comfy_health", return_value=health):
            with patch.object(server, "settings_summary", return_value=settings):
                with patch.object(server, "config_snapshot", return_value=config):
                    result = server.test_model_api({"target": "image"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertNotIn("ComfyUI", result["message"])

    def test_comfyui_local_model_test_does_not_require_cloud_model_config(self):
        server = load_server_module()
        health = {
            "ok": True,
            "image_backend": "comfyui",
            "generation_ready": True,
            "checks": {"object_info": {"ok": True}},
            "image_api_key_configured": False,
        }
        settings = {
            "image_backend": "comfyui",
            "models": {"image_model": ""},
            "endpoints": {"image_base_url": ""},
        }
        config = {"text_env_path": "/tmp/text.env", "image_env_path": "/tmp/image.env"}

        with patch.object(server, "comfy_health", return_value=health):
            with patch.object(server, "settings_summary", return_value=settings):
                with patch.object(server, "config_snapshot", return_value=config):
                    result = server.test_model_api({"target": "image", "live": True})

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertIn("本地模型", result["message"])

    def test_generation_backend_ready_accepts_comfyui_without_cloud_key(self):
        server = load_server_module()

        self.assertTrue(server.generation_backend_ready({
            "ok": True,
            "image_backend": "comfyui",
            "generation_ready": True,
            "image_api_key_configured": False,
        }))
        self.assertFalse(server.generation_backend_ready({
            "ok": False,
            "image_backend": "direct_api",
            "generation_ready": False,
            "image_api_key_configured": False,
        }))

    def test_dashboard_does_not_flag_missing_cloud_key_for_comfyui_local_models(self):
        server = load_server_module()
        health = {
            "ok": True,
            "image_backend": "comfyui",
            "generation_ready": True,
            "image_api_key_configured": False,
        }

        with patch.object(server.db, "dashboard_pending_outputs", return_value=[]):
            with patch.object(server.db, "dashboard_active_approval", return_value=None):
                with patch.object(server.db, "dashboard_pending_settings", return_value=[]):
                    todos = server.dashboard_todos({"slug": "test", "title": "测试"}, health, [])

        self.assertFalse(any(item.get("id") == "system-preflight" for item in todos))

    def test_image_model_live_test_calls_business_api(self):
        server = load_server_module()
        health = {
            "ok": True,
            "checks": {"object_info": {"ok": True}},
            "image_api_key_configured": True,
            "comfy_url": "http://127.0.0.1:8188",
        }
        settings = {
            "models": {"image_model": "gpt-image-2"},
            "endpoints": {"image_base_url": "https://image.example"},
        }
        config = {"text_env_path": "/tmp/text.env", "image_env_path": "/tmp/image.env"}

        with patch.object(server, "comfy_health", return_value=health):
            with patch.object(server, "settings_summary", return_value=settings):
                with patch.object(server, "config_snapshot", return_value=config):
                    with patch.object(server, "call_image_model_test", return_value={
                        "ok": True,
                        "elapsed_seconds": 2.5,
                        "generates_image": True,
                        "saved": False,
                    }) as call_image:
                        result = server.test_model_api({"target": "image", "live": True, "timeout": 180})

        self.assertTrue(result["ok"])
        self.assertFalse(result["dry_run"])
        self.assertTrue(result["detail"]["generates_image"])
        self.assertFalse(result["detail"]["saved"])
        call_image.assert_called_once_with("gpt-image-2", "https://image.example", "/tmp/image.env", timeout=180)

    def test_image_model_business_call_sends_application_user_agent(self):
        server = load_server_module()

        class Response:
            status = 200

            def read(self):
                return b'{"data":[{"url":"https://image.example/test.png"}]}'

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        with tempfile.TemporaryDirectory() as temp_dir:
            image_env = Path(temp_dir) / "image.env"
            image_env.write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")
            with patch.object(server.urllib.request, "urlopen", return_value=Response()) as urlopen:
                result = server.call_image_model_test(
                    "gpt-image-2",
                    "https://image.example/v1/images/generations",
                    str(image_env),
                    timeout=30,
                )

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://image.example/v1/images/generations")
        self.assertEqual(request.get_header("User-agent"), "ComicPipeline/2.0")
        self.assertTrue(result["generates_image"])

    def test_text_model_test_requires_text_key(self):
        server = load_server_module()
        health = {"text_api_key_configured": False}
        settings = {
            "models": {"novel_model": "gpt-5.4"},
            "endpoints": {"text_base_url": "https://text.example"},
        }
        config = {"text_env_path": "/tmp/text.env", "image_env_path": "/tmp/image.env"}

        with patch.object(server, "comfy_health", return_value=health):
            with patch.object(server, "settings_summary", return_value=settings):
                with patch.object(server, "config_snapshot", return_value=config):
                    result = server.test_model_api({"target": "text"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["target"], "text")
        self.assertIn("小说处理 API Key", result["message"])

    def test_runtime_config_includes_text_timeout_and_streaming(self):
        server = load_server_module()

        with patch.object(server, "read_env", return_value={}):
            config = server.runtime_config()

        self.assertIn("COMIC_PIPELINE_TEXT_MODEL_TIMEOUT", config)
        self.assertIn("COMIC_PIPELINE_TEXT_MODEL_STREAM", config)
        self.assertEqual(config["COMIC_PIPELINE_TEXT_MODEL_TIMEOUT"], "300")
        self.assertEqual(config["COMIC_PIPELINE_TEXT_MODEL_STREAM"], "true")

    def test_attach_import_summary_refreshes_stale_summary_from_result(self):
        server = load_server_module()
        job = {
            "stage": "process_novel",
            "project_slug": "ssj",
            "project_title": "搜神记",
            "import_summary": {
                "text_model_used": False,
                "text_model_error": "The read operation timed out",
            },
            "result": {
                "ok": True,
                "project_slug": "ssj",
                "project_title": "搜神记",
                "chapters": 138,
                "episodes": 138,
                "skeletons": [],
                "text_model": {
                    "configured": True,
                    "model": "gpt-5.4",
                    "used": True,
                    "error": "",
                },
            },
        }

        refreshed = server.attach_import_summary(job)

        self.assertTrue(refreshed["import_summary"]["text_model_used"])
        self.assertEqual(refreshed["import_summary"]["text_model_error"], "")

    def test_run_job_marks_start_failure_as_failed(self):
        server = load_server_module()
        job_id = "missing-command-job"
        server.JOBS.clear()
        server.JOB_PROCESSES.clear()
        server.JOBS[job_id] = {
            "id": job_id,
            "stage": "breakdown",
            "label": "AI 拆解",
            "status": "running",
            "started": "2026-07-01T00:00:00",
            "finished": "",
            "command": ["missing-command-for-test"],
            "result_path": "/tmp/missing-command-result.json",
            "project_slug": "ssj",
            "progress": {"total": 1, "completed": 0, "failed": 0, "current": "AI 拆解"},
        }

        with patch.object(server, "project_by_slug", return_value={"slug": "ssj", "project_config": {}, "manifest_dir": "/tmp"}):
            with patch.object(server, "effective_config", return_value=server.DEFAULTS.copy()):
                with patch.object(server, "runtime_config", return_value=server.DEFAULTS.copy()):
                    with patch.object(server, "project_manifest_dir", return_value=Path("/tmp")):
                        with patch.object(server.db, "save_job"):
                            with patch.object(server, "run_job_process", side_effect=FileNotFoundError("missing-command-for-test")):
                                server.run_job(job_id)

        self.assertEqual(server.JOBS[job_id]["status"], "failed")
        self.assertEqual(server.JOBS[job_id]["exit_code"], 127)
        self.assertIn("启动失败", server.JOBS[job_id]["stderr_tail"])

    def test_start_job_persists_project_and_retry_payload_before_launch(self):
        server = load_server_module()
        server.JOBS.clear()
        project = {
            "slug": "demo",
            "novel_path": "/tmp/demo.txt",
            "manifest_dir": "/tmp/demo",
            "project_config": {},
        }

        with patch.object(server, "assert_stage_allowed"):
            with patch.object(server, "active_project", return_value=project):
                with patch.object(server, "project_episode_plan_path", return_value=Path("/tmp/episode.json")):
                    with patch.object(server, "project_manifest_dir", return_value=Path("/tmp/demo")):
                        with patch.object(server.db, "save_job") as save_job:
                            with patch.object(server.threading, "Thread") as thread:
                                job = server.start_job({
                                    "stage": "status",
                                    "episode_number": 2,
                                    "pages": 4,
                                    "max_panels": 1,
                                    "max_pages": 1,
                                })

        self.assertEqual(job["project_slug"], "demo")
        self.assertEqual(job["retry_payload"]["stage"], "status")
        self.assertEqual(job["retry_payload"]["episode_number"], 2)
        save_job.assert_called_once()
        thread.return_value.start.assert_called_once()

    def test_retry_job_dispatches_saved_stage_payload(self):
        server = load_server_module()
        source = {
            "id": "failed-job",
            "stage": "status",
            "status": "failed",
            "project_slug": "ssj",
            "retry_payload": {"stage": "status", "episode_number": 3},
        }

        with patch.object(server, "recent_jobs", return_value=[source]):
            with patch.object(server, "active_project", return_value={"slug": "ssj"}):
                with patch.object(server, "start_job", return_value={"id": "new-job"}) as start_job:
                    result = server.retry_job_api("failed-job")

        self.assertEqual(result["id"], "new-job")
        payload = start_job.call_args.args[0]
        self.assertEqual(payload["episode_number"], 3)
        self.assertEqual(payload["retried_from"], "failed-job")

    def test_retry_completed_asset_job_only_reconciles_output(self):
        server = load_server_module()
        job = {
            "id": "asset-job",
            "stage": "asset_regenerate",
            "status": "failed",
            "exit_code": 0,
            "project_slug": "ssj",
            "retry_payload": {"asset_id": 12},
        }
        project = {"slug": "ssj"}
        with patch.object(server, "recent_jobs", return_value=[job]):
            with patch.object(server, "active_project", return_value=project):
                with patch.object(server, "project_by_slug", return_value=project):
                    with patch.object(server, "complete_asset_regeneration", return_value={"asset": {"id": 12}}) as reconcile:
                        with patch.object(server.db, "save_job") as save_job:
                            with patch.object(server, "start_regenerate_job") as regenerate:
                                result = server.retry_job_api("asset-job")

        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["result"]["reconciled"])
        reconcile.assert_called_once()
        save_job.assert_called_once()
        regenerate.assert_not_called()

    def test_retry_job_rejects_cross_project_execution(self):
        server = load_server_module()
        source = {
            "id": "other-project-job",
            "stage": "status",
            "status": "failed",
            "project_slug": "other",
            "retry_payload": {"stage": "status", "episode_number": 1},
        }

        with patch.object(server, "recent_jobs", return_value=[source]):
            with patch.object(server, "active_project", return_value={"slug": "ssj"}):
                with self.assertRaisesRegex(ValueError, "切换到该任务所属小说"):
                    server.retry_job_api("other-project-job")

    def test_close_reading_requires_approved_global_settings(self):
        server = load_server_module()

        with patch.object(server, "active_project", return_value={"slug": "ssj", "manifest_dir": "/tmp"}):
            with patch.object(server, "project_episode_plan_path", return_value=SERVER_PATH):
                with patch.object(server, "config_snapshot", return_value={"config": {"COMIC_PIPELINE_TEXT_MODEL": "gpt-5.4"}}):
                    with patch.object(server.db, "list_setting_items", return_value=[]):
                        with patch.object(server.db, "list_visual_assets", return_value=[]):
                            with self.assertRaisesRegex(ValueError, "全局设定"):
                                server.assert_stage_allowed("close_reading", 1)

    def test_close_reading_requires_approved_global_visual_assets(self):
        server = load_server_module()
        settings = [{
            "id": 1,
            "item_type": "character",
            "name": "神农",
            "review_status": "approved",
            "locked": True,
        }]

        with patch.object(server, "active_project", return_value={"slug": "ssj", "manifest_dir": "/tmp"}):
            with patch.object(server, "project_episode_plan_path", return_value=SERVER_PATH):
                with patch.object(server, "config_snapshot", return_value={"config": {"COMIC_PIPELINE_TEXT_MODEL": "gpt-5.4"}}):
                    with patch.object(server.db, "list_setting_items", return_value=settings):
                        with patch.object(server.db, "list_visual_assets", return_value=[]):
                            with self.assertRaisesRegex(ValueError, "全局素材"):
                                server.assert_stage_allowed("close_reading", 1)

    def test_close_reading_allows_approved_global_settings_and_assets(self):
        server = load_server_module()
        settings = [{"review_status": "approved", "locked": True}]
        assets = [{"review_status": "approved", "locked": True}]

        with patch.object(server, "active_project", return_value={"slug": "ssj", "manifest_dir": "/tmp"}):
            with patch.object(server, "project_episode_plan_path", return_value=SERVER_PATH):
                with patch.object(server, "config_snapshot", return_value={"config": {"COMIC_PIPELINE_TEXT_MODEL": "gpt-5.4"}}):
                    with patch.object(server.db, "list_setting_items", return_value=settings):
                        with patch.object(server.db, "list_visual_assets", return_value=assets):
                            server.assert_stage_allowed("close_reading", 1)

    def test_draft_approval_rejects_skeleton_pages_before_close_reading(self):
        server = load_server_module()
        detail = {
            "pages": [{
                "page_id": "EP01_P001",
                "status": "skeleton_needs_close_reading",
                "summary": "初始页面骨架，需要细读。",
                "panels": [{"title": "待细读", "prompt": "待细读：第一格"}],
            }],
            "media": {"summary": {}},
        }

        with patch.object(server, "episode_detail", return_value=detail):
            with patch.object(server, "status_snapshot", return_value={}):
                with self.assertRaisesRegex(ValueError, "细读"):
                    server.assert_approval_allowed(1, "draft", server.default_approval_state())

    def test_agent_recommends_close_reading_before_draft_approval(self):
        server = load_server_module()
        detail = {
            "pages": [{
                "page_id": "EP01_P001",
                "status": "skeleton_needs_close_reading",
                "summary": "初始页面骨架，需要细读。",
                "panels": [{"title": "待细读", "prompt": "待细读：第一格"}],
            }],
            "assets": {"total_assets": 1},
            "media": {"summary": {}},
        }

        with patch.object(server, "active_project", return_value={"slug": "ssj"}):
            with patch.object(server, "global_asset_readiness", return_value={
                "ok": True,
                "approved_settings": 1,
                "approved_assets": 1,
                "message": "",
            }):
                with patch.object(server, "chapter_asset_coverage", return_value={"ok": True, "message": ""}):
                    with patch.object(server, "generated_output_quality_status", return_value={}):
                        with patch.object(server, "generated_output_review_blockers", return_value={"count": 0}):
                            recommendation = server.agent_recommendation(
                                1,
                                {"ok": True, "image_api_key_configured": True},
                                detail,
                                {},
                                server.default_approval_state(),
                            )

        self.assertEqual(recommendation["stage"], "close_reading")
        self.assertFalse(recommendation["requires_approval"])

    def test_agent_final_episode_has_no_next_episode_action(self):
        server = load_server_module()
        detail = {
            "pages": [{"page_id": "EP02_P001", "status": "complete", "panels": [{}]}],
            "assets": {"total_assets": 1},
            "media": {"summary": {
                "pages_total": 1,
                "pages_ready": 1,
                "real_pages_ready": 1,
                "panels_total": 1,
                "panels_ready": 1,
            }},
        }
        approvals = {key: True for key in server.default_approval_state() if key != "updated"}

        with patch.object(server, "active_project", return_value={"slug": "test"}):
            with patch.object(server, "global_asset_readiness", return_value={"ok": True}):
                with patch.object(server, "chapter_asset_coverage", return_value={"ok": True, "message": ""}):
                    with patch.object(server, "generated_output_quality_status", return_value={"quality_failed": 0, "quality_missing": 0}):
                        with patch.object(server, "generated_output_review_blockers", return_value={"count": 0}):
                            with patch.object(server, "next_episode_number", return_value=0):
                                recommendation = server.agent_recommendation(
                                    2,
                                    {"ok": True, "image_api_key_configured": True},
                                    detail,
                                    {"texts": {"image_health_qa_md": "ready"}},
                                    approvals,
                                )

        self.assertEqual(recommendation["state"], "complete")
        self.assertEqual(recommendation["gate"], "")
        self.assertFalse(recommendation["requires_approval"])
        self.assertEqual(recommendation["action_label"], "")

    def test_episode_pages_preserve_close_reading_director_fields(self):
        server = load_server_module()
        director = {
            "page_rhythm": "铺垫-冲突-悬念",
            "emotional_arc": "平静到紧张",
            "layout_style": "diagonal_action",
            "visual_priority": "主角拔刀",
            "lettering_strategy": "对白靠上，页尾留悬念",
            "page_turn_hook": "黑影逼近",
            "camera_flow": ["远景到特写"],
        }
        plan = {
            "pages": [{
                "page_id": "EP01_P001",
                "title": "遭遇",
                "status": "close_reading_refined_needs_review",
                "summary": "主角在荒原遭遇神秘来客。",
                "director": director,
                "layout_style": "diagonal_action",
                "reading_flow": "从左上进入主视觉",
                "visual_priority": "主角拔刀",
                "close_reading_required": False,
                "close_reading_refined": True,
                "panels": [{
                    "panel_id": "EP01_P001_PANEL01",
                    "title": "拔刀",
                    "prompt": "少年拔刀迎敌",
                    "panel_role": "动作",
                    "shot_type": "中景",
                    "visual_priority": "铜刀出鞘",
                    "camera_direction": "由左向右",
                }],
            }],
        }

        with patch.object(server, "plan_path_for_page", return_value=Path("/tmp/page-plan.json")):
            with patch.object(server, "workflow_path_for_panel", return_value=None):
                pages = server.episode_pages_from_plan(
                    {"slug": "ssj"},
                    1,
                    plan,
                    {"pages": [], "panels": []},
                )

        self.assertEqual(pages[0]["director"], director)
        self.assertTrue(pages[0]["close_reading_refined"])
        self.assertEqual(pages[0]["panels"][0]["panel_role"], "动作")
        self.assertEqual(pages[0]["panels"][0]["camera_direction"], "由左向右")

    def test_breakdown_page_edits_update_director_and_panel_fields(self):
        server = load_server_module()
        plan = {
            "pages": [{
                "page_id": "DEMO_EP01_P001",
                "status": "close_reading_refined_needs_review",
                "summary": "原摘要",
                "director": {"page_rhythm": "原节奏"},
                "panels": [{
                    "panel_id": "DEMO_EP01_P001_PANEL01",
                    "title": "原标题",
                    "prompt": "原提示",
                }],
            }],
        }

        updated = server.apply_breakdown_page_edits(plan, [{
            "page_id": "DEMO_EP01_P001",
            "summary": "新摘要",
            "layout_style": "diagonal_action",
            "director": {
                "page_rhythm": "先静后动",
                "camera_flow": "全景；中景；近景",
            },
            "panels": [{
                "panel_id": "DEMO_EP01_P001_PANEL01",
                "title": "新标题",
                "prompt": "新提示",
                "shot_type": "近景",
            }],
        }])

        page = updated["pages"][0]
        panel = page["panels"][0]
        self.assertEqual(page["summary"], "新摘要")
        self.assertEqual(page["director"]["page_rhythm"], "先静后动")
        self.assertEqual(page["director"]["camera_flow"], ["全景", "中景", "近景"])
        self.assertEqual(page["status"], "close_reading_refined_needs_review")
        self.assertTrue(page["close_reading_refined"])
        self.assertEqual(panel["title"], "新标题")
        self.assertEqual(panel["prompt"], "新提示")
        self.assertEqual(panel["shot_type"], "近景")
        self.assertTrue(panel["close_reading_refined"])

    def test_next_episode_approval_requires_qa(self):
        server = load_server_module()
        detail = {"pages": [], "media": {"summary": {}}}

        with patch.object(server, "episode_detail", return_value=detail):
            with patch.object(server, "status_snapshot", return_value={}):
                with self.assertRaisesRegex(ValueError, "QA"):
                    server.assert_approval_allowed(1, "next_episode", server.default_approval_state())

    def test_next_episode_approval_is_allowed_after_qa(self):
        server = load_server_module()
        detail = {"pages": [], "media": {"summary": {}}}
        approvals = {**server.default_approval_state(), "qa": True}

        with patch.object(server, "episode_detail", return_value=detail):
            with patch.object(server, "status_snapshot", return_value={}):
                with patch.object(server, "next_episode_number", return_value=2):
                    server.assert_approval_allowed(1, "next_episode", approvals)

    def test_revoking_draft_approval_cascades_to_downstream_gates(self):
        server = load_server_module()
        saved = {}
        current = {
            "EP01": {
                "draft": True,
                "assets": True,
                "generation": True,
                "qa": True,
                "next_episode": True,
            },
        }

        with patch.object(server, "load_agent_approvals", return_value=current):
            with patch.object(server, "approval_key", return_value="EP01"):
                with patch.object(server, "save_agent_approvals", side_effect=lambda value: saved.update(value)):
                    with patch.object(server, "sync_gate_side_effects"):
                        result = server.set_episode_approval_gate(1, "draft", False)

        self.assertFalse(result["draft"])
        self.assertFalse(result["assets"])
        self.assertFalse(result["generation"])
        self.assertFalse(result["qa"])
        self.assertFalse(result["next_episode"])
        self.assertEqual(saved["EP01"], result)

    def test_sync_assets_creates_candidates_from_approved_global_settings(self):
        server = load_server_module()
        setting = {
            "id": 7,
            "item_type": "character",
            "name": "神农",
            "description": "大荒神帝，慈悲而威严。",
            "first_chapter_number": 1,
            "chapter_numbers": [1, 2],
            "visual_prompt": "白发神农，古代神话服饰，温和威严，角色设定图。",
            "negative_prompt": "modern city, text",
            "review_status": "approved",
            "locked": True,
            "raw": {"source": "test"},
        }
        saved_payloads = []

        def fake_upsert(_database_url, slug, asset):
            saved_payloads.append(asset)
            return {**asset, "id": len(saved_payloads), "project_slug": slug}

        with patch.object(server, "active_project", return_value={"slug": "ssj", "title": "搜神记"}):
            with patch.object(server, "episode_assets", return_value={"categories": {}, "total_assets": 0, "labels": {}}):
                with patch.object(server, "output_root", return_value=Path("/tmp/comic-output")):
                    with patch.object(server.db, "list_setting_items", return_value=[setting]):
                        with patch.object(server.db, "list_visual_assets", return_value=[]):
                            with patch.object(server.db, "upsert_visual_asset", side_effect=fake_upsert):
                                with patch.object(server.db, "add_review"):
                                    with patch.object(server, "attach_asset_db_state", side_effect=lambda _project, assets: assets):
                                        result = server.sync_assets_api({"episode_number": 1})

        self.assertTrue(result["ok"])
        self.assertEqual(result["setting_candidates_created"], 1)
        self.assertEqual(len(saved_payloads), 1)
        self.assertEqual(saved_payloads[0]["setting_item_id"], 7)
        self.assertEqual(saved_payloads[0]["asset_type"], "characters")
        self.assertEqual(saved_payloads[0]["title"], "神农")
        self.assertEqual(saved_payloads[0]["review_status"], "pending_review")
        self.assertIn("approved_setting", saved_payloads[0]["raw"]["source"])

    def test_setting_visual_asset_paths_are_unique_for_chinese_names(self):
        server = load_server_module()
        project = {"slug": "ssj", "title": "搜神记"}
        settings = [
            {"id": 1, "item_type": "location", "name": "第一卷", "review_status": "approved"},
            {"id": 2, "item_type": "location", "name": "第二卷", "review_status": "approved"},
        ]

        with patch.object(server, "output_root", return_value=Path("/tmp/comic-output")):
            paths = [
                server.setting_to_visual_asset_payload(project, setting)["file_path"]
                for setting in settings
            ]

        self.assertEqual(len(set(paths)), 2)
        self.assertIn("setting_1", paths[0])
        self.assertIn("setting_2", paths[1])

    def test_chapter_setting_references_are_inferred_from_text_and_chapter(self):
        server = load_server_module()
        settings = [
            {"id": 1, "name": "拓拔野", "aliases": ["小野"], "chapter_numbers": [], "item_type": "character"},
            {"id": 2, "name": "玉屏山", "aliases": [], "chapter_numbers": [3], "item_type": "location"},
            {"id": 3, "name": "无关人物", "aliases": [], "chapter_numbers": [8], "item_type": "character"},
        ]
        pages = [{
            "summary": "拓拔野夜闯庭院。",
            "source_excerpt": "小野抬头望向山巅。",
            "panels": [{"prompt": "少年在月色下拔剑"}],
        }]

        result = server.infer_referenced_setting_ids(3, pages, settings)

        self.assertEqual(result, [1, 2])

    def test_chapter_asset_coverage_blocks_missing_core_asset(self):
        server = load_server_module()
        project = {"slug": "ssj"}
        settings = [{
            "id": 1,
            "name": "拓拔野",
            "item_type": "character",
            "importance": "core",
            "review_status": "approved",
            "locked": True,
            "chapter_numbers": [3],
        }]
        coverage = server.chapter_asset_coverage(
            project,
            3,
            pages=[{"summary": "拓拔野进入庭院。", "panels": []}],
            settings=settings,
            assets=[],
            breakdown={"referenced_setting_ids": [1]},
        )

        self.assertFalse(coverage["ok"])
        self.assertEqual(coverage["required_count"], 1)
        self.assertEqual(coverage["missing_assets"], ["拓拔野"])
        self.assertIn("核心素材", coverage["message"])

    def test_chapter_asset_coverage_accepts_approved_linked_file(self):
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_path = Path(temp_dir) / "tuobaye.png"
            asset_path.write_bytes(b"image")
            settings = [{
                "id": 1,
                "name": "拓拔野",
                "item_type": "character",
                "importance": "core",
                "review_status": "approved",
                "locked": True,
                "chapter_numbers": [3],
            }]
            assets = [{
                "id": 9,
                "setting_item_id": 1,
                "file_path": str(asset_path),
                "review_status": "approved",
                "locked": True,
            }]

            coverage = server.chapter_asset_coverage(
                {"slug": "ssj"},
                3,
                pages=[{"summary": "拓拔野进入庭院。", "panels": []}],
                settings=settings,
                assets=assets,
                breakdown={"referenced_setting_ids": [1]},
            )

        self.assertTrue(coverage["ok"])
        self.assertEqual(coverage["covered_count"], 1)

    def test_asset_workflow_uses_approved_setting_prompts(self):
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "output" / "hero_reference.png"
            with patch.object(server, "GENERATED_ASSET_WORKFLOW_DIR", root / "workflows"):
                with patch.object(server, "config_snapshot", return_value={"config": {
                    "COMIC_PIPELINE_IMAGE_MODEL": "test-image-model",
                    "COMIC_PIPELINE_IMAGE_ENV_PATH": str(root / "image.env"),
                }}):
                    with patch.object(server, "comfy_output_root", return_value=root / "output"):
                        workflow_path = server.create_asset_workflow(
                            "hero",
                            "characters",
                            target,
                            approved_prompt="青衣少年，腰悬铜刀，长发束起。",
                            approved_negative_prompt="现代服饰，短发",
                        )

            workflow = __import__("json").loads(workflow_path.read_text(encoding="utf-8"))
            inputs = workflow["prompt"]["1"]["inputs"]
            self.assertIn("青衣少年", inputs["prompt"])
            self.assertIn("腰悬铜刀", inputs["prompt"])
            self.assertIn("现代服饰", inputs["negative_prompt"])
            self.assertEqual(inputs["model"], "test-image-model")
            self.assertEqual(inputs["quality"], "auto")
            self.assertEqual(inputs["api_key_env_path"], ".comic-pipeline/image.env")

    def test_asset_workflow_paths_are_unique_for_chinese_aliases(self):
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(server, "GENERATED_ASSET_WORKFLOW_DIR", root / "workflows"):
                with patch.object(server, "config_snapshot", return_value={"config": {}}):
                    with patch.object(server, "comfy_output_root", return_value=root / "output"):
                        first = server.create_asset_workflow(
                            "白石灯塔", "world_scenes", root / "output" / "setting_95_reference.png"
                        )
                        second = server.create_asset_workflow(
                            "黄铜罗盘", "weapons", root / "output" / "setting_107_reference.png"
                        )

            self.assertNotEqual(first, second)
            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())

    def test_complete_asset_regeneration_uses_comfy_numbered_output(self):
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            generated = root / "assets" / "hero_reference_00001_.png"
            generated.parent.mkdir()
            generated.write_bytes(b"generated-image")
            current = {"id": 12, "project_slug": "ssj", "raw": {}}

            with patch.object(server, "comfy_output_root", return_value=root):
                with patch.object(server.db, "get_visual_asset", return_value=current):
                    with patch.object(server.db, "update_visual_asset", side_effect=lambda _url, _id, updates: {**current, **updates}) as update:
                        with patch.object(server.db, "add_review"):
                            server.complete_asset_regeneration({"slug": "ssj"}, {
                                "id": "asset-job-numbered",
                                "asset_id": 12,
                                "asset_path": str(root / "assets" / "hero_reference.png"),
                                "workflow_path": str(root / "missing-workflow.json"),
                            })

            self.assertEqual(update.call_args.args[2]["file_path"], str(generated))

    def test_asset_batch_rejects_more_than_twenty_assets(self):
        server = load_server_module()

        with self.assertRaisesRegex(ValueError, "最多选择 20 个"):
            server.start_asset_batch_job({"asset_ids": list(range(1, 22))})

    def test_asset_batch_aggregates_failed_children_for_retry(self):
        server = load_server_module()
        project = {"slug": "ssj", "title": "搜神记"}
        parent = {
            "id": "asset-batch-parent",
            "stage": "asset_batch",
            "project_slug": "ssj",
            "asset_ids": [11, 12],
            "status": "running",
            "progress": {"total": 2, "completed": 0, "failed": 0},
            "retry_payload": {"asset_ids": [11, 12], "episode_number": 3},
        }
        server.JOBS[parent["id"]] = parent

        def fake_start(payload):
            asset_id = int(payload["asset_id"])
            child_id = f"child-{asset_id}"
            server.JOBS[child_id] = {
                "id": child_id,
                "asset_id": asset_id,
                "status": "passed" if asset_id == 11 else "failed",
                "diagnostics": {"title": "图片接口失败"} if asset_id == 12 else {},
            }
            return server.JOBS[child_id]

        with patch.object(server, "project_by_slug", return_value=project):
            with patch.object(server, "start_asset_regenerate_job", side_effect=fake_start):
                with patch.object(server.db, "save_job"):
                    server.run_asset_batch_job(parent["id"])

        result = server.JOBS[parent["id"]]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["completed_asset_ids"], [11])
        self.assertEqual(result["failed_asset_ids"], [12])
        self.assertEqual(result["retry_payload"]["asset_ids"], [12])
        self.assertEqual(result["progress"]["completed"], 1)
        self.assertEqual(result["progress"]["failed"], 1)

    def test_asset_batch_child_uses_parent_project_slug(self):
        server = load_server_module()
        project = {"slug": "novel_a", "title": "小说 A"}
        parent = {
            "id": "asset-batch-project",
            "stage": "asset_batch",
            "project_slug": "novel_a",
            "asset_ids": [7],
            "episode_number": 2,
            "status": "running",
            "progress": {"total": 1, "completed": 0, "failed": 0},
            "retry_payload": {"asset_ids": [7], "episode_number": 2},
        }
        server.JOBS[parent["id"]] = parent
        payloads = []

        def fake_start(payload):
            payloads.append(payload)
            server.JOBS["child-7"] = {"id": "child-7", "asset_id": 7, "status": "passed"}
            return server.JOBS["child-7"]

        with patch.object(server, "project_by_slug", return_value=project):
            with patch.object(server, "start_asset_regenerate_job", side_effect=fake_start):
                with patch.object(server.db, "save_job"):
                    server.run_asset_batch_job(parent["id"])

        self.assertEqual(payloads[0]["project_slug"], "novel_a")
        self.assertEqual(payloads[0]["episode_number"], 2)

    def test_backup_archive_rejects_unsafe_member_paths(self):
        server = load_server_module()

        for name in ("../config/.env", "/absolute/file", "C:/secret.txt", "files\\..\\secret.txt"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "不安全路径"):
                    server.validate_backup_member_name(name)

    def test_backup_archive_rejects_checksum_mismatch(self):
        server = load_server_module()
        data_bytes = json.dumps({"project": {"slug": "source"}}, ensure_ascii=False).encode("utf-8")
        manifest = {
            "schema_version": 1,
            "source_project": {"slug": "source", "title": "源项目"},
            "checksums": {"data.json": hashlib.sha256(b"different").hexdigest()},
            "files": [],
        }
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            archive.writestr("data.json", data_bytes)

        with self.assertRaisesRegex(ValueError, "校验和不一致"):
            server.read_project_backup_archive(stream.getvalue())

    def test_backup_import_rejects_existing_target_slug_before_writing(self):
        server = load_server_module()

        with patch.object(server.db, "get_project", return_value={"slug": "existing"}):
            with self.assertRaisesRegex(ValueError, "已存在"):
                server.import_project_backup_api({
                    "target_slug": "existing",
                    "content_base64": "not-read-when-target-exists",
                })

    def test_generation_context_includes_review_feedback_for_regeneration(self):
        server = load_server_module()
        block = server.generation_context_prompt_block({
            "settings": [],
            "assets": [],
            "review_feedback": "角色面部与前页不一致，手部变形，需要保持青衣和铜刀。",
        })

        self.assertIn("本次重生成审核反馈", block)
        self.assertIn("角色面部与前页不一致", block)
        self.assertIn("保持青衣和铜刀", block)

    def test_generation_hydrates_asset_aliases_and_normalizes_ai_reference_text(self):
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path = root / "episode.json"
            character = root / "character.png"
            location = root / "location.png"
            character.write_bytes(b"character")
            location.write_bytes(b"location")
            plan_path.write_text(__import__("json").dumps({
                "pages": [{"panels": [{
                    "prompt": "暴雨中林舟站在白石灯塔内。",
                    "reference_alias": "角色参考：林舟；场景参考：白石灯塔",
                }]}]
            }), encoding="utf-8")
            context = {"assets": [
                {"id": 2, "type": "world_scenes", "title": "白石灯塔", "file_path": str(location)},
                {"id": 1, "type": "characters", "title": "林舟", "file_path": str(character)},
            ]}

            with patch.object(server, "project_episode_plan_path", return_value=plan_path):
                result = server.hydrate_episode_asset_aliases({"slug": "test"}, 1, context)

            saved = __import__("json").loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["asset_aliases"]["林舟"], str(character))
            self.assertEqual(saved["pages"][0]["panels"][0]["reference_alias"], "林舟")
            self.assertEqual(result["plan_path"], str(plan_path))

    def test_complete_asset_regeneration_returns_asset_to_review_with_version(self):
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "hero.png"
            target.write_bytes(b"generated-image")
            current = {
                "id": 12,
                "project_slug": "ssj",
                "source_job_id": "old-job",
                "review_status": "approved",
                "locked": True,
                "raw": {"regeneration_versions": [{"job_id": "old-job"}]},
            }
            updates_seen = []

            def fake_update(_database_url, _asset_id, updates):
                updates_seen.append(updates)
                return {**current, **updates}

            with patch.object(server.db, "get_visual_asset", return_value=current):
                with patch.object(server.db, "update_visual_asset", side_effect=fake_update):
                    with patch.object(server.db, "add_review") as add_review:
                        result = server.complete_asset_regeneration({"slug": "ssj"}, {
                            "id": "asset-job-2",
                            "stage": "asset_regenerate",
                            "asset_id": 12,
                            "asset_path": str(target),
                            "backup_path": str(Path(temp_dir) / "backup.png"),
                            "workflow_path": str(Path(temp_dir) / "workflow.json"),
                            "result_path": str(Path(temp_dir) / "result.json"),
                        })

            updates = updates_seen[0]
            self.assertEqual(updates["source_job_id"], "asset-job-2")
            self.assertEqual(updates["review_status"], "pending_review")
            self.assertFalse(updates["locked"])
            self.assertEqual(len(updates["raw"]["regeneration_versions"]), 2)
            self.assertEqual(result["version"]["job_id"], "asset-job-2")
            add_review.assert_called_once()

    def test_restore_asset_backup_keeps_version_and_restores_missing_target(self):
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup = root / "backups" / "hero.png"
            target = root / "hero.png"
            backup.parent.mkdir()
            backup.write_bytes(b"previous-image")

            restored = server.restore_asset_backup({
                "stage": "asset_regenerate",
                "backup_path": str(backup),
                "asset_path": str(target),
            })

            self.assertEqual(restored, str(target))
            self.assertEqual(target.read_bytes(), b"previous-image")
            self.assertTrue(backup.is_file())

    def test_restore_failed_panel_regeneration_keeps_version_backup(self):
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup = root / "backups" / "panel.png"
            target = root / "panel.png"
            backup.parent.mkdir()
            backup.write_bytes(b"previous-panel")

            restored = server.restore_job_backup({
                "stage": "regenerate",
                "backup_path": str(backup),
                "panel_path": str(target),
            })

            self.assertEqual(restored, str(target))
            self.assertEqual(target.read_bytes(), b"previous-panel")
            self.assertTrue(backup.is_file())

    def test_locking_pending_visual_asset_marks_it_approved(self):
        server = load_server_module()
        current = {
            "id": 2,
            "project_slug": "ssj",
            "locked": False,
            "review_status": "pending_review",
        }
        updates_seen = []

        def fake_update(_database_url, _asset_id, updates):
            updates_seen.append(updates)
            return {**current, **updates}

        with patch.object(server.db, "get_visual_asset", return_value=current):
            with patch.object(server.db, "update_visual_asset", side_effect=fake_update):
                with patch.object(server.db, "add_review"):
                    result = server.lock_asset_api(2, {"locked": True})

        self.assertTrue(result["ok"])
        self.assertEqual(updates_seen[0]["locked"], True)
        self.assertEqual(updates_seen[0]["review_status"], "approved")

    def test_output_needs_work_requires_specific_feedback(self):
        server = load_server_module()
        current = {"id": 3, "project_slug": "ssj", "metadata": {}}
        with patch.object(server, "ensure_database"):
            with patch.object(server.db, "get_generated_output", return_value=current):
                with self.assertRaisesRegex(ValueError, "必须填写具体问题"):
                    server.review_output_api(3, {"action": "needs_work", "comment": ""})

    def test_output_approval_requires_complete_quality_checks(self):
        server = load_server_module()
        current = {"id": 3, "project_slug": "ssj", "metadata": {}}
        with patch.object(server, "ensure_database"):
            with patch.object(server.db, "get_generated_output", return_value=current):
                with self.assertRaisesRegex(ValueError, "全部质量检查项"):
                    server.review_output_api(3, {
                        "action": "approve",
                        "quality_checks": [{"key": "character_consistency", "status": "pass"}],
                    })

    def test_editing_approved_setting_saves_and_requires_review_again(self):
        server = load_server_module()
        current = {
            "id": 9,
            "project_slug": "ssj",
            "item_type": "character",
            "name": "拓拔野",
            "aliases": [],
            "description": "已审核的主角设定。",
            "first_chapter_number": 1,
            "chapter_numbers": [1],
            "visual_prompt": "青衣少年。",
            "negative_prompt": "",
            "relations": {},
            "source_evidence": [],
            "importance": "core",
            "review_status": "approved",
            "locked": False,
            "raw": {"source": "manual"},
        }
        updates_seen = []

        def fake_update(_database_url, _setting_id, updates):
            updates_seen.append(updates)
            return {**current, **updates}

        with patch.object(server, "ensure_database"):
            with patch.object(server.db, "get_setting_item", return_value=current):
                with patch.object(server.db, "update_setting_item", side_effect=fake_update):
                    with patch.object(server.db, "add_review"):
                        result = server.update_setting_api(9, {
                            "description": "人工修订后的主角设定。",
                        })

        self.assertTrue(result["ok"])
        self.assertEqual(updates_seen[0]["description"], "人工修订后的主角设定。")
        self.assertEqual(updates_seen[0]["review_status"], "pending_review")
        self.assertFalse(updates_seen[0]["locked"])

    def test_setting_scan_extracts_character_candidates_from_chapter_text(self):
        server = load_server_module()
        project = {"slug": "ssj", "title": "搜神记"}
        chapters = [
            {
                "chapter_number": 1,
                "volume": "第一卷",
                "title": "第一章 神农使者",
                "raw": {
                    "excerpt": "神农使者来到大荒，少年拓拔野与蚩尤同行，遇见雨师妾。",
                },
            },
            {
                "chapter_number": 2,
                "volume": "第一卷",
                "title": "第二章 谪仙人",
                "raw": {
                    "summary": "拓拔野再次见到姑射仙子，神农使者暗中观察。",
                },
            },
        ]

        with patch.object(server.db, "list_chapters", return_value=chapters):
            candidates = server.scan_setting_candidates(project, limit=20)

        characters = [item for item in candidates if item.get("item_type") == "character"]
        names = {item.get("name") for item in characters}
        self.assertIn("神农使者", names)
        self.assertIn("拓拔野", names)
        self.assertIn("蚩尤", names)
        self.assertTrue(all(item.get("visual_prompt") for item in characters))
        self.assertTrue(all(item.get("source_evidence") for item in characters))

    def test_ai_setting_discovery_finds_unknown_character_and_prop_from_chapter_text(self):
        server = load_server_module()
        chapters = [{
            "chapter_number": 1,
            "volume": "白石灯塔",
            "title": "第一章 雨夜来客",
            "raw": {
                "excerpt": "二十八岁的守塔人林舟穿着深蓝防水长衣，左眉有浅疤。他拿起黄铜罗盘，罗盘盖上刻着白色浪纹。",
            },
        }]

        with patch.object(server, "runtime_config", return_value={
            "COMIC_PIPELINE_TEXT_MODEL": "configured-model",
            "COMIC_PIPELINE_TEXT_ENV_PATH": "/tmp/text.env",
            "COMIC_PIPELINE_TEXT_MODEL_TIMEOUT": "300",
            "COMIC_PIPELINE_TEXT_MODEL_STREAM": "true",
        }):
            with patch.object(server, "chat_json", return_value={
                "items": [
                    {"item_type": "character", "name": "林舟", "description": "成年守塔人", "visual_prompt": "二十八岁男性，深蓝防水长衣，左眉浅疤", "importance": "core"},
                    {"item_type": "prop", "name": "黄铜罗盘", "description": "刻有白色浪纹", "visual_prompt": "黄铜罗盘，白色浪纹", "importance": "high"},
                    {"item_type": "character", "name": "不存在的人", "description": "模型幻觉"},
                ],
                "_model": "test-model",
            }):
                candidates, report = server.ai_discover_setting_candidates(
                    {"slug": "lighthouse", "title": "白石灯塔"},
                    chapters,
                    limit=10,
                )

        names = {item["name"] for item in candidates}
        self.assertEqual(names, {"林舟", "黄铜罗盘"})
        self.assertEqual(report["used_count"], 1)
        character = next(item for item in candidates if item["name"] == "林舟")
        self.assertEqual(character["item_type"], "character")
        self.assertEqual(character["chapter_numbers"], [1])
        self.assertTrue(character["source_evidence"])
        self.assertEqual(character["raw"]["source"], "ai_candidate_discovery")

    def test_scan_settings_ai_mode_enhances_candidates_with_text_model(self):
        server = load_server_module()
        project = {"slug": "ssj", "title": "搜神记"}
        chapters = [{
            "chapter_number": 1,
            "volume": "第一卷",
            "title": "第一章 神农使者",
            "raw": {"excerpt": "少年拓拔野身穿青色短袍，长发束起，腰悬铜刀，在荒原上奔行。"},
        }]
        saved_payloads = []

        def fake_chat_json(*_args, **_kwargs):
            return {
                "description": "AI增强后的全书设定描述。",
                "visual_prompt": "AI增强后的漫画视觉提示词，东方上古神话风格。",
                "negative_prompt": "modern city, text",
                "aliases": ["AI别名"],
                "chapter_numbers": [1],
                "feature_phrases": ["青色短袍"],
                "importance": "core",
                "_model": "test-text-model",
            }

        def fake_upsert(_database_url, slug, item):
            saved_payloads.append(item)
            return {**item, "id": len(saved_payloads), "project_slug": slug}

        with patch.object(server, "ensure_database"):
            with patch.object(server, "project_by_slug", return_value=project):
                with patch.object(server.db, "list_setting_items", return_value=[]):
                    with patch.object(server.db, "list_chapters", return_value=chapters):
                        with patch.object(server.db, "upsert_setting_item", side_effect=fake_upsert):
                            with patch.object(server.db, "add_review"):
                                with patch.object(server, "runtime_config", return_value={
                                    "COMIC_PIPELINE_TEXT_MODEL": "configured-novel-model",
                                    "COMIC_PIPELINE_TEXT_ENV_PATH": "/tmp/text.env",
                                    "COMIC_PIPELINE_TEXT_MODEL_TIMEOUT": "333",
                                    "COMIC_PIPELINE_TEXT_MODEL_STREAM": "true",
                                }):
                                    with patch.object(server, "chat_json", side_effect=fake_chat_json) as chat_mock:
                                        result = server.scan_settings_api("ssj", {
                                            "limit": 3,
                                            "extraction_mode": "ai",
                                        })

        self.assertTrue(result["ok"])
        self.assertEqual(result["extraction_mode"], "ai")
        self.assertTrue(chat_mock.called)
        self.assertGreaterEqual(result["report"]["ai_used_count"], 1)
        self.assertEqual(result["report"]["ai_error_count"], 0)
        self.assertTrue(any((item.get("raw") or {}).get("source") == "targeted_setting_prompt_ai_enhanced" for item in saved_payloads))

    def test_character_scan_adds_visual_feature_prompt_from_evidence(self):
        server = load_server_module()
        chapters = [{
            "chapter_number": 1,
            "title": "神农使者",
            "raw": {
                "excerpt": "少年拓拔野身穿青色短袍，长发束起，腰悬铜刀，目光倔强，在荒原上与蚩尤同行。",
            },
        }]

        candidates = server.extract_character_candidates_from_chapters(chapters, limit=4)
        tuobaye = next(item for item in candidates if item["name"] == "拓拔野")

        self.assertIn("识别特征", tuobaye["description"])
        self.assertIn("青色短袍", tuobaye["visual_prompt"])
        self.assertIn("腰悬铜刀", tuobaye["visual_prompt"])
        self.assertIn("feature_phrases", tuobaye["raw"])

    def test_character_scan_does_not_assign_nearby_character_features(self):
        server = load_server_module()
        chapters = [{
            "chapter_number": 3,
            "title": "傀儡英雄",
            "raw": {
                "excerpt": "拓拔野偷偷瞄了白衣女子一眼，见她玉靥飞红，眉目之间怒意隐隐。",
            },
        }]

        candidates = server.extract_character_candidates_from_chapters(chapters, limit=4)
        tuobaye = next(item for item in candidates if item["name"] == "拓拔野")

        self.assertNotIn("玉靥飞红", tuobaye["visual_prompt"])
        self.assertEqual(tuobaye["raw"]["feature_phrases"], [])

    def test_suggest_settings_from_instruction_scans_chapter_text(self):
        server = load_server_module()
        project = {"slug": "ssj", "title": "搜神记"}
        chapters = [
            {
                "chapter_number": 1,
                "title": "第一章 少年",
                "raw": {"excerpt": "少年拓拔野进入大荒，与蚩尤结伴同行。"},
            },
            {
                "chapter_number": 2,
                "title": "第二章 重逢",
                "raw": {"summary": "拓拔野救下雨师妾，继续追查神农使者的线索。"},
            },
        ]

        with patch.object(server.db, "list_chapters", return_value=chapters):
            candidates = server.suggest_setting_candidates_from_instruction(
                project,
                "补充主角拓拔野的角色设定，提取出现章节和视觉设定",
                limit=6,
            )

        self.assertTrue(candidates)
        first = candidates[0]
        self.assertEqual(first["item_type"], "character")
        self.assertEqual(first["name"], "拓拔野")
        self.assertEqual(first["review_status"], "pending_review")
        self.assertIn(1, first["chapter_numbers"])
        self.assertIn(2, first["chapter_numbers"])
        self.assertIn("user_instruction", first["raw"]["source"])

    def test_refresh_setting_prompt_fill_missing_preserves_existing_manual_fields(self):
        server = load_server_module()
        setting = {
            "id": 42,
            "project_slug": "ssj",
            "item_type": "character",
            "name": "拓拔野",
            "aliases": [],
            "description": "人工已经确认的主角描述。",
            "visual_prompt": "",
            "negative_prompt": "",
            "first_chapter_number": 1,
            "chapter_numbers": [],
            "relations": {},
            "source_evidence": [],
            "importance": "core",
            "review_status": "pending_review",
            "locked": False,
            "raw": {"source": "manual"},
        }
        chapters = [{
            "chapter_number": 1,
            "title": "神农使者",
            "raw": {"excerpt": "少年拓拔野身穿青色短袍，长发束起，腰悬铜刀，在荒原上奔行。"},
        }]

        with patch.object(server, "ensure_database"):
            with patch.object(server.db, "get_setting_item", return_value=setting):
                with patch.object(server.db, "list_chapters", return_value=chapters):
                    result = server.refresh_setting_prompt_api(42, {"mode": "fill_missing"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "fill_missing")
        self.assertEqual(result["editor_payload"]["description"], "人工已经确认的主角描述。")
        self.assertIn("青色短袍", result["editor_payload"]["visual_prompt"])
        self.assertEqual(result["candidate"]["name"], "拓拔野")
        self.assertTrue(result["changes"]["visual_prompt"]["changed"])
        self.assertFalse(result["changes"]["description"]["changed"])

    def test_refresh_setting_prompt_scans_current_setting_name_not_only_known_names(self):
        server = load_server_module()
        setting = {
            "id": 43,
            "project_slug": "ssj",
            "item_type": "character",
            "name": "阿青",
            "aliases": ["青衣少女"],
            "description": "",
            "visual_prompt": "",
            "negative_prompt": "",
            "first_chapter_number": None,
            "chapter_numbers": [],
            "relations": {},
            "source_evidence": [],
            "importance": "normal",
            "review_status": "pending_review",
            "locked": True,
            "raw": {},
        }
        chapters = [{
            "chapter_number": 8,
            "title": "试剑",
            "raw": {"excerpt": "青衣少女阿青身穿青衣，手持竹杖，目光清亮，从溪边走来。"},
        }]

        with patch.object(server, "ensure_database"):
            with patch.object(server.db, "get_setting_item", return_value=setting):
                with patch.object(server.db, "list_chapters", return_value=chapters):
                    result = server.refresh_setting_prompt_api(43, {"mode": "overwrite"})

        self.assertTrue(result["locked"])
        self.assertIn(8, result["editor_payload"]["chapter_numbers"])
        self.assertIn("阿青", result["editor_payload"]["visual_prompt"])
        self.assertIn("青衣", result["editor_payload"]["visual_prompt"])
        self.assertIn("竹杖", result["editor_payload"]["visual_prompt"])

    def test_refresh_setting_prompt_ai_mode_uses_text_model_enhancement(self):
        server = load_server_module()
        setting = {
            "id": 44,
            "project_slug": "ssj",
            "project_title": "搜神记",
            "item_type": "character",
            "name": "拓拔野",
            "aliases": [],
            "description": "",
            "visual_prompt": "",
            "negative_prompt": "",
            "first_chapter_number": None,
            "chapter_numbers": [],
            "relations": {},
            "source_evidence": [],
            "importance": "normal",
            "review_status": "pending_review",
            "locked": False,
            "raw": {},
        }
        chapters = [{
            "chapter_number": 1,
            "title": "神农使者",
            "raw": {"excerpt": "少年拓拔野身穿青色短袍，长发束起，腰悬铜刀，在荒原上奔行。"},
        }]
        model_result = {
            "description": "拓拔野是大荒少年主角，性格倔强，行动敏捷，腰间常带铜刀。",
            "visual_prompt": "拓拔野，少年体型，青色短袍，长发束起，腰悬铜刀，倔强清亮目光，东方上古神话漫画角色设定图。",
            "negative_prompt": "modern city, text, watermark",
            "aliases": ["大荒少年"],
            "chapter_numbers": [1],
            "feature_phrases": ["青色短袍", "长发束起", "腰悬铜刀"],
            "importance": "core",
            "_model": "test-text-model",
        }

        captured_env = {}

        def fake_chat_json(*_args, **_kwargs):
            captured_env["model"] = os.environ.get("COMIC_PIPELINE_TEXT_MODEL")
            captured_env["env_path"] = os.environ.get("COMIC_PIPELINE_TEXT_ENV_PATH")
            captured_env["timeout"] = os.environ.get("COMIC_PIPELINE_TEXT_MODEL_TIMEOUT")
            captured_env["stream"] = os.environ.get("COMIC_PIPELINE_TEXT_MODEL_STREAM")
            return model_result

        runtime = {
            "COMIC_PIPELINE_TEXT_MODEL": "configured-novel-model",
            "COMIC_PIPELINE_TEXT_ENV_PATH": "/tmp/text.env",
            "COMIC_PIPELINE_TEXT_MODEL_TIMEOUT": "333",
            "COMIC_PIPELINE_TEXT_MODEL_STREAM": "true",
        }

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(server, "ensure_database"):
                with patch.object(server, "runtime_config", return_value=runtime):
                    with patch.object(server.db, "get_setting_item", return_value=setting):
                        with patch.object(server.db, "list_chapters", return_value=chapters):
                            with patch.object(server, "chat_json", side_effect=fake_chat_json) as chat_mock:
                                result = server.refresh_setting_prompt_api(44, {
                                    "mode": "overwrite",
                                    "extraction_mode": "ai",
                                })

        self.assertTrue(result["ok"])
        self.assertTrue(result["enhancement"]["used"])
        self.assertEqual(result["enhancement"]["model"], "test-text-model")
        self.assertIn("青色短袍", result["editor_payload"]["visual_prompt"])
        self.assertIn("大荒少年", result["editor_payload"]["aliases"])
        self.assertEqual(result["editor_payload"]["importance"], "core")
        self.assertTrue(chat_mock.called)
        self.assertEqual(captured_env["model"], "configured-novel-model")
        self.assertEqual(captured_env["env_path"], "/tmp/text.env")
        self.assertEqual(captured_env["timeout"], "333")
        self.assertEqual(captured_env["stream"], "true")

    def test_refresh_setting_prompt_ai_mode_uses_fallback_chapter_evidence(self):
        server = load_server_module()
        setting = {
            "id": 45,
            "project_slug": "ssj",
            "project_title": "搜神记",
            "item_type": "location",
            "name": "主角初遇神农使者的荒原场景",
            "aliases": [],
            "description": "主角在荒原中遇到神农使者的关键场景。",
            "visual_prompt": "",
            "negative_prompt": "",
            "first_chapter_number": 1,
            "chapter_numbers": [1],
            "relations": {},
            "source_evidence": [],
            "importance": "normal",
            "review_status": "pending_review",
            "locked": False,
            "raw": {},
        }
        chapters = [{
            "chapter_number": 1,
            "title": "神农使者",
            "raw": {"excerpt": "荒原暮色沉沉，少年拓拔野看见神农使者自风沙中走来，铜铃声在草海间回荡。"},
        }]

        def fake_chat_json(*_args, **_kwargs):
            return {
                "description": "荒原场景中，拓拔野初遇神农使者，风沙、草海和铜铃声形成关键气氛。",
                "visual_prompt": "荒原暮色，草海风沙，少年拓拔野远望神农使者，铜铃声，东方上古神话漫画场景。",
                "negative_prompt": "modern city, text",
                "aliases": ["荒原初遇"],
                "chapter_numbers": [1],
                "feature_phrases": ["荒原暮色", "草海风沙", "铜铃声"],
                "importance": "high",
                "_model": "test-text-model",
            }

        with patch.object(server, "ensure_database"):
            with patch.object(server, "runtime_config", return_value={
                "COMIC_PIPELINE_TEXT_MODEL": "configured-novel-model",
                "COMIC_PIPELINE_TEXT_ENV_PATH": "/tmp/text.env",
                "COMIC_PIPELINE_TEXT_MODEL_TIMEOUT": "333",
                "COMIC_PIPELINE_TEXT_MODEL_STREAM": "true",
            }):
                with patch.object(server.db, "get_setting_item", return_value=setting):
                    with patch.object(server.db, "list_chapters", return_value=chapters):
                        with patch.object(server, "chat_json", side_effect=fake_chat_json) as chat_mock:
                            result = server.refresh_setting_prompt_api(45, {
                                "mode": "overwrite",
                                "extraction_mode": "ai",
                            })

        self.assertTrue(result["ok"])
        self.assertTrue(result["enhancement"]["used"])
        self.assertTrue(chat_mock.called)
        self.assertIn("荒原暮色", result["editor_payload"]["visual_prompt"])
        self.assertTrue(result["candidate"]["source_evidence"])
        self.assertEqual(result["candidate"]["source_evidence"][0]["type"], "fallback_chapter_context")


if __name__ == "__main__":
    unittest.main()
