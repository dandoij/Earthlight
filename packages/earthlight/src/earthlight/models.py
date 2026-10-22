"""The data shapes shared by the engine, the CLI, the API, and the web app.

Every model is immutable (fields cannot be reassigned, collections are tuples or
read-only mappings), rejects unknown fields, and refuses infinite or NaN numbers, so a
value that exists is a value that is valid. Field names are the JSON keys
(snake_case), and ``model_json_schema()`` of these models is the contract that the
API publishes and the web app generates its TypeScript types from.

Years are decimal astronomical years (see ``earthlight.time``); lookbacks and
uncertainties are in years.
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from earthlight.lookback import LookbackRange, MomentRange
from earthlight.time import DecimalYear

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)]
"""A stable id: lowercase letters and digits joined by single hyphens, like ``proxima-cen-b``."""

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
SourceUrl = Annotated[str, StringConstraints(pattern=r"^https?://\S+$", max_length=500)]

FactValue = str | int | float | bool | None
"""A value in a free-form ``facts`` table. Only plain JSON scalars are allowed."""


class EarthlightModel(BaseModel):
    """Base class: immutable, strict about unknown fields, and no infinity or NaN."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


# --- vantage points -----------------------------------------------------------------------


class VantageKind(StrEnum):
    """What a vantage point is. The values are part of the JSON contract."""

    PLANET = "planet"
    SPACECRAFT = "spacecraft"
    ZONE = "zone"
    STAR = "star"
    EXOPLANET = "exoplanet"
    STAR_CLUSTER = "star_cluster"
    GALAXY = "galaxy"
    GALAXY_CLUSTER = "galaxy_cluster"
    QUASAR = "quasar"
    COSMIC_BACKGROUND = "cosmic_background"


class VantagePoint(EarthlightModel):
    """A place you can stand on and look back at Earth from."""

    id: Slug
    name: Name
    kind: VantageKind
    lookback: LookbackRange = Field(
        description="Years of lookback: light from Earth that left this long ago is arriving here."
    )
    magnitude: float | None = Field(
        default=None,
        description="Apparent visual magnitude as seen from Earth (smaller is brighter).",
    )
    constellation: Name | None = Field(
        default=None, description="Full constellation name, for objects with a sky position."
    )
    ra_deg: float | None = Field(
        default=None,
        ge=0,
        lt=360,
        description="Right ascension in degrees (equatorial, about J2000). Set with dec_deg.",
    )
    dec_deg: float | None = Field(
        default=None,
        ge=-90,
        le=90,
        description="Declination in degrees (equatorial, about J2000). Set with ra_deg.",
    )
    fame: int = Field(
        default=0,
        ge=0,
        le=5,
        description="How well known the object is: 0 means not curated, 5 means a household name.",
    )
    host_id: Slug | None = Field(
        default=None, description="For an exoplanet, the id of its host star's vantage point."
    )
    wikipedia: Name | None = Field(
        default=None, description="Wikipedia article title, used to fetch an image."
    )
    facts: Mapping[str, FactValue] = Field(
        default_factory=dict, description="Extra facts shown on the object's page."
    )

    @field_validator("facts", mode="after")
    @classmethod
    def _freeze_facts(cls, value: Mapping[str, FactValue]) -> Mapping[str, FactValue]:
        return MappingProxyType(dict(value))

    @field_serializer("facts")
    def _facts_as_a_plain_object(self, value: Mapping[str, FactValue]) -> dict[str, FactValue]:
        return dict(value)

    @model_validator(mode="after")
    def _sky_position_is_complete(self) -> Self:
        if (self.ra_deg is None) != (self.dec_deg is None):
            raise ValueError("ra_deg and dec_deg must be given together")
        return self

    @model_validator(mode="after")
    def _host_only_for_exoplanets(self) -> Self:
        if self.host_id is not None:
            if self.kind is not VantageKind.EXOPLANET:
                raise ValueError("only an exoplanet can have a host_id")
            if self.host_id == self.id:
                raise ValueError("an exoplanet cannot be its own host")
        return self


# --- moment to place --------------------------------------------------------------------------


class ZoneInfo(EarthlightModel):
    """The zone of space that light from the chosen moment is crossing right now."""

    id: Slug
    name: Name
    description: Text
    inner_au: float = Field(ge=0, description="Distance from the Sun to the zone's inner edge.")
    outer_au: float = Field(gt=0, description="Distance from the Sun to the zone's outer edge.")
    lookback: LookbackRange
    percent_to_proxima: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Progress of the light towards Proxima Centauri, when that is meaningful.",
    )

    @model_validator(mode="after")
    def _edges_are_ordered(self) -> Self:
        if self.inner_au >= self.outer_au:
            raise ValueError("a zone's inner edge must be nearer than its outer edge")
        return self


