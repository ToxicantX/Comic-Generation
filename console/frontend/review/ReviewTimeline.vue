<script setup lang="ts">
import { computed } from "vue";

import {
  actionLabel,
  compactTime,
  displayReviewText,
  reviewHistoryGroups,
  timelineTypeLabel,
} from "./presentation";
import type {
  ReviewStats,
  ReviewTarget,
  ReviewTimelineFilter,
  ReviewTimelineItem,
  ReviewTimelineLimit,
  ReviewTimelineRange,
} from "./types";

const props = defineProps<{
  timeline: ReviewTimelineItem[];
  stats: ReviewStats;
  filter: ReviewTimelineFilter;
  range: ReviewTimelineRange;
  limit: ReviewTimelineLimit;
  selectedItemId: string;
}>();

const emit = defineEmits<{
  filterChange: [value: ReviewTimelineFilter];
  rangeChange: [value: ReviewTimelineRange];
  limitChange: [value: ReviewTimelineLimit];
  select: [itemId: string];
  openTarget: [target: ReviewTarget];
}>();

const groups = computed(() => reviewHistoryGroups(props.timeline).slice(0, 8));
const selected = computed(() => props.timeline.find(
  (item) => String(item.id) === String(props.selectedItemId),
) || props.timeline[0] || null);

function changeFilter(event: Event) {
  emit("filterChange", (event.target as HTMLSelectElement).value as ReviewTimelineFilter);
}

function changeRange(event: Event) {
  emit("rangeChange", (event.target as HTMLSelectElement).value as ReviewTimelineRange);
}

function changeLimit(event: Event) {
  emit("limitChange", Number((event.target as HTMLSelectElement).value) as ReviewTimelineLimit);
}
</script>

