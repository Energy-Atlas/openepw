import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/v1': 'http://127.0.0.1:8000', '/auth': 'http://127.0.0.1:8000', '/health': 'http://127.0.0.1:8000' } },
  preview: { proxy: { '/v1': 'http://127.0.0.1:8000', '/auth': 'http://127.0.0.1:8000', '/health': 'http://127.0.0.1:8000' } },
  test: { environment: 'jsdom', setupFiles: ['./tests/setup.ts'] },
})
