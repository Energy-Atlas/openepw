import AxeBuilder from '@axe-core/playwright'
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
  await expect(page.getByRole('heading', { name: 'Build a weather request' })).toHaveCSS(
    'color',
    'rgb(228, 231, 235)',
  )
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

test('scripted actions call real tools and invalidate a changed plan', async ({ page }) => {
  await page.locator('header').getByRole('button', { name: 'Agent', exact: true }).click()
  const panel = page.locator('.agent-panel')
  await expect(panel.getByText('Scripted · no LLM')).toBeVisible()
  await panel.getByRole('button', { name: /Find sources/ }).click()
  await expect(page.getByText('openmeteo · synthetic browser test')).toBeVisible()
  await panel.getByRole('button', { name: /Review a plan/ }).click()
  await expect(panel.getByRole('button', { name: /Run reviewed plan/ })).toBeEnabled()
  await page.getByLabel('Latitude', { exact: true }).fill('40')
  await expect(panel.getByRole('button', { name: /Run reviewed plan/ })).toBeDisabled()
})
test('map selection uses actual click coordinates', async ({ page }) => {
  await page.getByRole('button', { name: 'Select on map', exact: true }).click()
  await page.locator('.maplibregl-canvas').click({ position: { x: 240, y: 220 } })
  await expect(page.getByRole('button', { name: 'Select on map', exact: true })).toBeVisible()
  await expect(page.getByLabel('Latitude', { exact: true })).not.toHaveValue('42.44')
  await page.getByRole('button', { name: '2D / 3D', exact: true }).click()
  await page.getByRole('button', { name: 'Globe', exact: true }).click()
  await page.screenshot({ path: 'test-results/map.png' })
})
test('future generation uploads a baseline and real local signals', async ({ page, request }) => {
  const plan = await (
    await request.post('/v1/weather/plan', {
      data: { locations: { lat: 42.44, lon: -76.5 }, years: [2023], providers: ['openmeteo'] },
    })
  ).json()
  const submitted = await (await request.post('/v1/weather/jobs', { data: { plan } })).json()
  let job = submitted
  await expect
    .poll(
      async () => {
        job = await (await request.get('/v1/jobs/' + submitted.id)).json()
        return job.state
      },
      { timeout: 30000 },
    )
    .toBe('completed')
  const baseline = await (await request.get('/v1/artifacts/' + job.bundle.weather[0].id)).body()
  await page.getByRole('button', { name: 'Future weather', exact: true }).click()
  await page
    .getByLabel('Baseline EPW', { exact: true })
    .setInputFiles({ name: 'baseline.epw', mimeType: 'application/octet-stream', buffer: baseline })
  await expect(page.getByRole('button', { name: 'Review future plan', exact: true })).toBeEnabled()
  await page.getByText('Models and local signals', { exact: true }).click()
  const signal = {
    model: 'synthetic browser test',
    member: 'r1',
    scenario: 'ssp245',
    reference_period: [1985, 2014],
    climate_period: [2036, 2065],
    license: 'synthetic test fixture',
    source_uri: 'synthetic://browser',
    source_checksums: ['0'.repeat(64)],
    temperature_delta: Array(12).fill(2),
  }
  await page.getByLabel('Monthly signal JSON', { exact: true }).setInputFiles({
    name: 'signals.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify([signal])),
  })
  await expect(page.getByText('Signals registered')).toBeVisible()
  await page.getByRole('button', { name: 'Review future plan', exact: true }).click()
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
  await expect(page.getByText('8,760 rows', { exact: false })).toBeVisible()
})

test('all appearances keep readable chrome and accessible request controls', async ({ page }) => {
  for (const theme of ['light', 'dark', 'monochrome', 'lieflat', 'cleanLight', 'darkEngineering']) {
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await page.getByLabel('Appearance', { exact: true }).selectOption(theme)
    await page.keyboard.press('Escape')
    const actual = await page
      .getByRole('heading', { name: 'Build a weather request' })
      .evaluate((e) => getComputedStyle(e).color)
    const expected = await page.evaluate(() => {
      const el = document.createElement('span')
      el.style.color = 'var(--color-text)'
      document.body.append(el)
      const color = getComputedStyle(el).color
      el.remove()
      return color
    })
    expect(actual).toBe(expected)
  }
  const audit = await new AxeBuilder({ page }).analyze()
  expect(audit.violations.filter((v) => ['serious', 'critical'].includes(v.impact || ''))).toEqual(
    [],
  )
  await page.screenshot({ path: 'test-results/workspace-dark.png' })
})

test('comma lists and drafts survive reload without running jobs', async ({ page }) => {
  const years = page.getByLabel('Years (comma separated)')
  await years.fill('2023')
  await years.press('End')
  await years.pressSequentially(',2024')
  await years.press('Tab')
  await expect(years).toHaveValue('2023,2024')
  let submissions = 0
  page.on('request', (r) => {
    if (r.method() === 'POST' && r.url().endsWith('/jobs')) submissions++
  })
  await page.reload()
  await expect(page.getByLabel('Years (comma separated)')).toHaveValue('2023,2024')
  await expect(page.getByRole('button', { name: 'Run reviewed plan', exact: true })).toHaveCount(0)
  expect(submissions).toBe(0)
})
