import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import ReviewCenterView from "./ReviewCenterView.vue";
import type { ReviewCenterData } from "./types";

const outputTarget = {
  module: "workflow",
  tab: "media",
  episode: 1,
  focus_page_id: "SSJ_COMIC_EP01_P001",
};

const fixture: ReviewCenterData = {
  project: { slug: "ssj-comic", title: "山海纪" },
  summary: { outputs: 2, breakdowns: 1, settings: 1, assets: 0, jobs: 1, total: 4 },
  items: [
    {
      id: "output-1-SSJ_COMIC_EP01_P001",
      kind: "output",
      kind_label: "生成结果",
      title: "SSJ_COMIC_EP01_P001_PANEL01 生成结果待审核",
      detail: "QA 已完成，等待人工确认",
      status: "pending_review",
      status_label: "待审核",
      action_label: "审核本页",
      target: outputTarget,
      updated: "2026-09-28T12:35:00",
      count: 2,
      batch: { output_ids: [11, 12], scope_page_id: "SSJ_COMIC_EP01_P001" },
    },
    {
      id: "setting-7",
      kind: "setting",
      kind_label: "小说设定",
      title: "角色设定待审核：云澈",
      detail: "AI 提取 · 草稿",
      status: "draft",
      status_label: "草稿",
      action_label: "审核设定",
      target: { module: "settingsLibrary", setting_id: 7 },
      updated: "2026-09-28T12:20:00",
      count: 1,
    },
  ],
  timeline: [
    {
      id: 31,
      target_type: "generated_output",
      target_type_label: "生成结果",
      target_id: "11",
      target_label: "SSJ_COMIC_EP01_P001_PANEL01 生成结果",
      action: "needs_work",
      action_label: "退回修改",
      comment: "人物面部需要修正",
      created_at: "2026-09-28T12:30:00",
      change_summary: ["review_status：pending_review → needs_work"],
      change_details: [{ field: "review_status", label: "审核状态", before: "待审核", after: "待修改" }],
      target: outputTarget,
    },
    {
      id: 32,
      target_type: "setting",
      target_type_label: "小说设定",
      target_id: "7",
      target_label: "云澈",
      action: "approve",
      action_label: "通过",
      comment: "设定可用",
      created_at: "2026-09-28T12:40:00",
      change_summary: ["审核状态：待审核 → 已通过"],
      change_details: [],
      target: { module: "settingsLibrary", setting_id: 7 },
    },
  ],
  review_stats: {
    range: "30d",
    range_label: "最近 30 天",
    total: 2,
    return_total: 1,
    return_reasons: [{ label: "人物面部需要修正", count: 1 }],
    actions: [{ label: "退回修改", count: 1 }, { label: "通过", count: 1 }],
    target_types: [{ label: "生成结果", count: 1 }, { label: "小说设定", count: 1 }],
  },
  timeline_query: { type: "all", limit: 40, range: "30d" },
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ReviewCenterView", () => {
  it("renders the complete review center in Chinese without exposing internal IDs", () => {
    const wrapper = mount(ReviewCenterView, {
      props: {
        reviewCenter: fixture,
        selectedQueueItemId: "output-1-SSJ_COMIC_EP01_P001",
        selectedTimelineItemId: "31",
        timelineRange: "30d",
      },
    });

    expect(wrapper.text()).toContain("山海纪 · 审核中心");
    expect(wrapper.text()).toContain("生成结果");
    expect(wrapper.text()).toContain("第 1 章 · 第 1 页 · 第 1 格 生成结果待审核");
    expect(wrapper.text()).toContain("质检 已完成");
    expect(wrapper.text()).toContain("人物面部需要修正");
    expect(wrapper.text()).toContain("审核状态：待审核 → 待修改");
    expect(wrapper.text()).toContain("历史聚合1 条");
    expect(wrapper.text()).not.toContain("SSJ_COMIC");
    expect(wrapper.text()).not.toContain("#31");
    wrapper.unmount();
  });

  it("emits every parent-owned filter, selection and review action", async () => {
    const fetchSpy = vi.spyOn(window, "fetch");
    const intervalSpy = vi.spyOn(window, "setInterval");
    const wrapper = mount(ReviewCenterView, {
      props: {
        reviewCenter: fixture,
        selectedQueueItemId: "output-1-SSJ_COMIC_EP01_P001",
        selectedTimelineItemId: "31",
      },
    });

    await wrapper.get('[aria-label="刷新审核队列"]').trigger("click");
    await wrapper.get('[aria-label="筛选审核队列"]').setValue("setting");
    await wrapper.findAll(".queue-item")[1].trigger("click");
    await wrapper.get('[title="通过本页全部待审核输出"]').trigger("click");
    await wrapper.get('[title="在工作区定位该对象"]').trigger("click");
    await wrapper.get('[aria-label="筛选审核时间线"]').setValue("setting");
    await wrapper.get('[aria-label="审核时间范围"]').setValue("7d");
    await wrapper.get('[aria-label="审核记录数量"]').setValue("80");
    await wrapper.findAll(".timeline-list button")[1].trigger("click");
    await wrapper.findAll(".jump-button")[0].trigger("click");

    expect(wrapper.emitted("refresh")).toHaveLength(1);
    expect(wrapper.emitted("queueFilterChange")?.[0]).toEqual(["setting"]);
    expect(wrapper.emitted("selectQueueItem")?.[0]).toEqual(["setting-7"]);
    expect(wrapper.emitted("reviewOutputBatch")?.[0]).toEqual([fixture.items?.[0], "approve"]);
    expect(wrapper.emitted("openTarget")?.[0]).toEqual([outputTarget]);
    expect(wrapper.emitted("timelineFilterChange")?.[0]).toEqual(["setting"]);
    expect(wrapper.emitted("timelineRangeChange")?.[0]).toEqual(["7d"]);
    expect(wrapper.emitted("timelineLimitChange")?.[0]).toEqual([80]);
    expect(wrapper.emitted("selectTimelineItem")?.at(-1)).toEqual(["32"]);
    expect(wrapper.emitted("openTarget")?.at(-1)).toEqual([outputTarget]);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(intervalSpy).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("honors externally controlled queue filters and empty selections", () => {
    const wrapper = mount(ReviewCenterView, {
      props: {
        reviewCenter: fixture,
        queueFilter: "job",
        selectedQueueItemId: "missing",
        selectedTimelineItemId: "missing",
      },
    });

    expect(wrapper.text()).toContain("当前筛选下没有待处理审核项");
    expect(wrapper.text()).toContain("选择左侧审核项查看对象详情");
    expect(wrapper.text()).toContain("人物面部需要修正");
    wrapper.unmount();
  });
});
