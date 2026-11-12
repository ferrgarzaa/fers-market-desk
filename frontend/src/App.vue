<script setup>
import TopBar from './components/TopBar.vue'
import TickerTape from './components/TickerTape.vue'
import Watchlist from './components/Watchlist.vue'
import ChartPanel from './components/ChartPanel.vue'
import FeedPanel from './components/FeedPanel.vue'
import IntegrityPanel from './components/IntegrityPanel.vue'
import ObservationsPanel from './components/ObservationsPanel.vue'
import EventLog from './components/EventLog.vue'
import ReplayPanel from './components/ReplayPanel.vue'
</script>

<template>
  <div class="app">
    <TopBar />
    <TickerTape />
    <main class="grid">
      <div class="col left">
        <Watchlist class="grow" />
        <ReplayPanel />
      </div>
      <div class="col center">
        <ChartPanel class="grow3" />
        <ObservationsPanel class="grow" />
      </div>
      <div class="col right">
        <FeedPanel />
        <IntegrityPanel />
        <EventLog class="grow" />
      </div>
    </main>
    <footer class="foot">
      <span>SIMULATED WORKSTATION · no real orders · Part 4.1 market data &amp; dashboard</span>
      <span class="muted">Vue 3 · Lightweight Charts · FastAPI · SQLite · Yahoo Finance via yfinance</span>
    </footer>
  </div>
</template>

<style scoped>
.app { height: 100%; display: flex; flex-direction: column; }
.grid { flex: 1; min-height: 0; display: grid; grid-template-columns: 300px 1fr 330px; gap: 4px; padding: 4px; }
.col { display: flex; flex-direction: column; gap: 4px; min-height: 0; min-width: 0; }
.grow { flex: 1; }
.grow3 { flex: 3; min-height: 340px; }
.foot { display: flex; justify-content: space-between; padding: 3px 10px; font-size: 10px; color: var(--accent); border-top: 1px solid var(--line); background: #0e0b16; }
@media (max-width: 1100px) {
  .grid { grid-template-columns: 1fr; overflow: auto; }
  .grow3 { min-height: 420px; }
}
</style>
