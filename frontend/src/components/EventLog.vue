<script setup>
import { state } from '../store.js'
import { fmtTimeET } from '../format.js'

const cls = (s) => ({ live: 'up', stale: 'warn', unavailable: 'down', history_unavailable: 'down' }[s] || 'accent')
</script>

<template>
  <section class="panel">
    <div class="panel-head">Feed event log <span class="sub">feed_events table</span></div>
    <div class="panel-body">
      <div v-for="(e, i) in state.events" :key="i" class="ev" data-testid="event">
        <span class="muted">{{ fmtTimeET(e.time_ms) }}</span>
        <b :class="cls(e.state)">{{ e.state.toUpperCase() }}</b>
        <span class="muted">{{ e.detail }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.ev { display: grid; grid-template-columns: 62px 96px 1fr; gap: 6px; padding: 2px 0; border-bottom: 1px dashed #241d36; font-size: 11px; }
.ev span:last-child { word-break: break-word; }
</style>
