"""Run a Showcase use case: the same words through Jev and through an LLM call.

Lanes run in parallel, so "run both" costs the slower lane's time, not the sum,
and each lane's own latency is measured around its own HTTP call. The use cases
themselves live in ``usecases``; the measured calls in ``ai``.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from .usecases import USE_CASES  # noqa: F401  (re-exported for callers building context)

MAX_TEXT = 2000


def cases(ctx: dict | None = None) -> list[dict]:
    return [u.describe(ctx) for u in USE_CASES.values()]


def _against_jev(jev: dict, other: dict, order: tuple[str, ...], groups: dict) -> dict:
    out = {
        "agree": jev["answer"] == other["answer"],
        # how many times longer and dearer the other lane was than Jev
        "slower": round(other["latency_ms"] / jev["latency_ms"], 1) if jev["latency_ms"] else None,
        "dearer": round(other["cost_usd"] / jev["cost_usd"], 1) if jev["cost_usd"] else None,
    }
    # on an ordered scale, how far apart matters more than whether they differ
    if jev["answer"] in order and other["answer"] in order:
        out["levels_apart"] = abs(order.index(jev["answer"]) - order.index(other["answer"]))
    # when the answers are people, naming two different people on the same
    # department is a much smaller disagreement than sending it elsewhere
    if not out["agree"] and groups.get(jev["answer"]) and groups.get(jev["answer"]) == groups.get(other["answer"]):
        out["same_group"] = groups[jev["answer"]]
    return out


def run(case: str, text: str, lanes: list[str] | None = None, ctx: dict | None = None) -> dict:
    """Run some or all of a use case's lanes on the same words, in parallel.

    ``ctx`` carries live configuration a lane may read: the matrix and service
    level rules as Administration has them, and — for the matrix lane — the
    impact and urgency the caller picked on the form.
    """
    ctx = ctx or {}
    use = USE_CASES.get(case)
    if use is None:
        raise LookupError(f"no use case {case!r}; known: {', '.join(USE_CASES)}")
    text = (text or "").strip()
    if not text:
        raise ValueError("type a ticket subject first")
    if len(text) > MAX_TEXT:
        raise ValueError(f"keep it under {MAX_TEXT} characters")
    keys = [l.key for l in use.lanes]
    chosen = [k for k in (lanes or keys) if k in keys] or keys

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(chosen)) as pool:
        futures = {k: pool.submit(use.lane(k).run, text, ctx) for k in chosen}
        results = {k: f.result().as_dict() for k, f in futures.items()}
    wall_ms = round((time.perf_counter() - started) * 1000, 1)

    labels = use.label_map(ctx)
    groups = use.group_map(ctx)
    for r in results.values():
        r["label"] = labels.get(r["answer"], r["answer"])
        if groups.get(r["answer"]):
            r["group"] = groups[r["answer"]]

    compare = {}
    jev = results.get("jev")
    if jev and not jev["error"]:
        for k, r in results.items():
            if k != "jev" and not r["error"]:
                compare[k] = _against_jev(jev, r, use.order, groups)
    return {"case": case, "text": text, "lanes": chosen, "results": results, "wall_ms": wall_ms,
            "compare": compare or None}
