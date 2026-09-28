<script setup lang="ts">
import { computed } from "vue";

import ReviewObjectDetail from "./ReviewObjectDetail.vue";
import ReviewQueue from "./ReviewQueue.vue";
import ReviewTimeline from "./ReviewTimeline.vue";
import { displayReviewText } from "./presentation";
import type {
  ReviewCenterData,
  ReviewOutputBatchAction,
  ReviewQueueFilter,
  ReviewQueueItem,
  ReviewTarget,
  ReviewTimelineFilter,
  ReviewTimelineLimit,
  ReviewTimelineRange,
} from "./types";

const props = withDefaults(defineProps<{
  reviewCenter: ReviewCenterData;
  queueFilter?: ReviewQueueFilter;
  timelineFilter?: ReviewTimelineFilter;
  timelineRange?: ReviewTimelineRange;
  timelineLimit?: ReviewTimelineLimit;
  selectedQueueItemId?: string;
  selectedTimelineItemId?: string;
}>(), {
  queueFilter: "all",
  timelineFilter: "all",
  timelineRange: "all",
  timelineLimit: 40,
  selectedQueueItemId: "",
  selectedTimelineItemId: "",
});

const emit = defineEmits<{
  refresh: [];
  queueFilterChange: [value: ReviewQueueFilter];
  timelineFilterChange: [value: ReviewTimelineFilter];
  timelineRangeChange: [value: ReviewTimelineRange];
  timelineLimitChange: [value: ReviewTimelineLimit];
  selectQueueItem: [itemId: string];
  selectTimelineItem: [itemId: string];
  openTarget: [target: ReviewTarget];
  reviewOutputBatch: [item: ReviewQueueItem, action: ReviewOutputBatchAction];
}>();

const items = computed(() => props.reviewCenter.items || []);
const timeline = computed(() => props.reviewCenter.timeline || []);
const summary = computed(() => props.reviewCenter.summary || {});
const stats = computed(() => props.reviewCenter.review_stats || {});
const selectedQueueItem = computed(() => {
  const visible = items.value.filter(
    (item) => props.queueFilter === "all" || item.kind === props.queueFilter,
  );
  return visible.find((item) => String(item.id) === String(props.selectedQueueItemId)) || visible[0] || null;
});

const summaryCards = computed(() => [
  { label: "生成结果", count: Number(summary.value.outputs || 0), detail: "页面与分镜待审核" },
  { label: "章节拆解", count: Number(summary.value.breakdowns || 0), detail: "拆解草稿待确认" },
  { label: "小说设定", count: Number(summary.value.settings || 0), detail: "角色、场景与规则" },
  { label: "视觉素材", count: Number(summary.value.assets || 0), detail: "作品级参考资产" },
  { label: "任务诊断", count: Number(summary.value.jobs || 0), detail: "失败或等待任务" },
]);
</script>

<template>
  <section class="review-center" aria-label="审核中心">
    <header class="hero">
      <div>
        <span class="scope">{{ reviewCenter.project?.title ? `${displayReviewText(reviewCenter.project.title, "当前作品")} · 审核中心` : "审核中心" }}</span>
        <h1>待处理审核队列</h1>
        <p>集中查看生成结果、拆解、设定、素材和任务诊断。</p>
      </div>
      <div class="hero-actions">
        <span class="total-badge">{{ items.length ? `${items.length} 项` : "已清空" }}</span>
        <button type="button" class="refresh-button" title="刷新审核队列" aria-label="刷新审核队列" @click="emit('refresh')">
          <span aria-hidden="true">↻</span><strong>刷新审核</strong>
        </button>
      </div>
    </header>

    <div class="summary-grid" aria-label="待审核统计">
      <article v-for="card in summaryCards" :key="card.label">
        <span>{{ card.label }}</span>
        <strong>{{ card.count }}</strong>
        <small>{{ card.detail }}</small>
      </article>
    </div>

    <div class="workspace-grid">
      <ReviewQueue
        :items="items"
        :filter="queueFilter"
        :selected-item-id="selectedQueueItemId"
        @filter-change="emit('queueFilterChange', $event)"
        @select="emit('selectQueueItem', $event)"
      />
      <div class="review-details">
        <ReviewObjectDetail
          :item="selectedQueueItem"
          :timeline="timeline"
          @open-target="emit('openTarget', $event)"
          @review-output-batch="(item, action) => emit('reviewOutputBatch', item, action)"
        />
        <ReviewTimeline
          :timeline="timeline"
          :stats="stats"
          :filter="timelineFilter"
          :range="timelineRange"
          :limit="timelineLimit"
          :selected-item-id="selectedTimelineItemId"
          @filter-change="emit('timelineFilterChange', $event)"
          @range-change="emit('timelineRangeChange', $event)"
          @limit-change="emit('timelineLimitChange', $event)"
          @select="emit('selectTimelineItem', $event)"
          @open-target="emit('openTarget', $event)"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
.review-center {
  display: grid;
  min-width: 0;
  gap: 10px;
  color: var(--text, #edf0f5);
}

.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--line, #30384a);
  border-radius: 6px;
  background: var(--surface, #151a24);
}

.scope {
  color: var(--accent-strong, #aeb5ff);
  font-size: 11px;
}

.hero h1 {
  margin: 3px 0;
  color: var(--text, #edf0f5);
  font-size: 20px;
  line-height: 1.25;
}

.hero p {
  margin: 0;
  color: var(--muted, #9ca6b8);
  font-size: 12px;
}

.hero-actions {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 8px;
}

.total-badge {
  padding: 4px 7px;
  border: 1px solid var(--line, #30384a);
  border-radius: 4px;
  color: var(--muted, #9ca6b8);
  font-size: 11px;
}

.refresh-button {
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

.summary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.summary-grid article {
  display: grid;
  min-width: 0;
  gap: 3px;
  padding: 10px;
  border: 1px solid var(--line, #30384a);
  border-radius: 5px;
  background: var(--surface, #151a24);
}

.summary-grid span,
.summary-grid small {
  color: var(--muted, #9ca6b8);
  font-size: 11px;
}

.summary-grid strong {
  color: var(--text, #edf0f5);
  font-size: 20px;
}

.summary-grid small {
  overflow-wrap: anywhere;
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(300px, 0.34fr) minmax(0, 1fr);
  align-items: start;
  min-width: 0;
  gap: 10px;
}

.review-details {
  display: grid;
  min-width: 0;
  gap: 10px;
}

@media (max-width: 1180px) {
  .summary-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .workspace-grid {
    grid-template-columns: minmax(270px, 0.4fr) minmax(0, 1fr);
  }
}
</style>
