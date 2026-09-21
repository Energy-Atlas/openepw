import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.route(/^https:\/\//, async (route) => {
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
  await expect(page.getByText('1 sample points')).toBeVisible({ timeout: 15000 })
})

async function discover(page: Page) {
  await page.getByRole('button', { name: 'Find availability' }).click()
  await expect(page.getByRole('heading', { name: 'Download' })).toBeVisible()
  await expect(page.getByLabel('openmeteo / era5')).toBeVisible()
  await expect(page.getByLabel('cds / reanalysis-era5-single-levels')).toBeVisible()
}

async function startDownload(page: Page) {
  await page.getByRole('button', { name: 'Download weather' }).click()
  await page.getByRole('button', { name: 'Confirm job' }).click()
}

async function addCdsToReviewedPlan(page: Page) {
  const plan = page.getByRole('region', { name: 'Reviewed plan' })
  await expect(plan).toContainText('EPW mappings')
  const cds = page.getByLabel('cds / reanalysis-era5-single-levels')
  await cds.click()
  await expect(page.getByRole('alertdialog', { name: 'Update upstream inputs?' })).toBeVisible()
  await page.getByRole('button', { name: 'Apply change' }).click()
  await expect(cds).toBeChecked()
  await expect(plan).not.toContainText('This plan is stale and cannot run.')
}

test('browser map fixtures do not fetch live tiles', async ({ page }) => {
  const liveTiles: string[] = []
  page.context().on('response', (response) => {
    if (
      response.status() === 200 &&
      /tiles\.(mapterhorn|openfreemap)\.com/.test(new URL(response.url()).hostname)
    )
      liveTiles.push(new URL(response.url()).hostname)
  })
  await page.reload()
  await expect(page.getByRole('region', { name: 'Map' })).toBeVisible()
  await page.waitForTimeout(1500)
  expect(liveTiles).toEqual([])
})

test('Explore sends one spatial preview for an unchanged query', async ({ page }) => {
  let previews = 0
  let delayOnePreview = false
  await page.route('**/v1/spatial/preview', async (route) => {
    if (delayOnePreview) {
      delayOnePreview = false
      await new Promise((resolve) => setTimeout(resolve, 6000))
    }
    await route.continue()
  })
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/v1/spatial/preview') previews++
  })
  await page.reload()
  await expect(page.getByText('1 sample points')).toBeVisible()
  await page.waitForTimeout(1500)
  expect(previews).toBe(1)

  delayOnePreview = true
  await page.getByLabel('Latitude').fill('41.5')
  await expect.poll(() => previews).toBe(2)
  await expect(page.getByText('Working with the OpenEPW service…')).toHaveCount(0, {
    timeout: 15000,
  })
  await page.getByRole('button', { name: 'More run options' }).click()
  await page.getByRole('menuitem', { name: 'Refresh sample preview' }).click()
  await expect.poll(() => previews).toBe(3)
})

test('Explore does not automatically retry a failed spatial preview', async ({ page }) => {
  let previews = 0
  await page.route('**/v1/spatial/preview', async (route) => {
    previews++
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ code: 'SOURCE_UNAVAILABLE', message: 'Preview unavailable' }),
    })
  })
  await page.reload()
  await expect(page.getByRole('alert')).toContainText('Preview unavailable')
  await expect(
    page.getByText(/Sample preview did not complete; edit the query or use Refresh sample preview/),
  ).toBeVisible()
  await page.waitForTimeout(1500)
  expect(previews).toBe(1)

  await page.getByLabel('Latitude').fill('41.5')
  await expect.poll(() => previews).toBe(2)
})

test('Explore uses authoritative sampling, fixed globe controls and documented coverage', async ({
  page,
}) => {
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
})

test('multi-dataset Download runs, advances asynchronously and opens the full artifact inspector', async ({
  page,
}) => {
  await discover(page)
  await addCdsToReviewedPlan(page)
  const run = page.getByRole('button', { name: 'Download weather' })
  await expect(run).toBeEnabled()
  await startDownload(page)
  await expect(page.getByRole('heading', { name: 'Project', exact: true })).toBeVisible({
    timeout: 30000,
  })
  await expect(page.getByRole('region', { name: 'Weather inspector' })).toBeVisible()
  await expect(page.getByText(/8,784 rows/)).toBeVisible()
  await expect(page.getByRole('img', { name: /Monthly mean temperature/ })).toBeVisible()
  await expect(page.getByRole('img', { name: /Hourly dni heatmap/ })).toBeVisible()
  await expect(page.getByText('Leap day retained')).toBeVisible()
  await page.getByRole('button', { name: 'Collapse weather inspector' }).click()
  await expect(page.getByRole('button', { name: /Inspect .*\.epw/ })).toBeVisible()
  await page.getByRole('button', { name: /Inspect .*\.epw/ }).click()
  await expect(page.getByRole('region', { name: 'Weather inspector' })).toBeVisible()
  await page.getByRole('button', { name: 'History' }).click()
  await expect(page.getByRole('dialog', { name: 'Job history' })).toContainText('completed')
})

