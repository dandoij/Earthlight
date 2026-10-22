"""Tests for reading the curated history files."""

from pathlib import Path

import pytest

from earthlight.time import from_calendar
from earthlight_pipeline.history import (
    CATEGORIES,
    DESCRIPTION_REFERENCE_YEAR,
    HistoryData,
    HistoryError,
    category_counts,
    has_ongoing_period,
    load_aliases,
    load_curated_history,
    search_entries,
    years_covered,
)

SAMPLE = Path(__file__).parent / "data" / "history_sample"

EVENT = """\
events:
  - id: x
    name: X
    category: science
    region: Earth
    summary: Something happened.
    importance: 3
    source: https://example.org/x
    year: 1492
"""


def write(tmp_path: Path, text: str, name: str = "era.yaml") -> Path:
    (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def problems(tmp_path: Path) -> str:
    with pytest.raises(HistoryError) as error:
        load_curated_history(tmp_path)
    return str(error.value)


def test_the_sample_files_load_in_file_name_order() -> None:
    data = load_curated_history(SAMPLE)
    assert [e.id for e in data.events] == ["moon-landing", "formation-of-earth"]  # ancient first
    assert [p.id for p in data.periods] == ["cambrian"]
    assert [m.id for m in data.landmarks] == ["great-pyramid-of-giza"]
    assert data.total == 4
    assert data.events[1].year == -4.54e9 and data.events[1].year_uncertainty == 5e7
    assert data.events[0].year_uncertainty == 0  # the default


def test_every_category_the_loader_allows_is_a_plain_word() -> None:
    assert len(set(CATEGORIES)) == len(CATEGORIES) == 9
    assert all(c == c.lower() and " " not in c for c in CATEGORIES)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("year: 1492", 'year: "1492"', "year"),  # text is not a number
        ("importance: 3", "importance: true", "importance"),  # true is not 3
        ("importance: 3", 'importance: "3"', "importance"),
        ("importance: 3", "importance: 6", "importance"),
        ("importance: 3", "importance: 3.0", "importance"),
        ("year: 1492", "year: 1492\n    extra: 1", "extra"),  # unknown field
        ("year: 1492", "year: .inf", "year"),
        ("year: 1492", "year_uncertainty: -1\n    year: 1", "year_uncertainty"),
        ("source: https://example.org/x", "source: example.org/x", "source"),
        ("id: x", "id: Not A Slug", "id"),
        ("category: science", "category: Science", "category"),
        ("category: science", "category: sports", "category"),
        ("year: 1492", "date: 1492", "year"),  # the required field is missing
        ("year: 1492", "year: 2020-01-01", "year"),  # YAML turns this into a date
    ],
)
def test_a_wrong_value_is_an_error_not_a_silent_conversion(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    text = EVENT.replace(old, new)
    assert text != EVENT
    assert message in problems(write(tmp_path, text))


def test_a_period_that_ends_before_it_starts_is_refused(tmp_path: Path) -> None:
    write(
        tmp_path,
        EVENT.replace("events:", "periods:").replace("year: 1492", "start: 5\n    end: 1"),
    )
    assert "cannot end before it starts" in problems(tmp_path)


def test_a_landmark_needs_a_real_place(tmp_path: Path) -> None:
    text = EVENT.replace("events:", "landmarks:").replace(
        "year: 1492", "built_start: 1\n    built_end: 2\n    lat: 95\n    lon: 0"
    )
    assert "lat" in problems(write(tmp_path, text))


def test_every_problem_in_every_file_is_reported_together(tmp_path: Path) -> None:
    write(tmp_path, EVENT.replace("importance: 3", "importance: 9"), "a.yaml")
    write(tmp_path, EVENT.replace("category: science", "category: nope"), "b.yaml")
    text = problems(tmp_path)
    assert "a.yaml events 1 (x)" in text and "importance" in text
    assert "category 'nope' is not one of" in text
    assert "duplicate id: x" not in text  # the first file's entry is invalid, so not counted


def test_a_repeated_id_or_name_is_refused_naming_both_files(tmp_path: Path) -> None:
    write(tmp_path, EVENT, "a.yaml")
    write(tmp_path, EVENT, "b.yaml")
    text = problems(tmp_path)
    assert "duplicate id: x (in a.yaml, b.yaml)" in text
    assert "duplicate name in events: x (in a.yaml, b.yaml)" in text


def test_a_bad_category_names_its_file(tmp_path: Path) -> None:
    write(tmp_path, EVENT.replace("category: science", "category: sports"), "late.yaml")
    assert "late.yaml (x): category 'sports' is not one of" in problems(tmp_path)


def test_a_key_written_twice_in_one_entry_is_refused(tmp_path: Path) -> None:
    text = problems(write(tmp_path, EVENT.replace("year: 1492", "year: 1492\n    year: 1493")))
    assert "era.yaml: cannot be read" in text and "found the key 'year' twice" in text


def test_files_with_only_empty_lists_have_no_entries(tmp_path: Path) -> None:
    write(tmp_path, "events: []\nperiods: []\n", "a.yaml")
    write(tmp_path, "landmarks: []\n", "b.yaml")
    assert "no history entries" in problems(tmp_path)


def test_an_id_cannot_be_reused_across_types(tmp_path: Path) -> None:
    both = EVENT + (
        "periods:\n  - {id: x, name: Y, category: science, region: Earth, summary: S,"
        " importance: 1, source: 'https://example.org', start: 1, end: 2}\n"
    )
    assert "duplicate id: x" in problems(write(tmp_path, both))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "must be a mapping"),
        ("- a list\n", "must be a mapping"),
        ("people: []\n", "must be a mapping"),
        ("events: 5\n", "'events' must be a list"),
        ("events: [5]\n", "events 1 (?)"),
        ("events: [: bad\n", "cannot be read"),
    ],
)
def test_a_badly_shaped_file_is_reported(tmp_path: Path, text: str, message: str) -> None:
    assert message in problems(write(tmp_path, text))


