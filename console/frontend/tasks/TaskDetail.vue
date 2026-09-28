<script setup lang="ts">
import { computed } from "vue"

import {
  canCancelTask,
  canRetryTask,
  diagnosticReason,
  diagnosticSeverity,
  diagnosticTitle,
  displayFileName,
  displayText,
  formatTaskTime,
  inferTaskProgress,
  stageLabel,
  statusText,
  taskId,
  taskSummaryText,
  taskTarget,
} from "./presentation"
import type {
  TaskFileActionEvent,
  TaskFileActionMode,
  TaskFileEvent,
  TaskFilePreview,
  TaskJob,
} from "./types"

const props = defineProps<{
  job: TaskJob | null
  taskFilePreview: TaskFilePreview | null
}>()

const emit = defineEmits<{
  cancel: [jobId: string]
  retry: [jobId: string]
  "preview-file": [payload: TaskFileEvent]
  "download-file": [payload: TaskFileEvent]
  "file-action": [payload: TaskFileActionEvent]
}>()

const id = computed(() => props.job ? taskId(props.job) : "")
const progress = computed(() => props.job ? inferTaskProgress(props.job) : null)
const diagnostics = computed(() => {
  const issues = props.job?.diagnostics?.issues
  return Array.isArray(issues) ? issues.slice(0, 6) : []
})
const waitingCount = computed(() => Number(
  props.job?.diagnostics?.waiting_for_panels
    ?? props.job?.result?.waiting_for_panels
    ?? 0,
))
const visiblePreview = computed(() => {
  if (!props.taskFilePreview || !props.job) return null
  if (String(props.taskFilePreview.jobId ?? "") !== id.value) return null
  return props.taskFilePreview
})
const summary = computed(() => props.job ? taskSummaryText(props.job) : "")

function fileEvent(path: string): TaskFileEvent {
  return { jobId: id.value, path }
}

function emitFileAction(path: string, mode: TaskFileActionMode): void {
  emit("file-action", { ...fileEvent(path), mode })
}
</script>

