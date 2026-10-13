import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProductDialog, type ProductOption } from '../src/ProductDialog'

afterEach(cleanup)

const option = (id: string, available: number, group: 'actual' | 'typical' = 'actual'): ProductOption =>
  ({ id, label: id, group, available, unverified: available ? 0 : 1, sites: 1 })

describe('product dialog', () => {
  it('lists products checked here first and the rest under their own heading', () => {
    render(<ProductDialog options={[option('era5', 1), option('cds', 0), option('pvgis', 0, 'typical')]}
      selected={[]} busy={false} onToggle={vi.fn()} onType={vi.fn()} onConfirm={vi.fn()} />)
    const names = screen.getAllByText(/^(era5|cds|pvgis)$/).map(item => item.textContent)
    expect(names).toEqual(['era5', 'cds', 'pvgis'])
    expect(screen.getAllByText('Not checked here · checked when planning')).toHaveLength(2)
  })

  it('has no extra heading when the catalog lists nothing here', () => {
    render(<ProductDialog options={[option('era5', 0), option('cds', 0)]}
      selected={[]} busy={false} onToggle={vi.fn()} onType={vi.fn()} onConfirm={vi.fn()} />)
    expect(screen.queryByText('Not checked here · checked when planning')).toBeNull()
  })
})
