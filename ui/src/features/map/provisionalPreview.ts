import type { Schemas, WeatherRequest } from '../../api/client'
import { canFinish, geometry, type DrawMode, type Position } from './selection'

export type SpatialPreview = Schemas['SpatialPreview']

export const PROVISIONAL_DELAY_MS = 600

/**
 * The request for a provisional preview of a shape still being drawn or edited, or null when
 * there is nothing worth sampling yet. Only area shapes need it; point counts are exact.
 * Dataset selections are dropped, as for the authoritative Explore preview.
 */
export function provisionalRequest(
  draft: WeatherRequest,
  mode: DrawMode,
  vertices: Position[],
): WeatherRequest | null {
  if ((mode !== 'bbox' && mode !== 'polygon') || !canFinish(mode, vertices)) return null
  try {
    return {
      ...draft,
      dataset_selections: [],
      locations: geometry(mode, vertices) as WeatherRequest['locations'],
    }
  } catch {
    return null
  }
}

/**
 * Debounces provisional previews and cancels superseded requests. Results never enter the
 * workflow store: they cannot enable Run or change the authoritative preview version.
 */
export function createPreviewScheduler({
  fetch,
  onResult,
  delay = PROVISIONAL_DELAY_MS,
}: {
  fetch: (request: WeatherRequest, signal: AbortSignal) => Promise<SpatialPreview>
  onResult: (preview: SpatialPreview | null) => void
  delay?: number
}) {
  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | null = null
  let lastKey = ''

  function cancel() {
    clearTimeout(timer)
    controller?.abort()
    controller = null
  }

  return {
    schedule(request: WeatherRequest | null) {
      const key = request ? JSON.stringify(request) : ''
      if (key === lastKey) return
      lastKey = key
      cancel()
      if (!request) {
        onResult(null)
        return
      }
      timer = setTimeout(() => {
        const current = new AbortController()
        controller = current
        fetch(request, current.signal)
          .then((preview) => {
            if (!current.signal.aborted) onResult(preview)
          })
          .catch(() => {
            // A failed provisional preview is not an error: the authoritative preview on
            // apply reports problems. Clear the stale estimate instead.
            if (!current.signal.aborted) onResult(null)
          })
      }, delay)
    },
    dispose() {
      cancel()
      lastKey = ''
    },
  }
}
