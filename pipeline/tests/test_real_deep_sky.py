"""Tests that run the shipped curated list against a real SIMBAD snapshot."""

import re
from collections import Counter
from pathlib import Path

import pytest

from earthlight.models import VantageKind
from earthlight_pipeline.build_deep_sky import DEEP_SKY_FILE
from earthlight_pipeline.deep_sky import (
    build_deep_sky,
    find_record,
    load_curated,
    lookback_years,
    read_simbad,
)

SNAPSHOT = Path(__file__).parent / "data" / "simbad_snapshot.csv"


@pytest.fixture(scope="module")
def objects():
    return load_curated(DEEP_SKY_FILE)


@pytest.fixture(scope="module")
def built(objects):
    return build_deep_sky(objects, read_simbad([SNAPSHOT]))


def test_the_shipped_list_validates_and_has_a_sensible_size(objects) -> None:
    assert 40 <= len(objects) <= 160
    kinds = Counter(o.kind for o in objects)
    assert set(kinds) == {"galaxy", "galaxy_cluster", "quasar", "cosmic_background"}
    assert kinds["cosmic_background"] == 1
    assert all(o.fame >= 1 for o in objects)


def test_the_snapshot_covers_every_simbad_object_in_the_list(objects) -> None:
    # If this fails, a SIMBAD identifier was added or renamed: refresh
    # tests/data/simbad_snapshot.csv with the real rows (see docs/data-sources.md).
    records = read_simbad([SNAPSHOT])
    missing = [o.simbad for o in objects if o.simbad and find_record(records, o.simbad) is None]
    assert missing == []


def test_every_inline_redshift_cites_a_paper(objects) -> None:
    inline = [o for o in objects if o.inline]
    assert len(inline) >= 5
    for obj in inline:
        assert obj.inline is not None
        assert re.fullmatch(r"https://arxiv\.org/abs/\d{4}\.\d{4,5}", obj.inline.source), obj.id


def test_wikipedia_titles_are_plain_titles_not_urls_or_underscored(objects) -> None:
    for obj in objects:
        if obj.wikipedia:
            assert "wikipedia.org" not in obj.wikipedia and "_" not in obj.wikipedia, obj.id


def test_the_whole_list_builds_from_the_snapshot(objects, built) -> None:
    assert len(built.records) == len(objects)
    assert built.sources["simbad"] + built.sources["inline"] == len(objects)
    ids = [r.point.id for r in built.records]
    assert len(set(ids)) == len(ids)


def test_lookbacks_span_millions_to_nearly_the_age_of_the_universe(built) -> None:
    best = sorted(r.point.lookback.best for r in built.records)
    assert 1e8 < best[0] < 3e8  # the nearest curated object is about 185 million years back
    assert 13.7e9 < best[-1] < 13.8e9  # the cosmic microwave background
    for record in built.records:
        low, mid, high = (
            record.point.lookback.minimum,
            record.point.lookback.best,
            record.point.lookback.maximum,
        )
        assert low < mid < high, record.point.id


def test_spot_checks_against_known_values(built) -> None:
    by_id = {r.point.id: r.point for r in built.records}
    # Coma Cluster at z = 0.0234: about 330 million years of lookback.
    assert by_id["coma-cluster"].lookback.best == pytest.approx(3.3e8, rel=0.03)
    # 3C 273 at z = 0.158: about 2 billion years.
    assert by_id["3c-273"].lookback.best == pytest.approx(2.04e9, rel=0.03)
    # JWST record holders sit just under the 13.8 billion year age.
    assert 13.4e9 < by_id["jades-gs-z14-0"].lookback.best < 13.6e9
    assert by_id["mom-z14"].lookback.best > by_id["gn-z11"].lookback.best
    cmb = by_id["cosmic-microwave-background"]
    assert cmb.kind is VantageKind.COSMIC_BACKGROUND
    assert cmb.lookback.best == pytest.approx(lookback_years(1089.8))
    assert cmb.lookback.best == pytest.approx(13.787e9, abs=1e6)


def test_cmb_has_a_range_that_reflects_the_cosmology(built) -> None:
    cmb = next(r.point for r in built.records if r.point.id == "cosmic-microwave-background")
    width = cmb.lookback.maximum - cmb.lookback.minimum
    assert width == pytest.approx(2 * 0.020e9, rel=0.05)  # +- 20 million years


def test_search_entries_are_unique_and_describe_the_object(built) -> None:
    names = [r.search.name for r in built.records]
    assert len(set(names)) == len(names)
    assert all(
        r.search.description.endswith(f"redshift {r.point.facts['redshift']:g}")
        for r in built.records
    )
    cartwheel = next(r.search for r in built.records if r.point.id == "cartwheel-galaxy")
    assert "MCG-06-02-022a" in cartwheel.aliases.split("\n")
