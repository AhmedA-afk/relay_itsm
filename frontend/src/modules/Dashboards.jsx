import { ArrowUpRight, Pause, Play } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine, XAxis, YAxis } from 'recharts'
import { Button } from '@/components/kit/button'
import { ChartContainer, ChartTooltip } from '@/components/kit/chart'
import { Kpi, PageHead, Panel, StatusBadge, useFit } from '@/components/blocks'
import { Avatar, Ring, Sev } from '../components/ui'
import { C, PRIORITIES, burnFor, clock, heat, isLive, priorityColour, remainingFor } from '../lib/format'

const ROW = 44

/** A tooltip in the shadcn chart style, fed plain rows. */
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

/**
 * The layout answers to the width of the page (a container query on .cap), not
 * the window:
 *   narrow   one column
 *   @3xl     six tracks: gauge + list, then the two charts, then workload
 *   1400px+  twelve tracks: gauge, list and levels share a row; pressure and
 *            workload share the next
 * Every panel stretches to its row and hands the spare height to its chart or
 * list, so a tall neighbour never leaves a hole underneath a short one.
 */
export default function Dashboards({ tickets, now, running, setRunning, onOpen, onGo }) {
  const open = tickets.filter(isLive)
  const over = open.filter((t) => remainingFor(t, now) < 0)
  const hour = open.filter((t) => {
    const r = remainingFor(t, now)
    return r >= 0 && r <= 3600
  })
  const unclaimed = open.filter((t) => !t.assignee)
  const queue = open.slice().sort((a, b) => remainingFor(a, now) - remainingFor(b, now))
  const met = open.length ? Math.max(0, 1 - over.length / open.length) : 1
  const soonest = queue.find((t) => remainingFor(t, now) >= 0)

  const [listRef, fits] = useFit(ROW, 4)
  const shown = queue.slice(0, fits)

  const teams = Object.values(
    open.reduce((acc, t) => {
      const key = t.team ?? 'unassigned'
      acc[key] ??= { key, n: 0, worst: 0 }
      acc[key].n += 1
      acc[key].worst = Math.max(acc[key].worst, burnFor(t, now))
      return acc
    }, {}),
  ).sort((a, b) => b.worst - a.worst)
    .map((t) => ({ ...t, pct: Math.round(t.worst * 100) }))
  const teamMax = Math.max(120, ...teams.map((t) => t.pct))

  const levels = PRIORITIES.map((level) => {
    const mine = open.filter((t) => t.priority === level)
    const worst = mine.reduce((acc, t) => Math.max(acc, burnFor(t, now)), 0)
    return { level, count: mine.length, worst: Math.round(worst * 100) }
  })

  const people = Object.values(
    open.reduce((acc, t) => {
      const key = t.assignee ?? ''
      acc[key] ??= { name: t.assignee, n: 0, late: 0, worst: 0 }
      acc[key].n += 1
      acc[key].worst = Math.max(acc[key].worst, burnFor(t, now))
      if (remainingFor(t, now) < 0) acc[key].late += 1
      return acc
    }, {}),
  ).sort((a, b) => (a.name ? 0 : 1) - (b.name ? 0 : 1) || b.n - a.n || b.worst - a.worst)
  const busiest = Math.max(1, ...people.map((p) => p.n))

  return (
    <div className="scroll"><div className="pad"><div className="cap flex flex-col gap-4">
      <PageHead
        title="The desk, right now"
        action={
          <Button variant="outline" onClick={() => setRunning(!running)}>
            {running ? <Pause /> : <Play className="text-ok" />}
            {running ? 'Pause the clocks' : 'Clocks paused'}
          </Button>
        }
      >
        {over.length ? (
          <span className="text-crit">
            {over.length} {over.length === 1 ? 'ticket is' : 'tickets are'} past target
          </span>
        ) : (
          <span className="text-ok">Everything is inside its target</span>
        )}
        <span>, {hour.length} due inside the hour, {unclaimed.length} still unclaimed.</span>
      </PageHead>

      <div className="mt-2 grid grid-cols-1 gap-4 @xl:grid-cols-2 @5xl:grid-cols-4">
        <Kpi
          label="Open" value={open.length}
          badge="live" tone="ok"
          foot={`${open.filter((t) => t.kind === 'incident').length} incidents, ${open.filter((t) => t.kind !== 'incident').length} requests`}
          sub="Across both modules"
        />
        <Kpi
          label="Past target" value={over.length}
          badge={over.length ? 'breached' : 'clear'} tone={over.length ? 'crit' : 'ok'}
          foot={over.length ? 'Reply before anything new' : 'Nothing has slipped'}
          sub={`${Math.round(met * 100)}% of open work still inside target`}
          onClick={() => onGo('incidents')}
        />
        <Kpi
          label="Due inside the hour" value={hour.length}
          badge={hour.length ? 'soon' : 'quiet'} tone={hour.length ? 'warn' : 'mute'}
          foot={soonest ? `Next: ${soonest.id} in ${clock(remainingFor(soonest, now))}` : 'Nothing close'}
          sub="Before it tips past target"
        />
        <Kpi
          label="Unclaimed" value={unclaimed.length}
          badge={unclaimed.length ? 'waiting' : 'owned'} tone={unclaimed.length ? 'hot' : 'ok'}
          foot={unclaimed.length ? 'Nobody is on these yet' : 'Every ticket has an owner'}
          sub="Assign from the queue with A"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 @3xl:grid-cols-6 @8xl:grid-cols-12">
        <Panel
          title="Holding the line"
          description="Share of open work still inside its target"
          className="@3xl:col-span-2 @8xl:col-span-3"
          contentClassName="items-center justify-center gap-5 py-2"
          footer={
            <div className="flex w-full items-center justify-between gap-3">
              <StatusBadge tone="ok">{open.length - over.length} inside</StatusBadge>
              <StatusBadge tone="crit">{over.length} over</StatusBadge>
            </div>
          }
        >
          <Ring
            v={met} c={over.length ? C.warn : C.ok} big={`${Math.round(met * 100)}%`}
            small="in target" r={70} sw={12} bs={34}
            label="Share of open tickets still inside target"
          />
          <p className="max-w-[30ch] text-center text-[13px] leading-relaxed text-muted-foreground">
            {over.length
              ? 'The breached ones need a reply before anything else gets picked up.'
              : 'Nothing has slipped yet today.'}
          </p>
        </Panel>

        <Panel
          title="Breaching next"
          description="Soonest to cross their target, counting down live"
          action={<StatusBadge tone="ok" pulse={running}>{running ? 'Live' : 'Paused'}</StatusBadge>}
          className="@3xl:col-span-4 @8xl:col-span-5"
          contentClassName="px-2"
          footer={
            <div className="flex w-full items-center justify-between gap-3">
              <span>Showing {shown.length} of {queue.length} open</span>
              <Button variant="ghost" size="sm" className="-my-1 text-muted-foreground" onClick={() => onGo('incidents')}>
                Whole queue <ArrowUpRight />
              </Button>
            </div>
          }
        >
          {/* Measured box, rows absolutely inside it: the count follows the
              card's height and can never feed back into it. */}
          <div ref={listRef} className="relative flex-1" style={{ minHeight: ROW * 5 }}>
            <div className="absolute inset-0 flex flex-col overflow-hidden">
              {shown.map((t) => {
                const remaining = remainingFor(t, now)
                const colour = heat(burnFor(t, now), remaining < 0)
                return (
                  <button
                    key={t.id} onClick={() => onOpen(t.id)}
                    className="group grid shrink-0 grid-cols-[76px_minmax(0,1fr)_56px_96px] items-center gap-3 rounded-lg px-3 text-left transition-colors hover:bg-muted"
                    style={{ height: ROW }}
                  >
                    <span className="font-mono text-xs text-muted-foreground">{t.id}</span>
                    <span className="truncate text-sm text-foreground">{t.subject}</span>
                    <span><Sev p={t.priority} /></span>
                    <span className="flex items-center justify-end gap-2">
                      <span className="clk text-[13px]" style={{ color: colour }}>{clock(remaining)}</span>
                      <ArrowUpRight className="size-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                    </span>
                  </button>
                )
              })}
              {queue.length === 0 ? <p className="px-3 text-sm text-muted-foreground">Nothing open.</p> : null}
            </div>
          </div>
        </Panel>

        <Panel
          title="Open by level"
          description="Straight out of the matrix, so editing it moves these"
          className="@3xl:col-span-3 @8xl:col-span-4"
          footer="Hover a bar for how far its worst ticket has burned."
        >
          <ChartContainer config={{ count: { label: 'Open' } }} className="aspect-auto min-h-[220px] w-full flex-1">
            <BarChart data={levels} margin={{ top: 22, right: 4, left: 4, bottom: 0 }}>
              <CartesianGrid vertical={false} strokeDasharray="3 3" />
              <XAxis dataKey="level" tickLine={false} axisLine={false} tickMargin={10}
                tick={{ fontFamily: 'var(--mo)', fontSize: 12 }} />
              <YAxis hide allowDecimals={false} />
              <ChartTooltip cursor={{ fill: 'var(--g1)', radius: 8 }} content={
                <Tip render={(d) => (<><div className="font-medium">{d.level}</div><Line k="Open" v={d.count} /><Line k="Worst burn" v={`${d.worst}%`} /></>)} />
              } />
              <Bar dataKey="count" radius={[6, 6, 2, 2]} maxBarSize={56}>
                {levels.map((d) => <Cell key={d.level} fill={priorityColour(d.level)} />)}
                <LabelList dataKey="count" position="top" offset={8}
                  className="fill-foreground" fontSize={13} fontWeight={600} />
              </Bar>
            </BarChart>
          </ChartContainer>
        </Panel>

        <Panel
          title="Pressure by team"
          description="How much of its target each team's worst ticket has spent"
          className="@3xl:col-span-3 @8xl:col-span-7"
          footer="The dashed line is the target. Anything right of it is already late."
        >
          <ChartContainer config={{ pct: { label: 'Worst burn' } }} className="aspect-auto w-full flex-1"
            style={{ minHeight: Math.max(200, teams.length * 42 + 20) }}>
            <BarChart data={teams} layout="vertical" margin={{ top: 4, right: 48, left: 0, bottom: 4 }} barCategoryGap="22%">
              <CartesianGrid horizontal={false} strokeDasharray="3 3" />
              <XAxis type="number" domain={[0, teamMax]} hide />
              <YAxis type="category" dataKey="key" width={104} tickLine={false} axisLine={false}
                tick={{ fontFamily: 'var(--mo)', fontSize: 12 }} />
              <ReferenceLine x={100} stroke="var(--ink4)" strokeDasharray="4 4" />
              <ChartTooltip cursor={{ fill: 'var(--g1)' }} content={
                <Tip render={(d) => (<><div className="font-mono font-medium">{d.key}</div><Line k="Open" v={d.n} /><Line k="Worst burn" v={`${d.pct}%`} /></>)} />
              } />
              <Bar dataKey="pct" radius={[3, 6, 6, 3]} maxBarSize={24}>
                {teams.map((t) => <Cell key={t.key} fill={heat(t.worst, false)} />)}
                <LabelList dataKey="pct" position="right" offset={8} formatter={(v) => `${v}%`}
                  className="fill-muted-foreground" fontSize={12} fontFamily="var(--mo)" />
              </Bar>
            </BarChart>
          </ChartContainer>
        </Panel>

        <Panel
          title="Who is carrying what"
          description="Bar length is load; colour is how hot each person's worst ticket runs"
          className="@3xl:col-span-6 @8xl:col-span-5"
          contentClassName="@container"
          footer={`${people.filter((p) => p.name).length} people holding ${open.length - unclaimed.length} tickets · ${unclaimed.length} on nobody`}
        >
          <div className="grid flex-1 content-start gap-x-6 gap-y-1 @lg:grid-cols-2 @3xl:grid-cols-3 @8xl:grid-cols-1">
            {people.map((p) => (
              <div key={p.name ?? 'nobody'} className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-3 rounded-lg py-2">
                {p.name ? <Avatar name={p.name} size={28} /> : (
                  <span className="grid size-7 place-items-center rounded-full border border-dashed text-[10px] text-muted-foreground">—</span>
                )}
                <div className="min-w-0">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className={p.name ? 'truncate text-sm' : 'truncate text-sm text-muted-foreground'}>{p.name ?? 'Unclaimed'}</span>
                    <span className="font-mono text-xs text-muted-foreground">{p.n}</span>
                  </div>
                  {/* length is load; colour is how hot their worst ticket runs */}
                  <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-muted" title={`Worst at ${Math.round(p.worst * 100)}% of its target`}>
                    <div className="h-full rounded-full" style={{ width: `${(p.n / busiest) * 100}%`, background: heat(p.worst, false) }} />
                  </div>
                </div>
                {p.late ? <StatusBadge tone="crit">{p.late} late</StatusBadge> : <span className="w-[52px]" />}
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <div className="flex flex-wrap gap-2 pt-1">
        <Button onClick={() => onGo('incidents')}>Open incident management</Button>
        <Button variant="outline" onClick={() => onGo('reports')}>Look at the month</Button>
        <Button variant="ghost" onClick={() => onGo('intake')}>See what staff see</Button>
      </div>
    </div></div></div>
  )
}
