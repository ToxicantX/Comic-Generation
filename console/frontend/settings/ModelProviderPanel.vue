<script setup lang="ts">
import { computed } from "vue";

import type {
  ImageBackend,
  ModelProviderForm,
  ModelTarget,
  ModelTestResult,
} from "./types";

const props = defineProps<{
  target: ModelTarget;
  form: ModelProviderForm;
  models: string[];
  keyConfigured: boolean;
  imageBackend: ImageBackend;
  disabled?: boolean;
  fetching?: boolean;
  testing?: boolean;
  modelListMessage?: string;
  testResult?: ModelTestResult | null;
}>();

const emit = defineEmits<{
  "update:form": [form: ModelProviderForm];
  "fetch-models": [];
  "test-model": [];
}>();

const isText = computed(() => props.target === "text");
const title = computed(() => isText.value ? "小说处理" : "图片生成");
const eyebrow = computed(() => isText.value ? "文本模型" : "图片模型");
const modelLabel = computed(() => isText.value ? "小说处理模型" : "图片生成模型");
const catalogOptions = computed(() => {
  return [...new Set(props.models.filter(Boolean))];
});
const usesManualModel = computed(() => !catalogOptions.value.includes(props.form.model));
const keyDetail = computed(() => {
  if (props.keyConfigured) return `${title.value}密钥已配置。留空保存不会覆盖现有密钥。`;
  if (!isText.value && props.imageBackend === "comfyui") {
    return "本地模型工作流无需图片 API Key；仅云端图片节点需要配置。";
  }
  return `${title.value}密钥未配置，填写后保存；页面不会回显明文。`;
});
const testButtonText = computed(() => {
  if (props.testing) return "测试中...";
  if (!isText.value && props.imageBackend === "comfyui") return "检查本地模型环境";
  return `测试${title.value}模型`;
});
const resultClass = computed(() => {
  if (!props.testResult) return "neutral";
  return props.testResult.ok ? "ok" : "bad";
});
const resultDetail = computed(() => {
  const seconds = props.testResult?.detail?.elapsed_seconds;
  if (seconds) return `耗时 ${seconds} 秒`;
  return props.testResult?.dry_run ? "未生成图片" : "";
});

function patchForm(patch: Partial<ModelProviderForm>) {
  emit("update:form", { ...props.form, ...patch });
}

function fieldValue(event: Event) {
  return (event.target as HTMLInputElement | HTMLSelectElement).value;
}

function checkedValue(event: Event) {
  return (event.target as HTMLInputElement).checked;
}

function selectModel(event: Event) {
  patchForm({ model: fieldValue(event) });
}
</script>

