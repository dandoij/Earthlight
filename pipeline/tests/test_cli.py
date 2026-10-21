"""Tests for the earthlight-build command."""

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from earthlight.schema import SCHEMA_VERSION
from earthlight_pipeline import cli
from earthlight_pipeline.build_deep_sky import DeepSkyReport
from earthlight_pipeline.build_exoplanets import ExoplanetsReport
from earthlight_pipeline.build_stars import DEFAULT_MAX_VMAG, StarsReport
from earthlight_pipeline.cache import DEFAULT_CACHE_DIR
from earthlight_pipeline.cli import SOURCES, Source, app

runner = CliRunner()

UNBUILT = [source for source in SOURCES if source.command not in cli.IMPLEMENTED]
Call = tuple[str, dict[str, object]]


def fake_stars_report(database: Path) -> StarsReport:
    return StarsReport(
        hipparcos_total=10,
        built=8,
        by_source={"gaia": 5, "hipparcos": 3},
        skipped={"too_faint": 2},
        searchable=4,
        named=3,
        planet_hosts=2,
        fame_counts={0: 4, 3: 4},
        database=database,
        database_bytes=1_500_000,
    )


def fake_exoplanets_report(database: Path) -> ExoplanetsReport:
    return ExoplanetsReport(
        archive_total=20,
        built=18,
        by_source={"exoplanet_archive": 15, "bailer_jones_host": 3},
        skipped={"no_distance": 2},
        linked=6,
        stars_in_database=8,
        controversial=1,
        database=database,
        database_bytes=2_500_000,
    )


def fake_deep_sky_report(database: Path) -> DeepSkyReport:
    return DeepSkyReport(
        built=52,
        by_kind={"galaxy": 24, "quasar": 14},
        by_source={"simbad": 45, "inline": 7},
        nearest_years=184_000_000.0,
        farthest_years=13_786_000_000.0,
        database=database,
        database_bytes=200_000,
    )


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[Call]:
    """Replace the real builds, which use the network, with recorders."""
    recorded: list[Call] = []

    def fake_run_stars(**kwargs: object) -> StarsReport:
        recorded.append(("stars", kwargs))
        progress = kwargs["progress"]
        assert callable(progress)
        progress("downloading stars...")
        return fake_stars_report(Path(str(kwargs["database"])))

    def fake_run_exoplanets(**kwargs: object) -> ExoplanetsReport:
        recorded.append(("exoplanets", kwargs))
        progress = kwargs["progress"]
        assert callable(progress)
        progress("downloading planets...")
        return fake_exoplanets_report(Path(str(kwargs["database"])))

    def fake_run_deep_sky(**kwargs: object) -> DeepSkyReport:
        recorded.append(("deep-sky", kwargs))
        progress = kwargs["progress"]
        assert callable(progress)
        progress("downloading SIMBAD...")
        return fake_deep_sky_report(Path(str(kwargs["database"])))

    monkeypatch.setattr(cli, "run_deep_sky", fake_run_deep_sky)
    monkeypatch.setattr(cli, "run_stars", fake_run_stars)
    monkeypatch.setattr(cli, "run_exoplanets", fake_run_exoplanets)
    return recorded


def test_help_lists_every_source_and_the_extra_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for source in SOURCES:
        assert source.command in result.output
    assert "all" in result.output
    assert "config" in result.output
    for option in ("--cache-dir", "--refresh", "--database"):
        assert option in result.output


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "Usage" in result.output


def test_sources_are_unique_and_match_the_plan() -> None:
    commands = [s.command for s in SOURCES]
    assert len(set(commands)) == len(commands)
    assert commands == ["stars", "exoplanets", "deep-sky", "history", "population"]
    assert [s.step for s in SOURCES] == ["2.4", "2.5", "2.6", "2.8 to 2.13", "2.14"]
    assert {"stars", "exoplanets", "deep-sky"} == cli.IMPLEMENTED


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.command)
def test_each_source_help_names_its_plan_step(source: Source) -> None:
    result = runner.invoke(app, [source.command, "--help"])
    assert result.exit_code == 0
    assert f"step {source.step}" in " ".join(result.output.split())


@pytest.mark.parametrize("source", UNBUILT, ids=lambda s: s.command)
def test_unbuilt_sources_fail_clearly(source: Source) -> None:
    result = runner.invoke(app, [source.command])
    assert result.exit_code == 1
    assert "not implemented yet" in result.output
    assert source.step in result.output


def test_stars_runs_the_build_and_prints_the_report(calls: list[Call], tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["--cache-dir", str(tmp_path), "--refresh", "stars", "--max-vmag", "9.5"]
    )
    assert result.exit_code == 0, result.output
    (name, kwargs), *rest = calls
    assert name == "stars" and rest == []
    assert kwargs == {
        "cache_dir": tmp_path,
        "refresh": True,
        "database": tmp_path / "earthlight.db",
        "max_vmag": 9.5,
        "progress": kwargs["progress"],
    }
    assert "downloading stars..." in result.output
    assert "Stars built: 8 of 10 Hipparcos entries" in result.output
    assert "gaia 5, hipparcos 3" in result.output
    assert "Left out: too_faint 2" in result.output


