import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

type Employee = {
  id: number
  username: string
  display_name: string
  job_title: string
  department: string
  is_active: boolean
}
type Member = { id: number; username: string }

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

export default function EmployeeDirectory({
  organization,
  canManage,
  saving,
  setSaving,
  error,
  setError,
}: {
  organization: string
  canManage: boolean
  saving: boolean
  setSaving: (value: boolean) => void
  error: string
  setError: (value: string) => void
}) {
  const [employees, setEmployees] = useState<Employee[]>([])
  const [members, setMembers] = useState<Member[]>([])
  const [showInactive, setShowInactive] = useState(false)

  async function refresh() {
    if (!organization) return
    const query = showInactive && canManage ? '?status=all' : ''
    const result = await request<{ results: Employee[]; members?: Member[] }>(
      `/api/organizations/${organization}/employees/${query}`,
    )
    setEmployees(result.results)
    setMembers(result.members || [])
  }

  useEffect(() => {
    setEmployees([])
    setMembers([])
    refresh().catch((reason: Error) => setError(reason.message))
  }, [organization, showInactive, canManage])

  async function createEmployee(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSaving(true)
    const form = new FormData(event.currentTarget)
    const formElement = event.currentTarget
    try {
      await request(`/api/organizations/${organization}/employees/`, {
        method: 'POST',
        headers: csrfHeader(),
        body: JSON.stringify({
          membership_id: Number(form.get('membership_id')),
          display_name: form.get('display_name'),
          job_title: form.get('job_title'),
          department: form.get('department'),
        }),
      })
      formElement.reset()
      await refresh()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function updateEmployee(event: FormEvent<HTMLFormElement>, employee: Employee) {
    event.preventDefault()
    setError('')
    setSaving(true)
    const form = new FormData(event.currentTarget)
    try {
      await request(`/api/organizations/${organization}/employees/${employee.id}/`, {
        method: 'PATCH',
        headers: csrfHeader(),
        body: JSON.stringify({
          display_name: form.get('display_name'),
          job_title: form.get('job_title'),
          department: form.get('department'),
          is_active: form.get('is_active') === 'on',
        }),
      })
      await refresh()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return <>
    <div className="page-heading"><div><p className="eyebrow">PEOPLE</p><h1>Employees</h1><p className="muted">A work directory for {organization ? 'this organization' : 'your organization'}.</p></div><span className="count-pill">{employees.length} {employees.length === 1 ? 'profile' : 'profiles'}</span></div>
    {error && <div className="alert inline-alert">{error}</div>}
    <p className="employee-notice">This directory contains work profile details only. Payroll, salary, government identifiers, and personal contact information are not collected here.</p>
    {canManage && <section className="panel employee-create"><div className="panel-heading"><div><h2>Add an employee profile</h2><p>Choose an existing organization member. This does not create a login or change their access role.</p></div></div>
      {members.length ? <form className="employee-form" onSubmit={createEmployee}>
        <label>Organization member<select name="membership_id" required defaultValue=""><option value="" disabled>Choose a member</option>{members.map((member) => <option key={member.id} value={member.id}>{member.username}</option>)}</select></label>
        <label>Display name<input name="display_name" maxLength={160} required /></label>
        <label>Job title<input name="job_title" maxLength={120} /></label>
        <label>Department<input name="department" maxLength={100} /></label>
        <button className="primary" disabled={saving}>Add profile <span>＋</span></button>
      </form> : <p className="employee-empty-note">All active organization members already have profiles.</p>}
    </section>}
    {canManage && <label className="employee-filter"><input type="checkbox" checked={showInactive} onChange={(event) => setShowInactive(event.target.checked)} /> Include inactive profiles</label>}
    <section className="panel employee-directory"><div className="panel-heading"><div><h2>Employee directory</h2><p>Only active profiles are shown to employees.</p></div></div>
      {employees.length ? <div className="employee-list">{employees.map((employee) => <article className={`employee-card ${employee.is_active ? '' : 'inactive'}`} key={employee.id}>
        {canManage ? <form className="employee-edit-form" onSubmit={(event) => updateEmployee(event, employee)}>
          <div className="employee-card-heading"><div><strong>{employee.display_name}</strong><span>{employee.username}</span></div><label className="employee-active"><input name="is_active" type="checkbox" defaultChecked={employee.is_active} /> Active</label></div>
          <div className="employee-fields"><label>Display name<input name="display_name" maxLength={160} defaultValue={employee.display_name} required /></label><label>Job title<input name="job_title" maxLength={120} defaultValue={employee.job_title} /></label><label>Department<input name="department" maxLength={100} defaultValue={employee.department} /></label></div>
          <button className="quiet-action" disabled={saving}>Save profile</button>
        </form> : <div className="employee-card-heading"><div><strong>{employee.display_name}</strong><span>{[employee.job_title, employee.department].filter(Boolean).join(' · ') || 'Role not set'}</span></div></div>}
      </article>)}</div> : <div className="empty-state"><div className="empty-icon">◎</div><strong>No employee profiles yet</strong><p>An organization manager can add a profile for an existing member.</p></div>}
    </section>
    <p className="page-note"><span>◈</span> Profiles are organization-scoped and do not grant access. Access still comes from the member’s organization role.</p>
  </>
}
