"""HTTP surface.

Thin on purpose: parse, call ``service``, return. No decisions are made here.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from . import policy, service
from .clock import SystemClock, ensure_utc
from .db import create_all, engine, get_session
from .models import (
    Article,
    CatalogItem,
    Change,
    Problem,
    Release,
    SlaRuleRow,
    Team,
    Technician,
    Ticket,
)
from .seed import seed
from . import (deflection as deflection_module, duplicates as duplicates_module,
               escalation as escalation_module, history_report, routing,
               sentiment as sentiment_module, showcase, traditional)

clock = SystemClock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create the tables and lay down the fixture data, unless a test owns the
    database already."""
    if not os.environ.get("RELAY_SKIP_STARTUP"):
        create_all()
        with Session(engine) as session:
            seed(session, clock)
    yield


app = FastAPI(
    title="Relay", version="0.1.0",
    description="An ITSM service desk", lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:4173", "http://127.0.0.1:4173",
        "http://localhost:8010", "http://127.0.0.1:8010",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


def actor(x_actor: Optional[str] = Header(default=None)) -> str:
    return x_actor or "A. Okonkwo"


# ---------------------------------------------------------------- payloads

class ClaimIn(BaseModel):
    technician_id: str = "ao"


class ResolveIn(BaseModel):
    code: str
    note: str = ""


class MajorIn(BaseModel):
    on: bool = True


class HoldIn(BaseModel):
    reason: str = "Waiting on the caller"


class ClassifyIn(BaseModel):
    impact: Optional[str] = None
    urgency: Optional[str] = None
    category: Optional[str] = None
    team: Optional[str] = None
    reason: str = ""
    actor_kind: str = "person"


class MessageIn(BaseModel):
    body: str
    visibility: str = Field(default="public", pattern="^(public|internal|draft)$")


class ShowcaseIn(BaseModel):
    case: str = "kind"
    text: str = ""
    lanes: list[str] = []                  # empty means every lane the use case has
    form: dict[str, str] = {}              # what the caller picked, for the matrix lane


class MatrixIn(BaseModel):
    matrix: dict[str, dict[str, str]]


class TeamIn(BaseModel):
    key: Optional[str] = None               # required when creating
    name: Optional[str] = None
    domain: Optional[str] = None
    skills: Optional[str] = None
    position: Optional[int] = None


class PersonIn(BaseModel):
    id: Optional[str] = None                # required when creating
    name: Optional[str] = None
    team: Optional[str] = None
    tier: Optional[str] = None
    skills: Optional[str] = None
    location: Optional[str] = None
    capacity: Optional[int] = None
    on_leave: Optional[bool] = None


class RouteIn(BaseModel):
    engine: str = "jev"                     # jev | ai | rules
    apply: bool = False


class SentimentIn(BaseModel):
    engine: str = "jev"                     # jev | ai | lexicon


class EscalationIn(BaseModel):
    engine: str = "jev"                     # jev | ai | sla


class LinkIn(BaseModel):
    other: str                              # the ticket or problem it matches
    relation: str = Field(pattern="^(same_request|same_fault|known_problem)$")
    reason: str = ""
    actor_kind: str = "judgment"


class TicketIn(BaseModel):
    subject: str
    body: str = ""
    requester: str = ""
    department: str = ""
    kind: str = Field(default="incident", pattern="^(incident|request)$")
    impact: Optional[str] = None            # absent means the form default
    urgency: Optional[str] = None


# ---------------------------------------------------------------- meta

@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "now": clock.now()}