def test_stars_uses_the_default_magnitude_limit(calls: list[Call]) -> None:
    runner.invoke(app, ["stars"])
    kwargs = calls[0][1]
    assert kwargs["max_vmag"] == DEFAULT_MAX_VMAG == 8.0
    assert kwargs["refresh"] is False
    assert kwargs["cache_dir"] == DEFAULT_CACHE_DIR


def test_no_limit_keeps_every_star(calls: list[Call]) -> None:
    assert runner.invoke(app, ["stars", "--no-limit"]).exit_code == 0
    assert calls[0][1]["max_vmag"] is None


def test_a_limit_and_no_limit_together_is_an_error(calls: list[Call]) -> None:
    result = runner.invoke(app, ["stars", "--max-vmag", "7", "--no-limit"])
    assert result.exit_code == 2
    assert "not both" in result.output
    assert calls == []


def test_exoplanets_runs_the_build_and_prints_the_report(calls: list[Call], tmp_path: Path) -> None:
    result = runner.invoke(app, ["--cache-dir", str(tmp_path), "exoplanets"])
    assert result.exit_code == 0, result.output
    ((name, kwargs),) = calls
    assert name == "exoplanets"
    assert kwargs == {
        "cache_dir": tmp_path,
        "refresh": False,
        "database": tmp_path / "earthlight.db",
        "progress": kwargs["progress"],
    }
    assert "downloading planets..." in result.output
    assert "Planets built: 18 of 20 archive rows" in result.output
    assert "Linked to a host star: 6 (of 8 stars in the database)" in result.output


def test_deep_sky_runs_the_build_and_prints_the_report(calls: list[Call], tmp_path: Path) -> None:
    result = runner.invoke(app, ["--cache-dir", str(tmp_path), "--refresh", "deep-sky"])
    assert result.exit_code == 0, result.output
    ((name, kwargs),) = calls
    assert name == "deep-sky"
    assert kwargs == {
        "cache_dir": tmp_path,
        "refresh": True,
        "database": tmp_path / "earthlight.db",
        "progress": kwargs["progress"],
    }
    assert "downloading SIMBAD..." in result.output
    assert "Deep-sky objects built: 52" in result.output
    assert "Numbers from: inline 7, simbad 45" in result.output


def test_the_database_option_overrides_the_default(calls: list[Call], tmp_path: Path) -> None:
    target = tmp_path / "elsewhere" / "my.db"
    runner.invoke(app, ["--database", str(target), "stars"])
    assert calls[0][1]["database"] == target


def test_all_builds_stars_planets_and_deep_sky_into_a_fresh_database(
    calls: list[Call], tmp_path: Path
) -> None:
    database = tmp_path / "earthlight.db"
    database.write_text("an old database that must not survive", encoding="utf-8")
    result = runner.invoke(app, ["--database", str(database), "all"])
    assert result.exit_code == 1  # it stops at the first source that is not built yet
    assert [name for name, _ in calls] == [
        "stars",
        "exoplanets",
        "deep-sky",
    ]  # planets link to stars
    assert calls[0][1]["max_vmag"] == DEFAULT_MAX_VMAG
    out = result.output
    stars_at, planets_at, deep_at, history_at = (
        out.index(f"Building {s}") for s in ("stars", "exoplanets", "deep-sky", "history")
    )
    assert stars_at < planets_at < deep_at < history_at
    assert "Building population" not in out
    assert "'history' is not implemented yet" in out
    # The old file was replaced by an empty database with the current schema.
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
        assert connection.execute("SELECT count(*) FROM vantage_points").fetchone() == (0,)
    finally:
        connection.close()


def test_config_shows_the_defaults() -> None:
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    flat = result.output.replace("\n", "")
    assert str(DEFAULT_CACHE_DIR) in flat
    assert str(DEFAULT_CACHE_DIR / "earthlight.db") in flat
    assert "refresh cached files: no" in result.output


def test_global_options_reach_the_subcommands(tmp_path: Path) -> None:
    database = tmp_path / "x.db"
    result = runner.invoke(
        app, ["--cache-dir", str(tmp_path), "--refresh", "--database", str(database), "config"]
    )
    assert result.exit_code == 0
    flat = result.output.replace("\n", "")
    assert str(tmp_path) in flat and str(database) in flat
    assert "refresh cached files: yes" in result.output


def test_unknown_commands_are_rejected() -> None:
    result = runner.invoke(app, ["planets"])
    assert result.exit_code == 2
