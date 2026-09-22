"""Routing a live ticket: which department, then who on it.

The Showcase asks each question on its own, of typed words, to compare engines.
This module is the same two questions asked of a real ticket, in the order the
domain model puts them, with the answer written to the desk.

Two things are worth noticing about the shape:

* **The first answer narrows the second.** The person question is only ever
  asked about the department the ticket is going to, because code funnels it.
  A model is never asked to hold both decisions at once, so neither answer can
  quietly contradict the other.
* **Code has the last word.** Whatever comes back is checked against the roster
  by ``policy.accept_assignment`` before ``service.assign`` writes anything,
  and every write carries the engine's own reason into the audit log.

Nothing here decides anything itself; it composes ``usecases`` lanes and
``service`` writes.
"""

from __future__ import annotations

from typing import Optional

from sqlmodel import Session

from . import service
from .clock import Clock
from .models import Ticket
from .usecases import USE_CASES

ENGINES = {
    # lane key on each use case -> how the audit log should describe the actor
    "jev": ("jev", "judgment", "Relay judgment"),
    "ai": ("ai", "judgment", "Relay AI"),
    "rules": ("rules", "system", "Relay rules"),
}
# the person question's traditional lane is keyed differently, because it is
# rules *and* a counter rather than rules alone
PERSON_LANES = {"jev": "jev", "ai": "ai", "rules": "queue"}


def context(session: Session, team: Optional[str] = None) -> dict:
    """What the lanes read: the departments, and the people — narrowed to one
    department once that half is settled."""
    roster = service.roster_for_judgment(session)
    return {
        "teams": service.teams_for_judgment(session),
        "roster": [p for p in roster if p["team"] == team] if team else roster,
        # a settled department, so the traditional lane does not re-derive a
        # group of its own and contradict the half already decided
        "team": team,
    }


def suggest(session: Session, ticket: Ticket, engine: str = "jev") -> dict:
    """Both halves of a routing decision, without writing anything.

    The department question is skipped when the ticket already has one: a
    ticket a person has already placed is not re-argued, only staffed.
    """
    if engine not in ENGINES:
        raise ValueError(f"no routing engine {engine!r}; known: {', '.join(ENGINES)}")
    lane_key, actor_kind, actor = ENGINES[engine]

    out: dict = {"engine": engine, "actor": actor, "actor_kind": actor_kind,
                 "ticket": ticket.id, "subject": ticket.subject}

    team = ticket.team_key
    if team:
        out["team"] = {"answer": team, "kept": True,
                       "note": "the ticket already names a department, so only the person is decided"}
    else:
        measured = USE_CASES["team"].lane(lane_key).run(ticket.subject, context(session))
        out["team"] = measured.as_dict()
        team = measured.answer
        if measured.error or not team:
            out["error"] = measured.error or "no department came back"
            return out

    person_lane = USE_CASES["assignee"].lane(PERSON_LANES[lane_key])
    measured = person_lane.run(ticket.subject, context(session, team))
    out["person"] = measured.as_dict()
    if measured.error or not measured.answer:
        out["error"] = measured.error or "no person came back"
        return out

    names = {p["id"]: p["name"] for p in service.roster_for_judgment(session)}
    out["suggestion"] = {
        "team": team,
        "person": measured.answer,
        "person_name": names.get(measured.answer, measured.answer),
        "confidence": measured.confidence,
    }
    out["cost_usd"] = round(sum(
        out[half].get("cost_usd", 0) or 0 for half in ("team", "person") if isinstance(out.get(half), dict)
    ), 8)
    out["latency_ms"] = round(sum(
        out[half].get("latency_ms", 0) or 0 for half in ("team", "person") if isinstance(out.get(half), dict)
    ), 1)
    return out


def route(
    session: Session, ticket_id: str, clock: Clock, engine: str = "jev", apply: bool = False
) -> dict:
    """Suggest, and write it if asked to.

    ``apply=False`` is the interesting default: a suggestion the desk can look
    at, with its reason, before anyone lets it near a ticket.
    """
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise LookupError(f"no ticket {ticket_id}")
    out = suggest(session, ticket, engine)
    out["applied"] = False
    if not apply or "suggestion" not in out:
        return out

    _, actor_kind, actor = ENGINES[engine]
    note = lambda half: (out[half].get("detail", {}) or {}).get("note", "")  # noqa: E731
    service.assign(
        session, ticket_id,
        team=out["suggestion"]["team"], person=out["suggestion"]["person"],
        clock=clock, actor=actor, actor_kind=actor_kind,
        team_reason=note("team") or "routed by the department question",
        person_reason=note("person") or "routed by the person question",
    )
    out["applied"] = True
    return out