<template>
  <section class="timeline-panel" aria-label="审核时间线">
    <header class="section-head">
      <div>
        <span class="eyebrow">审核记录</span>
        <h2>对象历史与时间线</h2>
      </div>
      <span class="count-badge">{{ timeline.length ? `${timeline.length} 条` : "暂无" }}</span>
    </header>

    <div class="timeline-tools">
      <select :value="filter" aria-label="筛选审核时间线" @change="changeFilter">
        <option value="all">全部记录</option>
        <option value="generated_output">生成结果</option>
        <option value="chapter_breakdown">章节拆解</option>
        <option value="setting">小说设定</option>
        <option value="setting_scan">设定扫描</option>
        <option value="visual_asset">视觉素材</option>
      </select>
      <select :value="range" aria-label="审核时间范围" @change="changeRange">
        <option value="all">全部时间</option>
        <option value="7d">最近 7 天</option>
        <option value="30d">最近 30 天</option>
        <option value="90d">最近 90 天</option>
      </select>
      <select :value="limit" aria-label="审核记录数量" @change="changeLimit">
        <option :value="20">最近 20 条</option>
        <option :value="40">最近 40 条</option>
        <option :value="80">最近 80 条</option>
        <option :value="100">最近 100 条</option>
      </select>
    </div>

    <div class="insight-grid">
      <section class="reason-panel">
        <header>
          <strong>{{ displayReviewText(stats.range_label || "全部时间", "全部时间") }}</strong>
          <span>{{ Number(stats.total || 0) }} 条记录 · {{ Number(stats.return_total || 0) }} 条退回 / 待改</span>
        </header>
        <div v-if="stats.return_reasons?.length" class="reason-chips">
          <span v-for="reason in stats.return_reasons" :key="reason.label">
            {{ displayReviewText(reason.label, "未填写原因") }}<b>{{ Number(reason.count || 0) }}</b>
          </span>
        </div>
        <small v-else>当前范围内没有退回或待改原因。</small>
        <div class="distribution">
          <div>
            <b>动作分布</b>
            <p v-for="item in (stats.actions || []).slice(0, 4)" :key="item.label">
              {{ displayReviewText(item.label, "审核") }} <strong>{{ Number(item.count || 0) }}</strong>
            </p>
            <p v-if="!stats.actions?.length">暂无</p>
          </div>
          <div>
            <b>对象分布</b>
            <p v-for="item in (stats.target_types || []).slice(0, 4)" :key="item.label">
              {{ displayReviewText(item.label, "审核对象") }} <strong>{{ Number(item.count || 0) }}</strong>
            </p>
            <p v-if="!stats.target_types?.length">暂无</p>
          </div>
        </div>
      </section>

      <section class="groups-panel">
        <header><strong>按对象查看历史</strong><span>{{ groups.length ? `${groups.length} 组` : "暂无" }}</span></header>
        <div v-if="groups.length" class="group-list">
          <button
            v-for="group in groups"
            :key="group.key"
            type="button"
            @click="emit('select', String(group.items[0]?.id || ''))"
          >
            <span>{{ group.targetTypeLabel }}</span>
            <strong>{{ group.targetLabel }}</strong>
            <small>{{ group.latestAction || "审核" }} · {{ group.count }} 条 · {{ compactTime(group.latestAt) }}</small>
          </button>
        </div>
        <div v-else class="empty compact">暂无可聚合的审核历史。</div>
      </section>
    </div>

    <div class="timeline-grid">
      <div v-if="timeline.length" class="timeline-list">
        <button
          v-for="item in timeline.slice(0, 12)"
          :key="item.id"
          type="button"
          :class="{ active: String(item.id) === String(selectedItemId) }"
          :aria-pressed="String(item.id) === String(selectedItemId)"
          @click="emit('select', String(item.id))"
        >
          <header><span>{{ timelineTypeLabel(item) }}</span><b>{{ actionLabel(item.action, item.action_label) }}</b></header>
          <strong>{{ displayReviewText(item.target_label || item.target_type_label, "审核记录") }}</strong>
          <small>{{ displayReviewText(item.comment || "无备注", "无备注") }} · {{ compactTime(item.created_at) }}</small>
          <ul v-if="item.change_summary?.length">
            <li v-for="change in item.change_summary" :key="change">{{ displayReviewText(change, "记录已更新") }}</li>
          </ul>
        </button>
      </div>
      <div v-else class="empty">当前筛选下没有审核记录。</div>

      <section v-if="selected" class="timeline-detail">
        <header><span>{{ timelineTypeLabel(selected) }}</span><strong>{{ actionLabel(selected.action, selected.action_label) }}</strong></header>
        <dl>
          <div><dt>对象</dt><dd>{{ displayReviewText(selected.target_label || selected.target_type_label, "审核记录") }}</dd></div>
          <div><dt>时间</dt><dd>{{ compactTime(selected.created_at) }}</dd></div>
          <div><dt>备注</dt><dd>{{ displayReviewText(selected.comment || "无备注", "无备注") }}</dd></div>
        </dl>
        <div class="changes">
          <span>变更摘要</span>
          <ul v-if="selected.change_summary?.length">
            <li v-for="change in selected.change_summary" :key="change">{{ displayReviewText(change, "记录已更新") }}</li>
          </ul>
          <small v-else>暂无结构化变更。</small>
        </div>
        <div class="diff-table">
          <span>修改前后</span>
          <template v-if="selected.change_details?.length">
            <div class="diff-head"><b>字段</b><b>修改前</b><b>修改后</b></div>
            <div v-for="detail in selected.change_details" :key="`${detail.field}-${detail.label}`" class="diff-row">
              <b>{{ displayReviewText(detail.label || "字段", "字段") }}</b>
              <small>{{ displayReviewText(detail.before || "空", "空") }}</small>
              <small>{{ displayReviewText(detail.after || "空", "空") }}</small>
            </div>
          </template>
          <small v-else>暂无可展示的字段级对比。</small>
        </div>
        <button
          class="jump-button"
          type="button"
          :disabled="!selected.target?.module"
          @click="selected.target?.module && emit('openTarget', selected.target)"
        >
          <span aria-hidden="true">⌖</span><strong>{{ selected.target?.module ? "定位对象" : "暂无定位" }}</strong>
        </button>
      </section>
      <div v-else class="empty">选择一条审核记录查看详情。</div>
    </div>
  </section>
</template>

