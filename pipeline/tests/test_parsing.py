"""Tests for the forgiving value readers, and for every file reader surviving damaged rows."""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from earthlight_pipeline.exoplanets import read_archive, read_host_distances
from earthlight_pipeline.parsing import integer, number, positive, prefixed_integer
from earthlight_pipeline.stars import read_gaia_matches, read_hipparcos


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.5", 1.5),
        ("  -2.25  ", -2.25),
        ("1E3", 1000.0),
        ("9.1185E-4", 9.1185e-4),
        ("0", 0.0),
        (None, None),
        ("", None),
        ("   ", None),
        ("abc", None),
        ("1,5", None),
        ("inf", None),
        ("-inf", None),
        ("nan", None),
        ("1e999", None),  # overflows to infinity
    ],
)
def test_number(text: str | None, expected: float | None) -> None:
    assert number(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2.5", 2.5),
        ("0", None),
        ("-1", None),
        ("0.0", None),
        (None, None),
        ("x", None),
        ("inf", None),
    ],
)
def test_positive(text: str | None, expected: float | None) -> None:
    assert positive(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12", 12),
        (" 7 ", 7),
        ("007", 7),
        ("4616474464582858368", 4616474464582858368),  # larger than a float holds exactly
        (None, None),
        ("", None),
        ("-3", None),
        ("1.0", None),
        ("12abc", None),
        ("١٢", None),  # Arabic-Indic digits are not accepted
        (chr(0xFF11) + chr(0xFF12), None),  # nor are fullwidth digits
        ("²", None),  # nor superscripts, which str.isdigit() would allow
    ],
)
def test_integer(text: str | None, expected: int | None) -> None:
    assert integer(text) == expected


@pytest.mark.parametrize(
    ("text", "prefix", "expected"),
    [
        ("Gaia DR3 123", "Gaia DR3 ", 123),
        ("  HIP 70890 ", "HIP ", 70890),
        ("Gaia DR2 123", "Gaia DR3 ", None),
        ("HIP", "HIP ", None),
        ("HIP x", "HIP ", None),
        ("", "HIP ", None),
        (None, "HIP ", None),
    ],
)
def test_prefixed_integer(text: str | None, prefix: str, expected: int | None) -> None:
    assert prefixed_integer(text, prefix) == expected


@given(st.text())
def test_the_readers_never_raise_on_any_text(text: str) -> None:
    for read in (number, positive, integer):
        result = read(text)
        assert result is None or isinstance(result, int | float)
    found = prefixed_integer(text, "HIP ")
    assert found is None or found >= 0


# --- damaged files ---------------------------------------------------------------------------


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_a_row_shorter_than_the_header_does_not_crash_any_reader(tmp_path: Path) -> None:
    # The csv module gives None for cells a short row does not have.
    main = write(tmp_path / "main.csv", "HIP,Vmag,RAICRS,DEICRS,SpType,HD\n1,5.0,10.0\n2\n")
    plx = write(tmp_path / "plx.csv", "HIP,Plx,e_Plx\n1,3.0\n2\n")
    stars = {s.hip: s for s in read_hipparcos(main, plx)}
    assert stars[1].vmag == 5.0 and stars[1].dec_deg is None and stars[1].hd is None
    assert stars[1].parallax_mas == 3.0 and stars[1].parallax_error_mas is None
    assert stars[2].vmag is None

    gaia = write(
        tmp_path / "gaia.csv",
        "hip,source_id,parallax,parallax_error,phot_g_mean_mag,r_med_geo,r_lo_geo,r_hi_geo\n"
        "1,100,1.0\n2,200\n3\n",
    )
    matches = read_gaia_matches([gaia])
    assert matches[1].parallax_mas == 1.0 and matches[1].geo_distance_pc is None
    assert matches[2].parallax_mas is None
    assert 3 not in matches  # no source id at all

    hosts = write(
        tmp_path / "hosts.csv", "source_id,r_lo_geo,r_med_geo,r_hi_geo\n1,1,2\n2,1,2,3\n3\n"
    )
    assert read_host_distances([hosts]) == {2: (1.0, 2.0, 3.0)}

    header = (
        "pl_name,hostname,pl_controv_flag,sy_dist,sy_disterr1,sy_disterr2,sy_vmag,ra,dec,"
        "gaia_dr3_id,hip_name,disc_year,discoverymethod,sy_pnum,pl_rade,pl_bmasse,pl_orbper\n"
    )
    archive = write(tmp_path / "ps.csv", header + "Short b,Short,1,5.0\nHalf b,Half\nGone b\n")
    planets = {p.name: p for p in read_archive(archive)}
    assert planets["Short b"].distance_pc == 5.0 and planets["Short b"].controversial is True
    assert planets["Short b"].error_upper_pc is None and planets["Short b"].gaia_host_id is None
    assert planets["Half b"].distance_pc is None
    assert "Gone b" not in planets  # no host name
