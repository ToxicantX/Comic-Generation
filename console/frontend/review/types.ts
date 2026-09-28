export type ReviewQueueFilter = "all" | "output" | "breakdown" | "setting" | "asset" | "job";

export type ReviewTimelineFilter =
  | "all"
  | "generated_output"
  | "chapter_breakdown"
  | "setting"
  | "setting_scan"
  | "visual_asset";

export type ReviewTimelineRange = "all" | "7d" | "30d" | "90d";
export type ReviewTimelineLimit = 20 | 40 | 80 | 100;
export type ReviewOutputBatchAction = "approve" | "needs_work";

export interface ReviewTarget {
  module?: string;
  tab?: string;
  episode?: number;
  media_filter?: string;
  focus_page_id?: string;
  focus_review_status?: string;
  page_id?: string;
  setting_id?: number;
  asset_id?: number;
  [key: string]: unknown;
}

export interface ReviewOutputBatch {
  output_ids: number[];
  scope_page_id: string;
}

export interface ReviewQueueItem {
  id: string;
  kind: Exclude<ReviewQueueFilter, "all"> | string;
  kind_label?: string;
  title: string;
  detail: string;
  status: string;
  status_label?: string;
  action_label?: string;
  target: ReviewTarget;
  updated?: string;
  count?: number;
  priority?: number;
  batch?: ReviewOutputBatch;
}

export interface ReviewChangeDetail {
  field?: string;
  label?: string;
  before?: string;
  after?: string;
}

export interface ReviewTimelineItem {
  id: number | string;
  target_type: string;
  target_type_label?: string;
  target_id?: string;
  target_label?: string;
  action: string;
  action_label?: string;
  comment?: string;
  created_at?: string;
  change_summary?: string[];
  change_details?: ReviewChangeDetail[];
  target: ReviewTarget;
}

export interface ReviewStatItem {
  label: string;
  count: number;
}

export interface ReviewStats {
  range?: string;
  range_label?: string;
  total?: number;
  return_total?: number;
  return_reasons?: ReviewStatItem[];
  actions?: ReviewStatItem[];
  target_types?: ReviewStatItem[];
}

export interface ReviewSummary {
  outputs?: number;
  breakdowns?: number;
  settings?: number;
  assets?: number;
  jobs?: number;
  total?: number;
}

export interface ReviewCenterData {
  ok?: boolean;
  project?: {
    slug?: string;
    title?: string;
  };
  summary?: ReviewSummary;
  items?: ReviewQueueItem[];
  timeline?: ReviewTimelineItem[];
  review_stats?: ReviewStats;
  timeline_query?: {
    type?: string;
    limit?: number;
    range?: string;
  };
}

export interface ReviewHistoryGroup {
  key: string;
  target: ReviewTarget;
  targetLabel: string;
  targetTypeLabel: string;
  count: number;
  latestAt: string;
  latestAction: string;
  latestComment: string;
  actions: Record<string, number>;
  items: ReviewTimelineItem[];
}
