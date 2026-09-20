import { useEffect, useState } from 'react'
type Operation = {
  summary?: string
  description?: string
  requestBody?: unknown
  responses?: unknown
  parameters?: unknown
}
type Catalog = {
  python: { name: string; signature: string; description: string }[]
  mcp: { name: string; description: string; inputSchema: unknown }[]
  resources: { uri: string; description: string }[]
}
export function ApiDocs() {
  const [paths, setPaths] = useState<Record<string, Record<string, Operation>>>({})
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    Promise.all([
      fetch('/openapi.json').then((r) => r.json()),
      fetch(import.meta.env.BASE_URL + 'api-catalog.json').then((r) => r.json()),
    ])
      .then(([schema, c]) => {
        setPaths(schema.paths)
        setCatalog(c)
      })
      .catch(() => setError('API documentation could not load. Check the backend connection.'))
  }, [])
  return (
    <section className="panel docs-panel">
      <div className="eyebrow">DEVELOPER REFERENCE</div>
      <h1>OpenEPW APIs</h1>
      <p>
        One scientific service, three interfaces. Plan first, inspect the returned limitations, then
        execute.
      </p>
      <div className="actions">
        <a href="/docs" target="_blank" rel="noreferrer">
          Interactive REST reference ↗
        </a>
        <a href="https://github.com/Energy-Atlas/openepw" target="_blank" rel="noreferrer">
          Source code ↗
        </a>
      </div>
      <p className="notice">
        Credentials belong in the Python runtime. When enabled, REST requires an Authorization:
        Bearer header. Jobs return immediately; poll until terminal and inspect partial failures.
        Future baselines/signals are artifact IDs.
      </p>
      {error && <p className="error">{error}</p>}
      <h2>REST endpoints</h2>
      {Object.entries(paths).map(([path, methods]) =>
        Object.entries(methods).map(([method, op]) => (
          <details key={method + path}>
            <summary>
              <span className="badge">{method.toUpperCase()}</span> <code>{path}</code>
            </summary>
            <p>{op.summary}</p>
            <p>{op.description}</p>
            <pre>
              {JSON.stringify(
                { parameters: op.parameters, requestBody: op.requestBody, responses: op.responses },
                null,
                2,
              )}
            </pre>
          </details>
        )),
      )}
      <h2>Python package</h2>
      <pre>{`import openepw
from openepw import Location, WeatherRequest
request = WeatherRequest(locations=Location(lat=42.44, lon=-76.5), years=[2024], providers=["openmeteo"])
plan = openepw.plan(request)
bundle = openepw.execute(plan)`}</pre>
      {catalog?.python.map((p) => (
        <details key={p.name}>
          <summary>
            <code>
              {p.name}
              {p.signature}
            </code>
          </summary>
          <p>{p.description}</p>
        </details>
      ))}
      <h2>MCP tools</h2>
      <p>
        Launch <code>openepw mcp</code> for stdio or use loopback Streamable HTTP. Tool errors
        contain an error object; inspect the job/artifact references instead of expecting inline
        hourly data.
      </p>
      {catalog?.mcp.map((t) => (
        <details key={t.name}>
          <summary>
            <code>{t.name}</code>
          </summary>
          <p>{t.description}</p>
          <pre>{JSON.stringify(t.inputSchema, null, 2)}</pre>
        </details>
      ))}
      {catalog?.resources.map((r) => (
        <p key={r.uri}>
          <code>{r.uri}</code> — {r.description}
        </p>
      ))}
    </section>
  )
}
