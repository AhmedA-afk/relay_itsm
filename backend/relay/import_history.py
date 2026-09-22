"""Load the outside datasets into ``historicticket``.

    python -m relay.import_history                  # both, from the kagglehub cache
    python -m relay.import_history --abc a.csv --gcc b.csv

Idempotent: each run replaces the rows of the sources it loads. Alongside the
table it writes ``data/clean/history.csv`` (every normalised record) and
``data/clean/report.json`` (what was seen, repaired and refused, by rule).
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from glob import glob
from pathlib import Path

from sqlalchemy import delete, insert
from sqlmodel import Session

from . import history
from .db import create_all, engine
from .models import HistoricTicket

CACHE = Path.home() / ".cache" / "kagglehub" / "datasets"
DEFAULTS = {
    history.ABC: "ahanwadi/itsm-data/versions/*/ITSM_data.csv",
    history.GCC: "swapniljadhav96/itsm-dataset/versions/*/ITSM_Dataset.csv",
}
OUT = Path(__file__).resolve().parents[2] / "data" / "clean"
CHUNK = 5000


def find(source: str, given: str | None) -> Path | None:
    if given:
        return Path(given)
    hits = sorted(glob(str(CACHE / DEFAULTS[source])))
    return Path(hits[-1]) if hits else None


def read(path: Path, source: str, tally: history.Tally) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            if any("�" in (v or "") for v in row.values()):
                tally.fix(source, "undecodable bytes replaced")
            try:
                records.append(history.NORMALISERS[source](row, tally))
            except history.Refused as exc:
                tally.refuse(source, str(exc).split(":")[0])
    return records


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--abc", help="ABC Tech CSV (ITSM_data.csv)")
    parser.add_argument("--gcc", help="Gulf desk CSV (ITSM_Dataset.csv)")
    parser.add_argument("--out", default=str(OUT), help="where to write history.csv and report.json")
    args = parser.parse_args(argv)

    create_all()
    tally = history.Tally()
    loaded: dict[str, list[dict]] = {}
    for source, given in ((history.ABC, args.abc), (history.GCC, args.gcc)):
        path = find(source, given)
        if path is None or not path.exists():
            print(f"skip {source}: no file (download it with kagglehub, or pass --{source.split('_')[0]})")
            continue
        loaded[source] = read(path, source, tally)
        print(f"{source}: {len(loaded[source]):,} records from {path}")

    with Session(engine) as session:
        for source, records in loaded.items():
            session.exec(delete(HistoricTicket).where(HistoricTicket.source == source))
            for i in range(0, len(records), CHUNK):
                session.exec(insert(HistoricTicket), params=records[i:i + CHUNK])
        session.commit()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    everything = [r for rs in loaded.values() for r in rs]
    if everything:
        with (out / "history.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(everything[0].keys()))
            writer.writeheader()
            for r in everything:
                writer.writerow({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()})

    report = {
        **tally.as_dict(),
        "loaded": {s: len(rs) for s, rs in loaded.items()},
        "ranges": {
            s: [min(r["opened_at"] for r in rs).isoformat(), max(r["opened_at"] for r in rs).isoformat()]
            for s, rs in loaded.items() if rs
        },
        "status": {s: dict(Counter(r["status"] for r in rs)) for s, rs in loaded.items()},
        "priority": {s: dict(Counter(r["recorded_priority"] for r in rs)) for s, rs in loaded.items()},
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: report[k] for k in ("loaded", "refused", "repaired")}, indent=2))
    return report


if __name__ == "__main__":
    main()
