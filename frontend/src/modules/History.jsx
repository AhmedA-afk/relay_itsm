import { useEffect, useState } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, LabelList, XAxis, YAxis } from 'recharts'
import { Card } from '@/components/kit/card'
import { ChartContainer, ChartTooltip } from '@/components/kit/chart'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/kit/table'
import { PageHead, Panel, StatusBadge } from '@/components/blocks'
import { Ring } from '../components/ui'
import { api } from '../lib/api'
import { C, heat, priorityColour } from '../lib/format'

/**
 * Closed tickets from two public datasets, cleaned by relay.import_history.
 * Read-only and deliberately separate from the live desk: nothing here runs a
 * clock or appears in a queue.
 */

const fmt = (n) => n?.toLocaleString('en-GB') ?? '—'
const hours = (h) => (h == null ? '—' : h < 48 ? `${h.toFixed(1)} h` : `${(h / 24).toFixed(1)} d`)
const SYNTHETIC = 'gcc_desk'
const SAT = [['satisfied', C.ok], ['neutral', 'var(--ink4)'], ['dissatisfied', C.crit]]

function Tip({ active, payload, render }) {
  if (!active || !payload?.length) return null
  return (
    <div className="grid min-w-[9rem] gap-1 rounded-lg border bg-popover px-3 py-2 text-xs shadow-lg">
      {render(payload[0].payload)}
    </div>
  )
}
const Line = ({ k, v }) => (
  <div className="flex justify-between gap-4 text-muted-foreground">{k}<span className="font-mono text-foreground">{v}</span></div>
)

/** One row of a 100% stacked bar, drawn as plain flex segments. */
function Stack({ parts, total }) {
  return (
    <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted">
      {parts.map(([key, n, colour]) => n ? (
        <div key={key} title={`${key}: ${fmt(n)} (${Math.round((n / total) * 100)}%)`}
          style={{ width: `${(n / total) * 100}%`, background: colour }} className="h-full first:rounded-l-full last:rounded-r-full" />
      ) : null)}
    </div>
  )
}