test('a sampled partial source failure remains explicit while successful EPWs unlock Project', async ({
  page,
}) => {
  const polygon = {
    type: 'Polygon',
    coordinates: [
      [
        [-76.52, 42.42],
        [-76.4, 42.42],
        [-76.4, 42.48],
        [-76.52, 42.48],
        [-76.52, 42.42],
      ],
    ],
  }
  await page.getByLabel('Horizontal spacing').fill('5')
  await page.getByLabel('Vertical spacing').fill('5')
  await page.getByLabel('Import GeoJSON geometry').setInputFiles({
    name: 'selection.geojson',
    mimeType: 'application/geo+json',
    buffer: Buffer.from(JSON.stringify(polygon)),
  })
  await expect(page.getByText(/[2-9] sample points/)).toBeVisible()
  await discover(page)
  await addCdsToReviewedPlan(page)
  await expect(page.getByRole('button', { name: 'Download weather' })).toBeEnabled()
  await startDownload(page)
  await expect(page.getByRole('heading', { name: 'Project', exact: true })).toBeVisible({
    timeout: 45000,
  })
  await page.getByRole('button', { name: 'History' }).click()
  await expect(page.getByRole('dialog', { name: 'Job history' })).toContainText(
    'partially completed',
  )
  await expect(page.getByRole('dialog', { name: 'Job history' })).toContainText(
    'SOURCE_UNAVAILABLE',
  )
})

test('the deterministic Agent confirms jobs and narrow drawers restore focus', async ({ page }) => {
  await discover(page)
  await expect(page.getByRole('button', { name: 'Download weather' })).toBeEnabled()
  await page.getByRole('button', { name: 'Start the reviewed job' }).click()
  await expect(page.getByText('Confirmation required')).toBeVisible()
  await expect(
    page.getByText('This starts a server job and may invalidate downstream working state.'),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Keep reviewing' }).click()

  await page.setViewportSize({ width: 700, height: 850 })
  await expect(page.getByLabel('Weather map workspace')).toBeVisible()
  const controls = page.getByRole('button', { name: 'Controls' })
  await controls.click()
  await expect(page.getByRole('complementary', { name: 'Stage controls' })).toBeVisible()
  await page.getByRole('button', { name: 'Agent panel' }).click()
  await expect(page.getByRole('complementary', { name: 'Agent' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Agent panel' })).toBeFocused()
  await page.screenshot({ path: 'test-results/narrow-workspace.png' })
})

test('appearances remain accessible and map failure keeps numeric Explore controls', async ({
  page,
}) => {
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

  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function (type: string, ...args: unknown[]) {
      if (type.startsWith('webgl') || type === 'experimental-webgl') return null
      return original.apply(this, [type, ...args] as never)
    } as typeof original
  })
  await page.reload()
  await expect(page.getByLabel('Latitude')).toBeVisible()
  await page.getByLabel('Latitude').fill('41.5')
  await expect(page.getByText('1 sample points')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Find availability' })).toBeEnabled()
})

test('reload preserves drafts without submitting a job', async ({ page }) => {
  const years = page.getByLabel('Years')
  await years.fill('2023,2024')
  await years.press('Tab')
  await expect(years).toHaveValue('2023,2024')
  let submissions = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/jobs')) submissions++
  })
  await page.reload()
  await expect(page.getByLabel('Years')).toHaveValue('2023,2024')
  expect(submissions).toBe(0)
})

test('MapLibre module worker imports its shared runtime successfully', async ({ page }) => {
  const runtime = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith('/maplibre-gl-shared.mjs'),
  )
  await page.reload()
  const response = await runtime
  expect(response.status()).toBe(200)
  expect(response.headers()['content-type']).toMatch(/(?:text|application)\/javascript/)
  await expect(page.locator('.maplibregl-canvas')).toBeVisible()
})
