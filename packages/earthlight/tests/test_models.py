"""Tests for the shared data models."""

import json
import math
import os
import string
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, TypeAdapter, ValidationError

from earthlight.lookback import LookbackRange, MomentRange
from earthlight.models import (
    EarthSnapshot,
    HistoryEvent,
    HistoryPeriod,
    Landmark,
    LandmarkStatus,
    Match,
    MomentResult,
    PopulationEstimate,
    SearchResult,
    SearchType,
    SnapshotLandmark,
    Suggestion,
    VantageKind,
    VantagePoint,
    ZoneInfo,
)

SCHEMA_FILE = Path(__file__).parent / "data" / "models_schema.json"
SOURCE = "https://example.org/source"


def vantage(**overrides: Any) -> VantagePoint:
    values: dict[str, Any] = {
        "id": "vega",
        "name": "Vega",
        "kind": "star",
        "lookback": {"minimum": 24.9, "best": 25.0, "maximum": 25.1},
    }
    return VantagePoint.model_validate(values | overrides)


def event(**overrides: Any) -> HistoryEvent:
    values: dict[str, Any] = {
        "id": "fall-of-constantinople",
        "name": "Fall of Constantinople",
        "category": "politics",
        "region": "Europe",
        "summary": "The Ottoman army captured the capital of the Byzantine Empire.",
        "importance": 5,
        "source": SOURCE,
        "year": 1453.4,
    }
    return HistoryEvent.model_validate(values | overrides)


def landmark(**overrides: Any) -> Landmark:
    values: dict[str, Any] = {
        "id": "great-pyramid",
        "name": "Great Pyramid of Giza",
        "category": "monument",
        "region": "Africa",
        "summary": "A royal tomb built for a pharaoh of the Fourth Dynasty.",
        "importance": 5,
        "source": SOURCE,
        "built_start": -2560.0,
        "built_end": -2540.0,
        "lat": 29.98,
        "lon": 31.13,
    }
    return Landmark.model_validate(values | overrides)


# --- shared behavior -----------------------------------------------------------------------


def test_models_are_immutable() -> None:
    point = vantage()
    with pytest.raises(ValidationError):
        point.name = "Altair"  # pyright: ignore[reportAttributeAccessIssue]


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        vantage(colour="blue")


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_are_rejected(bad: float) -> None:
    with pytest.raises(ValidationError):
        vantage(magnitude=bad)
    with pytest.raises(ValidationError):
        event(year=bad)


def test_json_input_cannot_smuggle_in_infinity() -> None:
    payload = vantage().model_dump_json().replace('"magnitude":null', '"magnitude":Infinity')
    with pytest.raises(ValidationError):
        VantagePoint.model_validate_json(payload)


# --- vantage points -------------------------------------------------------------------------


@pytest.mark.parametrize("good", ["vega", "m31", "proxima-cen-b", "3c-273", "gaia-dr3-123456789"])
def test_valid_ids(good: str) -> None:
    assert vantage(id=good).id == good


@pytest.mark.parametrize(
    "bad",
    ["", "Vega", "proxima_cen_b", "proxima--cen", "-vega", "vega-", "a b", "vega!", "é", "a" * 101],
)
def test_invalid_ids(bad: str) -> None:
    with pytest.raises(ValidationError):
        vantage(id=bad)


def test_names_are_stripped_and_cannot_be_empty() -> None:
    assert vantage(name="  Vega  ").name == "Vega"
    with pytest.raises(ValidationError):
        vantage(name="   ")


def test_every_kind_is_a_snake_case_string() -> None:
    assert [k.value for k in VantageKind] == [
        "planet",
        "spacecraft",
        "zone",
        "star",
        "exoplanet",
        "star_cluster",
        "galaxy",
        "galaxy_cluster",
        "quasar",
        "cosmic_background",
    ]
    with pytest.raises(ValidationError):
        vantage(kind="comet")


def test_lookback_accepts_a_range_object_or_a_dict() -> None:
    from_object = vantage(lookback=LookbackRange(1.0, 2.0, 3.0))
    from_dict = vantage(lookback={"minimum": 1.0, "best": 2.0, "maximum": 3.0})
    assert from_object == from_dict


