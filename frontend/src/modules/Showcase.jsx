import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Bot, Check, ClipboardList, LayoutGrid, ListFilter, Loader2, Play, Sparkles, X } from 'lucide-react'
import { Button } from '@/components/kit/button'
import { Card } from '@/components/kit/card'
import { Input } from '@/components/kit/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/kit/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/kit/table'
import { StatusBadge } from '@/components/blocks'
import { cn } from '@/lib/utils'
import { api } from '../lib/api'
import { priorityColour } from '../lib/format'

/**
 * One decision, several ways of making it, measured on every run.
 *
 * A use case declares its lanes (Jev, an AI call, a traditional mechanism);
 * this screen builds itself from that. Each lane is its own request, fired
 * together on "Run all", so each resolves the moment its engine answers.
 * Latency is measured on the server around the engine's own work; the
 * browser's round trip sits beside it.
 */

const ICON = { jev: Sparkles, ai: Bot, matrix: LayoutGrid, form: ClipboardList, rules: ListFilter }
const SCALE = ['var(--crit)', 'var(--hot)', 'var(--warn)', 'var(--ink4)']

/** Colour for an answer on a use case's ordered scale, most severe first. */
function scaleColour(use, key) {
  if (/^P[1-4]$/.test(key)) return priorityColour(key)
  const i = use?.order?.indexOf(key) ?? -1
  return i < 0 ? 'var(--ink)' : SCALE[Math.min(SCALE.length - 1, Math.round((i * (SCALE.length - 1)) / Math.max(1, use.order.length - 1)))]
}
const usd = (v) => (v == null ? '—' : v === 0 ? '$0' : v < 0.01 ? `$${v.toFixed(7).replace(/0+$/, '')}` : `$${v.toFixed(2)}`)
const ms = (v) => (v == null ? '—' : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : v < 1 ? `${v.toFixed(2)} ms` : `${Math.round(v)} ms`)
const int = (v) => (v == null ? '—' : v.toLocaleString('en-GB'))
const idle = { pending: false, result: null, browserMs: null, error: null }

function useTicker(active) {
  const [t, setT] = useState(0)
  const start = useRef(0)
  useEffect(() => {
    if (!active) return undefined
    start.current = performance.now()
    setT(0)
    const id = setInterval(() => setT(performance.now() - start.current), 47)
    return () => clearInterval(id)
  }, [active])
  return t
}

function Metric({ label, value, sub, strong }) {
  return (
    <div className="flex flex-col gap-1 bg-card px-4 py-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={cn('font-mono tabular-nums', strong ? 'text-lg font-semibold tracking-tight' : 'text-[15px]')}>{value}</span>
      {sub ? <span className="text-[11.5px] leading-snug text-muted-foreground">{sub}</span> : null}
    </div>
  )
}

