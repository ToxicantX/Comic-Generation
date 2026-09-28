<script setup lang="ts">
import { computed } from "vue";

import {
  actionLabel,
  compactTime,
  displayReviewText,
  queueKindLabel,
  reviewHistoryGroups,
  reviewTargetKey,
  statusLabel,
} from "./presentation";
import type {
  ReviewOutputBatchAction,
  ReviewQueueItem,
  ReviewTarget,
  ReviewTimelineItem,
} from "./types";

const props = defineProps<{
  item: ReviewQueueItem | null;
  timeline: ReviewTimelineItem[];
}>();

const emit = defineEmits<{
  openTarget: [target: ReviewTarget];
  reviewOutputBatch: [item: ReviewQueueItem, action: ReviewOutputBatchAction];
}>();

const history = computed(() => {
  if (!props.item) return [];
  const groups = reviewHistoryGroups(props.timeline);
  const key = reviewTargetKey(props.item.target || {}, props.item.id);
  return groups.find((group) => group.key === key)?.items || [];
});

const actionSummary = computed(() => {
  const counts = new Map<string, number>();
  history.value.forEach((record) => {
    const label = actionLabel(record.action, record.action_label);
    counts.set(label, (counts.get(label) || 0) + 1);
  });
  return Array.from(counts.entries()).slice(0, 4).map(([label, count]) => `${label} ${count}`).join(" · ") || "暂无历史记录";
});

const canOpenTarget = computed(() => Boolean(props.item?.target?.module));
const canBatchOutput = computed(() => props.item?.kind === "output" && Boolean(props.item.batch?.output_ids?.length));
</script>

<template>
  <section class="detail-panel" aria-label="审核对象详情">
    <header class="section-head">
      <div>
        <span class="eyebrow">审核对象</span>
        <h2>详情与历史</h2>
      </div>
    </header>

    <div v-if="item" class="detail-content">
      <div class="object-title">
        <span>{{ queueKindLabel(item) }}</span>
        <strong>{{ displayReviewText(item.title, "待审核对象") }}</strong>
        <small>{{ displayReviewText(item.detail, "暂无详情") }}</small>
      </div>

      <dl class="object-facts">
        <div><dt>状态</dt><dd>{{ statusLabel(item.status, item.status_label) }}</dd></div>
        <div><dt>数量</dt><dd>{{ Number(item.count || 1) }} 项</dd></div>
        <div><dt>更新</dt><dd>{{ compactTime(item.updated) }}</dd></div>
      </dl>

      <section class="history-block">
        <header><span>历史聚合</span><b>{{ history.length ? `${history.length} 条` : "暂无" }}</b></header>
        <p>{{ actionSummary }}</p>
        <div v-if="history.length" class="history-list">
          <article v-for="record in history.slice(0, 5)" :key="record.id">
            <strong>{{ actionLabel(record.action, record.action_label) }}</strong>
            <small>{{ compactTime(record.created_at) }} · {{ displayReviewText(record.comment || "无备注", "无备注") }}</small>
          </article>
        </div>
        <small v-else>该对象暂无最近审核记录。</small>
      </section>

      <div class="actions">
        <button
          v-if="canBatchOutput"
          type="button"
          class="primary"
          title="通过本页全部待审核输出"
          @click="emit('reviewOutputBatch', item, 'approve')"
        >
          <span aria-hidden="true">✓</span><strong>本页全部通过</strong>
        </button>
        <button
          v-if="canBatchOutput"
          type="button"
          title="填写问题并将本页输出批量退回"
          @click="emit('reviewOutputBatch', item, 'needs_work')"
        >
          <span aria-hidden="true">↩</span><strong>本页批量待改</strong>
        </button>
        <button
          type="button"
          :disabled="!canOpenTarget"
          :title="canOpenTarget ? '在工作区定位该对象' : '该对象暂无定位入口'"
          @click="item && canOpenTarget && emit('openTarget', item.target)"
        >
          <span aria-hidden="true">⌖</span><strong>{{ canOpenTarget ? (displayReviewText(item.action_label, "定位处理")) : "暂无定位" }}</strong>
        </button>
      </div>
    </div>
    <div v-else class="empty">选择左侧审核项查看对象详情、审核历史和定位入口。</div>
  </section>
</template>

<style scoped>
.detail-panel {
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--line, #30384a);
  border-radius: 6px;
  background: var(--surface, #151a24);
}

.section-head h2 {
  margin: 2px 0 0;
  color: var(--text, #edf0f5);
  font-size: 16px;
}

.eyebrow,
.object-title small,
.object-facts dt,
.history-block p,
.history-block small {
  color: var(--muted, #9ca6b8);
}

.eyebrow,
.object-title span,
.object-facts dt {
  font-size: 11px;
}

.detail-content {
  display: grid;
  gap: 12px;
  margin-top: 12px;
}

.object-title {
  display: grid;
  min-width: 0;
  gap: 5px;
}

.object-title span {
  color: var(--accent-strong, #aeb5ff);
}

.object-title strong,
.object-title small {
  overflow-wrap: anywhere;
}

.object-title strong {
  color: var(--text, #edf0f5);
  font-size: 14px;
  line-height: 1.45;
}

.object-title small {
  line-height: 1.45;
}

.object-facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
}

.object-facts div {
  min-width: 0;
  padding: 8px;
  border: 1px solid var(--line, #30384a);
  border-radius: 4px;
  background: var(--surface-low, #10151e);
}

.object-facts dd {
  margin: 3px 0 0;
  overflow-wrap: anywhere;
  color: var(--text, #edf0f5);
  font-size: 12px;
}

.history-block {
  padding: 10px;
  border: 1px solid var(--line, #30384a);
  border-radius: 4px;
  background: var(--surface-low, #10151e);
}

.history-block > header,
.history-list article {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.history-block header span,
.history-block header b {
  color: var(--text, #edf0f5);
  font-size: 12px;
}

.history-block p {
  margin: 7px 0;
  font-size: 12px;
}

.history-list {
  display: grid;
  gap: 5px;
}

.history-list article {
  min-width: 0;
  padding-top: 5px;
  border-top: 1px solid var(--line, #30384a);
}

.history-list strong {
  color: var(--text, #edf0f5);
  font-size: 11px;
  white-space: nowrap;
}

.history-list small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.actions button {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  gap: 6px;
  padding: 0 10px;
  border: 1px solid var(--line-strong, #465066);
  border-radius: 4px;
  background: var(--surface-low, #10151e);
  color: var(--text, #edf0f5);
}

.actions button.primary {
  border-color: var(--accent, #7c86f7);
  background: var(--accent, #7c86f7);
  color: #fff;
}

.actions button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.empty {
  padding: 28px 12px;
  color: var(--muted, #9ca6b8);
  text-align: center;
  font-size: 12px;
}
</style>
