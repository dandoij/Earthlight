# Earthlight Implementation Plan

Follow the workflow in `CLAUDE.md`: one step per commit, learning summary after each, stop and wait for Ian. Tick each checkbox in the same commit as the step.

Each step lists **Build** (what to do) and **Done when** (how we know it is finished).

---

## Core concepts (reference)

- **Lookback:** An object L light-years away is receiving light that left Earth L years ago. Every vantage point is stored with `lookback_min`, `lookback_best`, `lookback_max` in years.
- **Moment to place:** `lookback = now - moment` (decimal years). Find vantage points whose `[lookback_min, lookback_max]` contains it.
- **Place to moment:** `moment range = now - [lookback_max, lookback_min]`. Find history overlapping that range.
- **Lookback ranges by source:**
  - 0 to about 1 day: solar system objects (planets, Voyager 1)
  - about 1 day to 4.2 years: zones (heliopause, Oort Cloud, interstellar space with "percent of the way to Proxima Centauri")
  - 4.2 years to thousands of years: stars and exoplanets (Gaia)
  - tens of thousands of years and beyond: deep-sky objects (globular clusters, Magellanic Clouds, Andromeda, galaxy clusters, distant galaxies, quasars, CMB)
- **Years:** Decimal years, astronomical numbering (1 BCE = 0, 2 BCE = -1). Display converts to "BCE/CE", "X million years ago", "3 hours ago", and so on.

## Target repo layout

```
earthlight/
├─ CLAUDE.md
├─ README.md
├─ LICENSE
├─ pyproject.toml              # uv workspace root
├─ docs/
│  ├─ PLAN.md
│  └─ data-sources.md
├─ packages/earthlight/        # shipped package: core engine + CLI
│  ├─ pyproject.toml
│  ├─ src/earthlight/
│  │  ├─ time.py  parse.py  lookback.py  solar_system.py
│  │  ├─ models.py  repository.py  engine.py  search.py
│  │  ├─ cli/
│  │  └─ data/earthlight.db
│  └─ tests/
├─ pipeline/                   # data build, never shipped
│  ├─ pyproject.toml
│  ├─ src/earthlight_pipeline/
│  ├─ curated/                 # deep_sky.yaml, history/*.yaml
│  └─ tests/
├─ apps/api/                   # FastAPI
└─ apps/web/                   # React
```

---

## Phase 0: Setup (branch `phase-0-setup`)

- [x] **0.1 Environment smoke test and name check**
  - **Build:** Confirm Python 3.12 ARM64, uv, Node ARM64, and git. In a throwaway environment, install astropy, astroquery, pandas, numpy, pydantic, typer, rich, fastapi and import each. Check whether `earthlight` is free on PyPI and TestPyPI. Record results in `docs/dev-setup.md`.
  - **Done when:** All imports succeed, or Ian has been told exactly what failed. Ian has confirmed the package name (or picked another).
- [x] **0.2 Monorepo skeleton**
  - **Build:** uv workspace root, empty `packages/earthlight` and `pipeline` members (src layout), `apps/` placeholders, `.gitignore` (including `pipeline/.cache/`), `.editorconfig`, MIT `LICENSE`.
  - **Done when:** `uv sync` works and `uv run python -c "import earthlight"` succeeds.
- [x] **0.3 Python tooling**
  - **Build:** ruff (lint + format), pyright (strict for `packages/earthlight`), pytest with one placeholder test, pre-commit running ruff on commit.
  - **Done when:** `uv run ruff check`, `uv run pyright`, `uv run pytest` all pass and pre-commit is installed.
- [x] **0.4 CI**
  - **Build:** GitHub Actions workflow: Python job on `ubuntu-latest` and `windows-latest` (ruff, pyright, pytest). Dependabot for pip and GitHub Actions.
  - **Done when:** Workflow file is valid (Ian confirms it runs green after pushing).
