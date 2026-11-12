export const ET = 'America/New_York'

export function fmtPrice(p) {
  if (p == null || Number.isNaN(p)) return '—'
  const d = p >= 1000 ? 2 : p >= 1 ? 2 : 6
  return p.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
}

export function fmtVol(v) {
  if (v == null) return '—'
  if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B'
  if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M'
  if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K'
  return v.toFixed(v % 1 ? 2 : 0)
}

export function fmtAge(ms) {
  if (ms == null) return '—'
  if (ms < 0) ms = 0
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  if (ms < 3600000) return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
  if (ms < 86400000) return `${Math.floor(ms / 3600000)}h ${Math.floor((ms % 3600000) / 60000)}m`
  return `${Math.floor(ms / 86400000)}d ${Math.floor((ms % 86400000) / 3600000)}h`
}

export function ageClass(ms) {
  if (ms == null) return 'muted'
  if (ms < 10000) return 'up'
  if (ms < 60000) return 'warn'
  return 'down'
}

export function fmtTimeET(ms, withSeconds = true) {
  if (ms == null) return '—'
  return new Date(ms).toLocaleTimeString('en-US', {
    timeZone: ET, hour12: false, hour: '2-digit', minute: '2-digit', ...(withSeconds ? { second: '2-digit' } : {}),
  })
}

export function fmtDateTimeET(ms) {
  if (ms == null) return '—'
  return new Date(ms).toLocaleString('en-US', {
    timeZone: ET, hour12: false, month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

export const isCrypto = (s) => s.endsWith('-USD')

// NYSE regular session Mon–Fri 09:30–16:00 ET. Exchange holidays are NOT modelled.
export function nyseSession(ms) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: ET, weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(new Date(ms)).map((p) => [p.type, p.value]))
  const mins = (parseInt(parts.hour, 10) % 24) * 60 + parseInt(parts.minute, 10)
  if (parts.weekday === 'Sat' || parts.weekday === 'Sun') return { label: 'NYSE CLOSED · WEEKEND', cls: 'down' }
  if (mins >= 570 && mins < 960) return { label: 'NYSE OPEN', cls: 'up' }
  if (mins >= 240 && mins < 570) return { label: 'NYSE PRE-MARKET', cls: 'warn' }
  if (mins >= 960 && mins < 1200) return { label: 'NYSE AFTER-HOURS', cls: 'warn' }
  return { label: 'NYSE CLOSED', cls: 'down' }
}

export const FEED_STATES = {
  live: { dot: 'live', cls: 'up', label: 'LIVE' },
  connected: { dot: 'wait', cls: 'accent', label: 'CONNECTED' },
  connecting: { dot: 'wait', cls: 'accent', label: 'CONNECTING' },
  starting: { dot: 'wait', cls: 'accent', label: 'STARTING' },
  stale: { dot: 'stale', cls: 'warn', label: 'STALE' },
  unavailable: { dot: 'bad', cls: 'down', label: 'UNAVAILABLE' },
}
