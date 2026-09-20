import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
export default defineConfig({
  base: '/ui/',
  optimizeDeps: { exclude: ['maplibre-gl'] },
  plugins: [
    react(),
    {
      name: 'flexlayout-css-map',
      enforce: 'pre',
      async load(id) {
        const file = id.split('?')[0].replaceAll('\\', '/')
        if (!/flexlayout-react\/style\/[^/]+\.css$/.test(file)) return null
        return {
          code: (await readFile(file, 'utf8')).replace(
            /\/\*#\s*sourceMappingURL=[^*]*\*\/\s*$/,
            '',
          ),
          map: null,
        }
      },
    },
    {
      name: 'maplibre-workers',
      apply: 'build',
      async generateBundle() {
        const require = createRequire(import.meta.url)
        const dir = join(dirname(require.resolve('maplibre-gl/package.json')), 'dist')
        for (const name of ['maplibre-gl-worker.mjs', 'maplibre-gl-shared.mjs'])
          this.emitFile({
            type: 'asset',
            fileName: 'assets/' + name,
            source: await readFile(join(dir, name)),
          })
      },
    },
  ],
  server: {
    proxy: Object.fromEntries(
      ['/v1', '/health', '/openapi.json', '/docs', '/redoc'].map((p) => [
        p,
        process.env.OPENEPW_API_URL || 'http://127.0.0.1:8000',
      ]),
    ),
  },
  build: { chunkSizeWarningLimit: 1500 },
})
