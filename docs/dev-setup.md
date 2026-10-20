# Dev setup notes

Results of the step 0.1 smoke test, run on 2026-10-20.

## Machine

- Windows 11 on ARM64 (Snapdragon), native PowerShell, not WSL.

## Toolchain

| Tool | Version | Architecture | Notes |
|---|---|---|---|
| git | 2.51.0 | n/a | Already installed |
| Node | 24.18.0 | arm64 | Already installed |
| uv | 0.13.1 | aarch64 | Installed with `winget install --id astral-sh.uv -e` |
| Python | 3.12.15 | ARM64 | Installed with `uv python install 3.12` |

The Microsoft Store Python 3.11.9 on this machine is an x64 (AMD64) build running under emulation. Do not use it for this project. uv picks the native 3.12 ARM64 build instead.

After installing uv, open a new terminal so the updated PATH is picked up.

## Library smoke test

Installed into a throwaway venv outside the repo with `uv pip install`, then imported on Python 3.12.15 ARM64. All native wheels were available; nothing needed a compiler.

| Package | Version | Result |
|---|---|---|
| astropy | 8.0.2 | OK |
| astroquery | 0.4.11 | OK |
| pandas | 3.0.6 | OK |
| numpy | 2.5.4 | OK |
| pydantic | 2.14.1 | OK |
| typer | 0.27.3 | OK |
| rich | 15.0.0 | OK |
| fastapi | 0.150.0 | OK |
| pyyaml | 6.0.3 | OK |
| scipy | 1.18.1 | OK (see below) |

### Finding: astropy cosmology needs scipy

`astropy.cosmology.Planck18.age(0)` fails with `No module named 'scipy.integrate'` unless scipy is installed. Step 2.6 converts redshift to lookback time with `Planck18`, so the `pipeline` package needs `scipy` as a dependency. It is not in the plan's dependency list, so it needs Ian's approval. It stays in `pipeline/` only and never ships in the runtime wheel.

With scipy installed: `Planck18.age(0)` = 13.79 Gyr and `Planck18.lookback_time(10)` = 13.32 Gyr.

## Package name check

Checked 2026-10-20 against the JSON API:

| Index | `earthlight` |
|---|---|
| PyPI | not found (404), appears free |
| TestPyPI | not found (404), appears free |

A 404 means no project exists today. The name is only reserved once we upload, so there is a small chance someone claims it before the first release.

## Decisions

- Package name `earthlight` confirmed by Ian.
- `scipy` approved as a `pipeline/` dependency (not shipped in the runtime wheel).
