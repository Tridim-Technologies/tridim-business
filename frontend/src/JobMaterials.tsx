import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './JobMaterials.css'

type Product = { id: number; sku: string; name: string; base_unit: string; is_active: boolean; balances: { location_id: number; available_quantity: string }[] }
type Location = { id: number; code: string; name: string; is_active: boolean }
type Line = { product_id: string; location_id: string; quantity: string; reservation_line_id: string }
type ReservationLine = { id: number; product_id: number; location_id: number; product_sku: string; product_name: string; base_unit: string; location_code: string; quantity: string; issued_quantity: string; remaining_quantity: string }
type Reservation = { id: number; status: 'active' | 'released'; reason: string; actor: string; created_at: string; released_by: string | null; released_at: string | null; lines: ReservationLine[] }
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
  const [lines, setLines] = useState<Line[]>([{ product_id: '', location_id: '', quantity: '', reservation_line_id: '' }])
  const [reservations, setReservations] = useState<Reservation[]>([])
  const loading = useRef(false)
  const base = `/api/organizations/${organization}/inventory/`

  const refresh = useCallback(async () => {
    if (!organization || loading.current) return
    loading.current = true
    try {
      const [data, reservationData] = await Promise.all([
        api<{ products: Product[]; locations: Location[] }>(base),
        api<{ results: Reservation[] }>(`/api/organizations/${organization}/jobs/${jobId}/material-reservations/`),
      ])
      setProducts(data.products); setLocations(data.locations); setReservations(reservationData.results)
    } catch (reason) { setError((reason as Error).message) } finally { loading.current = false }
  }, [base, jobId, organization])

  useEffect(() => { refresh() }, [refresh])

  function updateLine(index: number, field: keyof Line, value: string) {
    setLines((current) => current.map((line, lineIndex) => lineIndex === index
      ? { ...line, [field]: value, ...(field === 'product_id' || field === 'location_id' ? { reservation_line_id: '' } : {}) }
      : line))
  }

  function selectReservation(index: number, reservationLineId: string) {
    const reservedLine = reservations.flatMap((reservation) => reservation.status === 'active' ? reservation.lines : []).find((line) => line.id === Number(reservationLineId))
    setLines((current) => current.map((line, lineIndex) => lineIndex === index ? reservedLine
      ? { product_id: String(reservedLine.product_id), location_id: String(reservedLine.location_id), quantity: reservedLine.remaining_quantity, reservation_line_id: reservationLineId }
      : { ...line, reservation_line_id: '' } : line))
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError('')
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null
    const action = submitter?.value === 'reserve' ? 'reserve' : 'issue'
    const reservationLines = lines.map((line) => ({ product_id: Number(line.product_id), location_id: Number(line.location_id), quantity: line.quantity }))
    const issueLines = lines.map((line) => ({
      product_id: Number(line.product_id),
      location_id: Number(line.location_id),
      quantity: line.quantity,
      ...(line.reservation_line_id ? { reservation_line_id: Number(line.reservation_line_id) } : {}),
    }))
    try {
      await api(`/api/organizations/${organization}/jobs/${jobId}/material-${action === 'reserve' ? 'reservations' : 'issues'}/`, {
        method: 'POST', headers: csrfHeader(),
        body: JSON.stringify({
          idempotency_key: requestKey,
          reason: form.get('reason'),
          lines: action === 'reserve' ? reservationLines : issueLines,
        }),
      })
      setRequestKey(crypto.randomUUID()); setLines([{ product_id: '', location_id: '', quantity: '', reservation_line_id: '' }]); formElement.reset()
      await Promise.all([refresh(), onSaved()])
    } catch (reason) { setError((reason as Error).message) }
  }

  async function releaseReservation(reservationId: number) {
    setError('')
    try {
      await api(`/api/organizations/${organization}/jobs/${jobId}/material-reservations/${reservationId}/release/`, { method: 'POST', headers: csrfHeader(), body: '{}' })
      await Promise.all([refresh(), onSaved()])
    } catch (reason) { setError((reason as Error).message) }
  }

  const activeReservationLines = reservations.flatMap((reservation) => reservation.status === 'active' ? reservation.lines.filter((line) => Number(line.remaining_quantity) > 0).map((line) => ({ ...line, reason: reservation.reason })) : [])

  return <section className="job-materials">
    <h3>Materials used</h3>
    {issues.length ? <div className="job-material-history">{issues.map((issue) => <article className="job-note" key={issue.id}>
      <p>{issue.lines.map((line) => `${line.quantity} ${line.base_unit} · ${line.product_sku} · ${line.location_code}`).join(' | ')}</p>
      <span>{issue.reason} · {issue.actor} · {new Date(issue.created_at).toLocaleString()}</span>
    </article>)}</div> : <p className="form-note">No materials recorded for this job.</p>}
    {reservations.length > 0 && <div className="job-material-history"><h4>Material reservations</h4>{reservations.map((reservation) => <article className="job-note" key={reservation.id}>
      <p>{reservation.lines.map((line) => `${line.remaining_quantity} remaining of ${line.quantity} ${line.base_unit} · ${line.product_sku} · ${line.location_code}`).join(' | ')}</p>
      <span>{reservation.reason} · {reservation.actor} · {reservation.status}{reservation.released_by ? ` · released by ${reservation.released_by}` : ''}</span>
      {canManage && reservation.status === 'active' && <button type="button" className="quiet-action" onClick={() => void releaseReservation(reservation.id)}>Release unused quantities</button>}
    </article>)}</div>}
    {canManage && <form className="stack-form" onSubmit={submit}>
      {lines.map((line, index) => <div className="field-row" key={index}>
        {activeReservationLines.length > 0 && <label>Reservation<select value={line.reservation_line_id} onChange={(event) => selectReservation(index, event.target.value)}><option value="">Use unreserved stock</option>{activeReservationLines.map((reservationLine) => <option key={reservationLine.id} value={reservationLine.id}>{reservationLine.product_sku} · {reservationLine.location_code} · {reservationLine.remaining_quantity} {reservationLine.base_unit} reserved</option>)}</select></label>}
        <label>Product<select required disabled={Boolean(line.reservation_line_id)} value={line.product_id} onChange={(event) => updateLine(index, 'product_id', event.target.value)}><option value="" disabled>Select product</option>{products.filter((product) => product.is_active).map((product) => <option key={product.id} value={product.id}>{product.sku} · {product.name} ({product.base_unit})</option>)}</select></label>
        <label>Location<select required disabled={Boolean(line.reservation_line_id)} value={line.location_id} onChange={(event) => updateLine(index, 'location_id', event.target.value)}><option value="" disabled>Select location</option>{locations.filter((location) => location.is_active).map((location) => <option key={location.id} value={location.id}>{location.code} · {location.name}</option>)}</select>{line.product_id && line.location_id && <span className="form-note">Available: {products.find((product) => product.id === Number(line.product_id))?.balances.find((balance) => balance.location_id === Number(line.location_id))?.available_quantity || '0.000'}</span>}</label>
        <label>Quantity<input required type="number" min="0.001" step="0.001" value={line.quantity} onChange={(event) => updateLine(index, 'quantity', event.target.value)} /></label>
        {lines.length > 1 && <button type="button" className="quiet-action" onClick={() => setLines((current) => current.filter((_, lineIndex) => lineIndex !== index))}>Remove</button>}
      </div>)}
      <button type="button" className="quiet-action" onClick={() => setLines((current) => [...current, { product_id: '', location_id: '', quantity: '', reservation_line_id: '' }])}>Add material</button>
      <label>Reason<input name="reason" minLength={3} maxLength={500} placeholder="Materials used for this job" required /></label>
      {error && <div className="alert inline-alert">{error}</div>}
      <div className="purchasing-actions"><button type="submit" name="action" value="reserve" className="quiet-action" disabled={saving || !products.some((product) => product.is_active) || !locations.some((location) => location.is_active)}>Reserve for job</button><button type="submit" name="action" value="issue" className="primary" disabled={saving || !products.some((product) => product.is_active) || !locations.some((location) => location.is_active)}>Record materials</button></div>
      <p className="form-note">Reservations reduce available stock without changing on-hand quantity. Recording use creates an inventory issue; unused quantities need explicit release.</p>
    </form>}
  </section>
}
