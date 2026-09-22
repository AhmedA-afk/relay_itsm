"""Load API keys from .env files without a dependency, and never override the
real environment. Nearest file wins: backend/, then the use case folder, then
the workspace root where the keys live today."""

from __future__ import annotations

import os
from pathlib import Path

_HERE = Path(__file__).resolve().parent
CANDIDATES = (_HERE.parent / ".env", _HERE.parents[1] / ".env", _HERE.parents[2] / ".env")
_loaded = False


def load() -> None:
    global _loaded
    if _loaded:
        return
    for path in CANDIDATES:
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))
    _loaded = True


def key(*names: str) -> str | None:
    load()
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    return None
