import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import DialogHost from "./DialogHost.vue";
import { DIALOG_EVENT, type DialogOptions, type DialogResult } from "./types";

function requestDialog(options: DialogOptions) {
  return new Promise<DialogResult>((resolve) => {
    window.dispatchEvent(new CustomEvent(DIALOG_EVENT, { detail: { options, resolve } }));
  });
}

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("DialogHost", () => {
  it("confirms and cancels boolean dialogs", async () => {
    const wrapper = mount(DialogHost, { attachTo: document.body });
    const confirmed = requestDialog({ message: "确认生成？", confirmText: "开始" });
    await wrapper.vm.$nextTick();
    expect(document.activeElement?.textContent?.trim()).toBe("开始");
    await wrapper.get("button.primary").trigger("click");
    await expect(confirmed).resolves.toBe(true);

    const cancelled = requestDialog({ message: "确认取消？" });
    await wrapper.vm.$nextTick();
    await wrapper.findAll("button")[0].trigger("click");
    await expect(cancelled).resolves.toBe(false);
    wrapper.unmount();
  });

  it("returns prompt text and null when prompt input is cancelled", async () => {
    const wrapper = mount(DialogHost, { attachTo: document.body });
    const submitted = requestDialog({ message: "审核备注", prompt: true, defaultValue: "原值" });
    await wrapper.vm.$nextTick();
    const input = wrapper.get("input");
    expect(input.element).toBe(document.activeElement);
    await input.setValue("需要调整构图");
    await input.trigger("keydown", { key: "Enter" });
    await expect(submitted).resolves.toBe("需要调整构图");

    const cancelled = requestDialog({ message: "审核备注", prompt: true });
    await wrapper.vm.$nextTick();
    await wrapper.get(".app-dialog-overlay").trigger("mousedown");
    await expect(cancelled).resolves.toBeNull();

    const escaped = requestDialog({ message: "按键取消", prompt: true });
    await wrapper.vm.$nextTick();
    await wrapper.get(".app-dialog-overlay").trigger("keydown", { key: "Escape" });
    await expect(escaped).resolves.toBeNull();
    wrapper.unmount();
  });

  it("queues consecutive requests and restores the previous focus", async () => {
    vi.useFakeTimers();
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();
    const wrapper = mount(DialogHost, { attachTo: document.body });

    const first = requestDialog({ title: "第一步", message: "第一条" });
    await wrapper.vm.$nextTick();
    expect(wrapper.get("h2").text()).toBe("第一步");
    const second = requestDialog({ title: "第二步", message: "第二条" });
    await wrapper.get("button.primary").trigger("click");
    await expect(first).resolves.toBe(true);
    vi.runOnlyPendingTimers();
    await wrapper.vm.$nextTick();
    expect(wrapper.get("h2").text()).toBe("第二步");
    await wrapper.findAll("button")[0].trigger("click");
    await expect(second).resolves.toBe(false);
    vi.runOnlyPendingTimers();
    expect(document.activeElement).toBe(trigger);
    wrapper.unmount();
  });
});
