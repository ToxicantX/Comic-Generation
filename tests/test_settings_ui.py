import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SettingsUiTest(unittest.TestCase):
    def test_settings_exposes_both_image_backends(self):
        html = (ROOT / "console" / "static" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "console" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="imageBackend"', html)
        self.assertIn('<option value="direct_api">', html)
        self.assertIn('<option value="comfyui">', html)
        self.assertIn('COMIC_PIPELINE_IMAGE_BACKEND: $("imageBackend").value', app)
        self.assertIn('setValue("imageBackend",', app)

    def test_direct_mode_keeps_comfyui_controls_visible_but_optional(self):
        html = (ROOT / "console" / "static" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "console" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="comfySettingsFields"', html)
        self.assertIn('id="backendModeNote"', html)
        self.assertIn('startButton.textContent = isComfy ? "启动 ComfyUI" : "无需启动"', app)
        self.assertIn('fields.disabled = !isComfy', app)

    def test_unsaved_backend_switch_does_not_reuse_previous_health_result(self):
        app = (ROOT / "console" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function imageBackendSelectionChanged()", app)
        self.assertIn('? "保存后检查"', app)
        self.assertIn("startButton.disabled = !isComfy || pendingSave", app)
        self.assertIn("checkButton.disabled = pendingSave", app)
        self.assertIn("testImageButton.disabled = pendingSave", app)
        self.assertIn("后端类型已修改，请先保存设置", app)

    def test_direct_preview_stays_in_the_console(self):
        app = (ROOT / "console" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('previewLink.textContent = externalPreview ? "打开 ComfyUI 预览" : "查看生成结果"', app)
        self.assertIn('activateModule("media")', app)


if __name__ == "__main__":
    unittest.main()
