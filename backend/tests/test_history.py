"""The cleaning rules for imported history. Pure, so no database and no files."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from relay import history
from relay.history import Refused, Tally


def abc_row(**over) -> dict:
    row = {
        "CI_Name": "WBA000124", "CI_Cat": "application", "CI_Subcat": "Web Based Application",
        "WBS": "WBS000088", "Incident_ID": "IM0000005", "Status": "Closed",
        "Impact": "3", "Urgency": "3", "Priority": "3", "Category": "incident",
        "KB_number": "KM0000611", "No_of_Reassignments": "33",
        "Open_Time": "12/3/2012 15:44", "Reopen_Time": "", "Resolved_Time": "2/12/2013 12:36",
        "Close_Time": "2/12/2013 12:36", "Handle_Time_hrs": "4,35,47,86,389",
        "Closure_Code": "Software", "No_of_Related_Interactions": "1",
        "Related_Interaction": "SD0000011", "No_of_Related_Incidents": "", "No_of_Related_Changes": "",
        "Related_Change": "",
    }
    row.update(over)
    return row


def gcc_row(**over) -> dict:
    row = {
        "Status": "New", "Ticket ID": "TCKT-100000", "Priority": "High", "Source": "Email",
        "Topic": "Network Issue", "Agent Group": "Network Ops", "Agent Name": "Khalid Al-Salem",
        "Created time": "2024-07-04 12:42:00", "Expected SLA to resolve": "2024-07-04 14:42:00",
        "Expected SLA to first response": "2024-07-04 13:12:00", "First response time": "2024-07-04 13:02:00",
        "SLA For first response": "Met", "Resolution time": "2024-07-04 14:30:00", "SLA For Resolution": "Met",
        "Close time": "2024-07-04 14:32:00", "Agent interactions": "5", "Survey results": "Neutral",
        "Product group": "Cloud", "Support Level": "L3", "Country": "Oman",
    }
    row.update(over)
    return row


def utc(*a) -> datetime:
    return datetime(*a, tzinfo=timezone.utc)


# ---------------------------------------------------------------- dates

def test_slash_dates_are_day_first_like_dash_dates():
    assert history.parse_abc_time("12/3/2012 15:44") == utc(2012, 3, 12, 15, 44)
    assert history.parse_abc_time("29-03-2012 12:36") == utc(2012, 3, 29, 12, 36)


def test_placeholders_and_blanks_are_absent_not_errors():
    for v in ("", "  ", "#MULTIVALUE", "#N/B", "NS", "NA"):
        assert history.clean(v) is None
    assert history.parse_abc_time("") is None


def test_an_unreadable_time_refuses_the_row():
    with pytest.raises(Refused):
        history.parse_abc_time("sometime in March")


# ---------------------------------------------------------------- abc tech

def test_abc_maps_five_levels_onto_relays_four_and_keeps_the_raw_level():
    rec = history.normalise_abc(abc_row(Impact="5", Urgency="5 - Very Low", Priority="5"), Tally())
    assert (rec["impact"], rec["urgency"], rec["recorded_priority"]) == ("individual", "low", "P4")
    assert rec["source_priority"] == "5"


def test_abc_not_set_impact_leaves_priority_empty_rather_than_guessing():
    tally = Tally()
    rec = history.normalise_abc(abc_row(Impact="NS", Priority="NA"), tally)
    assert rec["impact"] is None and rec["recorded_priority"] is None
    assert tally.repaired[(history.ABC, "impact not set (NS): left empty")] == 1


def test_abc_duration_comes_from_timestamps_not_the_mangled_column():
    rec = history.normalise_abc(abc_row(Open_Time="1/1/2013 10:00", Resolved_Time="1/1/2013 13:30"), Tally())
    assert rec["resolution_hours"] == 3.5


def test_abc_translates_dutch_closure_codes():
    rec = history.normalise_abc(abc_row(Closure_Code="Kwaliteit van de output"), Tally())
    assert rec["closure"] == "Quality of output"


def test_abc_requests_for_information_are_requests():
    rec = history.normalise_abc(abc_row(Category="request for information"), Tally())
    assert rec["kind"] == "request"
    assert rec["subject"] == "Web Based Application information request on WBA000124"


def test_abc_trusts_an_in_progress_label_over_a_stray_close_stamp():
    rec = history.normalise_abc(abc_row(Status="Work in progress"), Tally())
    assert rec["status"] == "in_progress" and rec["closed_at"] is None


def test_abc_refuses_a_ticket_closed_before_it_opened():
    with pytest.raises(Refused):
        history.normalise_abc(abc_row(Open_Time="5/5/2013 10:00", Close_Time="4/5/2013 10:00"), Tally())


# ---------------------------------------------------------------- gulf desk

def test_gcc_status_comes_from_the_timestamps():
    tally = Tally()
    rec = history.normalise_gcc(gcc_row(Status="New"), tally)
    assert rec["status"] == "closed" and rec["source_status"] == "New"
    assert sum(tally.repaired.values()) == 1


def test_gcc_sla_outcome_is_recomputed_not_copied():
    rec = history.normalise_gcc(gcc_row(**{"Resolution time": "2024-07-04 15:00:00"}), Tally())
    assert rec["resolution_met"] is False            # the row still says "Met"
    assert rec["resolution_target_minutes"] == 120


def test_gcc_priority_words_become_relay_levels():
    assert history.normalise_gcc(gcc_row(Priority="Critical"), Tally())["recorded_priority"] == "P1"
    with pytest.raises(Refused):
        history.normalise_gcc(gcc_row(Priority="Whenever"), Tally())


# ---------------------------------------------------------------- replay

def test_replayed_subjects_say_only_what_the_fields_say():
    assert history.live_subject("Web Based Application incident on WBA000124") == \
        "Problem with web-based application WBA000124"
    assert history.live_subject("Laptop information request on LAP000019") == "Question about laptop LAP000019"


def test_requests_go_to_first_line_and_incidents_follow_their_item():
    assert history.team_for("Computer / Laptop", "incident")[0] == "endpoint"
    assert history.team_for("Application / Web Based Application", "request")[0] == "service_desk"
    assert history.team_for("", "incident")[0] == "service_desk"


def test_only_causes_that_name_an_outcome_get_a_relay_code():
    assert history.code_for("User error") == "nofault"
    assert history.code_for("Other") == ""


def test_the_sample_is_stable_and_roughly_the_asked_rate():
    ids = [f"IM{n:07d}" for n in range(8000)]
    kept = [i for i in ids if history.in_sample(i, 8)]
    assert kept == [i for i in ids if history.in_sample(i, 8)]
    assert 800 < len(kept) < 1200


def test_the_replayed_moment_keeps_weekday_and_time_of_day():
    now = utc(2026, 9, 18, 14, 5)
    cut, shift = history.weeks_back(now, utc(2014, 3, 7, 14, 0))
    assert cut.weekday() == now.weekday() and (cut.hour, cut.minute) == (14, 5)
    assert shift.days % 7 == 0 and cut.year == 2014