def test_a_missing_or_empty_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(HistoryError, match="not a directory"):
        load_curated_history(tmp_path / "missing")
    with pytest.raises(HistoryError, match=r"no .yaml files"):
        load_curated_history(tmp_path)


def test_search_entries_tell_the_hits_apart() -> None:
    entries = {e.id: e for e in search_entries(load_curated_history(SAMPLE))}
    assert entries["moon-landing"].type == "event"
    assert entries["moon-landing"].description == "Event, 1969 CE"
    assert (
        entries["cambrian"].description == "Period, 539 million years ago to 485 million years ago"
    )
    assert entries["great-pyramid-of-giza"].description == "Landmark, built 2560 BCE"
    assert entries["formation-of-earth"].description == "Event, 4.54 billion years ago"
    assert all(e.aliases == "" for e in entries.values())


def test_a_recent_event_is_described_by_its_year_not_as_days_ago(tmp_path: Path) -> None:
    late_2025 = from_calendar(2025, 12, 14)  # 18 days before the reference year starts
    assert DESCRIPTION_REFERENCE_YEAR - late_2025 < 1
    write(tmp_path, EVENT.replace("year: 1492", f"year: {late_2025!r}"))
    (entry,) = search_entries(load_curated_history(tmp_path))
    assert entry.description == "Event, 2025 CE"


def test_a_year_after_the_reference_year_is_a_calendar_year(tmp_path: Path) -> None:
    write(tmp_path, EVENT.replace("year: 1492", "year: 2026.9"))
    (entry,) = search_entries(load_curated_history(tmp_path))
    assert entry.description == "Event, 2026 CE"


def test_the_years_and_categories_covered() -> None:
    data = load_curated_history(SAMPLE)
    assert years_covered(data) == (-4.54e9, 1969.5)
    assert not has_ongoing_period(data)
    assert category_counts(data) == {"geological": 2, "civilization": 1, "technology": 1}


def test_there_is_nothing_to_cover_without_entries() -> None:
    with pytest.raises(ValueError, match="no history entries"):
        years_covered(HistoryData((), (), ()))


PERIOD = """\
periods:
  - id: era
    name: Era
    category: geological
    region: Earth
    summary: Something that lasts.
    importance: 3
    source: https://example.org/era
    start: -66000000
    ongoing: true
"""


def test_a_period_can_be_ongoing(tmp_path: Path) -> None:
    (period,) = load_curated_history(write(tmp_path, PERIOD)).periods
    assert period.ongoing and period.end is None
    (entry,) = search_entries(load_curated_history(tmp_path))
    assert entry.description == "Period, 66 million years ago to present"


