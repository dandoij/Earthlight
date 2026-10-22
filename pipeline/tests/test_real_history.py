"""Tests on the shipped history files in pipeline/curated/history."""

from pathlib import Path

import pytest

from earthlight.models import HistoryPeriod
from earthlight.time import from_calendar
from earthlight_pipeline.build_history import HISTORY_DIR, format_history_report, run_history
from earthlight_pipeline.history import (
    DESCRIPTION_REFERENCE_YEAR,
    HistoryData,
    has_ongoing_period,
    load_curated_history,
    years_covered,
)


@pytest.fixture(scope="module")
def shipped() -> HistoryData:
    return load_curated_history(HISTORY_DIR)


def end_or_now(period: HistoryPeriod) -> float:
    """The end year of a period, or infinity for one that is still going."""
    return float("inf") if period.ongoing else finite_end(period)


def finite_end(period: HistoryPeriod) -> float:
    """The end year of a period that has ended."""
    assert period.end is not None and not period.ongoing, period.id
    return period.end


def test_the_shipped_folder_exists_and_has_files() -> None:
    assert HISTORY_DIR.is_dir() and any(HISTORY_DIR.glob("*.yaml"))


def test_the_shipped_files_load_and_build_a_database(shipped: HistoryData, tmp_path: Path) -> None:
    report = run_history(database=tmp_path / "earthlight.db", progress=lambda _message: None)
    assert report.events == len(shipped.events)
    assert report.periods == len(shipped.periods)
    assert report.landmarks == len(shipped.landmarks)
    assert report.database_bytes > 0
    text = format_history_report(report)
    assert " to present " in text and "2,100" not in text


def test_every_entry_has_a_web_source_and_a_summary_in_a_sensible_length(
    shipped: HistoryData,
) -> None:
    entries = [*shipped.events, *shipped.periods, *shipped.landmarks]
    assert entries
    for entry in entries:
        assert entry.source.startswith("https://"), entry.id
        assert 40 <= len(entry.summary) <= 400, entry.id


def test_no_text_uses_a_dash_that_the_project_forbids(shipped: HistoryData) -> None:
    for entry in [*shipped.events, *shipped.periods, *shipped.landmarks]:
        text = f"{entry.name} {entry.region} {entry.summary}"
        assert chr(0x2014) not in text and chr(0x2013) not in text, entry.id


def test_the_eons_follow_each_other_without_gaps(shipped: HistoryData) -> None:
    periods = {p.id: p for p in shipped.periods}
    assert finite_end(periods["hadean-eon"]) == periods["archean-eon"].start
    assert finite_end(periods["archean-eon"]) == periods["proterozoic-eon"].start
    assert finite_end(periods["ediacaran-period"]) == finite_end(periods["proterozoic-eon"])


def test_the_universe_is_older_than_the_solar_system_which_is_older_than_earth(
    shipped: HistoryData,
) -> None:
    years = {e.id: e.year for e in shipped.events}
    assert (
        years["big-bang"]
        < years["first-stars"]
        < years["solar-system-forms"]
        < years["earth-forms"]
    )
    assert years["earth-forms"] < years["moon-forming-impact"] < years["oldest-fossil-life"]


def test_the_eras_follow_each_other_and_the_ice_ages_sit_inside_the_cenozoic(
    shipped: HistoryData,
) -> None:
    periods = {p.id: p for p in shipped.periods}
    assert finite_end(periods["proterozoic-eon"]) == periods["paleozoic-era"].start
    assert finite_end(periods["paleozoic-era"]) == periods["mesozoic-era"].start
    assert finite_end(periods["mesozoic-era"]) == periods["cenozoic-era"].start
    pleistocene, cenozoic = periods["pleistocene-epoch"], periods["cenozoic-era"]
    assert cenozoic.ongoing and cenozoic.start < pleistocene.start < finite_end(pleistocene)


def test_the_extinctions_mark_the_edges_of_the_eras(shipped: HistoryData) -> None:
    events = {e.id: e for e in shipped.events}
    periods = {p.id: p for p in shipped.periods}
    assert events["permian-triassic-extinction"].year == periods["mesozoic-era"].start
    assert events["end-cretaceous-extinction"].year == finite_end(periods["mesozoic-era"])


