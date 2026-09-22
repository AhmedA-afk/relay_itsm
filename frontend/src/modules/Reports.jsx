import { useEffect, useState } from 'react'
import { ArrowUpRight } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine, XAxis, YAxis } from 'recharts'
import { Button } from '@/components/kit/button'
import { Card } from '@/components/kit/card'
import { ChartContainer, ChartTooltip } from '@/components/kit/chart'
import { Kpi, PageHead, Panel, StatusBadge } from '@/components/blocks'
import { Meter, Mood, Ring, Risk } from '../components/ui'
import { api } from '../lib/api'
import { C, moodColour, moodLabel, priorityColour, riskColour, riskLabel, useCountUp } from '../lib/format'

const BUCKET_COLOURS = [C.ok, C.ok, C.warn, C.warn, C.hot, C.crit]
const TARGET = 95

function Tip({ active, payload, render }) {
  if (!active || !payload?.length) return null
  return (
    <div className="grid min-w-[9rem] gap-1 rounded-lg border bg-popover px-3 py-2 text-xs shadow-lg">
      {render(payload[0].payload)}
    </div>
  )
}

const Row = ({ k, v }) => (
  <div className="flex justify-between gap-4 text-muted-foreground">{k}<span className="font-mono text-foreground">{v}</span></div>
)

