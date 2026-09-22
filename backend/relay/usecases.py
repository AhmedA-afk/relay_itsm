"""The Showcase's use cases: one decision, two ways of making it.

Each use case says what is being decided, why it matters on a service desk, and
how each lane asks for it. **Mine** asks Jev a typed question. **Traditional**
asks a general-purpose LLM in a prompt and parses the JSON it writes back —
the way AI features in ITSM tools are usually built today.

Both lanes get the same definitions word for word, so a difference in answer is
a difference in the model, not in what it was told. Add a use case by adding an
entry to ``USE_CASES``; the screen builds itself from it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from . import ai, policy, traditional

# ---------------------------------------------------------------- 1. category

KIND_DEFS = {
    "incident": {
        "what": "Something that should work is broken, failing, degraded or unavailable: an unplanned "
                "interruption to an IT service, or a drop in its quality.",
        "not_for": "Asking for something new to be provided, access, information or a pre-approved change.",
        "examples": ["VPN keeps dropping every twenty minutes", "Label printer prints blank labels"],
    },
    "service_request": {
        "what": "A request for something to be provided: access, new equipment or software, information, "
                "advice, or a standard pre-approved change. Nothing is broken.",
        "not_for": "Reporting a failure, an error or an outage.",
        "examples": ["Need access to the finance shared drive", "New laptop for a starter on Monday"],
    },
}
KIND_LABELS = {"incident": "Incident", "service_request": "Service request"}
KIND_QUESTION = "Is this IT service desk ticket an incident or a service request?"


def _kind_mine(text: str, ctx: dict) -> ai.Measured:
    return ai.jev_choice(
        state={"ticket": {"subject": text}},
        question_id="kind",
        question={
            "type": "choice",
            "instructions": f"{KIND_QUESTION} Judge from `ticket.subject`, which is what the requester typed.",
            "criteria": KIND_DEFS,
        },
    )


def _kind_traditional(text: str, ctx: dict) -> ai.Measured:
    defs = "\n".join(
        f"- {k}: {v['what']} Not for: {v['not_for']} Examples: {'; '.join(v['examples'])}."
        for k, v in KIND_DEFS.items()
    )
    system = (
        "You classify IT service desk tickets.\n"
        f"{KIND_QUESTION}\n\nCategories:\n{defs}\n\n"
        "Answer with JSON only, in the form {\"category\": \"incident\"} or {\"category\": \"service_request\"}."
    )
    schema = {
        "type": "OBJECT",
        "properties": {"category": {"type": "STRING", "enum": list(KIND_DEFS)}},
        "required": ["category"],
    }
    return ai.gemini_json(system, f"Ticket subject: {text}", schema, answer_field="category")


# ---------------------------------------------------------------- 4. priority
#
# Relay never lets anyone, person or model, pick a priority directly. Priority
# is impact × urgency read out of the matrix in Administration. So both lanes
# are asked for impact and urgency against the same definitions, and the
# matrix is the live one, edits included.

IMPACT_DEFS = {
    "organization": "The whole organisation, or a service everyone relies on: every site, every customer, "
                    "revenue or safety at stake.",
    "department": "A whole department or site, or a service one department depends on: all of Finance, "
                  "one depot, every invoice.",
    "team": "A team or group: a few people, one office or bay, several devices.",
    "individual": "One person or one device.",
}
URGENCY_DEFS = {
    "critical": "Work has stopped or harm is happening now: money, safety, customers or a deadline within hours.",
    "high": "Work is badly slowed or about to stop, with no workaround, or a deadline within a day.",
    "medium": "Work goes on with a workaround or an inconvenience; it needs fixing within days.",
    "low": "No real effect on work yet: a question, a request, something cosmetic. It can wait.",
}
PRIORITY_LABELS = {"P1": "P1 · Critical", "P2": "P2 · High", "P3": "P3 · Moderate", "P4": "P4 · Low"}


def _matrix(ctx: dict) -> dict:
    return ctx.get("matrix") or policy.DEFAULT_MATRIX


def level_distribution(matrix: dict, impact_p: dict, urgency_p: dict) -> dict:
    """Probability of each level, pushing both distributions through the
    matrix cell by cell. Treats impact and urgency as independent, which is
    how the matrix treats them."""
    out = {p: 0.0 for p in policy.PRIORITIES}
    for i, pi in impact_p.items():
        for u, pu in urgency_p.items():
            if i in matrix and u in matrix[i]:
                out[matrix[i][u]] += pi * pu
    return {k: round(v, 4) for k, v in out.items()}


def _matrix_text(matrix: dict) -> str:
    rows = ["impact \\ urgency | " + " | ".join(policy.URGENCIES)]
    rows += [f"{i} | " + " | ".join(matrix[i][u] for u in policy.URGENCIES) for i in policy.IMPACTS]
    return "\n".join(rows)


def _priority_mine(text: str, ctx: dict) -> ai.Measured:
    matrix = _matrix(ctx)
    m = ai.jev_ask(
        state={"ticket": {"subject": text}},
        questions={
            "impact": {"type": "choice", "criteria": IMPACT_DEFS,
                       "instructions": "How widely does the problem in `ticket.subject` reach? Judge who and what "
                                       "is affected, not how upset the requester sounds."},
            "urgency": {"type": "choice", "criteria": URGENCY_DEFS,
                        "instructions": "How soon does the problem in `ticket.subject` hurt the work? Judge how "
                                        "fast the harm arrives and whether there is a workaround."},
        },
    )
    answers = m.detail.get("answers", {})
    imp, urg = answers.get("impact"), answers.get("urgency")
    if m.error or not imp or not urg:
        m.error = m.error or "Jev did not answer both questions"
        return m
    level = matrix[imp["choice"]][urg["choice"]]
    m.answer = level
    m.probabilities = level_distribution(matrix, imp["probabilities"], urg["probabilities"])
    m.confidence = m.probabilities.get(level)
    # Each chip carries the probability of the option chosen, not Jev's
    # confidence figure, which describes how concentrated the whole
    # distribution is and would read as the wrong number beside one option.
    m.detail["parts"] = [
        {"label": "Impact", "value": imp["choice"], "probability": imp["probabilities"].get(imp["choice"])},
        {"label": "Urgency", "value": urg["choice"], "probability": urg["probabilities"].get(urg["choice"])},
    ]
    m.detail["note"] = f"{imp['choice']} against {urg['choice']} in the matrix gives {level}"
    # The level is the matrix cell of the two chosen answers, as for every
    # ticket in Relay. When the probability pushed through the matrix leans
    # elsewhere, or barely backs the cell, say so rather than hide it.
    rival = max((k for k in m.probabilities if k != level), key=m.probabilities.get)
    if m.probabilities[rival] >= m.probabilities[level] or m.probabilities[level] < 0.6:
        m.detail["close_call"] = {"level": rival, "probability": m.probabilities[rival]}
    return m


def _priority_traditional(text: str, ctx: dict) -> ai.Measured:
    matrix = _matrix(ctx)
    defs = lambda d: "\n".join(f"- {k}: {v}" for k, v in d.items())  # noqa: E731
    system = (
        "You set the priority of IT service desk tickets from what the requester wrote.\n\n"
        "Impact, how widely the problem reaches. Judge who and what is affected, not how upset the "
        f"requester sounds:\n{defs(IMPACT_DEFS)}\n\n"
        "Urgency, how soon it hurts the work. Judge how fast the harm arrives and whether there is a "
        f"workaround:\n{defs(URGENCY_DEFS)}\n\n"
        f"Priority is read from this matrix, P1 highest and P4 lowest:\n{_matrix_text(matrix)}\n\n"
        "Decide impact and urgency, then read the priority from the matrix. "
        "Answer with JSON only: {\"impact\": ..., \"urgency\": ..., \"priority\": ...}."
    )
    schema = {
        "type": "OBJECT",
        "properties": {
            "impact": {"type": "STRING", "enum": list(IMPACT_DEFS)},
            "urgency": {"type": "STRING", "enum": list(URGENCY_DEFS)},
            "priority": {"type": "STRING", "enum": list(policy.PRIORITIES)},
        },
        "required": ["impact", "urgency", "priority"],
        "propertyOrdering": ["impact", "urgency", "priority"],
    }
    m = ai.gemini_json(system, f"Ticket subject: {text}", schema, answer_field="priority")
    parsed = m.detail.get("parsed") or {}
    imp, urg = parsed.get("impact"), parsed.get("urgency")
    if imp in matrix and urg in matrix.get(imp, {}):
        expected = matrix[imp][urg]
        m.detail["parts"] = [{"label": "Impact", "value": imp}, {"label": "Urgency", "value": urg}]
        m.detail["consistent"] = expected == m.answer
        m.detail["note"] = (f"{imp} against {urg} in the matrix gives {expected}"
                            + ("" if expected == m.answer else f", but it answered {m.answer}"))
    return m


def _priority_legend(ctx: dict) -> dict:
    rules = {r.priority: r for r in (ctx.get("rules") or policy.DEFAULT_SLA_RULES)}
    out = {}
    for p in policy.PRIORITIES:
        r = rules.get(p)
        if r:
            span = f"{r.resolution_minutes // 60} hours" if r.calendar == "always" else f"{r.resolution_minutes // 720} working days"
            out[p] = f"fixed within {span}"
    return out


# What a form puts in the fields nobody touches: "affects just me", "medium".
FORM_DEFAULTS = {"impact": "individual", "urgency": "medium"}


# ---------------------------------------------------------------- 2. risk and 3. impact
#
# Two single judgments, each asked the same way of every lane. Risk is the
# business exposure an issue carries; impact is how widely it reaches, with the
# same definitions priority uses, so the two use cases can be read together.

RISK_DEFS = {
    "critical": "Harm or exposure happening now: a security breach or ransomware, customer or personal data "
                "exposed, money moving wrongly, a safety hazard, or a legal or regulatory breach.",
    "high": "A credible threat of that harm if nothing is done soon: a phishing link clicked, suspicious "
            "access, failed payments or backups, a compliance deadline at risk, customers about to be affected.",
    "medium": "Some business exposure but contained: internal only, a workaround exists, no sensitive data or "
              "money involved, though it would grow if ignored.",
    "low": "No meaningful exposure: an inconvenience, a question, a routine request or a cosmetic fault.",
}
RISK_LABELS = {"critical": "Critical risk", "high": "High risk", "medium": "Medium risk", "low": "Low risk"}
RISK_QUESTION = ("How much business risk does the issue in `ticket.subject` carry: exposure to security, data, "
                 "money, compliance, safety or customers? Judge the exposure, not how annoyed the requester is.")
IMPACT_LABELS = {"organization": "Organisation", "department": "Department", "team": "Team", "individual": "Individual"}
IMPACT_QUESTION = ("How widely does the problem in `ticket.subject` reach? Judge who and what is affected, "
                   "not how upset the requester sounds.")


def _defs_text(criteria: dict) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in criteria.items())


def _one_jev(qid: str, question: str, criteria: dict):
    def run(text: str, ctx: dict) -> ai.Measured:
        return ai.jev_choice({"ticket": {"subject": text}}, qid,
                             {"type": "choice", "instructions": question, "criteria": criteria})
    return run


def _one_ai(field_name: str, question: str, criteria: dict, what: str):
    """The same question for Gemini: definitions in the prompt, the answer
    constrained to the same options, parsed from the JSON it writes."""
    def run(text: str, ctx: dict) -> ai.Measured:
        system = (
            f"You assess IT service desk tickets from what the requester wrote.\n"
            f"{question.replace('`ticket.subject`', 'the ticket')}\n\n{what}:\n{_defs_text(criteria)}\n\n"
            f'Answer with JSON only: {{"{field_name}": ...}}.'
        )
        schema = {"type": "OBJECT", "properties": {field_name: {"type": "STRING", "enum": list(criteria)}},
                  "required": [field_name]}
        return ai.gemini_json(system, f"Ticket subject: {text}", schema, answer_field=field_name)
    return run


# Traditional risk: the ordered keyword rules an administrator writes once.
# First match wins; nothing matched means low. Plausible rules, not tuned
# against the examples in either direction.
RISK_RULES = (
    ("critical", ("breach", "ransomware", "hacked", "virus", "malware", "leak", "leaked", "fraud", "fire",
                  "injury", "gdpr")),
    ("high", ("phishing", "suspicious", "password", "payment", "invoice", "payroll", "backup", "customer",
              "security", "compliance", "audit")),
    ("medium", ("down", "outage", "failed", "error", "crash", "slow", "not working", "broken")),
)


def _risk_rules(text: str, ctx: dict) -> ai.Measured:
    started = time.perf_counter()
    words = " " + "".join(c if c.isalnum() else " " for c in text.lower()) + " "
    hit = next(((level, kw) for level, kws in RISK_RULES for kw in kws if f" {kw} " in words), None)
    m = ai.Measured(provider="Relay", model="keyword rules", price={"input": 0, "output": 0, "source": "no model"})
    m.answer = hit[0] if hit else "low"
    m.detail = {
        "parts": [{"label": "Rule", "value": f"{hit[0]} ← “{hit[1]}”" if hit else "none matched", "by": "rule" if hit else "default"}],
        "note": (f"The {hit[0]} rule fired on the word “{hit[1]}”. First match wins." if hit
                 else "No keyword matched, so it falls to low."),
    }
    m.request = {"rules": [{"level": l, "keywords": list(k)} for l, k in RISK_RULES], "fallback": "low"}
    m.latency_ms = round((time.perf_counter() - started) * 1000, 3)
    return m


def _form_lane(fields: tuple[str, ...], derive):
    """A form the caller fills in, no model. ``derive`` turns the filled form
    into an answer and a note; a field left alone keeps the form's default."""
    def run(text: str, ctx: dict) -> ai.Measured:
        started = time.perf_counter()
        given = {k: v for k, v in (ctx.get("form") or {}).items() if k in fields and v}
        form = {k: given.get(k, FORM_DEFAULTS[k]) for k in fields}
        m = ai.Measured(provider="Relay", model="form", price={"input": 0, "output": 0, "source": "no model"})
        try:
            m.answer, note = derive(form, ctx)
        except KeyError as exc:
            m.error = f"the form has no value {exc}"
            return m
        m.detail = {
            # a value equal to the default is indistinguishable from one nobody touched
            "parts": [{"label": k.capitalize(), "value": form[k],
                       "by": "form default" if form[k] == FORM_DEFAULTS[k] else "caller"} for k in fields],
            "note": note + " The words are never read.",
            "form": form,
        }
        m.request = {"form": form}
        m.latency_ms = round((time.perf_counter() - started) * 1000, 3)
        return m
    return run


