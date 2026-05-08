"""Subcommand implementations for the ``pl-winner`` CLI.

Each module exposes a ``main(args)`` function that takes a parsed argparse
Namespace. Modules are imported lazily by ``cli.py`` so that ``pl-winner --help``
stays fast.
"""
