import {
  BoxSelect,
  Check,
  MapPin,
  MousePointer2,
  Pentagon,
  RedoDot,
  Trash2,
  Undo2,
  X,
} from 'lucide-react'
import type { DrawMode, Position } from './selection'
import { canFinish, measureSelection, moveVertex, undoVertex } from './selection'

const tools: { mode: DrawMode; label: string; icon: typeof MapPin }[] = [
  { mode: 'point', label: 'Select one point', icon: MapPin },
  { mode: 'points', label: 'Select multiple points', icon: RedoDot },
  { mode: 'bbox', label: 'Draw bounding box', icon: BoxSelect },
  { mode: 'polygon', label: 'Draw polygon', icon: Pentagon },
]

export function GeometryToolbar({
  mode,
  drawing,
  vertices,
  onMode,
  onDrawing,
  onVertices,
  onFinish,
  onClear,
}: {
  mode: DrawMode
  drawing: boolean
  vertices: Position[]
  onMode: (mode: DrawMode) => void
  onDrawing: (drawing: boolean) => void
  onVertices: (vertices: Position[]) => void
  onFinish: () => void
  onClear: () => void
}) {
  function nudge(event: React.KeyboardEvent) {
    if (!drawing || !vertices.length || !event.key.startsWith('Arrow')) return
    event.preventDefault()
    const [lon, lat] = vertices.at(-1)!
    const step = event.shiftKey ? 0.1 : 0.01
    const next: Position = [
      lon + (event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0),
      lat + (event.key === 'ArrowDown' ? -step : event.key === 'ArrowUp' ? step : 0),
    ]
    onVertices(moveVertex(vertices, vertices.length - 1, next))
  }

  return (
    <div className="geometry-tools" role="toolbar" aria-label="Geometry tools" onKeyDown={nudge}>
      <button
        type="button"
        title="Pan map"
        aria-label="Pan map"
        aria-pressed={!drawing}
        onClick={() => onDrawing(false)}
      >
        <MousePointer2 aria-hidden="true" />
      </button>
      {tools.map((tool) => {
        const Icon = tool.icon
        return (
          <button
            type="button"
            key={tool.mode}
            title={tool.label}
            aria-label={tool.label}
            aria-pressed={drawing && mode === tool.mode}
            onClick={() => {
              onMode(tool.mode)
              onVertices([])
              onDrawing(true)
            }}
          >
            <Icon aria-hidden="true" />
          </button>
        )
      })}
      <span className="geometry-divider" aria-hidden="true" />
      <button
        type="button"
        title="Undo last vertex"
        aria-label="Undo last vertex"
        disabled={!vertices.length}
        onClick={() => onVertices(undoVertex(vertices))}
      >
        <Undo2 aria-hidden="true" />
      </button>
      <button
        type="button"
        title="Delete selection"
        aria-label="Delete selection"
        onClick={onClear}
      >
        <Trash2 aria-hidden="true" />
      </button>
      {drawing && (
        <>
          <button
            type="button"
            className="geometry-finish"
            title="Finish selection"
            aria-label="Finish selection"
            disabled={!canFinish(mode, vertices)}
            onClick={onFinish}
          >
            <Check aria-hidden="true" />
          </button>
          <button
            type="button"
            title="Cancel drawing"
            aria-label="Cancel drawing"
            onClick={() => {
              onVertices([])
              onDrawing(false)
            }}
          >
            <X aria-hidden="true" />
          </button>
        </>
      )}
      <output aria-live="polite">{measureSelection(mode, vertices)}</output>
    </div>
  )
}
