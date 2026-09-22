import { useRef } from 'react'
import { motion } from 'motion/react'
import { PolarAngleAxis, RadialBar, RadialBarChart } from 'recharts'
import { C, moodColour, moodLabel, riskColour, riskLabel, PRIORITIES, priorityColour, priorityRank } from '../lib/format'

const PATHS = {
  list: 'M4 7h16M4 12h16M4 17h10',
  pulse: 'M3 12h4l2.5-7 3 14 2.5-7h6',
  alert: 'M12 9v4.2M12 16.9v.2M10.6 4.1L2.7 17.4A1.5 1.5 0 004 19.7h16a1.5 1.5 0 001.3-2.3L13.4 4.1a1.5 1.5 0 00-2.8 0z',
  cal: 'M8 3v3.5M16 3v3.5M3.5 9.5h17M5.5 5.5h13a2 2 0 012 2v11a2 2 0 01-2 2h-13a2 2 0 01-2-2v-11a2 2 0 012-2z',
  doc: 'M5 19.5V5.5a2 2 0 012-2h7l5 5v11a2 2 0 01-2 2H7a2 2 0 01-2-2z',
  tiles: 'M4.5 4.5h6v6h-6zM13.5 4.5h6v6h-6zM4.5 13.5h6v6h-6zM13.5 13.5h6v6h-6z',
  graph: 'M4.5 19.5V11M10 19.5V5M15.5 19.5v-6M21 19.5H3',
  dials: 'M12 15a3 3 0 100-6 3 3 0 000 6M19.4 15a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 01-2.8 2.8l-.1-.1A1.6 1.6 0 0014 21a2 2 0 01-4 0 1.6 1.6 0 00-2.9-1.4l-.1.1a2 2 0 01-2.8-2.8l.1-.1A1.6 1.6 0 003 13a2 2 0 010-4 1.6 1.6 0 001.4-2.9l-.1-.1a2 2 0 012.8-2.8l.1.1A1.6 1.6 0 0010 3a2 2 0 014 0 1.6 1.6 0 002.9 1.4l.1-.1a2 2 0 012.8 2.8l-.1.1A1.6 1.6 0 0021 10a2 2 0 010 4z',
  tray: 'M21.5 12.5h-5l-2 3h-5l-2-3h-5M5.8 4.5h12.4l3.3 8v5.5a2 2 0 01-2 2H4.5a2 2 0 01-2-2V12.5z',
  find: 'M11 18a7 7 0 100-14 7 7 0 000 14M20.5 20.5L16 16',
  next: 'M5 12h13.5M13 6l6.5 6-6.5 6',
  clock: 'M12 21a9 9 0 100-18 9 9 0 000 18M12 7.5V12l3 2',
  tick: 'M20 6.5L9.5 17 4.5 12',
  lock: 'M4.5 9.5h15v10.5h-15zM8.5 9.5V6.5a3.5 3.5 0 017 0v3',
  rise: 'M5 15l7-7 7 7',
  fall: 'M5 9l7 7 7-7',
  play: 'M7 4.5l12 7.5-12 7.5z',
  pause: 'M8 5h3v14H8zM13 5h3v14h-3z',
  siren: 'M12 3a5 5 0 015 5v5H7V8a5 5 0 015-5zM5 17h14M9 21h6M12 3V1.5',
  box: 'M3.5 8.5L12 4l8.5 4.5v7L12 20l-8.5-4.5zM3.5 8.5L12 13l8.5-4.5M12 13v7',
  stack: 'M12 3.5l8.5 4-8.5 4-8.5-4zM3.5 12l8.5 4 8.5-4M3.5 16l8.5 4 8.5-4',
  ticket: 'M4 8.5a2 2 0 012-2h12a2 2 0 012 2 2 2 0 000 4 2 2 0 010 4H6a2 2 0 01-2-4 2 2 0 000-4z',
  cart: 'M3 4h2l2.4 10.5A2 2 0 009.4 16h8.2a2 2 0 002-1.6L21 8H6M9.5 20h.01M17 20h.01',
  split: 'M4 4.5h6.5v15H4zM13.5 4.5H20v15h-6.5z',
  sun: 'M12 17a5 5 0 100-10 5 5 0 000 10M12 2.5v2M12 19.5v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2.5 12h2M19.5 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
  moon: 'M20.5 14.3A8.5 8.5 0 019.7 3.5a8.5 8.5 0 1010.8 10.8z',
  auto: 'M12 21a9 9 0 100-18 9 9 0 000 18M12 3v18a9 9 0 000-18z',
  people: 'M9 11.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7M2.5 20a6.5 6.5 0 0113 0M16.5 5.2a3.5 3.5 0 010 6.6M18 14.4a6.5 6.5 0 013.5 5.6',
}

export function Icon({ n, s = 15, c = 'currentColor', w = 1.6, fill }) {
  return (
    <svg
      width={s} height={s} viewBox="0 0 24 24"
      fill={fill ?? 'none'} stroke={fill ? 'none' : c}
      strokeWidth={w} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" style={{ flexShrink: 0 }}
    >
      <path d={PATHS[n]} />
    </svg>
  )
}