<template>
  <div v-if="!job" class="detail-empty">
    <strong>未选择任务</strong>
    <span>从左侧列表选择一项查看进度、诊断和结果文件。</span>
  </div>
  <article v-else class="task-detail">
    <header class="detail-header">
      <div class="detail-title">
        <span>{{ stageLabel(job.stage) }}</span>
        <h3>{{ displayText(job.label || "未命名任务") }}</h3>
      </div>
      <span class="status-badge" :data-state="job.status">{{ statusText(job.status) }}</span>
    </header>

    <section v-if="progress" class="progress-panel">
      <div class="progress-copy">
        <strong>{{ progress.current }}</strong>
        <span>{{ progress.completed }}/{{ progress.total }} 完成</span>
      </div>
      <div class="progress-track" :aria-label="`任务进度 ${progress.percent}%`">
        <span :style="{ width: `${progress.percent}%` }" />
      </div>
    </section>

    <dl class="meta-grid">
      <div><dt>章节</dt><dd>{{ job.episode_number ? `第 ${Number(job.episode_number)} 章` : "未指定" }}</dd></div>
      <div><dt>目标</dt><dd>{{ taskTarget(job) }}</dd></div>
      <div><dt>开始</dt><dd>{{ formatTaskTime(job.started) }}</dd></div>
      <div><dt>结束</dt><dd>{{ job.finished ? formatTaskTime(job.finished) : "尚未完成" }}</dd></div>
      <div><dt>退出状态</dt><dd>{{ job.exit_code === null || job.exit_code === undefined ? "未记录" : job.exit_code === 0 ? "正常" : "异常" }}</dd></div>
      <div><dt>当前阶段</dt><dd>{{ stageLabel(job.stage) }}</dd></div>
    </dl>

    <div v-if="canRetryTask(job) || canCancelTask(job)" class="primary-actions">
      <button v-if="canRetryTask(job)" type="button" @click="emit('retry', id)">
        <span aria-hidden="true">↻</span> 重试任务
      </button>
      <button v-if="canCancelTask(job)" class="danger" type="button" @click="emit('cancel', id)">
        <span aria-hidden="true">×</span> 取消任务
      </button>
    </div>

    <section v-if="job.result_path || job.generation_context_path || job.backup_path" class="detail-section">
      <div class="section-title">
        <h4>结果文件</h4>
        <span>文件操作由桌面运行时执行</span>
      </div>
      <div v-if="job.result_path" class="file-row">
        <div><strong>结果文件</strong><span>{{ displayFileName(job.result_path) }}</span></div>
        <div class="file-actions">
          <button type="button" title="预览结果" aria-label="预览结果" @click="emit('preview-file', fileEvent(job.result_path))">▤</button>
          <button type="button" title="下载文本" aria-label="下载文本" @click="emit('download-file', fileEvent(job.result_path))">⇩</button>
          <button type="button" title="在文件夹中显示" aria-label="在文件夹中显示" @click="emitFileAction(job.result_path, 'select')">⌖</button>
          <button type="button" title="打开结果目录" aria-label="打开结果目录" @click="emitFileAction(job.result_path, 'folder')">□</button>
        </div>
      </div>
      <div v-if="job.generation_context_path" class="file-row">
        <div><strong>生成上下文</strong><span>{{ displayFileName(job.generation_context_path) }}</span></div>
        <div class="file-actions">
          <button type="button" title="在文件夹中显示上下文" aria-label="在文件夹中显示上下文" @click="emitFileAction(job.generation_context_path, 'select')">⌖</button>
        </div>
      </div>
      <div v-if="job.backup_path" class="file-row">
        <div><strong>备份文件</strong><span>{{ displayFileName(job.backup_path) }}</span></div>
        <div class="file-actions">
          <button type="button" title="在文件夹中显示备份" aria-label="在文件夹中显示备份" @click="emitFileAction(job.backup_path, 'select')">⌖</button>
        </div>
      </div>

      <div v-if="visiblePreview" class="file-preview" aria-live="polite">
        <p v-if="visiblePreview.loading">正在读取文件...</p>
        <p v-else-if="visiblePreview.error" class="preview-error">{{ visiblePreview.error }}</p>
        <template v-else>
          <header>
            <strong>{{ displayFileName(visiblePreview.data?.name || visiblePreview.path) }}</strong>
            <span>{{ Number(visiblePreview.data?.size || 0) }} 字节{{ visiblePreview.data?.truncated ? " · 已截断" : "" }}</span>
          </header>
          <pre>{{ displayText(visiblePreview.data?.content || "") }}</pre>
        </template>
      </div>
    </section>

    <section v-if="waitingCount || diagnostics.length" class="detail-section diagnostics">
      <div class="section-title">
        <h4>{{ waitingCount ? `等待补充 ${waitingCount} 个分镜` : "任务诊断" }}</h4>
        <span>{{ diagnosticReason(job.diagnostics?.waiting_reason) }}</span>
      </div>
      <ul>
        <li v-for="(issue, index) in diagnostics" :key="`${issue.type || 'issue'}-${index}`">
          <div><strong>{{ diagnosticTitle(issue) }}</strong><em>{{ diagnosticSeverity(issue.severity) }}</em></div>
          <p>{{ displayText(issue.message || issue.raw || "等待处理") }}</p>
          <small v-if="issue.action">建议：{{ displayText(issue.action) }}</small>
          <small v-if="issue.retry_hint">{{ displayText(issue.retry_hint) }}</small>
        </li>
        <li v-if="waitingCount && !diagnostics.length"><p>仍有分镜尚未生成，请按当前流程继续补生成。</p></li>
      </ul>
    </section>

    <details v-if="summary" class="detail-log">
      <summary>结果摘要</summary>
      <pre>{{ summary }}</pre>
    </details>
    <details v-if="job.stdout_tail" class="detail-log">
      <summary>输出日志</summary>
      <pre>{{ displayText(job.stdout_tail) }}</pre>
    </details>
    <details v-if="job.stderr_tail" class="detail-log error-log">
      <summary>错误日志</summary>
      <pre>{{ displayText(job.stderr_tail) }}</pre>
    </details>
  </article>
</template>

<style scoped>
.task-detail,
.detail-empty {
  min-height: 0;
  height: 100%;
}

.task-detail {
  overflow: auto;
  padding: 2px 8px 16px 2px;
  color: #dce2e8;
  scrollbar-color: #4a5361 transparent;
}

.detail-empty {
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 6px;
  color: #7f8995;
  text-align: center;
}

.detail-empty strong {
  color: #c6ced7;
  font-size: 14px;
}

.detail-empty span {
  max-width: 360px;
  font-size: 12px;
  line-height: 1.6;
}

.detail-header,
.progress-copy,
.section-title,
.file-row,
.diagnostics li > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.detail-header {
  padding: 2px 0 13px;
  border-bottom: 1px solid #303741;
}

.detail-title {
  min-width: 0;
}

.detail-title > span,
.section-title > span {
  color: #8f99a5;
  font-size: 11px;
}

.detail-title h3,
.section-title h4 {
  margin: 3px 0 0;
  color: #f2f4f7;
  font-size: 15px;
  font-weight: 650;
  line-height: 1.35;
}

