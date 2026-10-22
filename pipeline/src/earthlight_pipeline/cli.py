"""The ``earthlight-build`` command: builds the Earthlight database one source at a time.

Each data source is a subcommand (the plan step that built it is in each command's help), and
``all`` runs every source in order.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from earthlight.schema import create_empty_database
from earthlight_pipeline.build_deep_sky import format_deep_sky_report, run_deep_sky
from earthlight_pipeline.build_exoplanets import format_exoplanets_report, run_exoplanets
from earthlight_pipeline.build_history import format_history_report, run_history
from earthlight_pipeline.build_population import format_population_report, run_population
from earthlight_pipeline.build_stars import DEFAULT_MAX_VMAG, format_stars_report, run_stars
from earthlight_pipeline.cache import DEFAULT_CACHE_DIR
from earthlight_pipeline.history import HistoryError
from earthlight_pipeline.population import PopulationError


@dataclass(frozen=True)
class Source:
    """One data source the pipeline builds, and the plan step that implements it."""

    command: str
    step: str
    summary: str


SOURCES: tuple[Source, ...] = (
    Source("stars", "2.4", "Hipparcos stars with Gaia and Bailer-Jones distances and IAU names."),
    Source("exoplanets", "2.5", "NASA Exoplanet Archive planets, linked to their host stars."),
    Source("deep-sky", "2.6", "Curated star clusters, galaxies, quasars, and the CMB."),
    Source("history", "2.7", "Hand-curated events, periods, and landmarks."),
    Source("population", "2.14", "Our World in Data world population estimates."),
)

DEFAULT_DATABASE_NAME = "earthlight.db"


@dataclass(frozen=True)
class BuildOptions:
    """Settings shared by every subcommand, set by the options before the subcommand."""

    cache_dir: Path
    refresh: bool
    database: Path


app = typer.Typer(
    name="earthlight-build",
    help="Build the Earthlight database from its data sources.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main(
    ctx: typer.Context,
    cache_dir: Annotated[
        Path, typer.Option(help="Where downloaded source files are cached.")
    ] = DEFAULT_CACHE_DIR,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Download cached files again.")
    ] = False,
    database: Annotated[
        Path | None,
        typer.Option(
            help="The database file to build into. Default: earthlight.db in the cache directory."
        ),
    ] = None,
) -> None:
    """Options that apply to every subcommand."""
    ctx.obj = BuildOptions(
        cache_dir=cache_dir,
        refresh=refresh,
        database=database if database is not None else cache_dir / DEFAULT_DATABASE_NAME,
    )


def get_options(ctx: typer.Context) -> BuildOptions:
    """The shared settings, for subcommands to read."""
    options = ctx.find_root().obj
    if not isinstance(options, BuildOptions):
        raise RuntimeError("build options were not set; the app callback did not run")
    return options


@app.command(name="config")
def show_config(ctx: typer.Context) -> None:
    """Show the settings the other commands would use."""
    options = get_options(ctx)
    typer.echo(f"cache directory: {options.cache_dir}")
    typer.echo(f"refresh cached files: {'yes' if options.refresh else 'no'}")
    typer.echo(f"database: {options.database}")


def _build_stars(options: BuildOptions, max_vmag: float | None) -> None:
    report = run_stars(
        cache_dir=options.cache_dir,
        refresh=options.refresh,
        database=options.database,
        max_vmag=max_vmag,
        progress=typer.echo,
    )
    typer.echo("")
    typer.echo(format_stars_report(report))


@app.command(
    name="stars",
    help="Hipparcos stars with Gaia and Bailer-Jones distances and IAU names. (step 2.4)",
)
def stars(
    ctx: typer.Context,
    max_vmag: Annotated[
        float | None,
        typer.Option(
            help=(
                "Leave out unnamed, distant stars fainter than this V magnitude "
                f"(default {DEFAULT_MAX_VMAG}). Named stars and stars within 12 light-years "
                "are always kept."
            )
        ),
    ] = None,
    no_limit: Annotated[
        bool, typer.Option("--no-limit", help="Keep every usable star (about 40 MB).")
    ] = False,
) -> None:
    """Build the star vantage points and store them in the database."""
    if no_limit and max_vmag is not None:
        raise typer.BadParameter("use either --max-vmag or --no-limit, not both")
    limit = None if no_limit else DEFAULT_MAX_VMAG if max_vmag is None else max_vmag
    _build_stars(get_options(ctx), limit)


def _build_exoplanets(options: BuildOptions) -> None:
    report = run_exoplanets(
        cache_dir=options.cache_dir,
        refresh=options.refresh,
        database=options.database,
        progress=typer.echo,
    )
    typer.echo("")
    typer.echo(format_exoplanets_report(report))


@app.command(
    name="exoplanets",
    help="NASA Exoplanet Archive planets, linked to their host stars. (step 2.5)",
)
def exoplanets(ctx: typer.Context) -> None:
    """Build the exoplanet vantage points and store them in the database.

    Run `stars` first: planets are linked to the host stars already in the database.
    """
    _build_exoplanets(get_options(ctx))


def _build_deep_sky(options: BuildOptions) -> None:
    report = run_deep_sky(
        cache_dir=options.cache_dir,
        refresh=options.refresh,
        database=options.database,
        progress=typer.echo,
    )
    typer.echo("")
    typer.echo(format_deep_sky_report(report))


@app.command(
    name="deep-sky",
    help="Star clusters, galaxies, quasars, and the CMB from the curated list. (step 2.6)",
)
def deep_sky(ctx: typer.Context) -> None:
    """Build the deep-sky vantage points from curated/deep_sky.yaml and store them."""
    _build_deep_sky(get_options(ctx))


def _build_history(options: BuildOptions) -> None:
    try:
        report = run_history(database=options.database, progress=typer.echo)
    except HistoryError as error:
        typer.echo(f"The history files have problems:\n{error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo("")
    typer.echo(format_history_report(report))


@app.command(
    name="history",
    help="Hand-curated events, periods, and landmarks from curated/history. (step 2.7)",
)
def history(ctx: typer.Context) -> None:
    """Build the history events, periods, and landmarks from curated/history/*.yaml."""
    _build_history(get_options(ctx))


def _build_population(options: BuildOptions) -> None:
    try:
        report = run_population(
            cache_dir=options.cache_dir,
            refresh=options.refresh,
            database=options.database,
            progress=typer.echo,
        )
    except PopulationError as error:
        typer.echo(f"The population file has problems:\n{error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo("")
    typer.echo(format_population_report(report))


@app.command(
    name="population",
    help="World population estimates from Our World in Data. (step 2.14)",
)
def population(ctx: typer.Context) -> None:
    """Build the world population table from the Our World in Data file."""
    _build_population(get_options(ctx))


@app.command(name="all")
def build_all(ctx: typer.Context) -> None:
    """Build every source in order into a fresh database, stopping at the first failure.

    The database file is recreated first: planets depend on their host stars, so rebuilding
    one source on top of the others is not always possible, and a full build is the one
    way to get a database that is consistent from top to bottom.
    """
    options = get_options(ctx)
    typer.echo(f"Creating a fresh database at {options.database}")
    create_empty_database(options.database, overwrite=True)
    builders = {
        "stars": lambda: _build_stars(options, DEFAULT_MAX_VMAG),
        "exoplanets": lambda: _build_exoplanets(options),
        "deep-sky": lambda: _build_deep_sky(options),
        "history": lambda: _build_history(options),
        "population": lambda: _build_population(options),
    }
    for source in SOURCES:
        typer.echo(f"Building {source.command}...")
        builders[source.command]()
