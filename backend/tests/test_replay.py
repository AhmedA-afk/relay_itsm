"""Replay against a throwaway database: routing must see the roster as the app does."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from relay import replay
from relay.clock import FrozenClock, utc
from relay.models import HistoricTicket, Technician, Ticket
from relay.seed import seed


def test_replay_never_hands_work_to_someone_on_leave():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    now = utc(2026, 9, 18, 14, 0)
    with Session(engine) as s:
        seed(s, FrozenClock(now))
        away = {t.id for t in s.exec(select(Technician)).all() if t.on_leave}
        assert away, "the seeded roster should have someone on leave"
        cut, _ = replay.history.weeks_back(now, replay.DEFAULT_AT)
        for n in range(30):   # thirty open requests: first line takes them all
            s.add(HistoricTicket(
                id=f"abc_tech:IM{n:07d}", source="abc_tech", source_id=f"IM{n:07d}", kind="request",
                subject="Laptop information request on LAP000001", category="Computer / Laptop",
                impact="individual", urgency="low", recorded_priority="P4",
                opened_at=cut - timedelta(hours=2), resolved_at=cut + timedelta(hours=5),
            ))
        s.commit()
        out = replay.replay(s, now, replay.DEFAULT_AT, every=1)
        assert out["open"] == 30
        held = {t.assignee_id for t in s.exec(select(Ticket).where(Ticket.id.startswith("IM"))).all()}
        assert held and not (held & away)
