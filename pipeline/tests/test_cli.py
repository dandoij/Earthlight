"""Tests for the earthlight-build command."""

import re
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from earthlight.schema import SCHEMA_VERSION
from earthlight_pipeline import cli
from earthlight_pipeline.build_deep_sky import DeepSkyReport
from earthlight_pipeline.build_exoplanets import ExoplanetsReport
from earthlight_pipeline.build_history import HistoryReport
from earthlight_pipeline.build_population import PopulationReport
from earthlight_pipeline.build_stars import DEFAULT_MAX_VMAG, StarsReport
from earthlight_pipeline.cache import DEFAULT_CACHE_DIR
from earthlight_pipeline.cli import SOURCES, Source, app
from earthlight_pipeline.history import HistoryError
from earthlight_pipeline.population import PopulationError

runner = CliRunner()

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


def fake_population_report(database: Path) -> PopulationReport:
    return PopulationReport(
        built=261,
        span="4.5 million in 10000 BCE to 8.09 billion in 2023 CE",
        database=database,
        database_bytes=250_000,
    )


def fake_history_report(database: Path) -> HistoryReport:
    return HistoryReport(
        events=10,
        periods=3,
        landmarks=2,
        by_category={"cosmic": 4, "science": 11},
        earliest_year=-13_800_000_000.0,
        latest_year=2025.0,
        database=database,
        database_bytes=300_000,
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

    def fake_run_history(**kwargs: object) -> HistoryReport:
        recorded.append(("history", kwargs))
        progress = kwargs["progress"]
        assert callable(progress)
        progress("reading history...")
        return fake_history_report(Path(str(kwargs["database"])))

    def fake_run_population(**kwargs: object) -> PopulationReport:
        recorded.append(("population", kwargs))
        progress = kwargs["progress"]
        assert callable(progress)
        progress("downloading population...")
        return fake_population_report(Path(str(kwargs["database"])))

    monkeypatch.setattr(cli, "run_population", fake_run_population)
    monkeypatch.setattr(cli, "run_history", fake_run_history)
    monkeypatch.setattr(cli, "run_deep_sky", fake_run_deep_sky)
    monkeypatch.setattr(cli, "run_stars", fake_run_stars)
    monkeypatch.setattr(cli, "run_exoplanets", fake_run_exoplanets)
    return recorded


ANSI_CODES = re.compile(r"\[[0-9;]*m")


def test_help_lists_every_source_and_the_extra_commands() -> None:
    # CI sets FORCE_COLOR and a narrow terminal, which colours the help and wraps option names.
    result = runner.invoke(app, ["--help"], env={"NO_COLOR": "1", "TERMINAL_WIDTH": "200"})
    assert result.exit_code == 0
    output = ANSI_CODES.sub("", result.output)
    for source in SOURCES:
        assert source.command in output
    assert "all" in output
    assert "config" in output
    for option in ("--cache-dir", "--refresh", "--database"):
        assert option in output


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "Usage" in result.output


def test_sources_are_unique_and_match_the_plan() -> None:
    commands = [s.command for s in SOURCES]
    assert len(set(commands)) == len(commands)
    assert commands == ["stars", "exoplanets", "deep-sky", "history", "population"]
    assert [s.step for s in SOURCES] == ["2.4", "2.5", "2.6", "2.7", "2.14"]


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.command)
def test_each_source_help_names_its_plan_step(source: Source) -> None:
    result = runner.invoke(app, [source.command, "--help"])
    assert result.exit_code == 0
    assert f"step {source.step}" in " ".join(result.output.split())


def test_population_runs_the_build_and_prints_the_report(calls: list[Call], tmp_path: Path) -> None:
    result = runner.invoke(app, ["--cache-dir", str(tmp_path), "--refresh", "population"])
    assert result.exit_code == 0, result.output
    ((name, kwargs),) = calls
    assert name == "population"
    assert kwargs == {
        "cache_dir": tmp_path,
        "refresh": True,
        "database": tmp_path / "earthlight.db",
        "progress": kwargs["progress"],
    }
    assert "downloading population..." in result.output
    assert "Population estimates built: 261" in result.output


def test_population_problems_are_printed_and_exit_with_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(**_kwargs: object) -> PopulationReport:
        raise PopulationError("year 2100: is after 2026, so it is a projection")

    monkeypatch.setattr(cli, "run_population", broken)
    result = runner.invoke(app, ["population"])
    assert result.exit_code == 1
    assert "The population file has problems" in result.output
    assert "year 2100" in result.output


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


def test_history_reads_the_curated_files_and_prints_the_report(
    calls: list[Call], tmp_path: Path
) -> None:
    result = runner.invoke(app, ["--database", str(tmp_path / "my.db"), "history"])
    assert result.exit_code == 0, result.output
    ((name, kwargs),) = calls
    assert name == "history"
    assert kwargs == {
        "database": tmp_path / "my.db",
        "progress": kwargs["progress"],
    }
    assert "reading history..." in result.output
    assert "History entries built: 15 (10 events, 3 periods, 2 landmarks)" in result.output


def test_history_problems_are_printed_and_exit_with_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(**_kwargs: object) -> HistoryReport:
        raise HistoryError("era.yaml events 1 (x): year: field required")

    monkeypatch.setattr(cli, "run_history", broken)
    result = runner.invoke(app, ["history"])
    assert result.exit_code == 1
    assert "The history files have problems" in result.output
    assert "era.yaml events 1 (x)" in result.output


def test_the_database_option_overrides_the_default(calls: list[Call], tmp_path: Path) -> None:
    target = tmp_path / "elsewhere" / "my.db"
    runner.invoke(app, ["--database", str(target), "stars"])
    assert calls[0][1]["database"] == target


def test_all_builds_every_finished_source_into_a_fresh_database(
    calls: list[Call], tmp_path: Path
) -> None:
    database = tmp_path / "earthlight.db"
    database.write_text("an old database that must not survive", encoding="utf-8")
    result = runner.invoke(app, ["--database", str(database), "all"])
    assert result.exit_code == 0, result.output
    assert [name for name, _ in calls] == [
        "stars",
        "exoplanets",
        "deep-sky",
        "history",
        "population",
    ]  # planets link to stars
    assert calls[0][1]["max_vmag"] == DEFAULT_MAX_VMAG
    out = result.output
    stars_at, planets_at, deep_at, history_at, population_at = (
        out.index(f"Building {s}")
        for s in ("stars", "exoplanets", "deep-sky", "history", "population")
    )
    assert stars_at < planets_at < deep_at < history_at < population_at
    assert "not implemented" not in out
    # The old file was replaced by an empty database with the current schema.
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT value FROM meta WHERE key = 'data_license'"
        ).fetchone() == ("CC BY-NC 3.0 IGO",)
        assert connection.execute(
            "SELECT count(*) FROM meta WHERE key = 'build_date'"
        ).fetchone() == (1,)
        assert connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
        assert connection.execute("SELECT count(*) FROM vantage_points").fetchone() == (0,)
    finally:
        connection.close()


def test_a_failed_all_build_leaves_the_old_database_untouched(
    calls: list[Call], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def broken(**_kwargs: object) -> DeepSkyReport:
        raise RuntimeError("SIMBAD is down")

    monkeypatch.setattr(cli, "run_deep_sky", broken)
    database = tmp_path / "earthlight.db"
    database.write_text("the old database", encoding="utf-8")
    result = runner.invoke(app, ["--database", str(database), "all"])
    assert result.exit_code != 0
    assert database.read_text(encoding="utf-8") == "the old database"
    assert list(tmp_path.iterdir()) == [database]  # the temporary file was cleaned up


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
