import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'

type Organization = { id: string; name: string; role: string }
type Customer = { id: number; name: string; contact_name: string; email: string; phone: string; status: 'active' | 'archived'; status_history: { previous_status: string; status: string; actor: string; created_at: string }[] }
type Quote = {
  id: string; series_id: string; revision_number: number; supersedes_id: string | null; is_current: boolean
  customer: number; customer_name: string; currency: string; valid_until: string; status: string
  lines: { id: number; description: string; quantity: string; unit_price: string }[]
  status_history: { status: string; actor: string; created_at: string }[]; job_id: number | null
}
type Job = {
  id: number; customer: number; customer_name: string; source_quotation_id: string; status: string; due_date: string | null
  status_history: { previous_status: string; status: string; actor: string; created_at: string; note: string }[]
  due_date_history: { previous_due_date: string | null; due_date: string | null; actor: string; created_at: string }[]
  assignments: { id: number; user: string; assigned_by: string; assigned_at: string; unassigned_by: string | null; unassigned_at: string | null }[]
  notes: { id: number; author: string; content: string; created_at: string }[]; created_at: string
}
type Invoice = {
  id: string; invoice_number: string; job_id: number; customer_name: string; source_quotation_id: string
  status: 'issued' | 'void'; issue_date: string; due_date: string; currency: string; total: string
  issued_by: string; issued_at: string; correction_reason: string; void_reason: string; voided_by: string | null; voided_at: string | null
  replaces_invoice_number: string | null
  lines: { description: string; quantity: string; unit_price: string; line_total: string; position: number }[]
}
type Session = { authenticated: boolean; user?: { id: number; username: string }; organizations?: Organization[] }

