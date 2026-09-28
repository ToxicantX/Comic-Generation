import importlib.util
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class GenerationApprovalTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "console"))
        spec = importlib.util.spec_from_file_location("generation_approval_server", ROOT / "console" / "server.py")
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.rows = [self.output(22, "page"), self.output(23, "panel")]
        self.approvals = {"EP01": {**self.server.default_approval_state(), "draft": True, "assets": True}}
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(self.server, "active_project", return_value={"slug": "review-project"}))
        stack.enter_context(patch.object(self.server, "database_url", return_value="mock-database"))
        stack.enter_context(patch.object(self.server, "episode_detail", return_value={"media": {"summary": {
            "pages_total": 1, "pages_ready": 1, "real_pages_ready": 1,
            "panels_total": 1, "panels_ready": 1,
        }}}))
        stack.enter_context(patch.object(self.server, "status_snapshot", return_value={}))
        self.list_outputs = stack.enter_context(patch.object(self.server.db, "list_generated_outputs", return_value=self.rows))
        stack.enter_context(patch.object(self.server, "load_agent_approvals", return_value=self.approvals))
        stack.enter_context(patch.object(self.server, "approval_key", return_value="EP01"))
        self.save = stack.enter_context(patch.object(self.server, "save_agent_approvals"))
        self.side_effects = stack.enter_context(patch.object(self.server, "sync_gate_side_effects"))
        stack.enter_context(patch.object(self.server, "agent_inspect", return_value={"ok": True}))

    def output(self, output_id, output_type):
        checks, summary = self.server.clean_output_quality_checks({
            key: "pass" for key, _label in self.server.OUTPUT_QUALITY_DIMENSIONS
        })
        return {
            "id": output_id, "output_type": output_type, "review_status": "approved",
            "metadata": {"review_quality_checks": checks, "review_quality_summary": summary},
        }

    def approve(self, approved=True):
        return self.server.update_episode_approval({"episode_number": 1, "gate": "generation", "approved": approved})

    def assert_blocked(self):
        with self.assertRaises(ValueError):
            self.approve()
        self.assertFalse(self.approvals["EP01"]["generation"])
        self.save.assert_not_called()
        self.side_effects.assert_not_called()

    def test_unapproved_output_blocks_even_with_passing_quality(self):
        for status in ("needs_work", "rejected", "pending_review", "draft", "", "unknown", None):
            with self.subTest(status=status):
                self.rows[0]["review_status"] = status
                self.assert_blocked()

    def test_no_approved_outputs_block(self):
        for row in self.rows:
            row["review_status"] = "pending_review"
        self.assert_blocked()

    def test_observed_needs_work_composition_failure_blocks(self):
        self.rows[0]["review_status"] = "needs_work"
        checks, summary = self.server.clean_output_quality_checks({"composition_readability": "fail"})
        self.rows[0]["metadata"] = {"review_quality_checks": checks, "review_quality_summary": summary}
        self.assert_blocked()

    def test_each_unknown_quality_item_blocks_despite_cached_pass(self):
        for index in range(len(self.server.OUTPUT_QUALITY_DIMENSIONS)):
            with self.subTest(dimension=index):
                self.rows[0] = self.output(22, "page")
                self.rows[0]["metadata"]["review_quality_checks"][index]["status"] = "unknown"
                self.assert_blocked()

    def test_each_failed_quality_item_blocks_despite_cached_pass(self):
        for index in range(len(self.server.OUTPUT_QUALITY_DIMENSIONS)):
            with self.subTest(dimension=index):
                self.rows[0] = self.output(22, "page")
                self.rows[0]["metadata"]["review_quality_checks"][index]["status"] = "fail"
                self.assert_blocked()

    def test_each_missing_quality_item_blocks_despite_cached_pass(self):
        for index in range(len(self.server.OUTPUT_QUALITY_DIMENSIONS)):
            with self.subTest(dimension=index):
                self.rows[0] = self.output(22, "page")
                self.rows[0]["metadata"]["review_quality_checks"].pop(index)
                self.assert_blocked()

    def test_cached_summary_without_item_checks_blocks(self):
        self.rows[0]["metadata"].pop("review_quality_checks")
        self.assert_blocked()

    def test_one_passing_dimension_is_not_a_complete_quality_review(self):
        self.rows[0]["metadata"] = {
            "review_quality_checks": [{"key": "composition_readability", "status": "pass"}],
            "review_quality_summary": {"total": 1, "passed": 1, "failed": 0, "unknown": 0},
        }
        self.assert_blocked()

    def test_duplicate_dimension_cannot_replace_missing_dimension(self):
        checks = self.rows[0]["metadata"]["review_quality_checks"]
        checks[-1] = dict(checks[0])
        self.assert_blocked()

    def test_invalid_quality_status_blocks(self):
        self.rows[0]["metadata"]["review_quality_checks"][0]["status"] = "approved"
        self.assert_blocked()

    def test_empty_registered_outputs_block(self):
        self.rows.clear()
        self.assert_blocked()

    def test_incomplete_registered_outputs_block(self):
        self.rows.pop()
        self.assert_blocked()

    def test_quality_ready_requires_every_output_to_be_approved(self):
        self.rows[0]["review_status"] = "needs_work"
        quality = self.server.generated_output_quality_status({"slug": "review-project"}, 1)
        self.assertFalse(quality["ready"])

    def test_quality_status_recomputes_failed_items_instead_of_cached_summary(self):
        self.rows[0]["metadata"]["review_quality_checks"][-1]["status"] = "fail"
        quality = self.server.generated_output_quality_status({"slug": "review-project"}, 1)
        self.assertEqual(quality["quality_failed"], 1)
        self.assertFalse(quality["ready"])

    def test_all_outputs_approved_with_five_passing_items_allow_generation(self):
        self.assertEqual(self.approve(), {"ok": True})
        self.assertTrue(self.approvals["EP01"]["generation"])
        self.save.assert_called_once()
        self.side_effects.assert_called_once_with(1, "generation", True)
        self.list_outputs.assert_called_with("mock-database", "review-project", 1)
        quality = self.server.generated_output_quality_status({"slug": "review-project"}, 1)
        self.assertEqual(quality["quality_checked"], 2)
        self.assertTrue(quality["ready"])

    def test_revoking_generation_remains_allowed(self):
        self.rows.clear()
        self.approvals["EP01"].update({"generation": True, "qa": True, "next_episode": True})
        self.approve(False)
        for gate in ("generation", "qa", "next_episode"):
            self.assertFalse(self.approvals["EP01"][gate])


if __name__ == "__main__":
    unittest.main()
