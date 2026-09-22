import { useEffect, useMemo, useState } from 'react'
import { Siren } from 'lucide-react'
import { Button } from '@/components/kit/button'
import { Notice } from '@/components/blocks'
import { AnimatePresence, motion } from 'motion/react'
import { Icon, Meter, Mood, Risk, Sev, Tabs, Tag, Empty } from '../components/ui'
import { C, burnFor, clock, heat, initials, isLive, remainingFor } from '../lib/format'

const live = isLive

export const INCIDENT_VIEWS = [
  ['open', 'All open', (t) => live(t)],
  ['mine', 'Mine', (t) => live(t) && t.assignee === 'A. Okonkwo'],
  ['unassigned', 'Unassigned', (t) => live(t) && !t.assignee],
  ['major', 'Major', (t) => live(t) && t.major, true],
  ['breached', 'Breached', (t) => live(t) && t.sla.breached, true],
  ['hour', 'Inside the hour', (t) => live(t) && t.sla.remaining_seconds >= 0 && t.sla.remaining_seconds <= 3600, true],
  ['unhappy', 'Unhappiest', (t) => live(t) && t.sentiment && t.sentiment.level <= 2, true],
  ['risk', 'At risk', (t) => live(t) && t.escalation && t.escalation.band !== 'quiet', true],
  ['hold', 'On hold', (t) => t.status === 'on_hold'],
  ['done', 'Resolved', (t) => t.status === 'resolved'],
]

export const REQUEST_VIEWS = [
  ['open', 'All open', (t) => live(t)],
  ['mine', 'Mine', (t) => live(t) && t.assignee === 'A. Okonkwo'],
  ['unassigned', 'Unassigned', (t) => live(t) && !t.assignee],
  ['hold', 'Waiting', (t) => t.status === 'on_hold'],
  ['breached', 'Past target', (t) => live(t) && t.sla.breached, true],
  ['unhappy', 'Unhappiest', (t) => live(t) && t.sentiment && t.sentiment.level <= 2, true],
  ['risk', 'At risk', (t) => live(t) && t.escalation && t.escalation.band !== 'quiet', true],
  ['done', 'Fulfilled', (t) => t.status === 'resolved'],
]

/**
 * One record board, used by both the incident and the request module.
 *
 * Everything module-specific arrives as props: the views, the column labels,
 * the copy. Adding the next record type is configuration rather than a third
 * copy of a table.
 */
