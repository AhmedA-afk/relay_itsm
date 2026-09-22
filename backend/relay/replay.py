"""Put real tickets on the live desk by replaying one moment of ABC Tech's queue.

    python -m relay.replay                      # 7 March 2014, 1 in 8, last 24h of resolutions
    python -m relay.replay --every 4 --at 2013-11-22

Reads the cleaned ``historicticket`` rows (run ``relay.import_history`` first),
takes every ABC Tech ticket that was open at the chosen moment, keeps a fixed
1-in-N sample, and writes them as live ``Ticket`` rows with every timestamp
moved forward by a whole number of weeks so they land at the same point of the
week, now. Tickets resolved in the day before the moment come along too, so the
Resolved view has real outcomes in it.

What a replayed ticket keeps from the source: its id, kind, item, impact and
urgency (so the matrix derives its level exactly as it does for any ticket),
its age, its reassignment history and, once resolved, its closure cause. What
Relay supplies, and records as a system event with its reason: the team (from
the item class), the person (least-loaded, the rule Administration shows), and
a subject built from the fields, because the source has no words to use.

Idempotent: a run removes the tickets and events of the previous one — every
replayed ticket keeps its ABC Tech id, which starts ``IM`` — and nothing else.
"""

from __future__ import annotations

import argparse
import dataclasses
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlmodel import Session, select

from . import history, policy
from .clock import SystemClock, ensure_utc
from .db import create_all, engine
from .models import Event, HistoricTicket, Message, Ticket
from .service import candidates

DEFAULT_AT = datetime(2014, 3, 7, 14, 0, tzinfo=timezone.utc)
PREFIX = "IM"   # ABC Tech's own id scheme, and how a re-run finds its rows


def replay(session: Session, now: datetime, at: datetime = DEFAULT_AT,
           every: int = 8, resolved_hours: int = 24) -> dict:
    cut, shift = history.weeks_back(now, at)
    weeks = int(shift / history.WEEK)

    ids = [t.id for t in session.exec(select(Ticket).where(Ticket.id.startswith(PREFIX))).all()]
    if ids:
        session.exec(delete(Event).where(Event.ticket_id.in_(ids)))
        session.exec(delete(Message).where(Message.ticket_id.in_(ids)))
        session.exec(delete(Ticket).where(Ticket.id.in_(ids)))
        session.flush()

    rows = session.exec(
        select(HistoricTicket)
        .where(HistoricTicket.source == history.ABC)
        .where(HistoricTicket.impact.is_not(None))       # no impact, no level: not replayable
        .where(HistoricTicket.opened_at <= cut)
    ).all()

    # Each person's full record — on leave, capacity, skills — with only the
    # count changing as tickets land, so routing sees what it sees in the app.
    people = {c.id: c for c in candidates(session)}
    load = {pid: c.open_tickets for pid, c in people.items()}
    picked = {"open": 0, "resolved": 0}

    for h in sorted(rows, key=lambda r: ensure_utc(r.opened_at)):
        if not history.in_sample(h.source_id, every):
            continue
        opened = ensure_utc(h.opened_at)
        resolved = ensure_utc(h.resolved_at)
        closed = ensure_utc(h.closed_at)
        ended = resolved or closed
        still_open = ended is None or ended > cut
        if not still_open and ended < cut - timedelta(hours=resolved_hours):
            continue

        team, team_reason = history.team_for(h.category, h.kind)
        pool = [dataclasses.replace(people[i], open_tickets=n) for i, n in load.items()]
        who = policy.route_to_person(team, pool)
        if still_open and who.value:
            load[who.value] += 1

        if still_open:
            status = "in_progress" if (h.reassignments or 0) > 0 else "assigned"
        else:
            status = "closed" if closed and closed <= cut else "resolved"
        reopened = 1 if h.reopened_at and ensure_utc(h.reopened_at) <= cut else 0
        at_now = lambda t: t + shift if t else None   # noqa: E731

        ticket = Ticket(
            id=h.source_id, kind=h.kind, subject=history.live_subject(h.subject),
            requester="", department="", impact=h.impact, urgency=h.urgency,
            category=h.category, team_key=team, assignee_id=who.value, status=status,
            service=h.service, affected_ci=h.affected_ci, reopened_count=reopened,
            opened_at=at_now(opened),
            resolved_at=None if still_open else at_now(resolved or closed),
            resolution_code="" if still_open else history.code_for(h.closure),
            resolution_note="" if still_open else f"ABC Tech closure cause: {h.closure or 'not recorded'}",
        )
        session.add(ticket)

        def event(field: str, new: str, reason: str, actor="Relay", kind="system", when=None):
            session.add(Event(ticket_id=h.source_id, at=when or at_now(opened), actor=actor, actor_kind=kind,
                              field=field, old_value="", new_value=new, reason=reason))

        event("created", h.source_id,
              f"replayed from ABC Tech {h.source_id}, opened {opened:%d %b %Y %H:%M}; "
              f"every time moved forward {weeks} weeks so the desk reads as live", actor="ABC Tech")
        event("impact", h.impact, "recorded by ABC Tech at intake", actor="ABC Tech", kind="person")
        event("urgency", h.urgency, "recorded by ABC Tech at intake", actor="ABC Tech", kind="person")
        derived = policy.DEFAULT_MATRIX[h.impact][h.urgency]
        event("priority", derived, f"{h.impact} against {h.urgency} in the matrix"
              + ("" if derived == h.recorded_priority else f"; ABC Tech had recorded {h.recorded_priority}"))
        event("team", team, team_reason)
        event("assignee", who.value or "", who.reason)
        if (h.reassignments or 0) > 0:
            event("reassignments", str(h.reassignments),
                  f"ABC Tech handed it between groups {h.reassignments} times over its whole life")
        if not still_open:
            event("status", ticket.status,
                  f"{history.code_for(h.closure) or 'no Relay code'}; closure cause recorded as "
                  f"{h.closure or 'nothing'}", actor="ABC Tech", kind="person", when=ticket.resolved_at)
        picked["open" if still_open else "resolved"] += 1

    session.commit()
    return {"moment": cut.isoformat(), "weeks": weeks, "every": every, **picked,
            "load": {k: v for k, v in load.items()}}


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--at", default=DEFAULT_AT.date().isoformat(),
                        help="the day to replay; the time of day is today's (default 2014-03-07)")
    parser.add_argument("--every", type=int, default=8, help="keep 1 in N of the tickets open then (default 8)")
    parser.add_argument("--resolved-hours", type=int, default=24,
                        help="also bring tickets resolved this many hours before the moment (default 24)")
    args = parser.parse_args(argv)

    create_all()
    now = SystemClock().now()
    target = datetime.fromisoformat(args.at).replace(tzinfo=timezone.utc,
                                                     hour=now.hour, minute=now.minute)
    with Session(engine) as session:
        if not session.exec(select(HistoricTicket).limit(1)).first():
            raise SystemExit("no history loaded; run python -m relay.import_history first")
        result = replay(session, now, target, args.every, args.resolved_hours)
    print(result)
    return result


if __name__ == "__main__":
    main()
