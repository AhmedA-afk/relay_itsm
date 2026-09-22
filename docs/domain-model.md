# Relay — domain model

Relay is a self-contained IT service desk, built to demonstrate typed judgments
from a System One model (Jev) composed with generative steps from Claude, inside a
workflow that ordinary code controls.

The model below is standard ITIL service-desk practice, chosen and named by us.
Every ticket, team, category, KB article, and SLA target in this project is
synthetic and authored here.

## The fictional deployment

Relay runs the internal IT desk for **Meridian Foods**, a ~1,200-person food
distribution company: four offices, a warehouse network, a field sales team, and
an ERP that everything depends on. That concreteness is deliberate — it gives
categories, teams, and SLA tiers real edges, and it makes the synthetic tickets
sound like tickets instead of test strings.

**Teams** (the routing targets):

| Team | Domain |
|---|---|
| `service_desk` | First line: accounts, passwords, how-do-I, triage |
| `endpoint` | Laptops, phones, printers, peripherals, OS and software installs |
| `network` | Connectivity, VPN, wifi, switches, the warehouse scanners |
| `erp_apps` | The ERP, warehouse management, reporting, integrations |
| `identity_security` | Access grants, offboarding, phishing, anything security-flavoured |
| `facilities` | Badges, desks, rooms, physical building requests |

## The record

Work enters as a **ticket**, of one of two kinds:

| Kind | Prefix | What it is |
|---|---|---|
| Incident | `INC-` | Something is broken or degraded, logged free-form |
| Request | `REQ-` | A request for a standard service from the catalog |

A ticket is defined by **requester + subject + body**, classified by **impact** and
**urgency**, routed to a **team** and then an **assignee**, and moved through a
status lifecycle under SLA timers.

## Classification

Two independent axes, both judged from the ticket text:

- **Impact** — how far the blast radius reaches:
  `individual` · `team` · `department` · `organization`
- **Urgency** — how soon it has to be dealt with:
  `low` · `medium` · `high` · `critical`

**Duplicates are three facts, not one.** "The same request raised twice", "a
second person hitting the same fault" and "an instance of a known problem" are
routinely collapsed into one *duplicate* flag, and the collapse costs: closing a
second reporter loses the person who has to be told when it is fixed. Relay keeps
them apart — `duplicate_of` with the ticket left open, `duplicate_of` with it
closed, and `problem_id` — and `relay/duplicates.py` decides which.

**Priority is derived, never asked for.** A 4×4 matrix maps
(impact × urgency) → `P1`…`P4`. The matrix is business policy: it lives in config
where a service-desk manager can read it and change it, and changing it does not
re-run any inference.

```
                urgency:  low    medium   high    critical
impact organization        P3      P2      P1       P1
       department          P3      P2      P2       P1
       team                P4      P3      P2       P2
       individual          P4      P4      P3       P2
```

## Lifecycle

```
new ──▶ assigned ──▶ in_progress ──▶ resolved ──▶ closed
                          │
                          ▼
                 waiting_on_requester ──▶ in_progress
```

Plus two terminal side-exits from any pre-resolved state: `cancelled` and `spam`.
The legal transitions are a table, not a chain of `if`s, so the set of allowed
moves is data the tests can enumerate.

## SLA

Targets are keyed on priority, with two clocks per ticket — **first response** and
**resolution**:

| Priority | First response | Resolution | Clock |
|---|---|---|---|
| P1 | 15 min | 4 h | 24×7 |
| P2 | 1 h | 8 h | 24×7 |
| P3 | 4 h | 3 business days | business hours |
| P4 | 1 business day | 5 business days | business hours |

A `waiting_on_requester` status pauses the resolution clock and never the response
clock. Breach triggers escalation, of two distinct kinds that are not
interchangeable:

- **functional** — hand to deeper expertise, because the current owner cannot fix it
- **hierarchical** — notify management, because a breach is imminent or the impact
  is severe

## Routing

The industry-standard strategies — manual, round robin, and least-loaded — all
answer "who is next" or "who is free". None of them reads the ticket.

Relay routes in two steps, and the split is the whole point:

1. **Which team's domain is this?** — semantic, judged from the ticket text.
2. **Who on that team gets it?** — mechanical, least-loaded with exclusions,
   decided in code.

**Step two is now argued both ways, on purpose.** `auto-route` still answers it
by counting, exactly as above. Showcase use case 6 asks it instead, over options
carrying each person's skills and current load, and reports what the counter
would have said so the two can be compared rather than debated. The claim under
step two — that nothing semantic is left once the team is known — is false the
moment two people on a team are good at different things; what stays true is
that *availability* is arithmetic. Leave, team membership and capacity are
checked in code before and after the question, so a judgment can influence who
gets the work but can never hand it to someone who is away or on another team.

## Where judgment is needed, and where it is not

| Needs semantic understanding | Stays in ordinary code |
|---|---|
| Incident or catalog request? | Which ID prefix to mint |
| How wide is the impact? How urgent? | impact × urgency → priority |
| Which category? Which team's domain? | least-loaded pick within that team |
| Does it name a deadline or a real event? | whether that clears the escalation bar |
| Spam? A duplicate of an open ticket? | what each of those triggers |
| Could this be self-served from the KB? | which article to attach, and the wording |
| Did the drafted reply hold to policy and fact? | send, hold, or block |
| Was the closed ticket actually resolved? | which tickets enter the QA queue |