function dateInputValue(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function latestVoidedInvoice(invoices: Invoice[], jobId: number): Invoice | undefined {
  return invoices
    .filter((invoice) => invoice.job_id === jobId && invoice.status === 'void')
    .sort((left, right) => right.issued_at.localeCompare(left.issued_at) || right.invoice_number.localeCompare(left.invoice_number))[0]
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

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [organization, setOrganization] = useState('')
  const [customers, setCustomers] = useState<Customer[]>([])
  const [quotations, setQuotations] = useState<Quote[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [customerStatus, setCustomerStatus] = useState<'active' | 'archived' | 'all'>('active')
  const [customerSearch, setCustomerSearch] = useState('')
  const [editingCustomer, setEditingCustomer] = useState<Customer | null>(null)
  const [editingQuote, setEditingQuote] = useState<Quote | null>(null)
  const [quoteLines, setQuoteLines] = useState([{ description: '', quantity: '1', unit_price: '' }])
  const [page, setPage] = useState<'customers' | 'quotations' | 'jobs' | 'invoices'>('customers')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function refreshSession() {
    await api('/api/csrf/')
    const current = await api<Session>('/api/session/').catch((): Session => ({ authenticated: false }))
    setSession(current)
    if (current.organizations?.length) setOrganization((selected) => selected || current.organizations![0].id)
  }

  const activeOrg = session?.organizations?.find((item) => item.id === organization)
  const canViewInvoices = ['owner', 'admin', 'finance'].includes(activeOrg?.role || '')

  const refreshData = useCallback(async () => {
    if (!organization) return
    const [customerData, quoteData, jobData, invoiceData] = await Promise.all([
      api<{ results: Customer[] }>(`/api/organizations/${organization}/customers/?status=${customerStatus}&search=${encodeURIComponent(customerSearch)}`),
      api<{ results: Quote[] }>(`/api/organizations/${organization}/quotations/`),
      api<{ results: Job[] }>(`/api/organizations/${organization}/jobs/`),
      canViewInvoices ? api<{ results: Invoice[] }>(`/api/organizations/${organization}/invoices/`) : Promise.resolve({ results: [] as Invoice[] }),
    ])
    setCustomers(customerData.results); setQuotations(quoteData.results); setJobs(jobData.results); setInvoices(invoiceData.results); setError('')
  }, [organization, customerStatus, customerSearch, canViewInvoices])

  useEffect(() => { refreshSession().catch((reason: Error) => setError(reason.message)).finally(() => setLoading(false)) }, [])
  useEffect(() => {
    if (!session?.authenticated || !organization) { setCustomers([]); setQuotations([]); setJobs([]); setInvoices([]); return }
    refreshData().catch((reason: Error) => setError(reason.message))
  }, [session, organization, refreshData])

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError('')
    const form = new FormData(event.currentTarget)
    try {
      const result = await api<Session>('/api/session/', { method: 'POST', headers: csrfHeader(), body: JSON.stringify({ username: form.get('username'), password: form.get('password') }) })
      setSession(result); setOrganization(result.organizations?.[0]?.id || '')
    } catch (reason) { setError((reason as Error).message) }
  }

  async function addCustomer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setSaving(true)
    const formElement = event.currentTarget; const form = new FormData(event.currentTarget)
    try {
      await api(`/api/organizations/${organization}/customers/`, { method: 'POST', headers: csrfHeader(), body: JSON.stringify({ name: form.get('name'), contact_name: form.get('contact_name'), email: form.get('email'), phone: form.get('phone') }) })
      formElement.reset(); await refreshData()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function addQuotation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setSaving(true)
    const formElement = event.currentTarget; const form = new FormData(event.currentTarget)
    try {
      const payload = {
        customer_id: Number(form.get('customer_id')), currency: form.get('currency'), valid_until: form.get('valid_until'),
        lines: quoteLines,
      }
      const path = editingQuote
        ? `/api/organizations/${organization}/quotations/${editingQuote.id}/revise/`
        : `/api/organizations/${organization}/quotations/`
      await api(path, { method: 'POST', headers: csrfHeader(), body: JSON.stringify(payload) })
      formElement.reset(); setEditingQuote(null); setQuoteLines([{ description: '', quantity: '1', unit_price: '' }]); await refreshData()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  function startRevision(quote: Quote) {
    setEditingQuote(quote)
    setQuoteLines(quote.lines.map(({ description, quantity, unit_price }) => ({ description, quantity, unit_price })))
  }

  function changeQuoteLine(index: number, key: 'description' | 'quantity' | 'unit_price', value: string) {
    setQuoteLines((lines) => lines.map((line, lineIndex) => lineIndex === index ? { ...line, [key]: value } : line))
  }

  async function toggleCustomer(customer: Customer) {
    setError(''); setSaving(true)
    try {
      await api(`/api/organizations/${organization}/customers/${customer.id}/`, {
        method: 'POST', headers: csrfHeader(),
        body: JSON.stringify({ action: customer.status === 'active' ? 'archive' : 'restore' }),
      })
      await refreshData()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function updateJob(job: Job, updates: { status?: string; due_date?: string | null }) {
    setError(''); setSaving(true)
    try {
      await api(`/api/organizations/${organization}/jobs/${job.id}/`, { method: 'PATCH', headers: csrfHeader(), body: JSON.stringify(updates) })
      await refreshData()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function addJobAssignment(event: FormEvent<HTMLFormElement>, job: Job) {
    event.preventDefault(); setError(''); setSaving(true)
    const formElement = event.currentTarget; const form = new FormData(formElement)
    try {
      await api(`/api/organizations/${organization}/jobs/${job.id}/assignments/`, { method: 'POST', headers: csrfHeader(), body: JSON.stringify({ username: form.get('username') }) })
      formElement.reset(); await refreshData()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function removeJobAssignment(job: Job, assignmentId: number) {
    setError(''); setSaving(true)
    try {
      await api(`/api/organizations/${organization}/jobs/${job.id}/assignments/${assignmentId}/remove/`, { method: 'POST', headers: csrfHeader(), body: JSON.stringify({}) })
      await refreshData()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function addJobNote(event: FormEvent<HTMLFormElement>, job: Job) {
    event.preventDefault(); setError(''); setSaving(true)
    const formElement = event.currentTarget; const form = new FormData(formElement)
    try {
      await api(`/api/organizations/${organization}/jobs/${job.id}/notes/`, { method: 'POST', headers: csrfHeader(), body: JSON.stringify({ content: form.get('content') }) })
      formElement.reset(); await refreshData()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function issueInvoice(event: FormEvent<HTMLFormElement>, job: Job) {
    event.preventDefault(); setError(''); setSaving(true)
    const formElement = event.currentTarget; const form = new FormData(formElement)
    try {
      const previousInvoice = latestVoidedInvoice(invoices, job.id)
      const payload: { due_date: string; correction_reason?: string; lines?: { position: number; quantity: string; unit_price: string }[] } = { due_date: String(form.get('due_date')) }
      if (previousInvoice) {
        payload.correction_reason = String(form.get('correction_reason'))
        payload.lines = previousInvoice.lines.map((line) => ({
          position: line.position,
          quantity: String(form.get(`quantity-${line.position}`)),
          unit_price: String(form.get(`unit-price-${line.position}`)),
        }))
      }
      await api(`/api/organizations/${organization}/jobs/${job.id}/invoice/`, { method: 'POST', headers: csrfHeader(), body: JSON.stringify(payload) })
      await refreshData()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function voidInvoice(event: FormEvent<HTMLFormElement>, invoice: Invoice) {
    event.preventDefault(); setError(''); setSaving(true)
    const formElement = event.currentTarget; const form = new FormData(formElement)
    try {
      await api(`/api/organizations/${organization}/invoices/${invoice.id}/void/`, { method: 'POST', headers: csrfHeader(), body: JSON.stringify({ reason: form.get('reason') }) })
      formElement.reset(); await refreshData()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function updateCustomer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!editingCustomer) return
    setError(''); setSaving(true)
    const form = new FormData(event.currentTarget)
    try {
      await api(`/api/organizations/${organization}/customers/${editingCustomer.id}/`, {
        method: 'PATCH', headers: csrfHeader(),
        body: JSON.stringify({ name: form.get('name'), contact_name: form.get('contact_name'), email: form.get('email'), phone: form.get('phone') }),
      })
      setEditingCustomer(null); await refreshData()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function transition(quote: Quote, action: 'send' | 'accept' | 'reject' | 'withdraw') {
    setError(''); setSaving(true)
    try {
      await api(`/api/organizations/${organization}/quotations/${quote.id}/transition/`, { method: 'POST', headers: csrfHeader(), body: JSON.stringify({ action }) })
      await refreshData()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function signOut() {
    await api('/api/session/', { method: 'DELETE', headers: csrfHeader() })
    setSession({ authenticated: false }); setCustomers([]); setQuotations([]); setJobs([]); setInvoices([])
  }

  if (loading) return <main className="loading">Loading your workspace…</main>
  if (!session?.authenticated) return <main className="login-shell"><section className="login-card">
    <div className="brand-mark">T</div><p className="eyebrow">TRIDIM BUSINESS</p><h1>One clear view of your work.</h1>
    <p className="muted">Sign in to manage your organization’s customers and quotations.</p>{error && <div className="alert">{error}</div>}
    <form onSubmit={signIn} className="stack-form"><label>Username<input name="username" autoComplete="username" required /></label><label>Password<input type="password" name="password" autoComplete="current-password" required /></label><button className="primary" type="submit">Sign in <span>→</span></button></form>
    <p className="footnote">Local alpha · Your organization’s data stays private to its members.</p>
  </section></main>

  const canWriteQuotes = ['owner', 'admin', 'sales'].includes(activeOrg?.role || '')
  const canAccept = ['owner', 'admin', 'operations'].includes(activeOrg?.role || '')
  const canManageCustomers = ['owner', 'admin', 'sales', 'operations'].includes(activeOrg?.role || '')
  const canManageJobs = ['owner', 'admin', 'operations'].includes(activeOrg?.role || '')
  const canWriteJobNotes = canManageJobs || activeOrg?.role === 'employee'
  const label = page === 'jobs' ? 'Jobs' : page === 'quotations' ? 'Quotations' : page === 'invoices' ? 'Invoices' : 'Customers'
  const visibleQuotes = quotations
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><div className="brand-mark">T</div><div><strong>Tridim</strong><small>BUSINESS</small></div></div>
      <div className="workspace-label">WORKSPACE</div><div className="workspace">{activeOrg?.name || 'No organization'}</div>
      <nav>
        <button className={`nav-item ${page === 'customers' ? 'active' : ''}`} onClick={() => setPage('customers')}><span className="nav-icon">◫</span> Customers</button>
        <button className={`nav-item ${page === 'quotations' ? 'active' : ''}`} onClick={() => setPage('quotations')}><span className="nav-icon">↗</span> Quotations</button>
        <button className={`nav-item ${page === 'jobs' ? 'active' : ''}`} onClick={() => setPage('jobs')}><span className="nav-icon">▦</span> Jobs</button>
        {canViewInvoices && <button className={`nav-item ${page === 'invoices' ? 'active' : ''}`} onClick={() => setPage('invoices')}><span className="nav-icon">▤</span> Invoices</button>}
      </nav>
      <div className="sidebar-bottom"><span className="avatar">{session.user?.username.slice(0, 1).toUpperCase()}</span><div className="user-label"><strong>{session.user?.username}</strong><small>{activeOrg?.role || 'Member'}</small></div><button className="icon-button" onClick={signOut} aria-label="Sign out">↗</button></div>
    </aside>
    <main className="main-area"><header className="topbar"><div><span className="breadcrumb">Workspace</span><span className="slash">/</span> {label}</div><div className="top-actions"><select aria-label="Organization" value={organization} onChange={(event) => { setOrganization(event.target.value); setCustomers([]); setQuotations([]); setJobs([]); setInvoices([]) }}>{session.organizations?.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}</select><span className="avatar small">{session.user?.username.slice(0, 1).toUpperCase()}</span></div></header>
      <div className="content">
        {page === 'customers' ? <>
          <div className="page-heading"><div><p className="eyebrow">RELATIONSHIPS</p><h1>Customers</h1><p className="muted">Keep the people and businesses you work with in one place.</p></div><span className="count-pill">{customers.length} {customers.length === 1 ? 'customer' : 'customers'}</span></div>
          {error && <div className="alert inline-alert">{error}</div>}
          <div className="content-grid"><section className="panel customer-panel"><div className="panel-heading"><div><h2>Customer directory</h2><p>Records for {activeOrg?.name || 'your organization'}</p></div></div>
            <div className="directory-tools"><input aria-label="Search customers" placeholder="Search name or contact" value={customerSearch} onChange={(event) => setCustomerSearch(event.target.value)} /><select aria-label="Customer status" value={customerStatus} onChange={(event) => setCustomerStatus(event.target.value as typeof customerStatus)}><option value="active">Active customers</option><option value="archived">Archived customers</option><option value="all">All customers</option></select></div>
            {customers.length ? <div className="customer-list">{customers.map((customer) => <article className="customer-row" key={customer.id}><span className="customer-avatar">{customer.name.slice(0, 1).toUpperCase()}</span><div className="customer-info"><strong>{customer.name}</strong><span>{customer.contact_name || customer.email || 'No contact details yet'} · {customer.status}</span>{customer.status_history.length > 0 && <details className="customer-history"><summary>Lifecycle history</summary>{customer.status_history.map((entry, index) => <span key={`${entry.status}-${index}`}>{entry.previous_status || 'created'} → {entry.status} · {entry.actor} · {new Date(entry.created_at).toLocaleString()}</span>)}</details>}</div>{canManageCustomers && <><button className="quiet-action" disabled={saving} onClick={() => setEditingCustomer(customer)}>Edit</button><button className="quiet-action" disabled={saving} onClick={() => toggleCustomer(customer)}>{customer.status === 'active' ? 'Archive' : 'Restore'}</button></>}</article>)}</div> : <div className="empty-state"><div className="empty-icon">◎</div><strong>{customerStatus === 'archived' ? 'No archived customers' : 'Your customer list starts here'}</strong><p>{customerStatus === 'archived' ? 'Archived records remain available here and keep their existing job and quotation links.' : 'Add a customer to keep their contact details ready for your next quote.'}</p></div>}
          </section>
          {canManageCustomers && <section className="panel add-panel"><div className="panel-heading"><div><h2>Add a customer</h2><p>Create a record for this workspace.</p></div></div><form className="stack-form" onSubmit={addCustomer}><label>Business or customer name <span className="required">*</span><input name="name" placeholder="e.g. Northstar Services" required /></label><label>Contact person<input name="contact_name" placeholder="Full name" /></label><label>Email address<input type="email" name="email" placeholder="name@business.com" /></label><label>Phone number<input name="phone" placeholder="+1 555 000 0000" /></label><button className="primary" disabled={saving || !organization}>{saving ? 'Saving…' : 'Add customer'} <span>＋</span></button></form></section>}</div>
          {editingCustomer && <section className="panel add-panel customer-edit-panel"><div className="panel-heading"><div><h2>Edit {editingCustomer.name}</h2><p>Update contact details for this organization.</p></div></div><form key={editingCustomer.id} className="stack-form" onSubmit={updateCustomer}><label>Business or customer name <span className="required">*</span><input name="name" defaultValue={editingCustomer.name} required /></label><label>Contact person<input name="contact_name" defaultValue={editingCustomer.contact_name} /></label><label>Email address<input type="email" name="email" defaultValue={editingCustomer.email} /></label><label>Phone number<input name="phone" defaultValue={editingCustomer.phone} /></label><button className="primary" disabled={saving}>{saving ? 'Saving…' : 'Save changes'} <span>✓</span></button><button type="button" className="quiet-action" onClick={() => setEditingCustomer(null)}>Cancel</button></form></section>}
          <p className="page-note"><span>◈</span> Customer records are visible only to members of this organization.</p>
        </> : page === 'invoices' ? <>
          <div className="page-heading"><div><p className="eyebrow">FINANCE</p><h1>Invoices</h1><p className="muted">Internal records issued from completed jobs. Payments and tax are not tracked here.</p></div><span className="count-pill">{invoices.length} {invoices.length === 1 ? 'invoice' : 'invoices'}</span></div>
          {error && <div className="alert inline-alert">{error}</div>}
          <section className="panel invoice-register"><div className="panel-heading"><div><h2>Invoice register</h2><p>Issued totals are shown in their source currency; payment allocations are not recorded.</p></div></div>
            {invoices.length ? <div className="invoice-list">{invoices.map((invoice) => <article className="invoice-card" key={invoice.id}>
              <div className="invoice-top"><div><strong>{invoice.invoice_number}</strong><span className="quote-id">{invoice.customer_name} · Job #{invoice.job_id}{invoice.replaces_invoice_number ? ` · Replaces ${invoice.replaces_invoice_number}` : ''}</span></div><span className={`quote-status ${invoice.status}`}>{invoice.status}</span></div>
              <div className="invoice-facts"><span>Issued {invoice.issue_date}</span><span>Due {invoice.due_date}</span><strong>{invoice.currency} {invoice.total}</strong></div>
              <div className="invoice-lines">{invoice.lines.map((line) => <div key={line.position}><span>{line.description} · {line.quantity} × {invoice.currency} {line.unit_price}</span><strong>{invoice.currency} {line.line_total}</strong></div>)}</div>
              {invoice.correction_reason && <p className="invoice-correction-note">Replacement reason: {invoice.correction_reason}</p>}
              {invoice.status === 'void' && <p className="invoice-void-note">Voided by {invoice.voided_by} · {invoice.voided_at ? new Date(invoice.voided_at).toLocaleString() : ''} · {invoice.void_reason}</p>}
              {invoice.status === 'issued' && <details className="invoice-void"><summary>Correct this invoice</summary><p>Voiding keeps this number and record. You can then issue a replacement from the completed job.</p><form className="job-inline-form" onSubmit={(event) => voidInvoice(event, invoice)}><input name="reason" maxLength={240} placeholder="Reason for correction" aria-label={`Reason for voiding ${invoice.invoice_number}`} required /><button className="quiet-action" disabled={saving}>Void invoice</button></form></details>}
            </article>)}</div> : <div className="empty-state"><div className="empty-icon">▤</div><strong>No invoices issued</strong><p>Complete a job, then issue an invoice from its job card.</p></div>}
          </section>
          <p className="page-note"><span>◈</span> Invoice totals copy the accepted quotation. Taxes and payments are not included.</p>
        </> : page === 'jobs' ? <>
          <div className="page-heading"><div><p className="eyebrow">DELIVERY</p><h1>Jobs</h1><p className="muted">Track delivery progress for work created from accepted quotations.</p></div><span className="count-pill">{jobs.length} {jobs.length === 1 ? 'job' : 'jobs'}</span></div>
          {error && <div className="alert inline-alert">{error}</div>}
          <section className="panel job-register"><div className="panel-heading"><div><h2>Job delivery register</h2><p>Records for {activeOrg?.name || 'your organization'}</p></div></div>
            {jobs.length ? <div className="job-list">{jobs.map((job) => {
              const activeAssignments = job.assignments.filter((assignment) => !assignment.unassigned_at)
              const activeInvoice = invoices.find((invoice) => invoice.job_id === job.id && invoice.status === 'issued')
              const voidedInvoice = latestVoidedInvoice(invoices, job.id)
              return <article className="job-card" key={job.id}>
                <div className="job-top"><div><strong>{job.customer_name}</strong><span className="quote-id">Job #{job.id} · From quote {job.source_quotation_id.slice(0, 8).toUpperCase()}</span></div><span className={`quote-status ${job.status}`}>{job.status.replace('_', ' ')}</span></div>
                <div className="job-fields">{canManageJobs ? <><label>Status<select aria-label={`Job ${job.id} status`} value={job.status} disabled={saving} onChange={(event) => updateJob(job, { status: event.target.value })}><option value="open">Open</option><option value="in_progress">In progress</option><option value="blocked">Blocked</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option></select></label><label>Due date<input aria-label={`Job ${job.id} due date`} type="date" value={job.due_date || ''} disabled={saving} onChange={(event) => updateJob(job, { due_date: event.target.value || null })} /></label></> : <div className="job-meta">Due {job.due_date || 'date not set'}</div>}</div>
                {job.status === 'completed' && canViewInvoices && (activeInvoice ? <div className="job-invoice-state"><strong>Invoice {activeInvoice.invoice_number} issued</strong><button className="quiet-action" onClick={() => setPage('invoices')}>View invoice</button></div> : <form className="job-invoice-form" onSubmit={(event) => issueInvoice(event, job)}>
                  {voidedInvoice && <><p className="form-note">This is a replacement for {voidedInvoice.invoice_number}. A reason is required; the issued lines below can be corrected.</p><label>Correction reason<input name="correction_reason" maxLength={240} required /></label>{voidedInvoice.lines.map((line) => <div className="invoice-correction-fields" key={line.position}><span>{line.description}</span><label>Quantity<input type="number" name={`quantity-${line.position}`} min="0.001" step="0.001" defaultValue={line.quantity} required /></label><label>Unit price<input type="number" name={`unit-price-${line.position}`} min="0" step="0.01" defaultValue={line.unit_price} required /></label></div>)}</>}
                  <label>Invoice due date<input type="date" name="due_date" aria-label={`Invoice due date for job ${job.id}`} min={dateInputValue(new Date())} defaultValue={dateInputValue(new Date(Date.now() + 30 * 86400000))} required /></label><button className="primary" disabled={saving}>{voidedInvoice ? 'Issue replacement invoice' : 'Issue invoice'} <span>＋</span></button>
                </form>)}
                <div className="job-assignments"><h3>Assigned team</h3>{activeAssignments.length ? activeAssignments.map((assignment) => <div className="assignment-chip" key={assignment.id}><span>{assignment.user}</span>{canManageJobs && <button className="quiet-action" disabled={saving} onClick={() => removeJobAssignment(job, assignment.id)}>Unassign</button>}</div>) : <p className="form-note">No team members assigned yet.</p>}{canManageJobs && <form className="job-inline-form" onSubmit={(event) => addJobAssignment(event, job)}><input name="username" placeholder="Organization member username" aria-label={`Assign member to job ${job.id}`} required /><button className="quiet-action" disabled={saving}>Assign</button></form>}</div>
                {(job.status_history.length > 0 || job.due_date_history.length > 0 || job.assignments.length > activeAssignments.length) && <details className="job-history"><summary>View delivery history</summary>{job.status_history.map((entry, index) => <div key={`status-${index}`}>{entry.previous_status || 'created'} → {entry.status} · {entry.actor} · {new Date(entry.created_at).toLocaleString()}{entry.note ? ` · ${entry.note}` : ''}</div>)}{job.due_date_history.map((entry, index) => <div key={`date-${index}`}>Due date {entry.previous_due_date || 'unset'} → {entry.due_date || 'unset'} · {entry.actor} · {new Date(entry.created_at).toLocaleString()}</div>)}{job.assignments.filter((assignment) => assignment.unassigned_at).map((assignment) => <div key={`assignment-${assignment.id}`}>{assignment.user} assigned by {assignment.assigned_by} · unassigned by {assignment.unassigned_by} · {new Date(assignment.unassigned_at!).toLocaleString()}</div>)}</details>}
                <div className="job-notes"><h3>Delivery notes</h3>{job.notes.map((note) => <div className="job-note" key={note.id}><p>{note.content}</p><span>{note.author} · {new Date(note.created_at).toLocaleString()}</span></div>)}{canWriteJobNotes && <form className="job-note-form" onSubmit={(event) => addJobNote(event, job)}><textarea name="content" placeholder="Add a delivery update" maxLength={2000} required /><button className="primary" disabled={saving}>Add note <span>＋</span></button></form>}</div>
              </article>
            })}</div> : <div className="empty-state"><div className="empty-icon">▦</div><strong>No jobs yet</strong><p>When your organization accepts a quotation, the linked job will appear here for delivery tracking.</p></div>}
          </section>
          <p className="page-note"><span>◈</span> Job changes are scoped to this organization and retained in delivery history.</p>
        </> : <>
          <div className="page-heading"><div><p className="eyebrow">WORKFLOW</p><h1>{label}</h1><p className="muted">Prepare a quote, track its decision, and create a job on acceptance.</p></div><span className="count-pill">{visibleQuotes.length} {visibleQuotes.length === 1 ? 'record' : 'records'}</span></div>
          {error && <div className="alert inline-alert">{error}</div>}
          <div className="content-grid"><section className="panel customer-panel"><div className="panel-heading"><div><h2>Quotation register</h2><p>Records for {activeOrg?.name || 'your organization'}</p></div></div>
            {visibleQuotes.length ? <div className="quote-list">{visibleQuotes.map((quote) => <article className="quote-row" key={quote.id}>
              <div className="quote-top"><div><strong>{quote.customer_name}</strong><span className="quote-id">Quote {quote.series_id.slice(0, 8).toUpperCase()} · Revision {quote.revision_number}{!quote.is_current ? ' · historical' : ''}</span></div><span className={`quote-status ${quote.status}`}>{quote.status}</span></div>
              <div className="quote-line">{quote.lines.map((line) => <div key={line.id}>{line.description} · {line.quantity} × {quote.currency} {line.unit_price}</div>)}</div>
              <div className="quote-meta">Valid until {quote.valid_until}{quote.job_id ? ` · Job #${quote.job_id}` : ''}</div>
              {quote.status_history.length > 1 && <details className="quote-history"><summary>View status history</summary>{quote.status_history.map((entry, index) => <div key={`${entry.status}-${index}`}>{entry.status} · {entry.actor} · {new Date(entry.created_at).toLocaleString()}</div>)}</details>}
              {quote.status === 'draft' && canWriteQuotes && <div className="quote-actions"><button disabled={saving} onClick={() => transition(quote, 'send')}>Send</button><button disabled={saving} onClick={() => startRevision(quote)}>Revise</button></div>}
              {quote.status === 'sent' && <div className="quote-actions">{canAccept && <button className="action-primary" disabled={saving} onClick={() => transition(quote, 'accept')}>Accept & create job</button>}{canWriteQuotes && <><button disabled={saving} onClick={() => transition(quote, 'reject')}>Reject</button><button disabled={saving} onClick={() => transition(quote, 'withdraw')}>Withdraw</button></>}</div>}
              {quote.status === 'sent' && canWriteQuotes && <div className="quote-actions"><button disabled={saving} onClick={() => startRevision(quote)}>Create revision</button></div>}
            </article>)}</div> : <div className="empty-state"><div className="empty-icon">↗</div><strong>No quotations yet</strong><p>Create a draft quotation to start this workflow.</p></div>}
          </section>
          {page === 'quotations' && canWriteQuotes && <section className="panel add-panel"><div className="panel-heading"><div><h2>{editingQuote ? `Revise quotation · v${editingQuote.revision_number}` : 'New quotation'}</h2><p>{editingQuote ? 'This creates a new draft revision and preserves this version.' : 'Start with one service line.'}</p></div></div><form key={editingQuote?.id || 'new'} className="stack-form" onSubmit={addQuotation}>
            <label>Customer <span className="required">*</span><select name="customer_id" required defaultValue={editingQuote?.customer ?? ''}><option value="" disabled>Select a customer</option>{editingQuote && !customers.some((customer) => customer.id === editingQuote.customer) && <option value={editingQuote.customer}>{editingQuote.customer_name} (current customer)</option>}{customers.filter((customer) => customer.status === 'active').map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select></label>
            <div className="field-row"><label>Currency<input name="currency" defaultValue={editingQuote?.currency || 'KES'} minLength={3} maxLength={3} required /></label><label>Valid until<input type="date" name="valid_until" min={new Date().toISOString().slice(0, 10)} defaultValue={editingQuote?.valid_until || new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10)} required /></label></div>
            <div className="quotation-lines">{quoteLines.map((line, index) => <div className="quotation-line-editor" key={index}><label>Service description<input placeholder="e.g. Equipment installation" value={line.description} onChange={(event) => changeQuoteLine(index, 'description', event.target.value)} required /></label><div className="field-row"><label>Quantity<input type="number" min="0.001" step="0.001" value={line.quantity} onChange={(event) => changeQuoteLine(index, 'quantity', event.target.value)} required /></label><label>Unit price<input type="number" min="0" step="0.01" placeholder="0.00" value={line.unit_price} onChange={(event) => changeQuoteLine(index, 'unit_price', event.target.value)} required /></label></div>{quoteLines.length > 1 && <button type="button" className="quiet-action" onClick={() => setQuoteLines((lines) => lines.filter((_, lineIndex) => lineIndex !== index))}>Remove line</button>}</div>)}</div>
            <button type="button" className="quiet-action" onClick={() => setQuoteLines((lines) => [...lines, { description: '', quantity: '1', unit_price: '' }])}>Add line item</button>
            <p className="form-note">Prices are stored as entered. Tax and quotation totals are not calculated here.</p><button className="primary" disabled={saving || !customers.some((customer) => customer.status === 'active')}>{saving ? 'Saving…' : editingQuote ? 'Create revision' : 'Save draft'} <span>＋</span></button>
            {editingQuote && <button type="button" className="quiet-action" onClick={() => { setEditingQuote(null); setQuoteLines([{ description: '', quantity: '1', unit_price: '' }]) }}>Cancel revision</button>}
          </form></section>}</div>
          <p className="page-note"><span>◈</span> Each status change is recorded with the acting team member and time.</p>
        </>}
      </div>
    </main>
  </div>
}