def _impact_from_form(form: dict, ctx: dict):
    return form["impact"], f"The caller set impact to {form['impact']}."


def _priority_from_form(form: dict, ctx: dict):
    level = _matrix(ctx)[form["impact"]][form["urgency"]]
    return level, f"{form['impact']} against {form['urgency']} in the matrix gives {level}."



# ------------------------------------------------- 5. department and 6. person
#
# Routing, split the way the domain model splits it: which department's domain
# is this, then who on it. The first question reads the ticket; the second has
# always been answered by counting, which is exactly what makes it worth
# putting to a judgment as well.
#
# Both use cases build their options from the live roster in Administration —
# add a department or a person there and it appears as an option here, in every
# lane, with no code change.

TEAM_QUESTION = ("Which department's domain does the ticket in `ticket.subject` belong to? Judge what the work "
                 "actually is, not which words appear in it.")
PERSON_QUESTION = ("Who should this ticket go to? Weigh what the work in `ticket.subject` needs against what each "
                   "person is good at, then against how much they are already carrying. A person who fits the work "
                   "beats a person who is merely free, but do not pile work on someone already over capacity when "
                   "a colleague can do the job.")


def _teams(ctx: dict) -> list[dict]:
    return ctx.get("teams") or []


def _roster(ctx: dict) -> list[dict]:
    """Only people who could actually take the ticket.

    Availability is not a judgment: leave is a fact in Administration, so code
    removes those people before anyone is asked. The model is asked the part
    that needs reading — who fits this work — and never gets the chance to
    hand a ticket to someone who is away.
    """
    return [p for p in (ctx.get("roster") or []) if not p.get("on_leave")]


def _team_criteria(ctx: dict) -> dict:
    return {
        t["key"]: (f"{t['domain']}." + (f" Typically handles: {', '.join(t['skills'])}." if t.get("skills") else ""))
        for t in _teams(ctx)
    }


def _person_criteria(ctx: dict) -> dict:
    out = {}
    for p in _roster(ctx):
        skills = ", ".join(p.get("skills") or []) or "no skills recorded"
        out[p["id"]] = (
            f"{p['name']}, {p['tier'].lower()} on {p['team_name']}. Good at: {skills}. "
            f"Currently carrying {p['open_tickets']} open tickets of a normal load of {p['capacity']}"
            + (f", based at {p['location']}." if p.get("location") else ".")
        )
    return out


def _team_labels(ctx: dict) -> dict:
    return {t["key"]: t["name"] for t in _teams(ctx)}


def _person_labels(ctx: dict) -> dict:
    return {p["id"]: p["name"] for p in (ctx.get("roster") or [])}


def _person_teams(ctx: dict) -> dict:
    """Which department each answer belongs to, so two lanes naming different
    people can still be reported as agreeing about the department."""
    return {p["id"]: p["team"] for p in (ctx.get("roster") or [])}


def _no_options(m: ai.Measured, what: str) -> ai.Measured:
    m.error = f"no {what} configured; add some under Oversight to run this"
    return m


def _team_jev(text: str, ctx: dict) -> ai.Measured:
    criteria = _team_criteria(ctx)
    if not criteria:
        return _no_options(ai.Measured(provider="TypeSafe", model=ai.JEV_MODEL), "departments")
    m = ai.jev_choice({"ticket": {"subject": text}}, "team",
                      {"type": "choice", "instructions": TEAM_QUESTION, "criteria": criteria})
    if m.answer:
        m.detail["note"] = f"{_team_labels(ctx).get(m.answer, m.answer)} owns this work."
    return m


def _team_ai(text: str, ctx: dict) -> ai.Measured:
    criteria = _team_criteria(ctx)
    if not criteria:
        return _no_options(ai.Measured(provider="Google", model=ai.GEMINI_MODEL), "departments")
    system = (
        "You route IT service desk tickets to the department that owns the work.\n"
        f"{TEAM_QUESTION.replace('`ticket.subject`', 'the ticket')}\n\nDepartments:\n{_defs_text(criteria)}\n\n"
        'Answer with JSON only: {"team": ...}.'
    )
    schema = {"type": "OBJECT", "properties": {"team": {"type": "STRING", "enum": list(criteria)}},
              "required": ["team"]}
    return ai.gemini_json(system, f"Ticket subject: {text}", schema, answer_field="team")


def _team_rules(text: str, ctx: dict) -> ai.Measured:
    """The assignment-group automation every ITSM tool ships with: an ordered
    list of keyword rules over the description, first match wins, no match
    falls to the service desk."""
    started = time.perf_counter()
    rule, keyword, category, team = traditional.match_rule(text)
    m = ai.Measured(provider="Relay", model="keyword rules",
                    price={"input": 0, "output": 0, "source": "no model"})
    m.answer = team
    known = _team_labels(ctx)
    m.detail = {
        "parts": [{"label": "Rule", "value": f"{rule} ← “{keyword}”" if rule else "none matched",
                   "by": "rule" if rule else "default"},
                  {"label": "Category", "value": category, "by": "rule" if rule else "default"}],
        "note": (f"The {rule} rule fired on the word “{keyword}” and sets the assignment group. First match wins."
                 if rule else "No keyword rule matched, so it lands in the service desk triage queue."),
    }
    if known and team not in known:
        # the rules name teams in code; a department renamed in Oversight is a
        # real failure mode of keyword automation, so say it rather than hide it
        m.detail["note"] += f" The rule names “{team}”, which is not a department any more."
    m.request = {"rules": [{"group": r[0], "keywords": list(r[1]), "team": r[3]} for r in traditional.RULES],
                 "fallback": traditional.FALLBACK[1]}
    m.latency_ms = round((time.perf_counter() - started) * 1000, 3)
    return m


