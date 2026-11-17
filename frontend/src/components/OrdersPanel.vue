<script setup>
import { computed } from 'vue'
import { state } from '../store.js'
import { fmtBarET, fmtMoney, fmtPrice, fmtQty, pnlClass } from '../format.js'

const orders = computed(() => state.status?.account?.orders || [])
</script>

<template>
  <section class="panel">
    <div class="panel-head">Orders &amp; fills · live bot <span class="sub">newest first · sim_orders + sim_fills</span></div>
    <div class="panel-body">
      <table data-testid="orders">
        <thead><tr><th>SIGNAL BAR</th><th>SYM</th><th>SIDE</th><th>STATUS</th><th>FILL BAR</th><th>QTY</th><th>FILL PX</th><th>FEE</th><th>REAL. P/L</th></tr></thead>
        <tbody>
          <tr v-for="o in orders" :key="o.id" :title="o.note || o.reason">
            <td class="muted">{{ fmtBarET(o.signal_bar) }}</td>
            <td><b>{{ o.symbol }}</b></td>
            <td :class="o.side === 'BUY' ? 'up' : 'down'"><b>{{ o.side }}</b></td>
            <td :class="o.status === 'filled' ? 'up' : o.status === 'pending' ? 'accent' : 'warn'">
              {{ o.status }}<div v-if="o.status === 'skipped'" class="note">{{ o.note }}</div></td>
            <td class="muted">{{ o.fill_bar ? fmtBarET(o.fill_bar) : '—' }}</td>
            <td>{{ fmtQty(o.fill_qty) }}</td>
            <td>{{ fmtPrice(o.fill_price) }}</td>
            <td>{{ o.fee != null ? fmtMoney(o.fee) : '—' }}</td>
            <td :class="pnlClass(o.realized_pnl)">{{ o.side === 'SELL' && o.realized_pnl != null ? fmtMoney(o.realized_pnl, true) : '—' }}</td>
          </tr>
          <tr v-if="!orders.length"><td colspan="9" class="muted">
            No signals yet. The bot acts only when SMA{{ state.status?.strategy?.[state.symbol]?.fast ?? 9 }}
            crosses SMA{{ state.status?.strategy?.[state.symbol]?.slow ?? 21 }} on a completed 1m candle.</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
table { font-size: 11px; }
.note { color: var(--muted); font-size: 10px; white-space: normal; max-width: 160px; }
</style>
