"""Legacy shim. Prefer: ``pl-winner fpl``."""
from __future__ import annotations
import sys
from pl_winner.cli import main
if __name__ == "__main__":
    raise SystemExit(main(["fpl", *sys.argv[1:]]))
