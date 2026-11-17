<script setup>
import { ref } from 'vue'
import { state } from '../store.js'
import { fmtPrice, fmtTimeET, fmtVol } from '../format.js'

const tab = ref('events')
const cls = (s) => ({ live: 'up', stale: 'warn', unavailable: 'down', history_unavailable: 'down' }[s] || 'accent')
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <span class="tabs">
        <button :class="{ active: tab === 'events' }" data-testid="tab-events" @click="tab = 'events'">Feed events</button>
        <button :class="{ active: tab === 'obs' }" data-testid="tab-obs" @click="tab = 'obs'">Observations</button>
      </span>
      <span class="sub">{{ tab === 'events' ? 'feed_events' : 'observations · ' + state.symbol }}</span>
    </div>
    <div class="panel-body">
      <template v-if="tab === 'events'">
        <div v-for="(e, i) in state.events" :key="i" class="ev" data-testid="event">
          <span class="muted">{{ fmtTimeET(e.time_ms) }}</span>
          <b :class="cls(e.state)">{{ e.state.toUpperCase() }}</b>
          <span class="muted">{{ e.detail }}</span>
        </div>
      </template>
      <table v-else data-testid="observations">
        <thead><tr><th>ID</th><th>KIND</th><th>SRC TIME</th><th>RECV</th><th>PRICE</th><th>VOL Δ</th><th>ARRIVAL</th></tr></thead>
        <tbody>
          <tr v-for="o in state.observations" :key="o.id">
            <td class="muted">#{{ o.id }}</td>
            <td>{{ o.kind }}{{ o.interval ? ' ' + o.interval : '' }}</td>
            <td>{{ fmtTimeET(o.source_time_ms) }}</td>
            <td class="muted">{{ fmtTimeET(o.received_time_ms) }}</td>
            <td>{{ fmtPrice(o.price) }}</td>
            <td>{{ fmtVol(o.volume_delta) }}</td>
            <td :class="o.arrival === 'out_of_order' ? 'down' : o.arrival === 'history' ? 'muted' : 'up'">{{ o.arrival }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.tabs { display: flex; gap: 4px; }
.tabs button { padding: 2px 6px; font-size: 10px; }
.ev { display: grid; grid-template-columns: 62px 96px 1fr; gap: 6px; padding: 2px 0; border-bottom: 1px dashed #241d36; font-size: 11px; }
.ev span:last-child { word-break: break-word; }
</style>
