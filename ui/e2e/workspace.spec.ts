import { test, expect } from '@playwright/test'
test.beforeEach(async ({ page }) => {
  await page.route('https://**', async (route) => {
    const url = route.request().url()
    if (url.includes('/styles/'))
      return route.fulfill({
        json: {
          version: 8,
          sources: {},
          layers: [
            { id: 'background', type: 'background', paint: { 'background-color': '#eef2f4' } },
          ],
        },
      })
    return route.abort()
  })
  await page.goto('./')
})
test('real backend retrieval, previews and downloads', async ({ page }) => {
  await expect(page.getByRole('link', { name: 'Source Code', exact: true })).toHaveAttribute(
    'href',
    'https://github.com/Energy-Atlas/openepw',
  )
  await page.getByRole('button', { name: 'Find sources', exact: true }).click()
  await expect(page.getByText('openmeteo · synthetic browser test')).toBeVisible()
  await page.getByRole('button', { name: 'Review plan', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Run reviewed plan', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Run reviewed plan', exact: true }).click()
  await page
    .locator('header')
    .getByRole('button', { name: /Results/ })
    .click()
  await expect(page.getByRole('button', { name: 'Download weather', exact: true })).toBeVisible({
    timeout: 30000,
  })
  await page
    .locator('.artifact-list')
    .getByRole('button', { name: /^weather / })
    .click()
  await expect(page.getByText('Weather preview', { exact: true })).toBeVisible()
  await expect(page.getByText(/Not certified simulation-ready/)).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download weather', exact: true }).click()
  expect((await download).suggestedFilename()).toMatch(/\.epw$/)
  await page.screenshot({ path: 'test-results/results.png' })
})
test('layout settings, future semantics and API docs', async ({ page }) => {
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await page.getByLabel('Appearance', { exact: true }).selectOption('darkEngineering')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Future weather', exact: true }).click()
  await expect(page.getByText(/2036–2065/)).toBeVisible()
  await page.getByRole('combobox', { name: 'Method', exact: true }).selectOption('climate_profile')
  await expect(page.getByText(/2045–2054/)).toBeVisible()
  await page.locator('header').getByRole('button', { name: 'API Docs', exact: true }).click()
  await expect(page.getByText('Python package', { exact: true })).toBeVisible()
  await expect(page.getByText('weather_generate_future', { exact: true })).toBeVisible()
  await page.screenshot({ path: 'test-results/docs-dark.png' })
})
test('compact workspace and map independent coordinate entry', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 })
  await expect(page.getByLabel('Latitude', { exact: true })).toBeVisible()
  await page.getByLabel('Latitude', { exact: true }).fill('35')
  await page.getByRole('button', { name: 'Review plan', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Run reviewed plan', exact: true })).toBeEnabled()
  await page.screenshot({ path: 'test-results/compact.png' })
})
