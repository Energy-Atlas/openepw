import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { App } from '../src/App'

describe('map-first shell', () => {
  it('opens one chat over a full-canvas map without a mode choice', () => {
    render(<App />)
    expect(screen.getByLabelText('Weather map')).toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'Weather chat' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeInTheDocument()
    expect(screen.queryByText('Guided workflow')).not.toBeInTheDocument()
  })

  it('offers scene controls without letting terrain run in a flat view', () => {
    render(<App />)
    expect(screen.getByRole('button', { name: '3D view' })).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Terrain' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '3D view' }))
    expect(screen.getByRole('checkbox', { name: 'Terrain' })).toBeEnabled()
  })
})
