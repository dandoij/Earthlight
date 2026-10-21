# Earthlight

Light travels exactly one light-year per year, so every star, planet, and galaxy is receiving a different slice of Earth's past right now. Earthlight turns that fact into a lookup tool: pick a moment in history and find out where in the universe that light is arriving today, or pick a place and see what Earth looked like in the light reaching it.

## The two modes

1. **Moment to place:** "Where in the universe is the light from this moment arriving right now?"
   Example: light that left Earth 500 years ago is now passing stars about 500 light-years away.
2. **Place to moment:** "If I stood on this star, planet, or galaxy, what would Earth look like in the light arriving there now?"
   Example: from a star 66 light-years away, you would be watching Earth as it was 66 years ago.

## Core concepts

**Lookback.** An object L light-years away is receiving light that left Earth L years ago, so L is its *lookback*. A star 25 light-years away is seeing Earth as it was 25 years ago. Everything in Earthlight comes down to comparing lookbacks with moments in time:

- **Moment to place:** `lookback = now - moment`, then find places whose lookback range contains it.
- **Place to moment:** `moments = now - lookback`, then find the history that falls in that span.

**Lookback ranges.** Distances are never exact, so every place has a low, a best, and a high lookback. Matching is interval arithmetic on those ranges, and the one with the narrowest range is the most precise match.

**Moments are decimal years.** 2026.5 is about the middle of 2026. Years use astronomical numbering, so there is a year 0: 1 BCE is 0, 2 BCE is -1, and so on. Python's `datetime` cannot go before year 1, so Earthlight has its own small calendar. Text input can be a bare calendar year (`1492`), a year with an era (`500 BCE`), an ISO date (`2004-06-15`), a time ago (`3 days ago`, `66 million years ago`, `66 mya`), or an event name (`fall of rome`).

**Where the light is.** For recent moments the light is still crossing our own neighborhood. Planet positions come from JPL's approximate orbital formulas, and the zones beyond them use conventional boundaries (the Oort Cloud edges in particular are approximate, because published values disagree).

| Lookback | Where the light is |
|---|---|
| Up to about 4 hours | Among the planets (Neptune is about 4 light-hours away) |
| About 17 hours | Passing the heliopause, 121.6 au out, where Voyager 1 left the Sun's bubble in 2012 |
| 12 days to 1.6 years | Crossing the Oort Cloud (about 2,000 to 100,000 au) |
| About 4.2 years | Reaching Proxima Centauri, the nearest star |
| Longer | Passing stars, then galaxies (data not built yet) |

Sources for every number are in [`docs/data-sources.md`](docs/data-sources.md).

### What works today

The building blocks below are written and tested. They are internal modules for now; the clean top-level interface (`earthlight.when(...)`) arrives in Phase 3. This snippet runs as shown (`now_year` is passed only so the output is repeatable; by default the current time is used):

```python
from earthlight.lookback import lookback_of
from earthlight.parse import MomentQuery, parse
from earthlight.solar_system import planet_distance_au, zone_for_lookback
from earthlight.time import format_year, from_calendar

NOW = 2026.0
for text in ("1492", "500 BCE", "66 mya", "fall of rome"):
    result = parse(text, now_year=NOW)
    if isinstance(result, MomentQuery):
        lookback = lookback_of(result.moment, now_year=NOW)
        print(
            f"{text!r}: lookback {lookback:,.0f} years, shown as {format_year(result.moment, now_year=NOW)!r}"
        )
    else:
        print(f"{text!r}: event query")

print(round(planet_distance_au("mars", from_calendar(2026, 1, 1)), 3), "au to Mars on 1 Jan 2026")
print(zone_for_lookback(1 / 365.25).name)  # light from one day ago
```

```text
'1492': lookback 534 years, shown as '1492 CE'
'500 BCE': lookback 2,525 years, shown as '500 BCE'
'66 mya': lookback 66,000,000 years, shown as '66 million years ago'
'fall of rome': event query
2.411 au to Mars on 1 Jan 2026
Beyond the heliopause
```

## Status

**In development.** The project skeleton, tooling, and CI are in place, and the core math and data models are written and tested: the time model, input parsing, lookback math, solar system positions, and the shared data shapes. There is no database, search engine, CLI, API, or web app yet. The full plan is in [`docs/PLAN.md`](docs/PLAN.md).