.status-badge {
  flex: 0 0 auto;
  padding: 4px 8px;
  border: 1px solid #46515f;
  border-radius: 4px;
  color: #cbd2da;
  font-size: 11px;
  background: #252b33;
}

.status-badge[data-state="running"],
.status-badge[data-state="queued"],
.status-badge[data-state="starting"] {
  border-color: #4075a4;
  color: #9ed0ff;
}

.status-badge[data-state="passed"] {
  border-color: #47745a;
  color: #9bdbb0;
}

.status-badge[data-state="failed"],
.status-badge[data-state="error"] {
  border-color: #8e4b48;
  color: #f2a19b;
}

.progress-panel,
.detail-section,
.detail-log {
  margin-top: 10px;
  border: 1px solid #303741;
  border-radius: 6px;
  background: #181d23;
}

.progress-panel {
  padding: 10px 12px;
}

.progress-copy {
  margin-bottom: 8px;
  font-size: 11px;
}

.progress-copy strong {
  color: #e5e9ed;
  font-size: 12px;
}

.progress-copy span {
  color: #8f99a5;
}

.progress-track {
  height: 4px;
  overflow: hidden;
  border-radius: 2px;
  background: #303741;
}

.progress-track span {
  display: block;
  height: 100%;
  background: #d39a43;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  margin: 10px 0 0;
  overflow: hidden;
  border: 1px solid #303741;
  border-radius: 6px;
  background: #303741;
}

.meta-grid > div {
  min-width: 0;
  padding: 8px 10px;
  background: #191e24;
}

.meta-grid dt {
  color: #818b97;
  font-size: 10px;
}

.meta-grid dd {
  overflow: hidden;
  margin: 3px 0 0;
  color: #d7dde4;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.primary-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.primary-actions button {
  min-height: 32px;
  padding: 0 11px;
  border: 1px solid #586474;
  border-radius: 5px;
  color: #e5e9ed;
  font-size: 12px;
  background: #252c35;
  cursor: pointer;
}

.primary-actions button:hover {
  border-color: #8491a1;
}

.primary-actions button.danger:hover {
  border-color: #c86560;
  color: #f3a09a;
}

.detail-section {
  padding: 11px 12px;
}

.section-title {
  margin-bottom: 9px;
}

.section-title h4 {
  margin: 0;
  font-size: 13px;
}

.file-row {
  min-height: 40px;
  padding: 6px 0;
  border-top: 1px solid #293039;
}

.file-row > div:first-child {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.file-row strong {
  color: #dce2e8;
  font-size: 11px;
}

.file-row span {
  overflow: hidden;
  color: #8f99a5;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-actions {
  display: flex;
  flex: 0 0 auto;
  gap: 4px;
}

.file-actions button {
  display: inline-grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 1px solid #3c4652;
  border-radius: 5px;
  color: #cbd2da;
  background: #242a32;
  cursor: pointer;
}

.file-actions button:hover {
  border-color: #758294;
  color: #fff;
}

.file-preview {
  margin-top: 8px;
  padding: 9px 10px;
  border: 1px solid #3a434e;
  border-radius: 5px;
  background: #11151a;
}

.file-preview header {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: #9da7b2;
  font-size: 10px;
}

.file-preview header strong {
  color: #dce2e8;
  font-size: 11px;
}

.file-preview pre,
.detail-log pre {
  max-height: 230px;
  margin: 8px 0 0;
  overflow: auto;
  color: #c7ced6;
  font-family: ui-monospace, "Cascadia Mono", Consolas, monospace;
  font-size: 11px;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.file-preview p {
  margin: 0;
  color: #9da7b2;
  font-size: 11px;
}

.file-preview .preview-error {
  color: #f0a29d;
}

.diagnostics ul {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.diagnostics li {
  padding: 9px 10px;
  border-left: 3px solid #d39a43;
  border-radius: 3px;
  background: #22231f;
}

.diagnostics li strong {
  color: #e6e9ed;
  font-size: 11px;
}

.diagnostics li em {
  color: #e2b66f;
  font-size: 10px;
  font-style: normal;
}

.diagnostics li p,
.diagnostics li small {
  display: block;
  margin: 4px 0 0;
  color: #abb4be;
  font-size: 10px;
  line-height: 1.5;
}

.detail-log {
  padding: 0 11px 10px;
}

.detail-log summary {
  padding: 10px 0;
  color: #cfd6de;
  font-size: 11px;
  cursor: pointer;
}

.detail-log pre {
  margin-top: 0;
}

.error-log pre {
  color: #efaaa4;
}
</style>
