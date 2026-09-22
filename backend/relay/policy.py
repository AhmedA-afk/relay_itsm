"""Every decision the desk makes, as pure functions.

Rules this module holds to, because the whole design depends on them:

* No I/O. No database, no network, no model call, no ``datetime.now()``.
  The current time arrives as an argument.
* Priority is **derived**, never stored. It is read out of the matrix every
  time impact or urgency changes, which is why a ticket can always show the
  cell it came from.
* Every decision returns its reason alongside its answer, so the audit log can
  record *why* without the caller inventing an explanation.

When the judgment layer lands, it supplies impact, urgency, category and team.
None of the arithmetic below moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping, Sequence

# ---------------------------------------------------------------- vocabulary

IMPACTS = ("organization", "department", "team", "individual")
URGENCIES = ("low", "medium", "high", "critical")
PRIORITIES = ("P1", "P2", "P3", "P4")

INCIDENT, REQUEST = "incident", "request"
PREFIXES = {INCIDENT: "INC", REQUEST: "REQ"}


def next_id(kind: str, existing: Iterable[str]) -> str:
    """The next id for a kind: one past the highest already minted.

    Which prefix to use is the textbook example of a decision that needs no
    judgment at all — it follows from the kind, and the kind is the thing worth
    reading. Pure, so the numbering is testable without a database.
    """
    prefix = PREFIXES.get(kind)
    if prefix is None:
        raise ValueError(f"unknown kind {kind!r}")
    used = [
        int(tail) for i in existing
        if i.startswith(f"{prefix}-") and (tail := i[len(prefix) + 1:]).isdigit()
    ]
    return f"{prefix}-{(max(used) + 1) if used else 1001}"

# new -> assigned -> in_progress -> resolved -> closed, plus two side exits
TRANSITIONS: Mapping[str, tuple[str, ...]] = {
    "new": ("assigned", "in_progress", "on_hold", "cancelled", "spam"),
    "assigned": ("in_progress", "on_hold", "new", "cancelled"),
    "in_progress": ("on_hold", "resolved", "assigned", "cancelled"),
    "on_hold": ("in_progress", "assigned", "cancelled"),
    "resolved": ("closed", "in_progress"),
    "closed": (),
    "cancelled": (),
    "spam": (),
}

# Closure codes. The gate in the interface exists because of this table: an
# incident cannot close without saying which of these happened.
RESOLUTION_CODES: Mapping[str, str] = {
    "permanent": "Fixed permanently",
    "workaround": "Workaround in place",
    "config": "Configuration change",
    "nofault": "No fault found",
    "duplicate": "Duplicate",
}

# A workaround means the cause is still out there, so it wants a problem record.
CODES_NEEDING_PROBLEM = ("workaround",)

# ---------------------------------------------------------------- escalation
#
# Escalation risk comes back as a probability. These are the lines a desk draws
# through it, and they live here because they are policy: a manager should be
# able to move them without anyone re-running a model or touching a prompt.
# Moving WATCH down widens the net and costs attention; moving it up narrows it
# and costs surprises.
ESCALATION_WATCH = 0.40      # worth a look before it goes wrong
ESCALATION_LIKELY = 0.65     # act now: this one is going to escalate


# ---------------------------------------------------------------- deflection
#
# What the portal does with an article it thinks might answer the question,
# and the two lines that decide. Deliberately asymmetric: showing a wrong
# article costs a moment's reading, while hiding a right one costs a ticket,
# a queue slot and somebody's afternoon. So the lower line is generous.
DEFLECT_LIKELY = 0.70        # lead with it; raising a ticket becomes secondary
DEFLECT_MAYBE = 0.35         # offer it above the form, quietly


def deflection_band(probability: float) -> "Decision":
    if probability >= DEFLECT_LIKELY:
        return Decision("answer", f"{probability:.0%} is at or over the {DEFLECT_LIKELY:.0%} line")
    if probability >= DEFLECT_MAYBE:
        return Decision("suggest", f"{probability:.0%} is over the {DEFLECT_MAYBE:.0%} line")
    return Decision("quiet", f"{probability:.0%} is under the {DEFLECT_MAYBE:.0%} line")


def escalation_band(probability: float) -> Decision:
    """A probability to the one word a queue can be sorted by."""
    if probability >= ESCALATION_LIKELY:
        return Decision("likely", f"{probability:.0%} is at or over the {ESCALATION_LIKELY:.0%} line")
    if probability >= ESCALATION_WATCH:
        return Decision("watch", f"{probability:.0%} is over the {ESCALATION_WATCH:.0%} watch line")
    return Decision("quiet", f"{probability:.0%} is under the {ESCALATION_WATCH:.0%} watch line")

DEFAULT_MATRIX: Mapping[str, Mapping[str, str]] = {
    "organization": {"low": "P3", "medium": "P2", "high": "P1", "critical": "P1"},
    "department": {"low": "P3", "medium": "P2", "high": "P2", "critical": "P1"},
    "team": {"low": "P4", "medium": "P3", "high": "P2", "critical": "P2"},
    "individual": {"low": "P4", "medium": "P4", "high": "P3", "critical": "P2"},
}


@dataclass(frozen=True)
class SlaRule:
    """One row of the service level table. Order matters: first match wins."""

    order: int
    priority: str
    response_minutes: int
    resolution_minutes: int
    calendar: str  # "always" or "business"


DEFAULT_SLA_RULES: tuple[SlaRule, ...] = (
    SlaRule(1, "P1", 15, 4 * 60, "always"),
    SlaRule(2, "P2", 60, 8 * 60, "always"),
    SlaRule(3, "P3", 4 * 60, 3 * 12 * 60, "business"),
    SlaRule(4, "P4", 12 * 60, 5 * 12 * 60, "business"),
)


@dataclass(frozen=True)
class BusinessHours:
    """Mon-Fri, 07:00 to 19:00, in whatever timezone the caller's datetimes use."""

    start_hour: int = 7
    end_hour: int = 19
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)

    @property
    def seconds_per_day(self) -> int:
        return (self.end_hour - self.start_hour) * 3600


