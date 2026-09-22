import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Empty, Icon, Meter, Tag } from '../components/ui'
import { C } from '../lib/format'
import { CalendarClock, Plus, Snowflake, TriangleAlert } from 'lucide-react'
import { Badge } from '@/components/kit/badge'
import { Button } from '@/components/kit/button'
import { Card } from '@/components/kit/card'
import { Dot, StatusBadge } from '@/components/blocks'
import { cn } from '@/lib/utils'

/** Everything read-only that hangs off the two working modules. */

function useResource(loader, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    let alive = true
    loader().then(
      (d) => { if (alive) setData(d) },
      (e) => { if (alive) setError(e.message) },
    )
    return () => { alive = false }
  }, deps)
  return { data, error }
}

function Screen({ title, lead, error, data, children, action }) {
  return (
    <div className="scroll"><div className="pad"><div className="cap">
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 18, flexWrap: 'wrap' }}>
        <div>
          <h1 className="h1">{title}</h1>
          <p className="lead" style={{ margin: '7px 0 0', maxWidth: 640 }}>{lead}</p>
        </div>
        {action}
      </div>
      {error ? <p className="mt" style={{ marginTop: 20, color: C.crit }}>{error}</p> : null}
      {!error && !data ? <p className="mt" style={{ marginTop: 20 }}>Loading…</p> : null}
      {data ? children : null}
    </div></div></div>
  )
}

export function Problems({ onGo, toast }) {
  const { data, error } = useResource(api.problems)
  return (
    <Screen
      title="Problem management" error={error} data={data}
      lead="What keeps coming back, heaviest first. Ticket count sets the order, not the date somebody raised it."
      action={
        <button
          className="b"
          onClick={() => toast?.('Problem capture is not wired — the list is read-only today')}
        >Open a problem</button>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 22 }}>
        {(data ?? []).map((p) => {
          const colour = C[p.severity] ?? C.mute
          return (
            <article key={p.id} className="glass" style={{ padding: '19px 21px' }}>
              <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                <div className="countbox" style={{ '--cc': colour }}>
                  <div className="cn">
                    {p.linked_count}
                  </div>
                  <div className="cl">{p.linked_count === 1 ? 'ticket' : 'tickets'}</div>
                </div>
                <div style={{ flex: 1, minWidth: 220 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6, flexWrap: 'wrap' }}>
                    <span className="mo fine">{p.id}</span>
                    <Tag k={p.state === 'Known error' ? 'ice' : 'mute'}>{p.state}</Tag>
                    <span className="fine">{p.since}</span>
                  </div>
                  <h2 className="h2" style={{ fontSize: 16, marginBottom: 11 }}>{p.title}</h2>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: '12px 26px' }}>
                    <div>
                      <div className="h3" style={{ marginBottom: 4 }}>Why it happens</div>
                      <p className="p" style={{ margin: 0, lineHeight: 1.55, color: p.root_cause ? 'var(--ink2)' : 'var(--ink4)' }}>
                        {p.root_cause || 'Still unknown.'}
                      </p>
                    </div>
                    <div>
                      <div className="h3" style={{ marginBottom: 4 }}>What we do meanwhile</div>
                      <p className="p" style={{ margin: 0, lineHeight: 1.55 }}>{p.workaround}</p>
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 11, marginTop: 15, paddingTop: 13, borderTop: '1px solid var(--edge)', flexWrap: 'wrap' }}>
                    <button className="b b-s b-bare" style={{ color: C.ice }} onClick={() => onGo('incidents')}>
                      {p.linked_tickets.join(', ') || 'no tickets linked'}
                    </button>
                    {p.change_id ? (
                      <button className="b b-s b-bare" style={{ color: C.ice }} onClick={() => onGo('changes')}>
                        Fix booked as {p.change_id}
                      </button>
                    ) : (
                      <span className="mt" style={{ color: C.warn }}>Nothing booked to fix it</span>
                    )}
                    <span style={{ flex: 1 }} />
                    <span className="fine">Owned by {p.owner}</span>
                  </div>
                </div>
              </div>
            </article>
          )
        })}
      </div>
    </Screen>
  )
}

const RISK_LABEL = { ok: 'Low', hot: 'Watch', crit: 'Risky', mute: 'Routine' }
const DAYS = [
  ['Mon', 21], ['Tue', 22], ['Wed', 23], ['Thu', 24], ['Fri', 25], ['Sat', 26], ['Sun', 27],
]
const TODAY = 2
const FROZEN = 4

/**
 * The change calendar as a week view: one card, hairline day columns, today's
 * date in a filled disc, the month-end freeze as hatched blocked time. Risk is
 * a colour rail on each event and a word; collisions are called out inside the
 * event that has them, so a clash is visible without opening anything.
 */
