"""Lookback math: the arithmetic that connects moments, distances, and light.

An object that is L light-years away receives light that left Earth L years ago.
That span is its *lookback* (in years). Every vantage point carries a
``LookbackRange`` (a low, best, and high estimate), and the engine matches moments
to ranges by simple interval arithmetic.

Two directions:

* Moment to place: ``lookback = now - moment``, then find ranges that contain it.
* Place to moment: ``moments = now - [lookback_max, lookback_min]``, then find
  history that overlaps those moments.

Distances are converted with the IAU definitions of the astronomical unit
(IAU 2012 Resolution B2) and the parsec (IAU 2015 Resolution B2), and the
light-year as the distance light travels in one Julian year (365.25 days).
"""

import math
from dataclasses import dataclass

from earthlight.time import DecimalYear, now

ASTRONOMICAL_UNIT_M = 149_597_870_700
"""Metres in one astronomical unit (exact, by IAU 2012 definition)."""

LIGHT_YEAR_M = 9_460_730_472_580_800
"""Metres in one light-year (exact: speed of light times one Julian year)."""

PARSEC_M = 648_000 / math.pi * ASTRONOMICAL_UNIT_M
"""Metres in one parsec (IAU 2015 definition: 648000/pi astronomical units)."""

PARSEC_IN_LIGHT_YEARS = PARSEC_M / LIGHT_YEAR_M
"""About 3.2616 light-years per parsec."""


@dataclass(frozen=True)
class LookbackRange:
    """A lookback in years as a low, best, and high estimate (``minimum <= best <= maximum``).

    Raises ValueError if the values are not finite, are negative, or are out of order.
    """

    minimum: float
    best: float
    maximum: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in (self.minimum, self.best, self.maximum)):
            raise ValueError("lookback values must be finite")
        if not 0 <= self.minimum <= self.best <= self.maximum:
            raise ValueError(
                "lookback must satisfy 0 <= minimum <= best <= maximum, got "
                f"{self.minimum}, {self.best}, {self.maximum}"
            )

    def contains(self, lookback: float) -> bool:
        """Return True if ``lookback`` lies inside the range (bounds included)."""
        return self.minimum <= lookback <= self.maximum

    def overlaps(self, low: float, high: float) -> bool:
        """Return True if the range overlaps the lookback interval ``[low, high]``."""
        return intervals_overlap(self.minimum, self.maximum, low, high)

    def to_moments(self, *, now_year: DecimalYear | None = None) -> "MomentRange":
        """The moments whose light this range is receiving (place to moment)."""
        reference = now() if now_year is None else now_year
        return MomentRange(
            earliest=reference - self.maximum,
            best=reference - self.best,
            latest=reference - self.minimum,
        )


@dataclass(frozen=True)
class MomentRange:
    """A span of moments as ``earliest <= best <= latest`` (decimal years).

    Raises ValueError if the values are not finite or are out of order.
    """

    earliest: DecimalYear
    best: DecimalYear
    latest: DecimalYear

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in (self.earliest, self.best, self.latest)):
            raise ValueError("moment values must be finite")
        if not self.earliest <= self.best <= self.latest:
            raise ValueError(
                "moments must satisfy earliest <= best <= latest, got "
                f"{self.earliest}, {self.best}, {self.latest}"
            )

    def overlaps(self, earliest: DecimalYear, latest: DecimalYear) -> bool:
        """Return True if the span overlaps the moment interval ``[earliest, latest]``."""
        return intervals_overlap(self.earliest, self.latest, earliest, latest)

    def to_lookback(self, *, now_year: DecimalYear | None = None) -> LookbackRange:
        """The lookback range that receives this span of moments (moment to place).

        Raises ValueError if part of the span is after ``now_year``, because
        light cannot yet have arrived from the future.
        """
        reference = now() if now_year is None else now_year
        return LookbackRange(
            minimum=reference - self.latest,
            best=reference - self.best,
            maximum=reference - self.earliest,
        )


def lookback_of(moment: DecimalYear, *, now_year: DecimalYear | None = None) -> float:
    """Years between ``moment`` and now. Negative if the moment is in the future."""
    reference = now() if now_year is None else now_year
    return reference - moment


def moment_of(lookback: float, *, now_year: DecimalYear | None = None) -> DecimalYear:
    """The moment that was ``lookback`` years before now (inverse of ``lookback_of``)."""
    reference = now() if now_year is None else now_year
    return reference - lookback


def intervals_overlap(a_low: float, a_high: float, b_low: float, b_high: float) -> bool:
    """Return True if the closed intervals ``[a_low, a_high]`` and ``[b_low, b_high]`` overlap.

    Intervals that only touch at one point do overlap. Raises ValueError if either
    interval is reversed.
    """
    _check_interval(a_low, a_high)
    _check_interval(b_low, b_high)
    return max(a_low, b_low) <= min(a_high, b_high)


def overlap_width(a_low: float, a_high: float, b_low: float, b_high: float) -> float:
    """Return the length shared by two closed intervals, or 0.0 if they do not overlap."""
    _check_interval(a_low, a_high)
    _check_interval(b_low, b_high)
    return max(0.0, min(a_high, b_high) - max(a_low, b_low))


def _check_interval(low: float, high: float) -> None:
    if not low <= high:
        raise ValueError(f"interval is reversed or not a number: [{low}, {high}]")


def parsecs_to_light_years(parsecs: float) -> float:
    """Convert a distance in parsecs to light-years."""
    return parsecs * PARSEC_IN_LIGHT_YEARS


def parallax_to_parsecs(parallax_mas: float) -> float:
    """Distance in parsecs for a parallax in milliarcseconds (1000 mas is 1 parsec).

    Raises ValueError unless the parallax is positive and finite.
    """
    if not (math.isfinite(parallax_mas) and parallax_mas > 0):
        raise ValueError(f"parallax must be positive and finite, got {parallax_mas}")
    return 1000.0 / parallax_mas


def lookback_range_from_parallax(
    parallax_mas: float, parallax_error_mas: float, *, sigmas: float = 1.0
) -> LookbackRange:
    """Convert a parallax measurement to a lookback range by inverting the parallax.

    The best estimate uses the measured parallax. A larger parallax means a nearer
    star, so ``parallax + sigmas * error`` gives the minimum lookback and
    ``parallax - sigmas * error`` gives the maximum.

    Simple inversion is only trustworthy for precise parallaxes. Raises ValueError
    if the parallax is not positive, the error or ``sigmas`` is negative, or the
    low end of the parallax reaches zero (an unbounded distance, so no maximum).
    """
    if not (math.isfinite(parallax_error_mas) and parallax_error_mas >= 0):
        raise ValueError(
            f"parallax error must be finite and not negative, got {parallax_error_mas}"
        )
    if not (math.isfinite(sigmas) and sigmas >= 0):
        raise ValueError(f"sigmas must be finite and not negative, got {sigmas}")

    spread = sigmas * parallax_error_mas
    best = parsecs_to_light_years(parallax_to_parsecs(parallax_mas))
    nearest = parsecs_to_light_years(parallax_to_parsecs(parallax_mas + spread))
    if parallax_mas - spread <= 0:
        raise ValueError("parallax is too uncertain: the distance has no upper limit")
    farthest = parsecs_to_light_years(parallax_to_parsecs(parallax_mas - spread))
    return LookbackRange(minimum=nearest, best=best, maximum=farthest)
