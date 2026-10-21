"""Keeps the README honest: its example must run and print what the README says it prints."""

import contextlib
import io
import re
from pathlib import Path

README = Path(__file__).resolve().parents[3] / "README.md"


def _block(language: str) -> str:
    match = re.search(rf"```{language}\n(.*?)```", README.read_text("utf-8"), re.DOTALL)
    assert match, f"README.md has no ```{language} block"
    return match.group(1)


def test_readme_example_prints_exactly_what_the_readme_shows() -> None:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(compile(_block("python"), "README.md example", "exec"), {})
    assert output.getvalue() == _block("text")
