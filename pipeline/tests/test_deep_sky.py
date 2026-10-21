"""Tests for the curated deep-sky list and the redshift to lookback rules."""

import math
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from scipy.integrate import quad

from earthlight.models import VantageKind
from earthlight_pipeline import deep_sky
from earthlight_pipeline.deep_sky import (
    AGE_UNCERTAINTY_FRACTION,
    PECULIAR_VELOCITY_KM_S,
    SPEED_OF_LIGHT_KM_S,
    CuratedError,
    CuratedObject,
    SimbadRecord,
    build_deep_sky,
    combined_uncertainty,
    find_record,
    identifier_variants,
    load_curated,
    lookback_from_redshift,
    lookback_years,
    read_simbad,
    redshift_uncertainty,
    simbad_identifiers,
)

DATA = Path(__file__).parent / "data"
SNAPSHOT = DATA / "simbad_snapshot.csv"
FLOOR = PECULIAR_VELOCITY_KM_S / SPEED_OF_LIGHT_KM_S


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "deep_sky.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def entry(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "test-object",
        "name": "Test Object",
        "kind": "galaxy",
        "fame": 2,
        "simbad": "NGC 1275",
    }
    return base | overrides


def snapshot() -> dict[str, SimbadRecord]:
    return read_simbad([SNAPSHOT])


# --- the curated file ------------------------------------------------------------------------


