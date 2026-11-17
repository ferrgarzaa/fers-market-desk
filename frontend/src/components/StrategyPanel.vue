<script setup>
import { computed } from 'vue'
import { state } from '../store.js'
import { fmtBarET, fmtPrice } from '../format.js'

const s = computed(() => state.status?.strategy?.[state.symbol])
const diff = computed(() => (s.value?.sma_fast != null && s.value?.sma_slow != null) ? s.value.sma_fast - s.value.sma_slow : null)
</script>

<template>
  <section class="panel">
    <div class="panel-head">Strategy · SMA {{ s?.fast ?? 9 }}/{{ s?.slow ?? 21 }} cross
      <span class="sub">bot trades {{ s?.interval ?? '1m' }} · completed candles only</span></div>
    <div class="panel-body" data-testid="strategy">
      <div class="state">
        <b :class="s?.state === 'bullish' ? 'up' : s?.state === 'bearish' ? 'down' : 'muted'">
          {{ (s?.state || 'warming up').toUpperCase() }}</b>
        <span class="muted"> · {{ state.symbol }} · {{ s?.bars_seen ?? 0 }} completed bars seen</span>
      </div>
      <dl class="kv">
        <dt style="color:#22d3ee">SMA{{ s?.fast }} (fast)</dt><dd>{{ fmtPrice(s?.sma_fast) }}</dd>
        <dt style="color:#fbbf24">SMA{{ s?.slow }} (slow)</dt><dd>{{ fmtPrice(s?.sma_slow) }}</dd>
        <dt>fast − slow</dt><dd :class="diff > 0 ? 'up' : diff < 0 ? 'down' : ''">{{ diff == null ? '—' : diff.toFixed(4) }}</dd>
        <dt>Last confirmed signal</dt>
        <dd>
          <template v-if="s?.last_signal">
            <b :class="s.last_signal.signal === 'BUY' ? 'up' : 'down'">{{ s.last_signal.signal }}</b>
            {{ fmtBarET(s.last_signal.time) }} · {{ s.last_signal.order_status }}
          </template>
          <span v-else class="muted">none since start</span>
        </dd>
      </dl>
      <div v-if="s?.provisional?.signal" class="prov" data-testid="strategy-provisional">
        ◌ PROVISIONAL {{ s.provisional.signal }}: the forming candle would cross if it closed now.
        Not traded until the candle completes.
      </div>
      <div v-else class="muted small">No provisional cross on the forming candle.</div>
    </div>
  </section>
</template>

<style scoped>
.state { font-size: 15px; margin-bottom: 6px; }
.prov { margin-top: 8px; padding: 5px 6px; border: 1px dashed var(--accent); color: #d8b4fe; font-size: 11px; }
.small { margin-top: 8px; font-size: 11px; }
</style>
