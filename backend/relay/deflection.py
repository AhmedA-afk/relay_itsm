"""Answering the question before it becomes a ticket.

The only judgment in Relay that runs before a record exists, and the only one
whose success is measured in work that never arrives.

Three things are code's job, not the model's:

* **Which articles are offered at all.** An article the knowledge owner marked
  stale, or left in draft, is not a candidate — that is a fact about the
  article, not a judgment about the question. They are counted and reported, so
  a neglected knowledge base shows up as a number rather than as quietly worse
  answers.
* **The shortlist.** Same cheap, recall-first filter the duplicate finder uses:
  rare shared words, generous about what it keeps, because a candidate it drops
  can never be offered.
* **What to do with the probability.** ``policy.deflection_band`` turns it into
  lead-with-it, offer-it, or say-nothing. The lines are asymmetric on purpose:
  showing a wrong article costs a moment's reading, hiding a right one costs a
  ticket.

Nobody is ever prevented from raising a ticket. The band decides what the portal
leads with, never what it allows.
"""

from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from . import policy, service
from .duplicates import described, words
from .models import Article, Ticket
from .usecases import DEFLECT_LABELS, USE_CASES

ENGINES = ("jev", "ai", "keywords")
SHORTLIST = 5
LIVE = "Live"


def offerable(session: Session) -> tuple[list[Article], int]:
    """Live articles, and how many were held back for not being live."""
    everything = session.exec(select(Article)).all()
    live = [a for a in everything if a.state == LIVE and not a.stale]
    return live, len(everything) - len(live)


def shortlist(session: Session, text: str, limit: int = SHORTLIST) -> tuple[list[dict], int]:
    """The handful worth asking about, offerable or not.

    Ranked by rare shared words over the title, the body and the keyword list —
    the same ``1/df`` weighting the duplicate finder uses, for the same reason:
    every article about the depot says "depot", so "depot" is not evidence.

    Stale and draft articles are asked about but never offered. Dropping them
    before the question would make "there is no answer written down" and "the
    answer is written down and rotting" look identical from the outside, and
    they call for completely different action: one is a gap in the knowledge
    base, the other is ten minutes of somebody's time.
    """
    live, held_back = offerable(session)
    everything = session.exec(select(Article)).all()
    if not everything:
        return [], held_back
    live_ids = {a.id for a in live}

    asked = words(text)
    bags = {a.id: words(f"{a.title} {a.body} {a.keywords}") for a in everything}
    frequency: dict[str, int] = {}
    for bag in bags.values():
        for word in bag:
            frequency[word] = frequency.get(word, 0) + 1

    scored = []
    for article in everything:
        shared = asked & bags[article.id]
        weight = sum(1 / frequency[w] for w in shared)
        scored.append((weight, {
            "id": article.id, "title": article.title, "body": article.body,
            "keywords": article.keywords, "owner": article.owner,
            "deflected": article.deflected,
            "offerable": article.id in live_ids,
            "state": "Live" if article.id in live_ids else (article.state or "Stale"),
            "kept_because": ("shares " + ", ".join(sorted(shared, key=lambda w: frequency[w])[:4]))
                            if shared else "nothing in common, checked anyway",
        }))
    scored.sort(key=lambda row: -row[0])
    return [article for _, article in scored[:limit]], held_back


