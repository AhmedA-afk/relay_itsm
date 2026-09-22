"""The traditional desk, the way most ITSM tools ship out of the box.

The right-hand lane of the Showcase. It models the default configuration of the
mainstream tools rather than any one vendor's product:

* **Intake is a form.** The caller writes a description and may pick an
  urgency. Impact is not the caller's to set; it sits at the form default
  until an agent triages the ticket.
* **Routing is an ordered list of keyword rules** on the description — the
  "if the description contains …, set category and assignment group" automation
  every tool offers. First match wins. No match falls to the service desk.
* **Priority is the impact × urgency lookup.** The same matrix Relay uses, so
  the comparison is about the inputs, not the arithmetic.
* **Assignment is a group queue.** The ticket waits until somebody takes it.
* **Deflection is keyword search** over the knowledge base.

The rules are the kind an administrator writes on day one and rarely revisits.
They have not been tuned against Relay's tickets in either direction.

Pure: no database, no clock. Every step returns what it decided, who or what
decided it, and why — the same shape the left-hand lane fills in.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Optional

# What the form puts in the fields nobody touches. "Affects just me" and
# "medium" are the out-of-the-box defaults across the common tools.
FORM_IMPACT = "individual"
FORM_URGENCY = "medium"

# Ordered. First rule whose any keyword appears in the text wins.
RULES: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    ("Network", ("vpn", "wifi", "wi-fi", "wireless", "network", "internet", "switch", "connect", "offline"),
     "Network / Connectivity", "network"),
    ("Access", ("password", "login", "log in", "locked", "access", "account", "permission", "mfa", "phishing",
                "leaver", "joiner", "offboard", "onboard"),
     "Identity / Access", "identity"),
    ("Hardware", ("laptop", "printer", "monitor", "keyboard", "mouse", "phone", "scanner", "screen", "device"),
     "Hardware / Device", "endpoint"),
    ("Applications", ("erp", "invoice", "report", "sap", "export", "application", "dashboard", "batch", "system"),
     "Software / Application", "erp_apps"),
    ("Facilities", ("badge", "desk", "room", "door", "building", "display", "chair"),
     "Facilities / Building", "facilities"),
)
FALLBACK = ("General / Other", "service_desk")


def _words(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9-]+", " ", text.lower()) + " "


def match_rule(text: str) -> tuple[Optional[str], Optional[str], str, str]:
    """(rule name, keyword that fired, category, team)."""
    haystack = _words(text)
    for name, keywords, category, team in RULES:
        for kw in keywords:
            if f" {kw} " in haystack or (" " in kw and kw in haystack):
                return name, kw, category, team
    return None, None, *FALLBACK


def keyword_overlap(query: str, articles: Iterable[Mapping], limit: int = 3) -> list[dict]:
    """Knowledge search by shared words. Also what the staff portal runs today,
    deliberately, so the difference a judgment model makes can be measured."""
    words = {w for w in query.lower().replace("/", " ").split() if len(w) > 2}
    hits = []
    for a in articles:
        score = len(words & set(str(a["keywords"]).split()))
        if score:
            hits.append({**{k: a[k] for k in ("id", "title", "body", "state") if k in a}, "score": score})
    hits.sort(key=lambda h: -h["score"])
    return hits[:limit]


def decide(text: str, caller_urgency: Optional[str] = None) -> dict:
    """Everything the traditional desk settles before a person reads the ticket."""
    rule, keyword, category, team = match_rule(text)
    urgency = caller_urgency or FORM_URGENCY
    return {
        "category": {
            "value": category, "by": "rule" if rule else "default",
            "reason": f"the {rule} rule fired on “{keyword}”" if rule
            else "no keyword rule matched, so the form's catch-all category stays",
        },
        "impact": {
            "value": FORM_IMPACT, "by": "form default",
            "reason": "callers cannot set impact; it stays at “affects just me” until an agent triages",
        },
        "urgency": {
            "value": urgency, "by": "caller" if caller_urgency else "form default",
            "reason": "picked by the caller on the form" if caller_urgency
            else "the caller left the urgency field at its default",
        },
        "team": {
            "value": team, "by": "rule" if rule else "default",
            "reason": f"the same rule sets the assignment group to {team}" if rule
            else "unmatched tickets land in the service desk triage queue",
        },
        "person": {
            "value": None, "by": "queue",
            "reason": f"waits in the {team} queue until someone takes it",
        },
        "effort": {
            "caller_fields": 2 if caller_urgency else 1,
            "touches_before_work": 2,     # triage sets impact, then someone picks it up
        },
    }
