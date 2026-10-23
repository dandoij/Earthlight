"""Rich layouts for command results.

Everything here turns a result model into something Rich can print. Nothing here reads the
clock or the database, so the layouts can be tested on hand-made models.
"""

from collections.abc import Iterable

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from earthlight.models import (
    EarthSnapshot,
    ExoplanetDetails,
    HistoryPeriod,
    Match,
    MomentResult,
    PlaceInfo,
    SearchResponse,
    SearchResult,
    SearchType,
    Suggestion,
    VantageKind,
    VantagePoint,
    ZoneInfo,
)
from earthlight.time import SECONDS_PER_DAY, SECONDS_PER_JULIAN_YEAR, DecimalYear, format_year

GRID_MIN_WIDTH = 100
"""Terminals at least this wide show the four category panels two by two."""

_CATEGORY_TITLES = (
    ("famous", "Famous"),
    ("exoplanet", "Exoplanet"),
    ("visible_tonight", "Visible tonight"),
    ("most_precise", "Most precise"),
)


def light_travel(years: float) -> str:
    """Describe a light-travel time as the distance it covers, such as ``534 light-years``."""
    seconds = years * SECONDS_PER_JULIAN_YEAR
    if seconds < 120:
        return f"{seconds:.0f} light-seconds"
    if seconds < 7200:
        return f"{seconds / 60:.0f} light-minutes"
    if seconds < 2 * SECONDS_PER_DAY:
        return f"{seconds / 3600:.1f} light-hours"
    if years < 1:
        return f"{seconds / SECONDS_PER_DAY:.0f} light-days"
    return f"{big_number(years)} light-years"


def big_number(value: float) -> str:
    """A count of years for people: ``4.2``, ``534``, ``12,000``, ``66 million``."""
    if value >= 1e9:
        return f"{float(f'{value / 1e9:.3g}'):g} billion"
    if value >= 1e6:
        return f"{float(f'{value / 1e6:.3g}'):g} million"
    if value >= 100:
        return f"{value:,.0f}"
    return f"{value:.1f}"


def _range_text(low: float, high: float) -> str:
    return f"{big_number(low)} to {big_number(high)}"


def match_panel(title: str, match: Match | None) -> Panel:
    """One category panel: the place, how far away it is, and how well it fits."""
    if match is None:
        body: RenderableType = Text("Nothing close enough (see the notes below).", style="dim")
        return Panel(body, title=title, title_align="left", border_style="dim")
    point = match.vantage_point
    where = [point.kind.value]
    if point.constellation:
        where.append(point.constellation)
    header = Text()
    header.append(point.name, style="bold")
    header.append(f"  {', '.join(where)}", style="dim")
    lines: list[RenderableType] = [header]
    lines.append(Text(f"{light_travel(point.lookback.best)} away"))
    low, high = point.lookback.minimum, point.lookback.maximum
    if big_number(low) != big_number(high):
        lines.append(Text(f"range {_range_text(low, high)} light-years", style="dim"))
    if point.magnitude is not None:
        lines.append(Text(f"magnitude {round(point.magnitude, 2):g}", style="dim"))
    if match.approximate:
        lines.append(Text("approximate: just outside its range", style="yellow"))
    elif abs(match.offset_years) >= 0.05:
        side = "nearer" if match.offset_years < 0 else "farther"
        lines.append(
            Text(f"best estimate {big_number(abs(match.offset_years))} years {side}", style="dim")
        )
    lines.append(Text(f"id {point.id}", style="dim"))
    return Panel(Group(*lines), title=title, title_align="left")


def zone_panel(zone: ZoneInfo) -> Panel:
    """The zone of space the light is crossing, for moments too recent to reach a star."""
    lines: list[RenderableType] = [
        Text(zone.name, style="bold"),
        Text(zone.description),
        Text(f"{zone.inner_au:,.0f} to {zone.outer_au:,.0f} au from the Sun", style="dim"),
    ]
    if zone.percent_to_proxima is not None:
        lines.append(
            Text(f"{zone.percent_to_proxima:.2g}% of the way to Proxima Centauri", style="dim")
        )
    return Panel(Group(*lines), title="Where the light is", title_align="left")