class Match(EarthlightModel):
    """A vantage point picked for a result, with how well it fits the chosen moment."""

    vantage_point: VantagePoint
    offset_years: float = Field(
        description="Best lookback estimate minus the chosen lookback. Negative means nearer."
    )
    approximate: bool = Field(
        default=False,
        description="True when no place's range contains the moment, so this is the best place "
        "whose range comes close (within 5%) and the match is only approximate.",
    )

    @property
    def range_width_years(self) -> float:
        """Width of the vantage point's lookback range: smaller means more precise.

        Deliberately not a serialized field, so that the JSON this model writes can be
        read back by the same model."""
        return self.vantage_point.lookback.maximum - self.vantage_point.lookback.minimum


class MomentResult(EarthlightModel):
    """The answer to "where is the light from this moment arriving right now?"."""

    moment: DecimalYear
    moment_label: Name = Field(description='The moment for people, such as "1492 CE".')
    lookback_years: float = Field(ge=0, description="Years between the moment and now.")
    zone: ZoneInfo | None = Field(
        default=None, description="Set when the light is still inside or near the solar system."
    )
    famous: Match | None = None
    exoplanet: Match | None = None
    visible_tonight: Match | None = None
    most_precise: Match | None = None
    notes: tuple[str, ...] = Field(
        default=(), description="Plain-language remarks, such as why a category is empty."
    )


# --- place to moment ---------------------------------------------------------------------------


class _HistoryEntry(EarthlightModel):
    """Fields shared by events, periods, and landmarks."""

    id: Slug
    name: Name
    category: Name
    region: Name
    summary: Text
    importance: int = Field(ge=1, le=5)
    wikipedia: Name | None = None
    source: SourceUrl


class HistoryEvent(_HistoryEntry):
    """Something that happened at a point in time."""

    year: DecimalYear
    year_uncertainty: float = Field(default=0.0, ge=0, description="Plus or minus, in years.")


class HistoryPeriod(_HistoryEntry):
    """An age, era, or dynasty that lasted for a span of time."""

    start: DecimalYear
    end: DecimalYear | None = Field(
        default=None, description="When the period ended. Missing exactly when it is ongoing."
    )
    ongoing: bool = Field(
        default=False,
        description="True for a period that has not ended yet, such as the Holocene.",
    )

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.ongoing != (self.end is None):
            raise ValueError("a period has an end year exactly when it is not ongoing")
        if self.end is not None and self.start > self.end:
            raise ValueError("a period cannot end before it starts")
        return self


class Landmark(_HistoryEntry):
    """A structure or place with a building and (maybe) a destruction date."""

    built_start: DecimalYear
    built_end: DecimalYear
    destroyed: DecimalYear | None = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.built_start > self.built_end:
            raise ValueError("a landmark cannot be finished before it is started")
        if self.destroyed is not None and self.destroyed < self.built_end:
            raise ValueError("a landmark cannot be destroyed before it is finished")
        return self


class LandmarkStatus(StrEnum):
    """Where a landmark stood in its life during the viewed span (never built yet is omitted)."""

    UNDER_CONSTRUCTION = "under_construction"
    STANDING = "standing"
    DESTROYED = "destroyed"


class SnapshotLandmark(Landmark):
    """A landmark together with its status during the viewed span."""

    status: LandmarkStatus

    @model_validator(mode="after")
    def _destroyed_needs_a_date(self) -> Self:
        if self.status is LandmarkStatus.DESTROYED and self.destroyed is None:
            raise ValueError("a destroyed landmark needs a destruction date")
        return self


class PopulationEstimate(EarthlightModel):
    """A world population estimate."""

    year: DecimalYear
    people: int = Field(ge=0)
    source: SourceUrl | None = None


