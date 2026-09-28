import type {
  ReviewHistoryGroup,
  ReviewQueueItem,
  ReviewTarget,
  ReviewTimelineItem,
} from "./types";

const queueKindLabels: Record<string, string> = {
  output: "生成结果",
  breakdown: "章节拆解",
  setting: "小说设定",
  asset: "视觉素材",
  job: "任务诊断",
};

const timelineTypeLabels: Record<string, string> = {
  output: "生成结果",
  generated_output: "生成结果",
  breakdown: "章节拆解",
  chapter_breakdown: "章节拆解",
  setting: "小说设定",
  setting_scan: "设定扫描",
  asset: "视觉素材",
  visual_asset: "视觉素材",
  page: "漫画页面",
  panel: "漫画分镜",
  job: "任务诊断",
};

const statusLabels: Record<string, string> = {
  draft: "草稿",
  pending_review: "待审核",
  needs_work: "待修改",
  approved: "已通过",
  completed: "已完成",
  waiting: "等待中",
  failed: "失败",
  error: "异常",
  running: "进行中",
};

const actionLabels: Record<string, string> = {
  approve: "通过",
  approved: "通过",
  needs_work: "退回修改",
  reject: "退回",
  update: "更新",
  create: "创建",
  cancel: "取消",
  cancelled: "已取消",
  interrupted: "已中断",
};

function internalIdDisplayName(value: string): string {
  const match = value.match(/(?:[A-Z0-9]+_)*EP0*(\d+)(?:_P0*(\d+))?(?:_PANEL0*(\d+))?/i);
  if (!match) return value;
  return [
    `第 ${Number(match[1])} 章`,
    match[2] ? `第 ${Number(match[2])} 页` : "",
    match[3] ? `第 ${Number(match[3])} 格` : "",
  ].filter(Boolean).join(" · ");
}

export function displayReviewText(value: unknown, fallback = "-"): string {
  const text = String(value ?? "")
    .replace(/\b(?:[A-Z0-9]+_)*EP\d+(?:_P\d+)?(?:_PANEL\d+)?\b/gi, internalIdDisplayName)
    .replace(/\bEP0*(\d+)\b/gi, (_, episode: string) => `第 ${Number(episode)} 章`)
    .replace(/\bP0*(\d+)\s*\/\s*panel\s*(\d+)\b/gi, (_, page: string, panel: string) => `第 ${Number(page)} 页 / 第 ${Number(panel)} 格`)
    .replace(/\bP0*(\d+)\b/gi, (_, page: string) => `第 ${Number(page)} 页`)
    .replace(/\bpanel\s*(\d+)\b/gi, (_, panel: string) => `第 ${Number(panel)} 格`)
    .replace(/\bQA\b/g, "质检")
    .replace(/\bAI\b/g, "智能")
    .replace(/ComfyUI/g, "生成后端")
    .replace(/\breview_status\b/gi, "审核状态")
    .replace(/\bpending_review\b/gi, "待审核")
    .replace(/\bneeds_work\b/gi, "待修改")
    .replace(/\bgenerated_output\b/gi, "生成结果")
    .trim();
  return text || fallback;
}

export function compactTime(value: unknown): string {
  const text = String(value ?? "");
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  return match ? `${match[2]}-${match[3]} ${match[4]}:${match[5]}` : text || "-";
}

export function queueKindLabel(item: Pick<ReviewQueueItem, "kind" | "kind_label">): string {
  return displayReviewText(item.kind_label || queueKindLabels[item.kind] || "审核对象", "审核对象");
}

export function statusLabel(status: string, label?: string): string {
  return displayReviewText(label || statusLabels[status] || "待处理", "待处理");
}

export function timelineTypeLabel(item: Pick<ReviewTimelineItem, "target_type" | "target_type_label">): string {
  return displayReviewText(item.target_type_label || timelineTypeLabels[item.target_type] || "审核记录", "审核记录");
}

export function actionLabel(action: string, label?: string): string {
  return displayReviewText(label || actionLabels[action] || "审核", "审核");
}

export function reviewTargetKey(target: ReviewTarget, fallback: string): string {
  const parts = [
    target.module,
    target.tab,
    target.episode,
    target.focus_page_id || target.page_id,
    target.setting_id,
    target.asset_id,
    target.media_filter,
  ].map((value) => String(value ?? ""));
  return parts.some(Boolean) ? parts.join("|") : fallback;
}

export function reviewHistoryGroups(timeline: ReviewTimelineItem[]): ReviewHistoryGroup[] {
  const groups = new Map<string, ReviewHistoryGroup>();
  timeline.forEach((item) => {
    const key = reviewTargetKey(item.target || {}, `${item.target_type}|${item.target_id ?? ""}`);
    const typeLabel = timelineTypeLabel(item);
    const targetLabel = displayReviewText(item.target_label || typeLabel, typeLabel);
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        target: item.target || {},
        targetLabel,
        targetTypeLabel: typeLabel,
        count: 0,
        latestAt: "",
        latestAction: "",
        latestComment: "",
        actions: {},
        items: [],
      });
    }
    const group = groups.get(key)!;
    const currentAction = actionLabel(item.action, item.action_label);
    group.count += 1;
    group.items.push(item);
    group.actions[currentAction] = (group.actions[currentAction] || 0) + 1;
    if (!group.latestAt || String(item.created_at || "") > group.latestAt) {
      group.latestAt = String(item.created_at || "");
      group.latestAction = currentAction;
      group.latestComment = displayReviewText(item.comment || "无备注", "无备注");
      group.targetLabel = targetLabel;
      group.targetTypeLabel = typeLabel;
    }
  });
  return Array.from(groups.values()).sort((left, right) => right.latestAt.localeCompare(left.latestAt));
}
