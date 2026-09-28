<script setup lang="ts">
import { computed, reactive, watch } from "vue";

import DesktopStoragePanel from "./DesktopStoragePanel.vue";
import DesktopUpdatePanel from "./DesktopUpdatePanel.vue";
import ImageBackendPanel from "./ImageBackendPanel.vue";
import ModelProviderPanel from "./ModelProviderPanel.vue";
import SettingsStatusPanel from "./SettingsStatusPanel.vue";
import type {
  ConfigSnapshot,
  DesktopDirectoryKey,
  DesktopInfo,
  DesktopUpdateState,
  FetchModelsRequest,
  GenerationBackend,
  ImageBackend,
  ModelProviderForm,
  ModelTarget,
  ModelTestResult,
  SettingsActivity,
  SettingsFormState,
  SettingsHealth,
  SettingsSavePayload,
  SettingsSummary,
  TestModelRequest,
} from "./types";

const props = withDefaults(defineProps<{
  config: ConfigSnapshot;
  settingsSummary: SettingsSummary | null;
  settingsHealth: SettingsHealth | null;
  generationBackend: GenerationBackend | null;
  novelPath: string;
  defaultPages: string | number;
  encoding: string;
  modelOptions?: Partial<Record<ModelTarget, string[]>>;
  modelListMessages?: Partial<Record<ModelTarget, string>>;
  modelTestResults?: Partial<Record<ModelTarget, ModelTestResult | null>>;
  activity?: SettingsActivity;
  desktopInfo?: DesktopInfo | null;
  desktopUpdate?: DesktopUpdateState | null;
}>(), {
  modelOptions: () => ({}),
  modelListMessages: () => ({}),
  modelTestResults: () => ({}),
  activity: () => ({}),
  desktopInfo: null,
  desktopUpdate: null,
});

const emit = defineEmits<{
  save: [payload: SettingsSavePayload];
  "health-check": [];
  "fetch-models": [request: FetchModelsRequest];
  "test-model": [request: TestModelRequest];
  "backend-check": [];
  "backend-start": [request: { wait_seconds: number }];
  "open-directory": [key: DesktopDirectoryKey];
  "check-update": [];
  "install-update": [];
}>();

const form = reactive<SettingsFormState>(formFromSnapshot());

const savedImageBackend = computed<ImageBackend>(() => normalizeBackend(
  props.settingsSummary?.image_backend
    || props.config.config.COMIC_PIPELINE_IMAGE_BACKEND,
));
const pendingBackendSave = computed(() => form.backend.imageBackend !== savedImageBackend.value);
const textKeyConfigured = computed(() => Boolean(props.config.text?.OPENAI_API_KEY_CONFIGURED));
const imageKeyConfigured = computed(() => Boolean(props.config.image?.OPENAI_API_KEY_CONFIGURED));
const desktopUpdateState = computed<DesktopUpdateState | null>(() => {
  if (!props.desktopInfo) return null;
  return props.desktopUpdate || {
    enabled: false,
    status: "disabled",
    currentVersion: props.desktopInfo.version,
    availableVersion: null,
    progress: null,
    lastCheckedAt: null,
    message: "更新状态暂不可用",
  };
});

watch(
  () => [props.config, props.novelPath, props.defaultPages, props.encoding] as const,
  () => Object.assign(form, formFromSnapshot()),
  { deep: true },
);

function normalizeBackend(value?: string): ImageBackend {
  return value === "comfyui" ? "comfyui" : "direct_api";
}

function configValue(key: string, fallback = "") {
  return props.config.config[key] || fallback;
}

