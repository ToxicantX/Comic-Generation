import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConsoleRedesignTest(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "console" / "static" / "index.html").read_text(encoding="utf-8")
        self.app = (ROOT / "console" / "static" / "app.js").read_text(encoding="utf-8")
        self.css = (ROOT / "console" / "static" / "obsidian.css").read_text(encoding="utf-8")
        self.base_css = (ROOT / "console" / "static" / "styles.css").read_text(encoding="utf-8")

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

    def test_workflow_uses_the_product_rail_for_chapter_context(self):
        self.assertIn('id="railChapterContext"', self.html)
        self.assertIn('id="workflowChapterSidebar"', self.html)
        self.assertIn('function syncWorkflowChapterContext()', self.app)
        self.assertIn('chapterContext.appendChild(workflowSidebar)', self.app)
        self.assertIn('.module-switch > .module-group > button {', self.css)
        self.assertNotIn('.module-switch button {', self.css)

    def test_workflow_context_drawer_is_shared_and_closed_by_default(self):
        self.assertIn('id="contextDrawer"', self.html)
        self.assertIn('id="contextDrawerTitle"', self.html)
        self.assertIn('id="contextDrawerCloseButton"', self.html)
        self.assertRegex(
            self.html,
            r'id="contextDrawer"[^>]+hidden[^>]+aria-hidden="true"',
        )
        self.assertIn('function openContextDrawer(', self.app)
        self.assertIn('function closeContextDrawer()', self.app)
        self.assertIn('drawer.classList.add("assistant-expanded")', self.app)
        self.assertIn('event.key === "Escape"', self.app)

    def test_workflow_layout_reserves_no_drawer_space_until_opened(self):
        self.assertNotIn('grid-template-columns: 220px minmax(0, 1fr) 320px;', self.css)
        self.assertIn('.workbench.module-view.active.context-drawer-open', self.css)
        self.assertIn('@media (min-width: 1440px)', self.css)
        self.assertIn('grid-template-columns: minmax(0, 1fr) 312px;', self.css)
        self.assertIn('.workbench > .context-drawer', self.css)
        self.assertIn('grid-column: 1;', self.css)
        self.assertIn('.context-drawer[hidden]', self.css)
        self.assertIn('.context-drawer .agent-simulation:empty', self.css)

    def test_topbar_reuses_live_project_and_health_controls(self):
        for element_id in ("projectSelect", "projectMetric", "comfyMetric", "refreshButton"):
            self.assertEqual(self.html.count(f'id="{element_id}"'), 1)

    def test_database_credentials_are_not_rendered_as_plain_text(self):
        settings = (ROOT / "console" / "frontend" / "settings" / "SettingsView.vue").read_text(encoding="utf-8")
        self.assertNotIn('data-test="database-url"', settings)
        self.assertIn("数据库由桌面运行时管理", settings)

    def test_source_reader_shows_full_chapter_before_breakdown(self):
        self.assertIn("if (!pages.length && source.text)", self.app)
        self.assertIn("fullText.textContent = source.text", self.app)

    def test_compact_pc_layout_has_alignment_overrides(self):
        self.assertIn("grid-template-rows: 15px 32px", self.css)
        self.assertIn(".setting-toolbar > * { min-width: 0; }", self.css)
        self.assertIn(".task-center-panel > .section-head .filter-select", self.css)

    def test_dynamic_content_uses_dark_theme_surfaces(self):
        self.assertIn(".review-summary-grid article", self.css)
        self.assertIn(".review-center-row,", self.css)
        self.assertIn(".job-log,", self.css)
        self.assertIn(".source-overview,", self.css)

    def test_dark_theme_uses_readable_accent_text(self):
        self.assertIn("--accent: #818cf8", self.css)
        self.assertIn("--accent-strong: #a5b4fc", self.css)
        self.assertIn(".import-result-actions button.primary", self.css)
        self.assertIn("textarea::placeholder { color: #78859d; }", self.css)

    def test_import_step_badge_matches_the_four_step_flow(self):
        self.assertIn('id="importWizardBadge" class="mini-badge">四步导入</span>', self.html)

    def test_import_results_and_preview_follow_theme_surfaces(self):
        for selector, background in (
            (r"\.import-result-card\.compact", "background: var(--surface);"),
            (r"\.import-chapter-table", "background: var(--surface);"),
            (r"\.import-strategy\.active", "background: var(--accent-soft);"),
        ):
            with self.subTest(selector=selector):
                rule = re.search(selector + r"\s*\{([^}]+)\}", self.base_css)
                self.assertIsNotNone(rule)
                self.assertIn(background, rule.group(1))

    def test_import_warning_background_tracks_the_warning_theme(self):
        rule = re.search(r"\.import-warnings span\s*\{([^}]+)\}", self.base_css)
        self.assertIsNotNone(rule)
        self.assertIn(
            "background: color-mix(in srgb, var(--warn) 10%, var(--surface));",
            rule.group(1),
        )

    def test_vue_notification_host_loads_before_the_legacy_console(self):
        vue_script = '/static/vue/console-ui.js?v=20260928-vue-baseline'
        legacy_script = '/static/app.js?v=20260928-vue-baseline'
        self.assertIn('/static/vue/console-ui.css?v=20260928-vue-baseline', self.html)
        self.assertIn(vue_script, self.html)
        self.assertLess(self.html.index(vue_script), self.html.index(legacy_script))
        self.assertIn('typeof window.comicNotify === "function"', self.app)
        self.assertIn("window.__comicPendingNotifications.push(notification)", self.app)
        self.assertNotIn('document.createElement("div");\n  toast.className', self.app)

    def test_vue_dialog_host_replaces_legacy_dialogs_and_native_calls(self):
        self.assertIn('id="appDialogHost"', self.html)
        for legacy_id in (
            'id="appDialog"',
            'id="appDialogTitle"',
            'id="appDialogKind"',
            'id="appDialogMessage"',
            'id="appDialogInput"',
            'id="appDialogConfirm"',
            'id="appDialogCancel"',
        ):
            with self.subTest(legacy_id=legacy_id):
                self.assertNotIn(legacy_id, self.html)
        self.assertIn('typeof window.comicDialog === "function"', self.app)
        self.assertIn("return window.comicDialog(options)", self.app)
        self.assertNotIn("window.confirm(", self.app)
        self.assertNotIn("window.prompt(", self.app)
        for legacy_selector in (".app-dialog-overlay", ".app-dialog", ".app-dialog-kind"):
            with self.subTest(legacy_selector=legacy_selector):
                self.assertNotIn(legacy_selector, self.base_css)
                self.assertNotIn(legacy_selector, self.css)


if __name__ == "__main__":
    unittest.main()
