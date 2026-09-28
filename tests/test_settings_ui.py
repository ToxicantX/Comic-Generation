import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SettingsUiTest(unittest.TestCase):
    def read_frontend(self, name):
        return (ROOT / "console" / "frontend" / "settings" / name).read_text(encoding="utf-8")

    def test_settings_has_independent_model_selectors_and_manual_inputs(self):
        html = (ROOT / "console" / "static" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "console" / "static" / "app.js").read_text(encoding="utf-8")
        panel = self.read_frontend("ModelProviderPanel.vue")
        view = self.read_frontend("SettingsView.vue")
        self.assertIn('id="settingsApp"', html)
        for target in ("text", "image"):
            self.assertIn(f'target="{target}"', view)
        self.assertIn(':id="`${target}-model-select`"', panel)
        self.assertIn(':data-test="`${target}-model-input`"', panel)
        self.assertIn(':data-test="`fetch-${target}-models`"', panel)
        self.assertIn('api("/api/settings/models"', app)
        self.assertIn("base_url: provider.baseUrl.trim()", view)
        self.assertIn("api_key: provider.apiKey.trim()", view)

    def test_settings_exposes_both_image_backends(self):
        html = (ROOT / "console" / "static" / "index.html").read_text(encoding="utf-8")
        backend = self.read_frontend("ImageBackendPanel.vue")
        view = self.read_frontend("SettingsView.vue")

        self.assertIn('id="settingsApp"', html)
        self.assertIn('<option value="direct_api">', backend)
        self.assertIn('<option value="comfyui">', backend)
        self.assertIn("COMIC_PIPELINE_IMAGE_BACKEND: form.backend.imageBackend", view)
        self.assertIn("COMIC_PIPELINE_COMFY_CHECKPOINT: form.backend.comfyCheckpoint.trim()", view)
        self.assertIn("COMIC_PIPELINE_COMFY_LORA_NAME: form.backend.comfyLoraName.trim()", view)
        self.assertIn("COMIC_PIPELINE_COMFY_CONTROLNET_NAME: form.backend.comfyControlnetName.trim()", view)

    def test_direct_mode_keeps_comfyui_optional(self):
        backend = self.read_frontend("ImageBackendPanel.vue")

        self.assertIn('v-if="isComfy"', backend)
        self.assertIn("默认直连图片 API", backend)
        self.assertIn("无需启动独立生成服务", backend)

    def test_unsaved_backend_switch_does_not_reuse_previous_health_result(self):
        backend = self.read_frontend("ImageBackendPanel.vue")
        view = self.read_frontend("SettingsView.vue")

        self.assertIn("const pendingBackendSave", view)
        self.assertIn(':disabled="pendingBackendSave"', view)
        self.assertIn('if (pendingSave.value) return "保存后检查"', backend)
        self.assertIn(':disabled="pendingSave || checking || starting"', backend)

    def test_direct_preview_stays_in_the_console(self):
        app = (ROOT / "console" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('previewLink.textContent = externalPreview ? "打开 ComfyUI 预览" : "查看生成结果"', app)
        self.assertIn('activateModule("media")', app)

    def test_desktop_settings_route_provider_keys_through_safe_storage(self):
        app = (ROOT / "console" / "static" / "app.js").read_text(encoding="utf-8")
        view = self.read_frontend("SettingsView.vue")

        self.assertIn("window.comicDesktop?.saveProviderSecrets", app)
        self.assertIn("delete requestPayload.text.OPENAI_API_KEY", app)
        self.assertIn("delete requestPayload.image.OPENAI_API_KEY", app)
        self.assertNotIn('data-test="database-url"', view)


if __name__ == "__main__":
    unittest.main()
