"""Tests for the Sun, Moon, and planets as places in from_vantage, info, search, and when."""

import pytest

import earthlight
from earthlight import UnresolvedNameError, from_vantage, info, search, when
from earthlight import engine as engine_module
from earthlight.lookback import LookbackRange
from earthlight.models import VantageKind, VantagePoint
from earthlight.solar_bodies import OUT_OF_TABLE_NOTE, PLANET_IDS, matching_solar_bodies

NOW = 2026.0
SECONDS_PER_YEAR = 365.25 * 86_400


# --- from_vantage ----------------------------------------------------------------------------


def test_a_planet_shows_earth_as_it_is_right_now() -> None:
    snapshot = from_vantage("saturn", now_year=NOW)
    point = snapshot.vantage_point
    assert (point.id, point.kind) == ("saturn", VantageKind.PLANET)
    minutes = point.lookback.best * SECONDS_PER_YEAR / 60
    assert 65 < minutes < 95
    assert snapshot.moments.best == pytest.approx(NOW - point.lookback.best)
    assert snapshot.earth_exists
    assert snapshot.events == ()  # nothing happened in the last hour or two
    assert [p.id for p in snapshot.periods][:2] == ["cenozoic-era", "holocene-epoch"]
    assert snapshot.population is not None
    assert any("almost exactly as it does now" in note for note in snapshot.notes)
    assert not snapshot.wide_span


@pytest.mark.parametrize(
    ("typed", "body_id"),
    [
        ("Saturn", "saturn"),
        ("SATURN", "saturn"),
        ("  saturn ", "saturn"),
        ("the sun", "sun"),
        ("Sol", "sun"),
        ("moon", "moon"),
        ("The Moon", "moon"),
        ("Luna", "moon"),
        ("earth's moon", "moon"),
        ("mercury", "mercury"),
        ("neptune", "neptune"),
    ],
)
def test_bodies_are_found_by_name(typed: str, body_id: str) -> None:
    assert from_vantage(typed, now_year=NOW).vantage_point.id == body_id


def test_the_moon_is_over_a_second_away_and_the_sun_over_eight_minutes() -> None:
    moon = from_vantage("moon", now_year=NOW).vantage_point
    sun = from_vantage("sun", now_year=NOW).vantage_point
    assert moon.kind is VantageKind.MOON
    assert sun.kind is VantageKind.STAR
    assert moon.lookback.best * SECONDS_PER_YEAR == pytest.approx(1.28, abs=0.01)
    assert sun.lookback.best * SECONDS_PER_YEAR / 60 == pytest.approx(8.18, abs=0.05)


def test_the_distance_follows_the_date() -> None:
    january = from_vantage("mars", now_year=2025.0).vantage_point.lookback
    later = from_vantage("mars", now_year=2026.5).vantage_point.lookback
    assert january.best != pytest.approx(later.best, rel=0.01)
    assert january.minimum == pytest.approx(later.minimum, rel=0.001)  # orbit sizes barely move
    assert january.maximum == pytest.approx(later.maximum, rel=0.001)


def test_far_away_places_get_no_about_now_note() -> None:
    assert not any(
        "almost exactly" in note for note in from_vantage("hip-70890", now_year=NOW).notes
    )
    assert not any(
        "almost exactly" in note for note in from_vantage("andromeda-galaxy", now_year=NOW).notes
    )


def test_a_date_outside_the_orbit_table_still_works() -> None:
    snapshot = from_vantage("jupiter", now_year=2100.0)
    assert snapshot.vantage_point.facts == {"distance_source": "orbit_range_midpoint"}
    assert snapshot.earth_exists


def test_the_earth_has_no_view_of_itself() -> None:
    for text in ("Earth", "earth", "the earth", "planet Earth"):
        with pytest.raises(UnresolvedNameError, match="Earth is where this light starts") as raised:
            from_vantage(text, now_year=NOW)
        assert raised.value.suggestions == ()
        assert raised.value.results == ()


def test_the_engine_finds_a_body_by_id_and_still_rejects_other_ids() -> None:
    assert engine_module.from_vantage("saturn", now_year=NOW).vantage_point.id == "saturn"
    with pytest.raises(engine_module.UnknownVantageError):
        engine_module.from_vantage("pluto", now_year=NOW)


