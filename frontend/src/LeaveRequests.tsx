import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

type LeaveRequest = {
  id: number
  employee: string
  is_requester: boolean
  start_date: string
  end_date: string
  category: 'annual' | 'personal' | 'parental' | 'other'
  note: string
  status: 'pending' | 'approved' | 'rejected' | 'cancelled'
  reviewed_by: string | null
  reviewed_at: string | null
  decision_reason: string
  created_at: string
  history: { action: string; actor: string; reason: string; created_at: string }[]
}

const categoryLabels: Record<LeaveRequest['category'], string> = {
  annual: 'Annual', personal: 'Personal', parental: 'Parental', other: 'Other',
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
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
  return response.json() as Promise<T>
}

function csrfHeader(): Record<string, string> {
  const token = document.cookie.split('; ').find((part) => part.startsWith('csrftoken='))?.split('=').slice(1).join('=')
  return token ? { 'X-CSRFToken': decodeURIComponent(token) } : {}
}

function today() {
  const date = new Date()
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

export default function LeaveRequests({
  organization, canManage, saving, setSaving, error, setError,
}: {
  organization: string
  canManage: boolean
  saving: boolean
  setSaving: (value: boolean) => void
  error: string
  setError: (value: string) => void
}) {
  const [requests, setRequests] = useState<LeaveRequest[]>([])

  async function refresh() {
    if (!organization) return
    const result = await request<{ results: LeaveRequest[] }>(`/api/organizations/${organization}/leave-requests/`)
    setRequests(result.results)
  }

  useEffect(() => {
    setRequests([])
    refresh().catch((reason: Error) => setError(reason.message))
  }, [organization, canManage])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSaving(true)
    const form = new FormData(event.currentTarget)
    const formElement = event.currentTarget
    try {
      await request(`/api/organizations/${organization}/leave-requests/`, {
        method: 'POST', headers: csrfHeader(),
        body: JSON.stringify({
          start_date: form.get('start_date'), end_date: form.get('end_date'),
          category: form.get('category'), note: form.get('note'),
        }),
      })
      formElement.reset()
      await refresh()
    } catch (reason) { setError((reason as Error).message) } finally { setSaving(false) }
  }

  async function transition(item: LeaveRequest, action: 'approve' | 'reject' | 'cancel', reason = '') {
    setError('')
    setSaving(true)
    try {
      await request(`/api/organizations/${organization}/leave-requests/${item.id}/transition/`, {
        method: 'POST', headers: csrfHeader(), body: JSON.stringify({ action, reason }),
      })
      await refresh()
    } catch (cause) { setError((cause as Error).message) } finally { setSaving(false) }
  }

  return <>
    <div className="page-heading"><div><p className="eyebrow">PEOPLE</p><h1>Leave requests</h1><p className="muted">Request time away and keep the decision visible.</p></div><span className="count-pill">{requests.length} {requests.length === 1 ? 'request' : 'requests'}</span></div>
    {error && <div className="alert inline-alert">{error}</div>}
    <p className="leave-notice">Add only a brief note needed to review your dates. Do not include medical details or attachments. This workflow does not calculate leave balances or legal entitlements.</p>
    <section className="panel leave-create"><div className="panel-heading"><div><h2>Request leave</h2><p>Your request will be sent to an organization manager.</p></div></div>
      <form className="leave-form" onSubmit={submit}>
        <label>Leave category<select name="category" defaultValue="annual"><option value="annual">Annual</option><option value="personal">Personal</option><option value="parental">Parental</option><option value="other">Other</option></select></label>
        <label>Start date<input type="date" name="start_date" min={today()} defaultValue={today()} required /></label>
        <label>End date<input type="date" name="end_date" min={today()} defaultValue={today()} required /></label>
        <label className="leave-note-field">Short note (optional)<input name="note" maxLength={500} placeholder="Brief context for the reviewer" /></label>
        <button className="primary" disabled={saving || !organization}>{saving ? 'Submitting…' : 'Submit request'} <span>＋</span></button>
      </form>
    </section>
    <section className="panel leave-list"><div className="panel-heading"><div><h2>{canManage ? 'Organization requests' : 'Your requests'}</h2><p>{canManage ? 'Review requests from organization members.' : 'Track the status and decision for your requests.'}</p></div></div>
      {requests.length ? <div className="leave-items">{requests.map((item) => {
        const own = item.is_requester
        return <article className="leave-item" key={item.id}>
          <div className="leave-item-heading"><div><strong>{canManage ? `Leave request · ${categoryLabels[item.category]}` : categoryLabels[item.category]}</strong>{canManage && <span>{item.employee}</span>}</div><span className={`leave-status ${item.status}`}>{item.status}</span></div>
          <p className="leave-dates">{item.start_date} – {item.end_date}</p>
          {item.note && <p className="leave-item-note">{item.note}</p>}
          {item.reviewed_at && <p className="leave-decision">{item.status} by {item.reviewed_by} · {new Date(item.reviewed_at).toLocaleString()}{item.decision_reason ? ` · ${item.decision_reason}` : ''}</p>}
          {canManage && item.status === 'pending' && !own && <div className="leave-actions"><button className="quiet-action" disabled={saving} onClick={() => transition(item, 'approve')}>Approve</button><form onSubmit={(event) => { event.preventDefault(); const form = new FormData(event.currentTarget); void transition(item, 'reject', String(form.get('reason') || '')) }}><input name="reason" maxLength={240} placeholder="Reason to reject" aria-label={`Reason to reject ${item.employee}'s request`} required /><button className="quiet-action" disabled={saving}>Reject</button></form></div>}
          {own && item.status === 'pending' && <button className="quiet-action" disabled={saving} onClick={() => transition(item, 'cancel')}>Cancel request</button>}
          <details className="leave-history"><summary>Request history</summary>{item.history.map((entry, index) => <span key={`${entry.action}-${index}`}>{entry.action} · {entry.actor} · {new Date(entry.created_at).toLocaleString()}{entry.reason ? ` · ${entry.reason}` : ''}</span>)}</details>
        </article>
      })}</div> : <div className="empty-state"><div className="empty-icon">◷</div><strong>No leave requests yet</strong><p>Submitted requests and decisions will appear here.</p></div>}
    </section>
  </>
}
