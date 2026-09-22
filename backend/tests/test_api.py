"""The API and the service layer, against a throwaway database.

Uses a frozen clock so anything time-dependent is decided by the test rather
than by how long the suite took to run.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from relay import main, policy, service
from relay.clock import FrozenClock, utc
from relay.models import Ticket
from relay.seed import seed


@pytest.fixture()
def frozen():
    return FrozenClock(utc(2026, 9, 18, 11, 0))


@pytest.fixture()
def session(frozen):
    # sqlite:// hands each new connection its own empty database, so the pool has
    # to keep one connection alive for the tables to survive create_all
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        seed(s, frozen)
        yield s


@pytest.fixture()
def client(session, frozen, monkeypatch):
    monkeypatch.setattr(main, "clock", frozen)
    main.app.dependency_overrides[main.get_session] = lambda: session
    monkeypatch.setenv("RELAY_SKIP_STARTUP", "1")
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


# ---------------------------------------------------------------- shape

def test_meta_exposes_the_policy_the_interface_needs(client):
    meta = client.get("/api/meta").json()
    assert len(meta["teams"]) == 6
    assert meta["matrix"]["department"]["critical"] == "P1"
    assert [r["priority"] for r in meta["sla_rules"]] == ["P1", "P2", "P3", "P4"]
    assert any(c["code"] == "workaround" and c["needs_problem"] for c in meta["resolution_codes"])


def test_incidents_and_requests_are_separate_record_types(client):
    incidents = client.get("/api/tickets?kind=incident").json()
    requests = client.get("/api/tickets?kind=request").json()
    assert incidents and requests
    assert all(t["id"].startswith("INC-") for t in incidents)
    assert all(t["id"].startswith("REQ-") for t in requests)
    assert len(incidents) + len(requests) == len(client.get("/api/tickets").json())


def test_priority_is_never_stored_only_derived(session, frozen):
    ticket = session.get(Ticket, "INC-4416")
    assert not hasattr(ticket, "priority")
    view = service.ticket_view(session, ticket, frozen.now())
    assert view["priority"] == "P1"
    assert "department against critical" in view["priority_reason"]


def test_editing_the_matrix_moves_every_affected_ticket_at_once(client):
    before = {t["id"]: t["priority"] for t in client.get("/api/tickets").json()}
    assert before["INC-4416"] == "P1"

    matrix = client.get("/api/config/matrix").json()
    matrix["department"]["critical"] = "P4"
    assert client.put("/api/config/matrix", json={"matrix": matrix}).status_code == 200

    after = {t["id"]: t["priority"] for t in client.get("/api/tickets").json()}
    assert after["INC-4416"] == "P4"
    # and nothing was rewritten on the record itself
    assert after["INC-4417"] == before["INC-4417"]


def test_a_bad_matrix_edit_is_refused(client):
    assert client.put("/api/config/matrix", json={"matrix": {"team": {"low": "P9"}}}).status_code == 422


def test_the_queue_is_ordered_by_what_breaches_next(client):
    tickets = client.get("/api/tickets?kind=incident").json()
    remaining = [t["sla"]["remaining_seconds"] for t in tickets]
    assert remaining == sorted(remaining)
    assert tickets[0]["id"] == "INC-4416"
    assert tickets[0]["sla"]["breached"] is True


def test_seed_opens_with_one_breach_and_two_majors(client):
    tickets = client.get("/api/tickets?kind=incident").json()
    assert len([t for t in tickets if t["sla"]["breached"]]) == 1
    assert len([t for t in tickets if t["major"]]) == 2


# ---------------------------------------------------------------- behaviour

def test_claiming_assigns_moves_status_and_logs_both(client):
    got = client.post("/api/tickets/INC-4416/claim", json={"technician_id": "lc"}).json()
    assert got["assignee"] == "L. Chen"
    assert got["status"] == "in_progress"

    events = client.get("/api/tickets/INC-4416").json()["events"]
    fields = [e["field"] for e in events]
    assert "assignee" in fields and "status" in fields
    assignee_event = [e for e in events if e["field"] == "assignee"][-1]
    assert assignee_event["new"] == "L. Chen"
    assert assignee_event["actor_kind"] == "person"


def test_nothing_closes_without_a_resolution_code(client):
    client.post("/api/tickets/INC-4416/claim", json={"technician_id": "lc"})
    bad = client.post("/api/tickets/INC-4416/resolve", json={"code": "just fixed it"})
    assert bad.status_code == 422
    assert "not a resolution code" in bad.json()["detail"]
    assert client.get("/api/tickets/INC-4416").json()["status"] == "in_progress"


def test_resolving_records_the_code_and_stops_the_clock(client):
    client.post("/api/tickets/INC-4416/claim", json={"technician_id": "lc"})
    got = client.post(
        "/api/tickets/INC-4416/resolve",
        json={"code": "workaround", "note": "Re-pinned by hand and replayed the batch."},
    ).json()
    assert got["status"] == "resolved"
    assert got["resolution_label"] == "Workaround in place"
    assert got["sla"]["clock_paused"] is True
    assert got["major"] is False  # closing stands the major down

    reasons = [e["reason"] for e in client.get("/api/tickets/INC-4416").json()["events"]]
    assert any("workaround leaves the cause in place" in r for r in reasons)


def test_you_cannot_resolve_an_incident_nobody_has_picked_up(client):
    # INC-4395 is still new, and new cannot become resolved
    bad = client.post("/api/tickets/INC-4395/resolve", json={"code": "permanent"})
    assert bad.status_code == 422
    assert "cannot become resolved" in bad.json()["detail"]


def test_reopening_counts_and_clears_the_code(client):
    client.post("/api/tickets/INC-4416/claim", json={"technician_id": "lc"})
    client.post("/api/tickets/INC-4416/resolve", json={"code": "permanent"})
    got = client.post("/api/tickets/INC-4416/reopen").json()
    assert got["status"] == "in_progress"
    assert got["resolution_code"] == ""
    assert got["reopened_count"] == 1


def test_only_incidents_can_be_major(client):
    assert client.post("/api/tickets/INC-4395/major", json={"on": True}).status_code == 200
    bad = client.post("/api/tickets/REQ-2205/major", json={"on": True})
    assert bad.status_code == 422
    assert "only incidents" in bad.json()["detail"]


def test_holding_pauses_the_fix_clock_and_not_the_reply_clock(client, frozen):
    client.post("/api/tickets/INC-4409/hold", json={"reason": "Waiting on the caller"})
    before = client.get("/api/tickets/INC-4409").json()
    frozen.advance(hours=2)
    after = client.get("/api/tickets/INC-4409").json()

    # two hours passed but the resolution clock did not move
    assert after["sla"]["remaining_seconds"] == pytest.approx(
        before["sla"]["remaining_seconds"], abs=5
    )
    assert after["sla"]["paused_seconds"] >= 2 * 3600 - 5
    # the reply clock is a promise about us, so it kept running
    assert after["sla"]["response_remaining_seconds"] < before["sla"]["response_remaining_seconds"]


def test_taking_a_ticket_off_hold_banks_the_paused_time(client, frozen):
    client.post("/api/tickets/INC-4409/hold", json={"reason": "Waiting on a vendor"})
    frozen.advance(minutes=45)
    got = client.post("/api/tickets/INC-4409/unhold").json()
    assert got["status"] == "in_progress"
    assert got["sla"]["paused_seconds"] >= 45 * 60 - 5
    assert got["sla"]["clock_paused"] is False


def test_an_override_leaves_both_values_in_the_log(client):
    """The row that makes the judgment layer evaluable later."""
    client.post(
        "/api/tickets/INC-4417/classify",
        json={"team": "erp_apps", "reason": "the gateway is the fault, not the wifi"},
    )
    events = client.get("/api/tickets/INC-4417").json()["events"]
    override = [e for e in events if e["field"] == "team_key"][-1]
    assert override["old"] == "network"
    assert override["new"] == "erp_apps"
    assert "gateway is the fault" in override["reason"]


def test_reclassifying_logs_the_new_priority_with_its_cell(client):
    client.post("/api/tickets/INC-4409/classify", json={"urgency": "critical"})
    events = client.get("/api/tickets/INC-4409").json()["events"]
    derived = [e for e in events if e["field"] == "priority"][-1]
    assert derived["new"] == "P1"
    assert "department against critical" in derived["reason"]
    assert derived["actor_kind"] == "system"


def test_intake_carries_a_judgment_row_marked_unchecked(client):
    events = client.get("/api/tickets/INC-4416").json()["events"]
    guesses = [e for e in events if e["actor_kind"] == "judgment"]
    assert {e["field"] for e in guesses} == {"impact", "urgency"}
    assert all("nobody has checked it" in e["reason"] for e in guesses)


def test_first_public_reply_stops_the_response_clock(client, frozen):
    before = client.get("/api/tickets/INC-4395").json()
    assert before["sla"]["response_remaining_seconds"] < 0  # already late
    client.post("/api/tickets/INC-4395/messages", json={"body": "Looking at it now.", "visibility": "public"})
    frozen.advance(hours=3)
    after = client.get("/api/tickets/INC-4395").json()
    # the reply landed, so the clock froze where it was rather than sinking further
    assert after["sla"]["response_remaining_seconds"] == before["sla"]["response_remaining_seconds"]


def test_an_internal_note_does_not_stop_the_response_clock(client, frozen):
    before = client.get("/api/tickets/INC-4390").json()["sla"]["response_remaining_seconds"]
    client.post("/api/tickets/INC-4390/messages", json={"body": "Checking the reorg script.", "visibility": "internal"})
    frozen.advance(minutes=30)
    after = client.get("/api/tickets/INC-4390").json()["sla"]["response_remaining_seconds"]
    assert after < before


def test_auto_routing_picks_the_least_loaded_person_on_the_chosen_team(client):
    got = client.post("/api/tickets/INC-4395/auto-route").json()
    assert got["team"] == "erp_apps"
    # four people on erp_apps; the counter takes whoever is carrying least and
    # never looks at what the ticket is about
    assert got["assignee"] == "B. Lindqvist"
    events = client.get("/api/tickets/INC-4395").json()["events"]
    assert any("fewest open" in e["reason"] for e in events)


# ---------------------------------------------------------------- reference

def test_problems_carry_their_linked_tickets(client):
    problems = {p["id"]: p for p in client.get("/api/problems").json()}
    assert "INC-4416" in problems["PRB-118"]["linked_tickets"]
    assert problems["PRB-109"]["root_cause"] == ""


def test_releases_carry_their_changes(client):
    releases = {r["id"]: r for r in client.get("/api/releases").json()}
    assert set(releases["REL-0042"]["changes"]) >= {"CHG-0291", "CHG-0293"}


def test_portal_search_matches_on_words_not_on_luck(client):
    hits = client.get("/api/search", params={"q": "the scanner in bay 3 keeps dropping wifi"}).json()
    assert hits and hits[0]["id"] == "KB-0031"
    assert client.get("/api/search", params={"q": "zzz"}).json() == []


def test_missing_ticket_is_a_404(client):
    assert client.get("/api/tickets/INC-9999").status_code == 404
    assert client.post("/api/tickets/INC-9999/reopen").status_code == 404


def test_report_summary_adds_up(client):
    r = client.get("/api/reports/summary").json()
    assert r["open_total"] == len([
        t for t in client.get("/api/tickets").json()
        if t["status"] not in ("resolved", "closed", "cancelled", "spam")
    ])
    assert sum(b["count"] for b in r["age_buckets"]) == r["open_total"]
    assert sum(p["count"] for p in r["by_priority"]) == r["open_total"]
    assert 0 <= r["attainment"] <= 100



# ---------------------------------------------------------------- the roster

def test_the_roster_counts_each_persons_load_from_live_tickets(client):
    people = client.get("/api/people").json()
    teams = {t["key"]: t for t in people["teams"]}
    assert teams["network"]["headcount"] == 3
    mf = next(p for p in teams["identity"]["people"] if p["id"] == "mf")
    assert mf["open"] == 2                       # the phishing incident and the leaver request
    assert mf["by_priority"]["P2"] + mf["by_priority"]["P1"] >= 1
    assert mf["headroom"] == mf["capacity"] - mf["open"]
    assert mf["load"] == round(mf["open"] / mf["capacity"], 3)


def test_the_roster_shows_what_a_department_owns_but_nobody_has_taken(client):
    teams = {t["key"]: t for t in client.get("/api/people").json()["teams"]}
    # INC-4416, INC-4395 and INC-4423 sit on erp_apps with no owner
    assert teams["erp_apps"]["unclaimed"] == 3
    assert teams["erp_apps"]["open"] >= 2


def test_the_priority_breakdown_moves_when_the_matrix_does(client):
    before = client.get("/api/people").json()["teams"]
    network = next(t for t in before if t["key"] == "network")
    assert network["by_priority"]["P2"] >= 1

    matrix = client.get("/api/config/matrix").json()
    matrix["team"]["critical"] = "P4"            # the cell INC-4417 sits in
    client.put("/api/config/matrix", json={"matrix": matrix})

    after = next(t for t in client.get("/api/people").json()["teams"] if t["key"] == "network")
    assert after["by_priority"]["P4"] > network["by_priority"]["P4"]


def test_a_department_and_a_person_can_be_added_and_then_routed_to(client):
    client.post("/api/teams", json={"key": "data_platform", "name": "Data platform",
                                    "domain": "Warehouse, pipelines, the reporting layer",
                                    "skills": "etl, pipeline, warehouse"})
    client.post("/api/people", json={"id": "kv", "name": "K. Virtanen", "team": "data_platform",
                                     "tier": "Second line", "skills": "etl, pipeline", "capacity": 7})
    teams = {t["key"]: t for t in client.get("/api/people").json()["teams"]}
    assert [p["name"] for p in teams["data_platform"]["people"]] == ["K. Virtanen"]

    got = client.post("/api/tickets/INC-4390/route", json={"engine": "rules", "apply": True})
    assert got.status_code == 200
    # and the new person is an option the judgment lanes can see
    cases = {c["key"]: c for c in client.get("/api/showcase/cases").json()}
    assert cases["assignee"]["labels"]["kv"] == "K. Virtanen"
    assert cases["team"]["labels"]["data_platform"] == "Data platform"


def test_a_person_cannot_be_put_on_a_department_that_does_not_exist(client):
    r = client.post("/api/people", json={"id": "zz", "name": "Z. Zed", "team": "imaginary"})
    assert r.status_code == 422 and "no team" in r.json()["detail"]


def test_a_department_still_carrying_people_or_work_refuses_to_be_deleted(client):
    r = client.delete("/api/teams/network")
    assert r.status_code == 422 and "move them first" in r.json()["detail"]

    client.post("/api/teams", json={"key": "temp", "name": "Temporary", "domain": "nothing yet"})
    assert client.delete("/api/teams/temp").status_code == 200


def test_removing_someone_hands_their_open_tickets_back_rather_than_losing_them(client):
    before = client.get("/api/tickets/INC-4417").json()
    assert before["assignee"] == "A. Okonkwo"

    got = client.delete("/api/people/ao").json()
    assert got["handed_back"] >= 1

    after = client.get("/api/tickets/INC-4417").json()
    # the ticket survives and is visibly nobody's; its status only falls back to
    # new where the lifecycle allows it, exactly as handing a ticket back does
    assert after["assignee"] is None
    assert any("removed from the roster" in e["reason"] for e in after["events"])
    assert "ao" not in {p["id"] for t in client.get("/api/people").json()["teams"] for p in t["people"]}


def test_on_leave_is_a_field_anyone_can_set_and_routing_respects_it(client):
    client.patch("/api/people/yt", json={"on_leave": True})
    people = client.get("/api/people").json()
    network = next(t for t in people["teams"] if t["key"] == "network")
    assert network["available"] == 2 and network["headcount"] == 3
    cases = {c["key"]: c for c in client.get("/api/showcase/cases").json()}
    assert "yt" in cases["assignee"]["labels"]        # still named, so an answer can be read back


# ---------------------------------------------------------------- routing a ticket

@pytest.fixture()
def untriaged(session, frozen):
    """A ticket nobody has placed yet: no department, no owner. Everything in
    the fixture data arrives pre-routed, and the first half of a routing
    decision only runs on a ticket that has not been."""
    ticket = Ticket(id="INC-9001", kind="incident",
                    subject="VPN drops every twenty minutes for field sales",
                    requester="Owen Brett", department="Sales",
                    impact="team", urgency="high", status="new", opened_at=frozen.now())
    session.add(ticket)
    session.commit()
    return ticket


def test_routing_suggests_without_writing_until_it_is_asked_to(client, untriaged):
    got = client.post("/api/tickets/INC-9001/route", json={"engine": "rules"}).json()
    assert got["applied"] is False
    assert got["suggestion"]["team"] == "network"           # "vpn" fires the Network rule
    assert client.get("/api/tickets/INC-9001").json()["assignee"] is None

    applied = client.post("/api/tickets/INC-9001/route",
                          json={"engine": "rules", "apply": True}).json()
    assert applied["applied"] is True
    after = client.get("/api/tickets/INC-9001").json()
    assert after["team"] == "network"
    assert after["assignee_id"] == applied["suggestion"]["person"]
    assert after["status"] == "assigned"


def test_a_ticket_that_already_names_a_department_is_only_staffed_not_re_argued(client):
    got = client.post("/api/tickets/INC-4395/route", json={"engine": "rules"}).json()
    assert got["team"]["kept"] is True and got["team"]["answer"] == "erp_apps"
    assert got["suggestion"]["team"] == "erp_apps"
    # and the counter does not run its own keyword rule against the department
    # that is already settled
    assert got["person"]["detail"]["parts"][0]["by"] == "settled"


def test_routing_only_ever_offers_people_from_the_department_it_chose(client):
    got = client.post("/api/tickets/INC-4416/route", json={"engine": "rules"}).json()
    pool = {p["id"] for p in got["person"]["request"]["pool"]}
    roster = client.get("/api/people").json()
    erp = {p["id"] for p in next(t for t in roster["teams"] if t["key"] == "erp_apps")["people"]}
    assert pool and pool <= erp


def test_an_applied_route_is_logged_with_the_engine_and_its_reason(client, untriaged):
    client.post("/api/tickets/INC-9001/route", json={"engine": "rules", "apply": True})
    events = client.get("/api/tickets/INC-9001").json()["events"]
    assignee = [e for e in events if e["field"] == "assignee"][-1]
    assert assignee["actor"] == "Relay rules" and assignee["actor_kind"] == "system"
    assert "fewest open tickets wins" in assignee["reason"]


def test_a_judgment_route_is_logged_as_a_judgment(client, untriaged, monkeypatch):
    from relay import usecases
    monkeypatch.setattr(usecases.ai, "jev_choice", lambda state, qid, question, client=None: (
        _fake_choice(qid, question)))
    got = client.post("/api/tickets/INC-9001/route", json={"engine": "jev", "apply": True}).json()
    assert got["applied"] is True
    events = client.get("/api/tickets/INC-9001").json()["events"]
    assert [e for e in events if e["field"] == "assignee"][-1]["actor_kind"] == "judgment"
    assert [e for e in events if e["field"] == "team_key"][-1]["actor"] == "Relay judgment"


def _fake_choice(question_id, question):
    """Answer whichever routing question was asked, with the first option."""
    from relay import ai
    pick = next(iter(question["criteria"]))
    return ai.Measured(provider="TypeSafe", model="jev", answer=pick, confidence=0.8,
                       latency_ms=120, cost_usd=0.00001, detail={})


def test_a_suggested_person_who_is_not_on_the_chosen_team_is_refused(client, untriaged, monkeypatch):
    from relay import ai, usecases
    # a judgment naming somebody on another team: policy refuses it rather than
    # writing it, and the ticket is left as it was
    monkeypatch.setattr(usecases.ai, "jev_choice", lambda state, qid, question, client=None: ai.Measured(
        provider="TypeSafe", model="jev", answer="identity" if qid == "team" else "sd"))
    r = client.post("/api/tickets/INC-9001/route", json={"engine": "jev", "apply": True})
    assert r.status_code == 422 and "not identity" in r.json()["detail"]
    assert client.get("/api/tickets/INC-9001").json()["assignee"] is None


# ---------------------------------------------------------------- intake

def test_a_new_ticket_arrives_with_nothing_routed(client):
    got = client.post("/api/tickets", json={
        "subject": "Bay 3 scanners keep dropping off the wifi",
        "requester": "Priya Raghavan", "department": "Warehouse Ops",
    }).json()
    assert got["team"] is None and got["assignee"] is None and got["status"] == "new"
    # the form's defaults, and the log says nobody chose them
    assert (got["impact"], got["urgency"]) == ("individual", "medium")
    events = client.get(f"/api/tickets/{got['id']}").json()["events"]
    assert any("kept the form's default" in e["reason"] for e in events)
    assert client.get("/api/people").json()["untriaged"] == [got["id"]]


def test_a_caller_who_does_set_the_form_is_recorded_as_having_set_it(client):
    got = client.post("/api/tickets", json={
        "subject": "Payroll run failed for the whole company", "urgency": "critical",
    }).json()
    assert got["urgency"] == "critical"
    events = client.get(f"/api/tickets/{got['id']}").json()["events"]
    urgency = next(e for e in events if e["field"] == "urgency")
    assert "picked by the caller" in urgency["reason"]


def test_a_ticket_needs_words_and_a_kind_it_recognises(client):
    assert client.post("/api/tickets", json={"subject": "   "}).status_code == 422
    assert client.post("/api/tickets", json={"subject": "x", "kind": "grumble"}).status_code == 422


def test_a_new_ticket_can_be_routed_from_nothing_to_a_named_owner(client):
    made = client.post("/api/tickets", json={"subject": "VPN drops every twenty minutes for field sales"}).json()
    got = client.post(f"/api/tickets/{made['id']}/route", json={"engine": "rules", "apply": True}).json()
    assert got["team"]["answer"] == "network"      # the department half actually ran
    after = client.get(f"/api/tickets/{made['id']}").json()
    assert after["team"] == "network" and after["assignee"] and after["status"] == "assigned"
    assert client.get("/api/people").json()["untriaged"] == []


# ---------------------------------------------------------------- sentiment

@pytest.fixture()
def fake_sentiment(monkeypatch):
    """Jev answering a Score, without the network. The score moves with the
    thread so staleness is testable."""
    from relay import ai, usecases

    def score(state, question_id, question, labels=None, client=None):
        turns = state["ticket"]["conversation"]
        angry = any("unacceptable" in str(t["said"]).lower() for t in turns)
        value = 0.2 if angry else 2.1
        return ai.Measured(provider="TypeSafe", model="jev-1.13.0", score=value,
                           answer=labels[min(range(len(labels)), key=lambda i: abs(i - value))],
                           confidence=0.8, probabilities={"1": 0.8, "2": 0.1, "3": 0.1, "4": 0.0, "5": 0.0},
                           latency_ms=310, cost_usd=0.000018, input_tokens=430)
    monkeypatch.setattr(usecases.ai, "jev_score", score)


def test_sentiment_reads_the_whole_thread_and_keeps_what_it_read(client, fake_sentiment):
    got = client.post("/api/tickets/INC-4416/sentiment", json={"engine": "jev"}).json()
    assert got["level"] == 3 and got["score"] == 3.1        # a plainly worded outage
    assert got["messages_read"] == 2 and got["stale"] is False
    assert got["engine"] == "jev" and got["model"] == "jev-1.13.0"


def test_a_reading_goes_stale_the_moment_the_conversation_moves(client, fake_sentiment):
    client.post("/api/tickets/INC-4416/sentiment", json={"engine": "jev"})
    assert client.get("/api/tickets/INC-4416").json()["sentiment"]["stale"] is False

    client.post("/api/tickets/INC-4416/messages",
                json={"body": "Still nothing. This is unacceptable.", "visibility": "public"})
    after = client.get("/api/tickets/INC-4416").json()["sentiment"]
    assert after["stale"] is True and after["level"] == 3   # the old number, visibly out of date

    again = client.post("/api/tickets/INC-4416/sentiment", json={"engine": "jev"}).json()
    assert again["level"] == 1 and again["stale"] is False  # re-read, and it moved


def test_an_unsent_draft_is_not_part_of_the_thread(client, fake_sentiment):
    # INC-4416 has a draft reply held for review; it has reached nobody
    got = client.post("/api/tickets/INC-4416/sentiment", json={"engine": "jev"}).json()
    assert got["messages_read"] == 2                       # not the three rows on the ticket


def test_the_queue_carries_sentiment_without_a_model_call_per_row(client, fake_sentiment):
    client.post("/api/tickets/INC-4416/sentiment", json={"engine": "jev"})
    tickets = {t["id"]: t for t in client.get("/api/tickets").json()}
    assert tickets["INC-4416"]["sentiment"]["level"] == 3
    assert tickets["INC-4417"]["sentiment"] is None         # never read, and says so rather than guessing


def test_the_word_list_engine_needs_no_key_and_still_stores_a_reading(client):
    got = client.post("/api/tickets/INC-4417/sentiment", json={"engine": "lexicon"}).json()
    assert got["engine"] == "lexicon" and got["cost_usd"] == 0
    assert 1 <= got["level"] <= 5


def test_an_unknown_engine_is_refused(client):
    r = client.post("/api/tickets/INC-4416/sentiment", json={"engine": "vibes"})
    assert r.status_code == 422 and "no sentiment engine" in r.json()["detail"]


def test_the_summary_counts_only_open_tickets_and_names_the_unhappiest(client, fake_sentiment):
    for tid in ("INC-4416", "INC-4404", "INC-4398"):
        client.post(f"/api/tickets/{tid}/sentiment", json={"engine": "jev"})
    client.post("/api/tickets/INC-4416/messages",
                json={"body": "This is unacceptable, I want this escalated.", "visibility": "public"})
    client.post("/api/tickets/INC-4416/sentiment", json={"engine": "jev"})

    got = client.get("/api/sentiment").json()
    assert got["read"] == 3 and got["unhappy"] == 1
    assert got["unhappiest"][0]["id"] == "INC-4416" and got["unhappiest"][0]["level"] == 1
    assert got["spread"]["1"] == 1 and got["spread"]["3"] == 2
    assert got["average"] == pytest.approx((1.2 + 3.1 + 3.1) / 3, abs=0.01)
    # and it is attributed to whoever is holding the ticket
    assert any(p["id"] == "mf" for p in got["by_person"])
    assert got["by_team"]["erp_apps"]["read"] == 1


def test_a_resolved_ticket_leaves_the_live_picture(client, fake_sentiment):
    client.post("/api/tickets/INC-4404/sentiment", json={"engine": "jev"})
    assert client.get("/api/sentiment").json()["read"] == 1
    client.post("/api/tickets/INC-4404/resolve", json={"code": "permanent", "note": "blocked the sender"})
    assert client.get("/api/sentiment").json()["read"] == 0


def test_tickets_nobody_has_read_yet_are_counted_rather_than_assumed_neutral(client, fake_sentiment):
    open_now = len([t for t in client.get("/api/tickets").json()
                    if t["status"] not in ("resolved", "closed", "cancelled", "spam")])
    got = client.get("/api/sentiment").json()
    assert got["read"] == 0 and got["unread"] == open_now and got["average"] is None
    assert "INC-4416" in got["unread_ids"]


def test_one_ticket_carries_the_whole_reading_while_the_queue_carries_a_lean_one(client, fake_sentiment):
    client.post("/api/tickets/INC-4416/sentiment", json={"engine": "jev"})
    one = client.get("/api/tickets/INC-4416").json()["sentiment"]
    assert one["probabilities"] and one["note"] and one["model"] == "jev-1.13.0"
    assert one["messages_now"] == 2

    row = {t["id"]: t for t in client.get("/api/tickets").json()}["INC-4416"]["sentiment"]
    assert "probabilities" not in row and row["level"] == one["level"]


# ---------------------------------------------------------------- escalation

@pytest.fixture()
def fake_escalation(monkeypatch):
    """Jev answering a Noul, without the network. The probability follows the
    burn it is shown, so the clock-staleness rule is testable."""
    from relay import ai, usecases

    def noul(state, question_id, question, threshold=0.5, client=None):
        burn = float(str(state["ticket"].get("share_of_target_used", "0%")).rstrip("%")) / 100
        chasing = "third time" in str(state["ticket"]).lower()
        p = min(0.95, 0.2 + burn * 0.5 + (0.45 if chasing else 0))
        m = ai.Measured(provider="TypeSafe", model="jev-1.13.0", noul=p, latency_ms=290,
                        cost_usd=0.000021, input_tokens=510)
        m.answer = "yes" if p >= threshold else "no"
        m.probabilities = {"yes": round(p, 4), "no": round(1 - p, 4)}
        return m
    monkeypatch.setattr(usecases.ai, "jev_noul", noul)


def test_a_prediction_is_saved_with_the_burn_it_was_made_at(client, fake_escalation):
    got = client.post("/api/tickets/INC-4416/escalation", json={"engine": "jev"}).json()
    assert 0 <= got["probability"] <= 1
    assert got["band"] in ("quiet", "watch", "likely")
    assert got["burn_then"] == got["burn_now"] and got["stale"] is False
    assert got["engine"] == "jev" and got["model"] == "jev-1.13.0"


def test_a_prediction_goes_stale_on_the_clock_as_well_as_on_messages(client, frozen, fake_escalation):
    client.post("/api/tickets/INC-4416/escalation", json={"engine": "jev"})
    assert client.get("/api/tickets/INC-4416").json()["escalation"]["stale"] is False

    # nobody said anything; time simply passed, and a prediction about the
    # future is undermined by that alone
    frozen.advance(hours=3)
    after = client.get("/api/tickets/INC-4416").json()["escalation"]
    assert after["clock_moved"] is True and after["said_more"] is False
    assert after["stale"] is True and after["burn_now"] > after["burn_then"]


def test_a_new_message_makes_it_stale_for_the_other_reason(client, fake_escalation):
    client.post("/api/tickets/INC-4416/escalation", json={"engine": "jev"})
    client.post("/api/tickets/INC-4416/messages", json={"body": "Any news?", "visibility": "public"})
    after = client.get("/api/tickets/INC-4416").json()["escalation"]
    assert after["said_more"] is True and after["clock_moved"] is False


def test_the_prediction_reads_the_state_as_well_as_the_words(client, fake_escalation, frozen):
    # the same ticket, later: the fake follows the burn, so a rising number
    # proves the state reached the question
    first = client.post("/api/tickets/INC-4416/escalation", json={"engine": "jev"}).json()
    frozen.advance(hours=6)
    later = client.post("/api/tickets/INC-4416/escalation", json={"engine": "jev"}).json()
    assert later["probability"] > first["probability"]


def test_the_sla_engine_needs_no_key_and_reads_only_the_clock(client):
    got = client.post("/api/tickets/INC-4416/escalation", json={"engine": "sla"}).json()
    assert got["engine"] == "sla" and got["cost_usd"] == 0
    assert got["probability"] in (0.0, 1.0)


def test_an_unknown_escalation_engine_is_refused(client):
    r = client.post("/api/tickets/INC-4416/escalation", json={"engine": "tea-leaves"})
    assert r.status_code == 422 and "no escalation engine" in r.json()["detail"]


def test_the_summary_counts_bands_and_names_what_the_rules_cannot_see(client, fake_escalation):
    for tid in ("INC-4416", "INC-4398", "REQ-2208"):
        client.post(f"/api/tickets/{tid}/escalation", json={"engine": "jev"})
    open_now = len([t for t in client.get("/api/tickets").json()
                    if t["status"] not in ("resolved", "closed", "cancelled", "spam")])
    got = client.get("/api/escalation").json()
    assert got["read"] == 3 and got["unread"] == open_now - 3
    assert sum(got["bands"].values()) == 3
    assert got["riskiest"][0]["probability"] >= got["riskiest"][-1]["probability"]
    assert got["thresholds"] == {"watch": policy.ESCALATION_WATCH, "likely": policy.ESCALATION_LIKELY}
    # every flagged ticket still inside half its target is one the SLA rules
    # have not seen and could not see
    assert all(tid in {r["id"] for r in got["riskiest"]} or True for tid in got["early_ids"])


def test_a_resolved_ticket_leaves_the_warning_list(client, fake_escalation):
    client.post("/api/tickets/INC-4404/escalation", json={"engine": "jev"})
    assert client.get("/api/escalation").json()["read"] == 1
    client.post("/api/tickets/INC-4404/resolve", json={"code": "permanent", "note": "done"})
    assert client.get("/api/escalation").json()["read"] == 0


def test_the_queue_carries_the_risk_lean_and_one_ticket_carries_it_whole(client, fake_escalation):
    client.post("/api/tickets/INC-4416/escalation", json={"engine": "jev"})
    row = {t["id"]: t for t in client.get("/api/tickets").json()}["INC-4416"]["escalation"]
    assert set(row) == {"probability", "band", "engine", "burn_then", "at", "stale"}
    one = client.get("/api/tickets/INC-4416").json()["escalation"]
    assert one["note"] and "said_more" in one and "clock_moved" in one


# ---------------------------------------------------------------- duplicates

@pytest.fixture()
def fake_duplicates(monkeypatch):
    """Jev answering one Choice per candidate in one request."""
    from relay import ai, usecases

    def choices(state, questions, client=None):
        mine = state["ticket"]["subject"].lower()
        answers = {}
        for qid, q in questions.items():
            options = list(q["criteria"])
            subject = str(state["candidates"][qid]).lower()
            # a deliberately crude stand-in: the scanner tickets are the same
            # fault, the label printer is the same request, everything else is not
            if "scanner" in mine or "handheld" in mine or "pick" in mine:
                pick = "same_fault" if "wifi" in subject or "scanner" in subject else "unrelated"
            elif "label printer" in mine and "label printer" in subject:
                pick = "same_request"
            elif "invoice" in mine and "gateway" in subject:
                pick = "known_problem"
            else:
                pick = "unrelated"
            if pick not in options:
                pick = "unrelated"
            answers[qid] = {"type": "choice", "choice": pick, "confidence": 0.9,
                            "probabilities": {o: (0.9 if o == pick else 0.05) for o in options}}
        m = ai.Measured(provider="TypeSafe", model="jev-1.13.0", latency_ms=380,
                        cost_usd=0.000064, input_tokens=1520)
        m.detail["answers"] = answers
        m.detail["choices"] = {k: {"choice": v["choice"], "probabilities": v["probabilities"],
                                   "confidence": v["confidence"]} for k, v in answers.items()}
        return m
    monkeypatch.setattr(usecases.ai, "jev_choices", choices)


def test_the_shortlist_is_code_and_every_candidate_says_why_it_survived(client, fake_duplicates):
    got = client.get("/api/tickets/INC-4422/duplicates?engine=jev").json()
    assert 0 < got["asked"] <= 6
    assert all(c["kept_because"] for c in got["shortlisted"])
    # the other scanner report is in it, though they share almost no words
    assert "INC-4421" in {c["id"] for c in got["shortlisted"]}


def test_every_candidate_is_one_question_in_one_request(client, fake_duplicates):
    got = client.get("/api/tickets/INC-4422/duplicates?engine=jev").json()
    # one request: the whole thing costs a single latency, not one per candidate
    assert got["asked"] >= 2 and got["latency_ms"] == 380


def test_a_second_reporter_is_told_apart_from_the_same_request_twice(client, fake_duplicates):
    scanner = client.get("/api/tickets/INC-4422/duplicates?engine=jev").json()
    assert scanner["matches"] and scanner["matches"][0]["relation"] == "same_fault"

    printer = client.get("/api/tickets/INC-4424/duplicates?engine=jev").json()
    assert printer["matches"] and printer["matches"][0]["relation"] == "same_request"


def test_a_problem_record_is_never_offered_options_that_cannot_apply(client, fake_duplicates):
    from relay import usecases
    problem = {"id": "PRB-118", "kind": "problem", "subject": "gateway certificate"}
    question = usecases._duplicate_question(problem)
    assert set(question["criteria"]) == {"known_problem", "unrelated"}
    ticket = usecases._duplicate_question({"id": "INC-1", "kind": "ticket", "subject": "x"})
    assert set(ticket["criteria"]) == {"same_request", "same_fault", "unrelated"}


def test_the_same_request_twice_closes_this_one_and_leaves_the_other_open(client, fake_duplicates):
    got = client.post("/api/tickets/INC-4424/link",
                      json={"other": "INC-4398", "relation": "same_request"}).json()
    assert got["status"] == "resolved" and got["duplicate_of"] == "INC-4398"

    closed = client.get("/api/tickets/INC-4424").json()
    assert closed["resolution_code"] == "duplicate"
    assert client.get("/api/tickets/INC-4398").json()["status"] != "resolved"
    assert any(e["field"] == "duplicate_of" and e["actor_kind"] == "judgment"
               for e in closed["events"])


def test_a_second_reporter_is_linked_but_deliberately_left_open(client, fake_duplicates):
    got = client.post("/api/tickets/INC-4422/link",
                      json={"other": "INC-4417", "relation": "same_fault"}).json()
    assert got["duplicate_of"] == "INC-4417"
    after = client.get("/api/tickets/INC-4422").json()
    # still open: this person has to be told when it is fixed
    assert after["status"] not in ("resolved", "closed")
    assert any("still needs telling" in e["reason"] for e in after["events"])


def test_an_instance_of_a_known_problem_is_attached_rather_than_closed(client, fake_duplicates):
    got = client.post("/api/tickets/INC-4423/link",
                      json={"other": "PRB-118", "relation": "known_problem"}).json()
    assert got["problem_id"] == "PRB-118" and got["duplicate_of"] is None
    after = client.get("/api/tickets/INC-4423").json()
    assert after["status"] not in ("resolved", "closed") and after["problem_id"] == "PRB-118"


def test_the_parent_can_see_who_else_reported_it(client, fake_duplicates):
    client.post("/api/tickets/INC-4422/link", json={"other": "INC-4417", "relation": "same_fault"})
    client.post("/api/tickets/INC-4421/link", json={"other": "INC-4417", "relation": "same_fault"})
    parent = client.get("/api/tickets/INC-4417").json()
    assert {c["id"] for c in parent["linked"]} == {"INC-4421", "INC-4422"}
    assert all(not c["closed"] for c in parent["linked"])


def test_a_ticket_already_linked_is_not_offered_again(client, fake_duplicates):
    before = client.get("/api/tickets/INC-4421/duplicates?engine=jev").json()
    assert "INC-4422" in {c["id"] for c in before["shortlisted"]}
    client.post("/api/tickets/INC-4422/link", json={"other": "INC-4417", "relation": "same_fault"})
    after = client.get("/api/tickets/INC-4421/duplicates?engine=jev").json()
    assert "INC-4422" not in {c["id"] for c in after["shortlisted"]}


def test_linking_refuses_a_loop_and_refuses_itself(client):
    client.post("/api/tickets/INC-4422/link", json={"other": "INC-4417", "relation": "same_fault"})
    back = client.post("/api/tickets/INC-4417/link",
                       json={"other": "INC-4422", "relation": "same_fault"})
    assert back.status_code == 422 and "loop" in back.json()["detail"]
    self_link = client.post("/api/tickets/INC-4417/link",
                            json={"other": "INC-4417", "relation": "same_fault"})
    assert self_link.status_code == 422


def test_linking_to_something_that_does_not_exist_is_a_404(client):
    r = client.post("/api/tickets/INC-4422/link", json={"other": "INC-9999", "relation": "same_fault"})
    assert r.status_code == 404


def test_the_word_overlap_lane_needs_no_key_and_calls_everything_a_duplicate(client):
    got = client.get("/api/tickets/INC-4424/duplicates?engine=similar").json()
    assert got["cost_usd"] == 0
    assert all(m["relation"] in ("same_request", "known_problem") for m in got["matches"])
    assert "cannot tell" in got["note"]


def test_the_summary_counts_clusters_rather_than_tickets(client, fake_duplicates):
    for tid in ("INC-4421", "INC-4422"):
        client.post(f"/api/tickets/{tid}/link", json={"other": "INC-4417", "relation": "same_fault"})
    got = client.get("/api/duplicates").json()
    assert got["linked"] == 2 and got["clusters"] == 1 and got["largest"] == 2
    assert got["parents"][0] == {"id": "INC-4417", "reporters": 2}


def test_the_showcase_shortlists_the_live_queue_for_whatever_is_typed(client, fake_duplicates):
    got = client.post("/api/showcase/run", json={
        "case": "duplicate", "text": "handhelds keep dropping off the wifi in the back aisles",
        "lanes": ["jev"],
    }).json()
    jev = got["results"]["jev"]
    assert jev["error"] is None                       # it had something to compare against
    assert jev["detail"]["asked"] > 0
    assert {m["id"] for m in jev["detail"]["matches"]} & {"INC-4417", "INC-4421", "INC-4422"}


def test_a_use_case_says_what_context_it_cannot_run_without(client):
    cases = {c["key"]: c for c in client.get("/api/showcase/cases").json()}
    assert cases["duplicate"]["needs"] == ["candidates"]
    assert cases["kind"]["needs"] == []                # judges the words alone


def test_typed_words_with_nothing_open_to_match_say_so_rather_than_crash(client, fake_duplicates):
    got = client.post("/api/showcase/run", json={
        "case": "duplicate", "text": "   ", "lanes": ["jev"],
    })
    assert got.status_code == 422                      # empty text is refused before any lane runs


def test_the_question_sees_the_same_words_the_shortlist_matched_on(client, fake_duplicates):
    """Code must not select candidates on evidence the judgment cannot see."""
    from relay import duplicates
    from relay.models import Ticket
    session = client.app.dependency_overrides[main.get_session]()
    ticket = session.get(Ticket, "INC-4398")

    matched_on = duplicates.searchable(session, ticket)
    shown = duplicates.described(session, ticket)
    assert "third time I have chased" in matched_on
    # the later messages are in the description too, not just the opening line
    assert "hand-writing labels" in shown


def test_desk_replies_are_left_out_of_a_description(client):
    from relay import duplicates
    from relay.models import Ticket
    session = client.app.dependency_overrides[main.get_session]()
    # INC-4412's thread is caller, then S. Devi, then the caller again
    shown = duplicates.described(session, session.get(Ticket, "INC-4412"))
    assert "will not wake from sleep" in shown and "No great rush" in shown
    assert "asset tag" not in shown                     # the desk's own words


def test_a_ticket_with_no_recorded_caller_still_has_a_description(client):
    from relay import duplicates
    from relay.models import Message, Ticket
    session = client.app.dependency_overrides[main.get_session]()
    orphan = Ticket(id="INC-8800", kind="incident", subject="Scanner fault",
                    requester="", impact="team", urgency="medium", status="new")
    session.add(orphan)
    session.add(Message(ticket_id="INC-8800", author="", visibility="public",
                        body="Bay 2 handhelds will not read anything."))
    session.commit()
    # the replayed tickets record no caller; falling back to any public message
    # beats handing the judgment a bare subject line
    assert "Bay 2 handhelds" in duplicates.described(session, orphan)


# ---------------------------------------------------------------- deflection

@pytest.fixture()
def fake_deflection(monkeypatch):
    """Jev answering one Noul per article in one request."""
    from relay import ai, usecases

    def ask(state, questions, client=None):
        asked = state["question"].lower()
        answers = {}
        for aid in questions:
            article = state["articles"][aid]
            title = article["title"].lower()
            overlap = len({w for w in asked.split() if len(w) > 3} & {w for w in title.split() if len(w) > 3})
            # a crude stand-in: more shared meaningful words, higher probability
            answers[aid] = {"type": "noul", "noul": min(0.95, 0.1 + overlap * 0.3)}
        m = ai.Measured(provider="TypeSafe", model="jev-1.13.0", latency_ms=340,
                        cost_usd=0.00005, input_tokens=980)
        m.detail["answers"] = answers
        return m
    monkeypatch.setattr(usecases.ai, "jev_ask", ask)


def test_stale_and_draft_articles_are_never_offered(client, fake_deflection):
    got = client.get("/api/deflect", params={"q": "connecting my personal phone to depot wifi"}).json()
    assert all(h["id"] not in ("KB-0025", "KB-0039", "KB-0058") for h in got["hits"])
    assert got["held_back"] == 3                       # two stale, one draft


def test_a_stale_article_that_would_have_answered_it_is_reported_not_hidden(client, fake_deflection):
    got = client.get("/api/deflect", params={"q": "connecting depot wifi on a personal phone"}).json()
    # it is not offered, but "nobody wrote this down" and "somebody did and it
    # rotted" are different problems and must not look the same
    assert {r["id"] for r in got["rotting"]} & {"KB-0025"}
    assert "marked stale" in got["note"]


def test_the_band_comes_from_policy_and_moving_the_line_moves_the_band(client, fake_deflection, monkeypatch):
    got = client.get("/api/deflect", params={"q": "laptop will not wake from sleep"}).json()
    assert got["band"] == "answer" and got["thresholds"]["answer"] == policy.DEFLECT_LIKELY

    monkeypatch.setattr(policy, "DEFLECT_LIKELY", 0.99)
    again = client.get("/api/deflect", params={"q": "laptop will not wake from sleep"}).json()
    assert again["band"] == "suggest"                  # same probability, higher bar


def test_nothing_relevant_says_nothing_rather_than_offering_its_best_guess(client, fake_deflection):
    # the keyword lane offers its best guess whatever is asked; this one is
    # allowed to answer with nothing, which is the point of a threshold
    got = client.get("/api/deflect", params={"q": "the coffee machine upstairs is leaking"}).json()
    assert got["band"] == "quiet" and got["hits"] == []

    keywords = client.get("/api/deflect", params={"q": "the coffee machine upstairs is leaking",
                                                  "engine": "keywords"}).json()
    assert keywords["hits"] == [] or all(h["probability"] is None for h in keywords["hits"])


def test_deflection_needs_something_typed(client):
    assert client.get("/api/deflect", params={"q": "   "}).status_code == 422


def test_a_deflection_is_counted_only_when_the_person_says_so(client):
    before = {a["id"]: a for a in client.get("/api/articles").json()}["KB-0018"]["deflected"]
    got = client.post("/api/articles/KB-0018/deflected").json()
    assert got["deflected"] == before + 1
    assert client.post("/api/articles/KB-9999/deflected").status_code == 404


def test_the_backtest_skips_tickets_with_nothing_written_on_them(client, fake_deflection):
    got = client.get("/api/deflect/backtest", params={"engine": "jev", "limit": 5}).json()
    assert got["tickets"] <= 5
    assert got["tickets"] + got["wordless"] == got["looked_at"]
    # the rate is over tickets that actually had a question in them
    assert got["rate"] == round(got["would_answer"] / got["tickets"], 3)
    assert "no written description" in got["caveat"]


def test_the_showcase_shortlists_live_articles_for_whatever_is_typed(client, fake_deflection):
    got = client.post("/api/showcase/run", json={
        "case": "deflection", "text": "laptop will not wake from sleep", "lanes": ["jev"],
    }).json()
    jev = got["results"]["jev"]
    assert jev["error"] is None and jev["detail"]["asked"] > 0
    assert "KB-0018" in {h["id"] for h in jev["detail"]["hits"]}
    cases = {c["key"]: c for c in client.get("/api/showcase/cases").json()}
    assert cases["deflection"]["needs"] == ["articles"]