def test_an_unknown_body_is_an_unresolved_name_with_a_guess() -> None:
    with pytest.raises(UnresolvedNameError) as raised:
        from_vantage("saturm", now_year=NOW)
    assert [s.id for s in raised.value.suggestions][:1] == ["saturn"]
    with pytest.raises(UnresolvedNameError) as pluto:
        from_vantage("pluto", now_year=NOW)
    assert "saturn" not in [s.id for s in pluto.value.suggestions]


# --- info ------------------------------------------------------------------------------------


def test_info_for_a_planet_has_no_exoplanet_details_or_planets() -> None:
    details = info("saturn", now_year=NOW)
    assert details.vantage_point.kind is VantageKind.PLANET
    assert details.exoplanet is None
    assert details.planet_ids == ()
    assert details.vantage_point.facts["distance_source"] == "jpl_approximate_elements"


def test_info_follows_the_date_it_is_given() -> None:
    early = info("mars", now_year=2025.0).vantage_point.lookback.best
    later = info("mars", now_year=2026.5).vantage_point.lookback.best
    assert early != pytest.approx(later, rel=0.01)


def test_info_for_the_sun_lists_the_planets() -> None:
    assert info("sun", now_year=NOW).planet_ids == PLANET_IDS
    assert "earth" not in PLANET_IDS


def test_info_for_the_moon_has_no_planets() -> None:
    details = info("the moon", now_year=NOW)
    assert details.vantage_point.kind is VantageKind.MOON
    assert details.planet_ids == ()


def test_info_reads_the_clock_when_not_given_one() -> None:
    point = info("mars").vantage_point
    assert point.kind is VantageKind.PLANET


# --- search ----------------------------------------------------------------------------------


def test_a_search_for_a_body_finds_it_first() -> None:
    hit = search("saturn").results[0]
    assert (hit.id, hit.name, hit.kind) == ("saturn", "Saturn", VantageKind.PLANET)
    assert hit.description == "Planet of the solar system"


def test_the_start_of_a_name_finds_the_body() -> None:
    assert search("sat").results[0].id == "saturn"
    assert search("jup").results[0].id == "jupiter"
    assert [r.id for r in search("mar").results][:1] == ["mars"]


def test_an_exact_body_comes_before_longer_names_that_contain_it() -> None:
    ids = [r.id for r in search("sun").results]
    assert ids[0] == "sun"
    assert len(ids) > 1  # words that merely contain "sun" follow it


def test_the_other_names_of_a_body_find_it() -> None:
    assert search("the moon").results[0].id == "moon"
    assert search("luna").results[0].id == "moon"
    assert search("sol").results[0].id == "sun"


def test_one_or_two_letters_do_not_find_bodies() -> None:
    for text in ("m", "ma", "s", "su"):
        assert not {r.id for r in search(text).results} & {"mars", "moon", "sun", "saturn"}


def test_the_limit_applies_to_bodies_too() -> None:
    assert len(search("sat", limit=1).results) == 1
    assert search("sat", limit=0).results == ()


@pytest.mark.parametrize(
    ("typo", "body_id"),
    [
        ("saturm", "saturn"),
        ("jupitar", "jupiter"),
        ("mercurry", "mercury"),
        ("nepttune", "neptune"),
    ],
)
def test_a_typo_for_a_body_is_offered_a_guess(typo: str, body_id: str) -> None:
    response = search(typo)
    assert response.results == ()
    assert response.suggestions[0].id == body_id
    assert 0.7 <= response.suggestions[0].similarity <= 1


def test_guesses_for_other_names_do_not_mention_bodies() -> None:
    assert [s.id for s in search("Betelguese").suggestions] == ["hip-27989"]


def test_a_body_name_is_not_a_moment() -> None:
    with pytest.raises(UnresolvedNameError, match="name of a place, not a moment"):
        when("saturn", now_year=NOW)


def test_matching_bodies_prefers_exact_then_prefix() -> None:
    assert [b.id for b in matching_solar_bodies("sol")] == ["sun"]
    assert [b.id for b in matching_solar_bodies("m")] == []
    assert [b.id for b in matching_solar_bodies("me")] == []
    assert [b.id for b in matching_solar_bodies("mer")] == ["mercury"]
    assert [b.id for b in matching_solar_bodies("nep")] == ["neptune"]
    assert [b.id for b in matching_solar_bodies("ear")] == []