@pytest.mark.parametrize(
    "bad",
    [
        {"minimum": 3.0, "best": 2.0, "maximum": 1.0},
        {"minimum": -1.0, "best": 2.0, "maximum": 3.0},
        {"minimum": 1.0, "best": 2.0},
    ],
)
def test_invalid_lookback_is_rejected(bad: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        vantage(lookback=bad)


@pytest.mark.parametrize("fame", [-1, 6])
def test_fame_must_be_between_0_and_5(fame: int) -> None:
    with pytest.raises(ValidationError):
        vantage(fame=fame)


def test_only_exoplanets_have_hosts() -> None:
    planet = vantage(id="proxima-cen-b", kind="exoplanet", host_id="proxima-cen")
    assert planet.host_id == "proxima-cen"
    with pytest.raises(ValidationError, match="only an exoplanet"):
        vantage(kind="star", host_id="proxima-cen")
    with pytest.raises(ValidationError, match="own host"):
        vantage(id="proxima-cen", kind="exoplanet", host_id="proxima-cen")


def test_facts_keep_their_scalar_types() -> None:
    point = vantage(
        facts={"spectral_type": "A0V", "planets": 1, "mass": 2.1, "variable": False, "x": None}
    )
    assert point.facts == {
        "spectral_type": "A0V",
        "planets": 1,
        "mass": 2.1,
        "variable": False,
        "x": None,
    }
    assert type(point.facts["planets"]) is int
    assert type(point.facts["mass"]) is float
    assert type(point.facts["variable"]) is bool


@pytest.mark.parametrize("bad", [{"nested": {"a": 1}}, {"list": [1, 2]}])
def test_facts_cannot_hold_containers(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        vantage(facts=bad)


# --- stable JSON ----------------------------------------------------------------------------


def test_vantage_point_json_shape_is_stable() -> None:
    point = vantage(
        magnitude=0.03, constellation="Lyra", fame=4, wikipedia="Vega", facts={"type": "A0V"}
    )
    assert point.model_dump(mode="json") == {
        "id": "vega",
        "name": "Vega",
        "kind": "star",
        "lookback": {"minimum": 24.9, "best": 25.0, "maximum": 25.1},
        "magnitude": 0.03,
        "constellation": "Lyra",
        "fame": 4,
        "host_id": None,
        "wikipedia": "Vega",
        "facts": {"type": "A0V"},
    }


def test_match_reports_its_range_width_but_does_not_serialize_it() -> None:
    match = Match(vantage_point=vantage(), offset_years=-0.5)
    assert match.range_width_years == pytest.approx(0.2)
    dumped = match.model_dump(mode="json")
    assert set(dumped) == {"vantage_point", "offset_years"}
    assert Match.model_validate_json(match.model_dump_json()) == match


_word = (
    st.text(alphabet=string.ascii_letters + " ", min_size=1, max_size=30)
    .map(str.strip)
    .filter(bool)
)
_slug = st.from_regex(
    r"[a-z0-9]{1,20}(-[a-z0-9]{1,20}){0,3}", fullmatch=True
)  # at most 83 characters
_scalar = st.one_of(
    st.text(max_size=20),
    st.integers(-(10**12), 10**12),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.none(),
)


@st.composite
def vantage_points(draw: st.DrawFn) -> VantagePoint:
    low, best, high = sorted(draw(st.floats(0, 1e10)) for _ in range(3))
    return VantagePoint(
        id=draw(_slug),
        name=draw(_word),
        kind=draw(st.sampled_from([k for k in VantageKind if k is not VantageKind.EXOPLANET])),
        lookback=LookbackRange(low, best, high),
        magnitude=draw(st.none() | st.floats(-30, 30)),
        constellation=draw(st.none() | _word),
        fame=draw(st.integers(0, 5)),
        wikipedia=draw(st.none() | _word),
        facts=draw(st.dictionaries(st.text(min_size=1, max_size=10), _scalar, max_size=4)),
    )


@given(vantage_points())
def test_vantage_points_survive_a_json_round_trip(point: VantagePoint) -> None:
    assert VantagePoint.model_validate_json(point.model_dump_json()) == point


@given(st.floats(-1e10, 2100), st.floats(0, 100), st.integers(1, 5))
def test_events_survive_a_json_round_trip(year: float, uncertainty: float, importance: int) -> None:
    item = event(year=year, year_uncertainty=uncertainty, importance=importance)
    assert HistoryEvent.model_validate_json(item.model_dump_json()) == item


# --- moment result ---------------------------------------------------------------------------


def zone_info(**overrides: Any) -> ZoneInfo:
    values: dict[str, Any] = {
        "id": "interstellar-space",
        "name": "Interstellar space",
        "description": "The gap between the Sun's surroundings and the nearest star.",
        "inner_au": 100_000.0,
        "outer_au": 268_000.0,
        "lookback": {"minimum": 1.58, "best": 2.9, "maximum": 4.24},
        "percent_to_proxima": 40.0,
    }
    return ZoneInfo.model_validate(values | overrides)


def test_zone_info_rules() -> None:
    assert zone_info().percent_to_proxima == 40.0
    assert zone_info(percent_to_proxima=None).percent_to_proxima is None
    for bad in (-1, 100.1):
        with pytest.raises(ValidationError):
            zone_info(percent_to_proxima=bad)
    with pytest.raises(ValidationError, match="nearer"):
        zone_info(inner_au=300_000.0)
    with pytest.raises(ValidationError, match="nearer"):
        zone_info(inner_au=268_000.0)  # equal edges leave no zone at all
    with pytest.raises(ValidationError):
        zone_info(outer_au=0)


def test_moment_result_defaults_are_empty() -> None:
    result = MomentResult(moment=1492.0, moment_label="1492 CE", lookback_years=534.5)
    assert result.zone is None
    assert (result.famous, result.exoplanet, result.visible_tonight, result.most_precise) == (
        None,
    ) * 4
    assert result.notes == []


def test_moment_result_holds_four_categories_and_a_zone() -> None:
    match = Match(vantage_point=vantage(), offset_years=0.1)
    result = MomentResult(
        moment=2000.0,
        moment_label="2000 CE",
        lookback_years=26.5,
        zone=zone_info(),
        famous=match,
        exoplanet=match,
        visible_tonight=match,
        most_precise=match,
        notes=["No exoplanet is that close."],
    )
    dumped = result.model_dump(mode="json")
    assert list(dumped) == [
        "moment",
        "moment_label",
        "lookback_years",
        "zone",
        "famous",
        "exoplanet",
        "visible_tonight",
        "most_precise",
        "notes",
    ]
    assert MomentResult.model_validate_json(result.model_dump_json()) == result


# --- history -----------------------------------------------------------------------------------


def test_event_rules() -> None:
    assert event().year_uncertainty == 0.0
    for bad in (
        {"importance": 0},
        {"importance": 6},
        {"year_uncertainty": -1},
        {"source": "not a url"},
        {"summary": ""},
    ):
        with pytest.raises(ValidationError):
            event(**bad)
    with pytest.raises(ValidationError):
        event(source="ftp://example.org/x")


def test_period_must_not_end_before_it_starts() -> None:
    values: dict[str, Any] = {
        "id": "ming-dynasty",
        "name": "Ming dynasty",
        "category": "politics",
        "region": "Asia",
        "summary": "A ruling house of China.",
        "importance": 4,
        "source": SOURCE,
        "start": 1368.0,
        "end": 1644.0,
    }
    assert HistoryPeriod.model_validate(values).end == 1644.0
    with pytest.raises(ValidationError, match="end before"):
        HistoryPeriod.model_validate(values | {"start": 1700.0})
    assert HistoryPeriod.model_validate(values | {"start": 1500.0, "end": 1500.0}).start == 1500.0


def test_landmark_rules() -> None:
    assert landmark().destroyed is None
    assert landmark(destroyed=1301.0).destroyed == 1301.0
    with pytest.raises(ValidationError, match="finished"):
        landmark(built_start=-2500.0)
    with pytest.raises(ValidationError, match="destroyed"):
        landmark(destroyed=-3000.0)
    for bad in ({"lat": 90.1}, {"lat": -91}, {"lon": 180.1}, {"lon": -181}):
        with pytest.raises(ValidationError):
            landmark(**bad)
    assert landmark(lat=-90, lon=-180).lat == -90


def test_landmark_dates_may_touch() -> None:
    # Finished the moment it was started, and destroyed the moment it was finished.
    item = landmark(built_start=-2550.0, built_end=-2550.0, destroyed=-2550.0)
    assert item.built_start == item.built_end == item.destroyed


def test_snapshot_landmark_adds_a_status() -> None:
    values = landmark().model_dump() | {"status": "standing"}
    item = SnapshotLandmark.model_validate(values)
    assert item.status is LandmarkStatus.STANDING
    assert [s.value for s in LandmarkStatus] == ["under_construction", "standing", "destroyed"]
    with pytest.raises(ValidationError):
        SnapshotLandmark.model_validate(landmark().model_dump())  # status is required


def snapshot(**overrides: Any) -> EarthSnapshot:
    values: dict[str, Any] = {
        "vantage_point": vantage(),
        "moments": MomentRange(1999.0, 2000.0, 2001.0),
        "moments_label": "1999 CE to 2001 CE",
    }
    return EarthSnapshot.model_validate(values | overrides)


def test_snapshot_can_hold_history() -> None:
    item = snapshot(
        events=[event()],
        landmarks=[
            SnapshotLandmark.model_validate(landmark().model_dump() | {"status": "standing"})
        ],
        population=PopulationEstimate(year=2000.0, people=6_100_000_000, source=SOURCE),
        notes=["A narrow span."],
    )
    assert item.earth_exists
    assert EarthSnapshot.model_validate_json(item.model_dump_json()) == item


def test_snapshot_before_earth_must_be_empty() -> None:
    empty = snapshot(earth_exists=False, notes=["Earth does not exist yet."])
    assert not empty.earth_exists
    with pytest.raises(ValidationError, match="before Earth"):
        snapshot(earth_exists=False, events=[event()])
    with pytest.raises(ValidationError, match="before Earth"):
        snapshot(earth_exists=False, population=PopulationEstimate(year=0.0, people=1))


def test_population_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        PopulationEstimate(year=1.0, people=-1)


# --- search --------------------------------------------------------------------------------------


def test_search_result_kind_matches_its_type() -> None:
    star = SearchResult(
        type=SearchType.VANTAGE_POINT, id="vega", name="Vega", kind=VantageKind.STAR
    )
    assert star.kind is VantageKind.STAR
    plain = SearchResult(
        type=SearchType.EVENT, id="fall-of-rome", name="Fall of Rome", description="476 CE"
    )
    assert plain.kind is None
    with pytest.raises(ValidationError, match="exactly when"):
        SearchResult(type=SearchType.VANTAGE_POINT, id="vega", name="Vega")
    with pytest.raises(ValidationError, match="exactly when"):
        SearchResult(type=SearchType.EVENT, id="x", name="X", kind=VantageKind.STAR)


def test_suggestion_similarity_is_between_0_and_1() -> None:
    assert (
        Suggestion(
            type=SearchType.EVENT, id="fall-of-rome", name="Fall of Rome", similarity=0.9
        ).similarity
        == 0.9
    )
    for bad in (-0.1, 1.1):
        with pytest.raises(ValidationError):
            Suggestion(type=SearchType.EVENT, id="x", name="X", similarity=bad)


def test_search_types_are_snake_case_strings() -> None:
    assert [t.value for t in SearchType] == ["vantage_point", "event", "period", "landmark"]


# --- schema snapshot ----------------------------------------------------------------------

PUBLIC_MODELS: dict[str, type[BaseModel]] = {
    "VantagePoint": VantagePoint,
    "MomentResult": MomentResult,
    "EarthSnapshot": EarthSnapshot,
    "SearchResult": SearchResult,
    "Suggestion": Suggestion,
}


def current_schemas() -> dict[str, Any]:
    return {name: TypeAdapter(model).json_schema() for name, model in PUBLIC_MODELS.items()}


def test_json_schemas_match_the_committed_snapshot() -> None:
    """Fails when a model's JSON shape changes. If the change is intended, regenerate with
    ``$env:UPDATE_SNAPSHOTS = "1"; uv run pytest packages/earthlight/tests/test_models.py``
    and review the diff of ``tests/data/models_schema.json``: it is the API contract."""
    schemas = current_schemas()
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SCHEMA_FILE.write_text(
            json.dumps(schemas, indent=1, sort_keys=True) + "\n", "utf-8", newline="\n"
        )
    committed = json.loads(SCHEMA_FILE.read_text("utf-8"))
    assert json.loads(json.dumps(schemas, sort_keys=True)) == committed
