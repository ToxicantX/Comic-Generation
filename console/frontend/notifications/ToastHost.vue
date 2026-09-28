<script setup lang="ts">
import NotificationToast from "./NotificationToast.vue";
import { useNotifications } from "./useNotifications";

const { notifications, dismiss } = useNotifications();
</script>

<template>
  <TransitionGroup name="toast" tag="div" class="app-toast-stack">
    <NotificationToast
      v-for="notification in notifications"
      :key="notification.id"
      :notification="notification"
      @dismiss="dismiss"
    />
  </TransitionGroup>
</template>

<style scoped>
.app-toast-stack {
  position: fixed;
  z-index: 1200;
  top: 16px;
  right: 16px;
  display: grid;
  gap: 8px;
  width: min(360px, calc(100vw - 32px));
  pointer-events: none;
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity 140ms ease, transform 140ms ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

@media (prefers-reduced-motion: reduce) {
  .toast-enter-active,
  .toast-leave-active {
    transition: none;
  }
}
</style>
