"""The ``earthlight-build`` command: builds the Earthlight database one source at a time.

Each data source is a subcommand. A source that has not been built yet is a placeholder that
fails with the plan step that implements it (the step number is in each command's help), and
``all`` runs every source in order.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from earthlight_pipeline.build_stars import DEFAULT_MAX_VMAG, format_stars_report, run_stars
from earthlight_pipeline.cache import DEFAULT_CACHE_DIR


@dataclass(frozen=True)
class Source:
    """One data source the pipeline builds, and the plan step that implements it."""

    command: str
    step: str
    summary: str


SOURCES: tuple[Source, ...] = (
    Source("stars", "2.4", "Hipparcos stars with Gaia and Bailer-Jones distances and IAU names."),
    Source("exoplanets", "2.5", "NASA Exoplanet Archive planets, linked to their host stars."),
    Source("deep-sky", "2.6", "Curated galaxies, clusters, quasars, and the CMB."),
    Source("history", "2.8 to 2.13", "Hand-curated events, periods, and landmarks."),
    Source("population", "2.14", "Our World in Data historical population estimates."),
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


def _not_implemented(source: Source) -> None:
    typer.echo(
        f"'{source.command}' is not implemented yet: it is built in step {source.step} "
        "of docs/PLAN.md.",
        err=True,
    )
    raise typer.Exit(code=1)


def _make_placeholder(source: Source) -> Callable[[], None]:
    def command() -> None:
        _not_implemented(source)

    return command


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


for _source in SOURCES:
    if _source.command != "stars":
        app.command(name=_source.command, help=f"{_source.summary} (step {_source.step})")(
            _make_placeholder(_source)
        )


@app.command(name="all")
def build_all(ctx: typer.Context) -> None:
    """Build every source in order, stopping at the first one that fails."""
    options = get_options(ctx)
    for source in SOURCES:
        typer.echo(f"Building {source.command}...")
        if source.command == "stars":
            _build_stars(options, DEFAULT_MAX_VMAG)
        else:
            _not_implemented(source)