def _person_note(person: dict) -> str:
    return (f"{person['name']} is {person['tier'].lower()} on {person['team_name']}, "
            f"carrying {person['open_tickets']} of {person['capacity']}.")


def _least_loaded(pool: list[dict]) -> dict | None:
    """Fewest open tickets, ties broken by id so the answer is stable."""
    return min(pool, key=lambda p: (p["open_tickets"], p["id"])) if pool else None


def _person_jev(text: str, ctx: dict) -> ai.Measured:
    criteria = _person_criteria(ctx)
    if not criteria:
        return _no_options(ai.Measured(provider="TypeSafe", model=ai.JEV_MODEL), "people")
    m = ai.jev_choice({"ticket": {"subject": text}}, "assignee",
                      {"type": "choice", "instructions": PERSON_QUESTION, "criteria": criteria})
    by_id = {p["id"]: p for p in _roster(ctx)}
    person = by_id.get(m.answer)
    if person:
        m.detail["parts"] = [
            {"label": "Department", "value": person["team_name"]},
            {"label": "Carrying", "value": f"{person['open_tickets']} of {person['capacity']}"},
        ]
        m.detail["note"] = _person_note(person)
        # The comparison worth seeing is not whether it picked someone, but
        # whether reading the ticket moved the answer off the counter's answer.
        counted = _least_loaded([p for p in _roster(ctx) if p["team"] == person["team"]])
        if counted and counted["id"] != person["id"]:
            m.detail["instead_of"] = {
                "id": counted["id"], "name": counted["name"],
                "why": f"least-loaded on {person['team_name']} is {counted['name']} "
                       f"at {counted['open_tickets']} of {counted['capacity']}",
            }
    return m


def _person_ai(text: str, ctx: dict) -> ai.Measured:
    criteria = _person_criteria(ctx)
    if not criteria:
        return _no_options(ai.Measured(provider="Google", model=ai.GEMINI_MODEL), "people")
    system = (
        "You assign IT service desk tickets to the person who should do the work.\n"
        f"{PERSON_QUESTION.replace('`ticket.subject`', 'the ticket')}\n\nThe people available:\n"
        f"{_defs_text(criteria)}\n\n"
        'Answer with JSON only: {"assignee": ...}, using the identifier on the left.'
    )
    schema = {"type": "OBJECT", "properties": {"assignee": {"type": "STRING", "enum": list(criteria)}},
              "required": ["assignee"]}
    m = ai.gemini_json(system, f"Ticket subject: {text}", schema, answer_field="assignee")
    person = {p["id"]: p for p in _roster(ctx)}.get(m.answer)
    if person:
        m.detail["parts"] = [
            {"label": "Department", "value": person["team_name"]},
            {"label": "Carrying", "value": f"{person['open_tickets']} of {person['capacity']}"},
        ]
        m.detail["note"] = _person_note(person)
    return m


def _person_queue(text: str, ctx: dict) -> ai.Measured:
    """What the tools do today: a keyword rule picks the group, then the person
    is whoever on it has fewest open tickets. Nothing about the person is read.

    When the department is already settled — which is the case when this runs
    inside a routing decision rather than on its own in the Showcase — the
    keyword step is skipped and only the counting is left. That is the honest
    split: the rule is the group's answer, the counter is the person's.
    """
    started = time.perf_counter()
    settled = ctx.get("team")
    if settled:
        rule, keyword, team = None, None, settled
        how = f"The department is already {team}."
    else:
        rule, keyword, _category, team = traditional.match_rule(text)
        how = (f"The {rule} rule fired on “{keyword}” and sends it to {team}." if rule
               else f"No keyword rule matched, so it goes to {team}.")
    m = ai.Measured(provider="Relay", model="rules and a counter",
                    price={"input": 0, "output": 0, "source": "no model"})
    pool = [p for p in _roster(ctx) if p["team"] == team]
    pick = _least_loaded(pool)
    if pick is None:
        m.error = f"nobody available on {team}"
        m.latency_ms = round((time.perf_counter() - started) * 1000, 3)
        return m
    m.answer = pick["id"]
    m.detail = {
        "parts": [
            {"label": "Group", "value": team, "by": "settled" if settled else ("rule" if rule else "default")},
            {"label": "Picked", "value": f"{pick['open_tickets']} of {pick['capacity']} open", "by": "counting"},
        ],
        "note": (f"{how} Within the group the fewest open tickets wins, which is {pick['name']} "
                 f"at {pick['open_tickets']}. What they are good at is never read."),
    }
    m.request = {"group": team, "matched": keyword, "strategy": "least_loaded",
                 "pool": [{"id": p["id"], "open_tickets": p["open_tickets"]} for p in pool]}
    m.latency_ms = round((time.perf_counter() - started) * 1000, 3)
    return m



# ---------------------------------------------------------------- 7. sentiment
#
# The first use case that is a Score rather than a Choice, and the reason the
# distinction matters: satisfaction is a position on a spectrum, not one of a
# set of options. A Score's levels are an ordered array and the answer can land
# *between* two of them — 2.4 is a real answer, and it means something a Choice
# could not say.
#
# The levels are written to be judged one at a time, each on its own against
# the words, because that is how the model reads them.

SENTIMENT_LEVELS = [
    "Angry. They are complaining about the service or the wait itself, not only about the fault: "
    "threatening to escalate, going over someone's head, saying this is unacceptable or that they have "
    "been let down.",
    "Unhappy. Visible frustration with how it is going: chasing, repeating themselves, pointing out how "
    "long it has been, saying nobody has come back to them, or blaming a missed deadline on the delay.",
    "Neutral. Stating what is wrong or what they need, plainly. No feeling either way — most tickets are "
    "written like this the moment they are raised.",
    "Positive. Warm or easy to deal with: polite, patient, apologising for the bother, offering to help, "
    "saying there is no rush.",
    "Delighted. Explicit thanks or praise for the help they got, saying it was quick, or that someone "
    "went out of their way.",
]
# What the desk calls them. The array index is what Jev answers on; these are
# what everything above the model call speaks in.
SENTIMENT_SCALE = ("1", "2", "3", "4", "5")
SENTIMENT_LABELS = {"1": "1 · Angry", "2": "2 · Unhappy", "3": "3 · Neutral",
                    "4": "4 · Positive", "5": "5 · Delighted"}
SENTIMENT_LEGEND = {"1": "complaining about the service itself", "2": "chasing, and saying so",
                    "3": "stating it plainly", "4": "easy to deal with", "5": "thanks or praise"}
# 1 is the end that needs attention, so the scale reads most severe first, the
# same way risk and impact do.
SENTIMENT_ORDER = ("1", "2", "3", "4", "5")
SENTIMENT_QUESTION = ("How satisfied does the person sound in `ticket`? Judge the feeling in what they wrote "
                      "towards the service desk and how their request is going — not how bad the fault is, and "
                      "not how urgent it is. A calmly reported outage is neutral; a politely worded third chase "
                      "is not.")


def sentiment_state(text: str) -> dict:
    return {"ticket": {"subject": text}}


def _sentiment_jev(text: str, ctx: dict) -> ai.Measured:
    m = ai.jev_score(
        state=ctx.get("state") or sentiment_state(text),
        question_id="sentiment",
        question={"type": "score", "instructions": SENTIMENT_QUESTION, "criteria": SENTIMENT_LEVELS},
        labels=list(SENTIMENT_SCALE),
    )
    if m.error or m.score is None:
        return m
    # The continuous position is the whole point of a Score, so show it rather
    # than rounding it away: 2.4 is "unhappy, leaning neutral".
    m.detail["parts"] = [{"label": "On the scale", "value": f"{m.score + 1:.2f} of 5"}]
    ranked = sorted(m.probabilities.items(), key=lambda kv: -kv[1])
    near = ranked[:2]
    where = f"It sits at {m.score + 1:.2f}, nearest {SENTIMENT_LABELS[m.answer].lower()}"
    # The score is the weighted average of the levels, so it can land nearest a
    # level that is not the most likely one — a distribution split between 2 and
    # 4 averages to 3 while barely backing 3 at all. Saying which is which is
    # the difference between a number you can act on and one that misleads.
    if near[0][0] != m.answer:
        where += (f", but that is the average of a split answer: most of the weight, "
                  f"{round(near[0][1] * 100)}%, is on {SENTIMENT_LABELS[near[0][0]].lower()}")
    elif len(near) > 1 and near[1][1] >= 0.15:
        where += (f", with {round(near[1][1] * 100)}% of the weight on "
                  f"{SENTIMENT_LABELS[near[1][0]].lower()}")
    m.detail["note"] = where + "."
    # The same rule the priority lane uses, for the same reason: a level the
    # distribution barely backs should say so rather than present as settled.
    # On a Score it fires often on purpose — sentiment sits between levels far
    # more than a category does.
    # The rival is the likeliest level that is not the one being reported —
    # which, when the score landed between two levels, is not the same as the
    # runner-up overall.
    rival = next((k for k, _ in ranked if k != m.answer), None)
    if rival and (m.probabilities[m.answer] < 0.6 or m.probabilities[rival] >= m.probabilities[m.answer]):
        m.detail["close_call"] = {"level": rival, "probability": m.probabilities[rival]}
    return m


