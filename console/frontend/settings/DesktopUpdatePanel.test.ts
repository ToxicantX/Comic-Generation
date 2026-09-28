import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import DesktopUpdatePanel from "./DesktopUpdatePanel.vue";
import type { DesktopUpdateState } from "./types";

function updateState(overrides: Partial<DesktopUpdateState> = {}): DesktopUpdateState {
  return {
    enabled: true,
    status: "idle",
    currentVersion: "0.1.0",
    availableVersion: null,
    progress: null,
    lastCheckedAt: null,
    message: "尚未检查更新",
    ...overrides,
  };
}

describe("DesktopUpdatePanel", () => {
  it("shows the current version and emits a manual update check", async () => {
    const wrapper = mount(DesktopUpdatePanel, { props: { state: updateState() } });

    expect(wrapper.text()).toContain("当前版本");
    expect(wrapper.text()).toContain("0.1.0");
    await wrapper.get('[data-test="check-update"]').trigger("click");

    expect(wrapper.emitted("check")).toEqual([[]]);
  });

  it("renders download progress without offering an early install", () => {
    const wrapper = mount(DesktopUpdatePanel, {
      props: {
        state: updateState({
          status: "downloading",
          availableVersion: "0.2.0",
          progress: { percent: 42.25, transferred: 425, total: 1000, bytesPerSecond: 200 },
          message: "正在后台下载更新",
        }),
      },
    });

    expect(wrapper.text()).toContain("0.2.0");
    expect(wrapper.text()).toContain("42%");
    expect(wrapper.find('[data-test="install-update"]').exists()).toBe(false);
  });

  it("offers restart only after the update has downloaded", async () => {
    const wrapper = mount(DesktopUpdatePanel, {
      props: {
        state: updateState({
          status: "downloaded",
          availableVersion: "0.2.0",
          message: "新版本已下载，可重启完成升级",
        }),
      },
    });

    await wrapper.get('[data-test="install-update"]').trigger("click");
    expect(wrapper.emitted("install")).toEqual([[]]);
  });

  it("explains that development mode does not contact the update service", () => {
    const wrapper = mount(DesktopUpdatePanel, {
      props: {
        state: updateState({
          enabled: false,
          status: "disabled",
          message: "开发模式不连接更新服务",
        }),
      },
    });

    expect(wrapper.text()).toContain("开发模式不连接更新服务");
    expect(wrapper.get('[data-test="check-update"]').attributes("disabled")).toBeDefined();
  });
});
