"""Tests for star clusters in the deep-sky list: the curated entries and the build."""

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from earthlight.models import VantageKind
from earthlight_pipeline.deep_sky import (
    CuratedError,
    CuratedObject,
    SimbadRecord,
    build_deep_sky,
    catalogue_names,
    cluster_names,
    cosmicflows_numbers,
    load_curated,
    read_simbad,
)
from earthlight_pipeline.galaxy_distances import GalaxyRecord, read_cosmicflows, read_mcconnachie
from earthlight_pipeline.star_clusters import ClusterRecord, read_hunt_reffert

DATA = Path(__file__).parent / "data"


def clusters() -> dict[str, ClusterRecord]:
    return read_hunt_reffert([DATA / "hunt_reffert_snapshot.csv"])


def simbad() -> dict[str, SimbadRecord]:
    return read_simbad([DATA / "simbad_snapshot.csv"])


def cluster_entry(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "pleiades",
        "name": "Pleiades",
        "kind": "star_cluster",
        "fame": 5,
        "distance": {"catalogue": "hunt_reffert_2023", "name": "Melotte_22"},
        "aliases": ["M45", "Seven Sisters"],
    }
    return base | overrides


def cluster_object(**overrides: object) -> CuratedObject:
    return CuratedObject.model_validate(cluster_entry(**overrides))


# --- the curated entry -----------------------------------------------------------------------