## Planned tech stack

- **Core and CLI:** Python 3.12 package with Typer, Rich, and Pydantic
- **Data:** SQLite database built from Gaia DR3 and Hipparcos star data, Bailer-Jones distances, the IAU Catalog of Star Names, the NASA Exoplanet Archive, and hand-curated deep-sky and history lists
- **API:** FastAPI
- **Web app:** React, TypeScript, and Vite
- **Tooling:** uv workspace, ruff, pyright, pytest with Hypothesis, pre-commit, GitHub Actions

## Repository layout

```
packages/earthlight/   the shipped Python package (core engine and CLI)
pipeline/              data build scripts (never shipped)
apps/api/              FastAPI service (placeholder)
apps/web/              React app (placeholder)
docs/                  plan, dev setup notes, data sources
```

## Development setup (Windows 11 on ARM64)

These steps use PowerShell. Other platforms work too, but this project is developed natively on Windows ARM64 (no WSL). See [`docs/dev-setup.md`](docs/dev-setup.md) for the tool versions that were tested.

1. Install [uv](https://docs.astral.sh/uv/), then open a new terminal so it is on your PATH:

   ```powershell
   winget install --id astral-sh.uv -e
   ```

2. Install a native Python 3.12 (uv picks the ARM64 build on ARM64 machines):

   ```powershell
   uv python install 3.12
   ```

3. Install the workspace and the git hook:

   ```powershell
   uv sync
   uv run pre-commit install
   ```

4. Run the checks (the same ones CI runs):

   ```powershell
   uv run ruff check
   uv run ruff format --check
   uv run pyright
   uv run pytest
   ```

Node.js is not needed yet. It will be required from Phase 7, when the web app is added.

## License

The **code** is MIT. See [`LICENSE`](LICENSE).

The **database** that Earthlight will bundle is licensed separately, as **CC BY-NC 3.0 IGO**. It is built from ESA's Gaia and Hipparcos data, which carry that non-commercial license, and a combined file follows its most restrictive source. See [`LICENSE-DATA`](LICENSE-DATA). Earthlight is a free, ad-free, educational project and does not charge for anything.

## Data licenses

The database is not built yet (Phase 2). This table lists every source that is, or will be, in it, and what each one requires. Exact quotes, DOIs, and how each source was checked are in [`docs/data-sources.md`](docs/data-sources.md).

| Source | Used for | License or terms | Required credit |
|---|---|---|---|
| **Gaia DR3** (ESA) | Star positions and parallaxes | CC BY-NC 3.0 IGO | ESA, Gaia DPAC. Gaia Collaboration, Vallenari et al. 2023, A&A 674, A1 |
| **Hipparcos** (ESA) | Distances and V magnitudes, especially for bright stars Gaia cannot measure | CC BY-NC 3.0 IGO (ESA archive terms) | ESA. van Leeuwen 2007, A&A 474, 653 |
| **Bailer-Jones et al. (2021)** | Distance ranges for Gaia stars | CC BY 4.0 | Bailer-Jones et al. 2021, AJ 161, 147 |
| **IAU Catalog of Star Names** | Proper names of stars | CC BY | IAU Working Group on Star Names (https://www.iau.org/public/themes/naming_stars/) |
| **NASA Exoplanet Archive** | Exoplanets, their host stars, and distances | No license stated; acknowledgment requested | See the acknowledgment below |
| **NASA/JPL** | Planet positions (JPL approximate orbital elements) and reference values | NASA content is generally not subject to copyright in the United States; acknowledgment requested | NASA/JPL. Not an endorsement by NASA |
| **Curated YAML** (our own work) | Deep-sky objects and history entries | Own work, summaries written in our own words with a source cited for each entry; MIT | None required |

Acknowledgment requested by the NASA Exoplanet Archive:

> This research has made use of the NASA Exoplanet Archive, which is operated by the California Institute of Technology, under contract with the National Aeronautics and Space Administration under the Exoplanet Exploration Program.

The Exoplanet Archive also asks users to cite its reference paper (Christiansen et al. 2025); the full citation will be added when the exoplanet data is built.
