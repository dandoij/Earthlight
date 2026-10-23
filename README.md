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

### Using it from the command line

The package installs an `earthlight` command with four subcommands. It is not on PyPI yet (packaging comes in a later phase), so from a clone run `uv sync` and then `uv run earthlight ...`.

| Command | Question |
|---|---|
| `earthlight when MOMENT` | Where is the light from this moment arriving right now? |
| `earthlight from PLACE` | What did Earth look like in the light arriving at this place? |
| `earthlight info PLACE` | What is known about this place? |
| `earthlight search TEXT` | Which places and history entries match this name? |

`when` guesses what kind of moment you typed: a bare number is a calendar year (`1492`), and `500 BCE`, `2004-06-15`, `3 days ago`, `66 mya`, and event names such as `apollo 11` all work. To skip the guessing, give exactly one of `--year`, `--date`, `--ago`, or `--event` instead (`earthlight when --ago "66 million years"`). Write a date that starts with a minus sign as `--date -0043-03-15`, because a bare argument that starts with a dash is read as an option. `PLACE` is a name (`Betelgeuse`, `Andromeda Galaxy`, `M31`, `Saturn`, `the Moon`) or an id from a search (`hip-27989`).

The examples below are real output, taken as if the date were 1 January 2026 and the terminal were 100 columns wide, so yours will differ a little in the numbers and the layout. A test runs every example in this section and fails if the README stops matching the program.

A year, shown as four panels (a wide terminal puts them two by two, a narrow one stacks them):

```console
$ earthlight when 1492
1492 CE
The light that left Earth then has travelled 534 light-years and is arriving at:
╭─ Famous ──────────────────────────────────────╮ ╭─ Exoplanet ────────────────────────────────────╮
│ Antares  star, Scorpius                       │ │ TOI-132 b  exoplanet, Grus                     │
│ 554 light-years away                          │ │ 534 light-years away                           │
│ range 473 to 667 light-years                  │ │ range 531 to 537 light-years                   │
│ magnitude 1.06                                │ │ magnitude 11.2                                 │
│ best estimate 19.7 years farther              │ │ best estimate 0.2 years nearer                 │
│ id hip-80763                                  │ │ id toi-132-b                                   │
╰───────────────────────────────────────────────╯ ╰────────────────────────────────────────────────╯
╭─ Visible tonight ─────────────────────────────╮ ╭─ Most precise ─────────────────────────────────╮
│ HIP 9132  star, Triangulum                    │ │ HIP 14859  star, Cepheus                       │
│ 534 light-years away                          │ │ 534 light-years away                           │
│ range 516 to 555 light-years                  │ │ range 533 to 535 light-years                   │
│ magnitude 5.84                                │ │ magnitude 7.06                                 │
│ best estimate 0.3 years farther               │ │ best estimate 0.1 years farther                │
│ id hip-9132                                   │ │ id hip-14859                                   │
╰───────────────────────────────────────────────╯ ╰────────────────────────────────────────────────╯
```

Recent light is still crossing our own neighbourhood, so there is no star to name yet:

```console
$ earthlight when "3 hours ago"
3 hours ago
The light that left Earth then has travelled 3.0 light-hours and is arriving at:
╭─ Where the light is ─────────────────────────────────────────────────────────────────────────────╮
│ Inside the heliosphere                                                                           │
│ The bubble of solar wind around the Sun, from the planets out to the heliopause.                 │
│ 0 to 122 au from the Sun                                                                         │
│ 0.00806% of the way to Proxima Centauri                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
This light has travelled about 3.0 light-hours (22 au) from Earth.
Right now it has passed Mercury, Venus, Mars, Jupiter, Saturn and Uranus and is still on its way to
Neptune.
No star is this close: the light is still crossing the Sun's own surroundings, about 0.00806% of the
way to the nearest star.
```

The other direction. Light from the most distant galaxies left before Earth existed:

```console
$ earthlight from GN-z11
GN-z11  galaxy  id gn-z11
13.4 billion light-years away. The light arriving there now left Earth between 13.4 billion years
ago and 13.3 billion years ago.
The light arriving at GN-z11 left about 13.4 billion years ago. Earth formed only about 4.54 billion
years ago, so in this light Earth does not exist yet.
```

The Sun, the Moon, and the planets are places too (`earthlight from saturn`, `earthlight info moon`). They are close enough that their distance changes every day, so it is worked out for the date instead of stored: Saturn is about 1.3 light-hours away on 1 January 2026, so from there you would see Earth as it was about an hour and twenty minutes ago. The range is the nearest and farthest the two can ever be, from the sizes of their orbits:

```console
$ earthlight info saturn
Saturn  planet  id saturn
1.3 light-hours away (range 1.1 to 1.5 light-hours)
Wikipedia: Saturn
Catalogue facts
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Fact            ┃ Value                    ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ distance au     │ 9.7118                   │
│ distance source │ jpl_approximate_elements │
└─────────────────┴──────────────────────────┘
See Earth from here: earthlight from saturn
```

