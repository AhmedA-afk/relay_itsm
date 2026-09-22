"""The impure layer: database plus policy.

Everything that decides anything lives in ``policy``. This module reads rows,
asks policy, writes rows, and records an event for each change. Keeping the two
apart is what lets the decision layer be tested with no database and no clock.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from sqlmodel import Session, select

from . import policy
from .clock import Clock, ensure_utc
from .models import (
    Escalation,
    Event,
    MatrixCell,
    Message,
    Sentiment,
    SlaRuleRow,
    Team,
    Technician,
    Ticket,
)

LIVE_EXCLUDED = ("resolved", "closed", "cancelled", "spam")


# what a form puts in the fields nobody touches, the same values the Showcase's
# traditional lanes use
FORM_IMPACT, FORM_URGENCY = "individual", "medium"


def skill_list(value: str) -> list[str]:
    """``"vpn, wifi, dns"`` as a list. Stored as one string because a skill set
    is read far more often than it is queried."""
    return [s.strip() for s in (value or "").split(",") if s.strip()]


# ---------------------------------------------------------------- configuration

def load_matrix(session: Session) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {i: {} for i in policy.IMPACTS}
    for cell in session.exec(select(MatrixCell)).all():
        out.setdefault(cell.impact, {})[cell.urgency] = cell.priority
    return out


def save_matrix(session: Session, matrix: dict[str, dict[str, str]]) -> None:
    for impact, row in matrix.items():
        if impact not in policy.IMPACTS:
            raise ValueError(f"unknown impact {impact!r}")
        for urgency, priority in row.items():
            if urgency not in policy.URGENCIES:
                raise ValueError(f"unknown urgency {urgency!r}")
            if priority not in policy.PRIORITIES:
                raise ValueError(f"unknown priority {priority!r}")
            cell = session.get(MatrixCell, (impact, urgency))
            if cell is None:
                session.add(MatrixCell(impact=impact, urgency=urgency, priority=priority))
            else:
                cell.priority = priority
                session.add(cell)
    session.commit()


def load_sla_rules(session: Session) -> tuple[policy.SlaRule, ...]:
    rows = session.exec(select(SlaRuleRow).order_by(SlaRuleRow.order)).all()
    return tuple(
        policy.SlaRule(r.order, r.priority, r.response_minutes, r.resolution_minutes, r.calendar)
        for r in rows
    )


# ---------------------------------------------------------------- reads

def sentiment_rows(session: Session) -> dict[str, dict]:
    """Saved sentiment per ticket, each marked stale if the thread has moved.

    Deliberately label-free: ``relay.sentiment`` owns what the levels are
    called, and it imports this module, so this one cannot import it back.
    """
    counts: dict[str, tuple[int, int]] = {}
    for m in session.exec(select(Message).where(Message.visibility.in_(("public", "internal")))).all():
        n, last = counts.get(m.ticket_id, (0, 0))
        counts[m.ticket_id] = (n + 1, max(last, m.id or 0))
    out = {}
    for row in session.exec(select(Sentiment)).all():
        n, last = counts.get(row.ticket_id, (0, 0))
        out[row.ticket_id] = {
            "score": round(row.score, 2), "level": row.level, "confidence": row.confidence,
            "engine": row.engine, "at": ensure_utc(row.at),
            "stale": row.message_count != n or (row.last_message_id or 0) != last,
        }
    return out

def escalation_rows(session: Session) -> dict[str, dict]:
    """Saved escalation predictions, lean. ``relay.escalation`` owns staleness
    against the clock, because that needs each ticket's live burn."""
    return {
        row.ticket_id: {"probability": round(row.probability, 4), "band": row.band,
                        "engine": row.engine, "burn_then": round(row.burn, 3),
                        "at": ensure_utc(row.at)}
        for row in session.exec(select(Escalation)).all()
    }


