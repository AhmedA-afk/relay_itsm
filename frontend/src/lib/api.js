const BASE = import.meta.env.VITE_API_BASE ?? ''

async function call(path, { method = 'GET', body } = {}) {
  const res = await fetch(`${BASE}/api${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      // who is acting, so the audit trail has a name rather than "system"
      'X-Actor': 'A. Okonkwo',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const payload = await res.json()
      if (payload?.detail) detail = payload.detail
    } catch {
      /* the body was not JSON; the status line will have to do */
    }
    const error = new Error(detail)
    error.status = res.status
    throw error
  }
  return res.status === 204 ? null : res.json()
}

export const api = {
  meta: () => call('/meta'),
  history: () => call('/history/summary'),
  showcaseCases: () => call('/showcase/cases'),
  showcaseRun: (body) => call('/showcase/run', { method: 'POST', body }),
  tickets: (kind) => call(kind ? `/tickets?kind=${kind}` : '/tickets'),
  ticket: (id) => call(`/tickets/${id}`),
  createTicket: (fields) => call('/tickets', { method: 'POST', body: fields }),

  claim: (id, technician_id = 'ao') => call(`/tickets/${id}/claim`, { method: 'POST', body: { technician_id } }),
  unassign: (id) => call(`/tickets/${id}/unassign`, { method: 'POST' }),
  autoRoute: (id) => call(`/tickets/${id}/auto-route`, { method: 'POST' }),
  resolve: (id, code, note = '') => call(`/tickets/${id}/resolve`, { method: 'POST', body: { code, note } }),
  reopen: (id) => call(`/tickets/${id}/reopen`, { method: 'POST' }),
  setMajor: (id, on) => call(`/tickets/${id}/major`, { method: 'POST', body: { on } }),
  hold: (id, reason) => call(`/tickets/${id}/hold`, { method: 'POST', body: { reason } }),
  unhold: (id) => call(`/tickets/${id}/unhold`, { method: 'POST' }),
  classify: (id, fields) => call(`/tickets/${id}/classify`, { method: 'POST', body: fields }),
  postMessage: (id, body, visibility = 'public') =>
    call(`/tickets/${id}/messages`, { method: 'POST', body: { body, visibility } }),

  people: () => call('/people'),
  sentiment: (id, engine = 'jev') =>
    call(`/tickets/${id}/sentiment`, { method: 'POST', body: { engine } }),
  sentimentSummary: () => call('/sentiment'),
  escalation: (id, engine = 'jev') =>
    call(`/tickets/${id}/escalation`, { method: 'POST', body: { engine } }),
  escalationSummary: () => call('/escalation'),
  duplicates: (id, engine = 'jev') => call(`/tickets/${id}/duplicates?engine=${engine}`),
  link: (id, other, relation) =>
    call(`/tickets/${id}/link`, { method: 'POST', body: { other, relation } }),
  createTeam: (fields) => call('/teams', { method: 'POST', body: fields }),
  updateTeam: (key, fields) => call(`/teams/${key}`, { method: 'PATCH', body: fields }),
  deleteTeam: (key) => call(`/teams/${key}`, { method: 'DELETE' }),
  createPerson: (fields) => call('/people', { method: 'POST', body: fields }),
  updatePerson: (id, fields) => call(`/people/${id}`, { method: 'PATCH', body: fields }),
  deletePerson: (id) => call(`/people/${id}`, { method: 'DELETE' }),
  route: (id, engine = 'jev', apply = false) =>
    call(`/tickets/${id}/route`, { method: 'POST', body: { engine, apply } }),

  matrix: () => call('/config/matrix'),
  saveMatrix: (matrix) => call('/config/matrix', { method: 'PUT', body: { matrix } }),

  problems: () => call('/problems'),
  changes: () => call('/changes'),
  releases: () => call('/releases'),
  articles: () => call('/articles'),
  catalog: () => call('/catalog'),
  search: (q) => call(`/search?q=${encodeURIComponent(q)}`),
  deflect: (q, engine = 'jev') =>
    call(`/deflect?q=${encodeURIComponent(q)}&engine=${engine}`),
  tookArticle: (id) => call(`/articles/${id}/deflected`, { method: 'POST' }),
  reports: () => call('/reports/summary'),
}
