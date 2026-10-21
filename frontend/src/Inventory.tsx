import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './Inventory.css'

type Product = {
  id: number
  sku: string
  name: string
  base_unit: string
  reorder_point: string
  on_hand_quantity: string
  is_active: boolean
  balances: { location_id: number; location_code: string; quantity: string }[]
}
type Location = { id: number; code: string; name: string; is_active: boolean }
type Movement = {
  id: number
  product_id: number
  product_sku: string
  product_name: string
  kind: 'receipt' | 'issue' | 'adjustment' | 'transfer'
  location_id: number
  location_code: string
  destination_id: number | null
  destination_code: string | null
  supplier_order_reference: string | null
  job_id: number | null
  direction: 'increase' | 'decrease' | ''
  quantity: string
  reason: string
  actor: string
  created_at: string
}
type InventoryData = { products: Product[]; locations: Location[]; movements: Movement[] }

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...init.headers,
    },
  })
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

function milliunits(value: string): bigint {
  const [whole, fraction = ''] = value.split('.')
  return BigInt(whole || '0') * 1000n + BigInt((fraction + '000').slice(0, 3))
}

export default function Inventory({ organization, canManage, onOpenPurchasing }: { organization: string; canManage: boolean; onOpenPurchasing: () => void }) {
  const [data, setData] = useState<InventoryData>({ products: [], locations: [], movements: [] })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const movementKeys = useRef(new Map<string, string>())
  const base = `/api/organizations/${organization}/inventory/`

  const refresh = useCallback(async () => {
    if (!organization) return
    const next = await api<InventoryData>(base)
    setData(next)
    setError('')
  }, [base, organization])

  useEffect(() => {
    refresh().catch((reason: Error) => setError(reason.message))
  }, [refresh])

  async function createProduct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    setSaving(true); setError('')
    try {
      await api(`${base}products/`, {
        method: 'POST', headers: csrfHeader(),
        body: JSON.stringify({ sku: form.get('sku'), name: form.get('name'), base_unit: form.get('base_unit'), reorder_point: String(form.get('reorder_point') || '0.000') }),
      })
      formElement.reset(); await refresh()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function updateProduct(event: FormEvent<HTMLFormElement>, product: Product) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setSaving(true); setError('')
    try {
      await api(`${base}products/${product.id}/`, {
        method: 'PATCH', headers: csrfHeader(),
        body: JSON.stringify({ sku: form.get('sku'), name: form.get('name'), base_unit: form.get('base_unit'), reorder_point: String(form.get('reorder_point') || '0.000'), is_active: form.get('is_active') === 'on' }),
      })
      await refresh()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function createLocation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    setSaving(true); setError('')
    try {
      await api(`${base}locations/`, {
        method: 'POST', headers: csrfHeader(),
        body: JSON.stringify({ code: form.get('code'), name: form.get('name') }),
      })
      formElement.reset(); await refresh()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function updateLocation(event: FormEvent<HTMLFormElement>, location: Location) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setSaving(true); setError('')
    try {
      await api(`${base}locations/${location.id}/`, {
        method: 'PATCH', headers: csrfHeader(),
        body: JSON.stringify({ code: form.get('code'), name: form.get('name'), is_active: form.get('is_active') === 'on' }),
      })
      await refresh()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function createMovement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    const kind = String(form.get('kind'))
    const payload: Record<string, string | number> = {
      product_id: Number(form.get('product_id')),
      location_id: Number(form.get('location_id')),
      kind,
      quantity: String(form.get('quantity')),
      reason: String(form.get('reason')),
    }
    if (kind === 'transfer') payload.destination_id = Number(form.get('destination_id'))
    if (kind === 'adjustment') payload.direction = String(form.get('direction'))
    const serialized = JSON.stringify(payload)
    const requestKey = movementKeys.current.get(serialized) || crypto.randomUUID()
    movementKeys.current.set(serialized, requestKey)
    payload.idempotency_key = requestKey
    setSaving(true); setError('')
    try {
      await api(`${base}movements/`, {
        method: 'POST', headers: csrfHeader(), body: JSON.stringify(payload),
      })
      formElement.reset()
      formElement.dataset.kind = 'receipt'
      movementKeys.current.delete(serialized)
      await refresh()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  const selectedKind = (event: FormEvent<HTMLFormElement>) => {
    const form = event.currentTarget
    const kind = String(new FormData(form).get('kind'))
    form.dataset.kind = kind
  }

  const lowStockProducts = data.products.filter((product) =>
    product.is_active && milliunits(product.reorder_point) > 0n &&
    milliunits(product.on_hand_quantity) < milliunits(product.reorder_point),
  )

  return <>
    <div className="page-heading"><div><p className="eyebrow">OPERATIONS</p><h1>Inventory</h1><p className="muted">Track product quantities across locations through recorded stock movements.</p></div><span className="count-pill">{data.products.length} {data.products.length === 1 ? 'product' : 'products'}</span></div>
    {error && <div className="alert inline-alert">{error}</div>}
    <p className="expense-notice">Synthetic product and quantity tracking only. Stock movements do not calculate value, taxes, accounting entries, or sales orders.</p>
    {canManage && <div className="inventory-setup-grid">
      <section className="panel add-panel"><div className="panel-heading"><div><h2>Add a product</h2><p>SKU is unique within this organization. Price and tax are not captured.</p></div></div>
        <form className="stack-form" onSubmit={createProduct}><label>SKU<input name="sku" maxLength={64} pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,63}" required /></label><label>Product name<input name="name" minLength={2} maxLength={160} required /></label><label>Base unit<input name="base_unit" placeholder="ea, kg, l" maxLength={16} pattern="[A-Za-z0-9._-]{1,16}" required /></label><label>Reorder point<input name="reorder_point" type="number" min="0" step="0.001" defaultValue="0.000" required /><span className="form-note">Total on-hand level that triggers a reorder suggestion. Zero disables it.</span></label><button className="primary" disabled={saving}>Add product <span>＋</span></button></form>
      </section>
      <section className="panel add-panel"><div className="panel-heading"><div><h2>Add a location</h2><p>Create a store, warehouse, or other stock point.</p></div></div>
        <form className="stack-form" onSubmit={createLocation}><label>Location code<input name="code" maxLength={32} pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,31}" required /></label><label>Location name<input name="name" minLength={2} maxLength={120} required /></label><button className="primary" disabled={saving}>Add location <span>＋</span></button></form>
        {data.locations.length > 0 && <div className="inventory-location-list">{data.locations.map((location) => <details key={location.id}><summary>{location.code} · {location.name} · {location.is_active ? 'active' : 'inactive'}</summary><form className="stack-form" onSubmit={(event) => updateLocation(event, location)}><label>Code<input name="code" defaultValue={location.code} maxLength={32} required /></label><label>Name<input name="name" defaultValue={location.name} maxLength={120} required /></label><label className="inventory-checkbox"><input type="checkbox" name="is_active" defaultChecked={location.is_active} /> Active</label><button className="quiet-action" disabled={saving}>Save location</button></form></details>)}</div>}
      </section>
    </div>}
    <section className="panel inventory-register"><div className="panel-heading"><div><h2>On-hand quantities</h2><p>Balances are derived from the append-only movement history. Reorder points apply to total stock across locations.</p></div></div>
      {data.products.length && data.locations.length ? <div className="table-scroll"><table><thead><tr><th>SKU</th><th>Product</th><th>Total on hand</th><th>Reorder point</th>{data.locations.map((location) => <th key={location.id}>{location.code} · {location.name}</th>)}{canManage && <th>Actions</th>}</tr></thead><tbody>{data.products.map((product) => <tr key={product.id}><td>{product.sku}</td><td>{product.name} <span className="quote-id">({product.base_unit}){!product.is_active ? ' · inactive' : ''}</span></td><td>{product.on_hand_quantity}</td><td>{product.reorder_point === '0.000' ? 'Not tracked' : product.reorder_point}</td>{data.locations.map((location) => <td key={location.id}>{product.balances.find((balance) => balance.location_id === location.id)?.quantity || '0.000'}</td>)}{canManage && <td><details><summary>Edit</summary><form className="stack-form" onSubmit={(event) => updateProduct(event, product)}><label>SKU<input name="sku" defaultValue={product.sku} maxLength={64} required /></label><label>Name<input name="name" defaultValue={product.name} maxLength={160} required /></label><label>Base unit<input name="base_unit" defaultValue={product.base_unit} maxLength={16} required /></label><label>Reorder point<input name="reorder_point" type="number" min="0" step="0.001" defaultValue={product.reorder_point} required /></label><label className="inventory-checkbox"><input type="checkbox" name="is_active" defaultChecked={product.is_active} /> Active</label><button className="quiet-action" disabled={saving}>Save product</button></form></details></td>}</tr>)}</tbody></table></div> : <div className="empty-state"><strong>{data.products.length ? 'Add a location to see stock by location' : 'Add a product to start tracking stock'}</strong><p>Every quantity change is recorded in the movement history.</p></div>}
    </section>
    {data.products.some((product) => milliunits(product.reorder_point) > 0n) && <section className="panel inventory-register"><div className="panel-heading"><div><h2>Below reorder point</h2><p>Products below their total on-hand threshold. Purchasing suggestions also account for incoming order quantities.</p></div>{canManage && <button className="quiet-action" onClick={onOpenPurchasing}>Review reorder suggestions</button>}</div>
      {lowStockProducts.length ? <div className="table-scroll"><table><thead><tr><th>SKU</th><th>Product</th><th>Total on hand</th><th>Reorder point</th></tr></thead><tbody>{lowStockProducts.map((product) => <tr key={product.id}><td>{product.sku}</td><td>{product.name} ({product.base_unit})</td><td>{product.on_hand_quantity}</td><td>{product.reorder_point}</td></tr>)}</tbody></table></div> : <div className="empty-state"><strong>All tracked products are at or above their reorder points</strong></div>}
    </section>}
    {canManage && data.products.length > 0 && data.locations.length > 0 && <section className="panel add-panel"><div className="panel-heading"><div><h2>Record a movement</h2><p>Every movement requires a reason. Issues and transfers cannot overdraw stock.</p></div></div>
      <form className="inventory-movement-form" data-kind="receipt" onSubmit={createMovement} onChange={selectedKind}>
        <label>Product<select name="product_id" required defaultValue=""><option value="" disabled>Select product</option>{data.products.filter((product) => product.is_active).map((product) => <option key={product.id} value={product.id}>{product.sku} · {product.name}</option>)}</select></label>
        <label>Movement<select name="kind" required defaultValue="receipt"><option value="receipt">Receive stock</option><option value="issue">Issue stock</option><option value="adjustment">Adjust counted stock</option><option value="transfer">Transfer between locations</option></select></label>
        <label>Location<select name="location_id" required defaultValue=""><option value="" disabled>Select location</option>{data.locations.filter((location) => location.is_active).map((location) => <option key={location.id} value={location.id}>{location.code} · {location.name}</option>)}</select></label>
        <label className="movement-destination">Destination<select name="destination_id" defaultValue=""><option value="" disabled>Select destination</option>{data.locations.filter((location) => location.is_active).map((location) => <option key={location.id} value={location.id}>{location.code} · {location.name}</option>)}</select></label>
        <label className="movement-direction">Adjustment<select name="direction" defaultValue="increase"><option value="increase">Increase</option><option value="decrease">Decrease</option></select></label>
        <label>Quantity<input name="quantity" type="number" min="0.001" step="0.001" required /></label>
        <label className="movement-reason">Reason<input name="reason" minLength={3} maxLength={500} required /></label>
        <button className="primary" disabled={saving}>Record movement <span>＋</span></button>
      </form>
    </section>}
    <section className="panel inventory-register"><div className="panel-heading"><div><h2>Recent movements</h2><p>Most recent 100 movements, newest first. Records cannot be edited or deleted.</p></div></div>
      {data.movements.length ? <div className="expense-list">{data.movements.map((movement) => <article className="expense-card" key={movement.id}><div className="invoice-top"><div><strong>{movement.kind.replace('_', ' ')} · {movement.product_sku}</strong><span className="quote-id">{movement.supplier_order_reference ? `${movement.supplier_order_reference} · ` : movement.job_id ? `Job #${movement.job_id} · ` : ''}{movement.location_code}{movement.destination_code ? ` → ${movement.destination_code}` : ''} · {movement.quantity} · {movement.actor} · {new Date(movement.created_at).toLocaleString()}</span></div></div><p>{movement.reason}{movement.kind === 'adjustment' ? ` · ${movement.direction}` : ''}</p></article>)}</div> : <div className="empty-state"><strong>No stock movements yet</strong><p>Receive or adjust stock to establish the first on-hand quantity.</p></div>}
    </section>
  </>
}
