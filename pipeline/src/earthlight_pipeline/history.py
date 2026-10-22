"""Read the curated history files into the shared Earthlight history models.

Pure logic like ``deep_sky.py``. ``curated/history/`` holds one YAML file per era. Each file is
a mapping with any of the keys ``events``, ``periods``, and ``landmarks``, each a list of
entries that match ``HistoryEvent``, ``HistoryPeriod``, and ``Landmark`` from
``earthlight.models`` (those models are the schema; there are no parallel ones here).

Entries are validated in strict mode, so a value of the wrong type is an error rather than a
silent conversion: ``year: "1492"`` (text) and ``importance: true`` are both refused. The
loader collects every problem in every file and reports them together, including a key that
appears twice in one entry (see ``curated_yaml.py``).
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from earthlight.models import HistoryEvent, HistoryPeriod, Landmark
from earthlight.time import format_year
from earthlight_pipeline.curated_yaml import load_yaml
from earthlight_pipeline.stars import SearchEntry

CATEGORIES = (
    "cosmic",
    "geological",
    "life",
    "human_origins",
    "civilization",
    "science",
    "war_politics",
    "culture",
    "technology",
)
"""The allowed values of ``category``. The model accepts any text; this fixed list keeps the
curated files consistent, so the web app can offer a filter for each."""

DESCRIPTION_REFERENCE_YEAR = 2026.0
"""The year that "N years ago" in search descriptions counts back from. It is fixed so that
rebuilding the database later gives the same text."""

_SECTIONS: dict[str, type[BaseModel]] = {
    "events": HistoryEvent,
    "periods": HistoryPeriod,
    "landmarks": Landmark,
}


class HistoryError(ValueError):
    """The history files have problems. The message lists all of them."""


@dataclass(frozen=True)
class HistoryData:
    """Everything the history files describe, ordered by file name and then by position."""

    events: tuple[HistoryEvent, ...]
    periods: tuple[HistoryPeriod, ...]
    landmarks: tuple[Landmark, ...]

    @property
    def total(self) -> int:
        return len(self.events) + len(self.periods) + len(self.landmarks)


def load_curated_history(directory: Path) -> HistoryData:
    """Read and validate every ``*.yaml`` file in ``directory``.

    Raises HistoryError listing every problem: files that cannot be read, entries that break
    their model, categories outside ``CATEGORIES``, and repeated ids or names.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise HistoryError(f"{directory} is not a directory")
    files = sorted(directory.glob("*.yaml"))
    if not files:
        raise HistoryError(f"{directory} has no .yaml files")

    found: dict[str, list[Any]] = {section: [] for section in _SECTIONS}
    origin: dict[int, str] = {}  # id() of each entry -> the name of the file it came from
    problems: list[str] = []
    for path in files:
        for section, entries in _read_file(path, problems).items():
            found[section] += entries
            origin.update((id(entry), path.name) for entry in entries)
    problems += _entry_problems(found, origin)
    if not problems and not any(found.values()):
        problems.append(f"{directory} has no history entries (every list is empty)")
    if problems:
        raise HistoryError("\n".join(problems))
    return HistoryData(
        events=tuple(found["events"]),
        periods=tuple(found["periods"]),
        landmarks=tuple(found["landmarks"]),
    )


