<script setup lang="ts">
import { onMounted, shallowRef, useTemplateRef } from "vue";

import type { DialogQueueItem, DialogResult } from "./types";

const props = defineProps<{
  dialog: DialogQueueItem;
}>();

const emit = defineEmits<{
  confirm: [result: DialogResult];
  cancel: [];
}>();

const inputValue = shallowRef(props.dialog.options.defaultValue);
const panel = useTemplateRef<HTMLElement>("panel");
const input = useTemplateRef<HTMLInputElement>("input");
const confirmButton = useTemplateRef<HTMLButtonElement>("confirmButton");

function confirm() {
  emit("confirm", props.dialog.options.prompt ? inputValue.value : true);
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    emit("cancel");
    return;
  }
  if (event.key !== "Tab" || !panel.value) return;
  const focusable = Array.from(panel.value.querySelectorAll<HTMLElement>("input, button:not([disabled])"));
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

onMounted(() => {
  if (props.dialog.options.prompt) input.value?.focus();
  else confirmButton.value?.focus();
});
</script>

<template>
  <div
    class="app-dialog-overlay"
    role="presentation"
    @mousedown.self="$emit('cancel')"
    @keydown="handleKeydown"
  >
    <section
      ref="panel"
      class="app-dialog"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="`${dialog.id}-title`"
      :aria-describedby="`${dialog.id}-message`"
    >
      <header class="app-dialog-head">
        <span class="app-dialog-kind">{{ dialog.options.kind }}</span>
        <h2 :id="`${dialog.id}-title`">{{ dialog.options.title }}</h2>
      </header>
      <p :id="`${dialog.id}-message`">{{ dialog.options.message }}</p>
      <input
        v-if="dialog.options.prompt"
        ref="input"
        v-model="inputValue"
        class="app-dialog-input"
        autocomplete="off"
        @keydown.enter.prevent="confirm"
      >
      <footer class="app-dialog-actions">
        <button type="button" @click="$emit('cancel')">
          {{ dialog.options.cancelText }}
        </button>
        <button ref="confirmButton" class="primary" type="button" @click="confirm">
          {{ dialog.options.confirmText }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.app-dialog-overlay {
  position: fixed;
  z-index: 1300;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(3, 8, 18, .78);
}

.app-dialog {
  width: min(460px, 100%);
  overflow: hidden;
  border: 1px solid var(--line-strong);
  border-radius: 7px;
  background: var(--surface);
  color: var(--text);
  box-shadow: 0 18px 46px rgba(0, 0, 0, .38);
}

.app-dialog-head {
  padding: 16px 18px 10px;
  border-bottom: 1px solid var(--line);
}

.app-dialog-kind {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  margin-bottom: 8px;
  border: 1px solid var(--accent);
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-size: 11px;
  font-weight: 900;
}

.app-dialog h2 {
  margin: 0;
  font-size: 18px;
  line-height: 1.3;
}

.app-dialog p {
  margin: 0;
  padding: 14px 18px;
  color: var(--muted);
  font-weight: 700;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.app-dialog-input {
  width: calc(100% - 36px);
  margin: 0 18px 14px;
}

.app-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px 16px;
  border-top: 1px solid var(--line);
}
</style>
