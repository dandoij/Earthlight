-- Earthlight database schema, version 1 (see SCHEMA_VERSION in schema.py).
--
-- The pipeline builds the database once; the engine opens it read-only. Conventions:
--   * Years are decimal astronomical years (1 BCE = 0). Lookbacks and uncertainties are in years.
--   * Ids are lowercase slugs: letters and digits joined by single hyphens, like proxima-cen-b.
--   * CHECK constraints repeat the rules of the Pydantic models in models.py, so a row that
--     the database accepts is a row the models accept. Tests keep the two in step.
--   * SQLite cannot put a subquery in a CHECK, so two rules are checked by the build instead:
--     "facts" must contain only scalar values, and "host_id" must point at a star.
--   * Foreign keys only work with PRAGMA foreign_keys = ON, which the build turns on.
--   * Needs SQLite 3.38 or newer (STRICT tables, built-in JSON, FTS5 with the trigram tokenizer).
--
-- "Slug", "name", "text", and "URL" below are written out in each table because SQLite has no
-- domain types:
--   slug: length 1 to 100, only a-z 0-9 and '-', never starting or ending with '-', no '--'
--   name: length 1 to 200, no leading or trailing whitespace
--   text: length 1 to 1000
--   URL:  starts with http:// or https://, no whitespace, at most 500 characters

-- Facts about this build: schema_version, build_date, data_license, and the version or
-- retrieval date of every source (see docs/data-sources.md).
CREATE TABLE meta (
    key   TEXT PRIMARY KEY CHECK (length(key) BETWEEN 1 AND 100),
    value TEXT NOT NULL
) STRICT;

-- Every place you can stand: planets, stars, exoplanets, galaxies, and so on.
CREATE TABLE vantage_points (
    id            TEXT PRIMARY KEY CHECK (
        length(id) BETWEEN 1 AND 100
        AND id NOT GLOB '*[^a-z0-9-]*' AND id NOT GLOB '-*' AND id NOT GLOB '*-' AND id NOT GLOB '*--*'
    ),
    name          TEXT NOT NULL CHECK (
        length(name) BETWEEN 1 AND 200 AND name = trim(name, ' ' || char(9, 10, 13))
    ),
    kind          TEXT NOT NULL CHECK (kind IN (
        'planet', 'moon', 'spacecraft', 'zone', 'star', 'exoplanet',
        'star_cluster', 'galaxy', 'galaxy_cluster', 'quasar', 'cosmic_background'
    )),
    -- Years of lookback. For Gaia stars min and max are the 16th and 84th percentiles of the
    -- distance (about a 68 percent interval); see docs/data-sources.md.
    lookback_min  REAL NOT NULL,
    lookback_best REAL NOT NULL,
    lookback_max  REAL NOT NULL,
    magnitude     REAL CHECK (magnitude IS NULL OR abs(magnitude) < 1e6),
    constellation TEXT CHECK (
        constellation IS NULL
        OR (length(constellation) BETWEEN 1 AND 200
            AND constellation = trim(constellation, ' ' || char(9, 10, 13)))
    ),
    ra_deg        REAL CHECK (ra_deg IS NULL OR (ra_deg >= 0 AND ra_deg < 360)),
    dec_deg       REAL CHECK (dec_deg IS NULL OR (dec_deg >= -90 AND dec_deg <= 90)),
    fame          INTEGER NOT NULL DEFAULT 0 CHECK (fame BETWEEN 0 AND 5),
    host_id       TEXT REFERENCES vantage_points (id),
    wikipedia     TEXT CHECK (
        wikipedia IS NULL
        OR (length(wikipedia) BETWEEN 1 AND 200 AND wikipedia = trim(wikipedia, ' ' || char(9, 10, 13)))
    ),
    facts         TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(facts) AND json_type(facts) = 'object'),
    CHECK (lookback_min >= 0 AND lookback_min <= lookback_best
           AND lookback_best <= lookback_max AND lookback_max < 1e15),
    CHECK ((ra_deg IS NULL) = (dec_deg IS NULL)),
    CHECK (host_id IS NULL OR (kind = 'exoplanet' AND host_id <> id)),
    UNIQUE (id, kind)
) STRICT;

-- Moment to place: which ranges contain a lookback.
CREATE INDEX idx_vantage_points_lookback ON vantage_points (lookback_min, lookback_max);
CREATE INDEX idx_vantage_points_kind_lookback ON vantage_points (kind, lookback_min, lookback_max);
-- The planets of a star.
CREATE INDEX idx_vantage_points_host ON vantage_points (host_id) WHERE host_id IS NOT NULL;
-- "Famous" and "visible tonight" rankings.
CREATE INDEX idx_vantage_points_fame ON vantage_points (fame DESC) WHERE fame > 0;
CREATE INDEX idx_vantage_points_magnitude ON vantage_points (magnitude) WHERE magnitude IS NOT NULL;

