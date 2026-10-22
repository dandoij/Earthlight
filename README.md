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

**Moments are decimal years.** 2026.5 is about the middle of 2026. Years use astronomical numbering, so there is a year 0: 1 BCE is 0, 2 BCE is -1, and so on. Python's `datetime` cannot go before year 1, so Earthlight has its own small calendar. Text input can be a bare calendar year (`1492`), a year with an era (`500 BCE`), an ISO date (`2004-06-15`), a time ago (`3 days ago`, `66 million years ago`, `66 mya`), or an event name (`apollo 11`, `world war ii`).

**Where the light is.** For recent moments the light is still crossing our own neighborhood. Planet positions come from JPL's approximate orbital formulas, and the zones beyond them use conventional boundaries (the Oort Cloud edges in particular are approximate, because published values disagree).

| Lookback | Where the light is |
|---|---|
| Up to about 4 hours | Among the planets (Neptune is about 4 light-hours away) |
| About 17 hours | Passing the heliopause, 121.6 au out, where Voyager 1 left the Sun's bubble in 2012 |
| 12 days to 1.6 years | Crossing the Oort Cloud (about 2,000 to 100,000 au) |
| About 4.2 years | Reaching Proxima Centauri, the nearest star |
| Longer | Passing stars, then galaxies, found in the bundled database |

Sources for every number are in [`docs/data-sources.md`](docs/data-sources.md).

### Using it from Python

The package answers both questions with four functions: `when`, `from_vantage`, `info`, and `search`. This snippet runs as shown (`now_year` is passed only so the output is repeatable; by default the current time is used):

```python
import earthlight

NOW = 2026.0  # fixed only so the output is repeatable; by default the current time is used

# Moment to place: where is the light from 1492 arriving now?
answer = earthlight.when("1492", now_year=NOW)
print(f"{answer.moment_label}: {answer.lookback_years:,.0f} years of lookback")
print("famous:", answer.famous.vantage_point.name)
print("visible tonight:", answer.visible_tonight.vantage_point.name)

# Recent light is still crossing our own neighbourhood.
print(earthlight.when("3 hours ago", now_year=NOW).zone.name)

# Place to moment: what does Earth look like from Betelgeuse?
snapshot = earthlight.from_vantage("Betelgeuse", now_year=NOW)
print(snapshot.moments_label)
print([event.name for event in snapshot.events][:3])

# Names, with did-you-mean for typos.
print(earthlight.search("Betelguese").suggestions[0].name)
try:
    earthlight.when("2100", now_year=NOW)
except earthlight.EarthlightError as error:
    print(error)
```

```text
1492 CE: 534 years of lookback
famous: Antares
visible tonight: HIP 9132
Inside the heliosphere
1455 CE to 1584 CE
['Columbus reaches the Americas', 'Vasco da Gama reaches India by sea', "Luther's Ninety-five Theses"]
Betelgeuse
2100 CE has not happened yet, so no light from it exists. Pick a moment in the past.
```

- `when(moment)` takes text (`"1492"`, `"500 BCE"`, `"2004-06-15"`, `"3 days ago"`, `"66 mya"`, or an event name such as `"apollo 11"`), a number (a decimal year), or a `datetime`. It returns one winner for each of four categories (famous, exoplanet, visible tonight, most precise), or the zone of space the light is crossing for very recent moments. When no place's range contains the moment exactly, the nearest place within 5% is shown and marked as approximate in the `notes`.
- `from_vantage(place)` takes an id (`"hip-27989"`) or a name (`"Betelgeuse"`, `"M31"`) and lists the most important events, periods, and landmarks in the span of Earth's history whose light is arriving there, with the world population. Light older than Earth reports that Earth does not exist yet.
- `info(place)` gives the place itself, the NASA archive details for an exoplanet, and the planets of a star.
- `search(text)` finds places and history by name; when nothing matches it offers did-you-mean guesses.
- Every deliberate failure raises a subclass of `EarthlightError` with a message written for the person who asked (a future moment, an unknown name, text that is not a moment).

## Status

**In development.** The project skeleton, tooling, and CI are in place. The core math and data models are written and tested (the time model, input parsing, lookback math, solar system positions, and the shared data shapes), and the data pipeline has built and validated the bundled database. The Python engine answers both questions from that database (`earthlight.when`, `from_vantage`, `info`, and `search`). There is no command-line tool, API, or web app yet. The full plan is in [`docs/PLAN.md`](docs/PLAN.md).

## Planned tech stack

- **Core and CLI:** Python 3.12 package with Typer, Rich, and Pydantic
- **Data:** SQLite database built from Gaia DR3 and Hipparcos star data, Bailer-Jones distances, the IAU Catalog of Star Names, the NASA Exoplanet Archive, and hand-curated deep-sky and history lists (built; see above)
- **API:** FastAPI
- **Web app:** React, TypeScript, and Vite
- **Tooling:** uv workspace, ruff, pyright, pytest with Hypothesis, pre-commit, GitHub Actions

