import { Model, type IJsonModel } from 'flexlayout-react'
export const layoutKey = 'openepw.layout.v1'
export function defaultLayout(): IJsonModel {
  return {
    global: {
      tabEnableRenderOnDemand: false,
      tabEnablePopout: false,
      tabEnableFloat: false,
      tabEnableClose: false,
      tabSetMinWidth: 240,
    },
    borders: [
      {
        type: 'border',
        location: 'right',
        size: 320,
        selected: -1,
        children: [{ type: 'tab', id: 'agent', name: 'Agent', component: 'agent' }],
      },
    ],
    layout: {
      type: 'row',
      children: [
        {
          type: 'tabset',
          weight: 28,
          children: [{ type: 'tab', id: 'request', name: 'Request', component: 'request' }],
        },
        {
          type: 'tabset',
          weight: 72,
          children: [
            { type: 'tab', id: 'map', name: 'Map', component: 'map' },
            { type: 'tab', id: 'results', name: 'Results', component: 'results' },
            { type: 'tab', id: 'docs', name: 'API Docs', component: 'docs' },
          ],
        },
      ],
    },
  }
}
export function loadLayout() {
  try {
    const raw = localStorage.getItem(layoutKey)
    if (raw) {
      const json = JSON.parse(raw)
      if (JSON.stringify(json).includes('page.')) throw Error()
      return Model.fromJson(json)
    }
  } catch {
    /* Recover incompatible or corrupt layout. */
  }
  return Model.fromJson(defaultLayout())
}