def look(session: Session, text: str, engine: str = "jev") -> dict:
    """Would anything already written answer this? Writes nothing."""
    if engine not in ENGINES:
        raise ValueError(f"no deflection engine {engine!r}; known: {', '.join(ENGINES)}")
    text = (text or "").strip()
    if not text:
        raise ValueError("type what you need first")

    articles, held_back = shortlist(session, text)
    measured = USE_CASES["deflection"].lane(engine).run(
        text, {"articles": articles, "held_back": held_back})
    detail = measured.detail or {}
    band = measured.answer or "quiet"
    return {
        "question": text,
        "engine": engine,
        "band": band,
        "label": DEFLECT_LABELS.get(band, band),
        "hits": detail.get("hits", []),
        # articles that would have answered it but are not fit to show: the
        # knowledge base has the answer and has let it go stale
        "rotting": detail.get("rotting", []),
        "checked": detail.get("asked", len(articles)),
        "held_back": held_back,
        "shortlisted": articles,
        "note": detail.get("note", ""),
        "thresholds": {"answer": policy.DEFLECT_LIKELY, "suggest": policy.DEFLECT_MAYBE},
        "error": measured.error,
        "cost_usd": measured.cost_usd,
        "latency_ms": measured.latency_ms,
        "input_tokens": measured.input_tokens,
        "model": measured.model,
    }


def took_it(session: Session, article_id: str) -> dict:
    """Somebody read the article instead of raising a ticket.

    The one number this whole use case exists to move, and the only honest way
    to collect it: the person said so. Nothing infers a deflection from the
    absence of a ticket.
    """
    article = session.get(Article, article_id)
    if article is None:
        raise LookupError(f"no article {article_id}")
    article.deflected += 1
    session.add(article)
    session.commit()
    return {"article": article.id, "deflected": article.deflected}


def would_have_helped(session: Session, now, engine: str = "jev", limit: int = 20) -> dict:
    """Run deflection over tickets that were already raised.

    A forward-looking deflection rate needs people, and there are none here. But
    every open ticket is a question somebody *did* bring to the desk, so asking
    how many of them the knowledge base already answers is a real measurement of
    the same thing, taken backwards — and unlike the escalation backtest, these
    tickets have words in them.

    Two things keep the number honest. It reads what the requester actually
    wrote — the description lives in the first ``Message``, not in
    ``Ticket.body``, and judging a subject line alone would measure the wrong
    thing. And it reports the replayed tickets separately: those carry no text
    by construction, so no deflection system could ever have helped them, and
    leaving them in the denominator would understate the rate for a reason that
    has nothing to do with the knowledge base.

    It is a ceiling rather than a rate either way: somebody who raised a ticket
    may well have searched first and scrolled past the article, which is the
    behaviour keyword search trained them into.
    """
    views = [v for v in service.list_tickets(session, now)
             if v["status"] not in service.LIVE_EXCLUDED]
    rows, wordless = [], []
    for view in views:
        if len(rows) >= limit:
            break
        ticket = session.get(Ticket, view["id"])
        said = described(session, ticket).strip()
        # A composed subject and nothing else: there is no question to answer,
        # so it is counted and skipped rather than scored as a miss. The limit
        # caps how many are *judged*, because capping how many are looked at
        # would spend the whole budget on rows nobody wrote.
        if not said:
            wordless.append(ticket.id)
            continue
        out = look(session, f"{ticket.subject} {said}".strip(), engine)
        rows.append({
            "id": ticket.id, "subject": ticket.subject, "band": out["band"],
            "top": out["hits"][0]["id"] if out["hits"] else None,
            "probability": out["hits"][0]["probability"] if out["hits"] else None,
            "rotting": out["rotting"][0]["id"] if out["rotting"] else None,
            "cost_usd": out["cost_usd"],
        })
    answered = [r for r in rows if r["band"] == "answer"]
    return {
        "engine": engine,
        "looked_at": len(rows) + len(wordless),
        "open_total": len(views),
        "wordless": len(wordless),
        "tickets": len(rows),
        "would_answer": len(answered),
        "would_suggest": sum(1 for r in rows if r["band"] == "suggest"),
        "rate": round(len(answered) / len(rows), 3) if rows else None,
        "answer_exists_but_stale": sum(1 for r in rows if r["rotting"]),
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
        "caveat": "A ceiling, not a rate: somebody who raised a ticket may have searched first and "
                  "scrolled past the article, which is what keyword search trains people to do. "
                  f"{len(wordless)} tickets were skipped for carrying no written description — they "
                  "are replayed rows — so nothing could have deflected them.",
        "rows": rows,
    }