def _sentiment_ai(text: str, ctx: dict) -> ai.Measured:
    levels = "\n".join(f"- {i + 1}: {d}" for i, d in enumerate(SENTIMENT_LEVELS))
    system = (
        "You read IT service desk tickets and rate how satisfied the person sounds.\n"
        f"{SENTIMENT_QUESTION.replace('`ticket`', 'the ticket')}\n\n"
        f"Rate from 1, most unsatisfied, to 5, most satisfied:\n{levels}\n\n"
        'Answer with JSON only: {"sentiment": 3}, a whole number from 1 to 5.'
    )
    schema = {"type": "OBJECT", "properties": {"sentiment": {"type": "INTEGER"}}, "required": ["sentiment"]}
    body = ctx.get("prose") or f"Ticket subject: {text}"
    m = ai.gemini_json(system, body, schema, answer_field="sentiment")
    if m.answer is not None:
        # an integer from the JSON, but every lane's answer is a key
        m.answer = str(m.answer) if str(m.answer) in SENTIMENT_LABELS else None
        if m.answer is None:
            m.error = "Gemini answered outside 1 to 5"
        else:
            # An LLM gives one whole number: no position between levels, and no
            # distribution to threshold on. That absence is the comparison.
            m.detail["note"] = f"It answered {m.answer}, a whole number, with nothing either side of it."
    return m


# The pre-model way, and still the common one: two word lists and a subtraction.
# Not tuned against the examples in either direction.
SENTIMENT_WORDS = {
    -2: ("unacceptable", "appalling", "disgraceful", "furious", "livid", "escalate", "escalating",
         "complaint", "complain", "ridiculous", "useless", "incompetent", "shambles", "fed up"),
    -1: ("again", "still", "waiting", "nobody", "no one", "chasing", "chase", "slow", "delay", "delayed",
         "frustrated", "frustrating", "annoyed", "disappointed", "urgent", "asap", "third time"),
    1: ("please", "thanks", "thank", "kindly", "appreciate", "sorry", "whenever", "no rush", "happy to"),
    2: ("brilliant", "excellent", "fantastic", "wonderful", "lifesaver", "superb", "grateful", "perfect"),
}


def _sentiment_lexicon(text: str, ctx: dict) -> ai.Measured:
    started = time.perf_counter()
    words = " " + "".join(c if c.isalnum() else " " for c in (ctx.get("prose") or text).lower()) + " "
    hits = [(w, weight) for weight, group in SENTIMENT_WORDS.items() for w in group
            if f" {w} " in words or (" " in w and w in words)]
    total = sum(weight for _, weight in hits)
    # net weight to a level, the usual banding
    level = "1" if total <= -3 else "2" if total <= -1 else "3" if total == 0 else "4" if total <= 2 else "5"
    m = ai.Measured(provider="Relay", model="word lists",
                    price={"input": 0, "output": 0, "source": "no model"})
    m.answer = level
    m.detail = {
        "parts": [{"label": "Net", "value": f"{total:+d} from {len(hits)} words" if hits else "no words matched",
                   "by": "word list" if hits else "default"}],
        "note": ((f"Matched {', '.join(f'“{w}”' for w, _ in hits[:4])}"
                  + (f" and {len(hits) - 4} more" if len(hits) > 4 else "")
                  + f", netting {total:+d}, which bands to {level}.")
                 if hits else "No word in either list appeared, so it falls to neutral.")
        + " It counts words; it cannot tell a thank-you from a sarcastic one, and “urgent” reads as unhappy "
          "whoever wrote it.",
    }
    m.request = {"lists": {str(k): list(v) for k, v in SENTIMENT_WORDS.items()}, "net": total}
    m.latency_ms = round((time.perf_counter() - started) * 1000, 3)
    return m



# ------------------------------------------------------------- 8. escalation
#
# The first use case that predicts rather than reads. Every other one answers
# something already true in the words — what kind of ticket this is, how widely
# it reaches, how the person sounds. This one answers what has not happened
# yet, which is a different kind of claim and deserves a different shape: a
# Noul, whose whole answer is a probability, thresholded in ``policy`` where a
# service desk manager can move the line without touching a prompt.
#
# It is also the only use case given the clock. Sentiment is deliberately kept
# away from target burn so it cannot become a slower way of reading the SLA
# field; escalation is the opposite — a human predicting a blow-up uses the age,
# the burn, the reopens and the bounces along with the words, so withholding
# them would only make it predict worse.

ESCALATION_STATEMENT = (
    "This ticket will escalate before it is resolved: either it gets handed on to deeper expertise "
    "because whoever holds it cannot finish it, or somebody senior is pulled in — the requester goes "
    "over the desk's head, complains, or a manager starts asking about it."
)
ESCALATION_CRITERIA = {
    "true": "There are real signs of it: the requester is chasing, frustrated, naming a deadline or "
            "threatening to take it further; the work is beyond whoever has it; it has already bounced "
            "or been reopened; or it is heading past its target with nobody visibly on it.",
    "false": "It is going to finish where it is: routine work, a requester who is content or quiet, "
             "time still on the clock, and nothing that needs a second pair of hands.",
}
ESCALATION_LABELS = {"yes": "Will escalate", "no": "Will not"}
ESCALATION_ORDER = ("yes", "no")
ESCALATION_LEGEND = {"yes": f"at or over the {policy.ESCALATION_WATCH:.0%} watch line",
                     "no": "quiet, on the numbers so far"}


def escalation_state(text: str) -> dict:
    return {"ticket": {"subject": text}}


def _band(m: ai.Measured, probability: float) -> ai.Measured:
    """Attach the policy band and say which line it fell against."""
    decision = policy.escalation_band(probability)
    m.detail["band"] = decision.value
    m.detail["note"] = f"{decision.reason}."
    m.detail["parts"] = [
        {"label": "Risk", "value": f"{probability:.0%}"},
        {"label": "Band", "value": decision.value},
    ]
    return m


def _escalation_jev(text: str, ctx: dict) -> ai.Measured:
    m = ai.jev_noul(
        state=ctx.get("state") or escalation_state(text),
        question_id="escalation",
        question={"type": "noul", "instructions": ESCALATION_STATEMENT, "criteria": ESCALATION_CRITERIA},
        threshold=policy.ESCALATION_WATCH,
    )
    if m.error or m.noul is None:
        return m
    _band(m, m.noul)
    # A Noul has no confidence figure, and 0.5 means evens rather than unsure.
    # Saying so beside the number stops it being read as a weak Choice.
    m.detail["note"] += " A Noul answers with the probability itself, so there is no separate confidence to quote."
    return m


def _escalation_ai(text: str, ctx: dict) -> ai.Measured:
    system = (
        "You predict whether IT service desk tickets are going to escalate.\n\n"
        f"{ESCALATION_STATEMENT}\n\n"
        f"It is true when: {ESCALATION_CRITERIA['true']}\n"
        f"It is false when: {ESCALATION_CRITERIA['false']}\n\n"
        'Answer with JSON only: {"escalation_risk": 0.73}, a probability from 0 to 1 that it will escalate.'
    )
    schema = {"type": "OBJECT", "properties": {"escalation_risk": {"type": "NUMBER"}},
              "required": ["escalation_risk"]}
    body = ctx.get("prose") or f"Ticket subject: {text}"
    m = ai.gemini_json(system, body, schema, answer_field="escalation_risk")
    raw = m.answer
    if raw is None:
        return m
    try:
        probability = float(raw)
    except (TypeError, ValueError):
        m.answer, m.error = None, f"Gemini answered {raw!r}, which is not a probability"
        return m
    if not 0 <= probability <= 1:
        m.answer, m.error = None, f"Gemini answered {probability}, outside 0 to 1"
        return m
    m.noul = probability
    m.answer = "yes" if probability >= policy.ESCALATION_WATCH else "no"
    m.probabilities = {"yes": round(probability, 4), "no": round(1 - probability, 4)}
    _band(m, probability)
    return m


# The traditional lane: the SLA escalation rule every ITSM tool ships with.
SLA_RULES = (
    (0.80, "the target is 80% gone"),
    (0.50, "the target is half gone"),
)


def _escalation_sla(text: str, ctx: dict) -> ai.Measured:
    started = time.perf_counter()
    state = ctx.get("ticket_state") or {}
    burn = float(state.get("burn") or 0)
    reopened = int(state.get("reopened") or 0)
    reassignments = int(state.get("reassignments") or 0)
    breached = bool(state.get("breached"))

    fired = []
    if breached:
        fired.append("it is already past target")
    for at, why in SLA_RULES:
        if burn >= at:
            fired.append(why)
            break
    if reopened:
        fired.append(f"it has been reopened {reopened} time{'s' if reopened > 1 else ''}")
    if reassignments >= 2:
        fired.append(f"it has been reassigned {reassignments} times")

    # The usual shape: a rule either fired or it did not, so the answer is a
    # flag rather than a probability. That 0 or 1 is why it cannot be compared
    # with the other two lanes on anything finer than agreement.
    probability = 1.0 if fired else 0.0
    m = ai.Measured(provider="Relay", model="SLA rules",
                    price={"input": 0, "output": 0, "source": "no model"})
    m.noul = probability
    m.answer = "yes" if fired else "no"
    m.probabilities = {"yes": probability, "no": 1 - probability}
    _band(m, probability)
    m.detail["note"] = (("Flagged because " + ", and ".join(fired) + ".") if fired
                        else "No rule fired: the clock still has room and nothing has bounced.")
    m.detail["note"] += (" It reads the clock and the counters, never the words — so it cannot see a "
                         "blow-up coming until the target is nearly gone.")
    m.detail["parts"] = [
        {"label": "Burn", "value": f"{burn:.0%} of target", "by": "clock"},
        {"label": "Rules", "value": f"{len(fired)} fired" if fired else "none fired", "by": "clock"},
    ]
    m.request = {"thresholds": [r[0] for r in SLA_RULES], "burn": burn, "reopened": reopened,
                 "reassignments": reassignments, "breached": breached}
    m.latency_ms = round((time.perf_counter() - started) * 1000, 3)
    return m