- [x] **0.5 README v0**
  - **Build:** Project pitch (2 to 3 sentences), the two modes, status ("in development"), tech stack list, dev setup for Windows ARM64.
  - **Done when:** README is accurate to the repo state.
- [x] **0.6 Phase review** (per `CLAUDE.md`)

---

## Phase 1: Core math and models (branch `phase-1-core`)

No database yet. Pure, heavily tested functions.

- [x] **1.1 Time model**
  - **Build:** `time.py`: decimal year type, conversions from dates and astronomical years, `now()` as a decimal year, and human formatting ("1492 CE", "500 BCE", "66 million years ago", "3 hours ago").
  - **Done when:** Unit tests plus Hypothesis round-trip tests (date to decimal year to date) pass, including BCE and year 0 edges.
- [x] **1.2 Input parser**
  - **Build:** `parse.py`: turns text into either a moment or an event-name query. Supports `1492`, `500 BCE`, `500 BC`, `2004-06-15`, `66 million years ago`, `66 mya`, `4.5 gya`, `3 days ago`. Bare numbers are calendar years. Clear error types for unparseable input. Hand-written, no date libraries.
  - **Done when:** Table-driven tests cover every format and the ambiguous cases.
- [x] **1.3 Lookback math**
  - **Build:** `lookback.py`: moment to lookback and back, interval overlap helpers, and parallax/distance to lookback range conversions (for pipeline reuse and tests).
  - **Done when:** Tests including Hypothesis properties (round-trips, interval invariants min <= best <= max).
- [x] **1.4 Solar system**
  - **Build:** `solar_system.py`: Earth-to-planet distance at a given date using JPL's published approximate Keplerian elements; Voyager 1 approximate distance; zone definitions (heliopause, inner and outer Oort Cloud, interstellar space) with light-travel times.
  - **Done when:** Planet distances match reference values within a documented tolerance, and tests cite where reference values came from.
- [x] **1.5 Shared models**
  - **Build:** `models.py`: Pydantic models for `VantagePoint` (id, name, kind, lookback range, facts), `MomentResult` (four category winners, zone info, notes), `EarthSnapshot` (events, periods, landmarks with status, population, notes), `SearchResult`, `Suggestion`.
  - **Done when:** Models validate, have docstrings, and serialize to stable JSON.
- [x] **1.6 README update** (core concepts section)
- [x] **1.7 Phase review**

---

## Phase 2: Data pipeline (branch `phase-2-data`)

- [x] **2.1 Pipeline scaffolding**
  - **Build:** `pipeline` workspace member with astropy, astroquery, scipy (needed by astropy cosmology), pandas, pyyaml. A `earthlight-build` command with subcommands per source. Downloads cached in `pipeline/.cache/` (gitignored).
  - **Done when:** `uv run earthlight-build --help` works.
