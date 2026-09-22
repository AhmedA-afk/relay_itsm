import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api } from '../lib/api'
import { Icon, Tag } from '../components/ui'
import { C, clock, isLive, remainingFor } from '../lib/format'

function Chrome({ onGo, active, count }) {
  return (
    <div className="ptop">
      <span className="h2" style={{ fontSize: 15 }}>Relay</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <button
          className="b b-bare b-s" onClick={() => onGo('intake')}
          style={active === 'intake' ? { color: 'var(--ink)' } : undefined}
        >Ask for something</button>
        <button
          className="b b-bare b-s" onClick={() => onGo('mine')}
          style={active === 'mine' ? { color: 'var(--ink)' } : undefined}
        >Your requests {count ? <span className="mo fine">{count}</span> : null}</button>
        <button className="b b-bare b-s" onClick={() => onGo('catalog')}>What we offer</button>
        <span className="av">KM</span>
      </div>
    </div>
  )
}

/**
 * The single front door.
 *
 * Deflection runs against the real knowledge base over the API, and this is the
 * one screen where a judgment faces a person rather than an agent.
 *
 * Three bands, from one probability, with the lines in `policy.py`:
 *
 *   answer  — lead with it; raising a ticket becomes the second option
 *   suggest — offer it above the form, quietly
 *   quiet   — say nothing and get out of the way
 *
 * The ticket is never taken away. Being wrong here costs the person directly,
 * so the strongest thing the band does is reorder the page.
 */
