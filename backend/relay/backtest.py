"""Scoring the escalation prediction against tickets whose outcome is known.

``architecture.md`` sets the bar: *"Calibration is an artifact, not a claim.
Until that exists, 'calibrated probabilities you can threshold' is marketing."*
This is the artifact for one prediction.

The imported ABC Tech set records, for every closed ticket, how many times it
was reassigned and whether it was reopened. That is escalation having actually
happened — a ticket handed on because whoever held it could not finish it — so
it is ground truth nobody had to invent.

**The caveat is load-bearing and belongs beside every number this produces.**
Neither imported dataset has ticket text. A subject like *"Problem with
web-based application WBA000124"* is composed from structured fields, so a
judgment reading it has almost nothing to read. This measures the floor: what
the prediction gets from category, priority and impact alone, with the language
it exists to read removed. Real tickets carry words, and the whole argument for
reading them is untested here. A good number would be encouraging; a mediocre
one proves much less than it appears to.

    python -m relay.backtest --n 200 --engine jev

Writes ``data/clean/escalation-backtest.json`` and prints the table.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from sqlmodel import Session, select

from . import policy
from .db import engine as db_engine
from .models import HistoricTicket
from .usecases import USE_CASES

REPORT = Path(__file__).resolve().parents[2] / "data" / "clean" / "escalation-backtest.json"
# Buckets for the calibration table: of the tickets it put in each band, how
# many actually escalated? A well-calibrated 70% bucket escalates ~70% of the
# time, which is a stronger claim than overall accuracy and a harder one to
# fake by always guessing the common answer.
BUCKETS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01))


# How many hand-offs make it an escalation rather than ordinary triage.
#
# One reassignment is the service desk passing a network fault to the network
# team, which is routing working correctly — 42% of ABC Tech tickets have it.
# Three is a ticket nobody can place, which is the thing being predicted. That
# lands at 17%, a rate a service desk would recognise. The line is here, in one
# named constant, because moving it changes what every number below means.
BOUNCES = 3


def escalated(ticket: HistoricTicket, bounces: int = BOUNCES) -> bool:
    """Did this ticket actually escalate?

    Reassignment is the recorded fact closest to the statement being predicted:
    the ticket was handed on because whoever had it could not finish it. A
    reopen counts too — the first resolution did not hold.
    """
    return bool((ticket.reassignments or 0) >= bounces or ticket.reopened_at)


def sample(session: Session, n: int, source: str = "abc_tech") -> list[HistoricTicket]:
    """A fixed, reproducible sample: every ticket whose id hashes into the slot.

    Taking the first N would take one week of one year. Hashing the id spreads
    the sample across the whole set and gives the same sample every run, which
    is what makes two runs comparable.
    """
    rows = session.exec(
        select(HistoricTicket).where(HistoricTicket.source == source)
        .order_by(HistoricTicket.id)
    ).all()
    rows = [r for r in rows if r.reassignments is not None]
    if not rows or n >= len(rows):
        return rows
    step = len(rows) / n
    return [rows[int(i * step)] for i in range(n)]


def as_context(ticket: HistoricTicket) -> dict:
    """A closed ticket as the lanes want it — the fields the source actually has.

    Nothing about the outcome goes in. The state is what was knowable while the
    ticket was still open, which is the only way the number means anything.
    """
    state = {
        "subject": ticket.subject,
        "category": ticket.category or "not recorded",
        "priority": ticket.recorded_priority or "not recorded",
        "impact": ticket.impact or "not recorded",
        "urgency": ticket.urgency or "not recorded",
        "owner": ticket.team or "not recorded",
        "note": "this ticket has no written description; the source recorded only these fields",
    }
    prose = "\n".join(f"{k}: {v}" for k, v in state.items())
    return {
        "state": {"ticket": state},
        "prose": prose,
        # the traditional lane gets what it would have had at the time: nothing
        # about the clock is knowable mid-flight from a closed row, so it sees
        # a fresh ticket, which is exactly its blind spot
        "ticket_state": {"burn": 0.0, "reopened": 0, "reassignments": 0, "breached": False},
    }


def run(n: int = 200, engine: str = "jev", source: str = "abc_tech", bounces: int = BOUNCES) -> dict:
    lane = USE_CASES["escalation"].lane(engine)
    with Session(db_engine) as session:
        tickets = sample(session, n, source)
    if not tickets:
        raise SystemExit(f"no {source} tickets imported; run `make import` first")

    started = time.perf_counter()
    rows, failures = [], 0
    for ticket in tickets:
        measured = lane.run(ticket.subject, as_context(ticket))
        if measured.error or measured.noul is None:
            failures += 1
            continue
        rows.append({
            "id": ticket.id,
            "probability": round(measured.noul, 4),
            "band": (measured.detail or {}).get("band", ""),
            "escalated": escalated(ticket, bounces),
            "reassignments": ticket.reassignments or 0,
            "reopened": bool(ticket.reopened_at),
            "cost_usd": measured.cost_usd,
            "latency_ms": measured.latency_ms,
        })
    wall = time.perf_counter() - started

    base = sum(1 for r in rows if r["escalated"]) / len(rows) if rows else 0
    flagged = [r for r in rows if r["probability"] >= policy.ESCALATION_WATCH]
    quiet = [r for r in rows if r["probability"] < policy.ESCALATION_WATCH]
    hits = sum(1 for r in flagged if r["escalated"])
    missed = sum(1 for r in quiet if r["escalated"])

    calibration = []
    for low, high in BUCKETS:
        inside = [r for r in rows if low <= r["probability"] < high]
        if inside:
            calibration.append({
                "band": f"{low:.0%}–{min(high, 1):.0%}",
                "tickets": len(inside),
                "escalated": sum(1 for r in inside if r["escalated"]),
                "actual_rate": round(sum(1 for r in inside if r["escalated"]) / len(inside), 3),
                "mean_prediction": round(sum(r["probability"] for r in inside) / len(inside), 3),
            })

    # Brier score: mean squared error of the probabilities. Lower is better,
    # and 0.25 is what you get by answering 0.5 to everything — so a number
    # above that is worse than refusing to guess.
    brier = round(sum((r["probability"] - (1 if r["escalated"] else 0)) ** 2 for r in rows) / len(rows), 4) if rows else None

    return {
        "engine": engine,
        "source": source,
        "caveat": "These tickets have no written description; the subject is composed from structured "
                  "fields. This measures what the prediction gets with almost nothing to read.",
        "ground_truth": f"reassigned {bounces} times or more, or reopened",
        "tickets": len(rows),
        "failed": failures,
        "base_rate": round(base, 3),
        "escalated": sum(1 for r in rows if r["escalated"]),
        "threshold": policy.ESCALATION_WATCH,
        "flagged": len(flagged),
        "caught": hits,
        "missed": missed,
        "precision": round(hits / len(flagged), 3) if flagged else None,
        "recall": round(hits / (hits + missed), 3) if (hits + missed) else None,
        "accuracy": round((hits + len(quiet) - missed) / len(rows), 3) if rows else None,
        "brier": brier,
        "brier_of_always_guessing_the_base_rate": round(base * (1 - base), 4),
        "calibration": calibration,
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
        "wall_seconds": round(wall, 1),
        "rows": rows,
    }


def show(report: dict) -> None:
    print(f"\n{report['engine']} over {report['tickets']} {report['source']} tickets "
          f"({report['wall_seconds']}s, ${report['cost_usd']})")
    print(f"  {report['escalated']} of them escalated — a base rate of {report['base_rate']:.0%}")
    print(f"  flagged {report['flagged']} at the {report['threshold']:.0%} line: "
          f"{report['caught']} right, {report['flagged'] - report['caught']} wrong, "
          f"{report['missed']} missed")
    print(f"  precision {report['precision']}  recall {report['recall']}  accuracy {report['accuracy']}")
    print(f"  Brier {report['brier']} against {report['brier_of_always_guessing_the_base_rate']} "
          f"for always answering the base rate")
    print("\n  predicted      tickets   actually escalated")
    for row in report["calibration"]:
        print(f"  {row['band']:>12}   {row['tickets']:>7}   {row['actual_rate']:>17.0%}")
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=200, help="how many tickets to score")
    parser.add_argument("--engine", default="jev", choices=("jev", "ai", "sla"))
    parser.add_argument("--all", action="store_true", help="every engine on the same sample")
    parser.add_argument("--bounces", type=int, default=BOUNCES,
                        help="hand-offs that count as an escalation")
    parser.add_argument("--source", default="abc_tech")
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args()

    engines = ("sla", "jev", "ai") if args.all else (args.engine,)
    reports = {}
    for name in engines:
        report = run(args.n, name, args.source, args.bounces)
        # the rows are the evidence, but they make the file unreadable; keep
        # them only when one engine was asked for
        reports[name] = report if len(engines) == 1 else {k: v for k, v in report.items() if k != "rows"}
        show(report)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(reports if len(engines) > 1 else reports[engines[0]], indent=2))
    print(f"\n  {list(reports.values())[0]['caveat']}")
    print(f"  written to {args.out}")


if __name__ == "__main__":
    main()
