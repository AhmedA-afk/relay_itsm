import { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, Pencil, Plus, Trash2, UserRound } from 'lucide-react'
import { Button } from '@/components/kit/button'
import { Card } from '@/components/kit/card'
import { Input } from '@/components/kit/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/kit/select'
import { Kpi, PageHead, Panel, StatusBadge } from '@/components/blocks'
import { cn } from '@/lib/utils'
import { api } from '../lib/api'
import { C, PRIORITIES, clock, initials, moodColour, moodLabel, priorityColour } from '../lib/format'

/**
 * The roster, and what it is carrying.
 *
 * Every number on this screen is counted from live tickets when the request is
 * served — nothing here is a stored total. That is the same rule priority
 * follows, and it has the same consequence: change the matrix in
 * Administration and these bars move, because the bars are made of derived
 * levels rather than remembered ones.
 *
 * It is also the input to routing. Departments and their domains are what the
 * department question offers as options; people, their skills and their loads
 * are what the person question offers. Add someone here and they are an option
 * in the Showcase on the next run, with no code change.
 */

const TIERS = ['First line', 'Second line', 'Third line', 'Team lead']

const load = (open, capacity) => (capacity ? open / capacity : 0)
const loadTone = (v) => (v >= 1 ? 'crit' : v >= 0.8 ? 'hot' : v >= 0.5 ? 'warn' : 'ok')

/** Open tickets as a share of a normal load, with the levels stacked inside. */
function LoadBar({ person }) {
  const share = load(person.open, person.capacity)
  const width = Math.min(1, share)
  return (
    <div className="flex items-center gap-2.5">
      <div className="relative h-2 min-w-[72px] flex-1 overflow-hidden rounded-full bg-muted">
        <div className="absolute inset-y-0 left-0 flex" style={{ width: `${width * 100}%` }}>
          {PRIORITIES.map((p) => {
            const n = person.by_priority?.[p] ?? 0
            if (!n) return null
            return (
              <span
                key={p}
                style={{ background: priorityColour(p), width: `${(n / Math.max(1, person.open)) * 100}%` }}
                title={`${n} ${p}`}
              />
            )
          })}
        </div>
        {share > 1 ? <span className="absolute inset-y-0 right-0 w-1" style={{ background: C.crit }} /> : null}
      </div>
      <span className="w-[54px] shrink-0 font-mono text-[11.5px] tabular-nums text-muted-foreground">
        {person.open}/{person.capacity}
      </span>
    </div>
  )
}

/** One chip per level a person is actually carrying. */
function Levels({ counts }) {
  const shown = PRIORITIES.filter((p) => counts?.[p])
  if (!shown.length) return <span className="text-[12px] text-muted-foreground">nothing open</span>
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map((p) => (
        <span
          key={p}
          className="rounded-md px-1.5 py-0.5 font-mono text-[11px] tabular-nums"
          style={{ background: `color-mix(in srgb, ${priorityColour(p)} 13%, transparent)`, color: priorityColour(p) }}
        >
          {counts[p]}×{p}
        </span>
      ))}
    </div>
  )
}

function Field({ label, hint, children, className }) {
  return (
    <label className={cn('flex min-w-0 flex-col gap-1.5', className)}>
      <span className="text-[12px] font-medium text-muted-foreground">{label}</span>
      {children}
      {hint ? <span className="text-[11.5px] leading-snug text-muted-foreground">{hint}</span> : null}
    </label>
  )
}

