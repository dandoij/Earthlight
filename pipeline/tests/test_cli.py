"""Tests for the earthlight-build command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from earthlight_pipeline.cache import DEFAULT_CACHE_DIR
from earthlight_pipeline.cli import SOURCES, Source, app

runner = CliRunner()


def test_help_lists_every_source_and_the_extra_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for source in SOURCES:
        assert source.command in result.output
    assert "all" in result.output
    assert "config" in result.output
    assert "--cache-dir" in result.output
    assert "--refresh" in result.output


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


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.command)
def test_unbuilt_sources_fail_clearly(source: Source) -> None:
    result = runner.invoke(app, [source.command])
    assert result.exit_code == 1
    assert "not implemented yet" in result.output
    assert source.step in result.output


def test_all_stops_at_the_first_unbuilt_source() -> None:
    result = runner.invoke(app, ["all"])
    assert result.exit_code == 1
    assert "Building stars" in result.output
    assert "Building exoplanets" not in result.output


def test_config_shows_the_defaults() -> None:
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert str(DEFAULT_CACHE_DIR) in result.output.replace("\n", "")
    assert "refresh cached files: no" in result.output


def test_global_options_reach_the_subcommands(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--cache-dir", str(tmp_path), "--refresh", "config"])
    assert result.exit_code == 0
    assert str(tmp_path) in result.output.replace("\n", "")
    assert "refresh cached files: yes" in result.output


def test_unknown_commands_are_rejected() -> None:
    result = runner.invoke(app, ["planets"])
    assert result.exit_code == 2
