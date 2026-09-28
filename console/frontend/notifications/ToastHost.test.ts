import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import ToastHost from "./ToastHost.vue";
import { NOTIFICATION_EVENT } from "./types";

afterEach(() => {
  vi.useRealTimers();
  window.__comicPendingNotifications = [];
});

describe("ToastHost", () => {
  it("renders and dismisses a notification from the legacy event bridge", async () => {
    const wrapper = mount(ToastHost, { attachTo: document.body });

    window.dispatchEvent(new CustomEvent(NOTIFICATION_EVENT, {
      detail: { message: "生成完成", title: "任务", type: "success", durationMs: 0 },
    }));
    await wrapper.vm.$nextTick();

    expect(wrapper.get("strong").text()).toBe("任务");
    expect(wrapper.get("p").text()).toBe("生成完成");
    expect(wrapper.get("article").classes()).toContain("success");

    await wrapper.get("button").trigger("click");
    expect(wrapper.find("article").exists()).toBe(false);
    wrapper.unmount();
  });

  it("limits the visible stack and automatically closes timed notifications", async () => {
    vi.useFakeTimers();
    const wrapper = mount(ToastHost);

    for (let index = 0; index < 5; index += 1) {
      window.dispatchEvent(new CustomEvent(NOTIFICATION_EVENT, {
        detail: { message: `通知 ${index}`, durationMs: 100 },
      }));
    }
    await wrapper.vm.$nextTick();
    expect(wrapper.findAll("article")).toHaveLength(4);
    expect(wrapper.text()).not.toContain("通知 0");

    vi.advanceTimersByTime(100);
    await wrapper.vm.$nextTick();
    expect(wrapper.findAll("article")).toHaveLength(0);
    wrapper.unmount();
  });
});
