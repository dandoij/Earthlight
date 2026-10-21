"""Tests for the earthlight-build command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from earthlight_pipeline import cli
from earthlight_pipeline.build_stars import DEFAULT_MAX_VMAG, StarsReport
from earthlight_pipeline.cache import DEFAULT_CACHE_DIR
from earthlight_pipeline.cli import SOURCES, Source, app

runner = CliRunner()

UNBUILT = [source for source in SOURCES if source.command != "stars"]


def fake_report(database: Path) -> StarsReport:
    return StarsReport(
        hipparcos_total=10,
        built=8,
        by_source={"gaia": 5, "hipparcos": 3},
        skipped={"too_faint": 2},
        searchable=4,
        named=3,
        fame_counts={0: 4, 3: 4},
        database=database,
        database_bytes=1_500_000,
    )


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Replace the real stars build, which uses the network, with a recorder."""
    recorded: list[dict[str, object]] = []

    def fake_run_stars(**kwargs: object) -> StarsReport:
        recorded.append(kwargs)
        progress = kwargs["progress"]
        assert callable(progress)
        progress("downloading...")
        return fake_report(Path(str(kwargs["database"])))

    monkeypatch.setattr(cli, "run_stars", fake_run_stars)
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


def test_stars_runs_the_build_and_prints_the_report(
    calls: list[dict[str, object]], tmp_path: Path
) -> None:
    result = runner.invoke(
        app, ["--cache-dir", str(tmp_path), "--refresh", "stars", "--max-vmag", "9.5"]
    )
    assert result.exit_code == 0, result.output
    assert calls == [
        {
            "cache_dir": tmp_path,
            "refresh": True,
            "database": tmp_path / "earthlight.db",
            "max_vmag": 9.5,
            "progress": calls[0]["progress"],
        }
    ]
    assert "downloading..." in result.output
    assert "Stars built: 8 of 10 Hipparcos entries" in result.output
    assert "gaia 5, hipparcos 3" in result.output
    assert "Left out: too_faint 2" in result.output


def test_stars_uses_the_default_magnitude_limit(calls: list[dict[str, object]]) -> None:
    runner.invoke(app, ["stars"])
    assert calls[0]["max_vmag"] == DEFAULT_MAX_VMAG == 8.0
    assert calls[0]["refresh"] is False
    assert calls[0]["cache_dir"] == DEFAULT_CACHE_DIR


def test_no_limit_keeps_every_star(calls: list[dict[str, object]]) -> None:
    assert runner.invoke(app, ["stars", "--no-limit"]).exit_code == 0
    assert calls[0]["max_vmag"] is None


def test_a_limit_and_no_limit_together_is_an_error(calls: list[dict[str, object]]) -> None:
    result = runner.invoke(app, ["stars", "--max-vmag", "7", "--no-limit"])
    assert result.exit_code == 2
    assert "not both" in result.output
    assert calls == []


def test_the_database_option_overrides_the_default(
    calls: list[dict[str, object]], tmp_path: Path
) -> None:
    target = tmp_path / "elsewhere" / "my.db"
    runner.invoke(app, ["--database", str(target), "stars"])
    assert calls[0]["database"] == target


def test_all_builds_stars_then_stops_at_the_first_unbuilt_source(
    calls: list[dict[str, object]],
) -> None:
    result = runner.invoke(app, ["all"])
    assert result.exit_code == 1
    assert len(calls) == 1
    assert calls[0]["max_vmag"] == DEFAULT_MAX_VMAG
    assert "Building stars" in result.output
    assert "Building exoplanets" in result.output
    assert "Building deep-sky" not in result.output
    assert "'exoplanets' is not implemented yet" in result.output


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
