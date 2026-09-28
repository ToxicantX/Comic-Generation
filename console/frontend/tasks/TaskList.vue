<script setup lang="ts">
import { computed } from "vue"

import {
  canCancelTask,
  canRetryTask,
  displayText,
  formatTaskTime,
  inferTaskProgress,
  stageLabel,
  statusText,
  taskId,
} from "./presentation"
import type { TaskJob } from "./types"

const props = defineProps<{
  jobs: readonly TaskJob[]
  selectedJobId: string
}>()

const emit = defineEmits<{
  select: [jobId: string]
  cancel: [jobId: string]
  retry: [jobId: string]
}>()

const rows = computed(() => props.jobs.map((job) => ({
  job,
  id: taskId(job),
  progress: inferTaskProgress(job),
})))
</script>

<template>
  <div class="task-list" aria-label="任务列表">
    <div v-if="!rows.length" class="empty-state">
      当前筛选下没有任务
    </div>
    <article
      v-for="row in rows"
      :key="row.id"
      class="task-row"
      :class="{ selected: row.id === selectedJobId }"
      :data-job-key="row.id"
    >
      <button class="task-main" type="button" @click="emit('select', row.id)">
        <span class="task-state" :data-state="row.job.status" aria-hidden="true" />
        <span class="task-copy">
          <span class="task-heading">
            <strong>{{ displayText(row.job.label || "未命名任务") }}</strong>
            <em>{{ statusText(row.job.status) }}</em>
          </span>
          <span class="task-meta">
            <span>{{ stageLabel(row.job.stage) }}</span>
            <span v-if="row.job.episode_number">第 {{ Number(row.job.episode_number) }} 章</span>
            <span>{{ formatTaskTime(row.job.started) }}</span>
          </span>
          <span class="task-progress" :aria-label="`任务进度 ${row.progress.percent}%`">
            <span class="task-progress-fill" :style="{ width: `${row.progress.percent}%` }" />
          </span>
          <span class="task-progress-meta">
            <span>{{ row.progress.current }}</span>
            <span>{{ row.progress.completed }}/{{ row.progress.total }}</span>
          </span>
        </span>
      </button>
      <div v-if="canRetryTask(row.job) || canCancelTask(row.job)" class="row-actions">
        <button
          v-if="canRetryTask(row.job)"
          class="icon-button"
          type="button"
          title="重试任务"
          aria-label="重试任务"
          @click="emit('retry', row.id)"
        >
          ↻
        </button>
        <button
          v-if="canCancelTask(row.job)"
          class="icon-button danger"
          type="button"
          title="取消任务"
          aria-label="取消任务"
          @click="emit('cancel', row.id)"
        >
          ×
        </button>
      </div>
    </article>
  </div>
</template>

<style scoped>
.task-list {
  min-height: 0;
  overflow: auto;
  padding: 2px 6px 8px 2px;
  scrollbar-color: #4a5361 transparent;
}

.task-row {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: stretch;
  margin-bottom: 6px;
  border: 1px solid #2c333d;
  border-radius: 6px;
  background: #191e24;
  transition: border-color 120ms ease, background 120ms ease;
}

.task-row:hover {
  border-color: #46515f;
  background: #1d232b;
}

.task-row.selected {
  border-color: #d39a43;
  background: #24221d;
  box-shadow: inset 3px 0 #d39a43;
}

.task-main {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr);
  gap: 10px;
  min-width: 0;
  padding: 11px 10px 10px;
  border: 0;
  color: inherit;
  text-align: left;
  background: transparent;
  cursor: pointer;
}

.task-state {
  width: 7px;
  height: 7px;
  margin-top: 5px;
  border-radius: 50%;
  background: #77808b;
}

.task-state[data-state="running"],
.task-state[data-state="queued"],
.task-state[data-state="starting"] {
  background: #68a9e6;
  box-shadow: 0 0 0 3px rgb(104 169 230 / 14%);
}

.task-state[data-state="passed"],
.task-state[data-state="complete"],
.task-state[data-state="completed"] {
  background: #72bd8d;
}

.task-state[data-state="failed"],
.task-state[data-state="error"],
.task-state[data-state="interrupted"] {
  background: #e47a73;
}

.task-state[data-state="waiting"],
.task-state[data-state="partial"] {
  background: #e1ad5b;
}

.task-copy,
.task-heading,
.task-meta,
.task-progress-meta {
  min-width: 0;
}

.task-copy {
  display: grid;
  gap: 6px;
}

.task-heading,
.task-progress-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.task-heading strong {
  overflow: hidden;
  color: #edf1f5;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-heading em {
  flex: 0 0 auto;
  color: #aeb7c2;
  font-size: 11px;
  font-style: normal;
}

.task-meta {
  display: flex;
  gap: 6px 12px;
  overflow: hidden;
  color: #8f99a5;
  font-size: 11px;
  white-space: nowrap;
}

.task-progress {
  display: block;
  width: 100%;
  height: 3px;
  overflow: hidden;
  border-radius: 2px;
  background: #303741;
}

.task-progress-fill {
  display: block;
  height: 100%;
  background: #d39a43;
}

.task-progress-meta {
  color: #89939f;
  font-size: 10px;
}

.row-actions {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  padding: 8px 8px 0 0;
}

.icon-button {
  display: inline-grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 1px solid #3b444f;
  border-radius: 5px;
  color: #cbd2da;
  font-size: 16px;
  background: #222831;
  cursor: pointer;
}

.icon-button:hover {
  border-color: #687587;
  color: #fff;
}

.icon-button.danger:hover {
  border-color: #c86560;
  color: #f3a09a;
}

.empty-state {
  display: grid;
  min-height: 160px;
  place-items: center;
  color: #7f8995;
  font-size: 13px;
}
</style>
