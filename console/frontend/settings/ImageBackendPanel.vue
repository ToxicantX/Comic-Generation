<script setup lang="ts">
import { computed } from "vue";

import type {
  GenerationBackend,
  ImageBackend,
  ImageBackendForm,
} from "./types";

const props = defineProps<{
  form: ImageBackendForm;
  savedBackend: ImageBackend;
  diagnostics?: GenerationBackend | null;
  checking?: boolean;
  starting?: boolean;
}>();

const emit = defineEmits<{
  "update:form": [form: ImageBackendForm];
  check: [];
  start: [];
}>();

const isComfy = computed(() => props.form.imageBackend === "comfyui");
const pendingSave = computed(() => props.form.imageBackend !== props.savedBackend);
const source = computed(() => props.diagnostics?.diagnostics || props.diagnostics || null);
const ready = computed(() => !pendingSave.value && Boolean(source.value?.ok));
const badgeText = computed(() => {
  if (pendingSave.value) return "保存后检查";
  if (ready.value) return isComfy.value ? "ComfyUI 可用" : "直连 API 可用";
  return isComfy.value ? "ComfyUI 未就绪" : "直连 API 未就绪";
});
const modeNote = computed(() => isComfy.value
  ? "使用本地模型、LoRA、ControlNet 或可视化工作流时选择此模式。"
  : "默认直连图片 API，不访问 8188，也无需启动独立生成服务。",
);
const diagnosticsRows = computed(() => {
  if (pendingSave.value) {
    return [["状态", "后端类型已修改，请先保存设置，再检查当前图片后端。"]];
  }
  if (!source.value) {
    return [["状态", isComfy.value
      ? "尚未检查 ComfyUI。"
      : "直连图片 API 模式无需启动服务，检查后可查看接口和密钥状态。"]];
  }
  if ((source.value.image_backend || props.savedBackend) === "direct_api") {
    return [
      ["状态", source.value.ok ? "直连图片 API 已就绪" : "直连图片 API 未就绪"],
      ["接口", source.value.provider?.base_url || "使用默认 OpenAI 地址"],
      ["密钥", source.value.provider?.api_key_configured ? "已配置" : "未配置"],
      ["启动", "无需独立服务，不访问 8188"],
    ];
  }
  const paths = source.value.paths || {};
  const catalog = source.value.health?.model_catalog || {};
  const issues = [
    ...(catalog.missing_nodes || []).map((item) => `节点:${item}`),
    ...(catalog.missing_models || []).map((item) => `模型:${item}`),
  ];
  const modelSummary = ["checkpoints", "loras", "vae", "clip", "controlnet"]
    .map((key) => `${key}:${Number(paths[key]?.files || 0)}`)
    .join(" · ");
  const logText = source.value.ok
    ? "后端已运行，健康检查通过。"
    : (source.value.logs?.stderr?.tail || "").trim().split(/\r?\n/).slice(-4).join(" / ");
  return [
    ["状态", source.value.ok ? "健康检查通过" : "不可访问或检查未通过"],
    ["地址", `${source.value.comfy_url || "-"} / 端口 ${source.value.port_open ? "已打开" : "未打开"}`],
    ["入口", `${paths.main_py?.exists ? "main.py 存在" : "main.py 缺失"} · ${paths.python?.exists ? "Python 可用" : "Python 不可用"}`],
    ["模型", `${modelSummary}${issues.length ? ` · ${issues.join(" / ")}` : ""}`],
    ["日志", logText || source.value.start_blocker || "暂无错误日志"],
  ];
});

function patchForm(patch: Partial<ImageBackendForm>) {
  emit("update:form", { ...props.form, ...patch });
}

function fieldValue(event: Event) {
  return (event.target as HTMLInputElement | HTMLSelectElement).value;
}

function selectBackend(event: Event) {
  patchForm({ imageBackend: fieldValue(event) === "comfyui" ? "comfyui" : "direct_api" });
}
</script>

