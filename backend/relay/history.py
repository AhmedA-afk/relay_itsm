"""Closed tickets from outside datasets, cleaned into Relay's vocabulary.

Pure, like ``policy``: no database, no files, no clock. A raw CSV row goes in;
a normalised record comes out, or the reason it was refused. Every repair is
counted in a ``Tally`` so the cleaning is reported, never silent.

Two sources, both from Kaggle:

``abc_tech``  ahanwadi/itsm-data — 46,606 incidents from "ABC Tech", 2012–14.
              Real-looking operational data with real-looking damage: dates in
              two formats, a mangled duration column, spreadsheet placeholders,
              a five-level scale where Relay has four, two Dutch closure codes.
``gcc_desk``  swapniljadhav96/itsm-dataset — 100,000 tickets from a service desk
              across six Gulf countries, 2024. Internally consistent timestamps,
              but every categorical column is spread almost exactly evenly and
              the status column contradicts the timestamps. Treat it as synthetic.

Neither source carries free text, so ``subject`` is composed from the
structured fields and says only what those fields say.

Recorded priority is stored here, which the live ``Ticket`` table never does.
The difference is deliberate: a live ticket's priority is a *decision* the
matrix makes on every read; a closed ticket's priority is a *fact* about what
someone decided at the time, and re-deriving it would rewrite history.
"""

from __future__ import annotations

import zlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional

ABC, GCC = "abc_tech", "gcc_desk"

SOURCE_LABELS: Mapping[str, str] = {
    ABC: "ABC Tech, 2012–14",
    GCC: "Gulf service desk, 2024",
}
SOURCE_ORIGINS: Mapping[str, str] = {
    ABC: "kaggle.com/datasets/ahanwadi/itsm-data",
    GCC: "kaggle.com/datasets/swapniljadhav96/itsm-dataset",
}

# Spreadsheet debris that means "no value": Excel's #MULTIVALUE, the Dutch
# export's #N/B ("niet beschikbaar"), and the source's own not-set markers.
PLACEHOLDERS = frozenset({"", "#MULTIVALUE", "#N/B", "NS", "NA", "N/A", "#N/A"})


@dataclass
class Tally:
    """Every repair and refusal, by rule, so the import can report them."""

    seen: Counter = field(default_factory=Counter)
    repaired: Counter = field(default_factory=Counter)
    refused: Counter = field(default_factory=Counter)

    def fix(self, source: str, rule: str, n: int = 1) -> None:
        self.repaired[(source, rule)] += n

    def refuse(self, source: str, rule: str) -> None:
        self.refused[(source, rule)] += 1

    def as_dict(self) -> dict:
        def group(c: Counter) -> dict:
            out: dict[str, dict[str, int]] = {}
            for (source, rule), n in sorted(c.items()):
                out.setdefault(source, {})[rule] = n
            return out
        return {"seen": dict(self.seen), "repaired": group(self.repaired), "refused": group(self.refused)}


class Refused(ValueError):
    """A row that cannot become a record. The message is the rule it broke."""


def clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = value.strip()
    return None if v in PLACEHOLDERS else v


# ---------------------------------------------------------------- abc tech

def parse_abc_time(value: Optional[str]) -> Optional[datetime]:
    """Day first, whichever separator the row happens to use.

    The export mixes ``29-03-2012 12:36`` with ``5/2/2012 13:32``. Every
    slash-form date in the file has both leading fields at 12 or under, and
    every dash-form date has a day above 12 — the signature of a spreadsheet
    that rewrote the day-first dates it *could* read as month-first. Read as
    day-first, no ticket closes before it opens; read as month-first, 8.4% do.
    Times carry no zone, so they are taken as UTC.
    """
    v = clean(value)
    if v is None:
        return None
    try:
        date_part, time_part = v.split(" ")
        sep = "-" if "-" in date_part else "/"
        day, month, year = (int(x) for x in date_part.split(sep))
        hour, minute = (int(x) for x in time_part.split(":")[:2])
        return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    except (ValueError, TypeError) as exc:
        raise Refused(f"unreadable time {v!r}") from exc


def five_level(value: Optional[str]) -> Optional[int]:
    """1–5, tolerating the one cell written as '5 - Very Low'."""
    v = clean(value)
    if v is None:
        return None
    head = v.split(" ", 1)[0]
    if head.isdigit() and 1 <= int(head) <= 5:
        return int(head)
    raise Refused(f"level outside 1-5: {v!r}")


