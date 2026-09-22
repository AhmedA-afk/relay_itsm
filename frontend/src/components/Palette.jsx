import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { Icon } from './ui'
import { C } from '../lib/format'

export default function Palette({
  tickets, routes, running, onClose, onGo, onOpen, onToggleClocks, onToggleDense,
}) {
  const [q, setQ] = useState('')
  const [index, setIndex] = useState(0)
  const input = useRef(null)

  const items = useMemo(() => [
    ...Object.entries(routes).map(([key, name]) => ({
      group: 'Go', label: name, run: () => onGo(key),
    })),
    { group: 'Do', label: running ? 'Pause the clocks' : 'Start the clocks', run: onToggleClocks },
    { group: 'Do', label: 'Switch row height', run: onToggleDense },
    ...tickets.map((t) => ({
      group: 'Tickets', label: `${t.id}  ${t.subject}`, run: () => onOpen(t.id),
    })),
  ], [routes, tickets, running, onGo, onOpen, onToggleClocks, onToggleDense])

  const results = items
    .filter((x) => x.label.toLowerCase().includes(q.toLowerCase()))
    .slice(0, 9)

  useEffect(() => { input.current?.focus() }, [])
  useEffect(() => { setIndex(0) }, [q])

  function onKey(e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setIndex((n) => Math.min(results.length - 1, n + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setIndex((n) => Math.max(0, n - 1)) }
    else if (e.key === 'Enter' && results[index]) { e.preventDefault(); results[index].run(); onClose() }
    else if (e.key === 'Escape') onClose()
  }

  const seen = new Set()

  return (
    <motion.div
      className="veil" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      transition={{ duration: 0.12 }} onClick={onClose}
    >
      <motion.div
        className="cmd glass" onClick={(e) => e.stopPropagation()}
        initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -6 }}
        transition={{ duration: 0.14, ease: 'easeOut' }}
        role="dialog" aria-modal="true" aria-label="Quick actions"
      >
        <label htmlFor="cq" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>
          Search
        </label>
        <input
          id="cq" ref={input} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
          placeholder="Find a ticket, jump somewhere, change something"
        />
        <ul role="listbox">
          {results.map((x, n) => {
            const head = !seen.has(x.group) && seen.add(x.group)
            return (
              <Fragment key={x.label + n}>
                {head ? <li className="gh" aria-hidden="true">{x.group}</li> : null}
                <li
                  role="option" aria-selected={n === index}
                  onMouseEnter={() => setIndex(n)}
                  onClick={() => { x.run(); onClose() }}
                >
                  <Icon n="next" s={13} c={n === index ? C.ice : 'var(--ink4)'} />
                  <span className="tr1">{x.label}</span>
                  {n === index ? <u>↵</u> : null}
                </li>
              </Fragment>
            )
          })}
          {results.length === 0 ? (
            <li style={{ color: 'var(--ink4)', cursor: 'default' }}>Nothing matches that</li>
          ) : null}
        </ul>
      </motion.div>
    </motion.div>
  )
}
