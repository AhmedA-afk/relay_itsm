import { useEffect, useState } from 'react'
import { Bot, Clock3, Copy, ListFilter, Siren, Sparkles } from 'lucide-react'
import { Button } from '@/components/kit/button'
import { Notice } from '@/components/blocks'
import { AnimatePresence, motion } from 'motion/react'
import { api } from '../lib/api'
import { Icon, Meter, Mood, Ring, Sev, Tabs, Tag } from '../components/ui'
import { C, burnFor, clock, heat, initials, moodColour, moodLabel, priorityColour, remainingFor, riskColour, riskLabel } from '../lib/format'

const TABS = [
  { k: 'talk', name: 'Conversation' },
  { k: 'work', name: 'Work' },
  { k: 'time', name: 'Clocks' },
  { k: 'near', name: 'Nearby' },
  { k: 'log', name: 'History' },
]

const STATUS = {
  new: ['Unclaimed', 'warn'],
  assigned: ['Assigned', 'ice'],
  in_progress: ['Live', 'ice'],
  on_hold: ['Held, waiting on them', 'mute'],
  resolved: ['Resolved', 'ok'],
  closed: ['Closed', 'mute'],
}


const ENGINES = [
  ['jev', 'Jev', Sparkles, 'One Choice question per half, options built from the live roster'],
  ['ai', 'AI', Bot, 'The same two questions as prompts to Gemini 3.8 Flash'],
  ['rules', 'Rules', ListFilter, 'Keyword rules for the department, fewest open tickets for the person'],
]

/**
 * Routing, on a real ticket rather than on typed words.
 *
 * Suggests first and writes only when asked. The department half is skipped
 * when the ticket already has one, and whatever comes back is checked against
 * the roster by the server before anything is written — a suggested name that
 * is on leave or on another team is refused rather than trusted.
 */
function Routing({ ticket, meta, run, busy, onGo }) {
  const [engine, setEngine] = useState('jev')
  const [got, setGot] = useState(null)
  const [asking, setAsking] = useState(false)
  const [failed, setFailed] = useState(null)

  const teamName = (key) => meta?.teams?.find((t) => t.key === key)?.name ?? key
  const ask = async () => {
    setAsking(true)
    setFailed(null)
    try {
      const out = await api.route(ticket.id, engine, false)
      setGot(out)
      if (out.error) setFailed(out.error)
    } catch (e) {
      setFailed(e.message)
    } finally {
      setAsking(false)
    }
  }

  const note = (half) => got?.[half]?.detail?.note
  const passedOver = got?.person?.detail?.instead_of

  return (
    <div style={{ padding: '16px 16px 15px', borderBottom: '1px solid var(--edge)' }}>
      <h2 className="h2">Where it should go</h2>
      <p className="fine" style={{ margin: '5px 0 10px' }}>
        {ticket.team
          ? `Already with ${teamName(ticket.team)}, so only the owner is decided.`
          : 'Nobody has placed this yet: both halves are open.'}
      </p>

      <div className="kv" style={{ gridTemplateColumns: '68px minmax(0,1fr)' }}>
        <span className="fine">Department</span>
        <span className="h3" style={{ fontWeight: 500 }}>{ticket.team ? teamName(ticket.team) : 'None'}</span>
      </div>
      <div className="kv" style={{ gridTemplateColumns: '68px minmax(0,1fr)' }}>
        <span className="fine">On it</span>
        <span className="h3" style={{ fontWeight: 500 }}>{ticket.assignee ?? 'Nobody'}</span>
      </div>

      <div style={{ display: 'flex', gap: 5, margin: '12px 0 9px' }}>
        {ENGINES.map(([key, name, Glyph, how]) => (
          <button
            key={key} className="b b-s" title={how} aria-pressed={engine === key}
            onClick={() => { setEngine(key); setGot(null); setFailed(null) }}
            style={engine === key
              ? { borderColor: 'color-mix(in srgb, var(--ice) 45%, transparent)', color: C.ice }
              : undefined}
          >
            <Glyph size={13} strokeWidth={1.9} />
            <span style={{ marginLeft: 5 }}>{name}</span>
          </button>
        ))}
      </div>

      <button className="b b-s" disabled={busy || asking} onClick={ask} style={{ width: '100%' }}>
        {asking ? 'Asking…' : got ? 'Ask again' : 'Ask where it should go'}
      </button>

      {failed ? (
        <p className="fine" style={{ margin: '10px 0 0', color: C.crit }}>{failed}</p>
      ) : null}

      {got?.suggestion ? (
        <div className="slab" style={{ padding: '13px 14px', marginTop: 11 }}>
          <div className="kv" style={{ gridTemplateColumns: '68px minmax(0,1fr)' }}>
            <span className="fine">Department</span>
            <span className="h3" style={{ fontWeight: 500 }}>
              {teamName(got.suggestion.team)}
              {got.team?.kept ? <span className="fine" style={{ marginLeft: 6 }}>kept</span> : null}
            </span>
          </div>
          <div className="kv" style={{ gridTemplateColumns: '68px minmax(0,1fr)' }}>
            <span className="fine">Owner</span>
            <span className="h3" style={{ fontWeight: 500 }}>
              {got.suggestion.person_name}
              {got.suggestion.confidence != null ? (
                <span className="mo fine" style={{ marginLeft: 7 }}>
                  {Math.round(got.suggestion.confidence * 100)}%
                </span>
              ) : null}
            </span>
          </div>

          {note('team') && !got.team?.kept ? (
            <p className="fine" style={{ margin: '9px 0 0', lineHeight: 1.5 }}>{note('team')}</p>
          ) : null}
          {note('person') ? (
            <p className="fine" style={{ margin: '6px 0 0', lineHeight: 1.5 }}>{note('person')}</p>
          ) : null}
          {passedOver ? (
            <p className="fine" style={{ margin: '8px 0 0', lineHeight: 1.5, color: C.ice }}>
              Passed over {passedOver.name}: {passedOver.why}.
            </p>
          ) : null}

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginTop: 12 }}>
            <span className="mo fine">
              {got.latency_ms ? `${Math.round(got.latency_ms)} ms` : '—'}
              {got.cost_usd ? ` · $${got.cost_usd.toFixed(7).replace(/0+$/, '')}` : ' · free'}
            </span>
            <button
              className="b b-s b-go" disabled={busy}
              onClick={() => run(
                () => api.route(ticket.id, engine, true),
                `${ticket.id} to ${got.suggestion.person_name}`,
              ).then(() => setGot(null))}
            >Apply it</button>
          </div>
        </div>
      ) : null}

      <p className="fine" style={{ margin: '10px 0 0', lineHeight: 1.5 }}>
        Applying writes both halves with the engine as the actor and its own reason, so the
        {' '}
        <button
          className="b-bare" onClick={() => onGo?.('people')}
          style={{ padding: 0, border: 0, background: 'none', font: 'inherit', color: C.ice, cursor: 'pointer' }}
        >roster</button>
        {' '}and the history below both show what decided it.
      </p>
    </div>
  )
}


