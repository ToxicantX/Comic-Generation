import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConsoleRedesignTest(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "console" / "static" / "index.html").read_text(encoding="utf-8")
        self.app = (ROOT / "console" / "static" / "app.js").read_text(encoding="utf-8")
        self.css = (ROOT / "console" / "static" / "obsidian.css").read_text(encoding="utf-8")

    def test_obsidian_shell_has_one_product_navigation(self):
        self.assertIn('/static/obsidian.css', self.html)
        self.assertEqual(self.html.count('>小说内容</button>'), 1)
        self.assertEqual(self.html.count('>小说设定</button>'), 1)
        self.assertEqual(self.html.count('>素材库</button>'), 1)
        self.assertEqual(self.html.count('>漫画制作</button>'), 1)
        self.assertNotIn('>章节工作台</button>', self.html)

    def test_novel_and_comic_routes_share_existing_workbench(self):
        self.assertIn('data-module="workflow" data-workspace-tab="content"', self.html)
        self.assertIn('data-module="workflow" data-workspace-tab="media"', self.html)
        self.assertIn('function workflowNavigationTab()', self.app)
        self.assertIn('workbench.dataset.workspace = tab === "media" ? "comic" : "novel"', self.app)

    def test_topbar_reuses_live_project_and_health_controls(self):
        for element_id in ("projectSelect", "projectMetric", "comfyMetric", "refreshButton"):
            self.assertEqual(self.html.count(f'id="{element_id}"'), 1)

    def test_database_credentials_are_not_rendered_as_plain_text(self):
        self.assertIn('id="databaseUrl" type="password"', self.html)

    def test_compact_pc_layout_has_alignment_overrides(self):
        self.assertIn("grid-template-rows: 15px 32px", self.css)
        self.assertIn(".setting-toolbar > * { min-width: 0; }", self.css)
        self.assertIn(".task-center-panel > .section-head .filter-select", self.css)

    def test_dynamic_content_uses_dark_theme_surfaces(self):
        self.assertIn(".review-summary-grid article", self.css)
        self.assertIn(".review-center-row,", self.css)
        self.assertIn(".job-log,", self.css)

    def test_dark_theme_uses_readable_accent_text(self):
        self.assertIn("--accent: #818cf8", self.css)
        self.assertIn("--accent-strong: #a5b4fc", self.css)
        self.assertIn(".import-result-actions button.primary", self.css)
        self.assertIn("textarea::placeholder { color: #78859d; }", self.css)

    def test_import_step_badge_matches_the_four_step_flow(self):
        self.assertIn('id="importWizardBadge" class="mini-badge">四步导入</span>', self.html)


if __name__ == "__main__":
    unittest.main()
