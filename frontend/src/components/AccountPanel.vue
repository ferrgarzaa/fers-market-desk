<script setup>
import { computed } from 'vue'
import { resetAccount, selectSymbol, state } from '../store.js'
import { fmtMoney, fmtPct, fmtPrice, fmtQty, pnlClass } from '../format.js'

const a = computed(() => state.status?.account)
</script>

<template>
  <section class="panel">
    <div class="panel-head">Sim account <span class="sub">SIMULATED · no real orders</span></div>
    <div class="panel-body" data-testid="account">
      <div class="equity">
        <span class="muted">EQUITY</span>
        <b>{{ fmtMoney(a?.equity) }}</b>
        <span :class="pnlClass(a?.return_pct)">{{ fmtPct(a?.return_pct, 3) }}</span>
      </div>
      <dl class="kv">
        <dt>Cash</dt><dd>{{ fmtMoney(a?.cash) }}</dd>
        <dt>Realized P/L</dt><dd :class="pnlClass(a?.realized_pnl)">{{ fmtMoney(a?.realized_pnl, true) }}</dd>
        <dt>Unrealized P/L</dt><dd :class="pnlClass(a?.unrealized_pnl)">{{ fmtMoney(a?.unrealized_pnl, true) }}</dd>
        <dt>Fees paid</dt><dd class="warn">{{ fmtMoney(a?.fees) }}</dd>
        <dt>Fills</dt><dd>{{ a?.fills ?? 0 }}</dd>
      </dl>
      <div class="sub-h">POSITIONS</div>
      <table data-testid="positions">
        <thead><tr><th>SYM</th><th>QTY</th><th>AVG</th><th>MARK</th><th>U-P/L</th></tr></thead>
        <tbody>
          <tr v-for="p in a?.positions || []" :key="p.symbol" @click="selectSymbol(p.symbol)">
            <td><b>{{ p.symbol }}</b></td><td>{{ fmtQty(p.qty) }}</td><td>{{ fmtPrice(p.avg_cost) }}</td>
            <td>{{ fmtPrice(p.mark) }}</td><td :class="pnlClass(p.unrealized_pnl)">{{ fmtMoney(p.unrealized_pnl, true) }}</td>
          </tr>
          <tr v-if="!a?.positions?.length"><td colspan="5" class="muted">Flat — waiting for a BUY cross</td></tr>
        </tbody>
      </table>
      <p class="muted note">
        Start {{ fmtMoney(a?.starting_cash) }} · BUY = {{ (a?.config.alloc ?? 0.1) * 100 }}% of cash ·
        fill at next candle open ± {{ ((a?.config.slippage ?? 0) * 100).toFixed(2) }}% slippage ·
        {{ ((a?.config.fee_rate ?? 0) * 100).toFixed(2) }}% fee · long-only
      </p>
      <button class="danger" data-testid="reset-account" @click="resetAccount()">Reset sim account</button>
    </div>
  </section>
</template>

<style scoped>
.equity { display: flex; align-items: baseline; gap: 10px; margin-bottom: 6px; }
.equity b { font-size: 18px; }
.sub-h { color: var(--down); font-weight: 700; font-size: 10px; letter-spacing: .08em; margin: 8px 0 2px; }
.note { font-size: 10px; line-height: 1.4; margin: 6px 0; }
tr { cursor: pointer; }
button { width: 100%; }
</style>
