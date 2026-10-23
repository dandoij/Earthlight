"""Turn the curated deep-sky list into Earthlight vantage points.

Pure logic like ``stars.py``: it reads the curated YAML and the SIMBAD files that
``sources.py`` has downloaded, and builds ``VantagePoint`` objects. The rules come from the
findings in ``docs/data-sources.md`` (step 2.6):

* The YAML holds names, kinds, and fame, never a distance. A number comes from SIMBAD
  (a redshift) or from an inline redshift that carries the URL of the paper it came from.
* A redshift becomes a lookback time with the Planck 2018 cosmology. Below redshift 0.01 an
  object's own motion through space is a large part of its redshift, so the build refuses
  to convert it (those objects need a measured distance, which is a later step).
* The range around the best lookback comes from the redshift's own uncertainty, combined
  with a floor for peculiar velocity.
"""

import csv
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import Field, ValidationError, model_validator

from earthlight.lookback import LookbackRange
from earthlight.models import (
    EarthlightModel,
    FactValue,
    Name,
    Slug,
    SourceUrl,
    VantageKind,
    VantagePoint,
)
from earthlight_pipeline.curated_yaml import load_yaml
from earthlight_pipeline.galaxy_distances import (
    COSMICFLOWS,
    GalaxyRecord,
    galaxy_lookback,
    pgc_number,
)
from earthlight_pipeline.parsing import number as _number
from earthlight_pipeline.parsing import positive as _positive
from earthlight_pipeline.parsing import words as _words
from earthlight_pipeline.star_clusters import CLUSTER_TYPES, ClusterRecord, cluster_lookback
from earthlight_pipeline.stars import SearchEntry, constellation_names

SPEED_OF_LIGHT_KM_S = 299_792.458
"""Exact, by the definition of the metre."""

MIN_REDSHIFT = 0.01
"""Below this (about 130 million light-years) redshift is not a usable distance."""

PECULIAR_VELOCITY_KM_S = 300.0
"""A floor for the uncertainty: galaxies typically move a few hundred km/s relative to the
smooth expansion, which shifts their redshift by this much whatever the spectrum says."""

AGE_UNCERTAINTY_FRACTION = 0.020 / 13.787
"""Planck 2018 gives the age of the universe as 13.787 +- 0.020 billion years (Table 2 of
arXiv:1807.06209, TT,TE,EE+lowE+lensing+BAO). Every lookback is widened by this fraction,
because the cosmology itself is uncertain by that much even for a perfectly known redshift.
(Other methods of measuring the expansion rate disagree by more; see docs/data-sources.md.)"""

WORST_ACCEPTED_QUALITY = "D"
"""SIMBAD grades redshifts A (best) to E (worst); E is not accepted."""

DeepSkyKind = Literal["star_cluster", "galaxy", "galaxy_cluster", "quasar", "cosmic_background"]

_KIND_LABELS = {
    "star_cluster": "Star cluster",
    "galaxy": "Galaxy",
    "galaxy_cluster": "Galaxy cluster",
    "quasar": "Quasar",
    "cosmic_background": "Cosmic microwave background",
}


class CuratedError(ValueError):
    """The curated file, or the data needed to build it, has problems. The message lists all."""


# --- the curated file ----------------------------------------------------------------------


class InlineRedshift(EarthlightModel):
    """A redshift typed into the YAML for an object SIMBAD does not hold, with its source."""

    redshift: float = Field(gt=0, strict=True)
    error: float = Field(ge=0, strict=True, description="One standard deviation, in redshift.")
    source: SourceUrl
    ra_deg: float | None = Field(
        default=None, ge=0, lt=360, strict=True, description="Right ascension, J2000/ICRS degrees."
    )
    dec_deg: float | None = Field(
        default=None, ge=-90, le=90, strict=True, description="Declination, J2000/ICRS degrees."
    )

    @model_validator(mode="after")
    def _position_is_complete(self) -> Self:
        if (self.ra_deg is None) != (self.dec_deg is None):
            raise ValueError("give both ra_deg and dec_deg, or neither")
        return self


CATALOGUE_KINDS = {
    "hunt_reffert_2023": "star_cluster",
    "mcconnachie_2012": "galaxy",
    "cosmicflows_4": "galaxy",
}
"""Each distance catalogue and the one kind of object that takes its numbers."""