function formFromSnapshot(): SettingsFormState {
  return {
    backend: {
      imageBackend: normalizeBackend(configValue("COMIC_PIPELINE_IMAGE_BACKEND", "direct_api")),
      comfyUrl: configValue("COMIC_PIPELINE_COMFY_URL"),
      comfyRoot: configValue("COMIC_PIPELINE_COMFY_ROOT"),
      comfyCheckpoint: configValue("COMIC_PIPELINE_COMFY_CHECKPOINT"),
      comfyLoraName: configValue("COMIC_PIPELINE_COMFY_LORA_NAME"),
      comfyLoraStrengthModel: configValue("COMIC_PIPELINE_COMFY_LORA_STRENGTH_MODEL", "1.0"),
      comfyLoraStrengthClip: configValue("COMIC_PIPELINE_COMFY_LORA_STRENGTH_CLIP", "1.0"),
      comfyControlnetName: configValue("COMIC_PIPELINE_COMFY_CONTROLNET_NAME"),
      comfyControlnetStrength: configValue("COMIC_PIPELINE_COMFY_CONTROLNET_STRENGTH", "1.0"),
      comfyControlnetStart: configValue("COMIC_PIPELINE_COMFY_CONTROLNET_START", "0.0"),
      comfyControlnetEnd: configValue("COMIC_PIPELINE_COMFY_CONTROLNET_END", "1.0"),
      comfySteps: configValue("COMIC_PIPELINE_COMFY_STEPS", "28"),
      comfyCfg: configValue("COMIC_PIPELINE_COMFY_CFG", "7.0"),
      comfySampler: configValue("COMIC_PIPELINE_COMFY_SAMPLER", "dpmpp_2m"),
      comfyScheduler: configValue("COMIC_PIPELINE_COMFY_SCHEDULER", "karras"),
      outputRoot: configValue("COMIC_PIPELINE_OUTPUT_ROOT"),
    },
    text: {
      model: configValue("COMIC_PIPELINE_TEXT_MODEL"),
      baseUrl: props.config.text?.OPENAI_BASE_URL || "",
      apiKey: "",
      timeout: configValue("COMIC_PIPELINE_TEXT_MODEL_TIMEOUT", "300"),
      stream: configValue("COMIC_PIPELINE_TEXT_MODEL_STREAM", "true").toLowerCase() !== "false",
      quality: "auto",
    },
    image: {
      model: configValue("COMIC_PIPELINE_IMAGE_MODEL"),
      baseUrl: props.config.image?.OPENAI_BASE_URL || "",
      apiKey: "",
      timeout: "180",
      stream: false,
      quality: configValue("COMIC_PIPELINE_IMAGE_QUALITY", "auto"),
    },
  };
}

function finiteNumber(value: string, fallback: number, minimum: number, maximum?: number, integer = false) {
  const parsed = integer ? Number.parseInt(value, 10) : Number.parseFloat(value);
  const normalized = Number.isFinite(parsed) ? parsed : fallback;
  const bounded = Math.max(minimum, maximum === undefined ? normalized : Math.min(normalized, maximum));
  return String(integer ? Math.trunc(bounded) : bounded);
}

function providerPayload(provider: ModelProviderForm) {
  const payload: { OPENAI_BASE_URL: string; OPENAI_API_KEY?: string } = {
    OPENAI_BASE_URL: provider.baseUrl.trim(),
  };
  const apiKey = provider.apiKey.trim();
  if (apiKey) payload.OPENAI_API_KEY = apiKey;
  return payload;
}

function buildSavePayload(): SettingsSavePayload {
  return {
    config: {
      ...props.config.config,
      COMIC_PIPELINE_IMAGE_BACKEND: form.backend.imageBackend,
      COMIC_PIPELINE_COMFY_URL: form.backend.comfyUrl.trim(),
      COMIC_PIPELINE_COMFY_ROOT: form.backend.comfyRoot.trim(),
      COMIC_PIPELINE_COMFY_CHECKPOINT: form.backend.comfyCheckpoint.trim(),
      COMIC_PIPELINE_COMFY_LORA_NAME: form.backend.comfyLoraName.trim(),
      COMIC_PIPELINE_COMFY_LORA_STRENGTH_MODEL: finiteNumber(form.backend.comfyLoraStrengthModel, 1, 0),
      COMIC_PIPELINE_COMFY_LORA_STRENGTH_CLIP: finiteNumber(form.backend.comfyLoraStrengthClip, 1, 0),
      COMIC_PIPELINE_COMFY_CONTROLNET_NAME: form.backend.comfyControlnetName.trim(),
      COMIC_PIPELINE_COMFY_CONTROLNET_STRENGTH: finiteNumber(form.backend.comfyControlnetStrength, 1, 0),
      COMIC_PIPELINE_COMFY_CONTROLNET_START: finiteNumber(form.backend.comfyControlnetStart, 0, 0, 0.99),
      COMIC_PIPELINE_COMFY_CONTROLNET_END: finiteNumber(form.backend.comfyControlnetEnd, 1, 0.01, 1),
      COMIC_PIPELINE_COMFY_STEPS: finiteNumber(form.backend.comfySteps, 28, 1, undefined, true),
      COMIC_PIPELINE_COMFY_CFG: finiteNumber(form.backend.comfyCfg, 7, 0.1),
      COMIC_PIPELINE_COMFY_SAMPLER: form.backend.comfySampler.trim(),
      COMIC_PIPELINE_COMFY_SCHEDULER: form.backend.comfyScheduler.trim(),
      COMIC_PIPELINE_NOVEL_PATH: props.novelPath,
      COMIC_PIPELINE_OUTPUT_ROOT: form.backend.outputRoot.trim(),
      COMIC_PIPELINE_TEXT_MODEL: form.text.model.trim(),
      COMIC_PIPELINE_TEXT_MODEL_TIMEOUT: finiteNumber(form.text.timeout, 300, 30, undefined, true),
      COMIC_PIPELINE_TEXT_MODEL_STREAM: form.text.stream ? "true" : "false",
      COMIC_PIPELINE_IMAGE_MODEL: form.image.model.trim(),
      COMIC_PIPELINE_IMAGE_QUALITY: form.image.quality,
      COMIC_PIPELINE_DEFAULT_PAGES: String(props.defaultPages),
      COMIC_PIPELINE_ENCODING: props.encoding,
      COMIC_PIPELINE_ACTIVE_PROJECT: props.config.projects?.active
        || configValue("COMIC_PIPELINE_ACTIVE_PROJECT", "sou_shen_ji"),
    },
    text: providerPayload(form.text),
    image: providerPayload(form.image),
  };
}