# -------------------------------------------------------------- 9. duplicates
#
# The first use case where code does real work *before* the model is asked
# anything, and the shape is the point. Comparing a new ticket against a
# hundred open ones is a hundred comparisons; comparing it against the six a
# cheap filter kept is six. So ordinary code shortlists for recall — same
# department, recent, any word in common — and the judgment supplies the
# precision the filter cannot.
#
# It is also the fan-out: every candidate is a separate question, but they go
# in one request over one state, evaluated in parallel. Six candidates cost six
# questions and one round trip.
#
# And it refuses the flattening every ITSM tool makes. "Duplicate" is three
# different facts with three different consequences, and getting them confused
# is how a second reporter of a live outage gets their ticket closed and is
# never told when it is fixed.

DUPLICATE_OF_TICKET = {
    "same_request": "The same person asking for the same thing again, or the same ticket raised twice. "
                    "Nothing new is being reported. This one can be closed and pointed at the other.",
    "same_fault": "A different person hitting the same underlying fault. The report is genuine and new — "
                  "somebody else is affected and will need telling when it is fixed — but there is only "
                  "one thing to fix.",
    "unrelated": "A different issue. It may be in the same area, on the same system, or use similar "
                 "words, but fixing one would not fix the other.",
}
DUPLICATE_OF_PROBLEM = {
    "known_problem": "This ticket is another instance of that known problem. The cause is already "
                     "recorded and there may be a workaround to apply.",
    "unrelated": "A different issue from that problem, however similar the words look.",
}
DUPLICATE_LABELS = {
    "same_request": "Same request, raised twice",
    "same_fault": "Same fault, another reporter",
    "known_problem": "An instance of a known problem",
    "unrelated": "Unrelated",
}
DUPLICATE_ORDER = ("same_request", "same_fault", "known_problem", "unrelated")
DUPLICATE_LEGEND = {
    "same_request": "close it, pointing at the other",
    "same_fault": "link it to the parent and keep it open",
    "known_problem": "attach it to the problem record",
    "unrelated": "leave it alone",
}


def _candidates(ctx: dict) -> list[dict]:
    """What the shortlist kept. Each is {id, kind, subject, …}."""
    return ctx.get("candidates") or []


def _duplicate_question(candidate: dict) -> dict:
    """One Choice per candidate, with the options that can apply to its kind.

    A problem record cannot be "the same request raised twice", so it is not
    offered as an option. Asking a question whose answers include impossible
    ones invites one of them.
    """
    criteria = DUPLICATE_OF_PROBLEM if candidate["kind"] == "problem" else DUPLICATE_OF_TICKET
    what = "problem record" if candidate["kind"] == "problem" else "open ticket"
    return {
        "type": "choice",
        "instructions": (
            f"How does the new ticket in `ticket` relate to the {what} in `candidates.{candidate['id']}`? "
            "Judge whether they are the same underlying thing, not whether they use similar words or touch "
            "the same system."
        ),
        "criteria": criteria,
    }


def _blank(provider: str, model: str, message: str) -> ai.Measured:
    m = ai.Measured(provider=provider, model=model)
    m.error = message
    return m


# Whether two tickets are "the same person asking again" cannot be settled
# without knowing who raised each. On a live ticket Relay knows; on words typed
# into the Showcase there is nobody, and saying so is better than letting the
# question be answered on a fact that is not in evidence.
NO_REQUESTER = ("not recorded — this was typed in rather than raised, so whether it is the same "
                "person asking again cannot be established")


def _new_ticket_state(text: str, ctx: dict) -> dict:
    state = dict(ctx.get("subject_state") or {"subject": text})
    state.setdefault("raised_by", NO_REQUESTER)
    return state


def _duplicate_jev(text: str, ctx: dict) -> ai.Measured:
    candidates = _candidates(ctx)
    if not candidates:
        return _blank("TypeSafe", ai.JEV_MODEL, "nothing to compare against; the shortlist is empty")

    state = {
        "ticket": _new_ticket_state(text, ctx),
        "candidates": {c["id"]: {k: v for k, v in c.items() if k not in ("id", "kind")} for c in candidates},
    }
    m = ai.jev_choices(state, {c["id"]: _duplicate_question(c) for c in candidates})
    if m.error:
        return m

    found = []
    for candidate in candidates:
        answer = m.detail.get("choices", {}).get(candidate["id"])
        if not answer or answer["choice"] in (None, "unrelated"):
            continue
        found.append({
            "id": candidate["id"], "kind": candidate["kind"], "subject": candidate.get("subject", ""),
            "relation": answer["choice"],
            "probability": answer["probabilities"].get(answer["choice"]),
            "confidence": answer["confidence"],
        })
    # strongest first, so the interface's first row is the one to act on
    found.sort(key=lambda f: -(f["probability"] or 0))
    return _finish(m, found, len(candidates))


def _finish(m: ai.Measured, found: list[dict], asked: int) -> ai.Measured:
    m.detail["matches"] = found
    m.detail["asked"] = asked
    if not found:
        m.answer = "unrelated"
        m.detail["note"] = f"None of the {asked} shortlisted look like the same thing."
        return m
    best = found[0]
    m.answer = best["relation"]
    m.probabilities = None
    m.confidence = best.get("probability")
    m.detail["note"] = (f"{DUPLICATE_LABELS[best['relation']]}: {best['id']}"
                        + (f", {best['probability']:.0%}" if best.get("probability") else "")
                        + f". {asked} candidates compared in one request"
                        + (f", {len(found)} matched." if len(found) > 1 else "."))
    m.detail["parts"] = [{"label": DUPLICATE_LABELS[f["relation"]], "value": f["id"],
                          "probability": f.get("probability")} for f in found[:3]]
    return m


def _duplicate_ai(text: str, ctx: dict) -> ai.Measured:
    candidates = _candidates(ctx)
    if not candidates:
        return _blank("Google", ai.GEMINI_MODEL, "nothing to compare against; the shortlist is empty")

    listed = "\n".join(
        f"- {c['id']} ({'problem record' if c['kind'] == 'problem' else 'open ticket'}"
        + (f", raised by {c['raised_by']}" if c.get("raised_by") else "") + f"): {c.get('subject', '')}"
        + (f" — {c['detail']}" if c.get("detail") else "")
        for c in candidates
    )
    who = (ctx.get("subject_state") or {}).get("raised_by") or NO_REQUESTER
    system = (
        "You decide whether a new IT service desk ticket is the same underlying thing as something "
        "already on the desk. Judge whether they are the same underlying thing, not whether they use "
        "similar words or touch the same system.\n\n"
        "For an open ticket, the relationship is one of:\n"
        + "\n".join(f"- {k}: {v}" for k, v in DUPLICATE_OF_TICKET.items())
        + "\n\nFor a problem record it is one of:\n"
        + "\n".join(f"- {k}: {v}" for k, v in DUPLICATE_OF_PROBLEM.items())
        + '\n\nAnswer with JSON only: {"matches": [{"id": "INC-1234", "relation": "same_fault"}]}. '
          "Include only genuine matches; an empty list is the right answer when nothing matches."
    )
    schema = {
        "type": "OBJECT",
        "properties": {"matches": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"id": {"type": "STRING"}, "relation": {"type": "STRING",
                           "enum": ["same_request", "same_fault", "known_problem", "unrelated"]}},
            "required": ["id", "relation"]}}},
        "required": ["matches"],
    }
    m = ai.gemini_json(system, f"New ticket, raised by {who}: {text}\n\nAlready on the desk:\n{listed}",
                       schema, answer_field="matches")
    if m.error:
        return m
    by_id = {c["id"]: c for c in candidates}
    found = []
    for row in (m.detail.get("parsed") or {}).get("matches") or []:
        candidate = by_id.get(row.get("id"))
        if candidate is None or row.get("relation") in (None, "unrelated"):
            continue
        found.append({"id": candidate["id"], "kind": candidate["kind"],
                      "subject": candidate.get("subject", ""), "relation": row["relation"],
                      "probability": None, "confidence": None})
    return _finish(m, found, len(candidates))


def _duplicate_similar(text: str, ctx: dict) -> ai.Measured:
    """The "similar incidents" panel every ITSM tool ships: shared words, ranked.

    It is the same function the staff portal searches the knowledge base with,
    pointed at tickets instead of articles — which is the honest comparison,
    because it is the same mechanism.
    """
    started = time.perf_counter()
    candidates = _candidates(ctx)
    if not candidates:
        m = _blank("Relay", "word overlap", "nothing to compare against; the shortlist is empty")
        m.price = {"input": 0, "output": 0, "source": "no model"}
        return m

    words = {w for w in text.lower().replace("/", " ").split() if len(w) > 2}
    scored = []
    for candidate in candidates:
        against = {w for w in f"{candidate.get('subject', '')} {candidate.get('detail', '')}".lower().split()
                   if len(w) > 2}
        shared = words & against
        if shared:
            scored.append((len(shared), sorted(shared), candidate))
    scored.sort(key=lambda row: -row[0])

    m = ai.Measured(provider="Relay", model="word overlap",
                    price={"input": 0, "output": 0, "source": "no model"})
    # It can say two tickets look alike. It cannot say what that means, so
    # everything it finds is reported as the one verdict it has.
    found = [{"id": c["id"], "kind": c["kind"], "subject": c.get("subject", ""),
              "relation": "known_problem" if c["kind"] == "problem" else "same_request",
              "probability": None, "confidence": None, "shared": shared}
             for _, shared, c in scored[:3]]
    _finish(m, found, len(candidates))
    if found:
        top = scored[0]
        m.detail["note"] = (f"{top[2]['id']} shares {top[0]} word{'s' if top[0] > 1 else ''} with it "
                            f"({', '.join(top[1][:4])}).")
    m.detail["note"] += (" Shared words are all it has: it cannot tell the same request raised twice from "
                         "a second person hitting the same fault, so it calls everything a duplicate.")
    m.request = {"shortlisted": [c["id"] for c in candidates], "matched_on": "shared words"}
    m.latency_ms = round((time.perf_counter() - started) * 1000, 3)
    return m