const MOOD_ENGINES = [['jev', 'Jev'], ['ai', 'AI'], ['lexicon', 'Words']]

/**
 * How the requester sounds, read from the whole thread.
 *
 * The only number in Relay that is stored rather than derived, so this is the
 * only panel that has to answer "as of when". It shows what it read and how
 * many messages have landed since, and marks itself stale rather than quietly
 * ageing.
 */
function Sentiment({ ticket, run, busy }) {
  const [engine, setEngine] = useState('jev')
  const [asking, setAsking] = useState(false)
  const [failed, setFailed] = useState(null)
  const s = ticket.sentiment

  const read = async () => {
    setAsking(true)
    setFailed(null)
    try {
      await run(() => api.sentiment(ticket.id, engine))
    } catch (e) {
      setFailed(e.message)
    } finally {
      setAsking(false)
    }
  }

  return (
    <div style={{ padding: '16px 16px 15px', borderBottom: '1px solid var(--edge)' }}>
      <h2 className="h2">How they sound</h2>
      <p className="fine" style={{ margin: '5px 0 10px' }}>
        Read from the whole conversation, 1 unhappiest to 5 happiest.
      </p>

      {s ? (
        <>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
            <span style={{
              fontSize: 27, fontWeight: 600, letterSpacing: '-.04em',
              color: moodColour(s.level), fontVariantNumeric: 'tabular-nums',
            }}>{s.score.toFixed(1)}</span>
            <span className="h3" style={{ fontWeight: 500 }}>{moodLabel(s.level)}</span>
            {s.confidence != null ? (
              <span className="mo fine">{Math.round(s.confidence * 100)}% sure</span>
            ) : null}
          </div>

          {s.probabilities ? (
            <div style={{ display: 'flex', gap: 3, marginTop: 11 }} aria-hidden="true">
              {['1', '2', '3', '4', '5'].map((k) => (
                <span key={k} style={{ flex: 1 }} title={`${Math.round((s.probabilities[k] ?? 0) * 100)}% on ${k}`}>
                  <span style={{
                    display: 'block', height: 4, borderRadius: 2,
                    background: moodColour(Number(k)),
                    opacity: 0.18 + 0.82 * (s.probabilities[k] ?? 0),
                  }} />
                </span>
              ))}
            </div>
          ) : null}

          {s.note ? (
            <p className="fine" style={{ margin: '10px 0 0', lineHeight: 1.5 }}>{s.note}</p>
          ) : null}

          {s.stale ? (
            <div className="slab" style={{ padding: '10px 12px', marginTop: 11 }}>
              <span className="fine" style={{ color: C.warn }}>
                Read {s.messages_read} message{s.messages_read === 1 ? '' : 's'} ago; there
                {s.messages_now - s.messages_read === 1 ? ' is 1 more' : ` are ${s.messages_now - s.messages_read} more`} now.
                This number is out of date.
              </span>
            </div>
          ) : null}

          <p className="fine mo" style={{ margin: '10px 0 0' }}>
            {s.engine === 'lexicon' ? 'word lists' : s.model || s.engine}
            {s.cost_usd ? ` · $${s.cost_usd.toFixed(7).replace(/0+$/, '')}` : ' · free'}
            {s.latency_ms ? ` · ${Math.round(s.latency_ms)} ms` : ''}
          </p>
        </>
      ) : (
        <p className="fine" style={{ margin: '0 0 10px', lineHeight: 1.5 }}>
          Nobody has read this thread yet. A survey would ask them weeks after it closed; this
          reads what they already wrote.
        </p>
      )}

      <div style={{ display: 'flex', gap: 5, margin: '12px 0 8px' }}>
        {MOOD_ENGINES.map(([key, name]) => (
          <button
            key={key} className="b b-s" aria-pressed={engine === key}
            onClick={() => setEngine(key)}
            style={engine === key
              ? { borderColor: 'color-mix(in srgb, var(--ice) 45%, transparent)', color: C.ice }
              : undefined}
          >{name}</button>
        ))}
      </div>
      <button className="b b-s" disabled={busy || asking} onClick={read} style={{ width: '100%' }}>
        {asking ? 'Reading…' : s ? 'Read it again' : 'Read the thread'}
      </button>
      {failed ? <p className="fine" style={{ margin: '9px 0 0', color: C.crit }}>{failed}</p> : null}
    </div>
  )
}


