// Shared reactive state + the single browser<->backend WebSocket.
import { reactive } from 'vue'

export const state = reactive({
  connected: false,          // browser <-> backend WebSocket
  symbol: 'BTC-USD',
  interval: '1m',
  symbols: [],
  intervals: ['1m', '5m', '15m'],
  status: null,              // latest server status message
  ticks: {},                 // symbol -> { price, source_time_ms, received_ms, dir, flash, ... }
  events: [],                // feed events (newest first)
  observations: [],          // recent stored observations for the selected symbol
  replay: { active: false, index: 0, count: 0, done: false },
  now: Date.now(),
})

const chartListeners = new Set()
export function onChartMessage(fn) {
  chartListeners.add(fn)
  return () => chartListeners.delete(fn)
}

let ws = null
let retry = 0

export function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg))
}

export function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${location.host}/ws`)
  ws.onopen = () => {
    state.connected = true
    retry = 0
    send({ action: 'subscribe', symbol: state.symbol, interval: state.interval })
  }
  ws.onclose = () => {
    state.connected = false
    setTimeout(connect, Math.min(1000 * 2 ** retry++, 10000))
  }
  ws.onmessage = (e) => handle(JSON.parse(e.data))
}

function updateTick(t) {
  const prev = state.ticks[t.symbol]
  let dir = prev?.dir || 'flat'
  if (prev && t.price > prev.price) dir = 'up'
  else if (prev && t.price < prev.price) dir = 'down'
  const changed = !prev || prev.price !== t.price
  state.ticks[t.symbol] = { ...t, dir, flash: (prev?.flash || 0) + (changed ? 1 : 0) }
}

function handle(m) {
  switch (m.type) {
    case 'status':
      state.status = m.status
      state.symbols = m.status.symbols
      state.intervals = m.status.intervals
      for (const [sym, t] of Object.entries(m.status.last_tick || {})) {
        if (!state.ticks[sym]) updateTick(t)
      }
      break
    case 'tick':
      updateTick(m.tick)
      break
    case 'feed_event':
      state.events.unshift(m.event)
      state.events.splice(60)
      break
    case 'events':
      state.events = m.events
      break
    case 'observations':
      state.observations = m.rows
      break
    case 'replay_start':
      state.replay = { active: true, index: 0, count: m.count, done: false }
      break
    case 'replay_candle':
      state.replay.index = m.index + 1
      break
    case 'replay_done':
      state.replay.done = true
      break
    case 'snapshot':
      state.replay = { active: false, index: 0, count: 0, done: false }
      break
  }
  if (['snapshot', 'candle', 'replay_start', 'replay_candle', 'replay_done'].includes(m.type)) {
    chartListeners.forEach((fn) => fn(m))
  }
}

export function selectSymbol(symbol) {
  state.symbol = symbol
  send({ action: 'subscribe', symbol, interval: state.interval })
}
export function selectInterval(interval) {
  state.interval = interval
  send({ action: 'subscribe', symbol: state.symbol, interval })
}
export function startReplay(speed = 40) { send({ action: 'replay', speed }) }
export function stopReplay() { send({ action: 'stop_replay' }) }

export async function setOutage(enabled) {
  await fetch('/api/feed/outage', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  })
}

setInterval(() => { state.now = Date.now() }, 250)
setInterval(() => send({ action: 'observations' }), 2000)
