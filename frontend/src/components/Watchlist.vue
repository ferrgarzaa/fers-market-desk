<script setup>
import { state, selectSymbol } from '../store.js'
import { ageClass, fmtAge, fmtPrice, isCrypto } from '../format.js'
</script>

<template>
  <section class="panel">
    <div class="panel-head">Watchlist <span class="sub">click to chart</span></div>
    <div class="panel-body">
      <table data-testid="watchlist">
        <thead><tr><th>SYM</th><th>LAST</th><th>CHG%</th><th>AGE</th></tr></thead>
        <tbody>
          <tr v-for="s in state.symbols" :key="s" :class="{ sel: s === state.symbol }" @click="selectSymbol(s)">
            <td><b>{{ s }}</b> <span class="muted tiny">{{ isCrypto(s) ? '24/7' : 'NYSE' }}</span></td>
            <td>
              <span :key="state.ticks[s]?.flash"
                    :class="state.ticks[s]?.dir === 'down' ? 'down flash-down' : state.ticks[s]?.dir === 'up' ? 'up flash-up' : ''">
                {{ fmtPrice(state.ticks[s]?.price) }}
              </span>
            </td>
            <td :class="(state.ticks[s]?.change_percent ?? 0) >= 0 ? 'up' : 'down'">
              {{ state.ticks[s]?.change_percent != null ? state.ticks[s].change_percent.toFixed(2) : '—' }}
            </td>
            <td :class="ageClass(state.ticks[s] ? state.now - state.ticks[s].source_time_ms : null)">
              {{ state.ticks[s] ? fmtAge(state.now - state.ticks[s].source_time_ms) : 'no data' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
tr { cursor: pointer; }
tr:hover td { background: #241d36; }
tr.sel td { background: rgba(168, 85, 247, .18); }
tr.sel td:first-child { box-shadow: inset 3px 0 0 var(--down); }
td { padding: 5px 4px; }
.tiny { font-size: 9px; }
</style>
