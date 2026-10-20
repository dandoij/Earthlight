# Earthlight: Working Agreement for Claude Code

Earthlight answers two questions using the fact that light travels one light-year per year:

1. **Moment to place:** "Where in the universe is the light from this moment arriving right now?"
2. **Place to moment:** "If I stood on this star, planet, or galaxy, what would Earth look like in the light arriving there now?"

It ships as a Python package with a CLI (`earthlight`), a FastAPI service, and a React web app.

The full phased plan lives in `docs/PLAN.md`. Read it at the start of every session and resume from the first unchecked step.

## Who you are working with

- **Ian** is a CS student building this as a resume project and wants to **learn** while building. He knows TypeScript, Angular, NestJS, and C#. Python packaging, FastAPI, and React are newer to him, so connect new concepts to what he knows (for example, "FastAPI dependencies work like NestJS providers").
- He prefers plain-language explanations with real-world analogies.
- **No em dashes** in anything you write: code comments, docs, commit messages, or chat. Use colons, commas, or parentheses instead.

## Development environment

- **Windows 11 on ARM64 (Snapdragon), native, not WSL.** Use PowerShell syntax for commands you show Ian.
- Use the ARM64 builds of Python and Node.
- If an instruction could differ by CPU architecture or OS, say so and confirm before assuming.
- If a package fails to install on Windows ARM64, stop and tell Ian. Falling back to WSL2 is the agreed plan B, but it is Ian's call.

## The step workflow (follow exactly)

1. **One step = one commit.** Each step in `docs/PLAN.md` is exactly one commit. Do not combine steps or start the next step until Ian says to continue.
2. **Before starting a step**, give a 2 to 4 sentence preview of what you are about to build and why.
3. **Before committing**, run the relevant checks (ruff, pyright, pytest, and for web: lint, typecheck, test). Do not commit failing code. If a check cannot pass for a good reason, explain and ask.
4. **Commit, never push.** Ian reviews every commit and pushes himself. Never run `git push`, never force-push, never rewrite history that Ian may have pushed.
5. **After committing**, post a learning summary in chat using this template:

   ```
   ## Step X.Y: <title>
   **What changed:** files and what each one does (short)
   **Why:** the reasoning and the alternatives we rejected
   **Concepts to know:** 1 to 3 ideas worth learning from this step, explained plainly with an analogy where helpful
   **How to verify:** exact commands Ian can run to see it work
   ```

6. **Tick the step's checkbox** in `docs/PLAN.md` as part of that step's commit.
7. Then **stop and wait** for Ian.

## Commit messages

- Conventional commits: `feat:`, `fix:`, `test:`, `docs:`, `chore:`, `ci:`, `refactor:`, `data:`.
- Subject under 72 characters. Body: 1 to 4 lines explaining **why**, not just what.

## Branches and phases

- Each phase gets its own branch, named in `docs/PLAN.md` (for example `phase-1-core`). Create it from an up-to-date `main` at the start of the phase.
- Ian merges each phase into `main` through a GitHub PR.

## End of every phase: code review

The last step of every phase is a review step:

1. Run the code review agent available in this Claude Code setup (a code-review subagent or the `/review` command) over the whole phase diff: `git diff main...HEAD`.
2. Summarize the findings for Ian in three groups: **bugs**, **clear improvements**, and **judgment calls**.
3. Fix bugs and clear improvements. For judgment calls, ask Ian before changing anything.
4. Commit all fixes as the phase's final commit: `fix: address phase N review findings`, with a body listing what was fixed.
5. Post the learning summary, then tell Ian the branch is ready for a PR and suggest a PR title and description.

## README

The README is updated in every phase (there is a dedicated docs step in each phase). Keep it accurate to what currently works: never document features that do not exist yet.

## When to stop and ask Ian

Ask instead of guessing whenever:

- A data source's real columns, tables, or API differ from what `docs/PLAN.md` assumes.
- A choice affects the public interface: CLI flags, API response shapes, database schema, package name.
- You want to add a dependency not listed in the plan.
- A step turns out bigger than one reviewable commit (propose a split).
- Two reasonable approaches exist and the plan does not pick one.
- Anything would cost money, create accounts, or touch external services (PyPI, Vercel, GitHub settings). Ian does those steps himself; give him exact instructions.

Keep questions short: state the options, the tradeoff, and your recommendation.

## Data integrity rules

- **History entries use only well-known, widely agreed dates.** Every entry needs a `source` URL. Summaries are written in our own words, never copied from Wikipedia or elsewhere.
- **Never invent scientific values.** Distances, redshifts, and object facts come from the pipeline sources or a cited reference.
- Verify a data source's current format before writing code against it, and record what you found in `docs/data-sources.md`.

## Locked decisions (do not revisit without asking)

| Area | Decision |
|---|---|
| Repo | Monorepo: `packages/earthlight` (core + CLI), `pipeline/` (data build, not shipped), `apps/api`, `apps/web` |
| Python tooling | uv workspace, Python 3.12, ruff, pyright, pytest + Hypothesis, pre-commit |
| Dependencies | Runtime core needs only stdlib + Typer/Rich + Pydantic. Heavy science libs (astropy, astroquery, pandas) live only in `pipeline/` |
| Storage | SQLite, read-only at runtime, bundled inside the wheel, built `.db` committed to git |
| Stars | Gaia DR3 for distances (Bailer-Jones geometric distances for ranges), HYG for names, linked via Gaia's Hipparcos cross-match |
| Exoplanets | NASA Exoplanet Archive |
| Deep sky | Curated YAML of about 100 to 150 objects (galaxies, clusters, quasars, JWST record holders, CMB); redshift to lookback via astropy cosmology in the pipeline |
| Recent lookbacks | Solar system zones and objects (planets via JPL approximate Keplerian formulas, Voyager, Oort Cloud, interstellar space) |
| History | Hand-curated YAML: events, periods, landmarks. About 160 entries budgeted by era, back to the first stars. Well-known dates only |
| Time | Decimal years with astronomical numbering (1 BCE = 0). Users can enter any date |
| Results | Four categories: famous, exoplanet, visible tonight (simple: naked-eye brightness + constellation), most precise |
| Search | SQLite FTS5 plus trigram index; did-you-mean via difflib |
| CLI | Typer + Rich. Commands `when`, `from`, `info`, `search`. Smart argument plus override flags. Bare numbers are calendar years. `--json` everywhere |
| API | FastAPI, sync endpoints, `/v1` prefix, RFC 9457 errors, cache headers, slowapi rate limit, shared Pydantic models, OpenAPI schema snapshot test |
| Web | React + TypeScript + Vite, React Router, TanStack Query, Tailwind + Radix primitives, planetarium aesthetic, d3-geo sky map, html-to-image share cards, Vitest + Testing Library + MSW, one Playwright test, npm |
| Types | openapi-typescript generates frontend types from the API schema |
| CI | GitHub Actions: Python on Ubuntu and Windows, web job, data schema check, Dependabot |
| Hosting | Vercel for web and API on one domain (free `*.vercel.app`), Dockerfile included for portability |
| Release | TestPyPI first, then PyPI via trusted publishing on version tags |
| License | MIT for code, Data Sources section crediting every dataset |
