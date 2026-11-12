import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { connect } from './store.js'

connect()
createApp(App).mount('#app')
