"""Single-entrypoint CLI: ``pl-winner <subcommand> [options]``.

Each subcommand defers heavy imports until it actually runs so ``pl-winner --help``
stays fast (~30ms instead of >1s).
"""
from __future__ import annotations

import argparse
import logging
import sys

from . import __version__

log = logging.getLogger("pl_winner")


def _setup_logging(verbose: bool, quiet: bool) -> None:
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _add_predict(sub) -> None:
    p = sub.add_parser("predict", help="Title race + simulation projections")
    p.add_argument("--league", default="E0",
                   help="football-data league code (E0=EPL, SP1=La Liga, D1=Bundesliga, ...)")
    p.add_argument("--current-year", type=int, default=2025)
    p.add_argument("--history", type=int, default=4)
    p.add_argument("--half-life", type=float, default=180.0)
    p.add_argument("--runs", type=int, default=10_000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--refresh", action="store_true", help="Force re-download CSV cache")
    p.set_defaults(_module="predict")


def _add_fixtures(sub) -> None:
    p = sub.add_parser("fixtures", help="Remaining fixtures with model probabilities")
    p.add_argument("--league", default="E0")
    p.add_argument("--current-year", type=int, default=2025)
    p.add_argument("--history", type=int, default=4)
    p.set_defaults(_module="fixtures")


def _add_backtest(sub) -> None:
    p = sub.add_parser("backtest", help="Walk-forward title + log-loss backtest")
    p.add_argument("--seasons", type=int, nargs="+", default=[2021, 2022, 2023, 2024])
    p.add_argument("--history", type=int, default=4)
    p.add_argument("--cutoff", type=int, default=349)
    p.add_argument("--half-life", type=float, default=180.0)
    p.add_argument("--runs", type=int, default=5000)
    p.set_defaults(_module="backtest")


def _add_fpl(sub) -> None:
    p = sub.add_parser("fpl", help="Top picks, captains, ILP squad, differentials, chips")
    p.add_argument("--gameweeks", type=int, default=3)
    p.add_argument("--budget", type=float, default=100.0)
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(_module="fpl")


def _add_value(sub) -> None:
    p = sub.add_parser("value", help="Calibration + ROI vs Bet365 + break-even odds")
    p.add_argument("--seasons", type=int, nargs="+", default=[2021, 2022, 2023, 2024])
    p.add_argument("--cutoff", type=int, default=200)
    p.add_argument("--history", type=int, default=4)
    p.add_argument("--half-life", type=float, default=180.0)
    p.add_argument("--bookie", choices=["B365", "PS", "Avg", "Max"], default="B365")
    p.add_argument("--edge", type=float, default=5.0)
    p.add_argument("--bins", type=int, default=10)
    p.set_defaults(_module="value")


def _add_tune(sub) -> None:
    p = sub.add_parser("tune", help="Cross-validate the half-life parameter")
    p.add_argument("--seasons", type=int, nargs="+", default=[2021, 2022, 2023, 2024])
    p.add_argument("--cutoff", type=int, default=200)
    p.add_argument("--history", type=int, default=4)
    p.add_argument("--candidates", type=float, nargs="+",
                   default=[60.0, 90.0, 120.0, 180.0, 270.0, 365.0, 540.0, 730.0, 1095.0])
    p.set_defaults(_module="tune")


def _add_track(sub) -> None:
    p = sub.add_parser("track", help="Persistent prediction tracker (record / score / report / backfill)")
    track_sub = p.add_subparsers(dest="track_op", required=True)

    rec = track_sub.add_parser("record", help="Save predictions for the upcoming GW")
    rec.add_argument("--year", type=int, default=2025)
    rec.add_argument("--gameweek", type=int, default=None)
    rec.add_argument("--history", type=int, default=4)
    rec.add_argument("--also-results", action="store_true")

    sc = track_sub.add_parser("score", help="Refresh stored results from the live CSV")
    sc.add_argument("--year", type=int, default=2025)
    sc.add_argument("--history", type=int, default=4)

    track_sub.add_parser("report", help="Print Brier / log-loss / hit rate")

    bf = track_sub.add_parser("backfill", help="Walk-forward seed past predictions")
    bf.add_argument("--seasons", type=int, nargs="+", default=[2022, 2023, 2024])
    bf.add_argument("--cutoff", type=int, default=200)
    bf.add_argument("--history", type=int, default=4)

    p.set_defaults(_module="track")


def _add_league(sub) -> None:
    p = sub.add_parser("league", help="Simulate an FPL mini-league")
    p.add_argument("--league-id", type=int, default=None)
    p.add_argument("--entry-ids", type=int, nargs="+", default=None)
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--runs", type=int, default=5000)
    p.set_defaults(_module="league")


def _add_tui(sub) -> None:
    p = sub.add_parser("tui", help="Interactive terminal UI")
    p.set_defaults(_module="_tui")


def _add_web(sub) -> None:
    p = sub.add_parser("web", help="Launch the Streamlit web UI")
    p.add_argument("--port", type=int, default=8501)
    p.add_argument("--host", default="localhost")
    p.set_defaults(_module="_web")


def _run_tui(args) -> int:
    from .tui import run_tui
    run_tui()
    return 0


def _run_web(args) -> int:
    import os
    import subprocess
    from pathlib import Path
    # When installed via pip, the streamlit app file ships next to the package.
    candidates = [
        Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py",
        Path(__file__).resolve().parent / "streamlit_app.py",
    ]
    app_path = next((c for c in candidates if c.exists()), None)
    if app_path is None:
        log.error("Streamlit app not found. Install web extras: pip install pl-winner[web]")
        return 1
    try:
        import streamlit  # noqa: F401
    except ImportError:
        log.error("Streamlit isn't installed. Run: pip install pl-winner[web]")
        return 1
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(app_path),
        "--server.port", str(args.port),
        "--server.address", args.host,
        "--browser.gatherUsageStats", "false",
    ]
    log.info(f"Launching Streamlit on http://{args.host}:{args.port}")
    return subprocess.call(cmd, env={**os.environ})


SUBCOMMANDS = [
    _add_predict, _add_fixtures, _add_backtest, _add_fpl, _add_value,
    _add_tune, _add_track, _add_league, _add_tui, _add_web,
]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pl-winner",
        description=(
            "Premier League predictor + FPL recommender.\n\n"
            "Examples:\n"
            "  pl-winner predict\n"
            "  pl-winner fpl --refresh\n"
            "  pl-winner tui\n"
            "  pl-winner web\n"
            "  pl-winner league --league-id 314 --top 10"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"pl-winner {__version__}")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<subcommand>")
    for register in SUBCOMMANDS:
        register(sub)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose, args.quiet)
    try:
        module_name = getattr(args, "_module", None)
        if module_name == "_tui":
            return _run_tui(args)
        if module_name == "_web":
            return _run_web(args)
        if module_name is None:
            parser.print_help()
            return 1
        mod = __import__(f"pl_winner.commands.{module_name}", fromlist=["main"])
        return int(mod.main(args) or 0)
    except KeyboardInterrupt:
        log.warning("Interrupted")
        return 130
    except Exception as e:  # noqa: BLE001
        if args.verbose:
            raise
        log.error(f"{type(e).__name__}: {e}")
        log.error("Re-run with -v for full traceback.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
