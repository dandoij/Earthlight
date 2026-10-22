# Data sources

What each dataset is, where it came from, and what we found when we checked it. Entries are added as the code that uses them is written. Step 2.2 verified every star, exoplanet, and name source against the live services and reviewed all licenses; the results are in the sections below, and the README Data Sources section (step 2.16) will summarize them.

Contents: [Solar system (step 1.4)](#solar-system-step-14), [Stars, exoplanets, and names (step 2.2)](#stars-exoplanets-and-names-step-22), [Licenses and attribution](#licenses-and-attribution), [Decisions made in step 2.2](#decisions-made-in-step-22).

## Solar system (step 1.4)

All retrieved 2026-10-20.

### JPL approximate planetary positions

- **Page:** https://ssd.jpl.nasa.gov/planets/approx_pos.html (NASA JPL Solar System Dynamics, "Approximate Positions of the Planets").
- **Used for:** Earth-to-planet positions in `earthlight/solar_system.py`.
- **What we use:** Table 1, Keplerian elements and rates per Julian century, with respect to the mean ecliptic and equinox of J2000, **valid for 1800 AD to 2050 AD only**. The page says the elements "are not valid outside the given time-interval over which they were fit", so the code raises `ValueError` outside that interval. The other table on the page (Table 2a, 3000 BC to 3000 AD, with the Table 2b extra terms) is not used.
- **Earth** is the page's "EM Bary" row (Earth-Moon barycenter). The Earth is on average about 4,700 km from it (the exact offset varies with the Moon's distance).
- **How it was captured:** the page was downloaded as raw HTML and the table text was copied verbatim into `packages/earthlight/tests/data/jpl_table1.txt`. A test checks every one of the 72 constants in the code against that file. (A summarizing fetch tool was cross-checked against the raw page; they agreed.)
- **Published accuracy** (same page, nominal errors for 1800 to 2050): distance error in thousands of km, longitude and latitude error in arcsec. Mercury 1, 15, 1. Venus 4, 20, 1. EM Bary 6, 20, 8. Mars 25, 40, 2. Jupiter 600, 400, 10. Saturn 1500, 600, 25. Uranus 1000, 50, 2. Neptune 200, 10, 1.
- **Finding:** for Jupiter through Neptune the elements behave like orbits around the solar system **barycenter**, not the Sun. Measured against Horizons, our Neptune position is within 83,000 to 278,000 km of the barycenter-centered position but up to 1.1 million km off the Sun-centered one. The Sun wobbles around the barycenter by up to about 1.45 million km (Horizons, sampled every 5 years over 1800 to 2050). Using the formulas from the Sun, as the page describes, therefore carries that wobble as extra error for the outer planets. The tests allow for it explicitly.
- **License:** see [Licenses and attribution](#licenses-and-attribution) (NASA/JPL).

### JPL Horizons (reference values for tests, and the Voyager 1 model)

- **Service:** https://ssd.jpl.nasa.gov/api/horizons.api (NASA JPL Horizons system API, version 1.2).
- **Planet reference vectors:** `packages/earthlight/tests/data/horizons_planets.json` records the exact query. Geocentric (`CENTER=500@399`), geometric (`VEC_CORR=NONE`), TDB, ecliptic J2000, at 1900-01-01, 1950-01-01, 2000-01-01 12:00, 2026-01-01, and 2050-01-01. Whole vectors are compared because a distance alone is blind to sideways errors when a planet is near opposition or conjunction.
- **Voyager 1 (`COMMAND=-31`, `CENTER=500@10`, the Sun):** distance from the Sun was 121.602494 au on 2012-08-25 (the day NASA says it left the heliosphere), 169.255256 au on 2026-01-01, and 183.495820 au on 2030-01-01. The model in `voyager1_distance_au` is a straight line through the 2026 and 2030 points, checked against twelve Horizons points from 2012 to 2035, including those two (worst error 0.12 au, at the 2012 end; 0.035 au at 2035-01-01). The distance from Earth differs by up to 1 au.
- **Sun relative to the barycenter** (`COMMAND=10`, `CENTER=500@0`): minimum 94,537 km and maximum 1,447,665 km over 51 samples from 1800 to 2050.
- **License:** see [Licenses and attribution](#licenses-and-attribution) (NASA/JPL).

### NASA Voyager 1 mission page

- **Page:** https://science.nasa.gov/mission/voyager/voyager-1/
- **Used for:** the heliopause crossing date (25 August 2012) and a speed cross-check (17.0 km/s relative to the Sun, as of 2024-08-21). Our model's radial speed is about 16.9 km/s, consistent because the total speed includes a small sideways part. The page gives no distance in au for the crossing; that distance comes from Horizons above.

### Proxima Centauri distance

- **Source:** NASA Exoplanet Archive, Planetary Systems table (`ps`), host `Proxima Cen`, default parameter set. Queried through the TAP service at https://exoplanetarchive.ipac.caltech.edu/TAP.
- **Value:** `sy_dist` = 1.30119 pc (error +0.00034 / -0.00035), which is 4.2438 light-years. `sy_plx` = 768.5 mas.
- **Why it matters:** upper bound of the "interstellar space" zone. Phase 2 will load the real Gaia-based distance for the star itself; the two may differ in the fourth digit, which does not matter for a zone boundary.
- **License:** see [Licenses and attribution](#licenses-and-attribution) (NASA Exoplanet Archive).

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

## Stars, exoplanets, and names (step 2.2)

All checked 2026-10-20 against the live services. Spot checks use stars everyone knows, so a wrong join shows up at once.

### Summary of what changed from the plan

| Plan assumption | What the live data showed | Resolution |
|---|---|---|
| "Gaia DR3 for distances" works for the stars users care about | Gaia has only 150 sources brighter than magnitude 3 (105 with a parallax). Only 1 of 12 famous stars tested (Proxima Centauri) is in the Gaia to Hipparcos cross-match. Betelgeuse, Sirius, Vega, Polaris, Rigel, Procyon, Arcturus, Pollux, Deneb, Aldebaran, and Antares are all missing. | Two-tier distances: Gaia with Bailer-Jones ranges where matched, otherwise the Hipparcos new reduction. |
| HYG for names | HYG is CC BY-SA 4.0 (share-alike), which cannot be combined with the ESA non-commercial data in one database. Its proper names are copied from the IAU list anyway. | Names come from the IAU Catalog of Star Names (CC BY). Constellations from astropy. |
| Everything can be credited under an MIT project | Gaia and Hipparcos data are CC BY-NC 3.0 IGO. | Code stays MIT. The built database is licensed separately as non-commercial. |
| Bailer-Jones table is a "DR3" table | It is `external.gaiaedr3_distance`, built on EDR3. EDR3 and DR3 share source ids, so the join still works. | Documented. |

### Hipparcos, new reduction (distance fallback and V magnitudes)

- **Service:** VizieR TAP at `https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync` (ADQL, CSV output). Table names contain slashes and must be double-quoted in queries.
- **`I/311/hip2`** (van Leeuwen 2007, "Validation of the new Hipparcos reduction", A&A 474, 653, DOI 10.1051/0004-6361:20078357): 117,955 rows, every one with a parallax. Columns used: `HIP`, `Plx` (mas), `e_Plx` (mas), `Hpmag`.
- **`I/239/hip_main`** (the original Hipparcos catalogue): 118,218 rows, 118,217 with `Vmag`, 117,955 with `Plx`. This is the source of apparent V magnitudes for the "visible tonight" category. V magnitudes for the famous stars match HYG's `mag` (for example Sirius -1.44, Vega 0.03, Betelgeuse 0.45, Polaris 1.97).
- **Distance ranges** from `1000 / (Plx +/- e_Plx)` parsecs, converted to light-years (1 sigma, rounded), using the same method as `earthlight.lookback.lookback_range_from_parallax`: Sirius 8.6 ly, Procyon 11.4 to 11.5, Vega 25.0 to 25.1, Pollux 33.7 to 33.9, Arcturus 36.5 to 36.9, Aldebaran 65.6 to 67.7, Polaris 426.3 to 439.0, Betelgeuse 441.9 to 570.2, Antares 473.4 to 667.0, Rigel 791.6 to 948.1, Deneb 1,240 to 1,639, Proxima Centauri 4.2. Where `Plx - e_Plx` reaches zero, the range has no upper limit and the star needs another treatment (to be decided in step 2.4).
- **Caveat:** simple parallax inversion is only trustworthy for precise parallaxes. Every famous star above has a parallax at least 5.9 times its error.

### Gaia DR3

- **Service:** Gaia Archive TAP at `https://gea.esac.esa.int/tap-server/tap/sync` (`REQUEST=doQuery`, `LANG=ADQL`, `FORMAT=csv`).
- **`gaiadr3.gaia_source`:** columns confirmed: `source_id`, `ra` and `dec` (degrees), `parallax` and `parallax_error` (mas), `parallax_over_error`, `phot_g_mean_mag`, `ruwe`.
- **`gaiadr3.hipparcos2_best_neighbour`** (Hipparcos new reduction matched to Gaia): 99,525 rows of about 118,000 Hipparcos stars. Columns: `source_id`, `original_ext_source_id` (the Hipparcos number), `angular_distance` (arcsec), `number_of_neighbours`, `xm_flag`. The other 18,000 or so Hipparcos stars have no Gaia match and use the Hipparcos distances.
- **Bright stars:** of the matched stars only 421 are brighter than G = 4. The famous bright stars saturate Gaia's detectors and are missing, as listed above.
- **Server quirks seen:** queries against `TAP_SCHEMA` fail with HTTP 500 (a bug in the archive's authorization layer), and a `WHERE` clause with a parenthesized `AND ( ... OR ... )` group also fails with HTTP 500. Plain `WHERE`, `IN (...)` lists, and joins work. Use simple conditions.

### Bailer-Jones distances

- **License:** CC BY 4.0. The GAVO data center, where the catalogue originates, states: "The Gaia eDR3 (photo-) geometric distances catalogue. is licensed under the Creative Commons Attribution 4.0 License" (https://dc.g-vo.org/gedr3dist/q/cone/info). It is credited separately and does not change the license of the combined database. Our copy is read from the Gaia Archive replica, which also carries ESA's terms for the archive.
- **Table:** `external.gaiaedr3_distance` in the Gaia Archive, replicated from the GAVO data center. Reference: Bailer-Jones et al. 2021, "Estimating Distances from Parallaxes. V. Geometric and Photogeometric Distances to 1.47 Billion Stars in Gaia Early Data Release 3", AJ 161, 147, DOI 10.3847/1538-3881/abd806.
- **Columns:** `source_id`, `r_med_geo`, `r_lo_geo`, `r_hi_geo`, `r_med_photogeo`, `r_lo_photogeo`, `r_hi_photogeo` (all in parsecs), and `flag`. Join on `source_id`.
- **Meaning:** `r_lo_geo` and `r_hi_geo` are the **16th and 84th percentiles** of the geometric distance posterior, described as "1-sigma-like" bounds. So `lookback_min` and `lookback_max` for a Gaia star are a roughly 68% interval, not hard limits. The photogeometric columns also exist; the plan uses the geometric ones.
- **`flag`:** the archive says not to use it for filtering.
- **Example (Proxima Centauri, Gaia source 5853498713190525696):** parallax 768.067 mas (parallax over error 15,400), Bailer-Jones geometric distance about 1.3 pc. HYG's Hipparcos-based distance was 1.2959 pc, the Exoplanet Archive has 1.30119 pc.

### NASA Exoplanet Archive

- **Service:** TAP at `https://exoplanetarchive.ipac.caltech.edu/TAP/sync`, table `ps` (Planetary Systems). Use `default_flag = 1` for one row per planet.
- **Columns used:** `pl_name`, `hostname`, `sy_dist` (pc) with `sy_disterr1` (upper) and `sy_disterr2` (lower, negative), `sy_vmag`, `ra`, `dec` (degrees), `gaia_dr3_id` (text such as `Gaia DR3 3767805209112436736`), `gaia_dr2_id`, `hip_name` (text such as `HIP 51260`), `disc_year`, `discoverymethod`, `sy_pnum`, `pl_controv_flag`. Column list obtained from `TAP_SCHEMA.columns`.
- **Counts:** 6,451 planets around 4,847 hosts. 6,323 (98.0%) have `sy_dist`, 6,215 (96.3%) also have both error columns, 6,129 (95.0%) have `sy_vmag`, 6,053 (93.8%) have `gaia_dr3_id`, 1,167 (18.1%) have `hip_name`. 58 are flagged controversial.
- **Distance quality:** half-width of the error interval divided by distance has median 1.0%, 90th percentile 4.0%, maximum 71%. The sign convention held for every row (`sy_disterr1` is not negative, `sy_disterr2` is not positive). Nearest: Proxima Centauri b (1.30119 pc). Farthest: KMT-2024-BLG-0176L b (8,340 pc).
- **Gap to handle in step 2.5:** 128 planets (2%) have no `sy_dist` in the default parameter set, including TRAPPIST-1 b and its siblings. For these, use the host star's Bailer-Jones distance through `gaia_dr3_id` where available, and otherwise leave the planet out.
- **Linking to stars:** match `gaia_dr3_id` to a star's Gaia source id (93.8% of planets), then `hip_name` (the remaining few).

### IAU Catalog of Star Names (proper names)

- **File:** https://www.pas.rochester.edu/~emamajek/WGSN/IAU-CSN.txt, maintained by the IAU Working Group on Star Names; last updated 2022-04-04. The IAU's public page is https://www.iau.org/public/themes/naming_stars/ and the file asks users to cite it.
- **Content:** 451 named objects, 411 with a Hipparcos number (no duplicates), the rest being stars outside the Hipparcos catalogue such as exoplanet hosts. All 8 famous test stars are present (Betelgeuse, Vega, Polaris, Sirius, Rigel, Proxima, Procyon, Arcturus). The IAU name for HIP 70890 is just "Proxima".
- **Parsing:** the columns are not reliably aligned (the Greek-letter column breaks fixed-width parsing, and the header line starts with `#` while data lines do not). Anchor on the date column: the four fields before it are always HIP, HD, right ascension, and declination, and the name is the first token. Comment lines begin with `#` or `$`. Names with diacritics are in a second column.
- **HYG, evaluated and not used (license):** HYG is actively maintained at https://codeberg.org/astronexus/hyg. On 2026-10-20 its page named v4.4 (`hyg/CURRENT/hyg_v44.csv.gz`) as current, with commits dated 2026-07-12, and states "This work is licensed under a Creative Commons Attribution-ShareAlike 4.0 International License." That share-alike license cannot be combined with the ESA non-commercial terms in one database, which is the only reason it is not used. Our checks used v4.1 (`hygdata_v41.csv`, an older copy: 119,626 rows, 37 columns, 117,951 with a Hipparcos number, 465 proper names, `ra` in **hours**). Its proper names come from the IAU list above.

### Constellations

`astropy.coordinates.get_constellation` works offline with no download, for both full and short names. Spot checks: Betelgeuse in Orion (Ori), Vega in Lyra (Lyr), Polaris in Ursa Minor (UMi), Sirius in Canis Major (CMa), Proxima in Centaurus (Cen).

## Star build results (step 2.4)

Built from the real services on 2026-10-21 with `uv run earthlight-build stars`. The star universe is the 118,218 entries of the Hipparcos main catalogue, and each becomes a vantage point with id `hip-<number>`.

### What happened to the 118,218 entries

| Outcome | Stars | Why |
|---|---|---|
| Distance from Gaia with Bailer-Jones | 98,004 | Matched in Gaia DR3 and has a Bailer-Jones geometric distance |
| Distance from Hipparcos | 11,636 | No usable Gaia distance, and the Hipparcos parallax is precise (at least 5 times its error) |
| Left out: `parallax_not_precise` | 7,865 | No Gaia distance and the Hipparcos parallax is under 5 times its error (3 times for IAU-named stars) |
| Left out: `non_positive_parallax` | 450 | Hipparcos parallax of zero or less |
| Left out: `no_position` | 263 | No position in the main catalogue |

That is 109,640 usable stars. The default magnitude limit (below) then keeps 39,976 of them.

### Magnitude limit and database size

The plan asks for the whole database to stay under about 20 MB. Measured on the real data, with exoplanets, history, and deep-sky objects still to come, the stars alone are:

| Unnamed stars no fainter than | Stars | Database size |
|---|---|---|
| V 6.5 (naked eye) | 8,856 | 3.5 MB |
| V 7.5 | 25,161 | 9.4 MB |
| **V 8.0 (the default)** | **39,976** | **14.4 MB** |
| V 8.5 | 58,860 | 21.8 MB |
| V 9.5 | 92,551 | 34.2 MB |
| No limit (`--no-limit`) | 109,640 | 40.4 MB |

Stars with an IAU name, and stars within 12 light-years, are always kept whatever their magnitude. At the default limit the build has 409 IAU-named stars, 420 searchable stars, and a fame spread of 0: 39,556, 2: 78, 3: 200, 4: 119, 5: 23.

### Rules chosen in this step

- **Distance source:** Gaia with Bailer-Jones when the star has a match and the match has a distance (`0 < r_lo_geo <= r_med_geo <= r_hi_geo`), otherwise the Hipparcos new reduction with a 1 sigma range from `earthlight.lookback.lookback_range_from_parallax`. The source is stored in the star's `facts` as `distance_source`. Gaia lists some very bright stars (for example Aludra and Polis) with no parallax or distance at all, and these fall back to Hipparcos.
- **Parallax precision:** a Hipparcos parallax must be at least 5 times its error. For IAU-named stars the bar is 3 times, because Alnilam (3.7) and Aludra (4.1) would otherwise be missing. Their ranges are wide but honest: Alnilam 1,553 to 2,718 ly and Aludra 1,599 to 2,630 ly, both about 2,000 light-years as expected. Two named stars still cannot be built: Alula Australis has no Hipparcos parallax or position, and Polis has a parallax of 0.09 with an error of 0.28.
- **Fame** (an editorial rule, not a measurement): 0 by default. An IAU-named star scores 2, rising to 3 if V is at most 6, 4 if at most 3, and 5 if at most 1.5. Any star within 12 light-years scores at least 3.
- **Searchable stars** are those with a fame above 0 (about 420). Every other star is stored but not in the search indexes, which keeps them small. Search entries carry the aliases `HIP n` and `HD n`.
- **Names:** the IAU diacritic spelling (for example "Chason" with a hacek, "Belenos" with accents). IAU names with several words are kept whole ("Alula Australis", "Proxima Centauri").
- **Facts stored per star:** `hip`, `distance_source`, and where known `hd`, `spectral_type`, `parallax_mas`, and `gaia_dr3_source_id` (as text, because the number is too large for JSON).
- **Positions** are the Hipparcos ICRS positions in degrees (epoch 1991.25), wrapped into 0 to 360. Proper motion is ignored, which is far below sky-map precision. Constellations are astropy's full names.

### Spot checks (from the built database)

| Star | Lookback (ly) | Source |
|---|---|---|
| Proxima Centauri | 4.2465 | Gaia |
| Sirius | 8.57 to 8.64 | Hipparcos |
| Procyon | 11.4 to 11.5 | Hipparcos |
| Vega | 25.0 to 25.1 | Hipparcos |
| Pollux | 33.7 to 33.9 | Hipparcos |
| Arcturus | 36.5 to 36.9 | Hipparcos |
| Aldebaran | 65.6 to 67.7 | Hipparcos |
| Polaris | 426.3 to 439.0 | Hipparcos |
| Betelgeuse | 441.9 to 570.2 | Hipparcos |
| Antares | 473.4 to 667.0 | Hipparcos |
| Rigel | 791.6 to 948.1 | Hipparcos |
| Deneb | 1,240 to 1,639 | Hipparcos |

Proxima Centauri's Gaia and Bailer-Jones distance is 1.3019 pc, which is 4.2465 light-years. The Exoplanet Archive's 1.30119 pc (used for the zone boundary in step 1.4) differs in the third decimal place, which does not matter for a zone edge.

### Things learned about the services

- **Gaia returns at most 50,000 rows per query and a 20,000-number batch takes about 45 seconds.** The build asks for Hipparcos numbers in batches of 20,000, seven batches in all (about five minutes the first time).
- **The Gaia archive sometimes drops a connection** (`RemoteDisconnected`). The download layer retries dropped connections, timeouts, and HTTP 429, 502, 503, and 504 with a doubling pause, and fails at once on errors that cannot succeed (404, 500, a missing file).
- **Completed batches stay in the cache**, so a build that fails partway resumes where it stopped.
- **One impossible declination crashes astropy for the whole batch.** Positions are checked before the constellation step, and bad stars are counted as `invalid_position`.
- **SQLite does not shrink a file when rows are deleted**, so a rebuilt database keeps its old size. The writer vacuums the file at the end.
- VizieR returns `I/311/hip2` positions in columns named `RArad` and `DErad` whose values are degrees. The build uses the main catalogue's `RAICRS` and `DEICRS` instead.

## Exoplanet build results (step 2.5)

Run on the full archive: 6,451 default-parameter planets, of which **6,356** were built.

### Distances

- **Archive range (6,215 planets):** `sy_dist` with its upper and lower error columns.
- **Host star range (141 planets):** where the archive has no distance or no error bars, the host's Bailer-Jones 16th, 50th, and 84th percentile distances, found through the `Gaia DR3 <id>` text in `gaia_dr3_id`. TRAPPIST-1 is one of these (40.62 light-years).
- **Left out (95 planets):** 51 with no distance anywhere (`no_distance`) and 44 with a distance but no usable error bars and no host range (`no_distance_error`).
- A range of zero width is never built, because it would make a planet look perfectly precise. Only 3 of the 108 planets without error bars had a parallax error to build a range from, so the host range is the fallback.
- The 128 planets without `sy_dist` mentioned in step 2.2: 77 were rescued through the host star, 51 left out.

### Host links

- A planet links to its host star (`host_id`) through its Hipparcos number (`hip_name`) or its Gaia source id. 1,236 planets are linked.
- Only 650 of the 1,167 planets with a Hipparcos host had that host in the magnitude 8 star database. The star build now **keeps every planet host** (862 stars) with fame at least 1 and the lower parallax bar, so the links exist. Because planets depend on those stars, the stars build refuses to run on a database that already has planets; `earthlight-build all` recreates the database first.

### Rules chosen in this step

- Every built planet is searchable (6,356 entries). 58 are flagged controversial.
- Fame: a short editorial list (51 Peg b, HD 209458 b, Proxima Cen b, TRAPPIST-1 e at 4; Kepler-22 b at 3), at least 3 within 12 light-years, otherwise 1.
- Extra facts stored: `distance_source` (`exoplanet_archive`, `bailer_jones_host`, or `host_star`), `planets_in_system`, `gaia_dr3_host_id`. Radius, mass, period, discovery year and method live only in the `exoplanets` table (no Pydantic model yet).
- Database size with stars and planets: **19.6 MB**, close to the 20 MB budget.

### Spot checks

| Planet | Lookback | Note |
|---|---|---|
| Proxima Cen b | 4.24 ly | host `hip-70890` |
| Teegarden's Star d | 12.49 ly | |
| 51 Peg b | 50.43 ly | host `hip-113357` |
| HD 209458 b | 157.54 ly | |
| Kepler-22 b | 634.84 ly | |
| TRAPPIST-1 b and e | 40.62 ly | host range |
| KMT-2024-BLG-0176L b | about 27,201 ly | microlensing, far away |

## Deep-sky build results (step 2.6)

The curated list `pipeline/curated/deep_sky.yaml` holds **52 far objects**: 24 galaxies, 14 quasars, 13 galaxy clusters, and the cosmic microwave background. The YAML holds names, kinds, and fame only. Every number comes from SIMBAD (45 objects) or from a redshift typed next to the URL of its paper (7 objects).

### What SIMBAD can and cannot do

Checked against the live TAP service at https://simbad.cds.unistra.fr/simbad/sim-tap/sync (no account). The `ident` table matches any name, and joins to `basic` for `ra`, `dec`, and the redshift columns `rvz_redshift`, `rvz_err`, `rvz_type` (`z` means the error is in redshift; `v` and `c` mean km/s), `rvz_qual` (grade A best to E worst), and `rvz_bibcode`.

- **Names are padded.** Catalogue numbers are stored with extra spaces ("M  31", "NGC  1300", "ACO  1656"), so the build asks for the one, two, and three space spellings. "NAME ..." identifiers are exact.
- **Redshift is only a distance far away.** Andromeda's SIMBAD redshift is negative and the Magellanic Clouds' are tiny, because their own motion dominates. The build refuses any redshift below 0.01 (about 130 million light-years).
- **SIMBAD's stored distances (`mesDistance`) are not usable for near objects.** M13 is listed as "0.008 Mpc" and the LMC as "0.05 Mpc", rounded to one digit, with one to four values since 2000 for each globular cluster checked. Near objects need proper catalogues, which is the new step 2.6b.
- **Redshift quality varies.** Many values are rounded ("Mrk 421: 0.03", "Ton 618: 2.2"); the build treats a missing error as half a unit of the last digit. Grade E is refused: SMACS 0723 (0.39, grade E) was left out for that reason.
- **Some famous objects are not in SIMBAD under any name** (the JWST record galaxies). Their redshifts are inline, each verified against the paper's own page.

### Rules chosen in this step

- **Redshift to lookback:** astropy's `Planck18` cosmology (Planck 2018 VI). Range: lookback at z minus and plus one uncertainty, where the uncertainty is the redshift's own error combined in quadrature with a 300 km/s peculiar velocity floor, then widened by 0.145 percent on each side (the Planck age uncertainty, 13.787 plus or minus 0.020 billion years). Without the widening the CMB would get a range of zero width.
- **Lookback is light-travel time to Earth.** The project treats the trip from Earth to the object as the same length. For high redshift that is a simplification (the universe expanded while the light travelled), noted here and not hidden.
- **Cosmology is a choice.** Some distance-ladder measurements give a faster expansion rate (H0 near 73 instead of the Planck 67.7). Age scales roughly as 1/H0, so that would shorten the oldest lookbacks by about a billion years. The displayed range reflects only the Planck fit.
- **Inline values:** JADES-GS-z14-0 z = 14.32 (+0.08, -0.20; the average error 0.14 is used), MoM-z14 z = 14.44 plus or minus 0.02, JADES-GS-z13-1-LA z = 13.01 (systemic, from Lyman-alpha 13.05), GN-z11 z = 10.603 and GHZ2 z = 12.34 (no error stated), J0313-1806 z = 7.6423 plus or minus 0.0013, and the CMB at the redshift of last scattering z* = 1089.80 plus or minus 0.21 (Planck 2018 VI Table 2, last column).
- **Everything is searchable**, by name and aliases (for example "Abell 1656" finds the Coma Cluster).
- **Facts stored:** `redshift`, `redshift_uncertainty`, `redshift_source` (a SIMBAD bibcode or the paper's URL), `cosmology`, `simbad_id`, `simbad_type`.

### Results

Lookbacks run from 185 million years (the Hydra Cluster) to 13.79 billion years (the CMB, 13,786.5 million years). Spot checks: Coma Cluster 332 million years, 3C 273 2.04 billion, Bullet Cluster 3.49 billion, TON 618 10.8 billion, JADES-GS-z14-0 13.50 billion. The database with all deep-sky objects added is about 0.2 MB.

### Other findings

- **astropy misspells three constellations and pads one:** "Chamaleon", "Ophiucus", "Pisces Austrinus", and "Crux " with a trailing space. The shared helper now corrects them to the IAU names, and a test checks all 88.
- **Wikipedia rate-limits bursts** (HTTP 429 after about 30 quick requests). Article titles were checked one request every few seconds; "NGC 4676" and "Pandora's Cluster" are redirects, so the file uses "Mice Galaxies" and "Abell 2744".

## Star-cluster build results (step 2.6b)

The curated list now also holds **33 star clusters**: 18 open and 15 globular. As in step 2.6, the YAML holds names, kinds, and fame only; each cluster's position and distance come from the Hunt and Reffert (2023) catalogue, and a cluster's **lookback is its distance in light-years**.

### Which catalogue, and why not the planned one

- **Hunt and Reffert (2023)**, "Improving the open cluster census. II. An all-sky cluster catalogue with Gaia DR3", A&A 673, A114 (arXiv:2303.13424). On VizieR as `J/A+A/673/A114/clusters` (Table 3 of the paper), queried over TAP like the other VizieR tables (table name in double quotes). It lists 7,167 clusters, 134 of them cross-matched to known globular clusters; the table has 6,818 open (`Type` = o) and 121 globular (`Type` = g) rows. Columns used: `Name`, `Type`, `RA_ICRS`, `DE_ICRS`, `dist16`, `dist50`, `dist84` (the 16th, 50th, and 84th percentile of a maximum-likelihood distance, in parsecs), `Ndist` (stars used), `globalPlx`, and `AllNames`.
- **Names:** the catalogue's `Name` uses underscores ("Melotte_22" is the Pleiades, "Melotte_25" the Hyades, "NGC_2632" Praesepe). `AllNames` lists the other designations, but it has errors (two different globular clusters both carry "GCL_44"), so the build never copies those aliases; search aliases are the curated ones only.
- **Baumgardt and Vasiliev (2021), the planned source for globular clusters, was not used.** It is not on VizieR (no table under `J/MNRAS/505/5957`), and the author's page (people.smp.uq.edu.au/HolgerBaumgardt/globular, "4th (Mar. 2023) version") gives no download location for the distances and states no license. Decided with Ian: use Hunt and Reffert for all clusters now, and add Baumgardt later only if its terms are confirmed.
- **47 Tucanae is not in the catalogue** under its NGC number, so it is not in the list.

### The distance range

The catalogue's percentiles cover only the random error of the Gaia parallaxes (Omega Centauri is 5,263 to 5,285 pc), which would make a falsely narrow range. The build therefore adds a **systematic parallax error of 0.010 mas in quadrature**, on each side, in parallax space, then converts back to distance. Support for the size: a study of globular clusters with Gaia EDR3 (Vasiliev and Baumgardt 2021, arXiv:2102.09568) gives 0.01 mas as the lower limit for a cluster's average parallax, and Maiz Apellaniz et al. (2021, A&A 649, A13) find a minimum systematic uncertainty of 10.3 microarcseconds for individual stars or compact clusters. (Both figures were read from search summaries of those papers, not from the papers themselves.) A different analysis (the Gaia EDR3 summary paper) gives a larger small-scale scatter of about 26 microarcseconds, so 0.01 mas is on the optimistic side.

- At 100 pc the floor is about 0.1 percent of the distance; at 10 kpc it is about 10 percent.
- It matters: Baumgardt and Vasiliev's 5.43 kpc for Omega Centauri is outside the catalogue's own range (5.26 to 5.28 kpc) but inside the widened one (a test checks this).
- A cluster far enough that the floor leaves no far limit (about 100 kpc) is refused, loudly.
- Light-years per parsec are computed from the definitions of the metre, the astronomical unit, and the Julian year (3.26156), not typed in.

### Results

| Cluster | Lookback (best) | Half-range |
|---|---|---|
| Hyades | 154 years | 0.1% |
| Pleiades | 440 years | 0.1% |
| Praesepe | 598 years | 0.2% |
| Jewel Box (NGC 4755) | 6,453 years | 2.0% |
| Omega Centauri | 17,200 years | 5.3% |
| Messier 13 | 25,900 years | 8.0% |
| Messier 2 (farthest) | 41,700 years | 13.1% |

These match the usual values (Pleiades about 440 light-years, Hyades about 150, Praesepe about 600). The deep-sky list now spans 154 years to 13.79 billion years of lookback.

### Terms and open items

- VizieR says its data are free to use "in a scientific context" with the original authors and publication cited, and that commercial use "is subject to rules depending of the origin" (https://cds.unistra.fr/vizier-org/licences_vizier.html). Earthlight is free and non-commercial. The catalogue's own ReadMe (the place a copyright notice would be) could not be read: the CDS file server answered with a bot-protection "Access Denied" page. **Open item for Ian:** read https://cdsarc.cds.unistra.fr/ftp/J/A+A/673/A114/ReadMe in a browser and confirm there is no extra restriction.
- The build records `source.hunt_reffert_2023` in the `meta` table, like `source.simbad`.
- Test data: `pipeline/tests/data/hunt_reffert_snapshot.csv` holds the 33 real rows, fetched with the pipeline's own query.

## Nearby-galaxy build results (step 2.6c)

The curated list now also holds **36 nearby galaxies**: 16 from McConnachie (2012) and 20 from Cosmicflows-4. Both catalogues give a **distance modulus** (the difference between a galaxy's apparent and absolute magnitude) with an error. The build turns a modulus `m` into a distance of `10 ** (m / 5 + 1)` parsecs, takes the range from `m` minus its negative error to `m` plus its positive error, and uses the distance in light-years as the lookback. There is no extra floor: unlike Gaia parallaxes, these errors already include the calibration of the method.

### The two catalogues

- **McConnachie (2012)**, "The Observed Properties of Dwarf Galaxies in and around the Local Group", AJ 144, 4 (arXiv:1204.1562). VizieR `J/AJ/144/4/catalog`, 102 galaxies. Columns used: `Name`, `RAJ2000` and `DEJ2000` (**decimal degrees**, despite the description saying "hour"), `(m-M)` with `E_(m-M)` (positive error) and `e_(m-M)` (negative error); a few galaxies have different positive and negative errors, and a few have none (those are refused). Column names with brackets are double-quoted in the query. Picked: the Magellanic Clouds, Andromeda and its satellites M32, NGC 205 and NGC 185, Triangulum, IC 10, IC 1613, NGC 6822, and the Sagittarius, Fornax, Sculptor, Draco, Ursa Minor, and Carina dwarfs. "Canis Major" is in the table at 7 kpc but left out, because whether it is a galaxy at all is debated.
- **Cosmicflows-4**, Tully et al. 2023, "Cosmicflows-4", ApJ 944, 94 (arXiv:2209.11238). VizieR `J/ApJ/944/94/table2` (distances of individual galaxies). Columns used: `PGC` (Principal Galaxies Catalogue number), `DM` and `e_DM` (modulus and uncertainty, "all methodologies"), `RAJ2000` and `DEJ2000` (decimal degrees). The curated name is `PGC n`. SIMBAD stores the same number as a `LEDA` identifier, which is how each galaxy's number was found and checked (M87 is PGC 41361, M51 is PGC 47404). The galaxies in the list are all in the table; **M81 is not** (and neither are M77, NGC 891 or NGC 4631): it appears only as the head of a group in the `groups` table, so it is not in the list.
- Test data: `pipeline/tests/data/mcconnachie_snapshot.csv` (16 rows) and `cosmicflows4_snapshot.csv` (20 rows), fetched with the pipeline's own queries.

### Results

| Galaxy | Source | Lookback (best) | Half-range |
|---|---|---|---|
| Sagittarius Dwarf (nearest) | McConnachie | 85,800 years | 6.9% |
| Large Magellanic Cloud | McConnachie | 165,000 years | 4.1% |
| Small Magellanic Cloud | McConnachie | 209,000 years | 5.5% |
| Andromeda | McConnachie | 2.56 million years | 3.2% |
| Triangulum | McConnachie | 2.64 million years | 2.8% |
| Centaurus A | Cosmicflows-4 | 11.9 million years | 1.8% |
| Whirlpool (M51) | Cosmicflows-4 | 27.2 million years | 3.6% |
| Messier 87 | Cosmicflows-4 | 55.0 million years | 1.8% |
| NGC 1365 (farthest) | Cosmicflows-4 | 61.1 million years | 2.1% |

These match the usual values (LMC about 163,000 light-years, Andromeda about 2.5 million). Draco and Ursa Minor have the same best lookback because the catalogue gives both the same distance modulus. With the clusters, the deep-sky list now spans 154 years to 13.79 billion years.

### Terms and open items

- Both catalogues come through VizieR, under the same terms as in step 2.6b: free to use in a scientific context with the original authors cited, commercial use depending on each catalogue. Earthlight is free and non-commercial. As for Hunt and Reffert, the CDS ReadMe files (where a copyright notice would be) could not be read because of bot protection. **Open item for Ian:** open https://cdsarc.cds.unistra.fr/ftp/J/AJ/144/4/ReadMe and https://cdsarc.cds.unistra.fr/ftp/J/ApJ/944/94/ReadMe in a browser and confirm there is no extra restriction.
- The build records `source.mcconnachie_2012` and `source.cosmicflows_4` in the `meta` table.
- Citations: McConnachie, A. W. 2012, AJ 144, 4 (arXiv:1204.1562); Tully, R. B., Kourkchi, E., Courtois, H. M., et al. 2023, ApJ 944, 94 (arXiv:2209.11238).

## Population build results (step 2.14)

The `population` table holds **261 world population estimates**, from 4.5 million people in 10000 BCE to 8.09 billion in 2023. They come from the Our World in Data "Population" chart (https://ourworldindata.org/grapher/population), which stitches three sources together.

### The real file

- **Download:** `https://ourworldindata.org/grapher/population.csv?csvType=full&useColumnShortNames=false`, 1.6 MB, 58,824 rows for about 250 countries and regions. Columns: `Entity`, `Code`, `Year`, `Population`. A `country=~OWID_WRL` filter added to the address was **ignored** (the file still came back whole; the page documents no such filter), so the whole file is downloaded and the build keeps the rows with code `OWID_WRL` (entity "World"). Metadata: `.../population.metadata.json`.
- **The world series** has 261 rows, one per year label, with no repeats and no gaps in order: every 1000 years from 10000 BCE to 1000 BCE (labels `-10000` to `-1000`), every 100 years from 0 to 1600, every 10 years from 1700 to 1790, and every year from 1800 to 2023. It ends at 2023: the series has **no projections**, although the chart's text says the UN data "include 2100 projections" (those are not in this file). The build still refuses any year after the current year, so a changed file cannot slip projections in.
- **Sources (from OWID's metadata):** HYDE 3.3 (PBL Netherlands Environmental Assessment Agency, 2023) for 10000 BCE to 1799; Gapminder "Population" v7 (2022) for 1800 to 1949; United Nations World Population Prospects 2024 for 1950 to 2023. OWID warns that "breaks in the data may occur at the boundaries between sources". Before 1800 the world value is HYDE's; from 1800 to 1950 it is the sum of the countries; after 1950 it is the UN's.
- **Licenses:** HYDE 3.3, CC BY 4.0 (https://doi.org/10.24416/UU01-AEZZIT); Gapminder, CC BY 4.0; UN WPP, CC BY 3.0 IGO. OWID's own processing is CC BY 4.0, and it says third-party data keep the terms of their original providers. All are compatible with the bundled database's CC BY-NC 3.0 IGO license, with credit. Suggested credit: "HYDE (2023); Gapminder (2022); UN WPP (2024), with major processing by Our World in Data".

### Rules chosen in this step

- **BCE labels are shifted to astronomical years.** OWID writes 10000 BCE as `-10000`. Earthlight writes N BCE as 1 - N (see the history notes), so the build stores `-9999`; the label `0` stays 0 and positive labels are unchanged. The estimates are far too coarse for one year to matter, but every year in the database now follows one rule. As a result the step from the label `-1000` to `0` is stored as 999 years.
- **Only the world is stored**, as whole numbers of people. The table has one `source` URL per row, the chart address.
- **The build fails loudly and lists every problem:** a missing column, no world rows, a year or population that is not a whole number, a population of zero or below, a repeated year, a year after this year, or rows out of order. A bad file stops the build before the database is touched.
- **The database records** `source.population` in `meta`: the name, the chart URL, the date retrieved, and the three combined sources with their versions and licenses.
- **Not done on purpose:** no interpolation between points. Whoever reads the table (Phase 3) decides how to estimate a year between two rows.

### Results

| Year | People |
|---|---|
| 10000 BCE | 4.5 million |
| 1000 BCE | 111 million |
| 0 | 232 million |
| 1000 CE | 323 million |
| 1800 | 983 million |
| 1950 | 2.49 billion |
| 2000 | 6.17 billion |
| 2023 | 8.09 billion |

The series is not rising every century: 1200 CE (445 million) is above 1400 CE (442 million), the time of the Black Death. Test data: `pipeline/tests/data/owid_population_snapshot.csv` holds all 261 real world rows plus a few rows each for Africa, Asia, Europe, and the United Kingdom, so tests prove that only the world is read.

## Full build results (step 2.15)

`earthlight-build all` recreates the database, runs every source in order, then records the license (`meta` keys `data_license` and `data_license_url`), rebuilds the search index, runs SQLite's integrity and foreign-key checks, and compacts the file. The result is committed at `packages/earthlight/src/earthlight/data/earthlight.db`.

| Table | Rows |
|---|---|
| Stars | 40,346 |
| Exoplanets | 6,356 |
| Deep-sky objects | 121 |
| History | 105 events, 33 periods, 22 landmarks |
| Population | 261 |
| Search entries | 7,808 |

The file is 19.9 MB (18.9 MiB), limit 20 MiB, checked by a test. Every century of lookback from 0 to 5,000 years, and every factor of ten from 10 years to 10 billion years, has at least one place; every century since 3000 BCE has a history entry except nine (listed in `KNOWN_HISTORY_GAPS` in the test, for Ian to decide whether to fill). The rules SQLite cannot express (plain-scalar `facts`, `host_id` pointing at a star) are checked in `packages/earthlight/tests/test_bundled_database.py`. A rebuild changes the file whenever a source updates, so the numbers above are for the build made on 2026-10-22.

## Corrections made in the phase 2 review (step 2.15)

- **Planets that disagree with their star.** The archive's system distance sometimes comes from an older catalogue: GJ 411 b and c were at 18.5 light-years while their host (Lalande 21185) is at 8.3 light-years in Gaia. When a planet is linked to a host whose distance comes from Gaia, and the planet's range does not overlap the host's range and the best values differ by more than 5%, the planet now takes the host's range (`distance_source` is `host_star`). 19 planets changed. Tiny gaps between very precise ranges (Proxima Centauri's planets) are left alone.
- **Alpha Centauri.** The Hipparcos new-reduction parallax for the pair (796.92 +- 25.90 mas for Alpha Cen B) is poor because the stars orbit each other, and put Toliman at 4.09 light-years, nearer than Proxima. A short override list (`PARALLAX_OVERRIDES` in `stars.py`) gives both stars the parallax of the pair from the orbit solution, 747.17 +- 0.61 mas (1.3384 +- 0.0011 parsecs), from Kervella et al. 2016, A&A 594, A107, as quoted in Kervella, Thevenin and Lovis 2017, A&A 598, L7. Both now sit at 4.37 light-years (`distance_source` is `literature`). Any future override needs a cited published value.
- **Deep-sky positions from the cited papers.** An inline redshift can now carry `ra_deg` and `dec_deg` copied from the same paper. Done for J0313-1806 (Wang et al., 03:13:43.84 -18:06:36.4, which matches SIMBAD), JADES-GS-z14-0 (Carniani et al., 3:32:19.905 -27:51:20.27) and MoM-z14 (Naidu et al., 150.0933255 +2.2731627, which matches SIMBAD). The papers for GN-z11 (Bunker et al.), GHZ2 (Castellano et al.) and JADES-GS-z13-1-LA (Witstok et al.) do not state a position in the text read, and SIMBAD has none under those names, so they and the CMB still have no position.

## History data (steps 2.7 to 2.13)

History is hand-curated, so the work is in the rules, not a download. `pipeline/curated/history/` holds one YAML file per era, each with any of `events`, `periods`, and `landmarks`. Entries are read straight into `HistoryEvent`, `HistoryPeriod`, and `Landmark` from `earthlight.models`, in strict mode (so `year: "1492"` or `importance: true` is an error).

### Rules chosen in step 2.7

- **Categories are a fixed list** in `history.py` (`CATEGORIES`): cosmic, geological, life, human_origins, civilization, science, war_politics, culture, technology. The model accepts any text; the loader enforces the list so the files stay consistent.
- **Ids are unique across events, periods, and landmarks**, and names are unique within each type. A problem that involves several entries (a repeated id, a bad category) names the file each entry came from.
- **A key may appear only once in a YAML mapping.** Plain PyYAML keeps the last of two `year:` lines without a word; our loader (`curated_yaml.py`, shared with the deep-sky list) reports it as a problem instead.
- **Every problem in every file is reported at once**, and a bad file stops the build before the database is touched. Files that hold no entries at all (every list empty) are reported as "no history entries", also before the database is touched.
- **A period that has not ended** (the Cenozoic, the Holocene, the Space Age) says `ongoing: true` in the YAML and has no `end`. The model, the database (`ongoing = 1`, `end_year` empty) and the search text ("... to present") all carry the flag, so nothing stores a made-up end year.
- **Years in the files:** N BCE is written as -(N-1) (so 2560 BCE is -2559, and 1 BCE is 0). A date given as "N years ago" is 2026 minus N; BP dates are 1950 minus N. At deep-time scale (millions of years) plain -N is fine.
- **Write years as plain integers** (`-4540000000`) or with a signed exponent (`-4.54e+9`). PyYAML follows YAML 1.1, which reads `-4.54e9` (no `+` or `-` after the `e`) as text, and strict mode then refuses it.
- **Search descriptions** read like "Event, 1492 CE" or "Period, 539 million years ago to 485 million years ago". "N years ago" counts back from a fixed year (`DESCRIPTION_REFERENCE_YEAR`) so a rebuild gives identical text. Recent dates are always calendar years ("2025 CE"), never "18 days ago", because the text is frozen into the database.
- **The build report** gives the latest year as "present" when a period is ongoing, rather than printing the 2100 stand-in.

### How dates are sourced

- **Deep time (2.8, 2.9):** eon, era, and period boundary ages come from a single source, the International Chronostratigraphic Chart (2023 and later editions) at stratigraphy.org/chart, and were not cross-checked against a second one. The chart is copyrighted by the ICS; we cite dates (facts) and write our own summaries. CSIRO republished the 2017 to 2019 editions as CC BY 4.0 RDF.
- **Everything else:** each date was read from a cited page (mostly Wikipedia, which itself cites the primary sources). Where possible a second independent page (Britannica, NASA, the Smithsonian, or a code reviewer's own knowledge) was used to check it, but not every entry has a second check; the unchecked ones are listed in the maintainer's review notes. An entry whose date could not be found is dropped rather than guessed, and a date that is a best estimate or a middle of a range gets a `year_uncertainty`.
- **Not used:** Seshat (CC BY-NC-SA, codes societies, not events) and bulk event dumps with unclear licenses.

## Licenses and attribution

Verified from the sources' own pages on 2026-10-20. Quotes are exact. This is a project record, not legal advice.

| Source | Terms found | Credit and citation to include |
|---|---|---|
| **Gaia DR3** (ESA) | "Gaia data are distributed under the CC BY-NC 3.0 IGO license." (https://www.cosmos.esa.int/web/gaia-users/license). ESA's terms: data are "open and free to use ... subject to proper acknowledgment", and "Prior to any commercial use ... including any use or application that directly or indirectly generates a financial gain, a detailed request for authorisation/licence shall be made ... to data.licences@esa.int" (https://www.cosmos.esa.int/web/esdc/terms-and-conditions). | Credit line: "Credit: ESA, Gaia DPAC". Cite Gaia Collaboration, Vallenari et al. 2023, A&A 674, A1, DOI 10.1051/0004-6361/202243940. Gaia's per-release acknowledgement text is linked from https://www.cosmos.esa.int/web/gaia-users/credits. |
| **Bailer-Jones distances** | CC BY 4.0, as stated by the GAVO data center (see the Bailer-Jones section above). | Credit separately: cite Bailer-Jones et al. 2021, AJ 161, 147, DOI 10.3847/1538-3881/abd806. |
| **Hipparcos** (ESA), via VizieR | ESA lists Hipparcos with the same archive terms (CC BY-NC 3.0 IGO). VizieR says its data are free "in a scientific context" and that "commercial usage of the data is subject to rules depending of the origin". Treated as non-commercial. | ESA credit line: "Credit: ESA". Cite van Leeuwen 2007, A&A 474, 653, DOI 10.1051/0004-6361:20078357. Acknowledge VizieR: DOI 10.26093/cds/vizier. |
| **NASA Exoplanet Archive** | No license or terms statement on its acknowledgement page, only a request for credit. | "This research has made use of the NASA Exoplanet Archive, which is operated by the California Institute of Technology, under contract with the National Aeronautics and Space Administration under the Exoplanet Exploration Program." The page also asks users to cite Christiansen et al. (2025) as the reference paper; the full citation (confirmed in step 2.16 through the arXiv and IPAC listings; the DOI came from the DOAJ record, so check it on the publisher page before citing formally): Christiansen et al. 2025, "The NASA Exoplanet Archive and Exoplanet Follow-up Observing Program: Data, Tools, and Usage", Planetary Science Journal 6, 186, DOI 10.3847/PSJ/ade3c2, arXiv:2506.03299. |
| **IAU Catalog of Star Names** | "All IAU-produced products (Images, Videos, Texts) are released under Creative Commons Attribution (i.e. free to use in all perpetuity, world-wide, as long as the source is mentioned)." | Cite the IAU WGSN and https://www.iau.org/public/themes/naming_stars/. |
| **NASA and JPL material** (planet elements, Horizons values, Voyager facts) | NASA says its content "generally are not subject to copyright in the United States", may be used for educational or informational purposes, and "NASA should be acknowledged as the source". It must not "implicitly convey NASA's endorsement of commercial goods or services" (https://www.nasa.gov/nasa-brand-center/images-and-media/). The JPL Solar System Dynamics site states no data terms of its own. | "NASA/JPL" for the orbital elements and Horizons values. Not an endorsement by NASA. |
| **SIMBAD** (CDS), deep-sky positions and redshifts | No license statement found; CDS asks for an acknowledgment. Used for a few hundred values under the same non-commercial, credited use as the other CDS services. | "This research has made use of the SIMBAD database, CDS, Strasbourg Astronomical Observatory, France." Cite Wenger et al. 2000, A&AS 143, 9, "The SIMBAD astronomical database" (wording from https://cds.unistra.fr/help/acknowledgement/). |
| **Hunt and Reffert (2023)** via VizieR, star-cluster positions and distances | VizieR: free to use in a scientific context with the original authors cited; commercial use depends on the catalogue. Non-commercial use here. The catalogue's ReadMe could not be read (bot protection), so confirm it. | Hunt, E. L. and Reffert, S. 2023, A&A 673, A114, "Improving the open cluster census. II. An all-sky cluster catalogue with Gaia DR3". "This research has made use of the VizieR catalogue access tool, CDS, Strasbourg, France (DOI : 10.26093/cds/vizier)." Original VizieR description: A&AS 143, 23 (2000). |
| **McConnachie (2012)** and **Cosmicflows-4** (Tully et al. 2023) via VizieR, nearby-galaxy positions and distance moduli | Same VizieR terms as above (free for scientific use with the authors cited; commercial use depends on the catalogue). Non-commercial use here. The catalogues' ReadMe files could not be read (bot protection), so confirm them. | McConnachie, A. W. 2012, AJ 144, 4, "The Observed Properties of Dwarf Galaxies in and around the Local Group". Tully, R. B., Kourkchi, E., Courtois, H. M., et al. 2023, ApJ 944, 94, "Cosmicflows-4". Same VizieR acknowledgement as above. |
| **Our World in Data**, world population (combining HYDE 3.3, Gapminder v7, and UN WPP 2024) | OWID's own processing is CC BY 4.0. HYDE 3.3: CC BY 4.0. Gapminder: CC BY 4.0. UN World Population Prospects: CC BY 3.0 IGO. Credit is required. | "HYDE (2023); Gapminder (2022); UN WPP (2024), with major processing by Our World in Data", "Population, HYDE, Gapminder, UN, Long-run data" [dataset]. Original data: PBL Netherlands Environmental Assessment Agency, "History Database of the Global Environment 3.3"; Gapminder, "Population v7"; United Nations, "World Population Prospects". |
| **Papers cited for inline redshifts** (step 2.6) | Published scientific results; only a number is taken from each, and each is cited by its arXiv URL in the curated file. | Bunker et al. (GN-z11), Castellano et al. (GHZ2), Witstok et al. (JADES-GS-z13-1-LA), Carniani et al. (JADES-GS-z14-0), Naidu et al. (MoM-z14), Wang et al. (J0313-1806), and Planck Collaboration 2018 VI (cosmology and the CMB). |
| **Curated YAML** (deep-sky objects, history; steps 2.6 to 2.13) | Our own work. Summaries are written in our own words, and every entry cites a source URL. Wikipedia is linked, never copied. | Covered by the repository's MIT license. |

**What the non-commercial terms mean for us.** Gaia and Hipparcos are the only source of star distances, so the built database is derived from ESA data under CC BY-NC 3.0 IGO. A combined file follows its most restrictive source, so the **bundled database is CC BY-NC 3.0 IGO**. The code is separate and stays MIT. The CC BY-NC 3.0 IGO legal code (https://creativecommons.org/licenses/by-nc/3.0/igo/legalcode) forbids exercising the licensed rights "in any manner that is primarily intended for or directed toward commercial advantage or private monetary compensation". The project owner's reading is that a free, ad-free, educational portfolio project is not that. The site must have no ads, no revenue, and no paid features. The share-alike license on HYG cannot be combined with non-commercial terms in one database, which is why HYG is not used.

**Not yet reviewed (later steps):** Our World in Data population estimates (step 2.14), constellation-line data for the sky map (step 8.5), and Wikipedia (we store article titles and links only, and never copy text).

## Decisions made in step 2.2

Approved by the project owner on 2026-10-20.

1. **Licensing:** the code stays MIT. The bundled database is licensed **CC BY-NC 3.0 IGO**, stated in a `LICENSE-DATA` file and in a "Data licenses" section of the README, with the full credits. The credit lines are "ESA, Gaia DPAC" for Gaia and "ESA" for Hipparcos. The project owner researched the terms and decided that a free, ad-free, educational portfolio project is non-commercial. Writing to data.licences@esa.int is optional and does not block any work.
2. **Star names:** the IAU Catalog of Star Names, not HYG. Constellations from astropy. Stars without an IAU name use a catalog designation such as "HIP 27989". HYG is not used because of its share-alike license; it is a maintained project (now at Codeberg) and is not described as abandoned.
3. **Star distances:** two tiers. Gaia with Bailer-Jones 16th to 84th percentile ranges where a star is matched, otherwise the Hipparcos new reduction with ranges from `1000 / (Plx +/- e_Plx)`. Each star records which source its distance came from (in `facts`).

### Consequences for later steps

- **2.3 schema:** `meta` records the source versions and the data license. A star's `facts` includes `distance_source` (`gaia` or `hipparcos`).
- **2.4 stars:** the star universe is the Hipparcos catalogue (about 118,000 stars, which also fits the size budget), upgraded with Gaia and Bailer-Jones distances where matched. V magnitude from `I/239/hip_main`, names from the IAU list through the Hipparcos number, constellation from astropy. Right ascension and declination in degrees (Hipparcos and Gaia agree on degrees; HYG used hours).
- **2.5 exoplanets:** the 128-planet distance gap above, linking by `gaia_dr3_id` and `hip_name`.
- **2.15 and 2.16:** `LICENSE-DATA` and the README "Data licenses" section already exist (added in step 2.2). Step 2.16 keeps them in line with the sources that were actually built, adds the Exoplanet Archive reference paper citation, and the build validates that the database's `meta` table records the data license.
- **Phase 5 packaging:** the wheel contains the database, so its license metadata must name both licenses (MIT for the code, CC BY-NC 3.0 IGO for the data), and the wheel must include `LICENSE-DATA`.