export default function Reports({ onGo, onOpen }) {
  const [data, setData] = useState(null)
  const [mood, setMood] = useState(null)
  const [risk, setRisk] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.reports().then(setData, (e) => setError(e.message))
    api.sentimentSummary().then(setMood, () => {})
    api.escalationSummary().then(setRisk, () => {})
  }, [])

  const attainment = useCountUp(data?.attainment ?? 0)

  if (error) return <div className="pad"><p className="mt" style={{ color: C.crit }}>{error}</p></div>
  if (!data) return <div className="pad"><p className="mt">Loading…</p></div>

  const buckets = data.age_buckets.map((b, i) => ({
    ...b, fill: BUCKET_COLOURS[i],
    share: data.open_total ? Math.round((b.count / data.open_total) * 100) : 0,
  }))
  const teams = data.by_team.map((t) => ({ ...t, value: Number(t.attainment.toFixed(1)) }))
  const under = teams.filter((t) => t.value < TARGET)

  return (
    <div className="scroll"><div className="pad"><div className="cap flex flex-col gap-4">
      <PageHead title="Reports">
        {data.open_total} open right now. Everything here is computed from the same records
        the queue reads, not from a separate warehouse.
      </PageHead>

      <div className="mt-2 grid grid-cols-1 gap-4 @xl:grid-cols-2 @5xl:grid-cols-4">
        <Card className="flex-row items-center gap-5 px-5 py-5 shadow-xs">
          <Ring
            v={(data.attainment ?? 0) / 100}
            c={data.attainment >= TARGET ? C.ok : C.warn}
            r={30} sw={7}
            label="Share of tickets inside target"
          />
          <div className="min-w-0">
            <div className="text-[13px] text-muted-foreground">Inside target</div>
            <div className="mt-1 text-[22px] font-semibold tracking-[-0.03em] tabular-nums">{attainment.toFixed(1)}%</div>
            <div className="mt-1.5">
              <StatusBadge tone={data.attainment >= TARGET ? 'ok' : 'warn'}>goal {TARGET}%</StatusBadge>
            </div>
          </div>
        </Card>
        <Kpi label="Open" value={data.open_total} foot="Across both modules" sub={`${data.major_total} major`} />
        <Kpi
          label="Past target" value={data.breached_total}
          badge={data.breached_total ? 'breached' : 'clear'} tone={data.breached_total ? 'crit' : 'ok'}
          foot={data.breached_total ? `${data.breached_total} of ${data.open_total} open` : 'Nothing past target'}
          sub="Clock ran out before a fix"
        />
        <Kpi
          label="Unclaimed" value={data.unassigned_total}
          badge={data.unassigned_total ? 'waiting' : 'owned'} tone={data.unassigned_total ? 'hot' : 'ok'}
          foot="Nobody has picked these up" sub="Routing leaves them on the team"
        />
      </div>

      {/* Two across at medium widths with the level panel spanning under them;
          three across once the page is wide enough to hold them side by side. */}
      <div className="grid grid-cols-1 gap-4 @3xl:grid-cols-2 @8xl:grid-cols-3">
        <Panel
          title="How long open tickets have waited"
          description="Anything past two days is where goodwill goes"
          footer="Colour moves from fresh to stale; it is age, not priority."
        >
          <ChartContainer config={{ count: { label: 'Tickets' } }} className="aspect-auto min-h-[230px] w-full flex-1">
            <BarChart data={buckets} margin={{ top: 22, right: 4, left: 4, bottom: 0 }}>
              <CartesianGrid vertical={false} strokeDasharray="3 3" />
              <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={10} fontSize={12} />
              <YAxis hide allowDecimals={false} />
              <ChartTooltip cursor={{ fill: 'var(--g1)', radius: 8 }} content={
                <Tip render={(d) => (<><div className="font-medium">{d.label}</div><Row k="Tickets" v={d.count} /><Row k="Of open" v={`${d.share}%`} /></>)} />
              } />
              <Bar dataKey="count" radius={[6, 6, 2, 2]} maxBarSize={52} minPointSize={2}>
                {buckets.map((b) => <Cell key={b.label} fill={b.fill} fillOpacity={b.count ? 1 : 0.25} />)}
                <LabelList dataKey="count" position="top" offset={8} className="fill-foreground" fontSize={13} fontWeight={600} />
              </Bar>
            </BarChart>
          </ChartContainer>
        </Panel>

        <Panel
          title="Who is missing targets"
          description={`Share of each team's tickets closed inside target, against the ${TARGET}% goal`}
          action={
            <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => onGo('incidents')}>
              Open queue <ArrowUpRight />
            </Button>
          }
          footer={
            under.length
              ? <span><span className="font-medium text-foreground">{under.map((t) => t.team).join(', ')}</span> {under.length === 1 ? 'is' : 'are'} under the line. The gap to {TARGET}% is what matters.</span>
              : <span>Every team is at or over {TARGET}%.</span>
          }
        >
          <ChartContainer config={{ value: { label: 'Attainment' } }} className="aspect-auto w-full flex-1" style={{ minHeight: Math.max(210, teams.length * 42 + 30) }}>
            <BarChart data={teams} layout="vertical" margin={{ top: 14, right: 48, left: 0, bottom: 4 }} barCategoryGap="22%">
              <CartesianGrid horizontal={false} strokeDasharray="3 3" />
              <XAxis type="number" domain={[0, 100]} hide />
              <YAxis type="category" dataKey="team" width={88} tickLine={false} axisLine={false}
                tick={{ fontFamily: 'var(--mo)', fontSize: 12 }} />
              <ReferenceLine x={TARGET} stroke="var(--ink3)" strokeDasharray="4 4"
                label={{ value: `${TARGET}%`, position: 'top', fontSize: 11, fill: 'var(--ink3)', fontFamily: 'var(--mo)' }} />
              <ChartTooltip cursor={{ fill: 'var(--g1)' }} content={
                <Tip render={(d) => (<><div className="font-mono font-medium">{d.team}</div><Row k="Inside target" v={`${d.value}%`} /><Row k="Gap to goal" v={d.value >= TARGET ? '—' : `${(TARGET - d.value).toFixed(1)} pts`} /></>)} />
              } />
              <Bar dataKey="value" radius={[3, 6, 6, 3]} maxBarSize={22} background={{ fill: 'var(--g1)', radius: 6 }}>
                {teams.map((t) => <Cell key={t.team} fill={t.value >= TARGET ? C.ok : C.warn} />)}
                <LabelList dataKey="value" position="right" offset={8} formatter={(v) => `${v}%`}
                  className="fill-muted-foreground" fontSize={12} fontFamily="var(--mo)" />
              </Bar>
            </BarChart>
          </ChartContainer>
        </Panel>

      <Panel
        title="Open work by level"
        description="Read out of the matrix, so editing it in administration moves these numbers"
        className="@3xl:col-span-2 @8xl:col-span-1"
        contentClassName="@container"
      >
        {/* Hairline grid: 1px gaps over the border colour. Four across when the
            panel is wide, two by two when it shares a row. */}
        <div className="grid flex-1 grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border @2xl:grid-cols-4">
          {data.by_priority.map((p) => (
            <div key={p.priority} className="flex flex-col justify-between gap-3 bg-card p-4">
              <div className="flex items-center justify-between">
                <StatusBadge tone={priorityColour(p.priority)}>
                  <span className="font-mono">{p.priority}</span>
                </StatusBadge>
              </div>
              <div className="text-[32px] font-semibold leading-none tracking-[-0.04em] tabular-nums">{p.count}</div>
              <Meter v={p.worst_burn} c={priorityColour(p.priority)} />
              <div className="text-[13px] text-muted-foreground">
                {p.count ? `Worst at ${Math.round(p.worst_burn * 100)}% of its target` : 'None open'}
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {mood ? (
        <Panel
          className="@3xl:col-span-2 @8xl:col-span-3"
          title="How people sound"
          description={
            mood.read
              ? `Read from the conversation on ${mood.read} open ticket${mood.read === 1 ? '' : 's'}, 1 unhappiest to 5 happiest`
              : 'Nothing read yet — open a ticket and read its thread'
          }
          action={
            mood.unread ? (
              <span className="text-[13px] text-muted-foreground">{mood.unread} not read</span>
            ) : null
          }
          footer={
            <span>
              Sentiment is the one number Relay stores rather than derives, because it costs a model
              call. Each reading keeps the message it last read, so
              {' '}{mood.stale ? <span className="font-medium text-foreground">{mood.stale} of these are marked out of date</span> : 'none of these are out of date'}
              {' '}rather than quietly ageing. Closed tickets are left out: their satisfaction is history.
            </span>
          }
        >
          {mood.read ? (
            <div className="flex flex-col gap-5 @3xl:flex-row">
              <div className="flex shrink-0 items-center gap-5">
                <div>
                  <div className="text-[13px] text-muted-foreground">Average</div>
                  <div
                    className="mt-1 text-[34px] font-semibold leading-none tracking-[-0.04em] tabular-nums"
                    style={{ color: moodColour(Math.round(mood.average)) }}
                  >{mood.average?.toFixed(1)}</div>
                  <div className="mt-1.5">
                    <StatusBadge tone={mood.unhappy ? 'hot' : 'ok'}>
                      {mood.unhappy ? `${mood.unhappy} unhappy` : 'nobody unhappy'}
                    </StatusBadge>
                  </div>
                </div>
                <div className="flex h-[92px] items-end gap-1.5">
                  {Object.entries(mood.spread).map(([level, n]) => {
                    const most = Math.max(1, ...Object.values(mood.spread))
                    return (
                      <div key={level} className="flex w-9 flex-col items-center gap-1.5" title={moodLabel(Number(level))}>
                        <span className="text-[11.5px] tabular-nums text-muted-foreground">{n || ''}</span>
                        <span
                          className="w-full rounded-t-[3px]"
                          style={{ height: `${Math.max(2, (n / most) * 58)}px`, background: moodColour(Number(level)),
                                   opacity: n ? 1 : 0.22 }}
                        />
                        <span className="font-mono text-[11px] text-muted-foreground">{level}</span>
                      </div>
                    )
                  })}
                </div>
              </div>

              <div className="min-w-0 flex-1">
                <div className="text-[13px] text-muted-foreground">Unhappiest open tickets</div>
                <div className="mt-1.5 flex flex-col">
                  {mood.unhappiest.slice(0, 5).map((t) => (
                    <button
                      key={t.id} onClick={() => onOpen?.(t.id)}
                      className="flex items-center gap-3 border-b py-2 text-left last:border-b-0 hover:bg-muted/50"
                    >
                      <Mood s={t} />
                      <span className="font-mono text-[11.5px] text-muted-foreground">{t.id}</span>
                      <span className="min-w-0 flex-1 truncate text-[13px]">{t.subject}</span>
                      <span className="shrink-0 text-[12px] text-muted-foreground">{t.assignee ?? 'nobody'}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed px-4 py-6 text-[13px] text-muted-foreground">
              A survey asks weeks after the ticket closed, when nothing can be done. This reads what
              people already wrote, while the ticket is still open — but somebody has to read it first.
            </div>
          )}
        </Panel>
      ) : null}

      {risk ? (
        <Panel
          className="@3xl:col-span-2 @8xl:col-span-3"
          title="What is about to go wrong"
          description={
            risk.read
              ? `Predicted on ${risk.read} open ticket${risk.read === 1 ? '' : 's'}: the chance each one escalates before it is resolved`
              : 'Nothing predicted yet — open a ticket and ask'
          }
          action={risk.unread ? <span className="text-[13px] text-muted-foreground">{risk.unread} not asked</span> : null}
          footer={
            <span>
              The probability is the model&rsquo;s; the {Math.round(risk.thresholds.watch * 100)}% watch line
              and the {Math.round(risk.thresholds.likely * 100)}% act line are policy, and moving them
              re-runs no inference. A prediction ages on the clock as well as on messages, so
              {' '}{risk.stale ? <span className="font-medium text-foreground">{risk.stale} of these want asking again</span> : 'none of these are out of date'}.
            </span>
          }
        >
          {risk.read ? (
            <div className="flex flex-col gap-5 @3xl:flex-row">
              <div className="flex shrink-0 gap-5">
                <div>
                  <div className="text-[13px] text-muted-foreground">Flagged</div>
                  <div
                    className="mt-1 text-[34px] font-semibold leading-none tracking-[-0.04em] tabular-nums"
                    style={{ color: risk.flagged ? riskColour(risk.bands.likely ? 'likely' : 'watch') : C.mute }}
                  >{risk.flagged}</div>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    <StatusBadge tone="crit">{risk.bands.likely} likely</StatusBadge>
                    <StatusBadge tone="warn">{risk.bands.watch} watch</StatusBadge>
                  </div>
                </div>
                <div className="max-w-[200px] border-l pl-5">
                  <div className="text-[13px] text-muted-foreground">Seen early</div>
                  <div className="mt-1 text-[34px] font-semibold leading-none tracking-[-0.04em] tabular-nums">
                    {risk.early}
                  </div>
                  <div className="mt-1.5 text-[12px] leading-snug text-muted-foreground">
                    flagged while still inside half their target, so no SLA rule has fired on them yet
                  </div>
                </div>
              </div>

              <div className="min-w-0 flex-1">
                <div className="text-[13px] text-muted-foreground">Most likely to escalate</div>
                <div className="mt-1.5 flex flex-col">
                  {risk.riskiest.slice(0, 5).map((t) => (
                    <button
                      key={t.id} onClick={() => onOpen?.(t.id)}
                      className="flex items-center gap-3 border-b py-2 text-left last:border-b-0 hover:bg-muted/50"
                    >
                      <Risk r={t} />
                      <span className="font-mono text-[11.5px] text-muted-foreground">{t.id}</span>
                      <span className="min-w-0 flex-1 truncate text-[13px]">{t.subject}</span>
                      <span className="shrink-0 font-mono text-[11.5px] text-muted-foreground">
                        {Math.round(t.burn * 100)}% used
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed px-4 py-6 text-[13px] text-muted-foreground">
              Every ITSM tool can tell you a ticket has breached. This is the question of which one is
              about to — but somebody has to ask it first.
            </div>
          )}
        </Panel>
      ) : null}
      </div>
    </div></div></div>
  )
}
