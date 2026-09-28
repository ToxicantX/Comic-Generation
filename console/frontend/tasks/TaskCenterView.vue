<script setup lang="ts">
import { computed, watch } from "vue"

import TaskDetail from "./TaskDetail.vue"
import TaskList from "./TaskList.vue"
import { taskId, taskStatusGroup } from "./presentation"
import type {
  TaskFileActionEvent,
  TaskFileEvent,
  TaskFilePreview,
  TaskFilter,
  TaskJob,
} from "./types"

const props = defineProps<{
  jobs: readonly TaskJob[]
  filter: TaskFilter
  selectedJobId: string
  taskFilePreview: TaskFilePreview | null
}>()

const emit = defineEmits<{
  "filter-change": [filter: TaskFilter]
  select: [jobId: string]
  cancel: [jobId: string]
  retry: [jobId: string]
  refresh: []
  "preview-file": [payload: TaskFileEvent]
  "download-file": [payload: TaskFileEvent]
  "file-action": [payload: TaskFileActionEvent]
}>()

const summary = computed(() => props.jobs.reduce((counts, job) => {
  const group = taskStatusGroup(job.status)
  counts.total += 1
  counts[group] += 1
  if ((job.diagnostics?.issues?.length ?? 0) > 0 || Number(job.diagnostics?.waiting_for_panels ?? 0) > 0) {
    counts.diagnostics += 1
  }
  return counts
}, {
  total: 0,
  running: 0,
  waiting: 0,
  failed: 0,
  passed: 0,
  cancelled: 0,
  other: 0,
  diagnostics: 0,
}))

const summaryCards = computed(() => [
  { label: "全部", value: summary.value.total, detail: "最近任务" },
  { label: "运行中", value: summary.value.running, detail: "执行或排队" },
  { label: "等待", value: summary.value.waiting, detail: "等待处理" },
  { label: "失败", value: summary.value.failed, detail: "需要处理" },
  { label: "已完成", value: summary.value.passed, detail: "执行完成" },
  { label: "诊断", value: summary.value.diagnostics, detail: "含诊断信息" },
])

const visibleJobs = computed(() => props.jobs.filter((job) => (
  props.filter === "all" || taskStatusGroup(job.status) === props.filter
)))

const selectedJob = computed(() => (
  visibleJobs.value.find((job) => taskId(job) === props.selectedJobId)
    ?? visibleJobs.value[0]
    ?? null
))

watch(
  () => [props.filter, props.selectedJobId, visibleJobs.value.map(taskId).join("|")],
  () => {
    const nextId = selectedJob.value ? taskId(selectedJob.value) : ""
    if (nextId !== props.selectedJobId) emit("select", nextId)
  },
  { immediate: true },
)

function onFilterChange(event: Event): void {
  const value = (event.target as HTMLSelectElement).value as TaskFilter
  emit("filter-change", value)
}
</script>

<template>
  <section class="task-center" aria-label="任务中心">
    <header class="task-toolbar">
      <div>
        <p>任务中心</p>
        <h2>运行任务与诊断</h2>
      </div>
      <div class="toolbar-actions">
        <span>{{ summary.total ? `${summary.total} 条任务` : "暂无任务" }}</span>
        <button type="button" title="刷新任务" aria-label="刷新任务" @click="emit('refresh')">↻</button>
      </div>
    </header>

    <div class="summary-strip" aria-label="任务状态统计">
      <article v-for="card in summaryCards" :key="card.label">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <small>{{ card.detail }}</small>
      </article>
    </div>

    <div class="task-layout">
      <section class="list-pane">
        <header class="pane-header">
          <div><span>任务列表</span><strong>最近任务</strong></div>
          <label>
            <span class="sr-only">筛选任务</span>
            <select :value="filter" aria-label="筛选任务" @change="onFilterChange">
              <option value="all">全部任务</option>
              <option value="running">运行中</option>
              <option value="waiting">等待处理</option>
              <option value="failed">失败任务</option>
              <option value="passed">已完成</option>
            </select>
          </label>
        </header>
        <TaskList
          :jobs="visibleJobs"
          :selected-job-id="selectedJob ? taskId(selectedJob) : ''"
          @select="emit('select', $event)"
          @cancel="emit('cancel', $event)"
          @retry="emit('retry', $event)"
        />
      </section>

      <section class="detail-pane">
        <header class="pane-header">
          <div><span>任务详情</span><strong>执行信息</strong></div>
          <span class="detail-badge">{{ selectedJob ? "已选择" : "未选择" }}</span>
        </header>
        <TaskDetail
          :job="selectedJob"
          :task-file-preview="taskFilePreview"
          @cancel="emit('cancel', $event)"
          @retry="emit('retry', $event)"
          @preview-file="emit('preview-file', $event)"
          @download-file="emit('download-file', $event)"
          @file-action="emit('file-action', $event)"
        />
      </section>
    </div>
  </section>
