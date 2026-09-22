"""Time, injected.

Nothing in the policy layer is allowed to call ``datetime.now()`` itself. Every
function that needs the time takes it as an argument, and the only object that
knows the real clock is the one wired up in ``main.py``. That is what makes SLA
behaviour an ordinary unit test instead of something you verify by waiting.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """The real clock. Used in the running app and nowhere in the tests."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FrozenClock:
    """A clock the tests move by hand."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock needs an aware datetime")
        self._at = at

    def now(self) -> datetime:
        return self._at

    def advance(self, **kwargs) -> "FrozenClock":
        self._at = self._at + timedelta(**kwargs)
        return self

    def set(self, at: datetime) -> "FrozenClock":
        self._at = at
        return self


def ensure_utc(value: datetime | None) -> datetime | None:
    """SQLite gives datetimes back without a timezone.

    Everything inside the app is aware UTC, and every datetime leaving over
    JSON has to carry its offset — a naive ISO string is read as *local* time by
    the browser, which would silently shift every clock in the interface.
    """
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def utc(*args) -> datetime:
    """Small helper so fixtures read as dates rather than as constructor noise."""
    return datetime(*args, tzinfo=timezone.utc)
