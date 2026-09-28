<script setup lang="ts">
import type { NotificationItem } from "./types";

defineProps<{
  notification: NotificationItem;
}>();

defineEmits<{
  dismiss: [id: string];
}>();
</script>

<template>
  <article
    class="app-toast"
    :class="notification.type"
    :role="notification.type === 'error' ? 'alert' : 'status'"
  >
    <div class="app-toast-content">
      <strong>{{ notification.title }}</strong>
      <p>{{ notification.message }}</p>
    </div>
    <button
      class="app-toast-close"
      type="button"
      aria-label="关闭提示"
      title="关闭提示"
      @click="$emit('dismiss', notification.id)"
    >
      &times;
    </button>
  </article>
</template>

<style scoped>
.app-toast {
  --toast-accent: var(--accent);
  display: grid;
  grid-template-columns: 4px minmax(0, 1fr) 28px;
  gap: 10px;
  align-items: start;
  min-height: 48px;
  overflow: hidden;
  border: 1px solid var(--line-strong);
  border-radius: 5px;
  background: var(--surface);
  color: var(--text);
  box-shadow: 0 8px 22px rgba(0, 0, 0, .25);
  pointer-events: auto;
}

.app-toast::before {
  content: "";
  width: 4px;
  height: 100%;
  background: var(--toast-accent);
}

.app-toast.success { --toast-accent: var(--ok); }
.app-toast.warn { --toast-accent: var(--warn); }
.app-toast.error { --toast-accent: var(--danger); }

.app-toast-content {
  min-width: 0;
  padding: 10px 0;
}

.app-toast strong {
  display: block;
  margin-bottom: 2px;
  font-size: 12px;
}

.app-toast p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.45;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.app-toast-close {
  width: 28px;
  min-width: 28px;
  height: 28px;
  min-height: 28px;
  margin: 6px 6px 0 0;
  padding: 0;
  border-color: transparent;
  background: transparent;
  color: var(--muted);
  font-size: 18px;
  line-height: 1;
}

.app-toast-close:hover,
.app-toast-close:focus-visible {
  border-color: var(--line-strong);
  background: var(--surface-mid);
  color: var(--text);
}
</style>
