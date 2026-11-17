<script setup>
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { CandlestickSeries, CrosshairMode, HistogramSeries, LineSeries, LineStyle, createChart, createSeriesMarkers } from 'lightweight-charts'
import { onChartMessage, selectInterval, state } from '../store.js'
import { ET, FEED_STATES, ageClass, fmtAge, fmtPrice, fmtTimeET, fmtVol } from '../format.js'

const el = ref(null)
const legend = ref(null)          // candle shown in the legend (hovered or latest)
const latest = ref(null)
const bars = new Map()            // time -> candle (current version)
let chart, candleSeries, volSeries, provLine = null
let fastSeries, slowSeries, markers
const ind = new Map()             // time -> {fast, slow, signal, provisional}
const indMeta = ref({ fast: 9, slow: 21, state: '' })
const FAST_C = '#22d3ee', SLOW_C = '#fbbf24'

function lineData(key) {
  return [...ind.values()].sort((a, b) => a.time - b.time).filter((p) => p[key] != null)
    .map((p) => ({ time: p.time, value: p[key], ...(p.provisional ? { color: 'rgba(233,228,245,.35)' } : {}) }))
}
function renderIndicators() {
  fastSeries.setData(lineData('fast'))
  slowSeries.setData(lineData('slow'))
  const ms = []
  for (const p of [...ind.values()].sort((a, b) => a.time - b.time)) {
    if (!p.signal) continue
    const buy = p.signal === 'BUY'
    if (p.provisional) {
      ms.push({ time: p.time, position: buy ? 'belowBar' : 'aboveBar', shape: 'circle', color: '#a855f7', text: `${p.signal}? (provisional)` })
    } else {
      ms.push({ time: p.time, position: buy ? 'belowBar' : 'aboveBar', shape: buy ? 'arrowUp' : 'arrowDown', color: buy ? UP : DOWN, text: p.signal })
    }
  }
  markers.setMarkers(ms)
}
function setIndicators(i, replace) {
  if (replace) ind.clear()
  if (!i) return
  indMeta.value = { fast: i.fast, slow: i.slow, state: i.state }
  // a newer point means older provisional points are no longer provisional candidates
  for (const p of i.points) ind.set(p.time, p)
  for (const [t, p] of ind) if (p.provisional && i.points.length && t < i.points.at(-1).time) ind.delete(t)
  renderIndicators()
}
let unsubscribe

const UP = '#4ade80', DOWN = '#f472b6'
const UP_FADE = 'rgba(74,222,128,0.18)', DOWN_FADE = 'rgba(244,114,182,0.18)'

function toCandle(c) {
  const up = c.close >= c.open
  const bar = { time: c.time, open: c.open, high: c.high, low: c.low, close: c.close }
  if (!c.is_complete) {
    // Provisional (unfinished) candle: hollow / faded body, so it never looks settled.
    Object.assign(bar, { color: up ? UP_FADE : DOWN_FADE, borderColor: up ? UP : DOWN, wickColor: up ? UP : DOWN })
  }
  return bar
}
function toVol(c) {
  const up = c.close >= c.open
  return { time: c.time, value: c.volume, color: c.is_complete ? (up ? 'rgba(74,222,128,.55)' : 'rgba(244,114,182,.55)') : 'rgba(168,85,247,.55)' }
}

function refreshProvisionalLine() {
  if (provLine) { candleSeries.removePriceLine(provLine); provLine = null }
  const c = latest.value
  if (c && !c.is_complete) {
    provLine = candleSeries.createPriceLine({
      price: c.close, color: '#a855f7', lineWidth: 1, lineStyle: LineStyle.Dashed,
      axisLabelVisible: true, title: 'PROVISIONAL',
    })
  }
}

function setAll(list) {
  bars.clear()
  list.forEach((c) => bars.set(c.time, c))
  const sorted = [...bars.values()].sort((a, b) => a.time - b.time)
  candleSeries.setData(sorted.map(toCandle))
  volSeries.setData(sorted.map(toVol))
  latest.value = sorted.at(-1) || null
  legend.value = latest.value
  refreshProvisionalLine()
}

function apply(c) {
  const last = latest.value
  bars.set(c.time, c)
  const historical = last && c.time < last.time
  try {
    candleSeries.update(toCandle(c), historical)
    volSeries.update(toVol(c), historical)
  } catch {
    // e.g. a late candle for a bucket the chart never had: rebuild from the map
    const sorted = [...bars.values()].sort((a, b) => a.time - b.time)
    candleSeries.setData(sorted.map(toCandle))
    volSeries.setData(sorted.map(toVol))
  }
  if (!last || c.time >= last.time) latest.value = c
  if (!hovering) legend.value = latest.value
  refreshProvisionalLine()
}

