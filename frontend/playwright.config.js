// Browser tests run the real backend in FEED_MODE=fake (deterministic, no network)
// plus the Vite dev server. The live Yahoo path is verified manually / in the video.
import { defineConfig } from '@playwright/test'

const py = process.env.PYTHON || 'python3'

export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    viewport: { width: 1600, height: 900 },
    channel: process.env.PW_CHANNEL || undefined,
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: `${py} -m uvicorn app.main:app --port 8000`,
      cwd: '../backend',
      url: 'http://127.0.0.1:8000/api/health',
      env: { FEED_MODE: 'fake', DB_PATH: '/tmp/fers-e2e.db', FINALIZE_GRACE_S: '1' },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'npx vite --port 5173 --strictPort --host 127.0.0.1',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
