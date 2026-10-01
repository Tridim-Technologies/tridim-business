import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

type Organization = { id: string; name: string; role: string }
type Customer = { id: number; name: string; contact_name: string; email: string; phone: string; created_at: string }
type Session = { authenticated: boolean; user?: { id: number; username: string }; organizations?: Organization[] }

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...init, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', ...init.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || body.name?.[0] || `Request failed (${response.status})`)
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function refreshSession() {
    await api('/api/csrf/')
    const current = await api<Session>('/api/session/').catch((): Session => ({ authenticated: false }))
    setSession(current)
    if (current.organizations?.length) setOrganization((selected) => selected || current.organizations![0].id)
  }

  useEffect(() => { refreshSession().catch((reason: Error) => setError(reason.message)).finally(() => setLoading(false)) }, [])

  useEffect(() => {
    if (!session?.authenticated || !organization) { setCustomers([]); return }
    api<{ results: Customer[] }>(`/api/organizations/${organization}/customers/`)
      .then((data) => { setCustomers(data.results); setError('') })
      .catch((reason: Error) => setError(reason.message))
  }, [session, organization])

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
    const formElement = event.currentTarget
    const form = new FormData(event.currentTarget)
    try {
      await api(`/api/organizations/${organization}/customers/`, { method: 'POST', headers: csrfHeader(), body: JSON.stringify({ name: form.get('name'), contact_name: form.get('contact_name'), email: form.get('email'), phone: form.get('phone') }) })
      formElement.reset()
      const data = await api<{ results: Customer[] }>(`/api/organizations/${organization}/customers/`)
      setCustomers(data.results)
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function signOut() {
    await api('/api/session/', { method: 'DELETE', headers: csrfHeader() })
    setSession({ authenticated: false }); setCustomers([])
  }

  if (loading) return <main className="loading">Loading your workspace…</main>
  if (!session?.authenticated) return <main className="login-shell">
    <section className="login-card">
      <div className="brand-mark">T</div><p className="eyebrow">TRIDIM BUSINESS</p>
      <h1>One clear view of your work.</h1><p className="muted">Sign in to manage your organization’s customer records.</p>
      {error && <div className="alert">{error}</div>}
      <form onSubmit={signIn} className="stack-form">
        <label>Username<input name="username" autoComplete="username" required /></label>
        <label>Password<input type="password" name="password" autoComplete="current-password" required /></label>
        <button className="primary" type="submit">Sign in <span>→</span></button>
      </form>
      <p className="footnote">Local alpha · Your organization’s data stays private to its members.</p>
    </section>
  </main>

  const activeOrg = session.organizations?.find((item) => item.id === organization)
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><div className="brand-mark">T</div><div><strong>Tridim</strong><small>BUSINESS</small></div></div>
      <div className="workspace-label">WORKSPACE</div><div className="workspace">{activeOrg?.name || 'No organization'}</div>
      <nav><span className="nav-item active"><span className="nav-icon">◫</span> Customers</span><span className="nav-item disabled"><span className="nav-icon">↗</span> Quotations</span><span className="nav-item disabled"><span className="nav-icon">▦</span> Jobs</span></nav>
      <div className="sidebar-bottom"><span className="avatar">{session.user?.username.slice(0, 1).toUpperCase()}</span><div className="user-label"><strong>{session.user?.username}</strong><small>{activeOrg?.role || 'Member'}</small></div><button className="icon-button" onClick={signOut} aria-label="Sign out">↗</button></div>
    </aside>
    <main className="main-area"><header className="topbar"><div><span className="breadcrumb">Workspace</span><span className="slash">/</span> Customers</div><div className="top-actions"><select aria-label="Organization" value={organization} onChange={(event) => setOrganization(event.target.value)}>{session.organizations?.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}</select><span className="avatar small">{session.user?.username.slice(0, 1).toUpperCase()}</span></div></header>
      <div className="content"><div className="page-heading"><div><p className="eyebrow">RELATIONSHIPS</p><h1>Customers</h1><p className="muted">Keep the people and businesses you work with in one place.</p></div><span className="count-pill">{customers.length} {customers.length === 1 ? 'customer' : 'customers'}</span></div>
        {error && <div className="alert inline-alert">{error}</div>}
        <div className="content-grid"><section className="panel customer-panel"><div className="panel-heading"><div><h2>Customer directory</h2><p>Records for {activeOrg?.name || 'your organization'}</p></div><span className="search-glyph">⌕</span></div>
          {customers.length ? <div className="customer-list">{customers.map((customer) => <article className="customer-row" key={customer.id}><span className="customer-avatar">{customer.name.slice(0, 1).toUpperCase()}</span><div className="customer-info"><strong>{customer.name}</strong><span>{customer.contact_name || customer.email || 'No contact details yet'}</span></div><span className="status-dot" title="Active record" /></article>)}</div> : <div className="empty-state"><div className="empty-icon">◎</div><strong>Your customer list starts here</strong><p>Add a customer to keep their contact details ready for your next quote.</p></div>}
        </section>
        <section className="panel add-panel"><div className="panel-heading"><div><h2>Add a customer</h2><p>Create a record for this workspace.</p></div></div><form className="stack-form" onSubmit={addCustomer}><label>Business or customer name <span className="required">*</span><input name="name" placeholder="e.g. Northstar Services" required /></label><label>Contact person<input name="contact_name" placeholder="Full name" /></label><label>Email address<input type="email" name="email" placeholder="name@business.com" /></label><label>Phone number<input name="phone" placeholder="+1 555 000 0000" /></label><button className="primary" disabled={saving || !organization}>{saving ? 'Saving…' : 'Add customer'} <span>＋</span></button></form></section></div>
        <p className="page-note"><span>◈</span> Customer records are visible only to members of this organization.</p>
      </div>
    </main>
  </div>
}