def ticket_view(
    session: Session,
    ticket: Ticket,
    now: datetime,
    matrix: Optional[dict] = None,
    rules: Optional[tuple[policy.SlaRule, ...]] = None,
    sentiments: Optional[dict] = None,
    escalations: Optional[dict] = None,
) -> dict:
    """A ticket as the interface needs it, with everything derived on the spot.

    Everything except sentiment, which is read from its own table rather than
    recomputed — see ``models.Sentiment`` for why that one is stored.
    """
    matrix = matrix if matrix is not None else load_matrix(session)
    rules = rules if rules is not None else load_sla_rules(session)

    opened_at = ensure_utc(ticket.opened_at)
    paused_at = ensure_utc(ticket.paused_at)
    resolved_at = ensure_utc(ticket.resolved_at)
    first_response_at = ensure_utc(ticket.first_response_at)

    prio = policy.derive_priority(matrix, ticket.impact, ticket.urgency)
    rule_decision = policy.pick_sla(prio.value, rules)
    rule: policy.SlaRule = rule_decision.value  # type: ignore[assignment]

    response_due = policy.due_at(opened_at, rule.response_minutes, rule.calendar)
    resolution_due = policy.due_at(opened_at, rule.resolution_minutes, rule.calendar)

    paused = ticket.paused_seconds
    if paused_at is not None:
        paused += int((now - paused_at).total_seconds())

    frozen = policy.clock_is_paused(ticket.status)
    reference = resolved_at or now

    remaining = policy.seconds_remaining(
        resolution_due, reference, rule.calendar, paused
    )
    burn = policy.target_burn(opened_at, resolution_due, reference, paused)

    response_remaining = policy.seconds_remaining(
        response_due, first_response_at or now, rule.calendar, 0
    )

    assignee = session.get(Technician, ticket.assignee_id) if ticket.assignee_id else None
    if sentiments is None:
        sentiments = sentiment_rows(session)
    if escalations is None:
        escalations = escalation_rows(session)
    risk = escalations.get(ticket.id)
    if risk is not None:
        # the clock has moved on if the burn has drifted since it was asked
        risk = {**risk, "stale": abs(burn - risk["burn_then"]) >= 0.15}

    return {
        "sentiment": sentiments.get(ticket.id),
        "escalation": risk,
        "id": ticket.id,
        "kind": ticket.kind,
        "subject": ticket.subject,
        "body": ticket.body,
        "requester": ticket.requester,
        "department": ticket.department,
        "impact": ticket.impact,
        "urgency": ticket.urgency,
        "priority": prio.value,
        "priority_reason": prio.reason,
        "category": ticket.category,
        "team": ticket.team_key,
        "assignee": assignee.name if assignee else None,
        "assignee_id": ticket.assignee_id,
        "status": ticket.status,
        "major": ticket.major,
        "hold_reason": ticket.hold_reason,
        "problem_id": ticket.problem_id,
        "service": ticket.service,
        "affected_ci": ticket.affected_ci,
        "duplicate_of": ticket.duplicate_of,
        "resolution_code": ticket.resolution_code,
        "resolution_label": policy.RESOLUTION_CODES.get(ticket.resolution_code, ""),
        "resolution_note": ticket.resolution_note,
        "reopened_count": ticket.reopened_count,
        "opened_at": opened_at,
        "resolved_at": resolved_at,
        "first_response_at": first_response_at,
        "sla": {
            "rule_order": rule.order,
            "rule_reason": rule_decision.reason,
            "calendar": rule.calendar,
            "response_minutes": rule.response_minutes,
            "resolution_minutes": rule.resolution_minutes,
            "response_due_at": response_due,
            "resolution_due_at": resolution_due,
            "response_remaining_seconds": response_remaining,
            "remaining_seconds": remaining,
            "burn": round(burn, 4),
            "paused_seconds": paused,
            "clock_paused": frozen,
            "breached": remaining < 0,
        },
    }


