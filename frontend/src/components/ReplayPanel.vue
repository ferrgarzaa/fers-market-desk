<script setup>
import { ref } from 'vue'
import { startReplay, state, stopReplay } from '../store.js'

const speed = ref(40)
</script>

<template>
  <section class="panel">
    <div class="panel-head">Replay <span class="sub">recorded revisions</span></div>
    <div class="panel-body">
      <p class="muted">Re-plays every stored revision of <b class="accent">{{ state.symbol }} {{ state.interval }}</b>
        in the order it was recorded — works when the market is closed.</p>
      <label class="muted">Speed: <b class="accent">{{ speed }}</b> rev/s</label>
      <input type="range" min="5" max="200" step="5" v-model.number="speed" />
      <div class="row">
        <button class="active" :disabled="state.replay.active" data-testid="replay-btn" @click="startReplay(speed)">▶ Replay</button>
        <button :disabled="!state.replay.active" data-testid="live-btn" @click="stopReplay()">● Back to live</button>
      </div>
      <div v-if="state.replay.active" class="prog">
        <div class="bar" :style="{ width: (state.replay.count ? 100 * state.replay.index / state.replay.count : 0) + '%' }"></div>
      </div>
    </div>
  </section>
</template>

<style scoped>
p { margin: 0 0 8px; line-height: 1.4; }
input[type=range] { width: 100%; accent-color: var(--down); }
.row { display: flex; gap: 6px; margin-top: 6px; }
.row button { flex: 1; }
.prog { height: 4px; background: var(--line); margin-top: 8px; }
.bar { height: 100%; background: linear-gradient(90deg, var(--accent), var(--down)); }
</style>