<style scoped>
.timeline-panel {
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--line, #30384a);
  border-radius: 6px;
  background: var(--surface, #151a24);
}

.section-head,
.reason-panel > header,
.groups-panel > header,
.timeline-list button header,
.timeline-detail > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.section-head h2 {
  margin: 2px 0 0;
  color: var(--text, #edf0f5);
  font-size: 16px;
}

.eyebrow,
.count-badge,
.reason-panel small,
.groups-panel small,
.timeline-list small,
.timeline-detail dt,
.timeline-detail small {
  color: var(--muted, #9ca6b8);
}

.eyebrow,
.count-badge {
  font-size: 11px;
}

.timeline-tools {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 7px;
  margin: 12px 0;
}

.timeline-tools select {
  min-width: 0;
  height: 32px;
  padding: 0 8px;
  border: 1px solid var(--line-strong, #465066);
  border-radius: 4px;
  background: var(--surface-low, #10151e);
  color: var(--text, #edf0f5);
}

.insight-grid,
.timeline-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 8px;
}

.reason-panel,
.groups-panel,
.timeline-detail {
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--line, #30384a);
  border-radius: 4px;
  background: var(--surface-low, #10151e);
}

.reason-panel header strong,
.groups-panel header strong,
.timeline-detail header strong {
  color: var(--text, #edf0f5);
  font-size: 12px;
}

.reason-panel header span,
.groups-panel header span {
  color: var(--muted, #9ca6b8);
  font-size: 11px;
}

.reason-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin: 8px 0;
}

.reason-chips span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 6px;
  border: 1px solid var(--line, #30384a);
  border-radius: 3px;
  color: var(--text, #edf0f5);
  font-size: 11px;
}

.reason-chips b {
  color: var(--accent-strong, #aeb5ff);
}

.distribution {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--line, #30384a);
}

.distribution b,
.distribution p {
  margin: 0;
  color: var(--muted, #9ca6b8);
  font-size: 11px;
}

.distribution p {
  display: flex;
  justify-content: space-between;
  gap: 5px;
  margin-top: 4px;
}

.distribution strong {
  color: var(--text, #edf0f5);
}

.group-list {
  display: grid;
  gap: 5px;
  margin-top: 8px;
}

.group-list button,
.timeline-list button {
  display: grid;
  min-width: 0;
  gap: 4px;
  padding: 8px;
  border: 1px solid var(--line, #30384a);
  border-radius: 4px;
  background: var(--surface, #151a24);
  color: var(--text, #edf0f5);
  text-align: left;
}

.group-list span,
.timeline-list header span,
.timeline-list header b,
.timeline-detail header span {
  color: var(--accent-strong, #aeb5ff);
  font-size: 11px;
}

.group-list strong,
.timeline-list strong,
.timeline-list small {
  overflow-wrap: anywhere;
}

.group-list strong,
.timeline-list strong {
  font-size: 12px;
}

.timeline-grid {
  margin-top: 8px;
}

.timeline-list {
  display: grid;
  align-content: start;
  gap: 5px;
  max-height: 520px;
  overflow: auto;
}

.timeline-list button.active {
  border-color: var(--accent, #7c86f7);
  background: var(--accent-soft, #252a5d);
}

.timeline-list ul,
.changes ul {
  margin: 4px 0 0;
  padding-left: 17px;
  color: var(--muted, #9ca6b8);
  font-size: 11px;
}

.timeline-detail {
  display: grid;
  align-content: start;
  gap: 10px;
}

.timeline-detail dl {
  display: grid;
  gap: 5px;
  margin: 0;
}

.timeline-detail dl div {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 7px;
}

.timeline-detail dt,
.timeline-detail dd {
  margin: 0;
  overflow-wrap: anywhere;
  font-size: 11px;
}

.timeline-detail dd {
  color: var(--text, #edf0f5);
}

.changes,
.diff-table {
  padding-top: 8px;
  border-top: 1px solid var(--line, #30384a);
}

.changes > span,
.diff-table > span {
  color: var(--text, #edf0f5);
  font-size: 11px;
  font-weight: 700;
}

.diff-head,
.diff-row {
  display: grid;
  grid-template-columns: minmax(70px, 0.6fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 6px;
  padding: 5px 0;
  border-bottom: 1px solid var(--line, #30384a);
  font-size: 11px;
}

.diff-row b,
.diff-row small {
  min-width: 0;
  overflow-wrap: anywhere;
}

.jump-button {
  display: inline-flex;
  align-items: center;
  justify-self: start;
  min-height: 32px;
  gap: 6px;
  padding: 0 10px;
  border: 1px solid var(--line-strong, #465066);
  border-radius: 4px;
  background: var(--surface, #151a24);
  color: var(--text, #edf0f5);
}

.jump-button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.empty {
  padding: 28px 12px;
  color: var(--muted, #9ca6b8);
  text-align: center;
  font-size: 12px;
}

.empty.compact {
  padding: 18px 8px;
}

@media (max-width: 1100px) {
  .insight-grid,
  .timeline-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