export function Changes({ toast }) {
  const { data, error } = useResource(api.changes)
  const waiting = (data ?? []).filter((c) => c.awaiting_board).length
  const risky = (data ?? []).filter((c) => c.risk === 'crit').length
  return (
    <Screen
      title="Change enablement" error={error} data={data}
      lead="Risk and collisions sit on the calendar itself, so nobody opens a change to discover it clashes with another."
      action={
        <Button onClick={() => toast?.('Change capture is not wired — the calendar is read-only today')}>
          <Plus /> Raise a change
        </Button>
      }
    >
      <Card className="mt-6 gap-0 overflow-hidden py-0 shadow-xs">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-3.5">
          <div className="flex items-baseline gap-3">
            <span className="text-[15px] font-semibold tracking-[-0.015em]">21 – 27 September</span>
            <span className="text-[13px] text-muted-foreground">
              {(data ?? []).length} changes · {risky} risky · {waiting} waiting on the board
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {['mute', 'ok', 'hot', 'crit'].map((k) => (
              <StatusBadge key={k} tone={k}>{RISK_LABEL[k]}</StatusBadge>
            ))}
          </div>
        </div>

        <div className="overflow-x-auto">
          <div className="grid min-w-[980px] grid-cols-7 divide-x">
            {DAYS.map(([name, number], index) => {
              const today = index === TODAY
              const frozen = index === FROZEN
              return (
                <div key={name} className="flex items-center justify-between gap-2 border-b px-3 py-2.5">
                  <span className={cn('text-xs font-medium uppercase tracking-wide', today ? 'text-foreground' : 'text-muted-foreground')}>{name}</span>
                  <span className="flex items-center gap-1.5">
                    {frozen ? <Badge variant="outline" className="h-5 gap-1 px-1.5 text-[11px] font-normal text-crit"><Snowflake className="size-3" />Freeze</Badge> : null}
                    <span className={cn(
                      'grid size-7 place-items-center rounded-full font-mono text-[13px] tabular-nums',
                      today ? 'bg-primary font-semibold text-primary-foreground' : 'text-foreground',
                    )}>{number}</span>
                  </span>
                </div>
              )
            })}

            {DAYS.map(([name], index) => {
              const items = (data ?? []).filter((c) => c.day_index === index)
              const today = index === TODAY
              const frozen = index === FROZEN
              return (
                <div
                  key={name}
                  className={cn('flex flex-col gap-2 p-2', today && 'bg-muted/40')}
                  style={{
                    // the week runs to the bottom of the window rather than stopping short
                    minHeight: 'max(380px, calc(100dvh - 330px))',
                    ...(frozen ? {
                      backgroundImage: 'repeating-linear-gradient(135deg, transparent 0 7px, color-mix(in srgb, var(--crit) 7%, transparent) 7px 8px)',
                    } : null),
                  }}
                >
                  {items.map((c) => {
                    const colour = C[c.risk] ?? C.mute
                    return (
                      <button
                        key={c.id}
                        onClick={() => toast?.(`${c.id} has no detail view yet — the calendar carries the state`)}
                        className={cn(
                          'relative w-full overflow-hidden rounded-lg border bg-card py-2.5 pl-3.5 pr-2.5 text-left shadow-xs transition-shadow hover:shadow-md',
                          c.collision && 'border-crit/40',
                        )}
                      >
                        <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: colour }} />
                        <span className="flex items-center justify-between gap-2">
                          <span className="whitespace-nowrap font-mono text-[11px] tabular-nums text-muted-foreground">{c.window.replace(' to ', '–')}</span>
                          <span className="text-[11px] font-medium" style={{ color: colour }}>{RISK_LABEL[c.risk]}</span>
                        </span>
                        <span className="mt-1.5 block text-[13px] font-medium leading-snug text-foreground">{c.title}</span>
                        <span className="mt-1 block font-mono text-[11px] text-muted-foreground">{c.id}</span>
                        {c.collision ? (
                          <span className="mt-2 flex items-start gap-1.5 rounded-md bg-crit/8 px-2 py-1.5 text-[11.5px] leading-snug text-crit">
                            <TriangleAlert className="mt-px size-3 shrink-0" />
                            {c.collision}
                          </span>
                        ) : null}
                        {c.awaiting_board ? (
                          <span className="mt-2 flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
                            <Dot tone="warn" /> Waiting on the board
                          </span>
                        ) : null}
                      </button>
                    )
                  })}
                  {items.length === 0 && !frozen ? (
                    <span className="px-1.5 pt-1 text-xs text-muted-foreground/70">Nothing booked</span>
                  ) : null}
                  {frozen ? (
                    <div className="m-auto max-w-[14ch] rounded-md border border-crit/25 bg-card px-3 py-2 text-center text-xs leading-snug text-crit shadow-xs">
                      Month end. Nothing ships.
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t px-5 py-3 text-[13px] text-muted-foreground">
          <span className="flex items-center gap-2"><CalendarClock className="size-4" /> The board meets Wednesday at 16:00.</span>
          <span>{waiting} {waiting === 1 ? 'change is' : 'changes are'} waiting on it.</span>
        </div>
      </Card>
    </Screen>
  )
}

const STAGES = ['Planned', 'Built', 'Tested', 'Approved', 'Deployed', 'Reviewed']

export function Releases({ onGo, toast }) {
  const { data, error } = useResource(api.releases)
  return (
    <Screen
      title="Release management" error={error} data={data}
      lead="Changes travel in groups. A release is the group, its window, and the one person answerable when it lands."
      action={
        <button
          className="b b-go"
          onClick={() => toast?.('Release planning is not wired — the list is read-only today')}
        >Plan a release</button>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 13, marginTop: 22 }}>
        {(data ?? []).map((r) => {
          const colour = C[r.risk] ?? C.ok
          return (
            <article key={r.id} className="glass" style={{ padding: '20px 22px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 18, flexWrap: 'wrap' }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 7, flexWrap: 'wrap' }}>
                    <span className="mo fine">{r.id}</span>
                    <Tag k={r.stage >= 4 ? 'ok' : r.risk}>{STAGES[r.stage]}</Tag>
                    <span className="fine">{r.window}</span>
                  </div>
                  <h2 className="h2" style={{ fontSize: 16.5 }}>{r.name}</h2>
                  <p className="p" style={{ margin: '7px 0 0', maxWidth: 560, lineHeight: 1.6 }}>{r.note}</p>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div className="fine">Answerable</div>
                  <div className="h3" style={{ marginTop: 4 }}>{r.owner}</div>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', margin: '20px 0 16px' }}>
                {STAGES.map((stage, i) => {
                  const on = i <= r.stage
                  const last = i === STAGES.length - 1
                  return (
                    <div key={stage} style={{ display: 'flex', alignItems: 'center', flex: last ? '0 0 auto' : 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 7, flexShrink: 0 }}>
                        <span style={{
                          width: 9, height: 9, borderRadius: '50%', background: on ? colour : 'transparent',
                          boxShadow: on
                            ? `inset 0 0 0 2px ${colour}`
                            : 'inset 0 0 0 2px var(--track)',
                        }} />
                        <span className="fine" style={{ color: on ? 'var(--ink2)' : 'var(--ink4)', whiteSpace: 'nowrap' }}>{stage}</span>
                      </div>
                      {!last ? (
                        <div style={{
                          flex: 1, height: 2, margin: '0 7px 18px', borderRadius: 1,
                          background: i < r.stage ? colour : 'var(--track)',
                        }} />
                      ) : null}
                    </div>
                  )
                })}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 9, paddingTop: 14, borderTop: '1px solid var(--edge)', flexWrap: 'wrap' }}>
                <span className="fine">Carries</span>
                {r.changes.map((cid) => (
                  <button key={cid} className="b b-s" onClick={() => onGo('changes')}>{cid}</button>
                ))}
                {r.changes.length === 0 ? <span className="fine">nothing yet</span> : null}
              </div>
            </article>
          )
        })}
      </div>
    </Screen>
  )
}

export function Knowledge({ toast }) {
  const { data, error } = useResource(api.articles)
  const max = Math.max(1, ...(data ?? []).map((a) => a.deflected))
  const totalDeflected = (data ?? []).reduce((n, a) => n + a.deflected, 0)
  const stale = (data ?? []).filter((a) => a.stale).length
  return (
    <Screen
      title="Knowledge base" error={error} data={data}
      lead="Ordered by how many tickets each one stopped this month, which is the only number worth acting on here."
      action={
        <button
          className="b b-go"
          onClick={() => toast?.('The KB editor is not wired — articles are read-only today')}
        >Write one</button>
      }
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(216px, 1fr))', gap: 12, marginTop: 20 }}>
        {[
          [`${totalDeflected}`, `tickets never raised, across ${(data ?? []).length} articles`],
          [`${stale}`, 'articles nobody checked this year'],
        ].map((k) => (
          <div key={k[1]} className="stat">
            <div className="sn">
              {k[0]}
            </div>
            <div className="sl">{k[1]}</div>
          </div>
        ))}
      </div>
      <div className="glass" style={{ marginTop: 14, overflow: 'hidden', padding: 0 }}>
        <div className="fine" style={{
          display: 'grid', gridTemplateColumns: '68px minmax(0,1fr) 104px 178px 104px 92px',
          gap: 12, padding: '12px 17px', borderBottom: '1px solid var(--edge)',
        }}>
          <div>Number</div><div>Title</div><div>Kept by</div><div>Last looked at</div><div>Stopped</div>
          <div style={{ textAlign: 'right' }}>State</div>
        </div>
        {(data ?? []).map((a) => (
          <div key={a.id} style={{
            display: 'grid', gridTemplateColumns: '68px minmax(0,1fr) 104px 178px 104px 92px',
            gap: 12, padding: '13px 17px', borderBottom: '1px solid var(--edge)', alignItems: 'center',
          }}>
            <div className="mo fine">{a.id}</div>
            <div className="tr1" style={{ fontSize: 13, color: 'var(--ink)' }}>{a.title}</div>
            <div className={a.owner === 'Nobody' ? 'tr1 nobody' : 'tr1'} style={{ fontSize: 12.5 }}>{a.owner}</div>
            <div className="mt" style={{ color: a.stale ? C.warn : 'var(--ink3)' }}>{a.reviewed_note}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
              <Meter v={a.deflected / max} c={C.ok} n={7} />
              <span className="mo" style={{ fontSize: 11.5 }}>{a.deflected}</span>
            </div>
            <div style={{ textAlign: 'right' }}>
              <Tag k={a.state === 'Live' ? 'ok' : a.state === 'Stale' ? 'warn' : 'mute'}>{a.state}</Tag>
            </div>
          </div>
        ))}
      </div>
    </Screen>
  )
}

export function Catalog({ onGo }) {
  const { data, error } = useResource(api.catalog)
  return (
    <Screen
      title="Service catalogue" error={error} data={data}
      lead="Grouped by what you are trying to get done rather than by which team owns it. Every wait and every approval is shown before you commit."
      action={<button className="b" onClick={() => onGo('intake')}>Not sure? Just describe it</button>}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 28, marginTop: 26 }}>
        {(data ?? []).map((group) => (
          <section key={group.name}>
            <h2 className="h2">{group.name}</h2>
            <p className="fine" style={{ margin: '4px 0 12px' }}>{group.note}</p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(256px, 1fr))', gap: 11 }}>
              {group.items.map((s) => (
                <button
                  key={s.name} className="slab" onClick={() => onGo('intake')}
                  style={{ padding: '16px 17px', textAlign: 'left', display: 'flex', flexDirection: 'column', minHeight: 132, cursor: 'pointer' }}
                >
                  <span style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                    <span className="h3" style={{ fontSize: 13.5, lineHeight: 1.35 }}>{s.name}</span>
                    <Icon n="next" s={14} c="var(--ink4)" />
                  </span>
                  <span className="p" style={{ display: 'block', marginTop: 8, lineHeight: 1.55 }}>{s.blurb}</span>
                  <span style={{ flex: 1 }} />
                  <span style={{ display: 'flex', alignItems: 'center', gap: 11, marginTop: 13, paddingTop: 12, borderTop: '1px solid var(--edge)' }}>
                    <span className="mt" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                      <Icon n="clock" s={12} />{s.turnaround}
                    </span>
                    <span className="fine" style={{ color: s.approval ? C.warn : 'var(--ink4)' }}>
                      {s.approval || 'Straight through'}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
    </Screen>
  )
}

export function Assets({ onGo }) {
  return (
    <div className="scroll"><div className="pad"><div className="cap">
      <h1 className="h1">Assets and the CMDB</h1>
      <p className="lead" style={{ margin: '7px 0 0', maxWidth: 640 }}>
        Not built, and saying so is more useful than a screen of invented laptops.
      </p>
      <div className="glass" style={{ padding: 24, marginTop: 22 }}>
        <h2 className="h2">What belongs here</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '18px 28px', marginTop: 16 }}>
          {[
            ['Configuration items and their dependencies',
              'The reason a ticket can name the systems it touches. INC-4416 already carries erp-prod-01 and pay-gw-02 as a string; those want to be real records.'],
            ['Blast radius',
              'When one item goes down, what else loses service. That answer is what turns an incident into a major incident, so this feeds the module built first.'],
            ['Hardware and software lifecycle',
              'Purchase, warranty, licence counts, end of life. Mostly finance and compliance work rather than service desk work.'],
            ['Discovery',
              'Whatever keeps all of the above honest without a human retyping it.'],
          ].map((x) => (
            <div key={x[0]}>
              <div className="h3">{x[0]}</div>
              <p className="p" style={{ margin: '6px 0 0', lineHeight: 1.6 }}>{x[1]}</p>
            </div>
          ))}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 9, marginTop: 16, flexWrap: 'wrap' }}>
        <button className="b b-go" onClick={() => onGo('incidents')}>Back to incident management</button>
        <button className="b" onClick={() => onGo('admin')}>See what is configurable</button>
      </div>
    </div></div></div>
  )
}
