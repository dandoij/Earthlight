"""Lets ``python -m earthlight`` run the command line."""

from earthlight.cli import app

if __name__ == "__main__":
    app(prog_name="earthlight")
