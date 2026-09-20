import { resolve } from 'node:path'
import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './e2e',
  timeout: 45000,
  workers: 1,
  use: {
    baseURL: process.env.UI_PRODUCTION ? 'http://127.0.0.1:8011/ui/' : 'http://127.0.0.1:5174/ui/',
    channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge',
    viewport: { width: 1440, height: 950 },
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `"${resolve(process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python')}" -m uvicorn ui_server:app --app-dir ../tests --host 127.0.0.1 --port 8011`,
      url: 'http://127.0.0.1:8011/health',
      reuseExistingServer: false,
      cwd: '.',
      env: { OPENEPW_UI_TEST_ROOT: '../.local/ui-browser-tests' },
    },
    ...(!process.env.UI_PRODUCTION
      ? [
          {
            command: 'npm run dev -- --port 5174',
            url: 'http://127.0.0.1:5174/ui/',
            env: { OPENEPW_API_URL: 'http://127.0.0.1:8011' },
            reuseExistingServer: false,
          },
        ]
      : []),
  ],
})