let hovering = false

function onMessage(m) {
  if (m.type === 'snapshot') {
    if (m.symbol !== state.symbol || m.interval !== state.interval) return
    setAll(m.candles)
    setIndicators(m.indicators, true)
    chart.timeScale().fitContent()
    const n = m.candles.length
    if (n > 150) chart.timeScale().setVisibleLogicalRange({ from: n - 150, to: n + 5 })
  } else if (m.type === 'candle') {
    if (m.candle.symbol === state.symbol && m.candle.interval === state.interval) apply(m.candle)
  } else if (m.type === 'indicators_tail') {
    if (m.symbol === state.symbol && m.interval === state.interval && !state.replay.active) setIndicators(m.indicators, false)
  } else if (m.type === 'replay_start') {
    setAll([])
    setIndicators(null, true)
  } else if (m.type === 'replay_candle') {
    const r = m.candle
    apply({ ...r, symbol: state.symbol, interval: state.interval, source: `replay · ${r.reason}` })
    if (m.index % 25 === 0) chart.timeScale().scrollToRealTime()
  } else if (m.type === 'replay_done') {
    chart.timeScale().fitContent()
  }
}

const tickFmt = (t) => new Date(t * 1000).toLocaleTimeString('en-US', { timeZone: ET, hour12: false, hour: '2-digit', minute: '2-digit' })