const RISK_ENGINES = [['jev', 'Jev'], ['ai', 'AI'], ['sla', 'SLA rules']]

/**
 * Whether this ticket is going to blow up.
 *
 * The only panel that predicts rather than reads, which changes two things.
 * The probability is the model's and the line it is judged against is policy's,
 * so the band can move without anyone touching a prompt. And it goes stale on
 * the clock as well as on messages — a prediction about the future is
 * undermined by time passing on its own, so the two causes are named apart.
 */
function Escalation({ ticket, run, busy }) {
  const [engine, setEngine] = useState('jev')
  const [asking, setAsking] = useState(false)
  const [failed, setFailed] = useState(null)
  const r = ticket.escalation

  const ask = async () => {
    setAsking(true)
    setFailed(null)
    try {
      await run(() => api.escalation(ticket.id, engine))
    } catch (e) {
      setFailed(e.message)
    } finally {
      setAsking(false)
    }
  }

  return (
    <div style={{ padding: '16px 16px 15px', borderBottom: '1px solid var(--edge)' }}>
      <h2 className="h2">Will this escalate?</h2>
      <p className="fine" style={{ margin: '5px 0 10px' }}>
        The chance it gets handed on or taken over somebody&rsquo;s head before it is resolved.
      </p>

      {r ? (
        <>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
            <span style={{
              fontSize: 27, fontWeight: 600, letterSpacing: '-.04em',
              color: riskColour(r.band), fontVariantNumeric: 'tabular-nums',
            }}>{Math.round(r.probability * 100)}%</span>
            <span className="h3" style={{ fontWeight: 500 }}>{riskLabel(r.band)}</span>
          </div>

          <div style={{ marginTop: 11 }} aria-hidden="true">
            <span style={{ display: 'block', height: 4, borderRadius: 2, background: 'var(--track)', position: 'relative' }}>
              <span style={{
                position: 'absolute', inset: '0 auto 0 0', width: `${Math.min(100, r.probability * 100)}%`,
                borderRadius: 2, background: riskColour(r.band),
              }} />
            </span>
          </div>

          {r.note ? (
            <p className="fine" style={{ margin: '10px 0 0', lineHeight: 1.5 }}>{r.note}</p>
          ) : null}

          {r.stale ? (
            <div className="slab" style={{ padding: '10px 12px', marginTop: 11 }}>
              <span className="fine" style={{ color: C.warn }}>
                {r.clock_moved
                  ? `Asked when ${Math.round(r.burn_then * 100)}% of the target was gone; it is ${Math.round(r.burn_now * 100)}% now.`
                  : `Asked before the last ${r.messages_now - r.messages_read} message${r.messages_now - r.messages_read === 1 ? '' : 's'}.`}
                {' '}A prediction ages even when nobody says anything.
              </span>
            </div>
          ) : null}

          <p className="fine mo" style={{ margin: '10px 0 0' }}>
            {r.engine === 'sla' ? 'SLA rules' : r.model || r.engine}
            {r.cost_usd ? ` · $${r.cost_usd.toFixed(7).replace(/0+$/, '')}` : ' · free'}
            {r.latency_ms ? ` · ${Math.round(r.latency_ms)} ms` : ''}
          </p>
        </>
      ) : (
        <p className="fine" style={{ margin: '0 0 10px', lineHeight: 1.5 }}>
          Nothing has predicted this one. The SLA rules will tell you it has breached; this is the
          question of whether it is about to.
        </p>
      )}

      <div style={{ display: 'flex', gap: 5, margin: '12px 0 8px' }}>
        {RISK_ENGINES.map(([key, name]) => (
          <button
            key={key} className="b b-s" aria-pressed={engine === key}
            onClick={() => setEngine(key)}
            style={engine === key
              ? { borderColor: 'color-mix(in srgb, var(--ice) 45%, transparent)', color: C.ice }
              : undefined}
          >{name}</button>
        ))}
      </div>
      <button className="b b-s" disabled={busy || asking} onClick={ask} style={{ width: '100%' }}>
        {asking ? 'Asking…' : r ? 'Ask again' : 'Predict it'}
      </button>
      {failed ? <p className="fine" style={{ margin: '9px 0 0', color: C.crit }}>{failed}</p> : null}
    </div>
  )
}


const DUP_ENGINES = [['jev', 'Jev'], ['ai', 'AI'], ['similar', 'Words']]
const DUP_ACTION = {
  same_request: 'Close as duplicate',
  same_fault: 'Link to the parent',
  known_problem: 'Attach to the problem',
}

/**
 * Has the desk got this already?
 *
 * Two halves, shown as two halves: what code shortlisted and why, then what
 * the judgment made of each one. The three relationships get three different
 * buttons, because they have three different consequences — and the one that
 * closes a ticket is never the default.
 */
