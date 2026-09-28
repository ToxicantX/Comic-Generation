import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import SettingsView from "./SettingsView.vue";
import type {
  ConfigSnapshot,
  GenerationBackend,
  SettingsSavePayload,
  SettingsHealth,
  SettingsSummary,
  TestModelRequest,
} from "./types";

function configSnapshot(overrides: Partial<ConfigSnapshot> = {}): ConfigSnapshot {
  return {
    root: "E:\\workspace\\ComfyUIProjects\\comic-pipeline",
    config_path: "E:\\workspace\\ComfyUIProjects\\comic-pipeline\\config\\.env",
    text_env_path: "E:\\workspace\\ComfyUIProjects\\comic-pipeline\\config\\text.env",
    image_env_path: "E:\\workspace\\ComfyUIProjects\\comic-pipeline\\config\\image.env",
    config: {
      COMIC_PIPELINE_IMAGE_BACKEND: "direct_api",
      COMIC_PIPELINE_COMFY_URL: "http://127.0.0.1:8188",
      COMIC_PIPELINE_COMFY_ROOT: "E:\\ComfyUI",
      COMIC_PIPELINE_COMFY_OUTPUT_ROOT: "E:\\ComfyUI\\output",
      COMIC_PIPELINE_COMFY_CHECKPOINT: "comic.safetensors",
      COMIC_PIPELINE_COMFY_LORA_NAME: "",
      COMIC_PIPELINE_COMFY_LORA_STRENGTH_MODEL: "1.0",
      COMIC_PIPELINE_COMFY_LORA_STRENGTH_CLIP: "1.0",
      COMIC_PIPELINE_COMFY_CONTROLNET_NAME: "",
      COMIC_PIPELINE_COMFY_CONTROLNET_STRENGTH: "1.0",
      COMIC_PIPELINE_COMFY_CONTROLNET_START: "0.0",
      COMIC_PIPELINE_COMFY_CONTROLNET_END: "1.0",
      COMIC_PIPELINE_COMFY_STEPS: "28",
      COMIC_PIPELINE_COMFY_CFG: "7.0",
      COMIC_PIPELINE_COMFY_SAMPLER: "dpmpp_2m",
      COMIC_PIPELINE_COMFY_SCHEDULER: "karras",
      COMIC_PIPELINE_NOVEL_PATH: "old.txt",
      COMIC_PIPELINE_OUTPUT_ROOT: "E:\\comic-output",
      COMIC_PIPELINE_TEXT_ENV_PATH: "config/text.env",
      COMIC_PIPELINE_IMAGE_ENV_PATH: "config/image.env",
      COMIC_PIPELINE_TEXT_MODEL: "novel-v1",
      COMIC_PIPELINE_TEXT_MODEL_TIMEOUT: "300",
      COMIC_PIPELINE_TEXT_MODEL_STREAM: "true",
      COMIC_PIPELINE_IMAGE_MODEL: "image-v1",
      COMIC_PIPELINE_IMAGE_QUALITY: "auto",
      COMIC_PIPELINE_DEFAULT_PAGES: "8",
      COMIC_PIPELINE_ENCODING: "utf-8",
      COMIC_PIPELINE_ACTIVE_PROJECT: "old-project",
      CUSTOM_KEEP: "preserved",
    },
    projects: { active: "current-novel", items: [] },
    database: { schema_ready: true },
    text: { OPENAI_BASE_URL: "https://text.example/v1", OPENAI_API_KEY_CONFIGURED: true },
    image: { OPENAI_BASE_URL: "https://image.example/v1", OPENAI_API_KEY_CONFIGURED: true },
    ...overrides,
  };
}

const summary: SettingsSummary = {
  image_backend: "direct_api",
  models: {
    novel_model: "novel-v1",
    image_model: "image-v1",
    sources: { novel_model: "global", image_model: "project" },
  },
  paths: { output_root: "E:\\comic-output", sources: { output_root: "global" } },
  project: { slug: "current-novel", title: "当前小说" },
};

const health: SettingsHealth = {
  ok: false,
  checks: [
    { name: "postgres", label: "PostgreSQL", ok: true, message: "连接正常" },
    { name: "image_model", label: "图片生成模型", ok: false, message: "未配置" },
  ],
};

const directBackend: GenerationBackend = {
  ok: true,
  image_backend: "direct_api",
  provider: { base_url: "https://image.example/v1", api_key_configured: true },
};

function mountSettings(overrides: Record<string, unknown> = {}) {
  return mount(SettingsView, {
    props: {
      config: configSnapshot(),
      settingsSummary: summary,
      settingsHealth: health,
      generationBackend: directBackend,
      novelPath: "E:\\novels\\new.txt",
      defaultPages: 12,
      encoding: "utf-8-sig",
      ...overrides,
    },
  });
}

