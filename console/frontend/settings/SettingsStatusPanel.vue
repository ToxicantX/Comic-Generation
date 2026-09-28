<script setup lang="ts">
import { computed } from "vue";

import type {
  ConfigSnapshot,
  ImageBackend,
  SettingsHealth,
  SettingsSummary,
} from "./types";

const props = defineProps<{
  config: ConfigSnapshot;
  summary?: SettingsSummary | null;
  health?: SettingsHealth | null;
  imageBackend: ImageBackend;
  checking?: boolean;
}>();

const emit = defineEmits<{
  "health-check": [];
}>();

const healthChecks = computed(() => props.health?.checks || []);
const passedCount = computed(() => healthChecks.value.filter((item) => item.ok).length);
const healthLabel = computed(() => {
  if (!props.health) return "未测试";
  return props.health.ok ? "全部通过" : `${passedCount.value}/${healthChecks.value.length} 通过`;
});
const sourceRows = computed(() => [
  {
    title: "流水线配置",
    path: props.config.config_path || "config/.env",
    detail: "图片后端、ComfyUI 参数、路径、数据库和当前小说项目。",
    state: "已读取",
    ok: true,
  },
  {
    title: "小说处理密钥",
    path: props.config.text_env_path || "config/text.env",
    detail: "独立保存小说处理接口地址和 API Key。",
    state: props.config.text?.OPENAI_API_KEY_CONFIGURED ? "已配置" : "未配置",
    ok: Boolean(props.config.text?.OPENAI_API_KEY_CONFIGURED),
  },
  {
    title: "图片生成密钥",
    path: props.config.image_env_path || "config/image.env",
    detail: "独立保存图片生成接口地址和 API Key。",
    state: props.config.image?.OPENAI_API_KEY_CONFIGURED
      ? "已配置"
      : (props.imageBackend === "comfyui" ? "本地可选" : "未配置"),
    ok: Boolean(props.config.image?.OPENAI_API_KEY_CONFIGURED || props.imageBackend === "comfyui"),
  },
  {
    title: "PostgreSQL 数据",
    path: "作品、章节、审核与任务索引",
    detail: "数据库连接值保留在本地配置中，不在状态面板回显凭据。",
    state: props.config.database?.schema_ready ? "已连接" : "未连接",
    ok: Boolean(props.config.database?.schema_ready),
  },
]);
const effectiveRows = computed(() => {
  const models = props.summary?.models || {};
  const paths = props.summary?.paths || {};
  return [
    ["图片生成后端", props.summary?.image_backend === "comfyui" ? "ComfyUI（本地模型）" : "直连图片 API", "全局配置"],
    ["小说处理模型", models.novel_model || "-", sourceLabel(models.sources?.novel_model)],
    ["图片生成模型", models.image_model || "-", sourceLabel(models.sources?.image_model)],
    ["输出目录", paths.output_root || "-", sourceLabel(paths.sources?.output_root)],
  ];
});

function sourceLabel(value?: string) {
  return value === "project" ? "当前小说项目" : "全局设置";
}

function failedAction(name?: string) {
  const actions: Record<string, string> = {
    postgres: "检查 PostgreSQL 服务、账号、密码和端口。",
    image_backend: props.imageBackend === "comfyui"
      ? "确认 ComfyUI 已启动，或使用生成后端面板启动。"
      : "配置图片 API Key 后测试图片生成模型。",
    text_api_key: "填写有效的小说处理 API Key 后保存。",
    image_api_key: "填写有效的图片生成 API Key 后保存。",
    output_root: "确认输出目录存在且当前用户可写。",
    novel_model: "选择或手动填写可用的小说处理模型。",
    image_model: "选择或手动填写可用的图片生成模型。",
  };
  return actions[name || ""] || "检查对应配置项后重新测试。";
}
</script>

