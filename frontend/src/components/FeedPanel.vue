<script setup>
import { computed } from 'vue'
import { state, setOutage } from '../store.js'
import { FEED_STATES, ageClass, fmtAge, fmtTimeET } from '../format.js'

const feed = computed(() => state.status?.feed)
const fs = computed(() => FEED_STATES[feed.value?.state] || FEED_STATES.starting)
const msgAge = computed(() => feed.value?.last_message_ms ? state.now - feed.value.last_message_ms : null)
const tick = computed(() => state.ticks[state.symbol])
const hist = computed(() => state.status?.history?.[`${state.symbol}|${state.interval}`] || '—')
</script>

<template>
  <section class="panel">
    <div class="panel-head">Feed status <span class="sub">{{ feed?.mode === 'fake' ? 'FAKE MODE (tests)' : 'live source' }}</span></div>
    <div class="panel-body">
      <div class="state" data-testid="feed-state">
        <span class="dot" :class="fs.dot"></span><b :class="fs.cls">{{ fs.label }}</b>
      </div>
      <div class="detail muted">{{ feed?.detail || '—' }}</div>
      <dl class="kv">
        <dt>Source</dt><dd class="accent">{{ feed?.source || '—' }}</dd>
        <dt>Transport</dt><dd>{{ feed?.mode === 'fake' ? 'fake generator' : 'Yahoo WS' }} → FastAPI → SQLite → browser WS</dd>
        <dt>Last msg (any sym)</dt><dd :class="ageClass(msgAge)">{{ fmtAge(msgAge) }} ago</dd>
        <dt>{{ state.symbol }} source time</dt><dd>{{ fmtTimeET(tick?.source_time_ms) }} ET</dd>
        <dt>{{ state.symbol }} received</dt><dd>{{ fmtTimeET(tick?.received_ms) }} ET</dd>
        <dt>Data age</dt><dd :class="ageClass(tick ? state.now - tick.source_time_ms : null)">{{ fmtAge(tick ? state.now - tick.source_time_ms : null) }}</dd>
        <dt>Transit (recv − src)</dt><dd>{{ tick ? fmtAge(tick.received_ms - tick.source_time_ms) : '—' }}</dd>
        <dt>Messages</dt><dd>{{ feed?.messages ?? 0 }}</dd>
        <dt>Reconnects</dt><dd>{{ feed?.reconnect_attempts ?? 0 }}</dd>
        <dt>History {{ state.interval }}</dt><dd>{{ hist }}</dd>
      </dl>
      <div class="actions">
        <button class="danger" :class="{ active: feed?.simulated_outage }" data-testid="outage-btn"
                @click="setOutage(!feed?.simulated_outage)">
          {{ feed?.simulated_outage ? '■ End simulated outage' : '⚠ Simulate feed outage' }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.state { font-size: 16px; margin-bottom: 2px; }
.detail { margin-bottom: 8px; font-size: 11px; min-height: 14px; word-break: break-word; }
.actions { margin-top: 10px; }
.actions button { width: 100%; }
</style>