# --- notes and wording -----------------------------------------------------------------------

ABOUT_NOW = "so from there Earth looks almost exactly as it does now."


@pytest.mark.parametrize(
    ("body_id", "distance"),
    [("moon", "1.3 light-seconds"), ("sun", "8.2 light-minutes"), ("saturn", "1.3 light-hours")],
)
def test_the_about_now_note_reads_correctly_for_each_body(body_id: str, distance: str) -> None:
    notes = from_vantage(body_id, now_year=NOW).notes
    assert f"This place is only {distance} away, {ABOUT_NOW}" in notes


def a_point_with_lookback(minimum_days: float, best_days: float, maximum_days: float):  # type: ignore[no-untyped-def]
    """A stand-in for ``solar_body`` that returns a place at the given distances in light-days."""

    def stand_in(body_id: str, now_year: float) -> VantagePoint:
        return VantagePoint(
            id=body_id,
            name="Test body",
            kind=VantageKind.PLANET,
            lookback=LookbackRange(
                minimum_days / 365.25, best_days / 365.25, maximum_days / 365.25
            ),
        )

    return stand_in


@pytest.mark.parametrize(("days", "expected"), [(0.9, True), (1.1, False)])
def test_the_about_now_note_turns_on_a_light_day(
    monkeypatch: pytest.MonkeyPatch, days: float, expected: bool
) -> None:
    monkeypatch.setattr(
        engine_module, "solar_body", a_point_with_lookback(days / 2, days * 0.75, days)
    )
    notes = engine_module.from_vantage("saturn", now_year=NOW).notes
    assert any(ABOUT_NOW in note for note in notes) is expected


def test_the_note_uses_the_far_end_not_the_best_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module, "solar_body", a_point_with_lookback(0.1, 0.5, 2.0))
    assert not any(ABOUT_NOW in n for n in engine_module.from_vantage("x", now_year=NOW).notes)


def test_a_date_outside_the_orbit_table_says_only_the_range_is_reliable() -> None:
    assert OUT_OF_TABLE_NOTE in from_vantage("jupiter", now_year=2100.0).notes
    assert OUT_OF_TABLE_NOTE in from_vantage("sun", now_year=1700.0).notes
    assert OUT_OF_TABLE_NOTE not in from_vantage("jupiter", now_year=NOW).notes
    assert OUT_OF_TABLE_NOTE not in from_vantage("moon", now_year=2100.0).notes  # no table


def test_the_moon_has_the_same_facts_as_the_other_bodies_and_a_whole_number_of_km() -> None:
    details = info("moon", now_year=NOW)
    assert details.vantage_point.facts["distance_au"] == 0.00257
    assert details.vantage_point.facts["mean_distance_km"] == 384_400
    assert '"mean_distance_km":384400' in details.model_dump_json()
    assert "distance_au" in info("saturn", now_year=NOW).vantage_point.facts


# --- tolerant names --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "body_id"),
    [
        ("Sun.", "sun"),
        ("the Sun!", "sun"),
        ("Säturn", "saturn"),
        (f"Earth{chr(0x2019)}s Moon", "moon"),
        ("EARTH'S MOON", "moon"),
    ],
)
def test_punctuation_accents_and_apostrophes_do_not_hide_a_body(typed: str, body_id: str) -> None:
    assert from_vantage(typed, now_year=NOW).vantage_point.id == body_id
    assert search(typed).results[0].id == body_id


def test_a_typo_for_an_other_name_is_still_offered() -> None:
    assert search("lunaa").suggestions[0].id == "moon"
    assert search("soll").suggestions[0].id == "sun"


def test_an_exact_only_name_is_not_a_search_prefix() -> None:
    assert "moon" not in {r.id for r in search("earth").results}
    assert "moon" not in {r.id for r in search("ear").results}


def test_short_prefixes_keep_the_body_first() -> None:
    assert search("sol").results[0].id == "sun"
    assert search("mar").results[0].id == "mars"


def test_the_top_level_names_are_unchanged() -> None:
    assert earthlight.info is info
