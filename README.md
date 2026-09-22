# Relay

An IT service desk for Meridian Foods, a fictional 1,200-person food distributor.
FastAPI and SQLite behind a React front end. The judgment layer is not wired yet;
everything it will need is.

```
make setup     # both halves: uv for the API, npm for the app
make dev       # API on :8010, Vite on :5173 with hot reload
make test      # 201 backend tests
make serve     # one process: build the app, serve it from the API on :8010
make reset     # drop the database; it reseeds on the next start
```

Port 8010 rather than 8000, because 8000 is taken by the paper-trading app in the
sibling directory. Override with `make dev PORT=9000`.

## What it does

Two working record types, split the way ITIL splits them:

- **Incident management** — things that broke. Major-incident flag, on-hold
  reasons, and a closure code that the server *requires* before anything can be
  resolved.
- **Service management** — things people asked for, each with an agreed
  turnaround.

Around them: problems with their linked incidents, a change calendar with
collisions on the calendar itself, releases carrying their changes, a knowledge
base ordered by tickets deflected, the staff portal, reports, and
administration. Assets and CMDB is an honest "not built" page rather than
invented laptops.

The clocks run. Every ticket carries a live countdown against its own target,
and the countdown ticks in the browser off an absolute `resolution_due_at` the
API returns, so it stays honest across a reload.

## The three rules the backend holds to

**Priority is derived, never stored.** There is no `priority` column. The server
reads it out of the matrix on every request. Edit a cell in administration and
every open ticket moves at once — that is a real round trip, not a UI trick, and
`test_editing_the_matrix_moves_every_affected_ticket_at_once` proves it.

**Policy is pure.** `relay/policy.py` does every calculation — the matrix, SLA
selection, business-hours arithmetic, legal transitions, routing — with no
database, no network, and no `datetime.now()`. Time arrives as an argument.
That is why `tests/test_policy.py` needs no fixtures and why SLA behaviour is an
ordinary unit test instead of something you verify by waiting.

**Decisions carry their reason.** Every write records an `Event` with actor,
actor kind, field, old value, new value and reason. Intake rows are already
marked `actor_kind="judgment"` with *"read off the wording at intake, nobody has
checked it"*. When a person overrides one, both values stay:

```
A. Okonkwo   person    status   in_progress -> resolved  closed as workaround in place
Relay        system    problem  PRB-118     -> PRB-118   a workaround leaves the cause
                                                          in place, so this wants a
                                                          problem record
```

That log is the data that makes the judgment layer measurable rather than
asserted.

## Layout

```
backend/
  relay/
    policy.py     every decision, pure. read this first
    clock.py      Clock protocol, SystemClock, FrozenClock
    models.py     tables. note what Ticket does NOT store
    service.py    database plus policy, and the event log
    seed.py       Meridian Foods. ages are relative to now
    main.py       HTTP. parse, call service, return
    history.py    cleaning rules for the imported datasets, pure
    import_history.py  loads them; writes data/clean/
    replay.py     puts a real moment of ABC Tech on the live desk
    ai.py         the two measured model calls, with prices
    usecases.py   Showcase use cases: the decision, every lane's prompt
    routing.py    a live ticket's department and owner, composed from the above
    sentiment.py  how the requester sounds, read from the whole thread
    escalation.py which open tickets are about to blow up
    duplicates.py the shortlist, the three relationships, and the linking
    deflection.py the answer before the ticket, and what it would have saved
    backtest.py   that prediction scored against tickets whose outcome is known
    showcase.py   runs the lanes in parallel
    traditional.py  keyword rules and search, what the portal runs today
  tests/
    test_policy.py   33 tests, no database, no clock
    test_api.py      89 tests against a throwaway database
    test_history.py  18 tests for cleaning and replay rules, no database
    test_showcase.py 51 tests for every lane, against a mock transport
frontend/
  src/
    lib/format.js    clock(), burn, the local tick
    lib/api.js       every endpoint in one place
    lib/theme.js     appearance: auto, light, dark
    components/      Icon, Sev, Tag, Meter, Ring, Tabs, Palette, Appearance
    components/kit/  shadcn/ui primitives (Card, Alert, Badge, Button, Chart …)
    components/blocks.jsx  Kpi, Panel, Notice, StatusBadge — compositions on the kit
    modules/         Board, Ticket, Dashboards, Reference, Reports, People, Admin, Portal
    index.css        Tailwind v4 entry; maps shadcn's names onto Relay's tokens
    styles.css       the visual system (Geist), light and dark
docs/
  domain-model.md   the ITSM model, vendor-neutral
  architecture.md   where the judgment layer plugs in
  module-map.md     modules to screens
```

