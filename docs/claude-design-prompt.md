Design **Relay**, an IT service management platform for Meridian Foods — a
1,200-person food distributor with four offices, a warehouse network, a field
sales team, and an ERP that everything depends on.

The premise: incumbent ITSM tools are fifteen years of feature accretion with a
chatbot stapled to the side. Relay keeps the full ITIL 4 surface but reorganises
it around two ideas — a genuine single point of contact for requesters, and a
keyboard-first workbench for agents who live in it eight hours a day. AI is an
ambient layer in the interface, never a chat window in the corner.

## Users

- **Requester** — any employee. Uses it twice a month, has had no training, and
  should never have to know the difference between an incident and a service
  request. That taxonomy is the desk's problem, not theirs.
- **Agent** — service desk technician. Eight hours a day, keyboard over mouse,
  wants density and speed. Optimise for the 200th ticket of the week.
- **Team lead** — queue health, SLA risk, who is drowning, reassignment.
- **Admin** — priority matrix, SLA targets, categories, teams, routing, catalog.

## Screens

**1. Requester intake** — one input, centred, nothing else competing. As they
type, matching KB articles and catalog services surface beneath it, so a good
number of asks resolve without a ticket. Submitting classifies silently in the
background; the requester sees a confirmation with the SLA promise, never an
impact/urgency dropdown.

**2. My requests** — their own tickets, each with status, the SLA promise and
how much of it is left, and the thread. Reopen and add-a-comment are one click.

**3. Service catalog** — browsable services grouped by outcome ("get access",
"new hire", "hardware"), not by owning IT team. Per-service form, visible
turnaround time, visible approval chain before they submit.

**4. Agent queue** — the centre of gravity. A dense, sortable table that holds
~40 rows on screen without feeling cramped: id, subject, requester, priority,
team, assignee, SLA remaining, age, status. Saved views down the left
(My open, Unassigned, SLA at risk, Breached, Waiting on requester). Multi-select
with bulk assign/priority/status. Sort by SLA risk by default, not by date —
the most useful question is always "what breaks next". Row hover reveals quick
actions; `j`/`k` moves, `Enter` opens, `⌘K` commands anything.

**5. Ticket workbench** — the screen that decides whether the product is good.
Three regions: the conversation as the spine, properties in a right rail,
tabbed work areas beneath the thread (Tasks, Approvals, SLA, Related, Activity).
Public replies and internal notes are visually distinct at a glance — different
background, unmistakable which one is about to be sent. Properties are inline-
editable without a modal. The SLA panel shows both clocks — first response and
resolution — as live countdowns that visibly change state at 75% and at breach.
Activity is a real audit trail: actor, timestamp, old value, new value, reason.

**6. Problems** — candidate problems with linked incident counts, root cause,
known error, workaround. The list answers "what keeps coming back".

**7. Change enablement** — a calendar as the primary view, with risk and
collision visible on the calendar itself rather than one level in. Change detail
carries risk assessment, implementation and rollback plan, and the approval chain.

**8. Knowledge** — article list with usage and staleness, and an editor. Show
which articles deflected tickets this month; that is the only KB metric anyone
acts on.

**9. Insights** — SLA attainment, MTTR, backlog age distribution, first-contact
resolution, CSAT. Four or five numbers that lead somewhere, not twenty gauges.

**10. Admin** — the priority matrix as an editable 4×4 grid (impact ×
urgency → P1–P4), SLA targets per priority, categories, teams, routing rules.
Configuration should look like configuration: plain, legible, dangerous-looking
where it is dangerous.

## AI affordances — design the slots, leave them unwired

Relay's judgment layer ships later. Design its affordances now so they are not
bolted on afterwards:

- **Suggested classification** on the workbench: a proposed impact, urgency,
  category, and team, each with a confidence indicator, each accepted or
  overridden in one keystroke. A human override must be visibly recorded, not
  silently swallowed.
- **"Why this priority"** — a popover explaining the derivation: which impact,
  which urgency, which matrix cell. Rules today, probabilities later, same slot.
- **Draft reply with a review state** — a composed response that is clearly not
  yet sent, carrying a screening verdict: clear to send / needs review / blocked,
  with the reason. Design all three states.
- **Deflection** in intake — surfaced KB articles that quietly reduce ticket
  volume, shown as help rather than as an obstacle.
- **Audit verdict** on a closed ticket — a small panel: resolved, consistent,
  policy-clean, needs follow-up, predicted satisfaction.

Confidence is shown as a bar or a dot, never as a raw decimal, and never as a
percentage that implies more precision than exists.

## Design direction

Reference points for feel, not to copy: Linear's density and keyboard primacy,
Superhuman's speed, Stripe's data clarity. Sharp, quiet, and fast.

- One accent colour, used for state and action only — never for decoration.
  Priority and SLA state carry the only other colour in the interface, and they
  must be distinguishable without relying on hue alone.
- A real type scale, one family, 13–14px base for agent surfaces and larger for
  requester surfaces. Tabular numerals in every table.
- 4px spacing grid. Borders and background steps to separate regions, not shadows.
- Light and dark, both first-class, both designed — not a filter over the other.
- Density is a setting agents can change, and the default is dense.
- Empty states say what to do next. Loading states are skeletons of the real
  layout, never spinners.
- Keyboard: `⌘K` command palette, `j`/`k` navigation, single-key actions on a
  focused ticket, and a shortcuts sheet on `?`.

## Motion — Framer Motion

Motion communicates state change and continuity. It never decorates.

- **Shared element** list → detail via `layoutId`: the ticket row's id and
  subject travel into the workbench header rather than the page swapping.
- **Stagger** on queue mount, ~20ms apart, capped at the first dozen rows.
- **AnimatePresence** for the right rail, drawers, and the command palette.
- **Spring** transitions for anything positional (`stiffness ~300, damping ~30`);
  eased 150–200ms for opacity and colour.
- **SLA countdowns** animate their state crossings; do not animate every tick.
- **Numbers** on Insights count up once on mount, never on re-render.
- **Status changes** animate the badge, and the activity row slides in above the
  thread so the cause and the effect are visually connected.
- Everything respects `prefers-reduced-motion`, which disables transforms and
  keeps opacity.
- Nothing exceeds 300ms. An agent doing this 200 times a day must never wait for
  an animation.

## Do not

- No purple-to-blue gradients, no glassmorphism, no frosted panels.
- No sparkle icons, no "✨ AI" badges, no robot avatars, no chat bubble in the
  bottom-right corner.
- No emoji as iconography.
- No marketing landing page, no hero section, no three-feature-card row.
- No modal for anything routine — inline editing and side panels instead.
- No rounded-2xl cards floating on a tinted background with drop shadows. This
  is a tool, not a dashboard template.
- No fake precision: no "94.7% confident", no invented ticket volumes presented
  as real metrics.
- No dead UI. If a control is drawn, it has a state and a behaviour.

## Content

Use realistic Meridian Foods tickets — warehouse barcode scanners dropping off
the wifi, ERP invoice batch failing overnight, a new depot hire needing access
before Monday, a finance laptop that will not wake. Real subjects, real
requester names, plausible timestamps, plausible SLA numbers. No lorem ipsum, no
"Ticket 1 / Ticket 2", no placeholder avatars.

## Deliverable

React with Framer Motion and Tailwind. Ship the queue and the ticket workbench
first and at full fidelity — they carry the product. Then intake, catalog, and
my-requests. Then problems, changes, knowledge, insights, admin.

Wire navigation between screens so it is clickable end to end. Every interactive
element does something, even if the data behind it is fixture data.