# -------------------------------------------------------------- 10. deflection
#
# The only use case that runs before a ticket exists, and the only one whose
# success is a ticket that never gets raised. Everything else here decides what
# to do with work; this one decides whether there is any.
#
# The question is deliberately stronger than "is this article relevant". An
# article about the right system that does not answer *this* person's question
# is relevant and useless: they read it, it does not help, and they raise the
# ticket anyway having wasted two minutes. So the Noul asks whether reading it
# would actually leave them with nothing to ask.
#
# Which articles are even offered is code's call, not a judgment: an article
# the knowledge owner has marked stale or left in draft is a fact about the
# article, and showing it is a knowledge-management failure rather than a
# matching one. ``deflection.shortlist`` drops them and says how many it
# dropped, so the cost of a neglected knowledge base is visible instead of
# quietly degrading the answers.

DEFLECT_STATEMENT = ("Reading `articles.{id}` would solve the problem described in `question` — the person "
                     "could follow it themselves and would have no reason to raise a ticket.")
DEFLECT_CRITERIA = {
    "true": "The article covers this exact problem and tells them what to do about it. Somebody who "
            "read it would be able to fix it, or would find the answer they were looking for.",
    "false": "It is about a different problem, or the same area but a different fault, or it explains "
             "something adjacent without answering this. Following it would leave them still needing "
             "the desk.",
}
DEFLECT_LABELS = {"answer": "Would answer it", "suggest": "Might help", "quiet": "Nothing that helps"}
DEFLECT_ORDER = ("answer", "suggest", "quiet")
DEFLECT_LEGEND = {"answer": "lead with it; the ticket becomes the second option",
                  "suggest": "offer it above the form", "quiet": "say nothing and get out of the way"}


def _articles(ctx: dict) -> list[dict]:
    return ctx.get("articles") or []


def _deflect_finish(m: ai.Measured, found: list[dict], asked: int, held_back: int = 0) -> ai.Measured:
    found.sort(key=lambda h: -(h["probability"] or 0))
    # Only a live article can be offered; one that would have answered it and
    # has been left to rot is reported separately, because "nobody wrote this
    # down" and "somebody wrote it down and it went stale" are different
    # problems with different fixes.
    hits = [h for h in found if h.get("offerable", True)]
    rotting = [h for h in found if not h.get("offerable", True)]
    m.detail["hits"] = hits
    m.detail["rotting"] = rotting
    m.detail["asked"] = asked
    m.detail["held_back"] = held_back
    best = hits[0] if hits else None
    band = policy.deflection_band(best["probability"]).value if best and best["probability"] is not None \
        else ("suggest" if best else "quiet")
    m.answer = band
    m.confidence = best["probability"] if best else None
    rot_note = ""
    if rotting:
        top = rotting[0]
        rot_note = (f" {top['id']}, {top['title']}, would have answered it"
                    + (f" ({top['probability']:.0%})" if top["probability"] is not None else "")
                    + f" but is marked {top.get('state', 'stale').lower()}, so it is not offered.")
    elif held_back:
        rot_note = f" {held_back} were held back as stale or unpublished."
    if not best:
        m.detail["note"] = f"Nothing offerable answers this." + rot_note
        return m
    m.detail["note"] = (f"{best['id']}, {best['title']}"
                        + (f", {best['probability']:.0%}" if best["probability"] is not None else "")
                        + f". {asked} articles checked in one request." + rot_note)
    m.detail["parts"] = [{"label": h["id"], "value": h["title"][:44], "probability": h["probability"]}
                         for h in hits[:3]]
    return m


def _deflect_jev(text: str, ctx: dict) -> ai.Measured:
    articles = _articles(ctx)
    if not articles:
        return _blank("TypeSafe", ai.JEV_MODEL, "no live knowledge articles to check against")
    state = {
        "question": text,
        "articles": {a["id"]: {"title": a["title"], "says": a.get("body", "")} for a in articles},
    }
    questions = {
        a["id"]: {"type": "noul", "instructions": DEFLECT_STATEMENT.format(id=a["id"]),
                  "criteria": DEFLECT_CRITERIA}
        for a in articles
    }
    m = ai.jev_ask(state, questions)
    if m.error:
        return m
    hits = []
    for article in articles:
        answer = m.detail.get("answers", {}).get(article["id"]) or {}
        probability = answer.get("noul")
        if probability is None or probability < policy.DEFLECT_MAYBE:
            continue
        hits.append({"id": article["id"], "title": article["title"], "body": article.get("body", ""),
                     "probability": round(probability, 4),
                     "offerable": article.get("offerable", True), "state": article.get("state", "Live"),
                     "band": policy.deflection_band(probability).value})
    return _deflect_finish(m, hits, len(articles), ctx.get("held_back", 0))


def _deflect_ai(text: str, ctx: dict) -> ai.Measured:
    articles = _articles(ctx)
    if not articles:
        return _blank("Google", ai.GEMINI_MODEL, "no live knowledge articles to check against")
    listed = "\n".join(f"- {a['id']}: {a['title']} — {a.get('body', '')}" for a in articles)
    system = (
        "You decide whether anything in a knowledge base would stop somebody needing to raise an IT "
        "ticket.\n\nFor each article, judge whether reading it would solve their problem — they could "
        "follow it themselves and would have no reason to contact the desk.\n\n"
        f"It is true when: {DEFLECT_CRITERIA['true']}\n"
        f"It is false when: {DEFLECT_CRITERIA['false']}\n\n"
        'Answer with JSON only: {"articles": [{"id": "KB-0001", "probability": 0.82}]}, a probability '
        "from 0 to 1 for each article you think might help. An empty list is the right answer when "
        "nothing does."
    )
    schema = {"type": "OBJECT", "properties": {"articles": {"type": "ARRAY", "items": {
        "type": "OBJECT", "properties": {"id": {"type": "STRING"}, "probability": {"type": "NUMBER"}},
        "required": ["id", "probability"]}}}, "required": ["articles"]}
    m = ai.gemini_json(system, f"They typed: {text}\n\nThe knowledge base:\n{listed}", schema,
                       answer_field="articles")
    if m.error:
        return m
    by_id = {a["id"]: a for a in articles}
    hits = []
    for row in (m.detail.get("parsed") or {}).get("articles") or []:
        article = by_id.get(row.get("id"))
        probability = row.get("probability")
        if article is None or not isinstance(probability, (int, float)):
            continue
        if not 0 <= probability <= 1 or probability < policy.DEFLECT_MAYBE:
            continue
        hits.append({"id": article["id"], "title": article["title"], "body": article.get("body", ""),
                     "probability": round(float(probability), 4),
                     "offerable": article.get("offerable", True), "state": article.get("state", "Live"),
                     "band": policy.deflection_band(probability).value})
    return _deflect_finish(m, hits, len(articles), ctx.get("held_back", 0))


def _deflect_keywords(text: str, ctx: dict) -> ai.Measured:
    """What the staff portal runs today: shared words against each article's
    keyword list. Left deliberately dumb from the start so this comparison
    would mean something."""
    started = time.perf_counter()
    articles = _articles(ctx)
    m = ai.Measured(provider="Relay", model="keyword search",
                    price={"input": 0, "output": 0, "source": "no model"})
    if not articles:
        m.error = "no live knowledge articles to check against"
        return m
    found = traditional.keyword_overlap(text, [{**a, "keywords": a.get("keywords", "")} for a in articles],
                                        limit=3)
    by_id = {a["id"]: a for a in articles}
    hits = [{"id": h["id"], "title": h.get("title", ""), "body": h.get("body", ""),
             "probability": None, "band": "suggest", "score": h["score"],
             "offerable": by_id.get(h["id"], {}).get("offerable", True),
             "state": by_id.get(h["id"], {}).get("state", "Live")} for h in found]
    _deflect_finish(m, hits, len(articles), ctx.get("held_back", 0))
    if hits:
        m.detail["note"] = (f"{hits[0]['id']} shares {found[0]['score']} keyword"
                            f"{'s' if found[0]['score'] > 1 else ''} with what they typed.")
    m.detail["note"] += (" It matches words against a keyword list, so it cannot tell an article about "
                         "this fault from one about the same equipment — and it has no probability to "
                         "threshold, only an order.")
    m.request = {"checked": [a["id"] for a in articles], "matched_on": "keyword overlap"}
    m.latency_ms = round((time.perf_counter() - started) * 1000, 3)
    return m


# ---------------------------------------------------------------- the registry

@dataclass(frozen=True)
class Lane:
    key: str               # jev | ai | form | rules | matrix
    name: str              # what the screen calls it
    engine: str            # the model or mechanism underneath
    how: str
    run: Callable[[str, dict], ai.Measured] = field(repr=False)
    form: tuple[str, ...] = ()   # form fields this lane reads instead of the words
    caveat: str = ""             # the honest one-liner beside its comparison with Jev

    def describe(self) -> dict:
        model = {"jev": ai.JEV_MODEL, "ai": ai.GEMINI_MODEL}.get(self.key)
        price = {"jev": ai.PRICES["jev"], "ai": ai.PRICES[ai.GEMINI_MODEL]}.get(self.key, {"input": 0, "output": 0})
        return {"key": self.key, "name": self.name, "engine": self.engine, "model": model, "how": self.how,
                "price": price, "no_model": model is None, "caveat": self.caveat,
                "form": [{"key": f, "label": f"{f.capitalize()}, as the caller sets it",
                          "options": list(FORM_OPTIONS[f])} for f in self.form]}


FORM_OPTIONS = {"impact": IMPACT_DEFS, "urgency": URGENCY_DEFS}


