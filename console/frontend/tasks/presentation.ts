import type {
  InferredTaskProgress,
  TaskDiagnosticIssue,
  TaskJob,
  TaskStatusGroup,
} from "./types"

const statusLabels: Record<string, string> = {
  running: "运行中",
  queued: "排队中",
  starting: "启动中",
  waiting: "等待重试",
  partial: "部分完成",
  passed: "已通过",
  complete: "已完成",
  completed: "已完成",
  failed: "失败",
  error: "失败",
  cancelled: "已取消",
  interrupted: "已中断",
}

const stageLabels: Record<string, string> = {
  preflight: "预检",
  breakdown: "智能拆解",
  draft_review: "拆解审稿",
  generate: "生成漫画",
  review: "生成审核",
  status: "状态刷新",
  asset: "素材生成",
  process_novel: "处理小说",
  regenerate: "重新生成",
  regenerate_page: "按页补生成",
  close_reading: "细读拆解",
  setting_scan: "设定扫描",
}

const diagnosticLabels: Record<string, string> = {
  empty_image_response: "接口未返回图片",
  rate_limited: "接口限流",
  auth_failed: "鉴权失败",
  model_unavailable: "模型不可用",
  workflow_missing: "工作流缺失",
  panel_failed: "分镜生成失败",
  timeout: "等待超时",
  backend_unreachable: "生成后端不可达",
  waiting_for_panels: "等待补充分镜",
  text_model_rate_limited: "小说模型限流",
  text_model_unavailable: "小说模型不可用",
  text_model_auth_failed: "小说模型鉴权失败",
  text_model_timeout: "小说模型超时",
  text_model_error: "小说处理失败",
  image_aspect_ratio_mismatch: "图片比例不匹配",
  unknown: "任务诊断",
}

const severityLabels: Record<string, string> = {
  blocked: "需先修复",
  cooldown: "等待冷却",
  retryable: "可重试",
  info: "提示",
}

export function taskId(job: TaskJob): string {
  return String(job.id ?? "")
}

export function statusText(value?: string): string {
  return statusLabels[String(value ?? "")] ?? "其他状态"
}

export function stageLabel(value?: string): string {
  return stageLabels[String(value ?? "")] ?? "其他阶段"
}

export function taskStatusGroup(value?: string): TaskStatusGroup {
  const status = String(value ?? "")
  if (["running", "queued", "starting"].includes(status)) return "running"
  if (status === "waiting") return "waiting"
  if (["failed", "error", "interrupted", "partial"].includes(status)) return "failed"
  if (status === "cancelled") return "cancelled"
  if (["passed", "complete", "completed"].includes(status)) return "passed"
  return "other"
}

export function canCancelTask(job: TaskJob): boolean {
  return ["running", "queued", "starting"].includes(String(job.status ?? ""))
}

export function canRetryTask(job: TaskJob): boolean {
  return ["failed", "waiting", "partial", "interrupted", "cancelled"].includes(String(job.status ?? ""))
    && Boolean(job.retry_payload && Object.keys(job.retry_payload).length)
}

function positiveNumber(value: unknown, fallback = 0): number {
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(0, number) : fallback
}

export function inferTaskProgress(job: TaskJob): InferredTaskProgress {
  const raw = job.progress ?? {}
  const status = String(job.status ?? "")
  const total = Math.max(positiveNumber(raw.total), 1)
  let completed = positiveNumber(raw.completed)
  let failed = positiveNumber(raw.failed)

  if (!job.progress) {
    if (["passed", "complete", "completed"].includes(status)) completed = 1
    if (["failed", "error", "interrupted"].includes(status)) failed = 1
  }

  completed = Math.min(completed, total)
  failed = Math.min(failed, total)
  const active = ["running", "queued", "starting"].includes(status)
  const cancelled = Boolean(raw.cancelled) || status === "cancelled"
  const interrupted = Boolean(raw.interrupted) || status === "interrupted"
  const waiting = Boolean(raw.waiting) || status === "waiting"
  const partial = Boolean(raw.partial) || status === "partial"
  let percent = Math.round((Math.min(total, completed + failed) / total) * 100)
  if (active && percent === 0) percent = 8
  if (waiting && percent === 0) percent = 12
  if ((cancelled || interrupted) && percent === 0) percent = 100

  const fallbackCurrent = active
    ? "运行中"
    : waiting
      ? "等待继续处理"
      : cancelled
        ? "已取消"
        : interrupted
          ? "任务已中断"
          : partial
            ? "部分完成"
            : statusText(status)

  return {
    total,
    completed,
    failed,
    percent: Math.min(100, Math.max(0, percent)),
    current: displayText(raw.current || fallbackCurrent),
    active,
    cancelled,
    interrupted,
    waiting,
    partial,
  }
}

