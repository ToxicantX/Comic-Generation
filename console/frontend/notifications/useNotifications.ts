import { onMounted, onUnmounted, readonly, shallowRef } from "vue";

import {
  NOTIFICATION_EVENT,
  type NotificationInput,
  type NotificationItem,
  type NotificationType,
} from "./types";

const MAX_VISIBLE_NOTIFICATIONS = 4;
const DEFAULT_DURATION_MS = 4_200;
const ERROR_DURATION_MS = 7_000;
const notificationTypes = new Set<NotificationType>(["info", "success", "warn", "error"]);

function normalizeNotification(input: NotificationInput, id: string): NotificationItem {
  const type = notificationTypes.has(input.type as NotificationType) ? input.type as NotificationType : "info";
  return {
    id,
    message: String(input.message || ""),
    type,
    title: String(input.title || "提示"),
    durationMs: input.durationMs ?? (type === "error" ? ERROR_DURATION_MS : DEFAULT_DURATION_MS),
  };
}

export function useNotifications() {
  const notifications = shallowRef<NotificationItem[]>([]);
  const timers = new Map<string, number>();
  let sequence = 0;

  function dismiss(id: string) {
    const timer = timers.get(id);
    if (timer !== undefined) window.clearTimeout(timer);
    timers.delete(id);
    notifications.value = notifications.value.filter((notification) => notification.id !== id);
  }

  function add(input: NotificationInput) {
    sequence += 1;
    const item = normalizeNotification(input, `notification-${Date.now()}-${sequence}`);
    const next = [...notifications.value, item];
    while (next.length > MAX_VISIBLE_NOTIFICATIONS) {
      const removed = next.shift();
      if (removed) dismiss(removed.id);
    }
    notifications.value = next;
    if (item.durationMs > 0) {
      timers.set(item.id, window.setTimeout(() => dismiss(item.id), item.durationMs));
    }
  }

  function handleNotification(event: Event) {
    const detail = (event as CustomEvent<NotificationInput>).detail;
    if (detail && typeof detail === "object") add(detail);
  }

  onMounted(() => {
    window.addEventListener(NOTIFICATION_EVENT, handleNotification);
    const pending = window.__comicPendingNotifications?.splice(0) ?? [];
    pending.forEach(add);
  });

  onUnmounted(() => {
    window.removeEventListener(NOTIFICATION_EVENT, handleNotification);
    timers.forEach((timer) => window.clearTimeout(timer));
    timers.clear();
  });

  return {
    notifications: readonly(notifications),
    add,
    dismiss,
  };
}