## Repository layout

```
packages/earthlight/   the shipped Python package (core engine and CLI)
pipeline/              data build scripts and the curated YAML lists (never shipped)
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

The **database** that Earthlight bundles is licensed separately, as **CC BY-NC 3.0 IGO**. It is built from ESA's Gaia and Hipparcos data, which carry that non-commercial license, and a combined file follows its most restrictive source. See [`LICENSE-DATA`](LICENSE-DATA). Earthlight is a free, ad-free, educational project and does not charge for anything.

## Data licenses

This table lists every source in the database and what each one requires. Exact quotes, DOIs, and how each source was checked are in [`docs/data-sources.md`](docs/data-sources.md). The license is also stored inside the database (the `data_license` entry in its `meta` table).

| Source | Used for | License or terms | Required credit |
|---|---|---|---|
| **Gaia DR3** (ESA) | Star positions and parallaxes | CC BY-NC 3.0 IGO | ESA, Gaia DPAC. Gaia Collaboration, Vallenari et al. 2023, A&A 674, A1 |
| **Hipparcos** (ESA) | Distances and V magnitudes, especially for bright stars Gaia cannot measure | CC BY-NC 3.0 IGO (ESA archive terms) | ESA. van Leeuwen 2007, A&A 474, 653 |
| **Bailer-Jones et al. (2021)** | Distance ranges for Gaia stars | CC BY 4.0 | Bailer-Jones et al. 2021, AJ 161, 147 |
| **IAU Catalog of Star Names** | Proper names of stars | CC BY | IAU Working Group on Star Names (https://www.iau.org/public/themes/naming_stars/) |
| **NASA Exoplanet Archive** | Exoplanets, their host stars, and distances | No license stated; acknowledgment requested | See the acknowledgment below |
| **NASA/JPL** | Planet positions (JPL approximate orbital elements) and reference values | NASA content is generally not subject to copyright in the United States; acknowledgment requested | NASA/JPL. Not an endorsement by NASA |
| **SIMBAD** (CDS) | Positions and redshifts of deep-sky objects | No license statement found; acknowledgment requested | See the acknowledgment below. Wenger et al. 2000, A&AS 143, 9 |
| **Hunt and Reffert (2023)**, via VizieR | Star-cluster positions and distances | Free for scientific use with the authors cited (VizieR terms); used here non-commercially | Hunt, E. L. and Reffert, S. 2023, A&A 673, A114 |
| **McConnachie (2012)** and **Cosmicflows-4** (Tully et al. 2023), via VizieR | Nearby-galaxy positions and distances | Same VizieR terms; used here non-commercially | McConnachie, A. W. 2012, AJ 144, 4. Tully, R. B., et al. 2023, ApJ 944, 94 |
| **Our World in Data** (HYDE 3.3, Gapminder v7, UN WPP 2024) | World population estimates | OWID processing CC BY 4.0; HYDE CC BY 4.0; Gapminder CC BY 4.0; UN WPP CC BY 3.0 IGO | "HYDE (2023); Gapminder (2022); UN WPP (2024), with major processing by Our World in Data" |
| **Papers cited for redshifts** | A redshift for a few record-holding objects (for example GN-z11 and JADES-GS-z14-0) | Published results; only a number is taken from each | Cited by arXiv link in `pipeline/curated/deep_sky.yaml` |
| **Curated YAML** (our own work) | Deep-sky objects and history entries | Own work, summaries written in our own words with a source cited for each entry; MIT | None required |

Acknowledgment requested by the NASA Exoplanet Archive:

> This research has made use of the NASA Exoplanet Archive, which is operated by the California Institute of Technology, under contract with the National Aeronautics and Space Administration under the Exoplanet Exploration Program.

The Exoplanet Archive also asks users to cite its reference paper: Christiansen et al. 2025, "The NASA Exoplanet Archive and Exoplanet Follow-up Observing Program: Data, Tools, and Usage", Planetary Science Journal 6, 186, DOI 10.3847/PSJ/ade3c2 (arXiv:2506.03299).

Acknowledgments requested by CDS for SIMBAD and VizieR:

> This research has made use of the SIMBAD database, CDS, Strasbourg Astronomical Observatory, France.
>
> This research has made use of the VizieR catalogue access tool, CDS, Strasbourg, France (DOI: 10.26093/cds/vizier).

The Hipparcos and Gaia distances are credited to ESA ("Credit: ESA" and "Credit: ESA, Gaia DPAC"); see the table above for the papers to cite.