function internalIdDisplayName(value: string): string {
  const match = value.match(/(?:[A-Z0-9]+_)*EP0*(\d+)(?:_P0*(\d+))?(?:_PANEL0*(\d+))?/i)
  if (!match) return ""
  return [
    `第 ${Number(match[1])} 章`,
    match[2] ? `第 ${Number(match[2])} 页` : "",
    match[3] ? `第 ${Number(match[3])} 格` : "",
  ].filter(Boolean).join(" · ")
}

export function displayText(value: unknown): string {
  return String(value ?? "")
    .replace(/\b(?:[A-Z0-9]+_)*EP\d+(?:_P\d+)?(?:_PANEL\d+)?/gi, (id) => internalIdDisplayName(id) || "任务对象")
    .replace(/\bEP0*(\d+)\b/gi, (_, episode: string) => `第 ${Number(episode)} 章`)
    .replace(/\bP0*(\d+)\s*\/\s*panel\s*(\d+)\b/gi, (_, page: string, panel: string) => `第 ${Number(page)} 页 / 第 ${Number(panel)} 格`)
    .replace(/\bP0*(\d+)\b/gi, (_, page: string) => `第 ${Number(page)} 页`)
    .replace(/\bpanel\s*(\d+)\b/gi, (_, panel: string) => `第 ${Number(panel)} 格`)
    .replace(/\bQA\b/g, "质检")
    .replace(/\bAI\b/g, "智能")
    .replace(/ComfyUI/g, "生成后端")
}

export function displayFileName(value?: string | null): string {
  const path = String(value ?? "")
  if (!path) return "未记录"
  const name = path.split(/[\\/]/).pop() || path
  return displayText(name)
    .replace(/[_-]+result\b/gi, " · 结果")
    .replace(/[_-]+backup\b/gi, " · 备份")
    .replace(/[_-]+context\b/gi, " · 上下文")
    .replace(/^context\b/i, "上下文")
}

function indexFrom(value: unknown, token: "EP" | "P" | "PANEL"): number {
  const pattern = token === "EP"
    ? /EP0*(\d+)/i
    : token === "PANEL"
      ? /PANEL0*(\d+)/i
      : /_P0*(\d+)/i
  const match = String(value ?? "").match(pattern)
  return match ? Number(match[1]) : 0
}

export function taskTarget(job: TaskJob): string {
  if (job.panel_id || job.page_id) {
    const source = job.panel_id || job.page_id
    const episode = indexFrom(source, "EP") || positiveNumber(job.episode_number)
    const page = indexFrom(job.page_id || source, "P")
    const panel = indexFrom(job.panel_id, "PANEL")
    return [
      episode ? `第 ${episode} 章` : "",
      page ? `第 ${page} 页` : "",
      panel ? `第 ${panel} 格` : "",
    ].filter(Boolean).join(" · ")
  }
  if (job.asset_alias) return displayText(job.asset_alias)
  return "未指定"
}

export function formatTaskTime(value?: string | null): string {
  const text = String(value ?? "").trim()
  if (!text) return "未记录"
  return text.replace("T", " ").replace(/\.\d+(?=(?:Z|[+-]\d\d:?\d\d)?$)/, "").replace(/Z$/, "")
}

export function diagnosticTitle(issue: TaskDiagnosticIssue): string {
  if (issue.panel_id) return internalIdDisplayName(issue.panel_id) || "分镜诊断"
  return diagnosticLabels[String(issue.type ?? "")] ?? "任务诊断"
}

export function diagnosticSeverity(value?: string): string {
  return severityLabels[String(value ?? "")] ?? "可重试"
}

export function diagnosticReason(value?: string): string {
  return diagnosticLabels[String(value ?? "")] ?? "等待后续处理"
}

export function taskSummaryText(job: TaskJob): string {
  const summary = job.result?.summary
  if (typeof summary === "string" || typeof summary === "number") return displayText(summary)
  if (summary && typeof summary === "object") return "任务已生成结构化结果，可预览结果文件查看完整内容。"
  return ""
}
