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
    cluster_names,
    load_curated,
    read_simbad,
)
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
