import importlib.util
import os
import sys
import subprocess
import unittest
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

    def test_close_reading_requires_approved_global_settings(self):
        server = load_server_module()

        with patch.object(server, "active_project", return_value={"slug": "ssj", "manifest_dir": "/tmp"}):
            with patch.object(Path, "is_file", return_value=True):
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
            with patch.object(Path, "is_file", return_value=True):
                with patch.object(server, "config_snapshot", return_value={"config": {"COMIC_PIPELINE_TEXT_MODEL": "gpt-5.4"}}):
                    with patch.object(server.db, "list_setting_items", return_value=settings):
                        with patch.object(server.db, "list_visual_assets", return_value=[]):
                            with self.assertRaisesRegex(ValueError, "全局素材"):
                                server.assert_stage_allowed("close_reading", 1)

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


if __name__ == "__main__":
    unittest.main()