@dataclass(frozen=True)
class UseCase:
    key: str
    title: str
    decision: str
    why: str
    # a fixed map for a fixed vocabulary; a function of ctx when the answers
    # are whatever is in Administration today, as routing's are
    labels: dict | Callable[[dict], dict]
    examples: tuple[str, ...]
    lanes: tuple[Lane, ...]
    order: tuple[str, ...] = ()    # answers from most to least severe, when they are a scale
    # a per-answer note for the screen, e.g. each priority's service target
    legend: Callable[[dict], dict] = field(default=lambda ctx: {}, repr=False)
    # which group each answer belongs to, so lanes naming two different people
    # can still be reported as agreeing about the department
    groups: Callable[[dict], dict] = field(default=lambda ctx: {}, repr=False)
    # context this use case cannot answer without, which the caller has to
    # build. Declared here rather than known by the HTTP layer, so the registry
    # stays the one place that describes a use case.
    needs: tuple[str, ...] = ()

    def lane(self, key: str) -> Lane | None:
        return next((l for l in self.lanes if l.key == key), None)

    def label_map(self, ctx: dict | None = None) -> dict:
        return self.labels(ctx or {}) if callable(self.labels) else self.labels

    def group_map(self, ctx: dict | None = None) -> dict:
        return self.groups(ctx or {})

    def describe(self, ctx: dict | None = None) -> dict:
        return {
            "key": self.key, "title": self.title, "decision": self.decision, "why": self.why,
            "labels": self.label_map(ctx), "examples": list(self.examples), "legend": self.legend(ctx or {}),
            "order": list(self.order), "lanes": [l.describe() for l in self.lanes],
            "groups": self.group_map(ctx), "form_defaults": FORM_DEFAULTS,
            "needs": list(self.needs),
        }


GEMINI_NAME = "Gemini 3.8 Flash"
FORM_CAVEAT = "Instant and free, but it never read the words: the answer is only as right as the form."