- [x] **2.2 Source verification**
  - **Outcome (2026-10-20):** see `docs/data-sources.md`. Three plan changes, approved by Ian: (1) the bundled database is CC BY-NC 3.0 IGO because Gaia and Hipparcos are ESA non-commercial data (code stays MIT; `LICENSE-DATA` and the README "Data licenses" section were added in this step); (2) proper names come from the IAU Catalog of Star Names instead of HYG (HYG's CC BY-SA terms cannot be combined with non-commercial data); (3) star distances are two-tier, Gaia with Bailer-Jones ranges where matched and the Hipparcos new reduction (VizieR I/311/hip2) otherwise, because Gaia misses the famous bright stars.
  - **Build:** Investigate and document in `docs/data-sources.md`: HYG current version and columns; Gaia DR3 tables for the bright-star query; Hipparcos cross-match table; Bailer-Jones distance table name and columns; Exoplanet Archive table and distance columns; licenses and attribution text for each.
  - **Done when:** Doc is complete. **Ask Ian** about anything that differs from this plan.
- [x] **2.3 Database schema**
  - **Phase 2.2 note:** `meta` also records the data license (CC BY-NC 3.0 IGO) and each source's version or retrieval date. A star's `facts` includes `distance_source` (`gaia` or `hipparcos`). Include the `VantagePoint` fields `ra_deg`, `dec_deg`, `fame`, `host_id`, and `wikipedia`.
  - **Build:** `schema.sql`: `meta` (schema_version, build date, source versions), `vantage_points` (with indexed lookback columns, kind, magnitude, constellation, ra_deg, dec_deg, fame, host_id, wikipedia, facts JSON), `exoplanets`, `events`, `periods`, `landmarks`, `population`, FTS5 tables (unicode61 for search, trigram for did-you-mean).
  - **Done when:** Schema builds an empty database and a test checks every table and index exists.
- [x] **2.4 Stars**
  - **Phase 2.2 note (replaces the Gaia-only and HYG parts of Build):** the star universe is the Hipparcos catalogue (about 118,000 stars). Distances come from Gaia DR3 plus Bailer-Jones (`external.gaiaedr3_distance`, 16th to 84th percentile) for stars in `gaiadr3.hipparcos2_best_neighbour` (99,525 of them), and from Hipparcos parallaxes (`I/311/hip2`, via `lookback_range_from_parallax`) for the rest. V magnitude from `I/239/hip_main`, proper names from the IAU Catalog of Star Names through the Hipparcos number, constellation from astropy, coordinates in degrees. Stars without an IAU name are named "HIP n". Decide how to treat stars whose parallax error reaches the parallax (no upper distance limit). See `docs/data-sources.md` for table names, columns, and server quirks.
  - **Outcome (2026-10-21):** `uv run earthlight-build stars` builds 39,976 stars (V 8.0 limit, 14.4 MB) from the real services: 98,004 usable Gaia distances and 11,636 Hipparcos distances before the limit, 409 IAU-named. The 12 famous stars all check out. IAU-named stars use a 3 times parallax bar and others 5 times; `--no-limit` keeps all 109,640 (40.4 MB). Counts, rules, and service quirks are in `docs/data-sources.md`. Stars have ids `hip-<n>` and facts `hip` and `gaia_dr3_source_id` (text) for linking in step 2.5.
  - **Build:** Gaia DR3 query for bright stars with precise parallax (tune cutoffs to keep the final database under about 20 MB), Bailer-Jones distances to lookback ranges, HYG names via cross-match, constellation via astropy.
  - **Done when:** Stars load; spot checks (for example Betelgeuse, Vega, Polaris) have sane distances; counts and size reported to Ian.
- [x] **2.5 Exoplanets**
  - **Outcome:** 6,356 of 6,451 planets built (details in `docs/data-sources.md`, "Exoplanet build results"); 1,236 linked to host stars; planet hosts are kept in the star build; `earthlight-build all` now recreates the database.
  - **Phase 2.2 note:** use `ps` with `default_flag = 1`. 128 planets (including TRAPPIST-1) have no `sy_dist`: fall back to the host star's distance through `gaia_dr3_id` (parse the `Gaia DR3 <id>` text) or `hip_name`, otherwise omit the planet. Add the Exoplanet Archive reference paper (Christiansen et al. 2025) to the README credits once the full citation is confirmed.
  - **Build:** Exoplanet Archive query, distance ranges from the archive's error columns, link to host star vantage points where possible.
  - **Done when:** Planets load with host links; spot checks (for example Proxima Cen b, Kepler-22 b).
- [x] **2.6 Deep-sky objects (far)**
  - **Split (agreed with Ian):** SIMBAD's stored distances are unusable for near objects, so 2.6 covers only objects with redshift 0.01 or more (52 objects); the near ones are the new step 2.6b.
  - **Build:** `pipeline/curated/deep_sky.yaml` holds names, kinds, and fame only. Position and redshift come from SIMBAD (45 objects); 7 objects (JWST record galaxies, the quasar J0313-1806, the CMB) carry an inline redshift with the URL of its paper. Redshift to lookback via astropy `Planck18`, with the uncertainty described in `docs/data-sources.md`. Strict Pydantic validation; the build fails loudly, listing every problem.
  - **Outcome:** 52 objects, lookbacks from 185 million years to 13.79 billion. Also fixed astropy's constellation misspellings in the shared helper.
  - **Done when:** Loads and validates; lookbacks span from hundreds of millions to about 13.8 billion years.
- [ ] **2.6b Deep-sky objects (near)**
  - **Build:** add nearby objects to the same curated list and the same `deep-sky` command: globular clusters (Baumgardt and Vasiliev 2021), open clusters (Gaia-based catalogue such as Hunt and Reffert 2023 on VizieR), Local Group galaxies (McConnachie 2012), and nearby galaxies out to about 40 Mpc (Cosmicflows). Verify each catalogue's real format and license first and record it in `docs/data-sources.md`. The `CuratedObject` model needs a `distance` alternative to `simbad` and `inline` (a catalogue, an identifier in it, and the catalogue's own range).
  - **Done when:** About 70 near objects load with sourced distance ranges; lookbacks span from tens of thousands of years to hundreds of millions.
