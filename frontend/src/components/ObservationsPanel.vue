<script setup>
import { state } from '../store.js'
import { fmtPrice, fmtTimeET, fmtVol } from '../format.js'
</script>

<template>
  <section class="panel">
    <div class="panel-head">Stored observations · {{ state.symbol }} <span class="sub">newest first, from SQLite</span></div>
    <div class="panel-body">
      <table data-testid="observations">
        <thead><tr><th>ID</th><th>KIND</th><th>SOURCE</th><th>SOURCE TIME</th><th>RECEIVED</th><th>PRICE</th><th>VOL Δ</th><th>ARRIVAL</th></tr></thead>
        <tbody>
          <tr v-for="o in state.observations" :key="o.id">
            <td class="muted">#{{ o.id }}</td>
            <td>{{ o.kind }}{{ o.interval ? ' ' + o.interval : '' }}</td>
            <td class="accent">{{ o.source }}</td>
            <td>{{ fmtTimeET(o.source_time_ms) }}</td>
            <td class="muted">{{ fmtTimeET(o.received_time_ms) }}</td>
            <td>{{ fmtPrice(o.price) }}</td>
            <td>{{ fmtVol(o.volume_delta) }}</td>
            <td :class="o.arrival === 'out_of_order' ? 'down' : o.arrival === 'history' ? 'muted' : 'up'">{{ o.arrival }}</td>
          </tr>
          <tr v-if="!state.observations.length"><td colspan="8" class="muted">No observations stored for this symbol yet.</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
