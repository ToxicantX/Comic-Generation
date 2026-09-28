export type TaskFilter = "all" | "running" | "waiting" | "failed" | "passed"

export type TaskStatusGroup = Exclude<TaskFilter, "all"> | "cancelled" | "other"

export type TaskFileActionMode = "select" | "folder"

export interface TaskProgress {
  total?: number | string
  completed?: number | string
  failed?: number | string
  current?: string
  cancelled?: boolean
  interrupted?: boolean
  waiting?: boolean
  partial?: boolean
}

export interface TaskDiagnosticIssue {
  panel_id?: string
  message?: string
  raw?: string
  type?: string
  severity?: string
  action?: string
  retry_hint?: string
  cooldown_seconds?: number | string
}

export interface TaskDiagnostics {
  title?: string
  domain?: string
  issues?: TaskDiagnosticIssue[]
  waiting_for_panels?: number | string
  waiting_reason?: string
  missing_panels?: string[]
}

export interface TaskResult {
  summary?: unknown
  waiting_for_panels?: number | string
  report?: Record<string, unknown>
  [key: string]: unknown
}

export interface TaskJob {
  id?: string | number
  label?: string
  status?: string
  stage?: string
  started?: string
  finished?: string
  episode_number?: number | string | null
  exit_code?: number | null
  result_path?: string | null
  generation_context_path?: string | null
  backup_path?: string | null
  panel_id?: string
  page_id?: string
  asset_alias?: string
  stdout_tail?: string
  stderr_tail?: string
  retry_payload?: Record<string, unknown> | null
  progress?: TaskProgress | null
  diagnostics?: TaskDiagnostics | null
  result?: TaskResult | null
  [key: string]: unknown
}

export interface TaskFilePreviewData {
  name?: string
  size?: number | string
  truncated?: boolean
  content?: string
}

export interface TaskFilePreview {
  jobId?: string | number
  path?: string
  data?: TaskFilePreviewData | null
  error?: string
  loading?: boolean
}

export interface TaskFileEvent {
  jobId: string
  path: string
}

export interface TaskFileActionEvent extends TaskFileEvent {
  mode: TaskFileActionMode
}

export interface InferredTaskProgress {
  total: number
  completed: number
  failed: number
  percent: number
  current: string
  active: boolean
  cancelled: boolean
  interrupted: boolean
  waiting: boolean
  partial: boolean
}
