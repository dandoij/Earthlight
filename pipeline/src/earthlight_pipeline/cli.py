"""The ``earthlight-build`` command: builds the Earthlight database one source at a time.

Each data source is a subcommand. They are placeholders until the step that builds that
source lands (the step number is in each command's help), and ``all`` runs them in order.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from earthlight_pipeline.cache import DEFAULT_CACHE_DIR


@dataclass(frozen=True)
class Source:
    """One data source the pipeline builds, and the plan step that implements it."""

    command: str
    step: str
    summary: str


SOURCES: tuple[Source, ...] = (
    Source("stars", "2.4", "Gaia DR3 stars with Bailer-Jones distances and HYG names."),
    Source("exoplanets", "2.5", "NASA Exoplanet Archive planets, linked to their host stars."),
    Source("deep-sky", "2.6", "Curated galaxies, clusters, quasars, and the CMB."),
    Source("history", "2.8 to 2.13", "Hand-curated events, periods, and landmarks."),
    Source("population", "2.14", "Our World in Data historical population estimates."),
)


@dataclass(frozen=True)
class BuildOptions:
    """Settings shared by every subcommand, set by the options before the subcommand."""

    cache_dir: Path
    refresh: bool


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
) -> None:
    """Options that apply to every subcommand."""
    ctx.obj = BuildOptions(cache_dir=cache_dir, refresh=refresh)


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


def _not_implemented(source: Source) -> None:
    typer.echo(
        f"'{source.command}' is not implemented yet: it is built in step {source.step} "
        "of docs/PLAN.md.",
        err=True,
    )
    raise typer.Exit(code=1)


def _make_command(source: Source) -> Callable[[], None]:
    def command() -> None:
        _not_implemented(source)

    return command


for _source in SOURCES:
    app.command(name=_source.command, help=f"{_source.summary} (step {_source.step})")(
        _make_command(_source)
    )


@app.command(name="all")
def build_all() -> None:
    """Build every source in order, stopping at the first one that fails."""
    for source in SOURCES:
        typer.echo(f"Building {source.command}...")
        _not_implemented(source)