- [x] **2.7 History schema and loader**
  - **Build:** Pydantic models and loader for `curated/history/*.yaml` (events, periods, landmarks). Fields include `year`, `year_uncertainty`, `category`, `region`, `summary` (own words), `importance` (1 to 5), `wikipedia`, `source`; landmarks add `built_start`, `built_end`, `destroyed`, `lat`, `lon`.
  - **Done when:** Loader validates a small sample file with tests.
  - **Phase 1 review note:** reuse `HistoryEvent`, `HistoryPeriod`, and `Landmark` from `earthlight.models` instead of defining parallel models, and validate the YAML in strict mode so `fame: true` or `year: "1492"` is an error, not a silent coercion.
- [x] **2.8 History: deep time** (before Earth to 540 million years ago, using the ICS chart as the main source)
- [x] **2.9 History: complex life to human evolution** (540 million to 300,000 years ago)
- [ ] **2.10 History: prehistory** (300,000 years ago to 3000 BCE)
- [ ] **2.11 History: ancient world** (3000 BCE to 500 CE)
- [ ] **2.12 History: 500 CE to 1800 CE**
- [ ] **2.13 History: 1800 CE to today**
  - **For 2.8 to 2.13:** Well-known dates only, a source per entry, own-words summaries. Target total about 160 across the six steps (roughly 5 / 20 / 15 / 35 / 40 / 45). Each commit lists its entries in the learning summary so Ian can spot-check quickly.
- [ ] **2.14 Population data**
  - **Build:** Our World in Data historical population estimates into the `population` table.
- [ ] **2.15 Build and validate the database**
  - **Phase 2.2 note:** the validation tests also check that `meta` records the CC BY-NC 3.0 IGO data license and that `LICENSE-DATA` exists.
  - **Phase 2.3 note:** SQLite cannot check two rules inside the schema, so the validation tests must: every `facts` value is a plain scalar (no nested objects or arrays), and every `host_id` points at a vantage point of kind `star`. The build also turns on `PRAGMA foreign_keys`, fills `search_entries` (deciding which things are searchable, for example leaving out unnamed stars to save space), and calls `rebuild_search_index()` before finishing.
  - **Build:** Full build into `packages/earthlight/src/earthlight/data/earthlight.db`. Validation tests: schema version, size limit, no duplicate ids, min <= best <= max, coverage per century from 3000 BCE to today and per era for deep time.
  - **Done when:** Tests pass; the built `.db` is committed.
- [ ] **2.16 README update** (data sources and attribution section): the "Data licenses" section and `LICENSE-DATA` already exist from step 2.2; update them to match what was actually built and add the Exoplanet Archive reference citation.
- [ ] **2.17 Phase review**

---

## Phase 3: Engine (branch `phase-3-engine`)