def _read_file(path: Path, problems: list[str]) -> dict[str, list[Any]]:
    """The valid entries of one file by section. Problems are appended to ``problems``."""
    try:
        data = load_yaml(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        problems.append(f"{path.name}: cannot be read ({error})")
        return {}
    if not isinstance(data, dict) or not data or not set(data) <= set(_SECTIONS):
        problems.append(
            f"{path.name}: must be a mapping with some of the keys {', '.join(_SECTIONS)}"
        )
        return {}
    result: dict[str, list[Any]] = {}
    for section, model in _SECTIONS.items():
        items = data.get(section, [])
        if not isinstance(items, list):
            problems.append(f"{path.name}: '{section}' must be a list")
            continue
        entries = result.setdefault(section, [])
        for position, item in enumerate(items, start=1):
            label = item.get("id", "?") if isinstance(item, dict) else "?"
            try:
                entries.append(model.model_validate(item, strict=True))
            except ValidationError as error:
                details = "; ".join(
                    f"{'.'.join(str(part) for part in e['loc']) or 'entry'}: {e['msg']}"
                    for e in error.errors()
                )
                problems.append(f"{path.name} {section} {position} ({label}): {details}")
    return result


def _entry_problems(found: dict[str, list[Any]], origin: dict[int, str]) -> list[str]:
    """Problems that need a look at all the entries together.

    ``origin`` maps ``id(entry)`` to its file name, so each problem says where to look.
    """
    problems: list[str] = []
    everything = [entry for entries in found.values() for entry in entries]
    for entry in everything:
        if entry.category not in CATEGORIES:
            problems.append(
                f"{origin[id(entry)]} ({entry.id}): category '{entry.category}' "
                f"is not one of {', '.join(CATEGORIES)}"
            )
    problems += _repeats("duplicate id", [(entry.id, entry) for entry in everything], origin)
    for section, entries in found.items():
        problems += _repeats(
            f"duplicate name in {section}",
            [(entry.name.lower(), entry) for entry in entries],
            origin,
        )
    return problems


def _repeats(label: str, keyed: list[tuple[str, Any]], origin: dict[int, str]) -> list[str]:
    """One problem for each key that more than one entry has, naming their files."""
    files: dict[str, list[str]] = {}
    for key, entry in keyed:
        files.setdefault(key, []).append(origin[id(entry)])
    return [
        f"{label}: {key} (in {', '.join(names)})" for key, names in files.items() if len(names) > 1
    ]


# --- search ----------------------------------------------------------------------------------


def _when(year: float) -> str:
    # format_year writes moments less than a year before its reference as "18 days ago", which
    # would be frozen into the database and go stale. Counting from at least a year later makes
    # every such moment a calendar year ("2025 CE"); deep-time text still counts from the fixed
    # reference year, because only years after it move the reference.
    return format_year(year, now_year=max(DESCRIPTION_REFERENCE_YEAR, year + 1))


def search_entries(data: HistoryData) -> list[SearchEntry]:
    """One search entry for every event, period, and landmark.

    The description tells hits apart: "Event, 1492 CE", "Period, 3000 BCE to 30 BCE", and
    "Landmark, built 2560 BCE".
    """
    entries = [
        SearchEntry("event", e.id, e.name, "", f"Event, {_when(e.year)}") for e in data.events
    ]
    entries += [
        SearchEntry(
            "period",
            p.id,
            p.name,
            "",
            f"Period, {_when(p.start)} to {'present' if p.end is None else _when(p.end)}",
        )
        for p in data.periods
    ]
    entries += [
        SearchEntry("landmark", m.id, m.name, "", f"Landmark, built {_when(m.built_end)}")
        for m in data.landmarks
    ]
    return entries


def years_covered(data: HistoryData) -> tuple[float, float]:
    """The earliest and latest year that any entry mentions. Raises ValueError if there are none.

    An ongoing period has no end year, so only its start counts; ``has_ongoing_period`` tells
    whether the history reaches the present.
    """
    years: list[float] = []
    years += [e.year for e in data.events]
    for p in data.periods:
        years += [p.start] if p.end is None else [p.start, p.end]
    for m in data.landmarks:
        years += [m.built_start, m.built_end]
        years += [] if m.destroyed is None else [m.destroyed]
    if not years:
        raise ValueError("there are no history entries")
    return min(years), max(years)


def has_ongoing_period(data: HistoryData) -> bool:
    """Whether any period is marked ``ongoing: true``."""
    return any(p.ongoing for p in data.periods)


def category_counts(data: HistoryData) -> dict[str, int]:
    """How many entries each category has, in the order of ``CATEGORIES``."""
    entries: Iterable[Any] = [*data.events, *data.periods, *data.landmarks]
    counts = Counter(entry.category for entry in entries)
    return {category: counts[category] for category in CATEGORIES if counts[category]}