function emittedPayload<T>(wrapper: ReturnType<typeof mountSettings>, event: string, index = 0): T {
  return wrapper.emitted(event)?.[index]?.[0] as T;
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("SettingsView", () => {
  it("renders supplied status without requesting an API", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const wrapper = mountSettings();

    expect(wrapper.text()).toContain("当前小说");
    expect(wrapper.text()).toContain("1/2 通过");
    expect(wrapper.text()).toContain("https://image.example/v1");
    expect(wrapper.find("fieldset").exists()).toBe(false);
    expect(wrapper.find('[data-test="database-url"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("数据库由桌面运行时管理");
    expect(fetchSpy).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("emits a complete merged save payload while keeping provider secrets independent", async () => {
    const wrapper = mountSettings();
    await wrapper.get('[data-test="text-model-input"]').setValue("novel-v2");
    await wrapper.get('[data-test="image-model-input"]').setValue("image-v2");
    await wrapper.get('[data-test="text-base-url"]').setValue("https://text-v2.example/v1");
    await wrapper.get('[data-test="image-base-url"]').setValue("https://image-v2.example/v1");
    await wrapper.get('[data-test="text-api-key"]').setValue("   ");
    await wrapper.get('[data-test="image-api-key"]').setValue("image-secret");
    await wrapper.get('[data-test="save-settings"]').trigger("click");

    const payload = emittedPayload<SettingsSavePayload>(wrapper, "save");
    expect(payload).toBeTruthy();
    expect(payload.config.CUSTOM_KEEP).toBe("preserved");
    expect(payload.config.COMIC_PIPELINE_NOVEL_PATH).toBe("E:\\novels\\new.txt");
    expect(payload.config.COMIC_PIPELINE_DEFAULT_PAGES).toBe("12");
    expect(payload.config.COMIC_PIPELINE_ENCODING).toBe("utf-8-sig");
    expect(payload.config.COMIC_PIPELINE_ACTIVE_PROJECT).toBe("current-novel");
    expect(payload.config.COMIC_PIPELINE_TEXT_MODEL).toBe("novel-v2");
    expect(payload.config.COMIC_PIPELINE_IMAGE_MODEL).toBe("image-v2");
    expect(payload.config.COMIC_PIPELINE_DATABASE_URL).toBeUndefined();
    expect(payload.text).toEqual({ OPENAI_BASE_URL: "https://text-v2.example/v1" });
    expect(payload.image).toEqual({
      OPENAI_BASE_URL: "https://image-v2.example/v1",
      OPENAI_API_KEY: "image-secret",
    });
    wrapper.unmount();
  });

  it("emits independent model discovery and test contracts", async () => {
    const wrapper = mountSettings();
    await wrapper.get('[data-test="text-api-key"]').setValue("text-secret");
    await wrapper.get('[data-test="image-api-key"]').setValue("image-secret");
    await wrapper.get('[data-test="fetch-text-models"]').trigger("click");
    await wrapper.get('[data-test="fetch-image-models"]').trigger("click");
    await wrapper.get('[data-test="test-text-model"]').trigger("click");
    await wrapper.get('[data-test="test-image-model"]').trigger("click");

    expect(wrapper.emitted("fetch-models")).toEqual([
      [{ target: "text", base_url: "https://text.example/v1", api_key: "text-secret" }],
      [{ target: "image", base_url: "https://image.example/v1", api_key: "image-secret" }],
    ]);
    const tests = (wrapper.emitted("test-model") || []) as unknown as Array<[TestModelRequest]>;
    expect(tests[0][0]).toMatchObject({ target: "text", timeout: 120, live: false });
    expect(tests[1][0]).toMatchObject({ target: "image", timeout: 180, live: true });
    expect(tests[0][0].config.text.OPENAI_API_KEY).toBe("text-secret");
    expect(tests[0][0].config.image.OPENAI_API_KEY).toBe("image-secret");
    wrapper.unmount();
  });

  it("keeps fetched model selections independent and preserves manual entry mode", async () => {
    const wrapper = mountSettings({
      modelOptions: {
        text: ["novel-v2", "novel-v3"],
        image: ["image-v2", "image-v3"],
      },
    });
    await wrapper.get("#text-model-select").setValue("novel-v3");
    await wrapper.get("#image-model-select").setValue("image-v2");
    await wrapper.get("#text-model-select").setValue("");
    await wrapper.get('[data-test="text-model-input"]').setValue("custom-novel");

    expect(wrapper.find('[data-test="text-model-input"]').exists()).toBe(true);
    await wrapper.get('[data-test="save-settings"]').trigger("click");
    const payload = emittedPayload<SettingsSavePayload>(wrapper, "save");
    expect(payload.config.COMIC_PIPELINE_TEXT_MODEL).toBe("custom-novel");
    expect(payload.config.COMIC_PIPELINE_IMAGE_MODEL).toBe("image-v2");
    wrapper.unmount();
  });

  it("shows ComfyUI fields and blocks stale backend actions until the switch is saved", async () => {
    const wrapper = mountSettings();
    await wrapper.get('[data-test="image-backend"]').setValue("comfyui");

    expect(wrapper.find("fieldset").exists()).toBe(true);
    expect(wrapper.text()).toContain("后端类型已修改，请先保存设置");
    expect(wrapper.get('[data-test="check-backend"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-test="start-backend"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-test="test-image-model"]').attributes("disabled")).toBeDefined();

    await wrapper.get('[data-test="save-settings"]').trigger("click");
    expect(emittedPayload<SettingsSavePayload>(wrapper, "save").config.COMIC_PIPELINE_IMAGE_BACKEND).toBe("comfyui");
    wrapper.unmount();
  });

  it("emits health and saved ComfyUI backend actions without owning transport", async () => {
    const comfyConfig = configSnapshot({
      config: {
        ...configSnapshot().config,
        COMIC_PIPELINE_IMAGE_BACKEND: "comfyui",
      },
    });
    const wrapper = mountSettings({
      config: comfyConfig,
      settingsSummary: { ...summary, image_backend: "comfyui" },
      generationBackend: {
        ok: false,
        image_backend: "comfyui",
        comfy_url: "http://127.0.0.1:8188",
        paths: {},
      },
    });

    await wrapper.get('[data-test="health-check"]').trigger("click");
    await wrapper.get('[data-test="check-backend"]').trigger("click");
    await wrapper.get('[data-test="start-backend"]').trigger("click");

    expect(wrapper.emitted("health-check")).toHaveLength(1);
    expect(wrapper.emitted("backend-check")).toHaveLength(1);
    expect(wrapper.emitted("backend-start")).toEqual([[{ wait_seconds: 20 }]]);
    wrapper.unmount();
  });

  it("resets unsaved fields when a new configuration snapshot arrives", async () => {
    const wrapper = mountSettings();
    await wrapper.get('[data-test="text-model-input"]').setValue("unsaved-model");
    await wrapper.setProps({
      config: configSnapshot({
        config: {
          ...configSnapshot().config,
          COMIC_PIPELINE_TEXT_MODEL: "server-model",
        },
      }),
      novelPath: "E:\\novels\\server.txt",
    });
    await wrapper.get('[data-test="save-settings"]').trigger("click");

    const payload = emittedPayload<SettingsSavePayload>(wrapper, "save");
    expect(payload.config.COMIC_PIPELINE_TEXT_MODEL).toBe("server-model");
    expect(payload.config.COMIC_PIPELINE_NOVEL_PATH).toBe("E:\\novels\\server.txt");
    wrapper.unmount();
  });

  it("only exposes approved desktop storage actions when the native host is available", async () => {
    const wrapper = mountSettings({
      desktopInfo: {
        platform: "win32",
        version: "0.1.0",
        serviceUrl: "http://127.0.0.1:8199",
        runtimeMode: "local",
        directories: {
          output: "C:\\Users\\Ada\\Documents\\Comic Pipeline\\output",
          backups: "C:\\Users\\Ada\\AppData\\Roaming\\Comic Pipeline\\backups",
          logs: "C:\\Users\\Ada\\AppData\\Roaming\\Comic Pipeline\\logs",
        },
      },
    });

    await wrapper.get('[data-test="open-output-directory"]').trigger("click");
    await wrapper.get('[data-test="open-backups-directory"]').trigger("click");
    await wrapper.get('[data-test="open-logs-directory"]').trigger("click");

    expect(wrapper.emitted("open-directory")).toEqual([["output"], ["backups"], ["logs"]]);
    wrapper.unmount();
  });

  it("forwards desktop update actions without owning the update transport", async () => {
    const desktopInfo = {
      platform: "win32",
      version: "0.1.0",
      serviceUrl: "http://127.0.0.1:8199",
      runtimeMode: "local",
      directories: {
        output: "C:\\Users\\Ada\\Documents\\Comic Pipeline\\output",
        backups: "C:\\Users\\Ada\\AppData\\Roaming\\Comic Pipeline\\backups",
        logs: "C:\\Users\\Ada\\AppData\\Roaming\\Comic Pipeline\\logs",
      },
    };
    const wrapper = mountSettings({
      desktopInfo,
      desktopUpdate: {
        enabled: true,
        status: "idle",
        currentVersion: "0.1.0",
        availableVersion: null,
        progress: null,
        lastCheckedAt: null,
        message: "尚未检查更新",
      },
    });

    await wrapper.get('[data-test="check-update"]').trigger("click");
    expect(wrapper.emitted("check-update")).toEqual([[]]);

    await wrapper.setProps({
      desktopUpdate: {
        enabled: true,
        status: "downloaded",
        currentVersion: "0.1.0",
        availableVersion: "0.2.0",
        progress: null,
        lastCheckedAt: "2026-09-29T00:00:00.000Z",
        message: "新版本已下载，可重启完成升级",
      },
    });
    await wrapper.get('[data-test="install-update"]').trigger("click");
    expect(wrapper.emitted("install-update")).toEqual([[]]);
    wrapper.unmount();
  });
});
