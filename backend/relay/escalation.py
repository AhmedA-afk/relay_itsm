"""Predicting which open tickets are about to escalate.

Everything else in Relay reads what is already true. This reads what has not
happened yet, and the difference shows up in three places:

* **It is given the clock.** Sentiment is deliberately kept away from target
  burn so it cannot become a slower way of reading the SLA field. Here the
  opposite holds: a human predicting a blow-up weighs the age, the burn, the
  reopens and the bounces alongside the words, so the state goes in with them.
* **It goes stale on time, not only on messages.** A reading of how somebody
  sounds is good until they say something else. A prediction is undermined by
  the clock alone — the same ticket at 30% of its target and at 90% is not the
  same ticket — so the row keeps the burn it saw and says which has moved.
* **The threshold is not in the prompt.** The model returns a probability;
  ``policy.escalation_band`` turns it into a word. Moving the line is a policy
  edit, not a prompt edit, and it re-runs no inference.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from . import policy, sentiment as sentiment_module, service
from .clock import Clock, ensure_utc
from .models import Escalation, Message, Ticket
from .usecases import USE_CASES

ENGINES = ("jev", "ai", "sla")
# how far the burn can move before a stored prediction is worth redoing
BURN_DRIFT = 0.15


def _reassignments(session: Session, ticket_id: str) -> int:
    """How many times this ticket has changed hands, counted from the log.

    The audit trail already knows; storing a counter beside it would be a
    second version of the same fact, free to drift.
    """
    return sum(1 for e in service.events_for(session, ticket_id) if e.field == "assignee" and e.new_value)


def context(session: Session, ticket: Ticket, view: dict) -> dict:
    """What every lane reads: the conversation, and the ticket's own state."""
    thread = sentiment_module.thread(session, ticket)
    mood = sentiment_module.stored(session, ticket)
    sla = view["sla"]
    state = {
        "burn": round(sla["burn"], 3),
        "breached": sla["breached"],
        "reopened": ticket.reopened_count,
        "reassignments": _reassignments(session, ticket.id),
        "hours_open": round((view["opened_at"] and sla["resolution_minutes"] or 0) / 60, 1),
        "priority": view["priority"],
        "status": ticket.status,
        "assigned": bool(ticket.assignee_id),
    }

    ticket_state = dict(thread["state"]["ticket"])
    ticket_state.update({
        "priority": view["priority"],
        "status": ticket.status,
        "owner": view["assignee"] or "nobody has picked it up",
        "share_of_target_used": f"{sla['burn']:.0%}",
        "past_target": sla["breached"],
        "times_reopened": ticket.reopened_count,
        "times_reassigned": state["reassignments"],
    })
    if mood:
        ticket_state["how_they_sound"] = f"{mood['score']} of 5, {mood['label']}"

    lines = [thread["prose"], "",
             f"[{view['priority']}, {ticket.status}, with {view['assignee'] or 'nobody'}; "
             f"{sla['burn']:.0%} of the target used"
             + (", already past target" if sla["breached"] else "")
             + (f"; reopened {ticket.reopened_count}x" if ticket.reopened_count else "")
             + (f"; reassigned {state['reassignments']}x" if state["reassignments"] else "")
             + (f"; sounds {mood['label'].lower()}" if mood else "") + "]"]

    return {
        "state": {"ticket": ticket_state},
        "prose": "\n".join(lines),
        "ticket_state": state,
        "last_message_id": thread["last_message_id"],
        "message_count": thread["message_count"],
        "burn": sla["burn"],
    }


def stored(session: Session, ticket: Ticket, view: Optional[dict] = None) -> Optional[dict]:
    """The saved prediction, and whether anything it depended on has moved."""
    row = session.get(Escalation, ticket.id)
    if row is None:
        return None
    messages = [m for m in service.messages_for(session, ticket.id)
                if m.visibility in sentiment_module.SENT]
    last = messages[-1].id if messages else None
    burn_now = view["sla"]["burn"] if view else row.burn
    said = row.message_count != len(messages) or row.last_message_id != last
    moved = abs(burn_now - row.burn) >= BURN_DRIFT
    return {
        "probability": round(row.probability, 4),
        "band": row.band,
        "engine": row.engine,
        "model": row.model,
        "note": row.note,
        "at": ensure_utc(row.at),
        "burn_then": round(row.burn, 3),
        "burn_now": round(burn_now, 3),
        "messages_read": row.message_count,
        "messages_now": len(messages),
        # why it is stale, not merely that it is: the two have different answers
        "said_more": said,
        "clock_moved": moved,
        "stale": said or moved,
        "cost_usd": row.cost_usd,
        "latency_ms": row.latency_ms,
    }


