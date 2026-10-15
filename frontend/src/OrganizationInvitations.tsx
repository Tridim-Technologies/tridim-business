import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

type Invitation = {
  id: number
  email: string
  role: string
  status: 'pending' | 'accepted' | 'revoked' | 'expired'
  invited_by: string
  created_at: string
  expires_at: string
}

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
  return response.json() as Promise<T>
}

function csrfHeader(): Record<string, string> {
  const token = document.cookie.split('; ').find((part) => part.startsWith('csrftoken='))?.split('=').slice(1).join('=')
  return token ? { 'X-CSRFToken': decodeURIComponent(token) } : {}
}

export default function OrganizationInvitations({
  organization, canInviteAdmin, saving, setSaving, error, setError,
}: {
  organization: string
  canInviteAdmin: boolean
  saving: boolean
  setSaving: (value: boolean) => void
  error: string
  setError: (value: string) => void
}) {
  const [invitations, setInvitations] = useState<Invitation[]>([])
  const [shareUrl, setShareUrl] = useState('')
  const [copied, setCopied] = useState(false)

  async function refresh() {
    if (!organization) return
    const result = await api<{ results: Invitation[] }>(`/api/organizations/${organization}/invitations/`)
    setInvitations(result.results)
  }

  useEffect(() => {
    setInvitations([])
    setShareUrl('')
    refresh().catch((reason: Error) => setError(reason.message))
  }, [organization])

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setShareUrl('')
    setCopied(false)
    setSaving(true)
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    try {
      const result = await api<{ invitation: Invitation; token: string }>(
        `/api/organizations/${organization}/invitations/`,
        {
          method: 'POST',
          headers: csrfHeader(),
          body: JSON.stringify({ email: form.get('email'), role: form.get('role') }),
        },
      )
      const url = new URL(window.location.href)
      url.hash = `invite=${encodeURIComponent(result.token)}`
      setShareUrl(url.toString())
      formElement.reset()
      await refresh()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function revoke(invitation: Invitation) {
    setError('')
    setSaving(true)
    try {
      await api(`/api/organizations/${organization}/invitations/${invitation.id}/revoke/`, {
        method: 'POST', headers: csrfHeader(), body: JSON.stringify({}),
      })
      await refresh()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(shareUrl)
      setCopied(true)
    } catch {
      setError('Copy was unavailable. Select and copy the invitation link manually.')
    }
  }

  return <>
    <div className="page-heading"><div><p className="eyebrow">PEOPLE</p><h1>Invitations</h1><p className="muted">Invite a team member to this organization.</p></div><span className="count-pill">{invitations.filter((item) => item.status === 'pending').length} pending</span></div>
    {error && <div className="alert inline-alert">{error}</div>}
    <p className="invitation-notice">Email delivery is not configured. Create an invitation, copy the link, and share it directly with the intended person. The link works once for seven days and does not verify email ownership.</p>
    <section className="panel invitation-create"><div className="panel-heading"><div><h2>Invite a member</h2><p>They can create an account or sign in to one that uses the invited email.</p></div></div>
      <form className="invitation-form" onSubmit={create}>
        <label>Email address<input type="email" name="email" autoComplete="email" maxLength={254} required /></label>
        <label>Organization role<select name="role" defaultValue="employee"><option value="employee">Employee</option><option value="sales">Sales</option><option value="operations">Operations</option><option value="finance">Finance</option>{canInviteAdmin && <option value="admin">Admin</option>}</select></label>
        <button className="primary" disabled={saving || !organization}>{saving ? 'Creating…' : 'Create invitation'} <span>＋</span></button>
      </form>
      {shareUrl && <div className="invitation-share"><strong>Copy this link now</strong><p>The secret link is shown once. It expires after seven days.</p><div><input aria-label="Invitation link" readOnly value={shareUrl} onFocus={(event) => event.currentTarget.select()} /><button className="quiet-action" onClick={copyLink}>{copied ? 'Copied' : 'Copy link'}</button></div></div>}
    </section>
    <section className="panel invitation-list"><div className="panel-heading"><div><h2>Recent invitations</h2><p>Invitation links are never shown again after creation.</p></div></div>
      {invitations.length ? <div className="invitation-items">{invitations.map((invitation) => <article className="invitation-item" key={invitation.id}>
        <div><strong>{invitation.email}</strong><span>{invitation.role} · Invited by {invitation.invited_by}</span></div>
        <div className="invitation-meta"><span className={`invitation-status ${invitation.status}`}>{invitation.status}</span><small>{invitation.status === 'pending' ? 'Expires' : 'Created'} {new Date(invitation.status === 'pending' ? invitation.expires_at : invitation.created_at).toLocaleString()}</small>{invitation.status === 'pending' && <button className="quiet-action" disabled={saving} onClick={() => revoke(invitation)}>Revoke</button>}</div>
      </article>)}</div> : <div className="empty-state"><div className="empty-icon">✉</div><strong>No invitations yet</strong><p>Create a link when you are ready to add someone to this organization.</p></div>}
    </section>
  </>
}