class CategoryGrid:
    """The four category panels: two by two on a wide terminal, stacked on a narrow one."""

    def __init__(self, panels: Iterable[Panel]) -> None:
        self.panels = tuple(panels)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        if options.max_width < GRID_MIN_WIDTH:
            yield from self.panels
            return
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(ratio=1)
        grid.add_column(ratio=1)
        for left, right in zip(self.panels[0::2], self.panels[1::2], strict=True):
            grid.add_row(left, right)
        yield grid


def moment_view(result: MomentResult) -> RenderableType:
    """The whole answer to ``when``: hero line, zone or four panels, then the notes."""
    parts: list[RenderableType] = []
    hero = Text()
    hero.append(result.moment_label, style="bold cyan")
    hero.append(
        f"\nThe light that left Earth then has travelled {light_travel(result.lookback_years)} "
        "and is arriving at:"
    )
    parts.append(hero)
    if result.zone is not None:
        parts.append(zone_panel(result.zone))
    matches = [(title, getattr(result, field)) for field, title in _CATEGORY_TITLES]
    # Inside the solar system no star is near enough: four empty panels would be noise.
    if result.zone is None or any(match is not None for _, match in matches):
        parts.append(CategoryGrid(match_panel(title, match) for title, match in matches))
    for note in result.notes:
        parts.append(Text(note, style="dim"))
    return Group(*parts)


def _place_header(point: VantagePoint) -> Text:
    header = Text()
    header.append(point.name, style="bold cyan")
    header.append(f"  {point.kind.value.replace('_', ' ')}", style="dim")
    if point.constellation:
        header.append(f", {point.constellation}", style="dim")
    header.append(f"  id {point.id}", style="dim")
    return header


def _history_table(title: str, shown: int, total: int, columns: tuple[str, ...]) -> Table:
    count = f"{shown}" if shown == total else f"{shown} of {total}"
    table = Table(title=f"{title} ({count})", title_justify="left", title_style="bold")
    for column in columns:
        table.add_column(column, overflow="fold")
    return table


def _period_end(period: HistoryPeriod, now_year: DecimalYear) -> str:
    if period.end is None:
        return "ongoing" if period.ongoing else "unknown"
    return format_year(period.end, now_year=now_year)


def _left_earth(snapshot: EarthSnapshot, now_year: DecimalYear) -> str:
    earliest = format_year(snapshot.moments.earliest, now_year=now_year)
    latest = format_year(snapshot.moments.latest, now_year=now_year)
    if earliest == latest:
        return f"in {earliest}" if "ago" not in earliest else earliest
    return f"between {earliest} and {latest}"


def snapshot_view(snapshot: EarthSnapshot, now_year: DecimalYear) -> RenderableType:
    """The answer to ``from``: what Earth looked like in the light arriving at one place."""
    point = snapshot.vantage_point
    parts: list[RenderableType] = [_place_header(point)]
    parts.append(
        Text(
            f"{light_travel(point.lookback.best)} away. The light arriving there now left Earth "
            f"{_left_earth(snapshot, now_year)}."
        )
    )
    if snapshot.events:
        table = _history_table(
            "Events", len(snapshot.events), snapshot.event_total, ("When", "Event", "Where")
        )
        for event in snapshot.events:
            table.add_row(format_year(event.year, now_year=now_year), event.name, event.region)
        parts.append(table)
    if snapshot.periods:
        table = _history_table(
            "Periods", len(snapshot.periods), snapshot.period_total, ("From", "To", "Period")
        )
        for period in snapshot.periods:
            table.add_row(
                format_year(period.start, now_year=now_year),
                _period_end(period, now_year),
                period.name,
            )
        parts.append(table)
    if snapshot.landmarks:
        table = _history_table(
            "Landmarks",
            len(snapshot.landmarks),
            snapshot.landmark_total,
            ("Finished", "Landmark", "Status", "Where"),
        )
        for landmark in snapshot.landmarks:
            table.add_row(
                format_year(landmark.built_end, now_year=now_year),
                landmark.name,
                landmark.status.value.replace("_", " "),
                landmark.region,
            )
        parts.append(table)
    if snapshot.population is not None:
        when = format_year(snapshot.population.year, now_year=now_year)
        parts.append(
            Text(
                f"World population: about {big_number(snapshot.population.people)} ({when})",
                style="bold",
            )
        )
    for note in snapshot.notes:
        parts.append(Text(note, style="dim"))
    return Group(*parts)