function Duplicates({ ticket, run, busy }) {
  const [engine, setEngine] = useState('jev')
  const [got, setGot] = useState(null)
  const [asking, setAsking] = useState(false)
  const [failed, setFailed] = useState(null)
  const [shortlist, setShortlist] = useState(false)

  const look = async () => {
    setAsking(true)
    setFailed(null)
    try {
      const out = await api.duplicates(ticket.id, engine)
      setGot(out)
      if (out.error) setFailed(out.error)
    } catch (e) {
      setFailed(e.message)
    } finally {
      setAsking(false)
    }
  }

  if (ticket.duplicate_of) {
    return (
      <div style={{ padding: '16px 16px 15px', borderBottom: '1px solid var(--edge)' }}>
        <h2 className="h2">Already linked</h2>
        <p className="fine" style={{ margin: '5px 0 0', lineHeight: 1.5 }}>
          This is the same thing as <span className="mo">{ticket.duplicate_of}</span>.
          {ticket.status === 'resolved'
            ? ' It was closed against it; the other one carries on.'
            : ' It stays open, because whoever raised it still needs telling when it is fixed.'}
        </p>
      </div>
    )
  }

  return (
    <div style={{ padding: '16px 16px 15px', borderBottom: '1px solid var(--edge)' }}>
      <h2 className="h2">Have we got this already?</h2>
      <p className="fine" style={{ margin: '5px 0 10px', lineHeight: 1.5 }}>
        Code narrows the queue to a handful; the engine says what each one actually is.
      </p>

      {ticket.linked?.length ? (
        <div className="slab" style={{ padding: '11px 13px', marginBottom: 11 }}>
          <span className="fine">
            {ticket.linked.length} other {ticket.linked.length === 1 ? 'person has' : 'people have'} reported
            this: {ticket.linked.map((c) => c.id).join(', ')}. They stay open until this one is fixed.
          </span>
        </div>
      ) : null}

      <div style={{ display: 'flex', gap: 5, marginBottom: 8 }}>
        {DUP_ENGINES.map(([key, name]) => (
          <button
            key={key} className="b b-s" aria-pressed={engine === key}
            onClick={() => { setEngine(key); setGot(null); setFailed(null) }}
            style={engine === key
              ? { borderColor: 'color-mix(in srgb, var(--ice) 45%, transparent)', color: C.ice }
              : undefined}
          >{name}</button>
        ))}
      </div>
      <button className="b b-s" disabled={busy || asking} onClick={look} style={{ width: '100%' }}>
        {asking ? 'Comparing…' : got ? 'Look again' : 'Look for duplicates'}
      </button>

      {failed ? <p className="fine" style={{ margin: '9px 0 0', color: C.crit }}>{failed}</p> : null}

      {got && !got.error ? (
        <>
          <p className="fine" style={{ margin: '11px 0 0', lineHeight: 1.5 }}>{got.note}</p>

          {got.matches.map((match) => (
            <div key={match.id} className="slab" style={{ padding: '12px 13px', marginTop: 9 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                <span className="mo" style={{ fontSize: 12 }}>{match.id}</span>
                <span className="h3" style={{ fontWeight: 500 }}>{match.label}</span>
                {match.probability != null ? (
                  <span className="mo fine">{Math.round(match.probability * 100)}%</span>
                ) : null}
              </div>
              <p className="fine" style={{ margin: '5px 0 0', lineHeight: 1.45 }}>{match.subject}</p>
              <button
                className={match.relation === 'same_request' ? 'b b-s' : 'b b-s b-go'}
                style={{ marginTop: 10, width: '100%' }}
                disabled={busy}
                onClick={() => run(
                  () => api.link(ticket.id, match.id, match.relation),
                  `${ticket.id} linked to ${match.id}`,
                ).then(() => setGot(null))}
              >{DUP_ACTION[match.relation]}</button>
            </div>
          ))}

          <button
            className="b b-s b-bare" style={{ marginTop: 10, width: '100%' }}
            onClick={() => setShortlist((v) => !v)}
          >
            {shortlist ? 'Hide' : 'Show'} the {got.asked} code shortlisted
          </button>
          {shortlist ? (
            <div style={{ marginTop: 8 }}>
              {got.shortlisted.map((c) => (
                <div key={c.id} className="kv" style={{ gridTemplateColumns: '72px minmax(0,1fr)' }}>
                  <span className="mo fine">{c.id}</span>
                  <span className="fine" style={{ lineHeight: 1.4 }}>{c.kept_because}</span>
                </div>
              ))}
              <p className="fine" style={{ margin: '8px 0 0', lineHeight: 1.5 }}>
                {got.asked} candidates, {got.asked} questions, one request
                {got.cost_usd ? ` · $${got.cost_usd.toFixed(7).replace(/0+$/, '')}` : ' · free'}
                {got.latency_ms ? ` · ${Math.round(got.latency_ms)} ms` : ''}
              </p>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  )
}

export default function Ticket({ id, now, meta, onBack, onGo, onAction, toast }) {
  const [ticket, setTicket] = useState(null)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('talk')
  const [mode, setMode] = useState('public')
  const [why, setWhy] = useState(false)
  const [gate, setGate] = useState(false)
  const [code, setCode] = useState('')
  const [note, setNote] = useState('')
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  const load = async () => {
    try { setTicket(await api.ticket(id)) } catch (e) { setError(e.message) }
  }
  useEffect(() => { load() }, [id])

  if (error) return <div className="pad"><p className="mt">{error}</p></div>
  if (!ticket) return <div className="pad"><p className="mt">Loading {id}…</p></div>

  const run = async (fn, message) => {
    setBusy(true)
    try {
      await fn()
      await load()
      onAction?.()
      if (message) toast?.(message)
    } catch (e) {
      toast?.(e.message)
    } finally {
      setBusy(false)
    }
  }

  const status = STATUS[ticket.status] ?? [ticket.status, 'mute']
  const incident = ticket.kind === 'incident'
  const remaining = remainingFor(ticket, now)
  const burn = burnFor(ticket, now)
  const colour = heat(burn, remaining < 0)
  const outbound = mode === 'public'
  const codes = meta?.resolution_codes ?? []

  const suggestions = [
    ['Impact', ticket.impact, 3],
    ['Urgency', ticket.urgency, 3],
    ['Category', ticket.category, 2],
    ['Team', ticket.team, 2],
  ]
  const facts = [
    ['Raised by', ticket.requester || 'Not recorded in the source'],
    ['Where', ticket.department],
    ['Category', ticket.category],
    ['Team', ticket.team],
    ['On it', ticket.assignee ?? 'Nobody'],
    ['Service', ticket.service],
    ['Systems', ticket.affected_ci || 'none recorded'],
    ...(ticket.problem_id ? [['Problem', ticket.problem_id]] : []),
    ...(ticket.resolution_label ? [['Fixed by', ticket.resolution_label]] : []),
    ...(ticket.reopened_count ? [['Reopened', `${ticket.reopened_count} time${ticket.reopened_count > 1 ? 's' : ''}`]] : []),
    ['Record type', incident ? 'Incident, something broke' : 'Request, someone asked'],
  ]

  const messages = ticket.messages ?? []
  const events = ticket.events ?? []

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 308px', height: '100%', minHeight: 0 }}>
      <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0, borderRight: '1px solid var(--edge)' }}>
        <div style={{ padding: '16px 20px 0', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <button className="b b-s b-bare fine" onClick={onBack}>Back to the list</button>
            <span className="mo fine">{ticket.id}</span>
            {remaining < 0 && ticket.status !== 'resolved' ? (
              <Tag k="crit" dot pulse>Past target by {clock(remaining).replace('+', '')}</Tag>
            ) : null}
            {ticket.status === 'resolved' ? <Tag k="ok" dot>Fixed, clock stopped</Tag> : null}
          </div>

          <motion.h1
            layoutId={`subject-${ticket.id}`} className="h1"
            style={{ marginTop: 10, fontSize: 24, lineHeight: 1.2 }}
          >{ticket.subject}</motion.h1>

          {ticket.major && ticket.status !== 'resolved' ? (
            <Notice className="mt-3.5" tone="crit" icon={Siren} title="Major incident">
              Hourly updates to the business, and it outranks everything else.
            </Notice>
          ) : null}

          {ticket.hold_reason ? (
            <Notice
              className="mt-3.5" tone="warn" icon={Clock3} title="On hold"
              action={
                <Button variant="outline" size="sm" disabled={busy}
                  onClick={() => run(() => api.unhold(ticket.id), `${ticket.id} back in progress`)}
                >Take it off hold</Button>
              }
            >
              {ticket.hold_reason}. The fix clock is paused; the reply clock is not.
            </Notice>
          ) : null}

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
            <Tag k={status[1]} dot>{status[0]}</Tag>
            {!ticket.assignee ? (
              <button className="b b-go" disabled={busy}
                onClick={() => run(() => api.claim(ticket.id), `${ticket.id} is yours`)}
              >Claim it</button>
            ) : (
              <button className="b" disabled={busy}
                onClick={() => run(() => api.unassign(ticket.id), `${ticket.id} handed back`)}
              >Hand it back</button>
            )}
            {ticket.status === 'resolved' ? (
              <button className="b" disabled={busy}
                onClick={() => run(() => api.reopen(ticket.id), `${ticket.id} reopened`)}
              >Reopen it</button>
            ) : (
              <button className="b" disabled={busy} onClick={() => { setGate(true); setCode(''); setNote('') }}>
                Mark it fixed
              </button>
            )}
            {incident ? (
              <button
                className="b" disabled={busy}
                style={ticket.major ? { borderColor: 'color-mix(in srgb, var(--crit) 45%, transparent)', color: C.crit } : undefined}
                onClick={() => run(
                  () => api.setMajor(ticket.id, !ticket.major),
                  ticket.major ? `${ticket.id} stood down` : `${ticket.id} declared a major incident`,
                )}
              >{ticket.major ? 'Stand down the major' : 'Call it a major incident'}</button>
            ) : null}
            {!ticket.hold_reason && ticket.status !== 'resolved' ? (
              <button className="b" disabled={busy}
                onClick={() => run(() => api.hold(ticket.id, 'Waiting on the caller'), `${ticket.id} put on hold`)}
              >Put it on hold</button>
            ) : null}
            <button className="b" onClick={() => onGo('problems')}>
              {ticket.problem_id ? `Linked to ${ticket.problem_id}` : 'Attach to a problem'}
            </button>
          </div>

          <div style={{ marginTop: 14 }}>
            <Tabs
              id="ticket-tabs" value={tab} onChange={setTab}
              items={TABS.map((t) => ({
                ...t,
                n: t.k === 'talk' ? messages.length : t.k === 'log' ? events.length : 0,
              }))}
            />
          </div>
        </div>

        <AnimatePresence>
          {gate ? (
            <motion.div
              key="gate" initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }}
              style={{ overflow: 'hidden', flexShrink: 0 }}
            >
              <div style={{
                margin: '14px 20px 0', padding: '18px 20px', borderRadius: 14,
                background: 'var(--g1)',
                boxShadow: 'inset 0 1px 0 var(--lit), inset 0 0 0 1px var(--edge)',
              }}>
                <h2 className="h2">How was it fixed?</h2>
                <p className="p" style={{ margin: '6px 0 0', maxWidth: 560, lineHeight: 1.6 }}>
                  Nothing closes without this. A month from now the only way to know whether the
                  cause was dealt with or merely stepped around is what gets picked here.
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 16 }}>
                  {codes.map((rc) => {
                    const on = code === rc.code
                    return (
                      <button
                        key={rc.code} onClick={() => setCode(rc.code)}
                        style={{
                          display: 'flex', gap: 12, alignItems: 'flex-start', textAlign: 'left',
                          padding: '12px 14px', borderRadius: 11, cursor: 'pointer',
                          background: on ? 'var(--ice-wash)' : 'var(--g1)',
                          boxShadow: `inset 0 0 0 1px ${on ? 'color-mix(in srgb, var(--ice) 40%, transparent)' : 'var(--edge)'}`,
                        }}
                      >
                        <span style={{
                          width: 13, height: 13, borderRadius: '50%', marginTop: 3, flexShrink: 0,
                          background: on ? C.ice : 'transparent',
                          boxShadow: on
                            ? `inset 0 0 0 2px ${C.ice}`
                            : 'inset 0 0 0 2px var(--track)',
                        }} />
                        <span>
                          <span className="h3" style={{ display: 'block' }}>{rc.label}</span>
                          {rc.needs_problem ? (
                            <span className="p" style={{ display: 'block', marginTop: 3, lineHeight: 1.5 }}>
                              Service is usable again but the cause is still there.
                            </span>
                          ) : null}
                        </span>
                      </button>
                    )
                  })}
                </div>

                {codes.find((c) => c.code === code)?.needs_problem ? (
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 10, marginTop: 13, padding: '11px 14px',
                    borderRadius: 11, background: 'color-mix(in srgb, var(--warn) 8%, transparent)', flexWrap: 'wrap',
                    boxShadow: 'inset 0 0 0 1px color-mix(in srgb, var(--warn) 30%, transparent)',
                  }}>
                    <Icon n="alert" s={14} c={C.warn} w={1.9} />
                    <span className="mt">
                      A workaround leaves the cause in place, so this wants a problem record
                      {ticket.problem_id ? `, and ${ticket.problem_id} is already open for it` : ''}.
                    </span>
                  </div>
                ) : null}

                <input
                  className="field" value={note} onChange={(e) => setNote(e.target.value)}
                  placeholder="What did you actually do? (optional, but the next person will thank you)"
                  style={{
                    width: '100%', marginTop: 13, height: 36, padding: '0 12px', borderRadius: 10,
                    background: 'var(--g1)', border: '1px solid var(--edge)', color: 'var(--ink)',
                  }}
                />

                <div style={{ display: 'flex', gap: 9, marginTop: 17, flexWrap: 'wrap', alignItems: 'center' }}>
                  <button
                    className={code ? 'b b-go' : 'b'} disabled={!code || busy}
                    style={code ? undefined : { opacity: 0.45, cursor: 'not-allowed' }}
                    onClick={() => run(
                      () => api.resolve(ticket.id, code, note),
                      `${ticket.id} closed`,
                    ).then(() => setGate(false))}
                  >Close it</button>
                  <button className="b b-bare" onClick={() => setGate(false)}>Not yet</button>
                  {!code ? <span className="fine">Pick a reason to enable closing</span> : null}
                </div>
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>

        <div className="scroll" style={{ padding: '18px 20px' }}>
          <AnimatePresence initial={false} mode="popLayout">
            <motion.div
              key={tab} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }} transition={{ duration: 0.15 }}
            >
              {tab === 'talk' ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {messages.map((m) => (
                    <div className="msg" key={m.id}>
                      <div className="av" style={m.visibility === 'draft' ? { background: 'none', boxShadow: 'inset 0 0 0 1px var(--edge2)' } : undefined}>
                        {m.visibility === 'draft' ? <Icon n="doc" s={13} c="var(--ink4)" /> : initials(m.author)}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', gap: 9, alignItems: 'baseline', marginBottom: 6, flexWrap: 'wrap' }}>
                          <span className="h3">
                            {m.visibility === 'draft' ? 'Drafted reply, not sent' : m.author}
                          </span>
                          {m.visibility === 'internal' ? (
                            <Tag k="warn"><Icon n="lock" s={10} w={2} />Team only</Tag>
                          ) : null}
                          <span className="fine">{new Date(m.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                        </div>
                        <div className={`say ${m.visibility === 'internal' ? 'in' : ''} ${m.visibility === 'draft' ? 'dr' : ''}`}>
                          {m.review_state ? (
                            <div style={{
                              display: 'flex', alignItems: 'center', gap: 9, padding: '10px 14px',
                              background: 'color-mix(in srgb, var(--hot) 10%, transparent)',
                              borderBottom: '1px solid color-mix(in srgb, var(--hot) 30%, transparent)',
                              flexWrap: 'wrap',
                            }}>
                              <Icon n="alert" s={14} c={C.hot} w={1.9} />
                              <span className="h3" style={{ color: C.hot }}>Held for a human</span>
                              <span className="mt">{m.review_reason}</span>
                            </div>
                          ) : null}
                          <div style={m.review_state ? { padding: '13px 15px', lineHeight: 1.65, color: 'var(--ink2)' } : undefined}>
                            {m.body}
                          </div>
                          {m.review_state ? (
                            <div style={{ display: 'flex', gap: 8, padding: '0 15px 14px', flexWrap: 'wrap', alignItems: 'center' }}>
                              <button
                                className="b b-s"
                                onClick={() => toast?.('Draft editing lands with the guard slot — nothing sent yet')}
                              >Edit, then send</button>
                              <button
                                className="b b-s b-bare"
                                onClick={() => toast?.('Held drafts are a fixture until the guard slot is wired')}
                              >Bin it</button>
                              <span className="fine">Sending stays off until that clause changes</span>
                            </div>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  ))}
                  {messages.length === 0 ? <p className="mt">Nothing said yet.</p> : null}
                </div>
              ) : null}

              {tab === 'time' ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
                  <div className="glass" style={{ padding: 20, display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap' }}>
                    <Ring
                      v={ticket.sla.response_remaining_seconds < 0 ? 1 : 0.6}
                      c={ticket.sla.response_remaining_seconds < 0 ? C.crit : C.ok}
                      big={clock(ticket.sla.response_remaining_seconds)}
                      small={ticket.sla.response_remaining_seconds < 0 ? 'over' : 'left'}
                      label="First reply clock"
                    />
                    <div style={{ flex: 1, minWidth: 200 }}>
                      <h2 className="h2">First reply</h2>
                      <p className="p" style={{ margin: '6px 0 0', lineHeight: 1.6 }}>
                        {ticket.sla.response_minutes} minutes from when it arrived,{' '}
                        {ticket.sla.calendar === 'business' ? 'counted in working hours' : 'round the clock'}.
                      </p>
                      <p className="fine" style={{ margin: '8px 0 0' }}>
                        This clock never pauses. It is a promise about us, not about them.
                      </p>
                    </div>
                  </div>
                  <div className="glass" style={{ padding: 20, display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap' }}>
                    <Ring v={burn} c={colour} big={clock(remaining)} small={remaining < 0 ? 'over' : 'left'} delay={0.1} label="Resolution clock" />
                    <div style={{ flex: 1, minWidth: 200 }}>
                      <h2 className="h2">Getting it fixed</h2>
                      <p className="p" style={{ margin: '6px 0 0', lineHeight: 1.6 }}>
                        {Math.round(ticket.sla.resolution_minutes / 60)} hours of target,{' '}
                        {Math.round(burn * 100)} per cent of it gone.
                      </p>
                      <div style={{ marginTop: 12 }}><Meter v={burn} c={colour} n={24} /></div>
                    </div>
                  </div>
                  <p className="mt">
                    Both clocks come from rule {ticket.sla.rule_order}, {ticket.sla.rule_reason}.
                  </p>
                </div>
              ) : null}

              {tab === 'work' ? (
                <div>
                  <p className="p" style={{ margin: 0, lineHeight: 1.6 }}>
                    Tasks are not wired yet. What is wired is the thing that matters on an
                    incident: nothing closes until somebody says how it was fixed.
                  </p>
                  <p className="mt" style={{ marginTop: 14 }}>
                    No approvals on an incident either. A replay like this needs an emergency
                    change, which is what sends it to the board.
                  </p>
                  <button className="b" style={{ marginTop: 10 }} onClick={() => onGo('changes')}>
                    Raise an emergency change
                  </button>
                </div>
              ) : null}

              {tab === 'near' ? (
                <div>
                  {[
                    [ticket.problem_id, 'The standing problem behind this', 'problems'],
                    ['KB-0042', 'Replaying a failed invoice batch', 'knowledge'],
                  ].filter((x) => x[0]).map((x) => (
                    <button
                      key={x[0]} onClick={() => onGo(x[2])}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 13, width: '100%', padding: '13px 6px',
                        borderBottom: '1px solid var(--edge)', textAlign: 'left',
                      }}
                    >
                      <span className="mo fine" style={{ width: 64, flexShrink: 0 }}>{x[0]}</span>
                      <span style={{ flex: 1, fontSize: 13 }}>{x[1]}</span>
                      <Icon n="next" s={13} c="var(--ink4)" />
                    </button>
                  ))}
                  {!ticket.problem_id ? (
                    <p className="mt" style={{ marginTop: 12 }}>No problem record links to this one yet.</p>
                  ) : null}
                </div>
              ) : null}

              {tab === 'log' ? (
                <div>
                  {events.map((e) => {
                    const colourOf = e.actor_kind === 'person' ? C.ice : e.actor_kind === 'judgment' ? C.hot : 'var(--ink4)'
                    return (
                      <div key={e.id} style={{
                        display: 'grid', gridTemplateColumns: '58px 104px minmax(0,1fr)', gap: 13,
                        padding: '11px 0', borderBottom: '1px solid var(--edge)', alignItems: 'baseline',
                      }}>
                        <span className="mo fine">
                          {new Date(e.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                        <span style={{ display: 'flex', alignItems: 'center', gap: 7, minWidth: 0 }}>
                          <span className="dot" style={{ color: colourOf }} />
                          <span className="tr1" style={{ fontSize: 12 }}>{e.actor}</span>
                        </span>
                        <span style={{ fontSize: 12.5 }}>
                          <strong style={{ fontWeight: 500 }}>{e.field}</strong>
                          {e.old ? <> {e.old} → </> : <> set to </>}
                          {e.new || '(cleared)'}
                          {e.reason ? <span style={{ color: 'var(--ink4)' }}>, {e.reason}</span> : null}
                        </span>
                      </div>
                    )
                  })}
                  <p className="fine" style={{ marginTop: 14 }}>
                    Every row keeps who acted and what it replaced. A judgment that gets
                    overridden leaves both values behind, which is the data that makes it
                    measurable later.
                  </p>
                </div>
              ) : null}
            </motion.div>
          </AnimatePresence>
        </div>

        <div style={{
          flexShrink: 0, borderTop: '1px solid var(--edge)', padding: '12px 20px 15px',
          background: outbound ? 'transparent' : 'color-mix(in srgb, var(--warn) 5%, transparent)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
            <div className="sw">
              <button aria-pressed={outbound} onClick={() => setMode('public')}>
                Reply to {ticket.requester ? ticket.requester.split(' ')[0] : 'the caller'}
              </button>
              <button aria-pressed={!outbound} onClick={() => setMode('internal')}>Note for the team</button>
            </div>
            <span className="fine" style={{ color: outbound ? 'var(--ink4)' : C.warn }}>
              {outbound ? 'They see this, and it stops the reply clock' : 'They never see this'}
            </span>
          </div>
          <div style={{
            border: `1px solid ${outbound ? 'var(--edge)' : 'color-mix(in srgb, var(--warn) 40%, transparent)'}`,
            borderRadius: 12, background: 'var(--g1)', padding: '12px 14px',
          }}>
            <label htmlFor="reply" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>
              Your reply
            </label>
            <input
              id="reply" value={draft} onChange={(e) => setDraft(e.target.value)}
              placeholder={outbound ? `Write to ${ticket.requester ? ticket.requester.split(' ')[0] : 'the caller'}` : 'What the team should know'}
              style={{ width: '100%', border: 0, background: 'none', fontSize: 13, outline: 'none', color: 'var(--ink)' }}
            />
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 11, gap: 8 }}>
              <span className="fine">Sends through the API and lands in the history</span>
              <button
                className={outbound ? 'b b-s b-go' : 'b b-s'} disabled={!draft.trim() || busy}
                style={draft.trim() ? undefined : { opacity: 0.45 }}
                onClick={() => run(
                  () => api.postMessage(ticket.id, draft.trim(), outbound ? 'public' : 'internal'),
                  outbound ? 'Reply sent' : 'Note saved',
                ).then(() => setDraft(''))}
              >{outbound ? 'Send' : 'Save note'}</button>
            </div>
          </div>
        </div>
      </div>

      <div className="scroll">
        {ticket.status !== 'resolved' && ticket.status !== 'closed' ? (
          <Routing ticket={ticket} meta={meta} run={run} busy={busy} onGo={onGo} />
        ) : null}
        <Sentiment ticket={ticket} run={run} busy={busy} />
        {ticket.status !== 'resolved' && ticket.status !== 'closed' ? (
          <Escalation ticket={ticket} run={run} busy={busy} />
        ) : null}
        <Duplicates ticket={ticket} run={run} busy={busy} />
        <div style={{ padding: '16px 16px 15px', borderBottom: '1px solid var(--edge)' }}>
          <h2 className="h2">How it got classified</h2>
          <p className="fine" style={{ margin: '5px 0 10px' }}>
            Read off the wording at intake. The judgment layer will write here; nothing has
            checked it yet.
          </p>
          {suggestions.map((x) => (
            <div key={x[0]} className="kv" style={{ gridTemplateColumns: '54px minmax(0,1fr) 42px' }}>
              <span className="fine">{x[0]}</span>
              <span className="tr1 h3" style={{ fontWeight: 500 }}>{x[1]}</span>
              <span style={{ display: 'flex', gap: 2.5 }} aria-label={`Confidence ${x[2]} of 3`}>
                {[1, 2, 3].map((i) => (
                  <span key={i} style={{
                    width: 10, height: 3, borderRadius: 2,
                    background: x[2] >= i ? C.ice : 'var(--track)',
                  }} />
                ))}
              </span>
            </div>
          ))}
        </div>

        <div style={{ padding: '16px 16px 24px' }}>
          <div className="kv">
            <span className="fine">Level</span>
            <span><Sev p={ticket.priority} /></span>
            <button className="b b-s" aria-expanded={why} onClick={() => setWhy(!why)}>Why</button>
          </div>
          <AnimatePresence>
            {why ? (
              <motion.div
                key="why" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.18 }} style={{ overflow: 'hidden' }}
              >
                <div className="slab" style={{ padding: '13px 14px', margin: '8px 0 10px' }}>
                  <p className="fine" style={{ margin: '0 0 9px' }}>
                    Nothing stores {ticket.priority}. The server reads it from the matrix on every request.
                  </p>
                  {[['Impact', ticket.impact], ['Urgency', ticket.urgency]].map((r) => (
                    <div key={r[0]} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, marginBottom: 7 }}>
                      <span className="mt">{r[0]}</span><span className="h3">{r[1]}</span>
                    </div>
                  ))}
                  <div className="line" style={{ margin: '3px 0 9px' }} />
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5 }}>
                    <span className="mt">Lands on</span>
                    <span className="mo h3" style={{ color: priorityColour(ticket.priority) }}>{ticket.priority}</span>
                  </div>
                  <p className="fine" style={{ margin: '9px 0 0' }}>{ticket.priority_reason}</p>
                  <button className="b b-s" style={{ marginTop: 11, width: '100%' }} onClick={() => onGo('admin')}>
                    Open the matrix
                  </button>
                </div>
              </motion.div>
            ) : null}
          </AnimatePresence>
          {facts.map((r) => (
            <div key={r[0]} className="kv" style={{ gridTemplateColumns: '78px minmax(0,1fr)' }}>
              <span className="fine">{r[0]}</span>
              <span className={r[1] === 'Nobody' ? 'tr1 nobody' : 'tr1'} style={{ fontSize: 12.5 }}>{r[1]}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
