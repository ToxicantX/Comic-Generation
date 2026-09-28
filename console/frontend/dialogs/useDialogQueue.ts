import { onMounted, onUnmounted, shallowReadonly, shallowRef } from "vue";

import {
  DIALOG_EVENT,
  type DialogEventDetail,
  type DialogOptions,
  type DialogQueueItem,
  type DialogResult,
  type NormalizedDialogOptions,
} from "./types";

function normalizeOptions(options: DialogOptions): NormalizedDialogOptions {
  return {
    title: String(options.title || "确认操作"),
    message: String(options.message || ""),
    kind: String(options.kind || "确认"),
    confirmText: String(options.confirmText || "确认"),
    cancelText: String(options.cancelText || "取消"),
    prompt: Boolean(options.prompt),
    defaultValue: String(options.defaultValue || ""),
  };
}

export function useDialogQueue() {
  const current = shallowRef<DialogQueueItem | null>(null);
  const pending: DialogQueueItem[] = [];
  let sequence = 0;

  function promote() {
    if (!current.value) current.value = pending.shift() ?? null;
  }

  function enqueue(detail: DialogEventDetail) {
    sequence += 1;
    const returnFocus = current.value?.returnFocus
      ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    pending.push({
      id: `dialog-${Date.now()}-${sequence}`,
      options: normalizeOptions(detail.options),
      resolve: detail.resolve,
      returnFocus,
    });
    promote();
  }

  function settle(result: DialogResult) {
    const active = current.value;
    if (!active) return;
    current.value = null;
    active.resolve(result);
    window.setTimeout(() => {
      if (pending.length) promote();
      else if (active.returnFocus?.isConnected) active.returnFocus.focus();
    }, 0);
  }

  function cancel(item: DialogQueueItem) {
    settle(item.options.prompt ? null : false);
  }

  function handleDialog(event: Event) {
    const detail = (event as CustomEvent<DialogEventDetail>).detail;
    if (detail?.options && typeof detail.resolve === "function") enqueue(detail);
  }

  onMounted(() => window.addEventListener(DIALOG_EVENT, handleDialog));

  onUnmounted(() => {
    window.removeEventListener(DIALOG_EVENT, handleDialog);
    if (current.value) {
      current.value.resolve(current.value.options.prompt ? null : false);
      current.value = null;
    }
    pending.splice(0).forEach((item) => item.resolve(item.options.prompt ? null : false));
  });

  return {
    current: shallowReadonly(current),
    settle,
    cancel,
  };
}