def test_the_human_story_is_in_time_order(shipped: HistoryData) -> None:
    years = {e.id: e.year for e in shipped.events}
    order = [
        "sahelanthropus",
        "lomekwi-stone-tools",
        "lucy",
        "earliest-homo",
        "homo-erectus",
        "early-controlled-fire",
    ]
    assert [years[i] for i in order] == sorted(years[i] for i in order)


def test_each_event_falls_inside_its_own_era(shipped: HistoryData) -> None:
    years = {e.id: e.year for e in shipped.events}
    periods = {p.id: p for p in shipped.periods}
    by_era = {
        "paleozoic-era": ["cambrian-explosion", "tiktaalik"],
        "mesozoic-era": ["first-dinosaurs", "first-mammals", "first-flowering-plants"],
        "cenozoic-era": ["sahelanthropus", "lucy", "lomekwi-stone-tools", "earliest-homo"],
        "pleistocene-epoch": ["homo-erectus", "early-controlled-fire", "first-homo-sapiens"],
    }
    for era, event_ids in by_era.items():
        for event_id in event_ids:
            assert periods[era].start < years[event_id] < end_or_now(periods[era]), (era, event_id)
    pleistocene = periods["pleistocene-epoch"]
    for event_id in ("sahelanthropus", "lucy", "lomekwi-stone-tools", "earliest-homo"):
        assert years[event_id] < pleistocene.start, event_id  # before the ice ages began


def test_the_ongoing_periods_are_still_going(shipped: HistoryData) -> None:
    periods = {p.id: p for p in shipped.periods}
    assert periods["cenozoic-era"].ongoing and periods["holocene-epoch"].ongoing
    assert periods["cenozoic-era"].end is None and periods["holocene-epoch"].end is None
    assert finite_end(periods["pleistocene-epoch"]) == periods["holocene-epoch"].start
    assert finite_end(periods["younger-dryas"]) == periods["holocene-epoch"].start


def test_the_prehistory_events_are_in_a_sensible_order(shipped: HistoryData) -> None:
    years = {e.id: e.year for e in shipped.events}
    order = [
        "first-homo-sapiens",
        "toba-eruption",
        "out-of-africa",
        "neanderthals-disappear",
        "chauvet-cave-paintings",
        "first-pottery",
        "humans-reach-the-americas",
        "farming-begins",
        "wheeled-vehicles",
        "otzi-the-iceman",
    ]
    assert [years[i] for i in order] == sorted(years[i] for i in order)
    assert years["earliest-writing"] < years["otzi-the-iceman"]


def test_the_landmarks_are_real_places_and_built_in_prehistory(shipped: HistoryData) -> None:
    sites = {m.id: m for m in shipped.landmarks}
    assert 36 < sites["gobekli-tepe"].lat < 38 and 38 < sites["gobekli-tepe"].lon < 40
    assert 51 < sites["stonehenge"].lat < 52 and -2 < sites["stonehenge"].lon < -1
    assert sites["gobekli-tepe"].built_end < sites["stonehenge"].built_start < -3000