</template>

<style scoped>
.task-center {
  box-sizing: border-box;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 10px;
  width: 100%;
  height: 100%;
  min-height: 620px;
  padding: 14px;
  overflow: hidden;
  color: #dce2e8;
  font-family: Inter, "Segoe UI", "Microsoft YaHei", sans-serif;
  color-scheme: dark;
  background: #11151a;
}

.task-toolbar,
.pane-header,
.toolbar-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.task-toolbar {
  min-height: 56px;
  padding: 0 2px 10px;
  border-bottom: 1px solid #2d343d;
}

.task-toolbar p,
.pane-header span {
  margin: 0;
  color: #8f99a5;
  font-size: 11px;
}

.task-toolbar h2 {
  margin: 3px 0 0;
  color: #f2f4f7;
  font-size: 18px;
  font-weight: 650;
}

.toolbar-actions > span,
.detail-badge {
  padding: 4px 8px;
  border: 1px solid #3b444f;
  border-radius: 4px;
  color: #aeb7c2;
  font-size: 11px;
  background: #1b2026;
}

.toolbar-actions button {
  display: inline-grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border: 1px solid #46515f;
  border-radius: 5px;
  color: #d8dee5;
  font-size: 17px;
  background: #222831;
  cursor: pointer;
}

.toolbar-actions button:hover {
  border-color: #758294;
  color: #fff;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 7px;
}

.summary-strip article {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px 8px;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid #2e353f;
  border-radius: 5px;
  background: #191e24;
}

.summary-strip span {
  align-self: center;
  color: #a4aeb9;
  font-size: 11px;
}

.summary-strip strong {
  grid-row: 1 / 3;
  grid-column: 2;
  align-self: center;
  color: #f0f2f4;
  font-size: 18px;
  font-weight: 650;
}

.summary-strip small {
  overflow: hidden;
  color: #727d89;
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-layout {
  display: grid;
  grid-template-columns: minmax(330px, 0.82fr) minmax(520px, 1.45fr);
  gap: 10px;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.list-pane,
.detail-pane {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  padding: 11px 10px 10px;
  overflow: hidden;
  border: 1px solid #2e353f;
  border-radius: 6px;
  background: #151a20;
}

.pane-header {
  min-height: 38px;
  padding: 0 2px 9px;
  border-bottom: 1px solid #293039;
}

.pane-header > div {
  display: grid;
  gap: 2px;
}

.pane-header strong {
  color: #e6eaf0;
  font-size: 13px;
  font-weight: 650;
}

.pane-header select {
  box-sizing: border-box;
  min-width: 112px;
  height: 30px;
  padding: 0 28px 0 9px;
  border: 1px solid #424c59;
  border-radius: 5px;
  color: #d5dce3;
  font-size: 11px;
  background: #20262e;
}

.pane-header + :deep(.task-list),
.pane-header + :deep(.task-detail),
.pane-header + :deep(.detail-empty) {
  margin-top: 8px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
