<script setup lang="ts">
import type { DesktopDirectoryKey, DesktopInfo } from "./types";

defineProps<{
  info: DesktopInfo;
}>();

const emit = defineEmits<{
  open: [key: DesktopDirectoryKey];
}>();

const directories: Array<{ key: DesktopDirectoryKey; label: string }> = [
  { key: "output", label: "输出目录" },
  { key: "backups", label: "备份目录" },
  { key: "logs", label: "日志目录" },
];
</script>

<template>
  <section class="desktop-storage">
    <header>
      <div>
        <p>桌面应用</p>
        <h2>本地存储</h2>
      </div>
      <span class="runtime-badge">{{ info.runtimeMode === "local" ? "本地运行时" : "外部运行时" }}</span>
    </header>
    <div class="directory-actions">
      <button
        v-for="directory in directories"
        :key="directory.key"
        type="button"
        :data-test="`open-${directory.key}-directory`"
        @click="emit('open', directory.key)"
      >
        <span aria-hidden="true">□</span>
        <strong>{{ directory.label }}</strong>
      </button>
    </div>
    <small>目录由桌面主进程按固定白名单打开，网页无法提交任意系统路径。</small>
  </section>
</template>

<style scoped>
.desktop-storage {
  display: grid;
  gap: 11px;
  min-width: 0;
  padding: 16px;
  background: #181b20;
  border: 1px solid #343940;
  border-radius: 6px;
}

.desktop-storage header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.desktop-storage p {
  margin: 0 0 3px;
  color: #9ba1aa;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

.desktop-storage h2 {
  margin: 0;
  font-size: 17px;
}

.runtime-badge {
  padding: 3px 7px;
  color: #9fd5ac;
  border: 1px solid #3d6748;
  border-radius: 4px;
  font-size: 11px;
}

.directory-actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.directory-actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-width: 0;
  min-height: 34px;
  padding: 6px 9px;
  color: #d7dbe0;
  background: #111419;
  border: 1px solid #414750;
  border-radius: 4px;
  font: inherit;
  cursor: pointer;
}

.directory-actions button:hover {
  color: #fff;
  border-color: #69717d;
}

.directory-actions strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.desktop-storage small {
  color: #9299a3;
  font-size: 11px;
  line-height: 1.5;
}
</style>