def test_ancient_dates_use_astronomical_numbering(shipped: HistoryData) -> None:
    """Each year is the integer part of the astronomical year of the date it stands for."""
    events = {e.id: e.year for e in shipped.events}
    expected_year = {  # N BCE is 1 - N
        "battle-of-marathon": 1 - 490,
        "death-of-socrates": 1 - 399,
        "death-of-alexander": 1 - 323,
        "qin-unifies-china": 1 - 221,
        "destruction-of-carthage": 1 - 146,
        "assassination-of-caesar": 1 - 44,
        "battle-of-actium": 1 - 31,
        "birth-of-confucius": 1 - 551,
        "vesuvius-eruption": 79,
        "invention-of-paper-by-cai-lun": 105,
        "founding-of-constantinople": 330,
        "fall-of-the-western-roman-empire": 476,
    }
    for event_id, year in expected_year.items():
        assert int(events[event_id] // 1) == year, event_id


def test_the_day_known_dates_land_in_the_right_season(shipped: HistoryData) -> None:
    events = {e.id: e.year for e in shipped.events}
    assert round(events["assassination-of-caesar"] % 1, 2) == 0.2  # 15 March, Julian-ish
    assert 0.65 < events["battle-of-marathon"] % 1 < 0.72  # September
    assert 0.40 < events["death-of-alexander"] % 1 < 0.45  # June
    assert 0.65 < events["battle-of-actium"] % 1 < 0.70  # September


def test_the_ancient_states_follow_the_expected_order(shipped: HistoryData) -> None:
    periods = {p.id: p for p in shipped.periods}
    assert finite_end(periods["roman-republic"]) == periods["roman-empire-west"].start  # 27 BCE
    assert (
        finite_end(periods["achaemenid-empire"]) > periods["classical-greece"].start
    )  # Persian Wars
    assert finite_end(periods["classical-greece"]) > finite_end(
        periods["achaemenid-empire"]
    )  # to Alexander
    assert finite_end(periods["old-kingdom-of-egypt"]) < periods["new-kingdom-of-egypt"].start
    assert periods["han-dynasty"].start < 0 < finite_end(periods["han-dynasty"])
    events = {e.id: e.year for e in shipped.events}
    assert events["battle-of-actium"] > events["assassination-of-caesar"]
    assert (
        events["fall-of-the-western-roman-empire"] == finite_end(periods["roman-empire-west"]) + 0.5
    )


def test_the_landmarks_stand_where_they_should(shipped: HistoryData) -> None:
    sites = {m.id: m for m in shipped.landmarks}
    assert (
        29 < sites["great-pyramid-of-giza"].lat < 30
        and 31 < sites["great-pyramid-of-giza"].lon < 32
    )
    assert 37 < sites["parthenon"].lat < 38 and 23 < sites["parthenon"].lon < 24
    assert 41 < sites["colosseum"].lat < 42 and 12 < sites["colosseum"].lon < 13
    colossus = sites["colossus-of-rhodes"]
    assert colossus.destroyed is not None and colossus.destroyed > colossus.built_end


def test_only_the_known_lost_landmarks_have_a_destruction_date(shipped: HistoryData) -> None:
    lost = {"colossus-of-rhodes"}
    for site in shipped.landmarks:
        assert (site.destroyed is not None) == (site.id in lost), site.id


def test_the_middle_ages_and_early_modern_dates_use_the_calendar_year(
    shipped: HistoryData,
) -> None:
    events = {e.id: e.year for e in shipped.events}
    expected_year = {
        "hijra": 622,
        "lindisfarne-raid": 793,
        "charlemagne-crowned": 800,
        "diamond-sutra-printed": 868,
        "norse-in-north-america": 1021,
        "battle-of-hastings": 1066,
        "crusaders-take-jerusalem": 1099,
        "genghis-khan-proclaimed": 1206,
        "magna-carta": 1215,
        "mongols-take-baghdad": 1258,
        "mansa-musa-hajj": 1324,
        "black-death-reaches-europe": 1347,
        "fall-of-constantinople": 1453,
        "gutenberg-bible": 1454,  # "1454 or 1455", so the middle of the two years
        "columbus-reaches-the-americas": 1492,
        "da-gama-reaches-india": 1498,
        "luther-ninety-five-theses": 1517,
        "fall-of-tenochtitlan": 1521,
        "first-circumnavigation": 1522,
        "copernicus-heliocentric-model": 1543,
        "galileo-starry-messenger": 1610,
        "peace-of-westphalia": 1648,
        "newton-principia": 1687,
        "declaration-of-independence": 1776,
        "storming-of-the-bastille": 1789,
        "jenner-smallpox-vaccination": 1796,
    }
    for event_id, year in expected_year.items():
        assert int(events[event_id]) == year, event_id  # positive years, so int() is the floor


def test_famous_days_fall_in_the_right_season(shipped: HistoryData) -> None:
    fraction = {e.id: e.year % 1 for e in shipped.events}
    assert 0.95 < fraction["charlemagne-crowned"] < 1  # Christmas Day
    assert 0.50 < fraction["declaration-of-independence"] < 0.51  # 4 July
    assert 0.52 < fraction["storming-of-the-bastille"] < 0.54  # 14 July
    assert 0.77 < fraction["columbus-reaches-the-americas"] < 0.79  # 12 October
    assert 0.18 < fraction["galileo-starry-messenger"] < 0.21  # 13 March


def test_the_empires_in_this_era_start_and_end_in_order(shipped: HistoryData) -> None:
    periods = {p.id: p for p in shipped.periods}
    events = {e.id: e.year for e in shipped.events}
    assert finite_end(periods["byzantine-empire"]) == events["fall-of-constantinople"]
    assert finite_end(periods["mongol-empire"]) == periods["ming-dynasty"].start
    assert periods["ottoman-empire"].start < events["fall-of-constantinople"]
    assert finite_end(periods["ottoman-empire"]) > events["storming-of-the-bastille"]
    assert finite_end(periods["tang-dynasty"]) < periods["song-dynasty"].start


def test_the_middle_age_landmarks_stand_where_they_should(shipped: HistoryData) -> None:
    sites = {m.id: m for m in shipped.landmarks}
    assert 41 < sites["hagia-sophia"].lat < 41.1 and 28.9 < sites["hagia-sophia"].lon < 29
    assert sites["borobudur"].lat < 0 and 110 < sites["borobudur"].lon < 111
    assert -13.2 < sites["machu-picchu"].lat < -13.1 and -72.6 < sites["machu-picchu"].lon < -72.5
    assert 13 < sites["angkor-wat"].lat < 14 and 103 < sites["angkor-wat"].lon < 104
    assert 37.1 < sites["alhambra"].lat < 37.2 and -3.7 < sites["alhambra"].lon < -3.5
    assert 39.9 < sites["forbidden-city"].lat < 40 and 116.3 < sites["forbidden-city"].lon < 116.5
    assert 27.1 < sites["taj-mahal"].lat < 27.2 and 78 < sites["taj-mahal"].lon < 78.1
    assert (
        sites["hagia-sophia"].built_end
        < sites["borobudur"].built_end
        < sites["angkor-wat"].built_end
    )


def test_the_modern_dates_use_the_calendar_year(shipped: HistoryData) -> None:
    events = {e.id: e.year for e in shipped.events}
    expected_year = {
        "battle-of-waterloo": 1815,
        "stockton-and-darlington-railway": 1825,
        "origin-of-species": 1859,
        "emancipation-proclamation": 1863,
        "telephone-patent": 1876,
        "first-powered-flight": 1903,
        "special-relativity": 1905,
        "sinking-of-the-titanic": 1912,
        "october-revolution": 1917,
        "influenza-pandemic-1918": 1918,
        "discovery-of-penicillin": 1928,
        "wall-street-crash": 1929,
        "hiroshima-bombing": 1945,
        "indian-independence": 1947,
        "dna-double-helix": 1953,
        "sputnik-launch": 1957,
        "first-human-in-space": 1961,
        "apollo-11-moon-landing": 1969,
        "chernobyl-disaster": 1986,
        "world-wide-web-proposed": 1989,
        "fall-of-the-berlin-wall": 1989,
        "mandela-released": 1990,
        "hubble-space-telescope-launch": 1990,
        "dissolution-of-the-soviet-union": 1991,
        "september-11-attacks": 2001,
        "human-genome-completed": 2003,
        "covid-19-pandemic-declared": 2020,
        "james-webb-space-telescope-launch": 2021,
    }
    for event_id, year in expected_year.items():
        assert int(events[event_id]) == year, event_id  # positive years, so int() is the floor


def test_the_best_known_modern_days_match_the_calendar(shipped: HistoryData) -> None:
    events = {e.id: e.year for e in shipped.events}
    anchors = {
        "sputnik-launch": from_calendar(1957, 10, 4),
        "apollo-11-moon-landing": from_calendar(1969, 7, 20),
        "september-11-attacks": from_calendar(2001, 9, 11),
        "special-relativity": from_calendar(1905, 9, 26),  # published, not received
    }
    for event_id, expected in anchors.items():
        assert abs(events[event_id] - expected) < 0.001, event_id


def test_the_wars_and_ages_line_up_with_their_events(shipped: HistoryData) -> None:
    periods = {p.id: p for p in shipped.periods}
    events = {e.id: e.year for e in shipped.events}
    assert periods["space-age"].start == events["sputnik-launch"]
    assert periods["space-age"].ongoing and periods["space-age"].end is None
    assert finite_end(periods["cold-war"]) == events["dissolution-of-the-soviet-union"]
    assert (
        periods["napoleonic-wars"].start
        < events["battle-of-waterloo"]
        < finite_end(periods["napoleonic-wars"])
    )
    assert finite_end(periods["world-war-i"]) < periods["great-depression"].start
    assert (
        periods["great-depression"].start
        < events["wall-street-crash"]
        < periods["world-war-ii"].start
    )
    assert (
        periods["world-war-ii"].start
        < events["hiroshima-bombing"]
        < finite_end(periods["world-war-ii"])
    )
    assert finite_end(periods["world-war-ii"]) < periods["cold-war"].start


def test_the_space_firsts_come_in_order(shipped: HistoryData) -> None:
    events = {e.id: e.year for e in shipped.events}
    order = [
        "sputnik-launch",
        "first-human-in-space",
        "apollo-11-moon-landing",
        "hubble-space-telescope-launch",
        "james-webb-space-telescope-launch",
    ]
    assert [events[i] for i in order] == sorted(events[i] for i in order)


def test_the_modern_landmarks_are_in_the_right_hemispheres(shipped: HistoryData) -> None:
    sites = {m.id: m for m in shipped.landmarks}
    assert 48 < sites["eiffel-tower"].lat < 49 and 2 < sites["eiffel-tower"].lon < 3
    assert 40 < sites["statue-of-liberty"].lat < 41 and -75 < sites["statue-of-liberty"].lon < -74
    assert (
        37 < sites["golden-gate-bridge"].lat < 38 and -123 < sites["golden-gate-bridge"].lon < -122
    )
    assert (
        -34 < sites["sydney-opera-house"].lat < -33 and 151 < sites["sydney-opera-house"].lon < 152
    )
    assert 25 < sites["burj-khalifa"].lat < 26 and 55 < sites["burj-khalifa"].lon < 56
    assert 9 < sites["panama-canal"].lat < 10 and -80 < sites["panama-canal"].lon < -79
    assert sites["eiffel-tower"].built_end < sites["empire-state-building"].built_start
    assert abs(sites["eiffel-tower"].built_end - from_calendar(1889, 3, 31)) < 0.001
    assert abs(sites["statue-of-liberty"].built_end - from_calendar(1886, 10, 28)) < 0.001
    assert abs(sites["burj-khalifa"].built_end - from_calendar(2010, 1, 4)) < 0.005


def test_the_history_reaches_from_the_big_bang_to_the_modern_day(shipped: HistoryData) -> None:
    earliest, latest = years_covered(shipped)
    assert earliest < -13.7e9
    assert 2021 < latest < DESCRIPTION_REFERENCE_YEAR  # the 2100 stand-in is not counted
    assert has_ongoing_period(shipped)
    assert 150 <= shipped.total <= 190


def test_bce_years_are_stored_as_one_minus_n(shipped: HistoryData) -> None:
    """Spot checks of the conversion that is easiest to get wrong: N BCE is 1 - N."""
    periods = {p.id: p for p in shipped.periods}
    events = {e.id: e.year for e in shipped.events}
    assert periods["han-dynasty"].start == 1 - 202
    assert periods["roman-republic"].start == 1 - 509
    assert periods["classical-greece"].start == 1 - 480
    assert periods["old-kingdom-of-egypt"].start == 1 - 2686
    assert events["farming-begins"] == 1 - 9000
    assert events["founding-of-rome"] == 1 - 753
    assert events["first-olympic-games"] == 1 - 776
    assert events["unification-of-egypt"] == 1 - 3150


def test_the_colossus_is_placed_at_the_harbour_and_says_its_site_is_unknown(
    shipped: HistoryData,
) -> None:
    colossus = {m.id: m for m in shipped.landmarks}["colossus-of-rhodes"]
    assert (colossus.lat, colossus.lon) == (36.45, 28.23)
    assert "exact location is unknown" in colossus.summary


def test_machu_picchu_is_at_13_163_degrees_south(shipped: HistoryData) -> None:
    machu_picchu = {m.id: m for m in shipped.landmarks}["machu-picchu"]
    assert round(machu_picchu.lat, 3) == -13.163


def test_wording_that_the_owner_chose_is_kept(shipped: HistoryData) -> None:
    events = {e.id: e for e in shipped.events}
    mammals = events["first-mammals"]
    assert "mammaliaforms" in mammals.name and "205 million years" in mammals.summary
    assert "an estimated 90,000 to 166,000 people had died by the end of 1945" in " ".join(
        events["hiroshima-bombing"].summary.split()
    )
    web = " ".join(events["world-wide-web-proposed"].summary.split())
    assert "December 1990" in web and "opened to the public in August 1991" in web
    americas = " ".join(events["humans-reach-the-americas"].summary.split())
    assert "Monte Verde" in americas and "14,500 years ago" in americas
    assert events["humans-reach-the-americas"].year_uncertainty == 5000  # the range is kept