export function Intake({ onGo, tickets, toast }) {
  const [q, setQ] = useState('the scanner in bay 3 keeps dropping off the wifi')
  const [found, setFound] = useState(null)
  const [looking, setLooking] = useState(false)
  const [sending, setSending] = useState(false)

  useEffect(() => {
    let alive = true
    if (!q.trim()) { setFound(null); return undefined }
    setLooking(true)
    // slower than a keyword search deserves, because this one costs a call
    const id = setTimeout(() => {
      api.deflect(q).then(
        (r) => { if (alive) { setFound(r); setLooking(false) } },
        () => { if (alive) setLooking(false) },
      )
    }, 650)
    return () => { alive = false; clearTimeout(id) }
  }, [q])

  const hits = found?.hits ?? []
  const band = found?.band ?? 'quiet'
  const lead = band === 'answer' ? hits[0] : null
  const rest = lead ? hits.slice(1) : hits

  const mine = tickets.filter(isLive).length

  return (
    <div className="scroll">
      <Chrome onGo={onGo} active="intake" count={mine} />
      <div className="pbody">
        <div>
          <h1 style={{ fontSize: 34, fontWeight: 600, letterSpacing: '-.04em', lineHeight: 1.08 }}>
            What do you need?
          </h1>
          <p className="lead" style={{ fontSize: 15, margin: '12px 0 0' }}>
            Say it the way you would say it to a colleague. Working out who fixes it is our job.
          </p>
        </div>

        <AnimatePresence initial={false}>
          {lead ? (
            <motion.div
              key="lead" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }} transition={{ duration: 0.22 }}
              style={{ marginTop: 24 }}
            >
              <div className="glass" style={{ padding: '20px 22px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, flexWrap: 'wrap' }}>
                  <Icon n="doc" s={15} c={C.ok} w={1.9} />
                  <span className="h2">This should sort it</span>
                  <span className="mo fine">{lead.id}</span>
                </div>
                <h3 className="h3" style={{ margin: '13px 0 0', fontSize: 16 }}>{lead.title}</h3>
                <p className="p" style={{ margin: '8px 0 0', lineHeight: 1.6 }}>{lead.body}</p>
                <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
                  <button
                    className="b b-go"
                    onClick={async () => {
                      try { await api.tookArticle(lead.id) } catch { /* counting is best effort */ }
                      toast?.('Glad that helped — nothing raised')
                      onGo('mine')
                    }}
                  >That sorted it</button>
                  <button className="b" onClick={() => onGo('knowledge')}>Read the whole article</button>
                </div>
              </div>
              <p className="fine" style={{ margin: '12px 0 0' }}>
                If it does not help, send it anyway — nothing here stops you.
              </p>
            </motion.div>
          ) : null}
        </AnimatePresence>

        <div className="ask" style={{ marginTop: 24 }}>
          <label htmlFor="ask" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>
            Describe what you need
          </label>
          <input
            id="ask" value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="The scanner in Bay 3 keeps losing wifi"
          />
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 16, gap: 10, flexWrap: 'wrap' }}>
            <span className="fine">Bay 3, Rotterdam depot</span>
            <button
              className="b b-go" disabled={!q.trim() || sending}
              onClick={async () => {
                setSending(true)
                try {
                  // it lands with no department and no owner: the desk, or a
                  // routing decision, settles that next
                  const made = await api.createTicket({
                    subject: q.trim(), requester: 'Priya Raghavan', department: 'Warehouse Ops',
                  })
                  setQ('')
                  toast?.(`${made.id} raised — nobody has placed it yet`)
                  onGo('mine')
                } catch (e) {
                  toast?.(e.message)
                } finally {
                  setSending(false)
                }
              }}
            >{sending ? 'Sending…' : 'Send it'}</button>
          </div>
        </div>

        <AnimatePresence initial={false} mode="popLayout">
          {rest.length ? (
            <motion.div
              key="hits" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }} transition={{ duration: 0.22 }} style={{ marginTop: 24 }}
            >
              <p className="mt" style={{ margin: '0 0 10px' }}>
                {lead ? 'These might help too' : 'One of these may save you the wait'}
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {rest.map((h) => {
                  const colour = h.state === 'Stale' ? C.warn : C.ok
                  return (
                    <button key={h.id} className="hit" onClick={() => onGo('knowledge')}>
                      <span className="ico" style={{
                        background: `color-mix(in srgb, ${colour} 15%, transparent)`,
                        boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${colour} 30%, transparent)`,
                      }}>
                        <Icon n="doc" s={12} c={colour} w={1.9} />
                      </span>
                      <span style={{ flex: 1, minWidth: 0 }}>
                        <span className="h3" style={{ display: 'block' }}>{h.title}</span>
                        <span className="p" style={{ display: 'block', marginTop: 4, lineHeight: 1.55 }}>{h.body}</span>
                      </span>
                      <span className="fine" style={{ whiteSpace: 'nowrap' }}>
                        {h.probability != null ? `${Math.round(h.probability * 100)}% · ` : ''}{h.id}
                      </span>
                    </button>
                  )
                })}
              </div>
              <p className="fine" style={{ marginTop: 12 }}>
                If none of them fit, send it and somebody will pick it up.
              </p>
            </motion.div>
          ) : (
            <motion.div key="chips" initial={{ opacity: 0 }} animate={{ opacity: 1 }} style={{ marginTop: 24 }}>
              <p className="mt" style={{ margin: '0 0 11px' }}>Or start from something people ask for a lot</p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {['reset password', 'new starter access', 'replacement scanner', 'phishing email', 'laptop sleep', 'meeting room'].map((x) => (
                  <button key={x} className="b b-s" style={{ borderRadius: 17, height: 31 }} onClick={() => setQ(x)}>
                    {x}
                  </button>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <p className="fine" style={{ marginTop: 36, paddingTop: 18, borderTop: '1px solid var(--edge)' }}>
          You will never be asked how urgent it is or which category it belongs to. Guessing
          that is our problem, not yours.
        </p>
      </div>
    </div>
  )
}

const STEPS = ['Arrived', 'Picked up', 'Being fixed', 'Done']

function stageOf(ticket) {
  if (ticket.status === 'resolved' || ticket.status === 'closed') return 3
  if (ticket.status === 'in_progress') return 2
  if (ticket.status === 'assigned' || ticket.status === 'on_hold') return 1
  return 0
}

/** The requester's own view. No levels, no categories, no jargon. */
export function MyRequests({ onGo, tickets, now, toast }) {
  const [which, setWhich] = useState('open')
  // Replayed ABC Tech requests have no caller, so they belong to nobody's portal.
  const theirs = tickets.filter((t) => t.requester)
  const open = theirs.filter(isLive)
  const done = theirs.filter((t) => !isLive(t))
  const shown = which === 'open' ? open : done

  return (
    <div className="scroll">
      <Chrome onGo={onGo} active="mine" count={open.length} />
      <div style={{ maxWidth: 780, margin: '0 auto', padding: '46px 16px 44px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16, marginBottom: 22, flexWrap: 'wrap' }}>
          <div>
            <h1 className="h1" style={{ fontSize: 28 }}>Your requests</h1>
            <p className="mt" style={{ margin: '5px 0 0' }}>Kofi Mensah, Warehouse Operations, Rotterdam</p>
          </div>
          <div className="sw" role="group" aria-label="Which requests">
            <button aria-pressed={which === 'open'} onClick={() => setWhich('open')}>Open {open.length}</button>
            <button aria-pressed={which === 'done'} onClick={() => setWhich('done')}>Finished {done.length}</button>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
          {shown.map((t) => {
            const finished = !isLive(t)
            const held = t.status === 'on_hold'
            const colour = finished ? C.ok : held ? C.warn : C.ice
            const stage = stageOf(t)
            const remaining = remainingFor(t, now)
            return (
              <article key={t.id} className="glass" style={{ padding: '19px 21px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 18, flexWrap: 'wrap' }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 7, flexWrap: 'wrap' }}>
                      <span className="mo fine">{t.id}</span>
                      <Tag k={finished ? 'ok' : held ? 'warn' : 'ice'} dot>
                        {finished ? (t.resolution_label || 'Done') : held ? 'Waiting on you' : t.assignee ? 'Somebody is on it' : 'With the desk'}
                      </Tag>
                    </div>
                    <h2 style={{ fontSize: 16.5, fontWeight: 500, lineHeight: 1.4, letterSpacing: '-.018em' }}>
                      {t.subject}
                    </h2>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="fine">{finished ? 'Finished' : held ? 'Paused while we wait on you' : 'We should be done in'}</div>
                    <div className="h3" style={{ marginTop: 4, fontSize: 14, color: finished ? C.ok : held ? C.warn : 'var(--ink)' }}>
                      {finished ? 'Clock stopped' : held ? 'Clock stopped' : clock(remaining)}
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', margin: '19px 0 16px' }}>
                  {STEPS.map((step, i) => {
                    const on = i <= stage
                    const last = i === STEPS.length - 1
                    return (
                      <div key={step} style={{ display: 'flex', alignItems: 'center', flex: last ? '0 0 auto' : 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 7, flexShrink: 0 }}>
                          <motion.span
                            initial={{ scale: 0 }} animate={{ scale: 1 }}
                            transition={{ delay: 0.08 + i * 0.06, duration: 0.25, ease: 'easeOut' }}
                            style={{
                              width: 10, height: 10, borderRadius: '50%',
                              background: on ? colour : 'transparent',
                              boxShadow: on
                                ? `inset 0 0 0 2px ${colour}`
                                : 'inset 0 0 0 2px var(--track)',
                            }}
                          />
                          <span className="fine" style={{ color: on ? 'var(--ink2)' : 'var(--ink4)', whiteSpace: 'nowrap' }}>
                            {step}
                          </span>
                        </div>
                        {!last ? (
                          <div style={{
                            flex: 1, height: 2, margin: '0 8px 18px', borderRadius: 1,
                            background: i < stage ? colour : 'var(--track)',
                          }} />
                        ) : null}
                      </div>
                    )
                  })}
                </div>

                {held ? (
                  <div className="slab" style={{ padding: '13px 15px' }}>
                    <p className="p" style={{ margin: 0, lineHeight: 1.6 }}>{t.hold_reason}</p>
                  </div>
                ) : null}

                <div style={{ display: 'flex', gap: 9, marginTop: 14, flexWrap: 'wrap', alignItems: 'center' }}>
                  {!finished ? (
                    <button
                      className="b b-s"
                      onClick={() => toast?.('Adding to a request is not wired yet — the desk sees it in the thread')}
                    >Add something</button>
                  ) : null}
                  {held ? <span className="mt" style={{ color: C.warn }}>They are waiting on your answer</span> : null}
                </div>
              </article>
            )
          })}
          {shown.length === 0 ? (
            <p className="mt">
              {which === 'open'
                ? 'Nothing open. Everything you asked for is done.'
                : 'Nothing finished yet.'}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  )
}
