import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "run_comic_episode_pipeline.py"


def load_module():
    spec = importlib.util.spec_from_file_location("episode_pipeline_backend_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EpisodePipelineBackendTest(unittest.TestCase):
    def test_direct_pipeline_defaults_to_repository_output(self):
        source = MODULE_PATH.read_text(encoding="utf-8")

        self.assertIn('or (WORKSPACE / "output")', source)
        self.assertNotIn(r'r"G:\ComfyUI\output"', source)
        self.assertIn('os.environ.setdefault("COMIC_PIPELINE_OUTPUT_ROOT"', source)

    def test_direct_api_health_stage_does_not_call_comfyui(self):
        module = load_module()
        args = SimpleNamespace(
            image_backend="direct_api",
            check_comfy_health=True,
            generate_images=True,
            skip_image_generation=False,
            dry_run=False,
            comfy_url="http://127.0.0.1:8188",
        )

        with patch.object(module, "run_command_stage") as run_command:
            result = module.stage_comfy_health(args, {"paths": {}}, {})

        self.assertEqual(result["status"], "skipped_not_required")
        self.assertEqual(result["backend"], "direct_api")
        run_command.assert_not_called()

    def test_direct_api_generates_missing_panels_from_existing_workflow_results(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = root / "panel01.json"
            workflow.write_text("{}", encoding="utf-8")
            panel = root / "output" / "panel01.png"
            page_result = root / "page_workflows.json"
            page_result.write_text(json.dumps({
                "page_id": "EP01_P001",
                "created": [{
                    "panel_id": "EP01_P001_PANEL01",
                    "workflow": str(workflow),
                    "expected_panel_path": str(panel),
                }],
            }), encoding="utf-8")
            workflow_create = root / "episode_workflows.json"
            workflow_create.write_text(json.dumps({
                "runs": [{
                    "page_id": "EP01_P001",
                    "workflow_result_path": str(page_result),
                }],
            }), encoding="utf-8")
            recovery = root / "recovery.json"
            context = {
                "paths": {
                    "workflow_create_result": workflow_create,
                    "recovery_result": recovery,
                },
                "generation_context_path": None,
            }
            args = SimpleNamespace(max_panels=0)
            calls = []

            def fake_generate(workflow_path, output_path, **kwargs):
                calls.append((Path(workflow_path), Path(output_path), kwargs))
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"generated")
                return {"completed": True, "backend": "direct_api"}

            with patch.object(module, "generate_from_workflow", side_effect=fake_generate):
                result = module.generate_panels_direct(args, context)

            self.assertTrue(result["completed"])
            self.assertEqual(result["jobs_discovered"], 1)
            self.assertEqual(result["jobs_attempted"][0]["panel_id"], "EP01_P001_PANEL01")
            self.assertEqual(calls[0][0], workflow)
            self.assertEqual(calls[0][1], panel)
            self.assertTrue(recovery.is_file())

    def test_direct_api_max_panels_reports_deferred_work_as_partial(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            created = []
            for index in (1, 2):
                workflow = root / f"panel{index:02d}.json"
                workflow.write_text("{}", encoding="utf-8")
                created.append({
                    "panel_id": f"EP01_P001_PANEL{index:02d}",
                    "workflow": str(workflow),
                    "expected_panel_path": str(root / "output" / f"panel{index:02d}.png"),
                })
            page_result = root / "page_workflows.json"
            page_result.write_text(json.dumps({
                "page_id": "EP01_P001",
                "created": created,
            }), encoding="utf-8")
            workflow_create = root / "episode_workflows.json"
            workflow_create.write_text(json.dumps({
                "runs": [{
                    "page_id": "EP01_P001",
                    "workflow_result_path": str(page_result),
                }],
            }), encoding="utf-8")
            context = {
                "paths": {
                    "workflow_create_result": workflow_create,
                    "recovery_result": root / "recovery.json",
                },
                "generation_context_path": None,
            }
            args = SimpleNamespace(max_panels=1)

            def fake_generate(workflow_path, output_path, **kwargs):
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"generated")
                return {"completed": True, "backend": "direct_api"}

            with patch.object(module, "generate_from_workflow", side_effect=fake_generate):
                result = module.generate_panels_direct(args, context)

        self.assertFalse(result["completed"])
        self.assertTrue(result["partial"])
        self.assertEqual(result["jobs_discovered"], 2)
        self.assertEqual(result["jobs_selected"], 1)
        self.assertEqual(result["jobs_deferred"], 1)
        self.assertEqual(result["deferred_reason"], "max_panels")
        summary = module.recovery_summary(result)
        self.assertEqual(summary["jobs_selected"], 1)
        self.assertEqual(summary["jobs_deferred"], 1)

    def test_direct_api_generates_missing_anchor_without_comfyui_queue(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = root / "anchor.json"
            workflow.write_text("{}", encoding="utf-8")
            output = root / "anchors" / "hero.png"
            args = SimpleNamespace(
                image_backend="direct_api",
                skip_image_generation=False,
                generate_images=True,
                dry_run=False,
                comfy_url="http://127.0.0.1:8188",
                max_prompt_polls=10,
            )
            state = {
                "missing_reference_files": [{"alias": "hero", "path": str(output)}],
                "anchor_workflow_candidates": {
                    "hero": {"workflow": str(workflow), "expected_path": str(output)},
                },
            }

            with patch.object(module, "reference_alias_state", return_value=state):
                with patch.object(module, "find_existing_anchor_jobs") as find_jobs:
                    def fake_generate(workflow_path, output_path, **kwargs):
                        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                        Path(output_path).write_bytes(b"generated")
                        return {"completed": True}

                    with patch.object(module, "generate_from_workflow", side_effect=fake_generate) as generate:
                        result = module.stage_anchor_assets(args, {}, {})

        self.assertEqual(result["status"], "passed")
        find_jobs.assert_not_called()
        generate.assert_called_once_with(workflow, output, env_path=None)


if __name__ == "__main__":
    unittest.main()