## Where the judgment layer goes

**Routing and deflection are wired.** `POST /api/tickets/{id}/route` puts the department and the
owner to Jev and writes the answer with `actor_kind="judgment"` and its reason.
That is the first judgment in Relay that changes a real ticket.

`POST /api/tickets/{id}/classify` accepts impact, urgency, category and team with
an `actor_kind` and logs the override; the classification slot means calling it
with `actor_kind="judgment"` from intake instead of taking the form's defaults.
Nothing else moves.

The slots still drawn in the interface and unwired:

| Slot | Where it is | What fills it |
|---|---|---|
| Suggested classification with confidence | ticket right rail | Jev: Choice on impact and urgency, as use cases 3 and 4 already do |
| A drafted reply held for review | conversation, `review_state` on `Message` | Claude drafts, Jev screens |

Leaving `GET /api/search` dumb was deliberate, and it paid off: `GET /api/deflect`
is the judgment counterpart and the two are measured against each other above.
Leaving intake's impact and urgency at the form's defaults is deliberate too — it is why a new
payroll failure arrives as a P4, and why the difference the classification slot
makes will be a number rather than a claim.

## Showcase: one decision, several ways

**Compare → Showcase** puts one decision to several engines side by side, on
words anyone can type, and measures every run: latency, input, output and
thinking tokens, cost per call and per 100k tickets. Each use case declares
its lanes; the screen builds itself from that, with a run button per lane and
one for all of them. Lanes are separate requests, so the fastest lands first.

