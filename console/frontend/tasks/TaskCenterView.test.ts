import { mount } from "@vue/test-utils"
import { afterEach, describe, expect, it, vi } from "vitest"

import TaskCenterView from "./TaskCenterView.vue"
import type { TaskFilePreview, TaskJob } from "./types"

const jobs: TaskJob[] = [
  {
    id: "1790571556646-regenerate",
    label: "SSJ_COMIC_EP01_P001_PANEL02",
    status: "failed",
    stage: "regenerate",
    started: "2026-09-28T04:59:16",
    finished: "2026-09-28T04:59:17",
    episode_number: 1,
    result_path: "C:\\output\\SSJ_COMIC_EP01_P001_PANEL02_result.json",
    generation_context_path: "C:\\output\\context.json",
    backup_path: "C:\\output\\SSJ_COMIC_EP01_P001_PANEL02_backup.png",
    progress: { total: 1, completed: 0, failed: 1, current: "执行失败" },
    retry_payload: { stage: "regenerate" },
    diagnostics: {
      issues: [{
        type: "image_aspect_ratio_mismatch",
        severity: "retryable",
        message: "SSJ_COMIC_EP01_P001_PANEL02 图片比例不匹配",
        action: "调整构图后重试",
      }],
    },
    stderr_tail: "SSJ_COMIC_EP01_P001_PANEL02 failed",
    result: { summary: { completed: false } },
  },
  {
    id: "1790581176922-process-novel",
    label: "处理小说",
    status: "running",
    stage: "process_novel",
    started: "2026-09-28T07:39:36",
    episode_number: null,
    progress: { total: 4, completed: 2, failed: 0, current: "扫描章节" },
  },
  {
    id: "1790571446633-review",
    label: "页面组装和 QA",
    status: "passed",
    stage: "review",
    started: "2026-09-28T04:57:26",
    finished: "2026-09-28T04:57:31",
    episode_number: 1,
    progress: { total: 1, completed: 1, failed: 0, current: "已完成" },
  },
]

function mountView(overrides: Partial<{
  jobs: TaskJob[]
  filter: "all" | "running" | "waiting" | "failed" | "passed"
  selectedJobId: string
  taskFilePreview: TaskFilePreview | null
}> = {}) {
  return mount(TaskCenterView, {
    props: {
      jobs,
      filter: "all",
      selectedJobId: String(jobs[0].id),
      taskFilePreview: null,
      ...overrides,
    },
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("TaskCenterView", () => {
  it("以中文呈现任务、状态、阶段和内部对象编号", () => {
    const wrapper = mountView()

    expect(wrapper.text()).toContain("第 1 章 · 第 1 页 · 第 2 格")
    expect(wrapper.text()).toContain("重新生成")
    expect(wrapper.text()).toContain("生成审核")
    expect(wrapper.text()).toContain("图片比例不匹配")
    expect(wrapper.text()).not.toContain("SSJ_COMIC")
    expect(wrapper.text()).not.toContain("regenerate")
    expect(wrapper.text()).not.toContain("1790571556646")
  })

  it("通过事件输出筛选、刷新和任务选择", async () => {
    const wrapper = mountView()

    await wrapper.get('select[aria-label="筛选任务"]').setValue("running")
    await wrapper.get('button[aria-label="刷新任务"]').trigger("click")
    await wrapper.findAll(".task-main")[1].trigger("click")

    expect(wrapper.emitted("filter-change")?.[0]).toEqual(["running"])
    expect(wrapper.emitted("refresh")?.[0]).toEqual([])
    expect(wrapper.emitted("select")?.at(-1)).toEqual([String(jobs[1].id)])
  })

  it("在筛选后请求父运行时修正选择且不直接改写输入", async () => {
    const wrapper = mountView({ filter: "running", selectedJobId: String(jobs[0].id) })

    expect(wrapper.emitted("select")?.[0]).toEqual([String(jobs[1].id)])
    expect(wrapper.props("selectedJobId")).toBe(String(jobs[0].id))
    expect(wrapper.text()).toContain("处理小说")
    expect(wrapper.text()).not.toContain("图片比例不匹配")
  })

  it("只向父运行时发送取消和重试请求", async () => {
    const failed = mountView()
    await failed.get('button[aria-label="重试任务"]').trigger("click")
    expect(failed.emitted("retry")?.[0]).toEqual([String(jobs[0].id)])

    const running = mountView({ selectedJobId: String(jobs[1].id) })
    await running.get('button[aria-label="取消任务"]').trigger("click")
    expect(running.emitted("cancel")?.[0]).toEqual([String(jobs[1].id)])
  })

  it("呈现文件预览并输出全部文件动作", async () => {
    const preview: TaskFilePreview = {
      jobId: jobs[0].id,
      path: jobs[0].result_path || "",
      data: {
        name: "SSJ_COMIC_EP01_P001_PANEL02_result.json",
        size: 128,
        truncated: true,
        content: "SSJ_COMIC_EP01_P001_PANEL02 已完成",
      },
    }
    const wrapper = mountView({ taskFilePreview: preview })

    expect(wrapper.text()).toContain("128 字节 · 已截断")
    expect(wrapper.text()).toContain("第 1 章 · 第 1 页 · 第 2 格 已完成")
    expect(wrapper.text()).not.toContain("SSJ_COMIC")

    await wrapper.get('button[aria-label="预览结果"]').trigger("click")
    await wrapper.get('button[aria-label="下载文本"]').trigger("click")
    await wrapper.get('button[aria-label="在文件夹中显示"]').trigger("click")
    await wrapper.get('button[aria-label="打开结果目录"]').trigger("click")

    const base = { jobId: String(jobs[0].id), path: jobs[0].result_path }
    expect(wrapper.emitted("preview-file")?.[0]).toEqual([base])
    expect(wrapper.emitted("download-file")?.[0]).toEqual([base])
    expect(wrapper.emitted("file-action")?.[0]).toEqual([{ ...base, mode: "select" }])
    expect(wrapper.emitted("file-action")?.[1]).toEqual([{ ...base, mode: "folder" }])
  })

  it("不请求任务接口且不创建轮询", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch")
    const intervalSpy = vi.spyOn(globalThis, "setInterval")
    const wrapper = mountView()

    await wrapper.get('button[aria-label="刷新任务"]').trigger("click")

    expect(fetchSpy).not.toHaveBeenCalled()
    expect(intervalSpy).not.toHaveBeenCalled()
  })
})