def test_an_ongoing_period_is_not_counted_as_an_end_year(tmp_path: Path) -> None:
    write(tmp_path, PERIOD, "a.yaml")
    write(tmp_path, EVENT, "b.yaml")
    data = load_curated_history(tmp_path)
    assert years_covered(data) == (-66_000_000, 1492)
    assert has_ongoing_period(data)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("ongoing: true", "ongoing: true\n    end: 2000", "not ongoing"),  # ongoing but ended
        ("ongoing: true", "ongoing: false", "not ongoing"),  # ended, but no end given
        ("ongoing: true", 'ongoing: "true"', "ongoing"),  # text is not a bool
        ("ongoing: true", "ongoing: 1", "ongoing"),  # nor is a number
        ("ongoing: true", "end: present", "end"),  # the old keyword is gone
    ],
)
def test_ongoing_must_agree_with_end(tmp_path: Path, old: str, new: str, message: str) -> None:
    assert message in problems(write(tmp_path, PERIOD.replace(old, new)))


def test_ongoing_is_not_allowed_on_an_event(tmp_path: Path) -> None:
    text = EVENT.replace("year: 1492", "year: 1492\n    ongoing: true")
    assert "ongoing" in problems(write(tmp_path, text))


# --- other names for search ----------------------------------------------------------------------


def alias_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "aliases.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def alias_problems(tmp_path: Path, body: str) -> str:
    data = load_curated_history(SAMPLE)
    with pytest.raises(HistoryError) as error:
        load_aliases(alias_file(tmp_path, body), data)
    return str(error.value)


def test_aliases_are_read_by_entry_id(tmp_path: Path) -> None:
    data = load_curated_history(SAMPLE)
    body = (
        "aliases:\n  moon-landing: [First moon landing, Man on the moon]\n"
        "  cambrian: [Cambrian Explosion]\n"
    )
    assert load_aliases(alias_file(tmp_path, body), data) == {
        "moon-landing": ("First moon landing", "Man on the moon"),
        "cambrian": ("Cambrian Explosion",),
    }


def test_aliases_are_stored_one_per_line_in_the_search_entries(tmp_path: Path) -> None:
    data = load_curated_history(SAMPLE)
    aliases = {"moon-landing": ("First moon landing", "Man on the moon")}
    entries = {e.id: e for e in search_entries(data, aliases)}
    assert entries["moon-landing"].aliases == "First moon landing\nMan on the moon"
    assert entries["cambrian"].aliases == ""
    assert all(e.aliases == "" for e in search_entries(data))


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("aliases:\n  not-an-entry: [Name]\n", "not-an-entry: there is no history entry"),
        ("aliases:\n  cambrian: []\n", "cambrian: must be a non-empty list"),
        ("aliases:\n  cambrian: Name\n", "cambrian: must be a non-empty list"),
        ("aliases:\n  cambrian: ['']\n", "is not text"),
        ("aliases:\n  cambrian: [5]\n", "is not text"),
        ("aliases:\n  cambrian: ['Café']\n", "plain ASCII"),
        ('aliases:\n  cambrian: ["one\\ntwo"]\n', "one line"),
        ("aliases:\n  cambrian: ['" + "x" * 201 + "']\n", "longer than 200"),
        ("aliases:\n  cambrian: [Cambrian]\n", "own name"),
        ("aliases:\n  cambrian: [cambrian]\n", "own name"),
        ("aliases:\n  cambrian: [Same, same]\n", "repeats an alias of the same entry"),
        ("aliases:\n  cambrian: [Same]\n  moon-landing: [SAME]\n", "is also an alias of cambrian"),
        ("other:\n  x: 1\n", "one key, 'aliases'"),
        ("- a\n- b\n", "one key, 'aliases'"),
        ("aliases:\n  cambrian: [A]\n  cambrian: [B]\n", "twice"),
    ],
)
def test_bad_aliases_are_refused(tmp_path: Path, body: str, message: str) -> None:
    assert message in alias_problems(tmp_path, body)


def test_every_problem_in_the_alias_file_is_reported_together(tmp_path: Path) -> None:
    text = alias_problems(tmp_path, "aliases:\n  nope: [A]\n  cambrian: ['']\n")
    assert len(text.splitlines()) == 2


def test_a_missing_alias_file_is_a_history_error(tmp_path: Path) -> None:
    data = load_curated_history(SAMPLE)
    with pytest.raises(HistoryError, match="cannot be read"):
        load_aliases(tmp_path / "nope.yaml", data)
