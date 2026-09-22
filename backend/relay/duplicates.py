"""Finding out whether the desk already has this, and linking it if so.

Two halves, and keeping them apart is the design:

**Code shortlists.** Comparing one ticket against a hundred open ones is a
hundred comparisons. A cheap filter — same department, recently opened, any
meaningful word in common, plus every problem record that shares a word — cuts
that to a handful. The filter is deliberately generous: it is tuned for recall,
because a candidate it drops can never be found, while a candidate it keeps
wrongly only costs one question. Precision is the judgment's job.

**The judgment decides what the relationship is.** Not "are these similar" but
which of three things is true, because they have three different consequences:

* ``same_request`` — the same ask raised twice. Close it, pointing at the other.
* ``same_fault``   — a different person hitting the same underlying fault. Link
  it to the parent and **keep it open**, because that person still needs telling
  when it is fixed. Closing them is how a desk loses the people it was meant to
  notify.
* ``known_problem`` — an instance of a recorded problem. Attach it, and whatever
  workaround somebody already wrote down applies.

Nothing here is stored. Sentiment and escalation keep a row because they are a
number somebody wants on a queue; this produces a *link*, and the link is the
artifact — ``duplicate_of``, ``problem_id``, and an event saying who decided it.
A finding nobody acted on is worth re-deriving next time, against whatever is
open by then.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlmodel import Session, select

from . import policy, service
from .clock import Clock, ensure_utc
from .models import Problem, Ticket
from .usecases import DUPLICATE_LABELS, USE_CASES

ENGINES = ("jev", "ai", "similar")
SHORTLIST = 6              # candidates carried forward; each costs one question
RESERVED = 2               # of those, slots held for the same department regardless of wording
WINDOW_DAYS = 30           # how far back an open ticket can be and still be a candidate
STOPWORDS = {
    "the", "and", "for", "with", "not", "was", "are", "has", "have", "this", "that", "from",
    "will", "can", "cannot", "any", "all", "but", "our", "out", "off", "its", "get", "got",
    "need", "needs", "please", "there", "their", "they", "when", "what", "some", "again",
    "went", "goes", "gone", "been", "being", "does", "did", "done", "now", "still", "back",
    "into", "over", "under", "about", "than", "then", "them", "these", "those", "would",
    "could", "should", "were", "where", "which", "while", "after", "before", "every",
}


def stem(word: str) -> str:
    """Crude suffix folding, so one fault described twice matches itself.

    "scanners" and "scanner", "picking" and "pickers" and "pick" are the same
    word for this purpose, and a filter that treats them as three is looking
    for the one spelling the other person did not use. Crude on purpose: this
    is a cheap filter feeding a judgment, not a linguistics exercise.
    """
    for suffix, keep in (("ing", 5), ("ers", 5), ("ies", 5), ("es", 5), ("s", 4)):
        if len(word) >= keep and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def words(text: str) -> set[str]:
    cleaned = "".join(c if c.isalnum() else " " for c in (text or "").lower())
    return {stem(w) for w in cleaned.split() if len(w) > 2 and w not in STOPWORDS}


def searchable(session: Session, ticket: Ticket) -> str:
    """Everything the requester actually wrote, not just the subject line.

    Relay keeps a ticket's description as its first ``Message`` rather than in
    ``Ticket.body``, which is empty on almost every row. Shortlisting on the
    subject alone throws away the sentence that says *why* — and the word that
    would have matched is usually in there: "something to do with a
    certificate" is what connects an invoice failure to the gateway problem,
    and it never appears in a subject line.
    """
    said = " ".join(m.body for m in service.messages_for(session, ticket.id)
                    if m.visibility == "public")
    return f"{ticket.subject} {ticket.body} {said}"


# How much of a description to carry into the question. Long enough for the
# detail that decides a match — "only the back aisles", "since the firmware
# update" — and short enough that six candidates stay cheap.
DESCRIPTION = 600


def described(session: Session, ticket: Ticket, limit: int = DESCRIPTION) -> str:
    """What the person who raised it said about it — all of it, not just the first line.

    The shortlist matches on the whole public thread, so handing the judgment
    only the opening sentence would mean code selecting candidates on evidence
    the judgment is not allowed to see. The detail that settles a match is
    often in the second message, not the first.

    Desk replies are left out on purpose: they are diagnosis and
    acknowledgement, and two tickets are not the same thing because the desk
    answered them in similar words. When nothing is attributed to the requester
    — the replayed tickets record no caller — any public message is better than
    nothing.
    """
    messages = [m for m in service.messages_for(session, ticket.id) if m.visibility == "public"]
    theirs = [m.body for m in messages if m.author and m.author == ticket.requester]
    said = " ".join(theirs or [m.body for m in messages])
    whole = f"{ticket.body} {said}".strip()
    return whole[:limit].rstrip() + ("…" if len(whole) > limit else "")


def shortlist(session: Session, ticket: Ticket, now, limit: int = SHORTLIST) -> list[dict]:
    """The shortlist for a ticket that exists: its own words, its own team."""
    return shortlist_for(session, searchable(session, ticket), now, team=ticket.team_key,
                         exclude=ticket.id, limit=limit)


def shortlist_for(
    session: Session,
    text: str,
    now,
    *,
    team: Optional[str] = None,
    exclude: Optional[str] = None,
    limit: int = SHORTLIST,
) -> list[dict]:
    """The handful worth asking about, and why each survived.

    Ranked by **rare** shared words rather than by how many. Counting matches
    rewards long conversations and common vocabulary: every warehouse ticket
    says "picking", so "picking" tells you nothing, while "certificate" appears
    in two documents on the whole desk and is almost a pointer. Each shared word
    is worth ``1/df`` — one over the number of candidates that use it — so one
    distinctive word outranks five ordinary ones.

    This is deliberately generous about what it keeps: a candidate it drops can
    never be found, while a candidate it keeps wrongly costs one question.
    Tickets on the same department stay in contention even with no overlap at
    all, because two people describing one fault rarely reach for the same
    nouns — which is exactly the case word matching is bad at, and the whole
    reason a judgment is being asked.
    """
    mine = words(text)
    cutoff = now - timedelta(days=WINDOW_DAYS)

    pool: list[tuple[dict, set[str]]] = []
    for other in session.exec(select(Ticket)).all():
        if exclude and other.id == exclude:
            continue
        if other.status in service.LIVE_EXCLUDED or other.duplicate_of:
            continue
        if ensure_utc(other.opened_at) < cutoff:
            continue
        pool.append(({
            "id": other.id, "kind": "ticket", "subject": other.subject,
            "detail": described(session, other), "status": other.status,
            "team": other.team_key, "raised_by": other.requester or "not recorded",
            "_same_team": bool(team) and other.team_key == team,
            "_opened": ensure_utc(other.opened_at).timestamp(),
        }, words(searchable(session, other))))

    for problem in session.exec(select(Problem)).all():
        pool.append(({
            "id": problem.id, "kind": "problem", "subject": problem.title,
            "detail": problem.root_cause or problem.workaround or "",
            "state": problem.state, "workaround": problem.workaround, "_same_team": False,
        }, words(f"{problem.title} {problem.root_cause} {problem.workaround}")))

    # how many candidates use each word: a word everybody uses is not evidence
    frequency: dict[str, int] = {}
    for _, bag in pool:
        for word in bag:
            frequency[word] = frequency.get(word, 0) + 1

    scored = []
    for candidate, bag in pool:
        shared = mine & bag
        weight = sum(1 / frequency[w] for w in shared)
        if not shared and not candidate["_same_team"]:
            continue
        rarest = sorted(shared, key=lambda w: frequency[w])[:4]
        candidate["kept_because"] = (("shares " + ", ".join(rarest)) if rarest
                                     else f"open on {candidate['team']}")
        scored.append((weight + (0.15 if candidate["_same_team"] else 0), candidate))

    scored.sort(key=lambda row: -row[0])
    kept = [candidate for _, candidate in scored[:limit - RESERVED]]

    # Two slots held back for the newest open tickets on the same department,
    # whatever they say. This is the channel that catches the case the whole
    # feature exists for: two people reporting one fault in words that have
    # nothing in common. Word similarity cannot find those by construction, so
    # if it owned every slot they would never be compared at all.
    seen = {candidate["id"] for candidate in kept}
    recent = sorted(
        (c for c, _ in pool if c["_same_team"] and c["id"] not in seen),
        key=lambda c: c.get("_opened", 0), reverse=True,
    )
    for candidate in recent[:RESERVED]:
        candidate["kept_because"] = (candidate.get("kept_because")
                                     or f"newest open on {candidate['team']}")
        kept.append(candidate)

    return [{k: v for k, v in candidate.items() if not k.startswith("_")} for candidate in kept[:limit]]


def look(session: Session, ticket_id: str, now, engine: str = "jev") -> dict:
    """Shortlist, then ask. Writes nothing."""
    if engine not in ENGINES:
        raise ValueError(f"no duplicate engine {engine!r}; known: {', '.join(ENGINES)}")
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise LookupError(f"no ticket {ticket_id}")

    candidates = shortlist(session, ticket, now)
    ctx = {
        "candidates": candidates,
        "subject_state": {"subject": ticket.subject,
                          "said": described(session, ticket),
                          "raised_by": ticket.requester, "department": ticket.department},
    }
    measured = USE_CASES["duplicate"].lane(engine).run(ticket.subject, ctx)
    matches = (measured.detail or {}).get("matches", [])
    return {
        "ticket": ticket.id,
        "engine": engine,
        "shortlisted": candidates,
        "asked": len(candidates),
        "matches": [{**m, "label": DUPLICATE_LABELS.get(m["relation"], m["relation"])} for m in matches],
        "note": (measured.detail or {}).get("note", ""),
        "error": measured.error,
        "cost_usd": measured.cost_usd,
        "latency_ms": measured.latency_ms,
        "input_tokens": measured.input_tokens,
        "model": measured.model,
    }


def link(
    session: Session,
    ticket_id: str,
    *,
    other_id: str,
    relation: str,
    clock: Clock,
    actor: str = "Relay judgment",
    actor_kind: str = "judgment",
    reason: str = "",
) -> dict:
    """Act on one finding. Each relationship does a different thing.

    ``same_request`` is the only one that closes anything, and it closes the
    *new* ticket rather than the one already being worked. The other two leave
    the ticket open on purpose.
    """
    if relation not in ("same_request", "same_fault", "known_problem"):
        raise ValueError(f"{relation!r} is not something to link on")
    ticket = service._get(session, ticket_id)
    now = clock.now()
    reason = reason or f"{DUPLICATE_LABELS[relation].lower()}, {other_id}"

    if relation == "known_problem":
        if session.get(Problem, other_id) is None:
            raise LookupError(f"no problem {other_id}")
        old, ticket.problem_id = ticket.problem_id, other_id
        service.record(session, ticket_id, at=now, actor=actor, actor_kind=actor_kind,
                       field="problem", old=old, new=other_id, reason=reason)
    else:
        other = session.get(Ticket, other_id)
        if other is None:
            raise LookupError(f"no ticket {other_id}")
        if other_id == ticket_id:
            raise ValueError("a ticket cannot be a duplicate of itself")
        if other.duplicate_of == ticket_id:
            raise ValueError(f"{other_id} is already linked to this one; linking both ways would loop")
        old, ticket.duplicate_of = ticket.duplicate_of, other_id
        service.record(session, ticket_id, at=now, actor=actor, actor_kind=actor_kind,
                       field="duplicate_of", old=old, new=other_id, reason=reason)

        if relation == "same_request":
            # The same ask twice, so this one is finished; the other carries on.
            #
            # The lifecycle says a ticket has to be picked up before it can be
            # resolved, and a duplicate is not exempt from that — somebody, or
            # something, took it in order to close it. So it walks the legal
            # step rather than being dropped into resolved from nowhere, and
            # the log says why it moved.
            if not policy.can_transition(ticket.status, "resolved"):
                policy.assert_transition(ticket.status, "in_progress")
                was_new, ticket.status = ticket.status, "in_progress"
                service.record(session, ticket_id, at=now, actor=actor, actor_kind=actor_kind,
                               field="status", old=was_new, new="in_progress",
                               reason=f"picked up in order to close it against {other_id}")
            policy.assert_transition(ticket.status, "resolved")
            service._resume_clock(session, ticket, now)
            was, ticket.status = ticket.status, "resolved"
            ticket.resolution_code = "duplicate"
            ticket.resolution_note = f"The same request as {other_id}, which is still open."
            ticket.resolved_at = now
            service.record(session, ticket_id, at=now, actor=actor, actor_kind=actor_kind,
                           field="status", old=was, new="resolved",
                           reason=f"closed as a duplicate of {other_id}")
        else:
            # a second reporter: they stay on the ticket, because they are the
            # person who has to be told when it is fixed
            service.record(session, ticket_id, at=now, actor="Relay", actor_kind="system",
                           field="duplicate_of", old=other_id, new=other_id,
                           reason="kept open: a second reporter still needs telling when it is fixed")

    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return {"ticket": ticket_id, "linked_to": other_id, "relation": relation,
            "status": ticket.status, "problem_id": ticket.problem_id,
            "duplicate_of": ticket.duplicate_of}


def children(session: Session, ticket_id: str) -> list[dict]:
    """Everything linked to this ticket, for the parent's own screen."""
    return [
        {"id": t.id, "subject": t.subject, "status": t.status, "requester": t.requester,
         "closed": t.status in service.LIVE_EXCLUDED}
        for t in session.exec(select(Ticket).where(Ticket.duplicate_of == ticket_id)).all()
    ]


def summary(session: Session, now) -> dict:
    """How much of the queue is actually one thing seen several times."""
    views = [v for v in service.list_tickets(session, now)
             if v["status"] not in service.LIVE_EXCLUDED or v["resolution_code"] == "duplicate"]
    linked = [v for v in views if v.get("duplicate_of")]
    parents: dict[str, int] = {}
    for v in linked:
        parents[v["duplicate_of"]] = parents.get(v["duplicate_of"], 0) + 1
    return {
        "linked": len(linked),
        "clusters": len(parents),
        "largest": max(parents.values()) if parents else 0,
        "parents": [{"id": pid, "reporters": n} for pid, n in
                    sorted(parents.items(), key=lambda kv: -kv[1])[:8]],
    }