<template>
  <section class="backend-panel">
    <header class="panel-head">
      <div>
        <p>图片生成</p>
        <h2>生成后端</h2>
      </div>
      <span :class="['status-badge', pendingSave ? 'pending' : ready ? 'ok' : 'bad']">{{ badgeText }}</span>
    </header>

    <label class="field">
      <span>后端类型</span>
      <select
        data-test="image-backend"
        :value="form.imageBackend"
        @change="selectBackend"
      >
        <option value="direct_api">直连图片 API（默认）</option>
        <option value="comfyui">ComfyUI（本地模型）</option>
      </select>
    </label>
    <p class="note">{{ modeNote }}</p>

    <fieldset v-if="isComfy" class="comfy-fields">
      <legend>ComfyUI 配置</legend>
      <label class="field">
        <span>ComfyUI 地址</span>
        <input :value="form.comfyUrl" autocomplete="off" @input="patchForm({ comfyUrl: fieldValue($event) })">
      </label>
      <label class="field">
        <span>ComfyUI 根目录</span>
        <input :value="form.comfyRoot" autocomplete="off" @input="patchForm({ comfyRoot: fieldValue($event) })">
      </label>
      <label class="field wide">
        <span>Checkpoint 文件名</span>
        <input :value="form.comfyCheckpoint" autocomplete="off" @input="patchForm({ comfyCheckpoint: fieldValue($event) })">
      </label>

      <div class="field-grid three">
        <label class="field">
          <span>LoRA 文件名</span>
          <input :value="form.comfyLoraName" autocomplete="off" placeholder="可留空" @input="patchForm({ comfyLoraName: fieldValue($event) })">
        </label>
        <label class="field">
          <span>LoRA 模型权重</span>
          <input type="number" step="0.05" :value="form.comfyLoraStrengthModel" @input="patchForm({ comfyLoraStrengthModel: fieldValue($event) })">
        </label>
        <label class="field">
          <span>LoRA 文本权重</span>
          <input type="number" step="0.05" :value="form.comfyLoraStrengthClip" @input="patchForm({ comfyLoraStrengthClip: fieldValue($event) })">
        </label>
      </div>

      <div class="field-grid four">
        <label class="field">
          <span>ControlNet 文件名</span>
          <input :value="form.comfyControlnetName" autocomplete="off" placeholder="可留空" @input="patchForm({ comfyControlnetName: fieldValue($event) })">
        </label>
        <label class="field">
          <span>强度</span>
          <input type="number" min="0" step="0.05" :value="form.comfyControlnetStrength" @input="patchForm({ comfyControlnetStrength: fieldValue($event) })">
        </label>
        <label class="field">
          <span>开始百分比</span>
          <input type="number" min="0" max="0.99" step="0.05" :value="form.comfyControlnetStart" @input="patchForm({ comfyControlnetStart: fieldValue($event) })">
        </label>
        <label class="field">
          <span>结束百分比</span>
          <input type="number" min="0.01" max="1" step="0.05" :value="form.comfyControlnetEnd" @input="patchForm({ comfyControlnetEnd: fieldValue($event) })">
        </label>
      </div>

      <div class="field-grid four">
        <label class="field">
          <span>采样步数</span>
          <input type="number" min="1" step="1" :value="form.comfySteps" @input="patchForm({ comfySteps: fieldValue($event) })">
        </label>
        <label class="field">
          <span>CFG</span>
          <input type="number" min="0.1" step="0.1" :value="form.comfyCfg" @input="patchForm({ comfyCfg: fieldValue($event) })">
        </label>
        <label class="field">
          <span>采样器</span>
          <input :value="form.comfySampler" autocomplete="off" @input="patchForm({ comfySampler: fieldValue($event) })">
        </label>
        <label class="field">
          <span>调度器</span>
          <input :value="form.comfyScheduler" autocomplete="off" @input="patchForm({ comfyScheduler: fieldValue($event) })">
        </label>
      </div>
      <p class="note wide">只有分镜存在参考图且配置了 ControlNet 时，才会生成 ControlNet 节点链。</p>
    </fieldset>

    <label class="field">
      <span>输出目录</span>
      <input data-test="output-root" :value="form.outputRoot" autocomplete="off" @input="patchForm({ outputRoot: fieldValue($event) })">
    </label>

    <div class="actions">
      <button
        type="button"
        data-test="check-backend"
        :disabled="pendingSave || checking || starting"
        @click="emit('check')"
      >
        {{ checking ? "检查中..." : (isComfy ? "检查 ComfyUI" : "检查直连 API") }}
      </button>
      <button
        v-if="isComfy"
        class="primary"
        type="button"
        data-test="start-backend"
        :disabled="pendingSave || checking || starting"
        @click="emit('start')"
      >
        {{ starting ? "启动中..." : "启动 ComfyUI" }}
      </button>
    </div>

    <dl class="diagnostics">
      <div v-for="row in diagnosticsRows" :key="row[0]">
        <dt>{{ row[0] }}</dt>
        <dd>{{ row[1] }}</dd>
      </div>
    </dl>
  </section>