function PersonForm({ person, teams, defaultTeam, onSave, onCancel, busy }) {
  const creating = !person
  const [f, setF] = useState(() => ({
    id: person?.id ?? '',
    name: person?.name ?? '',
    team: person?.team ?? defaultTeam ?? teams[0]?.key ?? '',
    tier: person?.tier ?? 'Second line',
    capacity: String(person?.capacity ?? 8),
    location: person?.location ?? '',
    skills: (person?.skills ?? []).join(', '),
    on_leave: person?.on_leave ?? false,
  }))
  const set = (k) => (v) => setF((prev) => ({ ...prev, [k]: v }))

  return (
    <Card className="gap-4 border-dashed px-5 py-5 shadow-none">
      <div className="grid grid-cols-1 gap-4 @xl:grid-cols-2 @4xl:grid-cols-4">
        {creating ? (
          <Field label="Identifier" hint="Short, letters and digits. It never changes.">
            <Input value={f.id} onChange={(e) => set('id')(e.target.value.trim())} placeholder="kv" />
          </Field>
        ) : null}
        <Field label="Name">
          <Input value={f.name} onChange={(e) => set('name')(e.target.value)} placeholder="K. Virtanen" />
        </Field>
        <Field label="Department">
          <Select value={f.team} onValueChange={set('team')}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {teams.map((t) => <SelectItem key={t.key} value={t.key}>{t.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Tier">
          <Select value={f.tier} onValueChange={set('tier')}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {TIERS.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Normal load" hint="Open tickets this person is expected to carry.">
          <Input
            type="number" min="1" value={f.capacity}
            onChange={(e) => set('capacity')(e.target.value)}
          />
        </Field>
        <Field label="Based at">
          <Input value={f.location} onChange={(e) => set('location')(e.target.value)} placeholder="HQ, Utrecht" />
        </Field>
        <Field
          label="Good at"
          className="@4xl:col-span-2"
          hint="Comma separated. These words are what a routing judgment reads when it is deciding whether this person fits a ticket."
        >
          <Input
            value={f.skills} onChange={(e) => set('skills')(e.target.value)}
            placeholder="vpn, wifi, depot link"
          />
        </Field>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
        <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <input
            type="checkbox" checked={f.on_leave}
            onChange={(e) => set('on_leave')(e.target.checked)}
          />
          On leave — nothing is routed to them while this is set
        </label>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button
            size="sm" disabled={busy || !f.name || (creating && !f.id)}
            onClick={() => onSave({ ...f, capacity: Number(f.capacity) || 1 }, creating)}
          >
            <Check className="size-4" />
            {creating ? 'Add to the desk' : 'Save'}
          </Button>
        </div>
      </div>
    </Card>
  )
}

function TeamForm({ team, onSave, onCancel, busy }) {
  const creating = !team
  const [f, setF] = useState(() => ({
    key: team?.key ?? '',
    name: team?.name ?? '',
    domain: team?.domain ?? '',
    skills: (team?.skills ?? []).join(', '),
  }))
  const set = (k) => (e) => setF((prev) => ({ ...prev, [k]: e.target.value }))

  return (
    <Card className="gap-4 border-dashed px-5 py-5 shadow-none">
      <div className="grid grid-cols-1 gap-4 @xl:grid-cols-2">
        {creating ? (
          <Field label="Key" hint="Letters, digits and underscores. Tickets are stored against it.">
            <Input value={f.key} onChange={(e) => setF((p) => ({ ...p, key: e.target.value.trim() }))} placeholder="data_platform" />
          </Field>
        ) : null}
        <Field label="Name">
          <Input value={f.name} onChange={set('name')} placeholder="Data platform" />
        </Field>
        <Field
          label="Domain"
          className="@xl:col-span-2"
          hint="A sentence, not a label. This is what the department question reads when it decides whether a ticket belongs here."
        >
          <Input value={f.domain} onChange={set('domain')} placeholder="Warehouse, pipelines, the reporting layer" />
        </Field>
        <Field label="Typically handles" className="@xl:col-span-2" hint="Comma separated.">
          <Input value={f.skills} onChange={set('skills')} placeholder="etl, pipeline, warehouse" />
        </Field>
      </div>
      <div className="flex justify-end gap-2 border-t pt-4">
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={busy}>Cancel</Button>
        <Button size="sm" disabled={busy || !f.name} onClick={() => onSave(f, creating)}>
          <Check className="size-4" />
          {creating ? 'Add department' : 'Save'}
        </Button>
      </div>
    </Card>
  )
}

/** Average sentiment across what this person is holding. */
function MoodAverage({ reading, className }) {
  if (!reading?.average) {
    return <span className={cn('text-[12px] text-muted-foreground', className)}>not read</span>
  }
  const level = Math.round(reading.average)
  return (
    <span
      className={cn('inline-flex items-baseline gap-1.5', className)}
      title={`${moodLabel(level)} on average, across ${reading.read} ticket${reading.read === 1 ? '' : 's'} that have been read`}
    >
      <span className="font-mono text-[13px] tabular-nums" style={{ color: moodColour(level) }}>
        {reading.average.toFixed(1)}
      </span>
      <span className="text-[11px] text-muted-foreground">of 5</span>
    </span>
  )
}


function PersonRow({ person, mood, onEdit, onRemove, busy }) {
  const share = load(person.open, person.capacity)
  return (
    <div className={cn(
      'grid grid-cols-1 items-center gap-3 border-b py-3 last:border-b-0 @3xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1.7fr)_170px_minmax(0,1fr)_84px_76px]',
      person.on_leave && 'opacity-60',
    )}>
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted font-mono text-[11px] text-muted-foreground">
          {initials(person.name)}
        </span>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate text-[13.5px] font-medium">{person.name}</span>
            {person.on_leave ? <StatusBadge tone="mute">on leave</StatusBadge> : null}
          </div>
          <div className="truncate text-[11.5px] text-muted-foreground">
            {person.tier}{person.location ? ` · ${person.location}` : ''}
          </div>
        </div>
      </div>

      <div className="min-w-0 text-[12px] leading-snug text-muted-foreground">
        {person.skills.length ? person.skills.join(' · ') : <span className="italic">no skills recorded</span>}
      </div>

      <div className="min-w-0">
        <LoadBar person={person} />
        {person.oldest_seconds > 0 ? (
          <div className="mt-1 font-mono text-[11px] text-muted-foreground">
            oldest {clock(person.oldest_seconds).replace('+', '')}
          </div>
        ) : null}
      </div>

      <div className="flex items-center gap-2">
        <Levels counts={person.by_priority} />
        {person.breached ? <StatusBadge tone="crit">{person.breached} past target</StatusBadge> : null}
      </div>

      <div><MoodAverage reading={mood} /></div>

      <div className="flex justify-end gap-1">
        <Button variant="ghost" size="icon" aria-label={`Edit ${person.name}`} onClick={onEdit} disabled={busy}>
          <Pencil className="size-4" />
        </Button>
        <Button variant="ghost" size="icon" aria-label={`Remove ${person.name}`} onClick={onRemove} disabled={busy}>
          <Trash2 className="size-4" />
        </Button>
      </div>
    </div>
  )
}

export default function People({ toast, onGo }) {
  const [data, setData] = useState(null)
  const [mood, setMood] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(null)   // {kind: 'person'|'team', id, team}

  const load_ = useCallback(async () => {
    try {
      const [roster, sentiment] = await Promise.all([
        api.people(),
        // the roster is useful with or without sentiment; a desk that has read
        // nothing yet should still see its loads
        api.sentimentSummary().catch(() => null),
      ])
      setData(roster)
      setMood(sentiment)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => { load_() }, [load_])

  const teams = data?.teams ?? []
  const everyone = useMemo(() => teams.flatMap((t) => t.people), [teams])
  const moodBy = useMemo(
    () => Object.fromEntries((mood?.by_person ?? []).map((p) => [p.id, p])),
    [mood],
  )

  const act = async (fn, message) => {
    setBusy(true)
    try {
      await fn()
      await load_()
      setEditing(null)
      if (message) toast?.(message)
    } catch (e) {
      toast?.(e.message)
    } finally {
      setBusy(false)
    }
  }

  const savePerson = (f, creating) => act(
    () => (creating
      ? api.createPerson({ ...f, id: f.id })
      : api.updatePerson(editing.id, { ...f, id: undefined })),
    creating ? `${f.name} is on the desk` : `${f.name} saved`,
  )

  const saveTeam = (f, creating) => act(
    () => (creating ? api.createTeam(f) : api.updateTeam(editing.id, { ...f, key: undefined })),
    creating ? `${f.name} added` : `${f.name} saved`,
  )

  const removePerson = (person) => act(async () => {
    const got = await api.deletePerson(person.id)
    toast?.(got.handed_back
      ? `${person.name} removed; ${got.handed_back} ticket${got.handed_back === 1 ? '' : 's'} handed back`
      : `${person.name} removed`)
  })

  if (error) return <div className="pad"><p className="mt" style={{ color: C.crit }}>{error}</p></div>
  if (!data) return <div className="pad"><p className="mt">Loading…</p></div>

  const capacity = everyone.filter((p) => !p.on_leave).reduce((n, p) => n + p.capacity, 0)
  const carried = everyone.reduce((n, p) => n + p.open, 0)
  const available = everyone.filter((p) => !p.on_leave).length
  const deskLoad = load(carried, capacity)

  return (
    <div className="scroll"><div className="pad"><div className="cap flex flex-col gap-4">
      <PageHead
        title="People and departments"
        action={
          <>
            <Button
              variant="outline" size="sm"
              onClick={() => setEditing({ kind: 'team' })} disabled={busy}
            >
              <Plus className="size-4" />Department
            </Button>
            <Button size="sm" onClick={() => setEditing({ kind: 'person' })} disabled={busy || !teams.length}>
              <Plus className="size-4" />Person
            </Button>
          </>
        }
      >
        {data.totals.people} people across {teams.length} departments, carrying {data.totals.open} open
        tickets. Nothing on this screen is stored: every load is counted from live tickets when the
        page is served, so editing the priority matrix moves these bars too. This roster is also
        what routing chooses from.
      </PageHead>

      <div className="mt-2 grid grid-cols-1 gap-4 @xl:grid-cols-2 @5xl:grid-cols-4">
        <Kpi
          label="Open right now" value={data.totals.open}
          foot={`${data.totals.unassigned} with nobody on them`}
          sub={data.untriaged.length ? `${data.untriaged.length} not even placed with a department` : 'every one has a department'}
        />
        <Kpi
          label="Desk load" value={`${Math.round(deskLoad * 100)}%`}
          tone={loadTone(deskLoad)} badge={deskLoad >= 1 ? 'over' : 'within'}
          foot={`${carried} open against ${capacity}`}
          sub="normal load of everyone not on leave"
        />
        <Kpi
          label="Available" value={available}
          foot={`${everyone.length - available} on leave`}
          sub="routing skips anyone away"
        />
        <Kpi
          label="Past target" value={everyone.reduce((n, p) => n + p.breached, 0)}
          tone="crit" badge="assigned work"
          foot="counted on the people holding them"
          sub="unassigned breaches are not here"
        />
      </div>

      {editing?.kind === 'team' ? (
        <TeamForm
          team={editing.id ? teams.find((t) => t.key === editing.id) : null}
          onSave={saveTeam} onCancel={() => setEditing(null)} busy={busy}
        />
      ) : null}
      {editing?.kind === 'person' && !editing.id ? (
        <PersonForm
          teams={teams} defaultTeam={editing.team}
          onSave={savePerson} onCancel={() => setEditing(null)} busy={busy}
        />
      ) : null}

      {teams.map((team) => (
        <Panel
          key={team.key}
          title={
            <span className="flex flex-wrap items-baseline gap-2.5">
              {team.name}
              <span className="font-mono text-[11.5px] font-normal text-muted-foreground">{team.key}</span>
              {team.unclaimed ? (
                <StatusBadge tone="warn">{team.unclaimed} waiting for an owner</StatusBadge>
              ) : null}
              {mood?.by_team?.[team.key]?.average ? (
                <span
                  className="font-mono text-[12px] font-normal"
                  style={{ color: moodColour(Math.round(mood.by_team[team.key].average)) }}
                  title={`${moodLabel(Math.round(mood.by_team[team.key].average))} on average across ${mood.by_team[team.key].read} read`}
                >{mood.by_team[team.key].average.toFixed(1)} of 5</span>
              ) : null}
            </span>
          }
          description={team.domain}
          action={
            <div className="flex gap-1">
              <Button
                variant="ghost" size="sm" disabled={busy}
                onClick={() => setEditing({ kind: 'person', team: team.key })}
              >
                <Plus className="size-4" />Person
              </Button>
              <Button
                variant="ghost" size="icon" aria-label={`Edit ${team.name}`} disabled={busy}
                onClick={() => setEditing({ kind: 'team', id: team.key })}
              >
                <Pencil className="size-4" />
              </Button>
              <Button
                variant="ghost" size="icon" aria-label={`Remove ${team.name}`} disabled={busy}
                onClick={() => act(() => api.deleteTeam(team.key), `${team.name} removed`)}
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          }
          footer={
            <span>
              {team.open} open on this department, {team.headcount} on it
              {team.available < team.headcount ? ` (${team.headcount - team.available} on leave)` : ''}
              {team.skills.length ? ` · handles ${team.skills.join(', ')}` : ''}
            </span>
          }
        >
          {editing?.kind === 'team' && editing.id === team.key ? null : null}
          <div className="flex flex-wrap items-center gap-2 pb-2">
            <Levels counts={team.by_priority} />
            {team.breached ? <StatusBadge tone="crit">{team.breached} past target</StatusBadge> : null}
          </div>

          {team.people.length ? (
            <div className="flex flex-col">
              {team.people.map((person) => (
                editing?.kind === 'person' && editing.id === person.id ? (
                  <div key={person.id} className="py-3">
                    <PersonForm
                      person={person} teams={teams}
                      onSave={savePerson} onCancel={() => setEditing(null)} busy={busy}
                    />
                  </div>
                ) : (
                  <PersonRow
                    key={person.id} person={person} busy={busy} mood={moodBy[person.id]}
                    onEdit={() => setEditing({ kind: 'person', id: person.id })}
                    onRemove={() => removePerson(person)}
                  />
                )
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-3 rounded-lg border border-dashed px-4 py-5 text-[13px] text-muted-foreground">
              <UserRound className="size-4" />
              Nobody on this department yet, so routing has nobody to offer for its work.
            </div>
          )}
        </Panel>
      ))}

      {data.unplaced.length ? (
        <Panel
          title="Not on any department"
          description="Their department was removed; they take no routed work until they are placed."
        >
          {data.unplaced.map((person) => (
            <PersonRow
              key={person.id} person={person} busy={busy} mood={moodBy[person.id]}
              onEdit={() => setEditing({ kind: 'person', id: person.id })}
              onRemove={() => removePerson(person)}
            />
          ))}
        </Panel>
      ) : null}

      {data.untriaged.length ? (
        <Panel
          title="Waiting for a department"
          description="Raised, but nobody has placed them, so no queue is watching them. Routing settles both halves at once: which department owns it, then who on that department gets it."
          action={
            <Button
              size="sm" disabled={busy}
              onClick={() => act(
                () => Promise.all(data.untriaged.map((id) => api.route(id, 'jev', true))),
                `${data.untriaged.length} routed`,
              )}
            >Route all with Jev</Button>
          }
        >
          <div className="flex flex-col">
            {data.untriaged.map((id) => (
              <div key={id} className="flex items-center justify-between gap-3 border-b py-2.5 last:border-b-0">
                <button
                  className="font-mono text-[12.5px] text-foreground hover:underline"
                  onClick={() => onGo?.('incidents')}
                >{id}</button>
                <div className="flex gap-1.5">
                  {['jev', 'ai', 'rules'].map((engine) => (
                    <Button
                      key={engine} variant="outline" size="sm" disabled={busy}
                      onClick={() => act(async () => {
                        const got = await api.route(id, engine, true)
                        toast?.(got.suggestion
                          ? `${id} to ${got.suggestion.person_name}`
                          : got.error ?? `${id} could not be routed`)
                      })}
                    >{engine === 'ai' ? 'AI' : engine === 'jev' ? 'Jev' : 'Rules'}</Button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Panel>
      ) : null}
    </div></div></div>
  )
}
