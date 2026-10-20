# Earthlight

Light travels exactly one light-year per year, so every star, planet, and galaxy is receiving a different slice of Earth's past right now. Earthlight turns that fact into a lookup tool: pick a moment in history and find out where in the universe that light is arriving today, or pick a place and see what Earth looked like in the light reaching it.

## The two modes

1. **Moment to place:** "Where in the universe is the light from this moment arriving right now?"
   Example: light that left Earth 500 years ago is now passing stars about 500 light-years away.
2. **Place to moment:** "If I stood on this star, planet, or galaxy, what would Earth look like in the light arriving there now?"
   Example: from a star 66 light-years away, you would be watching Earth as it was 66 years ago.

## Status

**In development.** Phase 0 (project setup) is complete. The repository currently contains the project skeleton, tooling, and CI only. There is no working engine, CLI, API, or web app yet. The full plan is in [`docs/PLAN.md`](docs/PLAN.md).

## Planned tech stack

- **Core and CLI:** Python 3.12 package with Typer, Rich, and Pydantic
- **Data:** SQLite database built from Gaia DR3, HYG, the NASA Exoplanet Archive, and hand-curated deep-sky and history lists
- **API:** FastAPI
- **Web app:** React, TypeScript, and Vite
- **Tooling:** uv workspace, ruff, pyright, pytest with Hypothesis, pre-commit, GitHub Actions

## Repository layout

```
packages/earthlight/   the shipped Python package (core engine and CLI)
pipeline/              data build scripts (never shipped)
apps/api/              FastAPI service (placeholder)
apps/web/              React app (placeholder)
docs/                  plan, dev setup notes
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

MIT. See [`LICENSE`](LICENSE). A Data Sources section crediting each dataset will be added once the data pipeline lands.