DEFAULT_HOURS = BusinessHours()


@dataclass(frozen=True)
class Decision:
    """An answer plus the reason for it, so the audit log never guesses."""

    value: object
    reason: str


# ---------------------------------------------------------------- priority

def derive_priority(
    matrix: Mapping[str, Mapping[str, str]], impact: str, urgency: str
) -> Decision:
    if impact not in IMPACTS:
        raise ValueError(f"unknown impact {impact!r}")
    if urgency not in URGENCIES:
        raise ValueError(f"unknown urgency {urgency!r}")
    priority = matrix[impact][urgency]
    return Decision(priority, f"{impact} against {urgency} in the matrix")


# ---------------------------------------------------------------- sla

def pick_sla(priority: str, rules: Sequence[SlaRule] = DEFAULT_SLA_RULES) -> Decision:
    """First rule in order whose conditions fit. Today the only condition is
    priority; the signature keeps room for the condition builder later."""
    for rule in sorted(rules, key=lambda r: r.order):
        if rule.priority == priority:
            return Decision(rule, f"rule {rule.order}, the first in order matching {priority}")
    raise ValueError(f"no service level rule covers {priority!r}")


def add_business_seconds(
    start: datetime, seconds: int, hours: BusinessHours = DEFAULT_HOURS
) -> datetime:
    """Walk forward through working time only.

    Used for P3 and P4, whose targets are quoted in working days. A ticket
    raised at 18:00 on Friday does not burn its target over the weekend.
    """
    if seconds <= 0:
        return start
    cursor = start
    remaining = seconds
    guard = 0
    while remaining > 0:
        guard += 1
        if guard > 10_000:  # a decade of weekends; something is wrong
            raise RuntimeError("business-hours walk failed to terminate")
        day_start = cursor.replace(hour=hours.start_hour, minute=0, second=0, microsecond=0)
        day_end = cursor.replace(hour=hours.end_hour, minute=0, second=0, microsecond=0)
        if cursor.weekday() not in hours.weekdays or cursor >= day_end:
            cursor = (day_start + timedelta(days=1))
            continue
        if cursor < day_start:
            cursor = day_start
        available = int((day_end - cursor).total_seconds())
        if remaining <= available:
            return cursor + timedelta(seconds=remaining)
        remaining -= available
        cursor = day_start + timedelta(days=1)
    return cursor


def business_seconds_between(
    start: datetime, end: datetime, hours: BusinessHours = DEFAULT_HOURS
) -> int:
    """How much working time separates two instants."""
    if end <= start:
        return 0
    total = 0
    cursor = start
    guard = 0
    while cursor < end:
        guard += 1
        if guard > 10_000:
            raise RuntimeError("business-hours count failed to terminate")
        day_start = cursor.replace(hour=hours.start_hour, minute=0, second=0, microsecond=0)
        day_end = cursor.replace(hour=hours.end_hour, minute=0, second=0, microsecond=0)
        if cursor.weekday() not in hours.weekdays or cursor >= day_end:
            cursor = day_start + timedelta(days=1)
            continue
        window_start = max(cursor, day_start)
        window_end = min(end, day_end)
        if window_end > window_start:
            total += int((window_end - window_start).total_seconds())
        cursor = day_start + timedelta(days=1)
    return total


def due_at(
    opened_at: datetime,
    minutes: int,
    calendar: str,
    hours: BusinessHours = DEFAULT_HOURS,
) -> datetime:
    if calendar == "business":
        return add_business_seconds(opened_at, minutes * 60, hours)
    return opened_at + timedelta(minutes=minutes)