class CatalogueDistance(EarthlightModel):
    """A distance taken from a catalogue, for objects near enough that redshift is no use."""

    catalogue: Literal["hunt_reffert_2023", "mcconnachie_2012", "cosmicflows_4"]
    name: Name = Field(
        description="The object's name in that catalogue, spelled exactly (Cosmicflows-4: PGC n)."
    )

    @model_validator(mode="after")
    def _cosmicflows_names_are_pgc_numbers(self) -> Self:
        if self.catalogue == COSMICFLOWS and pgc_number(self.name) is None:
            raise ValueError("a Cosmicflows-4 name is a Principal Galaxies Catalogue number: PGC n")
        return self


class CuratedObject(EarthlightModel):
    """One entry of ``curated/deep_sky.yaml``."""

    id: Slug
    name: Name
    kind: DeepSkyKind
    fame: int = Field(ge=1, le=5, strict=True)
    simbad: Name | None = Field(default=None, description="The object's identifier in SIMBAD.")
    inline: InlineRedshift | None = None
    distance: CatalogueDistance | None = None
    wikipedia: Name | None = None
    aliases: tuple[Name, ...] = ()

    @model_validator(mode="after")
    def _one_source_of_numbers(self) -> Self:
        given = [self.simbad is not None, self.inline is not None, self.distance is not None]
        if sum(given) != 1:
            raise ValueError("give exactly one of 'simbad', 'inline', and 'distance'")
        if self.distance is not None:
            wanted = CATALOGUE_KINDS[self.distance.catalogue]
            if self.kind != wanted:
                raise ValueError(f"{self.distance.catalogue} gives distances to a {wanted} only")
        elif self.kind == "star_cluster":
            raise ValueError("a star_cluster takes its numbers from 'distance'")
        return self