@app.get("/api/meta")
def meta(session: Session = Depends(get_session)) -> dict:
    teams = session.exec(select(Team).order_by(Team.position)).all()
    techs = session.exec(select(Technician)).all()
    rules = session.exec(select(SlaRuleRow).order_by(SlaRuleRow.order)).all()
    return {
        "now": clock.now(),
        "teams": [{"key": t.key, "name": t.name, "domain": t.domain} for t in teams],
        "technicians": [
            {"id": t.id, "name": t.name, "team": t.team_key, "tier": t.tier} for t in techs
        ],
        "matrix": service.load_matrix(session),
        "sla_rules": [
            {
                "order": r.order, "priority": r.priority, "calendar": r.calendar,
                "response_minutes": r.response_minutes,
                "resolution_minutes": r.resolution_minutes,
            }
            for r in rules
        ],
        "impacts": list(policy.IMPACTS),
        "urgencies": list(policy.URGENCIES),
        "priorities": list(policy.PRIORITIES),
        "statuses": list(policy.TRANSITIONS),
        "transitions": {k: list(v) for k, v in policy.TRANSITIONS.items()},
        "resolution_codes": [
            {"code": c, "label": l, "needs_problem": policy.requires_problem_record(c)}
            for c, l in policy.RESOLUTION_CODES.items()
        ],
        "hold_reasons": [
            "Waiting on the caller", "Waiting on a vendor",
            "Waiting on a change", "Outside working hours",
        ],
    }


# ---------------------------------------------------------------- tickets

@app.get("/api/tickets")
def list_tickets(
    kind: Optional[str] = Query(default=None, pattern="^(incident|request)$"),
    session: Session = Depends(get_session),
) -> list[dict]:
    return service.list_tickets(session, clock.now(), kind)


@app.post("/api/tickets", status_code=201)
def create_ticket(payload: TicketIn, session: Session = Depends(get_session)) -> dict:
    """A new ticket, as it arrives: words and a requester, nothing routed.

    It lands with no department and no owner on purpose — that is the state
    ``POST /api/tickets/{id}/route`` exists to resolve.
    """
    ticket = _act(service.create_ticket, session, clock=clock, **payload.model_dump())
    return _view(session, ticket)


@app.get("/api/tickets/{ticket_id}")
def get_ticket(ticket_id: str, session: Session = Depends(get_session)) -> dict:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(404, f"no ticket {ticket_id}")
    view = service.ticket_view(session, ticket, clock.now())
    # The list view carries a lean sentiment record, because a hundred-row queue
    # does not need every distribution. One ticket does: its rail shows the
    # spread, the reasoning and what the reading cost.
    view["sentiment"] = sentiment_module.stored(session, ticket) or view["sentiment"]
    view["escalation"] = escalation_module.stored(session, ticket, view) or view["escalation"]
    view["linked"] = duplicates_module.children(session, ticket_id)
    view["messages"] = [
        {
            "id": m.id, "at": ensure_utc(m.at), "author": m.author, "visibility": m.visibility,
            "body": m.body, "review_state": m.review_state, "review_reason": m.review_reason,
        }
        for m in service.messages_for(session, ticket_id)
    ]
    view["events"] = [
        {
            "id": e.id, "at": ensure_utc(e.at), "actor": e.actor, "actor_kind": e.actor_kind,
            "field": e.field, "old": e.old_value, "new": e.new_value, "reason": e.reason,
        }
        for e in service.events_for(session, ticket_id)
    ]
    return view


