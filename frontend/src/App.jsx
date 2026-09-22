import { useCallback, useEffect, useMemo, useState } from 'react'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { api } from './lib/api'
import { C, isIncident, isLive, useNow } from './lib/format'
import { useTheme } from './lib/theme'
import { Appearance, Failed, Icon, Shortcuts } from './components/ui'
import Board, { INCIDENT_VIEWS, REQUEST_VIEWS } from './modules/Board'
import Dashboards from './modules/Dashboards'
import Ticket from './modules/Ticket'
import Admin from './modules/Admin'
import Reports from './modules/Reports'
import History from './modules/History'
import People from './modules/People'
import Showcase from './modules/Showcase'
import { Assets, Catalog, Changes, Knowledge, Problems, Releases } from './modules/Reference'
import { Intake, MyRequests } from './modules/Portal'
import Palette from './components/Palette'

const NAV = [
  ['Compare', [
    ['showcase', 'Showcase', 'split'],
  ]],
  ['Operate', [
    ['dashboards', 'Dashboards', 'pulse'],
    ['incidents', 'Incident management', 'ticket'],
    ['services', 'Service management', 'cart'],
  ]],
  ['Improve', [
    ['problems', 'Problem management', 'alert'],
    ['changes', 'Change enablement', 'cal'],
    ['releases', 'Release management', 'box'],
  ]],
  ['Reference', [
    ['knowledge', 'Knowledge base', 'doc'],
    ['catalog', 'Service catalogue', 'tiles'],
    ['assets', 'Assets and CMDB', 'stack'],
  ]],
  ['Oversight', [
    ['reports', 'Reports', 'graph'],
    ['people', 'People and departments', 'people'],
    ['history', 'Ticket history', 'clock'],
    ['admin', 'Administration', 'dials'],
  ]],
]
const PORTAL = [
  ['intake', 'Ask for something', 'tray'],
  ['mine', 'Your requests', 'tray'],
]
const ROUTE_NAMES = Object.fromEntries(
  [...NAV.flatMap(([, items]) => items), ...PORTAL].map(([k, name]) => [k, name]),
)

