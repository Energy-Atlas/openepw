import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { GeometryToolbar } from './GeometryToolbar'
import { VertexHandle, vertexKey } from './VertexHandles'
import type { Position } from './selection'

afterEach(cleanup)

const square: Position[] = [
  [0, 0],
  [1, 0],
  [1, 1],
  [0, 1],
]

it('nudges a focused vertex and deletes only above the minimum vertex count', () => {
  expect(vertexKey(square, 1, 'ArrowUp', false, 3)?.[1]).toEqual([1, 0.01])
  expect(vertexKey(square, 1, 'ArrowLeft', true, 3)?.[1]).toEqual([0.9, 0])
  expect(vertexKey(square, 1, 'Delete', false, 3)).toEqual([
    [0, 0],
    [1, 1],
    [0, 1],
  ])
  expect(vertexKey(square.slice(0, 3), 0, 'Delete', false, 3)).toBeNull()
  expect(vertexKey(square, 0, 'a', false, 3)).toBeNull()
})

it('handles vertex keys before they reach map keyboard panning', () => {
  const onChange = vi.fn()
  const mapKeyboard = vi.fn()
  const { container } = render(
    <div>
      <VertexHandle vertices={square} index={2} minimum={3} onChange={onChange} />
    </div>,
  )
  container.firstElementChild!.addEventListener('keydown', mapKeyboard)
  const handle = screen.getByRole('button', { name: 'Vertex 3 of 4: 1.000, 1.000' })
  handle.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
  expect(onChange).toHaveBeenCalledWith([
    [0, 0],
    [1, 0],
    [1, 0.99],
    [0, 1],
  ])
  expect(mapKeyboard).not.toHaveBeenCalled()
})

it('reopens an applied shape for editing and labels apply and discard', () => {
  const onEdit = vi.fn()
  const onCancel = vi.fn()
  const props = {
    mode: 'polygon' as const,
    vertices: square,
    onMode: vi.fn(),
    onDrawing: vi.fn(),
    onVertices: vi.fn(),
    onFinish: vi.fn(),
    onClear: vi.fn(),
    onEdit,
    onCancel,
  }
  const { rerender } = render(<GeometryToolbar {...props} drawing={false} editable={false} />)
  expect(
    (screen.getByRole('button', { name: 'Edit shape vertices' }) as HTMLButtonElement).disabled,
  ).toBe(true)
  rerender(<GeometryToolbar {...props} drawing={false} editable />)
  fireEvent.click(screen.getByRole('button', { name: 'Edit shape vertices' }))
  expect(onEdit).toHaveBeenCalled()
  rerender(<GeometryToolbar {...props} drawing={false} editable editing />)
  expect(screen.getByRole('button', { name: 'Apply edited shape' })).toBeTruthy()
  expect(screen.getByRole('toolbar').textContent).toContain('km²')
  fireEvent.click(screen.getByRole('button', { name: 'Discard edits' }))
  expect(onCancel).toHaveBeenCalled()
})
