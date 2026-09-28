<script setup lang="ts">
import AppDialog from "./AppDialog.vue";
import { useDialogQueue } from "./useDialogQueue";

const { current, settle, cancel } = useDialogQueue();
</script>

<template>
  <AppDialog
    v-if="current"
    :key="current.id"
    :dialog="current"
    @confirm="settle"
    @cancel="cancel(current)"
  />
</template>
