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

## Licenses and attribution

Verified from the sources' own pages on 2026-10-20. Quotes are exact. This is a project record, not legal advice.

| Source | Terms found | Credit and citation to include |
|---|---|---|
| **Gaia DR3** (ESA) | "Gaia data are distributed under the CC BY-NC 3.0 IGO license." (https://www.cosmos.esa.int/web/gaia-users/license). ESA's terms: data are "open and free to use ... subject to proper acknowledgment", and "Prior to any commercial use ... including any use or application that directly or indirectly generates a financial gain, a detailed request for authorisation/licence shall be made ... to data.licences@esa.int" (https://www.cosmos.esa.int/web/esdc/terms-and-conditions). | Credit line: "Credit: ESA, Gaia DPAC". Cite Gaia Collaboration, Vallenari et al. 2023, A&A 674, A1, DOI 10.1051/0004-6361/202243940. Gaia's per-release acknowledgement text is linked from https://www.cosmos.esa.int/web/gaia-users/credits. |
| **Bailer-Jones distances** | CC BY 4.0, as stated by the GAVO data center (see the Bailer-Jones section above). | Credit separately: cite Bailer-Jones et al. 2021, AJ 161, 147, DOI 10.3847/1538-3881/abd806. |
| **Hipparcos** (ESA), via VizieR | ESA lists Hipparcos with the same archive terms (CC BY-NC 3.0 IGO). VizieR says its data are free "in a scientific context" and that "commercial usage of the data is subject to rules depending of the origin". Treated as non-commercial. | ESA credit line: "Credit: ESA". Cite van Leeuwen 2007, A&A 474, 653, DOI 10.1051/0004-6361:20078357. Acknowledge VizieR: DOI 10.26093/cds/vizier. |
| **NASA Exoplanet Archive** | No license or terms statement on its acknowledgement page, only a request for credit. | "This research has made use of the NASA Exoplanet Archive, which is operated by the California Institute of Technology, under contract with the National Aeronautics and Space Administration under the Exoplanet Exploration Program." The page also asks users to cite Christiansen et al. (2025) as the reference paper; the full citation is to be confirmed in step 2.16. |
| **IAU Catalog of Star Names** | "All IAU-produced products (Images, Videos, Texts) are released under Creative Commons Attribution (i.e. free to use in all perpetuity, world-wide, as long as the source is mentioned)." | Cite the IAU WGSN and https://www.iau.org/public/themes/naming_stars/. |
| **NASA and JPL material** (planet elements, Horizons values, Voyager facts) | NASA says its content "generally are not subject to copyright in the United States", may be used for educational or informational purposes, and "NASA should be acknowledged as the source". It must not "implicitly convey NASA's endorsement of commercial goods or services" (https://www.nasa.gov/nasa-brand-center/images-and-media/). The JPL Solar System Dynamics site states no data terms of its own. | "NASA/JPL" for the orbital elements and Horizons values. Not an endorsement by NASA. |
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