/** Severity as a lit three-bar stack, so it never relies on hue alone. */
export function Sev({ p }) {
  const rank = priorityRank(p)
  const colour = priorityColour(p)
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span className="sev" style={{ '--sc': colour }}>
        {[1, 2, 3].map((i) => <i key={i} data-on={rank >= i ? '1' : '0'} />)}
      </span>
      <span className="mo" style={{ fontSize: 11.5, fontWeight: 500, color: colour }}>{p}</span>
    </span>
  )
}

export function Tag({ k = 'mute', dot, pulse, children }) {
  return (
    <span className="tag" style={{ '--tc': C[k] ?? k }}>
      {dot ? <span className={pulse ? 'dot live' : 'dot'} /> : null}
      {children}
    </span>
  )
}

/**
 * The burn meter: how much of a ticket's own target is spent.
 *
 * A single capsule rather than a row of segments. Because it reads as a
 * fraction of that ticket's own target, a P1's four hours and a P4's five days
 * still land as comparable pressure, and at row scale one bar is quieter than
 * twelve. `n` is kept for callers that ask for a coarser read.
 */
export function Meter({ v, c, n, title }) {
  const value = Math.min(1, Math.max(0, v))
  const pct = n ? Math.round(value * n) / n : value
  return (
    <span
      className="meter" style={{ '--mc': c, width: '100%' }} title={title}
      role="img" aria-label={title}
    >
      <i style={{ width: `${Math.max(pct > 0 ? 3 : 0, pct * 100)}%` }} />
    </span>
  )
}

/**
 * A radial gauge, drawn by Recharts' RadialBarChart so every gauge in the app —
 * dashboard, reports, ticket clocks — shares one renderer. The figure sits in
 * HTML over the chart rather than in SVG text, so it gets the real type stack
 * and tabular figures.
 */
export function Ring({ v, c, big, small, r = 34, sw = 6, bs = 20, delay = 0, label }) {
  const value = Math.min(1, Math.max(0, v)) * 100
  const d = r * 2 + sw * 2 + 8
  return (
    <div role="img" aria-label={label} style={{ position: 'relative', width: d, height: d, flexShrink: 0 }}>
      <RadialBarChart
        width={d} height={d} data={[{ v: value }]} startAngle={90} endAngle={-270}
        innerRadius={r - sw / 2} outerRadius={r + sw / 2} barSize={sw}
        margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
      >
        <PolarAngleAxis type="number" domain={[0, 100]} tick={false} axisLine={false} />
        <RadialBar
          dataKey="v" fill={c} cornerRadius={sw / 2} background={{ fill: 'var(--track)' }}
          animationBegin={delay * 1000} animationDuration={900} animationEasing="ease-out"
        />
      </RadialBarChart>
      {big || small ? (
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', textAlign: 'center', pointerEvents: 'none',
        }}>
          {big ? (
            <span className="tn" style={{
              fontSize: bs, fontWeight: 600, letterSpacing: '-.04em', lineHeight: 1, color: 'var(--ink)',
            }}>{big}</span>
          ) : null}
          {small ? <span style={{ fontSize: 11.5, color: 'var(--ink3)', marginTop: 5 }}>{small}</span> : null}
        </div>
      ) : null}
    </div>
  )
}

/** Tabs with a rule that slides between them rather than jumping. */
export function Tabs({ id, value, onChange, items }) {
  const list = useRef(null)
  const index = items.findIndex((x) => x.k === value)

  function onKeyDown(e) {
    const last = items.length - 1
    const next =
      e.key === 'ArrowRight' ? Math.min(last, index + 1)
      : e.key === 'ArrowLeft' ? Math.max(0, index - 1)
      : e.key === 'Home' ? 0
      : e.key === 'End' ? last
      : -1
    if (next < 0 || next === index) return
    e.preventDefault()
    onChange(items[next].k)
    list.current?.children[next]?.focus()
  }

  return (
    <div className="tabs" role="tablist" ref={list} onKeyDown={onKeyDown} style={{ overflowX: 'auto' }}>
      {items.map((x) => {
        const on = x.k === value
        return (
          <button
            key={x.k} className="tb" role="tab" aria-selected={on}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(x.k)}
          >
            <span>{x.name}</span>
            {x.n ? <u style={x.hot ? { color: C.crit } : undefined}>{x.n}</u> : null}
            {on ? (
              <motion.span
                layoutId={id} className="rule"
                transition={{ duration: 0.18, ease: 'easeOut' }}
              />
            ) : null}
          </button>
        )
      })}
    </div>
  )
}

export function Avatar({ name, size = 26 }) {
  return (
    <span className="av" style={{ width: size, height: size, fontSize: size < 24 ? 9 : 10 }}>
      {initialsOf(name)}
    </span>
  )
}