export default function App() {
  // The Showcase is the front door: the comparison is what this build is for,
  // and the desk behind it is the evidence that the comparison is real rather
  // than a slide. Ctrl/Cmd+K or the rail reaches everything else.
  const [route, setRoute] = useState('showcase')
  const [openId, setOpenId] = useState(null)
  const [tickets, setTickets] = useState([])
  const [meta, setMeta] = useState(null)
  const [matrix, setMatrix] = useState(null)
  const [error, setError] = useState(null)
  const [dense, setDense] = useState(true)
  const [running, setRunning] = useState(true)
  const [palette, setPalette] = useState(false)
  const [sheet, setSheet] = useState(false)
  const [toasts, setToasts] = useState([])
  const [busy, setBusy] = useState(false)

  const now = useNow(running)
  const [theme, setTheme] = useTheme()

  const toast = useCallback((text) => {
    const id = Math.random().toString(36).slice(2)
    setToasts((t) => [...t, { id, text }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 2600)
  }, [])

  const load = useCallback(async () => {
    try {
      const [all, m] = await Promise.all([api.tickets(), api.meta()])
      setTickets(all)
      setMeta(m)
      setMatrix(m.matrix)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // The server owns the clocks, so a slow refresh keeps derived state honest
  // without the browser guessing. The countdown itself ticks locally.
  useEffect(() => {
    if (!running) return undefined
    const id = setInterval(load, 60_000)
    return () => clearInterval(id)
  }, [running, load])

  useEffect(() => {
    function onKey(e) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette(true) }
      const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)
      if (e.key === '?' && !typing) { e.preventDefault(); setSheet((s) => !s) }
      if (e.key === 'Escape') { setPalette(false); setSheet(false) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const go = useCallback((key) => { setRoute(key); setOpenId(null) }, [])
  const open = useCallback((id) => { setOpenId(id); setRoute('ticket') }, [])

  const claim = useCallback(async (id) => {
    setBusy(true)
    try {
      await api.claim(id)
      await load()
      toast(`${id} is yours`)
    } catch (e) {
      toast(e.message)
    } finally {
      setBusy(false)
    }
  }, [load, toast])

  const incidents = useMemo(() => tickets.filter(isIncident), [tickets])
  const requests = useMemo(() => tickets.filter((t) => !isIncident(t)), [tickets])
  const ticket = tickets.find((t) => t.id === openId)
  const portal = route === 'intake' || route === 'mine'
  const here = route === 'ticket' ? (ticket && !isIncident(ticket) ? 'services' : 'incidents') : route
  const breached = tickets.filter((t) => isLive(t) && t.sla.breached).length

  const counts = {
    incidents: incidents.filter(isLive).length,
    services: requests.filter(isLive).length,
  }

  function body() {
    if (error) return <Failed error={error} retry={load} />
    if (route === 'ticket' && ticket) {
      return (
        <Ticket
          id={ticket.id} now={now} meta={meta} toast={toast}
          onBack={() => go(isIncident(ticket) ? 'incidents' : 'services')}
          onGo={go} onAction={load}
        />
      )
    }
    if (route === 'incidents') {
      return (
        <Board
          id="inc" views={INCIDENT_VIEWS} tickets={incidents} now={now}
          dense={dense} setDense={setDense} onOpen={open} onClaim={claim} busy={busy}
          onNew={() => go('intake')}
          title="Incident management" newLabel="Log an incident"
          idLabel="Incident" sumLabel="What is broken" whoLabel="Caller"
          blurb={
            <span>
              {counts.incidents} open.{' '}
              {breached
                ? <span style={{ color: C.crit }}>{breached} past target</span>
                : <span style={{ color: C.ok }}>none past target</span>}
              <span>. Only things that broke; anything someone is asking for lives in service management.</span>
            </span>
          }
        />
      )
    }
    if (route === 'services') {
      return (
        <Board
          id="req" views={REQUEST_VIEWS} tickets={requests} now={now}
          dense={dense} setDense={setDense} onOpen={open} onClaim={claim} busy={busy}
          onNew={() => go('intake')}
          title="Service management" newLabel="Raise a request"
          idLabel="Request" sumLabel="What was asked for" whoLabel="Asked by"
          blurb={
            <span>
              {counts.services} open out of the catalogue. Things people have asked for, each
              with an agreed turnaround, rather than things that broke.
            </span>
          }
        />
      )
    }
    if (route === 'dashboards') {
      return (
        <Dashboards
          tickets={tickets} now={now} running={running} setRunning={setRunning}
          onOpen={open} onGo={go}
        />
      )
    }
    if (route === 'problems') return <Problems onGo={go} toast={toast} />
    if (route === 'changes') return <Changes toast={toast} />
    if (route === 'releases') return <Releases onGo={go} toast={toast} />
    if (route === 'knowledge') return <Knowledge toast={toast} />
    if (route === 'catalog') return <Catalog onGo={go} />
    if (route === 'assets') return <Assets onGo={go} />
    if (route === 'reports') return <Reports onGo={go} onOpen={open} />
    if (route === 'people') return <People toast={toast} onGo={go} />
    if (route === 'history') return <History onGo={go} />
    if (route === 'showcase') return <Showcase />
    if (route === 'admin') {
      return <Admin meta={meta} matrix={matrix ?? {}} onMatrix={(m) => { setMatrix(m); load() }} toast={toast} />
    }
    if (route === 'intake') return <Intake onGo={go} tickets={requests} toast={toast} />
    if (route === 'mine') return <MyRequests onGo={go} tickets={requests} now={now} toast={toast} />
    return null
  }

  return (
    <MotionConfig reducedMotion="user">
      <div className="app">
        <aside className="rail">
          <div className="logo">
            <i>R</i>
            <div><b>Relay</b><s>Meridian Foods</s></div>
          </div>
          {NAV.map(([group, items]) => (
            <nav key={group} className="nsec">
              <em>{group}</em>
              {items.map(([key, name, icon]) => (
                <button
                  key={key} className="nit" aria-current={here === key ? 'page' : undefined}
                  onClick={() => go(key)}
                >
                  <Icon n={icon} s={15} />
                  <span>{name}</span>
                  {counts[key] ? <u>{counts[key]}</u> : null}
                </button>
              ))}
            </nav>
          ))}
          <div className="railend">
            <nav className="nsec" style={{ marginBottom: 10 }}>
              <em>What staff see</em>
              {PORTAL.map(([key, name, icon]) => (
                <button
                  key={key} className="nit" aria-current={here === key ? 'page' : undefined}
                  onClick={() => go(key)}
                >
                  <Icon n={icon} s={15} />
                  <span>{name}</span>
                </button>
              ))}
            </nav>
            <Appearance mode={theme} onMode={setTheme} />
            <div className="me">
              <span className="av">AO</span>
              <span style={{ minWidth: 0 }}>
                <span style={{ display: 'block', fontSize: 12.5, fontWeight: 500 }}>A. Okonkwo</span>
                <span style={{ display: 'block', fontSize: 11.5, color: 'var(--ink4)' }}>Second line</span>
              </span>
            </div>
          </div>
        </aside>

        <div className="main">
          {!portal ? (
            <div className="bar">
              <button className="sk" onClick={() => setPalette(true)}>
                <Icon n="find" s={14} c="var(--ink4)" />
                <span className="lbl">Find anything</span>
                <span className="kb" style={{ marginLeft: 'auto' }}>⌘K</span>
              </button>
              <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
                <span className="fine" style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <span className={running ? 'dot live' : 'dot'} style={{ color: running ? C.ok : 'var(--ink4)' }} />
                  {running ? 'clocks running' : 'clocks paused'}
                </span>
                {breached ? (
                  <button className="b b-s b-bare" style={{ color: C.crit }} onClick={() => go('incidents')}>
                    {breached} past target
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}

          <AnimatePresence initial={false} mode="popLayout">
            <motion.div
              key={route + (openId ?? '')}
              style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.13 }}
            >
              {body()}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      <AnimatePresence>
        {palette ? (
          <Palette
            tickets={tickets} routes={ROUTE_NAMES} running={running}
            onClose={() => setPalette(false)}
            onGo={go} onOpen={open}
            onToggleClocks={() => setRunning((r) => !r)}
            onToggleDense={() => setDense((d) => !d)}
          />
        ) : null}
      </AnimatePresence>

      <AnimatePresence>
        {sheet ? <Shortcuts onClose={() => setSheet(false)} /> : null}
      </AnimatePresence>

      <div className="toasts" aria-live="polite">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div
              key={t.id} className="toast" role="status"
              initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 6 }}
              transition={{ duration: 0.16, ease: 'easeOut' }}
            >
              <Icon n="tick" s={14} c={C.ok} w={2.2} />
              {t.text}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </MotionConfig>
  )
}