function updateProvider(target: ModelTarget, value: ModelProviderForm) {
  form[target] = value;
}

function fetchModels(target: ModelTarget) {
  const provider = form[target];
  emit("fetch-models", {
    target,
    base_url: provider.baseUrl.trim(),
    api_key: provider.apiKey.trim(),
  });
}

function testModel(target: ModelTarget) {
  const textTimeout = Number.parseInt(form.text.timeout, 10) || 300;
  emit("test-model", {
    target,
    timeout: target === "text" ? Math.min(Math.max(textTimeout, 30), 120) : 180,
    live: target === "image" && form.backend.imageBackend === "direct_api",
    config: buildSavePayload(),
  });
}
</script>

<template>
  <section class="settings-view">
    <header class="settings-header">
      <div>
        <p>全局设置</p>
        <h1>运行配置</h1>
        <small>模型、生成后端和数据库保持独立配置；密钥只提交给宿主层，不在组件内存储或请求接口。</small>
      </div>
      <button
        class="save-button"
        type="button"
        data-test="save-settings"
        :disabled="activity.saving"
        @click="emit('save', buildSavePayload())"
      >
        {{ activity.saving ? "保存中..." : "保存设置" }}
      </button>
    </header>

    <SettingsStatusPanel
      :config="config"
      :summary="settingsSummary"
      :health="settingsHealth"
      :image-backend="form.backend.imageBackend"
      :checking="activity.checkingHealth"
      @health-check="emit('health-check')"
    />

    <section class="settings-grid">
      <ImageBackendPanel
        class="backend"
        :form="form.backend"
        :saved-backend="savedImageBackend"
        :diagnostics="generationBackend"
        :checking="activity.checkingBackend"
        :starting="activity.startingBackend"
        @update:form="form.backend = $event"
        @check="emit('backend-check')"
        @start="emit('backend-start', { wait_seconds: 20 })"
      />

      <ModelProviderPanel
        target="text"
        :form="form.text"
        :models="modelOptions.text || []"
        :key-configured="textKeyConfigured"
        :image-backend="form.backend.imageBackend"
        :fetching="activity.fetchingModels?.text"
        :testing="activity.testingModels?.text"
        :model-list-message="modelListMessages.text"
        :test-result="modelTestResults.text"
        @update:form="updateProvider('text', $event)"
        @fetch-models="fetchModels('text')"
        @test-model="testModel('text')"
      />

      <ModelProviderPanel
        target="image"
        :form="form.image"
        :models="modelOptions.image || []"
        :key-configured="imageKeyConfigured"
        :image-backend="form.backend.imageBackend"
        :disabled="pendingBackendSave"
        :fetching="activity.fetchingModels?.image"
        :testing="activity.testingModels?.image"
        :model-list-message="modelListMessages.image"
        :test-result="modelTestResults.image"
        @update:form="updateProvider('image', $event)"
        @fetch-models="fetchModels('image')"
        @test-model="testModel('image')"
      />

      <section class="compact-panel">
        <header>
          <div>
            <p>PostgreSQL</p>
            <h2>数据库</h2>
          </div>
          <span :class="['status-badge', config.database?.schema_ready ? 'ok' : 'bad']">
            {{ config.database?.schema_ready ? "已连接" : "未连接" }}
          </span>
        </header>
        <small>{{ config.database?.schema_ready ? "数据库由桌面运行时管理，作品、章节、审核状态和任务索引将自动持久化。" : (config.database?.error || "PostgreSQL 未就绪。") }}</small>
      </section>

      <section class="compact-panel import-snapshot">
        <header>
          <div>
            <p>导入向导</p>
            <h2>外部字段快照</h2>
          </div>
          <span class="status-badge">只读合并</span>
        </header>
        <dl>
          <div><dt>小说文件</dt><dd>{{ novelPath || "未选择" }}</dd></div>
          <div><dt>默认页数</dt><dd>{{ defaultPages }}</dd></div>
          <div><dt>文本编码</dt><dd>{{ encoding || "未设置" }}</dd></div>
        </dl>
        <small>这些字段由导入向导管理，保存设置时会原样合并，避免被设置页覆盖。</small>
      </section>

      <DesktopStoragePanel
        v-if="desktopInfo"
        :info="desktopInfo"
        @open="emit('open-directory', $event)"
      />

      <DesktopUpdatePanel
        v-if="desktopUpdateState"
        :state="desktopUpdateState"
        @check="emit('check-update')"
        @install="emit('install-update')"
      />
    </section>
  </section>