- [ ] **3.1 Repository layer**
  - **Build:** `repository.py`: open the bundled database via `importlib.resources` in read-only URI mode; typed query functions; schema version check on open.
  - **Done when:** Tests run against the real bundled database.
- [ ] **3.2 Moment to place**
  - **Phase 1 review notes:** read the clock once per request and pass `now_year` to every helper, so one answer never mixes two "now" values. A moment after now is rejected with a friendly "that has not happened yet" error (`MomentResult.lookback_years` must be >= 0). `parse` stays unaware of the future.
  - **Build:** `engine.when(moment)`: zone or solar system handling for lookbacks under 4.2 years; candidate query by interval overlap; scoring (closeness of best estimate, narrowness of range); one winner per category (famous, exoplanet, visible tonight, most precise); graceful notes when a category has no match.
  - **Done when:** Tests for recent dates, 1492, Rome, 66 million years ago, 4.5 billion years ago, and before the first stars.
- [ ] **3.3 Place to moment**
  - **Build:** `engine.from_(vantage_id)`: events overlapping the range, periods active, landmarks with status (standing, under construction, destroyed), population, "Earth does not exist yet" for lookbacks older than about 4.54 billion years, and a notice when the range is very wide.
  - **Done when:** Tests across all lookback scales.
- [ ] **3.4 Search and did-you-mean**
  - **Build:** `search.py`: FTS5 search over vantage points and events, exact matches first; trigram candidates plus difflib for suggestions.
  - **Done when:** Tests including typos ("Betelguese", "andromedia", "fall of rom").
- [ ] **3.5 Public interface**
  - **Build:** Clean top-level functions in `earthlight/__init__.py` (`when`, `from_vantage`, `info`, `search`) with docstrings and examples.
- [ ] **3.6 README update** (Python usage example)
- [ ] **3.7 Phase review**

---

## Phase 4: CLI (branch `phase-4-cli`)

- [ ] **4.1 CLI skeleton**: Typer app, `earthlight` entry point, `--version`, friendly error handling with exit codes.
- [ ] **4.2 `when` command**: smart argument plus `--year`, `--date`, `--ago`, `--event` overrides; Rich output (hero line, four category panels, zone info). Phase 1 review note: the overrides need public per-format entry points in `earthlight.parse` (for example `parse_year`, `parse_date`, `parse_ago`) so the CLI does not rebuild strings, and bare years (capped at 9999) should be reconciled with ISO years (up to 999999).
- [ ] **4.3 `from` and `info` commands**: Earth snapshot and object facts with Rich layout.
- [ ] **4.4 `search` command and did-you-mean** in all commands' "not found" errors.
- [ ] **4.5 `--json` output** for every command (same shapes as the API), plus CLI tests with Typer's `CliRunner` and JSON snapshot tests.
- [ ] **4.6 README update**: CLI usage with example output. Note for Ian on recording a demo GIF.
- [ ] **4.7 Phase review**

---

## Phase 5: Packaging and release (branch `phase-5-release`)

- [ ] **5.1 Wheel build**: build backend config, database included as package data, size check, `uv build`. Phase 2.2 note: the package license metadata must name both licenses (MIT for code, CC BY-NC 3.0 IGO for the bundled data) and the wheel must include `LICENSE-DATA`.
- [ ] **5.2 Install test in CI**: build the wheel, install it into a clean environment on Ubuntu and Windows, run `earthlight when 1492`.
- [ ] **5.3 Release workflow**: on version tags, publish to TestPyPI, then PyPI, via trusted publishing. Give Ian exact instructions for configuring the trusted publisher on both sites (he does this himself).
- [ ] **5.4 README update**: install instructions.
- [ ] **5.5 Phase review**
- After merge, Ian tags `v0.1.0rc1` for TestPyPI, verifies install, then `v0.1.0`.

---

## Phase 6: API (branch `phase-6-api`)

