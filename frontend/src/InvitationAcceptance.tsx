import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

type Invitation = { email: string; role: string; organization_name: string; expires_at: string }
type Session = { authenticated: boolean; user?: { id: number; username: string; email: string } }

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

export default function InvitationAcceptance({
  token, session, onComplete,
}: {
  token: string
  session: Session | null
  onComplete: (organizationId?: string) => Promise<void>
}) {
  const [invitation, setInvitation] = useState<Invitation | null>(null)
  const [mode, setMode] = useState<'create' | 'signin'>('create')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setLoading(true)
    api<Invitation>('/api/invitations/inspect/', {
      method: 'POST', headers: csrfHeader(), body: JSON.stringify({ token }),
    }).then(setInvitation).catch((reason: Error) => setError(reason.message)).finally(() => setLoading(false))
  }, [token])

  async function accept(payload: Record<string, unknown> = {}) {
    const result = await api<{ invitation: { organization: string } }>('/api/invitations/accept/', {
      method: 'POST', headers: csrfHeader(), body: JSON.stringify({ token, ...payload }),
    })
    const url = new URL(window.location.href)
    url.hash = ''
    window.history.replaceState(null, '', url.toString())
    await onComplete(result.invitation.organization)
  }

  async function createAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSaving(true)
    const form = new FormData(event.currentTarget)
    const password = String(form.get('password') || '')
    if (password !== form.get('password_confirm')) {
      setError('The passwords do not match.')
      setSaving(false)
      return
    }
    try {
      await accept({ username: form.get('username'), password })
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function signInAndAccept(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSaving(true)
    const form = new FormData(event.currentTarget)
    try {
      await api('/api/session/', {
        method: 'POST', headers: csrfHeader(),
        body: JSON.stringify({ username: form.get('username'), password: form.get('password') }),
      })
      await accept()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function signOut() {
    setSaving(true)
    setError('')
    try {
      await api('/api/session/', { method: 'DELETE', headers: csrfHeader() })
      window.location.reload()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <main className="invite-entry"><section className="invite-entry-card"><p>Checking invitation…</p></section></main>

  return <main className="invite-entry"><section className="invite-entry-card">
    <div className="brand-mark">T</div><p className="eyebrow">TRIDIM BUSINESS</p>
    {invitation ? <>
      <h1>Join {invitation.organization_name}</h1>
      <p className="muted">You have been invited as <strong>{invitation.role}</strong> using <strong>{invitation.email}</strong>.</p>
      {error && <div className="alert">{error}</div>}
      <p className="footnote">This one-time invitation expires {new Date(invitation.expires_at).toLocaleString()}. Accepting it does not verify ownership of the email address.</p>
      {session?.authenticated ? <div className="stack-form">
        <p>Signed in as <strong>{session.user?.username}</strong> ({session.user?.email || 'no email on account'}).</p>
        {(session.user?.email || '').toLowerCase() === invitation.email.toLowerCase() ? <button className="primary" disabled={saving} onClick={() => { setSaving(true); accept().catch((reason: Error) => setError(reason.message)).finally(() => setSaving(false)) }}>{saving ? 'Joining…' : 'Accept invitation'} <span>→</span></button> : <><p className="muted">Sign in with the account that uses the invited email address.</p><button className="quiet-action" disabled={saving} onClick={signOut}>Sign out and use another account</button></>}
      </div> : <>
        <div className="invite-mode"><button className={mode === 'create' ? 'active' : ''} onClick={() => { setMode('create'); setError('') }}>Create account</button><button className={mode === 'signin' ? 'active' : ''} onClick={() => { setMode('signin'); setError('') }}>I already have an account</button></div>
        {mode === 'create' ? <form className="stack-form" onSubmit={createAccount}>
          <label>Username<input name="username" autoComplete="username" maxLength={150} required /></label>
          <label>Password<input type="password" name="password" autoComplete="new-password" required /></label>
          <label>Confirm password<input type="password" name="password_confirm" autoComplete="new-password" required /></label>
          <button className="primary" disabled={saving}>{saving ? 'Creating account…' : 'Create account and join'} <span>→</span></button>
        </form> : <form className="stack-form" onSubmit={signInAndAccept}>
          <label>Username<input name="username" autoComplete="username" required /></label>
          <label>Password<input type="password" name="password" autoComplete="current-password" required /></label>
          <button className="primary" disabled={saving}>{saving ? 'Signing in…' : 'Sign in and accept'} <span>→</span></button>
        </form>}
      </>}
    </> : <>
      <h1>Invitation unavailable</h1><p className="muted">This link is invalid, expired, revoked, or already used. Ask the organization manager for a new invitation.</p>
      {error && <div className="alert">{error}</div>}
    </>}
    <p className="footnote">Organization access is limited to the role shown above.</p>
  </section></main>
}
