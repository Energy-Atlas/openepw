import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// Browser coverage is intentionally small: request-count, partial-job and state permutations
// live in Vitest and pytest. Every external host is stubbed so no test depends on live tiles.
let externalRequests: string[]

test.beforeEach(async ({ page }) => {
  externalRequests = []
  await page.route(
    (url) => url.hostname !== '127.0.0.1',
    async (route) => {
      const url = route.request().url()
      externalRequests.push(url)
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
    },
  )
})

async function open(page: Page) {
  await page.goto('./')
  await expect(page.getByText('1 sample points')).toBeVisible({ timeout: 15000 })
}

async function discover(page: Page) {
  await page.getByRole('button', { name: 'Find availability' }).click()
  await expect(page.getByRole('heading', { name: 'Download' })).toBeVisible()
  await expect(page.getByLabel('openmeteo / era5')).toBeVisible()
  await expect(page.getByLabel('cds / reanalysis-era5-single-levels')).toBeVisible()
}

test('the map renders offline and its module worker executes @production', async ({ page }) => {
  const liveTiles: string[] = []
  page.context().on('response', (response) => {
    const host = new URL(response.url()).hostname
    const stubbedStyle = new URL(response.url()).pathname.startsWith('/styles/')
    if (
      response.status() === 200 &&
      !stubbedStyle &&
      /tiles\.(mapterhorn|openfreemap)\./.test(host)
    )
      liveTiles.push(response.url())
  })
  const runtime = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith('/maplibre-gl-shared.mjs'),
  )
  await open(page)
  const response = await runtime
  expect(response.status()).toBe(200)
  expect(response.headers()['content-type']).toMatch(/(?:text|application)\/javascript/)
  await expect(page.locator('.maplibregl-canvas')).toBeVisible()
  // MapLibre's worker module defines these globals only after it and its shared runtime run.
  await expect
    .poll(async () => {
      const worker = page.workers().find((item) => item.url().endsWith('/maplibre-gl-worker.mjs'))
      return worker?.evaluate(() => {
        const scope = self as unknown as { registerWorkerSource?: unknown; worker?: unknown }
        return typeof scope.registerWorkerSource === 'function' && typeof scope.worker === 'object'
      })
    })
    .toBe(true)
  // Waiting for intercepted terrain tiles replaces a fixed sleep before the live-tile check.
  await expect
    .poll(() => externalRequests.filter((url) => url.includes('tiles.mapterhorn.com')).length)
    .toBeGreaterThan(0)
  expect(externalRequests.some((url) => url.includes('/styles/'))).toBe(true)
  expect(liveTiles).toEqual([])
})

test('Explore, Download and Project complete with confirmation and the artifact inspector', async ({
  page,
}) => {
  await open(page)
  await expect(page.getByRole('toolbar', { name: 'Geometry tools' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Globe' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Terrain' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Coverage layers' }).click()
  await expect(page.getByText('Extents are not observed availability.')).toBeVisible()
  await expect(page.getByText('ERA5 via Open-Meteo')).toBeVisible()
  await expect(page.getByText('PVGIS published TMY')).toBeVisible()
  await page.getByLabel('ERA5 via Open-Meteo').check()
  await expect(page.getByLabel('Opacity')).toBeVisible()

  await discover(page)
  await expect(page.getByRole('toolbar', { name: 'Geometry tools' })).toHaveCount(0)
  const run = page.getByRole('button', { name: 'Download weather' })
  await expect(run).toBeEnabled()
  await page.getByRole('button', { name: 'Start the reviewed job' }).click()
  await expect(page.getByText('Confirmation required')).toBeVisible()
  await expect(
    page.getByText('This starts a server job and may invalidate downstream working state.'),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Keep reviewing' }).click()

  const plan = page.getByRole('region', { name: 'Reviewed plan' })
  await expect(plan).toContainText('EPW mappings')
  const cds = page.getByLabel('cds / reanalysis-era5-single-levels')
  await cds.click()
  await expect(page.getByRole('alertdialog', { name: 'Update upstream inputs?' })).toBeVisible()
  await page.getByRole('button', { name: 'Apply change' }).click()
  await expect(cds).toBeChecked()
  await expect(plan).not.toContainText('This plan is stale and cannot run.')
  await expect(run).toBeEnabled()
  await run.click()
  await page.getByRole('button', { name: 'Confirm job' }).click()

  await expect(page.getByRole('heading', { name: 'Project', exact: true })).toBeVisible({
    timeout: 30000,
  })
  await expect(page.getByRole('region', { name: 'Weather inspector' })).toBeVisible()
  await expect(page.getByText(/8,784 rows/)).toBeVisible()
  await expect(page.getByRole('img', { name: /Monthly mean temperature/ })).toBeVisible()
  await expect(page.getByRole('img', { name: /Hourly dni heatmap/ })).toBeVisible()
  await expect(page.getByText('Leap day retained')).toBeVisible()
  await page.getByRole('button', { name: 'Collapse weather inspector' }).click()
  await page.getByRole('button', { name: /Inspect .*\.epw/ }).click()
  await expect(page.getByRole('region', { name: 'Weather inspector' })).toBeVisible()
  await page.getByRole('button', { name: 'History' }).click()
  await expect(page.getByRole('dialog', { name: 'Job history' })).toContainText('completed')
})

test('appearances, narrow drawers, draft reload and map failure stay accessible', async ({
  page,
}) => {
  await open(page)
  for (const appearance of ['light', 'dark', 'monochrome']) {
    await page.getByRole('button', { name: 'Settings' }).click()
    await page.getByLabel('Appearance').selectOption(appearance)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('heading', { name: 'Explore' })).toBeVisible()
    await page.screenshot({ path: `test-results/${appearance}-desktop.png` })
  }
  const audit = await new AxeBuilder({ page }).analyze()
  expect(
    audit.violations.filter((violation) =>
      ['serious', 'critical'].includes(violation.impact || ''),
    ),
  ).toEqual([])

  await page.setViewportSize({ width: 700, height: 850 })
  await expect(page.getByLabel('Weather map workspace')).toBeVisible()
  await page.getByRole('button', { name: 'Controls' }).click()
  await expect(page.getByRole('complementary', { name: 'Stage controls' })).toBeVisible()
  await page.getByRole('button', { name: 'Agent panel' }).click()
  await expect(page.getByRole('complementary', { name: 'Agent' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Agent panel' })).toBeFocused()
  await page.screenshot({ path: 'test-results/narrow-workspace.png' })

  await page.setViewportSize({ width: 1440, height: 950 })
  const years = page.getByLabel('Years')
  await years.fill('2023,2024')
  await years.press('Tab')
  await expect(years).toHaveValue('2023,2024')
  let submissions = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/jobs')) submissions++
  })
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function (type: string, ...args: unknown[]) {
      if (type.startsWith('webgl') || type === 'experimental-webgl') return null
      return original.apply(this, [type, ...args] as never)
    } as typeof original
  })
  await page.reload()
  await expect(page.getByLabel('Years')).toHaveValue('2023,2024')
  await page.getByLabel('Latitude').fill('41.5')
  await expect(page.getByText('1 sample points')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Find availability' })).toBeEnabled()
  expect(submissions).toBe(0)
})