class EarthSnapshot(EarthlightModel):
    """The answer to "what does Earth look like in the light arriving at this place?"."""

    vantage_point: VantagePoint
    moments: MomentRange = Field(description="The span of Earth's history whose light is arriving.")
    moments_label: Name = Field(description='The span for people, such as "1960 CE to 1980 CE".')
    earth_exists: bool = Field(
        default=True, description="False when the light is older than Earth itself."
    )
    events: tuple[HistoryEvent, ...] = ()
    periods: tuple[HistoryPeriod, ...] = ()
    landmarks: tuple[SnapshotLandmark, ...] = ()
    event_total: int = Field(
        default=0, ge=0, description="How many events fell in the span (more than are listed)."
    )
    period_total: int = Field(default=0, ge=0, description="How many periods overlapped the span.")
    landmark_total: int = Field(
        default=0, ge=0, description="How many landmarks were begun by the middle of the span."
    )
    wide_span: bool = Field(
        default=False,
        description="True when the span of Earth's history is very wide (over 1,000 years).",
    )
    population: PopulationEstimate | None = None
    notes: tuple[str, ...] = Field(
        default=(), description="Plain-language remarks, such as a very wide span."
    )

    @model_validator(mode="after")
    def _totals_cover_the_lists(self) -> Self:
        for listed, total, name in (
            (self.events, self.event_total, "event_total"),
            (self.periods, self.period_total, "period_total"),
            (self.landmarks, self.landmark_total, "landmark_total"),
        ):
            if total < len(listed):
                raise ValueError(f"{name} cannot be smaller than the number listed")
        return self

    @model_validator(mode="after")
    def _nothing_before_earth(self) -> Self:
        has_content = bool(self.events or self.periods or self.landmarks or self.population)
        if not self.earth_exists and has_content:
            raise ValueError("a snapshot before Earth existed cannot have history in it")
        return self


# --- search ---------------------------------------------------------------------------------


class SearchType(StrEnum):
    """What kind of thing a search result or suggestion points at."""

    VANTAGE_POINT = "vantage_point"
    EVENT = "event"
    PERIOD = "period"
    LANDMARK = "landmark"


class SearchResult(EarthlightModel):
    """One hit from a search. Results are ordered best first."""

    type: SearchType
    id: Slug
    name: Name
    kind: VantageKind | None = Field(
        default=None, description="Set for vantage points only: what kind of object it is."
    )
    description: Text | None = Field(default=None, description="A short line to tell hits apart.")

    @model_validator(mode="after")
    def _kind_only_for_vantage_points(self) -> Self:
        if (self.kind is not None) != (self.type is SearchType.VANTAGE_POINT):
            raise ValueError("kind is set exactly when type is vantage_point")
        return self


class Suggestion(EarthlightModel):
    """A did-you-mean guess for text that matched nothing."""

    type: SearchType
    id: Slug
    name: Name
    similarity: float = Field(ge=0, le=1, description="1 means identical text.")


class SearchResponse(EarthlightModel):
    """The answer to a search: hits best first, or guesses when nothing matched."""

    query: str = Field(description="The text that was searched for, with spaces tidied up.")
    results: tuple[SearchResult, ...] = ()
    suggestions: tuple[Suggestion, ...] = Field(
        default=(),
        description="Did-you-mean guesses, best first. Only given when results is empty.",
    )


# --- place details ----------------------------------------------------------------------------


class ExoplanetDetails(EarthlightModel):
    """What the NASA Exoplanet Archive says about a planet, beyond where it is."""

    nasa_name: Name
    host_name: Name
    discovery_year: int | None = None
    discovery_method: Name | None = None
    radius_earth: float | None = Field(
        default=None, gt=0, description="Radius in Earth radii, when measured."
    )
    mass_earth: float | None = Field(
        default=None, gt=0, description="Mass in Earth masses (sometimes a minimum mass)."
    )
    orbital_period_days: float | None = Field(default=None, gt=0)
    controversial: bool = Field(
        default=False, description="True when the archive flags the planet as disputed."
    )


class PlaceInfo(EarthlightModel):
    """Everything known about one place: the place itself and how it connects to others."""

    vantage_point: VantagePoint
    exoplanet: ExoplanetDetails | None = Field(
        default=None, description="Set for an exoplanet only."
    )
    planet_ids: tuple[Slug, ...] = Field(
        default=(), description="For a star, the ids of its known planets (ordered by id)."
    )

    @model_validator(mode="after")
    def _details_match_the_kind(self) -> Self:
        is_planet = self.vantage_point.kind is VantageKind.EXOPLANET
        if self.exoplanet is not None and not is_planet:
            raise ValueError("exoplanet details belong to an exoplanet only")
        if self.planet_ids and self.vantage_point.kind is not VantageKind.STAR:
            raise ValueError("only a star has planet_ids")
        return self
