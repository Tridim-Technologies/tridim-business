import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './Purchasing.css'

type Supplier = { id: number; code: string; name: string; is_active: boolean }
type Product = { id: number; sku: string; name: string; base_unit: string; is_active: boolean }
type Location = { id: number; code: string; name: string; is_active: boolean }
type OrderLine = {
  id: number
  product_id: number
  product_sku: string
  product_name: string
  base_unit: string
  ordered_quantity: string
  received_quantity: string
  remaining_quantity: string
}
type ReceiptLine = { order_line_id: number; product_sku: string; product_name: string; quantity: string; movement_id: number }
type Receipt = {
  id: number
  purchase_order_id: number
  location_id: number
  location_code: string
  actor: string
  created_at: string
  lines: ReceiptLine[]
}
type Order = {
  id: number
  reference: string
  supplier_id: number
  supplier_code: string
  supplier_name: string
  status: 'draft' | 'issued' | 'partially_received' | 'received' | 'cancelled'
  note: string
  created_by: string
  created_at: string
  updated_at: string
  issued_by: string | null
  issued_at: string | null
  cancelled_by: string | null
  cancelled_at: string | null
  lines: OrderLine[]
  receipts: Receipt[]
}
type PurchasingData = { suppliers: Supplier[]; orders: Order[]; locations: Location[]; products: Product[] }
type DraftLine = { product_id: string; quantity: string }

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...init.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const fieldError = Object.values(body).find((value) => Array.isArray(value)) as string[] | undefined
    throw new Error(body.detail || fieldError?.[0] || `Request failed (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function csrfHeader(): Record<string, string> {
  const token = document.cookie.split('; ').find((part) => part.startsWith('csrftoken='))?.split('=').slice(1).join('=')
  return token ? { 'X-CSRFToken': decodeURIComponent(token) } : {}
}

function OrderForm({
  suppliers,
  products,
  saving,
  initial,
  onSave,
}: {
  suppliers: Supplier[]
  products: Product[]
  saving: boolean
  initial?: Order
  onSave: (payload: { supplier_id: number; note: string; lines: { product_id: number; ordered_quantity: string }[] }) => Promise<void>
}) {
  const [supplierId, setSupplierId] = useState(String(initial?.supplier_id || ''))
  const [note, setNote] = useState(initial?.note || '')
  const [lines, setLines] = useState<DraftLine[]>(initial?.lines.map((line) => ({ product_id: String(line.product_id), quantity: line.ordered_quantity })) || [{ product_id: '', quantity: '' }])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    try {
      await onSave({
        supplier_id: Number(supplierId),
        note,
        lines: lines.filter((line) => line.product_id && line.quantity).map((line) => ({ product_id: Number(line.product_id), ordered_quantity: line.quantity })),
      })
      if (!initial) {
        setSupplierId('')
        setNote('')
        setLines([{ product_id: '', quantity: '' }])
      }
    } catch {
      // The parent keeps the failure visible and leaves this form ready to retry.
    }
  }

  function updateLine(index: number, field: keyof DraftLine, value: string) {
    setLines((current) => current.map((line, lineIndex) => lineIndex === index ? { ...line, [field]: value } : line))
  }

  return <form className="stack-form purchasing-order-form" onSubmit={(event) => void submit(event)}>
    <label>Supplier<select required value={supplierId} onChange={(event) => setSupplierId(event.target.value)}><option value="" disabled>Select supplier</option>{suppliers.filter((supplier) => supplier.is_active || supplier.id === Number(supplierId)).map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.code} · {supplier.name}{!supplier.is_active ? ' · inactive' : ''}</option>)}</select></label>
    <div className="purchasing-lines"><strong>Products and requested quantities</strong>{lines.map((line, index) => <div className="purchasing-line-input" key={index}>
      <label>Product<select required value={line.product_id} onChange={(event) => updateLine(index, 'product_id', event.target.value)}><option value="" disabled>Select product</option>{products.filter((product) => product.is_active || product.id === Number(line.product_id)).map((product) => <option key={product.id} value={product.id} disabled={lines.some((other, lineIndex) => lineIndex !== index && other.product_id === String(product.id))}>{product.sku} · {product.name}{!product.is_active ? ' · inactive' : ''}</option>)}</select></label>
      <label>Quantity ({products.find((product) => product.id === Number(line.product_id))?.base_unit || 'unit'})<input type="number" min="0.001" step="0.001" required value={line.quantity} onChange={(event) => updateLine(index, 'quantity', event.target.value)} /></label>
      {lines.length > 1 && <button type="button" className="quiet-action" aria-label="Remove product line" onClick={() => setLines((current) => current.filter((_, lineIndex) => lineIndex !== index))}>Remove</button>}
    </div>)}<button type="button" className="quiet-action" onClick={() => setLines((current) => [...current, { product_id: '', quantity: '' }])}>Add product line</button></div>
    <label>Note (optional)<textarea maxLength={500} value={note} onChange={(event) => setNote(event.target.value)} rows={2} /></label>
    <button className="primary" disabled={saving}>{initial ? 'Save draft' : 'Create draft'} <span>＋</span></button>
  </form>
}

export default function Purchasing({ organization, canManage }: { organization: string; canManage: boolean }) {
  const [data, setData] = useState<PurchasingData>({ suppliers: [], orders: [], locations: [], products: [] })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const receiptKeys = useRef(new Map<string, string>())
  const base = `/api/organizations/${organization}/purchasing/`

  const refresh = useCallback(async () => {
    if (!organization) return
    setData(await api<PurchasingData>(base))
    setError('')
  }, [base, organization])

  useEffect(() => { refresh().catch((reason: Error) => setError(reason.message)) }, [refresh])

  async function createSupplier(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setSaving(true); setError('')
    try {
      await api(`${base}suppliers/`, { method: 'POST', headers: csrfHeader(), body: JSON.stringify({ code: values.get('code'), name: values.get('name') }) })
      form.reset(); await refresh()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function updateSupplier(event: FormEvent<HTMLFormElement>, supplier: Supplier) {
    event.preventDefault()
    const values = new FormData(event.currentTarget)
    setSaving(true); setError('')
    try {
      await api(`${base}suppliers/${supplier.id}/`, { method: 'PATCH', headers: csrfHeader(), body: JSON.stringify({ code: values.get('code'), name: values.get('name'), is_active: values.get('is_active') === 'on' }) })
      await refresh()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function saveOrder(payload: { supplier_id: number; note: string; lines: { product_id: number; ordered_quantity: string }[] }, order?: Order) {
    setSaving(true); setError('')
    try {
      await api(order ? `${base}orders/${order.id}/` : `${base}orders/`, { method: order ? 'PATCH' : 'POST', headers: csrfHeader(), body: JSON.stringify(payload) })
      await refresh()
    } catch (reason) { setError((reason as Error).message); throw reason } finally { setSaving(false) }
  }

  async function transition(order: Order, action: 'issue' | 'cancel') {
    if (action === 'cancel' && !window.confirm(`Cancel the remaining quantity on ${order.reference}? Received stock will remain in inventory.`)) return
    setSaving(true); setError('')
    try { await api(`${base}orders/${order.id}/${action}/`, { method: 'POST', headers: csrfHeader(), body: '{}' }); await refresh() }
    catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function deleteOrder(order: Order) {
    if (!window.confirm(`Delete draft ${order.reference}?`)) return
    setSaving(true); setError('')
    try { await api(`${base}orders/${order.id}/`, { method: 'DELETE', headers: csrfHeader() }); await refresh() }
    catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function receiveOrder(event: FormEvent<HTMLFormElement>, order: Order) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    const lines = order.lines.map((line) => ({ order_line_id: line.id, quantity: String(values.get(`quantity-${line.id}`) || '') })).filter((line) => line.quantity !== '')
    if (lines.length === 0) { setError('Enter at least one quantity to receive.'); return }
    const payload = { location_id: Number(values.get('location_id')), lines }
    const serialized = JSON.stringify({ order_id: order.id, ...payload })
    const idempotencyKey = receiptKeys.current.get(serialized) || crypto.randomUUID()
    receiptKeys.current.set(serialized, idempotencyKey)
    setSaving(true); setError('')
    try {
      await api(`${base}orders/${order.id}/receipts/`, { method: 'POST', headers: csrfHeader(), body: JSON.stringify({ ...payload, idempotency_key: idempotencyKey }) })
      receiptKeys.current.delete(serialized); form.reset(); await refresh()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  return <>
    <div className="page-heading"><div><p className="eyebrow">OPERATIONS</p><h1>Purchasing</h1><p className="muted">Track supplier orders and receive quantities into stock locations.</p></div><span className="count-pill">{data.orders.length} {data.orders.length === 1 ? 'order' : 'orders'}</span></div>
    {error && <div className="alert inline-alert">{error}</div>}
    <p className="expense-notice">Quantity-only purchasing. Orders and receipts do not capture prices, currency, tax, payables, payments, or accounting entries.</p>
    {canManage && <div className="purchasing-setup-grid">
      <section className="panel add-panel"><div className="panel-heading"><div><h2>Add a supplier</h2><p>Use a business code and name. Contact details are not collected.</p></div></div>
        <form className="stack-form" onSubmit={(event) => void createSupplier(event)}><label>Supplier code<input name="code" maxLength={32} pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,31}" required /></label><label>Supplier name<input name="name" minLength={2} maxLength={160} required /></label><button className="primary" disabled={saving}>Add supplier <span>＋</span></button></form>
        <div className="purchasing-supplier-list">{data.suppliers.map((supplier) => <details key={supplier.id}><summary>{supplier.code} · {supplier.name}{!supplier.is_active ? ' · inactive' : ''}</summary><form className="stack-form" onSubmit={(event) => void updateSupplier(event, supplier)}><label>Code<input name="code" defaultValue={supplier.code} maxLength={32} required /></label><label>Name<input name="name" defaultValue={supplier.name} maxLength={160} required /></label><label className="inventory-checkbox"><input type="checkbox" name="is_active" defaultChecked={supplier.is_active} /> Active</label><button className="quiet-action" disabled={saving}>Save supplier</button></form></details>)}</div>
      </section>
      <section className="panel add-panel"><div className="panel-heading"><div><h2>Create a supplier order</h2><p>Drafts can be edited or removed. Issue an order to start receiving.</p></div></div>
        {data.suppliers.some((supplier) => supplier.is_active) && data.products.some((product) => product.is_active) ? <OrderForm suppliers={data.suppliers} products={data.products} saving={saving} onSave={(payload) => saveOrder(payload)} /> : <div className="empty-state"><strong>Add an active supplier and product first</strong></div>}
      </section>
    </div>}
    <section className="purchasing-order-list">
      {data.orders.length ? data.orders.map((order) => <article className="panel purchasing-order-card" key={order.id}>
        <div className="purchasing-order-heading"><div><p className="eyebrow">{order.reference}</p><h2>{order.supplier_code} · {order.supplier_name}</h2><p className="muted">Created by {order.created_by} · {new Date(order.created_at).toLocaleString()}</p></div><span className={`purchasing-status status-${order.status}`}>{order.status.replaceAll('_', ' ')}</span></div>
        {order.note && <p>{order.note}</p>}
        <div className="table-scroll"><table><thead><tr><th>SKU</th><th>Product</th><th>Ordered</th><th>Received</th><th>Remaining</th></tr></thead><tbody>{order.lines.map((line) => <tr key={line.id}><td>{line.product_sku}</td><td>{line.product_name} ({line.base_unit})</td><td>{line.ordered_quantity}</td><td>{line.received_quantity}</td><td>{line.remaining_quantity}</td></tr>)}</tbody></table></div>
        {canManage && order.status === 'draft' && <div className="purchasing-actions"><details><summary>Edit draft</summary><OrderForm key={`edit-${order.id}-${order.updated_at}`} suppliers={data.suppliers} products={data.products} saving={saving} initial={order} onSave={(payload) => saveOrder(payload, order)} /></details><button className="quiet-action" disabled={saving} onClick={() => void transition(order, 'issue')}>Issue order</button><button className="quiet-action" disabled={saving} onClick={() => void deleteOrder(order)}>Delete draft</button></div>}
        {canManage && ['issued', 'partially_received'].includes(order.status) && <div className="purchasing-receive-grid"><form className="stack-form purchasing-receive-form" onSubmit={(event) => void receiveOrder(event, order)}><h3>Receive quantities</h3><label>Stock location<select name="location_id" required defaultValue=""><option value="" disabled>Select location</option>{data.locations.filter((location) => location.is_active).map((location) => <option key={location.id} value={location.id}>{location.code} · {location.name}</option>)}</select></label>{order.lines.filter((line) => Number(line.remaining_quantity) > 0).map((line) => <label key={line.id}>{line.product_sku} · remaining {line.remaining_quantity} {line.base_unit}<input name={`quantity-${line.id}`} type="number" min="0.001" max={line.remaining_quantity} step="0.001" /></label>)}<button className="primary" disabled={saving}>Record receipt <span>＋</span></button></form><button className="quiet-action align-start" disabled={saving} onClick={() => void transition(order, 'cancel')}>Cancel remaining order</button></div>}
        {order.status === 'cancelled' && <p className="muted">Cancelled {order.cancelled_at ? new Date(order.cancelled_at).toLocaleString() : ''}. Previously received quantities remain in stock history.</p>}
        {order.receipts.length > 0 && <details className="purchasing-receipt-history"><summary>Receipt history ({order.receipts.length})</summary>{order.receipts.map((receipt) => <div className="purchasing-receipt-row" key={receipt.id}><strong>{receipt.location_code} · {new Date(receipt.created_at).toLocaleString()}</strong><span>{receipt.lines.map((line) => `${line.product_sku}: ${line.quantity}`).join(' · ')}</span></div>)}</details>}
      </article>) : <div className="panel empty-state"><strong>No supplier orders yet</strong><p>Add a supplier and create a draft order to begin.</p></div>}
    </section>
  </>
}