# Five source levels onto Relay's four. Levels 4 and 5 both land on the lowest
# rung; the raw level is kept alongside so nothing is lost.
IMPACT_FROM_5 = {1: "organization", 2: "department", 3: "team", 4: "individual", 5: "individual"}
URGENCY_FROM_5 = {1: "critical", 2: "high", 3: "medium", 4: "low", 5: "low"}
PRIORITY_FROM_5 = {1: "P1", 2: "P2", 3: "P3", 4: "P4", 5: "P4"}

ABC_KIND = {
    "incident": ("incident", "incident"),
    "complaint": ("incident", "complaint"),
    "request for information": ("request", "information request"),
    "request for change": ("request", "change request"),
}

ABC_CLOSURE = {
    "Kwaliteit van de output": "Quality of output",   # Dutch, in an English export
    "Overig": "Other",
    "No error - works as designed": "No error, works as designed",
}

CI_CLASS = {
    "subapplication": "Sub-application",
    "applicationcomponent": "Application component",
    "displaydevice": "Display device",
    "officeelectronics": "Office electronics",
    "networkcomponents": "Network components",
}


def ci_class(value: Optional[str]) -> Optional[str]:
    v = clean(value)
    if v is None:
        return None
    return CI_CLASS.get(v.lower(), v[:1].upper() + v[1:].lower())


def count(value: Optional[str]) -> Optional[int]:
    v = clean(value)
    return int(v) if v is not None and v.isdigit() else None


def normalise_abc(row: Mapping[str, str], tally: Tally) -> dict:
    tally.seen[ABC] += 1
    source_id = clean(row.get("Incident_ID"))
    if not source_id:
        raise Refused("no incident id")

    opened = parse_abc_time(row.get("Open_Time"))
    if opened is None:
        raise Refused("no open time")
    resolved = parse_abc_time(row.get("Resolved_Time"))
    closed = parse_abc_time(row.get("Close_Time"))
    reopened = parse_abc_time(row.get("Reopen_Time"))

    if resolved and resolved < opened:
        tally.fix(ABC, "resolved before opened: resolution time dropped")
        resolved = None
    if closed and closed < opened:
        raise Refused("closed before it opened")

    raw_status = clean(row.get("Status")) or ""
    status = {"Closed": "closed", "Work in progress": "in_progress"}.get(raw_status)
    if status is None:
        raise Refused(f"unknown status {raw_status!r}")
    if status == "in_progress" and closed:
        # The label is a person's statement; a close stamp on an open ticket is
        # an export artefact. Trust the person.
        tally.fix(ABC, "close time on a ticket still in progress: dropped")
        closed = None

    impact_raw = five_level(row.get("Impact"))
    urgency_raw = five_level(row.get("Urgency"))
    priority_raw = five_level(row.get("Priority"))
    if (row.get("Urgency") or "").strip() == "5 - Very Low":
        tally.fix(ABC, "urgency written as '5 - Very Low': read as 5")
    if impact_raw is None:
        tally.fix(ABC, "impact not set (NS): left empty")

    category_raw = (clean(row.get("Category")) or "").lower()
    if category_raw not in ABC_KIND:
        raise Refused(f"unknown category {category_raw!r}")
    kind, kind_label = ABC_KIND[category_raw]

    closure = clean(row.get("Closure_Code"))
    if closure in ABC_CLOSURE:
        if closure in ("Kwaliteit van de output", "Overig"):
            tally.fix(ABC, "Dutch closure code translated")
        closure = ABC_CLOSURE[closure]
    if closure is None:
        tally.fix(ABC, "closure code missing: left empty")

    cls = ci_class(row.get("CI_Cat"))
    sub = clean(row.get("CI_Subcat"))
    ci = clean(row.get("CI_Name"))
    if cls is None:
        tally.fix(ABC, "configuration item class missing: left empty")

    for col in ("Related_Interaction", "Related_Change"):
        if (row.get(col) or "").strip() in ("#MULTIVALUE", "#N/B"):
            tally.fix(ABC, f"{col} placeholder (#MULTIVALUE / #N/B): left empty, count kept")

    tally.fix(ABC, "Handle_Time_hrs unreadable: recomputed from timestamps")

    thing = sub or cls or "Unclassified item"
    subject = f"{thing} {kind_label}" + (f" on {ci}" if ci else "")

    return {
        "id": f"{ABC}:{source_id}",
        "source": ABC,
        "source_id": source_id,
        "kind": kind,
        "subject": subject,
        "category": " / ".join(x for x in (cls, sub) if x) or "",
        "service": clean(row.get("WBS")) or "",
        "affected_ci": ci or "",
        "team": "",
        "assignee": "",
        "channel": "",
        "country": "",
        "support_level": "",
        "impact": IMPACT_FROM_5.get(impact_raw) if impact_raw else None,
        "urgency": URGENCY_FROM_5.get(urgency_raw) if urgency_raw else None,
        "recorded_priority": PRIORITY_FROM_5.get(priority_raw) if priority_raw else None,
        "source_priority": str(priority_raw) if priority_raw else "",
        "source_status": raw_status,
        "status": status,
        "closure": closure or "",
        "kb_article": clean(row.get("KB_number")) or "",
        "opened_at": opened,
        "first_response_at": None,
        "resolved_at": resolved,
        "closed_at": closed,
        "reopened_at": reopened,
        "reassignments": count(row.get("No_of_Reassignments")),
        "interactions": count(row.get("No_of_Related_Interactions")),
        "related_incidents": count(row.get("No_of_Related_Incidents")) or 0,
        "related_changes": count(row.get("No_of_Related_Changes")) or 0,
        "satisfaction": "",
        "response_target_minutes": None,
        "resolution_target_minutes": None,
        "response_met": None,
        "resolution_met": None,
        "resolution_hours": hours_between(opened, resolved),
    }


