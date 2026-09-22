"""Tables.

Two things are deliberately absent from ``Ticket``:

* **priority** — derived from the matrix on every read, never stored, so a
  human edit and a judgment can never silently disagree.
* **due dates** — computed from ``opened_at`` plus the matching service level
  rule, so changing a target in configuration does not leave stale promises
  scattered through the data.

``Event`` is not optional. It carries actor, field, old value, new value and
reason on every change, which is the data that makes the judgment layer
evaluable once it lands.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Team(SQLModel, table=True):
    """A routing target: the department work is handed to.

    ``domain`` is the sentence a judgment reads to decide whether a ticket
    belongs here, so it is prose rather than a label. ``skills`` is the same
    ground in keywords, for the people underneath.
    """

    key: str = Field(primary_key=True)
    name: str
    domain: str
    position: int = 0
    skills: str = ""


class Technician(SQLModel, table=True):
    """One person on a team.

    ``skills`` and ``capacity`` exist because "who on this team" stops being
    arithmetic the moment two people on the same team are good at different
    things. Capacity is how many open tickets this person is expected to
    carry, which is what turns a raw count into load.
    """

    id: str = Field(primary_key=True)
    name: str
    team_key: str = Field(foreign_key="team.key", index=True)
    tier: str = "Second line"
    on_leave: bool = False
    skills: str = ""
    capacity: int = 8
    location: str = ""


class Ticket(SQLModel, table=True):
    id: str = Field(primary_key=True)
    kind: str = Field(index=True)           # incident | request
    subject: str
    body: str = ""
    requester: str = ""
    department: str = ""

    impact: str                              # organization | department | team | individual
    urgency: str                             # low | medium | high | critical
    category: str = ""

    team_key: Optional[str] = Field(default=None, foreign_key="team.key", index=True)
    assignee_id: Optional[str] = Field(default=None, foreign_key="technician.id", index=True)

    status: str = Field(default="new", index=True)
    major: bool = False
    hold_reason: str = ""
    problem_id: Optional[str] = None
    service: str = ""
    affected_ci: str = ""

    resolution_code: str = ""
    resolution_note: str = ""
    reopened_count: int = 0

    # The ticket this one turned out to be the same thing as. Two different
    # meanings live here, told apart by the status: a closed ticket pointing at
    # a parent was the same request raised twice, while an *open* one pointing
    # at a parent is a second reporter of the same fault — still open because
    # that person still needs telling when it is fixed. Instances of a known
    # problem use ``problem_id`` instead; see relay/duplicates.py.
    duplicate_of: Optional[str] = Field(default=None, foreign_key="ticket.id", index=True)

    opened_at: datetime = Field(default_factory=_now)
    first_response_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    paused_seconds: int = 0
    paused_at: Optional[datetime] = None


class Event(SQLModel, table=True):
    """The audit trail. One row per change, and it never gets rewritten."""

    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: str = Field(foreign_key="ticket.id", index=True)
    at: datetime = Field(default_factory=_now)
    actor: str = "system"
    actor_kind: str = "system"               # person | system | judgment
    field: str = ""
    old_value: str = ""
    new_value: str = ""
    reason: str = ""


class Message(SQLModel, table=True):
    """Conversation. ``visibility`` is why the guardrail has something to screen."""

    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: str = Field(foreign_key="ticket.id", index=True)
    at: datetime = Field(default_factory=_now)
    author: str = ""
    visibility: str = "public"               # public | internal | draft
    body: str = ""
    review_state: str = ""                   # "", clear, needs_review, blocked
    review_reason: str = ""


class Sentiment(SQLModel, table=True):
    """How satisfied the requester sounded, the last time anyone read the thread.

    **This is the one derived value Relay stores**, and the exception is
    deliberate. Priority is re-read from the matrix on every request because
    the matrix is a table lookup and costs nothing. Sentiment costs a model
    call, so deriving it per request would mean one call per ticket per page
    load — a queue column would cost a hundred calls a refresh.

    What makes the exception safe is that the row carries what it was computed
    from. ``last_message_id`` and ``message_count`` pin it to a point in the
    conversation, so anything reading it can tell whether the thread has moved
    since — a stored number that knows when it is out of date, rather than one
    that quietly goes stale. ``engine`` and ``model`` record who said it, the
    same way an ``Event`` records an actor.
    """

    ticket_id: str = Field(primary_key=True, foreign_key="ticket.id")
    score: float                             # 1.00 to 5.00, between levels allowed
    level: int                               # the nearest whole level, 1 to 5
    probabilities: str = ""                  # JSON, keyed "1".."5"
    confidence: Optional[float] = None
    engine: str = "jev"                      # jev | ai | lexicon
    model: str = ""
    note: str = ""
    at: datetime = Field(default_factory=_now)
    last_message_id: Optional[int] = None    # what the thread looked like when it was read
    message_count: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0


class Escalation(SQLModel, table=True):
    """The predicted chance this ticket escalates, and what it was predicted from.

    Stored for the same reason ``Sentiment`` is — a model call per ticket per
    page load is not a queue column — but it goes stale differently, and the
    difference matters. A sentiment reading is only wrong once somebody says
    something new. A prediction about the future is wrong as soon as *time*
    passes: the same ticket at 30% of its target and at 90% is not the same
    ticket. So this row keeps the burn it saw as well as the message count, and
    anything reading it can say which of the two has moved.
    """

    ticket_id: str = Field(primary_key=True, foreign_key="ticket.id")
    probability: float                       # 0 to 1, the Noul's own answer
    band: str = "quiet"                      # quiet | watch | likely, from policy
    engine: str = "jev"                      # jev | ai | sla
    model: str = ""
    note: str = ""
    at: datetime = Field(default_factory=_now)
    burn: float = 0.0                        # share of target gone when it was asked
    last_message_id: Optional[int] = None
    message_count: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0


class MatrixCell(SQLModel, table=True):
    """Configuration, editable at runtime. Reading a ticket's priority means
    reading these four by four rows."""

    impact: str = Field(primary_key=True)
    urgency: str = Field(primary_key=True)
    priority: str


class SlaRuleRow(SQLModel, table=True):
    order: int = Field(primary_key=True)
    priority: str
    response_minutes: int
    resolution_minutes: int
    calendar: str = "always"


class Article(SQLModel, table=True):
    id: str = Field(primary_key=True)
    title: str
    body: str = ""
    owner: str = ""
    reviewed_note: str = ""
    stale: bool = False
    deflected: int = 0
    state: str = "Live"
    keywords: str = ""


class Problem(SQLModel, table=True):
    id: str = Field(primary_key=True)
    title: str
    state: str = "Digging"
    since: str = ""
    root_cause: str = ""
    workaround: str = ""
    change_id: str = ""
    owner: str = ""
    severity: str = "warn"


class Change(SQLModel, table=True):
    id: str = Field(primary_key=True)
    title: str
    risk: str = "mute"                       # ok | hot | crit | mute
    window: str = ""
    day_index: int = 0
    day_name: str = ""
    day_number: int = 0
    collision: str = ""
    awaiting_board: bool = False
    frozen_day: bool = False
    release_id: str = ""


class Release(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    window: str = ""
    stage: int = 0
    risk: str = "ok"
    owner: str = ""
    note: str = ""


class CatalogItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    group_name: str = ""
    group_note: str = ""
    name: str = ""
    blurb: str = ""
    turnaround: str = ""
    approval: str = ""
    position: int = 0


class HistoricTicket(SQLModel, table=True):
    """A closed ticket imported from an outside dataset (see ``history``).

    Kept apart from ``Ticket`` on purpose: these never enter the live queue,
    never run a clock, and never change after import. Unlike ``Ticket`` this
    table *does* store priority — ``recorded_priority`` is what the source
    decided at the time, a fact to report on rather than a rule to re-apply.
    """

    id: str = Field(primary_key=True)          # "<source>:<source id>"
    source: str = Field(index=True)            # abc_tech | gcc_desk
    source_id: str
    kind: str = Field(index=True)              # incident | request
    subject: str = ""                          # composed from fields; neither source has text
    category: str = ""
    service: str = ""
    affected_ci: str = ""
    team: str = Field(default="", index=True)
    assignee: str = ""
    channel: str = ""
    country: str = ""
    support_level: str = ""

    impact: Optional[str] = None               # Relay's vocabulary, when the source had it
    urgency: Optional[str] = None
    recorded_priority: Optional[str] = Field(default=None, index=True)
    source_priority: str = ""                  # the raw value, before mapping
    source_status: str = ""
    status: str = ""
    closure: str = ""
    kb_article: str = ""

    opened_at: datetime = Field(index=True)
    first_response_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    reopened_at: Optional[datetime] = None

    reassignments: Optional[int] = None
    interactions: Optional[int] = None
    related_incidents: int = 0
    related_changes: int = 0
    satisfaction: str = ""                     # satisfied | neutral | dissatisfied
    response_target_minutes: Optional[int] = None
    resolution_target_minutes: Optional[int] = None
    response_met: Optional[bool] = None        # recomputed from the stamps, not copied
    resolution_met: Optional[bool] = None
    resolution_hours: Optional[float] = None
