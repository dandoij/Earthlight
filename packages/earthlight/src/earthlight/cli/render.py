"""Rich layouts for command results.

Everything here turns a result model into something Rich can print. Nothing here reads the
clock or the database, so the layouts can be tested on hand-made models.
"""

from collections.abc import Iterable

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from earthlight.models import Match, MomentResult, ZoneInfo
from earthlight.time import SECONDS_PER_DAY, SECONDS_PER_JULIAN_YEAR

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
    if high > low:
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


__all__ = ["CategoryGrid", "big_number", "light_travel", "moment_view"]
