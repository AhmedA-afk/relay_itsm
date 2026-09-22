# Relay — how it is built

## The spine

Four stages. Each one is a pure function of its inputs, and the only stages that
talk to a model are the ones marked.

```
  ticket text + context
          │
          ▼
  ┌───────────────────┐   ONE Jev request, ~12 questions, fanned out
  │  JUDGE            │   speculative questions included; code drops
  │  (jev)            │   the answers that turn out not to apply
  └─────────┬─────────┘
            │  typed answers + per-option probabilities + confidence
            ▼
  ┌───────────────────┐   pure. no network, no model, no clock.
  │  POLICY           │   priority matrix · SLA pick · team → assignee
  │  (pure python)    │   every threshold lives here, in one file
  └─────────┬─────────┘
            │  decisions + the reason for each
            ▼
  ┌───────────────────┐   persist, start SLA clocks, attach KB article,
  │  ACT              │   auto-resolve, or escalate
  └─────────┬─────────┘
            │
      ┌─────┴──────┐
      ▼            ▼
  ┌────────┐   ┌────────────────┐
  │ DRAFT  │   │ AUDIT on close │   Jev scores the finished session:
  │(claude)│   │ (jev)          │   resolved? consistent? policy-clean?
  └───┬────┘   └────────────────┘   needs follow-up? predicted CSAT?
      │
      ▼
  ┌────────────────┐   Jev screens Claude's draft before it can be sent
  │ GUARD (jev)    │──▶ send · hold for human · block
  └────────────────┘
```

## Five rules the code holds to

**1. Two files are the review surface.** Every Jev question lives in
`relay/questions.py`; every threshold and weight lives in `relay/policy.py`.
A service-desk manager should be able to read both without reading anything else,
because those are the two places where a human's judgment is actually encoded.

**2. Policy is pure.** It takes judgments plus config and returns decisions. No
I/O, no model call, no `datetime.now()` — the clock is injected. That makes the
entire decision layer unit-testable with zero API keys and zero flakiness, and it
means changing the priority matrix or a threshold re-runs no inference at all.

**3. One request per stage.** Questions that only matter on one branch get asked
anyway, up front, alongside the ones that decide the branch. Code discards what
does not apply. Serialising them into a chain of dependent calls is the mistake
this pattern exists to avoid.

**4. Every model call goes through a replay cache.** Keyed on the exact inputs,
with the fixtures committed. Consequence: `git clone && pytest` passes with no
keys at all, the web demo runs with no keys, and the published numbers are
reproducible. Delete the cache file to run live.

**5. Calibration is an artifact, not a claim.** A labeled set of synthetic
tickets, a threshold sweep over the routing and guardrail decisions, and a
measured cost-and-latency comparison against an LLM-only baseline doing the same
job. Until that exists, "calibrated probabilities you can threshold" is marketing.

*Partly delivered, and the result is worth reading.* `relay/backtest.py` scores
the escalation prediction against ABC Tech tickets whose outcome is recorded,
with the cost-and-latency comparison against Gemini alongside. It found that
none of the three engines beats the base rate on that data — because the data
has no ticket text, which is the one thing a judgment is there to read. The
artifact exists and it is not flattering, which is the point of building it
before making the claim rather than after. The remaining gap is a labelled set
that has words in it; a desk's own closed tickets would close it.

## Layout

```
ITSM_UseCase/
├── relay/
│   ├── domain.py         Ticket, Impact, Urgency, Priority, Status, Team  (pydantic)
│   ├── questions.py      ← the Jev question set. review surface #1
│   ├── policy.py         ← matrix, SLA table, thresholds. review surface #2
│   ├── judge.py          the Jev client wrapper: one request, typed answers back
│   ├── draft.py          the Claude client wrapper: reply drafting, summarising
│   ├── guard.py          screens a draft before it can be sent
│   ├── audit.py          scores a closed ticket
│   ├── pipeline.py       composes judge → policy → act
│   ├── store.py          SQLite persistence (sqlmodel)
│   └── cache.py          the replay cache both model clients go through
├── fixtures/
│   ├── tickets.jsonl     ~60 synthetic tickets, hand-labeled
│   ├── kb/               ~15 KB articles the guardrail checks drafts against
│   ├── catalog.yaml       service catalog + category tree
│   └── replay.json       recorded model calls, committed
├── evals/
│   ├── routing.py        accuracy per team, confusion matrix
│   ├── thresholds.py     sweep: auto-act rate vs error rate
│   └── baseline.py       same job, one LLM, no Jev — cost and latency
├── api/                  FastAPI over the same core
├── web/                  the workbench UI
├── tests/
└── docs/
```

## Stack

Python 3.12 · FastAPI · SQLite via SQLModel · pytest — and React with Vite and
Motion (`motion/react`, the renamed Framer Motion) for the front end.

**This deviates from the plan above, deliberately.** The stack originally read
FastAPI + Jinja + HTMX for a single process with no build step. The interface
that came out of the design work needs live countdowns, a command palette and
shared-element transitions, none of which HTMX carries well, so the front end is
a real React app. `make serve` still collapses it to one process: Vite builds to
`frontend/dist` and the API mounts it, so production is one port. `typesafe-sdk`
and `anthropic` arrive when the judgment layer does; neither is a dependency
yet.

## What is deliberately not built

No CMDB, no asset or licence management, no purchasing, no contracts, no
multi-tenancy, no email ingestion. One module — the service desk — carried all the
way through, instead of six sketched.