# ---------------------------------------------------------------- gulf desk

GCC_PRIORITY = {"Critical": "P1", "High": "P2", "Medium": "P3", "Low": "P4"}
GCC_KIND = {"Access Request": "request", "General Inquiry": "request"}   # the rest broke
GCC_TEAM = {
    "IT Support": "it_support", "Network Ops": "network_ops", "Security": "security",
    "Development": "development", "Customer Service": "customer_service",
}


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    v = clean(value)
    if v is None:
        return None
    try:
        return datetime.fromisoformat(v).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise Refused(f"unreadable time {v!r}") from exc


def normalise_gcc(row: Mapping[str, str], tally: Tally) -> dict:
    tally.seen[GCC] += 1
    source_id = clean(row.get("Ticket ID"))
    if not source_id:
        raise Refused("no ticket id")
    opened = parse_iso(row.get("Created time"))
    if opened is None:
        raise Refused("no created time")
    first = parse_iso(row.get("First response time"))
    resolved = parse_iso(row.get("Resolution time"))
    closed = parse_iso(row.get("Close time"))
    due_response = parse_iso(row.get("Expected SLA to first response"))
    due_resolve = parse_iso(row.get("Expected SLA to resolve"))

    if resolved and resolved < opened:
        raise Refused("resolved before it was created")

    raw_status = clean(row.get("Status")) or ""
    # Every row carries a resolution and a close stamp, including the 40% the
    # status column calls New or Open. The timestamps agree with each other and
    # with the SLA columns; the status column agrees with nothing.
    status = "closed" if closed else ("resolved" if resolved else "in_progress")
    if raw_status not in ("Closed",) and closed:
        tally.fix(GCC, f"status '{raw_status}' contradicts its close time: status set from timestamps")

    priority_raw = clean(row.get("Priority")) or ""
    if priority_raw not in GCC_PRIORITY:
        raise Refused(f"unknown priority {priority_raw!r}")

    topic = clean(row.get("Topic")) or "Ticket"
    product = clean(row.get("Product group")) or ""
    channel = (clean(row.get("Source")) or "").lower()
    group = clean(row.get("Agent Group")) or ""

    # SLA outcome is recomputed from the stamps rather than copied from the
    # "Met" columns, so the claim is checked, not trusted.
    response_met = (first <= due_response) if first and due_response else None
    resolution_met = (resolved <= due_resolve) if resolved and due_resolve else None

    return {
        "id": f"{GCC}:{source_id}",
        "source": GCC,
        "source_id": source_id,
        "kind": GCC_KIND.get(topic, "incident"),
        "subject": f"{topic}, {product.lower() or 'unspecified'}" + (f" (by {channel})" if channel else ""),
        "category": " / ".join(x for x in (product, topic) if x),
        "service": product,
        "affected_ci": "",
        "team": GCC_TEAM.get(group, group.lower().replace(" ", "_")),
        "assignee": clean(row.get("Agent Name")) or "",
        "channel": channel,
        "country": clean(row.get("Country")) or "",
        "support_level": clean(row.get("Support Level")) or "",
        "impact": None,
        "urgency": None,
        "recorded_priority": GCC_PRIORITY[priority_raw],
        "source_priority": priority_raw,
        "source_status": raw_status,
        "status": status,
        "closure": "",
        "kb_article": "",
        "opened_at": opened,
        "first_response_at": first,
        "resolved_at": resolved,
        "closed_at": closed,
        "reopened_at": None,
        "reassignments": None,
        "interactions": count(row.get("Agent interactions")),
        "related_incidents": 0,
        "related_changes": 0,
        "satisfaction": (clean(row.get("Survey results")) or "").lower(),
        "response_target_minutes": minutes_between(opened, due_response),
        "resolution_target_minutes": minutes_between(opened, due_resolve),
        "response_met": response_met,
        "resolution_met": resolution_met,
        "resolution_hours": hours_between(opened, resolved),
    }


