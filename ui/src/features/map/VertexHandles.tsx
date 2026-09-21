import { Marker } from '@vis.gl/react-maplibre'
import { useEffect, useRef } from 'react'
import { moveVertex, removeVertex, type Position } from './selection'

/** Pure keyboard handling for a focused vertex handle, testable without a map. */
export function vertexKey(
  vertices: Position[],
  index: number,
  key: string,
  shift: boolean,
  minimum: number,
): Position[] | null {
  if (key === 'Delete' || key === 'Backspace')
    return vertices.length > minimum ? removeVertex(vertices, index) : null
  if (!key.startsWith('Arrow')) return null
  const step = shift ? 0.1 : 0.01
  const [lon, lat] = vertices[index]
  return moveVertex(vertices, index, [
    lon + (key === 'ArrowLeft' ? -step : key === 'ArrowRight' ? step : 0),
    lat + (key === 'ArrowDown' ? -step : key === 'ArrowUp' ? step : 0),
  ])
}

/**
 * Draggable, focusable handles for the vertices being drawn or edited. Deleting stops at the
 * shape's minimum vertex count so the shape stays valid.
 */
export function VertexHandles({
  vertices,
  minimum,
  onChange,
}: {
  vertices: Position[]
  minimum: number
  onChange: (vertices: Position[]) => void
}) {
  return vertices.map((vertex, index) => (
    <Marker
      key={index}
      longitude={vertex[0]}
      latitude={vertex[1]}
      anchor="center"
      draggable
      onDrag={(event) =>
        onChange(moveVertex(vertices, index, [event.lngLat.lng, event.lngLat.lat]))
      }
    >
      <VertexHandle vertices={vertices} index={index} minimum={minimum} onChange={onChange} />
    </Marker>
  ))
}

export function VertexHandle({
  vertices,
  index,
  minimum,
  onChange,
}: {
  vertices: Position[]
  index: number
  minimum: number
  onChange: (vertices: Position[]) => void
}) {
  const button = useRef<HTMLButtonElement>(null)
  const latest = useRef({ vertices, index, minimum, onChange })
  latest.current = { vertices, index, minimum, onChange }
  // MapLibre listens for arrow keys on the map container, which contains every marker. A
  // native listener stops them here so nudging a vertex never also pans the globe.
  useEffect(() => {
    const element = button.current
    if (!element) return
    const keydown = (event: KeyboardEvent) => {
      const current = latest.current
      const next = vertexKey(
        current.vertices,
        current.index,
        event.key,
        event.shiftKey,
        current.minimum,
      )
      if (!next) return
      event.preventDefault()
      event.stopPropagation()
      current.onChange(next)
    }
    element.addEventListener('keydown', keydown)
    return () => element.removeEventListener('keydown', keydown)
  }, [])
  const [lon, lat] = vertices[index]
  return (
    <button
      ref={button}
      type="button"
      className="vertex-handle"
      aria-label={`Vertex ${index + 1} of ${vertices.length}: ${lat.toFixed(3)}, ${lon.toFixed(3)}`}
    />
  )
}
