<script setup>
import { state } from '../store.js'
</script>

<template>
  <div class="toasts" data-testid="toasts">
    <div v-for="t in state.toasts" :key="t.id" class="toast" :class="t.kind">{{ t.text }}</div>
  </div>
</template>

<style scoped>
.toasts { position: fixed; top: 64px; left: 50%; transform: translateX(-50%); z-index: 50; display: flex; flex-direction: column; gap: 6px; pointer-events: none; }
.toast { padding: 7px 14px; background: #241d36; border: 1px solid var(--accent); font-weight: 700; font-size: 12px; box-shadow: 0 4px 18px rgba(0,0,0,.5); }
.toast.buy { border-color: var(--up); color: var(--up); }
.toast.sell { border-color: var(--down); color: var(--down); }
.toast.skip { border-color: var(--warn); color: var(--warn); }
.toast.order { color: #d8b4fe; }
</style>
