"""What the imported history says, as one summary for the History screen.

The table only changes when ``import_history`` runs, so the summary is cached
against the row count and the newest id and recomputed only after an import.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from . import history, policy

REPORT = Path(__file__).resolve().parents[2] / "data" / "clean" / "report.json"
_cache: dict = {}


def _q(session: Session, sql: str, **params) -> list:
    return list(session.exec(text(sql).bindparams(**params)).all()) if params else list(session.exec(text(sql)).all())


def _pct(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    i = min(len(sorted_values) - 1, max(0, round(p * (len(sorted_values) - 1))))
    return round(sorted_values[i], 1)


def summary(session: Session) -> dict:
    stamp = tuple(_q(session, "select count(*), max(id) from historicticket")[0])
    if _cache.get("stamp") == stamp:
        return _cache["value"]
    value = _build(session) if stamp[0] else {"empty": True}
    _cache.update(stamp=stamp, value=value)
    return value


def _build(session: Session) -> dict:
    sources = []
    for source, total, incidents, first, last in _q(session, """
        select source, count(*), sum(kind = 'incident'), min(opened_at), max(opened_at)
        from historicticket group by source order by min(opened_at)
    """):
        sources.append({
            "source": source, "label": history.SOURCE_LABELS.get(source, source),
            "origin": history.SOURCE_ORIGINS.get(source, ""),
            "total": total, "incidents": incidents, "requests": total - incidents,
            "from": first[:10], "to": last[:10],
        })

    monthly: dict[str, list] = defaultdict(list)
    for source, month, n in _q(session, """
        select source, substr(opened_at, 1, 7) as m, count(*) from historicticket
        group by source, m order by source, m
    """):
        monthly[source].append({"month": month, "count": n})

    mix: dict[str, dict] = defaultdict(dict)
    for source, prio, n in _q(session, "select source, recorded_priority, count(*) from historicticket group by 1, 2"):
        mix[source][prio or "unset"] = n

    hours: dict[tuple, list] = defaultdict(list)
    for source, prio, h in _q(session, """
        select source, recorded_priority, resolution_hours from historicticket
        where resolution_hours is not null and recorded_priority is not null order by resolution_hours
    """):
        hours[(source, prio)].append(h)
    resolution = defaultdict(list)
    for (source, prio), hs in sorted(hours.items()):
        resolution[source].append({
            "priority": prio, "n": len(hs), "median": _pct(hs, 0.5), "p90": _pct(hs, 0.9),
        })

    # Does the source's own priority agree with Relay's matrix, read off the
    # mapped impact and urgency? A check on the mapping as much as on the data.
    agree = disagree = 0
    for imp, urg, prio, n in _q(session, """
        select impact, urgency, recorded_priority, count(*) from historicticket
        where source = :s and impact is not null and urgency is not null group by 1, 2, 3
    """, s=history.ABC):
        if policy.DEFAULT_MATRIX[imp][urg] == prio:
            agree += n
        else:
            disagree += n

    # What each extra hand-off costs, in hours to resolve.
    buckets = [("none", 0, 0), ("1", 1, 1), ("2", 2, 2), ("3 to 5", 3, 5), ("6 or more", 6, 10_000)]
    reassign = []
    for label, lo, hi in buckets:
        hs = [r[0] for r in _q(session, """
            select resolution_hours from historicticket where source = :s and reassignments between :lo and :hi
            and resolution_hours is not null order by resolution_hours
        """, s=history.ABC, lo=lo, hi=hi)]
        reassign.append({"label": label, "n": len(hs), "median": _pct(hs, 0.5)})

    closure = [{"label": c, "count": n} for c, n in _q(session, """
        select closure, count(*) from historicticket where source = :s and closure != ''
        group by 1 order by 2 desc limit 9
    """, s=history.ABC)]

    satisfaction = defaultdict(dict)
    for channel, sat, n in _q(session, """
        select channel, satisfaction, count(*) from historicticket
        where source = :s and satisfaction != '' group by 1, 2
    """, s=history.GCC):
        satisfaction[channel][sat] = n

    sla = [{"priority": p, "target_hours": round(t / 60, 1), "met": m, "n": n} for p, t, m, n in _q(session, """
        select recorded_priority, avg(resolution_target_minutes), avg(resolution_met), count(*)
        from historicticket where source = :s and resolution_met is not null group by 1 order by 1
    """, s=history.GCC)]

    cleaning = None
    if REPORT.exists():
        report = json.loads(REPORT.read_text())
        cleaning = {
            source: {
                "seen": report["seen"].get(source, 0),
                "refused": sum(report["refused"].get(source, {}).values()),
                "rules": report["repaired"].get(source, {}),
            }
            for source in report["seen"]
        }

    return {
        "empty": False,
        "total": sum(s["total"] for s in sources),
        "sources": sources,
        "monthly": monthly,
        "priority_mix": mix,
        "resolution": resolution,
        "matrix_agreement": {"agree": agree, "disagree": disagree},
        "reassignment_cost": reassign,
        "closure": closure,
        "satisfaction": satisfaction,
        "sla": sla,
        "cleaning": cleaning,
    }
