<script setup>
import { computed } from 'vue'
import { state } from '../store.js'
import { FEED_STATES, fmtTimeET, nyseSession } from '../format.js'

const session = computed(() => nyseSession(state.now))
const feed = computed(() => state.status?.feed)
const fs = computed(() => FEED_STATES[feed.value?.state] || FEED_STATES.starting)
const dateET = computed(() => new Date(state.now).toLocaleDateString('en-US', {
  timeZone: 'America/New_York', weekday: 'short', month: 'short', day: '2-digit', year: 'numeric',
}))
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <span class="logo">◆</span>
      <span class="name">FER'S MARKET DESK</span>
      <span class="tag">SIMULATION WORKSTATION · PART 4.1</span>
    </div>
    <div class="right">
      <span class="pill" :class="session.cls" data-testid="market-session">{{ session.label }}</span>
      <span class="pill up">CRYPTO 24/7</span>
      <span class="feed" data-testid="feed-badge">
        <span class="dot" :class="state.connected ? fs.dot : 'bad'"></span>
        <span :class="state.connected ? fs.cls : 'down'">
          {{ state.connected ? `FEED ${fs.label}` : 'BACKEND OFFLINE' }}
        </span>
        <span class="muted" v-if="feed"> · {{ feed.source }}</span>
      </span>
      <span class="clock" data-testid="clock">
        <span class="muted">{{ dateET }}</span>
        <b>{{ fmtTimeET(state.now) }}</b> <span class="muted">ET</span>
      </span>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 6px 12px; background: linear-gradient(90deg, #241638, #1c1729 45%, #2a1430);
  border-bottom: 1px solid var(--accent);
}
.brand { display: flex; align-items: baseline; gap: 10px; }
.logo { color: var(--down); font-size: 16px; }
.name { font-weight: 700; font-size: 15px; letter-spacing: .12em; color: var(--text); }
.tag { color: var(--accent); font-size: 10px; letter-spacing: .1em; }
.right { display: flex; align-items: center; gap: 14px; }
.clock b { font-size: 14px; margin-left: 6px; color: var(--text); }
.feed { white-space: nowrap; }
</style>
