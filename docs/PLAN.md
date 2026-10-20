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
- [ ] **0.5 README v0**
  - **Build:** Project pitch (2 to 3 sentences), the two modes, status ("in development"), tech stack list, dev setup for Windows ARM64.
  - **Done when:** README is accurate to the repo state.
- [ ] **0.6 Phase review** (per `CLAUDE.md`)

---

## Phase 1: Core math and models (branch `phase-1-core`)

No database yet. Pure, heavily tested functions.

- [ ] **1.1 Time model**
  - **Build:** `time.py`: decimal year type, conversions from dates and astronomical years, `now()` as a decimal year, and human formatting ("1492 CE", "500 BCE", "66 million years ago", "3 hours ago").
  - **Done when:** Unit tests plus Hypothesis round-trip tests (date to decimal year to date) pass, including BCE and year 0 edges.
- [ ] **1.2 Input parser**
  - **Build:** `parse.py`: turns text into either a moment or an event-name query. Supports `1492`, `500 BCE`, `500 BC`, `2004-06-15`, `66 million years ago`, `66 mya`, `4.5 gya`, `3 days ago`. Bare numbers are calendar years. Clear error types for unparseable input. Hand-written, no date libraries.
  - **Done when:** Table-driven tests cover every format and the ambiguous cases.
- [ ] **1.3 Lookback math**
  - **Build:** `lookback.py`: moment to lookback and back, interval overlap helpers, and parallax/distance to lookback range conversions (for pipeline reuse and tests).
  - **Done when:** Tests including Hypothesis properties (round-trips, interval invariants min <= best <= max).
- [ ] **1.4 Solar system**
  - **Build:** `solar_system.py`: Earth-to-planet distance at a given date using JPL's published approximate Keplerian elements; Voyager 1 approximate distance; zone definitions (heliopause, inner and outer Oort Cloud, interstellar space) with light-travel times.
  - **Done when:** Planet distances match reference values within a documented tolerance, and tests cite where reference values came from.
- [ ] **1.5 Shared models**
  - **Build:** `models.py`: Pydantic models for `VantagePoint` (id, name, kind, lookback range, facts), `MomentResult` (four category winners, zone info, notes), `EarthSnapshot` (events, periods, landmarks with status, population, notes), `SearchResult`, `Suggestion`.
  - **Done when:** Models validate, have docstrings, and serialize to stable JSON.
- [ ] **1.6 README update** (core concepts section)
- [ ] **1.7 Phase review**

---

## Phase 2: Data pipeline (branch `phase-2-data`)

- [ ] **2.1 Pipeline scaffolding**
  - **Build:** `pipeline` workspace member with astropy, astroquery, scipy (needed by astropy cosmology), pandas, pyyaml. A `earthlight-build` command with subcommands per source. Downloads cached in `pipeline/.cache/` (gitignored).
  - **Done when:** `uv run earthlight-build --help` works.
- [ ] **2.2 Source verification**
  - **Build:** Investigate and document in `docs/data-sources.md`: HYG current version and columns; Gaia DR3 tables for the bright-star query; Hipparcos cross-match table; Bailer-Jones distance table name and columns; Exoplanet Archive table and distance columns; licenses and attribution text for each.
  - **Done when:** Doc is complete. **Ask Ian** about anything that differs from this plan.
- [ ] **2.3 Database schema**
  - **Build:** `schema.sql`: `meta` (schema_version, build date, source versions), `vantage_points` (with indexed lookback columns, kind, magnitude, constellation, facts JSON), `exoplanets`, `events`, `periods`, `landmarks`, `population`, FTS5 tables (unicode61 for search, trigram for did-you-mean).
  - **Done when:** Schema builds an empty database and a test checks every table and index exists.
- [ ] **2.4 Stars**
  - **Build:** Gaia DR3 query for bright stars with precise parallax (tune cutoffs to keep the final database under about 20 MB), Bailer-Jones distances to lookback ranges, HYG names via cross-match, constellation via astropy.
  - **Done when:** Stars load; spot checks (for example Betelgeuse, Vega, Polaris) have sane distances; counts and size reported to Ian.