# ---------------------------------------------------------------- arithmetic

def hours_between(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 3600, 3)


def minutes_between(a: Optional[datetime], b: Optional[datetime]) -> Optional[int]:
    if a is None or b is None:
        return None
    return int((b - a).total_seconds() // 60)


NORMALISERS = {ABC: normalise_abc, GCC: normalise_gcc}


# ---------------------------------------------------------------- replay

# The live desk replays one real moment of ABC Tech's queue. Everything below
# is what makes a closed-ticket record fit Relay's live model: which team it
# belongs to, what to call it, how its closure maps onto Relay's codes, and
# which tickets a desk of Relay's size would carry. The database side is
# ``replay``; these stay pure so they can be tested on their own.

WEEK = timedelta(weeks=1)

# Step one of routing, by configuration item class. ABC Tech records no team,
# so the class of the thing that broke is the best evidence of whose it is.
TEAM_BY_CLASS = {
    "Application": "erp_apps", "Sub-application": "erp_apps", "Application component": "erp_apps",
    "Database": "erp_apps", "Storage": "erp_apps",
    "Computer": "endpoint", "Hardware": "endpoint", "Software": "endpoint",
    "Display device": "endpoint", "Office electronics": "endpoint", "Phone": "endpoint",
    "Network components": "network",
}

# ABC Tech's closure codes are causes; Relay's are outcomes. Only the ones
# that say which outcome happened are mapped. The cause always travels in the
# resolution note, so nothing is lost where the mapping is silent.
CODE_BY_CLOSURE = {
    "No error, works as designed": "nofault", "User error": "nofault", "Operator error": "nofault",
    "User manual not used": "nofault", "Inquiry": "nofault", "Questions": "nofault",
    "Software": "permanent", "Hardware": "permanent", "Data": "permanent", "Quality of output": "permanent",
}

VERB_BY_KIND = {"incident": "Problem with", "complaint": "Complaint about",
                "information request": "Question about", "change request": "Change requested to"}


def team_for(category: str, kind: str) -> tuple[str, str]:
    """The team, and the reason, for a replayed ticket."""
    if kind == "request":
        return "service_desk", "a request for information goes to first line"
    cls = (category or "").split(" / ")[0]
    team = TEAM_BY_CLASS.get(cls, "service_desk")
    if cls in TEAM_BY_CLASS:
        return team, f"no team in the source; routed by item class, {cls} belongs to {team}"
    return team, "no team and no item class in the source, so first line takes it"


def live_subject(subject: str) -> str:
    """'Web Based Application incident on WBA000124' → 'Problem with web-based application WBA000124'.

    Says only what the source's fields say: what kind of contact, about which
    item. Neither dataset has the words the caller used.
    """
    for label, verb in VERB_BY_KIND.items():
        marker = f" {label}"
        if marker in subject:
            thing, _, ci = subject.partition(marker)
            thing = thing.replace(" Based ", "-based ").lower() if thing[:1].isupper() and not thing.isupper() else thing
            ci = ci.removeprefix(" on ").strip()
            return f"{verb} {thing}" + (f" {ci}" if ci else "")
    return subject


def code_for(closure: str) -> str:
    return CODE_BY_CLOSURE.get(closure, "")


def in_sample(source_id: str, every: int) -> bool:
    """A fixed 1-in-``every`` sample. Hashing the id rather than drawing at
    random keeps the selection the same on every run and blind to content."""
    return every <= 1 or zlib.crc32(source_id.encode()) % every == 0


def weeks_back(now: datetime, target: datetime) -> tuple[datetime, timedelta]:
    """The moment in the source that sits a whole number of weeks before now,
    nearest to ``target``. Whole weeks keep weekday and time of day, so
    working-hours targets fall on the same days they did originally."""
    k = round((now - target) / WEEK)
    return now - k * WEEK, k * WEEK