-- Extra, typed details for vantage points of kind 'exoplanet'. The composite foreign key
-- guarantees the row it points at really is an exoplanet.
CREATE TABLE exoplanets (
    vantage_id          TEXT PRIMARY KEY,
    kind                TEXT NOT NULL DEFAULT 'exoplanet' CHECK (kind = 'exoplanet'),
    nasa_name           TEXT NOT NULL CHECK (length(nasa_name) BETWEEN 1 AND 200),
    host_name           TEXT NOT NULL CHECK (length(host_name) BETWEEN 1 AND 200),
    discovery_year      INTEGER CHECK (discovery_year IS NULL OR discovery_year BETWEEN 1900 AND 2200),
    discovery_method    TEXT CHECK (discovery_method IS NULL OR length(discovery_method) BETWEEN 1 AND 200),
    radius_earth        REAL CHECK (radius_earth IS NULL OR (radius_earth > 0 AND radius_earth < 1e6)),
    mass_earth          REAL CHECK (mass_earth IS NULL OR (mass_earth > 0 AND mass_earth < 1e9)),
    orbital_period_days REAL CHECK (orbital_period_days IS NULL OR (orbital_period_days > 0 AND orbital_period_days < 1e12)),
    controversial       INTEGER NOT NULL DEFAULT 0 CHECK (controversial IN (0, 1)),
    FOREIGN KEY (vantage_id, kind) REFERENCES vantage_points (id, kind) ON DELETE CASCADE
) STRICT;

-- Something that happened at a point in time (HistoryEvent in models.py).
CREATE TABLE events (
    id               TEXT PRIMARY KEY CHECK (
        length(id) BETWEEN 1 AND 100
        AND id NOT GLOB '*[^a-z0-9-]*' AND id NOT GLOB '-*' AND id NOT GLOB '*-' AND id NOT GLOB '*--*'
    ),
    name             TEXT NOT NULL CHECK (
        length(name) BETWEEN 1 AND 200 AND name = trim(name, ' ' || char(9, 10, 13))
    ),
    category         TEXT NOT NULL CHECK (
        length(category) BETWEEN 1 AND 200 AND category = trim(category, ' ' || char(9, 10, 13))
    ),
    region           TEXT NOT NULL CHECK (
        length(region) BETWEEN 1 AND 200 AND region = trim(region, ' ' || char(9, 10, 13))
    ),
    summary          TEXT NOT NULL CHECK (
        length(summary) BETWEEN 1 AND 1000 AND summary = trim(summary, ' ' || char(9, 10, 13))
    ),
    importance       INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
    wikipedia        TEXT CHECK (
        wikipedia IS NULL
        OR (length(wikipedia) BETWEEN 1 AND 200 AND wikipedia = trim(wikipedia, ' ' || char(9, 10, 13)))
    ),
    source           TEXT NOT NULL CHECK (
        length(source) <= 500
        AND (source GLOB 'http://?*' OR source GLOB 'https://?*')
        AND source NOT GLOB ('*[ ' || char(9) || char(10) || char(13) || ']*')
    ),
    year             REAL NOT NULL CHECK (abs(year) < 1e15),
    year_uncertainty REAL NOT NULL DEFAULT 0 CHECK (year_uncertainty >= 0 AND year_uncertainty < 1e15)
) STRICT;

CREATE INDEX idx_events_year ON events (year);

-- An age, era, or dynasty that lasted a span of time (HistoryPeriod). "start" and "end" are
-- SQL keywords or close to it, so the columns are start_year and end_year. An ongoing period has
-- ongoing = 1 and no end_year; consumers treat its end as "now".
CREATE TABLE periods (
    id          TEXT PRIMARY KEY CHECK (
        length(id) BETWEEN 1 AND 100
        AND id NOT GLOB '*[^a-z0-9-]*' AND id NOT GLOB '-*' AND id NOT GLOB '*-' AND id NOT GLOB '*--*'
    ),
    name        TEXT NOT NULL CHECK (
        length(name) BETWEEN 1 AND 200 AND name = trim(name, ' ' || char(9, 10, 13))
    ),
    category    TEXT NOT NULL CHECK (
        length(category) BETWEEN 1 AND 200 AND category = trim(category, ' ' || char(9, 10, 13))
    ),
    region      TEXT NOT NULL CHECK (
        length(region) BETWEEN 1 AND 200 AND region = trim(region, ' ' || char(9, 10, 13))
    ),
    summary     TEXT NOT NULL CHECK (
        length(summary) BETWEEN 1 AND 1000 AND summary = trim(summary, ' ' || char(9, 10, 13))
    ),
    importance  INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
    wikipedia   TEXT CHECK (
        wikipedia IS NULL
        OR (length(wikipedia) BETWEEN 1 AND 200 AND wikipedia = trim(wikipedia, ' ' || char(9, 10, 13)))
    ),
    source      TEXT NOT NULL CHECK (
        length(source) <= 500
        AND (source GLOB 'http://?*' OR source GLOB 'https://?*')
        AND source NOT GLOB ('*[ ' || char(9) || char(10) || char(13) || ']*')
    ),
    start_year  REAL NOT NULL CHECK (abs(start_year) < 1e15),
    -- NULL exactly when the period is ongoing (it has not ended yet, like the Holocene).
    end_year    REAL CHECK (end_year IS NULL OR abs(end_year) < 1e15),
    ongoing     INTEGER NOT NULL DEFAULT 0 CHECK (ongoing IN (0, 1)),
    CHECK ((ongoing = 1) = (end_year IS NULL)),
    CHECK (end_year IS NULL OR start_year <= end_year)
) STRICT;