def load_curated(path: Path) -> list[CuratedObject]:
    """Read and validate the curated file. Raises CuratedError listing every problem."""
    try:
        data = load_yaml(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:  # broken YAML, or a key repeated inside one entry
        raise CuratedError(f"{path} cannot be read ({error})") from error
    if (
        not isinstance(data, dict)
        or set(data) != {"objects"}
        or not isinstance(data["objects"], list)
    ):
        raise CuratedError(f"{path} must be a mapping with exactly one key, 'objects' (a list)")
    objects: list[CuratedObject] = []
    problems: list[str] = []
    for position, item in enumerate(data["objects"], start=1):
        label = item.get("id", "?") if isinstance(item, dict) else "?"
        try:
            objects.append(CuratedObject.model_validate(item))
        except ValidationError as error:
            details = "; ".join(
                f"{'.'.join(str(part) for part in e['loc']) or 'entry'}: {e['msg']}"
                for e in error.errors()
            )
            problems.append(f"entry {position} ({label}): {details}")
    for field in ("id", "name"):
        counts = Counter(getattr(o, field).lower() for o in objects)
        problems += [f"duplicate {field}: {value}" for value, n in counts.items() if n > 1]
    counts = Counter(_normalize(o.simbad) for o in objects if o.simbad)
    problems += [f"duplicate simbad identifier: {value}" for value, n in counts.items() if n > 1]
    counts = Counter((o.distance.catalogue, o.distance.name) for o in objects if o.distance)
    problems += [
        f"duplicate catalogue name: {name} in {catalogue}"
        for (catalogue, name), n in counts.items()
        if n > 1
    ]
    if problems:
        raise CuratedError("\n".join(problems))
    return objects


# --- SIMBAD --------------------------------------------------------------------------------


def _normalize(identifier: str) -> str:
    """An identifier with runs of spaces collapsed and lower-cased, for matching.

    SIMBAD pads some catalogue numbers with extra spaces ("M  31", "NGC  1300").
    """
    return _words(identifier).lower()


_CATALOGUE_PREFIX = re.compile(r"^([A-Za-z0-9+\-\[\]]+) (\S.*)$")


def identifier_variants(identifier: str) -> list[str]:
    """The spellings of ``identifier`` to ask SIMBAD about.

    "NAME ..." identifiers are exact. Others (such as "ACO 1656") may be stored with one to
    three spaces between the catalogue and the number, so all three are asked for.
    """
    identifier = _words(identifier)
    match = _CATALOGUE_PREFIX.match(identifier)
    if match is None or identifier.startswith("NAME "):
        return [identifier]
    return [f"{match.group(1)}{' ' * spaces}{match.group(2)}" for spaces in (1, 2, 3)]


@dataclass(frozen=True)
class SimbadRecord:
    """The SIMBAD row for one identifier. Missing values are None."""

    asked: str
    main_id: str
    object_type: str
    ra_deg: float | None
    dec_deg: float | None
    redshift_text: str
    redshift_error: float | None
    redshift_type: str
    quality: str
    bibcode: str


def read_simbad(paths: Iterable[Path]) -> dict[str, SimbadRecord]:
    """SIMBAD rows by normalized identifier, from the downloaded files."""
    records: dict[str, SimbadRecord] = {}
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                asked = _words(row["asked"])
                if not asked:
                    continue
                records[_normalize(asked)] = SimbadRecord(
                    asked=asked,
                    main_id=_words(row["main_id"]),
                    object_type=_words(row["otype"]),
                    ra_deg=_number(row["ra"]),
                    dec_deg=_number(row["dec"]),
                    redshift_text=_words(row["rvz_redshift"]),
                    redshift_error=_positive(row["rvz_err"]),
                    redshift_type=_words(row["rvz_type"]),
                    quality=_words(row["rvz_qual"]),
                    bibcode=_words(row["rvz_bibcode"]),
                )
    return records


def find_record(simbad_records: Mapping[str, SimbadRecord], identifier: str) -> SimbadRecord | None:
    """The row for ``identifier`` however SIMBAD pads it."""
    return simbad_records.get(_normalize(identifier))


# --- redshift to lookback ------------------------------------------------------------------


def redshift_uncertainty(record: SimbadRecord) -> float:
    """One standard deviation of the redshift, in redshift units.

    From the error SIMBAD gives (in redshift for type "z", in km/s otherwise); where there is
    none, half a unit of the last printed digit, because the value was rounded to that digit.
    The peculiar velocity floor is added in quadrature.
    """
    if record.redshift_error is not None:
        error = (
            record.redshift_error
            if record.redshift_type == "z"
            else record.redshift_error / SPEED_OF_LIGHT_KM_S
        )
    else:
        try:
            exponent = Decimal(record.redshift_text).as_tuple().exponent
        except InvalidOperation:
            exponent = 0
        error = 0.5 * 10.0 ** (exponent if isinstance(exponent, int) else 0)
    return combined_uncertainty(error)


def combined_uncertainty(error: float) -> float:
    """``error`` combined in quadrature with the peculiar velocity floor."""
    return math.hypot(error, PECULIAR_VELOCITY_KM_S / SPEED_OF_LIGHT_KM_S)


def lookback_years(redshift: float) -> float:
    """Years of light travel time to redshift ``redshift``, in the Planck 2018 cosmology."""
    from astropy.cosmology import Planck18

    # astropy's type stubs declare Planck18 as a bare Cosmology, which has no lookback_time.
    return float(Planck18.lookback_time(redshift).to_value("yr"))  # pyright: ignore[reportAttributeAccessIssue]


def lookback_from_redshift(redshift: float, sigma: float) -> LookbackRange:
    """The lookback for ``redshift``, with the range for plus and minus ``sigma``.

    The range is then widened on both sides by the uncertainty of the cosmology, so it never
    has zero width (the lookback to the cosmic microwave background hardly depends on its
    redshift).
    """
    best = lookback_years(redshift)
    return LookbackRange(
        lookback_years(max(redshift - sigma, 0.0)) * (1 - AGE_UNCERTAINTY_FRACTION),
        best,
        lookback_years(redshift + sigma) * (1 + AGE_UNCERTAINTY_FRACTION),
    )


# --- building ------------------------------------------------------------------------------


@dataclass(frozen=True)
class DeepSkyRecord:
    """A built object and its search entry."""

    point: VantagePoint
    search: SearchEntry


@dataclass
class DeepSkyBuild:
    """The result of building the deep-sky list."""

    records: list[DeepSkyRecord]
    sources: Counter[str]


def simbad_identifiers(objects: Iterable[CuratedObject]) -> list[str]:
    """Every spelling to ask SIMBAD about, for the objects that take their numbers from it."""
    return [v for o in objects if o.simbad for v in identifier_variants(o.simbad)]


def catalogue_names(objects: Iterable[CuratedObject], catalogue: str) -> list[str]:
    """The names to ask ``catalogue`` for, for the objects that take their distance from it."""
    return [o.distance.name for o in objects if o.distance and o.distance.catalogue == catalogue]


def cluster_names(objects: Iterable[CuratedObject]) -> list[str]:
    """The Hunt and Reffert names to ask for, for the objects that take their distance from it."""
    return catalogue_names(objects, "hunt_reffert_2023")


def cosmicflows_numbers(objects: Iterable[CuratedObject]) -> list[int]:
    """The PGC numbers to ask Cosmicflows-4 for."""
    return [
        number
        for name in catalogue_names(objects, COSMICFLOWS)
        if (number := pgc_number(name)) is not None
    ]


_PARENTHESIS = re.compile(r"(?P<base>.+?) \((?P<inner>.+)\)")
_MESSIER_SHORT = re.compile(r"M(?P<number>\d+)")


def search_aliases(item: CuratedObject, extra: Iterable[str] = ()) -> str:
    """The other names a person might type for ``item``, one per line.

    These are the names written in the YAML, any ``extra`` names, and names read off the
    display name: ``Andromeda Galaxy (Messier 31)`` is also found as ``Andromeda Galaxy`` and as
    ``Messier 31``, and an alias ``M31`` also gives ``Messier 31``. Each name appears once,
    ignoring case, and the display name itself is not repeated.
    """
    names = [*item.aliases, *extra]
    if match := _PARENTHESIS.fullmatch(item.name):
        names += [match["base"], match["inner"]]
    for name in list(names):
        if short := _MESSIER_SHORT.fullmatch(name):
            names.append(f"Messier {short['number']}")
    seen = {item.name.casefold()}
    kept: list[str] = []
    for name in names:
        if name.casefold() not in seen:
            seen.add(name.casefold())
            kept.append(name)
    return "\n".join(kept)


def build_deep_sky(
    objects: Iterable[CuratedObject],
    simbad_records: Mapping[str, SimbadRecord],
    cluster_records: Mapping[str, ClusterRecord] | None = None,
    galaxy_records: Mapping[tuple[str, str], GalaxyRecord] | None = None,
) -> DeepSkyBuild:
    """Build a vantage point for every curated object.

    Objects with a redshift take it from ``simbad_records`` or their inline value; star
    clusters take a distance from ``cluster_records`` and nearby galaxies one from
    ``galaxy_records`` (keyed by catalogue and name). Raises CuratedError listing every
    object that cannot be built, so the list is fixed in one pass instead of one failure at
    a time. The records come back in the order of ``objects``.
    """
    objects = list(objects)
    ordered_ids = [o.id for o in objects]
    clusters = [o for o in objects if o.distance and o.distance.catalogue == "hunt_reffert_2023"]
    galaxies = [o for o in objects if o.distance and o.distance.catalogue != "hunt_reffert_2023"]
    cluster_result = _build_clusters(clusters, cluster_records or {})
    galaxy_result = _build_catalogue_galaxies(galaxies, galaxy_records or {})
    objects = [o for o in objects if o.distance is None]
    problems: list[str] = [*cluster_result.problems, *galaxy_result.problems]
    resolved: list[tuple[CuratedObject, float, float, str, SimbadRecord | None]] = []
    for item in objects:
        if item.inline is not None:
            resolved.append(
                (
                    item,
                    item.inline.redshift,
                    combined_uncertainty(item.inline.error),
                    item.inline.source,
                    None,
                )
            )
            continue
        assert item.simbad is not None  # guaranteed by the model
        record = find_record(simbad_records, item.simbad)
        if record is None:
            problems.append(f"{item.id}: SIMBAD has no object '{item.simbad}'")
            continue
        redshift = _number(record.redshift_text)
        if redshift is None:
            problems.append(f"{item.id}: SIMBAD has no redshift for '{record.main_id}'")
        elif redshift < MIN_REDSHIFT:
            problems.append(
                f"{item.id}: redshift {redshift:g} is below {MIN_REDSHIFT}; "
                "it needs a measured distance instead"
            )
        elif not record.quality or record.quality > WORST_ACCEPTED_QUALITY:
            problems.append(
                f"{item.id}: SIMBAD grades the redshift of '{record.main_id}' "
                f"'{record.quality or 'none'}', which is not accepted"
            )
        else:
            source = record.bibcode or "SIMBAD"
            resolved.append((item, redshift, redshift_uncertainty(record), source, record))
    if problems:
        raise CuratedError("\n".join(problems))

    positions = [
        (r.ra_deg, r.dec_deg)
        if r
        else (item.inline.ra_deg, item.inline.dec_deg)
        if item.inline
        else (None, None)
        for item, *_, r in resolved
    ]
    with_position = [(ra, dec) for ra, dec in positions if ra is not None and dec is not None]
    names = iter(
        constellation_names([ra for ra, _ in with_position], [dec for _, dec in with_position])
    )

    records: list[DeepSkyRecord] = []
    sources: Counter[str] = Counter()
    for (item, redshift, sigma, source, record), (ra, dec) in zip(resolved, positions, strict=True):
        constellation = next(names) if ra is not None and dec is not None else None
        sources["simbad" if record else "inline"] += 1
        shown = round(redshift, 6)
        facts: dict[str, FactValue] = {
            "redshift": shown,
            "redshift_uncertainty": float(f"{sigma:.3g}"),
            "redshift_source": source,
            "cosmology": "Planck18",
        }
        if record is not None:
            facts["simbad_id"] = record.main_id
            facts["simbad_type"] = record.object_type
        point = VantagePoint(
            id=item.id,
            name=item.name,
            kind=VantageKind(item.kind),
            lookback=lookback_from_redshift(redshift, sigma),
            constellation=constellation,
            ra_deg=ra,
            dec_deg=dec,
            fame=item.fame,
            wikipedia=item.wikipedia,
            facts=facts,
        )
        search = SearchEntry(
            type="vantage_point",
            id=item.id,
            name=item.name,
            aliases=search_aliases(item, [record.main_id] if record else []),
            description=f"{_KIND_LABELS[item.kind]}, redshift {shown:g}",
        )
        records.append(DeepSkyRecord(point, search))
    by_id = {
        record.point.id: record
        for record in [*records, *cluster_result.records, *galaxy_result.records]
    }
    sources.update(cluster_result.sources)
    sources.update(galaxy_result.sources)
    return DeepSkyBuild([by_id[object_id] for object_id in ordered_ids], sources)


@dataclass
class _CatalogueBuild:
    problems: list[str]
    records: list[DeepSkyRecord]
    sources: Counter[str]


def _light_years_text(light_years: float) -> str:
    """A distance for people, to three significant figures: "441 light-years"."""
    rounded = float(f"{light_years:.3g}")
    if rounded >= 1e6:
        return f"{rounded / 1e6:g} million light-years"
    return f"{rounded:,.0f} light-years"


def _build_clusters(
    clusters: list[CuratedObject], cluster_records: Mapping[str, ClusterRecord]
) -> _CatalogueBuild:
    """Build the star clusters, which take a distance from the Hunt and Reffert catalogue."""
    problems: list[str] = []
    found: list[tuple[CuratedObject, ClusterRecord, LookbackRange]] = []
    for item in clusters:
        assert item.distance is not None  # guaranteed by the model
        record = cluster_records.get(item.distance.name)
        if record is None:
            problems.append(f"{item.id}: Hunt and Reffert has no cluster '{item.distance.name}'")
        elif record.cluster_type not in CLUSTER_TYPES:
            problems.append(
                f"{item.id}: '{record.name}' is type '{record.cluster_type}', "
                f"not one of {', '.join(CLUSTER_TYPES)}"
            )
        elif record.ra_deg is None or record.dec_deg is None:
            problems.append(f"{item.id}: Hunt and Reffert has no position for '{record.name}'")
        else:
            try:
                found.append((item, record, cluster_lookback(record)))
            except ValueError as error:
                problems.append(f"{item.id}: {error}")
    names = iter(
        constellation_names(
            [record.ra_deg for _, record, _ in found if record.ra_deg is not None],
            [record.dec_deg for _, record, _ in found if record.dec_deg is not None],
        )
    )
    records: list[DeepSkyRecord] = []
    for item, record, lookback in found:
        kind = CLUSTER_TYPES[record.cluster_type]
        facts: dict[str, FactValue] = {
            "distance_pc": round(record.dist50_pc or 0.0, 2),
            "distance_light_years": float(f"{lookback.best:.4g}"),
            "distance_source": "hunt_reffert_2023",
            "catalogue_name": record.name,
            "cluster_type": kind,
        }
        if record.member_stars is not None:
            facts["member_stars"] = record.member_stars
        point = VantagePoint(
            id=item.id,
            name=item.name,
            kind=VantageKind.STAR_CLUSTER,
            lookback=lookback,
            constellation=next(names),
            ra_deg=record.ra_deg,
            dec_deg=record.dec_deg,
            fame=item.fame,
            wikipedia=item.wikipedia,
            facts=facts,
        )
        search = SearchEntry(
            type="vantage_point",
            id=item.id,
            name=item.name,
            aliases=search_aliases(item),
            description=f"{kind.capitalize()} cluster, {_light_years_text(lookback.best)}",
        )
        records.append(DeepSkyRecord(point, search))
    sources: Counter[str] = Counter({"hunt_reffert_2023": len(records)} if records else {})
    return _CatalogueBuild(problems, records, sources)


_SOURCE_LABELS = {
    "mcconnachie_2012": "McConnachie 2012",
    COSMICFLOWS: "Cosmicflows-4",
}


def _build_catalogue_galaxies(
    galaxies: list[CuratedObject], records: Mapping[tuple[str, str], GalaxyRecord]
) -> _CatalogueBuild:
    """Build the nearby galaxies, which take a distance modulus from McConnachie or Cosmicflows."""
    problems: list[str] = []
    found: list[tuple[CuratedObject, GalaxyRecord, LookbackRange]] = []
    for item in galaxies:
        assert item.distance is not None  # guaranteed by the model
        label = _SOURCE_LABELS[item.distance.catalogue]
        record = records.get((item.distance.catalogue, item.distance.name))
        if record is None:
            problems.append(f"{item.id}: {label} has no galaxy '{item.distance.name}'")
        elif record.ra_deg is None or record.dec_deg is None:
            problems.append(f"{item.id}: {label} has no position for '{record.name}'")
        else:
            try:
                found.append((item, record, galaxy_lookback(record)))
            except ValueError as error:
                problems.append(f"{item.id}: {error}")
    names = iter(
        constellation_names(
            [record.ra_deg for _, record, _ in found if record.ra_deg is not None],
            [record.dec_deg for _, record, _ in found if record.dec_deg is not None],
        )
    )
    built: list[DeepSkyRecord] = []
    sources: Counter[str] = Counter()
    for item, record, lookback in found:
        assert item.distance is not None and record.modulus is not None
        sources[item.distance.catalogue] += 1
        facts: dict[str, FactValue] = {
            "distance_modulus": record.modulus,
            "distance_modulus_error_plus": record.error_plus,
            "distance_modulus_error_minus": record.error_minus,
            "distance_light_years": float(f"{lookback.best:.4g}"),
            "distance_source": item.distance.catalogue,
            "catalogue_name": record.name,
        }
        point = VantagePoint(
            id=item.id,
            name=item.name,
            kind=VantageKind(item.kind),
            lookback=lookback,
            constellation=next(names),
            ra_deg=record.ra_deg,
            dec_deg=record.dec_deg,
            fame=item.fame,
            wikipedia=item.wikipedia,
            facts=facts,
        )
        search = SearchEntry(
            type="vantage_point",
            id=item.id,
            name=item.name,
            aliases=search_aliases(item),
            description=f"{_KIND_LABELS[item.kind]}, {_light_years_text(lookback.best)}",
        )
        built.append(DeepSkyRecord(point, search))
    return _CatalogueBuild(problems, built, sources)
