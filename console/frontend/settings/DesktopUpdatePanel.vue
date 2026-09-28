<script setup lang="ts">
import { computed } from "vue";

import type { DesktopUpdateState } from "./types";

const props = defineProps<{
  state: DesktopUpdateState;
}>();

const emit = defineEmits<{
  check: [];
  install: [];
}>();

const statusLabel = computed(() => ({
  disabled: "已停用",
  idle: "待检查",
  checking: "检查中",
  "up-to-date": "已是最新",
  available: "发现更新",
  downloading: "下载中",
  downloaded: "等待安装",
  installing: "正在升级",
  error: "检查失败",
}[props.state.status]));
const progressPercent = computed(() => Math.round(props.state.progress?.percent || 0));
const checkDisabled = computed(() => !props.state.enabled || [
  "checking",
  "available",
  "downloading",
  "downloaded",
  "installing",
].includes(props.state.status));
const lastChecked = computed(() => {
  if (!props.state.lastCheckedAt) return "尚未检查";
  const date = new Date(props.state.lastCheckedAt);
  return Number.isNaN(date.getTime()) ? "已检查" : date.toLocaleString("zh-CN", { hour12: false });
});
</script>

<template>
  <section class="update-panel">
    <header class="update-header">
      <div>
        <p class="eyebrow">桌面客户端</p>
        <h2>软件更新</h2>
      </div>
      <span :class="['status-badge', state.status]">{{ statusLabel }}</span>
    </header>

    <dl class="version-list">
      <div>
        <dt>当前版本</dt>
        <dd>v{{ state.currentVersion }}</dd>
      </div>
      <div>
        <dt>可用版本</dt>
        <dd>{{ state.availableVersion ? `v${state.availableVersion}` : "-" }}</dd>
      </div>
      <div>
        <dt>上次检查</dt>
        <dd>{{ lastChecked }}</dd>
      </div>
    </dl>

    <div v-if="state.status === 'downloading'" class="download-progress">
      <div class="progress-label">
        <span>后台下载</span>
        <strong>{{ progressPercent }}%</strong>
      </div>
      <div class="progress-track" role="progressbar" :aria-valuenow="progressPercent" aria-valuemin="0" aria-valuemax="100">
        <span :style="{ width: `${progressPercent}%` }"></span>
      </div>
    </div>

    <p class="update-message">{{ state.message }}</p>

    <div class="update-actions">
      <button
        type="button"
        data-test="check-update"
        :disabled="checkDisabled"
        @click="emit('check')"
      >
        {{ state.status === "checking" ? "检查中..." : "检查更新" }}
      </button>
      <button
        v-if="state.status === 'downloaded'"
        class="primary"
        type="button"
        data-test="install-update"
        @click="emit('install')"
      >
        重启并升级
      </button>
    </div>
  </section>
</template>

<style scoped>
.update-panel {
  display: grid;
  gap: 12px;
  min-width: 0;
  padding: 16px;
  color: #e7e8ea;
  background: #181b20;
  border: 1px solid #343940;
  border-radius: 6px;
}

.update-header,
.progress-label,
.update-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.eyebrow {
  margin: 0 0 3px;
  color: #9ba1aa;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

.update-header h2 {
  margin: 0;
  font-size: 17px;
}

.status-badge {
  padding: 3px 7px;
  color: #b9bec5;
  border: 1px solid #4a5059;
  border-radius: 4px;
  font-size: 11px;
}

.status-badge.up-to-date,
.status-badge.downloaded { color: #9fd5ac; border-color: #3d6748; }
.status-badge.error { color: #e7a3a3; border-color: #704343; }
.status-badge.checking,
.status-badge.available,
.status-badge.downloading,
.status-badge.installing { color: #e5c978; border-color: #77652e; }

.version-list {
  display: grid;
  gap: 1px;
  margin: 0;
  overflow: hidden;
  background: #343940;
  border: 1px solid #343940;
}

.version-list div {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 10px;
  padding: 8px 9px;
  background: #111419;
}

.version-list dt { color: #8c939c; font-size: 11px; }
.version-list dd { margin: 0; color: #cdd1d6; font-size: 12px; }

.download-progress { display: grid; gap: 7px; }
.progress-label { color: #b9bec5; font-size: 11px; }
.progress-track { height: 5px; overflow: hidden; background: #0f1115; border: 1px solid #343940; }
.progress-track span { display: block; height: 100%; background: #d4b45f; transition: width 160ms ease; }

.update-message {
  min-height: 18px;
  margin: 0;
  color: #9299a3;
  font-size: 11px;
  line-height: 1.5;
}

.update-actions { justify-content: flex-end; }
.update-actions button {
  min-height: 34px;
  padding: 6px 10px;
  color: #d8dbe0;
  background: #22262c;
  border: 1px solid #414750;
  border-radius: 4px;
  font: inherit;
  cursor: pointer;
}
.update-actions button.primary { color: #111419; background: #d4b45f; border-color: #d4b45f; font-weight: 750; }
.update-actions button:disabled { opacity: .5; cursor: not-allowed; }
</style>