</template>

<style scoped>
.backend-panel {
  display: grid;
  align-content: start;
  gap: 12px;
  min-width: 0;
  padding: 16px;
  color: #e7e8ea;
  background: #181b20;
  border: 1px solid #343940;
  border-radius: 6px;
}

.panel-head,
.actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.panel-head p {
  margin: 0 0 3px;
  color: #9ba1aa;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

.panel-head h2 {
  margin: 0;
  font-size: 17px;
}

.status-badge {
  padding: 3px 7px;
  border: 1px solid #4a5059;
  border-radius: 4px;
  color: #b9bec5;
  font-size: 11px;
}

.status-badge.ok { color: #9fd5ac; border-color: #3d6748; }
.status-badge.bad { color: #e7a3a3; border-color: #704343; }
.status-badge.pending { color: #e5c778; border-color: #776538; }

.field {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.field > span {
  color: #b9bec5;
  font-size: 12px;
  font-weight: 650;
}

input,
select,
button {
  min-height: 34px;
  box-sizing: border-box;
  border: 1px solid #414750;
  border-radius: 4px;
  font: inherit;
}

input,
select {
  width: 100%;
  padding: 6px 9px;
  color: #f0f1f2;
  background: #101216;
}

button {
  padding: 6px 11px;
  color: #dfe2e6;
  background: #272b31;
  cursor: pointer;
}

button:hover:not(:disabled) { border-color: #747c86; background: #30353c; }
button:disabled { opacity: .5; cursor: not-allowed; }
button.primary { color: #111419; background: #d4b45f; border-color: #d4b45f; font-weight: 750; }

.comfy-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 11px;
  min-width: 0;
  margin: 0;
  padding: 12px;
  border: 1px solid #343940;
}

.comfy-fields legend {
  padding: 0 6px;
  color: #aeb4bc;
  font-size: 11px;
  font-weight: 700;
}

.field-grid {
  display: grid;
  grid-column: 1 / -1;
  gap: 10px;
}

.field-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.field-grid.four { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.wide { grid-column: 1 / -1; }

.note {
  margin: 0;
  color: #9299a3;
  font-size: 11px;
  line-height: 1.5;
}

.actions {
  justify-content: flex-start;
}

.diagnostics {
  display: grid;
  gap: 1px;
  margin: 0;
  overflow: hidden;
  background: #343940;
  border: 1px solid #343940;
  border-radius: 4px;
}

.diagnostics div {
  display: grid;
  grid-template-columns: 70px minmax(0, 1fr);
  gap: 10px;
  padding: 8px 9px;
  background: #111419;
}

.diagnostics dt {
  color: #939aa3;
  font-size: 11px;
}

.diagnostics dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  color: #c9cdd2;
  font-size: 12px;
}

@media (max-width: 1100px) {
  .comfy-fields,
  .field-grid.three,
  .field-grid.four { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
