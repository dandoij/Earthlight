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
from earthlight_pipeline.parsing import number as _number
from earthlight_pipeline.parsing import positive as _positive
from earthlight_pipeline.parsing import words as _words
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

DeepSkyKind = Literal["galaxy", "galaxy_cluster", "quasar", "cosmic_background"]

_KIND_LABELS = {
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


class CuratedObject(EarthlightModel):
    """One entry of ``curated/deep_sky.yaml``."""

    id: Slug
    name: Name
    kind: DeepSkyKind
    fame: int = Field(ge=1, le=5, strict=True)
    simbad: Name | None = Field(default=None, description="The object's identifier in SIMBAD.")
    inline: InlineRedshift | None = None
    wikipedia: Name | None = None
    aliases: tuple[Name, ...] = ()

    @model_validator(mode="after")
    def _one_source_of_numbers(self) -> Self:
        if (self.simbad is None) == (self.inline is None):
            raise ValueError("give exactly one of 'simbad' and 'inline'")
        return self


def load_curated(path: Path) -> list[CuratedObject]:
    """Read and validate the curated file. Raises CuratedError listing every problem."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
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


def build_deep_sky(
    objects: Iterable[CuratedObject], simbad_records: Mapping[str, SimbadRecord]
) -> DeepSkyBuild:
    """Build a vantage point for every curated object.

    Raises CuratedError listing every object that cannot be built, so the list is fixed in
    one pass instead of one failure at a time.
    """
    objects = list(objects)
    problems: list[str] = []
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

    positions = [(r.ra_deg, r.dec_deg) if r else (None, None) for *_, r in resolved]
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
        aliases = [*item.aliases, *([record.main_id] if record else [])]
        search = SearchEntry(
            type="vantage_point",
            id=item.id,
            name=item.name,
            aliases="\n".join(dict.fromkeys(aliases)),
            description=f"{_KIND_LABELS[item.kind]}, redshift {shown:g}",
        )
        records.append(DeepSkyRecord(point, search))
    return DeepSkyBuild(records, sources)