export default function Board({
  id, title, blurb, newLabel, idLabel, sumLabel, whoLabel,
  tickets, now, dense, setDense, onOpen, onClaim, busy, onNew,
  views = INCIDENT_VIEWS,
}) {
  const [view, setView] = useState(views[0][0])
  const [selected, setSelected] = useState([])
  const [cursor, setCursor] = useState(0)

  const predicate = views.find((v) => v[0] === view)?.[2] ?? (() => true)
  // Every view sorts by the clock, because that is what the desk works to.
  // The sentiment view is the one exception: there the point is who is most
  // unhappy, which is a different order from who is most late.
  const rows = useMemo(() => {
    const sorted = tickets.filter(predicate).slice()
    if (view === 'unhappy') return sorted.sort((a, b) => (a.sentiment?.score ?? 5) - (b.sentiment?.score ?? 5))
    if (view === 'risk') return sorted.sort((a, b) => (b.escalation?.probability ?? 0) - (a.escalation?.probability ?? 0))
    return sorted.sort((a, b) => a.sla.remaining_seconds - b.sla.remaining_seconds)
  }, [tickets, view])

  useEffect(() => { setCursor(0); setSelected([]) }, [view])

  useEffect(() => {
    function onKey(e) {
      if (e.target.tagName === 'INPUT' || e.metaKey || e.ctrlKey) return
      if (e.key === 'j') { e.preventDefault(); setCursor((n) => Math.min(rows.length - 1, n + 1)) }
      else if (e.key === 'k') { e.preventDefault(); setCursor((n) => Math.max(0, n - 1)) }
      else if (e.key === 'Enter' && rows[cursor]) { e.preventDefault(); onOpen(rows[cursor].id) }
      else if (e.key === 'a' && rows[cursor]) { e.preventDefault(); onClaim(rows[cursor].id) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [rows, cursor, onOpen, onClaim])

  const majors = tickets.filter((t) => t.major && live(t))
  const toggle = (ticketId) =>
    setSelected((s) => (s.includes(ticketId) ? s.filter((x) => x !== ticketId) : [...s, ticketId]))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{ padding: '20px 20px 0', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 20, flexWrap: 'wrap' }}>
          <div>
            <h1 className="h1">{title}</h1>
            <p className="lead" style={{ margin: '6px 0 0' }}>{blurb}</p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="b b-go" onClick={onNew}>{newLabel}</button>
          </div>
        </div>

        {majors.length ? (
          <Notice
            className="mt-4" tone="crit" icon={Siren}
            title={majors.length === 1 ? 'A major incident is open' : `${majors.length} major incidents are open`}
            action={<Button variant="outline" size="sm" onClick={() => setView('major')}>Show them</Button>}
          >
            Everything else waits.{' '}
            {majors.map((m, i) => (
              <span key={m.id}>{i ? ' and ' : ''}<span className="font-mono text-[12.5px] text-foreground">{m.id}</span></span>
            ))}{' '}
            need an owner and an update on the hour.
          </Notice>
        ) : null}

        <div style={{ marginTop: 16 }}>
          <Tabs
            id={id} value={view} onChange={setView}
            items={views.map((v) => ({
              k: v[0], name: v[1], n: tickets.filter(v[2]).length, hot: v[3] === true,
            }))}
          />
        </div>
      </div>

      <AnimatePresence>
        {selected.length ? (
          <motion.div
            key="bulk" initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.17 }}
            style={{ overflow: 'hidden', flexShrink: 0 }}
          >
            <div style={{
              display: 'flex', alignItems: 'center', gap: 9, padding: '10px 20px', flexWrap: 'wrap',
              background: 'var(--ice-wash)', borderBottom: '1px solid color-mix(in srgb, var(--ice) 26%, transparent)',
            }}>
              <span className="h3">{selected.length} selected</span>
              <button
                className="b b-s"
                onClick={async () => { for (const x of selected) await onClaim(x); setSelected([]) }}
              >Assign to me</button>
              <button className="b b-s b-bare" style={{ marginLeft: 'auto' }} onClick={() => setSelected([])}>
                Clear
              </button>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <div className="scroll">
        <div className={dense ? 'dense' : undefined}>
          <div className="qh">
            <div>
              <input
                id={`${id}-all`} type="checkbox" aria-label="Select every row"
                checked={rows.length > 0 && selected.length === rows.length}
                onChange={(e) => setSelected(e.target.checked ? rows.map((r) => r.id) : [])}
              />
            </div>
            <div>{idLabel}</div><div>{sumLabel}</div><div>{whoLabel}</div><div>Level</div>
            <div>Team</div><div>On it</div><div title="How satisfied the requester sounds, 1 to 5">Mood</div>
            <div title="Chance this escalates before it is resolved">Risk</div>
            <div>Target burn</div>
          </div>

          {rows.map((t, i) => {
            const remaining = remainingFor(t, now)
            const burn = burnFor(t, now)
            const colour = heat(burn, remaining < 0)
            const done = t.status === 'resolved'
            return (
              <div
                key={t.id} className="qr" data-sel={selected.includes(t.id) ? '1' : '0'}
                data-cursor={i === cursor ? '1' : '0'}
                tabIndex={0} role="button" aria-label={`${t.id}, ${t.subject}`}
                onFocus={() => setCursor(i)}
                onKeyDown={(e) => {
                  if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) {
                    e.preventDefault(); onOpen(t.id)
                  }
                }}
                onClick={() => { setCursor(i); onOpen(t.id) }}
              >
                {i === cursor ? (
                  <motion.span
                    layoutId={`${id}-cursor`} transition={{ duration: 0.15, ease: 'easeOut' }}
                    style={{
                      position: 'absolute', left: 0, top: 6, bottom: 6, width: 2, borderRadius: 2,
                      background: C.ice,
                    }}
                  />
                ) : null}
                <div>
                  <input
                    type="checkbox" aria-label={`Select ${t.id}`} checked={selected.includes(t.id)}
                    onClick={(e) => { e.stopPropagation(); toggle(t.id) }}
                    onChange={() => {}}
                  />
                </div>
                <div className="mo" style={{ fontSize: 11.5, color: 'var(--ink3)' }}>{t.id}</div>
                <div style={{ minWidth: 0, display: 'flex', alignItems: 'center', gap: 9 }}>
                  {t.major && !done ? (
                    <span title="Major incident" style={{ flexShrink: 0, display: 'inline-flex' }}>
                      <Icon n="siren" s={13} c={C.crit} w={2} />
                    </span>
                  ) : null}
                  <motion.span layoutId={`subject-${t.id}`} className="subj">{t.subject}</motion.span>
                  <span className="qa">
                    <button
                      className="b b-s" disabled={busy}
                      onClick={(e) => { e.stopPropagation(); onClaim(t.id) }}
                    >Assign to me</button>
                  </span>
                </div>
                <div className="tr1">{t.requester || <span className="nobody" title="Not recorded in the source">—</span>}</div>
                <div><Sev p={t.priority} /></div>
                <div className="mo tr1" style={{ fontSize: 11.5 }}>{t.team}</div>
                <div>
                  {t.assignee ? (
                    <span style={{ display: 'flex', alignItems: 'center', gap: 7, minWidth: 0 }}>
                      <span className="av" style={{ width: 21, height: 21, borderRadius: 7, fontSize: 9 }}>
                        {initials(t.assignee)}
                      </span>
                      <span className="tr1" style={{ fontSize: 12 }}>{t.assignee.split(' ').slice(-1)[0]}</span>
                    </span>
                  ) : (
                    <span className="tr1 nobody" style={{ fontSize: 12 }}>nobody</span>
                  )}
                </div>
                <div><Mood s={t.sentiment} /></div>
                <div><Risk r={t.escalation} /></div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {done ? (
                    <Tag k="ok"><Icon n="tick" s={11} w={2.4} />{t.resolution_label || 'Resolved'}</Tag>
                  ) : (
                    <>
                      <Meter
                        v={burn} c={colour} n={10}
                        title={`${Math.round(burn * 100)}% of the ${t.priority} target used`}
                      />
                      <span className="clk" style={{ fontSize: 12, color: colour, minWidth: 62, textAlign: 'right', flexShrink: 0, whiteSpace: 'nowrap' }}>
                        {remaining < 0 ? (
                          <span className="dot live" style={{ display: 'inline-block', color: C.crit, marginRight: 4 }} />
                        ) : null}
                        {clock(remaining)}
                      </span>
                    </>
                  )}
                </div>
              </div>
            )
          })}

          {rows.length === 0 ? (
            <div className="pad">
              <Empty
                title="Nothing in this view"
                body="Which is a good sign rather than a broken filter."
                action={<button className="b" onClick={() => setView(views[0][0])}>Show {views[0][1].toLowerCase()}</button>}
              />
            </div>
          ) : null}
        </div>
      </div>

      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14,
        padding: '9px 20px', borderTop: '1px solid var(--edge)', flexShrink: 0, flexWrap: 'wrap',
      }}>
        <div className="fine" style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <span className="kb">j</span><span className="kb">k</span> move
          <span className="kb">↵</span> open
          <span className="kb">a</span> assign to me
          <span className="kb">?</span> all keys
        </div>
        <div className="fine" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          Rows
          <div className="sw">
            <button aria-pressed={dense} onClick={() => setDense(true)}>Tight</button>
            <button aria-pressed={!dense} onClick={() => setDense(false)}>Roomy</button>
          </div>
        </div>
      </div>
    </div>
  )
}