function initialsOf(name) {
  if (!name) return '--'
  const parts = String(name).replace(/[^A-Za-z .]/g, '').split(/[ .]+/).filter(Boolean)
  return (parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')
}

export function Empty({ title, body, action }) {
  return (
    <div className="blank">
      <h2 className="h2">{title}</h2>
      {body ? <p className="p" style={{ margin: '6px 0 14px' }}>{body}</p> : null}
      {action}
    </div>
  )
}

export function Loading({ what = 'Loading' }) {
  return (
    <div className="pad">
      <p className="mt">{what}…</p>
    </div>
  )
}

export function Failed({ error, retry }) {
  return (
    <div className="pad">
      <Empty
        title="The desk is not answering"
        body={`${error}. The API runs on port 8010; start it with "make dev" if it is not up.`}
        action={retry ? <button className="b" onClick={retry}>Try again</button> : null}
      />
    </div>
  )
}

/**
 * Appearance: auto, light, dark.
 *
 * Auto is first and is the default, because the HIG asks apps to respect the
 * systemwide setting (`dark-mode.md`). The other two are here because a web
 * app has no system switch of its own inside a tab.
 */
export function Appearance({ mode, onMode }) {
  const options = [
    ['auto', 'auto', 'Match the system'],
    ['light', 'sun', 'Light'],
    ['dark', 'moon', 'Dark'],
  ]
  return (
    <div className="theme" role="group" aria-label="Appearance">
      {options.map(([k, icon, label]) => (
        <button
          key={k} onClick={() => onMode(k)} title={label}
          aria-pressed={mode === k} aria-label={label}
        >
          <Icon n={icon} s={14} w={1.7} />
        </button>
      ))}
    </div>
  )
}

/**
 * The '?' sheet. Lists only the keys that actually do something — a shortcut
 * on this list that does not work would be the same kind of lie as a button
 * that does nothing.
 */
export function Shortcuts({ onClose }) {
  const rows = [
    ['Find anything, jump anywhere', ['⌘', 'K']],
    ['Move through a queue', ['J', 'K']],
    ['Open the row under the cursor', ['↵']],
    ['Assign it to me', ['A']],
    ['Move between tabs', ['←', '→']],
    ['This sheet', ['?']],
    ['Close whatever is open', ['Esc']],
  ]
  return (
    <motion.div
      className="veil" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      transition={{ duration: 0.12 }} onClick={onClose}
    >
      <motion.div
        className="sheet" onClick={(e) => e.stopPropagation()}
        initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -6 }}
        transition={{ duration: 0.14, ease: 'easeOut' }}
        role="dialog" aria-modal="true" aria-label="Keyboard shortcuts"
      >
        <header><h2 className="h2">Keys</h2></header>
        <ul>
          {rows.map(([what, keys]) => (
            <li key={what}>
              {what}
              <span className="keys">{keys.map((k) => <span key={k} className="kb">{k}</span>)}</span>
            </li>
          ))}
        </ul>
      </motion.div>
    </motion.div>
  )
}

export { PRIORITIES }


/**
 * One sentiment reading: the position on the scale, coloured by level.
 *
 * A stale reading is shown rather than hidden, dimmed and marked, because the
 * honest statement is "3.1, before the last two replies" — not silence, and
 * not a number pretending to be current.
 */
export function Mood({ s, size = 12.5, showScore = true }) {
  if (!s) return <span className="nobody" title="Nobody has read this thread yet">—</span>
  const colour = moodColour(s.level)
  return (
    <span
      title={`${moodLabel(s.level)}${s.stale ? ' — read before the latest messages' : ''}`}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: size,
        opacity: s.stale ? 0.55 : 1,
      }}
    >
      <span style={{
        width: 7, height: 7, borderRadius: 999, flexShrink: 0, background: colour,
        outline: s.stale ? `1px dashed ${colour}` : undefined, outlineOffset: 2,
      }} />
      {showScore ? (
        <span className="mo" style={{ color: colour, fontVariantNumeric: 'tabular-nums' }}>
          {s.score.toFixed(1)}
        </span>
      ) : null}
    </span>
  )
}


/**
 * One escalation prediction: the probability, coloured by the band policy put
 * it in. Stale is shown rather than hidden — and for this one, stale has two
 * causes worth telling apart, so the tooltip names which.
 */
export function Risk({ r, size = 12.5 }) {
  if (!r) return <span className="nobody" title="Nothing has predicted this one">—</span>
  const colour = riskColour(r.band)
  const why = r.clock_moved ? 'the clock has moved since' : r.said_more ? 'more has been said since' : ''
  return (
    <span
      title={`${riskLabel(r.band)} — ${Math.round(r.probability * 100)}%${why ? `, but ${why}` : ''}`}
      className="mo"
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: size, color: colour,
        fontVariantNumeric: 'tabular-nums', opacity: r.stale ? 0.55 : 1,
      }}
    >
      {r.band === 'likely' ? <Icon n="siren" s={11} c={colour} w={2} /> : null}
      {Math.round(r.probability * 100)}%
    </span>
  )
}