<template>
  <section class="provider-panel" :data-provider="target">
    <header class="panel-head">
      <div>
        <p>{{ eyebrow }}</p>
        <h2>{{ title }}</h2>
      </div>
      <span :class="['status-badge', keyConfigured || (!isText && imageBackend === 'comfyui') ? 'ok' : 'bad']">
        {{ keyConfigured ? "已配置" : (!isText && imageBackend === "comfyui" ? "本地可选" : "未配置") }}
      </span>
    </header>

    <div class="model-picker">
      <label :for="`${target}-model-select`">{{ modelLabel }}</label>
      <div class="model-row">
        <select
          :id="`${target}-model-select`"
          :value="usesManualModel ? '' : form.model"
          :disabled="fetching || testing"
          @change="selectModel"
        >
          <option v-for="model in catalogOptions" :key="model" :value="model">{{ model }}</option>
          <option value="">手动输入</option>
        </select>
        <button
          type="button"
          :data-test="`fetch-${target}-models`"
          :disabled="fetching || testing"
          @click="emit('fetch-models')"
        >
          {{ fetching ? "获取中..." : "获取模型" }}
        </button>
      </div>
      <input
        v-if="usesManualModel"
        :id="`${target}-model-input`"
        :data-test="`${target}-model-input`"
        :value="form.model"
        :aria-label="`手动输入${modelLabel}`"
        autocomplete="off"
        placeholder="模型名称"
        @input="patchForm({ model: fieldValue($event) })"
      >
      <small v-if="modelListMessage" class="status-line" role="status">{{ modelListMessage }}</small>
    </div>

    <template v-if="isText">
      <p class="note">用于小说导入增强、章节细读、全书设定扫描和提示词整理。</p>
      <label class="field">
        <span>长文本超时秒数</span>
        <input
          data-test="text-timeout"
          type="number"
          min="30"
          step="30"
          :value="form.timeout"
          @input="patchForm({ timeout: fieldValue($event) })"
        >
      </label>
      <label class="toggle">
        <input
          data-test="text-stream"
          type="checkbox"
          :checked="form.stream"
          @change="patchForm({ stream: checkedValue($event) })"
        >
        <span>启用流式响应</span>
      </label>
    </template>
    <template v-else>
      <p class="note">直连 API 使用此模型；ComfyUI 的本地模型由工作流选择。</p>
      <label class="field">
        <span>图片生成质量</span>
        <select data-test="image-quality" :value="form.quality" @change="patchForm({ quality: fieldValue($event) })">
          <option value="auto">自动</option>
          <option value="low">低（更快）</option>
          <option value="medium">中</option>
          <option value="high">高</option>
        </select>
      </label>
    </template>

    <label class="field">
      <span>{{ title }}接口地址</span>
      <input
        :data-test="`${target}-base-url`"
        :value="form.baseUrl"
        autocomplete="off"
        @input="patchForm({ baseUrl: fieldValue($event) })"
      >
    </label>
    <label class="field">
      <span>{{ title }} API Key</span>
      <input
        :data-test="`${target}-api-key`"
        :value="form.apiKey"
        type="password"
        autocomplete="new-password"
        placeholder="留空表示不修改"
        @input="patchForm({ apiKey: fieldValue($event) })"
      >
    </label>
    <p class="note">{{ keyDetail }}</p>

    <button
      class="primary"
      type="button"
      :data-test="`test-${target}-model`"
      :disabled="disabled || testing || fetching"
      @click="emit('test-model')"
    >
      {{ testButtonText }}
    </button>
    <div :class="['test-result', resultClass]" role="status">
      <strong v-if="testResult">{{ testResult.ok ? "测试通过" : "测试失败" }}</strong>
      <span>{{ testResult?.message || `尚未测试${title}模型。` }}</span>
      <small v-if="resultDetail">{{ resultDetail }}</small>
    </div>
  </section>
</template>

<style scoped>
.provider-panel {
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
.model-row {
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
  line-height: 1.25;
}

.status-badge {
  flex: 0 0 auto;
  padding: 3px 7px;
  border: 1px solid #4a5059;
  border-radius: 4px;
  color: #b9bec5;
  font-size: 11px;
}

.status-badge.ok {
  color: #9fd5ac;
  border-color: #3d6748;
}

.status-badge.bad {
  color: #e7a3a3;
  border-color: #704343;
}

.model-picker,
.field {
  display: grid;
  gap: 6px;
}

.model-picker > label,
.field > span {
  color: #b9bec5;
  font-size: 12px;
  font-weight: 650;
}

.model-row select {
  min-width: 0;
  flex: 1 1 auto;
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

button:hover:not(:disabled) {
  border-color: #747c86;
  background: #30353c;
}

button:disabled {
  opacity: .5;
  cursor: not-allowed;
}

button.primary {
  justify-self: start;
  color: #111419;
  background: #d4b45f;
  border-color: #d4b45f;
  font-weight: 750;
}

.toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #c9cdd2;
  font-size: 12px;
}

.toggle input {
  width: 16px;
  min-height: 16px;
}

.note,
.status-line {
  margin: 0;
  color: #9299a3;
  font-size: 11px;
  line-height: 1.5;
}

.test-result {
  display: grid;
  gap: 3px;
  padding: 9px 10px;
  color: #aeb4bc;
  background: #111419;
  border-left: 3px solid #4a5059;
  font-size: 12px;
}

.test-result.ok {
  border-color: #548963;
}

.test-result.bad {
  border-color: #9a5656;
}

.test-result small {
  color: #858c95;
}
</style>