def _exoplanet_lines(details: ExoplanetDetails) -> list[RenderableType]:
    lines: list[RenderableType] = [Text(f"Orbits {details.host_name}")]
    if details.discovery_year is not None:
        found = f"Discovered in {details.discovery_year}"
        if details.discovery_method:
            found += f" by {details.discovery_method.lower()}"
        lines.append(Text(found))
    if details.mass_earth is not None:
        lines.append(Text(f"Mass {details.mass_earth:g} Earths"))
    if details.radius_earth is not None:
        lines.append(Text(f"Radius {details.radius_earth:g} Earths"))
    if details.orbital_period_days is not None:
        lines.append(Text(f"Orbit takes {details.orbital_period_days:g} days"))
    if details.controversial:
        lines.append(Text("Its existence is disputed.", style="yellow"))
    return lines


def info_view(details: PlaceInfo) -> RenderableType:
    """The answer to ``info``: the facts about one place."""
    point = details.vantage_point
    lookback = point.lookback
    parts: list[RenderableType] = [_place_header(point)]
    distance = f"{light_travel(lookback.best)} away"
    low, high = big_number(lookback.minimum), big_number(lookback.maximum)
    if low != high:  # a range that rounds to one number tells the reader nothing
        distance += f" (range {low} to {high} light-years)"
    parts.append(Text(distance))
    if point.magnitude is not None:
        parts.append(Text(f"Magnitude {round(point.magnitude, 2):g}"))
    if point.ra_deg is not None and point.dec_deg is not None:
        parts.append(Text(f"RA {point.ra_deg:.2f} deg, Dec {point.dec_deg:+.2f} deg"))
    if point.wikipedia:
        parts.append(Text(f"Wikipedia: {point.wikipedia}", style="dim"))
    if details.exoplanet is not None:
        parts.extend(_exoplanet_lines(details.exoplanet))
    if point.host_id:
        parts.append(Text(f"Host star: {point.host_id}"))
    if details.planet_ids:
        parts.append(Text("Planets: " + ", ".join(details.planet_ids)))
    if point.facts:
        facts = Table(title="Catalogue facts", title_justify="left", title_style="bold")
        facts.add_column("Fact", style="dim")
        facts.add_column("Value", overflow="fold")
        for key in sorted(point.facts):
            facts.add_row(key.replace("_", " "), str(point.facts[key]))
        parts.append(facts)
    parts.append(Text(f"See Earth from here: earthlight from {point.id}", style="dim"))
    return Group(*parts)


def _type_label(search_type: SearchType, kind: VantageKind | None = None) -> str:
    """What to call a hit: a place says what it is (star, galaxy), the rest say their type."""
    if search_type is SearchType.VANTAGE_POINT:
        return kind.value.replace("_", " ") if kind else "place"
    return search_type.value


def results_table(results: tuple[SearchResult, ...], title: str | None = None) -> Table:
    """Search hits as a table: what it is, its name, a detail line, and the id to use next."""
    table = Table(title=title, title_justify="left", title_style="bold")
    table.add_column("Type", style="dim")
    table.add_column("Name", style="bold", overflow="fold")
    table.add_column("Detail", overflow="fold")
    table.add_column("Id", style="dim", overflow="fold")
    for result in results:
        table.add_row(
            _type_label(result.type, result.kind),
            result.name,
            result.description or "",
            result.id,
        )
    return table


def suggestions_view(
    suggestions: tuple[Suggestion, ...], results: tuple[SearchResult, ...] = ()
) -> RenderableType | None:
    """Did-you-mean guesses and partial matches, or ``None`` if there is nothing to offer."""
    parts: list[RenderableType] = []
    if suggestions:
        parts.append(Text("Did you mean:", style="bold"))
        parts.extend(
            Text(f"  {guess.name}  ({_type_label(guess.type)}, id {guess.id})")
            for guess in suggestions
        )
    if results:
        parts.append(results_table(results, title="Partial matches"))
    return Group(*parts) if parts else None


def search_view(response: SearchResponse) -> RenderableType:
    """The answer to ``search``: the hits, or a plain "nothing found" with guesses."""
    if response.results:
        return results_table(response.results)
    parts: list[RenderableType] = [Text(f"Nothing found for '{response.query}'.")]
    guesses = suggestions_view(response.suggestions)
    if guesses is not None:
        parts.append(guesses)
    return Group(*parts)


__all__ = [
    "CategoryGrid",
    "big_number",
    "info_view",
    "light_travel",
    "moment_view",
    "results_table",
    "search_view",
    "snapshot_view",
    "suggestions_view",
]
