"""Reading how a requester sounds, from the ticket they are living in.

The Showcase asks this of typed words. This asks it of a real conversation,
which is where the feeling actually is: nobody is angry in the subject line of
the ticket they just raised, they get angry on the third reply.

Three rules hold it together:

* **The thread is the state.** Subject, the requester's own words, and what the
  desk has said back, in order. A reply that says "sorry for the delay" is part
  of why they sound the way they do.
* **What it read is stored with it.** The row keeps the last message it saw and
  how many there were, so anything showing the number can say whether the
  conversation has moved since. See ``models.Sentiment`` for why this is the
  one derived value Relay stores.
* **Nothing about the clock goes in.** A breached P1 is not the same thing as
  an unhappy requester, and letting the target leak into the state would make
  the score a slower, dearer way of reading the SLA field.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from . import service
from .clock import Clock, ensure_utc
from .models import Message, Sentiment, Technician, Ticket
from .usecases import SENTIMENT_LABELS, SENTIMENT_SCALE, USE_CASES

ENGINES = {"jev": "jev", "ai": "ai", "lexicon": "lexicon"}
# a draft has not been sent, so it is not part of what anyone has read
SENT = ("public", "internal")


def _messages(session: Session, ticket_id: str) -> list[Message]:
    return [m for m in service.messages_for(session, ticket_id) if m.visibility in SENT]


def thread(session: Session, ticket: Ticket) -> dict:
    """The conversation as both a state object and plain prose.

    Two shapes of the same content: Jev reads the state, the prompt-and-parse
    lane and the word lists read the prose. Same words either way, so a
    difference in answer is the engine rather than the brief.
    """
    messages = _messages(session, ticket.id)
    requester = ticket.requester or "the requester"
    turns = [{
        "from": m.author or "unknown",
        "side": "requester" if m.author == ticket.requester else "service desk",
        "said": m.body,
    } for m in messages]

    state = {"ticket": {
        "subject": ticket.subject,
        "raised_by": requester,
        "reopened_times": ticket.reopened_count,
        "conversation": turns or [{"from": requester, "side": "requester", "said": ticket.body or ticket.subject}],
    }}
    lines = [f"Ticket raised by {requester}: {ticket.subject}"]
    if ticket.body:
        lines.append(ticket.body)
    lines += [f"{t['from']} ({t['side']}): {t['said']}" for t in turns]
    if ticket.reopened_count:
        lines.append(f"[this ticket has been reopened {ticket.reopened_count} time(s)]")
    return {
        "state": state,
        "prose": "\n".join(lines),
        "last_message_id": messages[-1].id if messages else None,
        "message_count": len(messages),
        # only the requester's own words carry their feeling; if they have not
        # said anything since raising it, that is worth knowing
        "requester_turns": sum(1 for t in turns if t["side"] == "requester"),
    }


def stored(session: Session, ticket: Ticket) -> Optional[dict]:
    """The saved reading, with whether the conversation has moved since."""
    row = session.get(Sentiment, ticket.id)
    if row is None:
        return None
    messages = _messages(session, ticket.id)
    last = messages[-1].id if messages else None
    stale = row.message_count != len(messages) or row.last_message_id != last
    return {
        "score": round(row.score, 2),
        "level": row.level,
        "label": SENTIMENT_LABELS.get(str(row.level), str(row.level)),
        "probabilities": json.loads(row.probabilities) if row.probabilities else None,
        "confidence": row.confidence,
        "engine": row.engine,
        "model": row.model,
        "note": row.note,
        "at": ensure_utc(row.at),
        "messages_read": row.message_count,
        "messages_now": len(messages),
        "stale": stale,
        "cost_usd": row.cost_usd,
        "latency_ms": row.latency_ms,
    }


def read(session: Session, ticket_id: str, clock: Clock, engine: str = "jev") -> dict:
    """Score a live ticket's conversation and save the reading."""
    if engine not in ENGINES:
        raise ValueError(f"no sentiment engine {engine!r}; known: {', '.join(ENGINES)}")
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise LookupError(f"no ticket {ticket_id}")

    context = thread(session, ticket)
    measured = USE_CASES["sentiment"].lane(engine).run(ticket.subject, context)
    if measured.error or not measured.answer:
        raise ValueError(measured.error or "no sentiment came back")

    # Jev gives a position on the scale; the other two give a whole level. Both
    # are stored the same way, so the column reads the same whatever produced it.
    score = measured.score + 1 if measured.score is not None else float(measured.answer)
    row = session.get(Sentiment, ticket_id) or Sentiment(ticket_id=ticket_id, score=score, level=1)
    row.score = score
    row.level = int(measured.answer)
    row.probabilities = json.dumps(measured.probabilities) if measured.probabilities else ""
    row.confidence = measured.confidence
    row.engine = engine
    row.model = measured.model
    row.note = (measured.detail or {}).get("note", "")
    row.at = clock.now()
    row.last_message_id = context["last_message_id"]
    row.message_count = context["message_count"]
    row.cost_usd = measured.cost_usd
    row.latency_ms = measured.latency_ms
    session.add(row)
    session.commit()
    return {**stored(session, ticket), "measured": measured.as_dict()}


