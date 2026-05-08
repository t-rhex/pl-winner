"""Legacy shim. Prefer: ``pl-winner fixtures``."""
from __future__ import annotations
import sys
from pl_winner.cli import main
if __name__ == "__main__":
    raise SystemExit(main(["fixtures", *sys.argv[1:]]))