onMounted(() => {
  chart = createChart(el.value, {
    autoSize: true,
    layout: {
      background: { color: '#13101c' }, textColor: '#e9e4f5',
      fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
      panes: { separatorColor: '#2d2540', separatorHoverColor: '#a855f7' },
    },
    grid: { vertLines: { color: '#1f1a2e' }, horzLines: { color: '#1f1a2e' } },
    crosshair: { mode: CrosshairMode.Normal, vertLine: { color: '#a855f7' }, horzLine: { color: '#a855f7' } },
    rightPriceScale: { borderColor: '#2d2540' },
    timeScale: { borderColor: '#2d2540', timeVisible: true, secondsVisible: false, tickMarkFormatter: tickFmt },
    localization: { timeFormatter: (t) => new Date(t * 1000).toLocaleString('en-US', { timeZone: ET, hour12: false, month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' }) + ' ET' },
  })
  candleSeries = chart.addSeries(CandlestickSeries, {
    upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN,
  })
  fastSeries = chart.addSeries(LineSeries, { color: FAST_C, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false, title: 'SMA9' })
  slowSeries = chart.addSeries(LineSeries, { color: SLOW_C, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false, title: 'SMA21' })
  markers = createSeriesMarkers(candleSeries, [])
  volSeries = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false }, 1)
  chart.panes()[1]?.setHeight(110)

  chart.subscribeCrosshairMove((p) => {
    if (p.time && bars.has(p.time)) { hovering = true; legend.value = bars.get(p.time) }
    else { hovering = false; legend.value = latest.value }
  })
  unsubscribe = onChartMessage(onMessage)
})
onBeforeUnmount(() => { unsubscribe?.(); chart?.remove() })

const legendInd = computed(() => legend.value ? ind.get(legend.value.time) : null)
const strat = computed(() => state.status?.strategy?.[state.symbol])
const tick = computed(() => state.ticks[state.symbol])
const feed = computed(() => state.status?.feed)
const sourceAge = computed(() => tick.value ? state.now - tick.value.source_time_ms : null)
const banner = computed(() => {
  if (!state.connected) return { cls: 'bad', text: 'BACKEND OFFLINE — browser cannot reach the FastAPI server; chart is frozen' }
  if (state.replay.active) return { cls: 'replay', text: `REPLAY — recorded observations from SQLite, not live (${state.replay.index}/${state.replay.count})${state.replay.done ? ' · COMPLETE' : ''}` }
  const s = feed.value?.state
  if (s === 'unavailable') return { cls: 'bad', text: `FEED UNAVAILABLE — showing stored data only · ${feed.value.detail}` }
  if (s === 'stale') return { cls: 'stale', text: `FEED STALE — ${feed.value.detail}` }
  if (s === 'connecting' || s === 'connected' || s === 'starting') return { cls: 'wait', text: `FEED ${FEED_STATES[s].label} — waiting for first message…` }
  return null
})
</script>

<template>
  <section class="panel chart-panel">
    <div class="panel-head">
      <span>{{ state.symbol }} <span class="sub">· candles + volume · times in ET</span></span>
      <span class="ivs">
        <button v-for="iv in state.intervals" :key="iv" :class="{ active: iv === state.interval }"
                :data-testid="`iv-${iv}`" @click="selectInterval(iv)">{{ iv }}</button>
      </span>
    </div>
    <div class="legend" v-if="legend" data-testid="legend">
      <span class="muted">{{ fmtTimeET(legend.time * 1000, false) }}</span>
      <span>O <b>{{ fmtPrice(legend.open) }}</b></span>
      <span>H <b>{{ fmtPrice(legend.high) }}</b></span>
      <span>L <b>{{ fmtPrice(legend.low) }}</b></span>
      <span>C <b :class="legend.close >= legend.open ? 'up' : 'down'">{{ fmtPrice(legend.close) }}</b></span>
      <span>V <b>{{ fmtVol(legend.volume) }}</b></span>
      <span class="pill" :class="legend.is_complete ? 'up' : 'accent'" data-testid="candle-state">
        {{ legend.is_complete ? '✓ COMPLETE' : '◌ PROVISIONAL' }}
      </span>
      <span class="muted">rev {{ legend.revision }} · {{ legend.source }}</span>
    </div>
    <div class="legend ind" data-testid="sma-legend">
      <span :style="{ color: '#22d3ee' }">SMA{{ indMeta.fast }} <b>{{ fmtPrice(legendInd?.fast) }}</b></span>
      <span :style="{ color: '#fbbf24' }">SMA{{ indMeta.slow }} <b>{{ fmtPrice(legendInd?.slow) }}</b></span>
      <span v-if="legendInd?.fast != null && legendInd?.slow != null"
            :class="legendInd.fast > legendInd.slow ? 'up' : 'down'">
        {{ legendInd.fast > legendInd.slow ? '▲ fast above slow (bullish)' : '▼ fast below slow (bearish)' }}
      </span>
      <span v-if="legendInd?.provisional" class="pill accent">uses PROVISIONAL candle — not traded</span>
      <span v-if="legendInd?.signal && !legendInd.provisional" class="pill" :class="legendInd.signal === 'BUY' ? 'up' : 'down'">
        CONFIRMED {{ legendInd.signal }} (completed candle)</span>
      <span v-if="legendInd?.signal && legendInd.provisional" class="pill accent" data-testid="prov-signal">
        PROVISIONAL {{ legendInd.signal }}? — may disappear before the candle closes</span>
    </div>
    <div class="age-strip">
      <span>SOURCE <b class="accent">{{ feed?.source || '—' }}</b></span>
      <span>DATA AGE <b :class="ageClass(sourceAge)" data-testid="data-age">{{ fmtAge(sourceAge) }}</b>
        <span class="muted">(now − source timestamp)</span></span>
      <span v-if="tick">LAST <b :key="tick.flash" :class="[tick.dir === 'down' ? 'down flash-down' : 'up flash-up']">{{ fmtPrice(tick.price) }}</b></span>
    </div>
    <div v-if="banner" class="banner" :class="banner.cls" data-testid="chart-banner">{{ banner.text }}</div>
    <div ref="el" class="chart" data-testid="chart"></div>
  </section>
</template>

<style scoped>
.chart-panel { position: relative; }
.chart { flex: 1; min-height: 0; }
.ivs { display: flex; gap: 4px; }
.legend, .age-strip { display: flex; flex-wrap: wrap; gap: 12px; padding: 4px 8px; align-items: center; border-bottom: 1px solid var(--line); }
.age-strip { font-size: 11px; color: var(--muted); }
.legend.ind { font-size: 11px; }
.age-strip b { color: var(--text); }
.banner { padding: 5px 8px; font-weight: 700; letter-spacing: .04em; font-size: 11px; }
.banner.bad { background: rgba(244,114,182,.18); color: var(--down); border-bottom: 1px solid var(--down); }
.banner.stale { background: rgba(251,191,36,.12); color: var(--warn); border-bottom: 1px solid var(--warn); }
.banner.replay, .banner.wait { background: rgba(168,85,247,.18); color: #d8b4fe; border-bottom: 1px solid var(--accent); }
</style>