def by_ticket(session: Session) -> dict[str, dict]:
    """Every saved reading at once, for the queue and the dashboards.

    One query rather than one per row: the whole point of storing it is that a
    hundred-ticket queue costs no model calls to draw.
    """
    counts: dict[str, tuple[int, Optional[int]]] = {}
    for m in session.exec(select(Message).where(Message.visibility.in_(SENT))).all():
        n, last = counts.get(m.ticket_id, (0, None))
        counts[m.ticket_id] = (n + 1, max(last or 0, m.id or 0) or None)
    out = {}
    for row in session.exec(select(Sentiment)).all():
        n, last = counts.get(row.ticket_id, (0, None))
        out[row.ticket_id] = {
            "score": round(row.score, 2), "level": row.level,
            "label": SENTIMENT_LABELS.get(str(row.level), str(row.level)),
            "confidence": row.confidence, "engine": row.engine,
            "at": ensure_utc(row.at), "stale": row.message_count != n or row.last_message_id != last,
        }
    return out


def _mean(values: list[float]) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


def summary(session: Session, now: datetime) -> dict:
    """The desk's satisfaction as it stands, and who is carrying the unhappiest.

    Only open tickets count. A closed ticket's sentiment is history — useful to
    report on, but not something anybody can still do anything about, and
    mixing the two would let a good week of closures hide a bad queue.
    """
    readings = by_ticket(session)
    views = {v["id"]: v for v in service.list_tickets(session, now)}
    people = {t.id: t for t in session.exec(select(Technician)).all()}

    live = {tid: r for tid, r in readings.items()
            if tid in views and views[tid]["status"] not in service.LIVE_EXCLUDED}
    spread = {level: 0 for level in SENTIMENT_SCALE}
    for r in live.values():
        spread[str(r["level"])] = spread.get(str(r["level"]), 0) + 1

    per_person: dict[str, list[float]] = {}
    per_team: dict[str, list[float]] = {}
    for tid, r in live.items():
        view = views[tid]
        if view["assignee_id"]:
            per_person.setdefault(view["assignee_id"], []).append(r["score"])
        if view["team"]:
            per_team.setdefault(view["team"], []).append(r["score"])

    unread = [v["id"] for v in views.values()
              if v["status"] not in service.LIVE_EXCLUDED and v["id"] not in readings]
    unhappiest = sorted(live.items(), key=lambda kv: kv[1]["score"])[:8]

    return {
        "scale": {k: SENTIMENT_LABELS[k] for k in SENTIMENT_SCALE},
        "read": len(live),
        "unread": len(unread),
        "unread_ids": unread[:50],
        "stale": sum(1 for r in live.values() if r["stale"]),
        "average": _mean([r["score"] for r in live.values()]),
        "spread": spread,
        "unhappy": sum(1 for r in live.values() if r["level"] <= 2),
        "unhappiest": [
            {"id": tid, "subject": views[tid]["subject"], "score": r["score"], "level": r["level"],
             "label": r["label"], "stale": r["stale"], "priority": views[tid]["priority"],
             "assignee": views[tid]["assignee"], "team": views[tid]["team"]}
            for tid, r in unhappiest
        ],
        "by_person": [
            {"id": pid, "name": people[pid].name if pid in people else pid,
             "team": people[pid].team_key if pid in people else "", "average": _mean(scores),
             "read": len(scores)}
            for pid, scores in sorted(per_person.items(), key=lambda kv: _mean(kv[1]) or 5)
        ],
        "by_team": {team: {"average": _mean(scores), "read": len(scores)}
                    for team, scores in per_team.items()},
    }