<template>
  <section class="status-layout">
    <section class="status-panel">
      <header class="panel-head">
        <div>
          <p>配置来源</p>
          <h2>写入位置与职责</h2>
        </div>
      </header>
      <div class="source-list">
        <article v-for="(row, index) in sourceRows" :key="row.title" class="source-row">
          <span class="source-index">{{ String(index + 1).padStart(2, "0") }}</span>
          <div>
            <header>
              <strong>{{ row.title }}</strong>
              <em :class="row.ok ? 'ok' : 'bad'">{{ row.state }}</em>
            </header>
            <p>{{ row.detail }}</p>
            <code>{{ row.path }}</code>
          </div>
        </article>
      </div>
    </section>

    <section class="status-panel">
      <header class="panel-head">
        <div>
          <p>连接测试</p>
          <h2>当前配置状态</h2>
        </div>
        <div class="health-actions">
          <span :class="['health-badge', health?.ok ? 'ok' : health ? 'bad' : 'neutral']">{{ healthLabel }}</span>
          <button type="button" data-test="health-check" :disabled="checking" @click="emit('health-check')">
            {{ checking ? "测试中..." : "连接测试" }}
          </button>
        </div>
      </header>
      <div v-if="healthChecks.length" class="health-list">
        <article v-for="check in healthChecks" :key="check.name || check.label" :class="['health-row', check.ok ? 'ok' : 'bad']">
          <span class="status-dot"></span>
          <div>
            <header>
              <strong>{{ check.label || check.name || "检查项" }}</strong>
              <em>{{ check.ok ? "通过" : "需处理" }}</em>
            </header>
            <p>{{ check.message || "-" }}</p>
            <small v-if="check.source">来源：{{ sourceLabel(check.source) }}</small>
            <small v-if="!check.ok">{{ failedAction(check.name) }}</small>
          </div>
        </article>
      </div>
      <div v-else class="empty-state">点击“连接测试”检查 PostgreSQL、当前图片后端、API Key、输出目录和模型配置。</div>
    </section>

    <section class="effective-panel">
      <header>
        <div>
          <p>当前生效配置</p>
          <h2>{{ summary?.project?.title || summary?.project?.slug || "当前小说" }}</h2>
        </div>
      </header>
      <dl>
        <div v-for="row in effectiveRows" :key="row[0]">
          <dt>{{ row[0] }}</dt>
          <dd>{{ row[1] }}</dd>
          <em>{{ row[2] }}</em>
        </div>
      </dl>
    </section>
  </section>
</template>

<style scoped>
.status-layout {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.status-panel,
.effective-panel {
  min-width: 0;
  padding: 14px;
  color: #e7e8ea;
  background: #181b20;
  border: 1px solid #343940;
  border-radius: 6px;
}

.panel-head,
.health-actions,
.source-row header,
.health-row header,
.effective-panel > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.panel-head { margin-bottom: 11px; }

.panel-head p,
.effective-panel > header p {
  margin: 0 0 3px;
  color: #9ba1aa;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

.panel-head h2,
.effective-panel > header h2 {
  margin: 0;
  font-size: 16px;
}

.source-list,
.health-list {
  display: grid;
  gap: 1px;
  overflow: hidden;
  background: #343940;
  border: 1px solid #343940;
  border-radius: 4px;
}

.source-row,
.health-row {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 9px;
  padding: 9px;
  background: #111419;
}

.source-index {
  color: #727a84;
  font: 700 11px ui-monospace, SFMono-Regular, Consolas, monospace;
}

.source-row strong,
.health-row strong {
  font-size: 12px;
}

.source-row em,
.health-row em,
.health-badge {
  color: #aeb4bc;
  font-size: 10px;
  font-style: normal;
}

.source-row em.ok,
.health-badge.ok { color: #9fd5ac; }
.source-row em.bad,
.health-badge.bad { color: #e7a3a3; }

.source-row p,
.health-row p {
  margin: 4px 0;
  color: #aeb4bc;
  font-size: 11px;
  line-height: 1.45;
}

.source-row code,
.health-row small {
  display: block;
  overflow-wrap: anywhere;
  color: #7f8791;
  font-size: 10px;
}

.health-row {
  grid-template-columns: 8px minmax(0, 1fr);
}

.status-dot {
  width: 6px;
  height: 6px;
  margin-top: 5px;
  border-radius: 50%;
  background: #727a84;
}

.health-row.ok .status-dot { background: #69a979; }
.health-row.bad .status-dot { background: #b96767; }

.health-actions button {
  min-height: 30px;
  padding: 5px 9px;
  color: #dfe2e6;
  background: #272b31;
  border: 1px solid #414750;
  border-radius: 4px;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.health-actions button:disabled { opacity: .5; cursor: not-allowed; }

.empty-state {
  min-height: 72px;
  display: grid;
  place-items: center;
  padding: 12px;
  color: #8e959e;
  background: #111419;
  border: 1px dashed #3e444c;
  font-size: 11px;
  text-align: center;
}

.effective-panel {
  grid-column: 1 / -1;
}

.effective-panel dl {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin: 11px 0 0;
  background: #343940;
  border: 1px solid #343940;
}

.effective-panel dl div {
  min-width: 0;
  padding: 9px;
  background: #111419;
}

.effective-panel dt,
.effective-panel em {
  color: #858d96;
  font-size: 10px;
  font-style: normal;
}

.effective-panel dd {
  margin: 4px 0;
  overflow: hidden;
  color: #d6d9dd;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1100px) {
  .status-layout { grid-template-columns: minmax(0, 1fr); }
  .effective-panel { grid-column: auto; }
  .effective-panel dl { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
