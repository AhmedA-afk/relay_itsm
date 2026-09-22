"""Showcase: the measured model calls and the use-case runner. No network:
every HTTP call goes to an httpx.MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from relay import ai, showcase, usecases


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(ai.env, "key", lambda *names: "test-key")


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def jev_reply(choice="incident", p=0.97, tokens=345):
    return {"model": "jev-1.13.0", "answers": {"kind": {"type": "choice", "choice": choice, "confidence": 0.9,
            "probabilities": {"incident": p, "service_request": round(1 - p, 2)}}},
            "usage": {"input_tokens": tokens, "output_tokens": 32}}


def gemini_reply(text='{"category": "incident"}', inp=200, out=5, thoughts=94):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}], "modelVersion": "gemini-3.8-flash",
            "usageMetadata": {"promptTokenCount": inp, "candidatesTokenCount": out, "thoughtsTokenCount": thoughts}}


# ---------------------------------------------------------------- the calls

def test_jev_bills_input_only_at_the_published_rate():
    def handler(req):
        body = json.loads(req.content)
        assert req.headers["authorization"] == "Bearer test-key"
        assert body["questions"]["kind"]["type"] == "choice"
        return httpx.Response(200, json=jev_reply(tokens=1_000_000))
    m = ai.jev_choice({"t": "x"}, "kind", {"type": "choice", "instructions": "q", "criteria": {"a": "b"}},
                      client=client(handler))
    assert m.answer == "incident" and m.probabilities["incident"] == 0.97
    assert m.cost_usd == pytest.approx(0.042)      # a million input tokens, output free


def test_gemini_bills_thinking_as_output():
    m = ai.gemini_json("sys", "user", {"type": "OBJECT"}, "category",
                       client=client(lambda req: httpx.Response(200, json=gemini_reply(inp=1_000_000, out=0, thoughts=1_000_000))))
    assert m.answer == "incident"
    assert (m.input_tokens, m.thinking_tokens) == (1_000_000, 1_000_000)
    assert m.cost_usd == pytest.approx(0.75 + 3.75)


def test_gemini_text_that_is_not_json_is_an_error_not_a_guess():
    m = ai.gemini_json("s", "u", {}, "category", client=client(lambda r: httpx.Response(200, json=gemini_reply("incident"))))
    assert m.answer is None and "could not read" in m.error


def test_a_provider_error_is_reported_with_its_status():
    m = ai.jev_choice({}, "kind", {}, client=client(lambda r: httpx.Response(429, text="slow down")))
    assert m.answer is None and "429" in m.error


def test_a_missing_key_fails_without_calling_out(monkeypatch):
    monkeypatch.setattr(ai.env, "key", lambda *names: None)
    m = ai.gemini_json("s", "u", {}, "category", client=client(lambda r: pytest.fail("no call expected")))
    assert "not set" in m.error


# ---------------------------------------------------------------- the runner

@pytest.fixture()
def fake_models(monkeypatch):
    calls = []

    def jev(state, question_id, question, client=None):
        calls.append(("jev", state, question))
        return ai.Measured(provider="TypeSafe", model="jev", answer="service_request", latency_ms=400,
                           cost_usd=0.0000145, input_tokens=345)

    def gem(system, user, schema, answer_field, model=ai.GEMINI_MODEL, client=None):
        calls.append(("ai", system, user))
        return ai.Measured(provider="Google", model=model, answer="service_request", latency_ms=2400,
                           cost_usd=0.000504, input_tokens=180, thinking_tokens=94, output_tokens=5)

    monkeypatch.setattr(usecases.ai, "jev_choice", jev)
    monkeypatch.setattr(usecases.ai, "gemini_json", gem)
    return calls


def test_both_lanes_get_the_same_definitions(fake_models):
    showcase.run("kind", "Need a second monitor")
    (_, system, user), (_, state, question) = sorted(fake_models, key=lambda c: c[0])
    assert state == {"ticket": {"subject": "Need a second monitor"}}
    assert "Need a second monitor" in user
    for d in usecases.KIND_DEFS.values():
        assert d["what"] in system and question["criteria"] is usecases.KIND_DEFS


def test_run_both_compares_speed_cost_and_agreement(fake_models):
    r = showcase.run("kind", "Need a second monitor")
    assert r["results"]["jev"]["label"] == "Service request"
    assert r["compare"] == {"ai": {"agree": True, "slower": 6.0, "dearer": 34.8}}


def test_a_single_lane_runs_alone(fake_models):
    r = showcase.run("kind", "printer jam", ["ai"])
    assert list(r["results"]) == ["ai"] and r["compare"] is None
    assert [c[0] for c in fake_models] == ["ai"]


def test_the_runner_refuses_empty_text_and_unknown_cases(fake_models):
    with pytest.raises(ValueError):
        showcase.run("kind", "   ")
    with pytest.raises(LookupError):
        showcase.run("nope", "x")


# ---------------------------------------------------------------- priority

from relay import policy  # noqa: E402

MATRIX = policy.DEFAULT_MATRIX


def test_level_probabilities_come_from_both_distributions_through_the_matrix():
    dist = usecases.level_distribution(MATRIX, {"department": 0.5, "team": 0.5}, {"critical": 1.0})
    assert dist == {"P1": 0.5, "P2": 0.5, "P3": 0.0, "P4": 0.0}      # dept×critical=P1, team×critical=P2


def test_jevs_priority_is_the_matrix_cell_of_its_two_answers(monkeypatch):
    def ask(state, questions, client=None):
        assert set(questions) == {"impact", "urgency"}               # one request, both questions
        return ai.Measured(provider="TypeSafe", model="jev", detail={"answers": {
            "impact": {"choice": "team", "confidence": 0.8, "probabilities": {"team": 0.8, "individual": 0.2}},
            "urgency": {"choice": "high", "confidence": 0.9, "probabilities": {"high": 0.9, "medium": 0.1}},
        }})
    monkeypatch.setattr(usecases.ai, "jev_ask", ask)
    m = usecases.USE_CASES["priority"].lane("jev").run("scanners dropping off wifi", {"matrix": MATRIX})
    assert m.answer == "P2" and m.confidence == pytest.approx(0.72)   # team×high P2: 0.8×0.9
    assert sum(m.probabilities.values()) == pytest.approx(1.0)
    assert [p["probability"] for p in m.detail["parts"]] == [0.8, 0.9]
    assert "close_call" not in m.detail


def test_a_level_the_distribution_barely_backs_is_called_close():
    matrix = MATRIX
    m_dist = usecases.level_distribution(matrix, {"department": 1.0}, {"high": 0.49, "critical": 0.51})
    assert m_dist["P1"] > m_dist["P2"]          # dept×critical=P1 edges dept×high=P2


def test_gemini_is_caught_when_its_priority_contradicts_its_own_inputs(monkeypatch):
    def gem(system, user, schema, answer_field, model=ai.GEMINI_MODEL, client=None):
        assert "individual | P4 | P4 | P3 | P2" in system                # the live matrix is in the prompt
        return ai.Measured(provider="Google", model=model, answer="P1",
                           detail={"parsed": {"impact": "individual", "urgency": "low", "priority": "P1"}})
    monkeypatch.setattr(usecases.ai, "gemini_json", gem)
    m = usecases.USE_CASES["priority"].lane("ai").run("monitor request", {"matrix": MATRIX})
    assert m.detail["consistent"] is False and "gives P4" in m.detail["note"]


def test_the_legend_reads_the_live_service_targets():
    legend = usecases.USE_CASES["priority"].describe({"rules": policy.DEFAULT_SLA_RULES})["legend"]
    assert legend == {"P1": "fixed within 4 hours", "P2": "fixed within 8 hours",
                      "P3": "fixed within 3 working days", "P4": "fixed within 5 working days"}


def test_the_matrix_lane_never_reads_the_words():
    lane = usecases.USE_CASES["priority"].lane("matrix")
    a = lane.run("Payroll down for the whole company", {"matrix": MATRIX})
    b = lane.run("Can I get a second monitor?", {"matrix": MATRIX})
    assert a.answer == b.answer == "P4"                  # form defaults: individual × medium
    assert a.cost_usd == 0 and a.input_tokens == 0
    assert [p["by"] for p in a.detail["parts"]] == ["form default", "form default"]
    c = lane.run("x", {"matrix": MATRIX, "form": {"impact": "individual", "urgency": "medium"}})
    assert [p["by"] for p in c.detail["parts"]] == ["form default", "form default"]


def test_the_matrix_lane_uses_what_the_caller_picked():
    m = usecases.USE_CASES["priority"].lane("matrix").run(
        "anything", {"matrix": MATRIX, "form": {"impact": "organization", "urgency": "critical"}})
    assert m.answer == "P1" and m.detail["parts"][0]["by"] == "caller"


def test_priority_runs_three_lanes_and_measures_levels_apart(fake_models, monkeypatch):
    monkeypatch.setattr(usecases.ai, "jev_ask", lambda state, questions, client=None: ai.Measured(
        provider="TypeSafe", model="jev", latency_ms=400, cost_usd=0.00002, detail={"answers": {
            "impact": {"choice": "organization", "probabilities": {"organization": 1.0}},
            "urgency": {"choice": "critical", "probabilities": {"critical": 1.0}}}}))
    r = showcase.run("priority", "Payroll down for the whole company", ctx={"matrix": MATRIX})
    assert r["lanes"] == ["matrix", "ai", "jev"]
    assert r["results"]["jev"]["answer"] == "P1" and r["results"]["matrix"]["answer"] == "P4"
    assert r["compare"]["matrix"]["levels_apart"] == 3



# ---------------------------------------------------------------- risk and impact

def test_the_use_cases_come_in_the_agreed_order():
    assert list(usecases.USE_CASES) == ["kind", "risk", "impact", "priority", "team", "assignee",
                                        "sentiment", "escalation", "duplicate", "deflection"]
    assert [l.key for l in usecases.USE_CASES["risk"].lanes] == ["rules", "ai", "jev"]
    assert [l.key for l in usecases.USE_CASES["impact"].lanes] == ["form", "ai", "jev"]
    assert [l.key for l in usecases.USE_CASES["team"].lanes] == ["rules", "ai", "jev"]
    assert [l.key for l in usecases.USE_CASES["assignee"].lanes] == ["queue", "ai", "jev"]
    assert [l.key for l in usecases.USE_CASES["sentiment"].lanes] == ["lexicon", "ai", "jev"]
    assert [l.key for l in usecases.USE_CASES["escalation"].lanes] == ["sla", "ai", "jev"]
    assert [l.key for l in usecases.USE_CASES["duplicate"].lanes] == ["similar", "ai", "jev"]
    assert [l.key for l in usecases.USE_CASES["deflection"].lanes] == ["keywords", "ai", "jev"]


def test_risk_rules_take_the_first_keyword_that_matches():
    run = usecases.USE_CASES["risk"].lane("rules").run
    assert run("I clicked a link and typed my password", {}).answer == "high"
    assert run("ransomware note on the finance share", {}).answer == "critical"
    assert run("Can I get a second monitor?", {}).answer == "low"
    assert run("the payroll server is down", {}).answer == "high"     # payroll outranks down: order wins


def test_impact_form_defaults_to_one_person_and_ignores_the_words():
    run = usecases.USE_CASES["impact"].lane("form").run
    assert run("Whole company offline", {}).answer == "individual"
    assert run("x", {"form": {"impact": "organization"}}).answer == "organization"


def test_every_ai_and_jev_lane_shares_one_set_of_definitions(fake_models):
    for key, defs in (("risk", usecases.RISK_DEFS), ("impact", usecases.IMPACT_DEFS)):
        fake_models.clear()
        showcase.run(key, "Customer export found on a public share", ["ai", "jev"])
        (_, system, _), (_, _, question) = sorted(fake_models, key=lambda c: c[0])
        assert question["criteria"] is defs
        assert all(d in system for d in defs.values())


def test_levels_apart_follows_each_use_cases_own_scale(fake_models, monkeypatch):
    monkeypatch.setattr(usecases.ai, "jev_choice", lambda *a, **k: ai.Measured(
        provider="TypeSafe", model="jev", answer="organization", latency_ms=300, cost_usd=0.00002))
    r = showcase.run("impact", "Whole company offline", ["form", "jev"])
    assert r["compare"]["form"]["levels_apart"] == 3        # organization .. individual


# ---------------------------------------------------------------- routing

# a small desk, built the way /api/people hands it over
ROSTER = [
    {"id": "ao", "name": "A. Okonkwo", "team": "network", "team_name": "Network", "tier": "Second line",
     "skills": ["wifi", "access point", "barcode scanner"], "open_tickets": 4, "capacity": 8,
     "location": "Rotterdam depot", "on_leave": False},
    {"id": "yt", "name": "Y. Tanaka", "team": "network", "team_name": "Network", "tier": "Third line",
     "skills": ["switch", "firewall", "dns"], "open_tickets": 1, "capacity": 6,
     "location": "HQ", "on_leave": False},
    {"id": "tk", "name": "T. Okafor", "team": "network", "team_name": "Network", "tier": "First line",
     "skills": ["wifi"], "open_tickets": 0, "capacity": 10, "location": "HQ", "on_leave": True},
    {"id": "sd", "name": "S. Devi", "team": "endpoint", "team_name": "Endpoint", "tier": "First line",
     "skills": ["laptop", "monitor"], "open_tickets": 2, "capacity": 9, "location": "HQ", "on_leave": False},
]
TEAMS = [
    {"key": "network", "name": "Network", "domain": "Connectivity, VPN, depot wifi, the floor scanners",
     "skills": ["vpn", "wifi", "barcode scanner"]},
    {"key": "endpoint", "name": "Endpoint", "domain": "Laptops, phones, printers, peripherals", "skills": ["laptop"]},
]
DESK = {"teams": TEAMS, "roster": ROSTER}


def test_the_department_rules_name_a_team_from_one_keyword():
    m = usecases.USE_CASES["team"].lane("rules").run("Bay 3 wifi keeps dropping", DESK)
    assert m.answer == "network" and m.cost_usd == 0
    assert "wifi" in m.detail["note"]


def test_a_department_the_rules_name_but_oversight_no_longer_has_is_called_out():
    # the keyword rules carry team keys in code; renaming a department in
    # Administration silently breaks them, so the lane has to say so
    m = usecases.USE_CASES["team"].lane("rules").run("badge reader stuck", DESK)
    assert m.answer == "facilities"
    assert "not a department any more" in m.detail["note"]


def test_both_routing_lanes_are_given_the_live_departments(fake_models):
    showcase.run("team", "scanners dropping off wifi", ["ai", "jev"], ctx=DESK)
    (_, system, _), (_, _, question) = sorted(fake_models, key=lambda c: c[0])
    for t in TEAMS:
        assert t["domain"] in question["criteria"][t["key"]]
        assert t["domain"] in system


def test_nobody_on_leave_is_ever_offered_as_an_option(fake_models):
    showcase.run("assignee", "wifi drops in Bay 3", ["ai", "jev"], ctx=DESK)
    (_, system, _), (_, _, question) = sorted(fake_models, key=lambda c: c[0])
    assert set(question["criteria"]) == {"ao", "yt", "sd"}     # T. Okafor is away
    assert "T. Okafor" not in system


def test_each_persons_options_carry_their_skills_and_what_they_carry(fake_models):
    showcase.run("assignee", "core switch down", ["jev"], ctx=DESK)
    (_, _, question) = fake_models[0]
    assert "switch, firewall, dns" in question["criteria"]["yt"]
    assert "carrying 1 open tickets of a normal load of 6" in question["criteria"]["yt"]


def test_the_counter_picks_the_least_loaded_in_the_keyword_group_and_reads_nothing_else():
    run = usecases.USE_CASES["assignee"].lane("queue").run
    # both tickets are network work by keyword; the counter gives both to the
    # same person because it is comparing numbers, not the work
    a = run("wifi dropping in Bay 3", DESK)
    b = run("core switch firmware panic", DESK)
    assert a.answer == b.answer == "yt"            # 1 open beats 4; T. Okafor is on leave
    assert a.cost_usd == 0 and a.input_tokens == 0
    assert "never read" in a.detail["note"]


def test_the_counter_says_so_when_the_group_has_nobody_left():
    empty = {"teams": TEAMS, "roster": [p for p in ROSTER if p["team"] != "network"]}
    m = usecases.USE_CASES["assignee"].lane("queue").run("wifi down in Bay 3", empty)
    assert m.answer is None and "nobody available on network" in m.error


def test_jev_naming_someone_other_than_the_least_loaded_reports_who_it_passed_over(monkeypatch):
    monkeypatch.setattr(usecases.ai, "jev_choice", lambda *a, **k: ai.Measured(
        provider="TypeSafe", model="jev", answer="ao", confidence=0.71))
    m = usecases.USE_CASES["assignee"].lane("jev").run("Bay 3 scanners off the wifi", DESK)
    assert m.answer == "ao"
    assert m.detail["instead_of"]["id"] == "yt"          # the counter's answer, passed over
    assert "least-loaded on Network" in m.detail["instead_of"]["why"]


def test_jev_agreeing_with_the_counter_reports_no_alternative(monkeypatch):
    monkeypatch.setattr(usecases.ai, "jev_choice", lambda *a, **k: ai.Measured(
        provider="TypeSafe", model="jev", answer="yt"))
    m = usecases.USE_CASES["assignee"].lane("jev").run("core switch down", DESK)
    assert "instead_of" not in m.detail


def test_two_lanes_naming_different_people_on_one_team_is_a_smaller_disagreement(monkeypatch):
    monkeypatch.setattr(usecases.ai, "jev_choice", lambda *a, **k: ai.Measured(
        provider="TypeSafe", model="jev", answer="ao", latency_ms=300, cost_usd=0.00002))
    monkeypatch.setattr(usecases.ai, "gemini_json", lambda *a, **k: ai.Measured(
        provider="Google", model="gemini", answer="yt", latency_ms=2000, cost_usd=0.0005))
    r = showcase.run("assignee", "Bay 3 wifi", ["ai", "jev"], ctx=DESK)
    assert r["compare"]["ai"]["agree"] is False
    assert r["compare"]["ai"]["same_group"] == "network"       # both said Network
    assert r["results"]["jev"]["label"] == "A. Okonkwo"        # labels come from the live roster


def test_a_use_case_with_no_departments_configured_asks_for_some_rather_than_guessing():
    m = usecases.USE_CASES["team"].lane("jev").run("anything", {})
    assert m.answer is None and "add some under Oversight" in m.error


# ---------------------------------------------------------------- sentiment

def score_reply(score=1.4, probs=None, confidence=0.55):
    return {"model": "jev-1.13.0", "answers": {"sentiment": {
        "type": "score", "score": score, "confidence": confidence,
        "probabilities": probs or {"0": 0.1, "1": 0.45, "2": 0.4, "3": 0.05, "4": 0.0},
        "legend": {str(i): d for i, d in enumerate(usecases.SENTIMENT_LEVELS)},
    }}, "usage": {"input_tokens": 410, "output_tokens": 22}}


def test_a_score_comes_back_on_the_desks_own_scale_not_the_arrays():
    # Jev answers on level 0..4; everything above the model call speaks 1..5
    m = ai.jev_score({"t": "x"}, "sentiment",
                     {"type": "score", "criteria": usecases.SENTIMENT_LEVELS, "instructions": "q"},
                     labels=list(usecases.SENTIMENT_SCALE),
                     client=client(lambda r: httpx.Response(200, json=score_reply())))
    assert m.score == 1.4 and m.answer == "2"          # 1.4 is nearest level 1, shown as 2
    assert set(m.probabilities) == {"1", "2", "3", "4", "5"}
    assert m.probabilities["2"] == 0.45
    assert sum(m.probabilities.values()) == pytest.approx(1.0)


def test_the_score_is_sent_as_an_ordered_array_of_five_levels():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json=score_reply())
    usecases.ai.jev_score(sentiment := {"ticket": {"subject": "x"}}, "sentiment",
                          {"type": "score", "instructions": "q", "criteria": usecases.SENTIMENT_LEVELS},
                          labels=list(usecases.SENTIMENT_SCALE), client=client(handler))
    q = seen["questions"]["sentiment"]
    assert q["type"] == "score"
    assert isinstance(q["criteria"], list) and len(q["criteria"]) == 5      # ordered, not a mapping


def test_jev_reports_the_position_between_levels_rather_than_rounding_it_away(monkeypatch):
    monkeypatch.setattr(usecases.ai, "jev_score", lambda *a, **k: ai.Measured(
        provider="TypeSafe", model="jev", answer="2", score=1.4, confidence=0.55,
        probabilities={"1": 0.1, "2": 0.45, "3": 0.4, "4": 0.05, "5": 0.0}))
    m = usecases.USE_CASES["sentiment"].lane("jev").run("still waiting", {})
    assert m.detail["parts"][0]["value"] == "2.40 of 5"
    assert "nearest 2 · unhappy" in m.detail["note"]
    assert "40% of the weight on 3 · neutral" in m.detail["note"]
    assert m.detail["close_call"]["level"] == "3"          # confidence under a half


def test_a_confident_score_is_not_called_a_close_call(monkeypatch):
    monkeypatch.setattr(usecases.ai, "jev_score", lambda *a, **k: ai.Measured(
        provider="TypeSafe", model="jev", answer="1", score=0.05, confidence=0.93,
        probabilities={"1": 0.95, "2": 0.05, "3": 0.0, "4": 0.0, "5": 0.0}))
    m = usecases.USE_CASES["sentiment"].lane("jev").run("unacceptable", {})
    assert "close_call" not in m.detail


def test_the_word_lists_band_on_a_net_total_and_say_which_words_fired():
    run = usecases.USE_CASES["sentiment"].lane("lexicon").run
    angry = run("This is the third time I have raised this and nobody has come back to me. Unacceptable.", {})
    assert angry.answer == "1" and angry.cost_usd == 0
    assert "unacceptable" in angry.detail["note"]
    assert run("Scanner in Bay 3 keeps losing wifi mid-pick", {}).answer == "3"      # nothing matched
    assert run("Brilliant, thank you, much appreciated", {}).answer == "5"


def test_the_word_lists_cannot_tell_politeness_from_satisfaction():
    # the failure the caveat promises: a polite complaint reads as positive
    run = usecases.USE_CASES["sentiment"].lane("lexicon").run
    assert run("Please could someone look at this, thanks", {}).answer == "4"
    # and "urgent" reads as unhappy whoever wrote it
    assert run("Urgent: server room door will not lock", {}).answer == "2"


def test_gemini_answering_outside_the_scale_is_an_error_not_a_clamp(monkeypatch):
    monkeypatch.setattr(usecases.ai, "gemini_json", lambda *a, **k: ai.Measured(
        provider="Google", model="gemini", answer=9))
    m = usecases.USE_CASES["sentiment"].lane("ai").run("anything", {})
    assert m.answer is None and "outside 1 to 5" in m.error


def test_every_sentiment_lane_gets_the_same_five_levels(fake_models):
    showcase.run("sentiment", "still waiting, nobody has come back to me", ["ai", "jev"])
    (_, system, _), = [c for c in fake_models if c[0] == "ai"]
    for level in usecases.SENTIMENT_LEVELS:
        assert level in system


def test_a_lane_reading_a_whole_thread_scores_the_thread_not_the_subject(monkeypatch):
    seen = {}
    monkeypatch.setattr(usecases.ai, "jev_score", lambda state, **k: seen.update(state=state) or ai.Measured(
        provider="TypeSafe", model="jev", answer="1", score=0.2, probabilities={"1": 1.0}))
    usecases.USE_CASES["sentiment"].lane("jev").run(
        "subject only", {"state": {"ticket": {"conversation": [{"said": "this is the third time"}]}}})
    assert seen["state"]["ticket"]["conversation"][0]["said"] == "this is the third time"


def test_a_score_whose_nearest_level_is_not_its_likeliest_says_so(monkeypatch):
    # 52% on unhappy and 28% on positive averages out to 2.76, which rounds to
    # neutral — a level the distribution barely backs. Reporting "neutral" flat
    # would be the most misleading thing it could say.
    monkeypatch.setattr(usecases.ai, "jev_score", lambda *a, **k: ai.Measured(
        provider="TypeSafe", model="jev", answer="3", score=1.76, confidence=0.37,
        probabilities={"1": 0.05, "2": 0.52, "3": 0.15, "4": 0.28, "5": 0.0}))
    m = usecases.USE_CASES["sentiment"].lane("jev").run("not blaming anyone, but", {})
    assert "average of a split answer" in m.detail["note"]
    assert "52%, is on 2 · unhappy" in m.detail["note"]
    assert m.detail["close_call"]["level"] == "2"


# ---------------------------------------------------------------- escalation

def noul_reply(p=0.78):
    return {"model": "jev-1.13.0", "answers": {"escalation": {"type": "noul", "noul": p}},
            "usage": {"input_tokens": 520, "output_tokens": 14}}


def test_a_noul_comes_back_as_one_probability_and_no_confidence():
    m = ai.jev_noul({"t": "x"}, "escalation", {"type": "noul", "instructions": "q"}, threshold=0.4,
                    client=client(lambda r: httpx.Response(200, json=noul_reply(0.78))))
    assert m.noul == 0.78 and m.answer == "yes"
    assert m.probabilities == {"yes": 0.78, "no": 0.22}
    # the docs are explicit that a Noul returns no confidence; inventing one
    # would turn "evens" into "unsure", which is a different claim
    assert m.confidence is None


def test_the_noul_threshold_comes_from_policy_not_the_prompt():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json=noul_reply(0.5))
    below = ai.jev_noul({}, "escalation", {"type": "noul", "instructions": "q"}, threshold=0.65,
                        client=client(handler))
    above = ai.jev_noul({}, "escalation", {"type": "noul", "instructions": "q"}, threshold=0.4,
                        client=client(handler))
    assert below.answer == "no" and above.answer == "yes"      # same 0.5, different line
    assert seen["questions"]["escalation"]["type"] == "noul"
    assert "0.65" not in json.dumps(seen) and "threshold" not in json.dumps(seen)


def test_the_bands_are_policys_and_moving_them_re_runs_nothing(monkeypatch):
    monkeypatch.setattr(usecases.ai, "jev_noul", lambda *a, **k: ai.Measured(
        provider="TypeSafe", model="jev", noul=0.5, answer="yes", probabilities={"yes": 0.5, "no": 0.5}))
    assert usecases.USE_CASES["escalation"].lane("jev").run("x", {}).detail["band"] == "watch"
    monkeypatch.setattr(policy, "ESCALATION_LIKELY", 0.45)
    assert usecases.USE_CASES["escalation"].lane("jev").run("x", {}).detail["band"] == "likely"


def test_the_sla_lane_fires_on_the_clock_and_says_it_never_read_the_words():
    run = usecases.USE_CASES["escalation"].lane("sla").run
    quiet = run("I am absolutely furious and taking this to the director", {"ticket_state": {"burn": 0.1}})
    assert quiet.answer == "no"          # the angriest words in the world, and it sees nothing
    assert "never the words" in quiet.detail["note"]

    loud = run("routine password reset", {"ticket_state": {"burn": 0.85}})
    assert loud.answer == "yes" and loud.detail["band"] == "likely"
    assert "80% gone" in loud.detail["note"]


def test_the_sla_lane_answers_a_flag_rather_than_a_probability():
    run = usecases.USE_CASES["escalation"].lane("sla").run
    assert run("x", {"ticket_state": {"burn": 0.51}}).noul == 1.0
    assert run("x", {"ticket_state": {"burn": 0.49}}).noul == 0.0      # nothing in between


def test_a_reopen_or_repeated_bounces_fire_the_rules_on_their_own():
    run = usecases.USE_CASES["escalation"].lane("sla").run
    assert run("x", {"ticket_state": {"burn": 0.0, "reopened": 1}}).answer == "yes"
    assert run("x", {"ticket_state": {"burn": 0.0, "reassignments": 2}}).answer == "yes"
    assert run("x", {"ticket_state": {"burn": 0.0, "reassignments": 1}}).answer == "no"   # one is triage


def test_gemini_answering_something_that_is_not_a_probability_is_refused(monkeypatch):
    for bad in (1.4, -0.2, "very likely"):
        monkeypatch.setattr(usecases.ai, "gemini_json",
                            lambda *a, **k: ai.Measured(provider="Google", model="g", answer=bad))
        m = usecases.USE_CASES["escalation"].lane("ai").run("x", {})
        assert m.answer is None and m.error


def test_escalation_is_the_one_use_case_given_the_clock(monkeypatch):
    seen = {}
    monkeypatch.setattr(usecases.ai, "jev_noul", lambda state, **k: seen.update(state=state) or ai.Measured(
        provider="TypeSafe", model="jev", noul=0.3))
    usecases.USE_CASES["escalation"].lane("jev").run(
        "x", {"state": {"ticket": {"subject": "x", "share_of_target_used": "92%", "times_reopened": 2}}})
    assert seen["state"]["ticket"]["share_of_target_used"] == "92%"


def test_words_typed_with_no_requester_say_so_rather_than_letting_it_be_assumed(monkeypatch):
    seen = {}
    monkeypatch.setattr(usecases.ai, "jev_choices",
                        lambda state, questions, client=None: seen.update(state=state) or ai.Measured(
                            provider="TypeSafe", model="jev", detail={"choices": {}}))
    usecases.USE_CASES["duplicate"].lane("jev").run("printer is broken", {
        "candidates": [{"id": "INC-1", "kind": "ticket", "subject": "printer broken", "raised_by": "K. Mensah"}],
    })
    # "the same person asking again" cannot be settled from words with no author
    assert "cannot be established" in seen["state"]["ticket"]["raised_by"]
    assert seen["state"]["candidates"]["INC-1"]["raised_by"] == "K. Mensah"


def test_a_real_ticket_carries_its_own_requester_instead(monkeypatch):
    seen = {}
    monkeypatch.setattr(usecases.ai, "jev_choices",
                        lambda state, questions, client=None: seen.update(state=state) or ai.Measured(
                            provider="TypeSafe", model="jev", detail={"choices": {}}))
    usecases.USE_CASES["duplicate"].lane("jev").run("x", {
        "candidates": [{"id": "INC-1", "kind": "ticket", "subject": "y"}],
        "subject_state": {"subject": "x", "raised_by": "K. Mensah"},
    })
    assert seen["state"]["ticket"]["raised_by"] == "K. Mensah"
