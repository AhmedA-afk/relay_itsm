import { useState } from 'react'
import { api } from '../lib/api'
import { Icon, Tag } from '../components/ui'
import { C, PRIORITIES, priorityColour } from '../lib/format'

const IMPACTS = ['organization', 'department', 'team', 'individual']
const URGENCIES = ['low', 'medium', 'high', 'critical']

const DEFAULT_MATRIX = {
  organization: { low: 'P3', medium: 'P2', high: 'P1', critical: 'P1' },
  department: { low: 'P3', medium: 'P2', high: 'P2', critical: 'P1' },
  team: { low: 'P4', medium: 'P3', high: 'P2', critical: 'P2' },
  individual: { low: 'P4', medium: 'P4', high: 'P3', critical: 'P2' },
}

/**
 * Configuration, and it really configures.
 *
 * Pressing a cell writes to the API, and because the server derives priority on
 * every read rather than storing it, every open ticket moves at once. That is
 * the whole architectural argument, made pressable.
 */
export default function Admin({ meta, matrix, onMatrix, toast }) {
  const [busy, setBusy] = useState(false)
  const rules = meta?.sla_rules ?? []
  const teams = meta?.teams ?? []

  const save = async (next) => {
    setBusy(true)
    try {
      const saved = await api.saveMatrix(next)
      onMatrix(saved)
      toast?.('Matrix saved, every open ticket re-read')
    } catch (e) {
      toast?.(e.message)
    } finally {
      setBusy(false)
    }
  }

  const cycle = (impact, urgency) => {
    const current = matrix[impact][urgency]
    const next = JSON.parse(JSON.stringify(matrix))
    next[impact][urgency] = PRIORITIES[(PRIORITIES.indexOf(current) + 1) % 4]
    save(next)
  }

  return (
    <div className="scroll"><div className="pad"><div className="cap">
      <h1 className="h1">Administration</h1>
      <p className="lead" style={{ margin: '7px 0 0', maxWidth: 620 }}>
        All policy, no data. Change any of it and the next request follows the new rule,
        while nothing already decided gets rewritten behind your back.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 14, marginTop: 22 }}>
        <section className="glass" style={{ padding: '20px 21px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10 }}>
            <h2 className="h2">Impact and urgency into a level</h2>
            <button className="b b-s" disabled={busy} onClick={() => save(DEFAULT_MATRIX)}>Reset</button>
          </div>
          <p className="fine" style={{ margin: '5px 0 0' }}>
            Press a cell to change what it gives. It saves to the server and every open ticket
            re-reads its level on the next refresh.
          </p>
          <div className="mx" style={{ marginTop: 18 }}>
            <div />
            {URGENCIES.map((u) => (
              <div key={u} className="fine" style={{ textAlign: 'center', paddingBottom: 6 }}>{u}</div>
            ))}
            {IMPACTS.map((impact) => (
              <div key={impact} style={{ display: 'contents' }}>
                <div className="mt" style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', paddingRight: 10 }}>
                  {impact}
                </div>
                {URGENCIES.map((urgency) => {
                  const value = matrix?.[impact]?.[urgency] ?? '--'
                  return (
                    <button
                      key={impact + urgency} className="mc" disabled={busy}
                      style={{ '--cc': priorityColour(value) }}
                      aria-label={`${impact} impact with ${urgency} urgency currently gives ${value}. Press to change it.`}
                      onClick={() => cycle(impact, urgency)}
                    >{value}</button>
                  )
                })}
              </div>
            ))}
          </div>
          <p className="p" style={{ marginTop: 17, paddingTop: 14, borderTop: '1px solid var(--edge)', lineHeight: 1.6 }}>
            No ticket stores its level. The server reads it out of this grid on every request,
            which is why any ticket can always show you the cell it came from.
          </p>
        </section>

        <section className="glass" style={{ padding: '20px 21px' }}>
          <h2 className="h2">What we promise, and when</h2>
          <p className="fine" style={{ margin: '5px 0 0' }}>
            Checked in order. The first one that fits a ticket is the one that counts.
          </p>
          <div style={{ marginTop: 18 }}>
            <div className="fine" style={{
              display: 'grid', gridTemplateColumns: '50px minmax(0,1fr) minmax(0,1fr) 120px',
              gap: 11, paddingBottom: 9, borderBottom: '1px solid var(--edge)',
            }}>
              <div>Level</div><div>First reply</div><div>Fixed by</div><div>Counting</div>
            </div>
            {rules.map((r) => (
              <div key={r.order} style={{
                display: 'grid', gridTemplateColumns: '50px minmax(0,1fr) minmax(0,1fr) 120px',
                gap: 11, padding: '13px 0', borderBottom: '1px solid var(--edge)', alignItems: 'center',
              }}>
                <div><span className="tag mo" style={{ '--tc': priorityColour(r.priority) }}>{r.priority}</span></div>
                <div style={{ fontSize: 12.5 }}>{humanMinutes(r.response_minutes)}</div>
                <div style={{ fontSize: 12.5 }}>{humanMinutes(r.resolution_minutes)}</div>
                <div className="mt">{r.calendar === 'business' ? 'Working hours' : 'Round the clock'}</div>
              </div>
            ))}
          </div>
          <p className="p" style={{ marginTop: 17, lineHeight: 1.6 }}>
            The fix clock stops while a ticket waits on the person who raised it. The reply
            clock never stops, because that one is a promise about us.
          </p>
        </section>
      </div>

      <section className="glass" style={{ marginTop: 14, padding: '20px 21px' }}>
        <h2 className="h2">Who work goes to</h2>
        <p className="fine" style={{ margin: '5px 0 0' }}>Two questions, answered two different ways on purpose.</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 26, marginTop: 18 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 12, flexWrap: 'wrap' }}>
              <h3 className="h3">Which team should own this?</h3>
              <Tag k="mute">reading the ticket</Tag>
            </div>
            {teams.map((t) => (
              <div key={t.key} style={{
                display: 'grid', gridTemplateColumns: '108px minmax(0,1fr)', gap: 13,
                padding: '10px 0', borderBottom: '1px solid var(--edge)', alignItems: 'baseline',
              }}>
                <span className="mo" style={{ fontSize: 11.5 }}>{t.key}</span>
                <span className="p" style={{ lineHeight: 1.5 }}>{t.domain}</span>
              </div>
            ))}
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 12, flexWrap: 'wrap' }}>
              <h3 className="h3">Who on that team?</h3>
              <Tag k="ice">counting, not reading</Tag>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
              {[
                ['Whoever has least on', 'Fewest open tickets on that team wins, skipping anyone on leave.', true],
                ['Straight rotation', 'Next in line gets it, however much they already carry.', false],
                ['By hand', 'Nothing is handed out automatically. The team lead decides.', false],
              ].map((s) => (
                <label key={s[0]} style={{
                  display: 'flex', gap: 12, alignItems: 'flex-start', padding: '13px 15px', borderRadius: 12,
                  cursor: s[2] ? 'default' : 'not-allowed',
                  background: s[2] ? 'var(--ice-wash)' : 'var(--g1)',
                  boxShadow: `inset 0 0 0 1px ${s[2] ? 'color-mix(in srgb, var(--ice) 34%, transparent)' : 'var(--edge)'}`,
                  opacity: s[2] ? 1 : 0.62,
                }}>
                  <input type="radio" name="how" defaultChecked={s[2]} disabled={!s[2]} style={{ marginTop: 3 }} />
                  <span>
                    <span className="h3" style={{ display: 'block' }}>{s[0]}</span>
                    <span className="p" style={{ display: 'block', marginTop: 4, lineHeight: 1.5 }}>{s[1]}</span>
                  </span>
                </label>
              ))}
            </div>
            <p className="p" style={{ marginTop: 14, lineHeight: 1.6 }}>
              Least-loaded is the policy this build runs; the other two are shown for contrast,
              not as choices. Most service desks only ever answer the second question and call
              the whole thing routing — that is how a barcode fault ends up with whoever
              happened to be next.
            </p>
          </div>
        </div>
      </section>

      <section className="glass" style={{ marginTop: 14, padding: '20px 21px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <Icon n="alert" s={15} c={C.warn} w={1.8} />
          <h2 className="h2">Closure codes</h2>
        </div>
        <p className="fine" style={{ margin: '5px 0 14px' }}>
          An incident cannot be closed without one of these. The server refuses it, so the
          interface gate is a courtesy rather than the rule.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 11 }}>
          {(meta?.resolution_codes ?? []).map((c) => (
            <div key={c.code} className="slab" style={{ padding: '13px 15px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="h3">{c.label}</span>
                {c.needs_problem ? <Tag k="warn">wants a problem</Tag> : null}
              </div>
              <div className="mo fine" style={{ marginTop: 6 }}>{c.code}</div>
            </div>
          ))}
        </div>
      </section>
    </div></div></div>
  )
}

function humanMinutes(minutes) {
  if (minutes < 60) return `${minutes} minutes`
  if (minutes < 60 * 24) {
    const h = minutes / 60
    return `${h % 1 === 0 ? h : h.toFixed(1)} hour${h === 1 ? '' : 's'}`
  }
  const days = Math.round(minutes / (12 * 60))
  return `${days} working day${days === 1 ? '' : 's'}`
}
