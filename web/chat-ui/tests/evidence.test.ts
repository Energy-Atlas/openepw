import { describe, expect, it } from 'vitest'
import { availabilityFeatures } from '../src/map/evidence'
import type { AvailabilitySummary } from '../src/types'

describe('source scope overlays', () => {
  it('retains every distinct documented source footprint without treating it as point availability', () => {
    const option = (provider: string, dataset: string, footprint: [number, number, number, number] | null) => ({
      provider, dataset, footprint, status: 'unknown', access: 'unknown', health: 'unknown',
      evidence_ids: [], evidence_bases: ['published_scope'], unknowns: ['point coverage'],
      reasons: [], occurrence_index: 0,
    })
    const summary: AvailabilitySummary = { checked_at: '2026-09-26T00:00:00Z', snapshots: [], issues: [],
      options: [option('a', 'one', [-90, -20, 90, 20]), option('a', 'one', [-90, -20, 90, 20]),
        option('a', 'two', [-90, -20, 90, 20]), option('b', 'three', [10, 20, 30, 40]),
        option('c', 'no-map', null)],
    }
    const features = availabilityFeatures(summary)
    expect(features.features).toHaveLength(3)
    expect(features.features.map(feature => feature.properties?.key)).toEqual(['a/one', 'a/two', 'b/three'])
    expect(features.features.every(feature => feature.properties?.basis === 'documented scope')).toBe(true)
  })

  it('normalizes a documented 0–360 global rectangle for the globe', () => {
    const features = availabilityFeatures(undefined, { snapshot: null, unmapped: [], scopes: [{
      provider: 'cds', dataset: 'era5', footprint: [0, -89, 360, 89],
      longitude_convention: '0_360', evidence_bases: ['documentation'],
      evidence_dates: ['2026-09-25'],
    }] })
    expect(features.features).toHaveLength(1)
    expect(features.features[0].geometry.coordinates[0]).toEqual([
      [-180, -89], [180, -89], [180, 89], [-180, 89], [-180, -89],
    ])
  })

  it('splits a documented 0–360 scope at the antimeridian', () => {
    const features = availabilityFeatures(undefined, { snapshot: null, unmapped: [], scopes: [{
      provider: 'cds', dataset: 'regional', footprint: [170, -10, 190, 10],
      longitude_convention: '0_360', evidence_bases: ['documentation'], evidence_dates: [],
    }] })
    expect(features.features).toHaveLength(2)
    expect(features.features[0].geometry.coordinates[0][0]).toEqual([170, -10])
    expect(features.features[1].geometry.coordinates[0][0]).toEqual([-180, -10])
  })
})