CREATE INDEX idx_periods_span ON periods (start_year, end_year);

-- A structure or place with a building span and maybe a destruction date (Landmark).
CREATE TABLE landmarks (
    id          TEXT PRIMARY KEY CHECK (
        length(id) BETWEEN 1 AND 100
        AND id NOT GLOB '*[^a-z0-9-]*' AND id NOT GLOB '-*' AND id NOT GLOB '*-' AND id NOT GLOB '*--*'
    ),
    name        TEXT NOT NULL CHECK (
        length(name) BETWEEN 1 AND 200 AND name = trim(name, ' ' || char(9, 10, 13))
    ),
    category    TEXT NOT NULL CHECK (
        length(category) BETWEEN 1 AND 200 AND category = trim(category, ' ' || char(9, 10, 13))
    ),
    region      TEXT NOT NULL CHECK (
        length(region) BETWEEN 1 AND 200 AND region = trim(region, ' ' || char(9, 10, 13))
    ),
    summary     TEXT NOT NULL CHECK (
        length(summary) BETWEEN 1 AND 1000 AND summary = trim(summary, ' ' || char(9, 10, 13))
    ),
    importance  INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
    wikipedia   TEXT CHECK (
        wikipedia IS NULL
        OR (length(wikipedia) BETWEEN 1 AND 200 AND wikipedia = trim(wikipedia, ' ' || char(9, 10, 13)))
    ),
    source      TEXT NOT NULL CHECK (
        length(source) <= 500
        AND (source GLOB 'http://?*' OR source GLOB 'https://?*')
        AND source NOT GLOB ('*[ ' || char(9) || char(10) || char(13) || ']*')
    ),
    built_start REAL NOT NULL CHECK (abs(built_start) < 1e15),
    built_end   REAL NOT NULL CHECK (abs(built_end) < 1e15),
    destroyed   REAL CHECK (destroyed IS NULL OR abs(destroyed) < 1e15),
    lat         REAL NOT NULL CHECK (lat >= -90 AND lat <= 90),
    lon         REAL NOT NULL CHECK (lon >= -180 AND lon <= 180),
    CHECK (built_start <= built_end),
    CHECK (destroyed IS NULL OR destroyed >= built_end)
) STRICT;

CREATE INDEX idx_landmarks_built ON landmarks (built_start);
CREATE INDEX idx_landmarks_destroyed ON landmarks (destroyed) WHERE destroyed IS NOT NULL;

-- World population estimates (PopulationEstimate).
CREATE TABLE population (
    year   REAL PRIMARY KEY CHECK (abs(year) < 1e15),
    people INTEGER NOT NULL CHECK (people >= 0),
    source TEXT CHECK (
        source IS NULL
        OR (length(source) <= 500
            AND (source GLOB 'http://?*' OR source GLOB 'https://?*')
            AND source NOT GLOB ('*[ ' || char(9) || char(10) || char(13) || ']*'))
    )
) STRICT;

-- Search. One plain table lists everything searchable, and two FTS5 indexes sit over it. The
-- pipeline decides which things get an entry (for example, unnamed stars may be left out to keep
-- the database small). After filling search_entries, the build must run
-- rebuild_search_index() in schema.py, because these are external-content indexes.
CREATE TABLE search_entries (
    entry_id    INTEGER PRIMARY KEY,
    type        TEXT NOT NULL CHECK (type IN ('vantage_point', 'event', 'period', 'landmark')),
    id          TEXT NOT NULL CHECK (
        length(id) BETWEEN 1 AND 100
        AND id NOT GLOB '*[^a-z0-9-]*' AND id NOT GLOB '-*' AND id NOT GLOB '*-' AND id NOT GLOB '*--*'
    ),
    name        TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    -- Other names, one per line: catalog designations, Bayer letters, old spellings.
    aliases     TEXT NOT NULL DEFAULT '',
    -- A short line that tells hits apart, such as "Star in Orion" or "476 CE".
    description TEXT NOT NULL DEFAULT '',
    UNIQUE (type, id)
) STRICT;

-- Word search. unicode61 with remove_diacritics 2 folds case and accents, so "Chason" finds
-- "Chason" with a hacek. prefix = '2 3' makes short prefixes (type-ahead) fast.
CREATE VIRTUAL TABLE search_fts USING fts5(
    name, aliases, description,
    content = 'search_entries', content_rowid = 'entry_id',
    tokenize = 'unicode61 remove_diacritics 2', prefix = '2 3'
);

-- Did-you-mean candidates. The trigram tokenizer matches any substring of three or more
-- characters, which finds near-misses that word search cannot.
CREATE VIRTUAL TABLE search_trigram USING fts5(
    name, aliases,
    content = 'search_entries', content_rowid = 'entry_id',
    tokenize = 'trigram'
);
