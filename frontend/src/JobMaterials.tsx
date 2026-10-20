import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

type Product = { id: number; sku: string; name: string; base_unit: string; is_active: boolean }
type Location = { id: number; code: string; name: string; is_active: boolean }
type Line = { product_id: string; location_id: string; quantity: string }
type MaterialIssue = {
  id: number; job_id: number; reason: string; actor: string; created_at: string
  lines: { id: number; product_sku: string; product_name: string; base_unit: string; location_code: string; quantity: string }[]
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...init, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', ...init.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const fieldError = Object.values(body).find((value) => Array.isArray(value)) as string[] | undefined
    throw new Error(body.detail || fieldError?.[0] || `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

function csrfHeader(): Record<string, string> {
  const token = document.cookie.split('; ').find((part) => part.startsWith('csrftoken='))?.split('=').slice(1).join('=')
  return token ? { 'X-CSRFToken': decodeURIComponent(token) } : {}
}

export default function JobMaterials({ organization, jobId, issues, canManage, saving, onSaved }: {
  organization: string; jobId: number; issues: MaterialIssue[]; canManage: boolean; saving: boolean; onSaved: () => Promise<void>
}) {
  const [products, setProducts] = useState<Product[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [error, setError] = useState('')
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID())
  const [lines, setLines] = useState<Line[]>([{ product_id: '', location_id: '', quantity: '' }])
  const loading = useRef(false)
  const base = `/api/organizations/${organization}/inventory/`

  const refresh = useCallback(async () => {
    if (!organization || loading.current) return
    loading.current = true
    try {
      const data = await api<{ products: Product[]; locations: Location[] }>(base)
      setProducts(data.products); setLocations(data.locations)
    } catch (reason) { setError((reason as Error).message) } finally { loading.current = false }
  }, [base, organization])

  useEffect(() => { refresh() }, [refresh])

  function updateLine(index: number, field: keyof Line, value: string) {
    setLines((current) => current.map((line, lineIndex) => lineIndex === index ? { ...line, [field]: value } : line))
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError('')
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    try {
      await api(`/api/organizations/${organization}/jobs/${jobId}/material-issues/`, {
        method: 'POST', headers: csrfHeader(),
        body: JSON.stringify({
          idempotency_key: requestKey,
          reason: form.get('reason'),
          lines: lines.map((line) => ({ product_id: Number(line.product_id), location_id: Number(line.location_id), quantity: line.quantity })),
        }),
      })
      setRequestKey(crypto.randomUUID()); setLines([{ product_id: '', location_id: '', quantity: '' }]); formElement.reset()
      await onSaved()
    } catch (reason) { setError((reason as Error).message) }
  }

  return <section className="job-materials">
    <h3>Materials used</h3>
    {issues.length ? <div className="job-material-history">{issues.map((issue) => <article className="job-note" key={issue.id}>
      <p>{issue.lines.map((line) => `${line.quantity} ${line.base_unit} · ${line.product_sku} · ${line.location_code}`).join(' | ')}</p>
      <span>{issue.reason} · {issue.actor} · {new Date(issue.created_at).toLocaleString()}</span>
    </article>)}</div> : <p className="form-note">No materials recorded for this job.</p>}
    {canManage && <form className="stack-form" onSubmit={submit}>
      {lines.map((line, index) => <div className="field-row" key={index}>
        <label>Product<select required value={line.product_id} onChange={(event) => updateLine(index, 'product_id', event.target.value)}><option value="" disabled>Select product</option>{products.filter((product) => product.is_active).map((product) => <option key={product.id} value={product.id}>{product.sku} · {product.name} ({product.base_unit})</option>)}</select></label>
        <label>Location<select required value={line.location_id} onChange={(event) => updateLine(index, 'location_id', event.target.value)}><option value="" disabled>Select location</option>{locations.filter((location) => location.is_active).map((location) => <option key={location.id} value={location.id}>{location.code} · {location.name}</option>)}</select></label>
        <label>Quantity<input required type="number" min="0.001" step="0.001" value={line.quantity} onChange={(event) => updateLine(index, 'quantity', event.target.value)} /></label>
        {lines.length > 1 && <button type="button" className="quiet-action" onClick={() => setLines((current) => current.filter((_, lineIndex) => lineIndex !== index))}>Remove</button>}
      </div>)}
      <button type="button" className="quiet-action" onClick={() => setLines((current) => [...current, { product_id: '', location_id: '', quantity: '' }])}>Add material</button>
      <label>Reason<input name="reason" minLength={3} maxLength={500} placeholder="Materials used for this job" required /></label>
      {error && <div className="alert inline-alert">{error}</div>}
      <button className="primary" disabled={saving || !products.some((product) => product.is_active) || !locations.some((location) => location.is_active)}>Record materials</button>
      <p className="form-note">Recording reduces stock immediately. Quantities only; no reservations or cost allocation.</p>
    </form>}
  </section>
}