- [ ] **6.1 App skeleton**: `apps/api` workspace member depending on the local `earthlight` package; settings via pydantic-settings; CORS; `/v1/health`.
- [ ] **6.2 Endpoints**: `GET /v1/when?q=`, `/v1/from/{object_id}`, `/v1/objects/{object_id}`, `/v1/search?q=`, all returning the shared models. Sync `def` handlers.
- [ ] **6.3 Errors**: RFC 9457 problem-details responses, including did-you-mean suggestions on 404s.
- [ ] **6.4 Caching and rate limiting**: cache headers, in-memory memoization, slowapi limit. Document that serverless limits are per instance.
- [ ] **6.5 Tests**: TestClient tests per endpoint plus an OpenAPI schema snapshot test.
- [ ] **6.6 Dockerfile**: slim image, non-root user, local run instructions.
- [ ] **6.7 Vercel config for the API**: verify Vercel's current Python/FastAPI setup at implementation time, and ask Ian if anything differs from expectations.
- [ ] **6.8 README update**: API section and link to the auto-generated docs.
- [ ] **6.9 Phase review**

---

## Phase 7: Web foundation (branch `phase-7-web-foundation`)

- [ ] **7.1 Scaffold**: Vite + React + TypeScript in `apps/web`; ESLint, Prettier, Vitest; CI web job (lint, typecheck, test, build).
- [ ] **7.2 Typed API client**: openapi-typescript script that generates types from the API schema, a small fetch client, TanStack Query setup, and a CI check that generated types are up to date.
- [ ] **7.3 Planetarium theme**: Tailwind setup, color and type tokens, slowly drifting star-field background that respects `prefers-reduced-motion`, base layout.
- [ ] **7.4 Routing**: React Router with `/`, `/when/:query`, `/from/:id`, `/object/:id`, and a not-found page; MSW set up for tests.
- [ ] **7.5 README update**: web dev instructions.
- [ ] **7.6 Phase review**

---

## Phase 8: Web features (branch `phase-8-web-features`)

- [ ] **8.1 Search combobox**: Radix-based, keyboard accessible, grouped results (moments, stars, galaxies), did-you-mean.
- [ ] **8.2 Moment results page**: hero line, four category cards, zone and edge-case states, loading and error states.
- [ ] **8.3 Vantage page**: object fact card beside the Earth snapshot card.
- [ ] **8.4 Object page and images**: Wikipedia image fetched client-side by stored link, with a graceful fallback.
- [ ] **8.5 Sky map**: d3-geo stereographic "where to look" map with constellation lines (open dataset, attribution added). Uses `ra_deg` and `dec_deg` from `VantagePoint`.
- [ ] **8.6 Share card**: "Save card" button exporting a PNG with html-to-image.
- [ ] **8.7 Tests**: component tests with MSW and one Playwright flow (search 1492, open a star, see the snapshot).
- [ ] **8.8 Accessibility and responsive pass**: keyboard navigation, contrast, mobile layout.
- [ ] **8.9 README update**: screenshots placeholders and feature list.
- [ ] **8.10 Phase review**

---

## Phase 9: Deploy and launch (branch `phase-9-launch`)

- [ ] **9.1 Vercel deployment**: web and API on one `*.vercel.app` domain, preview deployments per PR. Give Ian step-by-step instructions for the parts he does in the Vercel dashboard.
- [ ] **9.2 Production checks**: verify CORS, cache headers, rate limit, and error pages against the live preview.
- [ ] **9.3 Final README**: live link, screenshots, architecture diagram (Mermaid), "how it works" science explanation, data sources and attribution, dev setup, and a short project summary Ian can adapt for his resume.
- [ ] **9.4 Phase review**
- After merge: Ian tags the release, confirms the live site, and adds it to his resume.

---

## Stretch backlog (not scheduled)

- Textual full-screen "mission console" TUI
- Link-preview (Open Graph) images for shared URLs
- 3D light-cone view with react-three-fiber
- Location-aware "above your horizon right now" visibility
- Wikidata to fill quiet centuries
- Custom domain
- "Your life in starlight": plot several personal dates at once