def list_tickets(
    session: Session, now: datetime, kind: Optional[str] = None
) -> list[dict]:
    stmt = select(Ticket)
    if kind:
        stmt = stmt.where(Ticket.kind == kind)
    matrix = load_matrix(session)
    rules = load_sla_rules(session)
    sentiments = sentiment_rows(session)
    escalations = escalation_rows(session)
    views = [
        ticket_view(session, t, now, matrix, rules, sentiments, escalations)
        for t in session.exec(stmt).all()
    ]
    views.sort(key=lambda v: v["sla"]["remaining_seconds"])
    return views


def messages_for(session: Session, ticket_id: str) -> list[Message]:
    return list(
        session.exec(
            select(Message).where(Message.ticket_id == ticket_id).order_by(Message.at)
        ).all()
    )


def events_for(session: Session, ticket_id: str) -> list[Event]:
    return list(
        session.exec(
            select(Event).where(Event.ticket_id == ticket_id).order_by(Event.id)
        ).all()
    )


def open_counts_by_person(session: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in session.exec(select(Ticket)).all():
        if t.assignee_id and t.status not in ("resolved", "closed", "cancelled", "spam"):
            counts[t.assignee_id] = counts.get(t.assignee_id, 0) + 1
    return counts


def candidates(session: Session) -> list[policy.Candidate]:
    loads = open_counts_by_person(session)
    return [
        policy.Candidate(
            id=t.id, name=t.name, team=t.team_key,
            open_tickets=loads.get(t.id, 0), on_leave=t.on_leave,
            skills=tuple(skill_list(t.skills)), capacity=t.capacity,
            tier=t.tier, location=t.location,
        )
        for t in session.exec(select(Technician)).all()
    ]


# ---------------------------------------------------------------- the roster

def _blank_load() -> dict:
    return {"open": 0, "breached": 0, "by_priority": {p: 0 for p in policy.PRIORITIES}}


def _add(load: dict, view: dict) -> None:
    load["open"] += 1
    load["by_priority"][view["priority"]] += 1
    if view["sla"]["breached"]:
        load["breached"] += 1


def workforce(session: Session, now: datetime) -> dict:
    """Departments, the people in them, and what each one is currently carrying.

    Every number here is counted from the live tickets rather than stored, for
    the same reason priority is: a load that is written down is a load that can
    be wrong. The priority breakdown comes from each ticket's derived level, so
    editing the matrix in Administration moves these bars too.
    """
    views = [v for v in list_tickets(session, now) if v["status"] not in LIVE_EXCLUDED]
    teams = session.exec(select(Team).order_by(Team.position)).all()
    people = session.exec(select(Technician).order_by(Technician.name)).all()

    per_person = {t.id: _blank_load() for t in people}
    per_team = {t.key: _blank_load() for t in teams}
    unclaimed = {t.key: 0 for t in teams}
    untriaged = []
    oldest: dict[str, float] = {}

    for v in views:
        if v["team"] in per_team:
            _add(per_team[v["team"]], v)
            if not v["assignee_id"]:
                unclaimed[v["team"]] += 1
        if v["assignee_id"] in per_person:
            _add(per_person[v["assignee_id"]], v)
            age = (now - v["opened_at"]).total_seconds()
            oldest[v["assignee_id"]] = max(oldest.get(v["assignee_id"], 0.0), age)
        elif not v["team"]:
            untriaged.append(v["id"])

    def person_row(t: Technician) -> dict:
        load = per_person[t.id]
        return {
            "id": t.id, "name": t.name, "team": t.team_key, "tier": t.tier,
            "skills": skill_list(t.skills), "capacity": t.capacity,
            "location": t.location, "on_leave": t.on_leave,
            **load,
            "load": round(load["open"] / t.capacity, 3) if t.capacity else None,
            "headroom": t.capacity - load["open"],
            "oldest_seconds": int(oldest.get(t.id, 0)),
        }

    rows = [person_row(t) for t in people]
    by_team: dict[str, list[dict]] = {}
    for row in rows:
        by_team.setdefault(row["team"], []).append(row)

    return {
        "teams": [
            {
                "key": t.key, "name": t.name, "domain": t.domain, "position": t.position,
                "skills": skill_list(t.skills),
                "people": sorted(by_team.get(t.key, []), key=lambda r: (r["on_leave"], -r["open"])),
                "headcount": len(by_team.get(t.key, [])),
                "available": sum(1 for r in by_team.get(t.key, []) if not r["on_leave"]),
                "capacity": sum(r["capacity"] for r in by_team.get(t.key, []) if not r["on_leave"]),
                "unclaimed": unclaimed.get(t.key, 0),
                **per_team[t.key],
            }
            for t in teams
        ],
        # people whose team was deleted or never set still have to be visible
        "unplaced": [r for r in rows if r["team"] not in per_team],
        "untriaged": untriaged,
        "totals": {
            "open": len(views),
            "people": len(rows),
            "unassigned": sum(1 for v in views if not v["assignee_id"]),
        },
    }


def roster_for_judgment(session: Session) -> list[dict]:
    """The roster as a routing decision needs to see it: who they are, what
    they are good at, and how much they are already carrying."""
    loads = open_counts_by_person(session)
    teams = {t.key: t for t in session.exec(select(Team)).all()}
    out = []
    for t in session.exec(select(Technician).order_by(Technician.team_key, Technician.name)).all():
        team = teams.get(t.team_key)
        out.append({
            "id": t.id, "name": t.name, "team": t.team_key,
            "team_name": team.name if team else t.team_key,
            "tier": t.tier, "skills": skill_list(t.skills),
            "open_tickets": loads.get(t.id, 0), "capacity": t.capacity,
            "location": t.location, "on_leave": t.on_leave,
        })
    return out


def teams_for_judgment(session: Session) -> list[dict]:
    return [
        {"key": t.key, "name": t.name, "domain": t.domain, "skills": skill_list(t.skills)}
        for t in session.exec(select(Team).order_by(Team.position)).all()
    ]


# ---------------------------------------------------------------- roster writes

def save_team(session: Session, key: str, fields: dict, *, creating: bool) -> Team:
    team = session.get(Team, key)
    if creating and team is not None:
        raise ValueError(f"a team called {key!r} already exists")
    if not creating and team is None:
        raise LookupError(f"no team {key}")
    if creating:
        if not key or not key.replace("_", "").isalnum():
            raise ValueError("a team key is letters, digits and underscores")
        last = session.exec(select(Team).order_by(Team.position.desc())).first()
        team = Team(key=key, name=fields.get("name") or key, domain=fields.get("domain", ""),
                    position=(last.position + 1) if last else 1)
    for field in ("name", "domain", "skills", "position"):
        if fields.get(field) is not None:
            setattr(team, field, fields[field])
    session.add(team)
    session.commit()
    session.refresh(team)
    return team


def delete_team(session: Session, key: str) -> None:
    """Refused while anyone or anything still points at it.

    Deleting a department out from under a live ticket would leave it owned by
    a key that resolves to nothing, so the refusal names what is in the way.
    """
    team = session.get(Team, key)
    if team is None:
        raise LookupError(f"no team {key}")
    people = session.exec(select(Technician).where(Technician.team_key == key)).all()
    if people:
        names = ", ".join(p.name for p in people[:3])
        more = f" and {len(people) - 3} more" if len(people) > 3 else ""
        raise ValueError(f"{team.name} still has {names}{more} on it; move them first")
    held = session.exec(
        select(Ticket).where(Ticket.team_key == key, Ticket.status.not_in(LIVE_EXCLUDED))
    ).all()
    if held:
        raise ValueError(f"{team.name} still owns {len(held)} open tickets; hand them over first")
    session.delete(team)
    session.commit()


def save_person(session: Session, person_id: str, fields: dict, *, creating: bool) -> Technician:
    person = session.get(Technician, person_id)
    if creating and person is not None:
        raise ValueError(f"a person with id {person_id!r} already exists")
    if not creating and person is None:
        raise LookupError(f"no person {person_id}")
    team_key = fields.get("team")
    if team_key is not None and session.get(Team, team_key) is None:
        raise ValueError(f"no team {team_key!r} to put them on")
    if creating:
        if not person_id or not person_id.replace("_", "").isalnum():
            raise ValueError("an id is letters, digits and underscores")
        if not fields.get("name"):
            raise ValueError("a person needs a name")
        if not team_key:
            raise ValueError("a person needs a team")
        person = Technician(id=person_id, name=fields["name"], team_key=team_key)
    if team_key is not None:
        person.team_key = team_key
    for field in ("name", "tier", "skills", "location"):
        if fields.get(field) is not None:
            setattr(person, field, fields[field])
    if fields.get("capacity") is not None:
        capacity = int(fields["capacity"])
        if capacity < 1:
            raise ValueError("capacity is at least one ticket")
        person.capacity = capacity
    if fields.get("on_leave") is not None:
        person.on_leave = bool(fields["on_leave"])
    session.add(person)
    session.commit()
    session.refresh(person)
    return person


def delete_person(session: Session, person_id: str, clock: Clock, actor: str) -> int:
    """Remove someone, handing back whatever they were holding.

    Their open tickets are unassigned rather than deleted or silently
    reassigned, and each hand-back is an event, because a ticket losing its
    owner is a fact the audit trail should carry.
    """
    person = session.get(Technician, person_id)
    if person is None:
        raise LookupError(f"no person {person_id}")
    now = clock.now()
    held = session.exec(
        select(Ticket).where(Ticket.assignee_id == person_id, Ticket.status.not_in(LIVE_EXCLUDED))
    ).all()
    for ticket in held:
        ticket.assignee_id = None
        if policy.can_transition(ticket.status, "new"):
            ticket.status = "new"
        session.add(ticket)
        record(session, ticket.id, at=now, actor=actor, actor_kind="person",
               field="assignee", old=person.name, new=None,
               reason=f"{person.name} was removed from the roster")
    session.delete(person)
    session.commit()
    return len(held)


# ---------------------------------------------------------------- writes

def record(
    session: Session,
    ticket_id: str,
    *,
    at: datetime,
    actor: str,
    actor_kind: str,
    field: str,
    old: object,
    new: object,
    reason: str = "",
) -> Event:
    event = Event(
        ticket_id=ticket_id, at=at, actor=actor, actor_kind=actor_kind,
        field=field, old_value="" if old is None else str(old),
        new_value="" if new is None else str(new), reason=reason,
    )
    session.add(event)
    return event


def _get(session: Session, ticket_id: str) -> Ticket:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise LookupError(f"no ticket {ticket_id}")
    return ticket


def _resume_clock(session: Session, ticket: Ticket, now: datetime) -> None:
    paused_at = ensure_utc(ticket.paused_at)
    if paused_at is not None:
        ticket.paused_seconds += int((now - paused_at).total_seconds())
        ticket.paused_at = None


def claim(session: Session, ticket_id: str, tech_id: str, clock: Clock, actor: str) -> Ticket:
    now = clock.now()
    ticket = _get(session, ticket_id)
    tech = session.get(Technician, tech_id)
    if tech is None:
        raise LookupError(f"no technician {tech_id}")
    old_assignee, old_status = ticket.assignee_id, ticket.status
    target = "in_progress" if policy.can_transition(ticket.status, "in_progress") else ticket.status
    if target != ticket.status:
        policy.assert_transition(ticket.status, target)
    _resume_clock(session, ticket, now)
    ticket.assignee_id = tech_id
    ticket.team_key = tech.team_key
    ticket.status = target
    ticket.hold_reason = ""
    session.add(ticket)
    record(session, ticket_id, at=now, actor=actor, actor_kind="person",
           field="assignee", old=old_assignee, new=tech.name, reason="claimed from the list")
    if old_status != target:
        record(session, ticket_id, at=now, actor=actor, actor_kind="person",
               field="status", old=old_status, new=target, reason="picked up by a technician")
    session.commit()
    session.refresh(ticket)
    return ticket


def unassign(session: Session, ticket_id: str, clock: Clock, actor: str) -> Ticket:
    now = clock.now()
    ticket = _get(session, ticket_id)
    old = ticket.assignee_id
    ticket.assignee_id = None
    if policy.can_transition(ticket.status, "new"):
        record(session, ticket_id, at=now, actor=actor, actor_kind="person",
               field="status", old=ticket.status, new="new", reason="handed back to the team")
        ticket.status = "new"
    session.add(ticket)
    record(session, ticket_id, at=now, actor=actor, actor_kind="person",
           field="assignee", old=old, new=None, reason="handed back")
    session.commit()
    session.refresh(ticket)
    return ticket


def auto_route(session: Session, ticket_id: str, clock: Clock, strategy: str = "least_loaded") -> Ticket:
    """Step two of routing. Step one picked the team; this only counts."""
    now = clock.now()
    ticket = _get(session, ticket_id)
    decision = policy.route_to_person(ticket.team_key or "", candidates(session), strategy)
    if decision.value is None:
        record(session, ticket_id, at=now, actor="Relay", actor_kind="system",
               field="assignee", old=ticket.assignee_id, new=None, reason=decision.reason)
        session.commit()
        session.refresh(ticket)
        return ticket
    tech = session.get(Technician, decision.value)
    old = ticket.assignee_id
    ticket.assignee_id = tech.id
    if policy.can_transition(ticket.status, "assigned"):
        ticket.status = "assigned"
    session.add(ticket)
    record(session, ticket_id, at=now, actor="Relay", actor_kind="system",
           field="assignee", old=old, new=tech.name, reason=decision.reason)
    session.commit()
    session.refresh(ticket)
    return ticket


def create_ticket(
    session: Session,
    *,
    subject: str,
    body: str = "",
    requester: str = "",
    department: str = "",
    kind: str = policy.INCIDENT,
    impact: Optional[str] = None,
    urgency: Optional[str] = None,
    clock: Clock,
) -> Ticket:
    """A ticket as it actually arrives: words, and almost nothing else.

    It lands with no department and no owner, which is the honest state of a
    ticket nobody has looked at — and the state routing exists to resolve.
    Impact and urgency fall back to the form defaults rather than being guessed
    here, and the event log says so in as many words, so the difference a
    judgment makes to those fields stays visible later.
    """
    subject = (subject or "").strip()
    if not subject:
        raise ValueError("a ticket needs a subject")
    if kind not in (policy.INCIDENT, policy.REQUEST):
        raise ValueError(f"unknown kind {kind!r}")
    if impact is not None and impact not in policy.IMPACTS:
        raise ValueError(f"unknown impact {impact!r}")
    if urgency is not None and urgency not in policy.URGENCIES:
        raise ValueError(f"unknown urgency {urgency!r}")

    now = clock.now()
    existing = [t.id for t in session.exec(select(Ticket)).all()]
    ticket = Ticket(
        id=policy.next_id(kind, existing), kind=kind, subject=subject, body=body,
        requester=requester, department=department,
        impact=impact or FORM_IMPACT, urgency=urgency or FORM_URGENCY,
        status="new", opened_at=now,
    )
    session.add(ticket)
    record(session, ticket.id, at=now, actor=requester or "the portal", actor_kind="person",
           field="created", old=None, new=ticket.id, reason="raised from the staff portal")
    for field, value, given in (("impact", ticket.impact, impact), ("urgency", ticket.urgency, urgency)):
        record(session, ticket.id, at=now, actor=requester or "the portal", actor_kind="person",
               field=field, old=None, new=value,
               reason="picked by the caller on the form" if given
               else "nobody touched the field, so it kept the form's default")
    session.commit()
    session.refresh(ticket)
    return ticket


def assign(
    session: Session,
    ticket_id: str,
    *,
    team: Optional[str] = None,
    person: Optional[str] = None,
    clock: Clock,
    actor: str = "Relay",
    actor_kind: str = "judgment",
    team_reason: str = "",
    person_reason: str = "",
) -> Ticket:
    """Put a ticket on a team, and optionally in someone's hands.

    This is where a routing judgment lands. It writes exactly what it was
    given and records who decided each half with its own reason, so the audit
    trail can later separate "the judgment picked the team" from "a person
    picked someone else". The person is checked against the roster by
    ``policy.accept_assignment`` before anything is written: a suggested name
    that is on leave, on another team, or not there at all is refused rather
    than trusted.
    """
    now = clock.now()
    ticket = _get(session, ticket_id)
    target_team = team or ticket.team_key

    if team and team != ticket.team_key:
        if session.get(Team, team) is None:
            raise LookupError(f"no team {team}")
        record(session, ticket_id, at=now, actor=actor, actor_kind=actor_kind,
               field="team_key", old=ticket.team_key, new=team,
               reason=team_reason or "routed to this team")
        ticket.team_key = team

    if person:
        decision = policy.accept_assignment(person, target_team or "", candidates(session))
        if decision.value is None:
            raise ValueError(decision.reason)
        tech = session.get(Technician, decision.value)
        if tech.id != ticket.assignee_id:
            record(session, ticket_id, at=now, actor=actor, actor_kind=actor_kind,
                   field="assignee", old=ticket.assignee_id, new=tech.name,
                   reason=person_reason or decision.reason)
            ticket.assignee_id = tech.id
        if policy.can_transition(ticket.status, "assigned"):
            record(session, ticket_id, at=now, actor="Relay", actor_kind="system",
                   field="status", old=ticket.status, new="assigned",
                   reason="a ticket with an owner is no longer waiting in the queue")
            ticket.status = "assigned"

    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


def resolve(
    session: Session, ticket_id: str, code: str, note: str, clock: Clock, actor: str
) -> Ticket:
    """No closure without a reason. The interface gate exists because this raises."""
    policy.validate_resolution(code)
    now = clock.now()
    ticket = _get(session, ticket_id)
    policy.assert_transition(ticket.status, "resolved")
    _resume_clock(session, ticket, now)
    old_status = ticket.status
    ticket.status = "resolved"
    ticket.resolution_code = code
    ticket.resolution_note = note
    ticket.resolved_at = now
    ticket.major = False
    ticket.hold_reason = ""
    session.add(ticket)
    record(session, ticket_id, at=now, actor=actor, actor_kind="person",
           field="status", old=old_status, new="resolved",
           reason=f"closed as {policy.RESOLUTION_CODES[code].lower()}")
    if policy.requires_problem_record(code):
        record(session, ticket_id, at=now, actor="Relay", actor_kind="system",
               field="problem", old=ticket.problem_id, new=ticket.problem_id,
               reason="a workaround leaves the cause in place, so this wants a problem record")
    session.commit()
    session.refresh(ticket)
    return ticket


def reopen(session: Session, ticket_id: str, clock: Clock, actor: str) -> Ticket:
    now = clock.now()
    ticket = _get(session, ticket_id)
    policy.assert_transition(ticket.status, "in_progress")
    old_code = ticket.resolution_code
    ticket.status = "in_progress"
    ticket.resolution_code = ""
    ticket.resolution_note = ""
    ticket.resolved_at = None
    ticket.reopened_count += 1
    session.add(ticket)
    record(session, ticket_id, at=now, actor=actor, actor_kind="person",
           field="status", old="resolved", new="in_progress",
           reason=f"reopened, previously closed as {policy.RESOLUTION_CODES.get(old_code, 'unknown').lower()}")
    session.commit()
    session.refresh(ticket)
    return ticket


def set_major(session: Session, ticket_id: str, on: bool, clock: Clock, actor: str) -> Ticket:
    now = clock.now()
    ticket = _get(session, ticket_id)
    if ticket.kind != policy.INCIDENT:
        raise ValueError("only incidents can be major incidents")
    old = ticket.major
    ticket.major = on
    session.add(ticket)
    record(session, ticket_id, at=now, actor=actor, actor_kind="person",
           field="major", old=old, new=on,
           reason="declared a major incident" if on else "stood down")
    session.commit()
    session.refresh(ticket)
    return ticket


def hold(session: Session, ticket_id: str, reason: str, clock: Clock, actor: str) -> Ticket:
    now = clock.now()
    ticket = _get(session, ticket_id)
    policy.assert_transition(ticket.status, "on_hold")
    old = ticket.status
    ticket.status = "on_hold"
    ticket.hold_reason = reason
    ticket.paused_at = now
    session.add(ticket)
    record(session, ticket_id, at=now, actor=actor, actor_kind="person",
           field="status", old=old, new="on_hold",
           reason=f"{reason}; the fix clock pauses, the reply clock does not")
    session.commit()
    session.refresh(ticket)
    return ticket


def unhold(session: Session, ticket_id: str, clock: Clock, actor: str) -> Ticket:
    now = clock.now()
    ticket = _get(session, ticket_id)
    policy.assert_transition(ticket.status, "in_progress")
    _resume_clock(session, ticket, now)
    was = ticket.hold_reason
    ticket.status = "in_progress"
    ticket.hold_reason = ""
    session.add(ticket)
    record(session, ticket_id, at=now, actor=actor, actor_kind="person",
           field="status", old="on_hold", new="in_progress",
           reason=f"no longer {was.lower()}" if was else "taken off hold")
    session.commit()
    session.refresh(ticket)
    return ticket


def reclassify(
    session: Session,
    ticket_id: str,
    *,
    impact: Optional[str] = None,
    urgency: Optional[str] = None,
    category: Optional[str] = None,
    team: Optional[str] = None,
    clock: Clock,
    actor: str,
    actor_kind: str = "person",
    reason: str = "",
) -> Ticket:
    """Where the judgment layer will write, and where a human override is logged.

    The interesting audit rows later are the ones that read "judgment suggested
    network, a person changed it to erp_apps" — which is only possible because
    both values land here with an actor.
    """
    now = clock.now()
    ticket = _get(session, ticket_id)
    changes = {"impact": impact, "urgency": urgency, "category": category, "team_key": team}
    matrix = load_matrix(session)
    before = policy.derive_priority(matrix, ticket.impact, ticket.urgency).value

    for field, new in changes.items():
        if new is None:
            continue
        old = getattr(ticket, field)
        if old == new:
            continue
        setattr(ticket, field, new)
        record(session, ticket_id, at=now, actor=actor, actor_kind=actor_kind,
               field=field, old=old, new=new, reason=reason or "reclassified by hand")

    session.add(ticket)
    after_decision = policy.derive_priority(matrix, ticket.impact, ticket.urgency)
    if after_decision.value != before:
        record(session, ticket_id, at=now, actor="Relay", actor_kind="system",
               field="priority", old=before, new=after_decision.value,
               reason=after_decision.reason)
    session.commit()
    session.refresh(ticket)
    return ticket


def add_message(
    session: Session, ticket_id: str, author: str, body: str, visibility: str, clock: Clock
) -> Message:
    now = clock.now()
    ticket = _get(session, ticket_id)
    message = Message(
        ticket_id=ticket_id, at=now, author=author, visibility=visibility, body=body
    )
    session.add(message)
    if visibility == "public" and ticket.first_response_at is None:
        ticket.first_response_at = now
        session.add(ticket)
        record(session, ticket_id, at=now, actor=author, actor_kind="person",
               field="first_response_at", old=None, new=now.isoformat(),
               reason="first reply to the requester stops the response clock")
    session.commit()
    session.refresh(message)
    return message