| Use case | Lanes |
|---|---|
| 1. Category: service request or incident | **Jev** (one Choice), **AI** (Gemini 3.8 Flash, JSON) |
| 2. Risk: business exposure, critical to low | **Traditional** (ordered keyword rules), **AI**, **Jev** |
| 3. Impact: organisation to individual | **Traditional** (the caller's form field), **AI**, **Jev** |
| 4. Priority: P1 to P4 | **Traditional** (the form and the matrix), **AI**, **Jev** |
| 5. Department: which team owns it | **Traditional** (assignment-group keyword rules), **AI**, **Jev** |
| 6. Individual: whom to assign | **Traditional** (rules for the group, fewest open for the person), **AI**, **Jev** |
| 7. Sentiment: 1 to 5 | **Traditional** (two word lists and a subtraction), **AI**, **Jev** (a Score) |
| 8. Escalation risk: will this blow up? | **Traditional** (the SLA escalation rules), **AI**, **Jev** (a Noul) |
| 9. Duplicate: have we got this already? | **Traditional** (the “similar incidents” word overlap), **AI**, **Jev** (a fan-out of Choices) |
| 10. Deflection: is the answer already written down? | **Traditional** (the portal's keyword search), **AI**, **Jev** (a fan-out of Nouls) |

Traditional lanes use no model: they cost nothing and answer in microseconds,
and each is shown with its honest limit. The form reads no words, so untouched
fields stay at their defaults; keyword rules read words, not meaning, and the
first match wins. On an ordered scale the comparison reports how many levels
apart two answers are, not just whether they differ.

Priority is never picked directly, in any lane: every lane settles impact and
urgency and the live matrix from Administration gives the level, as it does
for every ticket in Relay. Traditional takes impact and urgency from the form —
defaults unless the caller changes them — and never reads the words. AI is
given the definitions and the matrix and asked for all three; the server checks
its priority against its own impact and urgency. Jev answers impact and urgency
as two Choice questions in one request; code reads the matrix, and pushes the
two distributions through it to give a probability per level. When that
probability leans elsewhere or sits under 60%, the lane calls it a close call.

The last two build their options out of the live roster rather than a fixed
vocabulary: the departments in **Oversight → People and departments** are the
options for use case 5, and the people on them — with their skills and what
they are carrying — are the options for use case 6. Add a person there and they
are an option here on the next run, in every lane, with no code change.

Use case 6 is the one the architecture argues about with itself. The domain
model says "who on that team" is mechanical and belongs in code, and Relay's own
`auto-route` still answers it by counting. This lane asks instead, and reports
what the counter would have said, so the difference is measured rather than
asserted: on *"Warehouse scanners dropping off wifi in Bay 3"* the counter picks
whoever is idle, and both judgment lanes pick the person who has fixed depot wifi
before. Availability stays in code either way — anyone on leave is removed from
the options before the question is asked, and `policy.accept_assignment` checks
whatever comes back against the roster before it can be written.

Use case 7 is the first that is a **Score** rather than a Choice, which is the
point of it. Satisfaction is a position on a spectrum, so the answer can land
*between* two levels: on *"Great. Another day without the scanner working.
Brilliant service as always."* Jev returns **1.42**, nearest angry, and 0.65
confidence — it caught the sarcasm and is honestly unsure how far it goes. The
word lists read the same sentence as **4**, because "great" and "brilliant" are
in the positive list. Three levels apart, on the one sentence where it matters.

Where the score lands nearest a level that is not its likeliest one — a
distribution split between 2 and 4 averages to 3 while barely backing 3 — the
lane says so rather than reporting a confident middle.

Use case 8 is the first that **predicts** rather than reads, and the third
primitive: a **Noul**, whose whole answer is the probability that a statement is
true. It returns no confidence figure, because the probability already is the
answer — 0.5 means evens, not "unsure". Thresholding it is code's job, so the
lines live in `policy.ESCALATION_WATCH` and `ESCALATION_LIKELY` where a service
desk manager can move them; moving one re-runs no inference.

It is also the only use case given the clock. Sentiment is deliberately kept
away from target burn so it cannot become a slower way of reading the SLA field.
Escalation is the opposite: a human predicting a blow-up weighs the burn, the
reopens and the bounces alongside the words, so withholding them would only make
it predict worse.

Use case 9 is the first where **code does real work before the model is asked
anything**, and the first to use the **fan-out**: every shortlisted candidate is
its own Choice question, but they all go in one request over one state and are
evaluated in parallel. Six candidates cost six questions and one round trip —
about 380 ms and $0.00009 for the lot.

Every lane gets the same definitions word for word (`relay/usecases.py`), so a
disagreement is the engine, not the brief. Add a use case by adding an entry to
`USE_CASES`.

Keys stay on the server, read from `.env` in `backend/`, this folder, or the
workspace root: `TYPESAFE_API_KEY`, and `GOOGLE_API_KEY` (or `GOOGLE_AI_KEY`).
Prices live in `relay/ai.py` with their sources and the date they were checked:
Jev $0.042/M input, output free; Gemini 3.8 Flash $0.75/M input, $3.75/M output
with thinking billed as output (rates double on 1 January 2027). Both providers
use a kept-alive connection, so the first run after a restart pays a TLS
handshake the rest do not.

`GET /api/showcase/cases`; `POST /api/showcase/run` with `case`, `text`, and
optionally `lanes` (default: all) and `form` (`impact`, `urgency`).

## Routing a real ticket

The Showcase compares engines on typed words. `POST /api/tickets/{id}/route`
asks the same two questions of a live ticket and can write the answer:

```
POST /api/tickets/INC-4418/route  {"engine": "jev", "apply": true}
```

`engine` is `jev`, `ai` or `rules`; `apply` defaults to false, so the default is
a suggestion with its reason rather than a write. The department answer narrows
the person question to that department — code owns the funnel, so neither half
can contradict the other — and a ticket that already names a department is only
staffed, not re-argued. Applying writes both halves through `service.assign`
with the engine as the actor and `actor_kind="judgment"`, so the ticket's own
history shows what decided it. `relay/routing.py` composes it; it decides
nothing itself.

The ticket rail carries this as **Where it should go**, with an engine picker.
Tickets nobody has placed are listed on the roster screen with a route button
each, and `POST /api/tickets` raises one the way the portal does: words and a
requester, no department, no owner, impact and urgency left at the form's
defaults — which is why a payroll failure for all of Finance arrives as a P4
until something reads it.

## Sentiment on live tickets

The Showcase scores typed words. `POST /api/tickets/{id}/sentiment` scores the
**whole conversation** — subject, the requester's own words, what the desk said
back, and how many times it has been reopened. Nothing about the clock goes into
the state: a breached P1 is not the same thing as an unhappy requester, and
letting the target leak in would make the score a slower, dearer way of reading
the SLA field.

```
POST /api/tickets/INC-4398/sentiment  {"engine": "jev"}
→ 1.84, nearest 2 · unhappy, 16% of the weight on 1 · angry
```

**This is the one derived value Relay stores.** Priority is re-read from the
matrix on every request because a table lookup costs nothing; sentiment costs a
model call, so deriving it per request would mean one call per ticket per page
load. What makes the exception safe is that the row carries what it was computed
from: `last_message_id` and `message_count` pin it to a point in the
conversation, so every surface can tell you the number is out of date instead of
quietly ageing. Post a reply and the reading marks itself stale at once.

It surfaces in four places: a **Mood** column and an **Unhappiest** view on both
boards, sorted by score rather than by clock; a reading in the ticket rail with
the spread across all five levels and what it cost; a desk-wide distribution and
the unhappiest open tickets in **Reports**; and an average per person and per
department on the roster. `GET /api/sentiment` is the summary, counted over open
tickets only — a closed ticket's satisfaction is history, and mixing the two
would let a good week of closures hide a bad queue.

The two unhappiest tickets on the seeded desk are a **P3 and a P4**. The matrix
says they can wait; the people on them have been chasing for a week. That
disagreement is the whole reason to read it.

## Deflection: the ticket that never gets raised

The only judgment that runs before a record exists, and the only one whose
success is measured in work that never arrives. `GET /api/deflect?q=…` is the
counterpart to `GET /api/search`, which stays keyword-only on purpose so the
difference between them is measurable.

The question is deliberately stronger than "is this article relevant": *would
reading this leave them with nothing to ask?* An article about the right
equipment and the wrong fault is relevant and useless — they read it, it does
not help, and they raise the ticket anyway having wasted two minutes.

**Three bands, from one probability, with the lines in `policy.py`:**

| Band | Over | What the portal does |
|---|---|---|
| `answer` | 70% | Leads with it; raising a ticket becomes the second option |
| `suggest` | 35% | Offers it above the form, quietly |
| `quiet` | — | Says nothing and gets out of the way |

The lines are asymmetric on purpose: showing a wrong article costs a moment's
reading, hiding a right one costs a ticket. **Nobody is ever prevented from
raising one** — the band decides what the page leads with, never what it allows.

**Stale articles are held back by code, and reported anyway.** Whether an article
is fit to show is a fact about the article, not a judgment about the question, so
`deflection.shortlist` drops anything stale or in draft. But it still asks about
them, because "nobody wrote this down" and "somebody wrote it down and let it
rot" are different problems with different fixes:

```
GET /api/deflect?q=cant get my personal phone onto the depot wifi
→ quiet. Nothing offerable answers this. KB-0025, Connecting to depot wifi on a
  personal phone, would have answered it (87%) but is marked stale.
```

Keyword search offers KB-0031, the *barcode scanner* article, for that same
question — right equipment, wrong fault.

### How much work would it actually take away?

`GET /api/deflect/backtest` runs it over open tickets, which are questions
somebody did bring to the desk. It reads what the requester wrote and skips
tickets that carry no description at all — the replayed rows — because nothing
could ever have deflected those, and leaving them in the denominator would
understate the rate for a reason unrelated to the knowledge base.

Over the 12 open tickets that have words in them:

| | Fires on | Crosses the answer line | Cost |
|---|---|---|---|
| Keyword search | 9 of 12 | never — it has no probability to threshold | $0 |
| Jev | 5 of 12 | **1** (INC-4412 → KB-0018, 71%) | $0.0006 |

Keyword search offers something for three quarters of everything, including
KB-0031 for a badge-access request — which is how people learn to scroll past
self-service. Jev stays silent on seven, puts the three wifi tickets at 46–55%
(*"might help"* — KB-0031 says the fix works four times in five), and crosses the
line once.

An 8% ceiling on a nine-article knowledge base is a small number honestly
arrived at, and it is a **ceiling, not a rate**: somebody who raised a ticket may
have searched first and scrolled past the article already.

## Duplicates: three relationships, not one

Every ITSM tool has a "similar incidents" panel and one verdict: duplicate.
Relay refuses that flattening, because the three things it hides have three
different consequences:

| Relationship | What it means | What Relay does |
|---|---|---|
| `same_request` | The same ask raised twice | Closes it against the other, which carries on |
| `same_fault` | A different person hitting the same fault | Links it to the parent and **keeps it open** |
| `known_problem` | An instance of a recorded problem | Attaches it to the PRB, workaround and all |

The middle one is why this matters. Closing a second reporter as a duplicate
loses the person you needed to tell when it is fixed, so `same_fault` links and
leaves the ticket open on purpose, and the audit log says why in as many words.

**Code shortlists, judgment decides.** Comparing a ticket against a hundred open
ones is a hundred comparisons; `duplicates.shortlist` cuts it to six. It ranks by
*rare* shared words — each worth `1/df`, so one "certificate" outranks five
"printings" — over everything the requester actually wrote, not just the subject
line. Two of the six slots are held back for the newest open tickets on the same
department **whatever they say**, because the case this feature exists for is two
people describing one fault with no words in common, and word similarity cannot
find those by construction.

**Both stages read both the title and the description**, and it matters that they
read the same thing. Relay keeps a ticket's description as its first `Message`
rather than in `Ticket.body`, so:

| Stage | What it reads |
|---|---|
| `searchable` — what the shortlist matches on | subject + body + every public message, both sides |
| `described` — what the question is given | subject + everything *the requester* said, capped at 600 characters, both sides |

Desk replies are left out of the description on purpose: they are diagnosis and
acknowledgement, and two tickets are not the same thing because the desk answered
them in similar words. Everything the requester said is included rather than just
their opening line, because the detail that settles a match — *"only the back
aisles"*, *"since the firmware update"* — is usually in the second message. An
earlier version handed the judgment the first sentence only, which meant code was
selecting candidates on evidence the judgment was not allowed to see; fixing that
moved *"None of the invoices went out again"* against *"ERP invoice batch failed
overnight"* from **56% to 86%**, for about 6% more input tokens.

On the seeded desk, three people report the depot wifi in three different ways:

| Asked about | Word overlap | Jev |
|---|---|---|
| INC-4422 *"Handhelds losing connection mid-pick"* | INC-4417, called **same request** | PRB-114 **known problem** 99%, INC-4421 **same fault** 96%, INC-4417 **same fault** 88% |
| INC-4421 *"Pickers walk to the front to get a signal"* | three matches, all called **same request**, two of them unrelated tickets | INC-4422 **same fault** 93%, INC-4417 **same fault** 91% |
| INC-4423 *"None of the invoices went out again"* | INC-4398 (a label printer) called **same request** | PRB-118 **known problem** 100%, INC-4416 **same fault** 56% |
| INC-4424 *"Label printer, raising this again"* | INC-4398, **same request** | INC-4398 **same request** 98% |

The word lane gets the last one right and the rest wrong in the way that costs
most: it calls second reporters `same_request`, which is the verdict that closes
their ticket. It also cannot see PRB-118 as a *problem* rather than a duplicate —
and PRB-118 is only in the running at all because the shortlist reads Bea's
sentence, *"something to do with a certificate"*, which appears in no subject
line anywhere.

`GET /api/tickets/{id}/duplicates?engine=jev|ai|similar` finds; `POST
/api/tickets/{id}/link` acts, logged as `actor_kind="judgment"`. Nothing closes
without somebody pressing it. `GET /api/duplicates` counts how much of the queue
is one thing seen several times.

## Escalation risk on live tickets

`POST /api/tickets/{id}/escalation` predicts one open ticket, reading the
conversation *and* its state — burn, reopens, times reassigned, and how the
requester sounds. It stores the answer like sentiment, for the same reason, but
it goes stale differently and the difference is the interesting part: a reading
of how somebody *sounds* is only wrong once they say something new, while a
prediction about the future is undermined by time passing on its own. The row
keeps the burn it saw as well as the message count, so every surface can say
which of the two moved.

On the seeded desk, with both engines run over the same tickets:

| Ticket | Target used | SLA rules | Jev |
|---|---|---|---|
| INC-4398 — third chase, *"not another reference number"* | 34% | **0%**, nothing fired | **77%**, likely |
| INC-4386 — three weeks, waiting on a vendor | 4% | **0%**, nothing fired | **61%**, watch |
| INC-4416 — the invoice batch, already breached | 668% | **100%** | 85%, likely |
| REQ-2201 — thanked the desk for going further | 19% | 0% | **4%**, quiet |

The rules are right about INC-4416 — and right about a ticket that has already
blown up. The two they cannot see are the two worth seeing: both still have most
of their clock left, and one is *on hold*, so its target is paused and no rule
will ever fire on it. **Seen early** on the Reports panel counts exactly those —
flagged while still inside half their target — because that number, not the
accuracy, is what a prediction is bought for.

It surfaces as a **Risk** column and an **At risk** view on both boards, a panel
in the ticket rail, and a summary in Reports. `GET /api/escalation`.

### Does it work? A backtest, and an uncomfortable answer

`relay/backtest.py` scores the prediction against ABC Tech tickets whose outcome
is recorded, because `architecture.md` says calibration is an artifact rather
than a claim. Ground truth is **reassigned three times or more, or reopened** —
one hand-off is the service desk passing a network fault to the network team,
which is routing working correctly, while three is a ticket nobody can place.
That lands at a 17% base rate.

```
python -m relay.backtest --n 60 --all
```

Over 60 tickets, against a 15% base rate in the sample:

| Engine | Flagged | Caught | Brier | Cost | Time |
|---|---|---|---|---|---|
| SLA rules | 0 | 0 | 0.150 | $0 | 0.0s |
| Jev | 1 | 0 | 0.139 | $0.0013 | 24s |
| Gemini 3.8 Flash | 8 | 0 | 0.173 | $0.0667 | 173s |

**None of them works here, and Jev is only the least bad.** Every Brier score is
worse than 0.1275, which is what you get by always answering the base rate — so
none of the three adds information. Jev is closest to that floor and 51× cheaper
than the LLM call; Gemini flagged eight tickets and was wrong about all eight.

The reason is the caveat the module carries at the top and prints under every
run: **neither imported dataset has ticket text.** A subject like *"Problem with
web-based application WBA000124"* is composed from structured fields, so a
judgment that exists to read language is being asked to work with none. The
backtest measures the floor — what is left when the thing being tested is
removed — and it says the floor is nothing.

So the honest position is two statements that do not cancel out. On tickets with
words the separation is real and visible in the table above. On tickets without
them nobody can do this, and the only dataset with recorded outcomes has no
words. Calibrating this properly needs a desk's own closed tickets, text
included; until then the live behaviour is a demonstration, not a measurement,
and the number in `data/clean/escalation-backtest.json` is the only measured one
there is.

## Oversight: people and departments

**Oversight → People and departments** is the roster the routing questions draw
their options from, and it is editable: add, edit and remove departments and
people, set what each person is good at, their normal load, where they are based
and whether they are on leave.

It doubles as the load view. Per person and per department: open tickets against
a normal load, the split by priority, how many are past target, how old the
oldest is, and what a department owns that nobody has taken. None of it is
stored — every number is counted from live tickets when the request is served,
the same rule priority follows, which is why editing the matrix in
Administration moves these bars too.

Removing someone hands their open tickets back rather than reassigning them
silently, and each hand-back is an event. A department still carrying people or
open tickets refuses to be deleted and says what is in the way.

`GET /api/people`; `POST|PATCH|DELETE /api/teams[/{key}]` and
`/api/people[/{id}]`.

## History from real datasets

`make import` loads two public Kaggle datasets into a `historicticket` table and
Relay shows them under **Oversight → Ticket history**. They never enter the live
queue: they are closed, they would bury fourteen live tickets under 146,606, and
their clocks stopped years ago.

```
python -c "import kagglehub as k; k.dataset_download('ahanwadi/itsm-data'); k.dataset_download('swapniljadhav96/itsm-dataset')"
make import        # reads the kagglehub cache; --abc / --gcc take explicit paths
```

| Source | Rows | What the cleaning had to do |
|---|---|---|
| ABC Tech, 2012–14 | 46,606 | day-first dates in two formats (read month-first, 8.4% of tickets close before they open); five-level scale onto Relay's four; `NS`, `#MULTIVALUE`, `#N/B` to empty; two Dutch closure codes; the mangled `Handle_Time_hrs` recomputed from timestamps |
| Gulf service desk, 2024 | 100,000 | status column contradicts the timestamps on 80% of rows, so status comes from the stamps; SLA outcome recomputed rather than copied |

Every repair is counted by rule in `data/clean/report.json` and on the History
screen; no row was refused. The cleaning rules are pure functions in
`relay/history.py`, tested in `tests/test_history.py`.

### Real tickets on the live desk

`make replay` puts about a hundred ABC Tech tickets into Incident and Service
management alongside Meridian's fourteen. It replays one real moment rather
than inventing ages: every ticket open at 7 March 2014, at today's time of day,
with every timestamp moved forward a whole number of weeks (654) so weekdays
and working hours line up. A fixed 1-in-8 sample, by a hash of the id, sizes
the backlog to a six-person desk without cherry-picking; the day's resolutions
come along so the Resolved view has real outcomes.

Kept from the source: id (`IM…`), kind, item, impact and urgency, age,
reassignments, closure cause. Supplied by Relay and logged as events with the
reason: team (from the item class; requests go to first line), person
(least-loaded), and a subject built from the fields ("Problem with web-based
application WBA000124"). ABC Tech records no caller, so none is shown.
`--every 4` doubles the sample; `--at 2013-11-22` picks another day; re-running
replaces only the `IM…` tickets.

Two cautions. The Gulf set is spread almost perfectly evenly across every
category and meets every target, so treat it as synthetic. And neither set has
ticket text, so `subject` is composed from structured fields.

This table stores priority, which `Ticket` never does: a closed ticket's
priority is what someone decided at the time, and re-deriving it would rewrite
history. As a check, ABC Tech's recorded priority matches Relay's matrix on
99.5% of tickets.

## Two things worth knowing

**SQLite returns naive datetimes.** `clock.ensure_utc` coerces at every
boundary. Without it a naive ISO string reaches the browser and gets read as
local time, silently shifting every clock in the interface.

**Two styling systems, one set of tokens.** Newer screens (Dashboards, Reports,
the change calendar, every banner) are built from shadcn/ui on Tailwind v4, with
charts through Recharts. Older screens still use the classes in `styles.css`.
Both read the same custom properties, and `index.css` loads `styles.css` into a
`legacy` cascade layer between Tailwind's preflight and its utilities — so the
old resets beat preflight but never beat a component's own utilities. Add new
shadcn components with `npx shadcn@latest add <name>`; they land in
`components/kit/` (not `components/ui/`, which would collide with `ui.jsx`).

**Appearance defaults to the system and only then to a choice.** Every colour
is a semantic token defined three times in `styles.css`: on bare `:root` for
light, under `prefers-color-scheme: dark` guarded by `:not([data-theme=light])`,
and again under `[data-theme="dark"]`; `lib/theme.js` also mirrors the resolved
appearance as a `.dark` class for shadcn's `dark:` variants. That third block is what lets the in-app
control win in *both* directions — without it, choosing light inside a dark
system does nothing. `index.html` stamps the stored choice before first paint,
so a dark reload never flashes white.

**`AnimatePresence mode="wait"` deadlocks under React 18 StrictMode.** The
incoming view waits for an exit handshake that StrictMode's double-invoked
effects never complete, so the route locks and *no* click appears to work while
state updates fine underneath. Both route and tab transitions use a plain
cross-fade instead.
