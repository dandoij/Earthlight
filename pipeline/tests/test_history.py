"""Tests for reading the curated history files."""

from pathlib import Path

import pytest

from earthlight_pipeline.history import (
    CATEGORIES,
    ONGOING_END_YEAR,
    HistoryData,
    HistoryError,
    category_counts,
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


def test_a_repeated_id_or_name_is_refused(tmp_path: Path) -> None:
    write(tmp_path, EVENT, "a.yaml")
    write(tmp_path, EVENT, "b.yaml")
    text = problems(tmp_path)
    assert "duplicate id: x" in text and "duplicate name in events: x" in text


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
    assert entries["great-pyramid-of-giza"].description == "Landmark, built 2541 BCE"
    assert entries["formation-of-earth"].description == "Event, 4.54 billion years ago"
    assert all(e.aliases == "" for e in entries.values())


def test_the_years_and_categories_covered() -> None:
    data = load_curated_history(SAMPLE)
    assert years_covered(data) == (-4.54e9, 1969.5)
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
    end: present
"""


def test_a_period_can_be_ongoing(tmp_path: Path) -> None:
    (period,) = load_curated_history(write(tmp_path, PERIOD)).periods
    assert period.end == ONGOING_END_YEAR > 2026
    (entry,) = search_entries(load_curated_history(tmp_path))
    assert entry.description == "Period, 66 million years ago to present"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("start: -66000000", "start: present"),  # only an end can be ongoing
        ("end: present", "end: now"),
        ("end: present", 'end: "present "'),
    ],
)
def test_present_is_only_allowed_as_the_end_of_a_period(tmp_path: Path, old: str, new: str) -> None:
    assert "periods 1 (era)" in problems(write(tmp_path, PERIOD.replace(old, new)))


def test_present_is_not_allowed_for_an_event(tmp_path: Path) -> None:
    assert "year" in problems(write(tmp_path, EVENT.replace("year: 1492", "year: present")))