def test_a_valid_file_loads(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
objects:
  - id: coma-cluster
    name: Coma Cluster
    kind: galaxy_cluster
    fame: 4
    simbad: ACO 1656
    wikipedia: Coma Cluster
    aliases: [Abell 1656]
  - id: far-galaxy
    name: Far Galaxy
    kind: galaxy
    fame: 1
    inline:
      redshift: 10
      error: 0.1
      source: https://arxiv.org/abs/2302.07256
""",
    )
    coma, far = load_curated(path)
    assert coma.aliases == ("Abell 1656",) and coma.inline is None
    assert far.inline is not None and far.inline.redshift == 10.0 and far.simbad is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"inline": {"redshift": 1.0, "error": 0.1, "source": "https://a.org/x"}}, "exactly one"),
        ({"simbad": None}, "exactly one"),
        ({"fame": "3"}, "fame"),
        ({"fame": True}, "fame"),
        ({"fame": 0}, "fame"),
        ({"fame": 6}, "fame"),
        ({"kind": "star"}, "kind"),
        ({"kind": "Galaxy"}, "kind"),
        ({"id": "Not A Slug"}, "id"),
        ({"name": ""}, "name"),
        ({"lookback": 5.0}, "lookback"),  # numbers never go in the file
        ({"distance_ly": 5.0}, "distance_ly"),
        ({"aliases": "Perseus A"}, "aliases"),
    ],
)
def test_bad_entries_are_rejected(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    import yaml

    path = write(tmp_path, yaml.safe_dump({"objects": [entry(**overrides)]}))
    with pytest.raises(CuratedError, match=message):
        load_curated(path)


@pytest.mark.parametrize(
    "inline",
    [
        {"redshift": 0, "error": 0.1, "source": "https://a.org/x"},
        {"redshift": -1.0, "error": 0.1, "source": "https://a.org/x"},
        {"redshift": 1.0, "error": -0.1, "source": "https://a.org/x"},
        {"redshift": "1.0", "error": 0.1, "source": "https://a.org/x"},
        {"redshift": 1.0, "error": 0.1, "source": "not a url"},
        {"redshift": 1.0, "error": 0.1},
        {"redshift": 1.0, "error": 0.1, "source": "https://a.org/x", "note": "extra"},
    ],
)
def test_bad_inline_redshifts_are_rejected(tmp_path: Path, inline: dict[str, object]) -> None:
    import yaml

    path = write(tmp_path, yaml.safe_dump({"objects": [entry(simbad=None, inline=inline)]}))
    with pytest.raises(CuratedError, match="inline"):
        load_curated(path)


def test_an_integer_redshift_is_accepted(tmp_path: Path) -> None:
    import yaml

    inline = {"redshift": 7, "error": 0, "source": "https://a.org/x"}
    (obj,) = load_curated(
        write(tmp_path, yaml.safe_dump({"objects": [entry(simbad=None, inline=inline)]}))
    )
    assert obj.inline is not None and obj.inline.redshift == 7.0


def test_every_problem_is_reported_at_once(tmp_path: Path) -> None:
    import yaml

    items = [entry(fame=9), entry(id="b", name="B", kind="nope"), entry(id="c", name="C")]
    with pytest.raises(CuratedError) as error:
        load_curated(write(tmp_path, yaml.safe_dump({"objects": items})))
    lines = str(error.value).splitlines()
    assert any(line.startswith("entry 1 (test-object)") for line in lines)
    assert any(line.startswith("entry 2 (b)") for line in lines)


def test_duplicates_are_rejected(tmp_path: Path) -> None:
    import yaml

    items = [
        entry(),
        entry(name="Other", id="test-object"),  # same id
        entry(id="other", name="TEST OBJECT"),  # same name, any case
        entry(id="third", name="Third", simbad="NGC  1275"),  # same SIMBAD object, other spacing
    ]
    with pytest.raises(CuratedError) as error:
        load_curated(write(tmp_path, yaml.safe_dump({"objects": items})))
    text = str(error.value)
    assert "duplicate id: test-object" in text
    assert "duplicate name: test object" in text
    assert "duplicate simbad identifier: ngc 1275" in text


@pytest.mark.parametrize(
    "text", ["", "[]", "objects: 5", "objects: []\nextra: 1", "- id: x", "other: []"]
)
def test_the_file_must_be_a_mapping_with_an_objects_list(tmp_path: Path, text: str) -> None:
    with pytest.raises(CuratedError, match="objects"):
        load_curated(write(tmp_path, text))


def test_a_non_mapping_entry_is_reported_not_crashed(tmp_path: Path) -> None:
    with pytest.raises(CuratedError, match="entry 1"):
        load_curated(write(tmp_path, "objects:\n  - just a string\n"))


# --- identifiers -----------------------------------------------------------------------------


def test_catalogue_identifiers_are_asked_with_every_padding() -> None:
    assert identifier_variants("ACO 1656") == ["ACO 1656", "ACO  1656", "ACO   1656"]
    assert identifier_variants("  NGC   1275 ") == ["NGC 1275", "NGC  1275", "NGC   1275"]
    assert identifier_variants("SMACS J0723.3-7327") == [
        "SMACS J0723.3-7327",
        "SMACS  J0723.3-7327",
        "SMACS   J0723.3-7327",
    ]


def test_name_identifiers_and_single_words_are_exact() -> None:
    assert identifier_variants("NAME Cartwheel Galaxy") == ["NAME Cartwheel Galaxy"]
    assert identifier_variants("Sirius") == ["Sirius"]


def test_the_simbad_identifiers_skip_inline_objects() -> None:
    objects = [
        CuratedObject.model_validate(entry()),
        CuratedObject.model_validate(
            entry(
                id="b",
                name="B",
                simbad=None,
                inline={"redshift": 5.0, "error": 0.1, "source": "https://a.org/x"},
            )
        ),
    ]
    assert simbad_identifiers(objects) == identifier_variants("NGC 1275")


def test_simbad_rows_are_found_however_they_are_padded() -> None:
    records = snapshot()
    for spelling in ("ACO 1656", "aco  1656", "ACO   1656 "):
        found = find_record(records, spelling)
        assert found is not None and found.main_id == "ACO 1656"
    assert find_record(records, "ACO 99999") is None


def test_snapshot_rows_have_the_expected_fields() -> None:
    quasar = find_record(snapshot(), "3C 273")
    assert quasar is not None
    assert quasar.object_type == "BLL" and quasar.redshift_type == "z" and quasar.quality == "C"
    assert quasar.redshift_text == "0.15756751" and quasar.redshift_error == 5.0e-4
    assert quasar.ra_deg == pytest.approx(187.2779, abs=1e-4)
    assert quasar.dec_deg == pytest.approx(2.0524, abs=1e-4)


def test_short_and_blank_simbad_rows_do_not_crash(tmp_path: Path) -> None:
    path = tmp_path / "s.csv"
    path.write_text(
        "asked,main_id,otype,ra,dec,rvz_redshift,rvz_err,rvz_type,rvz_qual,rvz_bibcode\n"
        "A 1,A 1,G\n,,,,,,,,,\nB 2\n",
        encoding="utf-8",
    )
    records = read_simbad([path])
    assert set(records) == {"a 1", "b 2"}
    a = records["a 1"]
    assert a.redshift_text == "" and a.ra_deg is None and a.quality == ""


# --- redshift uncertainty --------------------------------------------------------------------


def record(**overrides: object) -> SimbadRecord:
    base: dict[str, object] = {
        "asked": "X",
        "main_id": "X",
        "object_type": "G",
        "ra_deg": 10.0,
        "dec_deg": 20.0,
        "redshift_text": "0.5",
        "redshift_error": None,
        "redshift_type": "z",
        "quality": "C",
        "bibcode": "2000XXX",
    }
    return SimbadRecord(**(base | overrides))  # type: ignore[arg-type]


def test_a_redshift_error_in_z_is_combined_with_the_velocity_floor() -> None:
    sigma = redshift_uncertainty(record(redshift_error=0.003))
    assert sigma == pytest.approx(math.hypot(0.003, FLOOR))


def test_an_error_in_kilometres_per_second_is_converted() -> None:
    sigma = redshift_uncertainty(record(redshift_type="v", redshift_error=4.0))
    assert sigma == pytest.approx(math.hypot(4.0 / SPEED_OF_LIGHT_KM_S, FLOOR))
    assert redshift_uncertainty(record(redshift_type="c", redshift_error=4.0)) == sigma


@pytest.mark.parametrize(
    ("text", "half_unit"), [("0.03", 0.005), ("2.2", 0.05), ("3.783", 0.0005), ("12", 0.5)]
)
def test_a_rounded_value_without_an_error_gets_half_a_unit(text: str, half_unit: float) -> None:
    sigma = redshift_uncertainty(record(redshift_text=text))
    assert sigma == pytest.approx(math.hypot(half_unit, FLOOR))


def test_the_floor_applies_even_to_a_precise_redshift() -> None:
    assert combined_uncertainty(0.0) == pytest.approx(FLOOR)
    assert redshift_uncertainty(record(redshift_error=1e-9)) == pytest.approx(FLOOR, rel=1e-6)


@given(st.floats(min_value=0, max_value=10, allow_nan=False))
def test_the_uncertainty_never_drops_below_the_floor(error: float) -> None:
    assert combined_uncertainty(error) >= FLOOR


# --- redshift to lookback --------------------------------------------------------------------


def test_lookback_matches_an_independent_integration() -> None:
    # Lookback time is the integral of dz / ((1 + z) H(z)). A flat universe of matter and a
    # cosmological constant (Planck 2018 values, radiation neglected) is within 0.5 percent of
    # astropy's full model at z = 1.
    h0, matter = 67.66, 0.3097
    seconds_per_year = 365.25 * 86400
    km_per_mpc = 3.0856775814913673e19

    def integrand(z: float) -> float:
        return 1.0 / ((1.0 + z) * math.sqrt(matter * (1.0 + z) ** 3 + (1.0 - matter)))

    integral, _ = quad(integrand, 0.0, 1.0)
    expected = integral / (h0 / km_per_mpc) / seconds_per_year
    assert lookback_years(1.0) == pytest.approx(expected, rel=0.005)
    assert 7.5e9 < lookback_years(1.0) < 8.3e9


def test_lookback_grows_with_redshift_and_stays_below_the_age_of_the_universe() -> None:
    values = [lookback_years(z) for z in (0.01, 0.1, 1, 3, 10, 14.4, 100, 1089.8)]
    assert values == sorted(values)
    assert values[0] == pytest.approx(1.4e8, rel=0.05)  # about 140 million years at z = 0.01
    assert values[-1] < 13.787e9  # Planck 2018 age
    assert values[-1] == pytest.approx(13.787e9, abs=1e6)  # last scattering is early


def test_the_range_is_ordered_and_always_has_width() -> None:
    for z in (0.0129, 0.5, 2.2, 7.6423, 14.44, 1089.8):
        sigma = combined_uncertainty(0.0)
        r = lookback_from_redshift(z, sigma)
        assert r.minimum < r.best < r.maximum


def test_the_range_includes_the_cosmology_uncertainty() -> None:
    z = 1089.8
    r = lookback_from_redshift(z, combined_uncertainty(0.21))
    best = lookback_years(z)
    assert r.best == best
    assert r.maximum - best == pytest.approx(best * AGE_UNCERTAINTY_FRACTION, rel=0.01)
    assert best - r.minimum == pytest.approx(best * AGE_UNCERTAINTY_FRACTION, rel=0.01)
    assert pytest.approx(0.00145, rel=0.01) == AGE_UNCERTAINTY_FRACTION


def test_a_big_sigma_does_not_push_the_range_below_zero_redshift() -> None:
    r = lookback_from_redshift(0.01, 0.5)
    assert 0 <= r.minimum < r.best < r.maximum


# --- building --------------------------------------------------------------------------------


def objects_for(*simbad: str) -> list[CuratedObject]:
    return [
        CuratedObject.model_validate(
            entry(id=f"object-{n}", name=f"Object {n}", simbad=name, aliases=["Alias"])
        )
        for n, name in enumerate(simbad)
    ]


def test_a_simbad_object_gets_position_constellation_and_facts() -> None:
    (built,) = build_deep_sky(objects_for("3C 273"), snapshot()).records
    point = built.point
    assert point.kind is VantageKind.GALAXY  # the entry's kind, not SIMBAD's guess
    assert point.ra_deg == pytest.approx(187.2779, abs=1e-4)
    assert point.constellation == "Virgo"
    assert point.fame == 2 and point.magnitude is None and point.host_id is None
    assert point.lookback.best == pytest.approx(lookback_years(0.15756751))
    assert point.facts == {
        "redshift": 0.157568,
        "redshift_uncertainty": float(f"{combined_uncertainty(5.0e-4):.3g}"),
        "redshift_source": "2022ApJS..261....2K",
        "cosmology": "Planck18",
        "simbad_id": "3C 273",
        "simbad_type": "BLL",
    }
    assert built.search.id == "object-0" and built.search.type == "vantage_point"
    assert built.search.aliases == "Alias\n3C 273"
    assert built.search.description == "Galaxy, redshift 0.157568"


def test_an_inline_object_has_no_position_and_cites_its_source() -> None:
    far = CuratedObject.model_validate(
        entry(
            id="far",
            name="Far",
            kind="cosmic_background",
            simbad=None,
            aliases=[],
            inline={
                "redshift": 1089.8,
                "error": 0.21,
                "source": "https://arxiv.org/abs/1807.06209",
            },
        )
    )
    build = build_deep_sky([far], {})
    (built,) = build.records
    assert built.point.ra_deg is None and built.point.constellation is None
    assert built.point.facts["redshift_source"] == "https://arxiv.org/abs/1807.06209"
    assert "simbad_id" not in built.point.facts
    assert built.point.lookback.maximum > built.point.lookback.minimum
    assert built.search.description == "Cosmic microwave background, redshift 1089.8"
    assert built.search.aliases == ""
    assert dict(build.sources) == {"inline": 1}


def test_positions_and_constellations_stay_with_the_right_objects() -> None:
    mixed = [
        *objects_for("NGC 1275"),
        CuratedObject.model_validate(
            entry(
                id="inline",
                name="Inline",
                simbad=None,
                inline={"redshift": 9.0, "error": 0.1, "source": "https://a.org/x"},
            )
        ),
        *objects_for("3C 273")[:1],
    ]
    mixed[2] = mixed[2].model_copy(update={"id": "later", "name": "Later"})
    build = build_deep_sky(mixed, snapshot())
    assert [r.point.constellation for r in build.records] == ["Perseus", None, "Virgo"]
    assert dict(build.sources) == {"simbad": 2, "inline": 1}


def test_every_problem_is_listed_when_objects_cannot_be_built() -> None:
    objects = objects_for(
        "ACO 99999",  # not in the snapshot
        "M 31",  # too near: its redshift is its own motion
        "SMACS J0723.3-7327",  # SIMBAD grades the redshift E
        "NGC 1275",  # fine
    )
    with pytest.raises(CuratedError) as error:
        build_deep_sky(objects, snapshot())
    lines = str(error.value).splitlines()
    assert len(lines) == 3
    assert "object-0: SIMBAD has no object 'ACO 99999'" in lines[0]
    assert "object-1: redshift" in lines[1] and "needs a measured distance" in lines[1]
    assert "object-2" in lines[2] and "'E'" in lines[2]


def test_an_object_with_no_redshift_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "s.csv"
    path.write_text(
        "asked,main_id,otype,ra,dec,rvz_redshift,rvz_err,rvz_type,rvz_qual,rvz_bibcode\n"
        "NGC 1275,NGC  1275,Bla,49.9,41.5,,,,,\n",
        encoding="utf-8",
    )
    with pytest.raises(CuratedError, match="no redshift"):
        build_deep_sky(objects_for("NGC 1275"), read_simbad([path]))


def test_a_missing_quality_grade_is_not_accepted(tmp_path: Path) -> None:
    path = tmp_path / "s.csv"
    path.write_text(
        "asked,main_id,otype,ra,dec,rvz_redshift,rvz_err,rvz_type,rvz_qual,rvz_bibcode\n"
        "NGC 1275,NGC  1275,Bla,49.9,41.5,0.0168,,z,,\n",
        encoding="utf-8",
    )
    with pytest.raises(CuratedError, match="'none'"):
        build_deep_sky(objects_for("NGC 1275"), read_simbad([path]))


def test_a_negative_redshift_from_a_nearby_object_is_refused_not_converted() -> None:
    # Andromeda is falling towards us: its SIMBAD redshift is negative.
    with pytest.raises(CuratedError, match=r"below 0.01"):
        build_deep_sky(objects_for("M 31"), snapshot())


def test_the_module_exposes_its_thresholds() -> None:
    assert deep_sky.MIN_REDSHIFT == 0.01 and deep_sky.WORST_ACCEPTED_QUALITY == "D"
