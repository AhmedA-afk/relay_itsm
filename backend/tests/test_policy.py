"""The decision layer, tested with no database, no network and no real clock.

That this file needs none of those is the point of keeping ``policy`` pure.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from relay import policy
from relay.clock import utc


# ---------------------------------------------------------------- priority

def test_priority_is_read_from_the_matrix():
    d = policy.derive_priority(policy.DEFAULT_MATRIX, "department", "critical")
    assert d.value == "P1"
    assert "department against critical" in d.reason


def test_every_matrix_cell_yields_a_known_priority():
    for impact in policy.IMPACTS:
        for urgency in policy.URGENCIES:
            got = policy.derive_priority(policy.DEFAULT_MATRIX, impact, urgency).value
            assert got in policy.PRIORITIES


def test_editing_the_matrix_changes_the_answer_with_no_other_change():
    edited = {k: dict(v) for k, v in policy.DEFAULT_MATRIX.items()}
    edited["individual"]["low"] = "P1"
    assert policy.derive_priority(policy.DEFAULT_MATRIX, "individual", "low").value == "P4"
    assert policy.derive_priority(edited, "individual", "low").value == "P1"


@pytest.mark.parametrize("impact,urgency", [("planet", "low"), ("team", "blistering")])
def test_nonsense_classification_is_refused(impact, urgency):
    with pytest.raises(ValueError):
        policy.derive_priority(policy.DEFAULT_MATRIX, impact, urgency)


# ---------------------------------------------------------------- sla choice

def test_first_matching_rule_in_order_wins():
    shadowed = (
        policy.SlaRule(1, "P1", 5, 60, "always"),
        policy.SlaRule(2, "P1", 999, 999, "always"),
    )
    rule = policy.pick_sla("P1", shadowed).value
    assert rule.order == 1
    assert rule.response_minutes == 5


def test_a_priority_with_no_rule_is_an_error_not_a_default():
    with pytest.raises(ValueError):
        policy.pick_sla("P9")


# ---------------------------------------------------------------- clocks

def test_round_the_clock_target_is_plain_arithmetic():
    opened = utc(2026, 9, 18, 6, 14)
    due = policy.due_at(opened, 15, "always")
    assert due == opened + timedelta(minutes=15)


def test_remaining_goes_negative_past_target():
    opened = utc(2026, 9, 18, 6, 14)
    due = policy.due_at(opened, 15, "always")
    now = opened + timedelta(minutes=40)
    assert policy.seconds_remaining(due, now) == -25 * 60


def test_time_on_hold_pushes_the_target_out_rather_than_being_forgiven():
    opened = utc(2026, 9, 18, 6, 0)
    due = policy.due_at(opened, 60, "always")
    now = opened + timedelta(minutes=90)
    assert policy.seconds_remaining(due, now) == -30 * 60
    # thirty of those ninety minutes were spent waiting on the requester
    assert policy.seconds_remaining(due, now, paused_seconds=30 * 60) == 0


def test_business_hours_target_skips_the_weekend():
    # Friday 18:00 plus four working hours lands Monday morning, not Saturday
    friday = utc(2026, 9, 18, 18, 0)
    assert friday.weekday() == 4
    due = policy.due_at(friday, 4 * 60, "business")
    assert due.weekday() == 0
    assert (due.hour, due.minute) == (10, 0)


def test_business_hours_target_inside_one_day_is_normal():
    monday = utc(2026, 9, 21, 9, 0)
    due = policy.due_at(monday, 120, "business")
    assert due == utc(2026, 9, 21, 11, 0)


def test_business_seconds_between_ignores_nights_and_weekends():
    friday_evening = utc(2026, 9, 18, 18, 0)
    monday_morning = utc(2026, 9, 21, 8, 0)
    # one hour left on Friday plus one hour on Monday
    assert policy.business_seconds_between(friday_evening, monday_morning) == 2 * 3600


def test_burn_is_comparable_across_priorities():
    opened = utc(2026, 9, 18, 6, 0)
    p1_due = policy.due_at(opened, 4 * 60, "always")
    p4_due = policy.due_at(opened, 40 * 60, "always")
    two_hours = opened + timedelta(hours=2)
    twenty_hours = opened + timedelta(hours=20)
    # half of each target spent means the same number on both
    assert policy.target_burn(opened, p1_due, two_hours) == pytest.approx(0.5)
    assert policy.target_burn(opened, p4_due, twenty_hours) == pytest.approx(0.5)


def test_burn_exceeds_one_when_breached():
    opened = utc(2026, 9, 18, 6, 0)
    due = policy.due_at(opened, 60, "always")
    assert policy.target_burn(opened, due, opened + timedelta(minutes=90)) == pytest.approx(1.5)


# ---------------------------------------------------------------- lifecycle

def test_the_happy_path_is_legal_end_to_end():
    chain = ["new", "assigned", "in_progress", "resolved", "closed"]
    for a, b in zip(chain, chain[1:]):
        assert policy.can_transition(a, b), f"{a} -> {b} should be allowed"


def test_closed_is_terminal():
    assert policy.TRANSITIONS["closed"] == ()
    with pytest.raises(ValueError):
        policy.assert_transition("closed", "in_progress")


def test_you_cannot_resolve_straight_from_new():
    assert not policy.can_transition("new", "resolved")


def test_resolved_can_be_reopened():
    assert policy.can_transition("resolved", "in_progress")


def test_the_fix_clock_pauses_on_hold_but_not_while_being_worked():
    assert policy.clock_is_paused("on_hold")
    assert not policy.clock_is_paused("in_progress")
    assert not policy.clock_is_paused("new")


# ---------------------------------------------------------------- closure codes

def test_closure_needs_a_known_code():
    policy.validate_resolution("permanent")
    with pytest.raises(ValueError):
        policy.validate_resolution("sorted it somehow")


def test_a_workaround_asks_for_a_problem_record():
    assert policy.requires_problem_record("workaround")
    assert not policy.requires_problem_record("permanent")


# ---------------------------------------------------------------- routing

def _pool():
    return [
        policy.Candidate("ao", "A. Okonkwo", "network", open_tickets=3),
        policy.Candidate("lc", "L. Chen", "network", open_tickets=1),
        policy.Candidate("zz", "Z. Away", "network", open_tickets=0, on_leave=True),
        policy.Candidate("mf", "M. Farah", "identity", open_tickets=9),
    ]


def test_least_loaded_picks_the_quietest_person_on_that_team():
    d = policy.route_to_person("network", _pool())
    assert d.value == "lc"
    assert "fewest open" in d.reason


def test_routing_never_reaches_across_teams():
    d = policy.route_to_person("identity", _pool())
    assert d.value == "mf"


def test_people_on_leave_are_skipped():
    quiet = [policy.Candidate("zz", "Z. Away", "network", 0, on_leave=True)]
    d = policy.route_to_person("network", quiet)
    assert d.value is None
    assert "nobody available" in d.reason


def test_manual_strategy_assigns_nobody_and_says_why():
    d = policy.route_to_person("network", _pool(), strategy="manual")
    assert d.value is None
    assert "team lead" in d.reason


def test_round_robin_ignores_load():
    first = policy.route_to_person("network", _pool(), strategy="round_robin", rotation_index=0)
    second = policy.route_to_person("network", _pool(), strategy="round_robin", rotation_index=1)
    assert {first.value, second.value} == {"ao", "lc"}


def test_an_empty_team_is_left_unclaimed_rather_than_guessed():
    d = policy.route_to_person("facilities", _pool())
    assert d.value is None


# ---------------------------------------------------------------- the roster

def person(pid, team="network", open_tickets=0, capacity=8, on_leave=False):
    return policy.Candidate(id=pid, name=pid.upper(), team=team, open_tickets=open_tickets,
                            on_leave=on_leave, capacity=capacity)


def test_load_is_a_share_of_capacity_not_a_raw_count():
    busy = person("a", open_tickets=5, capacity=6)
    roomy = person("b", open_tickets=6, capacity=12)
    assert busy.open_tickets < roomy.open_tickets      # the counter would pick the busier one
    assert busy.load > roomy.load                      # the share knows better
    assert busy.headroom == 1 and roomy.headroom == 6


def test_being_over_capacity_does_not_make_someone_ineligible():
    # a full team still has to answer the phone; capacity ranks people, it does
    # not remove them
    pool = policy.available("network", [person("a", open_tickets=99), person("b", team="endpoint")])
    assert [c.id for c in pool] == ["a"]


def test_leave_removes_someone_from_the_pool_entirely():
    assert policy.available("network", [person("a", on_leave=True)]) == []


def test_a_suggested_person_is_checked_against_the_roster_before_it_is_written():
    roster = [person("ao", open_tickets=4), person("sd", team="endpoint"), person("tk", on_leave=True)]
    assert policy.accept_assignment("ao", "network", roster).value == "ao"
    assert "carrying 4 of 8" in policy.accept_assignment("ao", "network", roster).reason

    assert policy.accept_assignment("nobody", "network", roster).value is None
    assert policy.accept_assignment("tk", "network", roster).value is None      # on leave
    assert policy.accept_assignment("sd", "network", roster).value is None      # wrong team
    assert "on endpoint, not network" in policy.accept_assignment("sd", "network", roster).reason


def test_ids_carry_on_from_the_highest_already_minted():
    assert policy.next_id("incident", ["INC-4416", "REQ-2205", "INC-4417"]) == "INC-4418"
    assert policy.next_id("request", ["INC-4416", "REQ-2205"]) == "REQ-2206"
    assert policy.next_id("incident", []) == "INC-1001"
    assert policy.next_id("incident", ["INC-nonsense", "abc:IM0001"]) == "INC-1001"