function FormPick({ label, value, options, onChange }) {
  return (
    <label className="flex flex-1 flex-col gap-1 text-xs text-muted-foreground">
      {label}
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="h-8 w-full text-[13px]"><SelectValue /></SelectTrigger>
        <SelectContent>{options.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
      </Select>
    </label>
  )
}

function Answer({ r, use }) {
  const order = use.order ?? []
  const level = order.includes(r.answer)
  const probs = r.probabilities
    ? Object.entries(r.probabilities).sort((a, b) => (level ? order.indexOf(a[0]) - order.indexOf(b[0]) : b[1] - a[1]))
    : null
  return (
    <>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="flex items-center gap-2.5 text-[26px] font-semibold leading-none tracking-[-0.03em]">
          {level ? <span className="size-2.5 rounded-full" style={{ background: scaleColour(use, r.answer) }} /> : null}
          {r.label}
        </span>
        {use.legend?.[r.answer] ? <span className="text-[13px] text-muted-foreground">{use.legend[r.answer]}</span> : null}
      </div>

      {r.detail?.parts ? (
        <div className="flex flex-wrap items-center gap-1.5 text-[13px]">
          {r.detail.parts.map((p) => (
            <span key={p.label} className="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5">
              <span className="text-muted-foreground">{p.label}</span>
              <span className="font-medium">{p.value}</span>
              {p.probability != null ? <span className="font-mono text-xs text-muted-foreground">{Math.round(p.probability * 100)}%</span> : null}
              {p.by ? <span className={cn('text-xs', p.by === 'form default' || p.by === 'default' ? 'text-warn' : 'text-muted-foreground')}>{p.by}</span> : null}
            </span>
          ))}
          {r.detail.consistent === false ? (
            <span className="inline-flex items-center gap-1 text-xs text-crit"><AlertTriangle className="size-3.5" />contradicts its own inputs</span>
          ) : r.detail.consistent === true ? (
            <span className="inline-flex items-center gap-1 text-xs text-ok"><Check className="size-3.5" />matches its own inputs</span>
          ) : null}
        </div>
      ) : null}

      {probs ? (
        <div className="flex flex-col gap-1.5">
          {probs.map(([k, p]) => (
            <div key={k} className="grid grid-cols-[112px_minmax(0,1fr)_44px] items-center gap-3 text-[13px]">
              <span className={cn('text-muted-foreground', k === r.answer && 'font-medium text-foreground')}>{use.labels?.[k] ?? k}</span>
              <span className="h-1.5 overflow-hidden rounded-full bg-muted">
                <span className="block h-full rounded-full" style={{ width: `${p * 100}%`, background: level ? scaleColour(use, k) : 'var(--ink)' }} />
              </span>
              <span className="text-right font-mono text-xs tabular-nums">{Math.round(p * 100)}%</span>
            </div>
          ))}
          {r.detail?.close_call ? (
            <span className="inline-flex items-start gap-1.5 text-xs text-warn">
              <AlertTriangle className="mt-px size-3.5 shrink-0" />
              A close call: {Math.round(r.detail.close_call.probability * 100)}% of the probability sits on {use.labels?.[r.detail.close_call.level] ?? r.detail.close_call.level}.
              A threshold in code can send this one to a person.
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">A probability for every option, ready for a threshold in code.</span>
          )}
        </div>
      ) : r.raw_text ? (
        <div className="flex flex-col gap-1.5 text-[13px]">
          <span className="text-muted-foreground">It wrote this, which the server then parsed:</span>
          <code className="w-fit max-w-full overflow-x-auto rounded-md border bg-muted/50 px-2 py-1 font-mono text-xs">{r.raw_text}</code>
          <span className="text-xs text-muted-foreground">No probabilities: text either parses to an answer or it does not.</span>
        </div>
      ) : null}
      {!probs && !r.raw_text && r.detail?.note ? (
        <span className="text-[13px] text-muted-foreground">{r.detail.note}</span>
      ) : null}
    </>
  )
}

function Lane({ lane, state, use, form, setForm }) {
  const { pending, result: r, browserMs, error } = state
  const tick = useTicker(pending)
  const Icon = ICON[lane.key] ?? Bot
  const isJev = lane.key === 'jev'
  const isMatrix = lane.no_model

  return (
    <Card className="@container gap-0 overflow-hidden py-0 shadow-xs">
      <div className="flex items-start justify-between gap-3 border-b px-5 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <span className={cn('grid size-9 shrink-0 place-items-center rounded-lg', isJev ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground')}>
            <Icon className="size-[18px]" />
          </span>
          <div className="min-w-0">
            <div className="text-[15px] font-semibold tracking-[-0.015em]">{lane.name}</div>
            <div className="truncate text-[13px] text-muted-foreground">
              {lane.engine}{lane.model ? <> · <span className="font-mono text-xs">{lane.model}</span></> : null}
            </div>
          </div>
        </div>
        {pending ? (
          <span className="flex shrink-0 items-center gap-1.5 font-mono text-[13px] tabular-nums text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />{ms(tick)}
          </span>
        ) : r && !r.error ? <StatusBadge tone="ok">answered</StatusBadge> : null}
      </div>

      {lane.form?.length ? (
        <div className="flex gap-2 border-b bg-muted/30 px-5 py-3">
          {lane.form.map((f) => (
            <FormPick key={f.key} label={f.label} value={form[f.key]} options={f.options}
              onChange={(v) => setForm((prev) => ({ ...prev, [f.key]: v }))} />
          ))}
        </div>
      ) : null}

      <div className="flex min-h-[150px] flex-col justify-center gap-3 px-5 py-5">
        {error || r?.error ? (
          <div className="flex items-start gap-2 text-sm text-crit"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{error || r.error}</div>
        ) : pending ? (
          <div className="text-sm text-muted-foreground">Asking {lane.engine}…</div>
        ) : r ? <Answer r={r} use={use} /> : (
          <div className="text-sm text-muted-foreground">Not run yet.</div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-px border-t bg-border @md:grid-cols-3">
        <Metric label="Latency" strong value={r ? ms(r.latency_ms) : pending ? ms(tick) : '—'}
          sub={browserMs != null ? `${ms(browserMs)} round trip in your browser` : 'measured on the server'} />
        <Metric label="Cost this call" strong value={r ? usd(r.cost_usd) : '—'}
          sub={isMatrix ? 'no model' : lane.price ? `$${lane.price.input}/M in · ${lane.price.output ? `$${lane.price.output}/M out` : 'output free'}` : null} />
        <Metric label="Per 100k tickets" value={r ? usd(r.cost_usd * 100_000) : '—'} sub="at this call's usage" />
        <Metric label="Input tokens" value={isMatrix ? 'none' : r ? int(r.input_tokens) : '—'} />
        <Metric label="Output tokens" value={isMatrix ? 'none' : r ? int(r.output_tokens) : '—'}
          sub={isJev ? 'not billed' : isMatrix ? null : 'the visible answer'} />
        <Metric label="Thinking tokens" value={isMatrix || isJev ? 'none' : r ? int(r.thinking_tokens) : '—'}
          sub={isMatrix ? (lane.form?.length ? 'nothing reads the text' : 'keywords, not a model') : isJev ? 'no generation' : r ? `billed as output: ${int(r.output_tokens + r.thinking_tokens)} total` : 'billed as output'} />
      </div>

      {r?.request && Object.keys(r.request).length ? (
        <details className="border-t px-5 py-3 text-[13px]">
          <summary className="cursor-pointer select-none text-muted-foreground">
            {isMatrix ? `What the ${lane.engine.toLowerCase()} worked from` : 'Exactly what was sent (the key stays on the server)'}
          </summary>
          <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-muted/50 p-3 font-mono text-[11.5px] leading-relaxed">
            {JSON.stringify(r.request, null, 2)}
          </pre>
        </details>
      ) : null}
    </Card>
  )
}

function Verdict({ lanes, states, use }) {
  const jev = states.jev?.result
  if (!jev || jev.error) return null
  const others = lanes.filter((l) => l.key !== 'jev').map((l) => [l, states[l.key]?.result]).filter(([, r]) => r && !r.error)
  if (!others.length) return null
  return (
    <Card className="gap-0 py-0 shadow-xs">
      {others.map(([l, r]) => {
        const agree = r.answer === jev.answer
        const order = use?.order ?? []
        const apart = order.includes(r.answer) && order.includes(jev.answer)
          ? Math.abs(order.indexOf(r.answer) - order.indexOf(jev.answer)) : null
        return (
          <div key={l.key} className="flex flex-wrap items-center gap-x-8 gap-y-2 border-b px-5 py-4 last:border-b-0">
            <span className="w-40 text-[13px] text-muted-foreground">Jev against {l.name}</span>
            <span className={cn('flex items-center gap-1.5 text-sm font-medium', agree ? 'text-ok' : 'text-crit')}>
              {agree ? <Check className="size-4" /> : <X className="size-4" />}
              {agree ? 'Same answer' : apart != null ? `${apart} level${apart === 1 ? '' : 's'} apart` : 'Different answers'}
            </span>
            {l.no_model ? (
              <span className="text-sm text-muted-foreground">{l.caveat}</span>
            ) : (
              <>
                <span className="text-sm"><span className="font-mono text-lg font-semibold tabular-nums">{(r.latency_ms / jev.latency_ms).toFixed(1)}×</span> <span className="text-muted-foreground">faster with Jev</span></span>
                <span className="text-sm"><span className="font-mono text-lg font-semibold tabular-nums">{(r.cost_usd / jev.cost_usd).toFixed(0)}×</span> <span className="text-muted-foreground">cheaper with Jev</span></span>
                <span className="text-sm text-muted-foreground">
                  saves {usd((r.cost_usd - jev.cost_usd) * 100_000)} and {Math.max(0, (r.latency_ms - jev.latency_ms) * 100_000 / 3_600_000).toFixed(0)} hours of waiting per 100k tickets
                </span>
              </>
            )}
          </div>
        )
      })}
    </Card>
  )
}

export default function Showcase() {
  const [cases, setCases] = useState([])
  const [caseKey, setCaseKey] = useState('kind')
  const [text, setText] = useState('Outlook keeps asking for my password since this morning')
  const [states, setStates] = useState({})
  const [form, setForm] = useState({ impact: 'individual', urgency: 'medium' })
  const [log, setLog] = useState([])
  const [loadError, setLoadError] = useState(null)
  const runId = useRef(0)

  useEffect(() => { api.showcaseCases().then(setCases, (e) => setLoadError(e.message)) }, [])
  const use = cases.find((c) => c.key === caseKey)
  const lanes = use?.lanes ?? []

  useEffect(() => {
    // a new use case starts clean: its own lanes, its own log, its own form defaults
    setStates({})
    setLog([])
    if (use?.form_defaults) setForm(use.form_defaults)
  }, [caseKey, use?.form_defaults])

  const run = useCallback(async (which) => {
    const subject = text.trim()
    if (!subject || !which.length) return
    const id = ++runId.current
    setStates((s) => ({ ...s, ...Object.fromEntries(which.map((k) => [k, { ...idle, pending: true }])) }))
    const entry = { id, text: subject, results: {} }
    await Promise.all(which.map(async (k) => {
      const t0 = performance.now()
      try {
        const r = await api.showcaseRun({ case: caseKey, text: subject, lanes: [k], form })
        entry.results[k] = r.results[k]
        if (runId.current === id) setStates((s) => ({ ...s, [k]: { pending: false, result: r.results[k], browserMs: performance.now() - t0, error: null } }))
      } catch (e) {
        if (runId.current === id) setStates((s) => ({ ...s, [k]: { ...idle, error: e.message } }))
      }
    }))
    setLog((prev) => [entry, ...prev].slice(0, 25))
  }, [caseKey, text, form])

  // the form lane is free and instant, so it follows the pickers live
  const firstForm = useRef(true)
  useEffect(() => {
    if (firstForm.current) { firstForm.current = false; return }
    const formLanes = lanes.filter((l) => l.form?.length && states[l.key]?.result).map((l) => l.key)
    if (formLanes.length) run(formLanes)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form])

  const busy = lanes.some((l) => states[l.key]?.pending)
  const all = lanes.map((l) => l.key)
  const avg = (k, field) => {
    const xs = log.map((e) => e.results[k]).filter((r) => r && !r.error).map((r) => r[field])
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null
  }

  return (
    <div className="scroll"><div className="pad"><div className="cap flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="h1">Showcase</h1>
          <p className="lead mt-1.5">One decision, made several ways, measured on every run.</p>
        </div>
        <label className="flex w-full max-w-sm flex-col gap-1.5 text-[13px] text-muted-foreground">
          Use case
          <Select value={caseKey} onValueChange={setCaseKey}>
            <SelectTrigger className="w-full"><SelectValue placeholder="Pick a use case" /></SelectTrigger>
            <SelectContent>
              {cases.map((c, i) => <SelectItem key={c.key} value={c.key}>{i + 1}. {c.title}</SelectItem>)}
            </SelectContent>
          </Select>
        </label>
      </div>

      {loadError ? <p className="text-sm text-crit">{loadError}</p> : null}

      {use ? (
        <Card className="gap-4 px-5 py-5 shadow-xs">
          <div>
            <div className="text-[15px] font-semibold tracking-[-0.015em]">{use.title}</div>
            <p className="mt-1.5 max-w-[84ch] text-sm leading-relaxed">{use.decision}</p>
            <p className="mt-1.5 max-w-[84ch] text-[13px] leading-relaxed text-muted-foreground">{use.why}</p>
          </div>
          <div className={cn('grid gap-3', lanes.length === 3 ? '@4xl:grid-cols-3' : '@3xl:grid-cols-2')}>
            {lanes.map((l) => {
              const Icon = ICON[l.key] ?? Bot
              return (
                <div key={l.key} className="rounded-lg border bg-muted/30 px-4 py-3">
                  <div className="flex items-center gap-2 text-[13px] font-medium"><Icon className="size-3.5" />{l.name} · {l.engine}</div>
                  <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{l.how}</p>
                </div>
              )
            })}
          </div>
          {use.legend && Object.keys(use.legend).length ? (
            <div className="flex flex-wrap gap-x-5 gap-y-1 text-[13px]">
              {Object.entries(use.legend).map(([k, v]) => (
                <span key={k} className="flex items-center gap-1.5">
                  <span className="size-2 rounded-full" style={{ background: scaleColour(use, k) }} />
                  <span className="font-medium">{use.labels[k]}</span><span className="text-muted-foreground">{v}</span>
                </span>
              ))}
            </div>
          ) : null}
        </Card>
      ) : null}

      <Card className="gap-3 px-5 py-5 shadow-xs">
        <label className="flex flex-col gap-1.5 text-[13px] text-muted-foreground">
          Ticket subject, in the requester&rsquo;s own words
          <Input value={text} onChange={(e) => setText(e.target.value)} maxLength={2000}
            onKeyDown={(e) => { if (e.key === 'Enter' && !busy) run(all) }}
            placeholder="Type any IT issue or request" className="h-11 text-[15px]" />
        </label>
        {use?.examples?.length ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs text-muted-foreground">Try</span>
            {use.examples.map((ex) => (
              <button key={ex} onClick={() => setText(ex)}
                className="rounded-full border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
                {ex}
              </button>
            ))}
          </div>
        ) : null}
      </Card>

      <div className={cn('grid grid-cols-1 gap-4', lanes.length === 3 ? '@6xl:grid-cols-3' : '@4xl:grid-cols-2')}>
        {lanes.map((l) => (
          <Lane key={l.key} lane={l} state={states[l.key] ?? idle} use={use} form={form} setForm={setForm} />
        ))}
      </div>

      <Verdict lanes={lanes} states={states} use={use} />

      <div className="flex flex-wrap gap-2">
        <Button size="lg" onClick={() => run(all)} disabled={busy || !text.trim()}>
          <Play /> {lanes.length > 2 ? 'Run all' : 'Run both'}
        </Button>
        {lanes.map((l) => {
          const Icon = ICON[l.key] ?? Bot
          return (
            <Button key={l.key} size="lg" variant="outline" onClick={() => run([l.key])} disabled={busy || !text.trim()}>
              <Icon /> Run {l.name === 'Traditional' ? 'traditional' : l.name}
            </Button>
          )
        })}
      </div>

      {log.length ? (
        <Card className="gap-0 overflow-hidden py-0 shadow-xs">
          <div className="flex flex-wrap items-baseline justify-between gap-3 border-b px-5 py-4">
            <div className="text-[15px] font-semibold tracking-[-0.015em]">This session</div>
            <div className="flex flex-wrap gap-5 text-[13px] text-muted-foreground">
              {lanes.filter((l) => !l.no_model).map((l) => (
                <span key={l.key}>{l.name} averages <span className="font-mono text-foreground">{ms(avg(l.key, 'latency_ms'))}</span> · <span className="font-mono text-foreground">{usd(avg(l.key, 'cost_usd'))}</span></span>
              ))}
            </div>
          </div>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-5">Subject</TableHead>
                  {lanes.map((l) => [
                    <TableHead key={`${l.key}a`}>{l.name}</TableHead>,
                    <TableHead key={`${l.key}m`} className="text-right">ms</TableHead>,
                    <TableHead key={`${l.key}c`} className="text-right">cost</TableHead>,
                  ])}
                </TableRow>
              </TableHeader>
              <TableBody>
                {log.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="max-w-[300px] truncate pl-5">{e.text}</TableCell>
                    {lanes.map((l) => {
                      const r = e.results[l.key]
                      const ok = r && !r.error
                      return [
                        <TableCell key={`${l.key}a`}>{r ? (r.error ? <span className="text-crit">error</span> : r.label) : <span className="text-muted-foreground">—</span>}</TableCell>,
                        <TableCell key={`${l.key}m`} className="text-right font-mono text-[13px]">{ok ? ms(r.latency_ms) : ''}</TableCell>,
                        <TableCell key={`${l.key}c`} className="text-right font-mono text-[13px]">{ok ? usd(r.cost_usd) : ''}</TableCell>,
                      ]
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </Card>
      ) : null}
    </div></div></div>
  )
}
