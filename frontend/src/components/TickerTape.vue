<script setup>
import { computed } from 'vue'
import { state, selectSymbol } from '../store.js'
import { fmtPrice } from '../format.js'

// Two copies so the CSS marquee loops seamlessly.
const items = computed(() => state.symbols.map((s) => ({ s, t: state.ticks[s] })))
</script>

<template>
  <div class="tape" data-testid="ticker-tape">
    <div class="track">
      <template v-for="copy in 2" :key="copy">
        <span v-for="it in items" :key="copy + it.s" class="item" @click="selectSymbol(it.s)">
          <b>{{ it.s }}</b>
          <span :key="it.t?.flash" :class="[it.t?.dir === 'down' ? 'down' : 'up',
                 it.t?.dir === 'down' ? 'flash-down' : it.t?.dir === 'up' ? 'flash-up' : '']">
            {{ it.t ? fmtPrice(it.t.price) : '—' }}
          </span>
          <span v-if="it.t?.change_percent != null" :class="it.t.change_percent >= 0 ? 'up' : 'down'">
            {{ it.t.change_percent >= 0 ? '▲' : '▼' }}{{ Math.abs(it.t.change_percent).toFixed(2) }}%
          </span>
          <span class="sep">│</span>
        </span>
      </template>
    </div>
  </div>
</template>

<style scoped>
.tape { overflow: hidden; white-space: nowrap; background: #0e0b16; border-bottom: 1px solid var(--line); padding: 4px 0; }
.track { display: inline-block; animation: scroll 40s linear infinite; }
.tape:hover .track { animation-play-state: paused; }
.item { margin: 0 10px; cursor: pointer; }
.item b { color: var(--accent); margin-right: 6px; }
.item span { margin-right: 6px; padding: 0 2px; }
.sep { color: var(--line); margin-left: 8px; }
@keyframes scroll { from { transform: translateX(0); } to { transform: translateX(-50%); } }
</style>