def test_a_cluster_entry_takes_its_numbers_from_a_catalogue() -> None:
    pleiades = cluster_object()
    assert pleiades.distance is not None and pleiades.distance.name == "Melotte_22"
    assert pleiades.simbad is None and pleiades.inline is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"simbad": "M 45"}, "exactly one"),  # two sources of numbers
        ({"distance": None}, "exactly one"),  # no source of numbers
        ({"kind": "galaxy"}, "star_cluster"),  # a distance is for clusters only
        ({"distance": {"catalogue": "somewhere_else", "name": "X"}}, "catalogue"),
        ({"distance": {"catalogue": "hunt_reffert_2023"}}, "name"),
        ({"distance": {"catalogue": "hunt_reffert_2023", "name": "X", "extra": 1}}, "extra"),
    ],
)
def test_a_badly_formed_cluster_entry_is_refused(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        cluster_object(**overrides)


def test_a_cluster_needs_a_distance_not_a_redshift() -> None:
    with pytest.raises(ValidationError, match="star_cluster"):
        CuratedObject.model_validate(
            {"id": "x", "name": "X", "kind": "star_cluster", "fame": 1, "simbad": "M 45"}
        )


def test_the_same_catalogue_name_twice_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "deep_sky.yaml"
    path.write_text(
        "objects:\n"
        "  - {id: a, name: A, kind: star_cluster, fame: 1,"
        " distance: {catalogue: hunt_reffert_2023, name: Melotte_22}}\n"
        "  - {id: b, name: B, kind: star_cluster, fame: 1,"
        " distance: {catalogue: hunt_reffert_2023, name: Melotte_22}}\n",
        encoding="utf-8",
    )
    with pytest.raises(CuratedError, match="duplicate catalogue name: Melotte_22"):
        load_curated(path)


def test_cluster_names_lists_only_the_clusters() -> None:
    mixed = [
        CuratedObject.model_validate(
            {"id": "g", "name": "G", "kind": "galaxy", "fame": 1, "simbad": "NGC 1275"}
        ),
        cluster_object(),
        cluster_object(
            id="hyades",
            name="Hyades",
            distance={"catalogue": "hunt_reffert_2023", "name": "Melotte_25"},
        ),
    ]
    assert cluster_names(mixed) == ["Melotte_22", "Melotte_25"]


# --- the build -------------------------------------------------------------------------------


def test_a_cluster_gets_a_position_a_constellation_and_its_facts() -> None:
    build = build_deep_sky([cluster_object()], {}, clusters())
    (built,) = build.records
    point = built.point
    assert point.kind is VantageKind.STAR_CLUSTER
    assert point.constellation == "Taurus"
    assert point.ra_deg == pytest.approx(56.68, abs=0.01) and point.dec_deg == pytest.approx(
        24.11, abs=0.01
    )
    assert point.fame == 5 and point.magnitude is None and point.host_id is None
    assert point.lookback.minimum < 440 < point.lookback.maximum
    assert point.lookback.best == pytest.approx(440, rel=0.01)
    assert point.facts == {
        "distance_pc": 134.84,
        "distance_light_years": 439.8,
        "distance_source": "hunt_reffert_2023",
        "catalogue_name": "Melotte_22",
        "cluster_type": "open",
        "member_stars": 907,
    }
    assert built.search.aliases == "M45\nSeven Sisters"  # only the curated aliases
    assert built.search.description == "Open cluster, 440 light-years"
    assert dict(build.sources) == {"hunt_reffert_2023": 1}


def test_a_globular_cluster_is_described_as_one() -> None:
    omega = cluster_object(
        id="omega-centauri",
        name="Omega Centauri",
        distance={"catalogue": "hunt_reffert_2023", "name": "NGC_5139"},
        aliases=[],
    )
    (built,) = build_deep_sky([omega], {}, clusters()).records
    assert built.point.facts["cluster_type"] == "globular"
    assert built.point.constellation == "Centaurus"
    assert built.search.description == "Globular cluster, 17,200 light-years"
    assert built.search.aliases == ""


def test_clusters_and_other_objects_keep_the_order_of_the_list() -> None:
    first = CuratedObject.model_validate(
        {"id": "ngc-1275", "name": "NGC 1275", "kind": "galaxy", "fame": 3, "simbad": "NGC 1275"}
    )
    last = CuratedObject.model_validate(
        {"id": "3c-273", "name": "3C 273", "kind": "quasar", "fame": 4, "simbad": "3C 273"}
    )
    build = build_deep_sky([first, cluster_object(), last], simbad(), clusters())
    assert [r.point.id for r in build.records] == ["ngc-1275", "pleiades", "3c-273"]
    assert dict(build.sources) == {"simbad": 2, "hunt_reffert_2023": 1}


def test_every_cluster_problem_is_listed_together() -> None:
    records = clusters()
    records["Moving_Group"] = replace(records["Melotte_22"], name="Moving_Group", cluster_type="m")
    records["No_Position"] = replace(records["Melotte_22"], name="No_Position", ra_deg=None)
    records["Disordered"] = replace(
        records["Melotte_22"], name="Disordered", dist16_pc=200.0, dist50_pc=100.0
    )
    objects = [
        cluster_object(id="missing", name="Missing", distance=_catalogue("Not_A_Cluster")),
        cluster_object(id="moving", name="Moving", distance=_catalogue("Moving_Group")),
        cluster_object(id="nowhere", name="Nowhere", distance=_catalogue("No_Position")),
        cluster_object(id="backwards", name="Backwards", distance=_catalogue("Disordered")),
        cluster_object(),  # fine
    ]
    with pytest.raises(CuratedError) as error:
        build_deep_sky(objects, {}, records)
    lines = str(error.value).splitlines()
    assert len(lines) == 4
    assert "missing: Hunt and Reffert has no cluster 'Not_A_Cluster'" in lines[0]
    assert "moving: 'Moving_Group' is type 'm'" in lines[1]
    assert "nowhere: Hunt and Reffert has no position" in lines[2]
    assert "backwards: Disordered" in lines[3] and "out of order" in lines[3]


def test_clusters_are_not_built_without_the_catalogue_rows() -> None:
    with pytest.raises(CuratedError, match="has no cluster 'Melotte_22'"):
        build_deep_sky([cluster_object()], {})


def _catalogue(name: str) -> dict[str, str]:
    return {"catalogue": "hunt_reffert_2023", "name": name}


# --- nearby galaxies (McConnachie 2012 and Cosmicflows-4) -------------------------------------


def galaxies() -> dict[tuple[str, str], GalaxyRecord]:
    return {
        **read_mcconnachie([DATA / "mcconnachie_snapshot.csv"]),
        **read_cosmicflows([DATA / "cosmicflows4_snapshot.csv"]),
    }


def galaxy_entry(catalogue: str, catalogue_name: str, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "a-galaxy",
        "name": "A Galaxy",
        "kind": "galaxy",
        "fame": 3,
        "distance": {"catalogue": catalogue, "name": catalogue_name},
        "aliases": ["Alias"],
    }
    return base | overrides


def galaxy_object(catalogue: str, catalogue_name: str, **overrides: object) -> CuratedObject:
    return CuratedObject.model_validate(galaxy_entry(catalogue, catalogue_name, **overrides))


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (galaxy_entry("hunt_reffert_2023", "Melotte_22"), "star_cluster only"),
        (galaxy_entry("mcconnachie_2012", "LMC", kind="star_cluster"), "galaxy only"),
        (galaxy_entry("cosmicflows_4", "PGC 28655", kind="quasar"), "galaxy only"),
        (galaxy_entry("cosmicflows_4", "M 82"), "PGC n"),
        (galaxy_entry("cosmicflows_4", "PGC"), "PGC n"),
        (galaxy_entry("cosmicflows_4", "PGC x1"), "PGC n"),
    ],
)
def test_a_galaxy_entry_must_match_its_catalogue(entry: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        CuratedObject.model_validate(entry)


def test_the_same_name_in_two_catalogues_is_fine_but_twice_in_one_is_not(tmp_path: Path) -> None:
    path = tmp_path / "deep_sky.yaml"
    same = (
        "objects:\n"
        "  - {id: a, name: A, kind: galaxy, fame: 1,"
        " distance: {catalogue: mcconnachie_2012, name: LMC}}\n"
        "  - {id: b, name: B, kind: galaxy, fame: 1,"
        " distance: {catalogue: mcconnachie_2012, name: LMC}}\n"
    )
    path.write_text(same, encoding="utf-8")
    with pytest.raises(CuratedError, match="duplicate catalogue name: LMC in mcconnachie_2012"):
        load_curated(path)
    path.write_text(
        same.replace(
            "mcconnachie_2012, name: LMC}}\n  - {id: b", "cosmicflows_4, name: PGC 1}}\n  - {id: b"
        ),
        encoding="utf-8",
    )
    assert [o.id for o in load_curated(path)] == ["a", "b"]


def test_the_names_to_ask_each_catalogue_for() -> None:
    objects = [
        galaxy_object("mcconnachie_2012", "LMC", id="lmc"),
        galaxy_object("cosmicflows_4", "PGC 28655", id="m82"),
        galaxy_object("cosmicflows_4", "PGC 47404", id="m51"),
        cluster_object(),
    ]
    assert catalogue_names(objects, "mcconnachie_2012") == ["LMC"]
    assert cosmicflows_numbers(objects) == [28655, 47404]
    assert cluster_names(objects) == ["Melotte_22"]


def test_a_local_group_galaxy_gets_a_position_and_its_distance_facts() -> None:
    lmc = galaxy_object("mcconnachie_2012", "LMC", id="lmc", name="Large Magellanic Cloud")
    build = build_deep_sky([lmc], {}, None, galaxies())
    (built,) = build.records
    point = built.point
    assert point.kind is VantageKind.GALAXY and point.constellation == "Dorado"
    assert point.ra_deg == pytest.approx(80.894, abs=0.001)
    assert point.lookback.minimum < point.lookback.best < point.lookback.maximum
    assert point.lookback.best == pytest.approx(165_000, rel=0.01)
    assert point.facts == {
        "distance_modulus": 18.52,
        "distance_modulus_error_plus": 0.09,
        "distance_modulus_error_minus": 0.09,
        "distance_light_years": 165_000.0,
        "distance_source": "mcconnachie_2012",
        "catalogue_name": "LMC",
    }
    assert (
        built.search.aliases == "Alias"
        and built.search.description == "Galaxy, 165,000 light-years"
    )
    assert dict(build.sources) == {"mcconnachie_2012": 1}


def test_a_cosmicflows_galaxy_is_described_in_millions_of_light_years() -> None:
    m82 = galaxy_object("cosmicflows_4", "PGC 28655", id="messier-82", name="Messier 82")
    (built,) = build_deep_sky([m82], {}, None, galaxies()).records
    assert built.point.facts["catalogue_name"] == "PGC 28655"
    assert built.point.constellation == "Ursa Major"
    assert built.search.description == "Galaxy, 11.5 million light-years"


def test_every_kind_of_object_keeps_its_place_in_the_list() -> None:
    first = CuratedObject.model_validate(
        {"id": "ngc-1275", "name": "NGC 1275", "kind": "galaxy", "fame": 3, "simbad": "NGC 1275"}
    )
    objects = [
        galaxy_object("cosmicflows_4", "PGC 28655", id="m82", name="M82"),
        first,
        cluster_object(),
        galaxy_object("mcconnachie_2012", "LMC", id="lmc", name="LMC"),
    ]
    build = build_deep_sky(objects, simbad(), clusters(), galaxies())
    assert [r.point.id for r in build.records] == ["m82", "ngc-1275", "pleiades", "lmc"]
    assert dict(build.sources) == {
        "cosmicflows_4": 1,
        "simbad": 1,
        "hunt_reffert_2023": 1,
        "mcconnachie_2012": 1,
    }


def test_every_galaxy_problem_is_listed_together() -> None:
    records = galaxies()
    lmc = records[("mcconnachie_2012", "LMC")]
    records[("mcconnachie_2012", "Nowhere")] = replace(lmc, name="Nowhere", ra_deg=None)
    records[("mcconnachie_2012", "NoErrors")] = replace(lmc, name="NoErrors", error_plus=None)
    records[("cosmicflows_4", "PGC 99")] = replace(lmc, name="PGC 99", modulus=-5.0)
    objects = [
        galaxy_object("mcconnachie_2012", "Not_A_Galaxy", id="missing"),
        galaxy_object("mcconnachie_2012", "Nowhere", id="nowhere"),
        galaxy_object("mcconnachie_2012", "NoErrors", id="noerrors"),
        galaxy_object("cosmicflows_4", "PGC 99", id="negative"),
        galaxy_object("cosmicflows_4", "PGC 98", id="absent"),
        galaxy_object("mcconnachie_2012", "LMC", id="fine"),
    ]
    with pytest.raises(CuratedError) as error:
        build_deep_sky(objects, {}, None, records)
    lines = str(error.value).splitlines()
    assert len(lines) == 5
    assert "missing: McConnachie 2012 has no galaxy 'Not_A_Galaxy'" in lines[0]
    assert "nowhere: McConnachie 2012 has no position" in lines[1]
    assert "noerrors" in lines[2] and "no distance modulus" in lines[2]
    assert "negative" in lines[3] and "not a distance" in lines[3]
    assert "absent: Cosmicflows-4 has no galaxy 'PGC 98'" in lines[4]
