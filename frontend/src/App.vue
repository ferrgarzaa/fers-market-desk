<script setup>
import TopBar from './components/TopBar.vue'
import TickerTape from './components/TickerTape.vue'
import Watchlist from './components/Watchlist.vue'
import ChartPanel from './components/ChartPanel.vue'
import FeedPanel from './components/FeedPanel.vue'
import IntegrityPanel from './components/IntegrityPanel.vue'
import LogPanel from './components/LogPanel.vue'
import ReplayPanel from './components/ReplayPanel.vue'
import StrategyPanel from './components/StrategyPanel.vue'
import AccountPanel from './components/AccountPanel.vue'
import OrdersPanel from './components/OrdersPanel.vue'
import BacktestPanel from './components/BacktestPanel.vue'
import Toasts from './components/Toasts.vue'
</script>

<template>
  <div class="app">
    <TopBar />
    <TickerTape />
    <Toasts />
    <main class="grid">
      <div class="col left">
        <Watchlist class="watch" />
        <AccountPanel class="grow" />
        <ReplayPanel class="replay" />
      </div>
      <div class="col center">
        <ChartPanel class="chart" />
        <div class="row">
          <OrdersPanel class="half" />
          <BacktestPanel class="half" />
        </div>
      </div>
      <div class="col right">
        <StrategyPanel />
        <FeedPanel class="feed" />
        <IntegrityPanel class="integ" />
        <LogPanel class="grow" />
      </div>
    </main>
    <footer class="foot">
      <span>SIMULATED WORKSTATION · no real orders · Part 4.2 indicators, simulated trading &amp; backtesting</span>
      <span class="muted">Vue 3 · Lightweight Charts · FastAPI · SQLite · Yahoo Finance via yfinance</span>
    </footer>
  </div>
</template>

<style scoped>
.app { height: 100%; min-height: 860px; display: flex; flex-direction: column; }
.grid { flex: 1; min-height: 0; display: grid; grid-template-columns: 290px 1fr 320px; gap: 4px; padding: 4px; }
.col { display: flex; flex-direction: column; gap: 4px; min-height: 0; min-width: 0; }
.grow { flex: 1; }
.watch { flex: 0 0 auto; max-height: 200px; }
.replay { flex: 0 0 auto; }
.chart { flex: 3; min-height: 360px; }
.row { flex: 2; min-height: 250px; display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
.half { min-height: 0; }
.feed { flex: 0 1 auto; max-height: 300px; }
.integ { flex: 0 1 auto; max-height: 190px; }
.foot { display: flex; justify-content: space-between; padding: 3px 10px; font-size: 10px; color: var(--accent); border-top: 1px solid var(--line); background: #0e0b16; }
@media (max-width: 1100px) {
  .grid { grid-template-columns: 1fr; overflow: auto; }
  .row { grid-template-columns: 1fr; }
  .chart { min-height: 420px; }
}
</style>