def seconds_remaining(
    due: datetime,
    now: datetime,
    calendar: str = "always",
    paused_seconds: int = 0,
    hours: BusinessHours = DEFAULT_HOURS,
) -> int:
    """Negative means past target.

    ``paused_seconds`` is time the ticket spent waiting on the requester, which
    the resolution clock does not count and the response clock does.
    """
    # Time spent on hold pushes the target out rather than being forgiven, so
    # the whole thing is one subtraction against an effective due date.
    effective = due + timedelta(seconds=paused_seconds)
    if now <= effective:
        if calendar == "business":
            return business_seconds_between(now, effective, hours)
        return int((effective - now).total_seconds())
    if calendar == "business":
        return -business_seconds_between(effective, now, hours)
    return int((effective - now).total_seconds())


def target_burn(
    opened_at: datetime,
    due: datetime,
    now: datetime,
    paused_seconds: int = 0,
) -> float:
    """Share of the ticket's own target that is gone. Above 1.0 means breached.

    Comparable across priorities on purpose: a P1 four-hour target and a P4
    five-day target both read as pressure rather than as raw clock.
    """
    window = (due - opened_at).total_seconds()
    if window <= 0:
        return 1.0
    spent = (now - opened_at).total_seconds() - paused_seconds
    return max(0.0, spent / window)


# ---------------------------------------------------------------- lifecycle

def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, ())


def assert_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        allowed = ", ".join(TRANSITIONS.get(current, ())) or "nothing"
        raise ValueError(f"{current} cannot become {target}; only {allowed}")


def clock_is_paused(status: str) -> bool:
    """The resolution clock stops while a ticket waits on the person who raised
    it. The response clock never stops, because that one is a promise about us."""
    return status in ("on_hold", "resolved", "closed", "cancelled", "spam")


def requires_problem_record(code: str) -> bool:
    return code in CODES_NEEDING_PROBLEM


def validate_resolution(code: str) -> None:
    if code not in RESOLUTION_CODES:
        known = ", ".join(RESOLUTION_CODES)
        raise ValueError(f"{code!r} is not a resolution code; expected one of {known}")


# ---------------------------------------------------------------- routing

@dataclass(frozen=True)
class Candidate:
    id: str
    name: str
    team: str
    open_tickets: int
    on_leave: bool = False
    skills: tuple[str, ...] = ()
    capacity: int = 8
    tier: str = "Second line"
    location: str = ""

    @property
    def headroom(self) -> int:
        """Tickets this person could still take before they are over capacity."""
        return self.capacity - self.open_tickets

    @property
    def load(self) -> float:
        """Open tickets as a share of capacity. Above 1.0 means overloaded.

        A raw count says a person with four tickets is busier than one with
        three; a share says whether either of them is actually full, which is
        the thing a router should be weighing.
        """
        return self.open_tickets / self.capacity if self.capacity > 0 else float("inf")


def available(team: str, candidates: Iterable[Candidate]) -> list[Candidate]:
    """Everyone on ``team`` who could take work: on the team, not on leave.

    Being over capacity does not make someone ineligible — a full team still
    has to answer the phone. It only makes them a worse pick than a colleague
    with room, which is what the load share expresses.
    """
    return [c for c in candidates if c.team == team and not c.on_leave]


def route_to_person(
    team: str,
    candidates: Iterable[Candidate],
    strategy: str = "least_loaded",
    rotation_index: int = 0,
) -> Decision:
    """Step two of routing, and deliberately mechanical.

    Step one is "which team's domain is this", which reads the ticket and is
    the judgment worth buying. This function only answers "who on that team",
    by counting. Keeping them apart is the point of the whole design.
    """
    pool = available(team, candidates)
    if not pool:
        return Decision(None, f"nobody available on {team}, left unclaimed")
    if strategy == "manual":
        return Decision(None, "manual assignment, the team lead hands work out")
    if strategy == "round_robin":
        pick = sorted(pool, key=lambda c: c.id)[rotation_index % len(pool)]
        return Decision(pick.id, f"next in rotation on {team}")
    pick = min(pool, key=lambda c: (c.open_tickets, c.id))
    return Decision(
        pick.id,
        f"fewest open on {team} at {pick.open_tickets}",
    )


def accept_assignment(
    person_id: str, team: str, candidates: Iterable[Candidate]
) -> Decision:
    """Check a suggested person against the roster before anything is written.

    A judgment names someone; this decides whether that name may be acted on.
    The checks are policy, not model behaviour, so they live here: the person
    has to exist, and they have to be on the team the ticket is going to. Being
    on leave is a refusal too — a suggestion is not a reason to hand work to
    someone who is away.
    """
    pool = {c.id: c for c in candidates}
    person = pool.get(person_id)
    if person is None:
        return Decision(None, f"no such person {person_id!r}")
    if person.on_leave:
        return Decision(None, f"{person.name} is on leave")
    if team and person.team != team:
        return Decision(None, f"{person.name} is on {person.team}, not {team}")
    return Decision(
        person.id,
        f"{person.name} is on {person.team} and available, "
        f"carrying {person.open_tickets} of {person.capacity}",
    )