def _act(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _view(session: Session, ticket: Ticket) -> dict:
    return service.ticket_view(session, ticket, clock.now())


@app.post("/api/tickets/{ticket_id}/claim")
def claim(ticket_id: str, payload: ClaimIn, session: Session = Depends(get_session),
          who: str = Depends(actor)) -> dict:
    return _view(session, _act(service.claim, session, ticket_id, payload.technician_id, clock, who))


@app.post("/api/tickets/{ticket_id}/unassign")
def unassign(ticket_id: str, session: Session = Depends(get_session),
             who: str = Depends(actor)) -> dict:
    return _view(session, _act(service.unassign, session, ticket_id, clock, who))


@app.post("/api/tickets/{ticket_id}/auto-route")
def auto_route(ticket_id: str, session: Session = Depends(get_session)) -> dict:
    return _view(session, _act(service.auto_route, session, ticket_id, clock))


@app.post("/api/tickets/{ticket_id}/resolve")
def resolve(ticket_id: str, payload: ResolveIn, session: Session = Depends(get_session),
            who: str = Depends(actor)) -> dict:
    return _view(session, _act(service.resolve, session, ticket_id, payload.code, payload.note, clock, who))


@app.post("/api/tickets/{ticket_id}/reopen")
def reopen(ticket_id: str, session: Session = Depends(get_session),
           who: str = Depends(actor)) -> dict:
    return _view(session, _act(service.reopen, session, ticket_id, clock, who))


@app.post("/api/tickets/{ticket_id}/major")
def major(ticket_id: str, payload: MajorIn, session: Session = Depends(get_session),
          who: str = Depends(actor)) -> dict:
    return _view(session, _act(service.set_major, session, ticket_id, payload.on, clock, who))


@app.post("/api/tickets/{ticket_id}/hold")
def hold(ticket_id: str, payload: HoldIn, session: Session = Depends(get_session),
         who: str = Depends(actor)) -> dict:
    return _view(session, _act(service.hold, session, ticket_id, payload.reason, clock, who))


@app.post("/api/tickets/{ticket_id}/unhold")
def unhold(ticket_id: str, session: Session = Depends(get_session),
           who: str = Depends(actor)) -> dict:
    return _view(session, _act(service.unhold, session, ticket_id, clock, who))


@app.post("/api/tickets/{ticket_id}/classify")
def classify(ticket_id: str, payload: ClassifyIn, session: Session = Depends(get_session),
             who: str = Depends(actor)) -> dict:
    return _view(session, _act(
        service.reclassify, session, ticket_id,
        impact=payload.impact, urgency=payload.urgency,
        category=payload.category, team=payload.team,
        clock=clock, actor=who, actor_kind=payload.actor_kind, reason=payload.reason,
    ))


@app.post("/api/tickets/{ticket_id}/messages")
def post_message(ticket_id: str, payload: MessageIn, session: Session = Depends(get_session),
                 who: str = Depends(actor)) -> dict:
    message = _act(service.add_message, session, ticket_id, who, payload.body, payload.visibility, clock)
    return {
        "id": message.id, "at": message.at, "author": message.author,
        "visibility": message.visibility, "body": message.body,
        "review_state": message.review_state, "review_reason": message.review_reason,
    }


# ---------------------------------------------------------------- configuration

@app.get("/api/config/matrix")
def get_matrix(session: Session = Depends(get_session)) -> dict:
    return service.load_matrix(session)


@app.put("/api/config/matrix")
def put_matrix(payload: MatrixIn, session: Session = Depends(get_session)) -> dict:
    _act(service.save_matrix, session, payload.matrix)
    return service.load_matrix(session)


# ---------------------------------------------------------------- reference data

@app.get("/api/problems")
def problems(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(select(Problem)).all()
    tickets = session.exec(select(Ticket)).all()
    out = []
    for p in rows:
        linked = [t.id for t in tickets if t.problem_id == p.id]
        out.append({
            "id": p.id, "title": p.title, "state": p.state, "since": p.since,
            "root_cause": p.root_cause, "workaround": p.workaround,
            "change_id": p.change_id, "owner": p.owner, "severity": p.severity,
            "linked_tickets": linked, "linked_count": max(len(linked), 0),
        })
    out.sort(key=lambda p: -p["linked_count"])
    return out


@app.get("/api/changes")
def changes(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(select(Change)).all()
    return [
        {
            "id": c.id, "title": c.title, "risk": c.risk, "window": c.window,
            "day_index": c.day_index, "day_name": c.day_name, "day_number": c.day_number,
            "collision": c.collision, "awaiting_board": c.awaiting_board,
            "release_id": c.release_id,
        }
        for c in rows
    ]


@app.get("/api/releases")
def releases(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(select(Release)).all()
    all_changes = session.exec(select(Change)).all()
    return [
        {
            "id": r.id, "name": r.name, "window": r.window, "stage": r.stage,
            "risk": r.risk, "owner": r.owner, "note": r.note,
            "changes": [c.id for c in all_changes if c.release_id == r.id],
        }
        for r in sorted(rows, key=lambda r: r.stage)
    ]


@app.get("/api/articles")
def articles(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(select(Article)).all()
    return [
        {
            "id": a.id, "title": a.title, "body": a.body, "owner": a.owner,
            "reviewed_note": a.reviewed_note, "stale": a.stale,
            "deflected": a.deflected, "state": a.state,
        }
        for a in sorted(rows, key=lambda a: -a.deflected)
    ]


@app.get("/api/catalog")
def catalog(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(select(CatalogItem).order_by(CatalogItem.position)).all()
    groups: list[dict] = []
    for item in rows:
        if not groups or groups[-1]["name"] != item.group_name:
            groups.append({"name": item.group_name, "note": item.group_note, "items": []})
        groups[-1]["items"].append({
            "name": item.name, "blurb": item.blurb,
            "turnaround": item.turnaround, "approval": item.approval,
        })
    return groups


@app.get("/api/search")
def search(q: str = "", session: Session = Depends(get_session)) -> list[dict]:
    """What the staff portal shows before a ticket exists.

    Plain keyword overlap, and deliberately so: this is exactly the spot where a
    judgment model earns its place later, and leaving it dumb makes the
    before-and-after measurable.
    """
    return traditional.keyword_overlap(q, [a.model_dump() for a in session.exec(select(Article)).all()])


@app.get("/api/reports/summary")
def reports(session: Session = Depends(get_session)) -> dict:
    now = clock.now()
    views = service.list_tickets(session, now)
    live = [v for v in views if v["status"] not in ("resolved", "closed", "cancelled", "spam")]
    breached = [v for v in live if v["sla"]["breached"]]
    buckets = [("under 4h", 0, 4), ("4 to 24h", 4, 24), ("1 to 2d", 24, 48),
               ("2 to 5d", 48, 120), ("5 to 10d", 120, 240), ("over 10d", 240, 10_000)]
    ages = []
    for label, lo, hi in buckets:
        n = 0
        for v in live:
            hours = (now - v["opened_at"]).total_seconds() / 3600
            if lo <= hours < hi:
                n += 1
        ages.append({"label": label, "count": n})

    by_team: dict[str, dict] = {}
    for v in views:
        key = v["team"] or "unassigned"
        row = by_team.setdefault(key, {"team": key, "total": 0, "breached": 0, "worst_burn": 0.0})
        row["total"] += 1
        if v["sla"]["breached"]:
            row["breached"] += 1
        row["worst_burn"] = max(row["worst_burn"], v["sla"]["burn"])
    for row in by_team.values():
        row["attainment"] = round(100.0 * (1 - row["breached"] / row["total"]), 1) if row["total"] else 100.0

    return {
        "open_total": len(live),
        "breached_total": len(breached),
        "major_total": len([v for v in live if v["major"]]),
        "unassigned_total": len([v for v in live if not v["assignee"]]),
        "attainment": round(100.0 * (1 - len(breached) / len(live)), 1) if live else 100.0,
        "age_buckets": ages,
        "by_team": sorted(by_team.values(), key=lambda r: r["attainment"]),
        "by_priority": [
            {
                "priority": p,
                "count": len([v for v in live if v["priority"] == p]),
                "worst_burn": round(max([v["sla"]["burn"] for v in live if v["priority"] == p], default=0.0), 4),
            }
            for p in policy.PRIORITIES
        ],
    }


# ---------------------------------------------------------------- sentiment

@app.post("/api/tickets/{ticket_id}/sentiment")
def read_sentiment(ticket_id: str, payload: SentimentIn,
                   session: Session = Depends(get_session)) -> dict:
    """Score how the requester sounds, from the whole conversation; see relay.sentiment.

    Saves the reading with the message it last read, so the interface can tell
    you when the thread has moved on since.
    """
    return _act(sentiment_module.read, session, ticket_id, clock, payload.engine)


@app.get("/api/sentiment")
def sentiment_summary(session: Session = Depends(get_session)) -> dict:
    """The desk's satisfaction across open tickets, and who holds the unhappiest."""
    return sentiment_module.summary(session, clock.now())


# ---------------------------------------------------------------- deflection

@app.get("/api/deflect")
def deflect(q: str = "", engine: str = Query(default="jev", pattern="^(jev|ai|keywords)$"),
            session: Session = Depends(get_session)) -> dict:
    """Would anything already written answer this, before a ticket exists?

    The judgment counterpart to ``GET /api/search``, which stays keyword-only on
    purpose so the difference between them is measurable. See relay.deflection.
    """
    return _act(deflection_module.look, session, q, engine)


@app.post("/api/articles/{article_id}/deflected")
def mark_deflected(article_id: str, session: Session = Depends(get_session)) -> dict:
    """Somebody read it instead of raising a ticket. Counted only when they say so."""
    return _act(deflection_module.took_it, session, article_id)


@app.get("/api/deflect/backtest")
def deflection_backtest(engine: str = Query(default="jev", pattern="^(jev|ai|keywords)$"),
                        limit: int = Query(default=20, ge=1, le=60),
                        session: Session = Depends(get_session)) -> dict:
    """How many open tickets the knowledge base already answers."""
    return _act(deflection_module.would_have_helped, session, clock.now(), engine, limit)


# ---------------------------------------------------------------- duplicates

@app.get("/api/tickets/{ticket_id}/duplicates")
def find_duplicates(ticket_id: str, engine: str = Query(default="jev", pattern="^(jev|ai|similar)$"),
                    session: Session = Depends(get_session)) -> dict:
    """Has the desk got this already? See relay.duplicates.

    Code shortlists the handful worth comparing; the engine says what the
    relationship is. Writes nothing — linking is a separate, deliberate call.
    """
    return _act(duplicates_module.look, session, ticket_id, clock.now(), engine)


@app.post("/api/tickets/{ticket_id}/link")
def link_duplicate(ticket_id: str, payload: LinkIn, session: Session = Depends(get_session),
                   who: str = Depends(actor)) -> dict:
    """Act on a finding: close it, link it to a parent, or attach it to a problem."""
    name = "Relay judgment" if payload.actor_kind == "judgment" else who
    return _act(duplicates_module.link, session, ticket_id, other_id=payload.other,
                relation=payload.relation, clock=clock, actor=name,
                actor_kind=payload.actor_kind, reason=payload.reason)


@app.get("/api/duplicates")
def duplicate_summary(session: Session = Depends(get_session)) -> dict:
    """How much of the queue is one thing reported several times."""
    return duplicates_module.summary(session, clock.now())


# ---------------------------------------------------------------- escalation

@app.post("/api/tickets/{ticket_id}/escalation")
def predict_escalation(ticket_id: str, payload: EscalationIn,
                       session: Session = Depends(get_session)) -> dict:
    """How likely this ticket is to escalate; see relay.escalation.

    Reads the conversation *and* the ticket's state — burn, reopens, bounces,
    and how the requester sounds — because a human predicting a blow-up uses
    all of it. The probability is the model's; the line it is judged against is
    ``policy.ESCALATION_WATCH``.
    """
    return _act(escalation_module.predict, session, ticket_id, clock, payload.engine)


@app.get("/api/escalation")
def escalation_summary(session: Session = Depends(get_session)) -> dict:
    """What is about to go wrong across the open queue."""
    return escalation_module.summary(session, clock.now())


# ---------------------------------------------------------------- the roster

@app.get("/api/people")
def people(session: Session = Depends(get_session)) -> dict:
    """Departments, who is on them, and what each person is carrying right now.

    Counted from live tickets on every request rather than stored, which is why
    editing the priority matrix moves the bars on this screen too.
    """
    return service.workforce(session, clock.now())


@app.post("/api/teams")
def create_team(payload: TeamIn, session: Session = Depends(get_session)) -> dict:
    if not payload.key:
        raise HTTPException(status_code=422, detail="a new department needs a key")
    team = _act(service.save_team, session, payload.key,
                payload.model_dump(exclude_none=True), creating=True)
    return {"key": team.key, "name": team.name, "domain": team.domain}


@app.patch("/api/teams/{key}")
def update_team(key: str, payload: TeamIn, session: Session = Depends(get_session)) -> dict:
    team = _act(service.save_team, session, key, payload.model_dump(exclude_none=True), creating=False)
    return {"key": team.key, "name": team.name, "domain": team.domain}


@app.delete("/api/teams/{key}")
def remove_team(key: str, session: Session = Depends(get_session)) -> dict:
    _act(service.delete_team, session, key)
    return {"deleted": key}


@app.post("/api/people")
def create_person(payload: PersonIn, session: Session = Depends(get_session)) -> dict:
    if not payload.id:
        raise HTTPException(status_code=422, detail="a new person needs an id")
    person = _act(service.save_person, session, payload.id,
                  payload.model_dump(exclude_none=True), creating=True)
    return {"id": person.id, "name": person.name, "team": person.team_key}


@app.patch("/api/people/{person_id}")
def update_person(person_id: str, payload: PersonIn, session: Session = Depends(get_session)) -> dict:
    person = _act(service.save_person, session, person_id,
                  payload.model_dump(exclude_none=True), creating=False)
    return {"id": person.id, "name": person.name, "team": person.team_key}


@app.delete("/api/people/{person_id}")
def remove_person(person_id: str, session: Session = Depends(get_session),
                  who: str = Depends(actor)) -> dict:
    handed_back = _act(service.delete_person, session, person_id, clock, who)
    return {"deleted": person_id, "handed_back": handed_back}


# ---------------------------------------------------------------- routing

@app.post("/api/tickets/{ticket_id}/route")
def route_ticket(ticket_id: str, payload: RouteIn, session: Session = Depends(get_session)) -> dict:
    """Both halves of a routing decision for one live ticket; see relay.routing.

    Suggests by default. With ``apply`` it writes the department and the owner,
    logged with the engine as the actor and its own reason.
    """
    return _act(routing.route, session, ticket_id, clock, payload.engine, payload.apply)


# ---------------------------------------------------------------- showcase

def _showcase_ctx(session: Session, case: str = "", text: str = "") -> dict:
    """Everything a lane might read, live from the database.

    Most of it is cheap and always included. A use case that declares it
    ``needs`` something builds it on demand — the duplicate lanes cannot
    compare against anything until code has shortlisted the queue for whatever
    was typed, which is the same shortlist a real ticket gets.
    """
    ctx = {
        "matrix": service.load_matrix(session),
        "rules": service.load_sla_rules(session),
        # the routing use cases build their options out of these, so a
        # department added under Oversight is an option here immediately
        "teams": service.teams_for_judgment(session),
        "roster": service.roster_for_judgment(session),
    }
    use = showcase.USE_CASES.get(case)
    if use and text.strip():
        if "candidates" in use.needs:
            ctx["candidates"] = duplicates_module.shortlist_for(session, text, clock.now())
        if "articles" in use.needs:
            ctx["articles"], ctx["held_back"] = deflection_module.shortlist(session, text)
    return ctx


@app.get("/api/showcase/cases")
def showcase_cases(session: Session = Depends(get_session)) -> list[dict]:
    return showcase.cases(_showcase_ctx(session))


@app.post("/api/showcase/run")
def run_showcase(payload: ShowcaseIn, session: Session = Depends(get_session)) -> dict:
    """The same words through Jev and through an LLM call, measured; see relay.showcase."""
    return _act(showcase.run, payload.case, payload.text, payload.lanes,
                {**_showcase_ctx(session, payload.case, payload.text), "form": payload.form})


# ---------------------------------------------------------------- history

@app.get("/api/history/summary")
def history_summary(session: Session = Depends(get_session)) -> dict:
    """Closed tickets imported from outside datasets; see relay.import_history."""
    return history_report.summary(session)


# ---------------------------------------------------------------- built frontend

_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="app")