USE_CASES: dict[str, UseCase] = {
    "kind": UseCase(
        key="kind",
        title="Category: service request or incident",
        decision="Given only what the person typed, is this something broken (an incident) or something "
                 "they want provided (a service request)?",
        why="It is the first fork on every service desk. Incidents go to people who restore service, "
            "against hours-long targets; requests go to fulfilment, against days. Pick wrong and the "
            "ticket waits in the wrong queue, on the wrong clock.",
        labels=KIND_LABELS,
        examples=(
            "Warehouse scanners dropping off wifi in Bay 3",
            "New depot hire needs ERP and scanner access by Monday",
            "Reporting module times out on month-end export",
            "Can I get a second monitor for my desk?",
            "Outlook keeps asking for my password since this morning",
            "How do I set up the VPN on my new phone?",
        ),
        lanes=(
            Lane("jev", "Jev", "TypeSafe",
                 "One Choice question to Jev, with the two definitions as its options. Jev returns the "
                 "choice with a probability for each option, and code reads it directly.", _kind_mine),
            Lane("ai", "AI", GEMINI_NAME,
                 "A prompt to Gemini 3.8 Flash carrying the same definitions, asking for JSON limited to "
                 "the two categories, run with the model's default thinking. The server parses the text "
                 "it writes back.", _kind_traditional),
        ),
    ),
    "risk": UseCase(
        key="risk",
        title="Risk: how much exposure the issue carries",
        decision="Given what the person typed, how much business risk is in it: security, data, money, "
                 "compliance, safety or customers?",
        why="Risk decides who else needs to know. A clicked phishing link is a security incident before it "
            "is a password reset; a failed payroll run is a money problem before it is an application "
            "error. Miss the exposure and the right people hear about it last.",
        labels=RISK_LABELS,
        order=tuple(RISK_DEFS),
        examples=(
            "I clicked a link in a strange email and typed my password",
            "Customer export spreadsheet found on a public file share",
            "Payroll run failed, staff will not be paid on Friday",
            "Fire door badge reader stuck open at the depot",
            "Label printer in Bay 1 printing blank labels",
            "Can I get a second monitor for my desk?",
        ),
        lanes=(
            Lane("rules", "Traditional", "Keyword rules",
                 "An ordered list of keyword rules, the kind every ITSM tool lets an administrator write: "
                 "the first rule whose word appears sets the risk, and no match means low.",
                 _risk_rules,
                 caveat="Instant and free, but it reads words, not meaning: the first keyword that matches wins."),
            Lane("ai", "AI", GEMINI_NAME,
                 "A prompt to Gemini 3.8 Flash with the four definitions, asking for JSON limited to "
                 "those levels, run with the model's default thinking.",
                 _one_ai("risk", RISK_QUESTION, RISK_DEFS, "Risk levels")),
            Lane("jev", "Jev", "TypeSafe",
                 "One Choice question to Jev with the same four definitions. It returns the level with a "
                 "probability for each.", _one_jev("risk", RISK_QUESTION, RISK_DEFS)),
        ),
        legend=lambda ctx: {"critical": "harm happening now", "high": "a credible threat soon",
                            "medium": "contained, but growing", "low": "no real exposure"},
    ),
    "impact": UseCase(
        key="impact",
        title="Impact: how widely it reaches",
        decision="Given what the person typed, who and what does the problem reach: the whole "
                 "organisation, a department, a team, or one person?",
        why="Impact is half of every priority in Relay; urgency is the other half. On most desks it is a "
            "form field the caller rarely changes, so almost everything arrives as affecting just one "
            "person, and a site-wide outage queues behind a mouse.",
        labels=IMPACT_LABELS,
        order=tuple(IMPACT_DEFS),
        examples=(
            "Payroll system down for the whole company on pay day",
            "Nobody in Finance can open the ERP this morning",
            "Three scanners in Bay 3 keep dropping off the wifi",
            "Rotterdam depot has no internet at all",
            "Shared drive permissions wrong for the HR team",
            "My laptop will not wake from sleep",
        ),
        lanes=(
            Lane("form", "Traditional", "Form",
                 "The caller picks impact on the form, which starts at “affects just me” until someone "
                 "changes it. No model reads the words.",
                 _form_lane(("impact",), _impact_from_form), form=("impact",), caveat=FORM_CAVEAT),
            Lane("ai", "AI", GEMINI_NAME,
                 "A prompt to Gemini 3.8 Flash with the four definitions, asking for JSON limited to "
                 "those levels, run with the model's default thinking.",
                 _one_ai("impact", IMPACT_QUESTION, IMPACT_DEFS, "Impact levels")),
            Lane("jev", "Jev", "TypeSafe",
                 "One Choice question to Jev with the same four definitions. It returns the level with a "
                 "probability for each.", _one_jev("impact", IMPACT_QUESTION, IMPACT_DEFS)),
        ),
        legend=lambda ctx: {"organization": "everyone, every site", "department": "a department or site",
                            "team": "a team or group", "individual": "one person or device"},
    ),
    "priority": UseCase(
        key="priority",
        title="Priority: P1 to P4",
        decision="Given what the person typed, where does it stand, from P1 (drop everything) to P4 "
                 "(it can wait)?",
        why="Priority sets the clock and the order of work: a P1 is due in hours, a P4 in days. Rate too "
            "high and the team burns out chasing noise; too low and the real outage sits behind a "
            "monitor request. Every lane ends in the same impact × urgency matrix from Administration; "
            "what differs is who decides impact and urgency.",
        labels=PRIORITY_LABELS,
        order=tuple(policy.PRIORITIES),
        examples=(
            "Payroll system down for the whole company on pay day",
            "ERP invoice batch failed overnight, 812 invoices unsent",
            "Warehouse scanners dropping off wifi in Bay 3, picking 40 minutes behind",
            "Finance laptop will not wake from sleep",
            "Meeting room display not connecting to laptops",
            "Can I get a second monitor for my desk?",
        ),
        lanes=(
            Lane("matrix", "Traditional", "Matrix",
                 "The caller picks impact and urgency on the form, which start at “affects just me” and "
                 "“medium” until someone changes them. The matrix gives the level. No model reads the "
                 "words.", _form_lane(("impact", "urgency"), _priority_from_form),
                 form=("impact", "urgency"), caveat=FORM_CAVEAT),
            Lane("ai", "AI", GEMINI_NAME,
                 "A prompt to Gemini 3.8 Flash with the same definitions and the matrix itself, asking for "
                 "impact, urgency and priority as JSON. The server parses it and checks the priority it "
                 "wrote against its own impact and urgency.", _priority_traditional),
            Lane("jev", "Jev", "TypeSafe",
                 "Two Choice questions to Jev in one request, impact and urgency, answered in parallel. "
                 "Code reads the level out of the live matrix, and combines Jev's two distributions into "
                 "a probability for each level.", _priority_mine),
        ),
        legend=_priority_legend,
    ),
    "team": UseCase(
        key="team",
        title="Department: which team owns it",
        decision="Given what the person typed, which department's domain is this work: the service desk, "
                 "endpoint, network, applications, identity, or facilities?",
        why="Every ticket is handed to a department before anyone reads it, and a wrong hand-off costs a "
            "round trip: the ticket sits in a queue whose people cannot fix it, then bounces. Reassignment "
            "counts are the clearest measure of routing that reads words instead of meaning.",
        labels=_team_labels,
        examples=(
            "Warehouse scanners dropping off wifi in Bay 3",
            "I clicked a link in a strange email and typed my password",
            "Month-end export times out before it finishes",
            "Fire door badge reader stuck open at the depot",
            "New starter needs a laptop and ERP access on Monday",
            "Label printer in Bay 1 printing blank labels",
        ),
        lanes=(
            Lane("rules", "Traditional", "Keyword rules",
                 "The assignment-group automation every ITSM tool ships with: an ordered list of keyword "
                 "rules over the description. The first rule whose word appears sets the group, and no "
                 "match falls to the service desk.", _team_rules,
                 caveat="Instant and free, but it matches words, not work: “scanner” is hardware to the "
                        "rules whether the scanner is broken or off the wifi."),
            Lane("ai", "AI", GEMINI_NAME,
                 "A prompt to Gemini 3.8 Flash listing every department with its domain and the work it "
                 "typically handles, asking for JSON limited to those keys.", _team_ai),
            Lane("jev", "Jev", "TypeSafe",
                 "One Choice question to Jev whose options are the departments in Administration, each "
                 "described by its domain. It returns the department with a probability for each.",
                 _team_jev),
        ),
    ),
    "assignee": UseCase(
        key="assignee",
        title="Individual: whom to assign",
        decision="Given what the person typed, which of the people on the desk should actually do the "
                 "work — weighing what it needs against what each of them is good at and already carrying?",
        why="This is the question ITSM tools answer by counting. Round robin and least-loaded both ask "
            "“who is next” or “who is free”, and neither has read the ticket — so the one person who has "
            "fixed this exact fault before gets it only by luck. Relay's own auto-route counts too; this "
            "use case is what asking instead would look like.",
        labels=_person_labels,
        groups=_person_teams,
        examples=(
            "Warehouse scanners dropping off wifi in Bay 3",
            "Payments gateway certificate expired, invoice batch stuck",
            "Month-end cold chain report shows stale temperatures",
            "Offboard the warehouse supervisor, revoke all access today",
            "Meeting room display not connecting to laptops",
            "New laptop for a starter on Monday",
        ),
        lanes=(
            Lane("queue", "Traditional", "Rules and a counter",
                 "What the tools do today, in two steps: a keyword rule picks the group, then the person "
                 "is whoever on it has fewest open tickets. Nothing about the person is read.",
                 _person_queue,
                 caveat="Instant and free, and it keeps the numbers level — but it has never read what "
                        "anyone is good at, so expertise only ever arrives by accident."),
            Lane("ai", "AI", GEMINI_NAME,
                 "A prompt to Gemini 3.8 Flash carrying the whole roster — each person's team, tier, "
                 "skills and current load — asking for JSON limited to those identifiers.", _person_ai),
            Lane("jev", "Jev", "TypeSafe",
                 "One Choice question to Jev whose options are the people available right now, each "
                 "described by what they are good at and what they are carrying. Code removes anyone on "
                 "leave before asking, and checks the answer against the roster before it is written.",
                 _person_jev),
        ),
    ),
    "sentiment": UseCase(
        key="sentiment",
        title="Sentiment: 1 to 5",
        decision="Given what the person wrote, how satisfied do they sound, from 1 (most unsatisfied) to "
                 "5 (most satisfied)?",
        why="Every desk reports satisfaction from a survey that most people never answer, weeks after the "
            "ticket closed, when nothing can be done about it. Reading the feeling in what they already "
            "wrote costs nothing extra and arrives while the ticket is still open — which is the only "
            "time it is any use.",
        labels=SENTIMENT_LABELS,
        order=SENTIMENT_ORDER,
        legend=lambda ctx: SENTIMENT_LEGEND,
        examples=(
            "This is the third time I have raised this and nobody has come back to me. Unacceptable.",
            "Still waiting on the laptop I asked for two weeks ago, and my start date was Monday",
            "Scanner in Bay 3 keeps losing wifi mid-pick",
            "No rush at all, but could I get a second monitor when you have a moment? Thanks",
            "Whoever fixed the depot link this morning, thank you — we were back picking in ten minutes",
            "I clicked a link in a strange email and typed my password, I am so sorry",
        ),
        lanes=(
            Lane("lexicon", "Traditional", "Word lists",
                 "Two word lists and a subtraction: angry words score down, polite ones up, and the net "
                 "bands to a level. The pre-model way, and still the common one.", _sentiment_lexicon,
                 caveat="Instant and free, but it counts words: it cannot tell a sarcastic thank-you from "
                        "a real one, and “urgent” reads as unhappy whoever wrote it."),
            Lane("ai", "AI", GEMINI_NAME,
                 "A prompt to Gemini 3.8 Flash with the same five levels, asking for a whole number from "
                 "1 to 5 as JSON. One number comes back, with nothing either side of it.", _sentiment_ai),
            Lane("jev", "Jev", "TypeSafe",
                 "One Score question to Jev with the five levels as its ordered criteria. It returns a "
                 "position on the scale that can land between two levels, and a probability for each — "
                 "so 2.4 is an answer, and code can threshold on it.", _sentiment_jev),
        ),
    ),
    "escalation": UseCase(
        key="escalation",
        title="Escalation risk: will this blow up?",
        decision="Given the ticket, how likely is it to escalate before it is resolved — handed on to "
                 "deeper expertise, or taken over somebody's head?",
        why="Escalations are expensive and almost always visible in advance: somebody chasing, a "
            "deadline named, work sitting with the wrong person. Every ITSM tool can tell you a ticket "
            "has breached; none of them tells you which one is about to. Seeing it a day early is the "
            "difference between a phone call and a complaint.",
        labels=ESCALATION_LABELS,
        order=ESCALATION_ORDER,
        legend=lambda ctx: ESCALATION_LEGEND,
        examples=(
            "This is the third time I have chased. I need someone here today, not another reference number.",
            "Payroll run failed, staff will not be paid on Friday and the director is asking me hourly",
            "Still waiting on the laptop I asked for two weeks ago, my start date was Monday",
            "Scanner in Bay 3 keeps losing wifi mid-pick",
            "Could I get a second monitor when you have a moment? No rush at all",
            "Password reset please",
        ),
        lanes=(
            Lane("sla", "Traditional", "SLA rules",
                 "The escalation rule every ITSM tool ships with: fire when the target is half or "
                 "80% gone, when it breaches, when it is reopened, or when it has bounced twice. "
                 "The clock and the counters, never the words.", _escalation_sla,
                 caveat="Instant and free, but it only knows what the clock knows: by the time it "
                        "fires, the escalation it predicts is one the wait helped cause."),
            Lane("ai", "AI", GEMINI_NAME,
                 "A prompt to Gemini 3.8 Flash with the same statement and both criteria, asking for "
                 "a probability between 0 and 1 as JSON. The server checks what comes back is "
                 "actually a probability.", _escalation_ai),
            Lane("jev", "Jev", "TypeSafe",
                 "One Noul question to Jev: the probability that the statement is true. A Noul "
                 "answers with the probability itself and no confidence figure, and the line it is "
                 "thresholded against lives in policy, not in the prompt.", _escalation_jev),
        ),
    ),
    "duplicate": UseCase(
        key="duplicate",
        title="Duplicate: have we got this already?",
        decision="Given a new ticket, is it the same underlying thing as something already open — and if "
                 "so, which of the three ways: the same request raised twice, another person hitting the "
                 "same fault, or an instance of a known problem?",
        why="A desk that cannot see duplicates fixes the same fault six times and tells five of the six "
            "nothing. But the three relationships are not interchangeable: closing a second reporter as a "
            "duplicate loses the person you needed to notify, and attaching an instance to its problem "
            "record is the difference between fixing it again and applying the workaround somebody already "
            "wrote down.",
        labels=DUPLICATE_LABELS,
        order=DUPLICATE_ORDER,
        # nothing can be compared until code has shortlisted what to compare
        # against, so whoever runs this has to supply it
        needs=("candidates",),
        legend=lambda ctx: DUPLICATE_LEGEND,
        examples=(
            "Handhelds in bay three keep losing their connection mid-pick",
            "Invoice run did not go out again last night, same as the certificate thing",
            "Label printer in Bay 1 is still printing blanks, raising this again",
            "Cannot get on the wifi from the mezzanine office",
            "New starter needs a laptop for Monday",
        ),
        lanes=(
            Lane("similar", "Traditional", "Word overlap",
                 "The “similar incidents” panel every ITSM tool ships: the shortlist ranked by how many "
                 "words each one shares with the new ticket. The same function the staff portal searches "
                 "the knowledge base with, pointed at tickets.", _duplicate_similar,
                 caveat="Instant and free, but shared words are all it has — it cannot tell the same "
                        "request raised twice from a second person hitting the same fault."),
            Lane("ai", "AI", GEMINI_NAME,
                 "A prompt to Gemini 3.8 Flash listing every shortlisted candidate with the same three "
                 "definitions, asking for a JSON list of genuine matches and their relationship.",
                 _duplicate_ai),
            Lane("jev", "Jev", "TypeSafe",
                 "One request, one Choice question per candidate, evaluated in parallel — the fan-out. "
                 "Each returns a relationship with a probability, and a problem record is never offered "
                 "options that cannot apply to it.", _duplicate_jev),
        ),
    ),
    "deflection": UseCase(
        key="deflection",
        title="Deflection: is the answer already written down?",
        decision="Before a ticket exists — would anything in the knowledge base solve this, so the "
                 "person never has to raise one at all?",
        why="The cheapest ticket is the one nobody raises. Every desk knows this and every desk's "
            "self-service search is keyword matching, which offers an article about the right "
            "equipment and the wrong fault — so people learn to scroll past it and raise the ticket "
            "anyway. This is the one judgment whose success is measured in work that never arrives.",
        labels=DEFLECT_LABELS,
        order=DEFLECT_ORDER,
        legend=lambda ctx: DEFLECT_LEGEND,
        needs=("articles",),
        examples=(
            "laptop wont wake up in the morning, have to hold the power button",
            "scanner in bay 3 keeps dropping off the wifi",
            "cant get my personal phone onto the depot wifi",
            "forgot my password and I am locked out",
            "got an email that looks like a scam, what do I do with it",
            "payroll run failed and nobody will be paid on Friday",
        ),
        lanes=(
            Lane("keywords", "Traditional", "Keyword search",
                 "The self-service search the staff portal runs today: shared words against each "
                 "article's keyword list, top three. Left deliberately dumb from the start so this "
                 "comparison would mean something.", _deflect_keywords,
                 caveat="Instant and free, but it matches equipment rather than faults — and it "
                        "returns an order, not a probability, so nothing can be thresholded on it."),
            Lane("ai", "AI", GEMINI_NAME,
                 "A prompt to Gemini 3.8 Flash listing every live article with the same definition, "
                 "asking for a probability per article as JSON.", _deflect_ai),
            Lane("jev", "Jev", "TypeSafe",
                 "One request, one Noul per live article, evaluated in parallel. Each returns the "
                 "probability that reading it would leave them with nothing to ask, and the lines "
                 "that turn those into show-it or stay-quiet live in policy.", _deflect_jev),
        ),
    ),
}
