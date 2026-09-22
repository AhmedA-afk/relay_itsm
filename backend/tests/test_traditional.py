"""The traditional desk's rules. Pure, so no database."""

from __future__ import annotations

from relay import traditional


def test_the_first_rule_that_matches_wins_even_when_a_later_one_fits_better():
    # An ERP failure that mentions access goes to identity: the Access rule
    # sits above Applications. That is how ordered keyword rules behave.
    d = traditional.decide("ERP invoice batch failed. I do not have access to restart it.")
    assert d["team"]["value"] == "identity"
    assert "access" in d["category"]["reason"]


def test_keywords_match_whole_words_only():
    assert traditional.match_rule("Meeting room display not connecting")[3] == "facilities"
    assert traditional.match_rule("cannot connect to the depot")[3] == "network"


def test_unmatched_text_falls_to_the_service_desk():
    d = traditional.decide("something odd happened")
    assert d["team"]["value"] == "service_desk" and d["team"]["by"] == "default"


def test_impact_is_never_the_callers_and_urgency_defaults():
    d = traditional.decide("vpn drops")
    assert (d["impact"]["value"], d["impact"]["by"]) == ("individual", "form default")
    assert (d["urgency"]["value"], d["urgency"]["by"]) == ("medium", "form default")
    assert traditional.decide("vpn drops", "critical")["urgency"]["by"] == "caller"


def test_the_ticket_waits_in_a_queue():
    assert traditional.decide("printer jam")["person"]["value"] is None


def test_keyword_overlap_ranks_by_shared_words():
    arts = [{"id": "A", "title": "a", "keywords": "wifi scanner"}, {"id": "B", "title": "b", "keywords": "wifi"}]
    assert [h["id"] for h in traditional.keyword_overlap("scanner wifi drops", arts)] == ["A", "B"]
