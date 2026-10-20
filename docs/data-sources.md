# Data sources

What each dataset is, where it came from, and what we found when we checked it. Entries are added as the code that uses them is written. Licenses and attribution wording for every source are reviewed in step 2.2 and summarized in the README Data Sources section; until then the license notes below say "not yet reviewed".

## Solar system (step 1.4)

All retrieved 2026-10-20.

### JPL approximate planetary positions

- **Page:** https://ssd.jpl.nasa.gov/planets/approx_pos.html (NASA JPL Solar System Dynamics, "Approximate Positions of the Planets").
- **Used for:** Earth-to-planet positions in `earthlight/solar_system.py`.
- **What we use:** Table 1, Keplerian elements and rates per Julian century, with respect to the mean ecliptic and equinox of J2000, **valid for 1800 AD to 2050 AD only**. The page says the elements "are not valid outside the given time-interval over which they were fit", so the code raises `ValueError` outside that interval. The other table on the page (Table 2a, 3000 BC to 3000 AD, with the Table 2b extra terms) is not used.
- **Earth** is the page's "EM Bary" row (Earth-Moon barycenter). The Earth itself is within about 4700 km of it.
- **How it was captured:** the page was downloaded as raw HTML and the table text was copied verbatim into `packages/earthlight/tests/data/jpl_table1.txt`. A test checks every one of the 72 constants in the code against that file. (A summarizing fetch tool was cross-checked against the raw page; they agreed.)
- **Published accuracy** (same page, nominal errors for 1800 to 2050): distance error in thousands of km, longitude and latitude error in arcsec. Mercury 1, 15, 1. Venus 4, 20, 1. EM Bary 6, 20, 8. Mars 25, 40, 2. Jupiter 600, 400, 10. Saturn 1500, 600, 25. Uranus 1000, 50, 2. Neptune 200, 10, 1.
- **Finding:** for Jupiter through Neptune the elements behave like orbits around the solar system **barycenter**, not the Sun. Measured against Horizons, our Neptune position is within 83,000 to 278,000 km of the barycenter-centered position but up to 1.1 million km off the Sun-centered one. The Sun wobbles around the barycenter by up to about 1.45 million km (Horizons, sampled every 5 years over 1800 to 2050). Using the formulas from the Sun, as the page describes, therefore carries that wobble as extra error for the outer planets. The tests allow for it explicitly.
- **License:** not yet reviewed.

### JPL Horizons (reference values for tests, and the Voyager 1 model)

- **Service:** https://ssd.jpl.nasa.gov/api/horizons.api (NASA JPL Horizons system API, version 1.2).
- **Planet reference vectors:** `packages/earthlight/tests/data/horizons_planets.json` records the exact query. Geocentric (`CENTER=500@399`), geometric (`VEC_CORR=NONE`), TDB, ecliptic J2000, at 1900-01-01, 1950-01-01, 2000-01-01 12:00, 2026-01-01, and 2050-01-01. Whole vectors are compared because a distance alone is blind to sideways errors when a planet is near opposition or conjunction.
- **Voyager 1 (`COMMAND=-31`, `CENTER=500@10`, the Sun):** distance from the Sun was 121.602494 au on 2012-08-25 (the day NASA says it left the heliosphere), 169.255256 au on 2026-01-01, and 183.495820 au on 2030-01-01. The model in `voyager1_distance_au` is a straight line through the 2026 and 2030 points, checked against ten Horizons points from 2012 to 2033 (worst error 0.12 au, at the 2012 end). The distance from Earth differs by up to 1 au.
- **Sun relative to the barycenter** (`COMMAND=10`, `CENTER=500@0`): minimum 94,537 km and maximum 1,447,665 km over 51 samples from 1800 to 2050.
- **License:** not yet reviewed.

### NASA Voyager 1 mission page

- **Page:** https://science.nasa.gov/mission/voyager/voyager-1/
- **Used for:** the heliopause crossing date (25 August 2012) and a speed cross-check (17.0 km/s relative to the Sun, as of 2024-08-21). Our model's radial speed is about 16.9 km/s, consistent because the total speed includes a small sideways part. The page gives no distance in au for the crossing; that distance comes from Horizons above.

### Proxima Centauri distance

- **Source:** NASA Exoplanet Archive, Planetary Systems table (`ps`), host `Proxima Cen`, default parameter set. Queried through the TAP service at https://exoplanetarchive.ipac.caltech.edu/TAP.
- **Value:** `sy_dist` = 1.30119 pc (error +0.00034 / -0.00035), which is 4.2438 light-years. `sy_plx` = 768.5 mas.
- **Why it matters:** upper bound of the "interstellar space" zone. Phase 2 will load the real Gaia-based distance for the star itself; the two may differ in the fourth digit, which does not matter for a zone boundary.
- **License:** not yet reviewed.

### Zone boundaries

| Boundary | Value | Basis |
|---|---|---|
| Heliopause | 121.6 au | Voyager 1 on the day it crossed (Horizons distance, NASA date). Varies with direction and solar cycle. |
| Inner Oort Cloud starts | 2,000 au | Conventional |
| Inner to outer Oort Cloud | 20,000 au | Conventional |
| Oort Cloud ends | 100,000 au | Conventional |
| Interstellar space ends | about 268,000 au | Proxima Centauri (above) |

The three Oort Cloud values are **conventional, approximate** numbers chosen with the project owner. Sources disagree widely: inner edge from about 250 to 5,000 au, the inner/outer split at about 20,000 au, and outer edge from 50,000 to 200,000 au. NASA's Oort Cloud page (https://science.nasa.gov/solar-system/oort-cloud/) gives no numeric boundaries at all, so there is no single authoritative citation. The values are treated as soft edges everywhere they appear.

### Constants

- Astronomical unit: 149,597,870,700 m (exact, IAU 2012 Resolution B2).
- Light-year: 9,460,730,472,580,800 m (exact: speed of light times one Julian year).
- Parsec: 648000/pi astronomical units (IAU 2015 Resolution B2).
- Speed of light: 299,792,458 m/s (exact, by the definition of the metre).
