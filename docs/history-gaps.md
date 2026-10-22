# History gaps to research

Nine centuries since 3000 BCE have no event, no period that ended in them, and no landmark whose construction started in them. The test `test_the_centuries_without_a_history_entry_are_the_known_ones` in `packages/earthlight/tests/test_bundled_database.py` lists them in `KNOWN_HISTORY_GAPS`. When you add an entry for one, remove that century's start year from the list.

| Century (BCE) | Start year in the list | Notes |
|---|---|---|
| 3000 to 2901 | -2999 | Early Bronze Age; first dynasties of Egypt are nearby |
| 2900 to 2801 | -2899 | |
| 2800 to 2701 | -2799 | |
| 2100 to 2001 | -2099 | |
| 2000 to 1901 | -1999 | |
| 1900 to 1801 | -1899 | |
| 1700 to 1601 | -1699 | |
| 1000 to 901 | -999 | |
| 900 to 801 | -899 | |

You do not need an entry for each century. One well-known entry can cover two or three if its date falls in them. Ideas to check, not facts to copy: early writing and cities, the Indus and Yellow River cultures, the Bronze Age collapse neighbourhood, the first alphabets, early Olympic or Phoenician trade dates. Choose only dates that sources agree on.

## Rules (from CLAUDE.md)

- Only well-known, widely agreed dates. Every entry needs a `source` URL.
- The summary is in our own words (2 to 3 sentences). Never copy Wikipedia or another source.
- Years are astronomical decimal years. **N BCE is written as 1 - N**: 2560 BCE is `-2559`, 1000 BCE is `-999`, 1 BCE is `0`. A CE year is written as is.
- If the date is only known to within some years, give `year_uncertainty` (plus or minus, in years). Do not add any other uncertainty field.

## Format

Put each entry in the file for its era (`pipeline/curated/history/04_ancient_world.yaml` for these centuries), under `events:`, `periods:`, or `landmarks:`.

Categories: `cosmic`, `geological`, `life`, `human_origins`, `civilization`, `science`, `war_politics`, `culture`, `technology`. Importance is 1 (known to specialists) to 5 (a household name).

```yaml
# An event: something that happened at a point in time.
events:
  - id: short-lowercase-slug          # unique, letters, digits, hyphens
    name: Name shown to people
    category: civilization
    region: Where, in a few words     # "Mesopotamia", "Global", "Egypt"
    summary: >-
      Two or three sentences in your own words.
    importance: 3
    wikipedia: Exact Wikipedia article title   # optional
    source: https://example.org/page
    year: -2559
    year_uncertainty: 50              # optional, plus or minus years

# A period: an age, era, or dynasty with a start and an end.
periods:
  - id: some-dynasty
    name: Some Dynasty
    category: war_politics
    region: Egypt
    summary: >-
      Two or three sentences in your own words.
    importance: 3
    source: https://example.org/page
    start: -2699
    end: -2181                        # leave out and add `ongoing: true` only if it has not ended

# A landmark: a structure, with when it was built and where it is.
landmarks:
  - id: some-structure
    name: Some Structure
    category: civilization
    region: Country or area
    summary: >-
      Two or three sentences in your own words.
    importance: 3
    source: https://example.org/page
    built_start: -2559
    built_end: -2539
    destroyed: -1000                  # optional; leave out if it still stands
    lat: 29.9792                      # degrees north is positive
    lon: 31.1342                      # degrees east is positive
```

A landmark counts toward a century only if its `built_start` falls in it. A period that has ended counts for every century it overlaps; an ongoing period, or a landmark that merely still stands, counts for none.

After adding entries, run `uv run pytest pipeline/tests/test_real_history.py` and rebuild with `uv run earthlight-build --database packages/earthlight/src/earthlight/data/earthlight.db all`.
