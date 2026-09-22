import { useEffect, useRef, useState } from 'react'

export const C = {
  ok: 'var(--ok)',
  warn: 'var(--warn)',
  hot: 'var(--hot)',
  crit: 'var(--crit)',
  // text-safe accent: deep enough to read as small text on a light surface
  ice: 'var(--ice-ink)',
  mute: 'var(--ink3)',
}

export const PRIORITIES = ['P1', 'P2', 'P3', 'P4']

export const priorityColour = (p) =>
  p === 'P1' ? C.crit : p === 'P2' ? C.hot : p === 'P3' ? C.warn : C.mute

export const priorityRank = (p) => 4 - PRIORITIES.indexOf(p)

/**
 * Sentiment, 1 unhappiest to 5 happiest.
 *
 * Unlike priority, the good end is worth colouring: a desk wants to see that
 * somebody is delighted, not only that somebody is furious. Levels 3 and 4 stay
 * neutral so the two ends carry the signal.
 */
export const MOOD = ['1 · Angry', '2 · Unhappy', '3 · Neutral', '4 · Positive', '5 · Delighted']
export const moodColour = (level) =>
  level <= 1 ? C.crit : level <= 2 ? C.hot : level >= 5 ? C.ok : C.mute
export const moodLabel = (level) => MOOD[Math.round(level) - 1] ?? '—'

/**
 * Escalation risk bands, as the server's policy names them.
 *
 * The colour is the band, not the probability: 41% and 64% are both "watch"
 * and should look alike, because the line between them is where the desk acts.
 */
export const riskColour = (band) => (band === 'likely' ? C.crit : band === 'watch' ? C.warn : C.mute)
export const riskLabel = (band) =>
  band === 'likely' ? 'Likely to escalate' : band === 'watch' ? 'Worth watching' : 'Quiet'

const pad = (n) => String(n).padStart(2, '0')

/** mm:ss under an hour, then hours, then days. A leading + means past target. */
export function clock(seconds) {
  const over = seconds < 0
  const a = Math.abs(Math.round(seconds))
  const sign = over ? '+' : ''
  if (a < 3600) return `${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`
  if (a < 86400) return `${sign}${Math.floor(a / 3600)}h ${pad(Math.floor((a % 3600) / 60))}m`
  return `${sign}${Math.floor(a / 86400)}d ${Math.floor((a % 86400) / 3600)}h`
}

export const heat = (burn, breached) =>
  breached || burn > 0.9 ? C.crit : burn > 0.72 ? C.hot : burn > 0.45 ? C.warn : C.ok

export function initials(name) {
  if (!name) return '--'
  const parts = String(name).replace(/[^A-Za-z .]/g, '').split(/[ .]+/).filter(Boolean)
  return (parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')
}

export const isIncident = (t) => t?.kind === 'incident'
export const isLive = (t) => !['resolved', 'closed', 'cancelled', 'spam'].includes(t?.status)

/**
 * A clock that runs in the browser without asking the server every second.
 *
 * The API hands back `resolution_due_at` as an absolute instant, so the
 * interface only has to know what time it is. Ticking a local counter keeps the
 * countdown honest across a reload and costs one state update a second.
 */
export function useNow(running = true, intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return undefined
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [running, intervalMs])
  return now
}

/**
 * Seconds left on a ticket's resolution clock, as of `now`.
 *
 * Held and resolved tickets keep whatever the server last computed, because
 * their clock is paused and counting down locally would be a lie.
 */
export function remainingFor(ticket, now) {
  const sla = ticket.sla
  if (!sla) return 0
  if (sla.clock_paused) return sla.remaining_seconds
  const due = Date.parse(sla.resolution_due_at) + sla.paused_seconds * 1000
  return Math.round((due - now) / 1000)
}

export function burnFor(ticket, now) {
  const sla = ticket.sla
  if (!sla) return 0
  if (sla.clock_paused) return sla.burn
  const opened = Date.parse(ticket.opened_at)
  const due = Date.parse(sla.resolution_due_at)
  const window = due - opened
  if (window <= 0) return 1
  const spent = now - opened - sla.paused_seconds * 1000
  return Math.max(0, spent / window)
}

/** Count a number up once, on mount, and never again on re-render. */
export function useCountUp(target, ms = 800) {
  const [value, setValue] = useState(0)
  const done = useRef(false)
  useEffect(() => {
    if (done.current) {
      setValue(target)
      return undefined
    }
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      setValue(target)
      done.current = true
      return undefined
    }
    let raf
    let start = null
    const step = (t) => {
      if (start === null) start = t
      const k = Math.min(1, (t - start) / ms)
      setValue(target * (1 - (1 - k) ** 3))
      if (k < 1) raf = requestAnimationFrame(step)
      else done.current = true
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return value
}
