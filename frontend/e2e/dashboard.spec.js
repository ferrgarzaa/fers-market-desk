import { expect, test } from '@playwright/test'

test('dashboard streams, shows source/age/status, survives an outage, and replays', async ({ page }) => {
  await page.goto('/')

  // live path: feed badge, chart canvas, watchlist prices, data age
  await expect(page.getByTestId('feed-badge')).toContainText('FEED LIVE')
  await expect(page.getByTestId('chart').locator('canvas').first()).toBeVisible()
  await expect(page.getByTestId('watchlist')).toContainText('BTC-USD')
  await expect(page.getByTestId('data-age')).not.toHaveText('—')
  await expect(page.getByTestId('candle-state')).toContainText('PROVISIONAL')
  await expect(page.getByTestId('observations')).toContainText('tick')
  await page.screenshot({ path: '../docs/evidence/e2e-live.png' })

  // interval selector re-subscribes
  await page.getByTestId('iv-5m').click()
  await expect(page.getByTestId('iv-5m')).toHaveClass(/active/)

  // unavailable-feed condition is visible
  await page.getByTestId('outage-btn').click()
  await expect(page.getByTestId('chart-banner')).toContainText('FEED UNAVAILABLE')
  await expect(page.getByTestId('feed-state')).toContainText('UNAVAILABLE')
  await expect(page.getByTestId('event').first()).toContainText('UNAVAILABLE')
  await page.screenshot({ path: '../docs/evidence/e2e-outage.png' })
  await page.getByTestId('outage-btn').click()
  await expect(page.getByTestId('feed-state')).toContainText('LIVE')

  // replay of stored revisions
  await page.getByTestId('replay-btn').click()
  await expect(page.getByTestId('chart-banner')).toContainText('REPLAY')
  await page.screenshot({ path: '../docs/evidence/e2e-replay.png' })
  await page.getByTestId('live-btn').click()
  await expect(page.getByTestId('chart-banner')).toHaveCount(0)
})