- [ ] **2.5 Exoplanets**
  - **Build:** Exoplanet Archive query, distance ranges from the archive's error columns, link to host star vantage points where possible.
  - **Done when:** Planets load with host links; spot checks (for example Proxima Cen b, Kepler-22 b).
- [ ] **2.6 Deep-sky objects**
  - **Build:** `curated/deep_sky.yaml` (about 100 to 150 objects: globular clusters, Magellanic Clouds, Andromeda, well-known galaxies and clusters, famous quasars, JWST record galaxies, CMB) with distance or redshift and a source. Redshift to lookback via astropy `Planck18`. Pydantic validation.
  - **Done when:** Loads and validates; lookbacks span from tens of thousands of years to about 13.8 billion.
- [ ] **2.7 History schema and loader**
  - **Build:** Pydantic models and loader for `curated/history/*.yaml` (events, periods, landmarks). Fields include `year`, `year_uncertainty`, `category`, `region`, `summary` (own words), `importance` (1 to 5), `wikipedia`, `source`; landmarks add `built_start`, `built_end`, `destroyed`, `lat`, `lon`.
  - **Done when:** Loader validates a small sample file with tests.
- [ ] **2.8 History: deep time** (before Earth to 540 million years ago, using the ICS chart as the main source)
- [ ] **2.9 History: complex life to human evolution** (540 million to 300,000 years ago)
- [ ] **2.10 History: prehistory** (300,000 years ago to 3000 BCE)
- [ ] **2.11 History: ancient world** (3000 BCE to 500 CE)
- [ ] **2.12 History: 500 CE to 1800 CE**
- [ ] **2.13 History: 1800 CE to today**
  - **For 2.8 to 2.13:** Well-known dates only, a source per entry, own-words summaries. Target total about 160 across the six steps (roughly 5 / 20 / 15 / 35 / 40 / 45). Each commit lists its entries in the learning summary so Ian can spot-check quickly.
- [ ] **2.14 Population data**
  - **Build:** Our World in Data historical population estimates into the `population` table.
- [ ] **2.15 Build and validate the database**
  - **Build:** Full build into `packages/earthlight/src/earthlight/data/earthlight.db`. Validation tests: schema version, size limit, no duplicate ids, min <= best <= max, coverage per century from 3000 BCE to today and per era for deep time.
  - **Done when:** Tests pass; the built `.db` is committed.
- [ ] **2.16 README update** (data sources and attribution section)
- [ ] **2.17 Phase review**

---

## Phase 3: Engine (branch `phase-3-engine`)

- [ ] **3.1 Repository layer**
  - **Build:** `repository.py`: open the bundled database via `importlib.resources` in read-only URI mode; typed query functions; schema version check on open.
  - **Done when:** Tests run against the real bundled database.
- [ ] **3.2 Moment to place**
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
- [ ] **4.2 `when` command**: smart argument plus `--year`, `--date`, `--ago`, `--event` overrides; Rich output (hero line, four category panels, zone info).
- [ ] **4.3 `from` and `info` commands**: Earth snapshot and object facts with Rich layout.
- [ ] **4.4 `search` command and did-you-mean** in all commands' "not found" errors.
- [ ] **4.5 `--json` output** for every command (same shapes as the API), plus CLI tests with Typer's `CliRunner` and JSON snapshot tests.
- [ ] **4.6 README update**: CLI usage with example output. Note for Ian on recording a demo GIF.
- [ ] **4.7 Phase review**

---

## Phase 5: Packaging and release (branch `phase-5-release`)

- [ ] **5.1 Wheel build**: build backend config, database included as package data, size check, `uv build`.
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
- [ ] **8.5 Sky map**: d3-geo stereographic "where to look" map with constellation lines (open dataset, attribution added).
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