</template>

<style scoped>
.settings-view {
  display: grid;
  gap: 12px;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: 16px;
  color: #e7e8ea;
  background: #101216;
}

.settings-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 2px 2px 8px;
  border-bottom: 1px solid #30353c;
}

.settings-header p,
.compact-panel header p {
  margin: 0 0 3px;
  color: #9ba1aa;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

.settings-header h1 {
  margin: 0;
  font-size: 22px;
  line-height: 1.2;
}

.settings-header small {
  display: block;
  margin-top: 5px;
  color: #9299a3;
  font-size: 11px;
}

.save-button {
  min-height: 36px;
  padding: 7px 14px;
  color: #111419;
  background: #d4b45f;
  border: 1px solid #d4b45f;
  border-radius: 4px;
  font: inherit;
  font-weight: 750;
  cursor: pointer;
}

.save-button:disabled { opacity: .5; cursor: not-allowed; }

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  align-items: start;
}

.backend { grid-column: 1 / -1; }

.compact-panel {
  display: grid;
  gap: 11px;
  min-width: 0;
  padding: 16px;
  background: #181b20;
  border: 1px solid #343940;
  border-radius: 6px;
}

.compact-panel header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.compact-panel h2 {
  margin: 0;
  font-size: 17px;
}

.status-badge {
  padding: 3px 7px;
  color: #b9bec5;
  border: 1px solid #4a5059;
  border-radius: 4px;
  font-size: 11px;
}

.status-badge.ok { color: #9fd5ac; border-color: #3d6748; }
.status-badge.bad { color: #e7a3a3; border-color: #704343; }

.compact-panel label {
  display: grid;
  gap: 6px;
}

.compact-panel label span {
  color: #b9bec5;
  font-size: 12px;
  font-weight: 650;
}

.compact-panel input {
  width: 100%;
  min-height: 34px;
  box-sizing: border-box;
  padding: 6px 9px;
  color: #f0f1f2;
  background: #101216;
  border: 1px solid #414750;
  border-radius: 4px;
  font: inherit;
}

.compact-panel small {
  color: #9299a3;
  font-size: 11px;
  line-height: 1.5;
}

.import-snapshot dl {
  display: grid;
  gap: 1px;
  margin: 0;
  overflow: hidden;
  background: #343940;
  border: 1px solid #343940;
}

.import-snapshot dl div {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 10px;
  padding: 8px 9px;
  background: #111419;
}

.import-snapshot dt {
  color: #8c939c;
  font-size: 11px;
}

.import-snapshot dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: #cdd1d6;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1100px) {
  .settings-grid { grid-template-columns: minmax(0, 1fr); }
  .backend { grid-column: auto; }
}
</style>