export default function History({ onGo }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => { api.history().then(setData, (e) => setError(e.message)) }, [])

  if (error) return <div className="pad"><p className="mt" style={{ color: C.crit }}>{error}</p></div>
  if (!data) return <div className="pad"><p className="mt">Loading 146k tickets…</p></div>
  if (data.empty) {
    return (
      <div className="pad"><PageHead title="Ticket history">
        Nothing imported yet. Run <span className="font-mono">python -m relay.import_history</span> in the backend.
      </PageHead></div>
    )
  }

  const agree = data.matrix_agreement
  const agreeShare = agree.agree / Math.max(1, agree.agree + agree.disagree)
  const costs = data.reassignment_cost
  const base = costs[0]?.median || 1
  const byPrio = ['P1', 'P2', 'P3', 'P4'].map((p) => ({
    p,
    ...Object.fromEntries(data.sources.map((s) => [s.source, (data.resolution[s.source] ?? []).find((r) => r.priority === p)])),
  }))

  return (
    <div className="scroll"><div className="pad"><div className="cap flex flex-col gap-4">
      <PageHead title="Ticket history">
        {fmt(data.total)} closed tickets from two public datasets, cleaned into Relay&rsquo;s vocabulary.
        None of them enter the live queue; they are here to learn from.
      </PageHead>

      <div className="mt-2 grid grid-cols-1 gap-4 @3xl:grid-cols-2">
        {data.sources.map((s) => {
          const months = data.monthly[s.source] ?? []
          return (
            <Card key={s.source} className="gap-0 overflow-hidden py-0 shadow-xs">
              <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
                <div className="min-w-0">
                  <div className="text-[13px] text-muted-foreground">{s.label}</div>
                  <div className="mt-1.5 text-[32px] font-semibold leading-none tracking-[-0.04em] tabular-nums">{fmt(s.total)}</div>
                  <div className="mt-2 text-[13px] text-muted-foreground">
                    <span className="font-medium text-foreground">{fmt(s.incidents)}</span> incidents ·{' '}
                    <span className="font-medium text-foreground">{fmt(s.requests)}</span> requests ·{' '}
                    {s.from} to {s.to}
                  </div>
                </div>
                {s.source === SYNTHETIC
                  ? <StatusBadge tone="warn">evenly spread: treat as synthetic</StatusBadge>
                  : <StatusBadge tone="ok">operational export</StatusBadge>}
              </div>
              <ChartContainer config={{ count: { label: 'Opened' } }} className="aspect-auto h-[92px] w-full">
                <AreaChart data={months} margin={{ top: 16, right: 0, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id={`fill-${s.source}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--ink)" stopOpacity={0.14} />
                      <stop offset="100%" stopColor="var(--ink)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <ChartTooltip cursor={false} content={<Tip render={(d) => (<><div className="font-mono font-medium">{d.month}</div><Line k="Opened" v={fmt(d.count)} /></>)} />} />
                  <Area dataKey="count" type="monotone" stroke="var(--ink3)" strokeWidth={1.5} fill={`url(#fill-${s.source})`} />
                </AreaChart>
              </ChartContainer>
              <div className="border-t px-5 py-2.5 font-mono text-[11.5px] text-muted-foreground">{s.origin}</div>
            </Card>
          )
        })}
      </div>

      <div className="grid grid-cols-1 gap-4 @3xl:grid-cols-6 @8xl:grid-cols-12">
        <Panel
          title="Every hand-off costs a day"
          description="ABC Tech: median time to resolve, by how many times the ticket was reassigned"
          className="@3xl:col-span-6 @8xl:col-span-8"
          footer={
            <span>
              A ticket passed six times takes <span className="font-medium text-foreground">{Math.round(costs.at(-1).median / base)}×</span> as
              long as one that lands right first time. This is the case for routing to a person, not just a team.
            </span>
          }
        >
          <ChartContainer config={{ median: { label: 'Median' } }} className="aspect-auto min-h-[240px] w-full flex-1">
            <BarChart data={costs} margin={{ top: 24, right: 8, left: 8, bottom: 0 }}>
              <CartesianGrid vertical={false} strokeDasharray="3 3" />
              <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={10} fontSize={12}
                tickFormatter={(v) => (v === 'none' ? 'first time' : `${v} hand-off${v === '1' ? '' : 's'}`)} />
              <YAxis hide />
              <ChartTooltip cursor={{ fill: 'var(--g1)', radius: 8 }} content={
                <Tip render={(d) => (<><div className="font-medium">{d.label === 'none' ? 'Never reassigned' : `${d.label} reassignments`}</div><Line k="Median" v={hours(d.median)} /><Line k="Tickets" v={fmt(d.n)} /></>)} />
              } />
              <Bar dataKey="median" radius={[6, 6, 2, 2]} maxBarSize={72}>
                {costs.map((c, i) => <Cell key={c.label} fill={heat(i / (costs.length - 1) * 1.05, false)} />)}
                <LabelList dataKey="median" position="top" offset={8} formatter={hours}
                  className="fill-foreground" fontSize={12.5} fontWeight={600} />
              </Bar>
            </BarChart>
          </ChartContainer>
        </Panel>

        <Panel
          title="The matrix already knew"
          description="ABC Tech's recorded priority against Relay's matrix, read off the same impact and urgency"
          className="@3xl:col-span-6 @8xl:col-span-4"
          contentClassName="items-center justify-center gap-4 py-2"
          footer={`${fmt(agree.disagree)} of ${fmt(agree.agree + agree.disagree)} disagree. ${fmt(data.priority_mix.abc_tech?.unset ?? 0)} had no impact set and are left out.`}
        >
          <Ring v={agreeShare} c={C.ok} big={`${(agreeShare * 100).toFixed(1)}%`} small="agree" r={64} sw={11} bs={28}
            label="Share of tickets whose recorded priority matches the matrix" />
          <p className="max-w-[34ch] text-center text-[13px] leading-relaxed text-muted-foreground">
            Their people and Relay&rsquo;s matrix land on the same level almost every time, which is
            what makes impact and urgency worth reading correctly at intake.
          </p>
        </Panel>

        <Panel
          title="Time to resolve, by priority"
          description="Median and 90th percentile. The two desks run on very different clocks."
          className="@3xl:col-span-6 @8xl:col-span-7"
          contentClassName="px-0"
        >
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-5">Level</TableHead>
                {data.sources.map((s) => (
                  <TableHead key={s.source} colSpan={3} className="text-right">{s.label}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow className="text-xs text-muted-foreground hover:bg-transparent">
                <TableCell className="pl-5" />
                {data.sources.map((s) => (
                  [<TableCell key={`${s.source}n`} className="text-right">tickets</TableCell>,
                   <TableCell key={`${s.source}m`} className="text-right">median</TableCell>,
                   <TableCell key={`${s.source}p`} className="pr-5 text-right">p90</TableCell>]
                ))}
              </TableRow>
              {byPrio.map((row) => (
                <TableRow key={row.p}>
                  <TableCell className="pl-5"><StatusBadge tone={priorityColour(row.p)}><span className="font-mono">{row.p}</span></StatusBadge></TableCell>
                  {data.sources.map((s) => {
                    const r = row[s.source]
                    return [
                      <TableCell key={`${s.source}n`} className="text-right font-mono text-xs text-muted-foreground">{fmt(r?.n)}</TableCell>,
                      <TableCell key={`${s.source}m`} className="text-right font-mono text-[13px]">{hours(r?.median)}</TableCell>,
                      <TableCell key={`${s.source}p`} className="pr-5 text-right font-mono text-[13px] text-muted-foreground">{hours(r?.p90)}</TableCell>,
                    ]
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="px-5 pt-4 text-[13px] text-muted-foreground">
            ABC Tech&rsquo;s P1 row rests on {fmt(byPrio[0].abc_tech?.n)} tickets; read it as an anecdote, not a rate.
          </p>
        </Panel>

        <Panel
          title="Priority mix"
          description="Share of each desk's tickets at each level"
          className="@3xl:col-span-6 @8xl:col-span-5"
          contentClassName="justify-center gap-6"
          footer={
            <div className="flex flex-wrap gap-1.5">
              {['P1', 'P2', 'P3', 'P4'].map((p) => <StatusBadge key={p} tone={priorityColour(p)}><span className="font-mono">{p}</span></StatusBadge>)}
              <StatusBadge tone="var(--g3)">not set</StatusBadge>
            </div>
          }
        >
          {data.sources.map((s) => {
            const m = data.priority_mix[s.source] ?? {}
            const parts = ['P1', 'P2', 'P3', 'P4'].map((p) => [p, m[p] ?? 0, priorityColour(p)]).concat([['not set', m.unset ?? 0, 'var(--g3)']])
            return (
              <div key={s.source}>
                <div className="mb-2 flex items-baseline justify-between gap-3 text-sm">
                  <span>{s.label}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    P1–P2 {Math.round((((m.P1 ?? 0) + (m.P2 ?? 0)) / s.total) * 100)}%
                  </span>
                </div>
                <Stack parts={parts} total={s.total} />
              </div>
            )
          })}
        </Panel>

        <Panel
          title="Why ABC Tech tickets closed"
          description="Closure cause, as recorded. Two Dutch codes translated."
          className="@3xl:col-span-3 @8xl:col-span-6"
        >
          <ChartContainer config={{ count: { label: 'Tickets' } }} className="aspect-auto w-full flex-1" style={{ minHeight: data.closure.length * 32 + 16 }}>
            <BarChart data={data.closure} layout="vertical" margin={{ top: 0, right: 56, left: 0, bottom: 0 }} barCategoryGap="24%">
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="label" width={176} tickLine={false} axisLine={false} fontSize={12} />
              <ChartTooltip cursor={{ fill: 'var(--g1)' }} content={<Tip render={(d) => (<><div className="font-medium">{d.label}</div><Line k="Tickets" v={fmt(d.count)} /></>)} />} />
              <Bar dataKey="count" fill="var(--ink3)" radius={[3, 5, 5, 3]} maxBarSize={18}>
                <LabelList dataKey="count" position="right" offset={8} formatter={fmt} className="fill-muted-foreground" fontSize={12} fontFamily="var(--mo)" />
              </Bar>
            </BarChart>
          </ChartContainer>
        </Panel>

        <Panel
          title="Satisfaction by channel"
          description="Gulf desk survey results"
          className="@3xl:col-span-3 @8xl:col-span-6"
          contentClassName="justify-center gap-5"
          footer="Each channel splits almost exactly into thirds, and every ticket met its target. Real desks do not look like this; it is why this set is marked synthetic."
        >
          {Object.entries(data.satisfaction).sort().map(([channel, counts]) => {
            const total = Object.values(counts).reduce((a, b) => a + b, 0)
            return (
              <div key={channel}>
                <div className="mb-2 flex items-baseline justify-between gap-3 text-sm">
                  <span className="capitalize">{channel}</span>
                  <span className="font-mono text-xs text-muted-foreground">{Math.round(((counts.satisfied ?? 0) / total) * 100)}% satisfied</span>
                </div>
                <Stack parts={SAT.map(([k, colour]) => [k, counts[k] ?? 0, colour])} total={total} />
              </div>
            )
          })}
        </Panel>

        {data.cleaning ? (
          <Panel
            title="What the cleaning did"
            description={`Every repair the importer made, by rule. ${
              Object.values(data.cleaning).reduce((n, c) => n + c.refused, 0)
                ? `${fmt(Object.values(data.cleaning).reduce((n, c) => n + c.refused, 0))} rows were refused.`
                : 'No row had to be refused.'}`}
            className="@3xl:col-span-6 @8xl:col-span-12"
            contentClassName="px-0"
          >
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-5">Source</TableHead>
                  <TableHead>Rule</TableHead>
                  <TableHead className="pr-5 text-right">Rows</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(data.cleaning).flatMap(([source, c]) => Object.entries(c.rules)
                  .sort((a, b) => b[1] - a[1])
                  .map(([rule, n], i) => (
                    <TableRow key={source + rule}>
                      <TableCell className="pl-5 text-muted-foreground">{i === 0 ? (data.sources.find((s) => s.source === source)?.label ?? source) : ''}</TableCell>
                      <TableCell className="whitespace-normal">{rule}</TableCell>
                      <TableCell className="pr-5 text-right font-mono text-[13px]">
                        {fmt(n)} <span className="text-muted-foreground">/ {fmt(c.seen)}</span>
                      </TableCell>
                    </TableRow>
                  )))}
              </TableBody>
            </Table>
          </Panel>
        ) : null}
      </div>
    </div></div></div>
  )
}