def predict(session: Session, ticket_id: str, clock: Clock, engine: str = "jev") -> dict:
    """Ask how likely this ticket is to escalate, and save the answer."""
    if engine not in ENGINES:
        raise ValueError(f"no escalation engine {engine!r}; known: {', '.join(ENGINES)}")
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise LookupError(f"no ticket {ticket_id}")

    view = service.ticket_view(session, ticket, clock.now())
    ctx = context(session, ticket, view)
    measured = USE_CASES["escalation"].lane(engine).run(ticket.subject, ctx)
    if measured.error or measured.noul is None:
        raise ValueError(measured.error or "no probability came back")

    row = session.get(Escalation, ticket_id) or Escalation(ticket_id=ticket_id, probability=0.0)
    row.probability = measured.noul
    row.band = (measured.detail or {}).get("band", policy.escalation_band(measured.noul).value)
    row.engine = engine
    row.model = measured.model
    row.note = (measured.detail or {}).get("note", "")
    row.at = clock.now()
    row.burn = ctx["burn"]
    row.last_message_id = ctx["last_message_id"]
    row.message_count = ctx["message_count"]
    row.cost_usd = measured.cost_usd
    row.latency_ms = measured.latency_ms
    session.add(row)
    session.commit()
    return {**stored(session, ticket, view), "measured": measured.as_dict()}


def rows(session: Session) -> dict[str, dict]:
    """Every saved prediction at once, lean, for the queue."""
    counts: dict[str, tuple[int, int]] = {}
    for m in session.exec(select(Message).where(Message.visibility.in_(sentiment_module.SENT))).all():
        n, last = counts.get(m.ticket_id, (0, 0))
        counts[m.ticket_id] = (n + 1, max(last, m.id or 0))
    out = {}
    for row in session.exec(select(Escalation)).all():
        n, last = counts.get(row.ticket_id, (0, 0))
        out[row.ticket_id] = {
            "probability": round(row.probability, 4), "band": row.band, "engine": row.engine,
            "at": ensure_utc(row.at), "burn_then": round(row.burn, 3),
            "said_more": row.message_count != n or (row.last_message_id or 0) != last,
        }
    return out


def summary(session: Session, now: datetime) -> dict:
    """What the desk should be worried about, and how sure anyone is.

    Open tickets only: a prediction about a ticket that has already closed is
    not a warning, it is a scorecard, and the two do not belong in one number.
    """
    saved = rows(session)
    views = {v["id"]: v for v in service.list_tickets(session, now)}
    live = {tid: r for tid, r in saved.items()
            if tid in views and views[tid]["status"] not in service.LIVE_EXCLUDED}

    for tid, r in live.items():
        r["clock_moved"] = abs(views[tid]["sla"]["burn"] - r["burn_then"]) >= BURN_DRIFT
        r["stale"] = r["said_more"] or r["clock_moved"]

    bands = {"likely": 0, "watch": 0, "quiet": 0}
    for r in live.values():
        bands[r["band"]] = bands.get(r["band"], 0) + 1

    unread = [v["id"] for v in views.values()
              if v["status"] not in service.LIVE_EXCLUDED and v["id"] not in saved]
    riskiest = sorted(live.items(), key=lambda kv: -kv[1]["probability"])[:8]

    # The comparison worth drawing: how many of the tickets a judgment is
    # worried about have not tripped a single SLA rule yet. Those are the ones
    # the traditional lane cannot see, and the only ones where a prediction
    # buys any time at all.
    early = [tid for tid, r in live.items()
             if r["band"] != "quiet" and not views[tid]["sla"]["breached"]
             and views[tid]["sla"]["burn"] < 0.5]

    return {
        "thresholds": {"watch": policy.ESCALATION_WATCH, "likely": policy.ESCALATION_LIKELY},
        "read": len(live),
        "unread": len(unread),
        "unread_ids": unread[:50],
        "stale": sum(1 for r in live.values() if r["stale"]),
        "bands": bands,
        "flagged": bands["likely"] + bands["watch"],
        "early": len(early),
        "early_ids": early[:10],
        "riskiest": [
            {"id": tid, "subject": views[tid]["subject"], "probability": r["probability"],
             "band": r["band"], "stale": r["stale"], "priority": views[tid]["priority"],
             "assignee": views[tid]["assignee"], "team": views[tid]["team"],
             "burn": round(views[tid]["sla"]["burn"], 3), "breached": views[tid]["sla"]["breached"]}
            for tid, r in riskiest
        ],
    }
