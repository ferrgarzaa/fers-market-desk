<script setup>
import { computed } from 'vue'
import { state } from '../store.js'

const db = computed(() => state.status?.db || {})
</script>

<template>
  <section class="panel">
    <div class="panel-head">SQLite integrity <span class="sub">{{ state.status?.db_path?.split(/[\\/]/).pop() }}</span></div>
    <div class="panel-body">
      <dl class="kv" data-testid="integrity">
        <dt>Ticks stored</dt><dd>{{ db.ticks ?? 0 }}</dd>
        <dt>History bars stored</dt><dd>{{ db.bars ?? 0 }}</dd>
        <dt>Candles</dt><dd>{{ db.candles ?? 0 }}</dd>
        <dt>Provisional now</dt><dd class="accent">{{ db.provisional ?? 0 }}</dd>
        <dt>Revisions logged</dt><dd>{{ db.revisions ?? 0 }}</dd>
        <dt>Duplicates rejected</dt><dd class="warn">{{ db.duplicates ?? 0 }}</dd>
        <dt>Out-of-order ticks</dt><dd class="down">{{ db.out_of_order ?? 0 }}</dd>
        <dt>Late revisions</dt><dd>{{ db.late_revisions ?? 0 }}</dd>
        <dt>History vs live kept live</dt><dd>{{ db.history_conflicts_kept_live ?? 0 }}</dd>
      </dl>
    </div>
  </section>
</template>
