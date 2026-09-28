<script setup lang="ts">
import { computed } from "vue";

import { displayReviewText, queueKindLabel, statusLabel } from "./presentation";
import type { ReviewQueueFilter, ReviewQueueItem } from "./types";

const props = defineProps<{
  items: ReviewQueueItem[];
  filter: ReviewQueueFilter;
  selectedItemId: string;
}>();

const emit = defineEmits<{
  filterChange: [value: ReviewQueueFilter];
  select: [itemId: string];
}>();

const visibleItems = computed(() => props.items.filter(
  (item) => props.filter === "all" || item.kind === props.filter,
));

function changeFilter(event: Event) {
  emit("filterChange", (event.target as HTMLSelectElement).value as ReviewQueueFilter);
}
</script>

<template>
  <section class="queue-panel" aria-label="审核队列">
    <header class="section-head">
      <div>
        <span class="eyebrow">审核队列</span>
        <h2>按优先级处理</h2>
      </div>
      <select class="filter-select" :value="filter" aria-label="筛选审核队列" @change="changeFilter">
        <option value="all">全部类型</option>
        <option value="output">生成结果</option>
        <option value="breakdown">章节拆解</option>
        <option value="setting">小说设定</option>
        <option value="asset">视觉素材</option>
        <option value="job">任务诊断</option>
      </select>
    </header>

    <div class="queue-count">{{ visibleItems.length ? `${visibleItems.length} 项待处理` : "当前筛选已清空" }}</div>
    <div v-if="visibleItems.length" class="queue-list">
      <button
        v-for="item in visibleItems"
        :key="item.id"
        type="button"
        class="queue-item"
        :class="{ active: String(item.id) === String(selectedItemId) }"
        :aria-pressed="String(item.id) === String(selectedItemId)"
        @click="emit('select', String(item.id))"
      >
        <span class="kind">{{ queueKindLabel(item) }}</span>
        <strong>{{ displayReviewText(item.title, "待审核对象") }}</strong>
        <small>{{ displayReviewText(item.detail, "暂无详情") }}</small>
        <footer>
          <b>{{ statusLabel(item.status, item.status_label) }}</b>
          <em>{{ displayReviewText(item.action_label, "处理") }}</em>
        </footer>
      </button>
    </div>
    <div v-else class="empty">当前筛选下没有待处理审核项。</div>
  </section>
</template>

<style scoped>
.queue-panel {
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--line, #30384a);
  border-radius: 6px;
  background: var(--surface, #151a24);
}

.section-head,
.queue-item footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-head h2 {
  margin: 2px 0 0;
  color: var(--text, #edf0f5);
  font-size: 16px;
  line-height: 1.3;
}

.eyebrow,
.queue-count,
.queue-item small,
.queue-item b {
  color: var(--muted, #9ca6b8);
}

.eyebrow {
  font-size: 11px;
}

.filter-select {
  min-width: 112px;
  height: 32px;
  padding: 0 28px 0 9px;
  border: 1px solid var(--line-strong, #465066);
  border-radius: 4px;
  background: var(--surface-low, #10151e);
  color: var(--text, #edf0f5);
}

.queue-count {
  margin: 12px 0 8px;
  font-size: 12px;
}

.queue-list {
  display: grid;
  gap: 6px;
}

.queue-item {
  display: grid;
  width: 100%;
  min-width: 0;
  gap: 5px;
  padding: 10px;
  overflow: hidden;
  border: 1px solid var(--line, #30384a);
  border-radius: 5px;
  background: var(--surface-low, #10151e);
  color: var(--text, #edf0f5);
  text-align: left;
}

.queue-item:hover {
  border-color: var(--line-strong, #465066);
  background: var(--surface-mid, #1b2230);
}

.queue-item.active {
  border-color: var(--accent, #7c86f7);
  background: var(--accent-soft, #252a5d);
}

.queue-item .kind,
.queue-item em {
  color: var(--accent-strong, #aeb5ff);
  font-size: 11px;
  font-style: normal;
}

.queue-item strong,
.queue-item small {
  overflow-wrap: anywhere;
}

.queue-item strong {
  font-size: 13px;
  line-height: 1.45;
}

.queue-item small {
  font-size: 12px;
  line-height: 1.45;
}

.queue-item footer {
  margin-top: 3px;
  padding-top: 7px;
  border-top: 1px solid var(--line, #30384a);
  font-size: 11px;
}

.empty {
  padding: 24px 12px;
  color: var(--muted, #9ca6b8);
  text-align: center;
  font-size: 12px;
}
</style>