Search finds them by the start of a name:

```console
$ earthlight search sat
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ Type   ┃ Name                  ┃ Detail                     ┃ Id             ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│ planet │ Saturn                │ Planet of the solar system │ saturn         │
│ event  │ Sputnik 1 is launched │ Event, 1957 CE             │ sputnik-launch │
└────────┴───────────────────────┴────────────────────────────┴────────────────┘
```

A typo gets guesses with ids you can use in the next command:

```console
$ earthlight search Betelguese
Nothing found for 'Betelguese'.
Did you mean:
  Betelgeuse  (place, id hip-27989)
```

Anything that cannot be answered prints an error and exits with code 1 (a mistyped command exits with code 2):

```console
$ earthlight when 2100
Error: 2100 CE has not happened yet, so no light from it exists. Pick a moment in the past.
```

Every command takes `--json` and then prints exactly one JSON document, the same shape the Python functions return. Errors under `--json` are also JSON on standard output, with the keys `title`, `detail`, `suggestions`, and `results`, so a script can read failures too:

```console
$ earthlight search androm --limit 1 --json
{
  "query": "androm",
  "results": [
    {
      "type": "vantage_point",
      "id": "andromeda-galaxy",
      "name": "Andromeda Galaxy (Messier 31)",
      "kind": "galaxy",
      "description": "Galaxy, 2.56 million light-years"
    }
  ],
  "suggestions": []
}
```

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

- `when(moment)` takes text (`"1492"`, `"500 BCE"`, `"2004-06-15"`, `"3 days ago"`, `"66 mya"`, or an event name such as `"apollo 11"`), a number (a decimal year), or a `datetime`. It returns one winner for each of four categories (famous, exoplanet, visible tonight, most precise), or the zone of space the light is crossing for very recent moments. When no place's range contains the moment exactly, the best place whose range comes within 5% is shown, with `approximate` set on the match and a note saying how far off it is. An event name uses the best search hit (an event's date, a period's start, a landmark's completion) and a note says which one, or calls it the closest match when its name does not contain every word you typed.
- `from_vantage(place)` takes an id (`"hip-27989"`) or a name (`"Betelgeuse"`, `"M31"`, `"saturn"`, `"the Moon"`; the Sun, Moon, and planets are worked out for the date) and lists the most important events, periods, and landmarks in the span of Earth's history whose light is arriving there (at most ten of each, with `event_total`, `period_total`, and `landmark_total` saying how many there were, and `wide_span` set when the span is over 1,000 years wide), with the world population. Light older than Earth reports that Earth does not exist yet.
- `info(place)` gives the place itself, the NASA archive details for an exoplanet, and the planets of a star.
- `search(text)` finds places and history by name; when nothing matches it offers did-you-mean guesses.
- Every deliberate failure raises a subclass of `EarthlightError` with a message written for the person who asked (a future moment, an unknown name, text that is not a moment).

## The bundled database

The package ships one read-only SQLite file, `packages/earthlight/src/earthlight/data/earthlight.db` (19.9 MB or 18.9 MiB, limit 20 MiB, committed to git). It is built by the data pipeline and checked by `packages/earthlight/tests/test_bundled_database.py`. It holds:

| Table | Contents |
|---|---|
| Stars | 40,346 Hipparcos stars with distance ranges (Gaia DR3 with Bailer-Jones where matched, otherwise Hipparcos), 409 of them with IAU proper names |
| Exoplanets | 6,356 planets from the NASA Exoplanet Archive, 1,236 linked to a host star in the star table |
| Deep sky | 121 curated objects: 33 star clusters, 60 galaxies, 13 galaxy clusters, 14 quasars, and the cosmic microwave background, from 154 to 13.79 billion light-years |
| History | 160 hand-curated entries (105 events, 33 periods, 22 landmarks) from the first stars to today |
| Population | 261 world population estimates from 10000 BCE to 2023 (Our World in Data) |
| Search | A full-text index over names, plus a trigram index built for typo-tolerant search (used from Phase 3) |

To rebuild it (this downloads every source and takes a few minutes; downloads are cached in `pipeline/.cache/`):

```powershell
uv run earthlight-build --database packages/earthlight/src/earthlight/data/earthlight.db all
```

What each source is, the real file formats, and the choices made while building are recorded in [`docs/data-sources.md`](docs/data-sources.md).

## Status

**In development.** The project skeleton, tooling, and CI are in place. The core math and data models are written and tested (the time model, input parsing, lookback math, solar system positions, and the shared data shapes), and the data pipeline has built and validated the bundled database. The Python engine answers both questions from that database (`earthlight.when`, `from_vantage`, `info`, and `search`). The `earthlight` command-line tool answers the same questions from a terminal (`when`, `from`, `info`, `search`, each with `--json`). There is no API or web app yet. The full plan is in [`docs/PLAN.md`](docs/PLAN.md).

## Planned tech stack

- **Core and CLI:** Python 3.12 package with Typer, Rich, and Pydantic (built; see above)
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
