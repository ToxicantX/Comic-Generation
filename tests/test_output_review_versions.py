import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PAGE_A = "NOVEL_A_EP01_P001"
PAGE_B = "NOVEL_A_EP01_P002"
PANEL_A1 = f"{PAGE_A}_PANEL01"
PANEL_A2 = f"{PAGE_A}_PANEL02"
PANEL_B1 = f"{PAGE_B}_PANEL01"
REVIEW_KEYS = (
    "reviewed_at", "review_action", "review_comment",
    "review_quality_checks", "review_quality_summary",
)


class OutputReviewVersionsTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "console"))
        self.addCleanup(sys.path.remove, str(ROOT / "console"))
        spec = importlib.util.spec_from_file_location("output_review_versions_server", ROOT / "console" / "server.py")
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.project = {"slug": "novel_a", "manifest_dir": temp_dir.name}
        self.rows = {
            1: self.output(1, "page", PAGE_A),
            2: self.output(2, "panel", PAGE_A, PANEL_A1),
            3: self.output(3, "panel", PAGE_A, PANEL_A2),
            4: self.output(4, "page", PAGE_B),
            5: self.output(5, "panel", PAGE_B, PANEL_B1),
        }
        self.media = {"episode_number": 1, "pages": [], "panels": []}
        for row in self.rows.values():
            metadata = row["metadata"]
            kind = row["output_type"]
            self.media[f"{kind}s"].append({
                "id": metadata["media_id"], "kind": kind,
                "page_id": metadata["page_id"], "panel_id": metadata["panel_id"],
                "path": row["file_path"], "exists": True, "production_status": "ready",
            })
        self.original = deepcopy(self.rows)
        self.versions = [{"output_id": 2, "role": "previous", "file_path": "backup.png"}]
        self.reviews = [{"action": "review:approved", "before_data": {}, "after_data": deepcopy(self.rows[2])}]
        self.old_versions = deepcopy(self.versions)
        self.old_reviews = deepcopy(self.reviews)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(self.server, "ensure_database"))
        stack.enter_context(patch.object(self.server, "database_url", return_value="mock-database"))
        stack.enter_context(patch.object(self.server.db, "get_approvals", return_value={"draft": True, "assets": True, "generation": True, "qa": True, "next_episode": True}))
        self.save_approvals = stack.enter_context(patch.object(self.server.db, "save_approvals"))
        stack.enter_context(patch.object(self.server, "active_project", side_effect=AssertionError("project switched")))
        self.episode_media = stack.enter_context(patch.object(self.server, "episode_media", return_value=self.media))
        self.sync_outputs = stack.enter_context(patch.object(self.server, "sync_outputs_api", wraps=self.server.sync_outputs_api))
        stack.enter_context(patch.object(self.server.db, "list_generated_outputs", side_effect=lambda _url, _slug, _episode: deepcopy(list(self.rows.values()))))
        stack.enter_context(patch.object(self.server.db, "list_output_versions", side_effect=lambda _url, _slug, _ids: deepcopy(self.versions)))
        stack.enter_context(patch.object(self.server, "ensure_initial_output_version"))
        stack.enter_context(patch.object(self.server.db, "get_generated_output_by_path", side_effect=self.get_by_path))
        stack.enter_context(patch.object(self.server.db, "get_generated_output", side_effect=lambda _url, output_id: deepcopy(self.rows.get(output_id))))
        stack.enter_context(patch.object(self.server.db, "upsert_generated_output", side_effect=self.upsert))
        self.update = stack.enter_context(patch.object(self.server.db, "update_generated_output", side_effect=self.update_output))
        stack.enter_context(patch.object(self.server.db, "add_output_version", side_effect=self.add_version))
        stack.enter_context(patch.object(self.server.db, "add_review", side_effect=lambda _url, _slug, review: self.reviews.append(deepcopy(review))))
        self.read_json = stack.enter_context(patch.object(self.server, "read_optional_json", return_value=None))

    def output(self, output_id, kind, page_id, panel_id=""):
        checks, summary = self.server.clean_output_quality_checks({
            key: "pass" for key, _label in self.server.OUTPUT_QUALITY_DIMENSIONS
        })
        return {
            "id": output_id, "project_slug": "novel_a", "chapter_number": 1, "job_id": f"old-job-{output_id}",
            "output_type": kind, "file_path": f"outputs/{panel_id or page_id}.png",
            "review_status": "approved", "metadata": {
                "media_id": panel_id or page_id, "page_id": page_id, "panel_id": panel_id,
                "reviewed_at": "2026-09-27T10:00:00", "review_action": "approve",
                "review_comment": "Old image passed", "review_quality_checks": checks,
                "review_quality_summary": summary, "custom_metadata": "keep",
                "source_job_id": f"old-job-{output_id}", "generation_context": {"captured_at": "old-context"},
            },
        }

    def get_by_path(self, _url, slug, file_path):
        return deepcopy(next((row for row in self.rows.values() if row["project_slug"] == slug and row["file_path"] == file_path), None))

    def upsert(self, _url, slug, record):
        before = self.get_by_path(_url, slug, record["file_path"])
        if before:
            saved = {**before, **deepcopy(record), "metadata": {**before["metadata"], **deepcopy(record["metadata"])}}
            saved["job_id"] = record.get("job_id") or before.get("job_id", "")
            if before["review_status"] == "approved":
                saved["review_status"] = "approved"
        else:
            saved = {**deepcopy(record), "id": max(self.rows, default=0) + 1, "project_slug": slug}
            saved["job_id"] = record.get("job_id", "")
        self.rows[saved["id"]] = saved
        return deepcopy(saved)

    def update_output(self, _url, output_id, updates):
        before = self.rows[output_id]
        saved = {**before, **deepcopy(updates), "metadata": {**before["metadata"], **deepcopy(updates.get("metadata") or {})}}
        self.rows[output_id] = saved
        return deepcopy(saved)

    def add_version(self, _url, slug, version):
        self.assertEqual(slug, self.project["slug"])
        self.versions.append(deepcopy(version))
        return deepcopy(version)

    def job(self, stage="regenerate", **updates):
        return {
            "id": "new-image-job", "stage": stage, "status": "running", "exit_code": None,
            "page_id": PAGE_A, "panel_id": PANEL_A1, "panel_ids": [PANEL_A1, PANEL_A2],
            "generation_context": {"page_ids": [PAGE_A, PAGE_B], "panel_ids": [PANEL_A1, PANEL_A2, PANEL_B1]},
            **updates,
        }

    def sync_job(self, job):
        return self.server.sync_and_record_job_output_versions(self.project, 1, job)

    def assert_review_preserved(self, output_id):
        row, original = self.rows[output_id], self.original[output_id]
        self.assertEqual(row["review_status"], original["review_status"])
        self.assertEqual({key: row["metadata"].get(key) for key in REVIEW_KEYS}, {key: original["metadata"].get(key) for key in REVIEW_KEYS})
        self.assertEqual(row["job_id"], original["job_id"])
        for key in ("source_job_id", "generation_context"):
            self.assertEqual(row["metadata"].get(key), original["metadata"].get(key))

    def assert_reset_scope(self, result, output_ids):
        self.assertEqual({call.args[1] for call in self.update.call_args_list}, set(output_ids))
        self.assertEqual({version["output_id"] for version in result["versions_recorded"]}, set(output_ids))
        returned = {row["id"]: row for row in result["outputs"]}
        returned_media = {item["db_output_id"]: item for item in [*result["media"]["pages"], *result["media"]["panels"]]} if output_ids else {}
        for output_id, row in self.rows.items():
            if output_id not in output_ids:
                self.assert_review_preserved(output_id)
                continue
            self.assertEqual(row["review_status"], "pending_review")
            self.assertEqual(row["job_id"], "new-image-job")
            self.assertEqual(row["metadata"]["source_job_id"], "new-image-job")
            self.assertEqual(returned[output_id], row)
            self.assertEqual(returned_media[output_id]["db_review_status"], "pending_review")
            self.assertFalse(returned_media[output_id]["db_review_comment"])
            for key in ("reviewed_at", "review_action", "review_comment"):
                self.assertFalse(row["metadata"].get(key))
            checks = row["metadata"]["review_quality_checks"]
            self.assertEqual({check["key"] for check in checks}, {key for key, _label in self.server.OUTPUT_QUALITY_DIMENSIONS})
            self.assertEqual(len(checks), 5)
            self.assertTrue(all(check["status"] == "unknown" and not check["note"] for check in checks))
            self.assertEqual(row["metadata"]["review_quality_summary"], {"total": 5, "passed": 0, "failed": 0, "unknown": 5})
            if output_id in self.original:
                self.assertEqual(row["metadata"]["custom_metadata"], "keep")
        self.assertEqual(self.versions[:len(self.old_versions)], self.old_versions)
        self.assertEqual(self.reviews[:len(self.old_reviews)], self.old_reviews)
        if output_ids:
            self.episode_media.assert_called_once_with(1, self.project)
        else:
            self.sync_outputs.assert_not_called()
            self.episode_media.assert_not_called()
            self.assertEqual(self.rows, self.original)

    def test_empty_generation_scope_never_matches_outputs(self):
        for context in (
            {"settings": [{"name": "Old character"}]},
            {"page_ids": [], "panel_ids": []},
            {"page_id": PAGE_A, "page_ids": [], "panel_ids": []},
        ):
            for item in [*self.media["pages"], *self.media["panels"]]:
                with self.subTest(context=context, item=item["id"]):
                    self.assertFalse(self.server.generation_context_matches_item(context, item))

    def test_successful_new_output_invalidates_downstream_gates_and_old_qa(self):
        self.sync_job(self.job())
        self.save_approvals.assert_called_once()
        _url, slug, episode, approvals = self.save_approvals.call_args.args
        self.assertEqual((slug, episode), ("novel_a", 1))
        self.assertTrue(approvals["draft"] and approvals["assets"])
        self.assertFalse(approvals["generation"] or approvals["qa"] or approvals["next_episode"])
        path = Path(self.project["manifest_dir"]) / f"{self.server.project_episode_stem(self.project, 1)}_pipeline_run.json"
        published = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(published["invalidated_by"], "new-image-job")
        self.assertFalse(self.server.qa_report_ready({"texts": {"status_md": "old report"}, "pipeline_result": published}))

    def test_failed_output_keeps_chapter_approval_unchanged(self):
        self.sync_job(self.job(status="failed"))
        self.save_approvals.assert_not_called()

    def test_page_assembly_without_new_panel_still_resets_page_review(self):
        result = self.sync_job(self.job("generate", result={
            "completed": True, "jobs_attempted": [],
            "stages": [{"name": "assemble_pages", "runs": [
                {"page_id": PAGE_A, "assembly_ok": True, "exit_code": 0},
            ]}],
        }))
        self.assert_reset_scope(result, {1})

    def test_explicit_empty_scope_list_does_not_fall_back_to_page(self):
        panel_only = {"page_id": PAGE_A, "page_ids": [], "panel_ids": [PANEL_A1]}
        self.assertFalse(self.server.generation_context_matches_item(panel_only, self.media["pages"][0]))
        self.assertTrue(self.server.generation_context_matches_item(panel_only, self.media["panels"][0]))
        self.assertFalse(self.server.generation_context_matches_item(panel_only, self.media["panels"][1]))
        page_only = {"page_id": PAGE_A, "page_ids": [PAGE_A], "panel_ids": []}
        self.assertTrue(self.server.generation_context_matches_item(page_only, self.media["pages"][0]))
        self.assertFalse(self.server.generation_context_matches_item(page_only, self.media["panels"][0]))

    def test_legacy_page_scope_still_matches_only_that_page(self):
        context = {"page_id": PAGE_A}
        for item in [*self.media["pages"], *self.media["panels"]]:
            with self.subTest(item=item["id"]):
                self.assertEqual(self.server.generation_context_matches_item(context, item), item["page_id"] == PAGE_A)

    def test_media_record_only_sets_provenance_for_matching_scope(self):
        context = {"page_ids": [PAGE_A], "panel_ids": [PANEL_A1]}
        self.server._REQUEST_CONTEXT.generation_context = context
        self.server._REQUEST_CONTEXT.source_job_id = "new-image-job"
        for item in [*self.media["pages"], *self.media["panels"]]:
            with self.subTest(item=item["id"]):
                record = self.server.media_output_record(self.project, 1, item)
                if item["id"] in {PAGE_A, PANEL_A1}:
                    self.assertEqual(record["job_id"], "new-image-job")
                    self.assertEqual(record["metadata"]["source_job_id"], "new-image-job")
                    self.assertEqual(record["metadata"]["generation_context"], context)
                else:
                    self.assertNotIn("job_id", record)
                    self.assertNotIn("source_job_id", record["metadata"])
                    self.assertNotIn("generation_context", record["metadata"])

    def test_successful_single_regeneration_resets_panel_and_assembled_page_only(self):
        self.assert_reset_scope(self.sync_job(self.job()), {1, 2})

    def test_successful_regeneration_resets_any_previous_review_status(self):
        for status in ("needs_work", "rejected", "pending_review"):
            with self.subTest(status=status):
                self.rows = deepcopy(self.original)
                self.rows[2]["review_status"] = status
                self.sync_job(self.job())
                row = self.rows[2]
                self.assertEqual(row["review_status"], "pending_review")
                self.assertFalse(row["metadata"].get("review_comment"))
                self.assertEqual(row["metadata"]["review_quality_summary"]["unknown"], 5)

    def test_successful_page_regeneration_resets_successful_panels_and_page(self):
        self.assert_reset_scope(self.sync_job(self.job("regenerate_page", runs=[
            {"panel_id": PANEL_A1, "ok": True}, {"panel_id": PANEL_A2, "ok": True},
        ])), {1, 2, 3})

    def test_partial_page_regeneration_preserves_failed_restored_panel(self):
        self.assert_reset_scope(self.sync_job(self.job("regenerate_page", runs=[
            {"panel_id": PANEL_A1, "ok": True}, {"panel_id": PANEL_A2, "ok": False},
        ])), {1, 2})

    def test_partial_page_result_reads_nested_runs(self):
        self.assert_reset_scope(self.sync_job(self.job("regenerate_page", status="partial", exit_code=1, result={
            "status": "partial", "completed": False, "runs": [
                {"panel_id": PANEL_A1, "ok": True}, {"panel_id": PANEL_A2, "ok": False},
            ],
        })), {1, 2})

    def test_all_failed_page_runs_preserve_old_page_and_panels(self):
        self.assert_reset_scope(self.sync_job(self.job("regenerate_page", runs=[
            {"panel_id": PANEL_A1, "ok": False}, {"panel_id": PANEL_A2, "ok": False},
        ])), set())

    def test_missing_page_runs_do_not_assume_all_targets_succeeded(self):
        self.assert_reset_scope(self.sync_job(self.job("regenerate_page")), set())

    def test_run_outside_requested_page_is_not_reset(self):
        self.assert_reset_scope(self.sync_job(self.job("regenerate_page", runs=[
            {"panel_id": PANEL_A1, "ok": True}, {"panel_id": PANEL_B1, "ok": True},
        ])), {1, 2})

    def test_generation_uses_completed_attempts_not_broad_context(self):
        self.assert_reset_scope(self.sync_job(self.job("generate", result={
            "completed": True, "jobs_attempted": [
                {"page_id": PAGE_A, "panel_id": PANEL_A1, "completed": True},
                {"page_id": PAGE_A, "panel_id": PANEL_A2, "completed": False},
                {"page_id": PAGE_B, "panel_id": PANEL_B1, "completed": False, "skipped": True},
            ],
        })), {1, 2})

    def test_generation_reads_live_pipeline_and_recovery_results(self):
        pipeline = {"completed": True, "paths": {"recovery_result": "new-recovery.json"}, "stages": [
            {"name": "assemble_pages", "runs": [
                {"page_id": PAGE_A, "status": "passed", "exit_code": 0, "assembly_ok": True},
                {"page_id": PAGE_B, "status": "passed", "exit_code": 0, "assembly_ok": True},
            ]},
        ]}
        recovery = {"jobs_attempted": [{"page_id": PAGE_A, "panel_id": PANEL_A1, "completed": True}]}
        self.read_json.side_effect = lambda path: {"new-pipeline.json": pipeline, "new-recovery.json": recovery}.get(str(path))
        self.assert_reset_scope(self.sync_job(self.job("generate", result_path="new-pipeline.json")), {1, 2, 4})
        self.read_json.assert_any_call(Path("new-pipeline.json"))
        self.read_json.assert_any_call(Path("new-recovery.json"))

    def test_generation_does_not_reset_existing_page_when_assembly_failed(self):
        self.assert_reset_scope(self.sync_job(self.job("generate", result={
            "partial": True, "completed": False,
            "jobs_attempted": [{"page_id": PAGE_A, "panel_id": PANEL_A1, "completed": True}],
            "pages_assembled": [{"page_id": PAGE_A, "assembly_ok": False, "exit_code": 1, "status": "failed"}],
        })), {2})

    def test_no_generation_attempts_preserve_all_reviews(self):
        self.assert_reset_scope(self.sync_job(self.job("generate", result={"completed": True, "jobs_attempted": []})), set())

    def test_missing_single_target_does_not_reset_entire_episode(self):
        self.assert_reset_scope(self.sync_job(self.job(panel_id="", page_id="")), set())

    def test_failed_and_cancelled_jobs_preserve_reviews_and_versions(self):
        for stage in ("generate", "regenerate", "regenerate_page"):
            for status in ("failed", "cancelled"):
                with self.subTest(stage=stage, status=status):
                    result = self.sync_job(self.job(stage, status=status, exit_code=1))
                    self.update.assert_not_called()
                    self.assertEqual(result["versions_recorded"], [])
                    for output_id in self.original:
                        self.assert_review_preserved(output_id)

    def test_cancelled_or_failed_result_does_not_reset_running_job(self):
        for result in ({"cancelled": True}, {"status": "failed", "completed": False}, {"completed": False, "ok": False}):
            with self.subTest(result=result):
                synced = self.sync_job(self.job(result=result))
                self.update.assert_not_called()
                self.assertEqual(synced["versions_recorded"], [])
                for output_id in self.original:
                    self.assert_review_preserved(output_id)

    def test_dry_run_preserves_all_reviews(self):
        result = self.sync_job(self.job("generate", result={"completed": True, "dry_run": True,
            "jobs_attempted": [{"page_id": PAGE_A, "panel_id": PANEL_A1, "completed": True}],
        }))
        self.update.assert_not_called()
        self.assertEqual(result["versions_recorded"], [])

    def test_ordinary_sync_preserves_every_review_status_and_quality(self):
        for output_id, status in zip(self.rows, ("approved", "needs_work", "rejected", "pending_review", "draft")):
            self.rows[output_id]["review_status"] = status
        self.original = deepcopy(self.rows)
        result = self.server.sync_outputs_api({"episode_number": 1}, self.project)
        self.assertTrue(result["ok"])
        self.update.assert_not_called()
        for output_id in self.original:
            self.assert_review_preserved(output_id)

    def test_successful_job_preserves_unrelated_rejected_output(self):
        self.rows[5]["review_status"] = "rejected"
        self.original = deepcopy(self.rows)
        self.assert_reset_scope(self.sync_job(self.job()), {1, 2})

    def test_new_generated_panel_starts_with_five_unknown_checks(self):
        del self.rows[2]
        self.assert_reset_scope(self.sync_job(self.job()), {1, 6})

    def test_thread_local_context_is_restored_after_job_sync(self):
        original_context = {"page_id": "other-project-page"}
        self.server._REQUEST_CONTEXT.generation_context = original_context
        self.server._REQUEST_CONTEXT.source_job_id = "other-job"
        self.sync_job(self.job())
        self.assertIs(self.server._REQUEST_CONTEXT.generation_context, original_context)
        self.assertEqual(self.server._REQUEST_CONTEXT.source_job_id, "other-job")


if __name__ == "__main__":
    unittest.main()
