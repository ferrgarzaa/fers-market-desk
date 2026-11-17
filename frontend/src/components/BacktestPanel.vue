<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { LineSeries, createChart } from 'lightweight-charts'
import { runBacktest, state } from '../store.js'
import { ET, fmtBarET, fmtMoney, fmtPct, fmtPrice, fmtQty, pnlClass } from '../format.js'

const fast = ref(9)
const slow = ref(21)
const el = ref(null)
let chart = null, eq = null, bh = null
const r = computed(() => state.backtest)
const m = computed(() => r.value?.metrics)

async function draw() {
  await nextTick()
  if (!r.value || !el.value) return
  if (!chart) {
    chart = createChart(el.value, {
      autoSize: true,
      layout: { background: { color: '#13101c' }, textColor: '#9a8fb5', fontFamily: "'JetBrains Mono', monospace", fontSize: 10 },
      grid: { vertLines: { visible: false }, horzLines: { color: '#1f1a2e' } },
      rightPriceScale: { borderColor: '#2d2540' },
      timeScale: { borderColor: '#2d2540', timeVisible: true, tickMarkFormatter: (t) => new Date(t * 1000).toLocaleTimeString('en-US', { timeZone: ET, hour12: false, hour: '2-digit', minute: '2-digit' }) },
      handleScroll: false, handleScale: false,
    })
    eq = chart.addSeries(LineSeries, { color: '#a855f7', lineWidth: 2, title: 'strategy', priceLineVisible: false })
    bh = chart.addSeries(LineSeries, { color: '#9a8fb5', lineWidth: 1, lineStyle: 2, title: 'buy&hold', priceLineVisible: false })
  }
  eq.setData(r.value.equity.map((p) => ({ time: p.time, value: p.equity })))
  bh.setData(r.value.equity.map((p) => ({ time: p.time, value: p.benchmark })))
  chart.timeScale().fitContent()
}
watch(r, draw)
onBeforeUnmount(() => chart?.remove())

const verdict = computed(() => {
  if (!m.value) return ''
  const diff = m.value.total_return_pct - m.value.benchmark_return_pct
  return `${diff >= 0 ? 'Beat' : 'Trailed'} buy-and-hold (same 10% sizing) by ${Math.abs(diff).toFixed(3)} pts over ${m.value.bars} completed candles.`
})
</script>

<template>
  <section class="panel">
    <div class="panel-head">Backtest · {{ state.symbol }} {{ state.interval }}
      <span class="sub">event-driven · completed candles from SQLite</span></div>
    <div class="panel-body">
      <div class="controls">
        <label>fast <input type="number" min="1" max="200" v-model.number="fast" /></label>
        <label>slow <input type="number" min="2" max="400" v-model.number="slow" /></label>
        <button class="active" :disabled="state.backtestBusy" data-testid="run-backtest" @click="runBacktest(fast, slow)">
          {{ state.backtestBusy ? 'Running…' : '▶ Run backtest' }}</button>
      </div>
      <div v-if="state.backtestError" class="down">{{ state.backtestError }}</div>
      <template v-if="r">
        <div class="metrics" data-testid="bt-metrics">
          <div><span>Return</span><b :class="pnlClass(m.total_return_pct)">{{ fmtPct(m.total_return_pct, 3) }}</b></div>
          <div><span>Buy &amp; hold</span><b :class="pnlClass(m.benchmark_return_pct)">{{ fmtPct(m.benchmark_return_pct, 3) }}</b></div>
          <div><span>Price chg</span><b :class="pnlClass(m.price_change_pct)">{{ fmtPct(m.price_change_pct) }}</b></div>
          <div><span>Max DD</span><b class="down">{{ m.max_drawdown_pct.toFixed(3) }}%</b></div>
          <div><span>Trades</span><b>{{ m.round_trips }} <small class="muted">({{ m.wins }}W)</small></b></div>
          <div><span>Win rate</span><b>{{ m.win_rate_pct == null ? '—' : m.win_rate_pct.toFixed(0) + '%' }}</b></div>
          <div><span>Fees</span><b class="warn">{{ fmtMoney(m.fees) }}</b></div>
          <div><span>Final equity</span><b>{{ fmtMoney(m.final_equity) }}</b></div>
        </div>
        <div class="period muted">
          {{ r.symbol }} {{ r.interval }} · SMA {{ r.fast }}/{{ r.slow }} · {{ fmtBarET(m.first_bar) }} → {{ fmtBarET(m.last_bar) }} ET ·
          {{ m.bars }} bars ({{ m.warmup_bars }} warm-up) · exposure {{ m.exposure_pct.toFixed(0) }}% ·
          {{ r.excluded_provisional }} provisional candle(s) excluded · run #{{ r.run_id }}
        </div>
        <div class="verdict">{{ verdict }}
          <span class="muted">In-sample, one instrument, one short window: it does not establish future performance.</span></div>
      </template>
      <div ref="el" class="eqchart" v-show="r" data-testid="bt-equity"></div>
      <table v-if="r" data-testid="bt-trades">
        <thead><tr><th>FILL BAR</th><th>SIDE</th><th>QTY</th><th>OPEN</th><th>FILL PX</th><th>FEE</th><th>P/L</th></tr></thead>
        <tbody>
          <tr v-for="(t, i) in [...r.trades].reverse()" :key="i">
            <td class="muted">{{ fmtBarET(t.time) }}</td>
            <td :class="t.side === 'BUY' ? 'up' : 'down'"><b>{{ t.side }}</b></td>
            <td>{{ fmtQty(t.qty) }}</td><td>{{ fmtPrice(t.ref_price) }}</td><td>{{ fmtPrice(t.fill_price) }}</td>
            <td>{{ fmtMoney(t.fee) }}</td>
            <td :class="pnlClass(t.realized_pnl)">{{ t.side === 'SELL' ? fmtMoney(t.realized_pnl, true) : '—' }}</td>
          </tr>
          <tr v-if="!r.trades.length"><td colspan="7" class="muted">No crossings in this window.</td></tr>
        </tbody>
      </table>
      <p v-if="!r" class="muted">Runs the SMA crossover over the stored completed {{ state.interval }} candles of
        {{ state.symbol }}. Each decision uses only closes up to that bar and fills at the next bar's open.</p>
    </div>
  </section>
</template>

<style scoped>
.controls { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
.controls label { color: var(--muted); }
input[type=number] { width: 52px; background: var(--bg); color: var(--text); border: 1px solid var(--line); font-family: var(--font); padding: 3px; }
.controls button { margin-left: auto; }
.metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; margin-bottom: 4px; }
.metrics div { background: #241d36; padding: 3px 6px; display: flex; flex-direction: column; }
.metrics span { color: var(--muted); font-size: 10px; }
.metrics b { font-size: 13px; }
.period { font-size: 10px; margin: 2px 0 4px; }
.verdict { font-size: 11px; margin-bottom: 4px; }
.eqchart { height: 110px; margin-bottom: 6px; }
</style>
